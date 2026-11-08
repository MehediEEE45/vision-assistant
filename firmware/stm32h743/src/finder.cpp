#include <Arduino.h>
#include <math.h>

#include "announce.h"
#include "camera.h"
#include "config.h"
#include "finder.h"
#include "haptics.h"
#include "tof.h"
#include "vision.h"
#include "vision_gatt.h"

namespace finder {

namespace {

constexpr int kNoSide = 2;
// One picture should take well under a second including warm-up.
constexpr uint32_t kDescribeTimeoutMs = 3000;
constexpr uint8_t kFailuresToFault = 3;
// A detection flickering between left and right on consecutive frames must
// not become a stream of words; a real change of side can wait this long.
constexpr uint32_t kSideChangeSpeechMs = 1200;

Mode g_mode = Mode::Idle;
uint8_t g_target = 0;
uint32_t g_startMs = 0;
uint32_t g_lastSeenMs = 0;
uint32_t g_lastHapticMs = 0;
uint32_t g_lastSpeechMs = 0;
int g_lastSide = kNoSide;
uint8_t g_failures = 0;
vision::Detection g_dets[vision::kMaxDetections];

bool aheadDistance(float angleDeg, uint32_t nowMs, uint16_t &mm)
{
  if (fabsf(angleDeg) > TOF_AHEAD_HALF_ANGLE_DEG) return false;
  bool valid = false;
  uint32_t age = 0;
  if (!tof::latest(tof::ZONE_AHEAD, mm, valid, age, nowMs)) return false;
  return valid && age < 500;
}

void finish()
{
  camera::sleep();
  g_mode = Mode::Idle;
}

bool ready()
{
  if (!camera::present()) {
    announce::cameraFault();
    return false;
  }
  if (!vision::available()) {
    announce::visionNotInstalled();
    return false;
  }
  return true;
}

// Raw FOMO output on the serial console, for bring-up: Serial.println(n < 0
// ? "no model" : "..."). The spoken announcement only ever names the
// strongest match per object, so this is the one place the actual
// score/position the model produced is visible at all.
void logDetections(int n)
{
  if (n < 0) {
    Serial.println(F("vision: no model (VISION_EI_HEADER not built in)"));
    return;
  }
  if (n == 0) {
    Serial.println(F("vision: nothing above VISION_MIN_CONFIDENCE"));
    return;
  }
  for (int i = 0; i < n; ++i) {
    Serial.print(F("vision: "));
    Serial.print(vision::label(g_dets[i].object));
    Serial.print(F(" score=")); Serial.print(g_dets[i].score, 2);
    Serial.print(F(" cx=")); Serial.print(g_dets[i].cx, 2);
    Serial.print(F(" cy=")); Serial.print(g_dets[i].cy, 2);
    Serial.print(F(" angle=")); Serial.println(vision::angleDeg(g_dets[i].cx), 1);
  }
}

void onDescribeFrame(uint32_t nowMs)
{
  const int n = vision::detect(camera::frame(), g_dets, vision::kMaxDetections);
  logDetections(n);
  finish();
  announce::describe(g_dets, n < 0 ? 0 : n, nowMs);
}

void onSearchFrame(uint32_t nowMs)
{
  const int n = vision::detect(camera::frame(), g_dets, vision::kMaxDetections);
  logDetections(n);
  const vision::Detection *best = nullptr;
  for (int i = 0; i < n; ++i) {
    if (g_dets[i].object == g_target) {
      best = &g_dets[i];  // strongest first
      break;
    }
  }

  if (best == nullptr) {
    if (nowMs - g_lastSeenMs >= FIND_TIMEOUT_MS) {
      finish();
      announce::searchNotFound(g_target);
    }
    return;
  }

  g_lastSeenMs = nowMs;
  const float angle = vision::angleDeg(best->cx);
  const int side = fabsf(angle) <= FIND_AHEAD_DEG ? 0 : (angle < 0.0f ? -1 : 1);

  if (side == 0) {
    if (g_lastSide != 0) haptics::play(VISION_PATTERN_ARRIVED, 70);
  } else if (nowMs - g_lastHapticMs >= FIND_HAPTIC_MS) {
    haptics::play(side < 0 ? VISION_PATTERN_TURN_LEFT : VISION_PATTERN_TURN_RIGHT, 70);
    g_lastHapticMs = nowMs;
  }

  const bool sideChanged = side != g_lastSide && nowMs - g_lastSpeechMs >= kSideChangeSpeechMs;
  if (sideChanged || nowMs - g_lastSpeechMs >= FIND_SPEECH_MS) {
    uint16_t mm = 0;
    const bool haveDistance = side == 0 && aheadDistance(angle, nowMs, mm);
    announce::searchGuidance(g_target, side, haveDistance, mm);
    g_lastSpeechMs = nowMs;
  }
  g_lastSide = side;
}

}  // namespace

Mode mode() { return g_mode; }
uint8_t target() { return g_target; }

bool describe(uint32_t nowMs)
{
  if (!ready()) return false;
  stop(false);
  camera::wake(nowMs);
  g_mode = Mode::Describe;
  g_startMs = nowMs;
  g_failures = 0;
  return true;
}

bool search(uint8_t object, uint32_t nowMs)
{
  if (object >= vision::OBJ_COUNT || !ready()) return false;
  stop(false);
  camera::wake(nowMs);
  g_mode = Mode::Search;
  g_target = object;
  g_startMs = nowMs;
  g_lastSeenMs = nowMs;
  g_lastHapticMs = 0;
  g_lastSpeechMs = nowMs;
  g_lastSide = kNoSide;
  g_failures = 0;
  announce::searchStarted(object);
  return true;
}

void stop(bool announceIt)
{
  if (g_mode == Mode::Idle) return;
  const bool wasSearch = g_mode == Mode::Search;
  finish();
  if (announceIt && wasSearch) announce::searchStopped();
}

void poll(uint32_t nowMs)
{
  if (g_mode == Mode::Idle) return;

  const uint32_t errorsBefore = camera::errorCount();
  if (camera::poll(nowMs)) {
    g_failures = 0;
    if (g_mode == Mode::Describe) {
      onDescribeFrame(nowMs);
    } else {
      onSearchFrame(nowMs);
    }
    return;
  }
  if (camera::errorCount() != errorsBefore && ++g_failures >= kFailuresToFault) {
    finish();
    announce::cameraFault();
    return;
  }
  if (g_mode == Mode::Describe && nowMs - g_startMs > kDescribeTimeoutMs) {
    finish();
    announce::cameraFault();
    return;
  }
  if (!camera::capturing()) camera::capture(nowMs);
}

}  // namespace finder
