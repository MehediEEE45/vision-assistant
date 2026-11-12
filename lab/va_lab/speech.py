"""Everything the laptop says goes through Speaker, as on the wearable.

Same ladder as the firmware's speaker.cpp and the app's OutputArbiter:
hazard > manoeuvre > answer > ambient > long-form reading. A hazard cuts
anything off; ambient news is dropped when something else is playing; reading
never interrupts anything and resumes at a sentence boundary.

One output stream mixes two layers, so a guidance ping never cuts speech:
  speech  one utterance at a time (recorded prompts, tones, synthesised text)
  effects short stereo cues (nudges, pings) laid on top

Utterance items:
  "PROMPT_ID"                 a recorded prompt (firmware/stm32h743/prompts)
  ("tone", name)              an earcon
  ("pause", ms)
  ("text", bangla, english)   synthesised in the current language (tts.py)
  ("audio", array, caption)   ready-made audio, e.g. a sentence being read
"""

import itertools
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd

from . import audio_io, config

SR = config.SAMPLE_RATE

HAZARD, MANEUVER, ANSWER, AMBIENT, LONGFORM = 0, 1, 2, 3, 4

TONES = {
    # name: (f0, f1, ms, gap_ms, repeats, level) as in the firmware's kTones
    "warn": (1400, 1400, 70, 50, 2, 0.7),
    "listen": (600, 1000, 120, 0, 1, 0.5),
    "ok": (880, 880, 80, 0, 1, 0.45),
    "error": (330, 260, 250, 0, 1, 0.6),
    "boot": (520, 1040, 300, 0, 1, 0.45),
    "alarm": (900, 1400, 400, 0, 6, 1.0),
    # one earcon per laptop mode, so the mode is known before any word
    "read": (700, 500, 90, 40, 2, 0.45),
    "find": (1200, 1200, 40, 120, 2, 0.4),
    "describe": (500, 900, 200, 0, 1, 0.45),
    "identify": (1000, 1000, 25, 60, 3, 0.45),
    "shutter": (1800, 900, 60, 0, 1, 0.5),
}

_ids = itertools.count(1)


def _tone(name):
    f0, f1, ms, gap, reps, level = TONES[name]
    n = int(SR * ms / 1000)
    out = []
    for r in range(reps):
        f = np.full(n, f0 if r % 2 == 0 else f1) if name == "alarm" else np.linspace(f0, f1, n)
        phase = 2 * np.pi * np.cumsum(f) / SR
        env = np.minimum(1.0, np.minimum(np.arange(n), n - 1 - np.arange(n)) / 80.0)
        out.append(level * np.sin(phase) * env)
        out.append(np.zeros(int(SR * gap / 1000)))
    return np.concatenate(out).astype(np.float32)


@dataclass
class Utterance:
    priority: int
    items: list = field(default_factory=list)
    tag: str = ""
    id: int = field(default_factory=lambda: next(_ids))


