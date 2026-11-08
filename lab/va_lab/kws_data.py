"""Keyword datasets: a slice of Google Speech Commands, plus your own recordings.

Speech Commands v0.02 (Warden 2018, CC-BY 4.0) is 2.3 GB. It is streamed and
only the words this project uses are written to disk, capped per word, so
the dataset folder stays under about 800 MB.
"""

import hashlib
import json
import re
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from . import audio_io, config

SR = config.SAMPLE_RATE
NOISE = "_background_noise_"
UNKNOWN = "_unknown_"
SILENCE = "_silence_"
MAX_NUM_WAVS_PER_CLASS = 2 ** 27 - 1


def which_set(filename, validation_percentage=10, testing_percentage=10):
    """The dataset's official split: by speaker, so no voice is in two splits."""
    base = Path(filename).name
    speaker = re.sub(r"_nohash_.*$", "", base)
    h = int(hashlib.sha1(speaker.encode("utf-8")).hexdigest(), 16)
    pct = (h % (MAX_NUM_WAVS_PER_CLASS + 1)) * (100.0 / MAX_NUM_WAVS_PER_CLASS)
    if pct < validation_percentage:
        return "validation"
    if pct < validation_percentage + testing_percentage:
        return "testing"
    return "training"


def download_speech_commands(dest=config.SPEECH_COMMANDS_DIR, words=config.DEMO_WORDS,
                             other_words=config.SC_OTHER_WORDS, per_word=1500, per_other=200,
                             url=config.SPEECH_COMMANDS_URL, progress=True):
    """Stream the archive and keep only what is needed. Safe to re-run."""
    import requests
    from tqdm.auto import tqdm

    dest = Path(dest)
    marker = dest / "complete.json"
    if marker.exists():
        print(f"already downloaded: {json.loads(marker.read_text())['counts']}")
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    caps = {w: per_word for w in words}
    caps.update({w: per_other for w in other_words})
    counts = Counter()

    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        bar = tqdm(total=total, unit="B", unit_scale=True, desc="speech_commands", disable=not progress)
        r.raw.decode_content = True

        class Counting:
            def read(self, n=-1):
                b = r.raw.read(n)
                bar.update(len(b))
                return b

        with tarfile.open(fileobj=Counting(), mode="r|gz") as tar:
            for m in tar:
                if not m.isfile():
                    continue
                name = m.name[2:] if m.name.startswith("./") else m.name
                parts = name.split("/")
                if len(parts) != 2 or not parts[1].endswith(".wav"):
                    continue
                folder = parts[0]
                if folder != NOISE:
                    cap = caps.get(folder)
                    if cap is None or counts[folder] >= cap:
                        continue
                out = dest / folder / parts[1]
                out.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as src:
                    out.write_bytes(src.read())
                counts[folder] += 1
        bar.close()

    marker.write_text(json.dumps({"url": url, "counts": dict(counts)}, indent=1))
    print(f"kept {sum(counts.values())} clips in {dest}")
    return dest


def _speaker_split(speaker, validation_percentage=10, testing_percentage=10):
    return which_set(f"{speaker}_nohash_0.wav", validation_percentage, testing_percentage)


def my_keyword_index(root=config.MY_KEYWORDS_DIR):
    """[(path, label, split)] for recordings made with notebook 02 or the wearable.

    Files are <label>.<speaker>_<n>.wav; the split is by speaker.
    """
    items = []
    for f in sorted(Path(root).glob("*/*.wav")):
        label = f.parent.name
        speaker = f.stem.split(".", 1)[1].rsplit("_", 1)[0] if "." in f.stem else "anon"
        items.append((f, label, _speaker_split(speaker)))
    return items


def _fit(x):
    if len(x) >= SR:
        return audio_io.loudest_second(x)
    return np.pad(x, (0, SR - len(x)))


def _to_int16(x):
    return np.clip(np.round(x * 32767.0), -32768, 32767).astype(np.int16)


