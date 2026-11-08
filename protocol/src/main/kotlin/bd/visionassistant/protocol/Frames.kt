package bd.visionassistant.protocol

/**
 * One fused 16-byte frame carrying all three range readings and the IMU
 * sample together.
 *
 * Deliberately not one characteristic per sensor. Per-sensor notifications
 * arrive interleaved and you end up fusing a left reading from one instant
 * with a centre reading from another — which is exactly how phantom obstacles
 * are born. A single frame guarantees the readings are time-coherent.
 *
 * ```
 *  offset size field        type      units
 *  0      2    seq          u16 LE    wraps at 65535
 *  2      2    tofLeft      u16 LE    mm, 0xFFFF = no return
 *  4      2    tofCentre    u16 LE    mm
 *  6      2    tofHead      u16 LE    mm, head-height sensor
 *  8      2    accelMilliG  u16 LE    magnitude, milli-g
 *  10     2    dtMillis     u16 LE    since previous frame
 *  12     1    pitchDeg     i8        degrees
 *  13     1    rollDeg      i8        degrees
 *  14     1    flags        u8        see companion
 *  15     1    crc8         u8        over bytes 0..14
 * ```
 */
data class SensorFrame(
    val seq: Int,
    val tofLeftMm: Int,
    val tofCentreMm: Int,
    val tofHeadMm: Int,
    val accelMilliG: Int,
    val dtMillis: Int,
    val pitchDeg: Int,
    val rollDeg: Int,
    val flags: Int,
) {
    val isWalking: Boolean get() = flags and FLAG_WALKING != 0
    val leftValid: Boolean get() = flags and FLAG_TOF_LEFT_VALID != 0
    val centreValid: Boolean get() = flags and FLAG_TOF_CENTRE_VALID != 0
    val headValid: Boolean get() = flags and FLAG_TOF_HEAD_VALID != 0
    val imuSaturated: Boolean get() = flags and FLAG_IMU_SATURATED != 0
    val buttonHeld: Boolean get() = flags and FLAG_BUTTON_HELD != 0

    /** Range readings that actually mean something, nearest first. */
    fun validRanges(): List<Pair<RangeSensor, Int>> = buildList {
        if (leftValid && tofLeftMm != NO_RETURN) add(RangeSensor.LEFT to tofLeftMm)
        if (centreValid && tofCentreMm != NO_RETURN) add(RangeSensor.CENTRE to tofCentreMm)
        if (headValid && tofHeadMm != NO_RETURN) add(RangeSensor.HEAD to tofHeadMm)
    }.sortedBy { it.second }

    companion object {
        const val SIZE_BYTES = 16
        const val NO_RETURN = 0xFFFF

        const val FLAG_WALKING = 1 shl 0
        const val FLAG_TOF_LEFT_VALID = 1 shl 1
        const val FLAG_TOF_CENTRE_VALID = 1 shl 2
        const val FLAG_TOF_HEAD_VALID = 1 shl 3
        const val FLAG_IMU_SATURATED = 1 shl 4
        const val FLAG_BUTTON_HELD = 1 shl 5
        const val FLAG_LOW_POWER = 1 shl 6

        /** Returns null on a length or CRC failure. A corrupt frame is discarded, never guessed at. */
        fun parse(bytes: ByteArray): SensorFrame? {
            if (bytes.size != SIZE_BYTES) return null
            if (Crc8.compute(bytes, 0, SIZE_BYTES - 1) != bytes[15].toInt() and 0xFF) return null
            return SensorFrame(
                seq = bytes.u16(0),
                tofLeftMm = bytes.u16(2),
                tofCentreMm = bytes.u16(4),
                tofHeadMm = bytes.u16(6),
                accelMilliG = bytes.u16(8),
                dtMillis = bytes.u16(10),
                pitchDeg = bytes[12].toInt(),
                rollDeg = bytes[13].toInt(),
                flags = bytes[14].toInt() and 0xFF,
            )
        }
    }
}

enum class RangeSensor { LEFT, CENTRE, HEAD }

