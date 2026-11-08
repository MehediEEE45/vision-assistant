package bd.visionassistant.core

/**
 * Visual states for the main interface.
 *
 * Although the app is designed for blind users, visual indicators help
 * sighted assistants and users with residual sight know what the device
 * is currently doing.
 */
enum class VisionUiState {
    IDLE,
    LISTENING,
    READING
}
