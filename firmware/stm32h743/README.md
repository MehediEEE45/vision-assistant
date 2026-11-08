# Standalone wearable: STM32H743 + ToF + I2S audio

Offline obstacle warnings with direction, spoken in Bangla and English, on a
WeAct-style STM32H743VIT6 core board. No phone, no network. The research and
the phased plan behind it are in [`docs/stm32-tinyml-plan.md`](../../docs/stm32-tinyml-plan.md).

**State:** compiles with zero warnings in this folder (`pio run`); 204 KB RAM
(150 KB of it is the camera frame) and 747 KB flash. It has **not yet run on
hardware**: every step of the bring-up below is the first time that part
meets a real board, so do them in order and stop at the first one that
fails.

---

## Parts

Phase one, all stocked in Bangladesh (prices and shops in the plan, section 5):

| Part | Why this one |
|---|---|
| VL53L1X ToF module (or VL53L0X) | Detected automatically at boot. VL53L1X gives left / ahead / right; VL53L0X gives ahead only. |
| INMP441 I2S microphone | Digital all the way to the MCU, so vibration-motor noise cannot get into the audio. 24-bit, 64 SCK per frame, 7.8–50 kHz. |
| MAX98357A I2S amplifier, 3 W | Digital in, no MCLK, no codec setup over I2C. Shares the microphone's clock. |
| 3 W speaker, 4 Ω (louder) or 8 Ω | Worn on the chest or shoulder. **Not earbuds**: a blind user needs their ears for traffic. |
| 2 × 10 mm 3 V coin vibration motors | Left and right. |
| 2 × NPN (S8050 or 2N2222), 2 × 1 kΩ, 2 × 1N4148, 1 × 100 µF | Motor drivers. |
| 1 × large tactile push button | The button a user can find by touch; K1 on the board is too small. |
| OV5640 5 MP camera on a 24-pin DVP ribbon (phase three) | Plugs into the board's camera connector. Used at 320×240 for recognising objects, not for photos. |

## Wiring

Every pin below avoids what the board already uses (LCD, camera, both flash
chips, microSD), so all of those stay available for later.

