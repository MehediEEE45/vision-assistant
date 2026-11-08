#include <Arduino.h>
#include <stdio.h>
#include <string.h>

#include "app.h"
#include "board_pins.h"
#include "config.h"
#include "display.h"
#include "display_assets.h"
#include "camera.h"
#include "finder.h"
#include "speaker.h"
#include "tof.h"
#include "vision.h"

namespace display {

namespace {

constexpr int kW = 160;
constexpr int kH = 80;
// The panel's visible window starts at column 1, row 26 of the controller's
// RAM (values from the board's Zephyr description, which drives this panel).
constexpr int kOffsetX = 1;
constexpr int kOffsetY = 26;

constexpr int kStatusRows = 11;
constexpr int kCaptionTop = 13;
constexpr int kCaptionLines = 4;  // 4 x 16 px fit below the status line
constexpr int kMaxLines = 24;

// A long caption (help) does not fit four lines; it pages this often.
constexpr uint32_t kPageMs = 2500;
constexpr uint32_t kStatusRefreshMs = 500;
constexpr uint32_t kCaptionCheckMs = 60;

constexpr uint16_t kBlack = 0x0000;
constexpr uint16_t kWhite = 0xFFFF;
constexpr uint16_t kYellow = 0xFFE0;
constexpr uint16_t kGrey = 0x8410;
constexpr uint16_t kNavy = 0x0010;
constexpr uint16_t kHazardBg = 0x9000;

SPI_HandleTypeDef g_spi;
bool g_ok = false;
// Stored byte-swapped: the panel takes each pixel most significant byte first.
uint16_t g_fb[kW * kH];

char g_status[32] = "";
uint32_t g_lastStatusMs = 0;
uint32_t g_lastCaptionMs = 0;

uint32_t g_seq = 0xFFFFFFFFu;
uint8_t g_item = 0xFF;
bool g_active = false;
uint32_t g_itemSinceMs = 0;
uint32_t g_page = 0;
uint32_t g_pages = 1;  // of the caption playing now

constexpr uint32_t kTestHoldMs = 8000;
bool g_testing = false;
uint32_t g_testUntilMs = 0;

inline uint16_t swap(uint16_t c) { return (uint16_t)((c >> 8) | (c << 8)); }

// CS stays low from the command byte through its last parameter: raised in
// between, this panel reads the parameters as new commands.
void command(uint8_t c, const uint8_t *d = nullptr, uint16_t n = 0)
{
  digitalWrite(PIN_LCD_CS, LOW);
  digitalWrite(PIN_LCD_DC, LOW);
  HAL_SPI_Transmit(&g_spi, &c, 1, 100);
  if (n) {
    digitalWrite(PIN_LCD_DC, HIGH);
    HAL_SPI_Transmit(&g_spi, (uint8_t *)d, n, 100);
  }
  digitalWrite(PIN_LCD_CS, HIGH);
}

struct InitStep {
  uint8_t cmd;
  uint8_t len;
  uint8_t data[16];
  uint16_t delayMs;
};

// ST7735 settings for this panel, from the board's Zephyr description:
// frame rate, inversion, power and gamma as the panel vendor tuned them.
const InitStep kInit[] = {
    {0x01, 0, {}, 150},                                   // software reset
    {0x11, 0, {}, 120},                                   // sleep out
    {0xB1, 3, {0x01, 0x2C, 0x2D}, 0},                     // frame rate, normal
    {0xB2, 3, {0x01, 0x2C, 0x2D}, 0},                     // frame rate, idle
    {0xB3, 6, {0x01, 0x2C, 0x2D, 0x01, 0x2C, 0x2D}, 0},   // frame rate, partial
    {0xB4, 1, {0x07}, 0},                                 // inversion control
    {0xC0, 3, {0xA2, 0x02, 0x84}, 0},                     // power 1..5
    {0xC1, 1, {0xC5}, 0},
    {0xC2, 2, {0x0A, 0x00}, 0},
    {0xC3, 2, {0x8A, 0x2A}, 0},
    {0xC4, 2, {0x8A, 0xEE}, 0},
    {0xC5, 1, {0x0E}, 0},                                 // VCOM
    {0x21, 0, {}, 0},                                     // inversion on: an IPS panel
    {0x36, 1, {LCD_MADCTL}, 0},
    {0x3A, 1, {0x05}, 0},                                 // 16 bits per pixel
    {0xE0, 16, {0x02, 0x1C, 0x07, 0x12, 0x37, 0x32, 0x29, 0x2D, 0x29, 0x25, 0x2B, 0x39, 0x00, 0x01, 0x03, 0x10}, 0},
    {0xE1, 16, {0x03, 0x1D, 0x07, 0x06, 0x2E, 0x2C, 0x29, 0x2D, 0x2E, 0x2E, 0x37, 0x3F, 0x00, 0x00, 0x02, 0x10}, 0},
    {0x13, 0, {}, 10},                                    // normal display
    {0x29, 0, {}, 100},                                   // display on
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
  const uint16_t c = swap(color);
  for (int yy = y; yy < y + h && yy < kH; ++yy) {
    for (int xx = x; xx < x + w && xx < kW; ++xx) g_fb[yy * kW + xx] = c;
  }
}

void text(int x, int y, const char *s, uint16_t color)
{
  const uint16_t c = swap(color);
  for (; *s && x + FONT_CELL_W <= kW; ++s, x += FONT_CELL_W) {
    const uint8_t ch = (uint8_t)*s;
    if (ch < 32 || ch > 126) continue;
    const uint8_t *g = kFontAscii[ch - 32];
    for (int r = 0; r < FONT_CELL_H; ++r) {
      for (int col = 0; col < FONT_CELL_W; ++col) {
        if (g[r] & (0x80 >> col)) g_fb[(y + r) * kW + x + col] = c;
      }
    }
  }
}

void bitmapLine(const CaptionLine &line, int x, int y, uint16_t color)
{
  const uint16_t c = swap(color);
  const int stride = (line.width + 7) / 8;
  for (int r = 0; r < CAPTION_LINE_HEIGHT && y + r < kH; ++r) {
    const uint8_t *row = line.bits + r * stride;
    for (int col = 0; col < line.width && x + col < kW; ++col) {
      if (row[col >> 3] & (0x80 >> (col & 7))) g_fb[(y + r) * kW + x + col] = c;
    }
  }
}

// The caption in the language of the clip that will actually play, which
// is English for any Bangla prompt not yet recorded.
const Caption &captionFor(uint16_t id)
{
  if (speaker::bangla() && speaker::hasBangla((PromptId)id) && kCaptionsBn[id].count > 0) return kCaptionsBn[id];
  return kCaptionsEn[id];
}

void formatDistance(char *out, size_t n, tof::Zone z, uint32_t nowMs)
{
  uint16_t mm = 0;
  bool valid = false;
  uint32_t age = 0;
  if (!tof::latest(z, mm, valid, age, nowMs) || age > 1000) {
    snprintf(out, n, "??");
  } else if (!valid) {
    snprintf(out, n, "--");
  } else if (mm >= 10000) {
    snprintf(out, n, "9+");
  } else {
    snprintf(out, n, "%u.%u", (unsigned)(mm / 1000), (unsigned)((mm % 1000) / 100));
  }
}

void buildStatus(char *out, size_t n, uint32_t nowMs)
{
  const char *lang = speaker::bangla() ? "BN" : "EN";
  const int menu = app_menuItem();
  if (app_alarmOn()) {
    snprintf(out, n, "%s ALARM - press to stop", lang);
  } else if (menu >= 0) {
    snprintf(out, n, "%s MENU: %s", lang, vision::label((uint8_t)menu));
  } else if (finder::mode() == finder::Mode::Search) {
    snprintf(out, n, "%s FIND: %s", lang, vision::label(finder::target()));
  } else if (finder::mode() == finder::Mode::Describe) {
    snprintf(out, n, "%s LOOKING...", lang);
  } else if (tof::chip() == tof::Chip::None) {
    snprintf(out, n, "%s NO DISTANCE SENSOR", lang);
  } else if (!tof::zonesAvailable()) {
    char a[6];
    formatDistance(a, sizeof(a), tof::ZONE_AHEAD, nowMs);
    snprintf(out, n, "%s AHEAD %sm", lang, a);
  } else {
    char l[6], a[6], r[6];
    formatDistance(l, sizeof(l), tof::ZONE_LEFT, nowMs);
    formatDistance(a, sizeof(a), tof::ZONE_AHEAD, nowMs);
    formatDistance(r, sizeof(r), tof::ZONE_RIGHT, nowMs);
    snprintf(out, n, "%s L%s A%s R%s", lang, l, a, r);
  }
}

void drawStatus()
{
  fill(0, 0, kW, kStatusRows, kNavy);
  text(2, 0, g_status, kWhite);
  flushRows(0, kStatusRows - 1);
}

// Picks the caption lines to show: the newest `show` lines of what has been
// said so far, or one page of a sentence too long to fit on its own.
int selectLines(const speaker::NowPlaying &np, uint32_t nowMs, int show, const CaptionLine **out)
{
  const CaptionLine *lines[kMaxLines];
  int count = 0;
  int currentFirst = 0;
  int currentCount = 0;
  const uint8_t last = np.active ? np.item : (uint8_t)(np.utterance.count ? np.utterance.count - 1 : 0);
  for (uint8_t i = 0; i < np.utterance.count && i <= last; ++i) {
    const speaker::Item &it = np.utterance.items[i];
    if (it.kind != speaker::kItemPrompt || it.value >= PROMPT_COUNT) continue;
    const Caption &cap = captionFor(it.value);
    if (i == last) currentFirst = count;
    for (uint8_t k = 0; k < cap.count && count < kMaxLines; ++k) lines[count++] = &cap.lines[k];
    if (i == last) currentCount = count - currentFirst;
  }

  int first = count > show ? count - show : 0;
  g_pages = 1;
  g_page = 0;
  if (np.active && currentCount > show) {
    g_pages = (uint32_t)((currentCount + show - 1) / show);
    g_page = ((nowMs - g_itemSinceMs) / kPageMs) % g_pages;
    first = currentFirst + (int)g_page * show;
  }
  int n = 0;
  for (; n < show && first + n < count; ++n) out[n] = lines[first + n];
  return n;
}

void captionColours(const speaker::NowPlaying &np, uint16_t &fg, uint16_t &bg)
{
  const bool hazard = np.utterance.priority == speaker::Priority::Hazard;
  bg = hazard && np.active ? kHazardBg : kBlack;
  fg = !np.active ? kGrey : hazard ? kYellow : kWhite;
}

void drawCaptions(const speaker::NowPlaying &np, uint32_t nowMs)
{
  const CaptionLine *sel[kCaptionLines];
  const int n = selectLines(np, nowMs, kCaptionLines, sel);
  uint16_t fg, bg;
  captionColours(np, fg, bg);
  fill(0, kStatusRows, kW, kH - kStatusRows, bg);
  for (int k = 0; k < n; ++k) bitmapLine(*sel[k], 2, kCaptionTop + k * CAPTION_LINE_HEIGHT, fg);
  flushRows(kStatusRows, kH - 1);
}

// ---- live camera view --------------------------------------------------

constexpr int kViewTop = kStatusRows;
constexpr int kViewRows = kH - kStatusRows;  // 69
// Halved, the 320x240 frame is 160x120; the middle 69 rows are shown, so the
// picture keeps its proportions and, above all, its full left-to-right width.
constexpr int kViewCropTop = (CAMERA_HEIGHT / 2 - kViewRows) / 2;
constexpr int kOverlayLines = 2;

bool g_view = LCD_CAMERA_VIEW != 0;
bool g_viewDrawn = false;
uint32_t g_viewSeq = 0;
uint32_t g_lastViewMs = 0;
uint32_t g_spokeUntilMs = 0;
bool g_viewHadCaption = false;

void drawView(const speaker::NowPlaying &np, uint32_t nowMs)
{
  const uint16_t *src = camera::frame();
  const bool haveFrame = camera::present() && camera::frameSeq() != 0;
  for (int y = 0; y < kViewRows; ++y) {
    uint16_t *dst = &g_fb[(kViewTop + y) * kW];
    if (!haveFrame) {
      for (int x = 0; x < kW; ++x) dst[x] = 0;
      continue;
    }
    const uint16_t *row = src + (size_t)(2 * (y + kViewCropTop)) * CAMERA_WIDTH;
    for (int x = 0; x < kW; ++x) dst[x] = swap(row[2 * x]);
  }
  // No PC/serial terminal needed to see why: the reason begin() or the last
  // capture failed is spelled out right where the picture should be.
  if (!camera::present()) {
    text(4, kViewTop + 20, "NO CAMERA:", kYellow);
    text(4, kViewTop + 36, camera::lastError(), kYellow);
  } else if (!haveFrame) {
    text(40, kViewTop + 20, "camera starting", kGrey);
    if (camera::errorCount() > 0) text(4, kViewTop + 36, camera::lastError(), kYellow);
  }

  const bool showCaption = np.seq != 0 && (np.active || (int32_t)(g_spokeUntilMs - nowMs) > 0);
  if (showCaption) {
    const CaptionLine *sel[kOverlayLines];
    const int n = selectLines(np, nowMs, kOverlayLines, sel);
    uint16_t fg, bg;
    captionColours(np, fg, bg);
    if (!np.active) fg = kWhite;  // grey is unreadable over a picture
    const int top = kH - n * CAPTION_LINE_HEIGHT - 2;
    fill(0, top, kW, kH - top, bg);
    for (int k = 0; k < n; ++k) bitmapLine(*sel[k], 2, top + 1 + k * CAPTION_LINE_HEIGHT, fg);
  }
  g_viewHadCaption = showCaption;
  flushRows(kViewTop, kH - 1);
  g_viewDrawn = true;
  g_lastViewMs = nowMs;
}

// Shown even without a camera: that is exactly when there is a reason to
// display (lastError()) that the user needs to see.
bool viewing() { return g_view; }

// Keeps frames coming while nothing else is using the camera. While the
// finder works, it takes the frames and the screen shows those.
void driveCamera(uint32_t nowMs)
{
  if (finder::mode() != finder::Mode::Idle) return;
  camera::wake(nowMs);
  camera::poll(nowMs);
  if (!camera::capturing() && nowMs - g_lastViewMs >= LCD_VIEW_FRAME_MS) camera::capture(nowMs);
}

bool initSpi()
{
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
  // 80 MHz kernel clock / 8 = 10 MHz, under the controller's 15 MHz write limit.
  g_spi.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_8;
  g_spi.Init.FirstBit = SPI_FIRSTBIT_MSB;
  g_spi.Init.TIMode = SPI_TIMODE_DISABLE;
  g_spi.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  g_spi.Init.NSSPMode = SPI_NSS_PULSE_DISABLE;
  g_spi.Init.FifoThreshold = SPI_FIFO_THRESHOLD_01DATA;
  g_spi.Init.MasterKeepIOState = SPI_MASTER_KEEP_IO_STATE_ENABLE;
  return HAL_SPI_Init(&g_spi) == HAL_OK;
}

}  // namespace

bool begin()
{
#if !LCD_ENABLED
  return false;
#else
  pinMode(PIN_LCD_CS, OUTPUT);
  pinMode(PIN_LCD_DC, OUTPUT);
  pinMode(PIN_LCD_RST, OUTPUT);
  pinMode(PIN_LCD_BL, OUTPUT);
  digitalWrite(PIN_LCD_CS, HIGH);
  // Dark until the first frame is written, so power-on noise never shows.
  digitalWrite(PIN_LCD_BL, LCD_BL_OFF);
  digitalWrite(PIN_LCD_RST, LOW);
  delay(10);
  digitalWrite(PIN_LCD_RST, HIGH);
  delay(120);
  if (!initSpi()) return false;
  for (const InitStep &s : kInit) {
    command(s.cmd, s.data, s.len);
    if (s.delayMs) delay(s.delayMs);
  }
  fill(0, 0, kW, kH, kBlack);
  flushRows(0, kH - 1);
  snprintf(g_status, sizeof(g_status), "Vision Assistant %s", FW_VERSION);
  drawStatus();
  digitalWrite(PIN_LCD_BL, LCD_BL_ON);
  g_ok = true;
  return true;
#endif
}

bool ok() { return g_ok; }

void setView(bool on)
{
  if (on == g_view) return;
  g_view = on;
  g_viewDrawn = false;
  if (!on) {
    if (finder::mode() == finder::Mode::Idle) camera::sleep();
    fill(0, kStatusRows, kW, kH - kStatusRows, kBlack);
    flushRows(kStatusRows, kH - 1);
    g_seq = 0xFFFFFFFFu;  // redraw the captions on the next pass
  }
}

bool viewOn() { return g_view; }

void testPattern(uint32_t nowMs)
{
  if (!g_ok) return;
  struct Bar {
    uint16_t color;
    const char *name;
  };
  const Bar bars[] = {{0xF800, "RED"}, {0x07E0, "GREEN"}, {0x001F, "BLUE"}, {kWhite, "WHITE"}};
  const int barH = kH / 4;
  for (int i = 0; i < 4; ++i) {
    fill(0, i * barH, kW, barH, bars[i].color);
    text(6, i * barH + (barH - FONT_CELL_H) / 2, bars[i].name, i == 3 ? kBlack : kWhite);
  }
  // A one-pixel frame: an edge missing or doubled means the RAM offsets are wrong.
  fill(0, 0, kW, 1, kYellow);
  fill(0, kH - 1, kW, 1, kYellow);
  fill(0, 0, 1, kH, kYellow);
  fill(kW - 1, 0, 1, kH, kYellow);
  text(kW - 3 * FONT_CELL_W - 4, 2, "TOP", kBlack);
  flushRows(0, kH - 1);
  g_testUntilMs = nowMs + kTestHoldMs;
  g_testing = true;
}

void update(uint32_t nowMs)
{
  if (!g_ok) return;

  if (g_testing) {
    if ((int32_t)(nowMs - g_testUntilMs) < 0) return;
    g_testing = false;
    fill(0, 0, kW, kH, kBlack);
    flushRows(0, kH - 1);
    // Forces both halves to redraw on this pass.
    g_status[0] = '\0';
    g_seq = 0xFFFFFFFFu;
    g_viewDrawn = false;
    g_lastStatusMs = nowMs - kStatusRefreshMs;
    g_lastCaptionMs = nowMs - kCaptionCheckMs;
  }

  if (viewing()) {
    driveCamera(nowMs);
    speaker::NowPlaying np;
    speaker::nowPlaying(np);
    const bool speechChanged = np.seq != g_seq || np.item != g_item || np.active != g_active;
    if (speechChanged) {
      if (np.seq != g_seq || np.item != g_item) g_itemSinceMs = nowMs;
      if (g_active && !np.active) g_spokeUntilMs = nowMs + LCD_CAPTION_HOLD_MS;
      g_seq = np.seq;
      g_item = np.item;
      g_active = np.active;
    }
    const bool newFrame = camera::frameSeq() != g_viewSeq && nowMs - g_lastViewMs >= LCD_VIEW_FRAME_MS;
    const bool captionExpired = g_viewHadCaption && !np.active && (int32_t)(g_spokeUntilMs - nowMs) <= 0;
    const bool pageTurn = np.active && g_pages > 1 && ((nowMs - g_itemSinceMs) / kPageMs) % g_pages != g_page;
    if (!g_viewDrawn || newFrame || speechChanged || captionExpired || pageTurn) {
      g_viewSeq = camera::frameSeq();
      drawView(np, nowMs);
    }
  } else if (nowMs - g_lastCaptionMs >= kCaptionCheckMs) {
    g_lastCaptionMs = nowMs;
    speaker::NowPlaying np;
    speaker::nowPlaying(np);
    const bool changed = np.seq != g_seq || np.item != g_item || np.active != g_active;
    if (changed) {
      if (np.seq != g_seq || np.item != g_item) g_itemSinceMs = nowMs;
      g_seq = np.seq;
      g_item = np.item;
      g_active = np.active;
      if (np.seq != 0) drawCaptions(np, nowMs);
    } else if (np.active && g_pages > 1) {
      // Re-draw only when a long caption turns its page.
      if (((nowMs - g_itemSinceMs) / kPageMs) % g_pages != g_page) drawCaptions(np, nowMs);
    }
  }

  if (nowMs - g_lastStatusMs >= kStatusRefreshMs) {
    g_lastStatusMs = nowMs;
    char s[sizeof(g_status)];
    buildStatus(s, sizeof(s), nowMs);
    if (strcmp(s, g_status) != 0) {
      strcpy(g_status, s);
      drawStatus();
    }
  }
}

}  // namespace display
