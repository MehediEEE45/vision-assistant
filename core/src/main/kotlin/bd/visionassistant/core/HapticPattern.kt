package bd.visionassistant.core

/**
 * The complete haptic vocabulary. Eight patterns, deliberately — a user can
 * learn eight buzzes and act on them without thinking. Twenty they cannot, and
 * a pattern that has to be decoded consciously is slower than speech, which
 * defeats the point of having it.
 *
 * [id] and [motorMask] are wire values written straight into the HapticCmd
 * characteristic. Changing either is a breaking change to the firmware
 * contract in docs/gatt.md and requires a protocol version bump.
 */
enum class HapticPattern(
    val id: Int,
    val motorMask: Int,
    val description: String,
) {
    OBSTACLE_LEFT(0x01, MOTOR_LEFT, "left motor, two pulses"),
    OBSTACLE_RIGHT(0x02, MOTOR_RIGHT, "right motor, two pulses"),
    OBSTACLE_AHEAD(0x03, MOTOR_BOTH, "both motors, sustained"),
    DROP_AHEAD(0x04, MOTOR_BOTH, "both motors, three hard pulses"),

    TURN_LEFT(0x10, MOTOR_LEFT, "left motor, three short"),
    TURN_RIGHT(0x11, MOTOR_RIGHT, "right motor, three short"),
    ARRIVED(0x20, MOTOR_BOTH, "both motors, long-short-long"),

    EMERGENCY(0xFF, MOTOR_BOTH, "both motors, continuous until acknowledged"),
    ;

    companion object {
        fun fromId(id: Int): HapticPattern? = entries.firstOrNull { it.id == id }
    }
}

const val MOTOR_LEFT = 0x01
const val MOTOR_RIGHT = 0x02
const val MOTOR_BOTH = 0x03

/**
 * Short non-speech tones. States that recur every few seconds get an earcon
 * rather than a sentence — "listening" spoken aloud fifty times an hour is
 * intolerable, a 120 ms rising tone is not.
 */
enum class Earcon {
    LISTENING,
    THINKING,
    CONFIRMED,
    ERROR,
    CONNECTION_LOST,
    CAPTURE_OK,
}
