import sys
from types import SimpleNamespace

import pytest

from va_lab import platform_support, vision


@pytest.mark.parametrize("system,expected", [("Darwin", [1200, 0]), ("Windows", [700, 0]), ("Linux", [0])])
def test_camera_backend_for_each_os(system, expected):
    cv = SimpleNamespace(CAP_AVFOUNDATION=1200, CAP_DSHOW=700, CAP_ANY=0)
    assert platform_support.camera_backends(cv, system) == expected


def test_camera_falls_back_and_releases_failed_backend(monkeypatch):
    import cv2
    calls = []
    class Capture:
        def __init__(self, index, backend):
            self.backend = backend
            calls.append((index, backend))
        def isOpened(self):
            return self.backend == cv2.CAP_ANY
        def release(self):
            calls.append("released")
        def set(self, *_):
            pass
    monkeypatch.setattr(vision, "camera_backends", lambda _: [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY])
    monkeypatch.setattr(cv2, "VideoCapture", Capture)
    cap = vision.open_camera(2)
    assert calls == [(2, cv2.CAP_AVFOUNDATION), "released", (2, cv2.CAP_ANY)]
    assert cap.isOpened()


def test_mac_speech_renders_file_without_shell(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(platform_support.subprocess, "run", lambda args, **kw: calls.append((args, kw)))
    text = "This is a quote: 'hello'; $(literal text)."
    out = platform_support.english_audio_file(text, tmp_path, "Darwin")
    assert out == tmp_path / "english.aiff"
    args, kwargs = calls[0]
    assert args[-2:] == ["--", text]
    assert kwargs["check"] is True
    assert "shell" not in kwargs


def test_windows_speech_uses_sapi_and_closes_stream(monkeypatch, tmp_path):
    calls = []
    stream = SimpleNamespace(Open=lambda *args: calls.append(("open", args)), Close=lambda: calls.append("close"))
    voice = SimpleNamespace(Speak=lambda text: calls.append(("speak", text)))
    fmt = SimpleNamespace()
    objects = {"SAPI.SpVoice": voice, "SAPI.SpFileStream": stream, "SAPI.SpAudioFormat": fmt}
    client = SimpleNamespace(CreateObject=lambda name: objects[name])
    com = SimpleNamespace(client=client, CoInitialize=lambda: calls.append("init"), CoUninitialize=lambda: calls.append("uninit"))
    monkeypatch.setitem(sys.modules, "comtypes", com)
    monkeypatch.setitem(sys.modules, "comtypes.client", client)
    monkeypatch.setitem(sys.modules, "comtypes.gen", SimpleNamespace(SpeechLib=SimpleNamespace(SAFT16kHz16BitMono=18, SSFMCreateForWrite=3)))
    assert platform_support.english_audio_file("hello", tmp_path, "Windows") == tmp_path / "english.wav"
    assert calls[-3:] == [("speak", "hello"), "close", "uninit"]
    assert fmt.Type == 18


def test_cpu_device_override(monkeypatch):
    monkeypatch.setenv("VA_DEVICE", "cpu")
    assert platform_support.torch_device(allow_mps=True) == "cpu"


def test_invalid_device_is_explained(monkeypatch):
    monkeypatch.setenv("VA_DEVICE", "bad-device")
    with pytest.raises(ValueError, match="VA_DEVICE"):
        platform_support.torch_device()


def test_bangla_conversion_uses_python_api(monkeypatch, tmp_path):
    from va_lab import bangla_voice
    import ctranslate2.converters
    from transformers import WhisperTokenizerFast
    calls = []
    class Converter:
        def __init__(self, name, **kwargs):
            calls.append((name, kwargs))
        def convert(self, out, **kwargs):
            calls.append((out, kwargs))
    monkeypatch.setattr(ctranslate2.converters, "TransformersConverter", Converter)
    monkeypatch.setattr(WhisperTokenizerFast, "from_pretrained", lambda _: SimpleNamespace(save_pretrained=lambda out: calls.append(("tokenizer", out))))
    monkeypatch.setattr(bangla_voice.config, "MODELS", tmp_path)
    assert bangla_voice.ensure_ct2_bangla() == tmp_path / "banglaasr-ct2"
    assert calls[1][1] == {"quantization": "int8_float32", "force": True}
