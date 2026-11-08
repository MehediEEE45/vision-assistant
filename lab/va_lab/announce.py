"""What the assistant says: firmware/stm32h743/src/announce.cpp, in Python.

Every sentence reports an observation and its limit. None may say that a
way is safe or clear (spine/safety-policy/banned-phrases.txt), and an object
not found is "not found", never "not there".
"""

from . import config
from .speech import ANSWER, HAZARD, MANEUVER, Utterance

VERY_CLOSE_MM = 400
DIST_STEPS = ["DIST_0_5", "DIST_1_0", "DIST_1_5", "DIST_2_0", "DIST_2_5", "DIST_3_0", "DIST_3_5", "DIST_4_0"]
ZONE_WORD = {"left": "ZONE_LEFT", "ahead": "ZONE_AHEAD", "right": "ZONE_RIGHT"}
OBST_WORD = {"left": "OBST_LEFT", "ahead": "OBST_AHEAD", "right": "OBST_RIGHT"}


def obj_prompt(obj):
    return "OBJ_" + obj.upper()


def distance_prompt(mm):
    if mm < 750:
        return "DIST_0_5"
    return DIST_STEPS[min(7, (int(mm) - 250) // 500)]


def distance_items(mm):
    return ["VERY_CLOSE"] if mm < VERY_CLOSE_MM else [distance_prompt(mm)]


def obstacle(alert):
    if alert.band == "immediate":
        return Utterance(HAZARD, [("tone", "warn"), OBST_WORD[alert.zone]], tag="obstacle")
    p = MANEUVER if alert.band == "approaching" else HAZARD
    return Utterance(p, [OBST_WORD[alert.zone], distance_prompt(alert.mm)], tag="obstacle")


def describe(detections, max_objects=3):
    items, seen = [], set()
    for d in sorted(detections, key=lambda d: -d.score):
        if d.obj in seen or len(seen) >= max_objects:
            continue
        seen.add(d.obj)
        items.append(obj_prompt(d.obj))
        if abs(d.angle_deg) > config.FIND_AHEAD_DEG:
            items.append("ZONE_LEFT" if d.angle_deg < 0 else "ZONE_RIGHT")
        else:
            items += ["ZONE_AHEAD"] + distance_items(d.distance_m * 1000)
    if not items:
        items = ["NOTHING_RECOGNISED"]
    return Utterance(ANSWER, items, tag="report")


def search_started(obj, bangla_order):
    head = [obj_prompt(obj), "SEARCHING_FOR"] if bangla_order else ["SEARCHING_FOR", obj_prompt(obj)]
    return Utterance(ANSWER, head + ["TURN_SLOWLY"], tag="search")


def search_guidance(obj, side, mm=None):
    items = [obj_prompt(obj), {-1: "ZONE_LEFT", 0: "ZONE_AHEAD", 1: "ZONE_RIGHT"}[side]]
    if side == 0 and mm is not None:
        items += distance_items(mm)
    return Utterance(ANSWER, items, tag="search")


def simple(*items, priority=ANSWER, tag=""):
    return Utterance(priority, list(items), tag=tag)


def battery(percent):
    if percent is None:
        return simple("BATTERY_UNKNOWN")
    return simple("BATTERY_LOW" if percent < 20 else "BATTERY_GOOD", priority=ANSWER)

