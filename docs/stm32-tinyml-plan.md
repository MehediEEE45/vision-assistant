# STM32H743 + ToF: offline obstacle direction and voice, on the board

Plan for a standalone, fully offline wearable built from an STM32H743VIT6 core
board, a VL53L1X (or VL53L0X) time-of-flight sensor and an OV5640 camera.
The firmware for all three phases is in
[`firmware/stm32h743/`](../firmware/stm32h743/README.md) and builds today.
The models for phases two and three still have to be trained.

Researched November 2026. Prices are Bangladeshi shop listings at that time;
check the shop before buying.

---

## 1. The short answer

**What these two parts can do, offline, with about ৳1,200–1,500 of extra
parts from Bangladeshi shops:**

- Warn about obstacles at chest and head height, **vibration first, speech
  second**, with direction (left / ahead / right) on a VL53L1X and "ahead"
  only on a VL53L0X.
- Speak in Bangla and English from recorded prompts. Distances are given in
  half metres ("দেড় মিটার", "আড়াই মিটার").
- Run without a phone, a network or an app: one button for "what is around
  me", repeat, help, language and an emergency siren.
- In phase two, understand about 14 spoken Bangla and English commands on
  the board itself (push-to-talk keyword spotting), once you have recorded
  the training data, which nobody has published yet.
- In phase three, with the 5 MP OV5640 camera, say which of eight known
  objects are around ("chair, left") and steer the user to one they name
  ("chair, right" … "chair, ahead, one metre"). The objects are person,
  chair, door, table, bottle, toilet, rickshaw and CNG (section 9b).

**What this microcontroller cannot do, whatever the model:** understand free
speech, speak arbitrary Bangla text (neural TTS), run a language model, or
read Bangla print. Those need the phone or the cloud; see the main
[plan](plan.md).

**The three things that decide whether it works:**

1. **Sunlight.** In strong ambient light, VL53L1X range drops from 3.6 m to
   **0.73 m in long mode**, but holds **1.35 m in short mode**. The VL53L0X
   manages about **0.5–0.8 m outdoors** even when overcast. The firmware
   switches the VL53L1X to short mode automatically, but outdoors you will
   need an ultrasonic sensor as well (section 8).
2. **The cone is narrower than the body.** A 27° diagonal field is about
   0.33 m wide at 1 m, while shoulders are about 0.45 m. Obstacles at the
   shoulder can be missed at close range. A wide 8×8 sensor fixes this
   (section 8).
3. **There is no Bangla keyword data.** The 50-language MLCommons spoken-words
   corpus has no Bengali, and no public Bangla command set matches this
   vocabulary. You have to record it yourselves (section 9).

The device **adds to the white cane; it does not replace it.** It sees
nothing at the feet: no steps, kerbs, drains or holes. Every user must be
told this in their own language before they use it.

---

## 2. What you have (verified)

### The board

The listing is a ROBOTICSSIGN copy of the **WeAct Studio MiniSTM32H7xx**
design. The PlatformIO board `weact_mini_h743vitx` and its pin map match it.

| | |
|---|---|
| MCU | STM32H743VIT6, Cortex-M7, double-precision FPU, 2 MB flash, 1 MB RAM, LQFP100 |
| Clock | up to **480 MHz on silicon revision V; 400 MHz on revision Y**. The revision letter is printed on the chip, and the firmware prints it too (REV_ID 0x2003 = V, 0x1003 = Y). |
| On board | 8 MB QSPI flash, 8 MB SPI flash, microSD, 0.96" ST7735 160×80 LCD, 8-bit DVP camera port (OV2640, OV5640, OV7670, OV7725), USB-C with DFU, key K1 (PC13), LED (PE3), 25 MHz and 32.768 kHz crystals |
| Power | 3.3–5.5 V in, on-board DC-DC 1 A |
| Radio | **none**: no Bluetooth or Wi-Fi (see section 13) |

The board package's own clock setup runs 480 MHz unconditionally, which is
out of specification on revision Y. The firmware therefore runs at
**240 MHz**, inside specification on both revisions and plenty for this
work.

### The sensor: which one is it?

You wrote VL53L0X, but the RoboticsBD link (product 3099) is a **VL53L1X**.
They are pin-compatible and look alike. The firmware reads each chip's
identity register and handles both, but they are not equal:

| | VL53L0X | VL53L1X |
|---|---|---|
| Range indoors (white target) | 1.2 m default, 2 m only in the dark "long range" profile | 3.6 m long mode, 2.9 m medium, 1.36 m short |
| Range in strong ambient light | 0.8 m white / 0.5 m grey (overcast, about 5 klux) | **0.73 m long mode, 0.76 m medium, 1.35 m short** |
| Field of view | 25° | 27° diagonal, programmable region of interest |
| Direction (left/right) | no | yes: move the region of interest across the 16×16 SPAD array |
| Max rate | about 30 Hz (33 ms budget) | 50 Hz in short mode (20 ms budget) |

From the ST datasheets: VL53L1X DS12385 rev 8 section 3.5.1 (timing budget
100 ms, 88% white target, 200 kcps/SPAD ambient); VL53L0X DocID029104 tables
11 and 13. Both are Class 1 eye-safe lasers.

**If yours is a VL53L0X:** it works for indoor "ahead" warnings. Buy a
VL53L1X for direction, and do not rely on either one alone outdoors.

