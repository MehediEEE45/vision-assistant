#include <Arduino.h>
#include <VL53L0X.h>
#include <VL53L1X.h>
#include <Wire.h>

#include "board_pins.h"
#include "config.h"
#include "tof.h"

namespace tof {

namespace {

constexpr uint8_t kAddress = 0x29;

// UM2555 (VL53L1X ULD multiple-zone note) centres an 8x16 region on SPAD 167
// for one half of the array and 231 for the other; 199 is the optical centre.
// Overlapping thirds of a 27-degree field are coarse, but enough to say which
// side an obstacle is on at walking distances.
constexpr uint8_t kRoiWidth = 8;
constexpr uint8_t kRoiHeight = 16;
constexpr uint8_t kSpadLeft = 167;
constexpr uint8_t kSpadAhead = 199;
constexpr uint8_t kSpadRight = 231;

// Ahead is measured twice per sweep: it is the zone the user walks into.
const Zone kSequence[4] = {ZONE_AHEAD, ZONE_LEFT, ZONE_AHEAD, ZONE_RIGHT};

// Ten failures in a row is about half a second of no data: long enough to
// ride out one bad transaction, short enough that the user learns quickly
// that obstacle warnings have stopped.
constexpr uint8_t kErrorsToFault = 10;
constexpr uint32_t kRecoveryIntervalMs = 2000;

VL53L1X g_l1;
VL53L0X g_l0;
Chip g_chip = Chip::None;
bool g_mirrored = TOF_ZONES_MIRRORED != 0;
bool g_long = true;
float g_ambient = 0.0f;
uint8_t g_brightCount = 0;
uint8_t g_dimCount = 0;
uint32_t g_errors = 0;
uint8_t g_errorsInRow = 0;
bool g_faulty = false;
Event g_event = Event::None;
uint32_t g_lastRecoveryMs = 0;
uint32_t g_lastSampleMs = 0;

uint8_t g_seq = 0;
bool g_measuring = false;
uint32_t g_startedMs = 0;
Zone g_measuringZone = ZONE_AHEAD;

struct Latest {
  uint16_t mm;
  bool valid;
  bool have;
  uint32_t atMs;
};
Latest g_latest[ZONE_COUNT] = {};

uint8_t spadFor(Zone z)
{
  switch (z) {
    case ZONE_LEFT: return g_mirrored ? kSpadRight : kSpadLeft;
    case ZONE_RIGHT: return g_mirrored ? kSpadLeft : kSpadRight;
    default: return kSpadAhead;
  }
}

uint32_t budgetMs() { return g_long ? 33 : 20; }

// A sensor reset mid-transaction can leave SDA held low, and the I2C
// peripheral cannot clear that on its own. Nine clocks release any target.
void recoverBus()
{
  Wire.end();
  pinMode(PIN_I2C_SDA, INPUT_PULLUP);
  pinMode(PIN_I2C_SCL, OUTPUT_OPEN_DRAIN);
  for (int i = 0; i < 9; ++i) {
    digitalWrite(PIN_I2C_SCL, LOW);
    delayMicroseconds(5);
    digitalWrite(PIN_I2C_SCL, HIGH);
    delayMicroseconds(5);
  }
  Wire.setSCL(PIN_I2C_SCL);
  Wire.setSDA(PIN_I2C_SDA);
  Wire.begin();
  Wire.setClock(TOF_I2C_CLOCK_HZ);
}

void hardReset()
{
  pinMode(PIN_TOF_XSHUT, OUTPUT);
  digitalWrite(PIN_TOF_XSHUT, LOW);
  delay(5);
  digitalWrite(PIN_TOF_XSHUT, HIGH);
  delay(5);
}

// Index-only write then read: changes no register on either chip.
bool probeL0X()
{
  Wire.beginTransmission(kAddress);
  Wire.write((uint8_t)0xC0);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom(kAddress, (uint8_t)1) != 1) return false;
  return Wire.read() == 0xEE;
}

bool probeL1X()
{
  Wire.beginTransmission(kAddress);
  Wire.write((uint8_t)0x01);
  Wire.write((uint8_t)0x0F);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom(kAddress, (uint8_t)2) != 2) return false;
  const uint8_t hi = Wire.read();
  const uint8_t lo = Wire.read();
  return hi == 0xEA && lo == 0xCC;
}

