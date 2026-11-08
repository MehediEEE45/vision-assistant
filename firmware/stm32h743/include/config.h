#pragma once

// Tunables. Every number here is expected to move during field testing; the
// reason each one starts where it does is next to it.

#define FW_VERSION "0.1.0"

// ---------------------------------------------------------------------------
// CPU
// ---------------------------------------------------------------------------

// 240 MHz is inside spec on both silicon revisions. The board package's own
// clock setup runs 480 MHz, which only revision V supports; revision Y stops
// at 400 MHz. Keyword spotting needs a small fraction of 240 MHz.
#define CPU_CLOCK_MHZ 240

// ---------------------------------------------------------------------------
// Audio: INMP441 in, MAX98357A out, one I2S bus
// ---------------------------------------------------------------------------

#define AUDIO_SAMPLE_RATE 16000

// 256 frames = 16 ms per DMA half. Short enough that a hazard sound starts
// within one block, long enough that the interrupt rate stays trivial.
#define AUDIO_FRAMES_PER_HALF 256

// INMP441 with L/R tied to GND drives the left slot. If the mic level reads
// zero, the module's L/R pin is pulled high: set 1, or tie L/R to GND.
#define MIC_SLOT 0

// The INMP441 is -26 dBFS at 94 dB SPL, so normal speech arrives around
// -50 dBFS. +18 dB keeps speech well above the 16-bit noise floor without
// clipping a shout at arm's length.
#define MIC_GAIN_SHIFT 3

// Street noise in Bangladesh is loud; start high and let the user turn down.
#define SPEAKER_VOLUME_PERCENT 85

// ---------------------------------------------------------------------------
// Distance sensor (VL53L1X preferred, VL53L0X detected automatically)
// ---------------------------------------------------------------------------

#define TOF_I2C_CLOCK_HZ 400000

// VL53L1X long mode reaches 3.6 m indoors but only 0.73 m in strong ambient
// light; short mode holds 1.35 m in the same light (datasheet DS12385 rev 8,
// section 3.5.1). So: long indoors, short when the ambient count says sunlight.
#define TOF_MODE_AUTO 1

// Ambient count rates reported by the sensor. Starting guesses: print them
// with the `status` command indoors, in shade and in sun, then set these.
#define TOF_AMBIENT_TO_SHORT_MCPS 5.0f
#define TOF_AMBIENT_TO_LONG_MCPS 2.0f

// Set to 1 if, once mounted, an object on the wearer's left is reported on
// the right. Which way round the sensor's SPAD array is depends on mounting.
#define TOF_ZONES_MIRRORED 0

// Sensing range spoken to the user. Deliberately below the datasheet maxima,
// which are for a white target: clothing, wood and bags reflect far less.
#define TOF_SPOKEN_RANGE_L1X_LONG_MM 2000
#define TOF_SPOKEN_RANGE_L1X_SHORT_MM 1000
#define TOF_SPOKEN_RANGE_L0X_MM 800

// ---------------------------------------------------------------------------
// Obstacle policy: same numbers as perception/obstacle-fusion/ObstaclePolicy.kt
// so the wearable and the phone app behave identically.
// ---------------------------------------------------------------------------

#define OBST_IMMEDIATE_MM 600
#define OBST_NEAR_MM 1200
#define OBST_APPROACHING_MM 2000
#define OBST_HYSTERESIS_MM 200
#define OBST_FRAMES_TO_CONFIRM 3
#define OBST_REANNOUNCE_IMMEDIATE_MS 1500
#define OBST_REANNOUNCE_NEAR_MS 3000
#define OBST_REANNOUNCE_APPROACHING_MS 6000

// Without an IMU there is no "walking" flag. A scene whose distance has not
// changed by more than this for this long is treated as standing still:
// a wall you are standing next to is not news.
#define OBST_STATIC_SCENE_MM 120
#define OBST_STATIC_SCENE_MS 2500

// The three VL53L1X zones overlap, so one obstacle can trip two of them a few
// frames apart. A second zone's alert at the same or a farther band inside
// this window is the same obstacle, not a new one.
#define OBST_CROSS_ZONE_MS 800

// At 0.9 m/s (typical white-cane walking speed) the approaching band is about
// two seconds out. Speak it; the haptic alone is easy to miss on a busy street.
#define OBST_SPEAK_APPROACHING 1

// ---------------------------------------------------------------------------
// Battery sense (optional): 100k/100k divider from the cell into PC0
// ---------------------------------------------------------------------------

