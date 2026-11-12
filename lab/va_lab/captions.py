"""Caption images for the on-screen window, Bangla included.

OpenCV cannot shape Bangla. Windows' text engine and macOS CoreText render
the joined letters to image masks; the preview window only pastes pixels.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import config

LINE_W = 600
FONT_EN = ("Segoe UI", 22)
FONT_BN = ("Nirmala UI", 22)

_PS = r"""
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$spec = Get-Content -Raw -Encoding UTF8 '__SPEC__' | ConvertFrom-Json
$flags = [System.Windows.Forms.TextFormatFlags]::NoPadding -bor [System.Windows.Forms.TextFormatFlags]::NoPrefix -bor [System.Windows.Forms.TextFormatFlags]::WordBreak
$size = New-Object System.Drawing.Size($spec.lineW, 2000)
foreach ($job in $spec.jobs) {
  $font = New-Object System.Drawing.Font($job.font, [single]$job.size, [System.Drawing.GraphicsUnit]::Pixel)
  $m = [System.Windows.Forms.TextRenderer]::MeasureText($job.text, $font, $size, $flags)
  $bmp = New-Object System.Drawing.Bitmap($spec.lineW, [Math]::Max(1, $m.Height))
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear([System.Drawing.Color]::Black)
  $rect = New-Object System.Drawing.Rectangle(0, 0, $spec.lineW, $m.Height)
  [System.Windows.Forms.TextRenderer]::DrawText($g, $job.text, $font, $rect, [System.Drawing.Color]::White, [System.Drawing.Color]::Black, $flags)
  $g.Dispose()
  $bmp.Save($job.path, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  $font.Dispose()
}
"""


def render_all(force=False):
    """Renders every prompt in both languages to models/captions/. Windows only."""
    if os.name != "nt":
        from .caption_renderer import render_all as render_portable
        return render_portable(force=force)
    config.CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    for pid, text in config.load_prompts().items():
        for lang, (font, size) in (("en", FONT_EN), ("bn", FONT_BN)):
            out = config.CAPTIONS_DIR / f"{lang}_{pid}.png"
            if text[lang].strip() and (force or not out.exists()):
                jobs.append({"text": text[lang], "font": font, "size": size, "path": str(out)})
    if not jobs:
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "spec.json"
        spec.write_text(json.dumps({"lineW": LINE_W, "jobs": jobs}, ensure_ascii=False), encoding="utf-8")
        script = Path(tmp) / "render.ps1"
        script.write_text(_PS.replace("__SPEC__", str(spec)), encoding="utf-8-sig")
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], check=True)
    return len(jobs)


_cache = {}


def mask(lang, pid):
    """Caption as a [h, w] uint8 coverage mask, or None if not rendered."""
    key = (lang, pid)
    if key not in _cache:
        import cv2
        path = config.CAPTIONS_DIR / f"{lang}_{pid}.png"
        img = cv2.imread(str(path)) if path.exists() else None
        if img is None:
            _cache[key] = None
        else:
            m = img.max(axis=2)
            rows = np.nonzero(m.max(axis=1) > 40)[0]
            cols = np.nonzero(m.max(axis=0) > 40)[0]
            _cache[key] = m[: rows[-1] + 2, : cols[-1] + 2] if len(rows) else None
    return _cache[key]


# ---- captions for free text (OCR results, descriptions) --------------------

import hashlib
import queue
import threading

_pending = set()
_jobs = queue.Queue()


def _worker():
    while True:
        text, lang, out = _jobs.get()
        try:
            font, size = FONT_BN if lang == "bn" else FONT_EN
            with tempfile.TemporaryDirectory() as tmp:
                spec = Path(tmp) / "spec.json"
                spec.write_text(json.dumps({"lineW": LINE_W, "jobs": [
                    {"text": text, "font": font, "size": size, "path": str(out)}]}, ensure_ascii=False),
                    encoding="utf-8")
                script = Path(tmp) / "render.ps1"
                script.write_text(_PS.replace("__SPEC__", str(spec)), encoding="utf-8-sig")
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                               check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        finally:
            _pending.discard(str(out))


_thread = None


def text_mask(text, lang):
    """Mask for arbitrary text; None until it has been rendered (in the background)."""
    global _thread
    if os.name != "nt":
        from .caption_renderer import text_mask as portable_mask
        return portable_mask(text, lang)
    if not text.strip():
        return None
    out = config.CAPTIONS_DIR / f"txt_{lang}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}.png"
    key = ("txt", str(out))
    if key in _cache:
        return _cache[key]
    if out.exists():
        import cv2
        img = cv2.imread(str(out))
        m = img.max(axis=2) if img is not None else None
        if m is not None:
            rows = np.nonzero(m.max(axis=1) > 40)[0]
            m = m[: rows[-1] + 2] if len(rows) else None
        _cache[key] = m
        return m
    if str(out) not in _pending:
        _pending.add(str(out))
        config.CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)
        _jobs.put((text, lang, out))
        if _thread is None:
            _thread = threading.Thread(target=_worker, daemon=True)
            _thread.start()
    return None
