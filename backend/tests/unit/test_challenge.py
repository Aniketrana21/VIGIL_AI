import time
import numpy as np
import pytest
import scipy.signal
import torch

from app.pipeline.challenge_service import AdaptiveChallengeService, ChallengeGenerator
from app.schemas.challenge import (
    CHALLENGE_PLATFORM_DISCLAIMER,
    DEFAULT_CONSENT_DISCLOSURE,
    ChallengeStatus,
    ChallengeTriggerReason,
    ChallengeVerificationRequest,
)


SAMPLE_RATE = 16000


def create_test_speech(duration_s: float = 1.5, f0: float = 130.0) -> torch.Tensor:
    t = np.linspace(0, duration_s, int(SAMPLE_RATE * duration_s), endpoint=False)
    jitter = 1.0 + 0.02 * np.sin(2 * np.pi * 3.7 * t)
    pulse = np.sin(2 * np.pi * f0 * jitter * t)
    sos = scipy.signal.butter(2, [300, 3400], btype="bandpass", fs=SAMPLE_RATE, output="sos")
    speech = scipy.signal.sosfilt(sos, pulse)
    envelope = 0.5 * (1.0 + np.sin(2 * np.pi * 4.0 * t)) ** 2
    out = (speech * envelope).astype(np.float32)
    peak = np.max(np.abs(out)) + 1e-9
    return torch.from_numpy(out / peak * 0.85)


@pytest.fixture
def challenge_service():
    return AdaptiveChallengeService(default_ttl_seconds=10.0)


