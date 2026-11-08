#pragma once

#include <stdint.h>

uint16_t chipRevisionId();
const char *chipRevisionName();

// Restarts into the chip's USB DFU boot loader, as holding BOOT0 would.
// Used by the `dfu` console command so uploads need no button presses.
[[noreturn]] void requestBootloader();
