"""Fetches every model the laptop assistant uses, once, so that afterwards it
runs with the network unplugged.

    %USERPROFILE%\\.venvs\\vision-ai-lab\\Scripts\\python.exe tools\\download_models.py

Then check:  set HF_HUB_OFFLINE=1  and run the assistant with Wi-Fi off.
"""

import os
import subprocess
import sys
from pathlib import Path

# Started with the wrong Python (VS Code's Run button uses whichever
# interpreter is selected): hand over to the lab's own environment.
VENV_PY = Path(os.environ.get("USERPROFILE", "~")).expanduser() / ".venvs" / "vision-ai-lab" / "Scripts" / "python.exe"
if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
    print(f"switching to {VENV_PY}", flush=True)
    sys.exit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve())] + sys.argv[1:]))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_lab import config  # noqa: E402

config.ensure_dirs()
steps = []


def step(name):
    def wrap(fn):
        steps.append((name, fn))
        return fn
    return wrap


@step("YOLO-World + COCO YOLOv8n (objects)")
def _():
    from va_lab.vision import Detector
    Detector("world")
    Detector("coco")


@step("EasyOCR Bengali + English (reading)")
def _():
    from va_lab import understand
    understand.get("ocr")


@step("Florence-2-base (describe, identify)")
def _():
    from va_lab import understand
    understand.get("florence")


@step("NLLB-200 600M (English <-> Bangla)")
def _():
    from va_lab import understand
    understand.get("nllb")


@step("MMS-TTS Bengali (speech) + BanglaASR + Whisper small (listening)")
def _():
    from va_lab import bangla_voice
    bangla_voice.synthesize("পরীক্ষা")
    bangla_voice._load_asr("bn")
    bangla_voice._load_asr("en")


if __name__ == "__main__":
    failed = []
    for name, fn in steps:
        print(f"-> {name}", flush=True)
        try:
            fn()
            print("   ok", flush=True)
        except Exception as e:
            print(f"   FAILED: {e!r}", flush=True)
            failed.append(name)
    print("all models ready" if not failed else f"failed: {failed} (re-run to retry)")
