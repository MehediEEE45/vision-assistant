package bd.visionassistant.input.wakeword

import kotlinx.coroutines.flow.Flow
/**
 * Always-on detection of "Hey Vision" / "এই ভিশন".
 *
 * Budget: under 1 false accept per day, tuned on real Sylhet street and
 * household audio rather than a quiet lab. A physical button on the wearable
 * is always the primary path — the wake word is a convenience, never the only
 * way to reach the assistant.
 *
 * Phase 1.
 */
interface WakeWordDetector {
    fun start()
    fun stop()
    val detections: Flow<Long>
}
