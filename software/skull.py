#!/usr/bin/env python3
"""
Silas Marrow, the talking skull of the Elephant Corral.

    python skull.py --list-cameras          find the Anker camera index
    python skull.py --list-audio            find speaker and mic device names
    python skull.py --show --no-skull       test vision + voice without the Arduino
    python skull.py --show                  full run with a preview window
    python skull.py                         headless (use the phone page)
    python skull.py --virtual               on-screen 3D skull instead of the Arduino,
                                            using this computer's camera, mic and speakers

Control page: http://<mac-mini>.local:8090      3D skull: .../skull
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import subprocess
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import cv2
from dotenv import load_dotenv

from hardware import Skull
from virtual import FirmwareSim
from vision import Camera, Tracker, draw_overlay, head_to_look, pick_target

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"
log = logging.getLogger("skull")

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".glb": "model/gltf-binary",
    ".png": "image/png",
    ".jpg": "image/jpeg",
}
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

EYES_OFF, EYES_IDLE, EYES_ALERT, EYES_TALK, EYES_LISTEN = range(5)

CANNED = [
    "Well, well. Another soul wanders into the Elephant Corral.",
    "Wipe your boots. This floor has seen better mud than yours.",
    "Welcome, stranger. The faro table is closed, but the coffee is just as dangerous.",
]


def load_config(path: Path) -> dict:
    return json.loads(path.read_text())


def apply_virtual_overrides(cfg: dict):
    """--virtual: lay the virtual.camera/ears/voice/gaze settings over the main ones."""
    for section in ("camera", "ears", "voice", "gaze"):
        cfg[section].update(cfg.get("virtual", {}).get(section, {}))


def viewer_config(cfg: dict) -> dict:
    v = cfg.get("virtual", {})
    model = v.get("model") or ""
    return {
        "pan_range_deg": cfg["gaze"]["pan_range_deg"],
        "tilt_range_deg": cfg["gaze"]["tilt_range_deg"],
        "jaw_open_deg": v.get("jaw_open_deg", 24),
        "invert_pan": v.get("invert_pan", False),
        "invert_tilt": v.get("invert_tilt", False),
        # A sculpted model in web/ replaces the built-in skull. None if there is none.
        "model": model if model and (WEB / model).is_file() else None,
        "camera_inset": v.get("camera_inset", True),
    }


def open_viewer(url: str):
    """Open the 3D skull in its own window: Chrome app mode if we can, else a tab."""
    try:
        if CHROME.exists():
            subprocess.Popen([str(CHROME), f"--app={url}"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return
    except OSError as e:
        log.warning("Could not start Chrome (%s), using the default browser", e)
    webbrowser.open(url)


class Director:
    """Owns the skull's behavior: who to look at, when to talk, when to listen."""

    def __init__(self, cfg: dict, skull: Skull, brain, mouth, ears):
        self.cfg = cfg
        self.skull, self.brain, self.mouth, self.ears = skull, brain, mouth, ears
        b = cfg["behavior"]
        self.armed = b.get("start_armed", False)
        self.conversation = b.get("conversation", True) and ears is not None
        self.state = "idle"
        self.lock = threading.Lock()

        # shared with the vision loop
        self.frame = None
        self.people = []
        self.target = None
        self.target_since = 0.0
        self.last_seen = 0.0
        self.jpeg = None

        # bookkeeping
        self.last_greet = -1e9
        self.greet_times: deque[float] = deque()
        self.greeted_ids: dict[int, float] = {}
        self.last_ambient = time.monotonic()
        self.last_said = ""
        self.last_heard = ""
        self.said_n = self.heard_n = 0      # lets the 3D page spot a repeated line
        self.events: deque[str] = deque(maxlen=60)
        self._eyes = None
        self._manual: deque[tuple[str, str]] = deque()
        self._cancel = threading.Event()
        self._hush = threading.Event()      # stops a pretend (no voice) line

    # ---- helpers -------------------------------------------------------
    def event(self, msg: str):
        log.info(msg)
        with self.lock:
            self.events.appendleft(time.strftime("%H:%M:%S  ") + msg)

    def eyes(self, mode: int):
        if mode != self._eyes:
            self._eyes = mode
            self.skull.eyes(mode)

    def say(self, text: str) -> bool:
        self.last_said = text
        self.said_n += 1
        self.event(f"SAY: {text}")
        if self.mouth is None:
            return self._pretend(text)
        return self.mouth.say(text)

    def _pretend(self, text: str) -> bool:
        """No voice: move the jaw for about as long as the line would take."""
        self._hush.clear()
        self.eyes(EYES_TALK)
        t0 = time.monotonic()
        length = min(6.0, 0.35 * len(text.split()))
        try:
            while (t := time.monotonic() - t0) < length:
                if self._hush.is_set():
                    return False
                syllable = abs(math.sin(t * math.pi * 4.2))
                phrase = 0.5 + 0.5 * math.sin(t * 1.9 + 1.0) ** 2
                self.skull.jaw(100 * syllable * phrase)
                time.sleep(0.02)
            return True
        finally:
            self.skull.jaw(0)
            self.eyes(EYES_ALERT)

    def person_here(self) -> bool:
        return time.monotonic() - self.last_seen < self.cfg["behavior"]["gone_after_s"]

    def active_hours(self) -> bool:
        start, end = self.cfg["behavior"].get("active_hours", [0, 24])
        return start <= time.localtime().tm_hour < end

    # ---- manual controls from the web page -----------------------------
    def request(self, kind: str, text: str = ""):
        self._manual.append((kind, text))

    def stop_talking(self):
        self._cancel.set()
        self._hush.set()
        if self.mouth:
            self.mouth.stop()

    # ---- main behavior loop --------------------------------------------
    def run(self):
        while True:
            try:
                self._tick()
            except Exception:
                log.exception("Director error")
                self.state = "idle"
                time.sleep(1)
            time.sleep(0.05)

    def _tick(self):
        if self._manual:
            kind, text = self._manual.popleft()
            self._cancel.clear()
            if kind == "say":
                self.state = "speaking"
                self.say(text)
            elif kind == "greet":
                self._encounter(forced=True)
            self.state = "idle"
            return

        now = time.monotonic()
        b = self.cfg["behavior"]
        while self.greet_times and now - self.greet_times[0] > 3600:
            self.greet_times.popleft()
        for tid, t in list(self.greeted_ids.items()):
            if now - t > b["regreet_same_person_after_s"]:
                del self.greeted_ids[tid]

        target = self.target
        if (self.armed and target is not None and self.active_hours()
                and target.track_id not in self.greeted_ids
                and target.height_frac >= b["min_height_frac"]
                and (target.face_visible or not b.get("require_face", True))
                and now - self.target_since >= b["present_s"]
                and now - self.last_greet >= b["min_gap_s"]
                and len(self.greet_times) < b["max_greetings_per_hour"]):
            self._encounter()
            return

        amb = b.get("ambient_every_min", 0)
        if (self.armed and amb and self.brain and self.active_hours()
                and not self.person_here()
                and now - self.last_ambient > amb * 60
                and now - self.last_greet > amb * 60):
            self.last_ambient = now
            self.state = "speaking"
            self.say(self.brain.ambient())
            self.state = "idle"

    def _encounter(self, forced: bool = False):
        b = self.cfg["behavior"]
        target, frame = self.target, self.frame
        if frame is None:
            return
        now = time.monotonic()
        self.last_greet = now
        self.greet_times.append(now)
        if target is not None:
            self.greeted_ids[target.track_id] = now

        self.state = "thinking"
        self.eyes(EYES_ALERT)
        self.event("Greeting " + (f"person #{target.track_id}" if target else "(manual)"))
        try:
            line = self.brain.greet(frame) if self.brain else random.choice(CANNED)
        except Exception as e:
            self.event(f"Claude error: {e}")
            line = random.choice(CANNED)

        self.state = "speaking"
        if not self.say(line) or self._cancel.is_set():
            return

        if not (self.conversation and self.ears and self.brain):
            return
        for _turn in range(b["max_conversation_turns"]):
            if not self.person_here() or self._cancel.is_set():
                break
            self.state = "listening"
            self.eyes(EYES_LISTEN)
            wav = self.ears.listen(b["listen_wait_s"], b["listen_max_s"], self._cancel)
            if wav is None:
                break
            self.state = "thinking"
            self.eyes(EYES_ALERT)
            try:
                heard = self.ears.transcribe(wav)
            except Exception as e:
                self.event(f"STT error: {e}")
                break
            if len(heard) < 2:
                break
            self.last_heard = heard
            self.heard_n += 1
            self.event(f"HEARD: {heard}")
            try:
                line = self.brain.reply(heard)
            except Exception as e:
                self.event(f"Claude error: {e}")
                break
            self.state = "speaking"
            if not self.say(line):
                break
        self.brain.reset()

    def status(self) -> dict:
        t = self.target
        with self.lock:
            events = list(self.events)
        return {
            "state": self.state,
            "armed": self.armed,
            "conversation": self.conversation,
            "people": len(self.people),
            "target": t.track_id if t else None,
            "skull": self.skull.status_line if self.skull.connected else "disconnected",
            "greetings_last_hour": len(self.greet_times),
            "last_said": self.last_said,
            "last_heard": self.last_heard,
            "volume": self.mouth.cfg.get("volume", 1.0) if self.mouth else None,
            "events": events,
        }


