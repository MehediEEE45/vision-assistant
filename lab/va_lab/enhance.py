"""Low-light help for a cheap webcam.

The test frames from this laptop were underexposed, and detection drops
sharply in that state. Dim frames get local contrast enhancement (CLAHE on
lightness) and a gamma lift before any model sees them, and very dark ones
are reported as such rather than as "nothing found".
"""

import cv2
import numpy as np

DIM = 90      # mean grey below this: enhance
DARK = 45     # below this: tell the user the light is low

_clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
_gamma = np.array([((i / 255.0) ** 0.7) * 255 for i in range(256)], np.uint8)


def brightness(frame):
    small = cv2.resize(frame, (80, 60), interpolation=cv2.INTER_AREA)
    return float(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean())


def enhance(frame):
    """(frame for the models, is_dark)."""
    b = brightness(frame)
    if b >= DIM:
        return frame, False
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lab[..., 0] = _clahe.apply(lab[..., 0])
    out = cv2.LUT(cv2.cvtColor(lab, cv2.COLOR_LAB2BGR), _gamma)
    return out, b < DARK


def sharpness(gray):
    """Variance of the Laplacian: low means motion blur or out of focus."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())
