"""Writes the lab's notebooks. Edit the cells here, then:

    python tools/build_notebooks.py          # all (clears saved outputs)
    python tools/build_notebooks.py 05 06    # only these
"""

import sys
from pathlib import Path

import nbformat as nbf

NB_DIR = Path(__file__).resolve().parent.parent / "notebooks"
KERNEL = {"name": "vision-ai-lab", "display_name": "Vision Assistant (project)", "language": "python"}

SETUP = """import sys, pathlib
LAB = pathlib.Path.cwd().parent if pathlib.Path.cwd().name == "notebooks" else pathlib.Path.cwd()
sys.path.insert(0, str(LAB))
from va_lab import config
config.ensure_dirs()
print("lab folder:", LAB)"""


def nb(name, cells):
    if len(sys.argv) > 1 and not any(name.startswith(a) for a in sys.argv[1:]):
        return
    book = nbf.v4.new_notebook()
    book.metadata["kernelspec"] = KERNEL
    book.metadata["language_info"] = {"name": "python"}
    for kind, src in cells:
        src = src.strip("\n")
        book.cells.append(nbf.v4.new_markdown_cell(src) if kind == "md" else nbf.v4.new_code_cell(src))
    NB_DIR.mkdir(parents=True, exist_ok=True)
    nbf.write(book, NB_DIR / name)
    print("wrote", name)


nb("00_setup_check.ipynb", [
    ("md", """# 00 · Setup check: camera, microphone, speakers, GPU

Run top to bottom once. Every later notebook assumes these pass.
Kernel: **Vision AI Lab (py3.11, CUDA)**."""),
    ("code", SETUP),
    ("code", """import torch, cv2, ultralytics, sounddevice as sd
print("torch", torch.__version__, "| CUDA:", torch.cuda.is_available(),
      torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
print("opencv", cv2.__version__, "| ultralytics", ultralytics.__version__)
print(sd.query_devices())
print("default input/output:", sd.default.device)"""),
    ("md", "## Speakers\nYou should hear the boot chime and *Vision Assistant ready* (the wearable's own prompt)."),
    ("code", """from va_lab.speech import Speaker, Utterance, ANSWER
spk = Speaker(bangla=False)
spk.say(Utterance(ANSWER, [("tone", "boot"), "BOOT"]))
print("Bangla prompts still to record:", len(spk.missing_bangla()))"""),
    ("md", "## Microphone\nSpeak for three seconds after running the cell. Speech at arm's length is usually −30 to −10 dBFS."),
    ("code", """from va_lab import audio_io
x = audio_io.record(3.0)
print(f"peak level {audio_io.dbfs(x):.1f} dBFS")
import sounddevice as sd; sd.play(x, 16000); sd.wait()"""),
    ("md", "## Camera"),
    ("code", """import matplotlib.pyplot as plt
from va_lab.vision import open_camera, grab
cap = open_camera(); frame = grab(cap); cap.release()
print("frame", frame.shape)
plt.figure(figsize=(7, 5)); plt.imshow(frame[..., ::-1]); plt.axis("off"); plt.show()"""),
    ("md", "## Captions\nRenders every prompt, Bangla included, for the assistant window (once; a few seconds)."),
    ("code", """from va_lab import captions
print("rendered", captions.render_all(), "caption images into", config.CAPTIONS_DIR)"""),
])

