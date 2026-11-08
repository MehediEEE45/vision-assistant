#include <Arduino.h>
#include <IWatchdog.h>

#include "announce.h"
#include "app.h"
#include "audio_i2s.h"
#include "board_pins.h"
#include "buttons.h"
#include "camera.h"
#include "config.h"
#include "console.h"
#include "display.h"
#include "finder.h"
#include "haptics.h"
#include "kws.h"
#include "obstacle_policy.h"
#include "speaker.h"
#include "tof.h"
#include "vision.h"

namespace {

obstacle::Policy g_policy;
bool g_warningsOn = true;
bool g_alarm = false;
bool g_voice = false;
// The press that stops the alarm must not also count as a click.
bool g_ignoreNextGesture = false;
uint32_t g_lastBatteryCheckMs = 0;
uint32_t g_lastBatteryNoticeMs = 0;
bool g_batteryNoticeDue = false;

// The find menu: a spoken list of the objects the model knows, stepped
// through with the same one button. Starts where the user last left it.
bool g_menuOpen = false;
uint8_t g_menuItem = 0;
uint32_t g_menuTouchedMs = 0;
// Long enough to listen to the whole list once; after that the user has
// probably walked away from it.
constexpr uint32_t kMenuIdleMs = 20000;

bool visionReady() { return camera::present() && vision::available(); }

void openMenu(uint32_t now)
{
  g_menuOpen = true;
  g_menuTouchedMs = now;
  announce::findMenu(g_menuItem, true);
}

void handleMenu(buttons::Event e, uint32_t now)
{
  g_menuTouchedMs = now;
  speaker::stopAll();
  switch (e) {
    case buttons::Event::Single:
      g_menuItem = (uint8_t)((g_menuItem + 1) % vision::OBJ_COUNT);
      announce::findMenu(g_menuItem, false);
      break;
    case buttons::Event::Double:
      g_menuOpen = false;
      finder::search(g_menuItem, now);
      break;
    case buttons::Event::Triple:
      announce::findMenu(g_menuItem, true);
      break;
    case buttons::Event::Long:
      g_menuOpen = false;
      announce::searchStopped();
      break;
    case buttons::Event::Alarm:
      g_menuOpen = false;
      app_startAlarm();
      break;
    default:
      break;
  }
}

const char *eventName(buttons::Event e)
{
  switch (e) {
    case buttons::Event::Single: return "single";
    case buttons::Event::Double: return "double";
    case buttons::Event::Triple: return "triple";
    case buttons::Event::Long: return "long";
    case buttons::Event::Alarm: return "alarm hold";
    default: return "down";
  }
}

void handleButtons(uint32_t now)
{
  const buttons::Event e = buttons::poll(now);
  if (e == buttons::Event::None) return;
  // Logged so a bring-up can tell a dead button from a gesture it did not mean.
  if (e != buttons::Event::Down) {
    Serial.print(F("button: "));
    Serial.println(eventName(e));
  }

  if (e == buttons::Event::Down) {
    if (g_alarm) {
      app_stopAlarm();
      g_ignoreNextGesture = true;
    }
    return;
  }
  if (g_ignoreNextGesture) {
    g_ignoreNextGesture = false;
    return;
  }
  if (g_menuOpen) {
    handleMenu(e, now);
    return;
  }

  // A press is the user asking for something now; whatever was playing is
  // no longer what they want to hear.
  switch (e) {
    case buttons::Event::Single:
      speaker::stopAll();
      if (finder::mode() == finder::Mode::Search) {
        finder::stop(true);
      } else if (g_voice) {
        announce::listening();
        kws::startListening(now);
      } else if (visionReady()) {
        finder::describe(now);
      } else {
        app_scan();
      }
      break;
    case buttons::Event::Double:
      speaker::stopAll();
      speaker::repeatLast();
      break;
    case buttons::Event::Triple:
      speaker::stopAll();
      if (visionReady()) {
        finder::stop(false);
        openMenu(now);
      } else {
        announce::help(g_voice);
      }
      break;
    case buttons::Event::Long:
      speaker::stopAll();
      speaker::setBangla(!speaker::bangla());
      announce::languageChanged();
      break;
    case buttons::Event::Alarm:
      app_startAlarm();
      break;
    default:
      break;
  }
}

void handleSensor(uint32_t now)
{
  tof::Sample s;
  if (tof::poll(now, s)) {
    console::onSample(s);
    obstacle::Alert a;
    if (g_warningsOn && !g_alarm && g_policy.onSample(s, a)) announce::obstacleAlert(a);
  }

  const tof::Event e = tof::takeEvent();
  if (e != tof::Event::None) {
    if (e == tof::Event::Fault || e == tof::Event::Recovered) g_policy.reset();
    announce::sensorEvent((uint8_t)e);
  }
}

void handleVoice(uint32_t now)
{
  kws::Command cmd;
  float confidence;
  const char *label;
  if (!kws::poll(now, cmd, confidence, label)) return;

  Serial.print(F("heard ")); Serial.print(label);
  Serial.print(F(" ")); Serial.print(confidence, 2);
  Serial.print(F(" -> ")); Serial.println(kws::commandName(cmd));

  switch (cmd) {
    case kws::Command::Emergency: app_startAlarm(); break;
    case kws::Command::Stop:
      speaker::stopAll();
      haptics::stop();
      finder::stop(false);
      break;
    case kws::Command::Repeat: speaker::repeatLast(); break;
    case kws::Command::WhatIsAhead:
      if (visionReady()) {
        finder::describe(now);
      } else {
        app_scan();
      }
      break;
    case kws::Command::Battery: {
      float v;
      const bool known = app_batteryVolts(v);
      announce::battery(known, known && v < BATTERY_LOW_VOLTS);
      break;
    }
    case kws::Command::Help: announce::help(true); break;
    case kws::Command::Bangla: speaker::setBangla(true); announce::languageChanged(); break;
    case kws::Command::English: speaker::setBangla(false); announce::languageChanged(); break;
    case kws::Command::Find: {
      const int object = vision::fromLabel(label);
      if (object >= 0) {
        finder::search((uint8_t)object, now);
      } else {
        announce::notUnderstood();
      }
      break;
    }
    default: announce::notUnderstood(); break;
  }
}

void handleBattery(uint32_t now)
{
#if BATTERY_SENSE_ENABLED
  if (now - g_lastBatteryCheckMs >= 10000) {
    g_lastBatteryCheckMs = now;
    float v;
    if (app_batteryVolts(v) && v < BATTERY_LOW_VOLTS &&
        (g_lastBatteryNoticeMs == 0 || now - g_lastBatteryNoticeMs >= BATTERY_REANNOUNCE_MS)) {
      g_batteryNoticeDue = true;
    }
  }
  // Ambient news is dropped while anything else plays, so wait for a gap
  // rather than lose it.
  if (g_batteryNoticeDue && !speaker::busy()) {
    g_batteryNoticeDue = false;
    g_lastBatteryNoticeMs = now;
    announce::batteryLow();
  }
#else
  (void)now;
  (void)g_lastBatteryCheckMs;
  (void)g_lastBatteryNoticeMs;
  (void)g_batteryNoticeDue;
#endif
}

void handleMenuTimeout(uint32_t now)
{
  if (g_menuOpen && now - g_menuTouchedMs >= kMenuIdleMs) {
    g_menuOpen = false;
    announce::searchStopped();
  }
}

void heartbeat(uint32_t now)
{
  // The board LED, for a sighted helper: fast flicker = alarm; quick blink =
  // no distance sensor, so warnings are not working; medium blink = looking
  // with the camera or listening; steady = speaking; a short blip every two
  // seconds = idle and healthy.
  bool on;
  if (g_alarm) {
    on = (now / 100) % 2;
  } else if (tof::chip() == tof::Chip::None) {
    on = (now / 150) % 2;
  } else if (finder::mode() != finder::Mode::Idle || kws::listening()) {
    on = (now / 300) % 2;
  } else if (speaker::busy()) {
    on = true;
  } else {
    on = now % 2000 < 60;
  }
  digitalWrite(PIN_LED, on ? HIGH : LOW);
}

}  // namespace