# --------------------------------------------------------------------------
# Vision + gaze loop (main thread)
# --------------------------------------------------------------------------

def vision_loop(cfg, camera, tracker, director: Director, skull: Skull, show: bool):
    gaze = cfg["gaze"]
    wander_at, wander = 0.0, (0.0, 0.0)
    while True:
        frame = camera.latest()
        if frame is None:
            time.sleep(0.02)
            continue
        people = tracker.people(frame)
        now = time.monotonic()
        prev = director.target
        target = pick_target(people, prev.track_id if prev else None)
        if target is not None:
            if prev is None or prev.track_id != target.track_id:
                director.target_since = now
            director.last_seen = now
        director.frame, director.people, director.target = frame, people, target

        busy = director.state != "idle"
        if target is not None:
            pan, tilt = head_to_look(target.head, gaze)
            skull.look(pan, tilt)
            if not busy:
                director.eyes(EYES_ALERT)
        elif not busy and not director.person_here():
            director.eyes(EYES_IDLE)
            if gaze.get("idle_wander", True) and now > wander_at:
                wander = (random.uniform(-35, 35), random.uniform(-10, 20))
                wander_at = now + random.uniform(4, 9)
            skull.look(*wander)

        status = (f"{director.state.upper()}  {'ARMED' if director.armed else 'disarmed'}"
                  f"  people:{len(people)}  cam:{camera.fps:.0f}fps"
                  f"  skull:{'ok' if skull.connected else 'offline'}")
        vis = draw_overlay(frame, people, target, status)
        ok, jpg = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 65])
        if ok:
            director.jpeg = jpg.tobytes()
        if show:
            cv2.imshow("skull (q quit, a arm, g greet, s stop)", vis)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                return
            if key == ord("a"):
                director.armed = not director.armed
                director.event("ARMED" if director.armed else "Disarmed")
            if key == ord("g"):
                director.request("greet")
            if key == ord("s"):
                director.stop_talking()


