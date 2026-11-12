import numpy as np
import pytest

from va_lab import audio_io, tts


def test_silent_native_output_is_not_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(tts, "_mem", {})
    monkeypatch.setattr(tts, "_english", lambda _: np.zeros(1600, np.float32))
    with pytest.raises(RuntimeError, match="silent audio"):
        tts.synth("test", "en")
    assert not list(tmp_path.glob("*.wav"))


def test_silent_old_cache_is_regenerated(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(tts, "_mem", {})
    _, path = tts._key_path("test", "en")
    audio_io.save_wav(path, np.zeros(1600, np.float32))
    generated = np.full(1600, 0.1, np.float32)
    monkeypatch.setattr(tts, "_english", lambda _: generated)
    assert np.allclose(tts.synth("test", "en"), generated)
    assert np.any(audio_io.load_wav(path))
