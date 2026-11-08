#include <Arduino.h>
#include <Wire.h>

#include "board_pins.h"
#include "camera.h"
#include "config.h"
#include "ov5640.h"
#include "ov7725_regs.h"

namespace camera {

namespace {

enum class Chip { None, Ov5640, Ov7725 };

constexpr uint8_t kSccbAddress = 0x3C;  // 7-bit; ST's code writes it as 0x78
// OV7725/OV7670 family: measured on this board (the `i2c` console command
// answers 0x21, not 0x3C) -- a cheaper DVP module than the OV5640 the rest of
// this file was first written against, with its own 8-bit-register SCCB.
constexpr uint8_t kOv7725Address = 0x21;
constexpr uint32_t kPixels = (uint32_t)CAMERA_WIDTH * CAMERA_HEIGHT;
constexpr uint32_t kFrameBytes = kPixels * 2;
static_assert(CAMERA_WIDTH == 320 && CAMERA_HEIGHT == 240, "only the sensor's 320x240 mode is wired up");
static_assert(kFrameBytes % 32 == 0, "the frame must be whole cache lines for invalidation to be exact");
static_assert(kFrameBytes / 4 <= 0xFFFF, "one frame must fit a single DMA transfer");

// A 320x240 frame takes well under 100 ms even at the slowest pixel clock.
// Half a second without one means the sensor or the ribbon has failed.
constexpr uint32_t kCaptureTimeoutMs = 500;

// AXI SRAM, where .bss lives on this board: reachable by DMA2. The D-cache
// is on, so the frame is invalidated before the CPU reads it.
alignas(32) uint16_t g_frame[kPixels];

TwoWire g_sccb(PIN_CAM_SDA, PIN_CAM_SCL);
OV5640_Object_t g_ov;
DCMI_HandleTypeDef g_dcmi;
DMA_HandleTypeDef g_dma;

bool g_present = false;
Chip g_chip = Chip::None;
uint32_t g_id = 0;
// Counts completed frames, so the screen can show whichever frame the
// finder last took without taking one of its own.
uint32_t g_frameSeq = 0;
// What the probe saw, for the console: no answer at all points at the
// ribbon or power; an answer with the wrong ID points at a different sensor.
bool g_answered = false;
bool g_pwdnHighOn = false;
bool g_vsyncLow = false;  // which polarity detectVsyncPolarity() measured, for the console
// Shown on the LCD itself when the camera fails: nobody bringing this board
// up at a bench has a PC serial terminal open every time.
const char *g_lastError = "";
bool g_awake = false;
uint32_t g_awakeSinceMs = 0;
bool g_capturing = false;
uint32_t g_captureStartMs = 0;
volatile bool g_frameDone = false;
volatile bool g_frameError = false;
uint32_t g_errors = 0;

int32_t busInit()
{
  g_sccb.begin();
  g_sccb.setClock(100000);
  return OV5640_OK;
}

int32_t busDeInit() { return OV5640_OK; }

int32_t busWrite(uint16_t, uint16_t reg, uint8_t *data, uint16_t len)
{
  g_sccb.beginTransmission(kSccbAddress);
  g_sccb.write((uint8_t)(reg >> 8));
  g_sccb.write((uint8_t)(reg & 0xFF));
  for (uint16_t i = 0; i < len; ++i) g_sccb.write(data[i]);
  return g_sccb.endTransmission() == 0 ? OV5640_OK : OV5640_ERROR;
}

int32_t busRead(uint16_t, uint16_t reg, uint8_t *data, uint16_t len)
{
  g_sccb.beginTransmission(kSccbAddress);
  g_sccb.write((uint8_t)(reg >> 8));
  g_sccb.write((uint8_t)(reg & 0xFF));
  if (g_sccb.endTransmission(false) != 0) return OV5640_ERROR;
  if (g_sccb.requestFrom(kSccbAddress, (uint8_t)len) != len) return OV5640_ERROR;
  for (uint16_t i = 0; i < len; ++i) data[i] = (uint8_t)g_sccb.read();
  return OV5640_OK;
}

int32_t busTick() { return (int32_t)HAL_GetTick(); }

void startXclk()
{
  // PLL1Q is 48 MHz (clock_config.cpp); halved, it is the 24 MHz input
  // clock that ST's register tables for this sensor assume.
  HAL_RCC_MCOConfig(RCC_MCO1, RCC_MCO1SOURCE_PLL1QCLK, RCC_MCODIV_2);
}

bool probe(bool pwdnHigh)
{
  digitalWrite(PIN_CAM_PWDN, pwdnHigh ? HIGH : LOW);
  // OV5640 power-up: at least 20 ms from PWDN release before SCCB access.
  delay(30);
  uint32_t id = 0;
  if (OV5640_ReadID(&g_ov, &id) != OV5640_OK) return false;
  g_answered = true;
  g_id = id;
  return id == OV5640_ID;
}

// OV7725 uses plain 8-bit-register SCCB, not ST's OV5640 IO abstraction.
uint8_t ov7725Read(uint8_t reg)
{
  g_sccb.beginTransmission(kOv7725Address);
  g_sccb.write(reg);
  // SCCB wants a STOP before the read, not a repeated start.
  if (g_sccb.endTransmission(true) != 0) return 0xFF;
  if (g_sccb.requestFrom(kOv7725Address, (uint8_t)1) != 1) return 0xFF;
  return (uint8_t)g_sccb.read();
}

bool ov7725Write(uint8_t reg, uint8_t val)
{
  g_sccb.beginTransmission(kOv7725Address);
  g_sccb.write(reg);
  g_sccb.write(val);
  return g_sccb.endTransmission() == 0;
}

bool probeOv7725()
{
  // PID high byte: 0x77 = OV7725, 0x76 = OV7670 (same family; this table
  // targets OV7725, the WeAct-bundled module). A reply either way sets
  // g_answered so a mismatch is reported precisely rather than as silence.
  const uint8_t pidh = ov7725Read(0x0A);
  if (pidh == 0xFF) return false;
  g_answered = true;
  g_id = pidh;
  return pidh == 0x77;
}

bool initOv7725()
{
  if (!ov7725Write(0x12, 0x80)) return false;  // COM7: soft reset
  delay(10);
  for (const Reg8 *r = kOv7725Init; !(r->reg == kOv7725End && r->val == kOv7725End); ++r) {
    if (!ov7725Write(r->reg, r->val)) return false;
  }
  delay(300);  // let exposure and white balance settle
  return true;
}

void initPins()
{
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();
  __HAL_RCC_GPIOE_CLK_ENABLE();

  GPIO_InitTypeDef g = {};
  g.Mode = GPIO_MODE_AF_PP;
  g.Pull = GPIO_PULLUP;
  g.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  g.Alternate = GPIO_AF13_DCMI;
  g.Pin = GPIO_PIN_4 | GPIO_PIN_6;  // HSYNC, PIXCLK
  HAL_GPIO_Init(GPIOA, &g);
  g.Pin = GPIO_PIN_7;  // VSYNC
  HAL_GPIO_Init(GPIOB, &g);
  g.Pin = GPIO_PIN_6 | GPIO_PIN_7;  // D0, D1
  HAL_GPIO_Init(GPIOC, &g);
  g.Pin = GPIO_PIN_3;  // D5
  HAL_GPIO_Init(GPIOD, &g);
  g.Pin = GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_4 | GPIO_PIN_5 | GPIO_PIN_6;  // D2 D3 D4 D6 D7
  HAL_GPIO_Init(GPIOE, &g);
}

// The module's VSYNC wiring can come out inverted from ST's reference design
// (seen in practice on this same WeAct DVP connector): guessing wrong means
// DCMI never completes a frame and the screen is stuck on "camera starting"
// forever, with no error anywhere. Measure it instead, while the sensor is
// actually streaming. Returns DCMI_VSPOLARITY_* or 0xFFFFFFFF if VSYNC never
// toggled at all (ribbon or power problem, not a polarity one).
uint32_t detectVsyncPolarity()
{
  __HAL_RCC_GPIOB_CLK_ENABLE();
  GPIO_InitTypeDef g = {};
  g.Pin = GPIO_PIN_7;
  g.Mode = GPIO_MODE_INPUT;
  g.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOB, &g);

