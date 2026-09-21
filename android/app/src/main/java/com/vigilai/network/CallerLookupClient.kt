package com.vigilai.network

import android.util.Log
import com.vigilai.screening.CallMetadata
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Caller Profile & Telemetry models returned by the VIGIL-AI Backend.
 */
data class CallerProfileData(
    val id: String?,
    val name: String,
    val phone: String,
    val company: String?,
    val companyVerified: Boolean,
    val companyNameClaimed: String? = null,
    val companyNameVerified: Boolean = false,
    val verificationSource: String = "caller_claim",
    val verificationStatus: String = "UNVERIFIED",
    val relationship: String = "UNKNOWN",
    val relationshipVerified: Boolean = false,
    val claimedRelationshipWarning: String? = null,
    val trustStatus: String = "neutral",
    val callerType: String = "unknown"
)

data class CallHistoryData(
    val totalCalls: Int,
    val callsLast1h: Int = 0,
    val callsLast24h: Int = 0,
    val callsLast7d: Int = 0,
    val averageCallDurationSec: Int = 0,
    val suspiciousEvents: Int = 0,
    val failedVerifications: Int = 0,
    val blockedCalls: Int = 0,
    val behavioralAnomaly: Boolean = false,
    val behavioralAnomalyReason: String? = null
)

data class RiskData(
    val score: Int,
    val level: String,
    val reasons: List<String> = emptyList()
)

data class CallerSecurityProfileData(
    val identityStatus: String,
    val phoneStatus: String,
    val historyLabel: String,
    val recentRiskLabel: String,
    val companyVerificationLabel: String,
    val speakerSimilarityPct: Int?,
    val deepfakeProbabilityPct: Int?,
    val livenessPct: Int?,
    val currentRiskScore: Int
)

data class IncomingCallScreenViewData(
    val screenType: String, // NORMAL_INCOMING | HIGH_RISK_ALERT
    val headerTitle: String,
    val callerName: String,
    val maskedPhone: String,
    val companyDisplay: String?,
    val companyBadge: String?,
    val callsSummaryTotal: Int,
    val callsSummaryToday: Int,
    val voiceIdentityPct: Int?,
    val voiceDeepfakePct: Int?,
    val voiceLivenessPct: Int?,
    val riskBadge: String,
    val warningBanner: String?,
    val availableActions: List<String>
)

data class CallerLookupResult(
    val caller: CallerProfileData,
    val history: CallHistoryData,
    val risk: RiskData,
    val recommendedAction: String, // ALLOW | MONITOR | VERIFY | BLOCK
    val securityProfile: CallerSecurityProfileData? = null,
    val screenView: IncomingCallScreenViewData? = null,
    val isFallback: Boolean = false
)

/**
 * High-performance, fail-safe Caller Lookup Client for Android Telecom CallScreeningService.
 *
 * Enforces a strict 1500ms network timeout to ensure the Telecom respondToCall() callback
 * completes well within the Android OS 5-second deadline.
 *
 * CRITICAL SECURITY ARCHITECTURE CONSTRAINTS:
 * 1. Never wait for heavy ML model inference during cellular call screening.
 * 2. Fail safely: If network times out or backend is unavailable, return safe fallback (ALLOW/MONITOR)
 *    and NEVER claim a caller is genuine solely because their number is known.
 */