#define BATTERY_SENSE_ENABLED 0
#define BATTERY_DIVIDER_RATIO 2.0f
#define BATTERY_LOW_VOLTS 3.50f
#define BATTERY_REANNOUNCE_MS (5UL * 60UL * 1000UL)

// ---------------------------------------------------------------------------
// Language
// ---------------------------------------------------------------------------

// Bangla first. Any prompt not yet recorded in Bangla falls back to English,
// and the console lists which ones at boot.
#define DEFAULT_LANGUAGE_BANGLA 1

// ---------------------------------------------------------------------------
// Voice commands (phase 2). Define KWS_EI_HEADER to the header of an Edge
// Impulse Arduino library placed in lib/, for example in platformio.ini:
//   build_flags = ... -D KWS_EI_HEADER=\"vision_kws_inferencing.h\"
// ---------------------------------------------------------------------------

// Below this confidence the device says it did not understand rather than
// guessing. A wrong "emergency" is worse than a repeat request.
// ---------------------------------------------------------------------------
// The board's LCD: captions of everything spoken, plus a status line. For a
// sighted helper, a teacher or a demo; the user never needs it.
// ---------------------------------------------------------------------------

#define LCD_ENABLED 1
// Memory-access control, the panel's orientation. 0x78 is landscape with the
// board's USB port on the left; 0xB8 turns the picture upside down. If red
// and blue come out swapped, toggle bit 3 (0x08).
#define LCD_MADCTL 0x78

// Live camera picture on the LCD, with captions over its lower part. Keeps
// the camera awake, which costs battery; for demos and bring-up. The
// console's `view on|off` changes it at run time.
#define LCD_CAMERA_VIEW 1
// About 8 frames a second: one frame takes ~20 ms to send to the panel,
// and the main loop has sensors and buttons to serve as well.
#define LCD_VIEW_FRAME_MS 120
// A finished sentence stays over the picture this long, then clears.
#define LCD_CAPTION_HOLD_MS 3000

// ---------------------------------------------------------------------------
// Camera (OV5640) and object recognition (phase 3)
// ---------------------------------------------------------------------------

#define CAMERA_ENABLED 1

// 320x240 RGB565 is 150 KB: far more pixels than a 96x96 model input needs,
// and small enough to sit beside the model in AXI SRAM.
#define CAMERA_WIDTH 320
#define CAMERA_HEIGHT 240

// Horizontal field of view of the lens. Common OV5640 DVP modules are 60-70
// degrees; measure yours (README, camera bring-up) and set it. It decides
// which third of the picture is "left" and whether an object is inside the
// ToF cone, so a wrong value turns into a wrong direction or distance.
#define CAMERA_HFOV_DEG 62.0f

// Set to 1 if a test image shows an object held on the wearer's left on the
// right of the picture. Left and right are the whole point of the guidance.
#define CAMERA_MIRROR 0
#define CAMERA_FLIP 0

// Set to 1 if test images come out with red and blue swapped.
#define CAMERA_SWAP_BYTES 0

// Exposure needs a few frames to settle after the sensor wakes; frames from
// that window are too dark to recognise anything in.
#define CAMERA_WARMUP_MS 400

// The ToF "ahead" zone is the middle half of a ~19 degree cone. An object is
// given a distance only when its centre lies inside it: otherwise the
// distance would belong to whatever the laser actually hit.
#define TOF_AHEAD_HALF_ANGLE_DEG 5.0f

#define VISION_MIN_CONFIDENCE 0.60f

// During a search, "ahead" means within this angle of straight on.
#define FIND_AHEAD_DEG 10.0f
// No sighting for this long ends the search with "not found".
#define FIND_TIMEOUT_MS 30000
// Guidance pacing. Faster than this is noise; slower and a user turning at
// normal speed sweeps past the object between nudges.
#define FIND_HAPTIC_MS 700
#define FIND_SPEECH_MS 3000

// An Edge Impulse Arduino export carries its own copy of the SDK, so two of
// them cannot link into one firmware. To run voice commands and object
// recognition together, merge both projects with Edge Impulse's multi-impulse
// deployment and adapt kws.cpp and vision.cpp to its entry points.
#if defined(KWS_EI_HEADER) && defined(VISION_EI_HEADER)
#error "Two Edge Impulse libraries cannot share one firmware; see the README, Edge Impulse multi-impulse"
#endif

#define KWS_MIN_CONFIDENCE 0.70f
// Emergency starts a siren in public, so it needs more certainty than the
// rest. Holding the button for four seconds is the dependable path.
#define KWS_EMERGENCY_CONFIDENCE 0.85f
#define KWS_LISTEN_MS 1500
