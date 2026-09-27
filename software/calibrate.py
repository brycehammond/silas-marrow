#!/usr/bin/env python3
"""
Hands-on calibration and test tool.

    python calibrate.py servos     nudge each servo to find its limits
    python calibrate.py eyes       cycle the eye modes and colors
    python calibrate.py mic        live mic level meter (tune speech_min_rms)
    python calibrate.py say "Howdy, pilgrim."   test voice + jaw sync
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cfg():
    return json.loads((HERE / "config.json").read_text())


def open_serial():
    import serial
    c = cfg()["hardware"]
    ser = serial.Serial(c["serial_port"], c["baud"], timeout=0.2)
    time.sleep(2.0)
    ser.reset_input_buffer()
    return ser


def servos():
    ser = open_serial()
    names = {0: "jaw", 1: "pan", 2: "tilt"}
    print(__doc__)
    print("Keys: 0/1/2 pick servo, a/d = -/+ 10us, A/D = -/+ 50us, c = 1500us, q = quit")
    print("Write down the values, then put them in the CALIBRATION block of the sketch.")
    print("Start with the skull OFF the mount so nothing binds while you explore.\n")
    ch, us = 0, 1500
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            ser.write(f"R{ch},{us}\n".encode())
            print(f"\r{names[ch]:5s} {us:5d} us   ", end="", flush=True)
            k = sys.stdin.read(1)
            if k == "q":
                break
            if k in "012":
                ch, us = int(k), 1500
            elif k == "a":
                us -= 10
            elif k == "d":
                us += 10
            elif k == "A":
                us -= 50
            elif k == "D":
                us += 50
            elif k == "c":
                us = 1500
            us = max(700, min(2300, us))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        ser.write(b"H\n")
        print()


def eyes():
    ser = open_serial()
    for name, rgb in [("ember red", (255, 32, 0)), ("ghost green", (40, 255, 60)),
                      ("witch purple", (160, 0, 255)), ("pumpkin", (255, 90, 0))]:
        ser.write(f"C{rgb[0]},{rgb[1]},{rgb[2]}\n".encode())
        for mode, label in [(1, "idle"), (2, "alert"), (4, "listen")]:
            print(f"{name}: {label}")
            ser.write(f"E{mode}\n".encode())
            time.sleep(2.5)
    ser.write(b"C255,32,0\nE1\n")


def mic():
    import numpy as np
    import sounddevice as sd
    from voice import find_device
    dev = find_device(cfg()["ears"].get("input_device"), "input")
    print("Talk at normal volume from where people will stand. Ctrl-C to stop.")
    with sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                        blocksize=480, device=dev) as s:
        while True:
            x, _ = s.read(480)
            rms = float(np.sqrt(np.mean(x ** 2)))
            print(f"\r{rms:6.3f} " + "#" * int(min(60, rms * 600)) + " " * 20,
                  end="", flush=True)


def say(text: str):
    from dotenv import load_dotenv
    from hardware import Skull
    from voice import Mouth
    load_dotenv(HERE / ".env")
    c = cfg()
    skull = Skull(c["hardware"]["serial_port"], c["hardware"]["baud"],
                  dry_run="--no-skull" in sys.argv)
    skull.start()
    time.sleep(2.5)
    skull.eyes(3)
    mouth = Mouth(os.environ["ELEVENLABS_API_KEY"], c["voice"], on_jaw=skull.jaw)
    t = time.time()
    mouth.say(text)
    print(f"done in {time.time() - t:.1f}s")
    skull.eyes(1)
    time.sleep(0.5)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
    elif sys.argv[1] == "servos":
        servos()
    elif sys.argv[1] == "eyes":
        eyes()
    elif sys.argv[1] == "mic":
        mic()
    elif sys.argv[1] == "say":
        say(" ".join(a for a in sys.argv[2:] if not a.startswith("--"))
            or "Well howdy. Welcome to the Elephant Corral, where the coffee is weak "
               "and the ghosts are strong.")
    else:
        print(__doc__)
