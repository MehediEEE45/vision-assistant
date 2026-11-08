#include <Arduino.h>
#include <math.h>

#include "announce.h"
#include "config.h"
#include "haptics.h"
#include "speaker.h"
#include "tof.h"
#include "vision_gatt.h"

namespace announce {

namespace {

using speaker::Priority;
using speaker::Utterance;

constexpr uint16_t kTagObstacle = 1;
constexpr uint16_t kTagReport = 2;
constexpr uint16_t kTagAlarm = 3;
constexpr uint16_t kTagSensor = 4;
constexpr uint16_t kTagSearch = 5;
constexpr uint16_t kTagMenu = 6;

// Anything closer than this is "very close" rather than a number: at 0.9 m/s
// it is under half a second away, and a number takes longer to say.
constexpr uint16_t kVeryCloseMm = 400;

// Half-metre steps: finer than anyone can act on while walking, and Bangla
// has native words for the halves (দেড়, আড়াই, সাড়ে).
PromptId distancePrompt(uint16_t mm)
{
  static const PromptId kSteps[] = {PROMPT_DIST_0_5, PROMPT_DIST_1_0, PROMPT_DIST_1_5,
                                    PROMPT_DIST_2_0, PROMPT_DIST_2_5, PROMPT_DIST_3_0,
                                    PROMPT_DIST_3_5, PROMPT_DIST_4_0};
  if (mm < 750) return PROMPT_DIST_0_5;
  uint32_t i = ((uint32_t)mm - 250) / 500;
  if (i > 7) i = 7;
  return kSteps[i];
}

PromptId obstaclePrompt(tof::Zone z)
{
  switch (z) {
    case tof::ZONE_LEFT: return PROMPT_OBST_LEFT;
    case tof::ZONE_RIGHT: return PROMPT_OBST_RIGHT;
    default: return PROMPT_OBST_AHEAD;
  }
}

PromptId zoneWord(tof::Zone z)
{
  switch (z) {
    case tof::ZONE_LEFT: return PROMPT_ZONE_LEFT;
    case tof::ZONE_RIGHT: return PROMPT_ZONE_RIGHT;
    default: return PROMPT_ZONE_AHEAD;
  }
}

uint8_t hapticFor(tof::Zone z)
{
  switch (z) {
    case tof::ZONE_LEFT: return VISION_PATTERN_OBSTACLE_LEFT;
    case tof::ZONE_RIGHT: return VISION_PATTERN_OBSTACLE_RIGHT;
    default: return VISION_PATTERN_OBSTACLE_AHEAD;
  }
}

void appendBanglaNotice(Utterance &u)
{
  if (speaker::bangla() && speaker::missingBanglaCount() > 0) u.prompt(PROMPT_BANGLA_MISSING);
}

// Word order follows the clip that will actually play: with Bangla selected
// but a prompt not yet recorded, the English clip needs English order.
bool banglaClip(PromptId id) { return speaker::bangla() && speaker::hasBangla(id); }

bool aheadReading(uint32_t nowMs, uint32_t maxAgeMs, uint16_t &mm)
{
  bool valid = false;
  uint32_t age = 0;
  return tof::latest(tof::ZONE_AHEAD, mm, valid, age, nowMs) && valid && age <= maxAgeMs;
}

PromptId sideWord(int side)
{
  return side == 0 ? PROMPT_ZONE_AHEAD : side < 0 ? PROMPT_ZONE_LEFT : PROMPT_ZONE_RIGHT;
}

}  // namespace

void obstacleAlert(const obstacle::Alert &a)
{
  const uint8_t intensity = a.band == obstacle::Band::Immediate ? 100
                            : a.band == obstacle::Band::Near    ? 80
                                                                : 60;
  haptics::play(hapticFor(a.zone), intensity);

  if (a.band == obstacle::Band::Approaching && !OBST_SPEAK_APPROACHING) return;

  const Priority p = a.band == obstacle::Band::Approaching ? Priority::Maneuver : Priority::Hazard;
  Utterance u(p, kTagObstacle);
  if (a.band == obstacle::Band::Immediate) {
    u.tone(speaker::TONE_WARN).prompt(obstaclePrompt(a.zone));
  } else {
    u.prompt(obstaclePrompt(a.zone)).prompt(distancePrompt(a.mm));
  }
  speaker::say(u);
}

void scanReport(uint32_t nowMs)
{
  Utterance u(Priority::Answer, kTagReport);
  if (tof::chip() == tof::Chip::None) {
    u.tone(speaker::TONE_ERROR).prompt(PROMPT_SENSOR_FAULT);
    speaker::say(u);
    return;
  }

  static const tof::Zone kAll[] = {tof::ZONE_LEFT, tof::ZONE_AHEAD, tof::ZONE_RIGHT};
  static const tof::Zone kAheadOnly[] = {tof::ZONE_AHEAD};
  const bool zones = tof::zonesAvailable();
  const tof::Zone *list = zones ? kAll : kAheadOnly;
  const uint8_t n = zones ? 3 : 1;

  for (uint8_t i = 0; i < n; ++i) {
    uint16_t mm = 0;
    bool valid = false;
    uint32_t age = 0;
    if (zones) u.prompt(zoneWord(list[i]));
    // Older than a second is not "what is there now".
    if (!tof::latest(list[i], mm, valid, age, nowMs) || age > 1000 || !valid) {
      u.prompt(PROMPT_NOTHING_FOUND);
    } else if (mm < kVeryCloseMm) {
      u.prompt(PROMPT_VERY_CLOSE);
    } else {
      u.prompt(distancePrompt(mm));
    }
  }
  // The limit is part of the observation: "nothing detected" means nothing
  // within this distance, inside the sensor's cone, and no more than that.
  u.prompt(PROMPT_RANGE_ABOUT).prompt(distancePrompt(tof::spokenRangeMm()));
  speaker::say(u);
}

void boot(bool restartedByWatchdog)
{
  Utterance u(Priority::Answer);
  u.tone(speaker::TONE_BOOT).prompt(restartedByWatchdog ? PROMPT_RESTARTED : PROMPT_BOOT);
  if (tof::chip() == tof::Chip::None) u.prompt(PROMPT_NO_SENSOR);
  appendBanglaNotice(u);
  speaker::say(u);
}

void sensorEvent(uint8_t e)
{
  switch ((tof::Event)e) {
    case tof::Event::Fault: {
      // Hazard priority: the user must know warnings have stopped, now.
      Utterance u(Priority::Hazard, kTagSensor);
      u.tone(speaker::TONE_ERROR).prompt(PROMPT_SENSOR_FAULT);
      speaker::say(u);
      break;
    }
    case tof::Event::Recovered: {
      Utterance u(Priority::Answer, kTagSensor);
      u.tone(speaker::TONE_OK).prompt(PROMPT_SENSOR_BACK);
      speaker::say(u);
      break;
    }
    case tof::Event::BrightLight: {
      Utterance u(Priority::Answer, kTagSensor);
      u.prompt(PROMPT_BRIGHT_LIGHT).prompt(PROMPT_RANGE_ABOUT).prompt(distancePrompt(tof::spokenRangeMm()));
      speaker::say(u);
      break;
    }
    case tof::Event::NormalLight: {
      Utterance u(Priority::Answer, kTagSensor);
      u.prompt(PROMPT_NORMAL_LIGHT).prompt(PROMPT_RANGE_ABOUT).prompt(distancePrompt(tof::spokenRangeMm()));
      speaker::say(u);
      break;
    }
    default:
      break;
  }
}

void languageChanged()
{
  Utterance u(Priority::Answer);
  u.prompt(speaker::bangla() ? PROMPT_LANG_BANGLA : PROMPT_LANG_ENGLISH);
  appendBanglaNotice(u);
  speaker::say(u);
}

void warningsChanged(bool on)
{
  Utterance u(Priority::Answer);
  u.prompt(on ? PROMPT_WARNINGS_ON : PROMPT_WARNINGS_OFF);
  speaker::say(u);
}

void help(bool voiceAvailable)
{
  Utterance u(Priority::Answer);
  u.prompt(voiceAvailable ? PROMPT_HELP_VOICE : PROMPT_HELP);
  speaker::say(u);
}

void alarmOn()
{
  haptics::play(VISION_PATTERN_EMERGENCY, 100);
  Utterance u(Priority::Hazard, kTagAlarm);
  u.prompt(PROMPT_ALARM_ON).tone(speaker::TONE_ALARM);
  speaker::say(u);
}

void alarmOff()
{
  haptics::stop();
  speaker::stopAll();
  Utterance u(Priority::Answer);
  u.prompt(PROMPT_ALARM_OFF);
  speaker::say(u);
}

void batteryLow()
{
  Utterance u(Priority::Ambient);
  u.prompt(PROMPT_BATTERY_LOW);
  speaker::say(u);
}

void battery(bool known, bool low)
{
  Utterance u(Priority::Answer);
  u.prompt(!known ? PROMPT_BATTERY_UNKNOWN : low ? PROMPT_BATTERY_LOW : PROMPT_BATTERY_GOOD);
  speaker::say(u);
}

void notUnderstood()
{
  Utterance u(Priority::Answer);
  u.tone(speaker::TONE_ERROR).prompt(PROMPT_NOT_UNDERSTOOD);
  speaker::say(u);
}

void listening()
{
  Utterance u(Priority::Answer);
  u.tone(speaker::TONE_LISTEN);
  speaker::say(u);
}

void describe(const vision::Detection *d, int n, uint32_t nowMs)
{
  Utterance u(Priority::Answer, kTagReport);
  bool distanceGiven = false;
  bool mentioned[vision::OBJ_COUNT] = {};
  int spoken = 0;
  // Three objects at most: a list longer than that is forgotten before it
  // ends. Strongest first, one mention per kind of object.
  for (int i = 0; i < n && spoken < 3; ++i) {
    if (mentioned[d[i].object]) continue;
    mentioned[d[i].object] = true;
    ++spoken;
    const float angle = vision::angleDeg(d[i].cx);
    u.prompt(vision::prompt(d[i].object));
    if (fabsf(angle) > FIND_AHEAD_DEG) {
      u.prompt(angle < 0.0f ? PROMPT_ZONE_LEFT : PROMPT_ZONE_RIGHT);
      continue;
    }
    u.prompt(PROMPT_ZONE_AHEAD);
    uint16_t mm = 0;
    if (fabsf(angle) <= TOF_AHEAD_HALF_ANGLE_DEG && aheadReading(nowMs, 500, mm)) {
      u.prompt(mm < kVeryCloseMm ? PROMPT_VERY_CLOSE : distancePrompt(mm));
      distanceGiven = true;
    }
  }
  if (spoken == 0) u.prompt(PROMPT_NOTHING_RECOGNISED);

  // The model knows a handful of objects; the laser sees anything. Always
  // say what is straight ahead, so an unrecognised obstacle is never silent.
  if (!distanceGiven && tof::chip() != tof::Chip::None) {
    uint16_t mm = 0;
    u.prompt(PROMPT_ZONE_AHEAD);
    if (aheadReading(nowMs, 1000, mm)) {
      u.prompt(mm < kVeryCloseMm ? PROMPT_VERY_CLOSE : distancePrompt(mm));
    } else {
      u.prompt(PROMPT_NOTHING_FOUND);
    }
  }
  speaker::say(u);
}

void searchStarted(uint8_t object)
{
  Utterance u(Priority::Answer, kTagSearch);
  if (banglaClip(PROMPT_SEARCHING_FOR)) {
    u.prompt(vision::prompt(object)).prompt(PROMPT_SEARCHING_FOR);
  } else {
    u.prompt(PROMPT_SEARCHING_FOR).prompt(vision::prompt(object));
  }
  u.prompt(PROMPT_TURN_SLOWLY);
  speaker::say(u);
}

void searchGuidance(uint8_t object, int side, bool haveDistance, uint16_t mm)
{
  Utterance u(Priority::Answer, kTagSearch);
  u.prompt(vision::prompt(object)).prompt(sideWord(side));
  if (side == 0 && haveDistance) u.prompt(mm < kVeryCloseMm ? PROMPT_VERY_CLOSE : distancePrompt(mm));
  speaker::say(u);
}

void searchNotFound(uint8_t object)
{
  // "Not found", never "not here": the camera saw only what it was pointed at.
  Utterance u(Priority::Answer, kTagSearch);
  u.prompt(vision::prompt(object)).prompt(PROMPT_NOT_FOUND);
  speaker::say(u);
}

void searchStopped()
{
  Utterance u(Priority::Answer, kTagSearch);
  u.prompt(PROMPT_SEARCH_STOPPED);
  speaker::say(u);
}

void findMenu(uint8_t object, bool first)
{
  Utterance u(Priority::Answer, kTagMenu);
  if (first) u.prompt(PROMPT_FIND_MENU);
  u.prompt(vision::prompt(object));
  speaker::say(u);
}

void cameraFault()
{
  Utterance u(Priority::Answer, kTagSensor);
  u.tone(speaker::TONE_ERROR).prompt(PROMPT_CAMERA_FAULT);
  speaker::say(u);
}

void visionNotInstalled()
{
  Utterance u(Priority::Answer);
  u.prompt(PROMPT_VISION_NOT_INSTALLED);
  speaker::say(u);
}

}  // namespace announce
