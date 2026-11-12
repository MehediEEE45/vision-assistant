"""Paths and tunables. Numbers shared with the firmware say where they come from."""

import csv
import os
import threading
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
REPO = LAB.parent
DATA = LAB / "data"
MODELS = LAB / "models"

# Keep downloads in this project; launchers and notebooks share these defaults.
# Existing user overrides still take precedence.
os.environ.setdefault("HF_HOME", str(LAB / ".cache" / "huggingface"))
os.environ.setdefault("TORCH_HOME", str(LAB / ".cache" / "torch"))
os.environ.setdefault("YOLO_CONFIG_DIR", str(LAB / ".cache" / "ultralytics"))
os.environ.setdefault("YOLO_AUTOINSTALL", "false")

FIRMWARE = REPO / "firmware" / "stm32h743"
PROMPTS_CSV = FIRMWARE / "tools" / "prompts.csv"
KEYWORDS_CSV = FIRMWARE / "tools" / "keywords.csv"
PROMPT_WAVS = FIRMWARE / "prompts"  # en/<ID>.wav, bn/<ID>.wav
BANNED_PHRASES = REPO / "spine" / "safety-policy" / "src" / "main" / "resources" / "banned-phrases.txt"

SPEECH_COMMANDS_DIR = DATA / "speech_commands"
MY_KEYWORDS_DIR = DATA / "my_keywords"
IMAGES_DIR = DATA / "images"
CAPTIONS_DIR = MODELS / "captions"

SAMPLE_RATE = 16000

# ---------------------------------------------------------------------------
# Keyword spotting
# ---------------------------------------------------------------------------

SPEECH_COMMANDS_URL = "http://download.tensorflow.org/data/speech_commands_v0.02.tar.gz"

# Speech Commands words used for the ready-made English demo model. They are
# the closest the public dataset gets to the device's commands; the full
# Bangla + English vocabulary needs your own recordings (notebook 02).
DEMO_WORDS = ["stop", "go", "yes", "no", "left", "right", "up", "down", "on", "off"]

# The rest of the dataset's words become the "_unknown_" class: without
# them the model learns that any speech at all is a command.
SC_OTHER_WORDS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "bed", "bird", "cat", "dog", "happy", "house", "marvin", "sheila", "tree", "wow",
    "backward", "forward", "follow", "learn", "visual",
]

KWS_LISTEN_S = 1.5
# Same thresholds as the firmware (config.h): a wrong "emergency" in public
# is worse than asking again.
KWS_MIN_CONFIDENCE = 0.70
KWS_EMERGENCY_CONFIDENCE = 0.85

# ---------------------------------------------------------------------------
# Camera and objects
# ---------------------------------------------------------------------------

CAMERA_INDEX = 0
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
# Most laptop webcams are 60-80 degrees horizontally. Measure yours (notebook
# 01): it decides what "left" means and every distance estimate.
CAMERA_HFOV_DEG = 70.0
# True for the laptop's own lid camera turned towards you; False for a
# camera that looks where you look (a chest or neck camera, a phone clipped
# on). It flips every left/right the assistant says, so set it to match.
CAMERA_FACES_USER = True

# The firmware's eight objects (src/vision.h), and the words YOLO-World is
# given for each. Open-vocabulary detection means door, rickshaw and CNG need
# no training at all on the laptop.
OBJECTS = ["person", "chair", "door", "table", "bottle", "toilet", "rickshaw", "cng"]
OBJECT_QUERIES = {
    "person": ["person"],
    "chair": ["chair"],
    "door": ["door"],
    "table": ["table", "dining table", "desk"],
    "bottle": ["bottle"],
    "toilet": ["toilet"],
    "rickshaw": ["cycle rickshaw", "rickshaw"],
    "cng": ["auto rickshaw", "tuk tuk"],
}
# COCO names for the fallback detector, which knows five of the eight.
COCO_TO_OBJECT = {"person": "person", "chair": "chair", "dining table": "table",
                  "bottle": "bottle", "toilet": "toilet"}

# Typical real heights in metres, for the pinhole distance estimate. A
# camera alone measures nothing: these turn a box's pixel height into an
# approximate distance, and are wrong for a child, a stool or a cut-off box.
OBJECT_HEIGHT_M = {"person": 1.60, "chair": 0.90, "door": 2.00, "table": 0.75,
                   "bottle": 0.25, "toilet": 0.75, "rickshaw": 1.80, "cng": 1.70}

# Typical widths: a second estimate beside the height one. The smaller of
# the two wins, because an obstacle reported too far away is the dangerous
# mistake; one reported too near is only a false alarm.
OBJECT_WIDTH_M = {"person": 0.45, "chair": 0.50, "door": 0.90, "table": 1.00,
                  "bottle": 0.08, "toilet": 0.40, "rickshaw": 1.10, "cng": 1.40}

DETECT_CONFIDENCE = 0.35
DETECT_IMGSZ = 480
# Florence-2-large describes a little better but needs 1.9 GB and ~8 s.
FLORENCE_LARGE = False
# CPU threads for the models that run there (Bangla voice, translation),
# leaving the rest of the 12 cores to the camera loop.
CPU_THREADS = 4
VISION_MIN_CONFIDENCE = 0.45
# An object must be seen in this many of the last STABLE_WINDOW frames before
# it is spoken about; a one-frame flicker is not an object.
STABLE_HITS = 3
STABLE_WINDOW = 5

# Firmware config.h: within this angle is "ahead" during a search.
FIND_AHEAD_DEG = 10.0
FIND_TIMEOUT_S = 30.0
FIND_NUDGE_S = 0.7
FIND_SPEECH_S = 3.0

# ---------------------------------------------------------------------------
# Obstacle policy: perception/obstacle-fusion/ObstaclePolicy.kt and the
# firmware's obstacle_policy.cpp. Keep all three the same.
# ---------------------------------------------------------------------------

OBST_IMMEDIATE_MM = 600
OBST_NEAR_MM = 1200
OBST_APPROACHING_MM = 2000
OBST_HYSTERESIS_MM = 200
OBST_FRAMES_TO_CONFIRM = 3
OBST_REANNOUNCE_MS = {"immediate": 1500, "near": 3000, "approaching": 6000}
# The firmware uses 120 mm for its laser. A camera estimate wobbles by a few
# hundred millimetres frame to frame, which at 120 would never count as
# standing still, so a seated user would hear the same chair every 3 s.
OBST_STATIC_SCENE_MM = 350
OBST_STATIC_SCENE_MS = 2500
OBST_CROSS_ZONE_MS = 800
# The camera's "ahead" zone for obstacles: the middle of the picture.
OBST_AHEAD_DEG = 12.0

# ---------------------------------------------------------------------------
# Speech
# ---------------------------------------------------------------------------

DEFAULT_BANGLA = True
VOLUME = 0.9


def load_prompts():
    """{ID: {"en": text, "bn": text}} from the firmware's prompts.csv."""
    with open(PROMPTS_CSV, encoding="utf-8", newline="") as f:
        return {r["id"]: {"en": r["en"], "bn": r["bn"]} for r in csv.DictReader(f)}


def load_keywords():
    """Rows of the firmware's keywords.csv: label, language, say, romanised, intent."""
    with open(KEYWORDS_CSV, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def ensure_dirs():
    for d in (DATA, MODELS, SPEECH_COMMANDS_DIR, MY_KEYWORDS_DIR, IMAGES_DIR, CAPTIONS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# Loading two models at once from two threads races inside transformers'
# lazy imports ("cannot import name AutoTokenizer"). Every load takes this.
MODEL_LOCK = threading.RLock()
