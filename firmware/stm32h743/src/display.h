#pragma once

#include <stdint.h>

// The board's 0.96" 160x80 LCD. Top line: language and what the device is
// doing (distances, find, menu, alarm). Below: a live caption of whatever is
// being spoken, in the language actually being heard, hazards in yellow on
// red. For whoever stands next to the user; the user never needs it.
namespace display {

bool begin();
void update(uint32_t nowMs);
bool ok();
// Colour bars, a border and "TOP", held for a few seconds: shows at a glance
// whether red and blue are swapped, the picture is upside down, or offset.
void testPattern(uint32_t nowMs);
// Live camera picture with captions over it (LCD_CAMERA_VIEW sets the default).
void setView(bool on);
bool viewOn();

}  // namespace display
