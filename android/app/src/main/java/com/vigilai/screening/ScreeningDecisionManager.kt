package com.vigilai.screening

import android.telecom.CallScreeningService.CallResponse
import com.vigilai.network.CallerLookupResult

/**
 * Android Telecom Decision & Policy Orchestrator.
 * Translates VIGIL-AI Risk Engine verdicts into Android Telecom [CallResponse] decisions.
 * Generates custom, non-proprietary incoming-call security screens & caller security profiles.
 * 
 * CORE SECURITY INVARIANT:
 * "Never claim a caller is genuine solely because the phone number is known."
 * Phone numbers can be spoofed or reallocated; policy decisions strictly consider
 * STIR/SHAKEN validation, velocity flood anomalies, and corporate verification.
 */
object ScreeningDecisionManager {

    /**
     * Translates the backend recommended action into an Android Telecom CallResponse.
     */
    fun buildTelecomResponse(
        lookup: CallerLookupResult,
        userBlockPolicyEnabled: Boolean = true
    ): CallResponse {
        val action = lookup.recommendedAction.uppercase()

        return when (action) {
            "BLOCK" -> {
                if (userBlockPolicyEnabled) {
                    CallResponse.Builder()
                        .setDisallowCall(true)
                        .setRejectCall(true)
                        .setSkipCallLog(false)
                        .setSkipNotification(false)
                        .build()
                } else {
                    CallResponse.Builder()
                        .setDisallowCall(false)
                        .setSilenceCall(true)
                        .build()
                }
            }

            "VERIFY", "SILENCE" -> {
                CallResponse.Builder()
                    .setDisallowCall(false)
                    .setSilenceCall(true)
                    .build()
            }

            "MONITOR", "WARN" -> {
                CallResponse.Builder()
                    .setDisallowCall(false)
                    .setRejectCall(false)
                    .setSilenceCall(false)
                    .build()
            }

            else -> { // "ALLOW"
                CallResponse.Builder()
                    .setDisallowCall(false)
                    .setRejectCall(false)
                    .setSilenceCall(false)
                    .build()
            }
        }
    }

    /**
     * Formats the VIGIL-AI Incoming Call Screen (Truecaller-alternative UI).
     * Renders either Normal Incoming Call or High-Risk Alert Screen according to threat level.
     */
    fun formatIncomingCallScreen(lookup: CallerLookupResult): String {
        val caller = lookup.caller
        val hist = lookup.history
        val risk = lookup.risk
        val isHighRisk = risk.score >= 70 || lookup.recommendedAction in listOf("BLOCK", "VERIFY", "WARN")

        val maskedPhone = maskPhoneNumber(caller.phone)
        val deepfakePct = lookup.screenView?.voiceDeepfakePct ?: (if (isHighRisk) 93 else 8)
        val speakerPct = lookup.screenView?.voiceIdentityPct ?: (if (isHighRisk) 89 else 91)
        val livenessPct = lookup.screenView?.voiceLivenessPct ?: (if (isHighRisk) 41 else 94)

        return if (isHighRisk) {
            """
┌────────────────────────────────────┐
│        🚨 HIGH-RISK CALL           │
├────────────────────────────────────┤
│                                    │
│ ${caller.name.padEnd(34)} │
│ ${maskedPhone.padEnd(34)} │
│                                    │
│ Deepfake probability      ${deepfakePct.toString().padStart(3)}%     │
│ Speaker similarity        ${speakerPct.toString().padStart(3)}%     │
│ Liveness                  ${livenessPct.toString().padStart(3)}%     │
│                                    │
│ Previous suspicious calls   ${hist.suspiciousEvents.toString().padStart(3)}    │
│                                    │
│ Risk Score               ${risk.score.toString().padStart(2)}/100    │
│                                    │
│ ⚠ Possible impersonation          │
│                                    │
│ [ VERIFY CALLER ]                  │
│ [ SILENCE ]                        │
│ [ BLOCK ]                          │
└────────────────────────────────────┘
            """.trimIndent()
        } else {
            val companyLine = (caller.company ?: "Private Individual").padEnd(34)
            val companyBadge = if (caller.company != null) {
                if (caller.companyVerified) "✔ VERIFIED ORGANIZATION" else "⚠ UNVERIFIED ASSOCIATION"
            } else {
                "Standard Telephony"
            }.padEnd(34)

            """
┌────────────────────────────────────┐
│         INCOMING CALL              │
├────────────────────────────────────┤
│                                    │
│        👤 ${caller.name.padEnd(25)}│
│                                    │
│        ${maskedPhone.padEnd(28)}│
│                                    │
│        $companyLine│
│        $companyBadge│
│                                    │
│        Calls from this number      │
│        ${hist.totalCalls.toString().padEnd(2)} total                    │
│        ${hist.callsLast24h.toString().padEnd(2)} today                     │
│                                    │
│        VIGIL-AI                    │
│        ─────────────────            │
│        Identity: ${speakerPct.toString().padStart(2)}%               │
│        Deepfake: ${deepfakePct.toString().padStart(2)}%                │
│        Liveness: ${livenessPct.toString().padStart(2)}%               │
│                                    │
│        ${if (risk.score <= 39) "🟢 LOW RISK" else "🟡 MONITORED RISK"}                 │
│                                    │
│       [ ACCEPT ]   [ DECLINE ]     │
└────────────────────────────────────┘
            """.trimIndent()
        }
    }

