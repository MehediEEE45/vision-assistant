#pragma once

#include <stdint.h>

class Print;

// OV5640 on the DVP connector, captured by DCMI one frame at a time.
//
// The sensor sleeps (software standby, registers kept) except while the user
// has asked for something: a description or a search. Frames are 320x240
// RGB565 in a single buffer that the next capture overwrites.
namespace camera {

bool begin();
bool present();
bool answered();  // something replied on SCCB, even if it was not a known sensor
uint32_t chipId();
const char *chipName();  // "OV5640", "OV7725", or "none"
// Lists what replies on the camera's I2C bus at both power-pin levels.
void scanBus(Print &out);
bool pwdnHighMeansOn();
bool vsyncPolarityLow();  // which DCMI_VSPOLARITY_* begin() measured for this module
const char *lastError();  // why begin() or the last capture failed; "" if nothing has

// Leave standby. Frames are usable CAMERA_WARMUP_MS later.
void wake(uint32_t nowMs);
void sleep();
bool awake();
bool warmedUp(uint32_t nowMs);

// Starts a snapshot if the sensor is awake, warmed up and idle.
bool capture(uint32_t nowMs);
bool capturing();

// True once, when the requested frame has landed and is safe to read.
bool poll(uint32_t nowMs);

const uint16_t *frame();  // CAMERA_WIDTH x CAMERA_HEIGHT, row-major RGB565
uint32_t frameSeq();      // increments each time a frame lands
uint32_t errorCount();

}  // namespace camera
