# Laptop validation record

Recorded on **2026-11-12** for the portable laptop work on `rehan`.
This records setup and smoke-test evidence, not an accuracy benchmark.

## Environment

| Item | Observed value |
|---|---|
| OS / architecture | macOS 27.2, arm64 |
| Python | 3.11.16, project-local `.venv` |
| PyTorch / torchvision | 2.15.0 / 0.29.2 |
| Transformers | 4.57.6 |
| EasyOCR | 1.7.2, Bengali/English plus an English-only recognizer |
| CTranslate2 / faster-whisper | 4.9.0 / 1.2.1 |
| OpenCV | 4.14.0, Cocoa window backend |
| Compute | Apple Metal for object detection; CPU for the other models |

The full Mac package snapshot is [requirements-macos.lock.txt](requirements-macos.lock.txt).
The portable setup uses [requirements.txt](requirements.txt), with OS-specific
dependencies selected by package markers. Windows requires its own environment.

## Automated regression checks

From `lab/`:

```bash
../.venv/bin/python -m pytest -q
```

**29 tests passed.** Coverage includes:

- macOS/Windows camera selection, backend fallback and native speech adapters;
- platform-independent Bangla model conversion and device overrides;
- reading completion and starting another page;
- cancelling background mode results, speech synthesis and speech recognition;
- rejecting silent speech caches and regenerating an invalid cache;
- bilingual intents, prohibited generated safety promises and obstacle confirmation;
- English OCR refinement while preserving Bengali text.

These tests mock OS devices and expensive model work. They do not measure
recognition accuracy or verify physical Windows hardware. The laptop GitHub
Actions workflow is configured to run them on macOS and Windows.

## Offline model checks

From `lab/`:

```bash
../.venv/bin/python -m va_lab.doctor --models --offline
```

**All 27 diagnostic checks passed** using cached models and generated inputs.
The command writes its detailed local report to `test-results/doctor.json`;
that generated report is ignored by Git.

| Check | Observed result | What it establishes |
|---|---|---|
| Dependencies / GUI backend | Imports succeeded; Cocoa available | Runtime packages and the preview backend load |
| Native speech / captions | English audio and joined Bangla caption masks produced | Mac native output adapters work outside the restricted sandbox |
| Object detection / free-text find | Inference, changing the query to “bag”, and restoring the default classes succeeded | Detector and query switching work on Metal; a generated page is not a real-object accuracy test |
| English OCR | `VISION ASSISTANT Read this page.` | The synthetic English page was read correctly after refinement |
| Bangla OCR | `চেয়ীর]` for the prompt `চেয়ার` | Bengali inference works, but this word was misrecognized; the smoke check only requires nonempty Bengali output |
| Scene caption | `vision assistant read this page` | Florence-2 inference works on the generated page |
| Object colour | Green | The colour classifier recognized a solid green test crop |
| English → Bangla | `একটা চেয়ার বাম দিকে।` | NLLB translation inference works |
| Bangla → English | `A chair` | Reverse translation inference works |
| Bangla speech | 2.56 seconds of audio | MMS generates non-silent speech |
| Bangla recognition | `সামনে কে আছে?` for synthesized `সামনে কী আছে` | BanglaASR runs offline; transcription is not exact |
| English recognition | `What is ahead?` | English speech recognition runs on synthesized speech |

Speech recognition here used synthesized audio, not a microphone recording.
Document OCR and generated descriptions can be incorrect despite a passing
inference smoke check. Inference timings vary with warm-up and hardware.

## Hardware and manual validation

The Mac hardware diagnostic detected a built-in microphone and stereo speakers.
The camera capture attempt was blocked by macOS camera authorization, so it did
not establish live camera behavior. Grant permission and rerun:

```bash
../.venv/bin/python -m va_lab.doctor --hardware --camera 0
```

Then follow the per-mode manual tests in [QUICKSTART.md](QUICKSTART.md#try-each-function).
Record results for Read, Find, Describe, Identify, voice input, stop/switch and
repeat before relying on a live demonstration.

**Windows hardware validation remains pending.** On Windows, run the same
diagnostics with `..\.venv\Scripts\python.exe`, then complete the manual tests.
Automatic OS selection and passing adapter tests do not guarantee identical
device behavior or performance on a different laptop.
