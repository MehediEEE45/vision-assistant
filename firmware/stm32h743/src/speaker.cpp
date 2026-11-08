#include <Arduino.h>
#include <math.h>

#include "audio_i2s.h"
#include "config.h"
#include "prompt_data.h"
#include "speaker.h"

namespace speaker {

namespace {

enum Kind : uint8_t { KIND_PROMPT = kItemPrompt, KIND_TONE = kItemTone, KIND_PAUSE = kItemPause };

constexpr int32_t kSamplesPerMs = AUDIO_SAMPLE_RATE / 1000;
// 4 ms. Cutting a word off at full amplitude clicks loudly through a small
// speaker; a click on top of a hazard warning reads as a second alarm.
constexpr int32_t kFadeSamples = 64;
constexpr int32_t kAttackSamples = 32;
constexpr int32_t kToneEnvelopeSamples = 80;

// Standard IMA ADPCM tables; tools/make_prompts.py encodes with the same ones.
const int16_t kStep[89] = {
    7,     8,     9,     10,    11,    12,    13,    14,    16,    17,    19,    21,    23,
    25,    28,    31,    34,    37,    41,    45,    50,    55,    60,    66,    73,    80,
    88,    97,    107,   118,   130,   143,   157,   173,   190,   209,   230,   253,   279,
    307,   337,   371,   408,   449,   494,   544,   598,   658,   724,   796,   876,   963,
    1060,  1166,  1282,  1411,  1552,  1707,  1878,  2066,  2272,  2499,  2749,  3024,  3327,
    3660,  4026,  4428,  4871,  5358,  5894,  6484,  7132,  7845,  8630,  9493,  10442, 11487,
    12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767};
const int8_t kIndexAdjust[8] = {-1, -1, -1, -1, 2, 4, 6, 8};

struct ToneSpec {
  uint16_t f0;
  uint16_t f1;  // sweep target; for the alarm, the second tone
  uint16_t ms;
  uint16_t gapMs;
  uint8_t repeats;  // 0 = until stopped
  uint8_t levelPercent;
};

const ToneSpec kTones[TONE_COUNT] = {
    /* WARN   */ {1400, 1400, 70, 50, 2, 70},
    /* LISTEN */ {600, 1000, 120, 0, 1, 50},
    /* OK     */ {880, 880, 80, 0, 1, 45},
    /* ERROR  */ {330, 260, 250, 0, 1, 60},
    /* BOOT   */ {520, 1040, 300, 0, 1, 45},
    /* ALARM  */ {900, 1400, 400, 0, 0, 100},
};

int16_t g_sine[256];

// Shared between the main loop and the audio interrupt.
constexpr uint8_t kQueueSize = 4;
Utterance g_queue[kQueueSize];
volatile uint8_t g_qHead = 0;
volatile uint8_t g_qTail = 0;
volatile bool g_stopRequest = false;
volatile bool g_bangla = DEFAULT_LANGUAGE_BANGLA != 0;
volatile int32_t g_volumeQ15 = (SPEAKER_VOLUME_PERCENT * 32767) / 100;
volatile bool g_busy = false;
uint8_t g_volumePercent = SPEAKER_VOLUME_PERCENT;

// Main loop only.
Utterance g_last;
bool g_haveLast = false;

// Audio interrupt only, except the two read by nowPlaying() under a
// critical section.
volatile uint32_t g_playSeq = 0;
bool g_active = false;
Utterance g_cur;
uint8_t g_itemIndex = 0;
Utterance g_incoming;
bool g_haveIncoming = false;
Utterance g_pending[4];
bool g_havePending[4] = {};
int32_t g_fade = 0;
bool g_fadeToSilence = false;
int32_t g_attack = 0;

bool g_itemActive = false;
uint8_t g_itemKind = KIND_PAUSE;
const uint8_t *g_adpcm = nullptr;
uint32_t g_samplesLeft = 0;
bool g_highNibble = false;
int32_t g_pred = 0;
int32_t g_index = 0;

const ToneSpec *g_tone = nullptr;
int32_t g_toneIndex = 0;
int32_t g_toneLength = 0;
int32_t g_gapLeft = 0;
uint8_t g_repeatsLeft = 0;
uint8_t g_segment = 0;
uint32_t g_phase = 0;

int32_t g_pauseLeft = 0;

const PromptClip &clipFor(uint16_t id)
{
  if (g_bangla && kPromptsBn[id].data != nullptr) return kPromptsBn[id];
  return kPromptsEn[id];
}

void startToneSegment()
{
  g_toneIndex = 0;
  g_toneLength = (int32_t)g_tone->ms * kSamplesPerMs;
  g_gapLeft = (int32_t)g_tone->gapMs * kSamplesPerMs;
}

bool startNextItem()
{
  while (g_itemIndex < g_cur.count) {
    const Item item = g_cur.items[g_itemIndex++];
    g_itemKind = item.kind;
    switch (item.kind) {
      case KIND_PROMPT: {
        if (item.value >= PROMPT_COUNT) continue;
        const PromptClip &clip = clipFor(item.value);
        if (clip.data == nullptr || clip.samples == 0) continue;
        g_adpcm = clip.data;
        g_samplesLeft = clip.samples;
        g_highNibble = false;
        g_pred = 0;
        g_index = 0;
        g_itemActive = true;
        return true;
      }
      case KIND_TONE:
        if (item.value >= TONE_COUNT) continue;
        g_tone = &kTones[item.value];
        g_repeatsLeft = g_tone->repeats;
        g_segment = 0;
        g_phase = 0;
        startToneSegment();
        g_itemActive = true;
        return true;
      case KIND_PAUSE:
        g_pauseLeft = (int32_t)item.value * kSamplesPerMs;
        g_itemActive = true;
        return true;
      default:
        continue;
    }
  }
  return false;
}

inline int32_t decodeNibble(uint8_t nib)
{
  const int32_t step = kStep[g_index];
  int32_t diff = step >> 3;
  if (nib & 4) diff += step;
  if (nib & 2) diff += step >> 1;
  if (nib & 1) diff += step >> 2;
  g_pred += (nib & 8) ? -diff : diff;
  if (g_pred > 32767) g_pred = 32767;
  else if (g_pred < -32768) g_pred = -32768;
  g_index += kIndexAdjust[nib & 7];
  if (g_index < 0) g_index = 0;
  else if (g_index > 88) g_index = 88;
  return g_pred;
}

int32_t toneSample()
{
  const float t = (float)g_toneIndex / (float)g_toneLength;
  float f;
  if (g_tone->repeats == 0) {
    f = g_segment ? g_tone->f1 : g_tone->f0;
  } else {
    f = g_tone->f0 + (g_tone->f1 - g_tone->f0) * t;
  }
  const uint32_t step = (uint32_t)(f * (4294967296.0f / (float)AUDIO_SAMPLE_RATE));
  const int32_t raw = g_sine[g_phase >> 24];
  g_phase += step;

  int32_t env = kToneEnvelopeSamples;
  if (g_toneIndex < env) env = g_toneIndex;
  if (g_toneLength - g_toneIndex < env) env = g_toneLength - g_toneIndex;
  ++g_toneIndex;
  return raw * g_tone->levelPercent / 100 * env / kToneEnvelopeSamples;
}

// False once the current item has produced its last sample.
bool itemSample(int32_t &s)
{
  switch (g_itemKind) {
    case KIND_PROMPT: {
      if (g_samplesLeft == 0) return false;
      const uint8_t byte = *g_adpcm;
      uint8_t nib;
      if (g_highNibble) {
        nib = byte >> 4;
        ++g_adpcm;
      } else {
        nib = byte & 0x0F;
      }
      g_highNibble = !g_highNibble;
      --g_samplesLeft;
      s = decodeNibble(nib);
      return true;
    }
    case KIND_TONE: {
      if (g_toneIndex < g_toneLength) {
        s = toneSample();
        return true;
      }
      if (g_gapLeft > 0) {
        --g_gapLeft;
        s = 0;
        return true;
      }
      if (g_tone->repeats == 0) {
        g_segment ^= 1;
      } else if (--g_repeatsLeft == 0) {
        return false;
      }
      startToneSegment();
      s = toneSample();
      return true;
    }
    case KIND_PAUSE:
      if (g_pauseLeft <= 0) return false;
      --g_pauseLeft;
      s = 0;
      return true;
    default:
      return false;
  }
}

void start(const Utterance &u)
{
  g_cur = u;
  g_itemIndex = 0;
  g_itemActive = false;
  g_active = true;
  g_attack = 0;
  ++g_playSeq;
}

bool startMostUrgentPending()
{
  for (uint8_t p = 0; p < 4; ++p) {
    if (g_havePending[p]) {
      g_havePending[p] = false;
      start(g_pending[p]);
      return true;
    }
  }
  return false;
}

void finishUtterance()
{
  g_active = false;
  startMostUrgentPending();
}

void pend(const Utterance &u)
{
  // Newest wins within a priority: by the time a queued note would play,
  // a newer one of the same kind is the only one still true.
  const uint8_t p = (uint8_t)u.priority;
  g_pending[p] = u;
  g_havePending[p] = true;
}

void offer(const Utterance &u)
{
  if (u.count == 0) return;

  if (g_fadeToSilence && g_active) {
    g_fadeToSilence = false;
    g_incoming = u;
    g_haveIncoming = true;
    return;
  }

  const Utterance *effective = g_haveIncoming ? &g_incoming : (g_active ? &g_cur : nullptr);
  if (effective == nullptr) {
    start(u);
    return;
  }

  const uint8_t up = (uint8_t)u.priority;
  const uint8_t ep = (uint8_t)effective->priority;
  const bool supersedes = up == ep && u.tag != 0 && u.tag == effective->tag;
  if (up < ep || supersedes) {
    if (g_haveIncoming && !supersedes) pend(g_incoming);
    g_incoming = u;
    g_haveIncoming = true;
    if (g_fade == 0) g_fade = kFadeSamples;
    return;
  }

  if (u.priority == Priority::Ambient) return;
  pend(u);
}

void onFadeDone()
{
  if (g_fadeToSilence) {
    g_fadeToSilence = false;
    g_active = false;
    return;
  }
  if (g_haveIncoming) {
    g_haveIncoming = false;
    start(g_incoming);
    return;
  }
  finishUtterance();
}

void handleStop()
{
  g_haveIncoming = false;
  for (uint8_t p = 0; p < 4; ++p) g_havePending[p] = false;
  if (g_active) {
    g_fadeToSilence = true;
    if (g_fade == 0) g_fade = kFadeSamples;
  }
}

int32_t nextSample()
{
  for (uint8_t guard = 0; guard < kMaxItems + 2; ++guard) {
    if (!g_itemActive && !startNextItem()) {
      finishUtterance();
      return 0;
    }
    int32_t s;
    if (itemSample(s)) return s;
    g_itemActive = false;
  }
  finishUtterance();
  return 0;
}

}  // namespace

Utterance::Utterance() : priority(Priority::Ambient), tag(0), count(0), items{} {}

Utterance::Utterance(Priority p, uint16_t t) : priority(p), tag(t), count(0), items{} {}

Utterance &Utterance::prompt(PromptId id)
{
  if (count < kMaxItems) items[count++] = Item{KIND_PROMPT, (uint16_t)id};
  return *this;
}

Utterance &Utterance::tone(Tone t)
{
  if (count < kMaxItems) items[count++] = Item{KIND_TONE, (uint16_t)t};
  return *this;
}

Utterance &Utterance::pause(uint16_t ms)
{
  if (count < kMaxItems) items[count++] = Item{KIND_PAUSE, ms};
  return *this;
}

void begin()
{
  for (int i = 0; i < 256; ++i) {
    g_sine[i] = (int16_t)(29000.0f * sinf(2.0f * (float)M_PI * (float)i / 256.0f));
  }
}

void say(const Utterance &u)
{
  if (u.count == 0) return;
  if (u.priority <= Priority::Answer) {
    for (uint8_t i = 0; i < u.count; ++i) {
      if (u.items[i].kind == KIND_PROMPT) {
        g_last = u;
        g_haveLast = true;
        break;
      }
    }
  }

  noInterrupts();
  uint8_t next = (uint8_t)((g_qHead + 1) % kQueueSize);
  if (next == g_qTail) {
    if (u.priority != Priority::Hazard) {
      interrupts();
      return;
    }
    // A hazard never waits behind a full queue.
    g_qTail = g_qHead;
    next = (uint8_t)((g_qHead + 1) % kQueueSize);
  }
  g_queue[g_qHead] = u;
  g_qHead = next;
  interrupts();
}

void stopAll()
{
  noInterrupts();
  g_qTail = g_qHead;
  g_stopRequest = true;
  interrupts();
}

void repeatLast()
{
  if (!g_haveLast) return;
  Utterance u = g_last;
  u.priority = Priority::Answer;
  u.tag = 0;
  say(u);
}

bool busy() { return g_busy; }

void nowPlaying(NowPlaying &out)
{
  noInterrupts();
  out.seq = g_playSeq;
  out.active = g_active;
  out.item = g_itemIndex > 0 ? (uint8_t)(g_itemIndex - 1) : 0;
  out.utterance = g_cur;
  interrupts();
}

void setVolumePercent(uint8_t percent)
{
  if (percent > 100) percent = 100;
  g_volumePercent = percent;
  g_volumeQ15 = ((int32_t)percent * 32767) / 100;
}

uint8_t volumePercent() { return g_volumePercent; }

void setBangla(bool bangla) { g_bangla = bangla; }
bool bangla() { return g_bangla; }

bool hasBangla(PromptId id)
{
  return id < PROMPT_COUNT && kPromptsBn[id].data != nullptr;
}

uint16_t missingBanglaCount()
{
  uint16_t recorded = 0;
  for (uint16_t i = 0; i < PROMPT_COUNT; ++i) {
    if (kPromptsBn[i].data != nullptr) ++recorded;
  }
  return recorded >= kPromptsBnExpected ? 0 : (uint16_t)(kPromptsBnExpected - recorded);
}

bool anyBangla()
{
  for (uint16_t i = 0; i < PROMPT_COUNT; ++i) {
    if (kPromptsBn[i].data != nullptr) return true;
  }
  return false;
}

}  // namespace speaker

void speaker_render(int16_t *out, size_t n)
{
  using namespace speaker;
  if (g_stopRequest) {
    g_stopRequest = false;
    handleStop();
  }
  while (g_qTail != g_qHead) {
    offer(g_queue[g_qTail]);
    g_qTail = (uint8_t)((g_qTail + 1) % kQueueSize);
  }

  const int32_t volume = g_volumeQ15;
  for (size_t i = 0; i < n; ++i) {
    int32_t s = 0;
    if (g_active) {
      s = nextSample();
      if (g_fade > 0) {
        s = s * g_fade / kFadeSamples;
        if (--g_fade == 0) onFadeDone();
      } else if (g_attack < kAttackSamples) {
        s = s * (g_attack + 1) / kAttackSamples;
        ++g_attack;
      }
    }
    out[i] = (int16_t)((s * volume) >> 15);
  }

  bool pending = g_haveIncoming;
  for (uint8_t p = 0; p < 4; ++p) pending = pending || g_havePending[p];
  g_busy = g_active || pending;
}
