package bd.visionassistant.output.haptics

import android.content.Context
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.os.Build
import bd.visionassistant.core.HapticPattern
import bd.visionassistant.core.MOTOR_LEFT
import bd.visionassistant.core.MOTOR_RIGHT
import bd.visionassistant.protocol.HapticCommand
import bd.visionassistant.spine.output.HapticEngine

/**
 * Writes to the wearable's motors, and falls back to the phone when the
 * wearable is not connected.
 *
 * The fallback is not a nicety. Directional information is lost — a phone in a
 * pocket cannot say "left" — so the fallback patterns encode direction in
 * *rhythm* instead, and the user is told once, out loud, that they are on the
 * reduced fallback. Degrading silently into a less informative mode is how
 * someone walks into a wall while trusting a buzz that no longer means what
 * they think it means.
 */
class WearableHapticEngine(
    context: Context,
    private val transport: HapticTransport,
) : HapticEngine {

    /** Writes a HapticCmd to the wearable. Supplied by the app, which owns the BLE link. */
    fun interface HapticTransport {
        /** Returns false when the wearable is not currently connected. */
        fun write(command: HapticCommand): Boolean
    }

    private val vibrator: Vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        (context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager).defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
    }

    private var intensity: Float = 0.8f

    override fun fire(pattern: HapticPattern) {
        val command = HapticCommand(
            motorMask = pattern.motorMask,
            patternId = pattern.id,
            intensity = (intensity.coerceIn(0f, 1f) * 255).toInt(),
            repeat = if (pattern == HapticPattern.EMERGENCY) 0 else 1,
        )
        if (transport.write(command)) return
        vibrateOnPhone(pattern)
    }

    override fun silence() {
        transport.write(HapticCommand.SILENCE)
        vibrator.cancel()
    }

    override fun setIntensity(intensity: Float) {
        this.intensity = intensity.coerceIn(0f, 1f)
    }

    /**
     * Rhythm carries what the left and right motors otherwise would: one pulse
     * for left, two for right, a long buzz for dead ahead.
     */
    private fun vibrateOnPhone(pattern: HapticPattern) {
        val timings = when {
            pattern.motorMask == MOTOR_LEFT -> longArrayOf(0, 140)
            pattern.motorMask == MOTOR_RIGHT -> longArrayOf(0, 140, 90, 140)
            pattern == HapticPattern.EMERGENCY -> longArrayOf(0, 400, 150, 400, 150, 400)
            pattern == HapticPattern.ARRIVED -> longArrayOf(0, 300, 120, 90, 120, 300)
            pattern == HapticPattern.DROP_AHEAD -> longArrayOf(0, 90, 70, 90, 70, 90)
            else -> longArrayOf(0, 400)
        }
        val amplitude = (intensity.coerceIn(0.1f, 1f) * 255).toInt()
        val amplitudes = IntArray(timings.size) { index -> if (index % 2 == 0) 0 else amplitude }
        vibrator.vibrate(VibrationEffect.createWaveform(timings, amplitudes, -1))
    }
}
