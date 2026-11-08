#pragma once

#include <stdint.h>

// The two things the camera is for:
//   describe  one picture: which known objects are where ("chair, left")
//   search    keep looking for one named object and steer the user to it,
//             metal-detector style, until found ahead, stopped or timed out
//
// The camera wakes only for these and sleeps as soon as they end.
namespace finder {

enum class Mode : uint8_t { Idle, Describe, Search };

Mode mode();
uint8_t target();  // the object being searched for, valid in Mode::Search
bool describe(uint32_t nowMs);
bool search(uint8_t object, uint32_t nowMs);
void stop(bool announceIt);
void poll(uint32_t nowMs);

}  // namespace finder