| Module | Module pin | Board pin |
|---|---|---|
| INMP441 | VDD / GND | 3V3 / GND |
| | SCK | **PB13** |
| | WS | **PB12** |
| | SD | **PB14** |
| | L/R | **GND** (left channel) |
| MAX98357A | VIN / GND | 5V / GND (5 V is louder; 3V3 also works) |
| | BCLK | **PB13** (same wire as the mic's SCK) |
| | LRC | **PB12** (same wire as the mic's WS) |
| | DIN | **PB15** |
| | GAIN, SD | leave unconnected (9 dB, on) |
| | speaker + / − | to the speaker only. **Never connect either speaker wire to GND**: the output is bridged. |
| VL53L1X / VL53L0X | VIN / GND | 3V3 / GND |
| | SCL / SDA | **PB10** / **PB11** |
| | XSHUT | **PD14** (optional; lets the firmware reset a hung sensor) |
| | GPIO1 | not connected |
| Left motor | | **PA0** → 1 kΩ → NPN base; emitter → GND; collector → motor −; motor + → 3V3; 1N4148 across the motor, cathode to + |
| Right motor | | **PA1**, same circuit |
| Button | | **PD10** to GND (internal pull-up) |
| Battery sense (optional) | | 100 k / 100 k divider from the cell + to **PC0**, then set `BATTERY_SENSE_ENABLED 1` |

Put the 100 µF capacitor across 3V3 and GND near the motors.

**Camera:** plug the OV5640 ribbon into the board's DVP connector with the
board unpowered, contacts the way WeAct's own module sits. Nothing else to
wire: the firmware drives the sensor's clock from PA8 (24 MHz), talks to it
on PB8/PB9, and tries both meanings of PA7 (power-down on most modules,
supply-enable on WeAct's) until the sensor answers. If your module is not
WeAct's, compare its 24-pin order with the WeAct schematic before plugging it
in.

## Flash it (Windows)

1. Open this folder (`firmware/stm32h743`) in VS Code with the PlatformIO extension.
2. Put the board in DFU mode: hold **BOOT0**, press and release **NRST**, release **BOOT0**.
3. The first time only, Windows needs a driver for "STM32 BOOTLOADER": install
   [STM32CubeProgrammer](https://www.st.com/en/development-tools/stm32cubeprog.html),
   which includes it.
4. PlatformIO → Upload (environment `weact_h743_dfu`), or `pio run -t upload`.
   It writes with STM32CubeProgrammer when that is installed. Plain dfu-util
   stops part-way on this chip with "get_status" error 74.
   With an ST-Link instead, use environment `weact_h743_stlink`.
5. The board restarts into the new firmware and appears as a USB serial port
   ("STMicroelectronics Virtual COM Port"). Open PlatformIO's Serial Monitor
   and type `help`.

**After the first flash, no more buttons.** Upload runs
`tools/pio_dfu_reset.py` first: it sends `dfu` to the running firmware,
which restarts into the USB boot loader, and the upload follows. Close any
serial monitor that holds the port first. If the firmware is hung or
missing, the script says so and you fall back to BOOT0 + NRST.

No driver or upload problem? STM32CubeProgrammer can also write
`.pio/build/weact_h743_dfu/firmware.bin` to `0x08000000` over USB.

## Bring-up, in this order

| # | Connect | Do | Expect |
|---|---|---|---|
| 1 | nothing | flash, `status` | silicon rev printed, core 240 MHz, audio running, sensor none. LED blinks fast (no sensor). The LCD shows the status line and the caption "Vision Assistant ready…". Press K1: the console prints `button: single`. Screen dark: `status` must say `display ok`; then `lcd` shows red, green, blue, white bars with a yellow border and "TOP" top right. Red and blue swapped: flip bit 0x08 of `LCD_MADCTL`. Upside down: `LCD_MADCTL 0xB8`. |
| 2 | amplifier + speaker | reset | boot chime, then "Vision Assistant ready. No distance sensor found…". `tone`, `say OBST_AHEAD`, `vol 50` all work. |
| 3 | microphone | `mic` | quiet room about −60 to −50 dBFS; speaking at 30 cm about −30 to −15. **−96 dBFS** means no data: check L/R to GND, or set `MIC_SLOT 1`. |
| 4 | ToF sensor | reset, `status`, `zones on` | sensor named, LED gives a short blip every two seconds. Readings change as a hand moves in front, and the LCD status line shows L/A/R distances. "sensor none": `i2c` must list 0x29 on the sensor bus; if not, check SDA/SCL and 3V3. |
| 5 | | hand on the wearer's **left**, `zones on` | `left` reads short. If `right` does, type `mirror`, then set `TOF_ZONES_MIRRORED 1` in `config.h`. |
| 6 | | `status` indoors, in shade, in sun | note the ambient Mcps in each; set `TOF_AMBIENT_TO_SHORT_MCPS` between shade and sun, `…_TO_LONG_MCPS` below shade. |
| 7 | motors | walk slowly at a wall | buzz on the correct side, then "Obstacle ahead. Two metres." / "…One metre.", then beep + "Obstacle ahead." under 60 cm. Standing still: silence after the first warning. |
| 8 | button | 1, 2, 3 presses; hold 2 s; hold 4 s | report of left/ahead/right; repeat; help; language change; alarm, any press stops it. |
| 9 | camera | reset, `cam` | `OV5640 id 0x5640` and which PA7 level powers it. "not found": reseat the ribbon. |
| 10 | | `python tools/capture_images.py --label test --count 1 --show` with a bottle held to the wearer's **left** | The bottle is on the **left** of the picture, the picture is upright and the colours are right. Otherwise set `CAMERA_MIRROR`, `CAMERA_FLIP` or `CAMERA_SWAP_BYTES` to 1 in `config.h`. |
| 11 | | stand 1.00 m from a wall, mark where the picture's left and right edges fall, measure the width W | horizontal field of view = 2 × atan(W / 2 m). Put it in `CAMERA_HFOV_DEG`: it decides what "left" means. |

Every number you change in step 6 or after field testing belongs in
`include/config.h`, with the reason next to it.

## Screen and LED

The board's own 0.96" LCD shows what the device is doing, for whoever stands
next to the user:

- **Top line:** language and state, for example `BN L1.2 A0.8 R--`
  (distances in metres; `--` means nothing in range, `??` no fresh reading),
  `FIND: chair`, `MENU: door`, `ALARM - press to stop`, `NO DISTANCE SENSOR`.
- **Below:** a live caption of whatever is being spoken. It is in the
  language actually heard, so English until the Bangla prompts are recorded.
  Hazards are yellow on red; finished sentences turn grey. Long text such as
  the help pages every 2.5 s.

The captions are pre-rendered on the PC (Bangla through Windows' text
engine, so joined letters come out right) by `tools/make_display_assets.py`,
which `make_prompts.py` runs for you. If the picture is upside down, set
`LCD_MADCTL 0xB8`; if red and blue are swapped, toggle bit 3 (`0x70`).

The **built-in button K1** is the device's button: no external button is
needed to start. The **built-in LED** (PE3) shows:

| LED | Means |
|---|---|
| short blip every 2 s | idle and healthy |
| steady on | speaking |
| medium blink | looking with the camera, or listening for a command |
| quick blink | no distance sensor: obstacle warnings are not working |
| fast flicker | alarm |

## Bangla voice prompts

Windows has no Bangla voice, so English prompts are synthesized and Bangla ones
are recorded by a person. Until they exist the device runs in English.

1. `python tools/make_prompts.py` prints every prompt that still needs a Bangla
   recording, with its text (all are in `tools/prompts.csv`).
2. One clear native speaker records each line in a quiet room, at a natural pace:
   phone voice recorder or Audacity, any sample rate.
3. Save each as `prompts/bn/<ID>.wav` (for example `prompts/bn/OBST_LEFT.wav`).
4. Run `python tools/make_prompts.py` again, then rebuild and flash.

The script refuses any prompt text containing a phrase from the app's banned
list (`spine/safety-policy/.../banned-phrases.txt`). The wearable follows the
same rule as the app: it reports what it observed and never says a way is safe.

## Voice commands (phase two)

Push-to-talk: press once, hear a rising tone, say one command. The vocabulary
is `tools/keywords.csv`, taken from the app's offline-reachable intents so the
phone and the wearable understand the same words.

1. Flash this firmware, then for each speaker:
   `python tools/record_dataset.py --speaker S01 --noise 120`
   (records through the device's own microphone; needs `pip install pyserial numpy`).
2. Upload: `edge-impulse-uploader --category split "dataset/*/*.wav"` into an
   [Edge Impulse](https://edgeimpulse.com) project.
3. Impulse: 1000 ms window, 16000 Hz; MFE or MFCC; keyword-spotting
   classifier. Train, then check the confusion matrix for `emergency_*` first.
4. Deploy as an **Arduino library**, unzip it into `lib/`, and add to
   `build_flags` in `platformio.ini`:
   `-D KWS_EI_HEADER=\"<project>_inferencing.h\"`
5. Build and flash. The button now listens; the report is the spoken command
   "সামনে কী" / "what is ahead".

The adapter in `src/kws.cpp` has not been compiled against a real Edge Impulse
export yet; expect to fix small API differences the first time.

`dataset/` is in `.gitignore`. It holds people's voices: never commit it.

## Object recognition: "what is ahead" and "find" (phase three)

The camera recognises eight objects: `person chair door table bottle toilet
rickshaw cng`. It runs only when asked, and the sensor sleeps otherwise.

**With a model installed, the button changes:**

| Press | Does |
|---|---|
| once | **describe**: up to three recognised objects with their side ("Chair, left. Person, ahead, two metres."), then what the laser sees straight ahead |
| three times | **find menu**: it says an object's name. Once = next name, twice = search for it, hold = cancel. |
| once, during a search | stop the search |

**While searching**, the side motor nudges you towards the object and the
device says "chair, left" or "chair, right". Once the object is ahead you feel
a long-short-long buzz and hear "chair, ahead, one metre": the distance comes
from the laser, and only when the object is inside its cone. After 30 s
without a sighting it says "chair, not found", never "there is no chair".

**Training the model (Edge Impulse FOMO):**

1. Pictures through the device's own camera, worn where it will be worn:
   `python tools/capture_images.py --label chair --count 60`.
   - Aim for at least 150 pictures per object, across homes, offices,
     corridors, streets, daylight and tube light.
   - Include pictures with **none** of the objects in them.
   - Rickshaws and CNGs: also look at the DhakaAI dataset (see the plan).
2. Upload with `edge-impulse-uploader --category split "images/*/*.png"`, then
   draw boxes in Studio using exactly the eight labels above.
3. Impulse:
   - Image block at **96×96**, resize mode **Squash**. The device squashes
     the full frame the same way, so training and the device see the same
     geometry.
   - Object detection block: **FOMO**.
   - Train, then check per-object accuracy on the test set.
4. Deploy as an **Arduino library**, unzip it into `lib/`, and add to
   `build_flags`: `-D VISION_EI_HEADER=\"<project>_inferencing.h\"`.

The adapter in `src/vision.cpp` has not been compiled against a real export
yet.

**Voice and camera together:** two Edge Impulse Arduino exports cannot link
into one firmware, because each carries its own copy of the SDK, and
`config.h` stops the build if both are set. Use Edge Impulse's multi-impulse
deployment to merge the two projects into one C++ library, and adapt
`kws.cpp` and `vision.cpp` to its entry points. Until then, use the button
menu for "find".

Pictures of people need their consent; `images/` is git-ignored.

## Code map

| File | What it owns |
|---|---|
| `src/audio_i2s.cpp` | I2S2 full duplex, DMA, D-cache maintenance, mic ring buffer |
| `src/speaker.cpp` | the priority ladder (hazard > manoeuvre > answer > ambient), ADPCM prompts, tones |
| `src/tof.cpp` | chip detection, three ROI zones, sunlight mode switching, fault recovery |
| `src/obstacle_policy.cpp` | port of the app's `ObstaclePolicy.kt` |
| `src/announce.cpp` | every sentence the device says |
| `src/haptics.cpp` | patterns from `firmware/include/vision_gatt.h` |
| `src/buttons.cpp` | one / two / three presses, hold, alarm hold |
| `src/kws.cpp` | Edge Impulse adapter (phase two) |
| `src/camera.cpp` | OV5640 power, clock, SCCB, DCMI snapshot by DMA, standby |
| `src/vision.cpp` | Edge Impulse FOMO adapter, frame squash, object table (phase three) |
| `src/finder.cpp` | describe and search: guidance, timeouts, ToF distance for centred objects |
| `src/display.cpp` | ST7735 LCD on SPI4: status line and live captions |
| `lib/ov5640/` | ST's OV5640 driver, unmodified (BSD-3-Clause) |
| `src/console.cpp` | USB console and the audio stream for data collection |
| `src/clock_config.cpp` | 240 MHz clock valid on both silicon revisions |
| `tools/` | prompt builder, caption renderer, voice dataset recorder, picture capture, auto-DFU upload hook, prompt and keyword lists |
