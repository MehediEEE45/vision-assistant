"""Check setup without opening devices; optionally run models or device checks.

    python -m va_lab.doctor
    python -m va_lab.doctor --models
    python -m va_lab.doctor --hardware --camera 0
"""

import argparse
import importlib
import json
import os
import platform
import sys
import time

from . import config

PACKAGES = ["torch", "torchvision", "cv2", "numpy", "sounddevice", "soundfile", "easyocr",
            "transformers", "ctranslate2", "faster_whisper", "sentencepiece", "clip", "PIL"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", action="store_true", help="Run real inference; download models first")
    parser.add_argument("--hardware", action="store_true", help="List audio devices and capture one camera frame")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--offline", action="store_true", help="Require cached models; forbid Hugging Face downloads")
    parser.add_argument("--skip-native", action="store_true", help="Dependency checks only, suitable for CI")
    parser.add_argument("--only", nargs="+", choices=["detector", "ocr", "caption", "translation", "voice", "asr"], help="Run selected model groups")
    args = parser.parse_args()
    args.models = args.models or bool(args.only)
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    config.ensure_dirs()
    results = []

    def check(name, fn):
        start = time.monotonic()
        try:
            detail = fn()
            result = {"check": name, "ok": True, "detail": str(detail), "seconds": round(time.monotonic() - start, 2)}
        except Exception as e:
            result = {"check": name, "ok": False, "detail": f"{type(e).__name__}: {e}", "seconds": round(time.monotonic() - start, 2)}
        results.append(result)
        print(f"{'PASS' if result['ok'] else 'FAIL'} {name}: {result['detail']} ({result['seconds']} s)", flush=True)

    print(f"Python {platform.python_version()} | {platform.system()} {platform.machine()} | {sys.executable}")
    for name in PACKAGES:
        check(f"import {name}", lambda name=name: getattr(importlib.import_module(name), "__version__", "available"))
    if not all(r["ok"] for r in results):
        print("Install requirements.txt using this Python environment before continuing.")
        return 1

    from . import audio_io, captions, safety, tts
    from .platform_support import torch_device
    from .vision import Detector, grab, open_camera
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    print(f"Detector device: {torch_device(allow_mps=True)}; other models: {torch_device()}")
    import torch
    torch.set_num_threads(config.CPU_THREADS)
    check("fixed prompt safety", lambda: safety.check_fixed([t for p in config.load_prompts().values() for t in p.values()]) or "all prompts passed")
    def gui_backend():
        import cv2
        line = next((s.strip() for s in cv2.getBuildInformation().splitlines() if s.strip().startswith("GUI:")), "GUI: NONE")
        if "NONE" in line:
            raise RuntimeError("OpenCV has no preview window backend. Rerun setup to restore opencv-python after EasyOCR.")
        return line
    check("camera window backend", gui_backend)
    if not args.skip_native:
        check("bilingual captions", lambda: captions.render_all() if platform.system() == "Windows" else _caption_check())
        check("native English speech", lambda: _audio_check(tts.synth("Vision Assistant is ready.", "en")))

    if args.hardware:
        check("audio devices", lambda: str(audio_io.devices()))

        def camera():
            cap = open_camera(args.camera)
            try:
                frame = grab(cap)
                if frame is None:
                    raise RuntimeError("Camera opened but returned no frame")
                return f"{frame.shape[1]} x {frame.shape[0]} frame; no photo saved"
            finally:
                cap.release()
        check("camera", camera)

    if args.models:
        from . import bangla_voice, understand
        image = Image.new("RGB", (640, 480), "white")
        draw = ImageDraw.Draw(image)
        face = ImageFont.load_default(size=40)
        draw.text((50, 120), "VISION ASSISTANT", fill="black", font=face)
        draw.text((50, 200), "Read this page.", fill="black", font=face)
        frame = np.asarray(image)[:, :, ::-1].copy()

        def detection():
            detector = Detector("world")
            found = detector.detect(frame)
            detector.set_queries(["bag"], "target")
            detector.detect(frame)
            detector.restore()
            detector.detect(frame)
            return f"YOLO-World inference, free-text target and restore completed: {len(found)} detections on a test page"

        def ocr():
            found = understand.get("ocr").read(frame)
            text = " ".join(t for _, t, _ in found)
            if "VISION" not in text.upper():
                raise AssertionError(f"Expected VISION in OCR output, got {text!r}")
            return text

        def bangla_ocr():
            captions.render_all()
            mask = captions.mask("bn", "OBJ_CHAIR")
            if mask is None:
                raise RuntimeError("Bangla test caption was not rendered")
            page = np.full((max(200, mask.shape[0] + 80), 640, 3), 255, np.uint8)
            page[40:40 + mask.shape[0], 20:20 + mask.shape[1]] = np.repeat((255 - mask)[..., None], 3, axis=2)
            found = understand.get("ocr").read(page)
            text = " ".join(t for _, t, _ in found)
            if not any("ঀ" <= c <= "৿" for c in text):
                raise AssertionError(f"No Bengali text recognized: {text!r}")
            return text

        def colour():
            result = understand.colour_name(np.full((96, 96, 3), (0, 180, 0), np.uint8))
            if result != "green":
                raise AssertionError(f"Expected green, got {result}")
            return result

        def model_check(key, name, fn):
            if not args.only or key in args.only:
                check(name, fn)

        model_check("detector", "object detection", detection)
        model_check("ocr", "English OCR", ocr)
        model_check("ocr", "Bangla OCR", bangla_ocr)
        model_check("caption", "scene caption", lambda: _text_check(understand.caption(frame, "short")))
        model_check("caption", "object colour", colour)
        model_check("translation", "English to Bangla", lambda: _text_check(understand.to_bangla("A chair is on the left.")))
        model_check("translation", "Bangla to English", lambda: _text_check(understand.to_english("একটি চেয়ার")))
        model_check("voice", "Bangla speech", lambda: _audio_check(bangla_voice.synthesize("সামনে একটি চেয়ার আছে।")))
        for language in (("bn", "en") if not args.only or "asr" in args.only else ()):
            def speech(language=language):
                x = tts.synth("সামনে কী আছে" if language == "bn" else "What is ahead?", language)
                return _text_check(bangla_voice.transcribe(x, language))
            check(f"{language} speech recognition", speech)

    out = config.LAB / "test-results" / "doctor.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {out}")
    return 0 if all(r["ok"] for r in results) else 1


def _caption_check():
    from .caption_renderer import text_mask
    for language, text in (("en", "Vision Assistant"), ("bn", "সামনে কী আছে")):
        mask = text_mask(text, language)
        if mask is None or not mask.max():
            raise AssertionError(f"Empty {language} caption")
    return "English and joined Bangla rendered"


def _audio_check(audio):
    import numpy as np
    if len(audio) < 1600 or not np.isfinite(audio).all() or np.max(np.abs(audio)) <= 0:
        raise AssertionError("Speech model returned empty or invalid audio")
    return f"{len(audio) / config.SAMPLE_RATE:.2f} seconds of audio"


def _text_check(text):
    if not text.strip():
        raise AssertionError("Model returned empty text")
    return text


if __name__ == "__main__":
    raise SystemExit(main())
