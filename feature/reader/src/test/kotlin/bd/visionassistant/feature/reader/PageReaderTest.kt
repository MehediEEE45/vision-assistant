package bd.visionassistant.feature.reader

import bd.visionassistant.core.FakeClock
import bd.visionassistant.core.HapticPattern
import bd.visionassistant.core.Language
import bd.visionassistant.perception.ocr.TextRecogniser
import bd.visionassistant.spine.output.EarconEngine
import bd.visionassistant.spine.output.HapticEngine
import bd.visionassistant.spine.output.OutputArbiter
import bd.visionassistant.spine.output.SpeechEngine
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals

@OptIn(ExperimentalCoroutinesApi::class)
class PageReaderTest {

    private val speech = ScriptedSpeech()
    private var page: List<String> = emptyList()
    private val recogniser = object : TextRecogniser {
        override suspend fun recognise(image: File): Result<List<String>> = Result.success(page)
    }

    @Test
    fun `reads paragraphs in order then says it has finished`() = runTest(UnconfinedTestDispatcher()) {
        val reader = reader()

        reader.readText(listOf("One.", "Two."), Language.ENGLISH)
        speech.finishCurrent()
        speech.finishCurrent()

        assertEquals(listOf("One.", "Two.", "finished"), speech.spoken)
        assertEquals(PageReader.State.IDLE, reader.state.value)
    }

    @Test
    fun `resume after a pause restarts the interrupted paragraph`() = runTest(UnconfinedTestDispatcher()) {
        val reader = reader()

        reader.readText(listOf("One.", "Two."), Language.ENGLISH)
        reader.pause(announce = false)
        assertEquals(PageReader.State.PAUSED, reader.state.value)

        reader.resume()

        assertEquals(listOf("One.", "One."), speech.spoken)
        assertEquals(PageReader.State.READING, reader.state.value)
    }

    @Test
    fun `next skips to the following paragraph`() = runTest(UnconfinedTestDispatcher()) {
        val reader = reader()

        reader.readText(listOf("One.", "Two.", "Three."), Language.ENGLISH)
        reader.next()

        assertEquals(listOf("One.", "Two."), speech.spoken)
    }

    @Test
    fun `next on the last paragraph finishes instead of repeating it`() = runTest(UnconfinedTestDispatcher()) {
        val reader = reader()

        reader.readText(listOf("One."), Language.ENGLISH)
        reader.next()

        assertEquals(listOf("One.", "finished"), speech.spoken)
        assertEquals(PageReader.State.IDLE, reader.state.value)
    }

    @Test
    fun `a page with no readable text says so and stays idle`() = runTest(UnconfinedTestDispatcher()) {
        val reader = reader()
        page = emptyList()

        reader.readImage(File("page.jpg"))

        assertEquals(listOf("no_text"), speech.spoken)
        assertEquals(PageReader.State.IDLE, reader.state.value)
    }

    @Test
    fun `recognised text is read aloud`() = runTest(UnconfinedTestDispatcher()) {
        val reader = reader()
        page = listOf("Chapter one.")

        reader.readImage(File("page.jpg"))

        assertEquals(listOf("Chapter one."), speech.spoken)
        assertEquals(PageReader.State.READING, reader.state.value)
    }

    @Test
    fun `stop ends reading and nothing more is spoken`() = runTest(UnconfinedTestDispatcher()) {
        val reader = reader()

        reader.readText(listOf("One.", "Two."), Language.ENGLISH)
        reader.stop()
        speech.finishCurrent()

        assertEquals(listOf("One."), speech.spoken)
        assertEquals(PageReader.State.IDLE, reader.state.value)
    }

    private fun TestScope.reader() = PageReader(
        arbiter = OutputArbiter(speech, NoHaptics, NoEarcons, FakeClock(), backgroundScope),
        recogniser = recogniser,
        phrases = { it.name.lowercase() },
        userLanguage = { Language.ENGLISH },
        scope = backgroundScope,
    )
}

private class ScriptedSpeech : SpeechEngine {
    val spoken = mutableListOf<String>()
    private var gate: CompletableDeferred<Unit>? = null

    override suspend fun speak(
        text: String,
        language: Language,
        onSentenceComplete: (charOffset: Int) -> Unit,
    ) {
        spoken += text
        val deferred = CompletableDeferred<Unit>()
        gate = deferred
        try {
            deferred.await()
        } finally {
            if (gate === deferred) gate = null
        }
    }

    fun finishCurrent() {
        gate?.complete(Unit)
    }

    override fun setRate(rate: Float) = Unit

    override fun hasOfflineVoice(language: Language): Boolean = true
}

private object NoHaptics : HapticEngine {
    override fun fire(pattern: HapticPattern) = Unit
    override fun silence() = Unit
    override fun setIntensity(intensity: Float) = Unit
}

private val NoEarcons = EarconEngine { _ -> }
