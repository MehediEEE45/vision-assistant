package bd.visionassistant.perception.fall

import bd.visionassistant.core.Clock
import bd.visionassistant.protocol.SensorFrame

/**
 * Free-fall, then impact, then stillness, then ask.
 *
 * Each stage exists to reject a specific false positive. Impact alone fires
 * every time the user sits down hard or sets the cane against a wall. Free-fall
 * followed by impact still fires when a bag is dropped. Requiring the user to
 * then lie still for [STILLNESS_MILLIS] rejects almost all of it, because
 * someone who sat down heavily gets up, shifts, or keeps walking.
 *
 * The final stage is a spoken question with a cancellable countdown. This
 * system never dials an emergency contact on a sensor reading alone — a false
 * alarm that calls a family member at 3am is how a user decides the feature is
 * not worth having, and turns off the one that would have saved them.
 */
class FallDetector(
    private val clock: Clock,
    private val thresholds: Thresholds = Thresholds(),
) {
    data class Thresholds(
        /** Below this the wearable is effectively in free-fall. */
        val freefallMilliG: Int = 400,
        /** Sustained free-fall before a fall is even plausible. */
        val freefallMinMillis: Long = 100,
        /** Impact magnitude that must follow the free-fall. */
        val impactMilliG: Int = 2_500,
        /** How long after free-fall the impact must arrive. */
        val impactWindowMillis: Long = 800,
        /** Movement above this counts as "the user is fine and moving". */
        val stillnessMilliG: Int = 1_250,
    )

    enum class State { IDLE, FREEFALL, AWAITING_IMPACT, WATCHING_STILLNESS, CHALLENGING }

    sealed interface Outcome {
        /** Ask "Are you okay?" and start the countdown. */
        data class Challenge(val countdownMillis: Long) : Outcome

        /** Countdown elapsed with no response. Escalate to the emergency flow. */
        data object Escalate : Outcome

        /** The user moved or answered. Stand down silently. */
        data object StoodDown : Outcome
    }

    var state: State = State.IDLE
        private set

    private var freefallStartedAt: Long = 0
    private var impactAt: Long = 0
    private var stillnessSince: Long = 0
    private var challengeStartedAt: Long = 0

    fun onFrame(frame: SensorFrame): Outcome? {
        val now = clock.nowMillis()
        val magnitude = frame.accelMilliG

        return when (state) {
            State.IDLE -> {
                if (magnitude < thresholds.freefallMilliG) {
                    freefallStartedAt = now
                    state = State.FREEFALL
                }
                null
            }

            State.FREEFALL -> {
                when {
                    magnitude >= thresholds.freefallMilliG &&
                        now - freefallStartedAt < thresholds.freefallMinMillis -> {
                        // Too brief to be a fall. A stumble, or a sensor glitch.
                        state = State.IDLE
                        null
                    }
                    magnitude >= thresholds.impactMilliG -> {
                        impactAt = now
                        stillnessSince = now
                        state = State.WATCHING_STILLNESS
                        null
                    }
                    magnitude >= thresholds.freefallMilliG -> {
                        state = State.AWAITING_IMPACT
                        null
                    }
                    else -> null
                }
            }

            State.AWAITING_IMPACT -> {
                when {
                    magnitude >= thresholds.impactMilliG -> {
                        impactAt = now
                        stillnessSince = now
                        state = State.WATCHING_STILLNESS
                        null
                    }
                    now - freefallStartedAt > thresholds.impactWindowMillis -> {
                        state = State.IDLE
                        null
                    }
                    else -> null
                }
            }

            State.WATCHING_STILLNESS -> {
                if (magnitude > thresholds.stillnessMilliG) {
                    // They are moving. Someone who sat down hard gets up.
                    state = State.IDLE
                    Outcome.StoodDown
                } else if (now - stillnessSince >= STILLNESS_MILLIS) {
                    challengeStartedAt = now
                    state = State.CHALLENGING
                    Outcome.Challenge(CHALLENGE_COUNTDOWN_MILLIS)
                } else {
                    null
                }
            }

            State.CHALLENGING -> {
                if (now - challengeStartedAt >= CHALLENGE_COUNTDOWN_MILLIS) {
                    state = State.IDLE
                    Outcome.Escalate
                } else {
                    null
                }
            }
        }
    }

    /**
     * The user answered, pressed the button, or moved. Any signal of life
     * cancels the countdown — the bar for standing down is deliberately far
     * lower than the bar for escalating.
     */
    fun cancel(): Outcome? {
        val wasChallenging = state == State.CHALLENGING
        state = State.IDLE
        return if (wasChallenging) Outcome.StoodDown else null
    }

    companion object {
        /** Lie still this long after impact before the app says anything. */
        const val STILLNESS_MILLIS: Long = 8_000

        /** "Are you okay?" then this long to answer before contacts are called. */
        const val CHALLENGE_COUNTDOWN_MILLIS: Long = 30_000
    }
}
