#include <Arduino.h>
#include <Wire.h>
#include <VL53L0X.h>
#include <VL53L1X.h>
#include <stdio.h>
#include <string.h>

#include "clock_config.h"
#include "font6x10.h"

// Standalone test: read the ToF distance sensor and show it live on the
// board's own LCD as "NN cm". Pin map and LCD init sequence copied from the
// vision-assistant firmware (board_pins.h / display.cpp) so this runs on the
// same WeAct MiniSTM32H743VITx wiring without needing that whole project.

// ---- pins (WeAct MiniSTM32H743VITx) ---------------------------------------
constexpr int kPinI2cScl = PB10;  // I2C2: PB8/PB9 belong to the camera's SCCB
constexpr int kPinI2cSda = PB11;
constexpr int kPinTofXshut = PD14;  // optional hard-reset line

constexpr int kPinLcdCs = PE11;
constexpr int kPinLcdDc = PE13;
constexpr int kPinLcdRst = PE15;
constexpr int kPinLcdBl = PE10;  // backlight lights when driven LOW

constexpr uint32_t kI2cClockHz = 400000;

// ---- LCD: ST7735, 160x80, SPI4 --------------------------------------------
namespace lcd {

constexpr int kW = 160;
constexpr int kH = 80;
constexpr int kOffsetX = 1;
constexpr int kOffsetY = 26;

constexpr uint16_t kBlack = 0x0000;
constexpr uint16_t kWhite = 0xFFFF;
constexpr uint16_t kYellow = 0xFFE0;
constexpr uint16_t kGrey = 0x8410;
constexpr uint16_t kRed = 0xF800;

SPI_HandleTypeDef g_spi;
uint16_t g_fb[kW * kH];

inline uint16_t swap16(uint16_t c) { return (uint16_t)((c >> 8) | (c << 8)); }

void command(uint8_t c, const uint8_t *d = nullptr, uint16_t n = 0)
{
  digitalWrite(kPinLcdCs, LOW);
  digitalWrite(kPinLcdDc, LOW);
  HAL_SPI_Transmit(&g_spi, &c, 1, 100);
  if (n) {
    digitalWrite(kPinLcdDc, HIGH);
    HAL_SPI_Transmit(&g_spi, (uint8_t *)d, n, 100);
  }
  digitalWrite(kPinLcdCs, HIGH);
}

struct InitStep {
  uint8_t cmd;
  uint8_t len;
  uint8_t data[16];
  uint16_t delayMs;
};

const InitStep kInit[] = {
    {0x01, 0, {}, 150},
    {0x11, 0, {}, 120},
    {0xB1, 3, {0x01, 0x2C, 0x2D}, 0},
    {0xB2, 3, {0x01, 0x2C, 0x2D}, 0},
    {0xB3, 6, {0x01, 0x2C, 0x2D, 0x01, 0x2C, 0x2D}, 0},
    {0xB4, 1, {0x07}, 0},
    {0xC0, 3, {0xA2, 0x02, 0x84}, 0},
    {0xC1, 1, {0xC5}, 0},
    {0xC2, 2, {0x0A, 0x00}, 0},
    {0xC3, 2, {0x8A, 0x2A}, 0},
    {0xC4, 2, {0x8A, 0xEE}, 0},
    {0xC5, 1, {0x0E}, 0},
    {0x21, 0, {}, 0},
    {0x36, 1, {0x78}, 0},
    {0x3A, 1, {0x05}, 0},
    {0xE0, 16, {0x02, 0x1C, 0x07, 0x12, 0x37, 0x32, 0x29, 0x2D, 0x29, 0x25, 0x2B, 0x39, 0x00, 0x01, 0x03, 0x10}, 0},
    {0xE1, 16, {0x03, 0x1D, 0x07, 0x06, 0x2E, 0x2C, 0x29, 0x2D, 0x2E, 0x2E, 0x37, 0x3F, 0x00, 0x00, 0x02, 0x10}, 0},
    {0x13, 0, {}, 10},
    {0x29, 0, {}, 100},
};

void flushRows(int y0, int y1)
{
  const uint16_t xs = kOffsetX, xe = kOffsetX + kW - 1;
  const uint16_t ys = (uint16_t)(kOffsetY + y0), ye = (uint16_t)(kOffsetY + y1);
  const uint8_t ca[4] = {(uint8_t)(xs >> 8), (uint8_t)xs, (uint8_t)(xe >> 8), (uint8_t)xe};
  const uint8_t ra[4] = {(uint8_t)(ys >> 8), (uint8_t)ys, (uint8_t)(ye >> 8), (uint8_t)ye};
  command(0x2A, ca, 4);
  command(0x2B, ra, 4);
  command(0x2C, (const uint8_t *)&g_fb[y0 * kW], (uint16_t)((y1 - y0 + 1) * kW * 2));
}

void fill(int x, int y, int w, int h, uint16_t color)
{
  const uint16_t c = swap16(color);
  for (int yy = y; yy < y + h && yy < kH; ++yy) {
    for (int xx = x; xx < x + w && xx < kW; ++xx) g_fb[yy * kW + xx] = c;
  }
}

// scale 1 = the native 6x10 font; scale N draws each font pixel as an NxN block.
void text(int x, int y, const char *s, uint16_t color, int scale = 1)
{
  const uint16_t c = swap16(color);
  const int cellW = kFontW * scale;
  for (; *s && x + cellW <= kW; ++s, x += cellW) {
    const uint8_t ch = (uint8_t)*s;
    if (ch < 32 || ch > 126) continue;
    const uint8_t *g = kFontAscii[ch - 32];
    for (int r = 0; r < kFontH; ++r) {
      for (int col = 0; col < kFontW; ++col) {
        if (!(g[r] & (0x80 >> col))) continue;
        for (int sy = 0; sy < scale; ++sy) {
          for (int sx = 0; sx < scale; ++sx) {
            const int px = x + col * scale + sx;
            const int py = y + r * scale + sy;
            if (px >= 0 && px < kW && py >= 0 && py < kH) g_fb[py * kW + px] = c;
          }
        }
      }
    }
  }
}

int textWidth(const char *s, int scale) { return (int)strlen(s) * kFontW * scale; }

bool begin()
{
  pinMode(kPinLcdCs, OUTPUT);
  pinMode(kPinLcdDc, OUTPUT);
  pinMode(kPinLcdRst, OUTPUT);
  pinMode(kPinLcdBl, OUTPUT);
  digitalWrite(kPinLcdCs, HIGH);
  digitalWrite(kPinLcdBl, HIGH);  // off until the first frame is drawn
  digitalWrite(kPinLcdRst, LOW);
  delay(10);
  digitalWrite(kPinLcdRst, HIGH);
  delay(120);

  __HAL_RCC_SPI4_CLK_ENABLE();
  __HAL_RCC_GPIOE_CLK_ENABLE();
  GPIO_InitTypeDef g = {};
  g.Pin = GPIO_PIN_12 | GPIO_PIN_14;  // SCK, MOSI
  g.Mode = GPIO_MODE_AF_PP;
  g.Pull = GPIO_NOPULL;
  g.Speed = GPIO_SPEED_FREQ_HIGH;
  g.Alternate = GPIO_AF5_SPI4;
  HAL_GPIO_Init(GPIOE, &g);

  g_spi.Instance = SPI4;
  g_spi.Init.Mode = SPI_MODE_MASTER;
  g_spi.Init.Direction = SPI_DIRECTION_2LINES_TXONLY;
  g_spi.Init.DataSize = SPI_DATASIZE_8BIT;
  g_spi.Init.CLKPolarity = SPI_POLARITY_LOW;
  g_spi.Init.CLKPhase = SPI_PHASE_1EDGE;
  g_spi.Init.NSS = SPI_NSS_SOFT;
  g_spi.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_8;
  g_spi.Init.FirstBit = SPI_FIRSTBIT_MSB;
  g_spi.Init.TIMode = SPI_TIMODE_DISABLE;
  g_spi.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  g_spi.Init.NSSPMode = SPI_NSS_PULSE_DISABLE;
  g_spi.Init.FifoThreshold = SPI_FIFO_THRESHOLD_01DATA;
  g_spi.Init.MasterKeepIOState = SPI_MASTER_KEEP_IO_STATE_ENABLE;
  if (HAL_SPI_Init(&g_spi) != HAL_OK) return false;

  for (const InitStep &s : kInit) {
    command(s.cmd, s.data, s.len);
    if (s.delayMs) delay(s.delayMs);
  }
  fill(0, 0, kW, kH, kBlack);
  flushRows(0, kH - 1);
  digitalWrite(kPinLcdBl, LOW);  // on
  return true;
}

}  // namespace lcd

