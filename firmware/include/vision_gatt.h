/*
 * vision_gatt.h - wearable side of the Vision Assistant BLE contract.
 *
 * FROZEN. This file and protocol/src/main/kotlin/.../Frames.kt describe the
 * same bytes. Firmware and app are built in parallel by different people, and
 * the two halves drifting apart is the single largest schedule risk in this
 * project.
 *
 * Changing any layout below is a breaking change:
 *   1. bump VISION_PROTOCOL_VERSION
 *   2. update Frames.kt and Gatt.kt to match
 *   3. update docs/gatt.md
 *   all in the same commit.
 *
 * Target: ESP32-S3, ESP-IDF. Little-endian, packed, no padding.
 */

#ifndef VISION_GATT_H
#define VISION_GATT_H

#include <stdint.h>
#include <stdbool.h>

#define VISION_PROTOCOL_VERSION 1

/* ------------------------------------------------------------------------- *
 * UUIDs - base 7a9bXXXX-4c3d-4f21-9e85-1b6c2d0f8a37
 * ------------------------------------------------------------------------- */

#define VISION_UUID_SERVICE       "7a9b0001-4c3d-4f21-9e85-1b6c2d0f8a37"
#define VISION_UUID_SENSOR_FRAME  "7a9b0002-4c3d-4f21-9e85-1b6c2d0f8a37"  /* notify  20 Hz */
#define VISION_UUID_EVENT         "7a9b0003-4c3d-4f21-9e85-1b6c2d0f8a37"  /* notify  on change */
#define VISION_UUID_HAPTIC_CMD    "7a9b0004-4c3d-4f21-9e85-1b6c2d0f8a37"  /* write, no response */
#define VISION_UUID_DEVICE_STATE  "7a9b0005-4c3d-4f21-9e85-1b6c2d0f8a37"  /* notify  0.1 Hz */
#define VISION_UUID_CONFIG        "7a9b0006-4c3d-4f21-9e85-1b6c2d0f8a37"  /* read / write */

#define VISION_SENSOR_HZ 20

/* ------------------------------------------------------------------------- *
 * SensorFrame - 16 bytes, notified at 20 Hz.
 *
 * One fused frame carrying all three ranges and the IMU sample together.
 * Deliberately NOT one characteristic per sensor: per-sensor notifications
 * arrive interleaved and the phone ends up fusing a left reading from one
 * instant with a centre reading from another, which is exactly how phantom
 * obstacles are born.
 * ------------------------------------------------------------------------- */

#define VISION_TOF_NO_RETURN 0xFFFFu

typedef struct __attribute__((packed)) {
    uint16_t seq;           /* wraps at 65535; phone counts gaps as dropped frames */
    uint16_t tof_left_mm;   /* VISION_TOF_NO_RETURN when out of range */
    uint16_t tof_centre_mm;
    uint16_t tof_head_mm;   /* head-height sensor */
    uint16_t accel_milli_g; /* magnitude */
    uint16_t dt_ms;         /* since previous frame */
    int8_t   pitch_deg;
    int8_t   roll_deg;
    uint8_t  flags;
    uint8_t  crc8;          /* over bytes 0..14 */
} vision_sensor_frame_t;

_Static_assert(sizeof(vision_sensor_frame_t) == 16, "SensorFrame must be 16 bytes");

#define VISION_FLAG_WALKING          (1u << 0)
#define VISION_FLAG_TOF_LEFT_VALID   (1u << 1)
#define VISION_FLAG_TOF_CENTRE_VALID (1u << 2)
#define VISION_FLAG_TOF_HEAD_VALID   (1u << 3)
#define VISION_FLAG_IMU_SATURATED    (1u << 4)
#define VISION_FLAG_BUTTON_HELD      (1u << 5)
#define VISION_FLAG_LOW_POWER        (1u << 6)

/* ------------------------------------------------------------------------- *
 * Event - 4 bytes, notified on change.
 * The SOS button path must never be polled.
 * ------------------------------------------------------------------------- */

typedef enum {
    VISION_EVT_SOS_PRESSED   = 0x01,
    VISION_EVT_FALL_CANDIDATE= 0x02,  /* phone confirms; wearable only suspects */
    VISION_EVT_BUTTON_SINGLE = 0x03,
    VISION_EVT_BUTTON_DOUBLE = 0x04,
    VISION_EVT_BUTTON_LONG   = 0x05,
    VISION_EVT_TAMPER        = 0x06,
    VISION_EVT_SENSOR_FAULT  = 0x07,
} vision_event_type_t;

typedef struct __attribute__((packed)) {
    uint8_t  type;
    uint16_t arg;
    uint8_t  crc8;
} vision_event_t;

