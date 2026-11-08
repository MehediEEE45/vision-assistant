#!/usr/bin/env python3
"""Build the LCD's captions and status font into firmware source.

    python tools/make_display_assets.py

Reads   tools/prompts.csv
Writes  include/display_assets.h, src/display_assets.c

Each prompt's text, in both languages, is word-wrapped to the 160x80 screen
and rendered to 1-bit bitmaps on this PC. Bangla is rendered by Windows'
own text engine because joined letters (যুক্তাক্ষর) and vowel signs need
complex-script shaping that no microcontroller font renderer does. The
board only copies pixels.

make_prompts.py runs this automatically; run it by hand only after editing
prompts.csv without regenerating the audio.
"""

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent

LINE_W = 156          # 160 px panel minus a 2 px margin each side
LINE_H = 16
FONT_EN = ("Segoe UI", 12)
FONT_BN = ("Nirmala UI", 12)
CELL_W, CELL_H = 6, 10
FONT_ASCII = ("Consolas", 10)

POWERSHELL = r"""
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$spec = Get-Content -Raw -Encoding UTF8 '__SPEC__' | ConvertFrom-Json
$flags = [System.Windows.Forms.TextFormatFlags]::NoPadding -bor [System.Windows.Forms.TextFormatFlags]::SingleLine -bor [System.Windows.Forms.TextFormatFlags]::NoPrefix
$big = New-Object System.Drawing.Size(4000, 200)
$out = @()
foreach ($job in $spec.captions) {
  $font = New-Object System.Drawing.Font($job.font, [single]$job.size, [System.Drawing.GraphicsUnit]::Pixel)
  $words = $job.text -split ' '
  $lines = @()
  $cur = ''
  foreach ($w in $words) {
    if ($w -eq '') { continue }
    $try = if ($cur -eq '') { $w } else { $cur + ' ' + $w }
    $width = [System.Windows.Forms.TextRenderer]::MeasureText($try, $font, $big, $flags).Width
    if ($width -le $spec.lineW -or $cur -eq '') { $cur = $try } else { $lines += $cur; $cur = $w }
  }
  if ($cur -ne '') { $lines += $cur }
  $i = 0
  foreach ($line in $lines) {
    $bmp = New-Object System.Drawing.Bitmap($spec.lineW, $spec.lineH)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::Black)
    $pt = New-Object System.Drawing.Point(0, 0)
    [System.Windows.Forms.TextRenderer]::DrawText($g, $line, $font, $pt, [System.Drawing.Color]::White, [System.Drawing.Color]::Black, $flags)
    $g.Dispose()
    $path = Join-Path $spec.dir ($job.key + '_' + $i + '.png')
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    $i++
  }
  $out += [pscustomobject]@{ key = $job.key; lines = $i }
  $font.Dispose()
}
$font = New-Object System.Drawing.Font($spec.asciiFont, [single]$spec.asciiSize, [System.Drawing.GraphicsUnit]::Pixel)
for ($c = 32; $c -le 126; $c++) {
  $bmp = New-Object System.Drawing.Bitmap($spec.cellW, $spec.cellH)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear([System.Drawing.Color]::Black)
  $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::SingleBitPerPixelGridFit
  $fmt = [System.Drawing.StringFormat]::GenericTypographic
  $g.DrawString([string][char]$c, $font, [System.Drawing.Brushes]::White, -0.5, -1.0, $fmt)
  $g.Dispose()
  $bmp.Save((Join-Path $spec.dir ('ascii_' + $c + '.png')), [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
}
$out | ConvertTo-Json -Depth 3 | Set-Content -Encoding UTF8 (Join-Path $spec.dir 'result.json')
"""


def load_prompts():
    with open(HERE / "prompts.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def render(rows, workdir):
    jobs = []
    for r in rows:
        for lang, (font, size) in (("en", FONT_EN), ("bn", FONT_BN)):
            text = (r.get(lang) or "").strip()
            if text:
                jobs.append({"key": f"{lang}_{r['id']}", "text": text, "font": font, "size": size})
    spec = {
        "dir": str(workdir), "lineW": LINE_W, "lineH": LINE_H, "captions": jobs,
        "asciiFont": FONT_ASCII[0], "asciiSize": FONT_ASCII[1], "cellW": CELL_W, "cellH": CELL_H,
    }
    spec_path = workdir / "spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    script = workdir / "render.ps1"
    script.write_text(POWERSHELL.replace("__SPEC__", str(spec_path)), encoding="utf-8-sig")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], check=True)
    result = json.loads((workdir / "result.json").read_text(encoding="utf-8-sig"))
    if isinstance(result, dict):
        result = [result]
    return {item["key"]: int(item["lines"]) for item in result}


