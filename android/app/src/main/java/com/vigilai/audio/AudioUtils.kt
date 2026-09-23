package com.vigilai.audio

import kotlin.math.log10
import kotlin.math.sqrt

/**
 * Utility functions for raw PCM audio manipulation, RMS calculation,
 * and 44-byte standard RIFF/WAV packaging for backend AI ingestion.
 */
object AudioUtils {

    /**
     * Wraps raw 16-bit PCM bytes into a standard 44-byte RIFF/WAV container
     * compatible with librosa, soundfile, Whisper, WavLM, and ECAPA-TDNN.
     */
    fun pcmToWav(
        pcmData: ByteArray,
        sampleRate: Int = 16000,
        channels: Int = 1,
        bitsPerSample: Int = 16
    ): ByteArray {
        val totalAudioLen = pcmData.size
        val totalDataLen = totalAudioLen + 36
        val byteRate = sampleRate * channels * (bitsPerSample / 8)
        val blockAlign = channels * (bitsPerSample / 8)

        val header = ByteArray(44)

        // 0-3: "RIFF"
        header[0] = 'R'.code.toByte()
        header[1] = 'I'.code.toByte()
        header[2] = 'F'.code.toByte()
        header[3] = 'F'.code.toByte()

        // 4-7: File size - 8
        header[4] = (totalDataLen and 0xff).toByte()
        header[5] = ((totalDataLen shr 8) and 0xff).toByte()
        header[6] = ((totalDataLen shr 16) and 0xff).toByte()
        header[7] = ((totalDataLen shr 24) and 0xff).toByte()

        // 8-11: "WAVE"
        header[8] = 'W'.code.toByte()
        header[9] = 'A'.code.toByte()
        header[10] = 'V'.code.toByte()
        header[11] = 'E'.code.toByte()

        // 12-15: "fmt "
        header[12] = 'f'.code.toByte()
        header[13] = 'm'.code.toByte()
        header[14] = 't'.code.toByte()
        header[15] = ' '.code.toByte()

        // 16-19: Subchunk1Size (16 for PCM format)
        header[16] = 16
        header[17] = 0
        header[18] = 0
        header[19] = 0

        // 20-21: AudioFormat (1 = Linear PCM)
        header[20] = 1
        header[21] = 0

        // 22-23: NumChannels
        header[22] = channels.toByte()
        header[23] = 0

        // 24-27: SampleRate
        header[24] = (sampleRate and 0xff).toByte()
        header[25] = ((sampleRate shr 8) and 0xff).toByte()
        header[26] = ((sampleRate shr 16) and 0xff).toByte()
        header[27] = ((sampleRate shr 24) and 0xff).toByte()

        // 28-31: ByteRate = SampleRate * NumChannels * BitsPerSample/8
        header[28] = (byteRate and 0xff).toByte()
        header[29] = ((byteRate shr 8) and 0xff).toByte()
        header[30] = ((byteRate shr 16) and 0xff).toByte()
        header[31] = ((byteRate shr 24) and 0xff).toByte()

        // 32-33: BlockAlign = NumChannels * BitsPerSample/8
        header[32] = blockAlign.toByte()
        header[33] = 0

        // 34-35: BitsPerSample
        header[34] = bitsPerSample.toByte()
        header[35] = 0

        // 36-39: "data" chunk header
        header[36] = 'd'.code.toByte()
        header[37] = 'a'.code.toByte()
        header[38] = 't'.code.toByte()
        header[39] = 'a'.code.toByte()

        // 40-43: Subchunk2Size = NumSamples * NumChannels * BitsPerSample/8
        header[40] = (totalAudioLen and 0xff).toByte()
        header[41] = ((totalAudioLen shr 8) and 0xff).toByte()
        header[42] = ((totalAudioLen shr 16) and 0xff).toByte()
        header[43] = ((totalAudioLen shr 24) and 0xff).toByte()

        val wavBuffer = ByteArray(44 + totalAudioLen)
        System.arraycopy(header, 0, wavBuffer, 0, 44)
        System.arraycopy(pcmData, 0, wavBuffer, 44, totalAudioLen)
        return wavBuffer
    }

    /**
     * Calculates RMS energy level in decibels (dBFS) for 16-bit PCM samples.
     */
    fun calculateRmsDb(pcmData: ByteArray): Float {
        if (pcmData.isEmpty()) return -100f

        var sumSquare = 0.0
        val sampleCount = pcmData.size / 2

        var i = 0
        while (i < pcmData.size - 1) {
            val sample = (pcmData[i].toInt() and 0xFF) or (pcmData[i + 1].toInt() shl 8)
            val shortSample = sample.toShort()
            val normalized = shortSample / 32768.0
            sumSquare += normalized * normalized
            i += 2
        }

        if (sampleCount == 0) return -100f
        val rms = sqrt(sumSquare / sampleCount)
        if (rms <= 0.00000001) return -100f
        val db = 20.0 * log10(rms)
        return db.toFloat()
    }
}
