package bd.visionassistant.spine.safety

/**
 * The application reports observations. It never certifies that an action is
 * safe.
 *
 * "Traffic light detected" is an observation the user can act on with their own
 * judgement. "It is safe to cross" is a promise this system cannot keep — the
 * detector has a false-negative rate, the camera has a field of view, and the
 * consequence of being wrong is someone stepping into traffic.
 *
 * The phrase list lives in banned-phrases.txt so the Gradle check and the
 * runtime guard read the same source. See [SAFE_ALTERNATIVES] for what to say
 * instead.
 */
object SafetyLanguagePolicy {

    val bannedPhrases: List<String> by lazy {
        (javaClass.getResourceAsStream("/banned-phrases.txt")
            ?: error("banned-phrases.txt missing from :spine:safety-policy resources"))
            .bufferedReader()
            .readLines()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") }
            .map { it.lowercase() }
    }

    /** Returns every banned phrase present in [text]. Empty means compliant. */
    fun violations(text: String): List<String> {
        val haystack = text.lowercase()
        return bannedPhrases.filter { haystack.contains(it) }
    }

    /**
     * Last-resort runtime guard. Anything that reaches the arbiter has already
     * passed the build check, so a hit here means a string was assembled at
     * runtime — from a cloud vision response, say — and must be rewritten
     * rather than spoken.
     */
    fun isCompliant(text: String): Boolean = violations(text).isEmpty()

    val SAFE_ALTERNATIVES: Map<String, String> = mapOf(
        "it is safe to cross" to "Traffic light detected ahead.",
        "no cars are coming" to "I do not detect a vehicle, but I cannot see everything.",
        "the road is clear" to "I see a crossing about five metres ahead.",
        "take two tablets" to "The label reads: two tablets twice daily.",
    )
}
