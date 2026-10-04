# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An animatronic talking skull ("Silas Marrow") that runs on a Mac mini. It has three parts, and each one depends on the others: Python software (`software/`), an Arduino sketch (`firmware/skull_controller/`), and parametric OpenSCAD parts (`cad/`). `README.md` is the full build and user guide (parts, wiring, assembly, calibration, troubleshooting).

## Commands

There are no tests, linter or build system. All Python runs from `software/`, inside the venv:

```bash
cd software
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                    # ANTHROPIC_API_KEY, ELEVENLABS_API_KEY

python skull.py --no-skull --no-voice --no-ai --show   # vision only, no hardware or API calls
python skull.py --show --no-skull       # camera + Claude + voice, no Arduino
python skull.py --show                  # full run with preview window
python skull.py --virtual               # on-screen 3D skull instead of the Arduino; built-in camera, mic, speakers
python skull.py -v                      # headless, debug logging
python skull.py --list-cameras | --list-audio

python calibrate.py servos | eyes | mic | say "Howdy, pilgrim."
```

The `--no-skull`, `--no-voice` and `--no-ai` flags each stub out one subsystem. Use them to exercise a change without the hardware or API keys. `--virtual` implies `--no-skull`, lays `cfg["virtual"]`'s `camera/ears/voice/gaze` over the main sections, and opens the viewer.

The viewer has test switches that need no running server state: `/skull?pose=<pan>,<tilt>,<jaw>,<eyes>` holds one pose, `?demo=1` self-animates, `?cam=front|34|side|low` moves the camera. `window.silas` exposes the scene in the browser console.

Export a CAD part (from `cad/`): `openscad -D 'part="turntable"' -o stl/turntable.stl skull_parts.scad`. Valid `part` names are listed at the bottom of the `.scad` file. `part="assembly"` previews the whole build.

The firmware is uploaded from the Arduino IDE and needs the Adafruit NeoPixel library.

## Architecture

**Threads in `skull.py`.** `main()` builds the components and starts these threads:
- **Main thread:** `vision_loop`. It reads frames, runs YOLO pose tracking (`vision.Tracker`), picks a target, sets `skull.look()`, and writes `director.target/frame/people`. It has to stay on the main thread because `cv2.imshow` (`--show`) needs it.
- **`Director.run`:** a state machine (`idle/thinking/speaking/listening`) that decides when to greet. `_encounter()` runs one greeting plus the conversation turns, and it blocks the director thread while it runs. Manual actions from the web page (`say`, `greet`) are queued in `_manual` and picked up by `_tick()`. `_cancel` interrupts an encounter.
- **HTTP control page:** `make_handler` → `ThreadingHTTPServer` on `web.port`. The phone UI's HTML is inline in `skull.py`. It talks to the `Director` and `Skull` objects directly. It also serves the 3D viewer: `/skull` (page), `/web/*` (static files from `software/web/`, exempt from the token because module imports cannot carry it) and `/api/pose` (server-sent events: `config` once, then `pose` and `status`).
- **`virtual.FirmwareSim`:** a 100 Hz thread that plays the Arduino's part.
- **`vision.Camera`**, **`hardware.Skull`** serial pump, and the **`voice.Mouth`** audio callback and receiver threads each run in the background too.

**Who gets greeted.** `faces.FaceMemory` (OpenCV YuNet + SFace, models downloaded to `software/models/` on first run) keeps face embeddings in memory for `regreet_same_person_after_s`. `Director._consider` runs on the director thread: it takes `face_looks` front-on looks at the target, greets if none match a remembered person, and otherwise stays quiet unless they keep looking for `linger_s`. YOLO track IDs (`greeted_ids`) are only a cache for the current appearance. Nothing is persisted, so the README privacy section must stay true.

