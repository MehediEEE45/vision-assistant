package bd.visionassistant.feature.settings

import bd.visionassistant.core.Language
/**
 * Every setting in this application is reachable by voice.
 *
 * This is not a convenience feature. If speech rate can only be changed on a
 * settings screen, a blind user whose speech rate is wrong cannot fix it — and
 * the first thing a new user needs to change is almost always the speech rate.
 *
 * Phase 1.
 */
interface VoiceSettings {
    suspend fun adjustSpeechRate(delta: Float)
    suspend fun adjustHapticIntensity(delta: Float)
    suspend fun setLanguage(language: Language)
    suspend fun toggleObstacleWarnings()
    suspend fun describeCurrentSettings(): String
}
