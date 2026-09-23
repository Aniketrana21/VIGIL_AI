package com.vigilai.service

import android.telecom.Call
import android.telecom.CallScreeningService
import android.util.Log
import com.vigilai.network.CallerLookupClient
import com.vigilai.network.CallerLookupResult
import com.vigilai.screening.CallMetadata
import com.vigilai.screening.LocalBlocklistManager
import com.vigilai.screening.ScreeningDecisionManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Android Mode B Telephony Call Screening Service.
 *
 * Automatically intercepts incoming cellular phone calls prior to ringing via Android Telecom framework.
 *
 * CRITICAL PLATFORM ARCHITECTURE CONSTRAINTS:
 * 1. Android's CallScreeningService does NOT have access to raw cellular call audio.
 *    Cellular call screening and real-time VoIP/WebRTC audio analysis are strictly separate components.
 * 2. Android Telecom enforces a 5-second hard deadline for respondToCall().
 * 3. NO heavy ML model inference is executed within this callback.
 * 4. Fast network lookup is supplemented by LocalBlocklistManager for instant offline rejection.
 * 5. Security Invariant: Never claim a caller is genuine solely because the phone number is known.
 */
class VigilCallScreeningService : CallScreeningService() {

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val tag = "VigilCallScreening"

    override fun onScreenCall(callDetails: Call.Details) {
        val startTime = System.currentTimeMillis()
        Log.i(tag, "CALL_SCREENING_STARTED: onScreenCall callback triggered by Android Telecom framework.")

        // 1. Extract dynamic Telecom metadata and multi-user device identity
        val metadata = CallMetadata.fromCallDetails(callDetails, context = applicationContext)
        val maskedCaller = metadata.toMaskedNumber()

        Log.i(tag, "CALL_SCREENING_RECEIVED: Call details received for caller: $maskedCaller (Raw: ${metadata.phoneNumber}, user: ${metadata.userId}, STIR/SHAKEN: ${metadata.callerNumberVerificationStatus})")
        Log.i(tag, "CALL_NUMBER_AVAILABLE: Phone number available: ${metadata.phoneNumber.isNotBlank()} (Number length: ${metadata.phoneNumber.length})")

        // 2. IMMEDIATE LOCAL BLOCKLIST CHECK: Zero-lag instant drop for known scam numbers
        if (LocalBlocklistManager.isBlocked(applicationContext, metadata.phoneNumber)) {
            Log.w(tag, "CALL_SCREENING_DECISION: LOCAL BLOCKLIST HIT for $maskedCaller: Immediately dropping and rejecting call via Telecom!")
            val immediateBlockResponse = CallResponse.Builder()
                .setDisallowCall(true)
                .setRejectCall(true)
                .setSkipCallLog(false)
                .setSkipNotification(false)
                .build()

            respondToCall(callDetails, immediateBlockResponse)
            val elapsed = System.currentTimeMillis() - startTime
            Log.i(tag, "CALL_SCREENING_COMPLETED: Instant rejection completed in ${elapsed}ms.")

            CallAlertOverlayService.showWarningAlert(
                context = applicationContext,
                caller = metadata.phoneNumber,
                riskScore = 1.0f,
                reason = "BLOCK: Caller explicitly listed in Blacklist directory"
            )

            // Asynchronously report decision audit to Supabase
            serviceScope.launch(Dispatchers.IO) {
                CallerLookupClient.reportDecision(
                    phoneNumber = metadata.phoneNumber,
                    action = "BLOCK",
                    reason = "Immediate rejection via Local Blocklist",
                    riskScore = 100,
                    userId = metadata.userId,
                    deviceId = metadata.deviceId
                )
            }
            return
        }

        // 3. Query VIGIL-AI Backend asynchronously within strict deadline
        serviceScope.launch {
            try {
                // Enforce maximum 3500ms budget for network + decision building
                val lookupResult: CallerLookupResult = withTimeoutOrNull(3500L) {
                    CallerLookupClient.lookupCaller(metadata)
                } ?: run {
                    Log.w(tag, "Lookup timed out beyond budget. Checking local fallback rules.")
                    val isBlockedLocally = LocalBlocklistManager.isBlocked(applicationContext, metadata.phoneNumber)
                    CallerLookupResult(
                        caller = com.vigilai.network.CallerProfileData(
                            id = null,
                            name = metadata.callerDisplayName ?: "Unverified Caller",
                            phone = metadata.phoneNumber,
                            company = null,
                            companyVerified = false,
                            trustStatus = if (isBlockedLocally) "blocked" else "neutral"
                        ),
                        history = com.vigilai.network.CallHistoryData(0, 0, 0, 0),
                        risk = com.vigilai.network.RiskData(
                            score = if (isBlockedLocally) 100 else 40,
                            level = if (isBlockedLocally) "CRITICAL" else "MEDIUM",
                            reasons = listOf(if (isBlockedLocally) "Known blocked number" else "Lookup timeout fallback")
                        ),
                        recommendedAction = if (isBlockedLocally) "BLOCK" else "MONITOR",
                        isFallback = true
                    )
                }

                // If backend confirmed BLOCK, persist to local blocklist for future zero-latency drops
                if (lookupResult.recommendedAction.equals("BLOCK", ignoreCase = true) || lookupResult.risk.score >= 55) {
                    LocalBlocklistManager.addBlocked(applicationContext, metadata.phoneNumber)
                }

                // 4. Build Telecom CallResponse according to configured security policy
                val callResponse = ScreeningDecisionManager.buildTelecomResponse(lookupResult)
                Log.i(tag, "CALL_SCREENING_DECISION: Recommendation=${lookupResult.recommendedAction}, RiskScore=${lookupResult.risk.score}")

                // 5. Respond to Android Telecom framework immediately
                respondToCall(callDetails, callResponse)

                val elapsed = System.currentTimeMillis() - startTime
                Log.i(tag, "CALL_SCREENING_COMPLETED: Responded to Telecom in ${elapsed}ms: Action=${lookupResult.recommendedAction} Risk=${lookupResult.risk.score}")

                // 6. Output formatted VIGIL-AI Incoming Call Screen & Caller Security Profile
                val incomingScreen = ScreeningDecisionManager.formatIncomingCallScreen(lookupResult)
                val securityProfile = ScreeningDecisionManager.formatCallerSecurityProfile(lookupResult)
                Log.i(tag, "\n$incomingScreen\n\n$securityProfile")

                // 7. Present Overlay Warning or HUD notification if suspicious or high risk
                if (lookupResult.risk.score >= 50 || lookupResult.recommendedAction in listOf("BLOCK", "VERIFY", "SILENCE")) {
                    CallAlertOverlayService.showWarningAlert(
                        context = applicationContext,
                        caller = metadata.phoneNumber,
                        riskScore = lookupResult.risk.score / 100.0f,
                        reason = "${lookupResult.recommendedAction}: ${lookupResult.risk.level} risk (${lookupResult.risk.reasons.firstOrNull() ?: "Review profile"})"
                    )
                }

                // 8. Asynchronously report decision audit back to Supabase PostgreSQL
                serviceScope.launch(Dispatchers.IO) {
                    CallerLookupClient.reportDecision(
                        phoneNumber = metadata.phoneNumber,
                        action = lookupResult.recommendedAction,
                        reason = lookupResult.risk.reasons.joinToString("; "),
                        riskScore = lookupResult.risk.score,
                        userId = metadata.userId,
                        deviceId = metadata.deviceId
                    )
                }

            } catch (e: Exception) {
                Log.e(tag, "Unexpected error screening call $maskedCaller: ${e.message}")
                val fallbackAction = if (LocalBlocklistManager.isBlocked(applicationContext, metadata.phoneNumber)) {
                    CallResponse.Builder().setDisallowCall(true).setRejectCall(true).build()
                } else {
                    CallResponse.Builder().setDisallowCall(false).setRejectCall(false).setSilenceCall(false).build()
                }
                respondToCall(callDetails, fallbackAction)
                Log.i(tag, "CALL_SCREENING_COMPLETED: Fallback response dispatched due to error.")
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        serviceScope.cancel()
    }
}