bool initL1X()
{
  g_l1.setBus(&Wire);
  g_l1.setTimeout(100);
  if (!g_l1.init()) return false;
  g_long = true;
  if (!g_l1.setDistanceMode(VL53L1X::Long)) return false;
  if (!g_l1.setMeasurementTimingBudget(33000)) return false;
  g_l1.setROISize(kRoiWidth, kRoiHeight);
  g_measuring = false;
  return true;
}

bool initL0X()
{
  g_l0.setBus(&Wire);
  g_l0.setTimeout(100);
  if (!g_l0.init()) return false;
  if (!g_l0.setMeasurementTimingBudget(33000)) return false;
  g_l0.startContinuous(0);
  return true;
}

bool detectAndInit()
{
  hardReset();
  g_chip = Chip::None;
  if (probeL0X() && initL0X()) {
    g_chip = Chip::VL53L0X;
  } else if (probeL1X() && initL1X()) {
    g_chip = Chip::VL53L1X;
  }
  g_errorsInRow = 0;
  g_lastSampleMs = millis();
  return g_chip != Chip::None;
}

bool fail(uint32_t nowMs)
{
  ++g_errors;
  if (++g_errorsInRow >= kErrorsToFault && !g_faulty) {
    g_faulty = true;
    g_event = Event::Fault;
    g_chip = Chip::None;
    g_lastRecoveryMs = nowMs;
  }
  return false;
}

void succeed(uint32_t nowMs)
{
  g_errorsInRow = 0;
  g_lastSampleMs = nowMs;
}

void store(const Sample &s)
{
  g_latest[s.zone] = Latest{s.mm, s.valid, true, s.atMs};
}

void switchMode(bool toLong)
{
  if (toLong) {
    g_l1.setDistanceMode(VL53L1X::Long);
    g_l1.setMeasurementTimingBudget(33000);
    g_event = Event::NormalLight;
  } else {
    // 20 ms is short mode's minimum budget and its highest rate.
    g_l1.setDistanceMode(VL53L1X::Short);
    g_l1.setMeasurementTimingBudget(20000);
    g_event = Event::BrightLight;
  }
  g_long = toLong;
  g_brightCount = 0;
  g_dimCount = 0;
}

void updateAmbient(float mcps)
{
  g_ambient = 0.8f * g_ambient + 0.2f * mcps;
#if TOF_MODE_AUTO
  // Asymmetric on purpose: dropping into short mode when the sun comes out
  // must be quick; climbing back out can wait for the light to settle.
  if (g_long) {
    g_brightCount = g_ambient > TOF_AMBIENT_TO_SHORT_MCPS ? g_brightCount + 1 : 0;
    if (g_brightCount >= 6) switchMode(false);
  } else {
    g_dimCount = g_ambient < TOF_AMBIENT_TO_LONG_MCPS ? g_dimCount + 1 : 0;
    if (g_dimCount >= 24) switchMode(true);
  }
#endif
}

bool pollL1X(uint32_t nowMs, Sample &out)
{
  if (!g_measuring) {
    const Zone z = kSequence[g_seq];
    g_seq = (uint8_t)((g_seq + 1) % 4);
    // A region change only applies to the next ranging that starts, so it is
    // written before each single-shot start, never during one.
    g_l1.setROICenter(spadFor(z));
    g_l1.readSingle(false);
    if (g_l1.last_status != 0) return fail(nowMs);
    g_measuring = true;
    g_startedMs = nowMs;
    g_measuringZone = z;
    return false;
  }

  const bool ready = g_l1.dataReady();
  if (g_l1.last_status != 0) {
    g_measuring = false;
    return fail(nowMs);
  }
  if (!ready) {
    if (nowMs - g_startedMs > 3 * budgetMs() + 20) {
      g_measuring = false;
      return fail(nowMs);
    }
    return false;
  }

  g_l1.read(false);
  g_measuring = false;
  if (g_l1.last_status != 0) return fail(nowMs);
  succeed(nowMs);

  const VL53L1X::RangingData &r = g_l1.ranging_data;
  const bool valid = r.range_status == VL53L1X::RangeValid ||
                     r.range_status == VL53L1X::RangeValidMinRangeClipped ||
                     r.range_status == VL53L1X::RangeValidNoWrapCheckFail;
  updateAmbient(r.ambient_count_rate_MCPS);
  out = Sample{g_measuringZone, valid, r.range_mm, nowMs};
  store(out);
  return true;
}

