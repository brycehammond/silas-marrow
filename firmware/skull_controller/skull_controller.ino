/*
  Talking skull controller: jaw + neck pan/tilt servos and WS2812 eyes.
  Board: Arduino Uno / Nano.   Libraries: Servo (built in), Adafruit NeoPixel.

  Serial 115200, newline-terminated commands from the Mac:
    J<0-100>          jaw open percent (fast, follows speech)
    L<pan>,<tilt>     look target, -100..100 percent of calibrated range (smoothed)
    E<mode>           eyes: 0 off, 1 idle, 2 alert, 3 talk, 4 listen
    C<r>,<g>,<b>      eye color
    H                 home: center head, close jaw
    X                 relax: detach servos until H (quiet, no holding torque)
    R<ch>,<us>        raw pulse for calibration, ch: 0 jaw, 1 pan, 2 tilt
    S                 status

  Safety: if the Mac goes quiet for WATCHDOG_MS, the head drifts to center
  and the jaw closes. All positions are clamped to the calibrated limits.
*/

#include <Servo.h>
#include <Adafruit_NeoPixel.h>

// ---------- pins ----------
const uint8_t PIN_JAW  = 9;
const uint8_t PIN_PAN  = 10;
const uint8_t PIN_TILT = 11;
const uint8_t PIN_EYES = 6;     // 330 ohm resistor in series to the first jewel's DIN
const uint8_t NUM_EYE_LEDS = 14; // two 7-LED jewels chained

// ---------- calibration (microseconds), find these with calibrate.py ----------
// Jaw: closed and fully open. Swap the numbers if the jaw moves backwards.
const int JAW_CLOSED_US = 1500;
const int JAW_OPEN_US   = 1150;
// Pan: center, and the pulse at +100% (turn to the skull's left from the viewer).
const int PAN_CENTER_US = 1500;
const int PAN_SPAN_US   = 500;   // +/- from center at 100%
// Tilt: center (looking level), span at +100% (looking up).
const int TILT_CENTER_US = 1500;
const int TILT_SPAN_US   = -250; // negative flips direction
// Hard limits, never exceeded even by R commands.
const int US_MIN = 700, US_MAX = 2300;

// ---------- motion feel ----------
const float PAN_MAX_SPEED  = 0.9;   // max percent change per 10 ms tick
const float TILT_MAX_SPEED = 0.6;
const float LOOK_SMOOTHING = 0.10;  // 0..1, lower = lazier head
const uint32_t WATCHDOG_MS = 3000;
const uint32_t JAW_TIMEOUT_MS = 400;
const uint8_t EYE_MAX_BRIGHTNESS = 110; // keep current and glare down

Servo jaw, pan, tilt;
Adafruit_NeoPixel eyes(NUM_EYE_LEDS, PIN_EYES, NEO_GRB + NEO_KHZ800);

float panPos = 0, tiltPos = 0, panTarget = 0, tiltTarget = 0, panVel = 0, tiltVel = 0;
int jawPct = 0;
uint8_t eyeMode = 1;
uint8_t eyeR = 255, eyeG = 32, eyeB = 0;
uint32_t lastHost = 0, lastJaw = 0, lastTick = 0, lastEye = 0;
bool attached = false;
bool relaxed = false;   // set by X, cleared by H or R

char buf[40];
uint8_t bufLen = 0;

int clampUs(long us) { return (int)constrain(us, US_MIN, US_MAX); }

void attachAll() {
  if (attached) return;
  jaw.attach(PIN_JAW);
  pan.attach(PIN_PAN);
  tilt.attach(PIN_TILT);
  attached = true;
}

void detachAll() {
  jaw.detach(); pan.detach(); tilt.detach();
  attached = false;
}

void writeServos() {
  if (!attached) return;
  jaw.writeMicroseconds(clampUs(JAW_CLOSED_US + (long)(JAW_OPEN_US - JAW_CLOSED_US) * jawPct / 100));
  pan.writeMicroseconds(clampUs(PAN_CENTER_US + (long)(PAN_SPAN_US * panPos / 100.0)));
  tilt.writeMicroseconds(clampUs(TILT_CENTER_US + (long)(TILT_SPAN_US * tiltPos / 100.0)));
}

// Critically damped-ish follow with a speed cap: smooth starts and stops.
void stepAxis(float &pos, float &vel, float target, float maxSpeed) {
  float desired = (target - pos) * LOOK_SMOOTHING;
  vel += (desired - vel) * 0.25;
  vel = constrain(vel, -maxSpeed, maxSpeed);
  pos += vel;
}

