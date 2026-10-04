"""
The skull's brain: Claude writes what the ghost says.

greet()  looks at a camera frame and writes an opening line.
reply()  continues a short conversation with whoever is standing there.
"""

from __future__ import annotations

import base64
import datetime as dt
import logging
import re
from collections import deque
from pathlib import Path

import anthropic
import cv2

log = logging.getLogger("skull.brain")


def frame_to_jpeg_b64(frame, max_side: int = 768) -> str:
    h, w = frame.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return base64.b64encode(jpg.tobytes()).decode()


def clean_line(text: str, allow_tags: bool) -> str:
    text = re.sub(r"\*[^*]*\*", "", text)           # *stage directions*
    if not allow_tags:
        text = re.sub(r"\[[^\]]*\]", "", text)      # [laughs] etc.
    text = text.replace("\u2014", ", ").replace("\u2013", ", ")
    text = text.strip().strip('"').strip()
    return re.sub(r"\s+", " ", text)


class Brain:
    def __init__(self, cfg: dict, persona_path: Path):
        self.cfg = cfg
        self.client = anthropic.Anthropic()          # reads ANTHROPIC_API_KEY
        self.persona = persona_path.read_text()
        self.recent: deque[str] = deque(maxlen=cfg.get("remember_last_lines", 12))
        self.history: list[dict] = []

    # ---- helpers -----------------------------------------------------------
    def _system(self) -> str:
        now = dt.datetime.now()
        part = ("morning" if now.hour < 12 else "afternoon" if now.hour < 17
                else "evening")
        extra = [f"Right now it is {now:%A} {part}, {now:%B %-d}."]
        if self.cfg.get("allow_audio_tags"):
            extra.append("You may add at most one ElevenLabs audio tag such as "
                         "[chuckles], [whispers], [sighs] or [cackles].")
        if self.recent:
            extra.append("Lines you have already said today (do not repeat them "
                         "or their jokes):\n" + "\n".join(f"- {l}" for l in self.recent))
        return self.persona + "\n\n## Right now\n\n" + "\n".join(extra)

    def _ask(self, messages: list[dict], max_tokens: int) -> str:
        extra = {}
        if self.cfg.get("thinking"):      # e.g. "between_tools" keeps Sonnet 5.5 from thinking first
            extra["thinking"] = {"type": self.cfg["thinking"]}
        r = self.client.messages.create(
            model=self.cfg["model"],
            max_tokens=max_tokens,
            system=self._system(),
            messages=messages,
            **extra,
        )
        text = "".join(b.text for b in r.content if b.type == "text")
        return clean_line(text, self.cfg.get("allow_audio_tags", False))

    # ---- public ------------------------------------------------------------
    def reset(self):
        self.history = []

    def greet(self, frame, note: str = "") -> str:
        prompt = ("Someone just walked through the front door and is looking at you. "
                  "This is what you see. Greet them in character. "
                  "Say only your spoken line.")
        if note:
            prompt += f" Context: {note}"
        user = {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": frame_to_jpeg_b64(frame)}},
            {"type": "text", "text": prompt},
        ]}
        line = self._ask([user], self.cfg.get("max_tokens", 150))
        self.history = [user, {"role": "assistant", "content": line}]
        self.recent.append(line)
        return line

    def reply(self, heard: str) -> str:
        self.history.append({"role": "user", "content":
                             f"(The person says:) {heard}\n"
                             "Reply in character, spoken line only."})
        line = self._ask(self.history, self.cfg.get("max_tokens", 150))
        self.history.append({"role": "assistant", "content": line})
        self.recent.append(line)
        return line

    def farewell(self) -> str:
        return self.reply("(They are walking away without saying anything.) "
                          "Say a very short parting line.")

    def ambient(self) -> str:
        """A line for when nobody is around but someone might be within earshot."""
        line = self._ask([{"role": "user", "content":
                           "Nobody is at the door. Mutter one short line to yourself "
                           "about the building's history or modern office life."}],
                         80)
        self.recent.append(line)
        return line
