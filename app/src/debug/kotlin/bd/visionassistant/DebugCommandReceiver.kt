package bd.visionassistant

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class DebugCommandReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val action = when (intent.action) {
            "bd.visionassistant.debug.UTTERANCE" -> VisionService.ACTION_UTTERANCE
            "bd.visionassistant.debug.READ_TEXT" -> VisionService.ACTION_READ_TEXT
            "bd.visionassistant.debug.READ_IMAGE" -> VisionService.ACTION_READ_IMAGE
            "bd.visionassistant.debug.LISTEN" -> VisionService.ACTION_START_LISTENING
            "bd.visionassistant.debug.READ_PAGE" -> VisionService.ACTION_READ_PAGE
            "bd.visionassistant.debug.REPEAT" -> VisionService.ACTION_REPEAT
            "bd.visionassistant.debug.STOP" -> VisionService.ACTION_STOP_SPEAKING
            else -> return
        }
        VisionService.send(context, action) {
            intent.getStringExtra(VisionService.EXTRA_TEXT)?.let { putExtra(VisionService.EXTRA_TEXT, it) }
            intent.getStringExtra(VisionService.EXTRA_PATH)?.let { putExtra(VisionService.EXTRA_PATH, it) }
        }
    }
}
