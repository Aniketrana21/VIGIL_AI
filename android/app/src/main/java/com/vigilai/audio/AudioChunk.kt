package com.vigilai.audio

import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * AudioChunk data representation for Android streaming audio.
 * Encapsulates sequence numbers, timestamps, and 16-bit Linear PCM audio bytes.
 */
data class AudioChunk(
    val sequenceId: Long,
    val timestampMs: Long,
    val sampleRate: Int = 16000,
    val channels: Int = 1,
    val pcmBytes: ByteArray
) {
    val numSamples: Int
        get() = pcmBytes.size / 2

    val durationMs: Float
        get() = if (sampleRate > 0) (numSamples.toFloat() / sampleRate) * 1000f else 0f

    /**
     * Serializes chunk into the standard 28-byte binary protocol:
     * [Magic(4B: 'VIGI')][Sequence(8B)][Timestamp(8B)][SampleRate(4B)][Length(4B)][PCM Bytes...]
     */
    fun serializeBinary(): ByteArray {
        val headerSize = 28
        val buffer = ByteBuffer.allocate(headerSize + pcmBytes.size).order(ByteOrder.BIG_ENDIAN)

        // Magic "VIGI" (0x56494749)
        buffer.put('V'.code.toByte())
        buffer.put('I'.code.toByte())
        buffer.put('G'.code.toByte())
        buffer.put('I'.code.toByte())

        // Sequence ID (uint64)
        buffer.putLong(sequenceId)

        // Timestamp (uint64)
        buffer.putLong(timestampMs)

        // Sample rate (uint32)
        buffer.putInt(sampleRate)

        // Payload length (uint32)
        buffer.putInt(pcmBytes.size)

        // Raw PCM bytes
        buffer.put(pcmBytes)

        return buffer.array()
    }

    /**
     * Serializes chunk into JSON envelope with Base64 payload.
     */
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("type", "AUDIO_CHUNK")
            put("sequence_id", sequenceId)
            put("timestamp_ms", timestampMs)
            put("sample_rate", sampleRate)
            put("channels", channels)
            put("pcm_base64", android.util.Base64.encodeToString(pcmBytes, android.util.Base64.NO_WRAP))
        }
    }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (javaClass != other?.javaClass) return false
        other as AudioChunk
        return sequenceId == other.sequenceId && timestampMs == other.timestampMs
    }

    override fun hashCode(): Int {
        var result = sequenceId.hashCode()
        result = 31 * result + timestampMs.hashCode()
        return result
    }
}