---

## 3. What is feasible on the board, offline

| Capability | Offline on STM32H743? | How |
|---|---|---|
| Obstacle warning, haptic + speech | **yes, phase one** | ToF, obstacle policy ported from the app |
| Left / ahead / right | **yes** with VL53L1X | three overlapping regions of interest |
| Head-height warning | partly | tilt the sensor up 5–10°, or add a second sensor |
| Steps, kerbs, holes | **no** | needs a downward sensor and a different policy; the cane remains the answer |
| Sunlight robustness | partial | automatic short mode; ultrasonic in phase two |
| Glass doors and windows | **no** with ToF alone | ultrasonic echoes off glass |
| Speech output, Bangla + English | **yes** | recorded prompts, IMA ADPCM, about 8 KB/s |
| Voice commands (about 14 words) | **yes, phase two** | push-to-talk keyword spotting |
| Free speech recognition | no | needs a phone or the cloud |
| Text-to-speech of arbitrary text | no | no Bangla TTS small enough |
| Fall detection | yes, with an IMU | port of the app's fall state machine |
| Emergency call or SMS | no radio | standalone: loud siren and haptic; with the phone: SMS |
| Walking direction or compass | partial | needs a magnetometer or GPS; not in scope |
| Recognise known objects (8 kinds) | **yes, phase three** | OV5640 and a FOMO model, on demand only (section 9b) |
| Find an object by name | **yes, phase three** | button menu now; by voice once both models are merged |
| Recognise anything else, or read text | no | the model knows only what it was trained on; reading is the phone's job |

---

## 4. System design

```
 VL53L1X ─I2C──┐                    ┌─ haptics (left / right coin motors)   ← first, within 60 ms
 button ───────┤   obstacle policy  │
 INMP441 ─I2S──┤ → speaker arbiter →├─ MAX98357A → speaker (chest/shoulder) ← prompts and tones
 OV5640 ─DCMI──┤   keyword spotter  └─ USB console (bring-up, data recording)
 (MPU6050) ────┘   object finder
                       STM32H743 @ 240 MHz, everything offline
```

The firmware keeps the rules the phone app is built on:

- **One arbiter decides what is heard.** Hazard > manoeuvre > answer >
  ambient, the same ladder as `OutputArbiter`. A hazard cuts a sentence off
  mid-word with a 4 ms fade, and ambient news is dropped when anything else
  is playing.
- **Haptics lead and speech explains.** The motor starts before the sentence
  is queued.
- **Same thresholds as the app.** 600 / 1,200 / 2,000 mm bands, 3-frame
  confirmation, 200 mm hysteresis, and 1.5 / 3 / 6 s re-announce intervals
  are copied from `ObstaclePolicy.kt`. Standing still is silent.
- **Observations, never promises.** "Nothing detected. Sensing range about
  one metre." The prompt builder runs the app's banned-phrase list and fails
  the build on "safe", "clear", "নিরাপদ", "রাস্তা ফাঁকা" and the rest.
- **Failures are spoken.** No sensor at boot, sensor lost, sensor back,
  bright light with shorter range, and a watchdog restart each have a
  sentence of their own.

---

## 5. What to buy in Bangladesh

### Audio: the best fit on the local market

**Microphone: INMP441 I2S MEMS module**, at least seven Bangladeshi shops.

- Digital output straight into the MCU, so motor and power noise cannot get
  into the audio the way it does with an analogue mic such as the MAX9814.
- 24-bit; 64 SCK clocks per frame; SCK 0.5–3.2 MHz; sample rate 7.8–50 kHz
  (datasheet table 3). 16 kHz is inside that range, at 1.024 MHz SCK.
- It needs 2^18 clock cycles to start, which is 0.26 s at 16 kHz. The
  firmware discards that.

| Shop | Price |
|---|---|
| Biggan Project | ৳245 (+ shipping) |
| RoboticsBD | ৳259 (discounted), "original" version ৳730 |
| TechShopBD | ৳260 |
| ElectroXBD | ৳280 |
| Leetech, CityTech | ৳350 |

**Amplifier: MAX98357A I2S class-D, 3 W.**

- Digital input, no MCLK, no register setup.
- Shares the microphone's I2S clock, so one bus handles both directions.
- 8–96 kHz input, and gain selected by one pin.

| Shop | Price |
|---|---|
| ElectroXBD | ৳280 |
| Dunia | ৳365 |
| Biggan Project | ৳399 |
| RoboticsBD, BDTronics | ৳450 |

**Speaker:**

- TechShopBD "Stereo Enclosed Speaker 3W 4 Ohm", ৳260. Recommended: 4 Ω is
  louder from the MAX98357A at 5 V.
- RoboticsBD 3 W 8 Ω mini speaker, ৳250.

Wear it on the chest or shoulder. **Do not use earbuds**: a blind pedestrian
depends on hearing traffic.

*Considered and rejected:*

- An analogue mic with the board's ADC, or a DAC feeding a PAM8403: analogue
  wiring next to PWM-driven motors picks up their noise.
- WM8960 or ES8388 codec boards: they need I2C register setup and MCLK, are
  rarely stocked locally, and add nothing at 16 kHz.
- Bone conduction would keep the ears free. No component-level transducer
  was found in Bangladeshi shops; Adafruit's 8 Ω 1 W one is $8.95 imported,
  and finished bone-conduction headsets sell locally from ৳3,290. Worth
  trying in phase three.