  uint32_t high = 0, low = 0, edges = 0;
  int last = -1;
  const uint32_t t0 = millis();
  while (millis() - t0 < 300) {
    const int v = (GPIOB->IDR & GPIO_PIN_7) ? 1 : 0;
    if (v) ++high; else ++low;
    if (last >= 0 && v != last) ++edges;
    last = v;
  }
  if (edges < 2) return 0xFFFFFFFFu;
  // VSYNC spends most of the frame in its "active video" level; DCMI wants
  // the blanking level, which is the less-common one.
  return high > low ? DCMI_VSPOLARITY_LOW : DCMI_VSPOLARITY_HIGH;
}

bool initDcmi(uint32_t vsPolarity)
{
  __HAL_RCC_DCMI_CLK_ENABLE();
  __HAL_RCC_DMA2_CLK_ENABLE();

  g_dma.Instance = DMA2_Stream3;
  g_dma.Init.Request = DMA_REQUEST_DCMI;
  g_dma.Init.Direction = DMA_PERIPH_TO_MEMORY;
  g_dma.Init.PeriphInc = DMA_PINC_DISABLE;
  g_dma.Init.MemInc = DMA_MINC_ENABLE;
  g_dma.Init.PeriphDataAlignment = DMA_PDATAALIGN_WORD;
  g_dma.Init.MemDataAlignment = DMA_MDATAALIGN_WORD;
  g_dma.Init.Mode = DMA_NORMAL;
  g_dma.Init.Priority = DMA_PRIORITY_HIGH;
  g_dma.Init.FIFOMode = DMA_FIFOMODE_ENABLE;
  g_dma.Init.FIFOThreshold = DMA_FIFO_THRESHOLD_FULL;
  g_dma.Init.MemBurst = DMA_MBURST_SINGLE;
  g_dma.Init.PeriphBurst = DMA_PBURST_SINGLE;
  if (HAL_DMA_Init(&g_dma) != HAL_OK) return false;
  __HAL_LINKDMA(&g_dcmi, DMA_Handle, g_dma);

  // HSPolarity measured LOW on this same WeAct DVP connector wiring (HSYNC
  // PA4) in an earlier bring-up; VSPolarity is measured fresh above because
  // it is the one that actually varies between individual camera modules.
  g_dcmi.Instance = DCMI;
  g_dcmi.Init.SynchroMode = DCMI_SYNCHRO_HARDWARE;
  g_dcmi.Init.PCKPolarity = DCMI_PCKPOLARITY_RISING;
  g_dcmi.Init.VSPolarity = vsPolarity;
  g_dcmi.Init.HSPolarity = DCMI_HSPOLARITY_LOW;
  g_dcmi.Init.CaptureRate = DCMI_CR_ALL_FRAME;
  g_dcmi.Init.ExtendedDataMode = DCMI_EXTEND_DATA_8B;
  g_dcmi.Init.JPEGMode = DCMI_JPEG_DISABLE;
  g_dcmi.Init.ByteSelectMode = DCMI_BSM_ALL;
  g_dcmi.Init.ByteSelectStart = DCMI_OEBS_ODD;
  g_dcmi.Init.LineSelectMode = DCMI_LSM_ALL;
  g_dcmi.Init.LineSelectStart = DCMI_OELS_ODD;
  if (HAL_DCMI_Init(&g_dcmi) != HAL_OK) return false;

  // Below the audio interrupt: a late frame costs nothing, a late audio
  // block is an audible gap.
  HAL_NVIC_SetPriority(DCMI_IRQn, 3, 0);
  HAL_NVIC_EnableIRQ(DCMI_IRQn);
  HAL_NVIC_SetPriority(DMA2_Stream3_IRQn, 3, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream3_IRQn);
  return true;
}

}  // namespace

