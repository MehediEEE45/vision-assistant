package bd.visionassistant.feature.navigate

import kotlinx.coroutines.flow.Flow
/**
 * Turn-by-turn walking guidance.
 *
 * Emits Announcements at Priority.MANEUVER and lets the arbiter decide when
 * they are heard. It never speaks directly — a hazard must be able to cut a
 * turn instruction mid-word, and only the arbiter can do that.
 *
 * Phase 3.
 */
interface Navigator {
    suspend fun routeTo(destination: String): Result<Unit>
    fun stop()
    val maneuvers: Flow<Maneuver>
}

data class Maneuver(
    val instruction: String,
    val distanceMetres: Int,
    val turn: Turn,
)

enum class Turn { LEFT, RIGHT, STRAIGHT, ARRIVE, REROUTE }
