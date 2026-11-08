"""Microphone and speaker on the laptop, at the wearable's 16 kHz mono."""

import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import resample_poly

from . import config

SR = config.SAMPLE_RATE


def devices():
    """Input and output devices, with the defaults marked."""
    return sd.query_devices()


def load_wav(path, sr=SR):
    x, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if file_sr != sr:
        g = np.gcd(int(file_sr), int(sr))
        x = resample_poly(x, sr // g, file_sr // g).astype(np.float32)
    return x


def save_wav(path, x, sr=SR):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(x, -1.0, 1.0), sr, subtype="PCM_16")


def record(seconds, sr=SR):
    """Blocking recording from the default microphone, float32 mono."""
    x = sd.rec(int(seconds * sr), samplerate=sr, channels=1, dtype="float32")
    sd.wait()
    return x[:, 0]


def dbfs(x):
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    return -96.0 if peak <= 0 else 20.0 * np.log10(peak)


def loudest_second(x, sr=SR):
    """The one-second stretch with the most energy: where the word is."""
    if len(x) <= sr:
        return np.pad(x, (0, sr - len(x)))
    step = sr // 20
    energy = np.convolve(x.astype(np.float64) ** 2, np.ones(sr), mode="valid")[::step]
    start = int(np.argmax(energy)) * step
    return x[start:start + sr]


class MicListener:
    """Non-blocking push-to-talk: start(), then poll() until it returns audio.

    The stream opens only for the listening window, so the microphone is
    not live the rest of the time.
    """

    def __init__(self, seconds=config.KWS_LISTEN_S, sr=SR):
        self.n = int(seconds * sr)
        self.sr = sr
        self._buf = []
        self._have = 0
        self._stream = None
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status):
        with self._lock:
            if self._have < self.n:
                self._buf.append(indata[:, 0].copy())
                self._have += frames

    def start(self):
        self.stop()
        self._buf, self._have = [], 0
        self._stream = sd.InputStream(samplerate=self.sr, channels=1, dtype="float32",
                                      callback=self._callback)
        self._stream.start()

    @property
    def listening(self):
        return self._stream is not None

    def poll(self):
        if self._stream is None:
            return None
        with self._lock:
            if self._have < self.n:
                return None
            x = np.concatenate(self._buf)[: self.n]
        self.stop()
        return x

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
