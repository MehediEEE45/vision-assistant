#include <Arduino.h>

#include "audio_i2s.h"
#include "config.h"

namespace {

constexpr size_t kHalfFrames = AUDIO_FRAMES_PER_HALF;
constexpr size_t kWordsPerHalf = kHalfFrames * 2;  // stereo slots
constexpr size_t kWordsTotal = kWordsPerHalf * 2;  // two halves

static_assert((kWordsPerHalf * sizeof(int32_t)) % 32 == 0,
              "each DMA half must be whole cache lines for maintenance to be exact");

// AXI SRAM, where the linker puts .bss on this board. DMA1 can reach it; it
// cannot reach DTCM. The D-cache is on (the Arduino core enables it), so every
// half is invalidated before reading and cleaned after writing.
alignas(32) int32_t g_rx[kWordsTotal];
alignas(32) int32_t g_tx[kWordsTotal];

I2S_HandleTypeDef g_i2s;
DMA_HandleTypeDef g_dmaRx;
DMA_HandleTypeDef g_dmaTx;

volatile bool g_running = false;
volatile bool g_muted = false;
volatile uint32_t g_errors = 0;
// The ring is filled only while someone reads it (keyword listening, the
// dataset stream). Otherwise it would sit full and count every sample as
// dropped.
volatile bool g_capture = false;

// Power-of-two ring so wrap is a mask. One second of history at 16 kHz.
constexpr uint32_t kRingSize = 16384;
int16_t g_ring[kRingSize];
volatile uint32_t g_head = 0;  // written only by the interrupt
volatile uint32_t g_tail = 0;  // written only by the consumer
volatile uint32_t g_dropped = 0;
volatile int32_t g_peak = 0;

// First-order DC blocker. The INMP441 output carries a small offset that
// would otherwise bias level checks and the keyword model's input.
float g_dcPrevIn = 0.0f;
float g_dcPrevOut = 0.0f;

int16_t g_render[kHalfFrames];

inline int16_t clamp16(int32_t v)
{
  if (v > 32767) return 32767;
  if (v < -32768) return -32768;
  return (int16_t)v;
}

void processHalf(size_t half)
{
  int32_t *rx = &g_rx[half * kWordsPerHalf];
  int32_t *tx = &g_tx[half * kWordsPerHalf];

  SCB_InvalidateDCache_by_Addr((uint32_t *)rx, kWordsPerHalf * sizeof(int32_t));

  int32_t peak = g_peak;
  uint32_t head = g_head;
  const uint32_t tail = g_tail;
  const bool capture = g_capture;
  for (size_t i = 0; i < kHalfFrames; ++i) {
    // 24-bit sample, MSB-aligned in a 32-bit slot; the low byte is the
    // microphone's tri-stated tail and is discarded.
    const int32_t s24 = rx[2 * i + MIC_SLOT] >> 8;
    const float x = (float)(s24 >> (8 - MIC_GAIN_SHIFT));
    const float y = x - g_dcPrevIn + 0.995f * g_dcPrevOut;
    g_dcPrevIn = x;
    g_dcPrevOut = y;
    const int16_t s = clamp16((int32_t)y);

    const int32_t a = s < 0 ? -(int32_t)s : s;
    if (a > peak) peak = a;

    if (!capture) continue;
    if (head - tail < kRingSize) {
      g_ring[head & (kRingSize - 1)] = s;
      ++head;
    } else {
      ++g_dropped;
    }
  }
  __DMB();
  g_head = head;
  g_peak = peak;

  speaker_render(g_render, kHalfFrames);
  const bool muted = g_muted;
  for (size_t i = 0; i < kHalfFrames; ++i) {
    const int32_t w = muted ? 0 : ((int32_t)g_render[i] << 16);
    tx[2 * i] = w;
    tx[2 * i + 1] = w;
  }
  SCB_CleanDCache_by_Addr((uint32_t *)tx, kWordsPerHalf * sizeof(int32_t));
}

bool initDma(DMA_HandleTypeDef &h, DMA_Stream_TypeDef *stream, uint32_t request, uint32_t direction)
{
  h.Instance = stream;
  h.Init.Request = request;
  h.Init.Direction = direction;
  h.Init.PeriphInc = DMA_PINC_DISABLE;
  h.Init.MemInc = DMA_MINC_ENABLE;
  h.Init.PeriphDataAlignment = DMA_PDATAALIGN_WORD;
  h.Init.MemDataAlignment = DMA_MDATAALIGN_WORD;
  h.Init.Mode = DMA_CIRCULAR;
  h.Init.Priority = DMA_PRIORITY_HIGH;
  h.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
  return HAL_DMA_Init(&h) == HAL_OK;
}

}  // namespace

extern "C" void DMA1_Stream0_IRQHandler(void) { HAL_DMA_IRQHandler(&g_dmaRx); }
extern "C" void DMA1_Stream1_IRQHandler(void) { HAL_DMA_IRQHandler(&g_dmaTx); }

