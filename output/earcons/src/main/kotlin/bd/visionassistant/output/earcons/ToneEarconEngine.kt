package bd.visionassistant.output.earcons

import android.media.AudioManager
import android.media.ToneGenerator
import bd.visionassistant.core.Earcon
import bd.visionassistant.spine.output.EarconEngine

/**
 * Short non-speech tones.
 *
 * States that recur every few seconds get a tone, not a sentence. "Listening"
 * spoken aloud fifty times an hour is intolerable; a 150 ms beep is not, and it
 * tells a blind user the tap registered before any speech could.
 */
class ToneEarconEngine : EarconEngine {

    private val generator: ToneGenerator? = try {
        ToneGenerator(AudioManager.STREAM_ACCESSIBILITY, VOLUME)
    } catch (e: RuntimeException) {
        // ToneGenerator throws when the audio system refuses another track.
        // Losing the beeps must not take speech down with it.
        null
    }

    override fun play(earcon: Earcon) {
        val (tone, millis) = when (earcon) {
            Earcon.LISTENING -> ToneGenerator.TONE_PROP_BEEP to 150
            Earcon.THINKING -> ToneGenerator.TONE_PROP_PROMPT to 120
            Earcon.CONFIRMED -> ToneGenerator.TONE_PROP_ACK to 150
            Earcon.ERROR -> ToneGenerator.TONE_PROP_NACK to 250
            Earcon.CONNECTION_LOST -> ToneGenerator.TONE_SUP_ERROR to 400
            Earcon.CAPTURE_OK -> ToneGenerator.TONE_PROP_BEEP2 to 200
        }
        generator?.startTone(tone, millis)
    }

    fun release() {
        generator?.release()
    }

    private companion object {
        const val VOLUME = 90
    }
}
