"""The four laptop modes: Read, Find, Describe, Identify.

One mode at a time. Each mode is entered with its own earcon, so the user
knows which mode it is before a word is spoken. Heavy work (OCR, captions,
translation) runs on a worker thread, so the camera window, the obstacle
warnings and the stop key never freeze. Every generated sentence goes
through safety.clean() before it is spoken.
"""

import threading
import time

import numpy as np

from . import announce, config, phrases, safety, tts, understand
from .ocr import check as ocr_check, reading_order, sentences
from .speech import ANSWER, LONGFORM, Utterance

PRIORITY_OBJECTS = ("person", "door", "rickshaw", "cng")


def _strip(t):
    return t.strip().rstrip("।.").strip()


class Mode:
    name = "idle"
    tone = None

    def __init__(self, app):
        self.app = app
        self.done = False
        self._cancelled = threading.Event()
        self._output_lock = threading.RLock()

    # helpers
    @property
    def bangla(self):
        return self.app.speaker.bangla

    def say_key(self, key, priority=ANSWER, tag=""):
        if self._cancelled.is_set():
            return None
        bn, en = phrases.P[key]
        return self._say(Utterance(priority, [("text", bn, en)], tag=tag or key))

    def _say(self, utterance):
        with self._output_lock:
            if not self._cancelled.is_set():
                return self.app.speaker.say(utterance)

    def say_text(self, bn, en, priority=ANSWER, tag=""):
        """Speaks generated text sentence by sentence, so the first sentence
        starts while the rest are still being synthesised."""
        if self._cancelled.is_set():
            return None
        bn, en = safety.clean(bn), safety.clean(en)
        bs, es = safety.sentences(bn), safety.sentences(en)
        if not (bs if self.bangla else es):
            return None
        n = max(len(bs), len(es))
        uid = None
        for i in range(n):
            if self._cancelled.is_set():
                break
            b = bs[i] if i < len(bs) else ""
            e = es[i] if i < len(es) else ""
            if (b if self.bangla else e).strip():
                uid = self._say(Utterance(priority, [("text", b, e)], tag=f"{tag}{i}" if tag else ""))
        return uid

    def run_async(self, fn):
        def wrap():
            try:
                fn()
            except Exception as e:  # a failed model must not kill the assistant
                print("mode error:", repr(e))
                if not self._cancelled.is_set():
                    self._say(Utterance(ANSWER, [("tone", "error"), "CAMERA_FAULT"]))
                self.done = True
        threading.Thread(target=wrap, daemon=True).start()

    # lifecycle
    def enter(self):
        pass

    def step(self, frame, dets, now):
        pass

    def exit(self):
        with self._output_lock:
            self._cancelled.set()
            self.done = True

    def on_intent(self, it, detail):
        return False

    def on_key(self, ch):
        return False

    def status(self):
        return self.name.upper()


# ---------------------------------------------------------------------------

