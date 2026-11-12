"""Fetches every model the laptop assistant uses, once, so that afterwards it
runs with the network unplugged.

    %USERPROFILE%\\.venvs\\vision-ai-lab\\Scripts\\python.exe tools\\download_models.py

Then check:  set HF_HUB_OFFLINE=1  and run the assistant with Wi-Fi off.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_lab import config  # noqa: E402

config.ensure_dirs()
import torch  # noqa: E402
torch.set_num_threads(config.CPU_THREADS)
steps = []


def step(key, name):
    def wrap(fn):
        steps.append((key, name, fn))
        return fn
    return wrap


@step("detector", "YOLO-World + COCO YOLOv8n (objects)")
def _():
    from va_lab.vision import Detector
    Detector("world")
    Detector("coco")


@step("ocr", "EasyOCR Bengali + English (reading)")
def _():
    from va_lab import understand
    understand.get("ocr")


@step("caption", "Florence-2-base (describe, identify)")
def _():
    from va_lab import understand
    understand.get("florence")


@step("translation", "NLLB-200 600M (English <-> Bangla)")
def _():
    from va_lab import understand
    understand.get("nllb")


@step("voice", "MMS-TTS Bengali (speech)")
def _():
    from va_lab import bangla_voice
    bangla_voice.synthesize("পরীক্ষা")


@step("asr", "BanglaASR + Whisper small (listening)")
def _():
    from va_lab import bangla_voice
    bangla_voice._load_asr("bn")
    bangla_voice._load_asr("en")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=[s[0] for s in steps], help="Download selected groups")
    parser.add_argument("--fetch-only", action="store_true", help="Cache Hugging Face files without loading models")
    args = parser.parse_args()
    if args.fetch_only:
        from huggingface_hub import list_repo_files, snapshot_download
        from va_lab import bangla_voice, understand
        repos = {"caption": [understand.FLORENCE], "translation": [understand.NLLB],
                 "voice": [bangla_voice.TTS_MODEL], "asr": [bangla_voice.ASR_MODEL_BN, "Systran/faster-whisper-small"]}
        for key in args.only or repos:
            for repo in repos.get(key, []):
                print(f"-> caching {repo}", flush=True)
                files = list_repo_files(repo)
                weights = ["*.safetensors"] if any(f.endswith(".safetensors") for f in files) else ["pytorch_model*.bin", "model.bin"]
                snapshot_download(repo, allow_patterns=weights + ["*.json", "*.txt", "*.model", "*.spm"], max_workers=4)
        sys.exit(0)
    failed = []
    for key, name, fn in steps:
        if args.only and key not in args.only:
            continue
        print(f"-> {name}", flush=True)
        try:
            fn()
            print("   ok", flush=True)
        except Exception as e:
            print(f"   FAILED: {e!r}", flush=True)
            failed.append(name)
    print("all models ready" if not failed else f"failed: {failed} (re-run to retry)")
    sys.exit(1 if failed else 0)
