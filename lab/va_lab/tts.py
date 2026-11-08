"""Speech for arbitrary text, offline: Bangla with MMS-TTS, English with the
Windows voice. Used for what no recorded prompt can cover: text read from a
page, a description, an object's name.

Results are cached in memory and on disk (models/tts_cache), so a phrase is
synthesised once ever.
"""

import hashlib
import re
import tempfile
import threading
from pathlib import Path

import numpy as np

from . import audio_io, config

CACHE_DIR = config.MODELS / "tts_cache"
_mem = {}
_lock = threading.Lock()

BANGLA_CHARS = re.compile(r"[ঀ-৿]")


def is_bangla(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if BANGLA_CHARS.match(c)) / len(letters) > 0.4


def _english(text):
    """Windows SAPI to a 16 kHz WAV, in-process. Offline."""
    import comtypes
    import comtypes.client
    comtypes.CoInitialize()
    try:
        voice = comtypes.client.CreateObject("SAPI.SpVoice")
        from comtypes.gen import SpeechLib
        stream = comtypes.client.CreateObject("SAPI.SpFileStream")
        fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
        fmt.Type = SpeechLib.SAFT16kHz16BitMono
        stream.Format = fmt
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "en.wav")
            stream.Open(path, SpeechLib.SSFMCreateForWrite)
            voice.AudioOutputStream = stream
            voice.Speak(text)
            stream.Close()
            x = audio_io.load_wav(path)
    finally:
        comtypes.CoUninitialize()
    peak = float(np.max(np.abs(x))) if len(x) else 1.0
    return (x / (peak or 1.0) * 0.9).astype(np.float32)


def _key_path(text, lang):
    text = " ".join(str(text).split())
    lang = lang or ("bn" if is_bangla(text) else "en")
    return (lang, text), CACHE_DIR / f"{lang}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}.wav"


def cached(text, lang=None):
    """True when synth() would return at once (no model call)."""
    key, path = _key_path(text, lang)
    return not key[1] or key in _mem or path.exists()


def synth(text, lang=None):
    """float32 16 kHz audio for `text`; lang "bn"/"en", detected if None."""
    text = " ".join(str(text).split())
    if not text:
        return np.zeros(1, np.float32)
    lang = lang or ("bn" if is_bangla(text) else "en")
    key = (lang, text)
    with _lock:
        if key in _mem:
            return _mem[key]
    path = CACHE_DIR / f"{lang}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}.wav"
    if path.exists():
        x = audio_io.load_wav(path)
    else:
        if lang == "bn":
            from . import bangla_voice
            x = bangla_voice.synthesize(text)
        else:
            x = _english(text)
        audio_io.save_wav(path, x)
    with _lock:
        _mem[key] = x
    return x


def warm(texts):
    """Synthesise a list ahead of time, e.g. every fixed phrase at start-up."""
    for t, lang in texts:
        synth(t, lang)
