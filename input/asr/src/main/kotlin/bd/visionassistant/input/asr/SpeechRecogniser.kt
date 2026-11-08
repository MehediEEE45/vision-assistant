package bd.visionassistant.input.asr

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import bd.visionassistant.core.Language
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * Two-tier by necessity. Android's SpeechRecognizer handles bn-BD well with a
 * connection; offline Bengali recognition is weak across every available
 * option, so the offline path is a fixed keyword vocabulary built from
 * IntentRouter's synonym tables.
 *
 * Every safety-critical intent must be reachable from the offline set. That is
 * a requirement, not a nice-to-have — see UserIntent.offlineReachable.
 */
interface SpeechRecogniser {
    /** Main thread only. Cancelling the caller stops the microphone. */
    suspend fun listenOnce(language: Language): Result<String>

    fun isAvailable(): Boolean
}

sealed class RecognitionFailure(message: String) : Exception(message) {
    class NothingHeard : RecognitionFailure("no speech recognised")
    class Unavailable : RecognitionFailure("no recognition service on this device")
    class NoPermission : RecognitionFailure("microphone permission not granted")
    class Network : RecognitionFailure("recogniser needs a network connection")
    class LanguageUnsupported : RecognitionFailure("language not supported by recogniser")
    class Other(code: Int) : RecognitionFailure("recogniser error $code")
}

class AndroidSpeechRecogniser(
    private val context: Context,
) : SpeechRecogniser {

    override fun isAvailable(): Boolean =
        SpeechRecognizer.isRecognitionAvailable(context) || onDeviceAvailable()

    override suspend fun listenOnce(language: Language): Result<String> {
        val first = listen(language)
        // Users code-switch constantly. If this recogniser has no model for the
        // primary language, one attempt in the other beats a dead end.
        return if (first.exceptionOrNull() is RecognitionFailure.LanguageUnsupported) {
            listen(language.other)
        } else {
            first
        }
    }

    private suspend fun listen(language: Language): Result<String> =
        suspendCancellableCoroutine { continuation ->
            val recognizer = when {
                SpeechRecognizer.isRecognitionAvailable(context) ->
                    SpeechRecognizer.createSpeechRecognizer(context)
                onDeviceAvailable() ->
                    SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
                else -> {
                    continuation.resume(Result.failure(RecognitionFailure.Unavailable()))
                    return@suspendCancellableCoroutine
                }
            }

            fun finish(result: Result<String>) {
                if (continuation.isActive) continuation.resume(result)
                recognizer.destroy()
            }

            recognizer.setRecognitionListener(object : RecognitionListener {
                override fun onResults(results: Bundle?) {
                    val best = results
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull { it.isNotBlank() }
                    finish(
                        if (best != null) Result.success(best)
                        else Result.failure(RecognitionFailure.NothingHeard())
                    )
                }

                override fun onError(error: Int) {
                    finish(Result.failure(failureFor(error)))
                }

                override fun onReadyForSpeech(params: Bundle?) = Unit
                override fun onBeginningOfSpeech() = Unit
                override fun onRmsChanged(rmsdB: Float) = Unit
                override fun onBufferReceived(buffer: ByteArray?) = Unit
                override fun onEndOfSpeech() = Unit
                override fun onPartialResults(partialResults: Bundle?) = Unit
                override fun onEvent(eventType: Int, params: Bundle?) = Unit
            })

            continuation.invokeOnCancellation {
                recognizer.cancel()
                recognizer.destroy()
            }

            recognizer.startListening(intentFor(language))
        }

    private fun intentFor(language: Language) =
        Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, language.bcp47)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, language.bcp47)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
        }

    private fun onDeviceAvailable(): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
            SpeechRecognizer.isOnDeviceRecognitionAvailable(context)

    private fun failureFor(error: Int): RecognitionFailure = when (error) {
        SpeechRecognizer.ERROR_NO_MATCH,
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> RecognitionFailure.NothingHeard()
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> RecognitionFailure.NoPermission()
        SpeechRecognizer.ERROR_NETWORK,
        SpeechRecognizer.ERROR_NETWORK_TIMEOUT,
        SpeechRecognizer.ERROR_SERVER -> RecognitionFailure.Network()
        ERROR_LANGUAGE_NOT_SUPPORTED,
        ERROR_LANGUAGE_UNAVAILABLE -> RecognitionFailure.LanguageUnsupported()
        else -> RecognitionFailure.Other(error)
    }

    private companion object {
        // SpeechRecognizer constants added in API 31; the recogniser can report
        // them on older releases through a newer Google app, so match by value.
        const val ERROR_LANGUAGE_NOT_SUPPORTED = 12
        const val ERROR_LANGUAGE_UNAVAILABLE = 13
    }
}