def noise_bank(slice_s=1.0, sc_root=config.SPEECH_COMMANDS_DIR, mine=config.MY_KEYWORDS_DIR):
    """One-second slices of every background-noise recording, float32."""
    slices = []
    files = sorted(Path(sc_root, NOISE).glob("*.wav")) + sorted(Path(mine, "_noise").glob("*.wav"))
    for f in files:
        x = audio_io.load_wav(f)
        n = int(slice_s * SR)
        for start in range(0, len(x) - n + 1, n // 2):
            slices.append(x[start:start + n])
    return np.stack(slices).astype(np.float32) if slices else np.zeros((1, SR), np.float32)


def build_dataset(vocab="demo", sc_root=config.SPEECH_COMMANDS_DIR, mine=config.MY_KEYWORDS_DIR,
                  unknown_max=4000, seed=0):
    """Arrays for training.

    vocab="demo":   the ten Speech Commands words (English only).
    vocab="custom": every label you recorded (notebook 02), Bangla and English.

    Returns {"classes", "noise", "training"/"validation"/"testing": (x int16 [N, 16000], y int64 [N])}.
    """
    rng = np.random.default_rng(seed)
    sc_root, mine = Path(sc_root), Path(mine)
    entries = []  # (path, label, split)

    if vocab == "demo":
        keywords = list(config.DEMO_WORDS)
        for w in keywords:
            entries += [(f, w, which_set(f.name)) for f in sorted((sc_root / w).glob("*.wav"))]
        unknown_words = list(config.SC_OTHER_WORDS)
    elif vocab == "custom":
        mine_idx = [e for e in my_keyword_index(mine) if not e[1].startswith("_")]
        keywords = sorted({label for _, label, _ in mine_idx})
        if not keywords:
            raise RuntimeError(f"no recordings in {mine}: record some with notebook 02 first")
        entries += mine_idx
        # Every Speech Commands word is "something else" to this vocabulary.
        unknown_words = list(config.DEMO_WORDS) + list(config.SC_OTHER_WORDS)
    else:
        raise ValueError("vocab must be 'demo' or 'custom'")

    unknown = []
    for w in unknown_words:
        unknown += [(f, UNKNOWN, which_set(f.name)) for f in sorted((sc_root / w).glob("*.wav"))]
    unknown += [(f, UNKNOWN, split) for f, label, split in my_keyword_index(mine) if label == "_unknown"]
    if len(unknown) > unknown_max:
        unknown = [unknown[i] for i in rng.choice(len(unknown), unknown_max, replace=False)]
    entries += unknown

    classes = keywords + [UNKNOWN, SILENCE]
    cls_idx = {c: i for i, c in enumerate(classes)}
    by_split = defaultdict(lambda: ([], []))
    for f, label, split in entries:
        xs, ys = by_split[split]
        xs.append(_to_int16(_fit(audio_io.load_wav(f))))
        ys.append(cls_idx[label])

    noise = noise_bank(sc_root=sc_root, mine=mine)
    per_class = max(1, int(np.median(np.bincount([cls_idx[e[1]] for e in entries])))) if entries else 100
    out = {"classes": classes, "noise": noise}
    for split, share in (("training", 0.8), ("validation", 0.1), ("testing", 0.1)):
        xs, ys = by_split[split]
        # Silence: background noise at a low level, and some true digital silence.
        n_sil = max(10, int(per_class * share))
        pick = rng.integers(0, len(noise), n_sil)
        gains = rng.uniform(0.0, 0.3, n_sil)[:, None]
        gains[: n_sil // 10] = 0.0
        sil = noise[pick] * gains
        xs = xs + [_to_int16(s) for s in sil]
        ys = ys + [cls_idx[SILENCE]] * n_sil
        out[split] = (np.stack(xs) if xs else np.zeros((0, SR), np.int16), np.array(ys, dtype=np.int64))
    return out


def summary(ds):
    rows = []
    for split in ("training", "validation", "testing"):
        y = ds[split][1]
        counts = np.bincount(y, minlength=len(ds["classes"]))
        rows.append((split, dict(zip(ds["classes"], counts.tolist()))))
    return rows