class Speaker:
    def __init__(self, bangla=config.DEFAULT_BANGLA, volume=config.VOLUME):
        self.prompts = config.load_prompts()
        self.bangla = bangla
        self.volume = volume
        self._cache = {}
        self._lock = threading.Lock()
        self._speech = np.zeros(0, np.float32)
        self._pos = 0
        self._effects = []                 # [array (n, 2), position]
        self._current = None
        self._bounds = []
        self._queue = []                   # utterances waiting their turn
        self._ready = []                   # synthesised on a worker, waiting to be offered
        self._pending = 0
        self._generation = 0
        self._prepare_lock = threading.Lock()
        import queue
        self._synth_q = queue.Queue()
        threading.Thread(target=self._synth_worker, daemon=True).start()
        self.status = {}                   # utterance id -> "playing" / "done" / "cut" / "dropped"
        self.last = None
        self.log = []
        self._stream = sd.OutputStream(samplerate=SR, channels=2, dtype="float32", blocksize=256,
                                       callback=self._callback)
        self._stream.start()

    # ---- assets --------------------------------------------------------

    def has_bangla(self, pid):
        return (config.PROMPT_WAVS / "bn" / f"{pid}.wav").exists()

    def missing_bangla(self):
        return [p for p, t in self.prompts.items() if t["bn"].strip() and not self.has_bangla(p)]

    def _lang_for(self, pid):
        return "bn" if self.bangla and self.has_bangla(pid) else "en"

    def _clip(self, item):
        if isinstance(item, tuple):
            kind = item[0]
            if kind == "tone":
                return _tone(item[1])
            if kind == "pause":
                return np.zeros(int(SR * item[1] / 1000), np.float32)
            if kind == "text":
                from . import tts
                return tts.synth(item[1] if self.bangla else item[2], "bn" if self.bangla else "en")
            if kind == "audio":
                return np.asarray(item[1], np.float32)
            raise ValueError(item)
        key = (self._lang_for(item), item)
        if key not in self._cache:
            path = config.PROMPT_WAVS / key[0] / f"{item}.wav"
            x = audio_io.load_wav(path)
            peak = float(np.max(np.abs(x))) or 1.0
            self._cache[key] = (x / peak * 0.9).astype(np.float32)
        return self._cache[key]

    def caption(self, item):
        """Text of an item in the language actually heard ("" for tones)."""
        if isinstance(item, tuple):
            if item[0] == "text":
                return item[1] if self.bangla else item[2]
            if item[0] == "audio":
                return item[2]
            return ""
        t = self.prompts.get(item, {"en": item, "bn": ""})
        return t["bn"] if self._lang_for(item) == "bn" else t["en"]

    # ---- the mixer -----------------------------------------------------

    def _callback(self, out, frames, time_info, status):
        out.fill(0)
        with self._lock:
            n = min(frames, len(self._speech) - self._pos)
            if n > 0:
                chunk = self._speech[self._pos:self._pos + n] * self.volume
                out[:n, 0] += chunk
                out[:n, 1] += chunk
                self._pos += n
            keep = []
            for fx in self._effects:
                arr, pos = fx
                m = min(frames, len(arr) - pos)
                out[:m] += arr[pos:pos + m] * self.volume
                fx[1] += m
                if fx[1] < len(arr):
                    keep.append(fx)
            self._effects = keep
        np.clip(out, -1.0, 1.0, out=out)

    def busy(self):
        with self._lock:
            return self._pos < len(self._speech)

    def _render(self, u):
        parts, bounds, t = [], [], 0.0
        for item in u.items:
            clip = self._clip(item)
            parts.append(clip)
            bounds.append((t, t + len(clip) / SR, item))
            t += len(clip) / SR
            if not (isinstance(item, tuple) and item[0] in ("tone", "pause")):
                parts.append(np.zeros(int(0.06 * SR), np.float32))
                t += 0.06
        audio = np.concatenate(parts) if parts else np.zeros(1, np.float32)
        fade = min(64, len(audio))
        audio[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
        return audio, bounds

    def _start(self, u):
        audio, bounds = self._render(u)  # may synthesise: outside the lock
        with self._lock:
            if self._current is not None and self._pos < len(self._speech):
                self.status[self._current.id] = "cut"
            self._speech, self._pos = audio, 0
            self._current, self._bounds = u, bounds
            self._started = time.monotonic()
        self.status[u.id] = "playing"
        text = " ".join(self.caption(i) for i in u.items if self.caption(i))
        self.log.append((time.strftime("%H:%M:%S"), u.priority, text))
        if u.priority <= ANSWER and any(not isinstance(i, tuple) or i[0] == "text" for i in u.items):
            self.last = u

    def _needs_synthesis(self, u):
        from . import tts
        lang = "bn" if self.bangla else "en"
        return [(i[1] if self.bangla else i[2], lang) for i in u.items
                if isinstance(i, tuple) and i[0] == "text" and not tts.cached(i[1] if self.bangla else i[2], lang)]

    def say(self, u: Utterance):
        """Plays now, after the current utterance, or not at all, by priority.

        Text not yet synthesised is synthesised on a worker thread first (a
        new Bangla sentence takes about a second), and the utterance is then
        offered again: the camera loop never waits for a voice."""
        todo = self._needs_synthesis(u)
        # Hazards and turns are recorded prompts: they never wait in line.
        with self._prepare_lock:
            generation = self._generation
            prepare = todo or (self._pending and u.priority >= ANSWER)
            if prepare:
                self.status[u.id] = "preparing"
                self._pending += 1
                self._synth_q.put((generation, u, todo))
        if prepare:
            # One worker, first in first out: sentences come out in the order
            # they were said, and a cached one never jumps ahead of a slow one.
            return u.id
        return self._offer(u)

    def _synth_worker(self):
        from . import tts
        while True:
            job = self._synth_q.get()
            if job is None:
                self._synth_q.task_done()
                return
            generation, u, todo = job
            try:
                for text, lang in todo:
                    if generation != self._generation:
                        break
                    tts.synth(text, lang)
                with self._prepare_lock:
                    if generation == self._generation:
                        self._ready.append(u)
                    else:
                        self.status[u.id] = "dropped"
            except Exception as e:
                print("speech synthesis failed:", repr(e))
                self.status[u.id] = "dropped"
            finally:
                with self._prepare_lock:
                    if generation == self._generation:
                        self._pending -= 1
                self._synth_q.task_done()

    def _offer(self, u):
        playing = self.busy() and self._current is not None
        if playing:
            cur = self._current
            same_tag = u.tag and u.tag == cur.tag and u.priority == cur.priority
            if u.priority < cur.priority or same_tag:
                # The interrupted answer is not lost: a less urgent utterance
                # still waiting keeps its place, as in the firmware's pending
                # slots. Only a newer one with the same tag replaces it.
                self._queue = [q for q in self._queue if not (u.tag and q.tag == u.tag)]
                self._start(u)
            elif u.priority == AMBIENT:
                self.status[u.id] = "dropped"
            else:
                self._queue = [q for q in self._queue if not (u.tag and q.tag == u.tag)]
                self._queue.append(u)
                self.status[u.id] = "queued"
            return u.id
        self._start(u)
        return u.id

    def poll(self):
        """Call every frame: marks finished speech and starts the next in line."""
        while self._ready:
            self._offer(self._ready.pop(0))
        if self._current is not None and not self.busy() and self.status.get(self._current.id) == "playing":
            self.status[self._current.id] = "done"
        if not self.busy() and self._queue:
            self._queue.sort(key=lambda q: q.priority)
            self._start(self._queue.pop(0))

    def stop(self):
        with self._prepare_lock:
            self._generation += 1
            self._pending = 0
            for uid, state in list(self.status.items()):
                if state == "preparing":
                    self.status[uid] = "dropped"
            for u in self._ready:
                self.status[u.id] = "dropped"
            self._ready = []
        with self._lock:
            if self._current is not None and self._pos < len(self._speech):
                self.status[self._current.id] = "cut"
            self._speech, self._pos = np.zeros(0, np.float32), 0
            self._effects = []
        for q in self._queue:
            self.status[q.id] = "dropped"
        self._queue = []

    def repeat(self):
        if self.last:
            self.say(Utterance(ANSWER, list(self.last.items)))

    # ---- spatial cues --------------------------------------------------

    def _effect(self, mono, pan):
        """pan -1 = left ear only, 0 = both, +1 = right ear only."""
        left = mono * min(1.0, 1.0 - pan)
        right = mono * min(1.0, 1.0 + pan)
        with self._lock:
            self._effects.append([np.stack([left, right], axis=1).astype(np.float32), 0])

    def nudge(self, side):
        """Two ticks in one ear: the laptop's left/right vibration motor."""
        n = int(0.05 * SR)
        tick = 0.6 * np.sin(2 * np.pi * 1200 * np.arange(n) / SR) * np.hanning(n)
        self._effect(np.concatenate([tick, np.zeros(int(0.06 * SR)), tick]), -1.0 if side < 0 else 1.0)

    def ping(self, pan, pitch=1.0, level=0.35):
        """One short sonar ping, panned towards the object; higher pitch when centred."""
        n = int(0.06 * SR)
        f = 900 * pitch
        p = level * np.sin(2 * np.pi * f * np.arange(n) / SR) * np.exp(-np.arange(n) / (0.02 * SR))
        self._effect(p, float(np.clip(pan, -1, 1)))

    def now_playing(self):
        """(utterance, index of the item playing, active) for captions."""
        if self._current is None:
            return None, -1, False
        with self._lock:
            t = self._pos / SR
            active = self._pos < len(self._speech)
        idx = len(self._bounds) - 1
        for i, (a, b, _) in enumerate(self._bounds):
            if t < b:
                idx = i
                break
        return self._current, idx, active

    def close(self):
        self.stop()
        self._synth_q.put(None)
        self._stream.stop()
        self._stream.close()
