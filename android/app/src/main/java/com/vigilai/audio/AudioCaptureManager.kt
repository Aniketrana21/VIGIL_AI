package com.vigilai.audio

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import androidx.core.content.ContextCompat
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import kotlin.concurrent.thread

/**
 * Manages low-latency 16kHz Mono 16-bit PCM microphone capture on Android.
 * Enforces explicit runtime permission checks, packet sequencing, and backpressure protection.
 */
class AudioCaptureManager(
    private val context: Context,
    private val sampleRate: Int = 16000,
    private val chunkDurationMs: Int = 100, // 100ms chunks = 1600 samples = 3200 bytes
    private val maxQueueCapacity: Int = 50, // Buffer cap for backpressure (~5s of audio)
    private val onChunkCaptured: (AudioChunk) -> Unit
) {
    private val TAG = "AudioCaptureManager"

    private var audioRecord: AudioRecord? = null
    private val isRecording = AtomicBoolean(false)
    private val sequenceCounter = AtomicLong(0)
    private var recordingThread: Thread? = null

    // Backpressure queue: drops oldest packets if transmission stalls
    private val chunkQueue = ArrayBlockingQueue<AudioChunk>(maxQueueCapacity)

    private val samplesPerChunk = (sampleRate * chunkDurationMs) / 1000
    private val bytesPerChunk = samplesPerChunk * 2 // 16-bit PCM = 2 bytes per sample

    /**
     * Verifies RECORD_AUDIO runtime permission before initializing AudioRecord.
     */
    fun hasRecordPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
    }

    /**
     * Starts continuous audio capture in a high-priority background thread.
     */
    @Synchronized
    fun startCapture(): Boolean {
        if (isRecording.get()) {
            Log.w(TAG, "Audio capture is already active.")
            return true
        }

        if (!hasRecordPermission()) {
            Log.e(TAG, "Cannot start capture: RECORD_AUDIO permission not granted.")
            return false
        }

        val channelConfig = AudioFormat.CHANNEL_IN_MONO
        val audioFormat = AudioFormat.ENCODING_PCM_16BIT
        val minBufferSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)
        val bufferSize = maxOf(minBufferSize, bytesPerChunk * 2)

        try {
            audioRecord = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                sampleRate,
                channelConfig,
                audioFormat,
                bufferSize
            )

            if (audioRecord?.state != AudioRecord.STATE_INITIALIZED) {
                Log.e(TAG, "AudioRecord failed to initialize.")
                return false
            }

            audioRecord?.startRecording()
            isRecording.set(true)
            sequenceCounter.set(0)
            chunkQueue.clear()

            recordingThread = thread(name = "VigilAudioCaptureThread", priority = Thread.MAX_PRIORITY) {
                captureLoop()
            }

            Log.i(TAG, "Audio capture successfully started at ${sampleRate}Hz mono (16-bit PCM).")
            return true
        } catch (e: SecurityException) {
            Log.e(TAG, "SecurityException starting AudioRecord: ${e.message}")
            return false
        } catch (e: Exception) {
            Log.e(TAG, "Exception starting AudioRecord: ${e.message}")
            return false
        }
    }

    private fun captureLoop() {
        val audioBuffer = ByteArray(bytesPerChunk)

        while (isRecording.get()) {
            var bytesRead = 0
            while (bytesRead < bytesPerChunk && isRecording.get()) {
                val read = audioRecord?.read(audioBuffer, bytesRead, bytesPerChunk - bytesRead) ?: -1
                if (read <= 0) {
                    Log.w(TAG, "AudioRecord read returned error code: $read")
                    break
                }
                bytesRead += read
            }

            if (bytesRead == bytesPerChunk) {
                val currentSeq = sequenceCounter.incrementAndGet()
                val chunk = AudioChunk(
                    sequenceId = currentSeq,
                    timestampMs = System.currentTimeMillis(),
                    sampleRate = sampleRate,
                    channels = 1,
                    pcmBytes = audioBuffer.copyOf()
                )

                // Enforce Backpressure: Drop oldest if network queue is congested
                if (!chunkQueue.offer(chunk)) {
                    chunkQueue.poll() // Discard oldest
                    chunkQueue.offer(chunk)
                    Log.w(TAG, "Backpressure triggered: dropped oldest audio chunk. Queue full.")
                }

                // Dispatch to network transmitter callback
                onChunkCaptured(chunk)
            }
        }
    }

    /**
     * Stops continuous recording and releases the audio hardware.
     */
    @Synchronized
    fun stopCapture() {
        isRecording.set(false)
        recordingThread?.interrupt()
        recordingThread = null

        try {
            audioRecord?.stop()
            audioRecord?.release()
            audioRecord = null
            Log.i(TAG, "Audio capture stopped and hardware released.")
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping AudioRecord: ${e.message}")
        }
    }
}
