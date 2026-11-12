"""Offscreen CoreText captions on macOS, with a Pillow fallback elsewhere."""

import os
import platform
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, features

from . import config

WIDTH = 600


@lru_cache(maxsize=2)
def font(lang):
    override = os.environ.get("VA_FONT_BN" if lang == "bn" else "VA_FONT_EN")
    candidates = [override] if override else []
    if lang == "bn":
        candidates += ["/System/Library/Fonts/KohinoorBangla.ttc",
                       "/System/Library/Fonts/Supplemental/Bangla Sangam MN.ttc",
                       "C:/Windows/Fonts/Nirmala.ttf",
                       "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf"]
    else:
        candidates += ["/System/Library/Fonts/Helvetica.ttc", "C:/Windows/Fonts/segoeui.ttf",
                       "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    if lang == "bn" and not features.check_feature("raqm"):
        raise RuntimeError("Joined Bangla captions require a Pillow wheel with RAQM support")
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(candidate, 22)
    if lang == "bn":
        raise RuntimeError("Bangla caption font missing; set VA_FONT_BN to a Bengali .ttf or .ttc")
    return ImageFont.load_default(size=22)


def render(text, lang):
    if platform.system() == "Darwin":
        return _render_macos(text, lang)
    face = font(lang)
    lines, line = [], ""
    for word in text.split():
        proposed = f"{line} {word}".strip()
        if line and face.getlength(proposed) > WIDTH - 4:
            lines.append(line)
            line = word
        else:
            line = proposed
    lines.append(line)
    image = Image.new("L", (WIDTH, max(36, len(lines) * 36)), 0)
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines):
        draw.text((1, i * 36), line, font=face, fill=255)
    return image


def _render_macos(text, lang):
    # AppKit shapes Bengali with CoreText, including on Pillow builds without
    # RAQM. Render offscreen so no window or screen capture is involved.
    import io
    import math
    import AppKit
    name = "Kohinoor Bangla" if lang == "bn" else "Helvetica"
    face = AppKit.NSFont.fontWithName_size_(name, 22) or AppKit.NSFont.systemFontOfSize_(22)
    attributed = AppKit.NSAttributedString.alloc().initWithString_attributes_(text, {
        AppKit.NSFontAttributeName: face,
        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.whiteColor(),
    })
    options = AppKit.NSStringDrawingUsesLineFragmentOrigin
    bounds = attributed.boundingRectWithSize_options_((WIDTH - 4, 10000), options)
    height = max(36, math.ceil(bounds.size.height) + 8)
    bitmap = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, WIDTH, height, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 0)
    context = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap)
    AppKit.NSGraphicsContext.saveGraphicsState()
    try:
        AppKit.NSGraphicsContext.setCurrentContext_(context)
        AppKit.NSColor.blackColor().setFill()
        AppKit.NSRectFill(((0, 0), (WIDTH, height)))
        attributed.drawWithRect_options_(((2, 2), (WIDTH - 4, height - 4)), options)
    finally:
        AppKit.NSGraphicsContext.restoreGraphicsState()
    data = bitmap.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    return Image.open(io.BytesIO(bytes(data))).convert("L")


def render_all(force=False):
    config.CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    made = 0
    for pid, texts in config.load_prompts().items():
        for lang, text in texts.items():
            out = config.CAPTIONS_DIR / f"{lang}_{pid}.png"
            if text.strip() and (force or not out.exists()):
                render(text, lang).save(out)
                made += 1
    return made


@lru_cache(maxsize=256)
def text_mask(text, lang):
    if not text.strip():
        return None
    return np.asarray(render(text, lang)).copy()
