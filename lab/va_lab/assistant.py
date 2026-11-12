"""The whole assistant on a laptop: webcam, microphone, speakers, one window.
Everything runs offline.

    python -m va_lab.assistant
    run_assistant.bat              (double-click, in lab/)

Modes (one at a time, each with its own earcon):
    R  Read      hold a page up; it guides you, captures, and reads aloud
                 (P pause/resume, . next paragraph, , previous, R new page)
    F  Find      asks what to find, then steers you with pings and words
    D  Describe  what is ahead, in detail
    I  Identify  the thing held in the middle: name, colour, text on it

Always:
    SPACE  speak a command, Bangla or English ("পড়ো", "দরজা খোঁজো", "এটা কী")
    K      one keyword instead (keyword model)      1-8  find one of the eight objects
    S      stop        L Bangla/English      W obstacle warnings      A alarm
    H      help        Q / Esc quit

The window is for a sighted helper; the user needs only sound.
"""

import argparse
import threading
import time

import cv2
import numpy as np

from . import announce, captions, config, enhance, phrases, safety, tts
from .audio_io import MicListener
from .modes import DescribeMode, FindMode, IdentifyMode, Mode, ReadMode
from .obstacle import ObstaclePolicy, nearest_per_zone
from .speech import ANSWER, HAZARD, Speaker, Utterance
from .vision import Detector, Stabiliser, focal_px, open_camera

COLOURS = {"person": (60, 200, 255), "chair": (90, 220, 90), "door": (255, 170, 60), "table": (200, 120, 255),
           "bottle": (60, 255, 255), "toilet": (255, 255, 120), "rickshaw": (60, 120, 255), "cng": (0, 210, 160),
           "target": (0, 0, 255)}
KEY_HELP = "R read  F find  D describe  I identify | SPACE speak  K keyword  1-8 find  S stop  L lang  W warn  A alarm  H help  Q quit"


