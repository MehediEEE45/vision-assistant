import threading
from types import SimpleNamespace

from va_lab import bangla_voice, speech, tts


def test_stop_discards_speech_still_being_synthesized(monkeypatch):
    import numpy as np
    monkeypatch.setattr(speech.sd, "OutputStream", lambda **_: SimpleNamespace(start=lambda: None, stop=lambda: None, close=lambda: None))
    started, release, drained = threading.Event(), threading.Event(), threading.Event()
    def synth(*_):
        started.set()
        assert release.wait(3)
        return np.ones(1600, dtype=np.float32)
    monkeypatch.setattr(tts, "cached", lambda *_: False)
    monkeypatch.setattr(tts, "synth", synth)
    speaker = speech.Speaker()
    task_done = speaker._synth_q.task_done
    def mark_done():
        task_done()
        drained.set()
    monkeypatch.setattr(speaker._synth_q, "task_done", mark_done)
    u = speech.Utterance(speech.ANSWER, [("text", "পরীক্ষা", "Test")])
    try:
        speaker.say(u)
        assert started.wait(3)
        speaker.stop()
        release.set()
        assert drained.wait(3)
        speaker.poll()
        assert speaker.status[u.id] == "dropped"
        assert not speaker.busy()
        assert speaker._pending == 0
        assert not speaker._ready
    finally:
        release.set()
        speaker.close()


def test_cancel_discards_in_flight_recognition(monkeypatch):
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(bangla_voice.audio_io, "MicListener", lambda _: SimpleNamespace(stop=lambda: None, poll=lambda: None, listening=False))
    def transcribe(*_, **__):
        started.set()
        assert release.wait(3)
        return "emergency"
    monkeypatch.setattr(bangla_voice, "transcribe", transcribe)
    listener = bangla_voice.Listener()
    worker = threading.Thread(target=listener._work, args=([0.1], "en", 0))
    worker.start()
    assert started.wait(3)
    listener.cancel()
    release.set()
    worker.join(3)
    assert not worker.is_alive()
    assert listener.poll() is None
