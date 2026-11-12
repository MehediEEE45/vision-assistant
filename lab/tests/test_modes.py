import threading
from types import SimpleNamespace

import pytest

from va_lab import modes


def app_stub():
    spoken = []
    speaker = SimpleNamespace(say=lambda u: spoken.append(u) or u.id, busy=lambda: False, status={1: "done"})
    return SimpleNamespace(speaker=speaker), spoken


def test_final_sentence_finishes_read_mode():
    app, spoken = app_stub()
    mode = modes.ReadMode(app)
    mode.state, mode.sentences, mode.idx, mode.uid = "reading", [(0, "A paragraph.")], 0, 1
    mode._advance()
    assert mode.state == "finished"
    assert mode.done
    assert spoken[-1].tag == "read_done"


@pytest.mark.parametrize("mode_class", [modes.DescribeMode, modes.IdentifyMode])
def test_exited_background_mode_cannot_speak(mode_class):
    app, spoken = app_stub()
    mode = mode_class(app)
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def job():
        started.set()
        assert release.wait(3)
        mode.say_text("সামনে চেয়ার।", "A chair is ahead.")
        finished.set()
    mode.run_async(job)
    assert started.wait(3)
    mode.exit()
    release.set()
    assert finished.wait(3)
    assert not spoken


def test_cancelled_job_error_does_not_announce_camera_fault():
    app, spoken = app_stub()
    mode = modes.DescribeMode(app)
    mode.exit()
    finished = threading.Event()
    def job():
        try:
            raise RuntimeError("model failure after cancellation")
        finally:
            finished.set()
    mode.run_async(job)
    assert finished.wait(3)
    with mode._output_lock:
        assert not spoken


def test_new_page_gets_new_reader_and_worker_state():
    app, _ = app_stub()
    entered = []
    app.set_mode = entered.append
    mode = modes.ReadMode(app)
    assert mode.on_intent("read", None)
    assert len(entered) == 1
    assert isinstance(entered[0], modes.ReadMode)
    assert entered[0] is not mode
    assert not entered[0].done


def test_stop_cancels_listening_and_mode():
    from va_lab.assistant import Assistant
    app = Assistant.__new__(Assistant)
    events = []
    app.mode = modes.DescribeMode(app)
    old = app.mode
    app.speaker = SimpleNamespace(stop=lambda: events.append(("stop", old._cancelled.is_set())), say=lambda _: None)
    app.mic = SimpleNamespace(stop=lambda: events.append("mic stopped"))
    app.speech_in = SimpleNamespace(cancel=lambda: events.append("asr cancelled"))
    app._listen_at = 123
    app.stop_all()
    assert app.mode.name == "idle"
    assert app._listen_at is None
    assert "asr cancelled" in events
    assert ("stop", True) in events
