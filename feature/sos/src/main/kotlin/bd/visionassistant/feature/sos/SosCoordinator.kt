package bd.visionassistant.feature.sos

/**
 * The emergency path: hardware button or voice, then a spoken countdown, then
 * an SMS with coordinates, then a call.
 *
 * The countdown is always cancellable and never skipped, including for a
 * detected fall. A false alarm that wakes a family member at 3am is how a user
 * decides to turn the feature off — and the feature they turn off is the one
 * that would have mattered.
 *
 * Phase 5.
 */
interface SosCoordinator {
    fun trigger(source: Source)
    fun cancel()

    enum class Source { HARDWARE_BUTTON, VOICE, FALL_DETECTED }
}
