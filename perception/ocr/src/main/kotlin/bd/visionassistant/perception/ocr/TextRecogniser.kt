package bd.visionassistant.perception.ocr

import android.content.Context
import android.net.Uri
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.File
import java.io.IOException
import kotlin.coroutines.resume

/**
 * The project's hardest dependency.
 *
 * ML Kit's on-device text recognition covers Latin, Chinese, Devanagari,
 * Japanese and Korean — NOT Bengali script. Tesseract's `ben` model performs
 * poorly on real photographs of newspapers. So:
 *
 *   Latin  -> on device, free, works offline        (implemented)
 *   Bangla -> cloud (Cloud Vision / Azure Read)      (Phase 4)
 *
 * Never advertise offline Bangla reading.
 */
interface TextRecogniser {
    /** Paragraphs in reading order. Empty when no readable text was found. */
    suspend fun recognise(image: File): Result<List<String>>
}

class MlKitTextRecogniser(
    private val context: Context,
) : TextRecogniser {

    private val client = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)

    override suspend fun recognise(image: File): Result<List<String>> {
        val input = try {
            // fromFilePath applies the EXIF rotation CameraX writes. A portrait
            // page decoded sideways comes back as nonsense, not as an error.
            InputImage.fromFilePath(context, Uri.fromFile(image))
        } catch (e: IOException) {
            return Result.failure(e)
        }

        return suspendCancellableCoroutine { continuation ->
            client.process(input)
                .addOnSuccessListener { text ->
                    val paragraphs = text.textBlocks
                        .map { block ->
                            block.text
                                .replace(HYPHENATED_BREAK, "")
                                .replace(LINE_BREAK, " ")
                                .trim()
                        }
                        .filter { paragraph -> paragraph.count(Char::isLetter) >= MIN_LETTERS }
                    if (continuation.isActive) continuation.resume(Result.success(paragraphs))
                }
                .addOnFailureListener { error ->
                    if (continuation.isActive) continuation.resume(Result.failure(error))
                }
        }
    }

    fun close() {
        client.close()
    }

    private companion object {
        // ML Kit keeps the printed line breaks inside a block. Left in, every
        // wrapped line becomes a sentence boundary for the speech engine and the
        // reading comes out as a string of disconnected fragments.
        val HYPHENATED_BREAK = Regex("-\\s*\\n\\s*")
        val LINE_BREAK = Regex("\\s*\\n\\s*")

        /** Page numbers, stray marks and misread specks are not worth a sentence. */
        const val MIN_LETTERS = 3
    }
}
