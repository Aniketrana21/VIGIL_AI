package com.vigilai.storage

import android.content.Context
import android.util.Log
import com.vigilai.screening.ThreeStageEvaluation
import org.json.JSONArray
import org.json.JSONObject

/**
 * Audit record representing an AI evaluation performed on an incoming or ongoing call.
 */
data class CallAuditRecord(
    val callId: String,
    val phoneNumber: String,
    val callerName: String? = null,
    val timestamp: Long = System.currentTimeMillis(),
    val verdict: String, // ALLOW, BLOCK, WARN, CHALLENGE
    val riskScore: Int,
    val threatLevel: String,
    val isClone: Boolean,
    val cloneProbability: Float,
    val isSpeakerMatched: Boolean,
    val similarityScore: Float,
    val matchedPersonName: String?,
    val matchedRelation: String?,
    val callerIntent: String,
    val isSpam: Boolean,
    val spamScore: Float,
    val transcript: String? = null,
    val explanation: String,
    val actionTaken: String,
    val audioOrigin: String = "LOCAL_MIC_AUDIO",
    val latencyMs: Long = 0L
) {
    fun toJson(): JSONObject {
        return JSONObject().apply {
            put("call_id", callId)
            put("phone_number", phoneNumber)
            put("caller_name", callerName ?: "")
            put("timestamp", timestamp)
            put("verdict", verdict)
            put("risk_score", riskScore)
            put("threat_level", threatLevel)
            put("is_clone", isClone)
            put("clone_probability", cloneProbability.toDouble())
            put("is_speaker_matched", isSpeakerMatched)
            put("similarity_score", similarityScore.toDouble())
            put("matched_person_name", matchedPersonName ?: "")
            put("matched_relation", matchedRelation ?: "")
            put("caller_intent", callerIntent)
            put("is_spam", isSpam)
            put("spam_score", spamScore.toDouble())
            put("transcript", transcript ?: "")
            put("explanation", explanation)
            put("action_taken", actionTaken)
            put("audio_origin", audioOrigin)
            put("latency_ms", latencyMs)
        }
    }

    companion object {
        fun fromJson(json: JSONObject): CallAuditRecord {
            return CallAuditRecord(
                callId = json.optString("call_id", ""),
                phoneNumber = json.optString("phone_number", "Unknown"),
                callerName = json.optString("caller_name").let { if (it.isBlank()) null else it },
                timestamp = json.optLong("timestamp", System.currentTimeMillis()),
                verdict = json.optString("verdict", "ALLOW"),
                riskScore = json.optInt("risk_score", 0),
                threatLevel = json.optString("threat_level", "LOW"),
                isClone = json.optBoolean("is_clone", false),
                cloneProbability = json.optDouble("clone_probability", 0.0).toFloat(),
                isSpeakerMatched = json.optBoolean("is_speaker_matched", false),
                similarityScore = json.optDouble("similarity_score", 0.0).toFloat(),
                matchedPersonName = json.optString("matched_person_name").let { if (it.isBlank()) null else it },
                matchedRelation = json.optString("matched_relation").let { if (it.isBlank()) null else it },
                callerIntent = json.optString("caller_intent", "NOMINAL"),
                isSpam = json.optBoolean("is_spam", false),
                spamScore = json.optDouble("spam_score", 0.0).toFloat(),
                transcript = json.optString("transcript").let { if (it.isBlank()) null else it },
                explanation = json.optString("explanation", ""),
                actionTaken = json.optString("action_taken", "ALLOW"),
                audioOrigin = json.optString("audio_origin", "LOCAL_MIC_AUDIO"),
                latencyMs = json.optLong("latency_ms", 0L)
            )
        }
    }
}

/**
 * Local persistent storage for VIGIL-AI screening and real-time call evaluations.
 * Maps phone numbers to their latest AI screening audit results for display in Call Logs.
 */
object CallAuditRepository {
    private const val TAG = "CallAuditRepo"
    private const val PREFS_NAME = "vigil_call_audit_prefs"
    private const val KEY_AUDITS = "call_audits_json"
    private const val MAX_AUDITS = 100

    private val memoryCache = mutableListOf<CallAuditRecord>()
    private var isLoaded = false

    private fun normalize(number: String?): String {
        if (number.isNullOrBlank()) return ""
        return number.replace(Regex("[^0-9+]"), "")
    }

    private fun ensureLoaded(context: Context) {
        if (isLoaded) return
        try {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val jsonStr = prefs.getString(KEY_AUDITS, null)
            memoryCache.clear()
            if (!jsonStr.isNullOrBlank()) {
                val array = JSONArray(jsonStr)
                for (i in 0 until array.length()) {
                    val obj = array.getJSONObject(i)
                    memoryCache.add(CallAuditRecord.fromJson(obj))
                }
            }
            isLoaded = true
        } catch (e: Exception) {
            Log.e(TAG, "Error loading audits: ${e.message}")
        }
    }

    private fun persist(context: Context) {
        try {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val array = JSONArray()
            for (audit in memoryCache.take(MAX_AUDITS)) {
                array.put(audit.toJson())
            }
            prefs.edit().putString(KEY_AUDITS, array.toString()).apply()
        } catch (e: Exception) {
            Log.e(TAG, "Error persisting audits: ${e.message}")
        }
    }

    @Synchronized
    fun saveAudit(context: Context, record: CallAuditRecord) {
        ensureLoaded(context)
        // Insert at beginning (newest first)
        memoryCache.removeAll { it.callId == record.callId }
        memoryCache.add(0, record)
        if (memoryCache.size > MAX_AUDITS) {
            memoryCache.removeAt(memoryCache.size - 1)
        }
        persist(context)
        Log.i(TAG, "Saved AI audit record for ${record.phoneNumber}: verdict=${record.verdict}, risk=${record.riskScore}")
    }

    @Synchronized
    fun getLatestAuditForNumber(context: Context, phoneNumber: String): CallAuditRecord? {
        ensureLoaded(context)
        val norm = normalize(phoneNumber)
        return memoryCache.firstOrNull { normalize(it.phoneNumber) == norm }
    }

    @Synchronized
    fun getAllAudits(context: Context): List<CallAuditRecord> {
        ensureLoaded(context)
        return ArrayList(memoryCache)
    }

    @Synchronized
    fun clearAll(context: Context) {
        memoryCache.clear()
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().remove(KEY_AUDITS).apply()
    }
}