bool pollL0X(uint32_t nowMs, Sample &out)
{
  const uint8_t irq = g_l0.readReg(VL53L0X::RESULT_INTERRUPT_STATUS);
  if (g_l0.last_status != 0) return fail(nowMs);
  if ((irq & 0x07) == 0) {
    if (nowMs - g_lastSampleMs > 300) {
      g_lastSampleMs = nowMs;
      return fail(nowMs);
    }
    return false;
  }

  // Device range status 11 is "range valid"; anything else (including the
  // 8190/8191 "nothing in range" values) is not a distance.
  const uint8_t rangeStatus = (g_l0.readReg(VL53L0X::RESULT_RANGE_STATUS) >> 3) & 0x0F;
  const uint16_t mm = g_l0.readRangeContinuousMillimeters();
  if (g_l0.timeoutOccurred() || g_l0.last_status != 0) return fail(nowMs);
  succeed(nowMs);

  const bool valid = rangeStatus == 11 && mm < 8190;
  out = Sample{ZONE_AHEAD, valid, mm, nowMs};
  store(out);
  return true;
}

}  // namespace

bool begin()
{
  Wire.setSCL(PIN_I2C_SCL);
  Wire.setSDA(PIN_I2C_SDA);
  Wire.begin();
  Wire.setClock(TOF_I2C_CLOCK_HZ);
  if (detectAndInit()) return true;
  g_faulty = true;
  g_lastRecoveryMs = millis();
  return false;
}

Chip chip() { return g_chip; }

const char *chipName()
{
  switch (g_chip) {
    case Chip::VL53L1X: return "VL53L1X";
    case Chip::VL53L0X: return "VL53L0X";
    default: return "none";
  }
}

bool zonesAvailable() { return g_chip == Chip::VL53L1X; }

bool poll(uint32_t nowMs, Sample &out)
{
  switch (g_chip) {
    case Chip::VL53L1X: return pollL1X(nowMs, out);
    case Chip::VL53L0X: return pollL0X(nowMs, out);
    default: break;
  }
  if (nowMs - g_lastRecoveryMs >= kRecoveryIntervalMs) {
    g_lastRecoveryMs = nowMs;
    recoverBus();
    if (detectAndInit() && g_faulty) {
      g_faulty = false;
      g_event = Event::Recovered;
    }
  }
  return false;
}

Event takeEvent()
{
  const Event e = g_event;
  g_event = Event::None;
  return e;
}

bool longMode() { return g_chip == Chip::VL53L1X && g_long; }
float ambientMcps() { return g_ambient; }
uint32_t errorCount() { return g_errors; }
bool faulty() { return g_faulty; }

bool latest(Zone zone, uint16_t &mm, bool &valid, uint32_t &ageMs, uint32_t nowMs)
{
  if (zone >= ZONE_COUNT || !g_latest[zone].have) return false;
  mm = g_latest[zone].mm;
  valid = g_latest[zone].valid;
  ageMs = nowMs - g_latest[zone].atMs;
  return true;
}

uint16_t spokenRangeMm()
{
  switch (g_chip) {
    case Chip::VL53L1X: return g_long ? TOF_SPOKEN_RANGE_L1X_LONG_MM : TOF_SPOKEN_RANGE_L1X_SHORT_MM;
    case Chip::VL53L0X: return TOF_SPOKEN_RANGE_L0X_MM;
    default: return 0;
  }
}

void setMirrored(bool mirrored) { g_mirrored = mirrored; }
bool mirrored() { return g_mirrored; }

}  // namespace tof
