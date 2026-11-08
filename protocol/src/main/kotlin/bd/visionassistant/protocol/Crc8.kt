package bd.visionassistant.protocol

/**
 * CRC-8 Dallas/Maxim (polynomial 0x31, reflected 0x8C, init 0x00).
 *
 * The same routine exists in firmware/include/vision_gatt.h. Both sides must
 * produce identical output for the vectors in Crc8Test — those vectors are the
 * cheapest possible guard against a silent endianness or polynomial mismatch
 * discovered three weeks into hardware bring-up.
 */
object Crc8 {
    private val TABLE = IntArray(256) { index ->
        var crc = index
        repeat(8) {
            crc = if (crc and 0x01 != 0) (crc shr 1) xor 0x8C else crc shr 1
        }
        crc
    }

    fun compute(data: ByteArray, offset: Int = 0, length: Int = data.size - offset): Int {
        require(offset >= 0 && length >= 0 && offset + length <= data.size) {
            "CRC range $offset..${offset + length} outside array of ${data.size}"
        }
        var crc = 0
        for (i in offset until offset + length) {
            crc = TABLE[(crc xor (data[i].toInt() and 0xFF)) and 0xFF]
        }
        return crc
    }

    /** Appends the CRC as the final byte. Used by the firmware simulator in tests. */
    fun seal(payload: ByteArray): ByteArray =
        payload + compute(payload).toByte()
}