_Static_assert(sizeof(vision_event_t) == 4, "Event must be 4 bytes");

/* ------------------------------------------------------------------------- *
 * HapticCmd - 4 bytes, write without response.
 *
 * No CRC. A corrupted buzz is harmless, and the round trip for an
 * acknowledgement would blow the 60 ms hazard haptic budget.
 * ------------------------------------------------------------------------- */

#define VISION_MOTOR_LEFT  0x01
#define VISION_MOTOR_RIGHT 0x02
#define VISION_MOTOR_BOTH  0x03

typedef enum {
    VISION_PATTERN_OBSTACLE_LEFT  = 0x01, /* left motor, two pulses */
    VISION_PATTERN_OBSTACLE_RIGHT = 0x02, /* right motor, two pulses */
    VISION_PATTERN_OBSTACLE_AHEAD = 0x03, /* both motors, sustained */
    VISION_PATTERN_DROP_AHEAD     = 0x04, /* both motors, three hard pulses */
    VISION_PATTERN_TURN_LEFT      = 0x10, /* left motor, three short */
    VISION_PATTERN_TURN_RIGHT     = 0x11, /* right motor, three short */
    VISION_PATTERN_ARRIVED        = 0x20, /* both, long-short-long */
    VISION_PATTERN_EMERGENCY      = 0xFF, /* both, continuous */
} vision_pattern_t;

typedef struct __attribute__((packed)) {
    uint8_t motor_mask;
    uint8_t pattern_id;
    uint8_t intensity;  /* 0..255 */
    uint8_t repeat;     /* 0 = continuous until silenced */
} vision_haptic_cmd_t;

_Static_assert(sizeof(vision_haptic_cmd_t) == 4, "HapticCmd must be 4 bytes");

/* ------------------------------------------------------------------------- *
 * DeviceState - 6 bytes, notified at 0.1 Hz.
 * ------------------------------------------------------------------------- */

typedef struct __attribute__((packed)) {
    uint8_t  battery_pct;
    uint8_t  charging;
    uint16_t sensor_health; /* 0 = all well; see bits below */
    uint16_t fw_version;
} vision_device_state_t;

_Static_assert(sizeof(vision_device_state_t) == 6, "DeviceState must be 6 bytes");

#define VISION_HEALTH_TOF_LEFT   (1u << 0)
#define VISION_HEALTH_TOF_CENTRE (1u << 1)
#define VISION_HEALTH_TOF_HEAD   (1u << 2)
#define VISION_HEALTH_IMU        (1u << 3)
#define VISION_HEALTH_MOTOR_L    (1u << 4)
#define VISION_HEALTH_MOTOR_R    (1u << 5)

/* ------------------------------------------------------------------------- *
 * Config - 8 bytes, read / write.
 *
 * Battery is the top hardware risk: a device that dies at 3pm is not an
 * assistive device. The phone turns the range sensors down to
 * tof_hz_stationary whenever the IMU says the user is standing still.
 * ------------------------------------------------------------------------- */

typedef struct __attribute__((packed)) {
    uint8_t  tof_hz_walking;      /* default 10 */
    uint8_t  tof_hz_stationary;   /* default 1  */
    uint8_t  imu_hz;              /* default 50 */
    uint8_t  haptic_gain;         /* default 200 */
    uint16_t fall_impact_milli_g; /* default 2500 */
    uint16_t fall_freefall_milli_g; /* default 400 */
} vision_config_t;

_Static_assert(sizeof(vision_config_t) == 8, "Config must be 8 bytes");

/* ------------------------------------------------------------------------- *
 * CRC-8 Dallas/Maxim, polynomial 0x31 reflected to 0x8C, init 0x00.
 * Must produce byte-identical results to Crc8.kt. The vectors in Crc8Test are
 * the cheapest guard against a silent polynomial or endianness mismatch found
 * three weeks into bring-up.
 * ------------------------------------------------------------------------- */

static inline uint8_t vision_crc8(const uint8_t *data, uint32_t length)
{
    uint8_t crc = 0;
    for (uint32_t i = 0; i < length; i++) {
        crc ^= data[i];
        for (uint8_t bit = 0; bit < 8; bit++) {
            crc = (crc & 0x01) ? (uint8_t)((crc >> 1) ^ 0x8C) : (uint8_t)(crc >> 1);
        }
    }
    return crc;
}

static inline void vision_seal_sensor_frame(vision_sensor_frame_t *frame)
{
    frame->crc8 = vision_crc8((const uint8_t *)frame, sizeof(*frame) - 1);
}

static inline void vision_seal_event(vision_event_t *event)
{
    event->crc8 = vision_crc8((const uint8_t *)event, sizeof(*event) - 1);
}

#endif /* VISION_GATT_H */
