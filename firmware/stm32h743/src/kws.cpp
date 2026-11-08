#include <Arduino.h>
#include <string.h>

#include "audio_i2s.h"
#include "config.h"
#include "kws.h"
#include "speaker.h"
#include "vision.h"

#if defined(KWS_EI_HEADER)
#include KWS_EI_HEADER
#define KWS_HAVE_MODEL 1
#else
#define KWS_HAVE_MODEL 0
#endif

namespace kws {

namespace {

enum class State : uint8_t { Idle, WaitForTone, Capture };
State g_state = State::Idle;

#if KWS_HAVE_MODEL

static_assert(EI_CLASSIFIER_FREQUENCY == AUDIO_SAMPLE_RATE,
              "the model must be trained on 16 kHz audio, the rate the microphone runs at");
static_assert(EI_CLASSIFIER_RAW_SAMPLE_COUNT == AUDIO_SAMPLE_RATE,
              "the model window must be one second");

constexpr size_t kWindow = AUDIO_SAMPLE_RATE;
constexpr size_t kCapture = (size_t)AUDIO_SAMPLE_RATE * KWS_LISTEN_MS / 1000;
static_assert(kCapture >= kWindow, "listening window shorter than the model window");

int16_t g_buf[kCapture];
size_t g_count = 0;
uint32_t g_quietSinceMs = 0;
const int16_t *g_window = nullptr;

// Raw int16 values as floats, unscaled: what Edge Impulse's audio blocks
// expect, and what its own numpy::int16_to_float produces.
int getData(size_t offset, size_t length, float *out)
{
  for (size_t i = 0; i < length; ++i) out[i] = (float)g_window[offset + i];
  return 0;
}

Command mapLabel(const char *label)
{
  struct Map {
    const char *prefix;
    Command cmd;
  };
  // Labels are <intent>_<language> (see tools/keywords.csv); the prefix is
  // the intent, so both languages land on the same command.
  static const Map kMap[] = {
      {"emergency", Command::Emergency}, {"stop", Command::Stop},       {"repeat", Command::Repeat},
      {"ahead", Command::WhatIsAhead},   {"battery", Command::Battery}, {"help", Command::Help},
      {"bangla", Command::Bangla},       {"english", Command::English},
  };
  for (const Map &m : kMap) {
    if (strncmp(label, m.prefix, strlen(m.prefix)) == 0) return m.cmd;
  }
  if (vision::fromLabel(label) >= 0) return Command::Find;
  return Command::Unknown;
}

size_t loudestSecond()
{
  size_t best = 0;
  uint64_t bestEnergy = 0;
  for (size_t start = 0; start + kWindow <= kCapture; start += AUDIO_SAMPLE_RATE / 10) {
    uint64_t e = 0;
    for (size_t i = start; i < start + kWindow; i += 4) {
      const int32_t v = g_buf[i];
      e += (uint64_t)(v * v);
    }
    if (e > bestEnergy) {
      bestEnergy = e;
      best = start;
    }
  }
  return best;
}

#endif

}  // namespace

void begin() {}

bool available() { return KWS_HAVE_MODEL != 0; }

const char *modelInfo()
{
#if KWS_HAVE_MODEL
  return EI_CLASSIFIER_PROJECT_NAME;
#else
  return "none";
#endif
}

void startListening(uint32_t)
{
#if KWS_HAVE_MODEL
  g_state = State::WaitForTone;
  g_quietSinceMs = 0;
  g_count = 0;
#endif
}

bool listening() { return g_state != State::Idle; }

bool poll(uint32_t nowMs, Command &cmd, float &confidence, const char *&label)
{
#if !KWS_HAVE_MODEL
  (void)nowMs;
  (void)cmd;
  (void)confidence;
  (void)label;
  return false;
#else
  switch (g_state) {
    case State::Idle:
      return false;

    case State::WaitForTone:
      // The listen tone must not be in the recording: the model never heard
      // it during training.
      if (speaker::busy()) {
        g_quietSinceMs = 0;
        return false;
      }
      if (g_quietSinceMs == 0) {
        g_quietSinceMs = nowMs;
        return false;
      }
      if (nowMs - g_quietSinceMs < 60) return false;
      audio::setMicCapture(true);
      g_count = 0;
      g_state = State::Capture;
      return false;

    case State::Capture: {
      g_count += audio::micRead(g_buf + g_count, kCapture - g_count);
      if (g_count < kCapture) return false;
      audio::setMicCapture(false);
      g_state = State::Idle;

      g_window = g_buf + loudestSecond();
      signal_t signal;
      signal.total_length = kWindow;
      signal.get_data = &getData;
      ei_impulse_result_t result = {0};
      if (run_classifier(&signal, &result, false) != EI_IMPULSE_OK) {
        cmd = Command::Unknown;
        confidence = 0.0f;
        label = "error";
        return true;
      }

      size_t top = 0;
      for (size_t i = 1; i < EI_CLASSIFIER_LABEL_COUNT; ++i) {
        if (result.classification[i].value > result.classification[top].value) top = i;
      }
      label = result.classification[top].label;
      confidence = result.classification[top].value;
      const Command c = mapLabel(label);
      const float needed = c == Command::Emergency ? KWS_EMERGENCY_CONFIDENCE : KWS_MIN_CONFIDENCE;
      cmd = confidence >= needed ? c : Command::Unknown;
      return true;
    }
  }
  return false;
#endif
}

const char *commandName(Command c)
{
  switch (c) {
    case Command::Emergency: return "emergency";
    case Command::Stop: return "stop";
    case Command::Repeat: return "repeat";
    case Command::WhatIsAhead: return "what-is-ahead";
    case Command::Battery: return "battery";
    case Command::Help: return "help";
    case Command::Bangla: return "bangla";
    case Command::English: return "english";
    case Command::Find: return "find";
    case Command::Unknown: return "unknown";
    default: return "none";
  }
}

}  // namespace kws
