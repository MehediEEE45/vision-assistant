#pragma once

#include <stdint.h>

#include "prompt_ids.h"

// Everything the user hears goes through here, for the same reason the phone
// app routes everything through OutputArbiter: a hazard, an answer and a
// battery note that all start at once are noise, and a user who stops
// trusting the device stops wearing it.
namespace speaker {

// Same ladder as the app. Lower value wins.
enum class Priority : uint8_t {
  Hazard = 0,    // preempts everything, mid-word
  Maneuver = 1,  // preempts answers and ambient
  Answer = 2,    // something the user asked for
  Ambient = 3,   // dropped if anything else is playing
};

enum Tone : uint8_t {
  TONE_WARN = 0,  // two short high beeps ahead of a hazard word
  TONE_LISTEN,    // rising: speak now
  TONE_OK,
  TONE_ERROR,     // low: something failed
  TONE_BOOT,
  TONE_ALARM,     // two-tone siren, runs until stopAll()
  TONE_COUNT
};

constexpr uint8_t kMaxItems = 12;

// Item kinds, as stored in Item::kind.
constexpr uint8_t kItemPrompt = 0;
constexpr uint8_t kItemTone = 1;
constexpr uint8_t kItemPause = 2;

struct Item {
  uint8_t kind;  // see speaker.cpp
  uint16_t value;
};

struct Utterance {
  Priority priority;
  // Nonzero tags supersede: a newer utterance with the same tag replaces the
  // one playing instead of queueing behind it. A fresh obstacle reading
  // makes the previous one worthless.
  uint16_t tag;
  uint8_t count;
  Item items[kMaxItems];

  Utterance();
  explicit Utterance(Priority p, uint16_t tag = 0);
  Utterance &prompt(PromptId id);
  Utterance &tone(Tone t);
  Utterance &pause(uint16_t ms);
};

void begin();
void say(const Utterance &u);

// What is being spoken right now, for the screen's captions. `seq` changes
// whenever a new utterance starts; `item` is the index of the item playing.
struct NowPlaying {
  uint32_t seq;
  bool active;
  uint8_t item;
  Utterance utterance;
};
void nowPlaying(NowPlaying &out);
void stopAll();
void repeatLast();
bool busy();

void setVolumePercent(uint8_t percent);
uint8_t volumePercent();

void setBangla(bool bangla);
bool bangla();
bool hasBangla(PromptId id);
bool anyBangla();
uint16_t missingBanglaCount();

}  // namespace speaker
