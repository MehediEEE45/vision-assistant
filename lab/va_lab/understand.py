"""Scene and object understanding, offline: Florence-2 captions, NLLB-200
translation, colour naming, and the model manager that keeps all of it
inside the GTX 1650's 4 GB.

Licences: Florence-2 MIT; NLLB-200 CC-BY-NC 4.0 (non-commercial use only).
"""

import threading

import cv2
import numpy as np

from . import config

# Base, not large, on a 4 GB GPU: 0.47 GB and 2.8 s for a detailed caption,
# against 1.9 GB and ~8 s, with nearly the same captions (measured on this
# laptop). Large also pushed the card past 4 GB, and YOLO then took up to 7 s
# per frame. config.FLORENCE_LARGE switches back.
FLORENCE = "florence-community/Florence-2-large" if config.FLORENCE_LARGE else "florence-community/Florence-2-base"
NLLB = "facebook/nllb-200-distilled-600M"

_lock = threading.Lock()
_models = {}
# How many heavy GPU jobs (caption, OCR) are running: the camera loop thins
# out detection meanwhile, so the two do not fight over the card.
busy = 0


class _Busy:
    def __enter__(self):
        global busy
        busy += 1

    def __exit__(self, *exc):
        global busy
        busy -= 1


gpu_job = _Busy()


# ---- model manager -------------------------------------------------------

def _free_gpu_gb():
    import torch
    if not torch.cuda.is_available():
        return 99.0
    free, _ = torch.cuda.mem_get_info()
    return free / 1e9


def unload(name):
    import gc
    import torch
    with _lock:
        _models.pop(name, None)
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def get(name):
    """Loads a model on first use. Florence needs ~1.6 GB of GPU; if that is
    not free, the OCR model is unloaded first (it reloads in a few seconds)."""
    with _lock:
        if name in _models:
            return _models[name]
    with config.MODEL_LOCK:
        with _lock:
            if name in _models:
                return _models[name]
        if name == "florence" and _free_gpu_gb() < (1.8 if config.FLORENCE_LARGE else 0.6):
            unload("ocr")
        if name == "ocr" and _free_gpu_gb() < 0.6:
            unload("florence")
        obj = _load(name)
        with _lock:
            _models[name] = obj
        return obj


def _load(name):
    import torch
    if name == "ocr":
        from .ocr import OCR
        return OCR()
    if name == "florence":
        from transformers import AutoProcessor, Florence2ForConditionalGeneration
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if dev == "cuda" else torch.float32
        proc = AutoProcessor.from_pretrained(FLORENCE)
        model = Florence2ForConditionalGeneration.from_pretrained(FLORENCE, torch_dtype=dtype).to(dev).eval()
        return proc, model, dev, dtype
    if name == "nllb":
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        tok_en = AutoTokenizer.from_pretrained(NLLB, src_lang="eng_Latn")
        tok_bn = AutoTokenizer.from_pretrained(NLLB, src_lang="ben_Beng")
        # GPU in fp16 when 1.4 GB is free: 0.55 s a sentence against 3.2 s on
        # the CPU, same translation (measured). Otherwise the CPU.
        gpu = torch.cuda.is_available() and _free_gpu_gb() > 1.4
        model = AutoModelForSeq2SeqLM.from_pretrained(NLLB, torch_dtype=torch.float16 if gpu else torch.float32)
        model = model.to("cuda" if gpu else "cpu").eval()
        return tok_en, tok_bn, model
    raise KeyError(name)


# ---- captions ------------------------------------------------------------

def caption(image_bgr, detail="detailed"):
    """English caption of a BGR image. detail: "short", "detailed" or "more"."""
    import torch
    from PIL import Image
    proc, model, dev, dtype = get("florence")
    task = {"short": "<CAPTION>", "detailed": "<DETAILED_CAPTION>", "more": "<MORE_DETAILED_CAPTION>"}[detail]
    img = Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
    inp = proc(text=task, images=img, return_tensors="pt").to(dev, dtype)
    with torch.no_grad(), gpu_job:
        # Greedy for short captions: twice as fast on a GTX 1650 and as good.
        ids = model.generate(**inp, max_new_tokens=96, num_beams=1 if detail == "short" else 2)
    raw = proc.batch_decode(ids, skip_special_tokens=False)[0]
    out = proc.post_process_generation(raw, task=task, image_size=img.size)[task]
    return " ".join(str(out).replace("<pad>", "").split())


# ---- translation ---------------------------------------------------------

def to_bangla(text):
    import torch
    tok_en, _, model = get("nllb")
    enc = tok_en(text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**enc, forced_bos_token_id=tok_en.convert_tokens_to_ids("ben_Beng"), max_new_tokens=160)
    return tok_en.batch_decode(out, skip_special_tokens=True)[0]


def to_english(text):
    import torch
    _, tok_bn, model = get("nllb")
    enc = tok_bn(text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**enc, forced_bos_token_id=tok_bn.convert_tokens_to_ids("eng_Latn"), max_new_tokens=40)
    return tok_bn.batch_decode(out, skip_special_tokens=True)[0]


# ---- colour --------------------------------------------------------------

def colour_name(image_bgr):
    """The main colour of an object crop, from pixels alone (no model)."""
    h, w = image_bgr.shape[:2]
    core = image_bgr[h // 5: h - h // 5, w // 5: w - w // 5]
    if core.size == 0:
        core = image_bgr
    hsv = cv2.cvtColor(core, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    hue, sat, val = hsv[:, 0] * 2, hsv[:, 1] / 255, hsv[:, 2] / 255
    coloured = (sat > 0.25) & (val > 0.2)
    if coloured.mean() < 0.3:
        v = float(np.median(val))
        return "black" if v < 0.25 else ("white" if v > 0.75 else "grey")
    hh, ss, vv = hue[coloured], sat[coloured], val[coloured]
    bins = [("red", 0, 15), ("orange", 15, 40), ("yellow", 40, 70), ("green", 70, 170),
            ("blue", 170, 260), ("purple", 260, 290), ("pink", 290, 340), ("red", 340, 361)]
    counts = {}
    for name, a, b in bins:
        counts[name] = counts.get(name, 0) + int(((hh >= a) & (hh < b)).sum())
    name = max(counts, key=counts.get)
    if name in ("orange", "red") and float(np.median(vv)) < 0.45:
        return "brown"
    return name


from .intent import OBJECTS_BN_EN  # noqa: E402  (shared with the router)


def query_for(spoken):
    """(english query, spoken name) for a spoken object name in either language."""
    s = spoken.strip(" ।?.!,")
    for bn, en in OBJECTS_BN_EN.items():
        if bn in s:
            return en, bn
    if any("ঀ" <= c <= "৿" for c in s):
        en = to_english(s).strip(" .").lower()
        for article in ("the ", "a ", "an "):
            if en.startswith(article):
                en = en[len(article):]
        return en, s
    return s.lower(), s


def preload(names=("ocr", "florence", "nllb")):
    """Loads the mode models in the background after start-up, so the first
    R, D or I press does not wait 10-30 s for a model to load."""
    def run():
        for n in names:
            try:
                get(n)
            except Exception as e:
                print(f"preload {n} failed:", repr(e))
    threading.Thread(target=run, daemon=True).start()
