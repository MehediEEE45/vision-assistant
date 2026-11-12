"""The OS-dependent parts of the laptop assistant live here."""

import os
import platform
import shutil
import subprocess
from pathlib import Path


def camera_backends(cv2, system=None):
    system = system or platform.system()
    preferred = {"Darwin": cv2.CAP_AVFOUNDATION, "Windows": cv2.CAP_DSHOW}
    backend = preferred.get(system, cv2.CAP_ANY)
    return list(dict.fromkeys((backend, cv2.CAP_ANY)))


def torch_device(allow_mps=False):
    import torch
    requested = os.environ.get("VA_DEVICE", "auto").lower()
    if requested not in {"auto", "cpu", "cuda", "mps"}:
        raise ValueError("VA_DEVICE must be auto, cpu, cuda or mps")
    cuda = torch.cuda.is_available()
    mps = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    if requested == "cuda" and not cuda:
        raise RuntimeError("VA_DEVICE=cuda requested, but CUDA is unavailable")
    if requested == "mps" and not mps:
        raise RuntimeError("VA_DEVICE=mps requested, but Apple Metal is unavailable")
    if requested != "auto":
        return requested
    if cuda:
        return "cuda"
    if allow_mps and mps:
        return "mps"
    return "cpu"


def english_audio_file(text, directory, system=None):
    """Render to a file so speech still passes through the interruptible mixer."""
    system = system or platform.system()
    directory = Path(directory)
    if system == "Darwin":
        out = directory / "english.aiff"
        subprocess.run(["/usr/bin/say", "-v", "Samantha", "-o", str(out), "--", text],
                       check=True, timeout=120)
        return out
    if system == "Windows":
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
            out = directory / "english.wav"
            stream.Open(str(out), SpeechLib.SSFMCreateForWrite)
            try:
                voice.AudioOutputStream = stream
                voice.Speak(text)
            finally:
                stream.Close()
            return out
        finally:
            comtypes.CoUninitialize()
    engine = shutil.which("espeak-ng") or shutil.which("espeak")
    if not engine:
        raise RuntimeError("English speech needs macOS say, Windows SAPI, or espeak-ng")
    out = directory / "english.wav"
    subprocess.run([engine, "-w", str(out), "--", text], check=True, timeout=120)
    return out