class Assistant:
    def __init__(self, detector="world", kws_path=None, camera_index=config.CAMERA_INDEX,
                 bangla=config.DEFAULT_BANGLA, warnings=None):
        # A camera turned towards the user sees the user and the wall behind
        # them: obstacle warnings from it would describe the user. Off unless
        # the camera looks where the user walks.
        if warnings is None:
            warnings = not config.CAMERA_FACES_USER
        import torch
        torch.set_num_threads(config.CPU_THREADS)
        safety.check_fixed([t for t, _ in phrases.all_texts()])
        self.speaker = Speaker(bangla=bangla)
        if bangla and not any(self.speaker.has_bangla(p) for p in self.speaker.prompts):
            self.speaker.bangla = False  # Bangla first, but not before any Bangla prompt exists
        captions.render_all()
        # Bangla speech model on the main thread first; then every fixed phrase
        # synthesised in the background, so no command waits for it later.
        from . import bangla_voice
        bangla_voice._load_tts()
        threading.Thread(target=self._warm_phrases, daemon=True).start()
        from . import understand
        understand.preload()
        threading.Thread(target=lambda: bangla_voice._load_asr("bn"), daemon=True).start()
        self.detector = Detector(detector)
        self.stabiliser = Stabiliser()
        self.camera_index = camera_index
        self.policy = ObstaclePolicy()
        self.warnings = warnings
        self.kws = None
        kws_path = kws_path or next((p for p in (config.MODELS / "kws_custom.pt", config.MODELS / "kws_demo.pt")
                                     if p.exists()), None)
        if kws_path:
            from .kws_model import KeywordSpotter
            self.kws = KeywordSpotter(kws_path)
        self.mic = MicListener()
        self.speech_in = None
        self._listen_at = None
        self.alarm = False
        self.mode = Mode(self)
        self.heard = ""
        self.detections = []
        self.last_frame = None
        self.dark = False
        self.awaiting_find = False
        self._last_raw = []

    def _warm_phrases(self):
        texts = phrases.all_texts()
        # the current language first: it is the one about to be needed
        texts.sort(key=lambda t: t[1] != ("bn" if self.speaker.bangla else "en"))
        try:
            tts.warm(texts)
        except Exception as e:
            print("phrase warm-up stopped:", repr(e))

    # ---- modes ---------------------------------------------------------

    def set_mode(self, mode):
        # Entered before it becomes current: the main loop never steps a
        # half-started mode.
        self.mode.exit()
        self.speaker.stop()
        self.stabiliser.reset()
        self.mode = Mode(self)
        mode.enter()
        if not mode.done:
            self.mode = mode

    def idle(self, announce_it=False):
        if self.mode.name != "idle":
            self.mode.exit()
            self.mode = Mode(self)
            if announce_it:
                self.say_key("mode_idle")

    def say_key(self, key, priority=ANSWER):
        self.speaker.say(Utterance(priority, [("text", *phrases.P[key])], tag=key))

    def say(self, *items, priority=ANSWER, tag=""):
        self.speaker.say(Utterance(priority, list(items), tag=tag))

    def ask_find(self):
        self.idle()
        self.say(("tone", "find"), ("text", *phrases.P["ask_find"]))
        self.awaiting_find = True
        self._start_listening(wait_for_speech_end=True)

    def find(self, obj=None, spoken=None):
        self.awaiting_find = False
        self.set_mode(FindMode(self, obj=obj, spoken=spoken))

    # ---- actions -------------------------------------------------------

    def stop_all(self):
        self.alarm = False
        self.awaiting_find = False
        self._listen_at = None
        self.mic.stop()
        if self.speech_in is not None:
            self.speech_in.cancel()
        was_active = self.mode.name != "idle"
        self.idle()
        self.speaker.stop()
        if was_active:
            self.say_key("mode_idle")

    def toggle_language(self, bangla=None):
        self.speaker.bangla = (not self.speaker.bangla) if bangla is None else bangla
        self.say("LANG_BANGLA" if self.speaker.bangla else "LANG_ENGLISH")

    def toggle_warnings(self, on=None):
        self.warnings = (not self.warnings) if on is None else on
        self.policy.reset()
        self.say("WARNINGS_ON" if self.warnings else "WARNINGS_OFF")

    def start_alarm(self):
        self.idle()
        self.alarm = True
        self.say("ALARM_ON", ("tone", "alarm"), priority=HAZARD, tag="alarm")

    def battery(self):
        try:
            import psutil
            b = psutil.sensors_battery()
            self.speaker.say(announce.battery(None if b is None else b.percent))
        except Exception:
            self.speaker.say(announce.battery(None))

    # ---- voice ---------------------------------------------------------

    def _start_listening(self, wait_for_speech_end=False):
        if self.speech_in is None:
            from .bangla_voice import Listener
            self.speech_in = Listener(seconds=3.0)
        self.speech_in.language = "bn" if self.speaker.bangla else "en"
        # The microphone opens once the question or tone has finished playing,
        # so the assistant never transcribes its own voice.
        self._listen_at = time.monotonic() + (0.3 if wait_for_speech_end else 0.15)

    def listen_speech(self):
        self.speaker.stop()
        self.say(("tone", "listen"))
        self._start_listening()

    def listen_keyword(self):
        if self.kws is None:
            self.say(("tone", "error"))
            self.heard = "no keyword model: train one in notebook 03"
            return
        self.speaker.stop()
        self.say(("tone", "listen"))
        time.sleep(0.15)
        self.mic.start()

    def dispatch(self, it, detail, text=""):
        """One intent from speech, keyword or key."""
        self.heard = f"{it} {detail or ''}".strip()
        if text:
            print(f"heard: {text!r} -> {it} {detail or ''}")
        if self.awaiting_find and it in ("find", "find_text", "unknown") and (detail or text):
            if it == "find":
                return self.find(obj=detail)
            return self.find(spoken=detail if it == "find_text" else text)
        self.awaiting_find = False
        if self.mode.on_intent(it, detail):
            return
        actions = {
            "emergency": self.start_alarm, "stop": self.stop_all, "repeat": self.speaker.repeat,
            "read": lambda: self.set_mode(ReadMode(self)), "ahead": lambda: self.set_mode(DescribeMode(self)),
            "identify": lambda: self.set_mode(IdentifyMode(self)), "battery": self.battery,
            "bangla": lambda: self.toggle_language(True), "english": lambda: self.toggle_language(False),
            "help": lambda: self.say_key("help"), "warnings_on": lambda: self.toggle_warnings(True),
            "warnings_off": lambda: self.toggle_warnings(False),
        }
        if it == "find":
            self.find(obj=detail)
        elif it == "find_text":
            self.find(spoken=detail)
        elif it in actions:
            actions[it]()
        else:
            self.say(("tone", "error"), "NOT_UNDERSTOOD")

    def _keyword_to_intent(self, label, conf):
        needed = config.KWS_EMERGENCY_CONFIDENCE if label.startswith("emergency") else config.KWS_MIN_CONFIDENCE
        if label.startswith("_") or conf < needed:
            return ("unknown", None)
        prefix = label.split("_")[0]
        if prefix in config.OBJECTS:
            return ("find", prefix)
        demo = {"stop": "stop", "go": "ahead", "yes": "resume", "no": "stop", "left": "previous",
                "right": "next", "on": "warnings_on", "off": "warnings_off", "up": "resume", "down": "pause"}
        custom = {"emergency": "emergency", "repeat": "repeat", "ahead": "ahead", "help": "help",
                  "battery": "battery", "bangla": "bangla", "english": "english", "stop": "stop"}
        return (custom.get(prefix) or demo.get(label) or "unknown", None)

    def _voice_step(self, now):
        if self._listen_at is not None and now >= self._listen_at and not self.speaker.busy():
            self._listen_at = None
            self.speech_in.start()
        if self.speech_in is not None:
            r = self.speech_in.poll()
            if r is not None:
                self.dispatch(*r)
        if self.kws is not None:
            audio = self.mic.poll()
            if audio is not None:
                label, conf, top = self.kws.classify(audio)
                print("keyword:", top)
                self.dispatch(*self._keyword_to_intent(label, conf))

    # ---- per frame -----------------------------------------------------

    def _obstacles(self, now_ms):
        if not self.warnings or self.alarm or self.mode.name == "read":
            return  # while reading, the page fills the picture: it is not an obstacle
        for zone, mm in nearest_per_zone(self.detections).items():
            alert = self.policy.on_sample(zone, mm, now_ms)
            if alert:
                if alert.zone != "ahead":
                    self.speaker.nudge(-1 if alert.zone == "left" else 1)
                self.speaker.say(announce.obstacle(alert))

    def _alarm_step(self):
        if self.alarm and not self.speaker.busy():
            self.say(("tone", "alarm"), priority=HAZARD, tag="alarm")

    # ---- drawing -------------------------------------------------------

    def draw(self, frame):
        h, w = frame.shape[:2]
        f = focal_px(w, self.detector.hfov)
        for a in (-config.OBST_AHEAD_DEG, config.OBST_AHEAD_DEG):
            x = int(w / 2 + f * np.tan(np.radians(a)))
            cv2.line(frame, (x, 30), (x, h), (80, 80, 80), 1)
        for d in self.detections:
            x1, y1, x2, y2 = map(int, d.box)
            c = COLOURS.get(d.obj, (255, 255, 255))
            cv2.rectangle(frame, (x1, y1), (x2, y2), c, 2)
            cv2.putText(frame, f"{d.obj} #{d.track} {d.score:.2f} ~{d.distance_m:.1f}m {d.angle_deg:+.0f}deg",
                        (x1 + 3, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1, cv2.LINE_AA)
        lang = "BN" if self.speaker.bangla else "EN"
        listening = self.mic.listening or (self.speech_in is not None and self.speech_in.listening)
        state = "ALARM" if self.alarm else self.mode.status()
        extra = "LISTENING..." if listening else (f"heard: {self.heard}" if self.heard else "")
        status = f"{lang} | {state} | warn {'on' if self.warnings else 'off'}{' | DARK' if self.dark else ''} | {extra}"
        cv2.rectangle(frame, (0, 0), (w, 26), (60, 20, 0), -1)
        cv2.putText(frame, status, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        canvas = np.zeros((h + 150, max(w, captions.LINE_W + 20), 3), np.uint8)
        canvas[:h, :w] = frame
        self._draw_captions(canvas, h)
        cv2.putText(canvas, KEY_HELP, (6, canvas.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (160, 160, 160),
                    1, cv2.LINE_AA)
        return canvas

    @staticmethod
    def _paste(canvas, m, x, y, colour, bottom):
        mh, mw = m.shape
        mh = min(mh, bottom - y)
        mw = min(mw, canvas.shape[1] - x)
        if mh <= 0 or mw <= 0:
            return y
        region = canvas[y:y + mh, x:x + mw]
        alpha = (m[:mh, :mw].astype(np.float32) / 255.0)[..., None]
        region[:] = (region * (1 - alpha) + np.array(colour, np.float32) * alpha).astype(np.uint8)
        return y + mh + 2

    def _draw_captions(self, canvas, top):
        u, idx, active = self.speaker.now_playing()
        if u is None:
            return
        hazard = u.priority == HAZARD and active
        colour = (0, 255, 255) if hazard else ((255, 255, 255) if active else (130, 130, 130))
        if hazard:
            canvas[top:top + 128] = (0, 0, 140)
        y, bottom = top + 6, top + 128
        for item in u.items[: idx + 1][-4:]:
            if isinstance(item, tuple) and item[0] in ("tone", "pause"):
                continue
            text = self.speaker.caption(item)
            if isinstance(item, tuple):
                m = captions.text_mask(text, "bn" if tts.is_bangla(text) else "en")
            else:
                m = captions.mask("bn" if self.speaker.bangla and self.speaker.has_bangla(item) else "en", item)
            if m is None:
                if not tts.is_bangla(text):  # OpenCV cannot draw Bangla: wait for the rendered caption
                    cv2.putText(canvas, text[:90], (10, y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 1, cv2.LINE_AA)
                    y += 28
                continue
            y = self._paste(canvas, m, 10, y, colour, bottom)
            if y >= bottom:
                break

    # ---- main loop -----------------------------------------------------

    def run(self, max_seconds=None, window="Vision Assistant (laptop, offline)"):
        cap = open_camera(self.camera_index)
        self.say(("tone", "boot"), "BOOT")
        t_end = None if max_seconds is None else time.monotonic() + max_seconds
        fps_t, fps_n, fps = time.monotonic(), 0, 0.0
        slow = 0.0
        try:
            while t_end is None or time.monotonic() < t_end:
                ok, frame = cap.read()
                if not ok:
                    self.say(("tone", "error"), "CAMERA_FAULT", tag="cam")
                    time.sleep(0.5)
                    continue
                now = time.monotonic()
                self.last_frame = frame
                seen, self.dark = enhance.enhance(frame)
                t_det = time.perf_counter()
                from . import understand
                self._frame_no = getattr(self, "_frame_no", 0) + 1
                thin = understand.busy > 0 and self._frame_no % 2  # a caption or OCR is using the GPU
                if self.mode.name == "read":
                    raw = []
                elif thin:
                    raw = self._last_raw
                else:
                    raw = self.detector.detect(seen)
                self._last_raw = raw
                det_ms = (time.perf_counter() - t_det) * 1000
                self.detections = self.stabiliser.update(raw)
                self._obstacles(int(now * 1000))
                self.mode.step(frame, self.detections, now)
                if self.mode.done:
                    self.idle()
                self._voice_step(now)
                self._alarm_step()
                self.speaker.poll()

                canvas = self.draw(seen.copy())
                fps_n += 1
                if now - fps_t >= 1.0:
                    fps, fps_t, fps_n = fps_n / (now - fps_t), now, 0
                loop_ms = (time.monotonic() - now) * 1000
                slow = max(slow * 0.95, loop_ms)
                cv2.putText(canvas, f"{fps:.0f} fps  detect {det_ms:.0f} ms  loop {loop_ms:.0f} ms  worst {slow:.0f}",
                            (canvas.shape[1] - 360, canvas.shape[0] - 26), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                            (200, 200, 200), 1, cv2.LINE_AA)
                if loop_ms > 250:
                    print(f"slow frame: {loop_ms:.0f} ms (detect {det_ms:.0f} ms, mode {self.mode.name})")
                cv2.imshow(window, canvas)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                self.on_key(key)
                if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                    break
        finally:
            self.mode.exit()
            self.mic.stop()
            if self.speech_in is not None:
                self.speech_in.mic.stop()
            self.speaker.close()
            cap.release()
            cv2.destroyAllWindows()

    def on_key(self, key):
        if key == 255:
            return
        if self.alarm and key != ord("a"):
            self.alarm = False
            self.speaker.stop()
            self.say("ALARM_OFF")
            return
        ch = chr(key).lower()
        if self.mode.on_key(ch):
            return
        actions = {" ": self.listen_speech, "k": self.listen_keyword,
                   "r": lambda: self.dispatch("read", None), "f": self.ask_find,
                   "d": lambda: self.dispatch("ahead", None), "i": lambda: self.dispatch("identify", None),
                   "s": self.stop_all, "l": self.toggle_language, "w": self.toggle_warnings,
                   "a": self.start_alarm, "h": lambda: self.say_key("help")}
        if ch in actions:
            actions[ch]()
        elif ch.isdigit() and 1 <= int(ch) <= len(config.OBJECTS):
            self.find(obj=config.OBJECTS[int(ch) - 1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detector", default="world", choices=["world", "coco", "custom"])
    ap.add_argument("--kws", help="keyword model (default: models/kws_custom.pt, else kws_demo.pt)")
    ap.add_argument("--camera", type=int, default=config.CAMERA_INDEX)
    ap.add_argument("--english", action="store_true")
    ap.add_argument("--camera-facing", choices=["user", "forward"], default="user",
                    help="user = laptop webcam (warnings off); forward = outward-facing camera")
    ap.add_argument("--max-seconds", type=float, help="Close automatically after this many seconds")
    args = ap.parse_args()
    config.CAMERA_FACES_USER = args.camera_facing == "user"
    Assistant(args.detector, args.kws, args.camera, bangla=not args.english).run(max_seconds=args.max_seconds)


if __name__ == "__main__":
    main()
