package com.vigilai.service

import android.app.Service
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.IBinder
import android.util.Log
import com.vigilai.network.VigilWebSocketClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Android MODE A (VoIP & Ambient Loudspeaker Streamer).
 * Captures microphone audio at 16kHz Mono 16-bit PCM and streams binary chunks
 * directly over a TLS WebSocket connection to the VIGIL-AI Backend for near real-time analysis.
 */
class AudioStreamVoipService : Service() {
    private val TAG = "AudioStreamVoip"
    private val serviceJob = Job()
    private val scope = CoroutineScope(Dispatchers.IO + serviceJob)

    private var audioRecord: AudioRecord? = null
    private var isRecording = false

    private val sampleRate = 16000
    private val channelConfig = AudioFormat.CHANNEL_IN_MONO
    private val audioFormat = AudioFormat.ENCODING_PCM_16BIT
    private val bufferSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat) * 2

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val serverWsUrl = intent?.getStringExtra("EXTRA_WS_URL") ?: com.vigilai.config.VigilConfig.getWsUrl(this)
        startStreaming(serverWsUrl)
        return START_STICKY
    }

    private fun startStreaming(serverWsUrl: String) {
        if (isRecording) return
        isRecording = true

        scope.launch {
            try {
                // Connect WebSocket and wire automatic termination handler
                VigilWebSocketClient.onTerminationRequested = {
                    Log.w(TAG, "AudioStreamVoipService: Enforcing immediate call termination due to critical fraud threat verdict!")
                    stopRecording()
                    stopSelf()
                }
                VigilWebSocketClient.connect(serverWsUrl)

                audioRecord = AudioRecord(
                    MediaRecorder.AudioSource.MIC,
                    sampleRate,
                    channelConfig,
                    audioFormat,
                    bufferSize
                )

                audioRecord?.startRecording()
                Log.i(TAG, "AudioRecord started at 16000Hz mono. Streaming to $serverWsUrl")

                val audioBuffer = ByteArray(bufferSize)

                while (isActive && isRecording) {
                    val bytesRead = audioRecord?.read(audioBuffer, 0, audioBuffer.size) ?: 0
                    if (bytesRead > 0) {
                        val chunkToSend = audioBuffer.copyOf(bytesRead)
                        VigilWebSocketClient.sendAudioChunk(chunkToSend)
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Streaming audio error: ${e.message}", e)
            } finally {
                stopRecording()
            }
        }
    }

    private fun stopRecording() {
        isRecording = false
        try {
            audioRecord?.stop()
            audioRecord?.release()
            audioRecord = null
            VigilWebSocketClient.disconnect()
            Log.i(TAG, "Audio streaming stopped cleanly.")
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping audio: ${e.message}")
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        stopRecording()
        serviceJob.cancel()
    }
}
