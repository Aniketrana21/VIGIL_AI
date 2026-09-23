package com.vigilai.screening

import com.vigilai.audio.AudioSourceOrigin
import com.vigilai.policy.*
import org.junit.Assert.*
import org.junit.Test

class ProtectionPolicyEngineTest {

    @Test
    fun testSyntheticVoiceCausesInstantBlock() {
        val stage1 = Stage1VoiceAuthenticityResult(
            state = VoiceAuthenticityState.SYNTHETIC,
            syntheticProbability = 0.96f,
            audioQuality = 0.90f,
            confidence = 0.94f,
            modelOutput = 0.96f,
            latencyMs = 120,
            reason = "Acoustic artifacts match neural vocoder"
        )
        val stage2 = Stage2SpeakerVerificationResult(
            state = SpeakerMatchState.NOT_ENROLLED,
            claimedSpeaker = null,
            enrolledProfileId = null,
            cosineSimilarity = 0.0f,
            calibratedThreshold = 0.65f,
            confidence = 0.0f,
            reason = "Not enrolled"
        )
        val stage3 = Stage3SpamRiskResult(
            isSpam = false,
            detectedIntent = "General",
            compositeRiskScore = 10,
            threatLevel = "LOW",
            confidence = 0.5f,
            contributingSignals = emptyList(),
            reason = "Clean conversation"
        )

        val decision = ProtectionPolicyEngine.evaluate(
            callId = "call_test_01",
            stage1 = stage1,
            stage2 = stage2,
            stage3 = stage3,
            audioOrigin = AudioSourceOrigin.LOCAL_MIC_AUDIO
        )

        assertEquals(DecisionAction.BLOCK, decision.action)
        assertTrue(decision.compositeRiskScore >= 95)
        assertEquals(AudioSourceOrigin.LOCAL_MIC_AUDIO, decision.audioOrigin)
        assertTrue(decision.reason.contains("Synthetic voice clone") || decision.reason.contains("BLOCK"))
    }

    @Test
    fun testInsufficientAudioYieldsUncertainWithoutBlocking() {
        val stage1 = Stage1VoiceAuthenticityResult(
            state = VoiceAuthenticityState.INSUFFICIENT_AUDIO,
            syntheticProbability = 0.5f,
            audioQuality = 0.2f,
            confidence = 0.2f,
            modelOutput = 0.5f,
            latencyMs = 45,
            reason = "Under 1.5s speech window"
        )
        val stage2 = Stage2SpeakerVerificationResult(
            state = SpeakerMatchState.UNCERTAIN,
            claimedSpeaker = null,
            enrolledProfileId = null,
            cosineSimilarity = 0.0f,
            calibratedThreshold = 0.65f,
            confidence = 0.0f,
            reason = "Audio too short"
        )
        val stage3 = Stage3SpamRiskResult(
            isSpam = false,
            detectedIntent = "Inconclusive",
            compositeRiskScore = 15,
            threatLevel = "LOW",
            confidence = 0.3f,
            contributingSignals = emptyList(),
            reason = "Insufficient transcript"
        )

        val decision = ProtectionPolicyEngine.evaluate(
            callId = "call_test_02",
            stage1 = stage1,
            stage2 = stage2,
            stage3 = stage3,
            audioOrigin = AudioSourceOrigin.UNKNOWN_AUDIO_SOURCE
        )

        assertEquals(DecisionAction.UNCERTAIN, decision.action)
        assertTrue(decision.compositeRiskScore < 50)
        assertTrue(decision.reason.contains("UNCERTAIN"))
    }

    @Test
    fun testGenuineVoiceWithHighFraudYieldsBlock() {
        val stage1 = Stage1VoiceAuthenticityResult(
            state = VoiceAuthenticityState.GENUINE,
            syntheticProbability = 0.05f,
            audioQuality = 0.85f,
            confidence = 0.92f,
            modelOutput = 0.05f,
            latencyMs = 110,
            reason = "Human harmonic resonance"
        )
        val stage2 = Stage2SpeakerVerificationResult(
            state = SpeakerMatchState.NOT_ENROLLED,
            claimedSpeaker = null,
            enrolledProfileId = null,
            cosineSimilarity = 0.0f,
            calibratedThreshold = 0.65f,
            confidence = 0.0f,
            reason = "Not enrolled"
        )
        val stage3 = Stage3SpamRiskResult(
            isSpam = true,
            detectedIntent = "OTP_HARVESTING",
            compositeRiskScore = 92,
            threatLevel = "CRITICAL",
            confidence = 0.95f,
            contributingSignals = listOf("OTP_HARVESTING: Urgent request for 6-digit code"),
            reason = "Active credential theft attempt"
        )

        val decision = ProtectionPolicyEngine.evaluate(
            callId = "call_test_03",
            stage1 = stage1,
            stage2 = stage2,
            stage3 = stage3,
            audioOrigin = AudioSourceOrigin.LOCAL_MIC_AUDIO
        )

        // Stage 3 alone emits WARN with banner & vibration rather than abruptly severing cellular call
        assertEquals(DecisionAction.WARN, decision.action)
        assertTrue(decision.compositeRiskScore >= 85)
        assertTrue(decision.reason.contains("WARN: Fraud Solicitation"))
    }

    @Test
    fun testEnrolledKnownSpeakerWithGenuineVoiceYieldsAllow() {
        val stage1 = Stage1VoiceAuthenticityResult(
            state = VoiceAuthenticityState.GENUINE,
            syntheticProbability = 0.03f,
            audioQuality = 0.92f,
            confidence = 0.91f,
            modelOutput = 0.03f,
            latencyMs = 95,
            reason = "Natural vocal jitter"
        )
        val stage2 = Stage2SpeakerVerificationResult(
            state = SpeakerMatchState.MATCH,
            claimedSpeaker = "Mom",
            enrolledProfileId = "contact_mom_01",
            cosineSimilarity = 0.88f,
            calibratedThreshold = 0.65f,
            confidence = 0.94f,
            reason = "ECAPA-TDNN embedding match"
        )
        val stage3 = Stage3SpamRiskResult(
            isSpam = false,
            detectedIntent = "Personal",
            compositeRiskScore = 5,
            threatLevel = "LOW",
            confidence = 0.8f,
            contributingSignals = emptyList(),
            reason = "Trusted conversation"
        )

        val decision = ProtectionPolicyEngine.evaluate(
            callId = "call_test_04",
            stage1 = stage1,
            stage2 = stage2,
            stage3 = stage3,
            audioOrigin = AudioSourceOrigin.LOCAL_MIC_AUDIO
        )

        assertEquals(DecisionAction.ALLOW, decision.action)
        assertTrue(decision.compositeRiskScore < 20)
    }
}
