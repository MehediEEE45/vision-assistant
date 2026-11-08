#pragma once

#include <stdint.h>

// One ToF sensor on I2C2. The chip is detected at boot: a VL53L1X gives three
// zones (left, ahead, right) by moving its region of interest; a VL53L0X has
// no region of interest and gives "ahead" only.
namespace tof {

enum class Chip : uint8_t { None, VL53L0X, VL53L1X };

enum Zone : uint8_t { ZONE_LEFT = 0, ZONE_AHEAD = 1, ZONE_RIGHT = 2, ZONE_COUNT = 3 };

struct Sample {
  Zone zone;
  bool valid;  // false = no target within range (or a failed reading)
  uint16_t mm;
  uint32_t atMs;
};

enum class Event : uint8_t { None, BrightLight, NormalLight, Fault, Recovered };

bool begin();
Chip chip();
const char *chipName();
bool zonesAvailable();

// Non-blocking. Returns true when a new zone reading is in `out`.
bool poll(uint32_t nowMs, Sample &out);

// Set by poll(); cleared by reading it.
Event takeEvent();

bool longMode();
float ambientMcps();
uint32_t errorCount();
bool faulty();

// Latest reading per zone, for the on-demand report.
bool latest(Zone zone, uint16_t &mm, bool &valid, uint32_t &ageMs, uint32_t nowMs);

// What the device tells the user it can see. Conservative on purpose.
uint16_t spokenRangeMm();

void setMirrored(bool mirrored);
bool mirrored();

}  // namespace tof