### The rest of phase one

| Part | Price seen | Shop |
|---|---|---|
| 2 × 10 mm 3 V coin vibration motor | ৳85 / ~৳100 / ৳115 each | Leetech / RoboDoc / electronics.com.bd |
| 2 × NPN (S8050 or 2N2222), 2 × 1 kΩ, 2 × 1N4148, 100 µF, large tactile button, jumper wire, perfboard | small parts, not priced | any local electronics shop |

Phase one total: about **৳1,200–1,500** plus shipping.

### Phase two (recommended)

| Part | Price seen | Why |
|---|---|---|
| MPU6050 (GY-521) | ৳199–৳450 (RadioGearBD, ElectroXBD ৳230, TechShopBD ৳320, RoboticsBD ৳290–372) | walking detection, which replaces the "standing still" guess, and fall detection |
| HC-SR04 ultrasonic | ৳70–৳160 (RoboticsBD ৳125, TechShopBD ৳120) | works in sunlight and echoes off glass. It runs on 5 V: divide its echo pin down to 3.3 V. |
| 18650 cell + TP4056 charger with protection | TP4056 ৳25–৳65; TP4056 with 5 V boost ৳190 (TechShopBD) | a day of battery; buy the cell from a reputable shop (price not checked) |

### Phase three (import)

Multizone ToF was not found in any Bangladeshi shop:

| Sensor | Field of view | Range in about 5 klux | Price (Pololu, 1 pc) |
|---|---|---|---|
| VL53L8CX | 45°×45° | about 2.8 m | $24.95 |
| VL53L5CX | 45°×45° | about 1.7 m | $19.95 |
| VL53L7CX | 60°×60° | lower; one ST table shows 65 cm in strong light, so check the datasheet | $19.95 |

AliExpress modules are cheaper but vary in quality.

---

## 6. Wiring

