package bd.visionassistant.spine.output

import bd.visionassistant.core.Earcon
import bd.visionassistant.core.HapticPattern
import bd.visionassistant.core.Language

/**
 * The only way sound leaves this application. Implemented by :output:tts
 * against Android's TextToSpeech; kept as an interface here so the arbiter
 * itself stays a plain JVM object that can be tested without a device.
 */
interface SpeechEngine {

    /**
     * Speaks [text] and returns when it has finished. Cancelling the calling
     * coroutine must stop audio promptly — preemption is implemented as
     * cancellation, so a slow stop is a missed hazard warning.
     *
     * [onSentenceComplete] reports the character offset just past each finished
     * sentence. The arbiter uses it to resume long-form reading at a sentence
     * boundary instead of mid-word, which is the whole difference between a
     * usable reader and an infuriating one.
     */
    suspend fun speak(
        text: String,
        language: Language,
        onSentenceComplete: (charOffset: Int) -> Unit = {},
    )

    /** 0.5 slowest .. 2.0 fastest, relative to the engine default. */
    fun setRate(rate: Float)

    /** True when the underlying engine has offline voice data for [language]. */
    fun hasOfflineVoice(language: Language): Boolean
}

interface HapticEngine {
    /** Must return immediately. The hazard budget from onset is 60 ms. */
    fun fire(pattern: HapticPattern)

    fun silence()

    fun setIntensity(intensity: Float)
}

fun interface EarconEngine {
    fun play(earcon: Earcon)
}

/** Observable arbiter decisions. Feeds the local event log and the tests. */
sealed interface ArbiterEvent {
    val announcementId: Long

    data class Started(override val announcementId: Long, val latencyMillis: Long) : ArbiterEvent
    data class Completed(override val announcementId: Long) : ArbiterEvent
    data class Preempted(
        override val announcementId: Long,
        val byId: Long,
        val resumeCharOffset: Int?,
    ) : ArbiterEvent
    data class Resumed(override val announcementId: Long, val fromCharOffset: Int) : ArbiterEvent
    data class Dropped(
        override val announcementId: Long,
        val reason: bd.visionassistant.core.DropReason,
    ) : ArbiterEvent
    data class BudgetMissed(
        override val announcementId: Long,
        val budgetMillis: Long,
        val actualMillis: Long,
    ) : ArbiterEvent
}
