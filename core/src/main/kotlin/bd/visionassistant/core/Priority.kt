package bd.visionassistant.core

/**
 * The output priority ladder. Every announcement in the system sits on exactly
 * one rung, and the rung decides what the user actually hears when two modules
 * want to speak at the same moment.
 *
 * Latency budgets are measured from the triggering event to audible or tactile
 * onset. They are assertions, not aspirations — see ArbiterLatencyTest.
 */
enum class Priority(
    val rank: Int,
    val budgetMillis: Long,
) {
    /**
     * Imminent collision, drop-off, vehicle closing. Cuts everything mid-word.
     * The haptic for a hazard fires on a separate 60 ms budget, because a buzz
     * reaches the user's motor response about 1.3 seconds before the sentence
     * explaining it finishes.
     */
    HAZARD(0, budgetMillis = 150),

    /** Turn instruction, arrival, off-route. Queues behind HAZARD only. */
    MANEUVER(1, budgetMillis = 400),

    /** The user asked for this. Never interrupted by AMBIENT. */
    ANSWER(2, budgetMillis = 1_200),

    /** Battery, connection state, passive landmarks. Droppable. */
    AMBIENT(3, budgetMillis = Long.MAX_VALUE),

    /**
     * Book and document reading. Suspends on HAZARD or MANEUVER and resumes
     * from the start of the interrupted sentence, never mid-word.
     */
    LONGFORM(4, budgetMillis = 500),
    ;

    /** True when an announcement at this priority may cut one already speaking. */
    fun preempts(other: Priority): Boolean = rank < other.rank

    companion object {
        /** Haptic onset budget for a hazard, independent of the speech budget. */
        const val HAZARD_HAPTIC_BUDGET_MILLIS: Long = 60

        /**
         * AMBIENT is dropped outright rather than queued when the arbiter has
         * been continuously busy for longer than this. A battery notice that
         * arrives two seconds late is noise; arriving never is correct.
         */
        const val AMBIENT_DROP_AFTER_BUSY_MILLIS: Long = 2_000
    }
}