bool begin()
{
#if !CAMERA_ENABLED
  return false;
#else
  pinMode(PIN_CAM_PWDN, OUTPUT);
  startXclk();

  OV5640_IO_t io = {};
  io.Init = busInit;
  io.DeInit = busDeInit;
  io.Address = kSccbAddress << 1;
  io.WriteReg = busWrite;
  io.ReadReg = busRead;
  io.GetTick = busTick;
  if (OV5640_RegisterBusIO(&g_ov, &io) != OV5640_OK) {
    g_lastError = "SCCB bus setup failed";
    return false;
  }

  // Most modules wire this pin to the sensor's PWDN (high = off). WeAct's
  // own module uses it as a supply enable (high = on). Try both; whichever
  // answers on SCCB is the one this module has. Tried at 0x3C (OV5640) first,
  // then 0x21 (OV7725/OV7670) -- cheaper DVP modules bundled with this same
  // board answer there instead, and a probe at the wrong address just times
  // out, it does not disturb the sensor that is actually there.
  if (probe(false)) {
    g_chip = Chip::Ov5640;
    g_pwdnHighOn = false;
  } else if (probe(true)) {
    g_chip = Chip::Ov5640;
    g_pwdnHighOn = true;
  } else if (probeOv7725()) {
    g_chip = Chip::Ov7725;
  } else {
    digitalWrite(PIN_CAM_PWDN, LOW);
    g_lastError = g_answered ? "wrong sensor on SCCB" : "no answer on SCCB: ribbon/power";
    return false;
  }

  if (g_chip == Chip::Ov5640) {
    if (OV5640_Init(&g_ov, OV5640_R320x240, OV5640_RGB565) != OV5640_OK) {
      g_lastError = "OV5640_Init failed";
      return false;
    }
    // 12 MHz keeps the pixel clock far below the 48 MHz limit that a 120 MHz
    // AHB allows (DCMI needs AHB >= 2.5 x PIXCLK), with plenty of frame rate.
    if (OV5640_SetPCLK(&g_ov, OV5640_PCLK_12M) != OV5640_OK) {
      g_lastError = "PCLK config failed";
      return false;
    }
    const uint32_t mirrorFlip = (CAMERA_MIRROR ? OV5640_MIRROR : 0u) | (CAMERA_FLIP ? OV5640_FLIP : 0u);
    if (OV5640_MirrorFlipConfig(&g_ov, mirrorFlip) != OV5640_OK) {
      g_lastError = "mirror/flip config failed";
      return false;
    }
  } else {
    if (!initOv7725()) {
      g_lastError = "OV7725 register init failed";
      return false;
    }
    // CAMERA_MIRROR/CAMERA_FLIP are not wired up for this chip yet (COM3 in
    // kOv7725Init is fixed); fix orientation with CAMERA_MIRROR in software
    // if needed, same as the ToF mirroring, until that is added.
  }

  // VSYNC only toggles while the sensor is actually streaming, so measure it
  // with a brief, throwaway stream before settling into standby. The OV5640
  // has an explicit standby register (OV5640_Start/Stop); OV7725 here has
  // none wired up, so it is simply left running.
  if (g_chip == Chip::Ov5640) OV5640_Start(&g_ov);
  delay(50);
  const uint32_t vsPolarity = detectVsyncPolarity();
  if (g_chip == Chip::Ov5640) OV5640_Stop(&g_ov);
  if (vsPolarity == 0xFFFFFFFFu) {
    g_lastError = "VSYNC never toggled: ribbon/power";
    return false;
  }
  g_vsyncLow = vsPolarity == DCMI_VSPOLARITY_LOW;

  initPins();
  if (!initDcmi(vsPolarity)) {
    g_lastError = "DCMI/DMA init failed";
    return false;
  }

  // Streaming costs power the user gets nothing for; standby keeps the
  // registers, so waking is one write. Only the OV5640 has that register.
  if (g_chip == Chip::Ov5640) OV5640_Stop(&g_ov);
  g_present = true;
  return true;
#endif
}

