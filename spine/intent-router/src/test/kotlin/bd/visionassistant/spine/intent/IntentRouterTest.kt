package bd.visionassistant.spine.intent

import bd.visionassistant.core.Language
import bd.visionassistant.core.UserIntent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

class IntentRouterTest {

    private val router = IntentRouter(savedPlaceNames = { setOf("home", "বাসা") })

    @Test
    fun `english navigation extracts the destination after the verb`() {
        val intent = router.route("Take me to Shahjalal University")
        assertIs<UserIntent.NavigateTo>(intent)
        assertEquals("shahjalal university", intent.destination)
    }

    @Test
    fun `bangla navigation extracts the destination before the verb`() {
        val intent = router.route("SUST এ যাও")
        assertIs<UserIntent.NavigateTo>(intent)
        assertEquals("sust", intent.destination)
    }

    @Test
    fun `a bare saved place name is a navigation request`() {
        val intent = router.route("বাসা")
        assertIs<UserIntent.NavigateTo>(intent)
        assertEquals("বাসা", intent.destination)
    }

    @Test
    fun `sos and help are never confused with one another`() {
        assertIs<UserIntent.Sos>(router.route("বাঁচাও"))
        assertIs<UserIntent.Sos>(router.route("emergency"))
        assertIs<UserIntent.Help>(router.route("সাহায্য"))
    }

    @Test
    fun `reading controls resolve in both languages`() {
        assertIs<UserIntent.ReadThis>(router.route("read this"))
        assertIs<UserIntent.ReadThis>(router.route("এটা পড়ো"))
        assertIs<UserIntent.NextParagraph>(router.route("পরের পাতা"))
        assertIs<UserIntent.PauseReading>(router.route("বিরতি"))
    }

    @Test
    fun `speech rate and language settings are reachable by voice`() {
        val faster = router.route("read faster")
        assertIs<UserIntent.SetSpeechRate>(faster)
        assertTrue(faster.delta > 0)

        assertEquals(Language.BANGLA, (router.route("বাংলায় বলো") as UserIntent.SetLanguage).language)
    }

    @Test
    fun `continue reading in bangla is not mistaken for navigation`() {
        assertIs<UserIntent.ResumeReading>(router.route("চালিয়ে যাও"))
        assertIs<UserIntent.ResumeReading>(router.route("continue"))
    }

    @Test
    fun `unrecognised speech is surfaced, never silently swallowed`() {
        val intent = router.route("mmm hmm what")
        assertIs<UserIntent.Unrecognised>(intent)
        assertEquals("mmm hmm what", intent.heard)
    }

    @Test
    fun `every offline-reachable intent has a phrase in both languages`() {
        // The offline keyword vocabulary is built from the router's tables. If a
        // safety-critical intent loses its Bangla phrase, it becomes unreachable
        // without a network — and Bengali speech recognition needs a network.
        val safetyCritical = listOf(
            "বাঁচাও" to UserIntent.Sos::class,
            "emergency" to UserIntent.Sos::class,
            "থামো" to UserIntent.StopSpeaking::class,
            "stop" to UserIntent.StopSpeaking::class,
            "সামনে কি" to UserIntent.WhatIsAhead::class,
            "what is in front of me" to UserIntent.WhatIsAhead::class,
        )
        safetyCritical.forEach { (phrase, expected) ->
            assertEquals(expected, router.route(phrase)::class, "phrase: $phrase")
        }
    }
}
