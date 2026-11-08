package bd.visionassistant.core

/**
 * What the user asked for, independent of the words or the language they used.
 *
 * [offlineReachable] marks intents that must remain available without a network
 * connection. Bengali speech recognition needs a connection; the offline path
 * is a fixed keyword vocabulary. Every safety-critical action has to be in that
 * vocabulary, so this flag is a requirement, not documentation.
 */
sealed class UserIntent(val offlineReachable: Boolean) {

    data object Sos : UserIntent(offlineReachable = true)
    data object StopSpeaking : UserIntent(offlineReachable = true)
    data object RepeatLast : UserIntent(offlineReachable = true)
    data object WhereAmI : UserIntent(offlineReachable = true)
    data object WhatIsAhead : UserIntent(offlineReachable = true)
    data object BatteryStatus : UserIntent(offlineReachable = true)
    data object Help : UserIntent(offlineReachable = true)

    data class NavigateTo(val destination: String) : UserIntent(offlineReachable = false)
    data class ShareLocationWith(val contact: String) : UserIntent(offlineReachable = true)
    data class CallContact(val contact: String) : UserIntent(offlineReachable = true)
    data class SaveCurrentPlaceAs(val label: String) : UserIntent(offlineReachable = true)

    data object ReadThis : UserIntent(offlineReachable = false)
    data object PauseReading : UserIntent(offlineReachable = true)
    data object ResumeReading : UserIntent(offlineReachable = true)
    data object NextParagraph : UserIntent(offlineReachable = true)
    data object PreviousParagraph : UserIntent(offlineReachable = true)
    data object RepeatParagraph : UserIntent(offlineReachable = true)
    data object OpenLibrary : UserIntent(offlineReachable = true)

    data class SetSpeechRate(val delta: Float) : UserIntent(offlineReachable = true)
    data class SetLanguage(val language: Language) : UserIntent(offlineReachable = true)
    data class SetHapticIntensity(val delta: Float) : UserIntent(offlineReachable = true)
    data object ToggleObstacleWarnings : UserIntent(offlineReachable = true)

    /** Recognised speech that matched no intent. Never silently swallowed. */
    data class Unrecognised(val heard: String) : UserIntent(offlineReachable = true)
}
