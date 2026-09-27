"""
Voice in and out, using ElevenLabs.

Mouth:  text -> ElevenLabs streaming TTS (raw PCM) -> speaker, while the loudness
        of each audio block drives the jaw servo, timed to when that block
        actually leaves the speaker.
Ears:   Anker mic -> simple energy-based speech detection -> ElevenLabs Scribe
        speech-to-text.
"""

from __future__ import annotations

import io
import logging
import math
import subprocess
import threading
import time
import wave
from collections import deque

import numpy as np
import requests
import sounddevice as sd

log = logging.getLogger("skull.voice")

API = "https://api.elevenlabs.io/v1"


def find_device(name_part: str | None, kind: str):
    """Return a sounddevice index whose name contains name_part (case-insensitive)."""
    if not name_part:
        return None
    key = "max_output_channels" if kind == "output" else "max_input_channels"
    for i, d in enumerate(sd.query_devices()):
        if d[key] > 0 and name_part.lower() in d["name"].lower():
            return i
    log.warning("No %s device matching %r, using the system default", kind, name_part)
    return None


def list_audio_devices():
    for i, d in enumerate(sd.query_devices()):
        io_ = []
        if d["max_input_channels"]:
            io_.append("in")
        if d["max_output_channels"]:
            io_.append("out")
        print(f"{i:2d}  {'/'.join(io_):6s}  {d['name']}")


# --------------------------------------------------------------------------
# Mouth
# --------------------------------------------------------------------------

