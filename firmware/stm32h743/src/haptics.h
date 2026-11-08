#pragma once

#include <stdint.h>

// Two coin motors, left and right. Pattern numbers are the vision_pattern_t
// values from firmware/include/vision_gatt.h, so the standalone wearable and
// the phone-driven one feel identical.
namespace haptics {

void begin();

// Starts immediately; a new pattern replaces the one running. Haptics lead:
// this is called before any speech is queued.
void play(uint8_t pattern, uint8_t intensityPercent);
void stop();
void update(uint32_t nowMs);
bool active();

}  // namespace haptics
