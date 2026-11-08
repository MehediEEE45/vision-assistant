#include <Arduino.h>

#include "board_pins.h"
#include "haptics.h"
#include "vision_gatt.h"

namespace haptics {

namespace {

struct Step {
  uint8_t mask;
  uint16_t onMs;
  uint16_t offMs;
};

struct Pattern {
  uint8_t id;
  uint8_t count;
  bool loop;
  Step steps[4];
};

constexpr uint8_t L = VISION_MOTOR_LEFT;
constexpr uint8_t R = VISION_MOTOR_RIGHT;
constexpr uint8_t B = VISION_MOTOR_BOTH;

// Timings follow the comments in vision_gatt.h. Side is the message: a
// left-only buzz must be unmistakable from a both-sides one even through a
// shirt, hence two clearly separated pulses rather than one longer one.
const Pattern kPatterns[] = {
    {VISION_PATTERN_OBSTACLE_LEFT, 2, false, {{L, 90, 70}, {L, 90, 0}}},
    {VISION_PATTERN_OBSTACLE_RIGHT, 2, false, {{R, 90, 70}, {R, 90, 0}}},
    {VISION_PATTERN_OBSTACLE_AHEAD, 1, false, {{B, 350, 0}}},
    {VISION_PATTERN_DROP_AHEAD, 3, false, {{B, 60, 60}, {B, 60, 60}, {B, 60, 0}}},
    {VISION_PATTERN_TURN_LEFT, 3, false, {{L, 50, 50}, {L, 50, 50}, {L, 50, 0}}},
    {VISION_PATTERN_TURN_RIGHT, 3, false, {{R, 50, 50}, {R, 50, 50}, {R, 50, 0}}},
    {VISION_PATTERN_ARRIVED, 3, false, {{B, 300, 100}, {B, 100, 100}, {B, 300, 0}}},
    {VISION_PATTERN_EMERGENCY, 1, true, {{B, 500, 200}}},
};

// An ERM coin motor will not start from rest at low duty. Full drive for the
// first few milliseconds spins it up; the requested intensity then holds it.
constexpr uint32_t kKickMs = 15;

const Pattern *g_pattern = nullptr;
uint8_t g_step = 0;
bool g_on = false;
uint32_t g_phaseStartMs = 0;
uint8_t g_dutyHold = 255;
int g_lastLeft = -1;
int g_lastRight = -1;

void drive(int left, int right)
{
  if (left != g_lastLeft) {
    analogWrite(PIN_MOTOR_LEFT, left);
    g_lastLeft = left;
  }
  if (right != g_lastRight) {
    analogWrite(PIN_MOTOR_RIGHT, right);
    g_lastRight = right;
  }
}

const Pattern *find(uint8_t id)
{
  for (const Pattern &p : kPatterns) {
    if (p.id == id) return &p;
  }
  return nullptr;
}

}  // namespace

void begin()
{
  // 20 kHz is above hearing, so the motors do not whine through the casing.
  analogWriteFrequency(20000);
  analogWriteResolution(8);
  pinMode(PIN_MOTOR_LEFT, OUTPUT);
  pinMode(PIN_MOTOR_RIGHT, OUTPUT);
  drive(0, 0);
}

void play(uint8_t pattern, uint8_t intensityPercent)
{
  const Pattern *p = find(pattern);
  if (p == nullptr) return;
  if (intensityPercent > 100) intensityPercent = 100;
  g_pattern = p;
  g_step = 0;
  g_on = true;
  g_phaseStartMs = millis();
  g_dutyHold = (uint8_t)((uint16_t)intensityPercent * 255 / 100);
  update(g_phaseStartMs);
}

void stop()
{
  g_pattern = nullptr;
  drive(0, 0);
}

bool active() { return g_pattern != nullptr; }

void update(uint32_t nowMs)
{
  if (g_pattern == nullptr) return;

  for (;;) {
    const Step &st = g_pattern->steps[g_step];
    const uint32_t elapsed = nowMs - g_phaseStartMs;
    if (g_on) {
      if (elapsed < st.onMs) {
        const int duty = elapsed < kKickMs ? 255 : g_dutyHold;
        drive((st.mask & L) ? duty : 0, (st.mask & R) ? duty : 0);
        return;
      }
      g_on = false;
      g_phaseStartMs += st.onMs;
      continue;
    }
    if (elapsed < st.offMs) {
      drive(0, 0);
      return;
    }
    g_phaseStartMs += st.offMs;
    if (++g_step >= g_pattern->count) {
      if (!g_pattern->loop) {
        stop();
        return;
      }
      g_step = 0;
    }
    g_on = true;
  }
}

}  // namespace haptics
