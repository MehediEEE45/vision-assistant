# Laptop assistant: four modes for blind users

Plan for turning the laptop lab (`lab/`) from a detection demo into an
assistant with four modes:

| Mode | Spoken as | What it does |
|---|---|---|
| **Read** | "পড়ো" / "read" | reads printed text aloud, Bangla and English |
| **Find** | "চেয়ার খুঁজো" / "find the door" | steers the user to a named object |
| **Describe** | "সামনে কী আছে" / "describe" | a detailed description of the scene ahead |
| **Identify** | "এটা কী" / "what is this" | names the object held in the centre and gives details about it |

Obstacle warnings stay on underneath all four.

Written November 2026, against the laptop as it is: GTX 1650 (4 GB),
built-in webcam and microphone, and the `vision-ai-lab` environment on C:.

**Everything runs offline.** No network, no API key, no cloud. Models are
downloaded once while setting up and then never need the internet. A test in
phase E unplugs the network and repeats every gate.

---

## 1. Why the current model disappoints, and the fixes

These problems were seen while testing, or follow from how the system works.
Each fix is part of phase A.

| Problem | Cause | Fix |
|---|---|---|
| Misses objects in a dim room | The webcam picture was dark (the test frame was underexposed), and YOLO-World-S is a small model | Enhance contrast before detecting (CLAHE). Use a longer exposure when the scene is dark. Warn "light is low" instead of saying "nothing found". Offer YOLO-World-M (more accurate, still fits 4 GB). |
| Detections flicker | Each frame is judged alone | Track objects across frames (ByteTrack, built into Ultralytics). An object must appear in 3 of the last 5 frames before it is spoken. |
| Wrong distances | A box covering only part of an object (a chair's backrest) gives a distance from that part alone | Already partly fixed: the estimate now takes the smaller of height- and width-based distances. In Identify and Find, say "about" and the band ("about one metre"), never a decimal. |
| Knows only 8 things | The object list is fixed | Find and Identify use open vocabulary. Any name the user says becomes the search class (section 4). |
| Weak Bangla speech recognition | Single words such as থামো and জরুরি fail; sentences work | Single words go to the keyword model (key K). Mode names are added to the keyword vocabulary. Each mode has a short, fixed command list (section 7). |
| The user cannot tell what it is doing | No mode concept | One mode at a time, announced on entry ("পড়ার মোড"), with a distinct earcon per mode. |

**First step:** tell me which of these you saw, or a new one, so it is fixed first.

---

## 2. Mode design

```
                 ┌──────────────── always on ────────────────┐
                 │ obstacle warnings (camera) · stop · help · │
                 │ language · emergency · priority arbiter     │
                 └────────────────────────────────────────────┘
   idle ──"পড়ো"──▶ READ ──"থামো"──▶ idle
     │──"খুঁজো X"─▶ FIND ──found / timeout / stop──▶ idle
     │──"সামনে কী"─▶ DESCRIBE (one shot) ──▶ idle
     └──"এটা কী"──▶ IDENTIFY (one shot, then follow-up questions for 20 s) ──▶ idle
```

- **One mode at a time.** Entering a mode stops the previous one. Each mode
  is a class with `enter()`, `step(frame)` and `exit()`, run by the existing
  loop in `assistant.py`.
- **Each mode has its own earcon,** so the user knows the mode before the word
  is spoken: Read a page-turn, Find a sonar ping, Describe a rising chime,
  Identify a click.
- **Keys mirror voice:** R read, F find, D describe, I identify, S stop, H help.
- **Priority.** A hazard (an obstacle closer than 0.6 m) cuts any mode's speech
  mid-word; reading resumes at the last sentence boundary, including the
  Bangla danda (।), as `PageReader` does.
- **Safety language.** Generated text (descriptions, model answers) is checked
  against `banned-phrases.txt` before it is spoken. A sentence containing
  "safe", "clear to cross", "নিরাপদ" and so on is dropped and replaced with the
  plain observation. The prompts already pass this check; generated text is
  new and needs the same guard.

---

## 3. Read mode

**Goal:** a blind user holds a page, a sign or a medicine box in front of the
camera and hears the text, Bangla or English.

**Pipeline:**

1. **Capture assistance** (the hardest part).
   - Before reading, a fast text detector finds text boxes on every frame and
     the assistant guides the user: "পাতা বাম দিকে কাটা পড়েছে, ডানে সরান",
     "আরো কাছে আনুন", "স্থির রাখুন".
   - It checks four things: the text area touching an edge, the text being
     too small, motion blur (variance of the Laplacian) and darkness.
   - Once the frame is good for half a second it captures automatically and
     plays a shutter earcon.
2. **OCR**, offline, on the captured frame:
   - **EasyOCR** with Bengali and English. On a Bengali document benchmark it
     scored 91% character and 78% word accuracy.
   - **Tesseract** (`ben` + `eng`) runs as a second engine, which scored 89%
     and 80% on the same benchmark. Where the two disagree on a line, the one
     with higher confidence wins.
   - About one word in five may be wrong, and the user is told so:
     "ভুল থাকতে পারে" (there may be mistakes), the first time per session.
     The app's `CLAUDE.md` rule applies: never advertise offline Bangla
     reading as reliable.
   - Better pictures matter more than a better engine, which is why capture
     assistance (step 1) comes first.
3. **Reading order.** Group the boxes into lines, then lines into columns, so
   a two-column newspaper is not read across both columns.
4. **Speech.**
   - Bangla text uses the MMS-TTS Bengali voice, offline.
   - English text uses the Windows English voice, offline.
   - Text is split into sentences on `.` `?` `!` and `।`.
5. **Controls** while reading:

   | Command | Does |
   |---|---|
   | pause / বিরতি | pause |
   | continue / চালিয়ে যাও | continue |
   | next / পরের | next paragraph |
   | previous / আগের | previous paragraph |
   | repeat / আবার | repeat the paragraph |
   | stop / থামো | stop |

   These are the app's intents, already in `intent.py`'s word tables.
6. **Medicine rule** (from the app's banned phrases): read the label and
   **never infer a dose**.

**Models:** EasyOCR (Bengali + English, about 0.3 GB of GPU memory),
Tesseract with `ben` and `eng` data, and the Windows English voice
(installed). MMS-TTS Bengali is already in use.

---

## 4. Find mode

**Goal:** "দরজা খুঁজো". The camera searches, and the user is steered left or
right until the object is ahead, with its rough distance.

**What changes from today:**

- **Any object, not eight.**
  - The spoken name is translated to English with a small Bangla→English
    dictionary of common objects (চাবি key, মোবাইল phone, ব্যাগ bag,
    জানালা window, সিঁড়ি stairs, লিফট lift …). Anything not in the
    dictionary goes through the translator in section 5.
  - YOLO-World's class is then set to that word, so "find my bag" works
    without training.
- **Tracking:** lock on to one track ID, so the guidance does not jump
  between two chairs (the current fix does this by angle; ByteTrack does it
  properly).
- **Guidance by sound, like a parking sensor:**
  - A soft ping in the ear on the object's side, faster as it gets closer.
  - When the object is within ±10° of straight ahead, the ping moves to both
    ears and a word is spoken: "দরজা, সামনে, প্রায় দুই মিটার".
  - Words come at most every 3 s; the ping fills the gaps.
- **Lost and found:** "দরজা হারিয়ে গেছে, ধীরে ঘুরুন" (lost, turn slowly)
  after 2 s without it. "পাওয়া যায়নি" (not found) after 30 s. Never "নেই"
  (not there).
- **Hand guidance** (phase C, optional): for small objects on a table,
  MediaPipe Hands tracks the user's hand and says "হাত আরো ডানে" (hand
  further right) until the hand reaches the object.

**Models:** YOLO-World-S, with M for accuracy; ByteTrack (in Ultralytics); a
dictionary file `objects_bn_en.csv`.

---

## 5. Describe mode

**Goal:** "সামনে কী আছে". One picture, and two or three spoken sentences
that say what is there and where.

**Pipeline:**

1. Take one good frame, using the same quality check as Read.
2. **Caption:**
   - **Florence-2-large** (Microsoft, MIT licence, 0.77 B parameters, about
     1.6 GB in fp16) with its detailed-caption task, offline on the GPU.
   - Or **Moondream2** in int4 (about 2 GB), which can also answer follow-up
     questions.
3. **Merge with detections.** YOLO-World supplies positions, and the speech
   uses them: "বাম দিকে একটি চেয়ার, সামনে প্রায় দুই মিটার দূরে একটি দরজা".
   The caption supplies context: "a room with a desk and a window, daylight".
4. **Into Bangla:**
   - **The object-and-position sentence is built from a template,** which is
     exact: object names from the dictionary, sides and distances from the
     recorded prompts.
   - **The caption's free text** is translated by NLLB-200-distilled-600M,
     offline (CC-BY-NC: non-commercial only; it runs on the CPU to save GPU
     memory). Machine translation of a caption can be clumsy, so it is
     spoken after the template sentence, never instead of it.
5. **Safety filter** on the result (section 2). Speak at answer priority.
6. **Honest limits:** if the light is poor, or the model's confidence is low,
   say so: "আলো কম, বর্ণনা ভুল হতে পারে" (light is low, the description may
   be wrong).

**Order:** nearest and most relevant first (people, doors, steps, vehicles),
the rest after: the app's "proximity, not confidence" rule.

---

## 6. Identify mode

**Goal:** "এটা কী". The user holds something up or points the camera at it,
and hears what it is and its details.

1. **Focus.**
   - Use the object nearest the centre of the picture, or the one in the
     user's hand if a hand is detected.
   - If nothing is centred, say "জিনিসটা মাঝখানে ধরুন" (hold it in the
     middle) and guide as in Find.
2. **Name and details:**
   - Florence-2's region-description task on that crop gives the name.
   - Colour comes from the crop's pixels; it is reliable and needs no model.
   - Approximate size.
   - **Any text on it** comes from Read's OCR on the crop: brand, product
     name, expiry date.
3. **Follow-up questions,** for 20 s after the answer:
   - "রং কী?" (what colour?), "লেখা পড়ো" (read the writing), "কিসের প্যাকেট?"
     (what packet is it?).
   - Moondream2 answers visual questions offline in English; NLLB translates
     the answer. Colour and text questions skip the model and use the
     direct methods above.
4. **Special cases,** stated honestly:
   - **Currency (Taka notes):** not in v1, the app's plan defers it to v1.5.
     The answer is "নোট মনে হচ্ছে, মান নিশ্চিত নয়" (looks like a note, value
     not certain) until a Bangladeshi-note dataset exists. Start collecting
     the pictures now.
   - **Medicine:** read the label only; **never a dose**.
   - **Faces:** no recognition of who someone is (out of v1 for privacy).
     "একজন মানুষ" (a person) only.

---

## 7. Voice control

Two recognisers, as now. Each does what it is good at.

| Recogniser | For | Examples |
|---|---|---|
| Keyword model (DS-CNN), key K or long-press | single words, especially safety | থামো, জরুরি, পড়ো, খুঁজো, বর্ণনা, এটা কী, পরের, আগের, আবার |
| BanglaASR + router, SPACE | sentences and object names | "লাল ব্যাগটা খুঁজে দাও", "লেখাটা পড়ে শোনাও" |

Additions:

- The mode names join `firmware/stm32h743/tools/keywords.csv`: পড়ো,
  খুঁজো, বর্ণনা, এটা কী. Record them in notebook 02 and retrain in 03.
- **Push-to-talk stays.** No always-on wake word: on a laptop in a noisy
  room it would trigger falsely.
- **Router additions:**
  - READ: পড়ো, পড়ে শোনাও, read
  - DESCRIBE: বর্ণনা, সামনে কী
  - IDENTIFY: এটা কী, কী এটা, what is this, identify
  - FIND: খুঁজো + object, where is

---

## 8. Running it on a 4 GB GPU

Not every model fits at once, so only what the current mode needs is loaded.

| Model | Device | Memory | Loaded |
|---|---|---|---|
| YOLO-World-S (M) | GPU | ~0.5 GB (~1 GB) | always |
| BanglaASR (Whisper-small) | GPU fp32 | ~1 GB | always (voice) |
| Keyword DS-CNN | CPU | <1 MB | always |
| EasyOCR bn+en | GPU | ~0.3–0.5 GB | Read, Identify |
| Florence-2-large fp16 | GPU | ~1.6 GB | Describe, Identify |
| Moondream2 int4 | GPU | ~2 GB | Identify follow-ups (optional) |
| NLLB-200-600M | CPU | (RAM 2.5 GB) | Describe, offline Bangla |
| MMS-TTS Bengali | CPU | (RAM 0.2 GB) | always |

A small **model manager** loads on first use, keeps the last mode's models
warm, and unloads others when GPU memory would exceed about 3.5 GB.
Florence-2 and Moondream2 are never resident together.

**Latency targets.** These are the app's ladder; the earcon always comes
first:

| Action | Earcon | First word |
|---|---|---|
| Hazard | at once | ≤ 0.2 s (already met) |
| Find guidance ping | — | every frame (~30 ms) |
| Describe and Identify | "দেখছি…" (looking) earcon | ≤ 3 s, by measurement |
| Read | the shutter earcon | ≤ 3 s after capture, by measurement |

---

## 9. Laptop setup for a blind user

- **Camera:**
  - The lid camera points at the user, not the world.
  - Buy a **USB webcam on a chest or neck clip** (about ৳1,500–3,000 in
    Bangladeshi shops), or use a phone as a webcam (DroidCam / Windows Phone
    Link).
  - Set it with `CAMERA_INDEX` and measure its field of view (notebook 01).
- **Audio:** an open-ear or bone-conduction headset, so traffic and voices
  stay audible. Stereo is needed for the left/right ping.
- **Control without a screen:**
  - Everything is reachable by voice and by large keys: SPACE, and the F and
    J home-row bumps.
  - The window is only for a helper.
- **Start-up:** `run_assistant.bat` runs at Windows login, and the device
  says the modes once.

---

## 10. Phases and gates

| Phase | Work | Gate (checked by someone other than the builder) |
|---|---|---|
| **A** (1 week) | Low-light handling, tracking with the 3-of-5 rule, mode framework and earcons, safety filter on generated text, router and keyword additions | Blindfolded tester switches between all four modes by voice, 10 of 10 commands correct, and no flicker-driven repeats in 5 minutes |
| **B** (1–2 weeks) | Read mode: capture assistance, EasyOCR, reading order, controls, Bangla sentence split | A blindfolded tester reads one printed Bangla page and one English page unaided. Character error rate measured on a fixed 20-page set. |
| **C** (1 week) | Find mode: any object via the dictionary, ping guidance, lost/found | Five objects placed around a room, each found within 30 s in at least 4 of 5 tries |
| **D** (1–2 weeks) | Describe (Florence-2 + positions + translation) and Identify (focus, region description, colour, OCR on the object, follow-ups) | 20 scenes and 20 objects, each answer judged right / partly right / wrong by two people. Blind testers rate usefulness. |
| **E** (1 week) | Model manager and memory budget, latency tuning, the **network-unplugged** run of every gate, field test with 3 blind users | Every latency target met. One-hour session without a crash. Debrief notes. |

---

## 11. Risks and licences

| Risk | Mitigation |
|---|---|
| Offline Bangla OCR is mediocre (about 78% word accuracy) | Say so to the user. Two engines vote per line. Capture assistance raises picture quality, which matters more than the engine. Later: fine-tune on photos of Bangladeshi print (textbooks, newspapers, labels) taken with the device itself. |
| A wrong description is believed | Hedge words ("মনে হচ্ছে", it seems), hazard objects first, no safety claims, and obstacle warnings stay rule-based |
| 4 GB GPU memory | Load per mode (section 8); NLLB and TTS on the CPU |
| Licences | **MMS-TTS and NLLB-200 are CC-BY-NC (non-commercial).** Florence-2 is MIT. EasyOCR is Apache-2.0. YOLO-World via Ultralytics is AGPL-3.0. Fine for a student project; anything sold needs replacements or licences. |
| Privacy | Nothing leaves the laptop: every model is local. Frames are not stored except by the explicit dataset tools. |
| A model that phones home | Set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` and turn off Ultralytics' update and settings checks, so a missing network never stalls or fails a command |

---

## 12. Decisions needed

1. ~~Offline or cloud?~~ **Decided: offline only.**
2. **Which problem did you see** with the current model (section 1)? It
   decides what phase A fixes first.
3. **Camera:** the laptop lid camera for now, or a USB chest camera or a phone
   as webcam?

---

## Sources

- [Bengali OCR benchmark, EasyOCR vs Tesseract (IDEAS/RePEc, 2024)](https://ideas.repec.org/a/dbk/rlatia/v2y2024ip98id1062486latia202498.html)
- [Florence-2 in Transformers](https://huggingface.co/docs/transformers/model_doc/florence2)
- [Moondream specifications (INT4 memory)](https://docs.moondream.ai/specifications)
- [NLLB-200-distilled-600M model card (CC-BY-NC)](https://huggingface.co/facebook/nllb-200-distilled-600M/blob/main/README.md)
- Qwen2.5-VL lists no Bengali among its OCR languages, so it is not used here: [model listing](https://openrouter.ai/qwen/qwen2.5-vl-3b-instruct:free/providers)
