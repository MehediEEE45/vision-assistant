#include <Arduino.h>
#include <IWatchdog.h>
#include <Wire.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "app.h"
#include "audio_i2s.h"
#include "camera.h"
#include "clock_config.h"
#include "config.h"
#include "console.h"
#include "display.h"
#include "finder.h"
#include "kws.h"
#include "prompt_data.h"
#include "speaker.h"
#include "tof.h"
#include "vision.h"

namespace console {

namespace {

char g_line[64];
uint8_t g_len = 0;
bool g_zones = false;
bool g_streaming = false;
uint32_t g_micUntilMs = 0;
uint32_t g_micNextMs = 0;

// Frame header for the binary audio stream; tools/record_dataset.py resyncs
// on it if a byte is ever lost.
constexpr uint8_t kSync0 = 0xA5;
constexpr uint8_t kSync1 = 0x5A;
constexpr uint16_t kBlockSamples = 256;

// After a snapshot the sensor stays awake this long, so tools/capture_images.py
// can take a series without paying the exposure warm-up each time.
constexpr uint32_t kSnapAwakeMs = 10000;
uint32_t g_snapAwakeUntilMs = 0;

const char *zoneName(uint8_t z)
{
  switch (z) {
    case tof::ZONE_LEFT: return "left";
    case tof::ZONE_RIGHT: return "right";
    default: return "ahead";
  }
}

float dbfs(int32_t peak)
{
  if (peak <= 0) return -96.0f;
  return 20.0f * log10f((float)peak / 32768.0f);
}

void printHelp()
{
  Serial.println(F("commands:"));
  Serial.println(F("  status            chip, clock, sensor, light mode, errors"));
  Serial.println(F("  zones on|off      print every distance reading"));
  Serial.println(F("  mirror            swap the left and right zones"));
  Serial.println(F("  scan              same as one button press"));
  Serial.println(F("  prompts           list prompts; * = recorded in Bangla"));
  Serial.println(F("  say <n|NAME>      play one prompt"));
  Serial.println(F("  tone              play a test tone"));
  Serial.println(F("  lang bn|en        switch language"));
  Serial.println(F("  vol <0-100>       speaker volume"));
  Serial.println(F("  mic               microphone level for 5 s"));
  Serial.println(F("  rec / stop        binary audio stream for tools/record_dataset.py"));
  Serial.println(F("  warnings on|off   obstacle warnings"));
  Serial.println(F("  alarm / quiet     start or stop the emergency alarm"));
  Serial.println(F("  cam               camera status"));
  Serial.println(F("  snap              one 320x240 picture, binary, for tools/capture_images.py"));
  Serial.println(F("  describe          what the camera recognises (needs a model)"));
  Serial.println(F("  find <object>     search for person/chair/door/table/bottle/toilet/rickshaw/cng"));
  Serial.println(F("  i2c               list devices answering on the sensor and camera I2C buses"));
  Serial.println(F("  lcd               colour bars on the screen for 8 s"));
  Serial.println(F("  view on|off       live camera picture on the screen"));
  Serial.println(F("  dfu               restart into the USB boot loader (PlatformIO Upload does this itself)"));
  Serial.println(F("  reset             restart the board"));
}

void scanSensorBus()
{
  Serial.print(F("sensor bus (PB10/PB11):"));
  int found = 0;
  for (uint8_t a = 1; a < 127; ++a) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.print(F(" 0x"));
      Serial.print(a, HEX);
      ++found;
    }
  }
  // 0x29 is the ToF sensor's address; anything else is a surprise worth seeing.
  Serial.println(found ? F("") : F(" nothing (a VL53L1X/VL53L0X answers at 0x29)"));
}

void printCamera()
{
  Serial.print(F("camera     "));
  if (!camera::present() && camera::answered()) {
    Serial.print(F("a sensor answered with id 0x")); Serial.print(camera::chipId(), HEX);
    Serial.println(F(", not a recognised OV5640/OV7725"));
  } else if (!camera::present()) {
    Serial.print(F("not present: ")); Serial.println(camera::lastError());
    Serial.println(F("  (check the ribbon is seated, then `reset`; `scan` lists what replies)"));
  } else {
    Serial.print(camera::chipName()); Serial.print(F(" id 0x")); Serial.print(camera::chipId(), HEX);
    Serial.print(camera::pwdnHighMeansOn() ? F(", PA7 high = on") : F(", PA7 low = on"));
    Serial.print(camera::vsyncPolarityLow() ? F(", vsync low") : F(", vsync high"));
    Serial.print(camera::awake() ? F(", awake") : F(", standby"));
    Serial.print(F(", errors ")); Serial.print(camera::errorCount());
    if (camera::errorCount() > 0) { Serial.print(F(" (")); Serial.print(camera::lastError()); Serial.print(')'); }
    Serial.println();
  }
  Serial.print(F("vision     ")); Serial.print(vision::modelInfo());
  Serial.print(F(", hfov ")); Serial.print(CAMERA_HFOV_DEG, 0); Serial.println(F(" deg"));
}

