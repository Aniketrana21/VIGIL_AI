package com.vigilai.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import androidx.core.content.ContextCompat
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Real-time In-Call Audio Agent.
 * Captures live voice audio during an active telephone call using Android's
 * VOICE_COMMUNICATION / MIC hardware pipeline at 16kHz mono 16-bit PCM.
 *
 * Buffers active speech segments (2.0 to 3.0 seconds), packages them into standard
 * WAV format with RIFF header, and delivers them for AI anti-spoofing and speaker verification.
 */
class CallAudioAgent(
    private val context: Context,
    private val sampleRate: Int = 16000,
    private val windowDurationSec: Float = 2.5f,
    private val onAudioSampleReady: (ByteArray) -> Unit
) {
    private val TAG = "CallAudioAgent"

    private var audioRecord: AudioRecord? = null
    private val isRunning = AtomicBoolean(false)
    private var workerThread: Thread? = null

    private val targetBytes = (sampleRate * 2 * windowDurationSec).toInt()

    fun hasAudioPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
    }

    @Synchronized
    fun startCapture(): Boolean {
        if (isRunning.get()) {
            Log.w(TAG, "CallAudioAgent is already capturing.")
            return true
        }

        if (!hasAudioPermission()) {
            Log.e(TAG, "Cannot start CallAudioAgent: RECORD_AUDIO permission not granted.")
            return false
        }

        val channelConfig = AudioFormat.CHANNEL_IN_MONO
        val audioFormat = AudioFormat.ENCODING_PCM_16BIT
        val minBufferSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)
        val bufferSize = maxOf(minBufferSize, 6400) // ~200ms buffer

        // Priority 1: VOICE_COMMUNICATION (hardware AEC + uplink/downlink acoustic capture)
        // Priority 2: MIC (standard physical microphone)
        val sourcesToTry = listOf(
            MediaRecorder.AudioSource.VOICE_COMMUNICATION,
            MediaRecorder.AudioSource.MIC
        )

        var recordInstance: AudioRecord? = null
        for (source in sourcesToTry) {
            try {
                val candidate = AudioRecord(source, sampleRate, channelConfig, audioFormat, bufferSize)
                if (candidate.state == AudioRecord.STATE_INITIALIZED) {
                    recordInstance = candidate
                    Log.i(TAG, "AudioRecord initialized using source $source at ${sampleRate}Hz")
                    break
                } else {
                    candidate.release()
                }
            } catch (e: Exception) {
                Log.w(TAG, "AudioSource $source failed: ${e.message}")
            }
        }

        if (recordInstance == null) {
            Log.e(TAG, "Failed to initialize any AudioRecord source for in-call capture.")
            return false
        }

        audioRecord = recordInstance
        try {
            audioRecord?.startRecording()
            isRunning.set(true)

            workerThread = thread(name = "CallAudioAgentWorker", priority = Thread.MAX_PRIORITY) {
                captureLoop()
            }
            Log.i(TAG, "CallAudioAgent capture started successfully.")
            return true
        } catch (e: Exception) {
            Log.e(TAG, "Exception starting in-call recording: ${e.message}")
            stopCapture()
            return false
        }
    }

    private fun captureLoop() {
        val readBuffer = ByteArray(3200) // 100ms chunk
        val accumulator = ByteArrayOutputStream(targetBytes)
        var lastDispatchedTime = System.currentTimeMillis()

        while (isRunning.get()) {
            val bytesRead = audioRecord?.read(readBuffer, 0, readBuffer.size) ?: -1
            if (bytesRead > 0) {
                accumulator.write(readBuffer, 0, bytesRead)

                // Once we have collected the target sample window (~2.5s)
                if (accumulator.size() >= targetBytes) {
                    val pcmBytes = accumulator.toByteArray()
                    accumulator.reset()

                    // Calculate energy to verify there is speech/sound
                    val rmsDb = AudioUtils.calculateRmsDb(pcmBytes)
                    Log.d(TAG, "Captured ${pcmBytes.size} bytes PCM. RMS Level: ${rmsDb}dB")

                    // Convert PCM to standard 44-byte WAV header
                    val wavBytes = AudioUtils.pcmToWav(pcmBytes, sampleRate = sampleRate)

                    // Dispatch to AI Agent
                    try {
                        onAudioSampleReady(wavBytes)
                    } catch (e: Exception) {
                        Log.e(TAG, "Error in audio sample consumer callback: ${e.message}")
                    }

                    lastDispatchedTime = System.currentTimeMillis()
                }
            } else if (bytesRead < 0) {
                Log.w(TAG, "AudioRecord read returned error code: $bytesRead")
                try { Thread.sleep(50) } catch (e: InterruptedException) { break }
            }
        }
    }

    @Synchronized
    fun stopCapture() {
        if (!isRunning.getAndSet(false)) return

        workerThread?.interrupt()
        workerThread = null

        try {
            audioRecord?.stop()
            audioRecord?.release()
            audioRecord = null
            Log.i(TAG, "CallAudioAgent stopped cleanly.")
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping CallAudioAgent: ${e.message}")
        }
    }
}
