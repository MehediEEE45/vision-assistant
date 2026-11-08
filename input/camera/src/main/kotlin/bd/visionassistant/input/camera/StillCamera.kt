package bd.visionassistant.input.camera

import android.content.Context
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.File
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * One still photograph of a page from the back camera.
 *
 * The camera is bound only for the length of a capture. It is the largest
 * battery draw in the app, and nothing needs it open between pages.
 */
class StillCamera(
    private val context: Context,
) {

    /** Main thread only. Throws if the camera cannot be opened or the capture fails. */
    suspend fun capture(owner: LifecycleOwner, into: File): File {
        val provider = cameraProvider()
        val useCase = ImageCapture.Builder()
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
            .build()

        provider.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, useCase)
        try {
            return takePicture(useCase, into)
        } finally {
            provider.unbind(useCase)
        }
    }

    private suspend fun cameraProvider(): ProcessCameraProvider =
        suspendCancellableCoroutine { continuation ->
            val future = ProcessCameraProvider.getInstance(context)
            future.addListener(
                {
                    runCatching { future.get() }
                        .onSuccess { if (continuation.isActive) continuation.resume(it) }
                        .onFailure { if (continuation.isActive) continuation.resumeWithException(it) }
                },
                ContextCompat.getMainExecutor(context),
            )
        }

    private suspend fun takePicture(useCase: ImageCapture, into: File): File =
        suspendCancellableCoroutine { continuation ->
            useCase.takePicture(
                ImageCapture.OutputFileOptions.Builder(into).build(),
                ContextCompat.getMainExecutor(context),
                object : ImageCapture.OnImageSavedCallback {
                    override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                        if (continuation.isActive) continuation.resume(into)
                    }

                    override fun onError(exception: ImageCaptureException) {
                        if (continuation.isActive) continuation.resumeWithException(exception)
                    }
                },
            )
        }
}
