#pragma once

#include <stdint.h>

// Push-to-talk keyword spotting. The button opens a 1.5 s window; the loudest
// one-second stretch of it is classified once. Push-to-talk rather than an
// always-on wake word: the physical button stays the primary path, and a
// device that wakes on street noise gets switched off.
//
// The model comes from Edge Impulse (see the README). Without one, available()
// is false and the button keeps its phase-one meaning.
namespace kws {

enum class Command : uint8_t {
  None,
  Emergency,
  Stop,
  Repeat,
  WhatIsAhead,
  Battery,
  Help,
  Bangla,
  English,
  Find,     // an object's name; `label` says which (vision::fromLabel)
  Unknown,  // heard something, below confidence or not a command
};

void begin();
bool available();
const char *modelInfo();

void startListening(uint32_t nowMs);
bool listening();

// True once, when a listening window has been classified.
bool poll(uint32_t nowMs, Command &cmd, float &confidence, const char *&label);

const char *commandName(Command c);

}  // namespace kws
