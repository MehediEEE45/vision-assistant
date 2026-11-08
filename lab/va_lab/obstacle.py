"""Obstacle policy: a Python port of firmware/stm32h743/src/obstacle_policy.cpp,
itself a port of the app's ObstaclePolicy.kt. Same bands, confirmation,
hysteresis, re-announce intervals and standing-still silence.

On the laptop the "sensor" is the camera: each frame gives, per zone, the
nearest recognised object's approximate distance. Anything the detector does
not know is invisible to it, which is why the wearable uses a laser.
"""

from dataclasses import dataclass

from . import config

ZONES = ("left", "ahead", "right")
BANDS = ("immediate", "near", "approaching", "clear")


@dataclass
class Alert:
    zone: str
    band: str
    mm: int


class _Zone:
    def __init__(self):
        self.current = "clear"
        self.candidate = "clear"
        self.frames = 0
        self.announced = False
        self.last_ms = 0
        self.anchor_mm = 0
        self.anchor_ms = 0


class ObstaclePolicy:
    def __init__(self):
        self.reset()

    def reset(self):
        self.zones = {z: _Zone() for z in ZONES}
        self.any_alert = False
        self.last_alert_ms = 0
        self.last_alert_band = "clear"

    def _band(self, z, mm):
        def edge(band, base):
            return base + (config.OBST_HYSTERESIS_MM if z.current == band else 0)
        if mm <= edge("immediate", config.OBST_IMMEDIATE_MM):
            return "immediate"
        if mm <= edge("near", config.OBST_NEAR_MM):
            return "near"
        if mm <= edge("approaching", config.OBST_APPROACHING_MM):
            return "approaching"
        return "clear"

    def on_sample(self, zone, mm, now_ms):
        """mm is None when nothing is in that zone. Returns an Alert or None."""
        z = self.zones[zone]
        band = self._band(z, mm) if mm is not None else "clear"
        if band == "clear":
            z.current = z.candidate = "clear"
            z.frames = 0
            return None
        if z.candidate != band:
            z.candidate, z.frames = band, 1
            return None
        z.frames += 1
        if z.frames < config.OBST_FRAMES_TO_CONFIRM:
            return None

        if z.anchor_ms == 0 or abs(mm - z.anchor_mm) > config.OBST_STATIC_SCENE_MM:
            z.anchor_mm, z.anchor_ms = mm, now_ms
        standing_still = now_ms - z.anchor_ms >= config.OBST_STATIC_SCENE_MS

        escalating = BANDS.index(band) < BANDS.index(z.current)
        quiet = not z.announced or now_ms - z.last_ms >= config.OBST_REANNOUNCE_MS[band]
        if not escalating and (not quiet or standing_still):
            return None

        if (self.any_alert and now_ms - self.last_alert_ms < config.OBST_CROSS_ZONE_MS
                and BANDS.index(band) >= BANDS.index(self.last_alert_band)):
            z.current, z.announced, z.last_ms = band, True, now_ms
            return None

        z.current, z.announced, z.last_ms = band, True, now_ms
        self.any_alert, self.last_alert_ms, self.last_alert_band = True, now_ms, band
        return Alert(zone, band, int(mm))


def zone_of(angle_deg):
    if abs(angle_deg) <= config.OBST_AHEAD_DEG:
        return "ahead"
    return "left" if angle_deg < 0 else "right"


def nearest_per_zone(detections):
    """{zone: mm or None} from one frame's detections."""
    out = {z: None for z in ZONES}
    for d in detections:
        z = zone_of(d.angle_deg)
        mm = int(d.distance_m * 1000)
        if out[z] is None or mm < out[z]:
            out[z] = mm
    return out
