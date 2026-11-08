# Build plan — 26 weeks, six phases

Twenty-five features were proposed. This plan ships eight of them properly and
names the three technical dependencies that decide whether the rest are
possible at all.

Assumes 2–3 people. Each phase ends at a gate that someone other than the
author verifies. If a gate does not pass, the phase is not finished and the
next one does not start — features built on an unstable spine cost more to fix
later than to delay now.

---

## Phase 0 · Weeks 1–2 · Foundations and three spikes

- Repo, module skeleton, CI with the dependency-direction check
- Freeze the BLE contract (`docs/gatt.md`) as a shared C header and Kotlin codec
- **Spike A** — record 20 real Bangla commands from three speakers; measure word
  error rate online and offline
- **Spike B** — photograph five Bangla newspaper pages through Cloud Vision;
  measure character error rate and **cost per page**
- **Spike C** — one ESP32-S3 and one VL53L1X streaming to a throwaway app
- Order hardware, in duplicate. Lead times here will surprise you

**Gate:** three spike results written into the README as numbers. If Spike B's
cost per page is unacceptable, the reader is redesigned now, not in week 16.

---

## Phase 1 · Weeks 3–6 · The spine

- `OutputArbiter` with the full P0–P4 ladder, preemption, TTL, sentence-boundary
  resume
- Foreground service, audio focus and ducking, Bluetooth headset routing
- Intent router with bilingual synonym tables; wake word at low duty cycle
- Earcons — short non-speech tones for listening / thinking / error / arrived
- Voice-driven settings, so speech rate and language change without sight
- Latency instrumentation into the local event log

**Gate:** a team member with the screen physically taped over changes the speech
rate, switches to Bangla, asks the time, interrupts a long utterance, and
recovers from an induced TTS failure. Latency assertions pass in CI.

---

## Phase 2 · Weeks 7–10 · The hardware loop

- Firmware: 3× VL53L1X at 10 Hz, IMU at 50 Hz, packed frames, deep-sleep duty
  cycling
- BLE link surviving Doze, airplane-mode toggles and walking out of range
- Obstacle policy: distance bands, hysteresis, minimum re-announce interval
- Haptic driver and the eight-pattern vocabulary
- Battery reporting and low-battery escalation

**Gate:** ten minutes down a crowded corridor and a pavement with **zero** false
hazard alarms, and every real obstacle announced before contact. Record both
numbers; they become the regression baseline.

---

## Phase 3 · Weeks 11–15 · Navigation

- Pedestrian routing, maneuver stream, off-route detection and re-route
- Bilingual instruction templates, in the units people actually use
- Saved places by voice, stored locally
- Pre-turn warning, arrival, and GPS-accuracy honesty ("my position is uncertain
  here")
- Interleaving with Phase 2: a hazard must cut a turn instruction correctly

**Gate:** a one-kilometre outdoor route completed by a blindfolded tester with a
sighted spotter, no instruction late enough to miss a turn.

---

## Phase 4 · Weeks 16–20 · Reading

- **Capture assistance** — the hardest part. Guide framing by voice: "move the
  phone higher", "hold steady", "I can see the whole page"
- Latin OCR on device; Bangla OCR to cloud with an offline capture queue
- Reading controls at P4 with correct resume
- Library with resume position, bookmarks, PDF/EPUB/TXT import
- Reading-order heuristics for multi-column newspaper layouts

**Gate:** a blind tester, unassisted, photographs and hears a full Bangla
newspaper column end to end — including recovering from one deliberately bad
first capture.

---

## Phase 5 · Weeks 21–24 · Vision, SOS and safety

- Scene description, object classes ordered by **proximity**, not confidence
- SOS: hardware button and voice → countdown → SMS with coordinates → call
- Fall detection: free-fall < 0.4 g for > 100 ms → impact > 2.5 g → 8 s
  stillness → spoken challenge → 30 s cancellable countdown
- Location sharing to a named contact
- Safety-language audit across every string resource

**Gate:** fifty simulated falls (dropped-on-cushion and sit-down-hard) with a
documented true-positive and false-positive count. SOS delivers a correct
location from a cold start in under 20 seconds.

---

## Phase 6 · Weeks 25–26 · Field trial

- Five blind users, one week each, real routes, structured debrief
- Battery tuning against the duty cycle actually observed in the logs
- Crash-free rate, ANR elimination, cold-start time
- Play Store listing with a genuinely accessible first-run flow

**Gate:** all five users complete their own routine route unassisted at least
once.

---

## Non-negotiable

Blind users test from **week 6**, not week 25. Recruit three to five people
through a school for the blind or a local disability organisation before Phase 1
ends. Every assumption in this repository about what is helpful is a sighted
guess until they correct it — and they will correct several.

---

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Phone battery dies by 3pm | **Critical** | Camera off unless invoked; ToF 10 Hz walking / 1 Hz stationary; GPS 1 Hz only in nav mode. Measure from week 3. |
| False hazard alarms | **Critical** | Hysteresis, minimum re-announce interval, multi-frame confirmation. Track per hour from week 7. Users abandon devices that cry wolf, permanently. |
| Bangla OCR cost or latency | **Critical** | Settled by Spike B in week 1. Fallback: on-device Latin plus a curated Bangla library rather than live camera reading. |
| BLE silent disconnects | High | 2 s watchdog on the notify stream; degradation announced aloud. |
| Liability from crossing advice | High | The app never says "it is safe to cross". CI lint over `strings.xml`. |
| Wake-word false accepts | High | Tune on real street and household audio, not a quiet lab. Target < 1/day. Physical button stays the primary path. |
| Hardware lead times | High | Order everything in week 1, in duplicate. |
| Face recognition privacy | Deferred | Out of v1. On return: on-device embeddings, explicit enrolment, never uploaded. |

---

## Definition of done

A feature is finished when it works screen-off and one-handed; works in Bangla
and English; degrades *explicitly* offline rather than failing silently; speaks
through the arbiter at a declared priority; announces its own failure in plain
language; survives an hour backgrounded; and has been used by a blind tester who
was not shown how.

## Metrics, on the dashboard from week 3

Time to first word (p50, p95) · false hazard alarms per hour of walking · missed
obstacles per hundred encounters · wake-word false accepts per day · Bangla OCR
character error rate on a fixed 20-page set · phone and wearable battery at 8
hours of mixed use · BLE uptime as a percentage of session duration.

---

## Deliberately not in v1

Indoor navigation (needs a beacon deployment you do not control) · face
recognition · traffic-light and crossing advice (the failure mode is someone
stepping into traffic) · caregiver portal (a second product) · book Q&A over an
LLM (cheap to add *after* the reader works — v1.5) · currency recognition
(well-bounded, but needs a BDT note dataset across wear, lighting and folds —
v1.5, start collecting now) · medicine identification (read the label, never
infer a dose).
