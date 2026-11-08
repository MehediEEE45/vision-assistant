package bd.visionassistant.input.camera

import kotlinx.coroutines.flow.Flow
/**
 * CameraX ImageAnalysis at 640x480. Detection does not need preview
 * resolution, and the camera is the single largest battery draw in this
 * application — it stays off unless a feature explicitly asks for frames.
 *
 * OCR opens a separate higher-resolution still capture on demand.
 *
 * Phase 2.
 */
interface CameraSource {
    fun analysisFrames(): Flow<AnalysisFrame>
    suspend fun captureStill(): ByteArray
}

data class AnalysisFrame(
    val widthPx: Int,
    val heightPx: Int,
    val rotationDegrees: Int,
    val luminance: ByteArray,
    val timestampMillis: Long,
)