# --------------------------------------------------------------------------
# Phone control page
# --------------------------------------------------------------------------

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Silas Marrow</title>
<style>
 :root{--bg:#120d0a;--card:#1f1813;--fg:#efe6da;--dim:#a8998a;--accent:#d9822b;--red:#b3261e}
 body{background:var(--bg);color:var(--fg);font-family:-apple-system,system-ui,sans-serif;margin:0;padding:16px;max-width:720px;margin:auto}
 h1{font-size:20px;margin:0 0 4px}.sub{color:var(--dim);font-size:13px;margin-bottom:12px}
 img{width:100%;border-radius:10px;background:#000;display:block}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
 button{font-size:16px;padding:14px;border:0;border-radius:10px;color:var(--fg);background:#3a2e25}
 button.on{background:var(--accent);color:#1a1008}
 #stop{background:var(--red)}
 .card{background:var(--card);border-radius:10px;padding:12px;margin:10px 0}
 .row{display:flex;gap:8px}.row input[type=text]{flex:1;font-size:16px;padding:12px;border-radius:8px;border:0;background:#2c231c;color:var(--fg)}
 .kv{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:14px}.kv b{color:var(--dim);font-weight:500}
 ul{padding-left:18px;font-size:13px;color:var(--dim);max-height:35vh;overflow:auto;margin:0}
 label{font-size:14px;color:var(--dim)}input[type=range]{width:100%}
</style></head><body>
<h1>Silas Marrow</h1><div class="sub">Talking skull of the Elephant Corral</div>
<img id="cam" alt="camera">
<div class="grid">
 <button id="arm" onclick="toggle('arm')">Arm</button>
 <button id="conv" onclick="toggle('conversation')">Conversation</button>
 <button onclick="act('greet')">Greet now</button>
 <button id="stop" onclick="act('stop')">Stop talking</button>
 <button onclick="act('home')">Center head</button>
 <button onclick="act('relax')">Relax servos</button>
 <button style="grid-column:1/-1" onclick="window.open('/skull' + q())">3D skull</button>
</div>
<div class="card"><div class="row">
 <input id="say" type="text" placeholder="Make Silas say something..." onkeydown="if(event.key==='Enter')sayIt()">
 <button onclick="sayIt()">Say</button></div></div>
<div class="card">
 <label>Volume <span id="volv"></span></label>
 <input id="vol" type="range" min="0" max="2" step="0.05" onchange="setVol(this.value)">
 <label>Eye color</label> <input id="eyec" type="color" value="#ff2000" onchange="setEyes(this.value)">
</div>
<div class="card kv" id="stat"></div>
<div class="card"><ul id="events"></ul></div>
<script>
const t = new URLSearchParams(location.search).get('t') || '';
const q = (extra) => '?' + new URLSearchParams(Object.assign(t ? {t} : {}, extra || {}));
document.getElementById('cam').src = '/stream' + q();
let S = {};
async function act(a, extra){ await fetch('/api/' + a + q(extra), {method:'POST'}); refresh(); }
function toggle(what){ act(what, {on: S[what === 'arm' ? 'armed' : what] ? '0' : '1'}); }
function sayIt(){ const el = document.getElementById('say'); if(el.value.trim()){ act('say', {text: el.value}); el.value=''; } }
function setVol(v){ act('volume', {v}); }
function setEyes(hex){ act('eyes', {hex: hex.slice(1)}); }
const esc = s => (s || '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function refresh(){
  try {
    S = await (await fetch('/api/status' + q())).json();
    document.getElementById('arm').classList.toggle('on', S.armed);
    document.getElementById('arm').textContent = S.armed ? 'Armed' : 'Arm';
    document.getElementById('conv').classList.toggle('on', S.conversation);
    const vol = document.getElementById('vol');
    if (S.volume !== null && document.activeElement !== vol) vol.value = S.volume;
    document.getElementById('volv').textContent = S.volume === null ? 'n/a' : Math.round(S.volume * 100) + '%';
    document.getElementById('stat').innerHTML =
      `<b>State</b><span>${S.state}</span><b>People</b><span>${S.people}</span>
       <b>Skull</b><span>${esc(S.skull)}</span><b>Greetings/hr</b><span>${S.greetings_last_hour}</span>
       <b>Said</b><span>${esc(S.last_said)}</span><b>Heard</b><span>${esc(S.last_heard)}</span>`;
    document.getElementById('events').innerHTML = S.events.map(e => `<li>${esc(e)}</li>`).join('');
  } catch (e) {}
}
setInterval(refresh, 1000); refresh();
</script></body></html>"""


def make_handler(director: Director, skull: Skull, token: str, sim: FirmwareSim,
                 viewer_cfg: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _q(self):
            return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

        def _authed(self):
            return not token or self._q().get("t") == token

        def _send(self, body: bytes, ctype: str, code: int = 200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(json.dumps(obj).encode(), "application/json", code)

        def do_GET(self):
            path = urlparse(self.path).path
            if path.startswith("/web/"):
                # Scripts and models only. No token: module imports cannot carry one.
                return self._static(path[len("/web/"):])
            if not self._authed():
                return self._json({"error": "bad token"}, 403)
            if path == "/":
                self._send(PAGE.encode(), "text/html; charset=utf-8")
            elif path == "/skull":
                self._static("skull.html")
            elif path == "/api/status":
                self._json(director.status())
            elif path == "/api/pose":
                self._pose()
            elif path == "/stream":
                self._stream()
            else:
                self._json({"error": "not found"}, 404)

        def _static(self, rel: str):
            f = (WEB / unquote(rel)).resolve()
            if (not f.is_relative_to(WEB) or not f.is_file()
                    or f.suffix not in STATIC_TYPES):
                return self._json({"error": "not found"}, 404)
            self._send(f.read_bytes(), STATIC_TYPES[f.suffix])

        def _pose(self):
            """Server-sent events for the 3D skull: config once, then pose and status."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            def send(event: str, obj):
                self.wfile.write(f"event: {event}\ndata: {json.dumps(obj)}\n\n".encode())

            try:
                send("config", viewer_cfg)
                pose = status = None
                sent_at = 0.0
                while True:
                    now = time.monotonic()
                    p = sim.snapshot()
                    if p != pose or now - sent_at > 0.5:
                        send("pose", p)
                        pose, sent_at = p, now
                    st = {"state": director.state, "armed": director.armed,
                          "people": len(director.people),
                          "said": director.last_said, "said_n": director.said_n,
                          "heard": director.last_heard, "heard_n": director.heard_n}
                    if st != status:
                        send("status", st)
                        status = st
                    time.sleep(1 / 60)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            if not self._authed():
                return self._json({"error": "bad token"}, 403)
            path, q = urlparse(self.path).path, self._q()
            on = q.get("on") == "1"
            if path == "/api/arm":
                director.armed = on
                director.event("ARMED" if on else "Disarmed")
            elif path == "/api/conversation":
                director.conversation = on and director.ears is not None
                director.event(f"Conversation {'on' if director.conversation else 'off'}")
            elif path == "/api/greet":
                director.request("greet")
            elif path == "/api/say":
                if q.get("text", "").strip():
                    director.request("say", q["text"].strip()[:400])
            elif path == "/api/stop":
                director.stop_talking()
            elif path == "/api/home":
                skull.home()
            elif path == "/api/relax":
                skull.relax()
            elif path == "/api/volume" and director.mouth:
                director.mouth.cfg["volume"] = max(0.0, min(2.0, float(q.get("v", 1))))
            elif path == "/api/eyes":
                h = q.get("hex", "ff2000")
                skull.eye_color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            else:
                return self._json({"error": "not found"}, 404)
            self._json(director.status())

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    jpg = director.jpeg
                    if jpg:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                         b"Content-Length: %d\r\n\r\n" % len(jpg))
                        self.wfile.write(jpg + b"\r\n")
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


# --------------------------------------------------------------------------

def list_cameras():
    for i in range(6):
        cap = cv2.VideoCapture(i, cv2.CAP_AVFOUNDATION)
        ok, frame = cap.read()
        if ok:
            print(f"camera {i}: {frame.shape[1]}x{frame.shape[0]}")
        cap.release()


def main():
    ap = argparse.ArgumentParser(description="Silas Marrow, the talking skull")
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--show", action="store_true", help="show a preview window")
    ap.add_argument("--no-skull", action="store_true", help="run without the Arduino")
    ap.add_argument("--virtual", action="store_true",
                    help="on-screen 3D skull instead of the Arduino, with this "
                         "computer's camera, mic and speakers")
    ap.add_argument("--no-voice", action="store_true", help="print lines instead of speaking")
    ap.add_argument("--no-ai", action="store_true", help="use canned lines, no Claude calls")
    ap.add_argument("--list-cameras", action="store_true")
    ap.add_argument("--list-audio", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    if args.list_cameras:
        return list_cameras()
    if args.list_audio:
        from voice import list_audio_devices
        return list_audio_devices()

    load_dotenv(HERE / ".env")
    cfg = load_config(Path(args.config))
    if args.virtual:
        args.no_skull = True
        apply_virtual_overrides(cfg)

    sim = FirmwareSim()
    sim.start()
    skull = Skull(cfg["hardware"]["serial_port"], cfg["hardware"]["baud"],
                  dry_run=args.no_skull, sim=sim)
    skull.start()

    brain = None
    if not args.no_ai:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("Set ANTHROPIC_API_KEY in software/.env (or use --no-ai)")
        from brain import Brain
        brain = Brain(cfg["claude"], HERE / cfg["claude"].get("persona_file", "persona.md"))

    mouth = ears = None
    if not args.no_voice:
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise SystemExit("Set ELEVENLABS_API_KEY in software/.env (or use --no-voice)")
        from voice import Ears, Mouth
        director_ref = {}
        mouth = Mouth(key, cfg["voice"], on_jaw=skull.jaw,
                      on_state=lambda talking: director_ref["d"].eyes(
                          EYES_TALK if talking else EYES_ALERT))
        ears = Ears(key, cfg["ears"])

    director = Director(cfg, skull, brain, mouth, ears)
    if mouth:
        director_ref["d"] = director
    skull.eye_color(*cfg["hardware"].get("eye_color", [255, 32, 0]))
    threading.Thread(target=director.run, daemon=True, name="director").start()

    token = cfg["web"].get("token", "")
    server = ThreadingHTTPServer(("0.0.0.0", cfg["web"]["port"]),
                                 make_handler(director, skull, token, sim,
                                              viewer_config(cfg)))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    director.event(f"Control page on port {cfg['web']['port']}")
    if args.virtual and cfg.get("virtual", {}).get("open_window", True):
        open_viewer(f"http://localhost:{cfg['web']['port']}/skull"
                    + (f"?{urlencode({'t': token})}" if token else ""))

    c = cfg["camera"]
    camera = Camera(c["index"], c["width"], c["height"], c.get("rotate", 0),
                    c.get("mirror", False))
    camera.start()
    tracker = Tracker(c.get("model", "yolo11n-pose.pt"), c.get("confidence", 0.5))

    try:
        vision_loop(cfg, camera, tracker, director, skull, args.show)
    except KeyboardInterrupt:
        pass
    finally:
        skull.home()
        time.sleep(0.3)
        cv2.destroyAllWindows()
        server.shutdown()


if __name__ == "__main__":
    main()