bool present() { return g_present; }
bool answered() { return g_answered; }
uint32_t chipId() { return g_id; }
const char *chipName() { return g_chip == Chip::Ov5640 ? "OV5640" : g_chip == Chip::Ov7725 ? "OV7725" : "none"; }

void scanBus(Print &out)
{
  // Toggling the power pin would wipe a working sensor's registers.
  if (g_present) {
    out.print(F("camera bus: "));
    out.print(chipName());
    out.println(F(" in use, not rescanned"));
    return;
  }
  for (int level = 0; level < 2; ++level) {
    digitalWrite(PIN_CAM_PWDN, level ? HIGH : LOW);
    delay(30);
    out.print(level ? F("camera bus, PA7 high:") : F("camera bus, PA7 low: "));
    int found = 0;
    for (uint8_t a = 1; a < 127; ++a) {
      g_sccb.beginTransmission(a);
      if (g_sccb.endTransmission() == 0) {
        out.print(F(" 0x"));
        out.print(a, HEX);
        ++found;
      }
    }
    out.println(found ? F("") : F(" nothing"));
  }
  digitalWrite(PIN_CAM_PWDN, LOW);
}
bool pwdnHighMeansOn() { return g_pwdnHighOn; }
bool vsyncPolarityLow() { return g_vsyncLow; }
const char *lastError() { return g_lastError; }

