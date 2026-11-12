"""Bangla voice output (TTS) and input (speech recognition), offline.

Output: Meta's MMS-TTS Bengali model (facebook/mms-tts-ben, VITS; licence
CC-BY-NC 4.0, so non-commercial use only). It fills in every Bangla prompt
the wearable and the laptop use until a person records them; a human
recording dropped into prompts/bn/ always wins (`overwrite=False`).

Input: BanglaASR (Whisper-small fine-tuned on Bangla) for Bangla, and
faster-whisper for English, on CUDA when available and CPU otherwise. Free speech becomes text, and
intent.route() turns text into an action, exactly as the phone app does
with Android's recogniser.

Both models download once (to the project's Hugging Face cache) and then run
with no network.
"""

import csv
import threading
from pathlib import Path

import numpy as np

from . import audio_io, config, intent
from .platform_support import torch_device

TTS_MODEL = "facebook/mms-tts-ben"
# Whisper-small fine-tuned on Bangla (Common Voice), run through CTranslate2
# int8 (ensure_ct2_bangla). Plain Whisper, even "medium", got 0 of 7 test
# commands right; this one gets the sentences.
ASR_MODEL_BN = "bangla-speech-processing/BanglaASR"
ASR_MODEL_EN = "small"

_tts = None
_asr = None
_tts_run = threading.Lock()  # one synthesis at a time: the model holds state (speaking_rate)
_asr_run = threading.Lock()


# ---------------------------------------------------------------- output --

def _load_tts():
    global _tts
    with config.MODEL_LOCK:
        return _load_tts_locked()


def _load_tts_locked():
    global _tts
    if _tts is None:
        import torch
        from transformers import AutoTokenizer, VitsModel
        tok = AutoTokenizer.from_pretrained(TTS_MODEL)
        # GPU: 0.1 s for a 9 s sentence against 3 s on the CPU (measured); 0.16 GB.
        model = VitsModel.from_pretrained(TTS_MODEL).to(torch_device()).eval()
        _tts = (tok, model, torch)
    return _tts


def synthesize(text, speed=1.0, seed=0):
    """Bangla text -> float32 audio at 16 kHz (the model's own rate)."""
    tok, model, torch = _load_tts()
    with _tts_run:
        return _synthesize(tok, model, torch, text, speed, seed)


