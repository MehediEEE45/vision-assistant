package bd.visionassistant.output.messaging

/**
 * SMS and the outbound call for the SOS flow.
 *
 * Location goes out before the call is placed: a delivered text with
 * coordinates survives a call that is not answered, and the target is a
 * correct location from a cold start in under 20 seconds.
 *
 * Phase 5.
 */
interface EmergencyMessenger {
    suspend fun sendLocation(toNumber: String, latitude: Double, longitude: Double, accuracyMetres: Float): Boolean
    fun placeCall(toNumber: String)
}
