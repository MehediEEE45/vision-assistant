"""Object detection on the webcam picture, with direction and approximate distance.

Default model: YOLO-World (open vocabulary). It is told the eight object
names, so door, rickshaw and CNG work without collecting a dataset.
Fallbacks: a model trained in notebook 04, or plain COCO YOLOv8n (5 of 8).

Distance from a camera alone is an estimate: pixel height of the box against
a typical real height (config.OBJECT_HEIGHT_M). The wearable measures it with
its laser instead; here it is labelled approximate everywhere it is shown.
"""

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config


@dataclass
class Detection:
    obj: str
    score: float
    box: tuple          # x1, y1, x2, y2 in pixels
    cx: float           # 0 = left edge, 1 = right edge
    angle_deg: float    # negative = the wearer's left
    distance_m: float   # approximate
    clipped: bool       # box touches an edge: the object is closer or bigger than estimated
    track: int = -1     # stable identity across frames (Stabiliser)


def focal_px(width_px, hfov_deg=config.CAMERA_HFOV_DEG):
    return (width_px / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)


def angle_deg(cx, hfov_deg=config.CAMERA_HFOV_DEG, faces_user=None):
    """Degrees from straight ahead, negative = the user's left.

    A camera turned towards the user sees the world mirrored: its left edge is
    the user's right."""
    faces_user = config.CAMERA_FACES_USER if faces_user is None else faces_user
    a = math.degrees(math.atan((cx - 0.5) * 2.0 * math.tan(math.radians(hfov_deg) / 2.0)))
    return -a if faces_user else a


class Detector:
    def __init__(self, mode="world", weights=None, device=None, conf=config.DETECT_CONFIDENCE,
                 hfov_deg=config.CAMERA_HFOV_DEG):
        from ultralytics import YOLO
        import torch

        self.device = device or (0 if torch.cuda.is_available() else "cpu")
        self.conf = conf
        self.hfov = hfov_deg
        self.mode = mode
        config.MODELS.mkdir(parents=True, exist_ok=True)

        if mode == "world":
            path = Path(weights) if weights else config.MODELS / "yolov8s-worldv2.pt"
            self.model = YOLO(str(path))
            self.queries, self.query_obj = [], []
            for obj in config.OBJECTS:
                for q in config.OBJECT_QUERIES[obj]:
                    self.queries.append(q)
                    self.query_obj.append(obj)
            self.model.set_classes(self.queries)
            self.names = {i: self.query_obj[i] for i in range(len(self.queries))}
        elif mode == "coco":
            path = Path(weights) if weights else config.MODELS / "yolov8n.pt"
            self.model = YOLO(str(path))
            self.names = {i: config.COCO_TO_OBJECT.get(n) for i, n in self.model.names.items()}
        elif mode == "custom":
            self.model = YOLO(str(weights or config.MODELS / "objects_custom.pt"))
            self.names = {i: (n if n in config.OBJECTS else None) for i, n in self.model.names.items()}
        else:
            raise ValueError("mode must be world, coco or custom")

    def set_queries(self, queries, label):
        """Find mode: look for exactly these words (YOLO-World only)."""
        if self.mode != "world":
            return False
        self.model.set_classes(list(queries))
        self.names = {i: label for i in range(len(queries))}
        self._custom = True
        return True

    def restore(self):
        if getattr(self, "_custom", False):
            self.model.set_classes(self.queries)
            self.names = {i: self.query_obj[i] for i in range(len(self.queries))}
            self._custom = False

    @property
    def supported(self):
        return sorted({n for n in self.names.values() if n})

    def detect(self, frame_bgr, min_score=config.VISION_MIN_CONFIDENCE):
        h, w = frame_bgr.shape[:2]
        f = focal_px(w, self.hfov)
        # 480 px, full precision: 15 ms on the GTX 1650. Half precision is
        # three times slower on this card (42 ms), measured, so it stays off.
        r = self.model.predict(frame_bgr, conf=self.conf, device=self.device, imgsz=config.DETECT_IMGSZ,
                               half=False, verbose=False)[0]
        out = []
        if r.boxes is None:
            return out
        xyxy = r.boxes.xyxy.cpu().numpy()
        cls = r.boxes.cls.cpu().numpy().astype(int)
        scores = r.boxes.conf.cpu().numpy()
        for (x1, y1, x2, y2), c, s in zip(xyxy, cls, scores):
            obj = self.names.get(int(c))
            if obj is None or s < min_score:
                continue
            h_m = config.OBJECT_HEIGHT_M.get(obj, 1.0)
            w_m = config.OBJECT_WIDTH_M.get(obj, 0.5)
            cx = (x1 + x2) / 2.0 / w
            dist = h_m * f / max(1.0, y2 - y1)
            cut_v = y1 <= 0.02 * h or y2 >= 0.98 * h
            cut_h = x1 <= 0.02 * w or x2 >= 0.98 * w
            # A partial box (a chair's backrest, a person cut at the waist)
            # makes the height estimate too far; the width one is the check.
            if not cut_h:
                dist = min(dist, w_m * f / max(1.0, x2 - x1))
            out.append(Detection(obj, float(s), (float(x1), float(y1), float(x2), float(y2)), float(cx),
                                 angle_deg(cx, self.hfov), float(dist), bool(cut_v or cut_h)))
        # One per object per place: several queries ("table", "desk") can
        # find the same thing.
        out.sort(key=lambda d: -d.score)
        kept = []
        for d in out:
            if not any(k.obj == d.obj and _iou(k.box, d.box) > 0.5 for k in kept):
                kept.append(d)
        return kept


class Stabiliser:
    """Keeps an object only once it has been seen in STABLE_HITS of the last
    STABLE_WINDOW frames, and gives it a track number that survives frames.

    Matching is by object kind and box overlap: enough for a handful of
    objects at walking pace, with no extra dependency."""

    def __init__(self, hits=config.STABLE_HITS, window=config.STABLE_WINDOW):
        self.hits, self.window = hits, window
        self.tracks = []   # dicts: id, obj, box, seen (list of bools), det
        self._next = 1

    def update(self, detections):
        for t in self.tracks:
            t["matched"] = False
        for d in sorted(detections, key=lambda d: -d.score):
            best, best_iou = None, 0.3
            for t in self.tracks:
                if t["obj"] == d.obj and not t["matched"]:
                    iou = _iou(t["box"], d.box)
                    if iou > best_iou:
                        best, best_iou = t, iou
            if best is None:
                best = {"id": self._next, "obj": d.obj, "seen": []}
                self._next += 1
                self.tracks.append(best)
            best.update(box=d.box, det=d, matched=True)
        for t in self.tracks:
            t["seen"] = (t["seen"] + [t["matched"]])[-self.window:]
        self.tracks = [t for t in self.tracks if any(t["seen"])]
        out = []
        for t in self.tracks:
            if t["matched"] and sum(t["seen"]) >= self.hits:
                t["det"].track = t["id"]
                out.append(t["det"])
        return out

    def reset(self):
        self.tracks = []


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def open_camera(index=config.CAMERA_INDEX, width=config.CAMERA_WIDTH, height=config.CAMERA_HEIGHT):
    import cv2

    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if not cap.isOpened():
        raise RuntimeError(f"camera {index} did not open: is another program using it?")
    return cap


def grab(cap, warmup=5):
    """One frame, after letting exposure settle."""
    frame = None
    for _ in range(warmup):
        ok, frame = cap.read()
    if frame is None:
        raise RuntimeError("no frame from the camera")
    return frame