class ReadMode(Mode):
    """Aim (guided), capture, OCR, then read sentence by sentence at long-form
    priority: anything more urgent interrupts, and reading resumes at the
    start of the sentence that was cut."""

    name = "read"
    warned = False  # the "offline reading may contain mistakes" notice, once per session

    def enter(self):
        self.state = "aim"
        self.app.speaker.say(Utterance(ANSWER, [("tone", "read"), ("text", *phrases.P["mode_read"])], tag="mode"))
        self.good = 0
        self.last_check = 0.0
        self.last_hint = None
        self.last_hint_t = 0.0
        self.aim_since = time.monotonic()
        self.sentences = []   # (paragraph index, text)
        self.audio = {}
        self.idx = 0
        self.uid = None
        self.paused = False
        self._hint_ready = False
        if not getattr(self, "_aim_thread", None):
            self._aim_thread = threading.Thread(target=self._aim_worker, daemon=True)
            self._aim_thread.start()

    def step(self, frame, dets, now):
        if self.state == "aim" and getattr(self, "_hint_ready", False):
            self._hint_ready = False
            hint = self._hint
            if hint is None:
                self.good += 1
                if self.good >= 2:
                    self._capture(self._frame)
                return
            self.good = 0
            if hint == "cap_no_text" and now - self.aim_since < 3.0:
                return
            if hint != self.last_hint or now - self.last_hint_t > 3.5:
                self.say_key(hint, tag="aim")
                self.last_hint, self.last_hint_t = hint, now
        elif self.state == "reading" and not self.paused:
            self._advance()

    def _aim_worker(self):
        """Text-box detection on the latest frame, off the camera loop."""
        while not self.done and self.state != "finished":
            if self.state == "aim" and not self.app.speaker.busy() and self.app.last_frame is not None:
                frame = self.app.last_frame.copy()
                try:
                    self._hint = ocr_check(frame, understand.get("ocr").boxes(frame))
                    self._frame = frame
                    self._hint_ready = True
                except Exception as e:
                    print("aiming check failed:", repr(e))
            time.sleep(0.3)

    def _capture(self, frame):
        self.state = "ocr"
        self.app.speaker.say(Utterance(ANSWER, [("tone", "shutter"), ("text", *phrases.P["cap_ok"])], tag="aim"))

        def work():
            res = understand.get("ocr").read(frame)
            if self._cancelled.is_set():
                return
            paras = reading_order(res)
            self.sentences = [(pi, s) for pi, p in enumerate(paras) for s in sentences(p)]
            if not self.sentences:
                self.say_key("read_none")
                self.state = "aim"
                self.aim_since = time.monotonic()
                return
            self.idx = 0
            self.audio = {}
            threading.Thread(target=self._synth_ahead, daemon=True).start()
            if not ReadMode.warned and any(tts.is_bangla(s) for _, s in self.sentences):
                ReadMode.warned = True
                self.say_key("ocr_warning")
            print("read:", [s for _, s in self.sentences])
            self.state = "reading"
        self.run_async(work)

    def _synth_ahead(self):
        for i, (_, s) in enumerate(self.sentences):
            if self.state not in ("reading", "ocr") or self.done:
                return
            while i > self.idx + 3 and not self.done:
                time.sleep(0.1)
            if self._cancelled.is_set():
                return
            try:
                audio = tts.synth(s)
            except Exception as e:
                print("reading synthesis failed:", repr(e))
                if not self._cancelled.is_set():
                    self.say_key("read_none")
                    self.done = True
                return
            if not self._cancelled.is_set():
                self.audio[i] = audio

    def _advance(self):
        sp = self.app.speaker
        if sp.busy():
            return
        st = sp.status.get(self.uid) if self.uid else None
        if st == "done":
            self.idx += 1
            self.uid = None
        elif st in ("cut", "dropped"):
            self.uid = None  # say the same sentence again
        elif st in ("playing", "queued", "preparing"):
            return
        if self.idx >= len(self.sentences):
            self.state = "finished"
            self.say_key("read_done")
            self.done = True
            return
        if self.idx not in self.audio:
            return  # still synthesising
        text = self.sentences[self.idx][1]
        self.uid = sp.say(Utterance(LONGFORM, [("audio", self.audio[self.idx], text)], tag="read"))

    def _jump_paragraph(self, delta):
        if not self.sentences:
            return
        cur = self.sentences[min(self.idx, len(self.sentences) - 1)][0]
        target = max(0, cur + delta)
        if delta < 0 and cur == 0:
            self.say_key("read_first")
        firsts = [i for i, (p, _) in enumerate(self.sentences) if p == target]
        if firsts:
            self.app.speaker.stop()
            self.idx, self.uid, self.paused = firsts[0], None, False
            self.state = "reading"

    def on_intent(self, it, detail):
        if it == "pause" and self.state == "reading":
            self.paused = True
            self.app.speaker.stop()
            self.uid = None
            self.say_key("read_paused")
            return True
        if it == "resume":
            self.paused = False
            return True
        if it == "next":
            self._jump_paragraph(+1)
            return True
        if it == "previous":
            self._jump_paragraph(-1)
            return True
        if it == "repeat" and self.sentences:
            self._jump_paragraph(0)
            return True
        if it == "read":
            self.app.set_mode(ReadMode(self.app))
            return True
        return False

    def on_key(self, ch):
        return self.on_intent({"p": "pause" if not self.paused else "resume", ".": "next",
                               ",": "previous", "r": "read"}.get(ch, ""), None)

    def exit(self):
        super().exit()

    def status(self):
        if self.state == "reading":
            return f"READ {self.idx + 1}/{len(self.sentences)}" + (" (paused)" if self.paused else "")
        return f"READ: {self.state}"


# ---------------------------------------------------------------------------