bool app_warningsOn() { return g_warningsOn; }

void app_setWarnings(bool on)
{
  if (on == g_warningsOn) return;
  g_warningsOn = on;
  g_policy.reset();
  announce::warningsChanged(on);
}

bool app_alarmOn() { return g_alarm; }

void app_startAlarm()
{
  if (g_alarm) return;
  g_alarm = true;
  g_menuOpen = false;
  finder::stop(false);
  announce::alarmOn();
}

void app_stopAlarm()
{
  if (!g_alarm) return;
  g_alarm = false;
  announce::alarmOff();
}

bool app_voiceAvailable() { return g_voice; }

int app_menuItem() { return g_menuOpen ? (int)g_menuItem : -1; }

void app_scan() { announce::scanReport(millis()); }

bool app_batteryVolts(float &volts)
{
#if BATTERY_SENSE_ENABLED
  uint32_t sum = 0;
  for (int i = 0; i < 8; ++i) sum += analogRead(PIN_BATTERY_SENSE);
  const float counts = (float)sum / 8.0f;
  volts = counts / 1023.0f * 3.3f * BATTERY_DIVIDER_RATIO;
  return true;
#else
  (void)volts;
  return false;
#endif
}

void setup()
{
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, HIGH);
  Serial.begin(115200);

  const bool restartedByWatchdog = IWatchdog.isReset(true);

  buttons::begin();
  haptics::begin();
  display::begin();
  speaker::begin();
  // Bangla first, but not before a single Bangla prompt exists: until then
  // every boot would open with "Bangla not recorded" in English.
  if (DEFAULT_LANGUAGE_BANGLA && !speaker::anyBangla()) speaker::setBangla(false);
  const bool audioOk = audio::begin();
  tof::begin();
  // The camera probe resets the sensor and waits half a second for it;
  // done before the watchdog starts so a slow sensor cannot trip it.
  camera::begin();
  kws::begin();
  g_voice = kws::available();

  announce::boot(restartedByWatchdog);
  console::begin(audioOk);

  // Four seconds covers the slowest thing the loop does (a sensor recovery
  // attempt or one inference) with room to spare; a hang longer than that
  // restarts the device, and the restart is announced.
  IWatchdog.begin(4000000);
}

void loop()
{
  const uint32_t now = millis();
  IWatchdog.reload();

  handleButtons(now);
  handleSensor(now);
  handleVoice(now);
  finder::poll(now);
  haptics::update(now);
  handleBattery(now);
  handleMenuTimeout(now);
  console::poll(now);
  display::update(now);
  heartbeat(now);
}
