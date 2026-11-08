package bd.visionassistant.feature.library

/**
 * Saved documents with a resume position, navigated entirely by voice.
 *
 * Resume position is a character offset at a sentence boundary, matching how
 * the arbiter resumes an interrupted utterance — the same invariant in both
 * places, so a book interrupted by a hazard and a book closed for a week both
 * pick up in the same way.
 *
 * Phase 4.
 */
interface Library {
    suspend fun save(title: String, text: String): Long
    suspend fun list(): List<Document>
    suspend fun resumePosition(documentId: Long): Int
    suspend fun setResumePosition(documentId: Long, charOffset: Int)
}

data class Document(
    val id: Long,
    val title: String,
    val charCount: Int,
    val lastOpenedMillis: Long,
)