bool sendAll(const uint8_t *p, size_t len)
{
  size_t sent = 0;
  uint32_t lastProgressMs = millis();
  while (sent < len) {
    IWatchdog.reload();
    const int room = Serial.availableForWrite();
    if (room > 0) {
      size_t n = len - sent;
      if (n > (size_t)room) n = (size_t)room;
      n = Serial.write(p + sent, n);
      if (n > 0) {
        sent += n;
        lastProgressMs = millis();
      }
    }
    // The host stopped reading. Give up rather than let the watchdog
    // restart the device mid-walk.
    if (millis() - lastProgressMs > 1500) return false;
  }
  return true;
}

void snap()
{
  if (!camera::present()) {
    Serial.println(F("no camera"));
    return;
  }
  if (finder::mode() != finder::Mode::Idle) {
    Serial.println(F("camera busy"));
    return;
  }
  camera::wake(millis());
  g_snapAwakeUntilMs = millis() + kSnapAwakeMs;
  while (!camera::warmedUp(millis())) {
    IWatchdog.reload();
    delay(5);
  }
  if (!camera::capture(millis())) {
    Serial.println(F("capture failed"));
    return;
  }
  while (!camera::poll(millis())) {
    IWatchdog.reload();
    if (!camera::capturing()) {
      Serial.println(F("capture timed out"));
      return;
    }
  }
  const uint32_t len = (uint32_t)CAMERA_WIDTH * CAMERA_HEIGHT * 2;
  // Format 1: RGB565, little-endian, row-major.
  const uint8_t header[14] = {'I', 'M', 'G', '1',
                              (uint8_t)(CAMERA_WIDTH & 0xFF), (uint8_t)(CAMERA_WIDTH >> 8),
                              (uint8_t)(CAMERA_HEIGHT & 0xFF), (uint8_t)(CAMERA_HEIGHT >> 8),
                              1, 0,
                              (uint8_t)(len & 0xFF), (uint8_t)((len >> 8) & 0xFF),
                              (uint8_t)((len >> 16) & 0xFF), (uint8_t)(len >> 24)};
  if (!sendAll(header, sizeof(header)) || !sendAll((const uint8_t *)camera::frame(), len)) {
    Serial.println(F("\nsend aborted"));
  }
  g_snapAwakeUntilMs = millis() + kSnapAwakeMs;
}

void printStatus()
{
  Serial.print(F("firmware   ")); Serial.println(F(FW_VERSION));
  Serial.print(F("silicon    rev ")); Serial.print(chipRevisionName());
  Serial.print(F(", core ")); Serial.print(SystemCoreClock / 1000000UL); Serial.println(F(" MHz"));
  Serial.print(F("audio      ")); Serial.print(audio::running() ? F("running") : F("FAILED"));
  Serial.print(F(", i2s errors ")); Serial.print(audio::errorCount());
  Serial.print(F(", mic dropped ")); Serial.println(audio::micDropped());
  Serial.print(F("sensor     ")); Serial.print(tof::chipName());
  if (tof::chip() == tof::Chip::VL53L1X) {
    Serial.print(tof::longMode() ? F(", long mode") : F(", short mode"));
    Serial.print(F(", ambient ")); Serial.print(tof::ambientMcps(), 2); Serial.print(F(" Mcps"));
    Serial.print(tof::mirrored() ? F(", mirrored") : F(""));
  }
  Serial.print(F(", errors ")); Serial.print(tof::errorCount());
  Serial.print(F(", spoken range ")); Serial.print(tof::spokenRangeMm()); Serial.println(F(" mm"));
  const uint32_t now = millis();
  for (uint8_t z = 0; z < tof::ZONE_COUNT; ++z) {
    uint16_t mm; bool valid; uint32_t age;
    if (tof::latest((tof::Zone)z, mm, valid, age, now)) {
      Serial.print(F("  ")); Serial.print(zoneName(z)); Serial.print(F(": "));
      if (valid) { Serial.print(mm); Serial.print(F(" mm")); } else { Serial.print(F("no target")); }
      Serial.print(F(" (")); Serial.print(age); Serial.println(F(" ms ago)"));
    }
  }
  Serial.print(F("language   ")); Serial.print(speaker::bangla() ? F("Bangla") : F("English"));
  Serial.print(F(", Bangla prompts missing ")); Serial.print(speaker::missingBanglaCount());
  Serial.print(F("/")); Serial.println(PROMPT_COUNT);
  Serial.print(F("volume     ")); Serial.print(speaker::volumePercent()); Serial.println(F("%"));
  Serial.print(F("warnings   ")); Serial.println(app_warningsOn() ? F("on") : F("off"));
  Serial.print(F("voice      ")); Serial.println(kws::modelInfo());
  float v;
  Serial.print(F("battery    "));
  if (app_batteryVolts(v)) { Serial.print(v, 2); Serial.println(F(" V")); } else { Serial.println(F("not wired")); }
  Serial.print(F("display    "));
#if LCD_ENABLED
  Serial.println(display::ok() ? F("ok") : F("FAILED (SPI4 init)"));
#else
  Serial.println(F("off (LCD_ENABLED 0)"));
#endif
  printCamera();
}