def to_bits(path, threshold=110):
    img = np.asarray(Image.open(path).convert("RGB")).astype(np.int32)
    # ClearType draws coloured fringes; the brightest channel is the coverage.
    lit = img.max(axis=2) > threshold
    return lit


def pack_rows(lit, width):
    stride = (width + 7) // 8
    out = bytearray()
    for row in lit[:, :width]:
        for b in range(stride):
            byte = 0
            for bit in range(8):
                x = b * 8 + bit
                if x < width and row[x]:
                    byte |= 0x80 >> bit
            out.append(byte)
    return bytes(out)


def c_bytes(data, indent="    "):
    return "\n".join(indent + ", ".join(f"0x{b:02X}" for b in data[i:i + 20]) + ","
                     for i in range(0, len(data), 20))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if os.name != "nt":
        sys.exit("Captions are rendered with the Windows text engine; run this on Windows.")
    rows = load_prompts()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        counts = render(rows, workdir)

        out = ["// Generated by tools/make_display_assets.py from tools/prompts.csv. Do not edit.",
               "#include <stddef.h>", "#include \"display_assets.h\"", ""]
        tables = {"en": [], "bn": []}
        total = 0
        for r in rows:
            for lang in ("en", "bn"):
                key = f"{lang}_{r['id']}"
                n = counts.get(key, 0)
                if n == 0:
                    tables[lang].append("{0, NULL}")
                    continue
                line_entries = []
                for i in range(n):
                    lit = to_bits(workdir / f"{key}_{i}.png")
                    cols = np.nonzero(lit.any(axis=0))[0]
                    width = int(cols[-1]) + 1 if len(cols) else 1
                    data = pack_rows(lit, width)
                    name = f"cap_{key}_{i}"
                    out.append(f"static const uint8_t {name}[{len(data)}] = {{\n{c_bytes(data)}\n}};")
                    line_entries.append(f"{{{width}, {name}}}")
                    total += len(data)
                out.append(f"static const CaptionLine lines_{key}[{n}] = {{{', '.join(line_entries)}}};")
                tables[lang].append(f"{{{n}, lines_{key}}}")

        glyphs = []
        for c in range(32, 127):
            lit = to_bits(workdir / f"ascii_{c}.png", threshold=100)
            rows_bits = []
            for y in range(CELL_H):
                byte = 0
                for x in range(CELL_W):
                    if lit[y, x]:
                        byte |= 0x80 >> x
                rows_bits.append(byte)
            glyphs.append("    {" + ", ".join(f"0x{b:02X}" for b in rows_bits) + "},")

    out.append("const Caption kCaptionsEn[PROMPT_COUNT] = {\n    " + ",\n    ".join(tables["en"]) + "\n};")
    out.append("const Caption kCaptionsBn[PROMPT_COUNT] = {\n    " + ",\n    ".join(tables["bn"]) + "\n};")
    out.append(f"const uint8_t kFontAscii[95][{CELL_H}] = {{\n" + "\n".join(glyphs) + "\n};")
    (FIRMWARE / "src" / "display_assets.c").write_text("\n".join(out) + "\n", encoding="utf-8")

    header = [
        "// Generated by tools/make_display_assets.py. Do not edit.",
        "#pragma once",
        "",
        "#include <stdint.h>",
        "",
        "#include \"prompt_ids.h\"",
        "",
        "#ifdef __cplusplus",
        "extern \"C\" {",
        "#endif",
        "",
        f"#define CAPTION_LINE_HEIGHT {LINE_H}",
        f"#define FONT_CELL_W {CELL_W}",
        f"#define FONT_CELL_H {CELL_H}",
        "",
        "// One rendered line: 1 bit per pixel, MSB first, rows of (width + 7) / 8 bytes.",
        "typedef struct {",
        "  uint8_t width;",
        "  const uint8_t *bits;",
        "} CaptionLine;",
        "",
        "typedef struct {",
        "  uint8_t count;  // 0 when the prompt has no text in that language",
        "  const CaptionLine *lines;",
        "} Caption;",
        "",
        "extern const Caption kCaptionsEn[PROMPT_COUNT];",
        "extern const Caption kCaptionsBn[PROMPT_COUNT];",
        f"extern const uint8_t kFontAscii[95][{CELL_H}];  // ' ' to '~', one byte per row, MSB = left",
        "",
        "#ifdef __cplusplus",
        "}",
        "#endif",
        "",
    ]
    (FIRMWARE / "include" / "display_assets.h").write_text("\n".join(header), encoding="utf-8")
    print(f"captions for {len(rows)} prompts, {total / 1024:.1f} KiB; ASCII font {CELL_W}x{CELL_H}")


if __name__ == "__main__":
    main()