nb("01_camera_object_detection.ipynb", [
    ("md", """# 01 · Camera: what is ahead, which side, how far

**YOLO-World** is given the wearable's eight object names, so *door*, *rickshaw*
and *CNG* work without training. Direction comes from where the box sits in the
picture; distance is a pinhole **estimate** from typical object heights
(`config.OBJECT_HEIGHT_M`). The wearable measures distance with its laser
instead; here it is approximate and shown with `~`."""),
    ("code", SETUP),
    ("code", """from va_lab.vision import Detector, open_camera, grab
det = Detector("world")          # downloads yolov8s-worldv2.pt into models/ the first time
print("objects:", det.supported, "| device:", det.device)"""),
    ("code", """import cv2, matplotlib.pyplot as plt
cap = open_camera(); frame = grab(cap); cap.release()
dets = det.detect(frame)
for d in dets:
    print(f"{d.obj:9s} {d.score:.2f}  {d.angle_deg:+5.1f} deg  ~{d.distance_m:.1f} m{' (cut off: closer)' if d.clipped else ''}")
img = frame.copy()
for d in dets:
    x1, y1, x2, y2 = map(int, d.box)
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
    cv2.putText(img, f"{d.obj} ~{d.distance_m:.1f}m", (x1, max(12, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
plt.figure(figsize=(8, 6)); plt.imshow(img[..., ::-1]); plt.axis("off"); plt.show()"""),
    ("md", "## What the assistant would say for this picture"),
    ("code", """from va_lab import announce
from va_lab.speech import Speaker
spk = Speaker(bangla=False)
u = announce.describe(dets)
print([spk.caption(i) for i in u.items])
spk.say(u)"""),
    ("md", """## Measure your webcam's field of view
Stand the laptop 1.00 m from a wall. Mark where the left and right edges of the
picture fall on the wall and measure the width W in metres."""),
    ("code", """import math
W = 1.40   # metres, measured
hfov = 2 * math.degrees(math.atan(W / 2 / 1.00))
print(f"horizontal field of view = {hfov:.1f} deg  ->  set CAMERA_HFOV_DEG in va_lab/config.py")"""),
    ("md", "## Speed: YOLO-World vs plain COCO YOLOv8n"),
    ("code", """import time
coco = Detector("coco")
for name, d in (("world", det), ("coco", coco)):
    d.detect(frame)
    t = time.perf_counter()
    for _ in range(20): d.detect(frame)
    print(f"{name:6s} {(time.perf_counter() - t) / 20 * 1000:6.1f} ms per frame, knows {d.supported}")"""),
    ("md", "## Live preview (press Q in the window to close)"),
    ("code", """cap = open_camera()
while True:
    ok, frame = cap.read()
    for d in det.detect(frame):
        x1, y1, x2, y2 = map(int, d.box)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f"{d.obj} {d.angle_deg:+.0f}deg ~{d.distance_m:.1f}m", (x1, max(12, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
    cv2.imshow("detections (Q to close)", frame)
    if cv2.waitKey(1) & 0xFF in (ord("q"), 27): break
cap.release(); cv2.destroyAllWindows()"""),
])