void listPrompts()
{
  for (uint16_t i = 0; i < PROMPT_COUNT; ++i) {
    Serial.print(i); Serial.print(speaker::hasBangla((PromptId)i) ? F(" * ") : F("   "));
    Serial.println(kPromptNames[i]);
  }
}

void sayPrompt(const char *arg)
{
  int id = -1;
  if (*arg >= '0' && *arg <= '9') {
    id = atoi(arg);
  } else {
    for (uint16_t i = 0; i < PROMPT_COUNT; ++i) {
      if (strcasecmp(arg, kPromptNames[i]) == 0) id = i;
    }
  }
  if (id < 0 || id >= PROMPT_COUNT) {
    Serial.println(F("no such prompt; try `prompts`"));
    return;
  }
  speaker::Utterance u(speaker::Priority::Answer);
  u.prompt((PromptId)id);
  speaker::say(u);
}

void startStreaming()
{
  speaker::stopAll();
  audio::setOutputMuted(true);
  audio::setMicCapture(true);
  g_streaming = true;
  Serial.print(F("REC "));
  Serial.println(AUDIO_SAMPLE_RATE);
}

void stopStreaming()
{
  g_streaming = false;
  audio::setMicCapture(false);
  audio::setOutputMuted(false);
  Serial.println();
  Serial.println(F("STOPPED"));
}

void pumpStream()
{
  static int16_t block[kBlockSamples];
  // Bounded per loop pass so buttons, sensor and haptics keep running.
  for (int n = 0; n < 4; ++n) {
    if (audio::micAvailable() < kBlockSamples) return;
    if (Serial.availableForWrite() < (int)(4 + sizeof(block))) return;
    audio::micRead(block, kBlockSamples);
    const uint8_t header[4] = {kSync0, kSync1, (uint8_t)(kBlockSamples & 0xFF), (uint8_t)(kBlockSamples >> 8)};
    Serial.write(header, sizeof(header));
    Serial.write((const uint8_t *)block, sizeof(block));
  }
}

