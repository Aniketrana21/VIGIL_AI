package com.vigilai.service

import android.telecom.Call
import android.telecom.CallScreeningService
import android.util.Log
import com.vigilai.network.VigilApiClient
import com.vigilai.screening.CallMetadata
import com.vigilai.screening.CallRiskEngine
import com.vigilai.screening.CallScreeningDecision
import com.vigilai.screening.DefaultCallRiskEngine
import com.vigilai.screening.ScreeningAction
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Android Mode B Telephony Call Screening Service.
 *
 * Intercepts incoming cellular phone calls prior to ringing via Android Telecom framework.
 *
 * CRITICAL PLATFORM ARCHITECTURE CONSTRAINTS:
 * 1. Android's CallScreeningService does NOT provide raw two-way cellular audio streams.
 *    Cellular call screening and real-time audio analysis (mic/VoIP Mode A) are strictly separate components.
 * 2. Android enforces a 5-second hard deadline for respondToCall().
 * 3. NO heavy deep-learning ML model inference is executed within this callback.
 * 4. If deep analysis cannot complete within the deadline, a safe preliminary decision
 *    is returned immediately while secondary analysis proceeds asynchronously.
 */
class VigilCallScreeningService : CallScreeningService() {

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val tag = "VigilCallScreening"

    // Risk engine with 3500ms strict deadline (well within Android Telecom's 5000ms limit)
    var riskEngine: CallRiskEngine = DefaultCallRiskEngine(
        remoteClient = VigilApiClient,
        deadlineTimeoutMs = 3500L,
        onSecondaryAnalysisNeeded = { metadata, decision ->
            dispatchSecondaryAnalysis(metadata, decision)
        }
    )

    override fun onScreenCall(callDetails: Call.Details) {
        val startTime = System.currentTimeMillis()

        // 1. Detect incoming call and extract only exposed Telecom metadata
        val metadata = CallMetadata.fromCallDetails(callDetails)
        val maskedCaller = metadata.toMaskedNumber()

        Log.i(tag, "Incoming call detected: $maskedCaller (STIR/SHAKEN status: ${metadata.callerNumberVerificationStatus})")

        // 2. Evaluate via VIGIL-AI Risk Engine asynchronously within strict deadline
        serviceScope.launch {
            try {
                // Pass metadata to risk engine
                val decision = riskEngine.evaluate(metadata)

                // 3. Build Telecom CallResponse (ALLOW, SILENCE, or BLOCK)
                val callResponse = decision.toCallResponse()

                // 4. Respond to Android Telecom framework within the required timeout
                respondToCall(callDetails, callResponse)

                val elapsed = System.currentTimeMillis() - startTime
                Log.i(tag, "Responded to call $maskedCaller in ${elapsed}ms: action=${decision.action}")

                // 5. Provide explanation to user if flagged or silenced/blocked
                handleUserExplanation(metadata, decision)

            } catch (e: Exception) {
                Log.e(tag, "Unexpected error screening call $maskedCaller, returning safe ALLOW fallback: ${e.message}")
                val safeFallback = CallScreeningDecision.createPreliminaryFallback(
                    explanation = "Safe fallback due to service exception: ${e.message}"
                )
                respondToCall(callDetails, safeFallback.toCallResponse())
            }
        }
    }

    /**
     * Presents an explanation to the user via notification or heads-up overlay banner.
     */
    private fun handleUserExplanation(metadata: CallMetadata, decision: CallScreeningDecision) {
        when (decision.action) {
            ScreeningAction.BLOCK -> {
                Log.w(tag, "Blocking high-risk impersonation call from: ${metadata.toMaskedNumber()}")
                CallAlertOverlayService.showWarningAlert(
                    context = applicationContext,
                    caller = metadata.phoneNumber,
                    riskScore = decision.riskScore,
                    reason = "BLOCKED: ${decision.explanation}"
                )
            }
            ScreeningAction.SILENCE -> {
                Log.w(tag, "Silencing suspicious call from: ${metadata.toMaskedNumber()}")
                CallAlertOverlayService.showWarningAlert(
                    context = applicationContext,
                    caller = metadata.phoneNumber,
                    riskScore = decision.riskScore,
                    reason = "SILENCED: ${decision.explanation}"
                )
            }
            ScreeningAction.ALLOW -> {
                if (decision.isPreliminary) {
                    Log.i(tag, "Call permitted with active secondary background analysis: ${metadata.toMaskedNumber()}")
                } else {
                    Log.i(tag, "Call permitted cleanly: ${metadata.toMaskedNumber()}")
                }
            }
        }
    }

    /**
     * Continues secondary threat analysis asynchronously if preliminary decision was returned.
     */
    private fun dispatchSecondaryAnalysis(metadata: CallMetadata, decision: CallScreeningDecision) {
        Log.i(tag, "Dispatching secondary threat analysis for ${metadata.toMaskedNumber()} (Task: ${decision.secondaryTaskId})")
        serviceScope.launch(Dispatchers.IO) {
            try {
                // Secondary non-blocking analysis (e.g. external threat DB lookup, anomaly correlation)
                val riskResult = VigilApiClient.queryRisk(
                    phoneNumber = metadata.phoneNumber,
                    displayName = metadata.callerDisplayName,
                    stirShakenStatus = metadata.callerNumberVerificationStatus,
                    carrierCode = metadata.carrierCode
                )

                if (riskResult.action == ScreeningAction.BLOCK || riskResult.action == ScreeningAction.SILENCE) {
                    Log.w(tag, "Secondary analysis completed: Escalated risk detected for ${metadata.toMaskedNumber()}!")
                    CallAlertOverlayService.showWarningAlert(
                        context = applicationContext,
                        caller = metadata.phoneNumber,
                        riskScore = riskResult.riskScore,
                        reason = "LATE WARNING: ${riskResult.reason}"
                    )
                }
            } catch (e: Exception) {
                Log.w(tag, "Secondary analysis background task failed gracefully: ${e.message}")
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        serviceScope.cancel()
    }
}
