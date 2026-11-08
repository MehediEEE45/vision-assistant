package bd.visionassistant.perception.objects

import bd.visionassistant.input.camera.AnalysisFrame
/**
 * MediaPipe / LiteRT object detection with a mandatory CPU fallback — delegate
 * availability on budget handsets in this market is unreliable and a silent
 * failure means the scene description simply stops working.
 *
 * Results are ordered by proximity, not confidence. "A person three metres
 * ahead" matters more than a high-confidence chair behind them.
 *
 * Phase 5.
 */
interface ObjectDetector {
    suspend fun detect(frame: AnalysisFrame): List<DetectedObject>
}

data class DetectedObject(
    val label: String,
    val confidence: Float,
    val estimatedDistanceMetres: Float?,
    val bearing: Bearing,
)

enum class Bearing { LEFT, AHEAD, RIGHT }