nb("02_keyword_dataset.ipynb", [
    ("md", """# 02 · Keyword dataset: download + record your own

1. **Google Speech Commands v0.02** (CC-BY 4.0). The 2.3 GB archive is streamed
   and only this project's words are kept (about 600 MB): ten demo command words,
   a slice of the rest as *unknown*, and the background-noise recordings.
2. **Your own voice**, Bangla and English, through this laptop's microphone, for
   the device's real vocabulary (`firmware/stm32h743/tools/keywords.csv`).
   No public Bangla keyword dataset exists for these words; this is how it is made.

Recordings stay on this computer (`data/`, git-ignored). Record a person only with
their consent."""),
    ("code", SETUP),
    ("code", """from va_lab import kws_data
kws_data.download_speech_commands()   # resumable: re-running skips if complete"""),
    ("code", """import collections, pathlib
counts = collections.Counter(p.parent.name for p in config.SPEECH_COMMANDS_DIR.glob("*/*.wav"))
print(dict(sorted(counts.items())))"""),
    ("code", """# Listen to a few examples
import random, sounddevice as sd
from va_lab import audio_io
for w in ["stop", "go", "left"]:
    f = random.choice(sorted((config.SPEECH_COMMANDS_DIR / w).glob("*.wav")))
    print(w, f.name); sd.play(audio_io.load_wav(f), 16000); sd.wait()"""),
    ("md", """## Record your own keywords

Set `SPEAKER` to an anonymous code (S01, S02, …). Each run asks for every
keyword `REPS` times in random order, then ordinary words for the *unknown*
class, then optional background noise. Say each word after **now**."""),
    ("code", """import random, time
from va_lab import audio_io
keywords = config.load_keywords()
for k in keywords: print(f"{k['label']:14s} {k['say']}  ({k['romanised']})")"""),
    ("code", """SPEAKER = "S01"   # anonymous code
REPS = 5          # 10+ per speaker is better; 30+ speakers is the goal

def next_index(label):
    d = config.MY_KEYWORDS_DIR / label
    return len(list(d.glob(f"{label}.{SPEAKER}_*.wav"))) + 1

def take(label, prompt):
    while True:
        print(f"\\nSay:  {prompt}"); time.sleep(0.5); print("  ... now")
        clip = audio_io.loudest_second(audio_io.record(config.KWS_LISTEN_S))
        level = audio_io.dbfs(clip)
        if level < -40: print(f"  too quiet ({level:.0f} dBFS), again"); continue
        if level > -0.5: print("  clipped, again a little further away"); continue
        path = config.MY_KEYWORDS_DIR / label / f"{label}.{SPEAKER}_{next_index(label)}.wav"
        audio_io.save_wav(path, clip); print("  saved", path.name, f"({level:.0f} dBFS)"); return

input("Quiet room, laptop at arm's length. Press Enter to start.")
for r in range(REPS):
    for k in random.sample(keywords, len(keywords)):
        take(k["label"], f"{k['say']}   ({k['romanised']})" if k["romanised"] else k["say"])"""),
    ("code", """# Ordinary words for the "_unknown" class (near-misses matter most)
FILLER = ["আম", "পানি", "কলম", "বাজার", "চা", "বই", "মোবাইল", "ভাত", "জামা", "চাবি", "থাকো", "আবার", "জানালা",
          "apple", "water", "pen", "phone", "hello", "okay", "thanks", "listen"]
for w in random.sample(FILLER, 10):
    take("_unknown", w)"""),
    ("code", """# Background noise: nobody speaking; fan, street, kitchen... (seconds)
SECONDS = 60
input(f"Leave the laptop somewhere noisy and press Enter; recording {SECONDS} s")
x = audio_io.record(SECONDS)
for i in range(0, len(x) - 16000 + 1, 16000):
    audio_io.save_wav(config.MY_KEYWORDS_DIR / "_noise" / f"_noise.{SPEAKER}_{i // 16000:03d}.wav", x[i:i + 16000])
print("saved", len(x) // 16000, "noise clips")"""),
    ("code", """counts = collections.Counter(p.parent.name for p in config.MY_KEYWORDS_DIR.glob("*/*.wav"))
print(dict(sorted(counts.items())))"""),
])

