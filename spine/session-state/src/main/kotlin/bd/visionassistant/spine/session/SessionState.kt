package bd.visionassistant.spine.session

import bd.visionassistant.core.Language
/**
 * What the assistant is currently doing, so two features cannot both believe
 * they own the user's attention. Navigation running while a book is open is
 * legitimate; two navigations are not.
 *
 * Phase 1.
 */
enum class Activity { IDLE, LISTENING, NAVIGATING, READING, CAPTURING, EMERGENCY }

data class Session(
    val activity: Activity = Activity.IDLE,
    val language: Language = Language.BANGLA,
    val speechRate: Float = 1.0f,
    val hapticIntensity: Float = 0.8f,
    val obstacleWarningsEnabled: Boolean = true,
    val wearableConnected: Boolean = false,
    val online: Boolean = false,
)