class TestPhase10ChallengeResponse:
    """
    Test suite for VIGIL-AI Phase 10: Adaptive Challenge-Response Verification.
    """

    def test_challenge_trigger_conditions(self):
        """
        Trigger Conditions:
        - risk level = HIGH or CRITICAL
        - OR model confidence is insufficient (< 0.60)
        - OR identity verification is inconclusive.
        """
        # 1. High and Critical Risk
        trig, reason = AdaptiveChallengeService.should_trigger_challenge(
            risk_level="CRITICAL", confidence=0.90
        )
        assert trig is True
        assert reason == ChallengeTriggerReason.CRITICAL_RISK

        trig, reason = AdaptiveChallengeService.should_trigger_challenge(
            risk_level="HIGH", confidence=0.85
        )
        assert trig is True
        assert reason == ChallengeTriggerReason.HIGH_RISK

        # 2. Insufficient Model Confidence
        trig, reason = AdaptiveChallengeService.should_trigger_challenge(
            risk_level="LOW", confidence=0.45
        )
        assert trig is True
        assert reason == ChallengeTriggerReason.LOW_CONFIDENCE

        # 3. Inconclusive Speaker Identity
        trig, reason = AdaptiveChallengeService.should_trigger_challenge(
            risk_level="LOW", confidence=0.85, speaker_match=False, speaker_similarity=0.42
        )
        assert trig is True
        assert reason == ChallengeTriggerReason.INCONCLUSIVE_IDENTITY

        # 4. Clean Low Risk (No trigger)
        trig, reason = AdaptiveChallengeService.should_trigger_challenge(
            risk_level="LOW", confidence=0.90, speaker_match=True, speaker_similarity=0.88
        )
        assert trig is False
        assert reason is None

    def test_unpredictability_and_no_immediate_reuse(self):
        """
        Requirements 1 & 2:
        - Challenge must be unpredictable.
        - Never reuse challenges immediately.
        """
        generator = ChallengeGenerator(history_capacity=50)
        generated_phrases = []

        for i in range(40):
            prompt, phrase = generator.generate_challenge_prompt()
            assert len(phrase) > 0
            assert "Please" in prompt
            # Must not equal the immediately preceding phrase
            if generated_phrases:
                assert phrase != generated_phrases[-1], f"Immediate repetition detected at index {i}: {phrase}"
            generated_phrases.append(phrase)

        # Unique count across 40 runs should be high (>= 35)
        unique_count = len(set(generated_phrases))
        assert unique_count >= 35, f"Expected high entropy unpredictability, got {unique_count} unique out of 40"

    def test_quick_expiration(self, challenge_service):
        """
        Requirement 3:
        - Challenge expires quickly.
        - Submissions after TTL deadline must return EXPIRED status.
        """
        challenge = challenge_service.create_challenge(ttl_seconds=0.2)
        assert challenge.status == ChallengeStatus.PENDING

        # Wait for expiration
        time.sleep(0.3)

        req = ChallengeVerificationRequest(
            challenge_id=challenge.challenge_id,
            user_consent=True,
        )
        res = challenge_service.verify_response(req)

        assert res.challenge_status == ChallengeStatus.EXPIRED
        assert res.risk_level in ["HIGH", "CRITICAL"]
        assert "expired" in res.user_warning.lower()

    def test_explicit_consent_enforcement(self, challenge_service):
        """
        Requirement 4:
        - Record the response only with explicit user consent and appropriate disclosure.
        - If consent is False, verification must fail immediately.
        """
        challenge = challenge_service.create_challenge()
        assert DEFAULT_CONSENT_DISCLOSURE in challenge.disclosure_notice

        req = ChallengeVerificationRequest(
            challenge_id=challenge.challenge_id,
            user_consent=False,  # User withheld consent
        )
        res = challenge_service.verify_response(req)

        assert res.challenge_status == ChallengeStatus.FAILED
        assert "consent" in res.user_warning.lower()

    def test_successful_challenge_verification(self, challenge_service):
        """
        Requirement 5 & 6:
        - Multi-model verification (deepfake, speaker, liveness).
        - Clean response yields PASSED status and LOW risk.
        """
        challenge = challenge_service.create_challenge()
        audio = create_test_speech(duration_s=1.5, f0=135.0)

        req = ChallengeVerificationRequest(
            challenge_id=challenge.challenge_id,
            user_consent=True,
            turn_taking_latency_ms=400.0,
        )
        res = challenge_service.verify_response(req, audio_tensor=audio)

        assert res.challenge_status == ChallengeStatus.PASSED
        assert res.risk_score <= 35
        assert res.recommended_action == "ALLOW"
        assert res.user_warning is None
        assert res.independent_verification_recommended is False

    def test_failed_challenge_verification_actions(self, challenge_service):
        """
        Requirement 8:
        If verification fails:
        → HIGH/CRITICAL RISK
        → warn user
        → recommend independent verification
        → optionally block according to configured policy.
        """
        challenge = challenge_service.create_challenge()

        # Simulate synthetic tone response that fails deepfake detector / liveness
        t = np.linspace(0, 1.5, 24000, endpoint=False)
        synth_tone = 0.9 * np.sin(2 * np.pi * 150.0 * t).astype(np.float32)
        # Soft-clip and flatten dynamic range
        synth_tone = np.tanh(synth_tone * 5.0).astype(np.float32)
        audio = torch.from_numpy(synth_tone)

        req = ChallengeVerificationRequest(
            challenge_id=challenge.challenge_id,
            user_consent=True,
            turn_taking_latency_ms=10.0,  # Robotic sub-20ms trigger
        )
        res = challenge_service.verify_response(req, audio_tensor=audio)

        # Verification must fail
        assert res.challenge_status == ChallengeStatus.FAILED
        # Risk level must be HIGH or CRITICAL
        assert res.risk_level in ["HIGH", "CRITICAL"]
        assert res.risk_score >= 80
        # Action must be BLOCK
        assert res.recommended_action == "BLOCK"
        # Must warn user
        assert res.user_warning is not None
        assert "CRITICAL" in res.user_warning or "WARNING" in res.user_warning
        # Must recommend independent verification
        assert res.independent_verification_recommended is True

    def test_compliance_and_disclaimer(self, challenge_service):
        """
        Requirement 7 & Return Contract:
        - Do not claim challenge-response is impossible for modern real-time AI systems.
        - Returns exact schema:
          {
            "challenge_id": "...",
            "challenge_status": "PASSED | FAILED | EXPIRED",
            "deepfake_probability": ...,
            "speaker_similarity": ...,
            "liveness": ...
          }
        """
        challenge = challenge_service.create_challenge()
        audio = create_test_speech()

        req = ChallengeVerificationRequest(
            challenge_id=challenge.challenge_id,
            user_consent=True,
        )
        res = challenge_service.verify_response(req, audio_tensor=audio)

        d = res.to_dict()
        assert "challenge_id" in d
        assert "challenge_status" in d
        assert d["challenge_status"] in ["PASSED", "FAILED", "EXPIRED"]
        assert "deepfake_probability" in d
        assert "speaker_similarity" in d
        assert "liveness" in d
        assert 0.0 <= d["deepfake_probability"] <= 1.0
        assert 0.0 <= d["liveness"] <= 1.0

        # Disclaimer check
        assert CHALLENGE_PLATFORM_DISCLAIMER == res.disclaimer
        assert "not an absolute guarantee" in res.disclaimer