The full table is in the [firmware README](../firmware/stm32h743/README.md#wiring).
In short:

- I2S2 on **PB12** (WS), **PB13** (CK), **PB14** (mic data in) and **PB15**
  (amplifier data out), in full duplex.
- ToF on I2C2 (**PB10** SCL, **PB11** SDA), XSHUT on **PD14**.
- Motors on **PA0** and **PA1** (TIM2 PWM at 20 kHz, above hearing).
- External button on **PD10**.

None of these pins is used by the LCD, the camera, either flash chip or the
microSD slot, so all of those remain available.

---

## 7. Mounting and timing

**Walking speed.** White-cane users walk at about **0.9 m/s**, falling to
about 0.6 m/s on difficult routes. A warning is only useful if it arrives
with time to act:

| Sensor and condition | Distance | Warning time at 0.9 m/s |
|---|---|---|
| VL53L1X long mode, indoors (conservative 2.0 m) | 2.0 m | 2.2 s |
| VL53L1X short mode, strong light (white / grey target) | 1.35 / about 1.0 m | 1.5 / 1.1 s |
| VL53L1X long mode, strong light: why the auto-switch exists | 0.73 m | 0.8 s |
| VL53L0X indoors (default mode) | 1.2 m | 1.3 s |
| VL53L0X outdoors, overcast (white / grey) | 0.8 / 0.5 m | 0.9 / 0.55 s |

A vibration reaches the user in about 150 ms. "Obstacle ahead" takes 1.05 s
to say (measured on the generated prompt).

**Head height is the gap worth filling.** In Manduchi and Kurniawan's survey
of more than 300 blind people, over 40% had a head-level accident at least
once a month. The cane finds what touches the ground; awnings, branches and
truck tailboards are what this device is for.

**Where to wear it.** On the chest at about 1.25 m, tilted up 5–10°. At
1.5 m, a 27° diagonal cone (about 19° per axis) spans roughly 1.0–1.5 m of
height level, or 1.25–1.75 m tilted up 10°. Decide in field testing, and
write down which heights you can and cannot see.

---

## 8. Direction: the options

| Option | Parts | Direction quality | Notes |
|---|---|---|---|
| **A. One VL53L1X, three ROI zones** (in phase one) | have it | coarse: thirds of a 19° cone | UM2555 regions: 8×16 SPADs centred on 167, 199 and 231. Ahead is sampled twice per sweep. |
| B. Two or three VL53L1X, angled | +1–2 sensors | good; fixed directions | XSHUT pins give each one a new I2C address at boot. Matches the app's left / centre / head frame. |
| C. VL53L8CX or VL53L7CX, 8×8 zones | import | best single sensor | 64 distances at 15 Hz; wide enough to cover the body at 1 m. |
| D. "Virtual cane": one sensor plus an IMU, user sweeps | MPU6050 | good if the user sweeps | IMU yaw tags each reading; research-grade, untested |
| E. HC-SR04 ahead, fused with ToF | ৳70–৳160 | ahead only | sunlight and glass; not a direction sensor |

**Recommendation:** A now; add E and the IMU in phase two; C in phase three.
With an 8×8 sensor, a small CNN can classify frames (wall, person, opening,
low obstacle). ST's model zoo already ships a CNN that runs on 8×8 frames
from these sensors on an STM32 (hand-posture recognition). Even then, the
warning itself stays rule-based: a model can add a label, but it must never
be the thing that suppresses a warning.

---

## 9. Voice: what "voice AI on the board" means here

### Input: push-to-talk keyword spotting

- Press once, a rising tone plays, then say one command. The firmware keeps
  1.5 s of audio, finds the loudest one-second stretch and classifies it
  **once**.
- Push-to-talk rather than an always-on wake word. Street noise would trigger
  a wake word, a false "emergency" in public is worse than a missed one, and
  the physical button stays the primary path.
- Because there is one inference per press, latency and power stop mattering.
  For scale: on an STM32H7A3 at 280 MHz, X-CUBE-AI runs the MLPerf Tiny
  image-classification model in about 43 ms, and keyword networks are
  smaller than that.
- **Vocabulary** (`firmware/stm32h743/tools/keywords.csv`) is taken from the
  app's offline-reachable intents in `IntentRouter`, so the phone and the
  wearable understand the same words:

  | Intent | Bangla | English |
  |---|---|---|
  | SOS | জরুরি | emergency |
  | Stop | থামো | stop |
  | Repeat | আবার বলো | repeat |
  | What is ahead | সামনে কী | what is ahead |
  | Help | সাহায্য | help |
  | Battery | ব্যাটারি | battery |
  | Bangla | বাংলা | Bangla |
  | English | ইংরেজি | English |

  Plus `_unknown` (other words, including near-misses such as থাকো and আবার
  on its own) and `_noise`.
- **Emergency needs 0.85 confidence**; everything else needs 0.70. Below
  that, the device says it did not understand rather than guessing.

### Data: you must collect it

**What exists:**

- MSWC (MLCommons, 50 languages, CC-BY 4.0) has Assamese and Odia but **no
  Bengali**.
- The Bangla speech sets found are BRADS/BRWDS (298 words, mostly regional,
  85 speakers, 2,439 clips, *Data in Brief* 2025), a 2025 isolated-word set
  (36 Bangla and 24 English words, 25 speakers, 1,800 clips) and a 10-class
  "short commands" study.

None of them has this vocabulary.

**Plan:**

- **Speakers.** At least 30 (mixed gender and age; standard, Sylheti and
  Chittagonian accents; include blind participants).
- **Clips.** 10 repetitions per keyword, which gives at least 300 clips per
  class. At least 1,000 `_unknown` clips and at least 20 minutes of `_noise`.
- **Noise.** Ceiling fans, rickshaw bells, traffic, markets and rain.
- **Microphone.** Record **through the device's own microphone**
  (`tools/record_dataset.py` streams it over USB). A model trained on a
  laptop microphone loses accuracy on an INMP441 in a case.
- **Splits.** Split train and test **by speaker**, never by clip.
- **Consent.** Signed consent for every speaker. Store anonymous codes only.
  The `dataset/` folder is git-ignored.

**Transfer learning.** Few-shot work ("Few-Shot Keyword Spotting in Any
Language", Mazumder et al., 2021, built on MSWC) and on-device customisation
studies, one of which reached up to 80% accuracy from 10 examples of unseen
words, show that a pretrained multilingual embedding needs far less Bangla
data. Use one if the first model falls short.

### Tool choice

| Tool | Cost | Why or why not |
|---|---|---|
| **Edge Impulse** (chosen) | free Developer plan | Upload clips, train a keyword model, export an Arduino library. The firmware adapter is `src/kws.cpp`. The company was reportedly acquired by Qualcomm in 2025: check the plan's terms. |
| ST Edge AI Core / X-CUBE-AI | free with an ST account, proprietary | STM32-optimised. ST reports 24–41% faster inference than TFLite Micro on its MLPerf Tiny runs. CubeMX workflow. The model zoo has audio-event detection (YAMNet, MiniResNet) and ToF hand posture, but no keyword spotting. |
| TensorFlow Lite Micro + CMSIS-NN | open source | Full control. The audio front end on the device must match training exactly, which is the classic silent failure. |

**Targets** (on held-out speakers):

- At most 5–10% of commands missed.
- **Zero** false "emergency" in an hour of street and market audio.
- Every confusion pair reviewed before a user hears the device.

### Output: recorded prompts, not TTS

- No Bangla text-to-speech engine fits on a microcontroller, and Windows has
  no Bangla voice (installed voices checked on this machine: David, Zira and
  Mark, all en-US).
- **English** prompts are synthesized offline with the Windows voice.
  **Bangla** prompts are recorded by a native speaker, which also sounds
  better to Bangla listeners.
- Storage: IMA ADPCM at 16 kHz is 8 KB/s. The 37 English prompts take
  489 KiB, and Bangla will be similar. Both fit in the 2 MB internal flash
  next to the firmware (584 KB in total today). The 8 MB QSPI flash is there
  for more.
- Quality: median ADPCM SNR is 24 dB across the prompts, and the worst is
  16 dB, on a short one.

---

## 9b. Camera: "what is ahead" and "find by name" (phase three)

The ToF knows *that* something is there; the camera can know *what* it is,
but only for the objects the model was trained on.

### How it works

- **On demand only.**
  - *Describe* takes one picture.
  - *Search* keeps taking pictures until the object is ahead, the user
    stops it, or 30 s pass without a sighting.
  - The rest of the time the sensor sits in software standby (registers
    kept, waking is one write). The first 400 ms after waking are discarded
    while exposure settles.
- **Picture to model.** A 320×240 RGB565 snapshot comes in over DCMI by DMA.
  It is **squashed**, not cropped, to the model's 96×96 input, because
  cropping would cut off the left and right edges, which are what the
  guidance is about. Train with Edge Impulse's resize mode set to Squash.
- **FOMO** (Edge Impulse) reports object *centres* on a grid rather than
  boxes. That is exactly what "left / ahead / right" needs, at a fraction of
  a box detector's cost.
- **Direction from the camera, distance from the laser.** A distance is
  given only when the object's centre lies inside the ToF "ahead" zone
  (±5°). Outside it, the laser's reading belongs to whatever it hit.
- **Guidance.** The left or right motor nudges the user (`TURN_LEFT` /
  `TURN_RIGHT` patterns, at most every 0.7 s) and the device says "chair,
  left". Ahead means within ±10°, and gets a long-short-long buzz plus
  "chair, ahead, one metre". Speech comes at most every 3 s.
- **Honest endings.** "Chair, not found", never "there is no chair": the
  camera saw only where it was pointed.
- **Obstacle warnings stay with the ToF** and the rule-based policy. The
  camera never suppresses a warning, and a describe report always ends with
  what the laser sees straight ahead, so an unrecognised obstacle is never
  silent.
- **Cost.** With no RTOS, the main loop pauses for one inference. That is
  tens of milliseconds for a small FOMO model; measure it in bring-up.

### Speed on this class of chip

| Model | Where measured | Speed |
|---|---|---|
| FOMO 96×96 | Edge Impulse, Arduino Nicla Vision (STM32H7) | 30 fps (vendor claim) |
| FOMO | OpenMV forum, H7 Plus | ~20 fps expected; one user measured 2.5 fps |
| ST YOLO LC v1, person only, int8 | ST model card, STM32H747 at 400 MHz | 179 ms at 192×192, 245 ms at 224×224, 321 ms at 256×256 |
| YOLOv5 | OpenMV forum, H7 Plus | about 0.3 fps |

Full 80-class detectors are not practical here. Measure your own model's
time on this board before judging the guidance.

### The eight objects, and where the data comes from

The objects were chosen for indoor independence (door, toilet, chair, table,
bottle) and for Bangladeshi streets (rickshaw, CNG, person).

- **COCO**, the usual pretraining set, has person, chair, bottle, toilet and
  dining table, but **no door and no rickshaw or CNG**.
- **DhakaAI** (2020 challenge): 3,953 images, 21 vehicle classes including
  rickshaw, auto-rickshaw and CNG, CC0 licence. It is street-camera footage,
  not chest height, so use it as a supplement.
- **IUT Dhaka indoor dataset** for visually impaired users: 5,196 images in
  8 indoor categories. Check its licence and classes before using it.
- **Most pictures should come from the device itself**, at chest height
  (`tools/capture_images.py`):
  - at least 150 per object;
  - homes, offices, corridors and streets, in daylight and tube light;
  - plus pictures with none of the objects.
  The keyword rule applies here too: train on the hardware the model runs
  on.

### What it will not do

- Small objects at a distance (keys, phones).
- Dark scenes.
- Anything outside the eight.
- Reading text.
- Judging whether a way is passable.

### Privacy and power

- Frames exist only in RAM, are overwritten by the next one, and are never
  stored or sent.
- Training pictures are a separate, explicit tool, and people in them must
  consent. `images/` is git-ignored.
- The sensor sleeps between uses. Measure its active current in bring-up.

### Voice and camera together

Each Edge Impulse Arduino export carries its own copy of the SDK, so two
cannot link into one firmware; `config.h` stops the build if both are set.
For a spoken "চেয়ার" to start a search, merge the keyword and object projects
with Edge Impulse's **multi-impulse** deployment, which produces one C++
library. Until then, "find" uses the button menu: press three times, once
for the next name, twice to search.

---

## 9c. Why PlatformIO, and when not

| Option | Verdict |
|---|---|
| **PlatformIO + Arduino core** (current) | **Keep it.** It is already installed, builds the whole firmware in about 40 s, and lives in VS Code. Audio, ToF, camera, arbiter and models are one C++ codebase. The HAL sits underneath (I2S, DCMI and DMA are configured with HAL directly), Edge Impulse Arduino exports drop into `lib/`, and ST-Link debugging works. |
| STM32CubeIDE | Worth it only for CubeMX's clock and pin GUI or X-CUBE-AI code generation. Switching now means rewriting the Arduino parts (Wire, Serial, PWM) in HAL for no gain. |
| OpenMV (MicroPython) | A good camera playground: OpenMV's own H7 camera uses the STM32H743, and WeAct publishes OpenMV support for this board. But it replaces this firmware, and audio, ToF and arbiter would need rewriting in MicroPython. Use it only as a lab tool for looking at the camera, then re-flash. |

---

## 10. Firmware as built

| Decision | Why |
|---|---|
| I2S2 full duplex for mic and amplifier | One clock pair, so the input and output rates can never drift apart. Four pins in total. |
| DMA buffers in AXI SRAM, D-cache maintained per half | DMA1 cannot reach DTCM, and the Arduino core enables the D-cache. |
| 16 ms audio blocks | A hazard sound starts within one block. |
| 240 MHz | Inside specification on both silicon revisions. |
| Watchdog, 4 s | A hung I2C bus or a firmware bug restarts the device, and the restart is announced. |
| I2C bus recovery, sensor re-detection every 2 s | A sensor that drops off comes back by itself, and the user is told both times. |
| Auto short mode in bright light | 73 cm versus 135 cm range in the sun. |
| "Standing still" = distance unchanged by 120 mm for 2.5 s | Stands in for the IMU's walking flag until there is one. |
| Cross-zone de-duplication, 800 ms | The zones overlap, and one obstacle must not produce two warnings. |
| ST's own OV5640 driver (BSD-3), DCMI settings copied from ST's OV5640 board support | Polarities and pixel clock as ST uses them; 12 MHz pixel clock, well under the 2.5:1 AHB-to-PIXCLK limit at 120 MHz AHB |
| Camera PA7 tried at both levels | Generic modules use it as power-down, WeAct's as supply enable; whichever answers on SCCB wins |

**What has been verified:**

- Compiles with zero warnings: 204 KB RAM, 747 KB flash, with the camera.
- The picture capture tool decodes RGB565 correctly (tested offline).
- The prompt pipeline, the safety-language check and the ADPCM round trip
  work.
- The dataset stream parser decodes framed audio correctly (tested offline).

**What has not:** nothing has run on hardware yet. The README has an
eight-step bring-up, in order.

---

## 11. Work plan, with gates

Each gate is checked by someone other than the person who built the part.

| Week | Work | Gate |
|---|---|---|
| 0 | Buy the phase-one parts | all in hand |
| 1 | Bring-up steps 1–8. Measure current with a USB meter. | All 8 pass. Ambient values recorded indoors, in shade and in sun. Battery hours estimated from measured current. |
| 2 | Chest mount or case. Tune thresholds in a corridor. | 10 minutes in a crowded corridor with **zero false alarms**, and every chest- or head-height obstacle announced before contact. This is the same gate as phase 2 of the main plan. |
| 3 | Outdoors: shade, sun, glass doors, a dark coat as the target | warning lead time measured for each case; decide on HC-SR04 |
| 4 | Record the Bangla prompts. Two or three blind listeners review the wording. | every prompt understood on first hearing, in traffic noise |
| 4–6 | Keyword data from 30+ speakers; train; evaluate on the device | the targets in section 9 |
| 7 | MPU6050: walking flag; port the fall state machine (free fall < 0.4 g for > 100 ms → impact > 2.5 g → 8 s still → spoken question → 30 s countdown → siren) | 50 simulated falls, true and false positives counted |
| 8 | HC-SR04 fusion for sunlight and glass | the sunlight gate from week 3 passes |
| 9–10 | Trials with 3–5 blind users and an orientation-and-mobility trainer. SUST ethics approval if you publish. | every user completes a familiar route; structured debrief |
| 11 | Camera bring-up (README steps 9–11): sensor ID, orientation, colour, field of view. Measure inference time and active current. | a picture from the wearer's position shows left as left |
| 11–13 | Pictures at chest height, at least 150 per object; label in Edge Impulse; train FOMO; test on the device | per-object recall measured on held-out rooms (not held-out pictures), at 1–3 m |
| 13 | Field test: describe and find, in three unfamiliar rooms and one street | a door found within 30 s in at least 4 of 5 tries; misrecognitions per describe counted; **no** recognition ever replaced a ToF warning |
| 14 | Blind users try find; debrief | which objects they actually want: revise the eight |

Blind users should hear the device from **week 4**, not week 10.

---

## 12. Testing and the numbers to keep

- **Per walk:** false alarms per hour; missed obstacles per 100; warning lead
  time (from video).
- **Voice:** missed commands (%); false accepts per hour of street audio;
  confusion pairs.
- **Device:** battery hours at 8 hours of mixed use; restarts per day; I2S
  error count.
- **Known blind spots, stated in every test log:** ground level, steps and
  drop-offs, glass (until there is an ultrasonic sensor), black or matte
  targets in sun, and anything outside the cone.

---

## 13. Using it with the Vision Assistant app later

The STM32H743 has no radio. To connect it to the phone:

- Add a **BLE bridge**, for example an ESP32-C3 module on USART3 (PD8/PD9),
  that serves the frozen GATT contract.
- `firmware/include/vision_gatt.h` is plain C and is already compiled into
  this firmware, so the haptic pattern numbers are identical.
- The left and ahead zones map onto `tof_left_mm` and `tof_centre_mm`. A
  second, tilted sensor would fill `tof_head_mm`.
- Adding ultrasonic or 8×8 data to the frame is a protocol change: update
  `Frames.kt`, `vision_gatt.h` and `docs/gatt.md` in one commit and bump the
  version (see `docs/gatt.md`).
- Before buying a BLE module, check that it can host a custom 128-bit
  service. ESP32 parts can.

---

## 14. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Short outdoor range in sunlight | Critical | Auto short mode (done). HC-SR04 in phase two. Speak the current range. |
| False alarms make users switch it off | Critical | App thresholds, standing-still silence, cross-zone de-duplication; tracked per hour from week 2 |
| Users trust it for steps and holes | Critical | Say it in training, in the help prompt and in the manual: it does not see the ground |
| Narrow cone misses shoulder-height obstacles at close range | High | Option B or C in section 8 |
| False "emergency" in public | High | Push-to-talk, 0.85 threshold, button-hold path, street-audio test |
| Bangla keyword data quality | High | Device microphone, 30+ speakers, accents, speaker-wise split |
| Clone board on revision Y | Medium | 240 MHz clock; revision printed at boot |
| Windows DFU driver | Medium | STM32CubeProgrammer installs it; ST-Link environment as fallback |
| Motor noise on I2C | Medium | Short wires, 100 µF near the motors, bus recovery in firmware |
| Voice recordings of real people | Medium | Consent, anonymous codes, `dataset/` git-ignored |
| A misrecognised object misleads the user | High | Eight objects only, 0.6 confidence, distance only inside the ToF cone, "not found" rather than "absent", ToF report always appended |
| Recognition fails in dim light or with a dirty lens | Medium | Say "No known object recognised" rather than guess; test under tube light and at dusk |
| Pictures of people | Medium | Frames never stored on the device; consent for training pictures; `images/` git-ignored |
| Loop pauses during inference | Medium | Small FOMO model; measure; a move to an RTOS is the fix if it grows |

---

## 15. Decisions for the team

1. **Which ToF chip is in the bag?** Flash and type `status`; the firmware
   reports it.
2. **Who records the Bangla prompts?** One voice for all of them.
3. **Mount position:** chest strap, shoulder or belt clip (test in week 2).
4. **When to order an 8×8 sensor:** it takes weeks to import, so order it in
   week 1 if you want it for week 8.
5. **Which eight objects?** The list is a starting proposal. Ask blind users
   in week 4 what they actually search for, and change `vision.h`,
   `prompts.csv` and `keywords.csv` together.
6. **Camera mount:** on the same plate as the ToF and pointing the same way.
   The "distance only inside the cone" rule assumes they are aligned.

---

## Sources

**Board**

- [WeAct MiniSTM32H7xx repository](https://github.com/WeActStudio/MiniSTM32H7xx)
- [Zephyr board documentation](https://docs.zephyrproject.org/latest/boards/weact/mini_stm32h743/doc/index.html)
- [Zephyr board device tree (pin map)](https://raw.githubusercontent.com/zephyrproject-rtos/zephyr/main/boards/weact/mini_stm32h743/mini_stm32h743.dts)
- [NuttX board page](https://nuttx.apache.org/docs/latest/platforms/arm/stm32h7/boards/weact-stm32h743/index.html)
- [Revision Y vs V (ST community)](https://community.st.com/t5/stm32cubeprogrammer-mcus/problem-stm32h743iit6-version-y-for-v/m-p/61493/highlight/true)
- [AN5312: migrating from revision Y to V](https://st.com/resource/en/application_note/an5312-.pdf)

**Sensors**

- [VL53L1X datasheet DS12385](https://www.makerguides.com/wp-content/uploads/2024/10/VL53L1X-Datasheet.pdf)
- [ST VL53L1X product page](https://www.st.com/en/imaging-and-photonics-solutions/vl53l1x.html)
- [UM2555: VL53L1X multiple-zone regions of interest](https://st.com/resource/en/user_manual/um2555-vl53l1x-ultra-lite-driver-multiple-zone-implementation-stmicroelectronics.pdf)
- [VL53L0X datasheet](https://www.elecrow.com/download/VL53L0X.pdf)
- Pololu carriers: [VL53L8CX](https://www.pololu.com/product/3419), [VL53L5CX](https://www.pololu.com/product/3417), [VL53L7CX](https://www.pololu.com/product/3418)
- [ST VL53L7CX/VL53L8CX flyer](https://www.st.com.cn/resource/en/flyer/vl53l7cx-vl53l8cx-flyer.pdf)
- Drivers: [pololu/vl53l1x-arduino](https://github.com/pololu/vl53l1x-arduino), [pololu/vl53l0x-arduino](https://github.com/pololu/vl53l0x-arduino)

**Audio**

- [INMP441 datasheet](https://arduino.ua/files/INMP441.PDF)
- [MAX98357A (Analog Devices)](https://www.analog.com/en/products/max98357a.html)

**Bangladeshi shop listings**

- INMP441: [Biggan Project](https://bigganproject.bd/en/sound-sensor/inmp441-i2s-mems-microphone-module), [TechShopBD](https://techshopbd.com/product/inmp441-omnidirectional-microphone-module), [RoboticsBD](https://store.roboticsbd.com/sensors/1753-inmp441-omnidirectional-microphone-module-robotics-bangladesh.html), [ElectroXBD](https://electroxbd.com/product/inmp441-omnidirectional-microphone-module/)
- MAX98357A: [ElectroXBD](https://electroxbd.com/product/max98357-audio-amplifier-board-electroxbd/), [Dunia](https://www.dunia.com.bd/product/max98357a-i2s-mono-amplifier-module-class-d-3w/), [Biggan Project](https://bigganproject.bd/en/class-d-amplifier/max98357a-i2s-audio-amplifier-module), [RoboticsBD](https://store.roboticsbd.com/electronics-module/2919-max98357a-i2s-dac-class-d-mono-amplifier-module-robotics-bangladesh.html)
- Speaker: [TechShopBD 3 W 4 Ω](https://techshopbd.com/product/stereo-enclosed-speaker-3w-4-ohm), [RoboticsBD 3 W 8 Ω](https://store.roboticsbd.com/sound-sensor-robotics-bangladesh/2307-stereo-enclosed-speaker-3w-8-robotics-bangladesh.html)
- Coin motors: [Leetech](https://leetechbd.com/product/vibration-motor-dc3v-flat-coin-mini/), [RoboDoc](https://robodocbd.com/product/coin-type-vibration-motor-10mm), [electronics.com.bd](https://www.electronics.com.bd/components-price-in-Bangladesh/vibration-micro-motor-3v-10mmx3mm-coin-shape)
- MPU6050: [ElectroXBD](https://electroxbd.com/product/mpu6050-sensor-electroxbd/), [TechShopBD](https://techshopbd.com/product/6dof-accelerometer-gyroscope-gy-521-mpu-6050)
- HC-SR04: [RoboticsBD](https://store.roboticsbd.com/sensors/22-ultrasonic-sonar-sensor-hc-sr04-robotics-bangladesh.html), [TechShopBD](https://techshopbd.com/product/sonar-sensor-hc-sr04)
- TP4056: [RoboticsBD](https://store.roboticsbd.com/chargers-balancer/1822-tp4056-1a-li-ion-lithium-battery-charging-module-with-current-protection-type-c-robotics-bangladesh.html), [TechShopBD (with boost)](https://techshopbd.com/product/tp4056-lithium-battery-charger-with-boost-converter)
- Bone conduction: [Adafruit transducer](https://www.adafruit.com/product/1674), [GadStyle headsets](https://www.gadstyle.com/category/electronics/earphones-headphones/bone-conduction/4592/)

**Users and mobility**

- [Obstacle alerts and walking speed of white-cane users (AAU)](https://vbn.aau.dk/en/publications/the-cost-of-knowing-how-obstacle-alerts-reduce-walking-speeds-of-)
- [Manduchi and Kurniawan, head-level and fall accidents survey (UCSC tech report)](https://tr.soe.ucsc.edu/sites/default/files/technical-reports/UCSC-SOE-10-24.pdf)

**Keyword spotting and data**

- [MLCommons Multilingual Spoken Words Corpus](https://mlcommons.org/datasets/multilingual-spoken-words/)
- [Few-Shot Keyword Spotting in Any Language](https://arxiv.org/pdf/2104.01454)
- [On-device customisation of tiny keyword models (KU Leuven)](https://lirias.kuleuven.be/retrieve/8559ab1c-1bfc-46ca-85cb-54c114f0752b)
- [BRADS/BRWDS Bangla regional speech](https://pubmed.ncbi.nlm.nih.gov/41210356/)
- [Bangla/English isolated words (2025)](https://arxiv.org/pdf/2507.07068)
- [Bangla short speech commands](https://www.researchgate.net/publication/328927003_Bangla_Short_Speech_Commands_Recognition_Using_Convolutional_Neural_Networks)
- [Arm ML-Zoo MicroNet-S keyword model](https://github.com/ARM-software/ML-zoo/blob/master/models/keyword_spotting/micronet_small/tflite_int8/definition.yaml)

**Tools and benchmarks**

- [STM32 model zoo](https://github.com/STMicroelectronics/stm32ai-modelzoo), [model zoo v4.0](https://stm32ai.st.com/model-zoo/)
- [STM32Cube.AI model performances (ST wiki)](https://wiki.st.com/stm32mcu/wiki/AI:STM32Cube.AI_model_performances)
- [ST and MLCommons](https://blog.st.com/mlcommons)
- [X-CUBE-AI and ST Edge AI Core versions](https://stcommunity.st.com/t5/edge-ai/what-s-the-newest-onnx-runtime-version-that-the-x-cube-ai-10-2-0/td-p/864360)
- [MLPerf Tiny benchmark paper](https://arxiv.org/html/2106.07597v4)
- [Edge Impulse Developer plan](https://forum.edgeimpulse.com/t/introducing-the-developer-plan-more-power-more-freedom-for-free/13998), [Edge Impulse C++ deployment](https://docs.edgeimpulse.com/hardware/deployments/run-cpp)

**Camera and object recognition**

- [ST OV5640 driver](https://github.com/STMicroelectronics/stm32-ov5640)
- [ST STM32H747I-DISCO camera BSP](https://github.com/STMicroelectronics/stm32h747i-disco-bsp)
- [WeAct camera connector pin map (Zephyr shield)](https://docs.zephyrproject.org/latest/boards/shields/weact_ov2640_cam_module/doc/index.html)
- [FOMO overview (CNX Software)](https://www.cnx-software.com/2022/04/18/fomo-faster-objects-more-objects-real-time-object-detection-embedded-systems/?amp=1)
- OpenMV forum: [FOMO frame rate](https://forums.openmv.io/t/how-to-increase-fps-in-edgeimpulse/10548), [detectors on H7](https://forums.openmv.io/t/deploying-object-detection-models-on-openmv-cam-h7-r2/8169)
- [ST YOLO LC v1 model card](https://huggingface.co/STMicroelectronics/st_yolo_lc_v1)
- [DhakaAI vehicle dataset](https://datasetninja.com/dhaka-ai), [YOLO on Bangladeshi traffic](https://arxiv.org/pdf/2212.09144)
- [Indoor object dataset for the visually impaired (IUT Dhaka)](https://repository.iutoic-dhaka.edu/items/d27e7c4b-f826-4e4b-8cbd-341908b30857)
- [Edge Impulse multi-impulse deployment](https://docs.edgeimpulse.com/docs/multi-impulse)
