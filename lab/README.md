# Vision Assistant lab: the wearable on a laptop

The STM32H743 wearable's behaviour, run on a laptop: the webcam stands in for
the OV5640, the built-in microphone for the INMP441, and the speakers for the
MAX98357A. Left/right ticks in the speakers stand in for the vibration motors.

It speaks with the wearable's own prompts (`firmware/stm32h743/prompts`), so a
Bangla recording made for the device plays here too. It follows the same rules:

- the obstacle bands of `ObstaclePolicy.kt`;
- the hazard > manoeuvre > answer > ambient priority ladder;
- "not found", never "not there".

**This is a prototype for testing behaviour, not a mobility aid.** Its obstacle
warnings see only the eight objects it knows, and its distances are camera
estimates.

## The four modes (offline)

Plan: [`docs/laptop-modes-plan.md`](../docs/laptop-modes-plan.md). Start with
`run_assistant.bat`; the first time only, with internet, run
`tools/download_models.py`.

| Key / say | Mode | Models | Tested on this laptop |
|---|---|---|---|
| **R** / "পড়ো" | Read: aiming hints ("পাতাটা উপরে তুলুন"), auto-capture, reading order, sentence-by-sentence speech; P pause, `.` / `,` next/previous paragraph | EasyOCR bn+en | read "JETSON NANO DEVELOPER KIT" off a box |
| **F** / "চাবি খোঁজো" | Find any object: ping in the ear on its side, faster when centred; words every 3 s | YOLO-World (open vocabulary), Bangla→English dictionary + NLLB | "লাল ব্যাগ" → query "bag" |
| **D** / "সামনে কী আছে" | Describe: where the known things are, then a detailed caption, in Bangla | Florence-2-large + NLLB | "ছবিতে দেখা যায় একজন লোক একটি ল্যাপটপের সামনে বসে আছে, তার বাম দিকে একটি চেয়ার…" |
| **I** / "এটা কী" | Identify the object in the middle: name, colour, text on it; then "রং কী", "লেখা পড়ো" | Florence-2 + EasyOCR + colour from pixels | "একটি সবুজ বাক্স… রং সবুজ… লেখা আছে: DEVELOPER KIT" |

Always on underneath:

- obstacle warnings (not while reading);
- dim-frame enhancement;
- the 3-of-5-frames rule against flicker;
- a safety filter that drops any generated sentence promising safety.

Timings on the GTX 1650, measured live:

| What | Time |
|---|---|
| Object detection (YOLO-World-S, 480 px, fp32) | 15 ms per frame. fp16 is 3× slower on this card. |
| Describe: first fact ("ডান দিকে একটি বোতল") | 1 s after the key |
| Describe: first sentence of the description | 6 s |
| Identify: answer | 4 s |
| Bangla speech recognition (BanglaASR, CTranslate2 int8) | 0.4 s |
| Bangla voice (MMS on GPU) | 0.1 s per sentence |
| Translation (NLLB fp16 on GPU) | 0.5 s per sentence |
| GPU memory with everything loaded | ~3.0 GB of 4 |

**Speed choices:**

- **Florence-2-base, not large.** Large took 1.9 GB and pushed the card past
  4 GB; detection then slowed to seconds per frame.
- **Background work.** All heavy work runs off the camera loop, and the
  models are preloaded at start-up.
- **Thinned detection.** While a caption or OCR job runs, detection runs on
  every other frame.
- **Diagnostics.** The window's bottom line shows fps and loop time, and any
  frame over 250 ms is printed in the console.

`CAMERA_FACES_USER = True` (the default) is for the laptop's own camera
turned towards you. In that setup:

- left and right are mirrored to match you;
- obstacle warnings are off, because the camera sees you and the wall
  behind you.

With a chest camera or a phone looking where you walk, set it to `False`.

## Folders

```
lab/
  notebooks/   00-05, run in order (kernel "Vision AI Lab (py3.11, CUDA)")
  va_lab/      the code the notebooks call
  data/        datasets and your recordings (git-ignored)
    speech_commands/  slice of Google Speech Commands v0.02
    my_keywords/      your Bangla + English keyword recordings
    images/           webcam pictures for notebook 04
  models/      trained and downloaded models (git-ignored)
  tools/       build_notebooks.py
```

## Setup (done once on this laptop)

The Python environment lives at `%USERPROFILE%\.venvs\vision-ai-lab`. It is on
C: because CUDA torch alone is about 3 GB and E: was nearly full. To recreate it:

```powershell
py -3.11 -m venv $env:USERPROFILE\.venvs\vision-ai-lab
$py = "$env:USERPROFILE\.venvs\vision-ai-lab\Scripts\python.exe"
& $py -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
& $py -m pip install -r requirements.txt
& $py -m ipykernel install --user --name vision-ai-lab --display-name "Vision AI Lab (py3.11, CUDA)"
```

To use it:

1. Open `lab/notebooks` in VS Code or Jupyter Lab.
2. Pick the kernel **Vision AI Lab (py3.11, CUDA)**.
3. Run the notebooks in order.

## Notebooks

| # | What | Needs you? |
|---|---|---|
| 00 | camera, microphone, speakers, GPU check; renders the captions | yes: listen and speak |
| 01 | YOLO-World on the webcam: object, side, approximate distance; measure the field of view; live preview | point the camera |
| 02 | download the Speech Commands slice; record your own Bangla/English keywords | recording only |
| 03 | train the DS-CNN keyword spotter (demo model, then custom); confusion matrix; ONNX export; try it | no (the try-it cell: speak) |
| 04 | webcam pictures → auto-labels from YOLO-World → train a small YOLOv8n on the GPU | take pictures |
| 05 | the whole assistant, live | yes |
| 06 | Bangla voice: TTS for every prompt, Bangla speech recognition, the intent router | speak |

Or without Jupyter, from `lab/`:
`%USERPROFILE%\.venvs\vision-ai-lab\Scripts\python.exe -m va_lab.assistant`

## Models

| Model | What | Source |
|---|---|---|
| `yolov8s-worldv2.pt` | open-vocabulary detector, told the eight object names | Ultralytics, downloaded on first use |
| `yolov8n.pt` | COCO detector, the fallback, and the base for notebook 04 | Ultralytics, downloaded on first use |
| `kws_demo.pt` / `.onnx` | DS-CNN, 10 English words + unknown + silence, 23k parameters, **92.8% on unseen speakers** | trained in notebook 03 |
| `kws_custom.pt` / `.onnx` | DS-CNN on your recordings: the device's vocabulary | trained in notebook 03 |
| `objects_custom.pt` | YOLOv8n for the eight objects | trained in notebook 04 |
| `facebook/mms-tts-ben` | Bangla text-to-speech (VITS), made all 52 Bangla prompts | Meta MMS, CC-BY-NC 4.0 (non-commercial), HF cache on C: |
| `bangla-speech-processing/BanglaASR` | Bangla speech → text (Whisper-small fine-tuned) | Hugging Face, HF cache on C: |
| faster-whisper `small` | English speech → text | Hugging Face, HF cache on C: |

## Bangla voice

**Speaking.** `bangla_voice.make_bangla_prompts()` wrote every Bangla prompt
to `firmware/stm32h743/prompts/bn/`. The laptop and the wearable firmware now
both speak Bangla: the wearable's flash went from 37% to 70%. A human recording
with the same file name is never overwritten, and it sounds better than the
synthetic voice, so record the important ones (obstacle and alarm prompts) when
you can.

**Listening.** SPACE records 3 s. BanglaASR turns it into text, and
`intent.route()`, the app's `IntentRouter` ported to Python, turns the text
into an action. The router folds Bangla spelling variants (শ/ষ/স, ি/ী, য/জ),
ignores spaces and fuzzy-matches, because recognisers misspell Bangla.
Emergency is never fuzzy-matched: a false siren in public is worse than
asking again.

Tested on the synthetic voice:

| Said | Result |
|---|---|
| "সামনে কী আছে" | heard as "সামনে কে আছে" → describe ✓ |
| "দরজা খুঁজে দাও" | heard as "যজা খুঁজে দাও" → find door ✓ |
| "চেয়ারটা কোথায়" | heard as "যে আর্তা কোথায়" → find **toilet** ✗ |

The assistant says what it is searching for, so the user can stop it.
Single words (থামো, জরুরি) are unreliable through speech recognition; key
**K** uses the keyword model for those.

**Demo voice commands:**

| Say | Does |
|---|---|
| stop | stop |
| go | describe |
| left / right | find menu |
| yes | search |
| no | cancel |
| up / down | volume |
| on / off | obstacle warnings |

With `kws_custom.pt` the commands are the device's own (`firmware/stm32h743/tools/keywords.csv`):
জরুরি, থামো, আবার বলো, সামনে কী, চেয়ার, দরজা … and their English equivalents.

## Data and privacy

- **Speech Commands v0.02:** Warden 2018, CC-BY 4.0. Only this project's
  words are kept (about 600 MB of the 2.3 GB archive).
- **Your recordings and pictures:** they stay in `data/`, which is
  git-ignored. Record or photograph people only with their consent, and use
  anonymous speaker codes (S01, S02 …).
