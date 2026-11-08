package bd.visionassistant.perception.obstacle

import bd.visionassistant.core.Clock
import bd.visionassistant.core.HapticPattern
import bd.visionassistant.protocol.RangeSensor
import bd.visionassistant.protocol.SensorFrame

/**
 * Turns a 20 Hz range stream into the smallest number of alerts that keeps the
 * user safe.
 *
 * Users abandon devices that cry wolf, permanently. That makes false alarms per
 * hour the metric this class exists to minimise, and it does so with three
 * mechanisms:
 *
 *  1. **Multi-frame confirmation** — a band is only entered after
 *     [FRAMES_TO_CONFIRM] consecutive readings agree. At 20 Hz that costs 150 ms,
 *     which fits inside the 150 ms hazard speech budget because the haptic
 *     fires on confirmation, not on the first stray reading.
 *  2. **Hysteresis** — leaving a band requires retreating past the entry
 *     threshold plus [HYSTERESIS_MM]. Without it, a reading hovering on a band
 *     edge produces an alert on every other frame.
 *  3. **Re-announce intervals** — once warned about something, the user is not
 *     warned again about it for a band-specific interval. They heard you.
 *
 * Standing still suppresses everything. A wall you are standing next to is not
 * news, and a stationary user being told about it every two seconds is the
 * single fastest way to get a device switched off.
 */
class ObstaclePolicy(
    private val clock: Clock,
    private val config: Config = Config(),
) {
    data class Config(
        val immediateMm: Int = 600,
        val nearMm: Int = 1_200,
        val approachingMm: Int = 2_000,
        val headroomMm: Int = 900,
    )

    enum class Band(val reannounceMillis: Long) {
        IMMEDIATE(reannounceMillis = 1_500),
        NEAR(reannounceMillis = 3_000),
        APPROACHING(reannounceMillis = 6_000),
        CLEAR(reannounceMillis = Long.MAX_VALUE),
    }

    data class Alert(
        val band: Band,
        val sensor: RangeSensor,
        val distanceMm: Int,
        val haptic: HapticPattern,
        val isHeadHeight: Boolean,
    )

    private val confirmations = mutableMapOf<RangeSensor, Confirmation>()
    private val lastAnnouncedAt = mutableMapOf<RangeSensor, Long>()
    private val currentBand = mutableMapOf<RangeSensor, Band>()

    /** Returns an alert only when one is genuinely worth the user's attention. */
    fun onFrame(frame: SensorFrame): Alert? {
        if (!frame.isWalking) {
            reset()
            return null
        }

        val nearest = frame.validRanges().firstOrNull() ?: run {
            reset()
            return null
        }

        val (sensor, distanceMm) = nearest
        val band = bandFor(sensor, distanceMm)

        if (band == Band.CLEAR) {
            confirmations.remove(sensor)
            currentBand[sensor] = Band.CLEAR
            return null
        }

        val confirmation = confirmations.getOrPut(sensor) { Confirmation(band) }
        if (confirmation.band != band) {
            confirmations[sensor] = Confirmation(band)
            return null
        }
        if (++confirmation.frames < FRAMES_TO_CONFIRM) return null

        val now = clock.nowMillis()
        val previousBand = currentBand[sensor] ?: Band.CLEAR
        val lastAt = lastAnnouncedAt[sensor]

        // Closing in deserves an immediate re-warning; holding steady does not.
        val escalating = band.ordinal < previousBand.ordinal
        val quietEnough = lastAt == null || now - lastAt >= band.reannounceMillis
        if (!escalating && !quietEnough) return null

        currentBand[sensor] = band
        lastAnnouncedAt[sensor] = now

        return Alert(
            band = band,
            sensor = sensor,
            distanceMm = distanceMm,
            haptic = hapticFor(sensor),
            isHeadHeight = sensor == RangeSensor.HEAD,
        )
    }

    fun reset() {
        confirmations.clear()
        currentBand.clear()
    }

    private fun bandFor(sensor: RangeSensor, distanceMm: Int): Band {
        // The head sensor uses a tighter threshold. A branch at head height is
        // only an obstacle once it is close enough to be unavoidable, and
        // warning about every overhead sign makes the device unusable.
        val immediate = if (sensor == RangeSensor.HEAD) config.headroomMm else config.immediateMm
        val exiting = currentBand[sensor] ?: Band.CLEAR
        val margin = if (exiting == Band.CLEAR) 0 else HYSTERESIS_MM

        return when {
            distanceMm <= immediate + marginFor(exiting, Band.IMMEDIATE, margin) -> Band.IMMEDIATE
            sensor == RangeSensor.HEAD -> Band.CLEAR
            distanceMm <= config.nearMm + marginFor(exiting, Band.NEAR, margin) -> Band.NEAR
            distanceMm <= config.approachingMm + marginFor(exiting, Band.APPROACHING, margin) -> Band.APPROACHING
            else -> Band.CLEAR
        }
    }

    /** Widen a band's upper edge only while the user is already inside it. */
    private fun marginFor(currentBand: Band, candidate: Band, margin: Int): Int =
        if (currentBand == candidate) margin else 0

    private fun hapticFor(sensor: RangeSensor): HapticPattern = when (sensor) {
        RangeSensor.LEFT -> HapticPattern.OBSTACLE_LEFT
        RangeSensor.CENTRE -> HapticPattern.OBSTACLE_AHEAD
        RangeSensor.HEAD -> HapticPattern.OBSTACLE_AHEAD
    }

    private class Confirmation(val band: Band) {
        var frames: Int = 0
    }

    companion object {
        /** 3 frames at 20 Hz = 150 ms of agreement before anything is announced. */
        const val FRAMES_TO_CONFIRM = 3

        /** Retreat margin before a band is considered left. */
        const val HYSTERESIS_MM = 200
    }
}