// ---- ToF: VL53L0X or VL53L1X, auto-detected -------------------------------
namespace tof {

enum class Chip { None, L0X, L1X };

constexpr uint8_t kAddress = 0x29;

VL53L0X g_l0;
VL53L1X g_l1;
Chip g_chip = Chip::None;

void hardReset()
{
  pinMode(kPinTofXshut, OUTPUT);
  digitalWrite(kPinTofXshut, LOW);
  delay(5);
  digitalWrite(kPinTofXshut, HIGH);
  delay(5);
}

// A sensor reset mid-transaction can leave SDA held low; nine clocks release it.
void recoverBus()
{
  Wire.end();
  pinMode(kPinI2cSda, INPUT_PULLUP);
  pinMode(kPinI2cScl, OUTPUT_OPEN_DRAIN);
  for (int i = 0; i < 9; ++i) {
    digitalWrite(kPinI2cScl, LOW);
    delayMicroseconds(5);
    digitalWrite(kPinI2cScl, HIGH);
    delayMicroseconds(5);
  }
  Wire.setSCL(kPinI2cScl);
  Wire.setSDA(kPinI2cSda);
  Wire.begin();
  Wire.setClock(kI2cClockHz);
}

// A full 7-bit address sweep. The camera on this same board turned out to
// answer 0x21, not the 0x3C it was built for -- so for the ToF sensor too,
// find the real address on the bus instead of only ever trying the
// datasheet default (0x29).
constexpr uint8_t kMaxFound = 8;
uint8_t g_found[kMaxFound];
uint8_t g_foundCount = 0;

void scanBus()
{
  g_foundCount = 0;
  for (uint8_t addr = 0x08; addr <= 0x77; ++addr) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0 && g_foundCount < kMaxFound) g_found[g_foundCount++] = addr;
  }
}

