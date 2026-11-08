#!/usr/bin/env python3
"""Build the wearable's voice prompts into firmware source.

    python tools/make_prompts.py             # synthesize missing English, encode all
    python tools/make_prompts.py --regen-en  # re-synthesize every English prompt

Reads   tools/prompts.csv, prompts/en/<ID>.wav, prompts/bn/<ID>.wav
Writes  include/prompt_ids.h, src/prompt_data.c

English prompts are synthesized offline with the Windows voice (no network).
Bangla prompts must be recorded by a person: Windows has no Bangla voice, and
a native speaker's recording is clearer to a Bangla listener than any
synthetic one. Any WAV works (phone recorder, Audacity); it is converted to
16 kHz mono here. A missing Bangla prompt falls back to English on the device.

Every prompt text is checked against the app's banned-phrase list before
anything is written. The wearable is held to the same rule as the app: it
reports observations and never tells the user that something is safe.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent
REPO = FIRMWARE.parent.parent
BANNED = REPO / "spine" / "safety-policy" / "src" / "main" / "resources" / "banned-phrases.txt"

RATE = 16000
ENGLISH_VOICE = "Microsoft Zira Desktop"

STEP = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66,
    73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408,
    449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066,
    2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630,
    9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794,
    32767,
]
INDEX_ADJUST = [-1, -1, -1, -1, 2, 4, 6, 8]


def load_prompts():
    with open(HERE / "prompts.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    ids = [r["id"].strip() for r in rows]
    if len(set(ids)) != len(ids):
        sys.exit("prompts.csv: duplicate id")
    for r in rows:
        if not r["id"].isidentifier():
            sys.exit(f"prompts.csv: {r['id']!r} is not a valid C identifier")
    return rows


def check_banned(rows):
    if not BANNED.exists():
        print(f"warning: {BANNED} not found; safety-language check skipped")
        return
    banned = [
        line.strip().lower()
        for line in BANNED.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    bad = []
    for r in rows:
        for lang in ("en", "bn"):
            text = (r.get(lang) or "").lower()
            bad += [f"  {r['id']} ({lang}) contains \"{p}\"" for p in banned if p in text]
    if bad:
        sys.exit("Prompt text promises the user that something is safe:\n" + "\n".join(bad))


def synthesize_english(jobs):
    """jobs: list of (text, path). One PowerShell call for all of them."""
    if not jobs:
        return
    if os.name != "nt":
        sys.exit("English synthesis uses the Windows voice; run on Windows or supply prompts/en/*.wav")
    with tempfile.TemporaryDirectory() as tmp:
        spec = Path(tmp) / "jobs.json"
        spec.write_text(json.dumps([{"text": t, "path": str(p)} for t, p in jobs]), encoding="utf-8")
        script = Path(tmp) / "synth.ps1"
        script.write_text(
            "Add-Type -AssemblyName System.Speech\n"
            f"$jobs = Get-Content -Raw -Encoding UTF8 '{spec}' | ConvertFrom-Json\n"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
            f"try {{ $s.SelectVoice('{ENGLISH_VOICE}') }} catch {{ }}\n"
            "$s.Rate = 0\n"
            "$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
            f"{RATE}, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
            "[System.Speech.AudioFormat.AudioChannel]::Mono)\n"
            "foreach ($j in $jobs) { $s.SetOutputToWaveFile($j.path, $fmt); $s.Speak($j.text) }\n"
            "$s.SetOutputToNull()\n"
            "$s.Dispose()\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            check=True,
        )


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(frames)
    if width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        v = b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
        x = v.astype(np.float32) / float(1 << 23)
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float32) / float(1 << 31)
    else:
        sys.exit(f"{path}: unsupported sample width {width}")
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    return rate, x


def to_16k(rate, x):
    if rate == RATE:
        return x
    # Low-pass below the new Nyquist before interpolating, or a 44.1/48 kHz
    # phone recording folds its hiss back into the speech band.
    cutoff = 0.45 * RATE / rate
    n = np.arange(-63, 64)
    h = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hanning(len(n))
    h /= h.sum()
    y = np.convolve(x, h, mode="same")
    t = np.arange(0, len(y) * RATE / rate) * (rate / RATE)
    return np.interp(t, np.arange(len(y)), y).astype(np.float32)


def condition(x):
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak < 1e-4:
        sys.exit("recording is silent")
    # Trim silence at -40 dB below the peak, keeping 20 ms either side, so
    # concatenated prompts ("Obstacle ahead." + "One metre.") run together
    # the way a person would say them.
    above = np.nonzero(np.abs(x) > peak * 0.01)[0]
    pad = int(0.02 * RATE)
    x = x[max(0, above[0] - pad): min(len(x), above[-1] + pad)]
    x = x / peak * 0.89
    fade = min(int(0.005 * RATE), len(x) // 2)
    ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    x[:fade] *= ramp
    x[len(x) - fade:] *= ramp[::-1]
    return np.clip(np.round(x * 32767.0), -32768, 32767).astype(np.int16)


def adpcm_encode(samples):
    """IMA ADPCM, low nibble first. Mirrors decodeNibble() in src/speaker.cpp."""
    pred, index = 0, 0
    out = bytearray()
    decoded = np.empty(len(samples), dtype=np.int16)
    nibbles = []
    for i, s in enumerate(samples.astype(np.int32)):
        step = STEP[index]
        diff = int(s) - pred
        nib = 0
        if diff < 0:
            nib = 8
            diff = -diff
        if diff >= step:
            nib |= 4
            diff -= step
        if diff >= step >> 1:
            nib |= 2
            diff -= step >> 1
        if diff >= step >> 2:
            nib |= 1
        # Track the decoder exactly, so errors never accumulate.
        d = step >> 3
        if nib & 4:
            d += step
        if nib & 2:
            d += step >> 1
        if nib & 1:
            d += step >> 2
        pred = pred - d if nib & 8 else pred + d
        pred = max(-32768, min(32767, pred))
        index = max(0, min(88, index + INDEX_ADJUST[nib & 7]))
        decoded[i] = pred
        nibbles.append(nib)
    if len(nibbles) % 2:
        nibbles.append(0)
    for lo, hi in zip(nibbles[0::2], nibbles[1::2]):
        out.append(lo | (hi << 4))
    return bytes(out), decoded


def snr_db(ref, test):
    noise = ref.astype(np.float64) - test.astype(np.float64)
    p_sig = np.mean(ref.astype(np.float64) ** 2)
    p_noise = np.mean(noise ** 2) + 1e-9
    return 10 * np.log10(p_sig / p_noise)


def c_array(name, data):
    lines = []
    for i in range(0, len(data), 20):
        lines.append("    " + ", ".join(f"0x{b:02X}" for b in data[i:i + 20]) + ",")
    return f"static const uint8_t {name}[{len(data)}] = {{\n" + "\n".join(lines) + "\n};\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regen-en", action="store_true", help="re-synthesize every English prompt")
    args = ap.parse_args()
    # Windows consoles default to cp1252, which cannot print the Bangla list.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    rows = load_prompts()
    check_banned(rows)

    en_dir = FIRMWARE / "prompts" / "en"
    bn_dir = FIRMWARE / "prompts" / "bn"
    en_dir.mkdir(parents=True, exist_ok=True)
    bn_dir.mkdir(parents=True, exist_ok=True)

    jobs = [(r["en"], en_dir / f"{r['id']}.wav") for r in rows
            if args.regen_en or not (en_dir / f"{r['id']}.wav").exists()]
    if jobs:
        print(f"synthesizing {len(jobs)} English prompts with {ENGLISH_VOICE}")
    synthesize_english(jobs)

    arrays, en_table, bn_table, missing_bn = [], [], [], []
    total = 0
    worst_snr = 99.0
    for r in rows:
        pid = r["id"]
        for lang, folder, table in (("en", en_dir, en_table), ("bn", bn_dir, bn_table)):
            path = folder / f"{pid}.wav"
            if not path.exists():
                if lang == "en":
                    sys.exit(f"missing {path}")
                table.append("{NULL, 0}")
                if (r.get("bn") or "").strip():
                    missing_bn.append(pid)
                continue
            pcm = condition(to_16k(*read_wav(path)))
            data, decoded = adpcm_encode(pcm)
            worst_snr = min(worst_snr, snr_db(pcm, decoded))
            name = f"{lang}_{pid}"
            arrays.append(c_array(name, data))
            table.append(f"{{{name}, {len(pcm)}u}}")
            total += len(data)

    ids_h = ["// Generated by tools/make_prompts.py from tools/prompts.csv. Do not edit.",
             "#pragma once", "", "typedef enum {"]
    ids_h += [f"  PROMPT_{r['id']} = {i}," for i, r in enumerate(rows)]
    ids_h += ["  PROMPT_COUNT", "} PromptId;", ""]
    (FIRMWARE / "include" / "prompt_ids.h").write_text("\n".join(ids_h), encoding="utf-8")

    c = ["// Generated by tools/make_prompts.py from tools/prompts.csv. Do not edit.",
         "#include <stddef.h>", "#include \"prompt_data.h\"", ""]
    c += arrays
    c.append("const PromptClip kPromptsEn[PROMPT_COUNT] = {\n    " + ",\n    ".join(en_table) + "\n};\n")
    c.append("const PromptClip kPromptsBn[PROMPT_COUNT] = {\n    " + ",\n    ".join(bn_table) + "\n};\n")
    expected = sum(1 for r in rows if (r.get("bn") or "").strip())
    c.append(f"const uint16_t kPromptsBnExpected = {expected}u;\n")
    c.append("const char *const kPromptNames[PROMPT_COUNT] = {\n    "
             + ",\n    ".join(f"\"{r['id']}\"" for r in rows) + "\n};\n")
    (FIRMWARE / "src" / "prompt_data.c").write_text("\n".join(c), encoding="utf-8")

    print(f"{len(rows)} prompts, {total / 1024:.0f} KiB of flash, worst ADPCM SNR {worst_snr:.1f} dB")
    # The screen's captions come from the same prompts.csv; keep them in step.
    subprocess.run([sys.executable, str(HERE / "make_display_assets.py")], check=True)
    if missing_bn:
        print(f"Bangla not recorded yet ({len(missing_bn)}): record prompts/bn/<ID>.wav for")
        for pid in missing_bn:
            text = next(r["bn"] for r in rows if r["id"] == pid)
            print(f"  {pid:16} {text}")


if __name__ == "__main__":
    main()
