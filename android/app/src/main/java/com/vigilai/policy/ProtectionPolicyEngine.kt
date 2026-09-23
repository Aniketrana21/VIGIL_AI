package com.vigilai.policy

import com.vigilai.audio.AudioSourceOrigin

/**
 * Production-Safe Decision Verdicts issued by the Policy Engine.
 */
enum class DecisionAction {
    ALLOW,
    WARN,
    CHALLENGE,
    BLOCK,
    UNCERTAIN
}

/**
 * Stage 1: Production-Safe Voice Authenticity States.
 */
enum class VoiceAuthenticityState {
    GENUINE,
    SYNTHETIC,
    UNCERTAIN,
    INSUFFICIENT_AUDIO
}

data class Stage1VoiceAuthenticityResult(
    val state: VoiceAuthenticityState,
    val syntheticProbability: Float,
    val audioQuality: Float, // 0.0 to 1.0 (SNR / energy)
    val confidence: Float, // 0.0 to 1.0
    val modelOutput: Float,
    val latencyMs: Long,
    val reason: String
)

/**
 * Stage 2: ECAPA-TDNN Speaker Verification States.
 */
enum class SpeakerMatchState {
    MATCH,
    MISMATCH,
    UNCERTAIN,
    NOT_ENROLLED
}

data class Stage2SpeakerVerificationResult(
    val state: SpeakerMatchState,
    val claimedSpeaker: String?,
    val enrolledProfileId: String?,
    val cosineSimilarity: Float,
    val calibratedThreshold: Float, // Calibrated EER decision boundary (e.g. 0.65)
    val confidence: Float,
    val reason: String
)

/**
 * Stage 3: Fraud & Intent Risk Analysis.
 */
data class Stage3SpamRiskResult(
    val isSpam: Boolean,
    val detectedIntent: String,
    val compositeRiskScore: Int, // 0 to 100
    val threatLevel: String, // LOW, MEDIUM, HIGH, CRITICAL
    val confidence: Float,
    val contributingSignals: List<String>,
    val reason: String
)

/**
 * Central Policy Engine Decision Output.
 * AI models do NOT directly execute irreversible telecom drop actions;
 * they provide probabilistic signals to this engine.
 */
data class ProtectionDecision(
    val callId: String,
    val action: DecisionAction,
    val compositeRiskScore: Int,
    val confidence: Float,
    val stage1: Stage1VoiceAuthenticityResult,
    val stage2: Stage2SpeakerVerificationResult,
    val stage3: Stage3SpamRiskResult,
    val audioOrigin: AudioSourceOrigin,
    val reason: String,
    val timestamp: Long = System.currentTimeMillis()
)

/**
 * VIGIL-AI Production Policy Engine.
 * Decoupled decision authority enforcing safety rules:
 * - When model confidence is low or audio is insufficient, NEVER issue an unverified BLOCK.
 * - Targeted clone (high similarity to enrolled contact + high synthetic score) triggers immediate BLOCK.
 * - Impersonation (claims enrolled identity but biometric mismatch) triggers immediate BLOCK.
 * - Clean voice + verified speaker -> ALLOW.
 */
object ProtectionPolicyEngine {

