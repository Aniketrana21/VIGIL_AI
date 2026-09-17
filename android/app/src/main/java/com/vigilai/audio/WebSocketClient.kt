package com.vigilai.audio

import android.util.Log
import okhttp3.*
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

interface StreamingTelemetryListener {
    fun onConnectionStateChanged(state: String)
    fun onTelemetryReceived(telemetryJson: JSONObject)
    fun onError(errorMessage: String)
}

/**
 * Resilient OkHttp WebSocket client for real-time PCM audio streaming.
 * Implements exponential backoff reconnection, binary frame transport, and telemetry events.
 */
class WebSocketClient(
    private val serverUrl: String,
    private val telemetryListener: StreamingTelemetryListener? = null
) {
    private val TAG = "VigilWebSocketClient"

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .pingInterval(5, TimeUnit.SECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private val isConnected = AtomicBoolean(false)
    private val shouldReconnect = AtomicBoolean(true)
    private var reconnectAttempts = 0

    fun connect() {
        shouldReconnect.set(true)
        val request = Request.Builder().url(serverUrl).build()

        telemetryListener?.onConnectionStateChanged("CONNECTING")
        Log.i(TAG, "Connecting to audio stream ingest: $serverUrl")

        webSocket = httpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                isConnected.set(true)
                reconnectAttempts = 0
                telemetryListener?.onConnectionStateChanged("CONNECTED")
                Log.i(TAG, "WebSocket connection established.")

                // Send config handshake
                val config = JSONObject().apply {
                    put("type", "CONFIG")
                    put("data", JSONObject().apply {
                        put("sample_rate", 16000)
                        put("window_seconds", 2.0)
                    })
                }
                ws.send(config.toString())
            }

            override fun onMessage(ws: WebSocket, text: String) {
                try {
                    val json = JSONObject(text)
                    telemetryListener?.onTelemetryReceived(json)
                } catch (e: Exception) {
                    Log.e(TAG, "Error parsing telemetry text: ${e.message}")
                }
            }

            override fun onClosing(ws: WebSocket, code: Int, reason: String) {
                isConnected.set(false)
                telemetryListener?.onConnectionStateChanged("CLOSING")
                Log.w(TAG, "WebSocket closing: $code / $reason")
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                isConnected.set(false)
                telemetryListener?.onConnectionStateChanged("DISCONNECTED")
                Log.i(TAG, "WebSocket closed: $code / $reason")
                scheduleReconnect()
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                isConnected.set(false)
                telemetryListener?.onConnectionStateChanged("DISCONNECTED")
                telemetryListener?.onError(t.message ?: "Network failure")
                Log.e(TAG, "WebSocket failure: ${t.message}", t)
                scheduleReconnect()
            }
        })
    }

    /**
     * Sends an AudioChunk serialized in the 28-byte binary format.
     */
    fun sendAudioChunk(chunk: AudioChunk): Boolean {
        if (!isConnected.get() || webSocket == null) {
            return false
        }
        val binaryData = chunk.serializeBinary()
        return webSocket?.send(binaryData.toByteString(0, binaryData.size)) ?: false
    }

    private fun scheduleReconnect() {
        if (!shouldReconnect.get()) return

        reconnectAttempts++
        val backoffDelayMs = minOf(10000L, (1000L * Math.pow(1.5, reconnectAttempts.toDouble())).toLong())
        Log.i(TAG, "Scheduling reconnect in ${backoffDelayMs}ms (attempt $reconnectAttempts)")

        Thread {
            try {
                Thread.sleep(backoffDelayMs)
                if (shouldReconnect.get()) {
                    connect()
                }
            } catch (ignored: InterruptedException) { }
        }.start()
    }

    fun disconnect() {
        shouldReconnect.set(false)
        isConnected.set(false)
        webSocket?.close(1000, "Client disconnect requested")
        webSocket = null
        telemetryListener?.onConnectionStateChanged("DISCONNECTED")
    }
}
