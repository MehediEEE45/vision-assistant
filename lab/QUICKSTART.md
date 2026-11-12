# Laptop prototype: macOS and Windows

Work on the `rehan` branch in this project folder. Python 3.11 is recommended;
3.12 is also accepted. `.venv/` at the repository root is the environment for
both systems. No Python source edits are needed when changing operating systems.

## Get this branch

Install Git and Python 3.11, then clone the laptop branch:

```bash
git clone --branch rehan --single-branch https://github.com/RehanulBary/vision-assistant.git
cd vision-assistant
```

This is the laptop branch in RehanulBary's fork. The original Android/wearable
repository is [MehediEEE45/vision-assistant](https://github.com/MehediEEE45/vision-assistant).

On another computer, create its environment with the setup script below. A Mac
`.venv` cannot be reused on Windows. The downloaded models are several GB; this
Mac's environment plus models/caches occupied about 7 GB before adding datasets
or notebook extras.

For the tested behavior and outstanding platform checks, see
[VALIDATION.md](VALIDATION.md). Windows adapters and regression tests are included;
native Windows camera, microphone and speaker testing is still required.

## macOS

From the repository root:

```bash
./lab/setup.command --dev --models
./lab/run_assistant.command
```

Setup uses an existing Python 3.11 installation when available. It installs
runtime packages and pytest, downloads the models, and checks package imports.
Models and caches stay inside `lab/models/`, `lab/.cache/` and Ultralytics' `weights/`
folder in the project; setup can be rerun.
`--models` is optional when models have already been downloaded.

The launcher runs offline by default. Grant camera and microphone access to
the app hosting Python (for example Terminal) when macOS asks. Permission can
be changed in System Settings → Privacy & Security → Camera / Microphone.

To select another camera or an outward-facing camera:

```bash
./lab/run_assistant.command --camera 1 --camera-facing forward
```

The default `--camera-facing user` is the built-in laptop webcam. It mirrors
directions to the user's perspective and disables obstacle warnings: a webcam
looking at the user cannot see where they are walking.

## Windows

Install Python 3.11, then from the `lab` folder:

```bat
setup.bat --dev --cpu --models
run_assistant.bat
```

The environment is `..\.venv\Scripts\python.exe`, independent of any developer's
username or old virtual environment. `--cpu` selects CPU PyTorch for the initial
setup. For NVIDIA acceleration, install a compatible CUDA-enabled PyTorch build
into this environment using the [official selector](https://pytorch.org/get-started/locally/)
and rerun setup without `--cpu`.
Camera and microphone permissions must be enabled for desktop apps in Windows Settings.

English speech uses Windows SAPI. Mac uses its built-in `say` engine. Both
render audio into the same interruptible mixer. Bangla speech uses MMS on both
platforms. Bangla captions use native CoreText on Mac and the Windows text engine
on Windows. Camera backends are selected automatically, with a fallback.

## Check the setup

On Mac, from `lab/`:

```bash
../.venv/bin/python -m va_lab.doctor
../.venv/bin/python -m va_lab.doctor --models --offline
../.venv/bin/python -m va_lab.doctor --hardware --camera 0
../.venv/bin/python -m pytest -q
```

On Windows, use `..\.venv\Scripts\python.exe` instead of `../.venv/bin/python`.

The default diagnostic checks imports, fixed prompt safety, native English speech
and captions. `--models` runs real detector, OCR, caption, translation, Bangla
speech and Bangla/English recognition inference on generated test inputs. It
does not open a microphone. `--hardware` lists audio devices and captures a
single camera frame without saving a photo. Results go to `test-results/doctor.json`.
`--skip-native` checks dependencies without OS speech/graphics, for CI.

To download selected model groups, from `lab/`:

```bash
../.venv/bin/python tools/download_models.py --only detector ocr caption translation voice asr
```

The command returns an error if any group fails; rerun it after fixing the reported
problem. Downloads need internet. After a complete download, the normal launcher
uses the cached models offline.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Camera cannot open | Grant access to Terminal/Python or the hosting app. Close other camera apps, run the hardware diagnostic, and try `--camera 1` if using an external camera. |
| Microphone fails or hears nothing | Grant microphone access, select the correct default input in OS settings, then press Space and speak after the tone. The hardware diagnostic lists available audio devices. |
| OpenCV says its window function is unavailable | Rerun setup. EasyOCR also installs a headless OpenCV distribution; setup restores the GUI wheel last. |
| Missing model while offline | Run the model downloader with internet access. Model files and caches are not part of the Git clone. |
| English voice is silent or fails | Check the installed macOS Samantha voice or Windows SAPI voice, then run the default diagnostic from Terminal/Command Prompt. A restricted execution sandbox can block native speech. |
| Slow first response | Models must load and text/audio caches must warm. Other models use CPU on Mac by default; the author's Windows timings in README.md are not Mac benchmarks. |
| K reports no keyword model | Use Space for speech recognition, or train the optional keyword model with notebook 03. |

When reporting a problem, include the command, the relevant console error and
`test-results/doctor.json`. Review any recognized document text before sharing it.

## Try each function

The OpenCV window must have keyboard focus. Use `Q` or Escape to close it.

| Test | Action | Expected result |
|---|---|---|
| Read | Press **R**, hold up a clearly printed English or Bangla page | Aiming hints, automatic capture, then speech. **P** pauses/resumes; **.** / **,** step paragraphs. Completion returns to idle. |
| Find | Press **1–8** to select person/chair/door/table/bottle/toilet/rickshaw/CNG, or **F** and say an object name | Directional pings and spoken guidance; a lost target eventually times out. Free-text search requires the default YOLO-World detector. |
| Describe | Press **D** | Object positions followed by a scene description in the selected language. |
| Identify | Press **I**, hold an object in the centre | A description, approximate dominant colour and any readable text. For 20 seconds, ask “রং কী” or “লেখা পড়ো”. |
| Voice input | Press **Space**, wait for the tone, speak within the 3-second window | Bangla or English command runs. **L** switches language. |
| Stop / switch | Start **D** or **I**, then press **S** or another mode key while it works | Cancelled results do not start speaking later. |
| Repeat / help | Say “আবার বলো” / “repeat”, or press **H** | Repeats the last answer or explains the controls. |

**K** is optional keyword spotting. Its trained `kws_custom.pt` or `kws_demo.pt`
must be produced through notebook 03; those training outputs are not distributed
with the repository. Space-based speech commands work without a keyword model.

## Device selection and limits

`VA_DEVICE=cpu` forces CPU execution. The detector uses Apple Metal when available,
or CUDA on compatible Windows machines. The other models default to CPU on Mac
and CUDA when available. `VA_DEVICE=mps` is an opt-in for testing Metal with the
other PyTorch models; CTranslate2 speech recognition uses its CPU/CUDA backend.
Actual latency depends on the hardware and model warm-up.

`requirements-macos.lock.txt` records the installed Mac package versions for
reproducing this environment. Windows uses the portable requirements and its
platform-specific dependencies. CI runs the regression tests on both systems.
CI does not download the large models or test physical cameras/microphones.

This is a webcam prototype. Distances are estimates based on assumed object sizes;
unknown obstacles may be missed. Bangla OCR and recognition can make mistakes.
Automated tests do not certify mobility safety or physical Windows device behavior.

Notebook/training extras are optional: rerun setup with `--notebooks`. It registers
the project environment as the `vision-ai-lab` Jupyter kernel inside `.venv`.
Use `open_notebooks.command` / `open_notebooks.bat` and select “Vision Assistant
(project)”, or select `.venv` in your editor.