class Mouth:
    def __init__(self, api_key: str, cfg: dict, on_jaw, on_state=None):
        self.key = api_key
        self.cfg = cfg
        self.on_jaw = on_jaw                  # callable(percent)
        self.on_state = on_state or (lambda speaking: None)
        self.device = find_device(cfg.get("output_device"), "output")
        self.speaking = False
        self._stop = threading.Event()
        self._lock = threading.Lock()         # one utterance at a time

    def stop(self):
        self._stop.set()

    # ---- ElevenLabs ------------------------------------------------------
    def _tts_stream(self, text: str, fmt: str):
        c = self.cfg
        url = f"{API}/text-to-speech/{c['voice_id']}/stream"
        params = {"output_format": fmt,
                  "optimize_streaming_latency": c.get("optimize_streaming_latency", 2)}
        body = {
            "text": text,
            "model_id": c["tts_model"],
            "voice_settings": {
                "stability": c.get("stability", 0.45),
                "similarity_boost": c.get("similarity_boost", 0.8),
                "style": c.get("style", 0.35),
                "use_speaker_boost": True,
            },
        }
        r = requests.post(url, params=params, json=body, stream=True, timeout=30,
                          headers={"xi-api-key": self.key, "accept": "*/*"})
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs TTS {r.status_code}: {r.text[:300]}")
        return r

    def _pcm_chunks(self, text: str):
        """Yield (sample_rate, int16 bytes). Falls back to MP3 + ffmpeg if PCM is refused."""
        fmt = self.cfg.get("output_format", "pcm_22050")
        try:
            r = self._tts_stream(text, fmt)
            sr = int(fmt.split("_")[1])
            yield sr, None
            for chunk in r.iter_content(chunk_size=4096):
                if self._stop.is_set():
                    return
                yield sr, chunk
            return
        except RuntimeError as e:
            if "output_format" not in str(e) and "403" not in str(e):
                raise
            log.warning("PCM output refused (%s); falling back to MP3 via ffmpeg", e)

        r = self._tts_stream(text, "mp3_44100_128")
        sr = 24000
        ff = subprocess.Popen(
            ["ffmpeg", "-loglevel", "quiet", "-i", "pipe:0", "-f", "s16le",
             "-ac", "1", "-ar", str(sr), "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)

        def feed():
            try:
                for chunk in r.iter_content(chunk_size=4096):
                    ff.stdin.write(chunk)
            finally:
                ff.stdin.close()
        threading.Thread(target=feed, daemon=True).start()
        yield sr, None
        while not self._stop.is_set():
            data = ff.stdout.read(4096)
            if not data:
                break
            yield sr, data

    # ---- playback + jaw -------------------------------------------------
    def say(self, text: str) -> bool:
        """Speak text, blocking until done. Returns False if interrupted or failed."""
        text = text.strip()
        if not text:
            return True
        with self._lock:
            self._stop.clear()
            try:
                return self._say(text)
            except Exception as e:
                log.error("Speech failed: %s", e)
                return False
            finally:
                self.speaking = False
                self.on_jaw(0)
                self.on_state(False)

    def _say(self, text: str) -> bool:
        c = self.cfg
        gain = float(c.get("volume", 1.0))
        chunks = self._pcm_chunks(text)
        sr, _ = next(chunks)
        block = int(sr * 0.02)                 # 20 ms blocks
        buf = bytearray()
        buf_lock = threading.Lock()
        done_receiving = threading.Event()
        finished = threading.Event()
        jaw_queue: deque[tuple[float, float]] = deque()
        env = {"level": 0.0}
        floor_db, ceil_db = c.get("jaw_floor_db", -42), c.get("jaw_ceiling_db", -12)
        attack, release = c.get("jaw_attack", 0.6), c.get("jaw_release", 0.45)
        max_open = c.get("jaw_max_open", 100)
        offset = c.get("jaw_delay_s", 0.0)

        def receive():
            try:
                for _, chunk in chunks:
                    if chunk:
                        with buf_lock:
                            buf.extend(chunk)
            finally:
                done_receiving.set()
        threading.Thread(target=receive, daemon=True).start()

        # Pre-buffer ~150 ms so network hiccups do not stutter the start.
        t0 = time.monotonic()
        while len(buf) < sr * 2 * 0.15 and not done_receiving.is_set():
            if time.monotonic() - t0 > 10 or self._stop.is_set():
                return False
            time.sleep(0.005)

        def callback(outdata, frames, t, status):
            need = frames * 2
            with buf_lock:
                data = bytes(buf[:need])
                del buf[:need]
            if len(data) < need:
                if done_receiving.is_set() and not buf:
                    finished.set()
                data += b"\x00" * (need - len(data))
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            if gain != 1.0:
                samples = np.clip(samples * gain, -32768, 32767)
            outdata[:] = samples.astype(np.int16).tobytes()

            rms = math.sqrt(float(np.mean((samples / 32768.0) ** 2)) + 1e-12)
            db = 20 * math.log10(rms)
            target = min(1.0, max(0.0, (db - floor_db) / (ceil_db - floor_db)))
            k = attack if target > env["level"] else release
            env["level"] += (target - env["level"]) * k
            delay = max(0.0, t.outputBufferDacTime - t.currentTime) + offset
            jaw_queue.append((time.monotonic() + delay, env["level"] * max_open))

        self.speaking = True
        self.on_state(True)
        with sd.RawOutputStream(samplerate=sr, channels=1, dtype="int16",
                                blocksize=block, device=self.device, callback=callback):
            while not finished.is_set():
                if self._stop.is_set():
                    break
                now = time.monotonic()
                while jaw_queue and jaw_queue[0][0] <= now:
                    self.on_jaw(jaw_queue.popleft()[1])
                time.sleep(0.005)
            # let the last buffered audio drain
            end = time.monotonic() + 0.3
            while time.monotonic() < end and not self._stop.is_set():
                while jaw_queue and jaw_queue[0][0] <= time.monotonic():
                    self.on_jaw(jaw_queue.popleft()[1])
                time.sleep(0.005)
        return not self._stop.is_set()


# --------------------------------------------------------------------------
# Ears
# --------------------------------------------------------------------------

class Ears:
    RATE = 16000

    def __init__(self, api_key: str, cfg: dict):
        self.key = api_key
        self.cfg = cfg
        self.device = find_device(cfg.get("input_device"), "input")

    def listen(self, wait_s: float, max_s: float, cancel: threading.Event | None = None
               ) -> bytes | None:
        """Record one utterance. Returns WAV bytes, or None if nobody spoke."""
        c = self.cfg
        block = int(self.RATE * 0.03)
        silence_end = c.get("end_of_speech_silence_s", 0.9)
        min_rms = c.get("speech_min_rms", 0.012)
        frames: list[np.ndarray] = []
        pre_roll: deque[np.ndarray] = deque(maxlen=10)   # keep 0.3 s before speech
        noise = []
        started = False
        quiet_for = 0.0
        t_start = time.monotonic()

        with sd.InputStream(samplerate=self.RATE, channels=1, dtype="float32",
                            blocksize=block, device=self.device) as stream:
            while True:
                if cancel is not None and cancel.is_set():
                    return None
                data, _ = stream.read(block)
                x = data[:, 0].copy()
                rms = float(np.sqrt(np.mean(x ** 2)))
                elapsed = time.monotonic() - t_start
                if len(noise) < 10:                       # first 0.3 s = room noise
                    noise.append(rms)
                    continue
                threshold = max(min_rms, float(np.median(noise)) * 3.0)
                if not started:
                    pre_roll.append(x)
                    if rms > threshold:
                        started = True
                        frames.extend(pre_roll)
                    elif elapsed > wait_s:
                        return None
                else:
                    frames.append(x)
                    quiet_for = quiet_for + 0.03 if rms < threshold else 0.0
                    if quiet_for >= silence_end or elapsed > wait_s + max_s:
                        break

        audio = np.concatenate(frames)
        if len(audio) < self.RATE * 0.4:
            return None
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.RATE)
            w.writeframes(pcm.tobytes())
        return out.getvalue()

    def transcribe(self, wav: bytes) -> str:
        r = requests.post(
            f"{API}/speech-to-text",
            headers={"xi-api-key": self.key},
            data={"model_id": self.cfg.get("stt_model", "scribe_v1"),
                  "language_code": "en", "tag_audio_events": "false"},
            files={"file": ("speech.wav", wav, "audio/wav")},
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs STT {r.status_code}: {r.text[:300]}")
        return (r.json().get("text") or "").strip()
