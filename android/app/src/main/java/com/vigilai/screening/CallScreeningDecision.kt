package com.vigilai.screening

import android.os.Build
import android.telecom.CallScreeningService.CallResponse

/**
 * Supported screening actions per Android Telecom specifications.
 */
enum class ScreeningAction {
    ALLOW,    // Ring normally, allow user to answer
    SILENCE,  // Silence ringer, ring silently without disturbing user
    BLOCK     // Reject call immediately, suppress notifications
}

/**
 * Encapsulates the evaluation decision made by VIGIL-AI's screening layer.
 */
data class CallScreeningDecision(
    /**
     * Selected Telecom action (ALLOW, SILENCE, BLOCK).
     */
    val action: ScreeningAction,

    /**
     * Assessed risk score between 0.0 (safe) and 1.0 (dangerous).
     */
    val riskScore: Float,

    /**
     * User-facing explanation detailing why this decision was taken.
     */
    val explanation: String,

    /**
     * Whether this decision was produced as a safe preliminary fallback
     * (e.g., due to deadline expiration prior to completing deep secondary checks).
     */
    val isPreliminary: Boolean = false,

    /**
     * Time taken to reach decision in milliseconds.
     */
    val latencyMs: Long = 0L,

    /**
     * Optional secondary analysis task identifier if queued for background processing.
     */
    val secondaryTaskId: String? = null
) {
    /**
     * Builds the corresponding Android Telecom [CallResponse] to submit to [respondToCall].
     */
    fun toCallResponse(): CallResponse {
        val builder = CallResponse.Builder()
        when (action) {
            ScreeningAction.BLOCK -> {
                builder.setDisallowCall(true)
                builder.setRejectCall(true)
                builder.setSkipCallLog(false)
                builder.setSkipNotification(true)
            }
            ScreeningAction.SILENCE -> {
                builder.setDisallowCall(false)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    builder.setSilenceCall(true)
                }
            }
            ScreeningAction.ALLOW -> {
                builder.setDisallowCall(false)
            }
        }
        return builder.build()
    }

    /**
     * Formats an audit log entry that preserves privacy by masking PII.
     */
    fun toSecureAuditLog(maskedCaller: String): String {
        return "[AUDIT_LOG] caller=$maskedCaller action=$action score=%.2f preliminary=$isPreliminary latency=${latencyMs}ms explanation=\"$explanation\""
            .format(riskScore)
    }

    companion object {
        /**
         * Factory for safe preliminary decisions returned when the platform deadline is near.
         */
        fun createPreliminaryFallback(
            explanation: String = "Platform screening deadline reached: safe preliminary allow granted with background surveillance",
            latencyMs: Long = 0L,
            secondaryTaskId: String? = null
        ): CallScreeningDecision {
            return CallScreeningDecision(
                action = ScreeningAction.ALLOW,
                riskScore = 0.25f,
                explanation = explanation,
                isPreliminary = true,
                latencyMs = latencyMs,
                secondaryTaskId = secondaryTaskId
            )
        }
    }
}
