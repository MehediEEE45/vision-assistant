package bd.visionassistant.output.tts

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.speech.tts.Voice
import bd.visionassistant.core.Language
import bd.visionassistant.spine.output.SpeechEngine
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.Locale
import java.util.concurrent.atomic.AtomicLong
import kotlin.coroutines.resume

/**
 * The only place in this application that calls TextToSpeech.
 *
 * Three things here are load-bearing and easy to get wrong:
 *
 *  1. **Sentence boundaries.** onRangeStart reports where the engine currently
 *     is in the string. We precompute sentence ends and report one to the
 *     arbiter each time speech passes it, so an interrupted book resumes at the
 *     start of a sentence rather than mid-word.
 *
 *  2. **The Bangla danda.** "।" terminates a Bengali sentence. A boundary
 *     detector that only knows about "." treats an entire Bangla paragraph as
 *     one sentence, and every interruption then restarts the whole paragraph.
 *
 *  3. **The audio channel.** Left at the default, speech plays as media: a
 *     user who turns their music down, or a music app holding focus, silences
 *     the warnings too.
 */
class AndroidSpeechEngine(
    context: Context,
) : SpeechEngine {

    private val ready = CompletableDeferred<Boolean>()
    private val utteranceCounter = AtomicLong(0)
    private val pending = mutableMapOf<String, Utterance>()

    private val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    private val speechAttributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        .build()

    private val focusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
        .setAudioAttributes(speechAttributes)
        .build()

    private val tts = TextToSpeech(context.applicationContext) { status ->
        ready.complete(status == TextToSpeech.SUCCESS)
    }

    init {
        tts.setAudioAttributes(speechAttributes)
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) = Unit

            override fun onRangeStart(utteranceId: String?, start: Int, end: Int, frame: Int) {
                val utterance = pending[utteranceId] ?: return
                utterance.reportBoundariesUpTo(start)
            }

            override fun onDone(utteranceId: String?) {
                pending.remove(utteranceId)?.finish(completed = true)
            }

            @Deprecated("Required by the base class", ReplaceWith(""))
            override fun onError(utteranceId: String?) {
                pending.remove(utteranceId)?.finish(completed = false)
            }

            override fun onError(utteranceId: String?, errorCode: Int) {
                pending.remove(utteranceId)?.finish(completed = false)
            }

            override fun onStop(utteranceId: String?, interrupted: Boolean) {
                pending.remove(utteranceId)?.finish(completed = false)
            }
        })
    }

    override suspend fun speak(
        text: String,
        language: Language,
        onSentenceComplete: (charOffset: Int) -> Unit,
    ) {
        if (!ready.await()) return

        tts.language = localeFor(language)
        val id = "vision-${utteranceCounter.incrementAndGet()}"
        // Off by default: pages being read are the user's private documents.
        // Enable while debugging with `adb shell setprop log.tag.VisionSpeech DEBUG`.
        if (android.util.Log.isLoggable("VisionSpeech", android.util.Log.DEBUG)) {
            android.util.Log.d("VisionSpeech", "speak $id [${language.bcp47}] $text")
        }

        // Held only while speaking, so music ducks under a warning instead of
        // the warning being lost under the music.
        audioManager.requestAudioFocus(focusRequest)
        try {
            speakAwaitingCompletion(text, id, onSentenceComplete)
        } finally {
            audioManager.abandonAudioFocusRequest(focusRequest)
        }
    }

    private suspend fun speakAwaitingCompletion(
        text: String,
        id: String,
        onSentenceComplete: (charOffset: Int) -> Unit,
    ) {
        suspendCancellableCoroutine { continuation ->
            val utterance = Utterance(
                boundaries = sentenceBoundaries(text),
                onSentenceComplete = onSentenceComplete,
                onFinish = { if (continuation.isActive) continuation.resume(Unit) },
            )
            pending[id] = utterance

            continuation.invokeOnCancellation {
                // Preemption is cancellation. A slow stop here is a missed
                // hazard warning, so this must not wait for anything.
                pending.remove(id)
                tts.stop()
            }

            val params = Bundle().apply {
                putString(TextToSpeech.Engine.KEY_PARAM_UTTERANCE_ID, id)
            }
            val queued = tts.speak(text, TextToSpeech.QUEUE_FLUSH, params, id)
            if (queued != TextToSpeech.SUCCESS) {
                pending.remove(id)
                if (continuation.isActive) continuation.resume(Unit)
            }
        }
    }

    override fun setRate(rate: Float) {
        tts.setSpeechRate(rate.coerceIn(0.5f, 2.0f))
    }

    /**
     * Checked on first run. If the offline voice is missing we walk the user
     * through installing it by voice — we cannot assume it is present, and a
     * user with no data plan and no offline voice has a silent phone.
     */
    override fun hasOfflineVoice(language: Language): Boolean {
        val locale = localeFor(language)
        return tts.voices.orEmpty().any { voice: Voice ->
            voice.locale.language == locale.language && !voice.isNetworkConnectionRequired
        }
    }

    fun shutdown() {
        tts.stop()
        tts.shutdown()
    }

    private fun localeFor(language: Language): Locale = when (language) {
        Language.BANGLA -> Locale.forLanguageTag("bn-BD")
            .takeIf { tts.isLanguageAvailable(it) >= TextToSpeech.LANG_AVAILABLE }
            ?: Locale.forLanguageTag("bn-IN")
        Language.ENGLISH -> Locale.US
    }

    private class Utterance(
        private val boundaries: List<Int>,
        private val onSentenceComplete: (Int) -> Unit,
        private val onFinish: () -> Unit,
    ) {
        private var nextBoundaryIndex = 0

        fun reportBoundariesUpTo(charOffset: Int) {
            while (nextBoundaryIndex < boundaries.size && boundaries[nextBoundaryIndex] <= charOffset) {
                onSentenceComplete(boundaries[nextBoundaryIndex])
                nextBoundaryIndex++
            }
        }

        fun finish(completed: Boolean) {
            if (completed && boundaries.isNotEmpty()) onSentenceComplete(boundaries.last())
            onFinish()
        }
    }

    companion object {
        /** "।" is the Bengali sentence terminator and is not optional here. */
        private val SENTENCE_END = Regex("[.!?।\\n]+\\s*")

        internal fun sentenceBoundaries(text: String): List<Int> =
            SENTENCE_END.findAll(text)
                .map { it.range.last + 1 }
                .filter { it < text.length }
                .toList()
    }
}
