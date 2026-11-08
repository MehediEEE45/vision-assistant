#pragma once

#include <stdint.h>

#include "tof.h"

// C++ port of perception/obstacle-fusion/ObstaclePolicy.kt, with the same
// bands, confirmation, hysteresis and re-announce intervals. Keep the two in
// step: a user moving between the phone and the standalone wearable should
// not have to relearn what a warning means.
namespace obstacle {

enum class Band : uint8_t { Immediate = 0, Near = 1, Approaching = 2, Clear = 3 };

struct Alert {
  tof::Zone zone;
  Band band;
  uint16_t mm;
};

class Policy {
 public:
  // Returns true, filling `out`, only when the reading is worth the user's
  // attention. Everything else is silence.
  bool onSample(const tof::Sample &s, Alert &out);
  void reset();

 private:
  struct ZoneState {
    Band current = Band::Clear;
    Band candidate = Band::Clear;
    uint8_t frames = 0;
    bool announced = false;
    uint32_t lastAnnouncedMs = 0;
    uint16_t anchorMm = 0;
    uint32_t anchorMs = 0;
  };

  Band bandFor(const ZoneState &z, uint16_t mm) const;
  static uint32_t reannounceMs(Band b);

  ZoneState zones_[tof::ZONE_COUNT];
  uint32_t lastAlertMs_ = 0;
  Band lastAlertBand_ = Band::Clear;
  bool anyAlert_ = false;
};

}  // namespace obstacle
