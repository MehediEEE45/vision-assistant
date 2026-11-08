#pragma once

#include <stdint.h>

#include "tof.h"

// USB serial console for bring-up and data collection. Type `help` in any
// serial monitor at 115200 (the rate is ignored over USB; any value works).
namespace console {

void begin(bool audioOk);
void poll(uint32_t nowMs);
void onSample(const tof::Sample &s);
bool streaming();

}  // namespace console
