package bd.visionassistant.protocol

import java.util.UUID

/**
 * The wearable contract. Frozen — firmware and app are built in parallel by
 * different people and the single largest schedule risk in a project like this
 * is the two halves drifting apart.
 *
 * Any change to a frame layout is a breaking change: bump [PROTOCOL_VERSION],
 * regenerate firmware/include/vision_gatt.h, and update docs/gatt.md in the
 * same commit. The app refuses to pair with a wearable reporting a different
 * major version rather than silently misreading its sensors.
 */
object Gatt {
    const val PROTOCOL_VERSION: Int = 1

    private fun uuid(short: String) = UUID.fromString("7a9b$short-4c3d-4f21-9e85-1b6c2d0f8a37")

    val SERVICE: UUID = uuid("0001")

    /** notify, 20 Hz, 16 bytes. See [SensorFrame]. */
    val SENSOR_FRAME: UUID = uuid("0002")

    /** notify on change, 4 bytes. See [DeviceEvent]. */
    val EVENT: UUID = uuid("0003")

    /** write-without-response, 4 bytes. See [HapticCommand]. */
    val HAPTIC_CMD: UUID = uuid("0004")

    /** notify, 0.1 Hz, 6 bytes. See [DeviceState]. */
    val DEVICE_STATE: UUID = uuid("0005")

    /** read/write, 8 bytes. See [WearableConfig]. */
    val CONFIG: UUID = uuid("0006")

    val CLIENT_CHARACTERISTIC_CONFIG: UUID =
        UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

    /**
     * If no SensorFrame arrives within this window the link is treated as dead
     * and the degradation is announced out loud. Silent failure of a safety
     * sensor is the worst behaviour this system can have — the user keeps
     * walking, trusting a device that stopped looking.
     */
    const val SENSOR_WATCHDOG_MILLIS: Long = 2_000

    const val NOMINAL_SENSOR_HZ: Int = 20
}
