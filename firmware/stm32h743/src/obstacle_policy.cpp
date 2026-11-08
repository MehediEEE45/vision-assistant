#include "obstacle_policy.h"

#include "config.h"

namespace obstacle {

uint32_t Policy::reannounceMs(Band b)
{
  switch (b) {
    case Band::Immediate: return OBST_REANNOUNCE_IMMEDIATE_MS;
    case Band::Near: return OBST_REANNOUNCE_NEAR_MS;
    case Band::Approaching: return OBST_REANNOUNCE_APPROACHING_MS;
    default: return UINT32_MAX;
  }
}

Band Policy::bandFor(const ZoneState &z, uint16_t mm) const
{
  // Hysteresis: a band's upper edge widens only while the user is inside it,
  // so a reading hovering on an edge does not alert on every other frame.
  auto edge = [&](Band b, uint16_t base) -> uint32_t {
    return (uint32_t)base + (z.current == b ? OBST_HYSTERESIS_MM : 0);
  };
  if (mm <= edge(Band::Immediate, OBST_IMMEDIATE_MM)) return Band::Immediate;
  if (mm <= edge(Band::Near, OBST_NEAR_MM)) return Band::Near;
  if (mm <= edge(Band::Approaching, OBST_APPROACHING_MM)) return Band::Approaching;
  return Band::Clear;
}

bool Policy::onSample(const tof::Sample &s, Alert &out)
{
  if (s.zone >= tof::ZONE_COUNT) return false;
  ZoneState &z = zones_[s.zone];

  const Band band = s.valid ? bandFor(z, s.mm) : Band::Clear;
  if (band == Band::Clear) {
    z.current = Band::Clear;
    z.candidate = Band::Clear;
    z.frames = 0;
    return false;
  }

  if (z.candidate != band) {
    z.candidate = band;
    z.frames = 1;
    return false;
  }
  if (z.frames < 255) ++z.frames;
  if (z.frames < OBST_FRAMES_TO_CONFIRM) return false;

  const int32_t moved = (int32_t)s.mm - (int32_t)z.anchorMm;
  if (z.anchorMs == 0 || moved > OBST_STATIC_SCENE_MM || moved < -OBST_STATIC_SCENE_MM) {
    z.anchorMm = s.mm;
    z.anchorMs = s.atMs;
  }
  const bool standingStill = s.atMs - z.anchorMs >= OBST_STATIC_SCENE_MS;

  // Closing in deserves an immediate re-warning; holding steady does not.
  const bool escalating = (uint8_t)band < (uint8_t)z.current;
  const bool quietEnough = !z.announced || s.atMs - z.lastAnnouncedMs >= reannounceMs(band);
  if (!escalating && (!quietEnough || standingStill)) return false;

  // The zones overlap, so one obstacle can trip two of them a few frames
  // apart. The second is not news unless it is closer, and the user has
  // already been told about it, so its re-announce clock starts now too.
  if (anyAlert_ && s.atMs - lastAlertMs_ < OBST_CROSS_ZONE_MS &&
      (uint8_t)band >= (uint8_t)lastAlertBand_) {
    z.current = band;
    z.announced = true;
    z.lastAnnouncedMs = s.atMs;
    return false;
  }

  z.current = band;
  z.announced = true;
  z.lastAnnouncedMs = s.atMs;
  anyAlert_ = true;
  lastAlertMs_ = s.atMs;
  lastAlertBand_ = band;
  out = Alert{s.zone, band, s.mm};
  return true;
}

void Policy::reset()
{
  for (auto &z : zones_) z = ZoneState{};
  anyAlert_ = false;
  lastAlertBand_ = Band::Clear;
}

}  // namespace obstacle