class FindMode(Mode):
    """Steer the user to one object: a ping in the ear on its side, faster and
    higher as it centres; words every few seconds; "lost" and "not found"."""

    name = "find"

    def __init__(self, app, obj=None, spoken=None):
        super().__init__(app)
        self.obj = obj           # one of config.OBJECTS, or None for free text
        self.spoken = spoken     # what the user said, for free text
        self.label, self.name_bn, self.name_en = obj or "target", "", ""
        self.track, self.side = None, None

    def enter(self):
        sp = self.app.speaker
        self.label = self.obj or "target"
        if self.obj:
            self.name_bn = _strip(sp.prompts[announce.obj_prompt(self.obj)]["bn"])
            self.name_en = _strip(sp.prompts[announce.obj_prompt(self.obj)]["en"]).lower()
        else:
            query, said = understand.query_for(self.spoken)
            if not self.app.detector.set_queries([query], "target"):
                self.say_key("find_unknown")
                self.done = True
                return
            self.name_bn, self.name_en = said if any("ঀ" <= c <= "৿" for c in said) else query, query
            print(f"find: '{self.spoken}' -> query '{query}'")
        self.name_item = announce.obj_prompt(self.obj) if self.obj else ("text", self.name_bn, self.name_en)
        sp.say(Utterance(ANSWER, [("tone", "find"), ("text", f"{self.name_bn} খুঁজছি। ধীরে ধীরে ঘুরুন।",
                                                     f"Searching for {self.name_en}. Turn slowly.")], tag="find"))
        now = time.monotonic()
        self.start = self.seen = now
        self.lost_said = False
        self.next_ping = 0.0
        self.spoke = now
        self.side = None
        self.track = None

    def step(self, frame, dets, now):
        mine = [d for d in dets if d.obj == self.label]
        if self.track is not None and any(d.track == self.track for d in mine):
            best = next(d for d in mine if d.track == self.track)
        else:
            best = max(mine, key=lambda d: d.score, default=None)
        if best is None:
            if now - self.seen > 2.0 and not self.lost_said and self.side is not None:
                self.lost_said = True
                self.say_key("find_lost", tag="find")
            if now - self.seen >= config.FIND_TIMEOUT_S:
                self.say_text(f"{self.name_bn} পাওয়া যায়নি।", f"{self.name_en} not found.", tag="find")
                self.done = True
            return
        self.track, self.seen, self.lost_said = best.track, now, False
        half = config.CAMERA_HFOV_DEG / 2
        pan = float(np.clip(best.angle_deg / half, -1, 1))
        centred = abs(best.angle_deg) <= config.FIND_AHEAD_DEG
        side = 0 if centred else (-1 if best.angle_deg < 0 else 1)
        if now >= self.next_ping:
            self.app.speaker.ping(0.0 if centred else pan, pitch=1.6 if centred else 1.0)
            near = min(1.0, max(0.0, (best.distance_m - 0.5) / 3.0))
            self.next_ping = now + (0.25 + 0.5 * near if centred else 0.45 + 0.4 * abs(pan))
        if (side != self.side and now - self.spoke > 1.2) or now - self.spoke > config.FIND_SPEECH_S:
            # Recorded prompts, not synthesis: guidance must be instant.
            items = [self.name_item, {-1: "ZONE_LEFT", 0: "ZONE_AHEAD", 1: "ZONE_RIGHT"}[side]]
            if centred:
                items.append(announce.distance_prompt(best.distance_m * 1000))
            self.app.speaker.say(Utterance(ANSWER, items, tag="find"))
            self.spoke = now
        self.side = side

    def exit(self):
        super().exit()
        self.app.detector.restore()

    def status(self):
        return f"FIND: {self.name_en if hasattr(self, 'name_en') else '...'}"


# ---------------------------------------------------------------------------

def scene_sentence(dets, prompts, max_objects=4):
    """Where things are, from the detector: exact, no translation needed."""
    def rank(d):
        return (0 if d.obj in PRIORITY_OBJECTS else 1, d.distance_m)
    seen, bn, en = set(), [], []
    for d in sorted(dets, key=rank):
        if d.obj in seen or len(seen) >= max_objects:
            continue
        # A camera facing the user sees the user: a person filling most of the
        # picture is them, not something in front of them.
        if config.CAMERA_FACES_USER and d.obj == "person" and d.box[3] - d.box[1] > 0.55 * config.CAMERA_HEIGHT:
            continue
        seen.add(d.obj)
        name_bn = _strip(prompts[announce.obj_prompt(d.obj)]["bn"]) if d.obj in config.OBJECTS else d.obj
        name_en = _strip(prompts[announce.obj_prompt(d.obj)]["en"]).lower() if d.obj in config.OBJECTS else d.obj
        side = 0 if abs(d.angle_deg) <= config.FIND_AHEAD_DEG else (-1 if d.angle_deg < 0 else 1)
        pid = announce.distance_prompt(d.distance_m * 1000)
        dist_bn, dist_en = _strip(prompts[pid]["bn"]), _strip(prompts[pid]["en"]).lower()
        bn.append(f"{ {-1: 'বাম দিকে', 0: 'সামনে', 1: 'ডান দিকে'}[side] } একটি {name_bn}, প্রায় {dist_bn} দূরে")
        en.append(f"a {name_en} { {-1: 'on the left', 0: 'ahead', 1: 'on the right'}[side] }, about {dist_en} away")
    if not bn:
        return "", ""
    return "; ".join(bn) + "।", ("; ".join(en) + ".").capitalize()