nb("03_keyword_training.ipynb", [
    ("md", """# 03 · Train the keyword spotter (DS-CNN)

* **Demo model** — ten English Speech Commands words, trains now from the
  downloaded data. Mapped to assistant actions in `assistant.py`:
  *stop* stop · *go* describe · *left/right* find menu · *yes* search · *no*
  cancel · *up/down* volume · *on/off* obstacle warnings.
* **Custom model** — your own Bangla + English recordings (notebook 02), with
  Speech Commands as *unknown*. This is the device's real vocabulary.

The split is **by speaker**: test accuracy is on voices the model never heard."""),
    ("code", SETUP),
    ("code", """import torch, numpy as np, matplotlib.pyplot as plt
from va_lab import kws_data, kws_model
ds = kws_data.build_dataset("demo")
print(ds["classes"])
for split, counts in kws_data.summary(ds): print(split, counts)"""),
    ("code", """model, history = kws_model.train(ds, epochs=30, batch_size=256)
test = kws_model.evaluate(model, ds["testing"])
print(f"test accuracy (unseen speakers): {test['accuracy']:.3f}")"""),
    ("code", """fig, ax = plt.subplots(1, 2, figsize=(13, 5))
ax[0].plot([h["train_acc"] for h in history], label="train"); ax[0].plot([h["val_acc"] for h in history], label="validation")
ax[0].set_xlabel("epoch"); ax[0].set_ylabel("accuracy"); ax[0].legend(); ax[0].grid(alpha=.3)
c = test["confusion"]; cn = c / c.sum(1, keepdims=True)
ax[1].imshow(cn, cmap="Blues"); ax[1].set_xticks(range(len(ds["classes"])), ds["classes"], rotation=60)
ax[1].set_yticks(range(len(ds["classes"])), ds["classes"]); ax[1].set_title("test confusion (rows = true)")
plt.tight_layout(); plt.show()
for i, name in enumerate(ds["classes"]): print(f"{name:10s} recall {cn[i, i]:.2f}")"""),
    ("code", """kws_model.save(model, ds["classes"], config.MODELS / "kws_demo.pt", history, vocab="demo")
kws_model.export_onnx(model, config.MODELS / "kws_demo.onnx")
print("saved", config.MODELS / "kws_demo.pt", "and .onnx;", sum(p.numel() for p in model.parameters()), "parameters")"""),
    ("md", "## Try it: run the cell, wait for the tone, say a word"),
    ("code", """from va_lab import audio_io
from va_lab.speech import Speaker, Utterance, ANSWER
import time
spot = kws_model.KeywordSpotter(config.MODELS / "kws_demo.pt")
Speaker(bangla=False).say(Utterance(ANSWER, [("tone", "listen")])); time.sleep(0.25)
label, conf, top = spot.classify(audio_io.record(config.KWS_LISTEN_S))
print(f"heard: {label} ({conf:.2f})   top3: {top}")"""),
    ("md", """## Custom vocabulary (after recording in notebook 02)
Needs recordings from several speakers to be meaningful; with one speaker the
test split may be empty (the split is by speaker)."""),
    ("code", """try:
    dsc = kws_data.build_dataset("custom")
except RuntimeError as e:
    print(e)
else:
    for split, counts in kws_data.summary(dsc): print(split, counts)
    mc, hc = kws_model.train(dsc, epochs=40, batch_size=128)
    print("test accuracy:", kws_model.evaluate(mc, dsc["testing"])["accuracy"])
    kws_model.save(mc, dsc["classes"], config.MODELS / "kws_custom.pt", hc, vocab="custom")
    kws_model.export_onnx(mc, config.MODELS / "kws_custom.onnx")"""),
])

nb("04_custom_object_training.ipynb", [
    ("md", """# 04 · Train your own small object detector (optional)

YOLO-World already finds the eight objects, but it is big. This notebook makes a
small, fast YOLOv8n that knows exactly these eight, **without hand-labelling**:

1. take pictures with the webcam, where the device will be used;
2. YOLO-World labels them automatically (review a few!);
3. YOLOv8n trains on the GTX 1650.

The same pictures, at 96×96, are what the wearable's FOMO model needs too."""),
    ("code", SETUP),
    ("code", """import cv2, time
from va_lab.vision import open_camera
def capture(n=60, every_s=1.0, folder=config.IMAGES_DIR / "raw"):
    folder.mkdir(parents=True, exist_ok=True); cap = open_camera(); saved = 0; last = 0
    while saved < n:
        ok, frame = cap.read(); cv2.imshow("capturing (Q stops)", frame)
        if time.time() - last >= every_s:
            cv2.imwrite(str(folder / f"img_{int(time.time() * 1000)}.jpg"), frame); saved += 1; last = time.time()
        if cv2.waitKey(1) & 0xFF in (ord("q"), 27): break
    cap.release(); cv2.destroyAllWindows(); print("saved", saved, "pictures in", folder)
capture(n=60)   # walk around: doors, chairs, tables, bottles, people (with consent)"""),
    ("code", """import random, shutil, yaml, pathlib
from va_lab.vision import Detector
det = Detector("world")
names = config.OBJECTS
root = config.IMAGES_DIR / "yolo"
for s in ("train", "val"):
    (root / "images" / s).mkdir(parents=True, exist_ok=True); (root / "labels" / s).mkdir(parents=True, exist_ok=True)
imgs = sorted((config.IMAGES_DIR / "raw").glob("*.jpg")); random.seed(0); random.shuffle(imgs)
n_boxes = 0
for i, p in enumerate(imgs):
    split = "val" if i % 5 == 0 else "train"
    img = cv2.imread(str(p)); h, w = img.shape[:2]
    lines = []
    for d in det.detect(img, min_score=0.45):
        x1, y1, x2, y2 = d.box
        lines.append(f"{names.index(d.obj)} {(x1+x2)/2/w:.6f} {(y1+y2)/2/h:.6f} {(x2-x1)/w:.6f} {(y2-y1)/h:.6f}")
    shutil.copy(p, root / "images" / split / p.name)
    (root / "labels" / split / (p.stem + ".txt")).write_text("\\n".join(lines))
    n_boxes += len(lines)
(root / "data.yaml").write_text(yaml.safe_dump({"path": str(root), "train": "images/train", "val": "images/val",
                                                "names": {i: n for i, n in enumerate(names)}}))
print(len(imgs), "pictures,", n_boxes, "auto-labelled boxes ->", root / "data.yaml")"""),
    ("code", """from ultralytics import YOLO
y = YOLO(str(config.MODELS / "yolov8n.pt"))
res = y.train(data=str(config.IMAGES_DIR / "yolo" / "data.yaml"), epochs=50, imgsz=320, batch=16,
              device=0, project=str(config.MODELS / "runs"), name="objects", exist_ok=True)
best = pathlib.Path(res.save_dir) / "weights" / "best.pt"
shutil.copy(best, config.MODELS / "objects_custom.pt"); print("saved", config.MODELS / "objects_custom.pt")"""),
    ("code", """# Use it: python -m va_lab.assistant --detector custom
YOLO(str(config.MODELS / "objects_custom.pt")).export(format="onnx", imgsz=320)"""),
])

