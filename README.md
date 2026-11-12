# Vision Assistant

An Android + wearable assistant for blind and low-vision users in Bangladesh.
Obstacle warning, walking navigation, document reading and emergency help, in
**বাংলা** and English.

The full 26-week plan, with phase gates and the risk register, is in
[`docs/plan.md`](docs/plan.md).

## Laptop prototype: macOS and Windows

The `rehan` branch includes a portable laptop prototype in [`lab/`](lab/):
Read, Find, Describe and Identify, with Bangla/English speech and a webcam.
Camera, native English speech, captions and compute selection adapt to the OS.

Start with the **[laptop setup and testing guide](lab/QUICKSTART.md)**. It covers
fresh clones, the project-local Python environment, model downloads, launchers,
permissions, controls, troubleshooting and optional notebooks on both systems.
The **[validation record](lab/VALIDATION.md)** distinguishes automated tests,
offline model checks and hardware testing still to be completed.

On macOS, from the repository root:

```bash
./lab/setup.command --dev --models
./lab/run_assistant.command
```

On Windows, from `lab`:

```bat
setup.bat --dev --cpu --models
run_assistant.bat
```

Downloaded models, environments and personal recordings are generated locally;
they are not included in Git. Windows needs its own environment and downloads.
The architecture and Android build instructions below describe the phone and
wearable side of the project.

---

## The two rules everything else follows from

**1. No feature ever speaks or vibrates directly.**

For a sighted user's app the screen is the product. Here it inverts: the user
never sees a pixel, so the product *is* the sequence of sounds and vibrations
they receive. If every feature calls `TextToSpeech.speak()` on its own, a
hazard warning, a turn instruction and a book paragraph collide into noise —
and once a user stops trusting the device, no amount of later polish wins them
back.

So features build an `Announcement` and hand it to `OutputArbiter`, which alone
decides what is heard, deferred, dropped or resumed. `./gradlew
checkArchitecture` fails the build if a feature module so much as depends on an
output module.

**2. Haptics lead, speech explains.**

A vibration reaches the user's motor response in about 150 ms. "Obstacle on
your left" takes 1.4 seconds to finish. The buzz fires first, synchronously,
before the arbiter touches a queue. Speech is the footnote, never the alarm.

### The priority ladder

| | | Preempts | Budget to onset |
|---|---|---|---|
| **P0** | Hazard — collision, drop-off, vehicle | everything, mid-word | haptic 60 ms, audio 150 ms |
| **P1** | Maneuver — turn, arrival, off-route | P2 and below | 400 ms |
| **P2** | Answer — the user asked for this | P3 and below | 1200 ms to first word |
| **P3** | Ambient — battery, connection | nothing | best effort, dropped when busy |
| **P4** | Long-form — book and document reading | nothing | resumes ≤ 500 ms, at a sentence boundary |

Budgets are assertions, not aspirations. They are instrumented and asserted in
`OutputArbiterTest`.

---

## Layout

```
core/                 domain types: Announcement, Priority, HapticPattern, UserIntent
protocol/             BLE wire format + CRC-8, shared with firmware. FROZEN.
spine/
  output-arbiter/     the single point that decides what the user hears
  intent-router/      one bilingual synonym table, not two command sets
  session-state/      what the assistant is currently doing
  safety-policy/      phrases this app must never say
input/                wakeword, asr, camera, location, ble-link, gestures
perception/           obstacle-fusion, fall-detect, objects, ocr
output/               tts, earcons, haptics, messaging
feature/              navigate, reader, library, describe, sos, settings-voice
app/                  the foreground service that wires it together
firmware/include/     vision_gatt.h — the wearable half of the contract
firmware/stm32h743/   standalone offline wearable: STM32H743 + ToF + I2S audio
                      (plan: docs/stm32-tinyml-plan.md)
```

Dependencies run downward through the spine. A feature may not import an output
module; that is enforced, not merely documented.

---

## Build

Needs JDK 17 and the Android SDK (platform 34). Android Studio's bundled JBR
works.

```bash
./gradlew checkArchitecture checkSafetyLanguage   # the two policy gates
./gradlew test                                    # pure-JVM logic tests
./gradlew :app:assembleDebug
```

Both policy checks run in CI on every push and are the fastest signal that a
change has broken an invariant that matters.

---

## What is real, and what is a placeholder

**Working now** — the arbiter with full preemption, TTL expiry, tag supersession
and sentence-boundary resume; the BLE codec with CRC cross-checked against the
firmware header; the bilingual intent router; the obstacle policy with
hysteresis and multi-frame confirmation; the fall-detection state machine;
`AndroidSpeechEngine`; `WearableLink` with its watchdog; `WearableHapticEngine`
with a phone fallback.

**Interface only** — wake word, ASR, camera, location, object detection, OCR,
and every `feature/` module. Each carries the phase it lands in.

---

## Three things that will bite you

**Bangla OCR is the hardest dependency in the project.** ML Kit's on-device text
recognition covers Latin, Chinese, Devanagari, Japanese and Korean — *not*
Bengali script, and Tesseract's `ben` model is poor on real photographs of
newspapers. Bangla reading must go to cloud with an offline capture queue.
Measure the cost per page in week 1, before the reader is designed around it.

**Bangla speech recognition needs a network.** The offline path is a fixed
keyword vocabulary built from `IntentRouter`'s synonym tables, so every
safety-critical intent must have a phrase in that set. `UserIntent
.offlineReachable` marks them and a test asserts it.

**Battery is the top hardware risk.** A device that dies at 3pm is not an
assistive device. Camera off unless invoked; range sensors at 10 Hz walking and
1 Hz stationary; GPS at 1 Hz only while navigating.

---

## Safety posture

This application reports observations. It never certifies that an action is
safe. "Traffic light detected ahead" is something the user can act on with their
own judgement; "it is safe to cross" is a promise the system cannot keep, and
the consequence of being wrong is someone stepping into traffic.

`spine/safety-policy/src/main/resources/banned-phrases.txt` holds the phrase
list and `./gradlew checkSafetyLanguage` fails the build on a violation, in
either language.

Likewise, a detected fall never dials anyone on a sensor reading alone. It asks,
then counts down, and any signal of life cancels it.