class DescribeMode(Mode):
    """One picture: where the known things are (exact), then a caption of the
    whole scene (Florence-2, translated by NLLB in Bangla)."""

    name = "describe"

    def enter(self):
        self.app.speaker.say(Utterance(ANSWER, [("tone", "describe"), ("text", *phrases.P["mode_describe"])], tag="mode"))
        frame, dets, dark = self.app.last_frame.copy(), list(self.app.detections), self.app.dark

        def work():
            prompts = self.app.speaker.prompts
            where_bn, where_en = scene_sentence(dets, prompts)
            if where_bn:
                self.say_text(where_bn, where_en, tag="describe")
            cap_en = understand.caption(frame, "detailed")
            if self._cancelled.is_set():
                return
            print("caption:", cap_en)
            # Translated and spoken a sentence at a time: the first is heard
            # while the next is still being translated.
            for i, sent in enumerate(safety.sentences(cap_en)):
                if self._cancelled.is_set():
                    return
                self.say_text(understand.to_bangla(sent) if self.bangla else "", sent, tag=f"describe{i}_")
            if dark:
                self.say_key("low_light", tag="describe3")
            self.done = True
        self.run_async(work)


# ---------------------------------------------------------------------------

class IdentifyMode(Mode):
    """The thing held in the middle: name, colour, and any text on it; then
    20 s for follow-up questions ("রং কী", "লেখা পড়ো")."""

    name = "identify"
    FOLLOW_UP_S = 20.0

    def enter(self):
        self.app.speaker.say(Utterance(ANSWER, [("tone", "identify")], tag="mode"))
        self.start = time.monotonic()
        self.state = "aim"
        self.result = None
        self.hinted = False

    def _centre_object(self, dets):
        cands = [d for d in dets if abs(d.angle_deg) <= 15]
        return max(cands, key=lambda d: (d.box[2] - d.box[0]) * (d.box[3] - d.box[1]), default=None)

    def step(self, frame, dets, now):
        if self.state == "aim":
            target = self._centre_object(dets)
            if target is None and now - self.start < 1.5:
                return
            if target is None and not self.hinted:
                self.hinted = True
                self.say_key("nothing_centre", tag="aim")
            h, w = frame.shape[:2]
            if target is not None:
                x1, y1, x2, y2 = target.box
                pad = 0.1 * max(x2 - x1, y2 - y1)
                box = (max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad))
            else:
                box = (w * 0.25, h * 0.2, w * 0.75, h * 0.8)  # the middle of the picture
            crop = frame[int(box[1]):int(box[3]), int(box[0]):int(box[2])].copy()
            self.state = "working"
            self.run_async(lambda: self._identify(crop, target))
        elif self.state == "answered" and now - self.answered_at > self.FOLLOW_UP_S:
            self.done = True

    def _identify(self, crop, target):
        cap_en = understand.caption(crop, "short").rstrip(".")
        if self._cancelled.is_set():
            return
        colour = understand.colour_name(crop)
        res = understand.get("ocr").read(crop)
        if self._cancelled.is_set():
            return
        text = " ".join(t for _, t, c in res if c > 0.3)
        cap_bn = understand.to_bangla(cap_en) if self.bangla else ""
        c_bn, c_en = phrases.COLOURS[colour]
        self.result = {"cap_bn": cap_bn, "cap_en": cap_en, "c_bn": c_bn, "c_en": c_en, "text": text}
        print("identify:", self.result)
        bn = f"মনে হচ্ছে {_strip(cap_bn)}। রং {c_bn}।"
        en = f"It looks like {cap_en}. Colour: {c_en}."
        if text:
            bn += f" লেখা আছে: {text}।"
            en += f" The text says: {text}."
        self.say_text(bn, en, tag="identify")
        self.say_key("follow_up", tag="identify2")
        self.answered_at = time.monotonic()
        self.state = "answered"

    def on_intent(self, it, detail):
        if self.result is None:
            return False
        r = self.result
        if it == "colour":
            self.say_text(f"রং {r['c_bn']}।", f"Colour: {r['c_en']}.", tag="identify")
        elif it == "read":
            if r["text"]:
                self.say_text(f"লেখা আছে: {r['text']}।", f"The text says: {r['text']}.", tag="identify")
            else:
                self.say_key("no_text_on_it", tag="identify")
        elif it == "repeat":
            self.app.speaker.repeat()
        else:
            return False
        self.answered_at = time.monotonic()
        return True

    def status(self):
        return f"IDENTIFY: {self.state}"
