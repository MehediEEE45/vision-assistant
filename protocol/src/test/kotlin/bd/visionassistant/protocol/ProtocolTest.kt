package bd.visionassistant.protocol

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Cross-checks the Kotlin codec against the firmware header.
 *
 * The CRC vectors below are the cheapest possible guard against a silent
 * polynomial or endianness mismatch — the kind you otherwise discover three
 * weeks into hardware bring-up, after a fortnight of blaming the radio.
 * Run the same vectors through vision_crc8() in firmware/include/vision_gatt.h
 * on the ESP32 and compare.
 */
class Crc8Test {

    @Test
    fun `matches the CRC-8 Maxim check value`() {
        // The standard check value for this algorithm over "123456789".
        assertEquals(0xA1, Crc8.compute("123456789".toByteArray()))
    }

    @Test
    fun `known vectors`() {
        assertEquals(0x00, Crc8.compute(ByteArray(0)))
        assertEquals(0x5E, Crc8.compute(byteArrayOf(0x01)))
    }
}

class SensorFrameTest {

    /** seq=1, left=1500mm, centre=800mm, head=no return, 1000mg, dt=50ms, pitch=2, roll=-3. */
    private val goodFrame = byteArrayOf(
        1, 0,
        220.toByte(), 5,
        32, 3,
        255.toByte(), 255.toByte(),
        232.toByte(), 3,
        50, 0,
        2,
        253.toByte(),
        0x0F,
        255.toByte(),
    )

    @Test
    fun `parses a well formed frame`() {
        val frame = assertNotNull(SensorFrame.parse(goodFrame))
        assertEquals(1, frame.seq)
        assertEquals(1_500, frame.tofLeftMm)
        assertEquals(800, frame.tofCentreMm)
        assertEquals(SensorFrame.NO_RETURN, frame.tofHeadMm)
        assertEquals(1_000, frame.accelMilliG)
        assertEquals(50, frame.dtMillis)
        assertEquals(2, frame.pitchDeg)
        assertEquals(-3, frame.rollDeg)
        assertTrue(frame.isWalking)
    }

    @Test
    fun `a corrupt frame is discarded, never guessed at`() {
        val corrupted = goodFrame.copyOf().also { it[4] = 0x7F }
        assertNull(SensorFrame.parse(corrupted))
    }

    @Test
    fun `a truncated frame is discarded`() {
        assertNull(SensorFrame.parse(goodFrame.copyOf(12)))
    }

    @Test
    fun `valid ranges come back nearest first and exclude no-return readings`() {
        val frame = assertNotNull(SensorFrame.parse(goodFrame))
        val ranges = frame.validRanges()
        assertEquals(listOf(RangeSensor.CENTRE to 800, RangeSensor.LEFT to 1_500), ranges)
    }

    @Test
    fun `sequence gaps are visible to the caller`() {
        // Frame layout keeps seq first precisely so a dropped-frame count is
        // cheap. BLE uptime and dropped frames are both dashboard metrics.
        val frame = assertNotNull(SensorFrame.parse(goodFrame))
        assertEquals(1, frame.seq)
    }
}

class HapticCommandTest {

    @Test
    fun `encodes to exactly four bytes in wire order`() {
        val encoded = HapticCommand(motorMask = 0x01, patternId = 0x10, intensity = 200, repeat = 3).encode()
        assertEquals(HapticCommand.SIZE_BYTES, encoded.size)
        assertEquals(0x01, encoded[0].toInt() and 0xFF)
        assertEquals(0x10, encoded[1].toInt() and 0xFF)
        assertEquals(200, encoded[2].toInt() and 0xFF)
        assertEquals(3, encoded[3].toInt() and 0xFF)
    }

    @Test
    fun `silence stops every motor`() {
        val encoded = HapticCommand.SILENCE.encode()
        assertEquals(0, encoded[0].toInt())
        assertEquals(0, encoded[2].toInt())
    }
}

class WearableConfigTest {

    @Test
    fun `round trips through the wire format`() {
        val config = WearableConfig(
            tofHzWalking = 10,
            tofHzStationary = 1,
            imuHz = 50,
            hapticGain = 200,
            fallImpactMilliG = 2_500,
            fallFreefallMilliG = 400,
        )
        val decoded = assertNotNull(WearableConfig.parse(config.encode()))
        assertEquals(config, decoded)
    }
}
