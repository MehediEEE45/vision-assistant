package bd.visionassistant.feature.describe

/**
 * Answers "what is in front of me?" at Priority.ANSWER.
 *
 * Orders by proximity and stops at three objects. A list of eleven things is
 * not a description, it is a recital, and by the time it finishes the scene
 * has changed.
 *
 * Every phrase it produces must pass SafetyLanguagePolicy: it reports what was
 * observed and never that an action is safe.
 *
 * Phase 5.
 */
interface SceneDescriber {
    suspend fun describeWhatIsAhead()
}