def _synthesize(tok, model, torch, text, speed, seed):
    text = text.replace("।", ",").strip(" ,")  # the danda is not in its vocabulary; a comma gives the pause
    inputs = tok(text, return_tensors="pt").to(model.device)
    model.speaking_rate = speed
    torch.manual_seed(seed)  # VITS samples its prosody: fixed seed, same prompt every time
    with torch.no_grad():
        wav = model(**inputs).waveform[0].float().cpu().numpy().astype(np.float32)
    sr = model.config.sampling_rate
    if sr != config.SAMPLE_RATE:
        from scipy.signal import resample_poly
        g = np.gcd(sr, config.SAMPLE_RATE)
        wav = resample_poly(wav, config.SAMPLE_RATE // g, sr // g).astype(np.float32)
    peak = float(np.max(np.abs(wav))) or 1.0
    return wav / peak * 0.9


def _banned():
    if not config.BANNED_PHRASES.exists():
        return []
    return [l.strip().lower() for l in config.BANNED_PHRASES.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def make_bangla_prompts(overwrite=False, speed=0.95, log=print):
    """Writes prompts/bn/<ID>.wav for every prompt with Bangla text.

    Skips any that exist (a human recording is better) unless overwrite.
    Refuses text containing a banned phrase, as make_prompts.py does.
    """
    banned = _banned()
    out_dir = config.PROMPT_WAVS / "bn"
    out_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    with open(config.PROMPTS_CSV, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        text = (r["bn"] or "").strip()
        if not text:
            continue
        bad = [p for p in banned if p in text.lower()]
        if bad:
            raise ValueError(f"{r['id']}: prompt promises safety ({bad}); fix prompts.csv")
        path = out_dir / f"{r['id']}.wav"
        if path.exists() and not overwrite:
            continue
        audio_io.save_wav(path, synthesize(text, speed=speed))
        made += 1
        log(f"  {r['id']:18s} {text}")
    (out_dir / "SOURCE.txt").write_text(
        "Synthesized with facebook/mms-tts-ben (CC-BY-NC 4.0) by lab/va_lab/bangla_voice.py.\n"
        "Replace any file with a human recording of the same name; it will be kept.\n", encoding="utf-8")
    return made


# ----------------------------------------------------------------- input --

def _load_asr(language):
    with config.MODEL_LOCK:
        return _load_asr_locked(language)


def ensure_ct2_bangla():
    """BanglaASR converted to CTranslate2 int8 (once): 0.4 s per command and
    about 0.25 GB of GPU, against 1-1.6 s and 1 GB for the float32 original,
    with the same transcripts. Half precision is not an option: the original
    model overflows in fp16 and outputs only "!!!!" or "-"."""
    out = config.MODELS / "banglaasr-ct2"
    if (out / "model.bin").exists() and (out / "tokenizer.json").exists():
        return out
    from ctranslate2.converters import TransformersConverter
    from transformers import WhisperTokenizerFast
    converter = TransformersConverter(ASR_MODEL_BN, copy_files=["tokenizer_config.json", "preprocessor_config.json"])
    converter.convert(str(out), quantization="int8_float32", force=True)
    WhisperTokenizerFast.from_pretrained(ASR_MODEL_BN).save_pretrained(str(out))
    return out


def _load_asr_locked(language):
    global _asr
    key = "bn" if language == "bn" else "en"
    if _asr is None or _asr[0] != key:
        import torch
        from faster_whisper import WhisperModel
        cuda = torch_device() == "cuda"
        if key == "bn":
            _asr = (key, WhisperModel(str(ensure_ct2_bangla()), device="cuda" if cuda else "cpu",
                                      compute_type="int8"))
        else:
            _asr = (key, WhisperModel(ASR_MODEL_EN, device="cuda" if cuda else "cpu",
                                      compute_type="int8_float16" if cuda else "int8"))
    return _asr[1]


def transcribe(audio, language="bn"):
    """16 kHz float32 audio -> text. language "bn" or "en".

    No hint prompt: given the phrase list as a prompt, Whisper loops on it
    and invents commands, which is worse than a plain miss.
    """
    with _asr_run:
        asr = _load_asr(language)
        segments, _ = asr.transcribe(np.asarray(audio, np.float32), language=language, beam_size=2,
                                     vad_filter=True, condition_on_previous_text=False, without_timestamps=True)
        return " ".join(seg.text.strip() for seg in segments).strip()


def listen_and_route(seconds=3.0, language="bn"):
    """Record, transcribe, route. Returns (intent, detail, text)."""
    audio = audio_io.record(seconds)
    text = transcribe(audio, language=language)
    it, detail = intent.route(text)
    return it, detail, text


class Listener:
    """Non-blocking version for the live assistant: start(), then poll().
    Transcription runs on its own thread, so the camera never freezes."""

    def __init__(self, seconds=3.0, language="bn"):
        self.mic = audio_io.MicListener(seconds)
        self.language = language
        self._result = None
        self._busy = False
        self._generation = 0
        self._lock = threading.Lock()

    @property
    def listening(self):
        return self.mic.listening or self._busy

    def start(self):
        self._result = None
        self.mic.start()

    def cancel(self):
        self.mic.stop()
        with self._lock:
            self._generation += 1
            self._result = None
            self._busy = False

    def _work(self, audio, language, generation):
        try:
            text = transcribe(audio, language=language)
            it, detail = intent.route(text)
            result = (it, detail, text)
        except Exception as e:
            print("speech recognition failed:", repr(e))
            result = ("unknown", None, "")
        with self._lock:
            if generation == self._generation:
                self._result = result
                self._busy = False

    def poll(self):
        with self._lock:
            if self._result is not None:
                r, self._result = self._result, None
                return r
        audio = self.mic.poll()
        if audio is None:
            return None
        if audio_io.dbfs(audio) < -45:
            return ("unknown", None, "")
        with self._lock:
            self._busy = True
            generation = self._generation
        threading.Thread(target=self._work, args=(audio, self.language, generation), daemon=True).start()
        return None


def warm_up(language="bn"):
    """Loads the models now, so the first command does not wait for them."""
    _load_asr(language)
    _load_tts()