void updateEyes(uint32_t now) {
  if (now - lastEye < 20) return;
  lastEye = now;
  float level;
  switch (eyeMode) {
    case 0: level = 0; break;
    case 1: level = 0.18 + 0.12 * sin(now / 900.0); break;             // slow breathing
    case 2: level = 0.55; break;                                        // alert
    case 3: level = 0.35 + 0.65 * jawPct / 100.0                        // talk: flare with jaw
                    + 0.05 * sin(now / 37.0); break;
    case 4: level = 0.40 + 0.15 * sin(now / 250.0); break;              // listening pulse
    default: level = 0.3;
  }
  level = constrain(level, 0, 1);
  // Small per-LED flicker so the eyes feel like embers, not bulbs.
  for (uint8_t i = 0; i < NUM_EYE_LEDS; i++) {
    float f = level * (0.85 + 0.15 * ((i * 73 + now / 60) % 17) / 16.0);
    if (i % 7 == 0) f = min(1.0, f * 1.2);  // jewel center LED a bit hotter
    uint8_t k = (uint8_t)(f * EYE_MAX_BRIGHTNESS);
    eyes.setPixelColor(i, eyes.Color((uint16_t)eyeR * k / 255, (uint16_t)eyeG * k / 255,
                                     (uint16_t)eyeB * k / 255));
  }
  eyes.show();
}

void status() {
  Serial.print(F("OK pan=")); Serial.print(panPos, 0);
  Serial.print(F(" tilt=")); Serial.print(tiltPos, 0);
  Serial.print(F(" jaw=")); Serial.print(jawPct);
  Serial.print(F(" eyes=")); Serial.print(eyeMode);
  Serial.println(attached ? F(" servos=on") : F(" servos=off"));
}

void handle(char *cmd) {
  char c = cmd[0];
  char *arg = cmd + 1;
  lastHost = millis();
  switch (c) {
    case 'J':
      if (!relaxed) attachAll();
      jawPct = constrain(atoi(arg), 0, 100);
      lastJaw = millis();
      break;
    case 'L': {
      if (!relaxed) attachAll();
      char *comma = strchr(arg, ',');
      panTarget = constrain(atoi(arg), -100, 100);
      if (comma) tiltTarget = constrain(atoi(comma + 1), -100, 100);
      break;
    }
    case 'E': eyeMode = constrain(atoi(arg), 0, 4); break;
    case 'C': {
      int r = 0, g = 0, b = 0;
      sscanf(arg, "%d,%d,%d", &r, &g, &b);
      eyeR = constrain(r, 0, 255); eyeG = constrain(g, 0, 255); eyeB = constrain(b, 0, 255);
      break;
    }
    case 'H':
      relaxed = false;
      attachAll();
      panTarget = tiltTarget = 0; jawPct = 0;
      break;
    case 'X':
      relaxed = true;
      detachAll();
      break;
    case 'R': {
      int ch = 0, us = 1500;
      sscanf(arg, "%d,%d", &ch, &us);
      relaxed = false;
      attachAll();
      us = clampUs(us);
      if (ch == 0) jaw.writeMicroseconds(us);
      if (ch == 1) pan.writeMicroseconds(us);
      if (ch == 2) tilt.writeMicroseconds(us);
      Serial.print(F("RAW ")); Serial.print(ch); Serial.print(' '); Serial.println(us);
      lastTick = millis() + 5000;  // hold the raw pose for 5 s before normal motion resumes
      return;
    }
    case 'S': status(); return;
    default: break;
  }
}

void setup() {
  Serial.begin(115200);
  eyes.begin();
  eyes.clear();
  eyes.show();
  attachAll();
  writeServos();
  lastHost = millis();
  Serial.println(F("SKULL READY"));
}

void loop() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (bufLen) { buf[bufLen] = 0; handle(buf); bufLen = 0; }
    } else if (bufLen < sizeof(buf) - 1) {
      buf[bufLen++] = ch;
    }
  }

  uint32_t now = millis();
  if ((int32_t)(now - lastTick) >= 10) {
    lastTick = now;
    if (now - lastHost > WATCHDOG_MS) { panTarget = 0; tiltTarget = 0; jawPct = 0; }
    if (now - lastJaw > JAW_TIMEOUT_MS) jawPct = 0;
    stepAxis(panPos, panVel, panTarget, PAN_MAX_SPEED);
    stepAxis(tiltPos, tiltVel, tiltTarget, TILT_MAX_SPEED);
    writeServos();
  }
  updateEyes(now);
}
