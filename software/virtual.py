"""
Software twin of the Arduino sketch, for the on-screen 3D skull.

FirmwareSim takes the same newline-free ASCII commands that hardware.Skull
writes to the serial port and behaves like firmware/skull_controller.ino:
smoothed and speed-capped head motion, the jaw timeout and the host watchdog.
The web viewer (web/skull.js) reads snapshot() through /api/pose.

The constants below are copies of the "motion feel" block in the sketch.
Keep the two in sync.
"""

from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("skull.virtual")

PAN_MAX_SPEED = 0.9      # max percent change per 10 ms tick
TILT_MAX_SPEED = 0.6
LOOK_SMOOTHING = 0.10    # 0..1, lower = lazier head
VEL_BLEND = 0.25
WATCHDOG_S = 3.0
JAW_TIMEOUT_S = 0.4
TICK_S = 0.010


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _atoi(s: str) -> int:
    """C atoi: leading whitespace, optional sign, digits; 0 if there are none."""
    s = s.lstrip()
    end = 1 if s[:1] in ("+", "-") else 0
    while end < len(s) and s[end].isdigit():
        end += 1
    try:
        return int(s[:end])
    except ValueError:
        return 0


class FirmwareSim:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        now = clock()
        self.pan_pos = self.tilt_pos = 0.0
        self.pan_vel = self.tilt_vel = 0.0
        self.pan_target = self.tilt_target = 0.0
        self.jaw_pct = 0
        self.eye_mode = 1
        self.eye_rgb = (255, 32, 0)
        self.attached = True
        self.relaxed = False          # set by X, cleared by H
        self._last_host = now
        self._last_jaw = now
        # What the servos were last told. Detached servos keep their pose.
        self._out = (0.0, 0.0, 0)

    # ---- commands --------------------------------------------------------
    def handle(self, line: str) -> str | None:
        """Process one command. Returns the reply line for S, else None."""
        line = line.strip()
        if not line:
            return None
        c, arg = line[0], line[1:]
        with self._lock:
            now = self._clock()
            self._last_host = now
            if c == "J":
                if not self.relaxed:
                    self.attached = True
                self.jaw_pct = _clamp(_atoi(arg), 0, 100)
                self._last_jaw = now
            elif c == "L":
                if not self.relaxed:
                    self.attached = True
                pan, _, tilt = arg.partition(",")
                self.pan_target = float(_clamp(_atoi(pan), -100, 100))
                if tilt:
                    self.tilt_target = float(_clamp(_atoi(tilt), -100, 100))
            elif c == "E":
                self.eye_mode = _clamp(_atoi(arg), 0, 4)
            elif c == "C":
                rgb = [_clamp(_atoi(p), 0, 255) for p in arg.split(",")[:3]]
                self.eye_rgb = tuple(rgb + [0] * (3 - len(rgb)))
            elif c == "H":
                self.relaxed = False
                self.attached = True
                self.pan_target = self.tilt_target = 0.0
                self.jaw_pct = 0
            elif c == "X":
                self.relaxed = True
                self.attached = False
            elif c == "S":
                return self._status()
            # R (raw calibration pulses) has no meaning without real servos.
        return None

    # ---- motion ----------------------------------------------------------
    @staticmethod
    def _step_axis(pos, vel, target, max_speed):
        desired = (target - pos) * LOOK_SMOOTHING
        vel += (desired - vel) * VEL_BLEND
        vel = _clamp(vel, -max_speed, max_speed)
        return pos + vel, vel

    def tick(self, now: float | None = None):
        """One 10 ms firmware tick."""
        with self._lock:
            if now is None:
                now = self._clock()
            if now - self._last_host > WATCHDOG_S:
                self.pan_target = self.tilt_target = 0.0
                self.jaw_pct = 0
            if now - self._last_jaw > JAW_TIMEOUT_S:
                self.jaw_pct = 0
            self.pan_pos, self.pan_vel = self._step_axis(
                self.pan_pos, self.pan_vel, self.pan_target, PAN_MAX_SPEED)
            self.tilt_pos, self.tilt_vel = self._step_axis(
                self.tilt_pos, self.tilt_vel, self.tilt_target, TILT_MAX_SPEED)
            if self.attached:
                self._out = (self.pan_pos, self.tilt_pos, self.jaw_pct)

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="skull-sim").start()

    def _run(self):
        due = self._clock()
        while True:
            now = self._clock()
            steps = 0
            while due <= now and steps < 25:
                self.tick(now)
                due += TICK_S
                steps += 1
            if due <= now:          # fell far behind (the Mac slept): do not replay it
                due = now + TICK_S
            time.sleep(max(0.0, due - self._clock()))

    # ---- readout ---------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            pan, tilt, jaw = self._out
            return {
                "pan": round(pan, 2) + 0.0,       # + 0.0 turns -0.0 into 0.0
                "tilt": round(tilt, 2) + 0.0,
                "jaw": int(jaw),
                "eye_mode": self.eye_mode,
                "eye_rgb": list(self.eye_rgb),
                "servos": self.attached,
            }

    def _status(self) -> str:
        return (f"OK pan={self.pan_pos:.0f} tilt={self.tilt_pos:.0f} jaw={self.jaw_pct}"
                f" eyes={self.eye_mode} servos={'on' if self.attached else 'off'}")

    def status(self) -> str:
        with self._lock:
            return self._status()