void printScan(Print &out)
{
  out.print("i2c scan (PB10/PB11): ");
  if (g_foundCount == 0) {
    out.println("no device answered");
    return;
  }
  for (uint8_t i = 0; i < g_foundCount; ++i) {
    if (i) out.print(", ");
    out.print("0x");
    out.print(g_found[i], HEX);
  }
  out.println();
}

void addrLine(char *out, size_t n)
{
  if (g_foundCount == 0) {
    snprintf(out, n, "i2c: no device found");
    return;
  }
  int pos = snprintf(out, (int)n, "i2c addr:");
  for (uint8_t i = 0; i < g_foundCount && pos < (int)n - 6; ++i) {
    pos += snprintf(out + pos, n - pos, " %02X", g_found[i]);
  }
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

bool detectAndInit()
{
  hardReset();
  g_chip = Chip::None;
  scanBus();
  printScan(Serial);
  if (probeL0X()) {
    g_l0.setBus(&Wire);
    g_l0.setTimeout(200);
    if (g_l0.init() && g_l0.setMeasurementTimingBudget(33000)) {
      g_l0.startContinuous(0);
      g_chip = Chip::L0X;
    }
  } else if (probeL1X()) {
    g_l1.setBus(&Wire);
    g_l1.setTimeout(200);
    if (g_l1.init() && g_l1.setDistanceMode(VL53L1X::Long) &&
        g_l1.setMeasurementTimingBudget(33000)) {
      g_l1.startContinuous(50);
      g_chip = Chip::L1X;
    }
  }
  return g_chip != Chip::None;
}

const char *chipName()
{
  switch (g_chip) {
    case Chip::L0X: return "VL53L0X";
    case Chip::L1X: return "VL53L1X";
    default: return "none";
  }
}

// Returns true with a fresh millimetre reading, false if nothing new/valid yet.
bool read(uint16_t &mm)
{
  switch (g_chip) {
    case Chip::L0X: {
      mm = g_l0.readRangeContinuousMillimeters();
      return !g_l0.timeoutOccurred() && mm < 8190;
    }
    case Chip::L1X: {
      g_l1.read(true);  // blocks until a measurement is ready
      if (g_l1.timeoutOccurred()) return false;
      const VL53L1X::RangingData &r = g_l1.ranging_data;
      const bool valid = r.range_status == VL53L1X::RangeValid ||
                         r.range_status == VL53L1X::RangeValidMinRangeClipped ||
                         r.range_status == VL53L1X::RangeValidNoWrapCheckFail;
      mm = r.range_mm;
      return valid;
    }
    default:
      return false;
  }
}

}  // namespace tof