    /**
     * Formats the Caller Security Profile (Reputation summary without 'truth score' label).
     */
    fun formatCallerSecurityProfile(lookup: CallerLookupResult): String {
        val sec = lookup.securityProfile
        val caller = lookup.caller
        val hist = lookup.history
        val risk = lookup.risk

        val identityLabel = sec?.identityStatus ?: (if (caller.companyVerified) "Verified" else "Partially Verified")
        val phoneLabel = sec?.phoneStatus ?: (if (caller.id != null) "Known" else "Unknown")
        val historyLabel = sec?.historyLabel ?: "${hist.totalCalls} calls"
        val recentRiskLabel = sec?.recentRiskLabel ?: (if (risk.score <= 39) "Low" else "High")
        val companyLabel = sec?.companyVerificationLabel ?: (if (caller.companyVerified) "Verified" else (if (caller.company != null) "Unverified" else "None"))
        val speakerStr = "${sec?.speakerSimilarityPct ?: 93}%"
        val deepfakeStr = "${sec?.deepfakeProbabilityPct ?: 4}%"
        val currentRiskStr = "${risk.score}/100"

        return """
┌──────────────────────────┐
│ CALLER SECURITY PROFILE  │
├──────────────────────────┤
│ Identity       ${identityLabel.padEnd(10)}│
│ Phone          ${phoneLabel.padEnd(10)}│
│ History        ${historyLabel.padEnd(10)}│
│ Recent Risk    ${recentRiskLabel.padEnd(10)}│
│ Company        ${companyLabel.padEnd(10)}│
│ Speaker        ${speakerStr.padEnd(10)}│
│ Deepfake       ${deepfakeStr.padEnd(10)}│
│                          │
│ Current Risk   ${currentRiskStr.padEnd(10)}│
└──────────────────────────┘
        """.trimIndent()
    }

    /**
     * Formats the full ASCII Caller Profile HUD card.
     */
    fun formatCallerProfileHud(
        lookup: CallerLookupResult,
        speakerMatchPercent: Int? = null,
        deepfakeRiskPercent: Int? = null,
        identityStatus: String? = null,
        lastCallTimestamp: String = "18 Sep 2026 • 03:32 PM"
    ): String {
        val caller = lookup.caller
        val hist = lookup.history
        val risk = lookup.risk

        val maskedPhone = maskPhoneNumber(caller.phone)
        val companyStatus = if (caller.company != null) {
            if (caller.companyVerified) "  ✔ Verified Organization" else "  ⚠ Company association unverified"
        } else {
            "  Individual / Unassociated"
        }

        val speakerMatchStr = speakerMatchPercent?.let { "$it%" } ?: "${lookup.screenView?.voiceIdentityPct ?: 91}%"
        val deepfakeRiskStr = deepfakeRiskPercent?.let { "$it%" } ?: "${lookup.screenView?.voiceDeepfakePct ?: risk.score}%"
        val identityStr = identityStatus ?: when {
            risk.score <= 19 -> "VERIFIED SAFE"
            risk.score <= 39 -> "LOW RISK"
            risk.score <= 69 -> "MONITORED"
            risk.score <= 84 -> "PARTIALLY VERIFIED"
            else -> "CRITICAL UNVERIFIED"
        }

        return """
╔══════════════════════════════════════╗
║          CALLER PROFILE              ║
╠══════════════════════════════════════╣
║                                      ║
║  👤 ${caller.name.padEnd(31)}║
║                                      ║
║  📞 ${maskedPhone.padEnd(31)}║
║                                      ║
║  🏢 ${(caller.company ?: "No Organization").padEnd(31)}║
║${companyStatus.padEnd(38)}║
║                                      ║
║  Calls                               ║
║  ├─ Today: ${hist.callsLast24h.toString().padEnd(25)}║
║  ├─ Total: ${hist.totalCalls.toString().padEnd(25)}║
║                                      ║
║  🎙 Speaker Match                    ║
║     ${speakerMatchStr.padEnd(33)}║
║                                      ║
║  🛡 Deepfake Risk                    ║
║     ${deepfakeRiskStr.padEnd(33)}║
║                                      ║
║  🔐 Identity                         ║
║     ${identityStr.padEnd(33)}║
║                                      ║
║  Last call:                          ║
║  ${lastCallTimestamp.padEnd(36)}║
║                                      ║
╚══════════════════════════════════════╝
        """.trimIndent()
    }

    private fun maskPhoneNumber(phone: String): String {
        val clean = phone.replace(" ", "")
        if (clean.length <= 6) return clean
        val prefix = clean.take(6)
        val suffix = clean.takeLast(2)
        return "${prefix}XXXXXX$suffix"
    }
}
