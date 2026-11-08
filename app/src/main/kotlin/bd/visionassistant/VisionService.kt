package bd.visionassistant

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.content.res.Resources
import android.os.IBinder
import androidx.annotation.StringRes
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import bd.visionassistant.core.Announcement
import bd.visionassistant.core.Earcon
import bd.visionassistant.core.HapticPattern
import bd.visionassistant.core.Language
import bd.visionassistant.core.Priority
import bd.visionassistant.core.SystemClock
import bd.visionassistant.core.UserIntent
import bd.visionassistant.core.VisionUiState
import bd.visionassistant.feature.reader.PageReader
import bd.visionassistant.input.asr.AndroidSpeechRecogniser
import bd.visionassistant.input.asr.RecognitionFailure
import bd.visionassistant.input.ble.WearableLink
import bd.visionassistant.output.earcons.ToneEarconEngine
import bd.visionassistant.output.haptics.WearableHapticEngine
import bd.visionassistant.output.tts.AndroidSpeechEngine
import bd.visionassistant.perception.fall.FallDetector
import bd.visionassistant.perception.obstacle.ObstaclePolicy
import bd.visionassistant.perception.ocr.MlKitTextRecogniser
import bd.visionassistant.protocol.DeviceEvent
import bd.visionassistant.spine.intent.IntentRouter
import bd.visionassistant.spine.output.OutputArbiter
import bd.visionassistant.spine.safety.SafetyLanguagePolicy
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import java.io.File
import java.util.Locale

/**
 * The runtime. One foreground service owns perception, arbitration and output
 * for the life of the session.
 *
 * Note what this class does NOT do: it never calls the speech or vibration APIs
 * itself. Every path here ends at [arbiter], which decides what the user
 * actually hears. That is the whole architecture in one place — if a future
 * change adds a `tts.speak(...)` anywhere outside :output:tts, the priority
 * ladder stops being true and the app degrades into noise.
 */
class VisionService : LifecycleService() {

    private lateinit var speech: AndroidSpeechEngine
    private lateinit var haptics: WearableHapticEngine
    private lateinit var earcons: ToneEarconEngine
    private lateinit var arbiter: OutputArbiter
    private lateinit var wearable: WearableLink
    private lateinit var recogniser: AndroidSpeechRecogniser
    private lateinit var textRecogniser: MlKitTextRecogniser
    private lateinit var reader: PageReader

    private val router = IntentRouter()
    private val obstaclePolicy = ObstaclePolicy(SystemClock)
    private val fallDetector = FallDetector(SystemClock)

    private var language = Language.BANGLA
    private var speechRate = 1.0f
    private var lastSpoken: Announcement? = null
    private var listening: Job? = null
    private var isListening = false
    private var localized: Pair<Language, Resources>? = null

