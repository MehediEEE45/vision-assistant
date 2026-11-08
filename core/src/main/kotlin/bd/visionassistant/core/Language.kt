package bd.visionassistant.core

/**
 * Users code-switch inside a single utterance — "SUST এ যাও" is normal speech,
 * not an edge case. There is one intent router with bilingual synonym tables,
 * never two parallel command sets.
 */
enum class Language(val bcp47: String, val ttsTag: String) {
    /** Primary target. Falls back to bn-IN voice data where bn-BD is absent. */
    BANGLA("bn-BD", "bn"),
    ENGLISH("en-US", "en"),
    ;

    val other: Language get() = if (this == BANGLA) ENGLISH else BANGLA

    companion object {
        fun fromTag(tag: String): Language =
            if (tag.startsWith("bn", ignoreCase = true)) BANGLA else ENGLISH
    }
}
