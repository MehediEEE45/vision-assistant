#include <Arduino.h>

#include "board_pins.h"
#include "buttons.h"

namespace buttons {

namespace {

constexpr uint32_t kDebounceMs = 25;
// Slower than a phone's double-tap window: some users press deliberately.
constexpr uint32_t kMultiClickGapMs = 400;
constexpr uint32_t kLongMs = 1200;
constexpr uint32_t kAlarmMs = 4000;

bool g_rawLast = false;
bool g_stable = false;
uint32_t g_rawChangedMs = 0;
uint32_t g_downAtMs = 0;
bool g_alarmFired = false;
uint8_t g_clicks = 0;
uint32_t g_lastReleaseMs = 0;
bool g_downEventPending = false;

bool readRaw()
{
  const bool board = digitalRead(PIN_BUTTON_BOARD) == HIGH;
  const bool ext = digitalRead(PIN_BUTTON_EXT) == LOW;
  return board || ext;
}

}  // namespace

void begin()
{
  pinMode(PIN_BUTTON_BOARD, INPUT_PULLDOWN);
  pinMode(PIN_BUTTON_EXT, INPUT_PULLUP);
  g_rawLast = g_stable = readRaw();
}

bool held() { return g_stable; }

Event poll(uint32_t nowMs)
{
  const bool raw = readRaw();
  if (raw != g_rawLast) {
    g_rawLast = raw;
    g_rawChangedMs = nowMs;
  }

  if (raw != g_stable && nowMs - g_rawChangedMs >= kDebounceMs) {
    g_stable = raw;
    if (g_stable) {
      g_downAtMs = nowMs;
      g_alarmFired = false;
      g_downEventPending = true;
    } else {
      const uint32_t heldMs = nowMs - g_downAtMs;
      if (g_alarmFired) {
        g_clicks = 0;
      } else if (heldMs >= kLongMs) {
        g_clicks = 0;
        return Event::Long;
      } else {
        ++g_clicks;
        g_lastReleaseMs = nowMs;
        if (g_clicks >= 3) {
          g_clicks = 0;
          return Event::Triple;
        }
      }
    }
  }

  if (g_downEventPending) {
    g_downEventPending = false;
    return Event::Down;
  }

  if (g_stable && !g_alarmFired && nowMs - g_downAtMs >= kAlarmMs) {
    g_alarmFired = true;
    g_clicks = 0;
    return Event::Alarm;
  }

  if (!g_stable && g_clicks > 0 && nowMs - g_lastReleaseMs >= kMultiClickGapMs) {
    const uint8_t n = g_clicks;
    g_clicks = 0;
    return n == 1 ? Event::Single : Event::Double;
  }

  return Event::None;
}

}  // namespace buttons