    fun evaluate(
        callId: String,
        stage1: Stage1VoiceAuthenticityResult,
        stage2: Stage2SpeakerVerificationResult,
        stage3: Stage3SpamRiskResult,
        audioOrigin: AudioSourceOrigin = AudioSourceOrigin.LOCAL_MIC_AUDIO
    ): ProtectionDecision {
        var riskScore = stage3.compositeRiskScore
        val reasons = mutableListOf<String>()

        // 1. Safeguard: Insufficient Audio or Low SNR
        if (stage1.state == VoiceAuthenticityState.INSUFFICIENT_AUDIO || stage1.audioQuality < 0.25f) {
            return ProtectionDecision(
                callId = callId,
                action = DecisionAction.UNCERTAIN,
                compositeRiskScore = minOf(45, riskScore),
                confidence = 0.30f,
                stage1 = stage1,
                stage2 = stage2,
                stage3 = stage3,
                audioOrigin = audioOrigin,
                reason = "UNCERTAIN: Insufficient speech audio or degraded SNR. Bypassing irreversible block action to prevent false positive."
            )
        }

        // 2. Stage 1 Deepfake Evaluation
        if (stage1.state == VoiceAuthenticityState.SYNTHETIC && stage1.confidence >= 0.65f) {
            riskScore = maxOf(riskScore, 95)
            reasons.add("Synthetic voice clone detected (Probability: ${(stage1.syntheticProbability * 100).toInt()}%, Conf: ${(stage1.confidence * 100).toInt()}%)")

            // Synergy: Targeted clone attack (attacker cloned enrolled victim)
            if (stage2.state == SpeakerMatchState.MATCH) {
                reasons.add("Targeted Impersonation: Synthetic voice matched to enrolled voiceprint '${stage2.claimedSpeaker}'. Severe threat.")
            }

            return ProtectionDecision(
                callId = callId,
                action = DecisionAction.BLOCK,
                compositeRiskScore = 99,
                confidence = stage1.confidence,
                stage1 = stage1,
                stage2 = stage2,
                stage3 = stage3,
                audioOrigin = audioOrigin,
                reason = "BLOCK: " + reasons.joinToString("; ")
            )
        }

        // 3. Stage 2 Biometric Speaker Evaluation
        if (stage2.state == SpeakerMatchState.MISMATCH && stage2.confidence >= 0.70f) {
            riskScore = maxOf(riskScore, 90)
            reasons.add("Biometric Mismatch: Caller claimed '${stage2.claimedSpeaker}' but similarity (${(stage2.cosineSimilarity * 100).toInt()}%) fell below calibrated threshold (${(stage2.calibratedThreshold * 100).toInt()}%)")

            return ProtectionDecision(
                callId = callId,
                action = DecisionAction.BLOCK,
                compositeRiskScore = riskScore,
                confidence = stage2.confidence,
                stage1 = stage1,
                stage2 = stage2,
                stage3 = stage3,
                audioOrigin = audioOrigin,
                reason = "BLOCK: Identity Impersonation - " + reasons.joinToString("; ")
            )
        }

        // 4. Stage 3 Fraud & Intent Evaluation
        if (stage3.isSpam && stage3.compositeRiskScore >= 85) {
            reasons.add("Conversation Intelligence: Severe fraud phrase / extortion detected (${stage3.detectedIntent})")
            return ProtectionDecision(
                callId = callId,
                action = DecisionAction.WARN,
                compositeRiskScore = stage3.compositeRiskScore,
                confidence = stage3.confidence,
                stage1 = stage1,
                stage2 = stage2,
                stage3 = stage3,
                audioOrigin = audioOrigin,
                reason = "WARN: Fraud Solicitation - " + reasons.joinToString("; ")
            )
        }

        // 5. Unenrolled / Unknown Caller
        if (stage2.state == SpeakerMatchState.NOT_ENROLLED) {
            reasons.add("Caller is not in verified contacts. Monitoring active.")
            return ProtectionDecision(
                callId = callId,
                action = if (riskScore > 50) DecisionAction.CHALLENGE else DecisionAction.ALLOW,
                compositeRiskScore = maxOf(20, riskScore),
                confidence = 0.80f,
                stage1 = stage1,
                stage2 = stage2,
                stage3 = stage3,
                audioOrigin = audioOrigin,
                reason = "ALLOW / MONITOR: Natural speech verified from unverified contact."
            )
        }

        // 6. Nominal Clean Call
        return ProtectionDecision(
            callId = callId,
            action = DecisionAction.ALLOW,
            compositeRiskScore = minOf(15, riskScore),
            confidence = 0.95f,
            stage1 = stage1,
            stage2 = stage2,
            stage3 = stage3,
            audioOrigin = audioOrigin,
            reason = "ALLOW: Natural human speech and verified relationship confirmed."
        )
    }
}
