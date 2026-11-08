# Vision Assistant — working notes

Accessibility assistant for blind and low-vision users in Bangladesh. Android
app plus an ESP32-S3 wearable. See `README.md` for the architecture and
`docs/plan.md` for the phased plan.

## Before changing anything

Two invariants are enforced by the build. Breaking either is not a style
question:

1. **A feature module must never depend on an output module.** Features submit
   an `Announcement` to `OutputArbiter`; the arbiter alone decides what the user
   hears. `./gradlew checkArchitecture`
2. **No string may promise the user that something is safe.** This app reports
   observations. `./gradlew checkSafetyLanguage`

If a change seems to require breaking one, the design is wrong — raise it rather
than adding an exception.

## Build

JDK 17 and Android SDK platform 34. On this machine, Android Studio's bundled
JBR works:

```powershell
$env:JAVA_HOME="C:\Program Files\Android\Android Studio\jbr"
./gradlew checkArchitecture checkSafetyLanguage test :app:assembleDebug
```

Gradle 8.9, AGP 8.7.3, Kotlin 2.0.21. AGP and Kotlin reach subprojects through
`buildSrc` convention plugins (`vision.android.library`, `vision.kotlin.jvm`) —
do **not** add a `plugins { ... apply false }` block to the root build file, or
plugin resolution fails with "already on the classpath with an unknown version".

## Testing the arbiter

`OutputArbiter` is an actor: submissions go on a channel, one loop drains it.
Tests must use `runTest(UnconfinedTestDispatcher())` so that loop runs eagerly —
with the default `StandardTestDispatcher`, `advanceUntilIdle()` does not execute
`backgroundScope` work and nothing happens at all.

`FakeClock` drives TTL and busy-window logic. Nothing in these tests sleeps.

## Testing on a device

Nobody can speak into the microphone or hold a page up from adb, so debug
builds ship `DebugCommandReceiver` (debug source set only). Send it explicitly:

```powershell
adb shell am broadcast -n bd.visionassistant.debug/bd.visionassistant.DebugCommandReceiver `
  -a bd.visionassistant.debug.UTTERANCE --es text "'next paragraph'"
```

Actions: `UTTERANCE`, `READ_TEXT`, `READ_IMAGE` (`--es path`, a file under the
app's own `Android/data/.../files`), `LISTEN`, `READ_PAGE`, `REPEAT`, `STOP`.

What was spoken and which gesture sent what are logged only when enabled —
page text is private:

```powershell
adb shell setprop log.tag.VisionSpeech DEBUG
adb shell setprop log.tag.VisionInput DEBUG
```

The whole screen is one button, so any hand on the phone during a test sends
real commands. Check `VisionInput` before calling a stray listen a bug.

## Layer rules

```
core, protocol   →  depend on nothing (protocol may use core)
spine            →  core
input            →  core, protocol
perception       →  core, protocol, input
output           →  core, protocol, spine
feature          →  core, spine, input, perception     (never output)
app              →  everything
```

## Facts worth not rediscovering

- **ML Kit text recognition does not support Bengali script** (Latin, Chinese,
  Devanagari, Japanese, Korean only). Bangla OCR must go to cloud. Do not
  advertise offline Bangla reading.
- **Bangla ASR needs a network.** The offline path is a fixed keyword vocabulary
  built from `IntentRouter`'s tables. Every intent marked
  `offlineReachable = true` must have a phrase there in both languages.
- **Bangla TTS is fine** — Google `bn-BD`/`bn-IN` with downloadable offline voice
  data. Check for it on first run; do not assume it is installed.
- **`।` (danda) terminates a Bengali sentence.** A boundary detector that only
  knows `.` treats a whole Bangla paragraph as one sentence, so every
  interruption restarts the paragraph.
- The GATT contract is frozen. Changing a frame layout means updating
  `Frames.kt`, `firmware/include/vision_gatt.h` and `docs/gatt.md` in one commit
  and bumping the protocol version.

## Style

Comments explain *why*, and only where the why is non-obvious — a threshold
chosen for a physiological reason, a rule that exists because of a specific
failure mode. No comments restating what the code does.