**Data flow for one line.** `brain.Brain` (Anthropic SDK; system prompt = `persona.md` + time of day + recently said lines) → text → `voice.Mouth.say()` streams ElevenLabs TTS (PCM, with an MP3/ffmpeg fallback) to `sounddevice`. The output callback computes the audio level in dB and maps it through `jaw_floor_db`/`jaw_ceiling_db` with attack/release to call `on_jaw` → `Skull.jaw()`. `voice.Ears` records until silence (RMS threshold) and transcribes with ElevenLabs Scribe. `Brain.history` holds only the current encounter and is cleared by `reset()`. `Brain.recent` persists across encounters so lines don't repeat.

**Serial protocol (Mac → Arduino).** Commands are newline-terminated ASCII (`J`, `L`, `E`, `C`, `H`, `X`, `R`, `S`). They are documented in both `hardware.py` and the header of `skull_controller.ino`, so keep the two in sync. `Skull` never blocks callers: `jaw()`/`look()` only store targets, and a 50 Hz thread sends the values that changed. The firmware smooths head motion, clamps every pulse to the calibrated limits, closes the jaw after `JAW_TIMEOUT_MS` without `J`, and re-centers after `WATCHDOG_MS` without any host traffic. The Python side therefore has to keep sending.

**Virtual skull.** `Skull._pump` tees every serial line into `virtual.FirmwareSim`, a Python port of the sketch's `handle()` and `loop()`. It runs in every mode, so `/skull` is the stand-in with `--virtual` and a live twin with real hardware. `web/skull.js` draws whatever `FirmwareSim.snapshot()` reports. Nothing upstream (`Director`, `vision_loop`, `Mouth`) knows which skull is listening. Firmware behavior now lives in three places that must stay in sync: the motion constants and command parsing in the `.ino` and `virtual.py`, and the eye brightness formulas in the `.ino` (`updateEyes`) and `web/skull.js` (`eyeLevel`, `flicker`).

`web/skullgeo.js` builds the default skull from signed distance functions meshed with surface nets at page load. A `web/skull.glb` with nodes `cranium`, `jaw`, `eye_L`, `eye_R` replaces it. three.js is vendored and pinned in `web/vendor/` (r169); keep the folder layout, the loader imports `../utils/`.

**Where the tuning lives:**
- `software/config.json`: all runtime behavior (gaze math, greeting rules and rate caps, Claude model, voice and jaw sync, mic thresholds, devices). `cfg[...]` sections are passed straight into each component.
- Servo pulse calibration (`JAW_*_US`, `PAN_*`, `TILT_*`) and motion feel are compile-time constants at the top of the `.ino`, not in config.
- `software/persona.md`: character, history and content rules (no comments on bodies, age or race; admit it's an AI if sincerely asked). It is read at startup.
- CAD dimensions marked `(M)` in `skull_parts.scad` are the measured hardware dimensions. The STLs in `cad/stl/` are exports at default values and are regenerated by hand.
- Cable path through the neck: the `horn_column` is flattened to `column_w` and the turntable has matching openings (`column_profile`, `cable_channels`). Wires drop beside the flats, inside the lazy susan's `ls_hole`. The column is solid because the pan servo's horn caps its bottom, so a hollow column would not help. `turntable` and `horn_column` share `col_screw_a` and must be re-exported together.

Eye mode integers (`EYES_OFF..EYES_LISTEN` = 0..4 in `skull.py`) must match the `E<mode>` cases in the firmware.

**Build docs.** `docs/parts.md` is the parts list, `docs/wiring.svg` is the wiring diagram, and `docs/assembly.md` is the assembly guide. The guide's screw table is derived from hole sizes in the `.scad`, and its "Open questions" section records design points not yet confirmed on real parts (the cable path beside the horn column, missing bearing fasteners). All three restate facts held elsewhere, so update them when those change: the `PIN_*` constants in the `.ino`, the wiring text in README section 3, the parts in README sections 1 and 2, and the `(M)` dimensions in `skull_parts.scad`. The SVG is hand-laid-out text with a solid background so it reads in GitHub dark mode.