// Both callbacks come from the receive stream. Transmit runs a FIFO's depth
// ahead of receive, so when receive finishes a half, transmit has already
// moved past the same half of its own buffer and it is free to refill.
extern "C" void HAL_I2SEx_TxRxHalfCpltCallback(I2S_HandleTypeDef *) { processHalf(0); }
extern "C" void HAL_I2SEx_TxRxCpltCallback(I2S_HandleTypeDef *) { processHalf(1); }

extern "C" void HAL_I2S_ErrorCallback(I2S_HandleTypeDef *) { ++g_errors; }

namespace audio {

bool begin()
{
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_SPI2_CLK_ENABLE();
  __HAL_RCC_DMA1_CLK_ENABLE();

  GPIO_InitTypeDef gpio = {};
  gpio.Pin = GPIO_PIN_12 | GPIO_PIN_13 | GPIO_PIN_14 | GPIO_PIN_15;  // see board_pins.h
  gpio.Mode = GPIO_MODE_AF_PP;
  gpio.Pull = GPIO_NOPULL;
  gpio.Speed = GPIO_SPEED_FREQ_MEDIUM;
  gpio.Alternate = GPIO_AF5_SPI2;
  HAL_GPIO_Init(GPIOB, &gpio);

  if (!initDma(g_dmaRx, DMA1_Stream0, DMA_REQUEST_SPI2_RX, DMA_PERIPH_TO_MEMORY)) return false;
  if (!initDma(g_dmaTx, DMA1_Stream1, DMA_REQUEST_SPI2_TX, DMA_MEMORY_TO_PERIPH)) return false;
  __HAL_LINKDMA(&g_i2s, hdmarx, g_dmaRx);
  __HAL_LINKDMA(&g_i2s, hdmatx, g_dmaTx);

  HAL_NVIC_SetPriority(DMA1_Stream0_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream0_IRQn);
  HAL_NVIC_SetPriority(DMA1_Stream1_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream1_IRQn);

  g_i2s.Instance = SPI2;
  g_i2s.Init.Mode = I2S_MODE_MASTER_FULLDUPLEX;
  g_i2s.Init.Standard = I2S_STANDARD_PHILIPS;
  // 32-bit slots give the 64 clocks per frame the INMP441 requires; the
  // MAX98357A accepts the same framing.
  g_i2s.Init.DataFormat = I2S_DATAFORMAT_32B;
  g_i2s.Init.MCLKOutput = I2S_MCLKOUTPUT_DISABLE;
  g_i2s.Init.AudioFreq = AUDIO_SAMPLE_RATE;
  g_i2s.Init.CPOL = I2S_CPOL_LOW;
  g_i2s.Init.FirstBit = I2S_FIRSTBIT_MSB;
  g_i2s.Init.WSInversion = I2S_WS_INVERSION_DISABLE;
  g_i2s.Init.Data24BitAlignment = I2S_DATA_24BIT_ALIGNMENT_RIGHT;
  // Keeps clock and word-select driven between transfers, so the amplifier
  // never sees a floating clock and pops.
  g_i2s.Init.MasterKeepIOState = I2S_MASTER_KEEP_IO_STATE_ENABLE;
  if (HAL_I2S_Init(&g_i2s) != HAL_OK) return false;

  memset(g_tx, 0, sizeof(g_tx));
  SCB_CleanDCache_by_Addr((uint32_t *)g_tx, sizeof(g_tx));

  // Size is in DMA items, which are 32-bit words here.
  if (HAL_I2SEx_TransmitReceive_DMA(&g_i2s, (const uint16_t *)g_tx, (uint16_t *)g_rx,
                                    (uint16_t)kWordsTotal) != HAL_OK) {
    return false;
  }
  g_running = true;
  return true;
}

bool running() { return g_running; }
uint32_t errorCount() { return g_errors; }

size_t micAvailable()
{
  return (size_t)(g_head - g_tail);
}

size_t micRead(int16_t *dst, size_t maxSamples)
{
  const uint32_t head = g_head;
  __DMB();
  uint32_t tail = g_tail;
  size_t n = 0;
  while (tail != head && n < maxSamples) {
    dst[n++] = g_ring[tail & (kRingSize - 1)];
    ++tail;
  }
  g_tail = tail;
  return n;
}

void micFlush()
{
  g_tail = g_head;
}

void setMicCapture(bool on)
{
  if (on) {
    g_tail = g_head;
    g_dropped = 0;
  }
  g_capture = on;
}

uint32_t micDropped() { return g_dropped; }

int32_t micTakePeak()
{
  noInterrupts();
  const int32_t p = g_peak;
  g_peak = 0;
  interrupts();
  return p;
}

void setOutputMuted(bool muted) { g_muted = muted; }

}  // namespace audio