void handle(char *line)
{
  char *arg = strchr(line, ' ');
  if (arg != nullptr) {
    *arg++ = '\0';
    while (*arg == ' ') ++arg;
  } else {
    arg = line + strlen(line);
  }

  if (strcmp(line, "stop") == 0) {
    if (g_streaming) stopStreaming();
    return;
  }
  if (g_streaming) return;

  if (strcmp(line, "help") == 0 || strcmp(line, "?") == 0) printHelp();
  else if (strcmp(line, "status") == 0) printStatus();
  else if (strcmp(line, "zones") == 0) { g_zones = strcmp(arg, "off") != 0; }
  else if (strcmp(line, "mirror") == 0) {
    tof::setMirrored(!tof::mirrored());
    Serial.println(tof::mirrored() ? F("zones mirrored") : F("zones normal"));
  }
  else if (strcmp(line, "scan") == 0) app_scan();
  else if (strcmp(line, "prompts") == 0) listPrompts();
  else if (strcmp(line, "say") == 0) sayPrompt(arg);
  else if (strcmp(line, "tone") == 0) {
    speaker::Utterance u(speaker::Priority::Answer);
    u.tone(speaker::TONE_OK);
    speaker::say(u);
  }
  else if (strcmp(line, "lang") == 0) {
    speaker::setBangla(strcmp(arg, "en") != 0);
    Serial.println(speaker::bangla() ? F("Bangla") : F("English"));
  }
  else if (strcmp(line, "vol") == 0) {
    speaker::setVolumePercent((uint8_t)constrain(atoi(arg), 0, 100));
    Serial.print(speaker::volumePercent()); Serial.println(F("%"));
  }
  else if (strcmp(line, "mic") == 0) {
    audio::micTakePeak();
    g_micUntilMs = millis() + 5000;
    g_micNextMs = millis() + 250;
  }
  else if (strcmp(line, "rec") == 0) startStreaming();
  else if (strcmp(line, "warnings") == 0) {
    app_setWarnings(strcmp(arg, "off") != 0);
    Serial.println(app_warningsOn() ? F("warnings on") : F("warnings off"));
  }
  else if (strcmp(line, "alarm") == 0) app_startAlarm();
  else if (strcmp(line, "quiet") == 0) app_stopAlarm();
  else if (strcmp(line, "cam") == 0) printCamera();
  else if (strcmp(line, "snap") == 0) snap();
  else if (strcmp(line, "describe") == 0) finder::describe(millis());
  else if (strcmp(line, "find") == 0) {
    const int object = vision::fromLabel(arg);
    if (object < 0) {
      Serial.println(F("objects: person chair door table bottle toilet rickshaw cng"));
    } else {
      finder::search((uint8_t)object, millis());
    }
  }
  else if (strcmp(line, "i2c") == 0) {
    scanSensorBus();
    camera::scanBus(Serial);
  }
  else if (strcmp(line, "view") == 0) {
    display::setView(strcmp(arg, "off") != 0);
    Serial.println(display::viewOn() ? F("lcd: camera view on") : F("lcd: captions only"));
  }
  else if (strcmp(line, "lcd") == 0) {
    if (display::ok()) {
      display::testPattern(millis());
      Serial.println(F("lcd: bars top to bottom RED GREEN BLUE WHITE, yellow border, TOP at top right"));
    } else {
      Serial.println(F("lcd: not running"));
    }
  }
  else if (strcmp(line, "dfu") == 0) {
    Serial.println(F("DFU"));
    Serial.flush();
    delay(100);
    requestBootloader();
  }
  else if (strcmp(line, "reset") == 0) { Serial.flush(); delay(50); NVIC_SystemReset(); }
  else if (*line != '\0') { Serial.print(F("unknown: ")); Serial.println(line); }
}

}  // namespace

void begin(bool audioOk)
{
  Serial.println();
  Serial.print(F("Vision Assistant wearable ")); Serial.println(F(FW_VERSION));
  Serial.print(F("silicon rev ")); Serial.print(chipRevisionName());
  Serial.print(F(", sensor ")); Serial.print(tof::chipName());
  Serial.print(F(", audio ")); Serial.println(audioOk ? F("ok") : F("FAILED"));
  if (speaker::missingBanglaCount() > 0) {
    Serial.print(F("Bangla prompts not recorded: "));
    Serial.print(speaker::missingBanglaCount());
    Serial.println(F(" (English is used for those). See tools/README in the firmware folder."));
  }
  Serial.println(F("type `help`"));
}

void onSample(const tof::Sample &s)
{
  if (!g_zones || g_streaming) return;
  Serial.print(zoneName(s.zone)); Serial.print(' ');
  if (s.valid) Serial.print(s.mm); else Serial.print(F("--"));
  Serial.print(F(" amb ")); Serial.println(tof::ambientMcps(), 2);
}

bool streaming() { return g_streaming; }

void poll(uint32_t nowMs)
{
  while (Serial.available() > 0) {
    const char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      g_line[g_len] = '\0';
      handle(g_line);
      g_len = 0;
    } else if (g_len < sizeof(g_line) - 1) {
      g_line[g_len++] = c;
    }
  }

  if (g_streaming) pumpStream();

  if (g_snapAwakeUntilMs != 0 && (int32_t)(nowMs - g_snapAwakeUntilMs) >= 0) {
    g_snapAwakeUntilMs = 0;
    if (finder::mode() == finder::Mode::Idle) camera::sleep();
  }

  if (g_micUntilMs != 0 && (int32_t)(nowMs - g_micNextMs) >= 0) {
    const int32_t peak = audio::micTakePeak();
    Serial.print(F("mic peak ")); Serial.print(dbfs(peak), 1); Serial.println(F(" dBFS"));
    g_micNextMs = nowMs + 250;
    if ((int32_t)(nowMs - g_micUntilMs) >= 0) g_micUntilMs = 0;
  }
}

}  // namespace console
