"""
Short-term memory for faces, so the skull does not greet the same person twice.

YOLO track IDs only last while someone stays in frame. This keeps a face
embedding for each person greeted and matches new arrivals against it.
Embeddings live in memory only. They are dropped after `regreet_same_person_after_s`
and when the program exits. Nothing is written to disk and no names are kept.

Models: OpenCV's YuNet (detector) and SFace (embedding), downloaded on first use.
"""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("skull.faces")

ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models/"
MODELS = {
    "detector": "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "embedder": "face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
MIN_CROP = 480      # small crops are scaled up to this height before detection
MAX_SAMPLES = 8     # embeddings kept per person
MAX_YAW = 0.35      # nose offset from the midpoint of the eyes, in eye distances


def _model(model_dir: Path, key: str) -> str:
    path = model_dir / Path(MODELS[key]).name
    if not path.is_file():
        model_dir.mkdir(parents=True, exist_ok=True)
        log.info("Downloading %s", path.name)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(ZOO + MODELS[key], tmp)
        tmp.rename(path)
    return str(path)


class FaceMemory:
    def __init__(self, model_dir: Path, window_s: float, threshold: float = 0.363,
                 min_score: float = 0.9):
        self.window_s, self.threshold = window_s, threshold
        self.detector = cv2.FaceDetectorYN.create(_model(model_dir, "detector"), "",
                                                  (320, 320), min_score)
        self.embedder = cv2.FaceRecognizerSF.create(_model(model_dir, "embedder"), "")
        self.people: list[dict] = []       # {"t": greeted at (monotonic), "samples": [embedding]}

    def look(self, frame, box) -> np.ndarray | None:
        """Embedding of the face inside a person's box, or None unless it is a clear,
        front-on face. So a result also means the person is looking at the skull."""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = (int(v) for v in box)
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 - x1 < 20 or y2 - y1 < 20:
            return None
        crop = frame[y1:y2, x1:x2]
        if crop.shape[0] < MIN_CROP:
            k = MIN_CROP / crop.shape[0]
            crop = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        self.detector.setInputSize((crop.shape[1], crop.shape[0]))
        _, found = self.detector.detect(crop)
        if found is None or not len(found):
            return None
        face = max(found, key=lambda f: f[2] * f[3])      # the largest face
        right_eye, left_eye, nose = face[4:6], face[6:8], face[8:10]
        eyes = float(np.linalg.norm(right_eye - left_eye))
        if eyes < 1 or abs(nose[0] - (right_eye[0] + left_eye[0]) / 2) / eyes > MAX_YAW:
            return None                                   # turned away: a poor sample
        return self.embedder.feature(self.embedder.alignCrop(crop, face)).copy()

    def _forget_old(self, now: float):
        self.people = [p for p in self.people if now - p["t"] <= self.window_s]

    def find(self, emb: np.ndarray, now: float) -> dict | None:
        """The remembered person this face belongs to, or None if it is new (or forgotten).
        `person["t"]` is when the skull last spoke to them."""
        self._forget_old(now)
        best, who = 0.0, None
        for p in self.people:
            score = max(self.embedder.match(emb, s, cv2.FaceRecognizerSF_FR_COSINE)
                        for s in p["samples"])
            if score > best:
                best, who = score, p
        if who is None or best < self.threshold:
            return None
        self.add(who, emb)                        # another look at them helps next time
        return who

    def add(self, person: dict, emb: np.ndarray):
        if len(person["samples"]) < MAX_SAMPLES:
            person["samples"].append(emb)

    def remember(self, embs: list, now: float) -> dict | None:
        """Record that the skull spoke to the person these looks belong to."""
        person = None
        for emb in embs:
            if person is None:
                person = self.find(emb, now)
            else:
                self.add(person, emb)
        if person is None and embs:
            person = {"t": now, "samples": list(embs[:MAX_SAMPLES])}
            self.people.append(person)
        if person is not None:
            person["t"] = now
        return person
