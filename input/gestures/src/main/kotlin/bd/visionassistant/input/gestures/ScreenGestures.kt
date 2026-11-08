package bd.visionassistant.input.gestures

/**
 * The whole screen is one button.
 *
 * A blind user cannot hit a 48dp target, so there are no targets: a tap
 * anywhere means "listen", a two-finger tap means "stop", a long press means
 * "repeat". These coexist with TalkBack rather than fighting it.
 *
 * Phase 1.
 */
enum class Gesture { TAP, TWO_FINGER_TAP, LONG_PRESS, SWIPE_LEFT, SWIPE_RIGHT, SHAKE }