// ---- app -------------------------------------------------------------------

constexpr uint32_t kRecoveryIntervalMs = 2000;
constexpr int kBigScale = 4;  // "123cm" at scale 4 is 120x40 px, fits 160x80

uint32_t g_lastRecoveryMs = 0;
char g_shown[48] = "";

void drawCentered(const char *s, uint16_t color, int scale)
{
  const int w = lcd::textWidth(s, scale);
  const int h = kFontH * scale;
  lcd::fill(0, 20, lcd::kW, 50, lcd::kBlack);
  lcd::text((lcd::kW - w) / 2, 20 + (50 - h) / 2, s, color, scale);
  lcd::flushRows(20, 69);
}

void setup()
{
  Serial.begin(115200);

  Wire.setSCL(kPinI2cScl);
  Wire.setSDA(kPinI2cSda);
  Wire.begin();
  Wire.setClock(kI2cClockHz);

  lcd::begin();
  lcd::text(4, 2, "ToF live distance", lcd::kWhite);
  lcd::flushRows(0, 19);

  if (tof::detectAndInit()) {
    Serial.print("tof sensor: ");
    Serial.println(tof::chipName());
  } else {
    Serial.println("tof sensor: none detected on PB10(SCL)/PB11(SDA)");
    g_lastRecoveryMs = millis();
  }
}

// Bit-banged open-drain I2C on any two pins, so a swapped SCL/SDA wiring or
// the other header pair can be tested without moving a single wire.
namespace soft {

int g_scl, g_sda;

void rel(int p) { pinMode(p, INPUT_PULLUP); }
void low(int p) { pinMode(p, OUTPUT); digitalWrite(p, LOW); }
void dly() { delayMicroseconds(10); }

bool writeByte(uint8_t b)
{
  for (int i = 7; i >= 0; --i) {
    if (b & (1 << i)) rel(g_sda); else low(g_sda);
    dly(); rel(g_scl); dly(); low(g_scl);
  }
  rel(g_sda); dly(); rel(g_scl); dly();
  const bool ack = digitalRead(g_sda) == LOW;
  low(g_scl);
  return ack;
}

void scan(int scl, int sda, const char *name)
{
  g_scl = scl;
  g_sda = sda;
  Serial.print(name);
  Serial.print(": ");
  int found = 0;
  for (uint8_t a = 0x08; a <= 0x77; ++a) {
    rel(g_sda); rel(g_scl); dly();
    low(g_sda); dly(); low(g_scl);  // start
    const bool ack = writeByte((uint8_t)(a << 1));
    low(g_sda); dly(); rel(g_scl); dly(); rel(g_sda); dly();  // stop
    if (ack) {
      Serial.print("0x");
      Serial.print(a, HEX);
      Serial.print(" ");
      ++found;
    }
  }
  Serial.println(found ? "" : "nothing");
}

// Every GPIO with the internal pull-down on: a pin that still reads HIGH has
// an external pull-up, which is what an I2C module's SCL/SDA look like.
// USB (PA11/12), SWD (PA13/14) and the LCD (PE10-15) are left alone.
int findPulledUp(int *out, int max)
{
  int n = 0;
  for (int port = 0; port < 5; ++port) {
    for (int pin = 0; pin < 16; ++pin) {
      if (port == 0 && pin >= 11 && pin <= 14) continue;
      if (port == 4 && pin >= 10) continue;
      const int d = pinNametoDigitalPin((PinName)((port << 4) | pin));
      if (d < 0) continue;
      pinMode(d, INPUT_PULLDOWN);
      delayMicroseconds(200);
      if (digitalRead(d) == HIGH && n < max) {
        out[n++] = d;
        Serial.print("  P");
        Serial.print((char)('A' + port));
        Serial.print(pin);
        Serial.println(" is pulled up externally");
      }
      pinMode(d, INPUT);
    }
  }
  return n;
}

const char *nameOf(int d)
{
  static char s[2][6];
  static int k = 0;
  k ^= 1;
  const PinName p = digitalPinToPinName(d);
  snprintf(s[k], sizeof(s[k]), "P%c%d", 'A' + ((p >> 4) & 0xF), p & 0xF);
  return s[k];
}

void hunt()
{
  int pins[16];
  Serial.println("looking for externally pulled-up pins...");
  const int n = findPulledUp(pins, 16);
  for (int i = 0; i < n; ++i) {
    for (int j = 0; j < n; ++j) {
      if (i == j) continue;
      char label[32];
      snprintf(label, sizeof(label), "SCL=%s SDA=%s", nameOf(pins[i]), nameOf(pins[j]));
      scan(pins[i], pins[j], label);
    }
  }
  Serial.println("hunt done");
}

}  // namespace soft