void wake(uint32_t nowMs)
{
  if (!g_present || g_awake) return;
  // OV7725 has no standby wired up (see begin()): it is already running,
  // this just starts the warm-up clock so exposure/white-balance settle.
  if (g_chip == Chip::Ov5640) OV5640_Start(&g_ov);
  g_awake = true;
  g_awakeSinceMs = nowMs;
}

void sleep()
{
  if (!g_present || !g_awake) return;
  if (g_capturing) {
    HAL_DCMI_Stop(&g_dcmi);
    g_capturing = false;
  }
  if (g_chip == Chip::Ov5640) OV5640_Stop(&g_ov);
  g_awake = false;
}

bool awake() { return g_awake; }

bool warmedUp(uint32_t nowMs)
{
  return g_awake && nowMs - g_awakeSinceMs >= CAMERA_WARMUP_MS;
}

bool capture(uint32_t nowMs)
{
  if (!g_present || g_capturing || !warmedUp(nowMs)) return false;
  g_frameDone = false;
  g_frameError = false;
  if (HAL_DCMI_Start_DMA(&g_dcmi, DCMI_MODE_SNAPSHOT, (uint32_t)g_frame, kFrameBytes / 4) != HAL_OK) {
    ++g_errors;
    return false;
  }
  g_capturing = true;
  g_captureStartMs = nowMs;
  return true;
}

bool capturing() { return g_capturing; }

bool poll(uint32_t nowMs)
{
  if (!g_capturing) return false;
  if (g_frameDone) {
    g_capturing = false;
    HAL_DCMI_Stop(&g_dcmi);
    SCB_InvalidateDCache_by_Addr((uint32_t *)g_frame, (int32_t)kFrameBytes);
#if CAMERA_SWAP_BYTES
    uint32_t *w = (uint32_t *)g_frame;
    for (uint32_t i = 0; i < kFrameBytes / 4; ++i) w[i] = __REV16(w[i]);
#endif
    ++g_frameSeq;
    return true;
  }
  if (g_frameError || nowMs - g_captureStartMs > kCaptureTimeoutMs) {
    g_lastError = g_frameError ? "DCMI/DMA error mid-frame" : "capture timeout: no frame from DCMI";
    g_capturing = false;
    HAL_DCMI_Stop(&g_dcmi);
    ++g_errors;
  }
  return false;
}

const uint16_t *frame() { return g_frame; }
uint32_t frameSeq() { return g_frameSeq; }
uint32_t errorCount() { return g_errors; }

}  // namespace camera

extern "C" void DCMI_IRQHandler(void) { HAL_DCMI_IRQHandler(&camera::g_dcmi); }
extern "C" void DMA2_Stream3_IRQHandler(void) { HAL_DMA_IRQHandler(&camera::g_dma); }
extern "C" void HAL_DCMI_FrameEventCallback(DCMI_HandleTypeDef *) { camera::g_frameDone = true; }
extern "C" void HAL_DCMI_ErrorCallback(DCMI_HandleTypeDef *) { camera::g_frameError = true; }
