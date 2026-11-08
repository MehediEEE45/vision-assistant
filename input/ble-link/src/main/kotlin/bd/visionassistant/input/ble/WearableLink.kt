package bd.visionassistant.input.ble

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.os.Build
import bd.visionassistant.protocol.DeviceEvent
import bd.visionassistant.protocol.DeviceState
import bd.visionassistant.protocol.Gatt
import bd.visionassistant.protocol.HapticCommand
import bd.visionassistant.protocol.SensorFrame
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * GATT client for the wearable.
 *
 * The watchdog is the important part. A BLE connection can stay nominally
 * "connected" while notifications silently stop — a firmware hang, a wedged
 * sensor, a stack bug. The user keeps walking, trusting a device that stopped
 * looking. So if no SensorFrame arrives within [Gatt.SENSOR_WATCHDOG_MILLIS],
 * [status] drops to [Status.DEGRADED] and the app says so out loud.
 *
 * Silent failure of a safety sensor is the worst behaviour this system can
 * have. Everything here is arranged to make that impossible.
 */
@SuppressLint("MissingPermission")
class WearableLink(
    private val context: Context,
    private val scope: CoroutineScope,
) {
    enum class Status { DISCONNECTED, CONNECTING, CONNECTED, DEGRADED, INCOMPATIBLE }

    private val _status = MutableStateFlow(Status.DISCONNECTED)
    val status: StateFlow<Status> = _status

    private val _frames = MutableSharedFlow<SensorFrame>(
        replay = 0,
        extraBufferCapacity = 64,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val frames: SharedFlow<SensorFrame> = _frames

    private val _events = MutableSharedFlow<DeviceEvent>(extraBufferCapacity = 16)
    val events: SharedFlow<DeviceEvent> = _events

    private val _deviceState = MutableStateFlow<DeviceState?>(null)
    val deviceState: StateFlow<DeviceState?> = _deviceState

    private var gatt: BluetoothGatt? = null
    private var hapticCharacteristic: BluetoothGattCharacteristic? = null

    @Volatile private var lastFrameAtMillis: Long = 0
    @Volatile private var droppedFrames: Long = 0
    private var lastSeq: Int = -1

    fun connect(address: String) {
        val adapter = BluetoothAdapter.getDefaultAdapter() ?: return
        val device: BluetoothDevice = adapter.getRemoteDevice(address)
        _status.value = Status.CONNECTING
        gatt = device.connectGatt(context, /* autoConnect = */ true, callback, BluetoothDevice.TRANSPORT_LE)
        startWatchdog()
    }

    fun disconnect() {
        gatt?.disconnect()
        gatt?.close()
        gatt = null
        _status.value = Status.DISCONNECTED
    }

    /**
     * Write-without-response, no acknowledgement awaited. The hazard haptic
     * budget is 60 ms from sensor to buzz; a round trip does not fit inside it.
     */
    fun sendHaptic(command: HapticCommand): Boolean {
        val characteristic = hapticCharacteristic ?: return false
        val connection = gatt ?: return false
        val payload = command.encode()

        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            connection.writeCharacteristic(
                characteristic,
                payload,
                BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE,
            ) == BluetoothStatusCodes_SUCCESS
        } else {
            @Suppress("DEPRECATION")
            characteristic.value = payload
            @Suppress("DEPRECATION")
            characteristic.writeType = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
            @Suppress("DEPRECATION")
            connection.writeCharacteristic(characteristic)
        }
    }

    /** Frames lost to radio conditions since connection, from the sequence counter. */
    fun droppedFrameCount(): Long = droppedFrames

    private fun startWatchdog() {
        scope.launch {
            while (isActive) {
                delay(Gatt.SENSOR_WATCHDOG_MILLIS / 2)
                val connected = _status.value == Status.CONNECTED || _status.value == Status.DEGRADED
                if (!connected) continue

                val silentFor = System.currentTimeMillis() - lastFrameAtMillis
                _status.value = if (silentFor > Gatt.SENSOR_WATCHDOG_MILLIS) {
                    Status.DEGRADED
                } else {
                    Status.CONNECTED
                }
            }
        }
    }

    private val callback = object : BluetoothGattCallback() {

        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    lastFrameAtMillis = System.currentTimeMillis()
                    gatt.requestMtu(64)
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    _status.value = Status.DISCONNECTED
                    hapticCharacteristic = null
                }
            }
        }

        override fun onMtuChanged(gatt: BluetoothGatt, mtu: Int, status: Int) {
            gatt.discoverServices()
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            val service = gatt.getService(Gatt.SERVICE)
            if (service == null) {
                _status.value = Status.INCOMPATIBLE
                return
            }

            hapticCharacteristic = service.getCharacteristic(Gatt.HAPTIC_CMD)

            listOf(Gatt.SENSOR_FRAME, Gatt.EVENT, Gatt.DEVICE_STATE).forEach { uuid ->
                service.getCharacteristic(uuid)?.let { enableNotifications(gatt, it) }
            }

            _status.value = Status.CONNECTED
        }

        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
        ) {
            dispatch(characteristic.uuid, value)
        }

        @Deprecated("Pre-Tiramisu callback, still delivered on older devices")
        override fun onCharacteristicChanged(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
        ) {
            @Suppress("DEPRECATION")
            characteristic.value?.let { dispatch(characteristic.uuid, it) }
        }
    }

    private fun dispatch(uuid: java.util.UUID, value: ByteArray) {
        when (uuid) {
            Gatt.SENSOR_FRAME -> {
                // A corrupt frame is discarded, never guessed at.
                val frame = SensorFrame.parse(value) ?: return
                lastFrameAtMillis = System.currentTimeMillis()
                trackSequence(frame.seq)
                _frames.tryEmit(frame)
            }
            Gatt.EVENT -> DeviceEvent.parse(value)?.let { _events.tryEmit(it) }
            Gatt.DEVICE_STATE -> DeviceState.parse(value)?.let { _deviceState.value = it }
        }
    }

    private fun trackSequence(seq: Int) {
        if (lastSeq >= 0) {
            val expected = (lastSeq + 1) and 0xFFFF
            if (seq != expected) {
                droppedFrames += ((seq - expected) and 0xFFFF).toLong()
            }
        }
        lastSeq = seq
    }

    private fun enableNotifications(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic) {
        gatt.setCharacteristicNotification(characteristic, true)
        val descriptor = characteristic.getDescriptor(Gatt.CLIENT_CHARACTERISTIC_CONFIG) ?: return

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            gatt.writeDescriptor(descriptor, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
        } else {
            @Suppress("DEPRECATION")
            descriptor.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            @Suppress("DEPRECATION")
            gatt.writeDescriptor(descriptor)
        }
    }
}

private const val BluetoothStatusCodes_SUCCESS = 0
