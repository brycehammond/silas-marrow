"""
Camera + person tracking.

Uses a YOLO pose model so we get a nose/eye keypoint for each person, which
is exactly where the skull should look. Falls back to the top of the person's
box when the face is not visible.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np
import torch
from ultralytics import YOLO

log = logging.getLogger("skull.vision")

ROTATIONS = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
             270: cv2.ROTATE_90_COUNTERCLOCKWISE}


@dataclass
class Person:
    track_id: int
    box: tuple[int, int, int, int]      # pixels x1, y1, x2, y2
    head: tuple[float, float]           # normalized 0..1 in the frame
    height_frac: float                  # box height / frame height (closeness)
    face_visible: bool


class Camera:
    """Grabs frames on its own thread so inference always sees the newest one."""

    def __init__(self, index: int, width: int, height: int, rotate: int = 0,
                 mirror: bool = False):
        self.index, self.width, self.height = index, width, height
        self.rotate, self.mirror = rotate, mirror
        self._frame = None
        self._lock = threading.Lock()
        self._cap = None
        self.fps = 0.0

    def _open(self):
        cap = cv2.VideoCapture(self.index, cv2.CAP_AVFOUNDATION)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        return cap

    def start(self):
        self._cap = self._open()
        if not self._cap.isOpened():
            raise SystemExit(
                "Could not open the camera. Run `python skull.py --list-cameras`, "
                "set camera_index in config.json, and allow camera access for your "
                "terminal in System Settings > Privacy & Security > Camera.")
        threading.Thread(target=self._run, daemon=True, name="camera").start()

    def _run(self):
        fails, n, t0 = 0, 0, time.monotonic()
        while True:
            ok, frame = self._cap.read()
            if not ok:
                fails += 1
                if fails > 50:
                    log.warning("Camera stopped responding, reopening")
                    self._cap.release()
                    time.sleep(1)
                    self._cap = self._open()
                    fails = 0
                time.sleep(0.02)
                continue
            fails = 0
            if self.rotate in ROTATIONS:
                frame = cv2.rotate(frame, ROTATIONS[self.rotate])
            if self.mirror:
                frame = cv2.flip(frame, 1)
            with self._lock:
                self._frame = frame
            n += 1
            if n % 30 == 0:
                now = time.monotonic()
                self.fps = 30 / (now - t0)
                t0 = now

    def latest(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()


class Tracker:
    NOSE, LEFT_EYE, RIGHT_EYE = 0, 1, 2

    def __init__(self, model: str = "yolo11n-pose.pt", confidence: float = 0.5):
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = YOLO(model)
        self.conf = confidence
        log.info("Pose tracker on %s", self.device)

    def people(self, frame) -> list[Person]:
        h, w = frame.shape[:2]
        r = self.model.track(frame, persist=True, conf=self.conf, device=self.device,
                             imgsz=640, verbose=False, tracker="bytetrack.yaml")[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []
        boxes = r.boxes.xyxy.cpu().numpy()
        ids = (r.boxes.id.cpu().numpy().astype(int) if r.boxes.id is not None
               else np.arange(len(boxes)) * -1 - 1)
        kps = r.keypoints.data.cpu().numpy() if r.keypoints is not None else None

        out = []
        for i, (x1, y1, x2, y2) in enumerate(boxes):
            face = False
            hx, hy = (x1 + x2) / 2, y1 + 0.12 * (y2 - y1)   # top of box fallback
            if kps is not None:
                pts = kps[i]
                facial = [pts[j] for j in (self.NOSE, self.LEFT_EYE, self.RIGHT_EYE)
                          if pts[j][2] > 0.5]
                if facial:
                    hx = float(np.mean([p[0] for p in facial]))
                    hy = float(np.mean([p[1] for p in facial]))
                    face = True
            out.append(Person(
                track_id=int(ids[i]),
                box=(int(x1), int(y1), int(x2), int(y2)),
                head=(hx / w, hy / h),
                height_frac=(y2 - y1) / h,
                face_visible=face,
            ))
        return out


def pick_target(people: list[Person], current_id: int | None) -> Person | None:
    """Stick with whoever we are already looking at; otherwise the closest person."""
    if not people:
        return None
    for p in people:
        if p.track_id == current_id:
            return p
    return max(people, key=lambda p: p.height_frac)


def head_to_look(head: tuple[float, float], cfg: dict) -> tuple[float, float]:
    """
    Turn a head position in the camera frame into pan/tilt percentages.

    The camera is fixed in the base, so this is simple geometry: the offset
    from frame center times the camera's field of view gives an angle, and
    the firmware maps -100..100 percent onto the calibrated servo range.
    """
    hfov, vfov = cfg["camera_hfov_deg"], cfg["camera_vfov_deg"]
    pan_deg = (head[0] - 0.5) * hfov
    tilt_deg = (0.5 - head[1]) * vfov + cfg["tilt_offset_deg"]
    if cfg.get("invert_pan"):
        pan_deg = -pan_deg
    if cfg.get("invert_tilt"):
        tilt_deg = -tilt_deg
    pan = pan_deg / cfg["pan_range_deg"] * 100
    tilt = tilt_deg / cfg["tilt_range_deg"] * 100
    return max(-100, min(100, pan)), max(-100, min(100, tilt))


def draw_overlay(frame, people: list[Person], target: Person | None, status: str):
    h, w = frame.shape[:2]
    for p in people:
        color = (0, 0, 255) if target and p.track_id == target.track_id else (0, 200, 0)
        cv2.rectangle(frame, p.box[:2], p.box[2:], color, 2)
        cv2.circle(frame, (int(p.head[0] * w), int(p.head[1] * h)), 7, (255, 0, 255), -1)
        cv2.putText(frame, f"#{p.track_id}", (p.box[0], p.box[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    cv2.rectangle(frame, (0, 0), (w, 32), (0, 0, 0), -1)
    cv2.putText(frame, status, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                (200, 200, 255), 2)
    return frame