nb("05_live_assistant.ipynb", [
    ("md", """# 05 · The whole assistant, live and offline

A window opens with the camera picture, a status line and live captions (Bangla
included). Everything is spoken; the left and right ears stand in for the
wearable's vibration motors.

| Key | Mode / action |
|---|---|
| **R** | **Read**: hold a page up; it guides you ("move the page right", "hold steady"), captures, reads. In Read: P pause/resume, `.` next paragraph, `,` previous, R a new page |
| **F** | **Find**: asks what to find, you say it ("চাবি", "লাল ব্যাগ", "door"); a ping in the ear on its side, faster when centred |
| **D** | **Describe**: where the known things are, then a detailed description of the scene |
| **I** | **Identify**: hold an object in the middle: name, colour, text on it; then ask "রং কী" or "লেখা পড়ো" |
| SPACE | say any command in Bangla or English: "পড়ো", "দরজা খোঁজো", "সামনে কী আছে", "এটা কী", "থামো" |
| K | one keyword instead (notebook 03 model) |
| 1–8 | find: person chair door table bottle toilet rickshaw cng |
| S / L / W / A / H / Q | stop · Bangla↔English · obstacle warnings · alarm · help · quit |

Set `CAMERA_FACES_USER = True` in `va_lab/config.py` if you use the laptop's own
camera turned towards you, so left and right come out right.
**A prototype for testing behaviour, not a mobility aid.**"""),
    ("code", SETUP),
    ("code", """from va_lab.assistant import Assistant
app = Assistant(detector="world")
app.run()                               # Q in the window to quit"""),
    ("code", """for t, pr, text in app.speaker.log[-40:]: print(t, pr, text)"""),
])

