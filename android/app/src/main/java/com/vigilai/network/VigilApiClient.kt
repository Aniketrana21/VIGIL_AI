package com.vigilai.network

import android.util.Log
import com.vigilai.screening.RemoteRiskResponse
import com.vigilai.screening.ScreeningAction
import com.vigilai.screening.ScreeningRemoteClient
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit

enum class Action {
    ALLOW, WARN, BLOCK
}

data class CallerRiskResult(
    val action: Action,
    val riskScore: Float,
    val reason: String
)

/**
 * Networking client for REST and WebSocket interactions with VIGIL-AI Backend.
 * Implements [ScreeningRemoteClient] for incoming-call screening evaluations.
 */
object VigilApiClient : ScreeningRemoteClient {
    private val client = OkHttpClient.Builder()
        .connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(3, TimeUnit.SECONDS)
        .build()

    var backendBaseUrl = "http://10.233.185.235:8000" // User local Wi-Fi IP
    var apiKey = "vigil-ai-hackathon-demo-key-2026"

    override suspend fun queryRisk(
        phoneNumber: String,
        displayName: String?,
        stirShakenStatus: Int,
        carrierCode: String?
    ): RemoteRiskResponse {
        val legacy = queryCallerRisk(
            phoneNumber = phoneNumber,
            displayName = displayName ?: "",
            stirShakenStatus = stirShakenStatus
        )
        val action = when (legacy.action) {
            Action.BLOCK -> ScreeningAction.BLOCK
            Action.WARN -> ScreeningAction.SILENCE
            Action.ALLOW -> ScreeningAction.ALLOW
        }
        return RemoteRiskResponse(
            action = action,
            riskScore = legacy.riskScore,
            reason = legacy.reason
        )
    }

    fun queryCallerRisk(
        phoneNumber: String,
        displayName: String,
        stirShakenStatus: Int
    ): CallerRiskResult {
        val url = "$backendBaseUrl/api/v1/screening/evaluate"

        val json = JSONObject().apply {
            put("device_id", "android_${android.os.Build.ID}")
            put("phone_number", phoneNumber)
            put("caller_display_name", displayName)
            put("stir_shaken_status", stirShakenStatus)
            put("timestamp", System.currentTimeMillis())
        }

        val mediaType = "application/json; charset=utf-8".toMediaTypeOrNull()
        val requestBody = RequestBody.create(mediaType, json.toString())

        val request = Request.Builder()
            .url(url)
            .addHeader("X-API-Key", apiKey)
            .post(requestBody)
            .build()

        return try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                return CallerRiskResult(Action.ALLOW, 0.1f, "API check failed, allow by default")
            }
            val respBody = response.body?.string() ?: ""
            val respJson = JSONObject(respBody)

            val actionStr = respJson.optString("action", "ALLOW")
            val score = respJson.optDouble("risk_score", 0.1).toFloat()
            val reason = respJson.optString("reason", "Call evaluated")

            val action = when (actionStr.uppercase()) {
                "BLOCK" -> Action.BLOCK
                "WARN" -> Action.WARN
                else -> Action.ALLOW
            }

            CallerRiskResult(action, score, reason)
        } catch (e: Exception) {
            Log.e("VigilApiClient", "Error contacting backend: ${e.message}")
            CallerRiskResult(Action.ALLOW, 0.1f, "Network error: ${e.message}")
        }
    }
}

object VigilWebSocketClient {
    private var webSocket: WebSocket? = null
    private val client = OkHttpClient.Builder().build()
    var onTerminationRequested: (() -> Unit)? = null

    fun connect(wsUrl: String) {
        val request = Request.Builder().url(wsUrl).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                Log.i("VigilWebSocket", "WebSocket connected: $wsUrl")
            }

            override fun onMessage(ws: WebSocket, text: String) {
                Log.d("VigilWebSocket", "Verdict received: $text")
                try {
                    val json = org.json.JSONObject(text)
                    val action = json.optString("action")
                    val type = json.optString("type")
                    val event = json.optString("event")
                    if (action.equals("TERMINATE", ignoreCase = true) ||
                        action.equals("BLOCK", ignoreCase = true) ||
                        type.equals("CALL_TERMINATED", ignoreCase = true) ||
                        event.equals("call_terminated", ignoreCase = true)) {
                        Log.w("VigilWebSocket", "🛑 Critical fraud threat verdict received: Enforcing automatic call termination!")
                        onTerminationRequested?.invoke()
                    }
                } catch (e: Exception) {
                    // non-fatal parse error
                }
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                Log.e("VigilWebSocket", "WebSocket failure: ${t.message}")
            }
        })
    }

    fun sendAudioChunk(bytes: ByteArray) {
        webSocket?.send(bytes.toByteString(0, bytes.size))
    }

    fun disconnect() {
        webSocket?.close(1000, "Service stopped")
        webSocket = null
        onTerminationRequested = null
    }
}
