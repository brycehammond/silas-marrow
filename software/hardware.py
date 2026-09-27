"""
Serial link to the skull's Arduino (jaw, neck pan/tilt, eye LEDs).

A background thread streams the latest jaw and look targets at a fixed rate,
so the audio and vision threads only ever set numbers and never block on USB.
Protocol (newline terminated, see firmware/skull_controller.ino):
    J<0-100>            jaw open percent
    L<pan>,<tilt>       look target, each -100..100 percent of calibrated range
    E<mode>             eyes: 0 off, 1 idle, 2 alert, 3 talk, 4 listen
    C<r>,<g>,<b>        eye color 0-255
    H                   home (center, jaw closed)
    X                   relax (detach servos)
    S                   status
"""

from __future__ import annotations

import logging
import threading
import time

import serial

log = logging.getLogger("skull.hw")


class Skull:
    def __init__(self, port: str, baud: int = 115200, dry_run: bool = False,
                 rate_hz: float = 50.0):
        self.port = port
        self.baud = baud
        self.dry_run = dry_run
        self.period = 1.0 / rate_hz
        self.connected = dry_run
        self.status_line = "dry run" if dry_run else "disconnected"

        self._lock = threading.Lock()
        self._jaw = 0
        self._look = (0, 0)
        self._sent_jaw = None
        self._sent_look = None
        self._last_look_sent = 0.0
        self._last_jaw_sent = 0.0
        self._pending: list[str] = []
        self._ser = None

    # ---- targets set by other threads ---------------------------------
    def jaw(self, percent: float):
        self._jaw = int(max(0, min(100, percent)))

    def look(self, pan: float, tilt: float):
        self._look = (int(max(-100, min(100, pan))), int(max(-100, min(100, tilt))))

    def eyes(self, mode: int):
        self.command(f"E{int(mode)}")

    def eye_color(self, r: int, g: int, b: int):
        self.command(f"C{int(r)},{int(g)},{int(b)}")

    def home(self):
        self._jaw = 0
        self._look = (0, 0)
        self.command("H")

    def relax(self):
        self.command("X")

    def command(self, cmd: str):
        with self._lock:
            self._pending.append(cmd)

    # ---- serial thread --------------------------------------------------
    def start(self):
        threading.Thread(target=self._run, daemon=True, name="skull-serial").start()

    def _run(self):
        while True:
            if self.dry_run:
                self._pump(lambda line: log.debug("(dry) %s", line))
                continue
            try:
                with serial.Serial(self.port, self.baud, timeout=0) as ser:
                    time.sleep(2.0)  # Arduino resets when the port opens
                    ser.reset_input_buffer()
                    self._ser = ser
                    self.connected = True
                    self._sent_jaw = self._sent_look = None
                    log.info("Skull connected on %s", self.port)
                    buf = b""
                    while True:
                        self._pump(lambda line: ser.write((line + "\n").encode()))
                        data = ser.read(256)
                        if data:
                            buf += data
                            while b"\n" in buf:
                                line, buf = buf.split(b"\n", 1)
                                text = line.decode(errors="replace").strip()
                                if text:
                                    self.status_line = text
                                    log.debug("skull: %s", text)
            except (serial.SerialException, OSError) as e:
                if self.connected:
                    log.warning("Skull serial lost (%s), retrying", e)
                self.connected = False
                self._ser = None
                self.status_line = "disconnected"
                time.sleep(3)

    def _pump(self, write):
        start = time.monotonic()
        with self._lock:
            pending, self._pending = self._pending, []
        for cmd in pending:
            write(cmd)
        jaw = self._jaw
        # Re-send an open jaw every 100 ms; the firmware closes it if we go quiet.
        if jaw != self._sent_jaw or (jaw > 0 and start - self._last_jaw_sent > 0.1):
            write(f"J{jaw}")
            self._sent_jaw = jaw
            self._last_jaw_sent = start
        look = self._look
        # Re-send the look target at least every 0.5 s so the firmware
        # watchdog knows the host is alive.
        if look != self._sent_look or start - self._last_look_sent > 0.5:
            write(f"L{look[0]},{look[1]}")
            self._sent_look = look
            self._last_look_sent = start
        time.sleep(max(0.0, self.period - (time.monotonic() - start)))
