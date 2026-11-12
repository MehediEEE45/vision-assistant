"""Reading printed text, offline: EasyOCR (Bengali + English).

Offline Bangla OCR is mediocre: about 91% of characters and 78% of words
right on a published Bengali document benchmark. The user is told so, and
the work goes into getting a good picture first (`check`), which matters
more than the engine.
"""

import re

import cv2
import numpy as np

from . import config, enhance
from .platform_support import torch_device

MODEL_DIR = config.MODELS / "easyocr"
_SPLIT = re.compile(r"(?<=[.!?।])\s+")


class OCR:
    def __init__(self):
        import easyocr
        import torch
        device = torch_device()
        self.reader = easyocr.Reader(["bn", "en"], gpu=False if device == "cpu" else device,
                                     model_storage_directory=str(MODEL_DIR), verbose=False)
        # The Bengali recognizer covers Latin too, but confuses capital I/L/!
        # on English pages. Reuse its boxes and refine uncertain Latin lines
        # with the English recognizer; Bengali and mixed-script lines stay here.
        self.english = easyocr.Reader(["en"], gpu=False if device == "cpu" else device,
                                     model_storage_directory=str(MODEL_DIR), detector=False, verbose=False)

    def boxes(self, frame, width=640):
        """Fast text-box detection only, for aiming. [(x1, y1, x2, y2)] in frame pixels."""
        h, w = frame.shape[:2]
        scale = width / w if w > width else 1.0
        small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale != 1.0 else frame
        horiz, _ = self.reader.detect(small, min_size=8)
        out = []
        for x1, x2, y1, y2 in (horiz[0] if horiz else []):
            out.append((x1 / scale, y1 / scale, x2 / scale, y2 / scale))
        return out

    def read(self, image):
        """[(x1, y1, x2, y2), text, confidence] for every text line found."""
        from .understand import gpu_job
        with gpu_job:
            res = self.reader.readtext(image, paragraph=False)
        out = []
        for pts, text, conf in res:
            pts = np.asarray(pts)
            if conf < 0.95 and not any("ঀ" <= c <= "৿" for c in text) and any(c.isascii() and c.isalpha() for c in text):
                x1, y1 = np.maximum(0, np.floor(pts.min(axis=0)).astype(int) - 2)
                x2, y2 = np.minimum((image.shape[1], image.shape[0]), np.ceil(pts.max(axis=0)).astype(int) + 2)
                crop = image[y1:y2, x1:x2]
                if crop.size:
                    with gpu_job:
                        candidates = self.english.recognize(crop, detail=1, paragraph=False)
                    if candidates:
                        _, english, score = max(candidates, key=lambda r: r[2])
                        if english.strip() and score > conf:
                            text, conf = english, score
            out.append(((float(pts[:, 0].min()), float(pts[:, 1].min()),
                         float(pts[:, 0].max()), float(pts[:, 1].max())), text.strip(), float(conf)))
        return [r for r in out if r[1]]


def check(frame, boxes, faces_user=None):
    """None when the picture is good to read, else a phrase key saying what to fix."""
    faces_user = config.CAMERA_FACES_USER if faces_user is None else faces_user
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if gray.mean() < enhance.DARK:
        return "cap_dark"
    if not boxes:
        return "cap_no_text"
    b = np.array(boxes)
    x1, y1, x2, y2 = b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max()
    m = 0.02
    cut_l, cut_r = x1 <= m * w, x2 >= (1 - m) * w
    cut_t, cut_b = y1 <= m * h, y2 >= (1 - m) * h
    if (cut_l and cut_r) or (cut_t and cut_b):
        return "cap_farther"
    # Text cut off at the picture's left edge means the page must move towards
    # the picture's right. For a camera facing the user, that is the user's left.
    if cut_l or cut_r:
        towards_image_right = cut_l
        return "cap_move_left" if towards_image_right == faces_user else "cap_move_right"
    if cut_t:
        return "cap_move_down"
    if cut_b:
        return "cap_move_up"
    if np.median(b[:, 3] - b[:, 1]) < 0.025 * h:
        return "cap_closer"
    region = gray[int(y1):int(y2), int(x1):int(x2)]
    if region.size and enhance.sharpness(region) < 60:
        return "cap_steady"
    return None


def reading_order(results):
    """Paragraphs (strings) in reading order: columns left to right, lines top
    to bottom, words left to right. Two-column pages are not read across."""
    if not results:
        return []
    boxes = np.array([r[0] for r in results])
    hmed = float(np.median(boxes[:, 3] - boxes[:, 1])) or 10.0

    # Columns: split where no box covers a vertical strip wider than 2.5 lines.
    xs = sorted((b[0], b[2]) for b in boxes)
    cols, cur_end, starts = [], xs[0][1], [xs[0][0]]
    for a, b in xs[1:]:
        if a - cur_end > 2.5 * hmed:
            cols.append((starts[-1], cur_end))
            starts.append(a)
        cur_end = max(cur_end, b)
    cols.append((starts[-1], cur_end))

    paragraphs = []
    for c0, c1 in cols:
        col = [r for r in results if c0 - 1 <= (r[0][0] + r[0][2]) / 2 <= c1 + 1]
        col.sort(key=lambda r: (r[0][1] + r[0][3]) / 2)
        lines, line = [], []
        for r in col:
            yc = (r[0][1] + r[0][3]) / 2
            if line and abs(yc - np.mean([(q[0][1] + q[0][3]) / 2 for q in line])) > 0.6 * hmed:
                lines.append(line)
                line = []
            line.append(r)
        if line:
            lines.append(line)
        para, last_bottom = [], None
        for ln in lines:
            ln.sort(key=lambda r: r[0][0])
            top = min(r[0][1] for r in ln)
            if para and last_bottom is not None and top - last_bottom > 1.2 * hmed:
                paragraphs.append(" ".join(para))
                para = []
            para.append(" ".join(r[1] for r in ln))
            last_bottom = max(r[0][3] for r in ln)
        if para:
            paragraphs.append(" ".join(para))
    return [p for p in paragraphs if p.strip()]


def sentences(paragraph):
    """Split on . ? ! and the Bangla danda. Without the danda a whole Bangla
    paragraph is one sentence, and every interruption restarts it."""
    return [s.strip() for s in _SPLIT.split(paragraph) if s.strip()]