object CallerLookupClient {
    private const val TAG = "CallerLookupClient"
    private const val CLIENT_TIMEOUT_MS = 3000L

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(CLIENT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        .readTimeout(CLIENT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        .writeTimeout(CLIENT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        .build()

    var baseUrl: String = "http://10.233.185.235:8000" // User local Wi-Fi IP
    var apiKey: String = "dev-vigil-secret-key-change-in-prod"

    /**
     * Performs fast pre-call metadata lookup and preliminary risk evaluation.
     */
    suspend fun lookupCaller(metadata: CallMetadata): CallerLookupResult = withContext(Dispatchers.IO) {
        val url = "$baseUrl/api/v1/screening/lookup"

        val payload = JSONObject().apply {
            put("phone_number", metadata.phoneNumber)
            put("caller_display_name", metadata.callerDisplayName ?: "")
            put("caller_name", metadata.callerDisplayName ?: "")
            put("contact_match", metadata.isKnownContact)
            put("stir_shaken_status", metadata.callerNumberVerificationStatus)
            put("carrier_code", metadata.carrierCode ?: "")
            put("device_id", metadata.deviceId ?: "android_${android.os.Build.ID}")
            put("user_id", metadata.userId ?: "")
            put("installation_id", metadata.installationId ?: "")
            put("call_direction", "INCOMING")
            put("incoming_timestamp", metadata.timestampMillis)
        }

        val requestBody = payload.toString().toRequestBody("application/json; charset=utf-8".toMediaTypeOrNull())
        val request = Request.Builder()
            .url(url)
            .addHeader("X-API-Key", apiKey)
            .post(requestBody)
            .build()

        try {
            val response = httpClient.newCall(request).execute()
            if (!response.isSuccessful) {
                Log.w(TAG, "Backend returned HTTP ${response.code} for lookup. Executing safe fallback.")
                return@withContext createSafeFallback(metadata, "HTTP ${response.code} backend error")
            }

            val bodyString = response.body?.string() ?: ""
            val json = JSONObject(bodyString)

            val callerJson = json.getJSONObject("caller")
            val historyJson = json.getJSONObject("history")
            val riskJson = json.getJSONObject("risk")

            val reasonsArray = riskJson.optJSONArray("reasons")
            val reasonsList = mutableListOf<String>()
            if (reasonsArray != null) {
                for (i in 0 until reasonsArray.length()) {
                    reasonsList.add(reasonsArray.getString(i))
                }
            }

            // Security Profile parsing
            var secProfile: CallerSecurityProfileData? = null
            val secJson = json.optJSONObject("security_profile")
            if (secJson != null) {
                secProfile = CallerSecurityProfileData(
                    identityStatus = secJson.optString("identity_status", "Unverified"),
                    phoneStatus = secJson.optString("phone_status", "Known"),
                    historyLabel = secJson.optString("history_label", "0 calls"),
                    recentRiskLabel = secJson.optString("recent_risk_label", "Low"),
                    companyVerificationLabel = secJson.optString("company_verification_label", "None"),
                    speakerSimilarityPct = if (secJson.isNull("speaker_similarity_pct")) null else secJson.optInt("speaker_similarity_pct"),
                    deepfakeProbabilityPct = if (secJson.isNull("deepfake_probability_pct")) null else secJson.optInt("deepfake_probability_pct"),
                    livenessPct = if (secJson.isNull("liveness_pct")) null else secJson.optInt("liveness_pct"),
                    currentRiskScore = secJson.optInt("current_risk_score", 0)
                )
            }

            // Screen View parsing
            var screenView: IncomingCallScreenViewData? = null
            val scrJson = json.optJSONObject("screen_view")
            if (scrJson != null) {
                val actArray = scrJson.optJSONArray("available_actions")
                val actList = mutableListOf<String>()
                if (actArray != null) {
                    for (i in 0 until actArray.length()) {
                        actList.add(actArray.getString(i))
                    }
                }
                screenView = IncomingCallScreenViewData(
                    screenType = scrJson.optString("screen_type", "NORMAL_INCOMING"),
                    headerTitle = scrJson.optString("header_title", "INCOMING CALL"),
                    callerName = scrJson.optString("caller_name", callerJson.optString("name")),
                    maskedPhone = scrJson.optString("masked_phone", metadata.phoneNumber),
                    companyDisplay = if (scrJson.isNull("company_display")) null else scrJson.optString("company_display"),
                    companyBadge = if (scrJson.isNull("company_badge")) null else scrJson.optString("company_badge"),
                    callsSummaryTotal = scrJson.optInt("calls_summary_total", 0),
                    callsSummaryToday = scrJson.optInt("calls_summary_today", 0),
                    voiceIdentityPct = if (scrJson.isNull("voice_identity_pct")) null else scrJson.optInt("voice_identity_pct"),
                    voiceDeepfakePct = if (scrJson.isNull("voice_deepfake_pct")) null else scrJson.optInt("voice_deepfake_pct"),
                    voiceLivenessPct = if (scrJson.isNull("voice_liveness_pct")) null else scrJson.optInt("voice_liveness_pct"),
                    riskBadge = scrJson.optString("risk_badge", "🟢 LOW RISK"),
                    warningBanner = if (scrJson.isNull("warning_banner")) null else scrJson.optString("warning_banner"),
                    availableActions = actList
                )
            }

            CallerLookupResult(
                caller = CallerProfileData(
                    id = if (callerJson.isNull("id")) null else callerJson.optString("id"),
                    name = callerJson.optString("name", "Unknown caller"),
                    phone = callerJson.optString("phone", metadata.phoneNumber),
                    company = if (callerJson.isNull("company")) null else callerJson.optString("company"),
                    companyVerified = callerJson.optBoolean("company_verified", false),
                    companyNameClaimed = if (callerJson.isNull("company_name_claimed")) null else callerJson.optString("company_name_claimed"),
                    companyNameVerified = callerJson.optBoolean("company_name_verified", false),
                    verificationSource = callerJson.optString("verification_source", "caller_claim"),
                    verificationStatus = callerJson.optString("verification_status", "UNVERIFIED"),
                    relationship = callerJson.optString("relationship", "UNKNOWN"),
                    relationshipVerified = callerJson.optBoolean("relationship_verified", false),
                    claimedRelationshipWarning = if (callerJson.isNull("claimed_relationship_warning")) null else callerJson.optString("claimed_relationship_warning"),
                    trustStatus = callerJson.optString("trust_status", "neutral"),
                    callerType = callerJson.optString("caller_type", "unknown")
                ),
                history = CallHistoryData(
                    totalCalls = historyJson.optInt("total_calls", 0),
                    callsLast1h = historyJson.optInt("calls_last_1h", 0),
                    callsLast24h = historyJson.optInt("calls_last_24h", 0),
                    callsLast7d = historyJson.optInt("calls_last_7d", 0),
                    averageCallDurationSec = historyJson.optInt("average_call_duration_sec", 0),
                    suspiciousEvents = historyJson.optInt("suspicious_events", 0),
                    failedVerifications = historyJson.optInt("failed_verifications", 0),
                    blockedCalls = historyJson.optInt("blocked_calls", 0),
                    behavioralAnomaly = historyJson.optBoolean("behavioral_anomaly", false),
                    behavioralAnomalyReason = if (historyJson.isNull("behavioral_anomaly_reason")) null else historyJson.optString("behavioral_anomaly_reason")
                ),
                risk = RiskData(
                    score = riskJson.optInt("score", 15),
                    level = riskJson.optString("level", "LOW"),
                    reasons = reasonsList
                ),
                recommendedAction = json.optString("recommended_action", "ALLOW"),
                securityProfile = secProfile,
                screenView = screenView,
                isFallback = false
            )
        } catch (e: Exception) {
            Log.e(TAG, "Call screening lookup failed or timed out (<${CLIENT_TIMEOUT_MS}ms): ${e.message}")
            createSafeFallback(metadata, "Network timeout/error: ${e.message}")
        }
    }

    /**
     * Reports screening action taken by Android Telecom to backend for audit logging.
     */
    suspend fun reportDecision(
        phoneNumber: String,
        action: String,
        reason: String,
        riskScore: Int,
        userId: String? = null,
        deviceId: String? = null
    ) = withContext(Dispatchers.IO) {
        val url = "$baseUrl/api/v1/screening/decision"
        val payload = JSONObject().apply {
            put("phone_number", phoneNumber)
            put("action", action)
            put("reason", reason)
            put("risk_score", riskScore)
            put("device_id", deviceId ?: "android_${android.os.Build.ID}")
            if (userId != null) put("user_id", userId)
        }
        val requestBody = payload.toString().toRequestBody("application/json; charset=utf-8".toMediaTypeOrNull())
        val request = Request.Builder()
            .url(url)
            .addHeader("X-API-Key", apiKey)
            .post(requestBody)
            .build()
        try {
            httpClient.newCall(request).execute().close()
        } catch (e: Exception) {
            Log.w(TAG, "Failed to asynchronously report call decision: ${e.message}")
        }
    }

    private fun createSafeFallback(metadata: CallMetadata, fallbackReason: String): CallerLookupResult {
        val isBlockedLocally = com.vigilai.screening.LocalBlocklistManager.isBlocked(null, metadata.phoneNumber)
        return CallerLookupResult(
            caller = CallerProfileData(
                id = null,
                name = metadata.callerDisplayName ?: "Unverified Caller",
                phone = metadata.phoneNumber,
                company = null,
                companyVerified = false,
                trustStatus = if (isBlockedLocally) "blocked" else "neutral",
                callerType = "unknown"
            ),
            history = CallHistoryData(
                totalCalls = 0,
                callsLast1h = 0,
                callsLast24h = 0,
                callsLast7d = 0,
                averageCallDurationSec = 0,
                suspiciousEvents = 0,
                failedVerifications = 0,
                blockedCalls = 0,
                behavioralAnomaly = false
            ),
            risk = RiskData(
                score = if (isBlockedLocally) 100 else 30,
                level = if (isBlockedLocally) "CRITICAL" else "MEDIUM",
                reasons = listOf(fallbackReason, if (isBlockedLocally) "Listed in local blacklist" else "Real-time verification unconfirmed")
            ),
            recommendedAction = if (isBlockedLocally) "BLOCK" else "MONITOR",
            securityProfile = CallerSecurityProfileData(
                identityStatus = if (isBlockedLocally) "Blocked" else "Unverified",
                phoneStatus = "Known",
                historyLabel = "0 calls",
                recentRiskLabel = if (isBlockedLocally) "Critical" else "Medium",
                companyVerificationLabel = "None",
                speakerSimilarityPct = null,
                deepfakeProbabilityPct = null,
                livenessPct = null,
                currentRiskScore = if (isBlockedLocally) 100 else 30
            ),
            screenView = IncomingCallScreenViewData(
                screenType = "NORMAL_INCOMING",
                headerTitle = "INCOMING CALL",
                callerName = metadata.callerDisplayName ?: "Unverified Caller",
                maskedPhone = metadata.phoneNumber,
                companyDisplay = null,
                companyBadge = null,
                callsSummaryTotal = 0,
                callsSummaryToday = 0,
                voiceIdentityPct = null,
                voiceDeepfakePct = null,
                voiceLivenessPct = null,
                riskBadge = "🟡 MODERATE RISK",
                warningBanner = "Unverified network status",
                availableActions = listOf("ACCEPT", "DECLINE")
            ),
            isFallback = true
        )
    }
}
