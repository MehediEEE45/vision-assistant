# Wearable BLE contract — v1

**Status: FROZEN.** Firmware and app are built in parallel by different people,
and the two halves drifting apart is the single largest schedule risk in this
project.

Three files describe the same bytes and change together, in one commit:

| | |
|---|---|
| `protocol/src/main/kotlin/bd/visionassistant/protocol/Frames.kt` | app side |
| `firmware/include/vision_gatt.h` | wearable side |
| this document | the agreement |

Changing any layout bumps `Gatt.PROTOCOL_VERSION` and
`VISION_PROTOCOL_VERSION`. The app refuses to pair with a wearable reporting a
different major version rather than silently misreading its sensors.

---

## Service and characteristics

Base UUID `7a9bXXXX-4c3d-4f21-9e85-1b6c2d0f8a37`.

| Characteristic | Short | Direction | Rate | Bytes |
|---|---|---|---|---|
| Service | `0001` | — | — | — |
| SensorFrame | `0002` | notify | 20 Hz | 16 |
| Event | `0003` | notify | on change | 4 |
| HapticCmd | `0004` | write, no response | on demand | 4 |
| DeviceState | `0005` | notify | 0.1 Hz | 6 |
| Config | `0006` | read / write | on demand | 8 |

All multi-byte fields are **little-endian**. Structures are packed, no padding.

---

## SensorFrame — 16 bytes

| Offset | Size | Field | Units |
|---:|---:|---|---|
| 0 | 2 | `seq` | u16, wraps at 65535 |
| 2 | 2 | `tof_left_mm` | u16, `0xFFFF` = no return |
| 4 | 2 | `tof_centre_mm` | u16 |
| 6 | 2 | `tof_head_mm` | u16, head-height sensor |
| 8 | 2 | `accel_milli_g` | u16, magnitude |
| 10 | 2 | `dt_ms` | u16, since previous frame |
| 12 | 1 | `pitch_deg` | i8 |
| 13 | 1 | `roll_deg` | i8 |
| 14 | 1 | `flags` | u8 |
| 15 | 1 | `crc8` | over bytes 0–14 |

Flags: `0x01` walking · `0x02` left valid · `0x04` centre valid · `0x08` head
valid · `0x10` IMU saturated · `0x20` button held · `0x40` low power.

### Why one fused frame and not one characteristic per sensor

Per-sensor notifications arrive interleaved. The phone would end up fusing a
left reading from one instant with a centre reading from another — which is
precisely how phantom obstacles are born. One frame guarantees the three range
readings and the IMU sample are time-coherent.

The bandwidth is not the constraint. At a 15 ms connection interval, 16-byte
notifications at 20 Hz leave enormous headroom; coherence is the reason.

`seq` sits first so the phone can count gaps cheaply. Dropped frames are a
dashboard metric — see `WearableLink.droppedFrameCount()`.

---

## Event — 4 bytes

`type:u8` · `arg:u16` · `crc8:u8`

| Value | Meaning |
|---|---|
| `0x01` | SOS button pressed |
| `0x02` | Fall candidate — the wearable only *suspects*; the phone confirms |
| `0x03` | Button, single press |
| `0x04` | Button, double press |
| `0x05` | Button, long press |
| `0x06` | Tamper |
| `0x07` | Sensor fault |

The SOS path is a notification, never a poll.

---

## HapticCmd — 4 bytes

`motor_mask:u8` · `pattern_id:u8` · `intensity:u8` · `repeat:u8`

No CRC. A corrupted buzz is harmless, and the round trip for an acknowledgement
would blow the 60 ms hazard haptic budget.

Motors: `0x01` left, `0x02` right, `0x03` both. `repeat = 0` means continuous
until silenced.

### The haptic vocabulary — eight patterns, and no more

| ID | Pattern | Motors | Feel |
|---|---|---|---|
| `0x01` | Obstacle left | left | two pulses |
| `0x02` | Obstacle right | right | two pulses |
| `0x03` | Obstacle ahead | both | sustained |
| `0x04` | Drop ahead | both | three hard pulses |
| `0x10` | Turn left | left | three short |
| `0x11` | Turn right | right | three short |
| `0x20` | Arrived | both | long–short–long |
| `0xFF` | Emergency | both | continuous |

Eight, deliberately. A user can learn eight buzzes and act on them without
thinking. Twenty they cannot — and a pattern that has to be decoded consciously
is slower than speech, which defeats the point of having it.

---

## DeviceState — 6 bytes

`battery_pct:u8` · `charging:u8` · `sensor_health:u16` · `fw_version:u16`

`sensor_health` is a fault bitfield, `0` meaning all well: `0x01` left range ·
`0x02` centre range · `0x04` head range · `0x08` IMU · `0x10` left motor ·
`0x20` right motor. Faults are spoken aloud, named.

---

## Config — 8 bytes

`tof_hz_walking` (10) · `tof_hz_stationary` (1) · `imu_hz` (50) ·
`haptic_gain` (200) · `fall_impact_milli_g` (2500, u16) ·
`fall_freefall_milli_g` (400, u16)

Battery is the top hardware risk. The phone turns the range sensors down to
`tof_hz_stationary` whenever the IMU reports the user is standing still.

---

## The watchdog

A BLE connection can stay nominally *connected* while notifications silently
stop — a firmware hang, a wedged sensor, a stack bug. The user keeps walking,
trusting a device that stopped looking.

So: if no SensorFrame arrives within **2000 ms**, `WearableLink.status` drops to
`DEGRADED` and the app says so out loud, at hazard priority.

Silent failure of a safety sensor is the worst behaviour this system can have.

---

## CRC-8

Dallas/Maxim — polynomial `0x31`, reflected `0x8C`, init `0x00`.

Cross-check vectors, asserted in `Crc8Test` and reproducible with
`vision_crc8()` on the ESP32:

| Input | CRC |
|---|---|
| `""` | `0x00` |
| `0x01` | `0x5E` |
| `"123456789"` | `0xA1` |

Run these on both sides during bring-up. They are the cheapest possible guard
against a polynomial or endianness mismatch — the kind you otherwise discover
three weeks in, after a fortnight of blaming the radio.
