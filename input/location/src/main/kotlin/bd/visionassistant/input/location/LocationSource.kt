package bd.visionassistant.input.location

import kotlinx.coroutines.flow.Flow
/**
 * 1 Hz while navigating, far slower otherwise.
 *
 * Accuracy is reported alongside every fix because the assistant has to be
 * honest about it: "my position is uncertain here" is more useful than a
 * confident instruction based on a 40-metre error.
 *
 * Phase 3.
 */
interface LocationSource {
    fun fixes(): Flow<Fix>
    suspend fun lastKnown(): Fix?
}

data class Fix(
    val latitude: Double,
    val longitude: Double,
    val accuracyMetres: Float,
    val bearingDegrees: Float?,
    val timestampMillis: Long,
) {
    val isTrustworthy: Boolean get() = accuracyMetres <= 20f
}