    override fun onCreate() {
        super.onCreate()

        // Speak the phone's language until the user chooses one by voice.
        language = Language.fromTag(resources.configuration.locales[0].language)

        wearable = WearableLink(applicationContext, lifecycleScope)
        speech = AndroidSpeechEngine(applicationContext)
        haptics = WearableHapticEngine(applicationContext) { command -> wearable.sendHaptic(command) }
        earcons = ToneEarconEngine()
        arbiter = OutputArbiter(
            speech = speech,
            haptics = haptics,
            earcons = earcons,
            clock = SystemClock,
            scope = lifecycleScope,
        )
        recogniser = AndroidSpeechRecogniser(applicationContext)
        textRecogniser = MlKitTextRecogniser(applicationContext)
        reader = PageReader(
            arbiter = arbiter,
            recogniser = textRecogniser,
            phrases = { phrase -> text(phraseText(phrase)) },
            userLanguage = { language },
            scope = lifecycleScope,
        )

        startForeground(NOTIFICATION_ID, buildNotification())

        observeWearable()
        observeDeviceState()
        lifecycleScope.launch { reader.state.collect { publishUiState() } }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        when (intent?.action) {
            ACTION_START_LISTENING -> startListening()
            ACTION_STOP_SPEAKING -> stopEverything()
            ACTION_REPEAT -> repeatLast()
            ACTION_READ_PAGE -> requestPageCapture()
            ACTION_READ_IMAGE -> intent.getStringExtra(EXTRA_PATH)?.let { readImage(File(it)) }
            ACTION_CAPTURE_FAILED -> say(
                if (intent.getBooleanExtra(EXTRA_PERMISSION_MISSING, false)) R.string.read_camera_permission_needed
                else R.string.read_capture_failed
            )
            ACTION_UTTERANCE -> intent.getStringExtra(EXTRA_TEXT)?.let { onUtterance(it) }
            ACTION_READ_TEXT -> intent.getStringExtra(EXTRA_TEXT)?.let {
                reader.readText(it.split(PARAGRAPH_BREAK), language)
            }
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent): IBinder? {
        super.onBind(intent)
        return null
    }

    override fun onDestroy() {
        listening?.cancel()
        wearable.disconnect()
        speech.shutdown()
        earcons.release()
        textRecogniser.close()
        _uiState.value = VisionUiState.IDLE
        super.onDestroy()
    }

    // -- perception ----------------------------------------------------------

    private fun observeWearable() {
        lifecycleScope.launch {
            wearable.frames.collect { frame ->
                obstaclePolicy.onFrame(frame)?.let { alert ->
                    submit(
                        Announcement.hazard(
                            text = obstacleText(alert),
                            language = language,
                            haptic = alert.haptic,
                            tag = "obstacle.${alert.sensor}",
                        )
                    )
                }

                when (fallDetector.onFrame(frame)) {
                    is FallDetector.Outcome.Challenge -> submit(
                        Announcement.hazard(
                            text = text(R.string.fall_are_you_okay),
                            language = language,
                            haptic = HapticPattern.EMERGENCY,
                            tag = "fall.challenge",
                        )
                    )
                    FallDetector.Outcome.Escalate -> escalateEmergency()
                    FallDetector.Outcome.StoodDown, null -> Unit
                }
            }
        }

        lifecycleScope.launch {
            wearable.events.collect { event ->
                when (event.type) {
                    DeviceEvent.Type.SOS_PRESSED -> escalateEmergency()
                    DeviceEvent.Type.BUTTON_SINGLE -> startListening()
                    DeviceEvent.Type.BUTTON_DOUBLE -> stopEverything()
                    DeviceEvent.Type.BUTTON_LONG -> repeatLast()
                    DeviceEvent.Type.FALL_CANDIDATE -> Unit // confirmed on this side
                    DeviceEvent.Type.SENSOR_FAULT -> announceDegradation()
                    DeviceEvent.Type.TAMPER -> Unit
                }
            }
        }
    }

    private fun observeDeviceState() {
        lifecycleScope.launch {
            wearable.status.collectLatest { status ->
                when (status) {
                    // A link that is nominally connected but has stopped sending
                    // frames is the dangerous case: the user keeps walking,
                    // trusting a device that stopped looking.
                    WearableLink.Status.DEGRADED -> announceDegradation()
                    WearableLink.Status.DISCONNECTED -> submit(
                        Announcement.ambient(text(R.string.wearable_disconnected), language, tag = "wearable.link")
                    )
                    WearableLink.Status.INCOMPATIBLE -> say(R.string.wearable_incompatible)
                    else -> Unit
                }
            }
        }
    }

    private fun announceDegradation() {
        submit(
            Announcement.hazard(
                text = text(R.string.wearable_degraded),
                language = language,
                haptic = HapticPattern.EMERGENCY,
                tag = "wearable.link",
            )
        )
    }

    // -- listening -----------------------------------------------------------

    private fun startListening() {
        if (isListening) return
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            say(R.string.mic_permission_needed)
            return
        }
        if (!recogniser.isAvailable()) {
            say(R.string.asr_unavailable)
            return
        }

        val wasReading = reader.state.value == PageReader.State.READING
        // The microphone hears the phone's own speaker. Anything still talking
        // would be transcribed as if the user had said it.
        reader.pause(announce = false)
        arbiter.stopAll()

        isListening = true
        publishUiState()
        listening = lifecycleScope.launch {
            try {
                arbiter.submit(
                    Announcement(text = "", priority = Priority.ANSWER, language = language, earcon = Earcon.LISTENING)
                )
                // Lets the beep finish before the microphone opens.
                delay(EARCON_SETTLE_MILLIS)
                val result = recogniser.listenOnce(language)

                isListening = false
                publishUiState()
                result.fold(
                    onSuccess = { heard -> onUtterance(heard, resumeReadingAfter = wasReading) },
                    onFailure = { failure ->
                        say(listeningFailureText(failure))
                        if (wasReading) reader.resume()
                    },
                )
            } finally {
                isListening = false
                publishUiState()
            }
        }
    }