// `scan` re-runs the bus sweep; `dfu` restarts into the boot loader so
// `pio run -t upload` needs no BOOT0/NRST presses.
void pollSerial()
{
  static char buf[16];
  static uint8_t n = 0;
  while (Serial.available()) {
    const char c = (char)Serial.read();
    if (c != '\n' && c != '\r') {
      if (n < sizeof(buf) - 1) buf[n++] = c;
      continue;
    }
    buf[n] = '\0';
    n = 0;
    if (strcmp(buf, "dfu") == 0) {
      Serial.println("DFU");
      Serial.flush();
      delay(100);
      requestBootloader();
    } else if (strcmp(buf, "camtest") == 0) {
      // Known-good control: the OV7725 answers 0x21 on this bus only while it
      // gets XCLK (MCO1 on PA8), at either PWDN (PA7) level.
      __HAL_RCC_GPIOA_CLK_ENABLE();
      GPIO_InitTypeDef g = {};
      g.Pin = GPIO_PIN_8;
      g.Mode = GPIO_MODE_AF_PP;
      g.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
      g.Alternate = GPIO_AF0_MCO;
      HAL_GPIO_Init(GPIOA, &g);
      HAL_RCC_MCOConfig(RCC_MCO1, RCC_MCO1SOURCE_HSE, RCC_MCODIV_1);
      pinMode(PA7, OUTPUT);
      for (int lvl = 0; lvl < 2; ++lvl) {
        digitalWrite(PA7, lvl ? HIGH : LOW);
        delay(50);
        tof::scanBus();
        Serial.print(lvl ? "XCLK on, PA7 high: " : "XCLK on, PA7 low: ");
        tof::printScan(Serial);
      }
    } else if (strcmp(buf, "wiggle") == 0) {
      Wire.end();
      const int p[2] = {PB8, PB9};
      const char *nm[2] = {"PB8", "PB9"};
      for (int i = 0; i < 2; ++i) {
        const int o = p[1 - i];
        soft::rel(o);
        soft::low(p[i]);
        delayMicroseconds(50);
        const int selfLow = digitalRead(p[i]);
        const int other = digitalRead(o);
        soft::rel(p[i]);
        delayMicroseconds(50);
        const int selfHigh = digitalRead(p[i]);
        Serial.print(nm[i]);
        Serial.print(": driven low reads ");
        Serial.print(selfLow ? "HIGH(!)" : "LOW");
        Serial.print(", released reads ");
        Serial.print(selfHigh ? "HIGH" : "LOW(!)");
        Serial.print(", other line while this low: ");
        Serial.println(other ? "HIGH (not shorted)" : "LOW (SHORTED!)");
      }
      // ~10 kHz: slow enough for any module, long wires or weak pull-ups.
      soft::g_scl = PB8;
      soft::g_sda = PB9;
      Serial.print("slow soft scan: ");
      int found = 0;
      for (uint8_t a = 0x08; a <= 0x77; ++a) {
        soft::rel(PB9); soft::rel(PB8); delayMicroseconds(100);
        soft::low(PB9); delayMicroseconds(100); soft::low(PB8);
        bool ack = true;
        for (int b = 7; b >= 0 && ack; --b) {
          if (((a << 1) >> b) & 1) soft::rel(PB9); else soft::low(PB9);
          delayMicroseconds(50); soft::rel(PB8); delayMicroseconds(50); soft::low(PB8);
        }
        soft::rel(PB9); delayMicroseconds(50); soft::rel(PB8); delayMicroseconds(50);
        ack = digitalRead(PB9) == LOW;
        soft::low(PB8); delayMicroseconds(50);
        soft::low(PB9); delayMicroseconds(50); soft::rel(PB8); delayMicroseconds(50); soft::rel(PB9);
        if (ack) { Serial.print("0x"); Serial.print(a, HEX); Serial.print(" "); ++found; }
      }
      Serial.println(found ? "" : "nothing");
      tof::recoverBus();
      Wire.setClock(100000);
      tof::scanBus();
      Serial.print("hardware 100kHz ");
      tof::printScan(Serial);
      Wire.setClock(kI2cClockHz);
    } else if (strcmp(buf, "hunt") == 0) {
      Wire.end();
      soft::hunt();
      tof::recoverBus();
    } else if (strcmp(buf, "soft") == 0) {
      Wire.end();
      soft::scan(PB8, PB9, "SCL=PB8  SDA=PB9 ");
      soft::scan(PB9, PB8, "SCL=PB9  SDA=PB8  (swapped)");
      soft::scan(PB10, PB11, "SCL=PB10 SDA=PB11");
      soft::scan(PB11, PB10, "SCL=PB11 SDA=PB10 (swapped)");
      tof::recoverBus();
    } else if (strcmp(buf, "lines") == 0) {
      // With no internal pull, a line reads HIGH only if the module's own
      // pull-up is powered and actually connected to that pin.
      Wire.end();
      pinMode(kPinI2cScl, INPUT);
      pinMode(kPinI2cSda, INPUT);
      delay(5);
      Serial.print("SCL(PB10)=");
      Serial.print(digitalRead(kPinI2cScl) ? "HIGH" : "LOW");
      Serial.print(" SDA(PB11)=");
      Serial.println(digitalRead(kPinI2cSda) ? "HIGH" : "LOW");
      pinMode(kPinI2cScl, INPUT_PULLDOWN);
      pinMode(kPinI2cSda, INPUT_PULLDOWN);
      delay(5);
      Serial.print("with pull-down: SCL=");
      Serial.print(digitalRead(kPinI2cScl) ? "HIGH" : "LOW");
      Serial.print(" SDA=");
      Serial.println(digitalRead(kPinI2cSda) ? "HIGH" : "LOW");
      tof::recoverBus();
    } else if (strcmp(buf, "scan") == 0) {
      tof::scanBus();
      tof::printScan(Serial);
      Serial.print("tof sensor: ");
      Serial.println(tof::chipName());
    }
  }
}

