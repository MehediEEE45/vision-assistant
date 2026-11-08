#include <Arduino.h>
#include <math.h>
#include <string.h>

#include "config.h"
#include "vision.h"

#if defined(VISION_EI_HEADER)
#include VISION_EI_HEADER
#define VISION_HAVE_MODEL 1
#else
#define VISION_HAVE_MODEL 0
#endif

namespace vision {

namespace {

struct ObjectInfo {
  const char *label;
  PromptId prompt;
};

const ObjectInfo kObjects[OBJ_COUNT] = {
    {"person", PROMPT_OBJ_PERSON}, {"chair", PROMPT_OBJ_CHAIR},   {"door", PROMPT_OBJ_DOOR},
    {"table", PROMPT_OBJ_TABLE},   {"bottle", PROMPT_OBJ_BOTTLE}, {"toilet", PROMPT_OBJ_TOILET},
    {"rickshaw", PROMPT_OBJ_RICKSHAW}, {"cng", PROMPT_OBJ_CNG},
};

#if VISION_HAVE_MODEL

#if EI_CLASSIFIER_OBJECT_DETECTION != 1
#error "the vision model must be an object detection (FOMO) model"
#endif

constexpr int kSrcW = CAMERA_WIDTH;
constexpr int kSrcH = CAMERA_HEIGHT;
constexpr int kDstW = EI_CLASSIFIER_INPUT_WIDTH;
constexpr int kDstH = EI_CLASSIFIER_INPUT_HEIGHT;

const uint16_t *g_frame = nullptr;

// Squash the whole 4:3 frame into the model's square input, averaging each
// source block. Squash, not crop: cropping would throw away the edges of the
// picture, which is where "left" and "right" live. Train with Edge Impulse's
// resize mode set to Squash so training and device see the same geometry.
int getData(size_t offset, size_t length, float *out)
{
  for (size_t n = 0; n < length; ++n) {
    const int i = (int)(offset + n);
    const int x = i % kDstW;
    const int y = i / kDstW;
    const int x0 = x * kSrcW / kDstW;
    int x1 = (x + 1) * kSrcW / kDstW;
    const int y0 = y * kSrcH / kDstH;
    int y1 = (y + 1) * kSrcH / kDstH;
    if (x1 <= x0) x1 = x0 + 1;
    if (y1 <= y0) y1 = y0 + 1;

    uint32_t r = 0, g = 0, b = 0, count = 0;
    for (int sy = y0; sy < y1; ++sy) {
      const uint16_t *row = g_frame + sy * kSrcW;
      for (int sx = x0; sx < x1; ++sx) {
        const uint16_t p = row[sx];
        const uint32_t r5 = (p >> 11) & 0x1F;
        const uint32_t g6 = (p >> 5) & 0x3F;
        const uint32_t b5 = p & 0x1F;
        r += (r5 << 3) | (r5 >> 2);
        g += (g6 << 2) | (g6 >> 4);
        b += (b5 << 3) | (b5 >> 2);
        ++count;
      }
    }
    // Edge Impulse image input: one float per pixel holding 0xRRGGBB.
    out[n] = (float)(((r / count) << 16) | ((g / count) << 8) | (b / count));
  }
  return 0;
}

#endif

}  // namespace

bool available() { return VISION_HAVE_MODEL != 0; }

const char *modelInfo()
{
#if VISION_HAVE_MODEL
  return EI_CLASSIFIER_PROJECT_NAME;
#else
  return "none";
#endif
}

const char *label(uint8_t object) { return object < OBJ_COUNT ? kObjects[object].label : "?"; }

PromptId prompt(uint8_t object)
{
  return object < OBJ_COUNT ? kObjects[object].prompt : PROMPT_NOT_UNDERSTOOD;
}

int fromLabel(const char *text)
{
  if (text == nullptr) return -1;
  size_t n = 0;
  while (text[n] != '\0' && text[n] != '_') ++n;
  if (n == 0) return -1;
  for (uint8_t i = 0; i < OBJ_COUNT; ++i) {
    if (strlen(kObjects[i].label) == n && strncmp(text, kObjects[i].label, n) == 0) return i;
  }
  return -1;
}

float angleDeg(float cx)
{
  const float halfFov = CAMERA_HFOV_DEG * 0.5f * (float)M_PI / 180.0f;
  return atanf((cx - 0.5f) * 2.0f * tanf(halfFov)) * 180.0f / (float)M_PI;
}

int detect(const uint16_t *frame, Detection *out, uint8_t max)
{
#if !VISION_HAVE_MODEL
  (void)frame;
  (void)out;
  (void)max;
  return -1;
#else
  g_frame = frame;
  signal_t signal;
  signal.total_length = (size_t)kDstW * kDstH;
  signal.get_data = &getData;
  ei_impulse_result_t result = {0};
  if (run_classifier(&signal, &result, false) != EI_IMPULSE_OK) return -1;

  int n = 0;
  for (uint32_t i = 0; i < result.bounding_boxes_count; ++i) {
    const ei_impulse_result_bounding_box_t &bb = result.bounding_boxes[i];
    if (bb.value < VISION_MIN_CONFIDENCE) continue;
    const int obj = fromLabel(bb.label);
    if (obj < 0) continue;
    const float cx = ((float)bb.x + (float)bb.width * 0.5f) / (float)kDstW;
    const float cy = ((float)bb.y + (float)bb.height * 0.5f) / (float)kDstH;

    // FOMO marks every grid cell an object covers, so one chair can arrive
    // as several neighbouring centroids. Keep one per object per place.
    bool merged = false;
    for (int k = 0; k < n; ++k) {
      if (out[k].object == obj && fabsf(out[k].cx - cx) < 0.15f && fabsf(out[k].cy - cy) < 0.15f) {
        if (bb.value > out[k].score) out[k] = Detection{(uint8_t)obj, bb.value, cx, cy};
        merged = true;
        break;
      }
    }
    if (!merged && n < max) out[n++] = Detection{(uint8_t)obj, bb.value, cx, cy};
  }

  for (int a = 1; a < n; ++a) {
    const Detection d = out[a];
    int b = a - 1;
    while (b >= 0 && out[b].score < d.score) {
      out[b + 1] = out[b];
      --b;
    }
    out[b + 1] = d;
  }
  return n;
#endif
}

}  // namespace vision