    fun onUtterance(heard: String, resumeReadingAfter: Boolean = false) {
        var resumeReading = resumeReadingAfter
        when (val intent = router.route(heard)) {
            UserIntent.Sos -> {
                resumeReading = false
                escalateEmergency()
            }
            UserIntent.StopSpeaking -> {
                resumeReading = false
                stopEverything()
            }
            UserIntent.RepeatLast -> {
                resumeReading = false
                repeatLast()
            }
            UserIntent.ReadThis -> {
                resumeReading = false
                requestPageCapture()
            }
            UserIntent.PauseReading -> {
                resumeReading = false
                when (reader.state.value) {
                    PageReader.State.READING -> reader.pause()
                    // Already paused, normally by the listening that heard this command.
                    PageReader.State.PAUSED -> say(R.string.read_paused)
                    PageReader.State.IDLE -> say(R.string.read_nothing_open)
                }
            }
            UserIntent.ResumeReading -> {
                resumeReading = false
                reader.resume()
            }
            UserIntent.NextParagraph -> {
                resumeReading = false
                reader.next()
            }
            UserIntent.PreviousParagraph -> {
                resumeReading = false
                reader.previous()
            }
            UserIntent.RepeatParagraph -> {
                resumeReading = false
                reader.repeat()
            }
            is UserIntent.SetLanguage -> {
                language = intent.language
                say(R.string.language_now)
            }
            is UserIntent.SetSpeechRate -> {
                speechRate = (speechRate + intent.delta).coerceIn(MIN_SPEECH_RATE, MAX_SPEECH_RATE)
                speech.setRate(speechRate)
                say(R.string.confirmed)
            }
            // Never silently swallowed. Silence reads as a broken device.
            is UserIntent.Unrecognised -> say(R.string.did_not_understand)
            else -> say(R.string.not_built_yet)
        }
        if (resumeReading) reader.resume()
    }

    private fun listeningFailureText(failure: Throwable): Int = when (failure) {
        is RecognitionFailure.NothingHeard -> R.string.did_not_hear
        is RecognitionFailure.NoPermission -> R.string.mic_permission_needed
        is RecognitionFailure.Unavailable -> R.string.asr_unavailable
        is RecognitionFailure.Network -> R.string.asr_network
        else -> R.string.asr_failed
    }

    // -- reading -------------------------------------------------------------

    private fun requestPageCapture() {
        // The camera is bound to the visible activity. Capturing from this
        // service would need a camera foreground-service type the app does not
        // declare yet.
        if (_captureRequests.subscriptionCount.value == 0) {
            say(R.string.read_open_app)
            return
        }
        listening?.cancel()
        reader.stop()
        arbiter.stopAll()
        say(R.string.read_hold_steady)
        _captureRequests.tryEmit(Unit)
    }

    private fun readImage(image: File) {
        lifecycleScope.launch {
            arbiter.submit(
                Announcement(text = "", priority = Priority.ANSWER, language = language, earcon = Earcon.CAPTURE_OK)
            )
            try {
                reader.readImage(image)
            } finally {
                if (image.canonicalPath.startsWith(cacheDir.canonicalPath)) image.delete()
            }
        }
    }

    private fun phraseText(phrase: PageReader.Phrase): Int = when (phrase) {
        PageReader.Phrase.NO_TEXT -> R.string.read_no_text
        PageReader.Phrase.FINISHED -> R.string.read_finished
        PageReader.Phrase.PAUSED -> R.string.read_paused
        PageReader.Phrase.NOT_READING -> R.string.read_nothing_open
    }

    // -- shared --------------------------------------------------------------

    private fun stopEverything() {
        listening?.cancel()
        reader.stop()
        arbiter.stopAll()
    }

    private fun repeatLast() {
        val last = lastSpoken
        when {
            reader.state.value != PageReader.State.IDLE -> reader.repeat()
            last != null -> arbiter.submit(last.copy(id = Announcement.nextId()))
            else -> say(R.string.nothing_to_repeat)
        }
    }