nb("06_bangla_voice.ipynb", [
    ("md", """# 06 · Bangla voice: speaking and listening, offline

* **Output:** Meta's MMS-TTS Bengali (`facebook/mms-tts-ben`, CC-BY-NC 4.0:
  non-commercial use). It writes every Bangla prompt into
  `firmware/stm32h743/prompts/bn/`, so the **wearable and the laptop both speak
  Bangla**. A human recording with the same file name always wins: record
  `OBST_LEFT.wav` yourself and it is kept.
* **Input:** BanglaASR (Whisper fine-tuned on Bangla; faster-whisper for English) turns speech into
  text; `intent.route()` (the app's IntentRouter, in Python) turns text into
  an action. Mixed speech works: *"chair টা কোথায়"*.

Both models download once to the Hugging Face cache on C: and then need no network."""),
    ("code", SETUP),
    ("code", """from va_lab import bangla_voice as bv, intent, audio_io
import sounddevice as sd
x = bv.synthesize("সামনে বাধা। দেড় মিটার।")
sd.play(x, 16000); sd.wait()"""),
    ("md", """## Make (or refresh) every Bangla prompt
`overwrite=False` keeps existing files, including human recordings."""),
    ("code", """n = bv.make_bangla_prompts(overwrite=False)
print("made", n, "new Bangla prompts in", config.PROMPT_WAVS / "bn")"""),
    ("code", """# Listen to a few through the assistant's own speaker
from va_lab.speech import Speaker, Utterance, ANSWER
spk = Speaker(bangla=True)
spk.say(Utterance(ANSWER, ["OBJ_CHAIR", "ZONE_LEFT", "DIST_1_5"])); import time; time.sleep(3)
spk.say(Utterance(ANSWER, ["ALARM_ON"])); time.sleep(4)
print("still English-only:", spk.missing_bangla())"""),
    ("md", "## The router on text (no microphone)"),
    ("code", """for u in ["চেয়ার টা কোথায়", "door koi", "সামনে কী আছে", "থামো", "জরুরি", "ব্যাটারি কত", "আজকে আবহাওয়া"]:
    print(f"{u:20s} -> {intent.route(u)}")"""),
    ("md", "## Speak: run the cell, wait for the tone, say a command in Bangla (3 s)"),
    ("code", """spk.say(Utterance(ANSWER, [("tone", "listen")])); time.sleep(0.3)
audio = audio_io.record(3.0)
text = bv.transcribe(audio, language="bn")
print("heard:", text)
print("action:", intent.route(text))"""),
    ("md", """## How well it hears
Bangla uses **BanglaASR** (Whisper-small fine-tuned on Bangla). Tested on the
MMS voice: full sentences ("সামনে কী আছে", "দরজা খুঁজে দাও") come through;
single words ("থামো", "জরুরি") often do not. Those are what the keyword model
(notebook 03, key **K**) is for, and emergency is never matched loosely:
it needs the exact word or the alarm key."""),
])

nb("07_modes_offline.ipynb", [
    ("md", """# 07 · The four modes, one at a time (offline)

Each cell tests one mode's models on a still picture, so you can see what each
model says before using it live. Run `tools/download_models.py` once with
internet; after that this works with Wi-Fi off."""),
    ("code", SETUP),
    ("code", """import os
os.environ["HF_HUB_OFFLINE"] = "1"; os.environ["TRANSFORMERS_OFFLINE"] = "1"
import cv2, matplotlib.pyplot as plt
from va_lab import understand, ocr, safety
from va_lab.vision import open_camera, grab
cap = open_camera(); frame = grab(cap); cap.release()
plt.figure(figsize=(7, 5)); plt.imshow(frame[..., ::-1]); plt.axis("off"); plt.show()"""),
    ("md", "## Describe: Florence-2 caption → NLLB Bangla → safety filter"),
    ("code", """en = understand.caption(frame, "detailed")
bn = understand.to_bangla(en)
print("EN:", en); print("BN:", bn); print("after safety filter:", safety.clean(bn))"""),
    ("md", "## Identify: the middle of the picture"),
    ("code", """h, w = frame.shape[:2]
crop = frame[int(h*.2):int(h*.8), int(w*.25):int(w*.75)]
print("name:", understand.caption(crop, "short"), "| colour:", understand.colour_name(crop))
plt.imshow(crop[..., ::-1]); plt.axis("off"); plt.show()"""),
    ("md", "## Read: hold a printed page in front of the camera, then run"),
    ("code", """cap = open_camera(); page = grab(cap, warmup=10); cap.release()
reader = understand.get("ocr")
print("aiming hint:", ocr.check(page, reader.boxes(page)))
res = reader.read(page)
for para in ocr.reading_order(res):
    print("¶", para)
    for s in ocr.sentences(para): print("   -", s)"""),
    ("md", "## Find any object by name (YOLO-World, open vocabulary)"),
    ("code", """from va_lab.vision import Detector
det = Detector("world")
query, said = understand.query_for("চাবি")      # Bangla name -> English query
print(said, "->", query)
det.set_queries([query], "target")
print([(d.obj, round(d.angle_deg), round(d.distance_m, 1)) for d in det.detect(frame)])
det.restore()"""),
])
