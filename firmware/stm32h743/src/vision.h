#pragma once

#include <stdint.h>

#include "prompt_ids.h"

// Object recognition on the camera frame: an Edge Impulse FOMO model,
// compiled in when VISION_EI_HEADER names its Arduino library (README).
//
// FOMO reports where an object's centre is, not its outline. That is exactly
// what guidance needs ("chair, left"), at a fraction of a box detector's cost.
namespace vision {

// The model's labels must be exactly these, lowercase. Keyword labels use
// the same words before an underscore (chair_bn, chair_en) so a spoken name
// and a recognised object meet in one table.
enum Object : uint8_t {
  OBJ_PERSON = 0,
  OBJ_CHAIR,
  OBJ_DOOR,
  OBJ_TABLE,
  OBJ_BOTTLE,
  OBJ_TOILET,
  OBJ_RICKSHAW,
  OBJ_CNG,
  OBJ_COUNT
};

struct Detection {
  uint8_t object;
  float score;
  float cx;  // 0 = left edge of the picture, 1 = right edge
  float cy;
};

constexpr uint8_t kMaxDetections = 8;

bool available();
const char *modelInfo();

const char *label(uint8_t object);
PromptId prompt(uint8_t object);
// Matches "chair", "chair_bn", "chair_en". -1 for anything else.
int fromLabel(const char *label);

// Degrees from straight ahead; negative is the wearer's left.
float angleDeg(float cx);

// Runs the model once on a camera frame; blocks for one inference. Returns
// the number of detections, strongest first, merged per object; -1 on error
// or with no model.
int detect(const uint16_t *frame, Detection *out, uint8_t max);

}  // namespace vision
