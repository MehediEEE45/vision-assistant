package bd.visionassistant.spine.intent

import bd.visionassistant.core.Language
import bd.visionassistant.core.UserIntent

/**
 * One router with bilingual synonym tables — never two parallel command sets.
 *
 * Users code-switch inside a single utterance: "SUST এ যাও" is ordinary speech
 * in Sylhet, not an edge case, and a design with separate Bangla and English
 * command paths cannot parse it at all.
 *
 * Word order differs between the two languages in a way that matters here.
 * English puts the destination after the verb ("take me to SUST"); Bangla puts
 * it before ("SUST এ যাও"). [extractDestination] handles both.
 */
class IntentRouter(
    private val savedPlaceNames: () -> Set<String> = { emptySet() },
) {

    fun route(utterance: String): UserIntent {
        val text = normalise(utterance)
        if (text.isBlank()) return UserIntent.Unrecognised(utterance)

        // Ordered deliberately. Emergency first: if the user is shouting for
        // help, no other interpretation is worth considering.
        SOS_WORDS.firstMatchIn(text)?.let { return UserIntent.Sos }
        STOP_WORDS.firstMatchIn(text)?.let { return UserIntent.StopSpeaking }
        REPEAT_WORDS.firstMatchIn(text)?.let { return UserIntent.RepeatLast }

        // Reading controls come before navigation. "চালিয়ে যাও" (continue) ends
        // in the navigation verb "যাও" and would otherwise route to a place
        // called "চালিয়ে".
        PAUSE_READING_WORDS.firstMatchIn(text)?.let { return UserIntent.PauseReading }
        RESUME_READING_WORDS.firstMatchIn(text)?.let { return UserIntent.ResumeReading }
        NEXT_PARAGRAPH_WORDS.firstMatchIn(text)?.let { return UserIntent.NextParagraph }
        PREVIOUS_PARAGRAPH_WORDS.firstMatchIn(text)?.let { return UserIntent.PreviousParagraph }
        LIBRARY_WORDS.firstMatchIn(text)?.let { return UserIntent.OpenLibrary }

        NAVIGATE_WORDS.firstMatchIn(text)?.let {
            val destination = extractDestination(text, it)
            if (destination.isNotBlank()) return UserIntent.NavigateTo(destination)
        }

        WHERE_AM_I_WORDS.firstMatchIn(text)?.let { return UserIntent.WhereAmI }
        WHAT_IS_AHEAD_WORDS.firstMatchIn(text)?.let { return UserIntent.WhatIsAhead }
        BATTERY_WORDS.firstMatchIn(text)?.let { return UserIntent.BatteryStatus }

        // Rate and language are checked before "read" on purpose. "Read faster"
        // contains "read", and a user asking for a faster voice does not want a
        // new page captured.
        FASTER_WORDS.firstMatchIn(text)?.let { return UserIntent.SetSpeechRate(+0.15f) }
        SLOWER_WORDS.firstMatchIn(text)?.let { return UserIntent.SetSpeechRate(-0.15f) }
        SWITCH_TO_BANGLA_WORDS.firstMatchIn(text)?.let { return UserIntent.SetLanguage(Language.BANGLA) }
        SWITCH_TO_ENGLISH_WORDS.firstMatchIn(text)?.let { return UserIntent.SetLanguage(Language.ENGLISH) }

        READ_WORDS.firstMatchIn(text)?.let { return UserIntent.ReadThis }

        HELP_WORDS.firstMatchIn(text)?.let { return UserIntent.Help }

        // A saved place spoken on its own — "home", "বাসা" — is a navigation
        // request. Blind users shorten commands aggressively once fluent.
        savedPlaceNames().firstOrNull { text.contains(normalise(it)) }
            ?.let { return UserIntent.NavigateTo(it) }

        return UserIntent.Unrecognised(utterance)
    }

    private fun extractDestination(text: String, matched: String): String {
        val index = text.indexOf(matched)
        val before = text.substring(0, index).trim()
        val after = text.substring(index + matched.length).trim()

        // Bangla: destination precedes the verb, often with a postposition.
        val banglaCandidate = before
            .removeSuffix("এ")
            .removeSuffix("তে")
            .removeSuffix("এর")
            .trim()

        val englishCandidate = after
            .removePrefix("to")
            .removePrefix("me to")
            .trim()

        return when {
            englishCandidate.isNotBlank() -> englishCandidate
            banglaCandidate.isNotBlank() -> banglaCandidate
            else -> ""
        }
    }

    private fun normalise(raw: String): String =
        raw.lowercase()
            .replace(PUNCTUATION, " ")
            .replace(WHITESPACE, " ")
            .trim()

    private companion object {
        val PUNCTUATION = Regex("[.,!?;:।\"'()\\[\\]]")
        val WHITESPACE = Regex("\\s+")

        /**
         * Every phrase below must remain reachable offline, so the wake-word
         * and keyword-spotting vocabulary is built from exactly these strings.
         *
         * Note SOS uses "জরুরি"/"বাঁচাও" while Help uses "সাহায্য". They are
         * deliberately kept phonetically distant: an offline keyword spotter
         * confusing "call an ambulance" with "what can you do" is not a bug you
         * discover politely.
         */
        val SOS_WORDS = listOf("sos", "emergency", "save me", "জরুরি", "বাঁচাও", "বিপদ")
        val HELP_WORDS = listOf("help", "what can you do", "সাহায্য", "কি করতে পারো")

        val STOP_WORDS = listOf("stop", "quiet", "be quiet", "থামো", "চুপ", "বন্ধ করো")
        val REPEAT_WORDS = listOf("repeat", "say that again", "আবার বলো", "পুনরায় বলো")

        val NAVIGATE_WORDS = listOf("take me to", "navigate to", "go to", "যাও", "নিয়ে চলো", "চলো")
        val WHERE_AM_I_WORDS = listOf("where am i", "my location", "আমি কোথায়", "আমার অবস্থান")
        val WHAT_IS_AHEAD_WORDS =
            listOf("what is in front", "what is ahead", "describe", "সামনে কি", "সামনে কী", "বর্ণনা")
        val BATTERY_WORDS = listOf("battery", "charge", "ব্যাটারি", "চার্জ")

        val READ_WORDS = listOf("read this", "read it", "read", "পড়ো", "পড়ে শোনাও")
        val PAUSE_READING_WORDS = listOf("pause", "hold on", "বিরতি", "একটু থামাও")
        val RESUME_READING_WORDS = listOf("continue", "resume", "চালিয়ে যাও", "আবার শুরু")
        val NEXT_PARAGRAPH_WORDS = listOf("next paragraph", "next page", "পরের অনুচ্ছেদ", "পরের পাতা")
        val PREVIOUS_PARAGRAPH_WORDS =
            listOf("previous paragraph", "previous page", "আগের অনুচ্ছেদ", "আগের পাতা")
        val LIBRARY_WORDS = listOf("my books", "library", "open library", "আমার বই", "লাইব্রেরি")

        val FASTER_WORDS = listOf("faster", "speed up", "দ্রুত", "তাড়াতাড়ি")
        val SLOWER_WORDS = listOf("slower", "slow down", "ধীরে", "আস্তে")
        val SWITCH_TO_BANGLA_WORDS = listOf("speak bangla", "bangla", "বাংলায় বলো", "বাংলা")
        val SWITCH_TO_ENGLISH_WORDS = listOf("speak english", "english", "ইংরেজিতে বলো", "ইংরেজি")

        /** Longest match first, so "next page" beats a bare "next". */
        fun List<String>.firstMatchIn(text: String): String? =
            sortedByDescending { it.length }.firstOrNull { text.contains(it) }
    }
}
