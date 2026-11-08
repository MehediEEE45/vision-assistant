package bd.visionassistant.feature.reader

import bd.visionassistant.core.Announcement
import bd.visionassistant.core.Language
import bd.visionassistant.perception.ocr.TextRecogniser
import bd.visionassistant.spine.output.ArbiterEvent
import bd.visionassistant.spine.output.OutputArbiter
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.File

/**
 * Reads a page aloud one paragraph at a time, at Priority.LONGFORM.
 *
 * Paragraphs are submitted one by one rather than as a single announcement so
 * that next, previous and repeat have something to step between. Within a
 * paragraph the arbiter already resumes at a sentence boundary after a hazard.
 *
 * Still to come (Phase 4): capture guidance — "move the phone higher" — and
 * Bangla pages, which need cloud recognition.
 */
class PageReader(
    private val arbiter: OutputArbiter,
    private val recogniser: TextRecogniser,
    private val phrases: (Phrase) -> String,
    private val userLanguage: () -> Language,
    scope: CoroutineScope,
) {
    enum class Phrase { NO_TEXT, FINISHED, PAUSED, NOT_READING }

    enum class State { IDLE, READING, PAUSED }

    private val _state = MutableStateFlow(State.IDLE)
    val state: StateFlow<State> = _state.asStateFlow()

    private var paragraphs: List<String> = emptyList()
    private var index = 0
    private var readingLanguage = Language.ENGLISH
    private var speakingId: Long? = null

    init {
        scope.launch {
            arbiter.events.collect { event ->
                if (event is ArbiterEvent.Completed && event.announcementId == speakingId) {
                    onParagraphFinished()
                }
            }
        }
    }

    suspend fun readImage(image: File) {
        val found = recogniser.recognise(image).getOrDefault(emptyList())
        if (found.isEmpty()) {
            stop()
            say(Phrase.NO_TEXT)
            return
        }
        // The on-device model reads Latin script only, so the text is spoken with
        // the English voice whatever the interface language is. A Bangla voice
        // reading English words is close to unintelligible.
        readText(found, Language.ENGLISH)
    }

    fun readText(paragraphs: List<String>, language: Language) {
        val clean = paragraphs.map { it.trim() }.filter { it.isNotEmpty() }
        if (clean.isEmpty()) {
            say(Phrase.NO_TEXT)
            return
        }
        cancelSpeech()
        this.paragraphs = clean
        index = 0
        readingLanguage = language
        _state.value = State.READING
        speakCurrent()
    }

    fun pause(announce: Boolean = true) {
        if (_state.value != State.READING) return
        _state.value = State.PAUSED
        cancelSpeech()
        if (announce) say(Phrase.PAUSED)
    }

    /** Restarts the paragraph that was interrupted, from its beginning. */
    fun resume() {
        when (_state.value) {
            State.PAUSED -> {
                _state.value = State.READING
                speakCurrent()
            }
            State.IDLE -> say(Phrase.NOT_READING)
            State.READING -> Unit
        }
    }

    fun next() = jumpTo(index + 1)

    fun previous() = jumpTo(index - 1)

    fun repeat() = jumpTo(index)

    fun stop() {
        cancelSpeech()
        paragraphs = emptyList()
        index = 0
        _state.value = State.IDLE
    }

    private fun jumpTo(target: Int) {
        if (paragraphs.isEmpty()) {
            say(Phrase.NOT_READING)
            return
        }
        cancelSpeech()
        if (target > paragraphs.lastIndex) {
            stop()
            say(Phrase.FINISHED)
            return
        }
        index = target.coerceAtLeast(0)
        _state.value = State.READING
        speakCurrent()
    }

    private fun onParagraphFinished() {
        speakingId = null
        if (_state.value != State.READING) return
        index++
        if (index < paragraphs.size) {
            speakCurrent()
        } else {
            stop()
            say(Phrase.FINISHED)
        }
    }

    private fun speakCurrent() {
        val announcement = Announcement.reading(paragraphs[index], readingLanguage)
        speakingId = announcement.id
        arbiter.submit(announcement)
    }

    private fun cancelSpeech() {
        speakingId = null
        arbiter.cancelTag(Announcement.READING_TAG)
    }

    private fun say(phrase: Phrase) {
        arbiter.submit(Announcement.answer(phrases(phrase), userLanguage()))
    }
}