void loop()
{
  pollSerial();
  const uint32_t now = millis();

  if (tof::g_chip == tof::Chip::None) {
    if (now - g_lastRecoveryMs >= kRecoveryIntervalMs) {
      g_lastRecoveryMs = now;
      tof::recoverBus();
      if (tof::detectAndInit()) {
        Serial.print("tof sensor found: ");
        Serial.println(tof::chipName());
      }
    }
    char addr[32];
    tof::addrLine(addr, sizeof(addr));
    char label[48];
    snprintf(label, sizeof(label), "NO SENSOR|%s", addr);  // key off both fields
    if (strcmp(g_shown, label) != 0) {
      strcpy(g_shown, label);
      drawCentered("NO SENSOR", lcd::kYellow, 2);
      lcd::fill(0, 70, lcd::kW, 10, lcd::kBlack);
      lcd::text(4, 70, addr, lcd::kGrey);
      lcd::flushRows(70, 79);
    }
    return;
  }

  uint16_t mm = 0;
  const bool valid = tof::read(mm);
  char line[16];
  if (!valid) {
    snprintf(line, sizeof(line), "--");
  } else if (mm >= 9990) {
    snprintf(line, sizeof(line), ">999cm");
  } else {
    snprintf(line, sizeof(line), "%ucm", (unsigned)(mm / 10));
  }

  if (strcmp(line, g_shown) != 0) {
    strcpy(g_shown, line);
    Serial.print("distance: ");
    Serial.print(valid ? mm : 0);
    Serial.println(" mm");
    drawCentered(line, valid ? lcd::kWhite : lcd::kRed, kBigScale);
  }
}
