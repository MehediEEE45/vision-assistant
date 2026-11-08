package bd.visionassistant.core

/**
 * A request to reach the user. Features construct these and hand them to the
 * arbiter; nothing outside the output layer ever calls a speech or vibration
 * API directly.
 *
 * @param text already localised into [language]. Resolve string resources at
 *   the call site so the arbiter never needs an Android Context.
 * @param haptic fired before [text] is spoken, when present.
 * @param earcon a short non-speech tone played before [text], for states that
 *   recur constantly and do not deserve a sentence every time.
 * @param ttlMillis drop the announcement if it has not started by then. A turn
 *   instruction for a corner already passed is worse than silence.
 * @param tag announcements sharing a tag supersede one another in the queue,
 *   so five obstacle reports in one second become one.
 * @param resumable true for [Priority.LONGFORM] reading, where an interruption
 *   must resume at a sentence boundary rather than restart or vanish.
 */
data class Announcement(
    val text: String,
    val priority: Priority,
    val language: Language,
    val haptic: HapticPattern? = null,
    val earcon: Earcon? = null,
    val ttlMillis: Long = DEFAULT_TTL_MILLIS,
    val tag: String? = null,
    val resumable: Boolean = false,
    val id: Long = nextId(),
) {
    init {
        require(text.isNotBlank() || haptic != null || earcon != null) {
            "An announcement must carry speech, a haptic, or an earcon"
        }
        require(ttlMillis > 0) { "ttlMillis must be positive" }
    }

    companion object {
        const val DEFAULT_TTL_MILLIS: Long = 10_000

        private var counter: Long = 0
        private val lock = Any()

        fun nextId(): Long = synchronized(lock) { ++counter }

        /** Hazard: haptic first, speech as the footnote. */
        fun hazard(text: String, language: Language, haptic: HapticPattern, tag: String? = null) =
            Announcement(
                text = text,
                priority = Priority.HAZARD,
                language = language,
                haptic = haptic,
                ttlMillis = 1_500,
                tag = tag,
            )

        fun maneuver(text: String, language: Language, haptic: HapticPattern? = null) =
            Announcement(
                text = text,
                priority = Priority.MANEUVER,
                language = language,
                haptic = haptic,
                ttlMillis = 6_000,
                tag = "navigation.maneuver",
            )

        fun answer(text: String, language: Language) =
            Announcement(text, Priority.ANSWER, language)

        fun ambient(text: String, language: Language, tag: String? = null) =
            Announcement(text, Priority.AMBIENT, language, ttlMillis = 4_000, tag = tag)

        fun reading(sentence: String, language: Language) =
            Announcement(
                text = sentence,
                priority = Priority.LONGFORM,
                language = language,
                ttlMillis = Long.MAX_VALUE / 4,
                tag = READING_TAG,
                resumable = true,
            )

        /** Shared by every page paragraph, so one cancelTag stops the reader. */
        const val READING_TAG = "reader.sentence"
    }
}

/** Why an announcement never reached the user. Logged, and used in tests. */
enum class DropReason {
    EXPIRED,
    SUPERSEDED_BY_SAME_TAG,
    AMBIENT_WHILE_BUSY,
    QUEUE_FULL,
    CANCELLED,
}
