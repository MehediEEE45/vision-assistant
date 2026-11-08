#pragma once

#include <stddef.h>
#include <stdint.h>

// One I2S bus, full duplex: INMP441 microphone in, MAX98357A amplifier out,
// 16 kHz mono both ways. DMA runs continuously from begin(); everything else
// is ring buffers and a render callback.
namespace audio {

bool begin();
bool running();
uint32_t errorCount();

// Microphone, filled from the DMA interrupt while capture is on. One
// consumer at a time; turning capture on empties the ring and the drop count.
void setMicCapture(bool on);
size_t micAvailable();
size_t micRead(int16_t *dst, size_t maxSamples);
void micFlush();
uint32_t micDropped();

// Peak absolute sample since the last call, for level checks.
int32_t micTakePeak();

// While muted the amplifier receives silence. Used while recording training
// data, so the device never hears its own voice prompts.
void setOutputMuted(bool muted);

}  // namespace audio

// Implemented by the speaker. Called from the DMA interrupt every 16 ms; must
// fill `n` samples and must not block.
void speaker_render(int16_t *out, size_t n);
