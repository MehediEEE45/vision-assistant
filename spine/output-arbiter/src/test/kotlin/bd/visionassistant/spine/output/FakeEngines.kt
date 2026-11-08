package bd.visionassistant.spine.output

import bd.visionassistant.core.Earcon
import bd.visionassistant.core.HapticPattern
import bd.visionassistant.core.Language
import kotlinx.coroutines.CompletableDeferred

/**
 * A speech engine that never finishes on its own. Tests decide when an
 * utterance completes, which is what makes preemption timing assertable
 * without sleeping.
 */
class FakeSpeechEngine : SpeechEngine {
    val spoken = mutableListOf<String>()
    var rate: Float = 1.0f
        private set

    private var gate: CompletableDeferred<Unit>? = null
    private var onSentence: ((Int) -> Unit)? = null

    val isSpeaking: Boolean get() = gate != null

    override suspend fun speak(
        text: String,
        language: Language,
        onSentenceComplete: (charOffset: Int) -> Unit,
    ) {
        spoken += text
        onSentence = onSentenceComplete
        val deferred = CompletableDeferred<Unit>()
        gate = deferred
        try {
            deferred.await()
        } finally {
            gate = null
            onSentence = null
        }
    }

    /** Simulates the TTS engine reporting a completed sentence boundary. */
    fun reportSentenceBoundary(charOffset: Int) {
        onSentence?.invoke(charOffset)
    }

    fun finishCurrent() {
        gate?.complete(Unit)
    }

    override fun setRate(rate: Float) {
        this.rate = rate
    }

    override fun hasOfflineVoice(language: Language): Boolean = true
}

class FakeHapticEngine : HapticEngine {
    val fired = mutableListOf<HapticPattern>()
    var silenced = 0
        private set

    override fun fire(pattern: HapticPattern) {
        fired += pattern
    }

    override fun silence() {
        silenced++
    }

    override fun setIntensity(intensity: Float) = Unit
}

class FakeEarconEngine : EarconEngine {
    val played = mutableListOf<Earcon>()
    override fun play(earcon: Earcon) {
        played += earcon
    }
}