    private fun escalateEmergency() {
        stopEverything()
        submit(
            Announcement.hazard(
                text = text(R.string.sos_starting),
                language = language,
                haptic = HapticPattern.EMERGENCY,
                tag = "sos",
            )
        )
    }

    /**
     * The screen follows what the service is doing, not the arbiter's event
     * stream: an earcon-only announcement completes the instant it starts, so
     * arbiter events cannot say how long listening lasts.
     */
    private fun publishUiState() {
        _uiState.value = when {
            isListening -> VisionUiState.LISTENING
            reader.state.value != PageReader.State.IDLE -> VisionUiState.READING
            else -> VisionUiState.IDLE
        }
    }

    private fun say(@StringRes id: Int) {
        submit(Announcement.answer(text(id), language))
    }

    private fun submit(announcement: Announcement) {
        val worthRepeating = announcement.text.isNotBlank() &&
            announcement.priority != Priority.AMBIENT &&
            announcement.priority != Priority.LONGFORM
        if (worthRepeating) lastSpoken = announcement
        arbiter.submit(announcement)
    }

    /**
     * Speech follows the language chosen by voice, which can differ from the
     * phone's locale. Resolving strings against the locale instead hands a
     * Bangla voice English text.
     */
    private fun text(@StringRes id: Int): String {
        val cached = localized
        val res = if (cached != null && cached.first == language) {
            cached.second
        } else {
            val config = Configuration(resources.configuration).apply {
                setLocale(Locale.forLanguageTag(language.bcp47))
            }
            createConfigurationContext(config).resources.also { localized = language to it }
        }
        return res.getString(id)
    }

    private fun obstacleText(alert: ObstaclePolicy.Alert): String {
        val text = when {
            alert.isHeadHeight -> text(R.string.obstacle_head_height)
            alert.haptic == HapticPattern.OBSTACLE_LEFT -> text(R.string.obstacle_left)
            alert.haptic == HapticPattern.OBSTACLE_RIGHT -> text(R.string.obstacle_right)
            else -> text(R.string.obstacle_ahead)
        }
        // Belt and braces: the build already rejects banned phrases in string
        // resources, so a hit here means a string was assembled at runtime.
        check(SafetyLanguagePolicy.isCompliant(text)) { "Unsafe phrasing reached the arbiter: $text" }
        return text
    }

    private fun buildNotification(): Notification {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW)
        )

        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )

        return Notification.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.service_running))
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    companion object {
        const val ACTION_START_LISTENING = "bd.visionassistant.action.START_LISTENING"
        const val ACTION_STOP_SPEAKING = "bd.visionassistant.action.STOP_SPEAKING"
        const val ACTION_REPEAT = "bd.visionassistant.action.REPEAT"
        const val ACTION_READ_PAGE = "bd.visionassistant.action.READ_PAGE"
        const val ACTION_READ_IMAGE = "bd.visionassistant.action.READ_IMAGE"
        const val ACTION_CAPTURE_FAILED = "bd.visionassistant.action.CAPTURE_FAILED"
        const val ACTION_UTTERANCE = "bd.visionassistant.action.UTTERANCE"
        const val ACTION_READ_TEXT = "bd.visionassistant.action.READ_TEXT"

        const val EXTRA_PATH = "path"
        const val EXTRA_TEXT = "text"
        const val EXTRA_PERMISSION_MISSING = "permission_missing"

        private const val CHANNEL_ID = "vision_assistant_runtime"
        private const val NOTIFICATION_ID = 1
        private const val EARCON_SETTLE_MILLIS = 250L
        private const val MIN_SPEECH_RATE = 0.5f
        private const val MAX_SPEECH_RATE = 2.0f
        private val PARAGRAPH_BREAK = Regex("\\n\\s*\\n")

        private val _uiState = MutableStateFlow(VisionUiState.IDLE)
        val uiState: StateFlow<VisionUiState> = _uiState.asStateFlow()

        private val _captureRequests = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
        val captureRequests: SharedFlow<Unit> = _captureRequests.asSharedFlow()

        fun start(context: Context) {
            context.startForegroundService(Intent(context, VisionService::class.java))
        }

        fun send(context: Context, action: String, extras: Intent.() -> Unit = {}) {
            context.startService(Intent(context, VisionService::class.java).setAction(action).apply(extras))
        }
    }
}