/** Asynchronous wearable events. The SOS button path must never be polled. */
data class DeviceEvent(
    val type: Type,
    val arg: Int,
) {
    enum class Type(val wire: Int) {
        SOS_PRESSED(0x01),
        FALL_CANDIDATE(0x02),
        BUTTON_SINGLE(0x03),
        BUTTON_DOUBLE(0x04),
        BUTTON_LONG(0x05),
        TAMPER(0x06),
        SENSOR_FAULT(0x07),
        ;

        companion object {
            fun fromWire(value: Int): Type? = entries.firstOrNull { it.wire == value }
        }
    }

    companion object {
        const val SIZE_BYTES = 4

        fun parse(bytes: ByteArray): DeviceEvent? {
            if (bytes.size != SIZE_BYTES) return null
            if (Crc8.compute(bytes, 0, SIZE_BYTES - 1) != bytes[3].toInt() and 0xFF) return null
            val type = Type.fromWire(bytes[0].toInt() and 0xFF) ?: return null
            return DeviceEvent(type, bytes.u16(1))
        }
    }
}

/**
 * Written to the wearable, no response expected. No CRC: a corrupted buzz is
 * harmless and the round trip for acknowledgement would blow the 60 ms hazard
 * haptic budget.
 */
data class HapticCommand(
    val motorMask: Int,
    val patternId: Int,
    val intensity: Int,
    val repeat: Int = 1,
) {
    fun encode(): ByteArray = byteArrayOf(
        motorMask.toByte(),
        patternId.toByte(),
        intensity.coerceIn(0, 255).toByte(),
        repeat.coerceIn(0, 255).toByte(),
    )

    companion object {
        const val SIZE_BYTES = 4

        /** Stops every motor immediately. Sent when the user cancels an alert. */
        val SILENCE = HapticCommand(motorMask = 0, patternId = 0, intensity = 0, repeat = 0)
    }
}

data class DeviceState(
    val batteryPercent: Int,
    val charging: Boolean,
    val sensorHealth: Int,
    val firmwareVersion: Int,
) {
    fun isHealthy(): Boolean = sensorHealth == 0

    /** Human-readable faults, for the spoken degradation notice. */
    fun faults(): List<String> = buildList {
        if (sensorHealth and (1 shl 0) != 0) add("left range sensor")
        if (sensorHealth and (1 shl 1) != 0) add("centre range sensor")
        if (sensorHealth and (1 shl 2) != 0) add("head range sensor")
        if (sensorHealth and (1 shl 3) != 0) add("motion sensor")
        if (sensorHealth and (1 shl 4) != 0) add("left motor")
        if (sensorHealth and (1 shl 5) != 0) add("right motor")
    }

    companion object {
        const val SIZE_BYTES = 6

        fun parse(bytes: ByteArray): DeviceState? {
            if (bytes.size != SIZE_BYTES) return null
            return DeviceState(
                batteryPercent = (bytes[0].toInt() and 0xFF).coerceIn(0, 100),
                charging = bytes[1].toInt() != 0,
                sensorHealth = bytes.u16(2),
                firmwareVersion = bytes.u16(4),
            )
        }
    }
}

/**
 * Duty-cycle knobs. Battery is the top hardware risk: a device that dies at
 * 3pm is not an assistive device, so the phone turns these down whenever the
 * IMU says the user is standing still.
 */
data class WearableConfig(
    val tofHzWalking: Int = 10,
    val tofHzStationary: Int = 1,
    val imuHz: Int = 50,
    val hapticGain: Int = 200,
    val fallImpactMilliG: Int = 2_500,
    val fallFreefallMilliG: Int = 400,
) {
    fun encode(): ByteArray = byteArrayOf(
        tofHzWalking.toByte(),
        tofHzStationary.toByte(),
        imuHz.toByte(),
        hapticGain.toByte(),
        (fallImpactMilliG and 0xFF).toByte(), (fallImpactMilliG shr 8).toByte(),
        (fallFreefallMilliG and 0xFF).toByte(), (fallFreefallMilliG shr 8).toByte(),
    )

    companion object {
        const val SIZE_BYTES = 8

        fun parse(bytes: ByteArray): WearableConfig? {
            if (bytes.size != SIZE_BYTES) return null
            return WearableConfig(
                tofHzWalking = bytes[0].toInt() and 0xFF,
                tofHzStationary = bytes[1].toInt() and 0xFF,
                imuHz = bytes[2].toInt() and 0xFF,
                hapticGain = bytes[3].toInt() and 0xFF,
                fallImpactMilliG = bytes.u16(4),
                fallFreefallMilliG = bytes.u16(6),
            )
        }
    }
}

private fun ByteArray.u16(offset: Int): Int =
    (this[offset].toInt() and 0xFF) or ((this[offset + 1].toInt() and 0xFF) shl 8)
