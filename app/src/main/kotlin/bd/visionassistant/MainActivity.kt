package bd.visionassistant

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.View
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import bd.visionassistant.core.VisionUiState
import bd.visionassistant.input.camera.StillCamera
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.io.File
import kotlin.coroutines.cancellation.CancellationException

/**
 * The whole screen is one button.
 *
 * There is no layout here worth designing, and that is the point: the user
 * never sees it. A blind user cannot reliably hit a 48dp target, so there are
 * no targets — a tap anywhere means "listen", a double tap "read a page", a
 * two-finger tap "stop", a long press "repeat".
 *
 * The visible text exists for a sighted helper setting the device up, and for
 * low-vision users with residual sight, which is why it is enormous and high
 * contrast rather than merely large.
 */
class MainActivity : ComponentActivity() {

    private lateinit var gestures: GestureDetector
    private lateinit var surface: TextView
    private val camera by lazy { StillCamera(this) }

    private var multiTouch = false
    private var capturing = false

    private val permissionRequest =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
            startServiceIfAllowed()
        }

    private val cameraPermissionRequest =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) command(VisionService.ACTION_READ_PAGE, "camera-permission-granted")
        }

    @SuppressLint("ClickableViewAccessibility")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        surface = TextView(this).apply {
            text = getString(R.string.screen_is_one_button)
            textSize = 34f
            setPadding(48, 48, 48, 48)
            contentDescription = getString(R.string.screen_is_one_button)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES
            // With TalkBack on, raw touches never reach the listener below:
            // TalkBack turns a double tap into a click. Without this, the app
            // does nothing at all for the users it is built for.
            setOnClickListener { command(VisionService.ACTION_START_LISTENING, "accessibility-click") }
        }
        setContentView(surface)

        gestures = GestureDetector(this, object : GestureDetector.SimpleOnGestureListener() {
            override fun onDown(e: MotionEvent): Boolean = true

            override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
                command(VisionService.ACTION_START_LISTENING, "tap")
                return true
            }

            override fun onDoubleTap(e: MotionEvent): Boolean {
                command(VisionService.ACTION_READ_PAGE, "double-tap")
                return true
            }

            override fun onLongPress(e: MotionEvent) {
                command(VisionService.ACTION_REPEAT, "long-press")
            }
        })

        surface.setOnTouchListener { _, event -> onSurfaceTouch(event) }

        observeState()
        observeCaptureRequests()
        requestRuntimePermissionsThenStart()
    }

    /**
     * A two-finger tap begins as a one-finger touch. Unless the gesture detector
     * is told to cancel, lifting that first finger also counts as a single tap,
     * and "stop" is immediately followed by "listen".
     */
    private fun onSurfaceTouch(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_POINTER_DOWN -> if (!multiTouch) {
                multiTouch = true
                val cancel = MotionEvent.obtain(event).apply { action = MotionEvent.ACTION_CANCEL }
                gestures.onTouchEvent(cancel)
                cancel.recycle()
                command(VisionService.ACTION_STOP_SPEAKING, "two-finger-tap")
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> if (multiTouch) {
                multiTouch = false
                return true
            }
        }
        if (multiTouch) return true
        return gestures.onTouchEvent(event)
    }

    private fun observeState() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                VisionService.uiState.collect { state -> updateUi(state) }
            }
        }
    }

    private fun observeCaptureRequests() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                VisionService.captureRequests.collect { capturePage() }
            }
        }
    }

    private suspend fun capturePage() {
        if (capturing) return
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            command(VisionService.ACTION_CAPTURE_FAILED, "capture") {
                putExtra(VisionService.EXTRA_PERMISSION_MISSING, true)
            }
            cameraPermissionRequest.launch(Manifest.permission.CAMERA)
            return
        }

        capturing = true
        try {
            // Time to hear "hold the phone above the page" and settle the hand.
            delay(HOLD_STILL_MILLIS)
            val photo = camera.capture(this, File(cacheDir, "page-${System.currentTimeMillis()}.jpg"))
            command(VisionService.ACTION_READ_IMAGE, "capture") {
                putExtra(VisionService.EXTRA_PATH, photo.absolutePath)
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            if (Log.isLoggable(INPUT_LOG_TAG, Log.DEBUG)) Log.d(INPUT_LOG_TAG, "capture failed", e)
            command(VisionService.ACTION_CAPTURE_FAILED, "capture")
        } finally {
            capturing = false
        }
    }

    private fun updateUi(state: VisionUiState) {
        val (color, text) = when (state) {
            VisionUiState.IDLE -> Color.BLACK to getString(R.string.screen_is_one_button)
            VisionUiState.LISTENING -> Color.parseColor("#1565C0") to getString(R.string.state_listening)
            VisionUiState.READING -> Color.parseColor("#2E7D32") to getString(R.string.state_reading)
        }
        surface.setBackgroundColor(color)
        surface.text = text
        surface.contentDescription = text
        surface.setTextColor(Color.WHITE)
    }

    private fun requestRuntimePermissionsThenStart() {
        val needed = requiredPermissions().filter {
            checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
        }
        if (needed.isEmpty()) startServiceIfAllowed()
        else permissionRequest.launch(needed.toTypedArray())
    }

    /**
     * From Android 14, startForeground() throws if a declared service type lacks
     * its runtime permission. Earlier releases have no such rule, and gating
     * them on Bluetooth needlessly left listening and reading unreachable.
     */
    private fun startServiceIfAllowed() {
        val canStart = Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE ||
            checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED

        if (canStart) {
            VisionService.start(this)
        } else {
            surface.announceForAccessibility(getString(R.string.permission_needed))
            surface.text = getString(R.string.permission_needed)
        }
    }

    private fun requiredPermissions(): List<String> = buildList {
        add(Manifest.permission.RECORD_AUDIO)
        add(Manifest.permission.CAMERA)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            add(Manifest.permission.BLUETOOTH_CONNECT)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            add(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    /** Off by default. `adb shell setprop log.tag.VisionInput DEBUG` shows which gesture sent what. */
    private fun command(action: String, source: String, extras: Intent.() -> Unit = {}) {
        if (Log.isLoggable(INPUT_LOG_TAG, Log.DEBUG)) Log.d(INPUT_LOG_TAG, "$source -> $action")
        VisionService.send(this, action, extras)
    }

    private companion object {
        const val HOLD_STILL_MILLIS = 2_500L
        const val INPUT_LOG_TAG = "VisionInput"
    }
}
