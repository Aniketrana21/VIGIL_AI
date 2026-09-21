package com.vigilai.screening

import android.util.Log
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Interface for the remote risk engine screening client.
 */
interface ScreeningRemoteClient {
    suspend fun queryRisk(
        phoneNumber: String,
        displayName: String?,
        stirShakenStatus: Int,
        carrierCode: String?
    ): RemoteRiskResponse
}

data class RemoteRiskResponse(
    val action: ScreeningAction,
    val riskScore: Float,
    val reason: String
)

/**
 * Contract for evaluating incoming call metadata under strict real-time deadlines.
 */
interface CallRiskEngine {
    /**
     * Evaluates incoming [CallMetadata] and produces a [CallScreeningDecision].
     * Must complete within the platform deadline (typically < 3500ms).
     */
    suspend fun evaluate(metadata: CallMetadata): CallScreeningDecision
}

/**
 * Production implementation of VIGIL-AI's real-time incoming call risk engine.
 *
 * Enforces:
 * 1. Strict latency budget (< deadlineTimeoutMs) to avoid OS Telecom timeouts.
 * 2. NO deep learning / ML model inference on the initial call screening path.
 * 3. Two-stage screening: safe preliminary decision on deadline expiry with secondary analysis.
 * 4. Local fast-path overrides (blacklists, verified contacts).
 * 5. Secure audit logging masking PII.
 */
class DefaultCallRiskEngine(
    private val remoteClient: ScreeningRemoteClient? = null,
    private val blacklistedNumbers: Set<String> = emptySet(),
    private val trustedContacts: Set<String> = emptySet(),
    private val deadlineTimeoutMs: Long = 3500L,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val onSecondaryAnalysisNeeded: ((CallMetadata, CallScreeningDecision) -> Unit)? = null
) : CallRiskEngine {

    private val tag = "VigilCallRiskEngine"

    override suspend fun evaluate(metadata: CallMetadata): CallScreeningDecision {
        val startTime = System.currentTimeMillis()
        val maskedNumber = metadata.toMaskedNumber()

        // 1. Synthesize local verification signals
        val signal = CallVerificationSignal.fromMetadata(
            metadata = metadata,
            blacklistedNumbers = blacklistedNumbers,
            trustedContacts = trustedContacts
        )

        // 2. Fast-path local rule: Known scam blacklist
        if (signal.isBlacklisted) {
            val latency = System.currentTimeMillis() - startTime
            val decision = CallScreeningDecision(
                action = ScreeningAction.BLOCK,
                riskScore = 1.0f,
                explanation = "Blocked: ${signal.explanation}",
                isPreliminary = false,
                latencyMs = latency
            )
            logAudit(decision, maskedNumber)
            return decision
        }

        // 3. Fast-path local rule: Trusted device contact
        if (signal.isKnownContact) {
            val latency = System.currentTimeMillis() - startTime
            val decision = CallScreeningDecision(
                action = ScreeningAction.ALLOW,
                riskScore = 0.0f,
                explanation = "Allowed: ${signal.explanation}",
                isPreliminary = false,
                latencyMs = latency
            )
            logAudit(decision, maskedNumber)
            return decision
        }

        // 4. Fast-path local rule: STIR/SHAKEN Cryptographic Verification Failed
        // High confidence spoofing indicator
        if (signal.stirShakenLevel == StirShakenLevel.VERIFICATION_FAILED) {
            val latency = System.currentTimeMillis() - startTime
            val decision = CallScreeningDecision(
                action = ScreeningAction.SILENCE,
                riskScore = 0.75f,
                explanation = "Silenced: Carrier STIR/SHAKEN cryptographic check failed (caller ID spoofing risk)",
                isPreliminary = false,
                latencyMs = latency
            )
            logAudit(decision, maskedNumber)
            return decision
        }

        // 5. Fast-path local rule: Verified STIR/SHAKEN with clean caller ID
        if (signal.stirShakenLevel == StirShakenLevel.VERIFIED_PASSED && signal.flaggedKeywords.isEmpty()) {
            val latency = System.currentTimeMillis() - startTime
            val decision = CallScreeningDecision(
                action = ScreeningAction.ALLOW,
                riskScore = 0.05f,
                explanation = "Allowed: Carrier STIR/SHAKEN identity verified",
                isPreliminary = false,
                latencyMs = latency
            )
            logAudit(decision, maskedNumber)
            return decision
        }

        // 6. Timed evaluation path with remote backend intelligence
        // Strictly guarded by deadlineTimeoutMs to comply with Android Telecom 5s timeout.
        val decision = try {
            withTimeoutOrNull(deadlineTimeoutMs) {
                withContext(ioDispatcher) {
                    evaluateWithRemoteOrHeuristics(metadata, signal, startTime)
                }
            } ?: run {
                // Timeout reached before remote response completed!
                val latency = System.currentTimeMillis() - startTime
                Log.w(tag, "Screening timed out after ${latency}ms for $maskedNumber. Returning safe preliminary allow.")
                val fallback = CallScreeningDecision.createPreliminaryFallback(
                    explanation = "Screening timeout: Safe preliminary allow granted. Secondary background check active.",
                    latencyMs = latency,
                    secondaryTaskId = "sec_${System.currentTimeMillis()}"
                )
                // Trigger secondary background analysis
                onSecondaryAnalysisNeeded?.invoke(metadata, fallback)
                fallback
            }
        } catch (e: Exception) {
            val latency = System.currentTimeMillis() - startTime
            Log.e(tag, "Exception during screening evaluation for $maskedNumber: ${e.message}")
            CallScreeningDecision.createPreliminaryFallback(
                explanation = "Safe fallback due to evaluation error: ${e.message}",
                latencyMs = latency
            )
        }

        logAudit(decision, maskedNumber)
        return decision
    }

    private suspend fun evaluateWithRemoteOrHeuristics(
        metadata: CallMetadata,
        signal: CallVerificationSignal,
        startTime: Long
    ): CallScreeningDecision {
        if (remoteClient != null) {
            val remoteResp = remoteClient.queryRisk(
                phoneNumber = metadata.phoneNumber,
                displayName = metadata.callerDisplayName,
                stirShakenStatus = metadata.callerNumberVerificationStatus,
                carrierCode = metadata.carrierCode
            )
            val latency = System.currentTimeMillis() - startTime
            return CallScreeningDecision(
                action = remoteResp.action,
                riskScore = remoteResp.riskScore,
                explanation = remoteResp.reason,
                isPreliminary = false,
                latencyMs = latency
            )
        }

        // Local heuristic fallback when remote client is not configured
        val latency = System.currentTimeMillis() - startTime
        val score = signal.summarySignalScore
        val action = when {
            score >= 0.85f -> ScreeningAction.BLOCK
            score >= 0.50f -> ScreeningAction.SILENCE
            else -> ScreeningAction.ALLOW
        }

        return CallScreeningDecision(
            action = action,
            riskScore = score,
            explanation = signal.explanation,
            isPreliminary = false,
            latencyMs = latency
        )
    }

    private fun logAudit(decision: CallScreeningDecision, maskedNumber: String) {
        val auditLine = decision.toSecureAuditLog(maskedNumber)
        Log.i(tag, auditLine)
    }
}
