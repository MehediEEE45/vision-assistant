#pragma once

#include <stdint.h>

// One logical button: the board's K1 and the external one act the same.
//
//   press once      Single   (what is around / push-to-talk with a model)
//   press twice     Double   (repeat)
//   press 3 times   Triple   (help)
//   hold 1.2-4 s    Long     (switch language), fires on release
//   hold 4 s        Alarm    fires while still held
//
// Long fires on release so that someone holding on towards the alarm never
// changes the language on the way there.
namespace buttons {

enum class Event : uint8_t { None, Single, Double, Triple, Long, Alarm, Down };

void begin();
Event poll(uint32_t nowMs);
bool held();

}  // namespace buttons
