import pytest
from app.pipeline.policy_engine import (
    FinalRiskDecisionEngine,
    FinalRiskDecisionResult,
    FinalRiskEngineInput,
    PolicyConfig,
    get_final_risk_engine,
)


@pytest.fixture
def engine():
    return FinalRiskDecisionEngine()


class TestPhase12FinalRiskEngine:
    """
    Exhaustive verification of VIGIL-AI Phase 12 Final Risk Engine.
    Validates multi-signal policy orchestration, threshold configurability,
    versioning, low-confidence safeguards, explainability, and all 9 target scenarios.
    """

    def test_genuine_speaker(self, engine):
        """
        Scenario 1: Genuine speaker.
        Pristine bonafide speech, verified caller, matching voiceprint, low conversation risk.
        -> ALLOW, LOW risk level.
        """
        inp = FinalRiskEngineInput(
            deepfake_score=0.03,
            speaker_similarity=0.92,
            liveness_score=0.96,
            replay_probability=0.04,
            caller_verification_status=True,
            conversation_risk=0.02,
            model_confidence=0.95,
            audio_quality=0.98,
        )
        res: FinalRiskDecisionResult = engine.evaluate(inp)

        assert res.risk_level == "LOW"
        assert res.action == "ALLOW"
        assert res.risk_score <= 34
        assert res.requires_human_verification is False
        assert "HIGH_SYNTHETIC_PROBABILITY" not in res.signals

    def test_cloned_speaker(self, engine):
        """
        Scenario 2: Cloned speaker (Targeted Clone Attack).
        Matches enrolled victim's identity (similarity 0.91) but possesses synthetic neural vocoder artifacts (0.94 spoof).
        -> Non-linear synergy triggers TARGETED_CLONE_DETECTED -> CRITICAL BLOCK.
        """
        inp = FinalRiskEngineInput(
            deepfake_score=0.94,
            speaker_similarity=0.91,
            liveness_score=0.35,
            replay_probability=0.55,
            caller_verification_status=False,
            conversation_risk=0.10,
            model_confidence=0.92,
            audio_quality=0.88,
        )
        res: FinalRiskDecisionResult = engine.evaluate(inp)

        assert res.risk_level == "CRITICAL"
        assert res.action == "BLOCK"
        assert res.risk_score >= 85
        assert "TARGETED_CLONE_DETECTED" in res.signals
        assert "HIGH_SYNTHETIC_PROBABILITY" in res.signals

    def test_replay_attack(self, engine):
        """
        Scenario 3: Replay attack.
        Loudspeaker playback with high replay probability and low acoustic liveness.
        -> REPLAY_ATTACK_DETECTED / LOW_LIVENESS -> WARN or BLOCK.
        """
        inp = FinalRiskEngineInput(
            deepfake_score=0.15,
            speaker_similarity=0.88,
            liveness_score=0.22,
            replay_probability=0.82,
            caller_verification_status=True,
            conversation_risk=0.05,
            model_confidence=0.90,
            audio_quality=0.75,
        )
        res: FinalRiskDecisionResult = engine.evaluate(inp)

        assert res.action in ["WARN", "BLOCK", "CHALLENGE"]
        assert "REPLAY_ATTACK_DETECTED" in res.signals or "LOW_LIVENESS" in res.signals
        assert res.risk_score > 34

    def test_unknown_speaker(self, engine):
        """
        Scenario 4: Unknown / unenrolled speaker with clean bonafide audio.
        -> Flagged as UNKNOWN_SPEAKER, but NOT blindly blocked.
        """
        inp = FinalRiskEngineInput(
            deepfake_score=0.04,
            speaker_similarity=None,  # No profile in store
            liveness_score=0.92,
            replay_probability=0.08,
            caller_verification_status=True,
            conversation_risk=0.02,
            model_confidence=0.92,
            audio_quality=0.90,
        )
        res: FinalRiskDecisionResult = engine.evaluate(inp)

        assert "UNKNOWN_SPEAKER" in res.signals
        assert res.action in ["ALLOW", "MONITOR"]
        assert res.risk_level == "LOW"

    def test_noisy_audio(self, engine):
        """
        Scenario 5: Noisy audio / degraded SNR.
        Low audio quality with moderate uncertainty.
        -> Signals POOR_AUDIO_QUALITY, avoids unilateral irreversible BLOCK.
        """
        inp = FinalRiskEngineInput(
            deepfake_score=0.48,
            speaker_similarity=0.78,
            liveness_score=0.60,
            replay_probability=0.30,
            caller_verification_status=True,
            conversation_risk=0.10,
            model_confidence=0.55,  # Low confidence due to background noise
            audio_quality=0.25,  # Poor audio SNR
        )
        res: FinalRiskDecisionResult = engine.evaluate(inp)

        assert "POOR_AUDIO_QUALITY" in res.signals
        assert res.action != "BLOCK", "Noisy audio with uncertain confidence must not trigger irreversible BLOCK"
        assert res.action in ["MONITOR", "CHALLENGE", "WARN"]

    def test_low_confidence_prediction(self, engine):
        """
        Scenario 6: Low-confidence prediction.
        Model indicates high deepfake score (0.95), but epistemic/aleatoric confidence is very low (0.42 < 0.60).
        Safety Rule: Avoid irreversible action solely from a low-confidence ML prediction!
        -> Downgrades BLOCK to CHALLENGE; sets requires_human_verification = True.
        """
        inp = FinalRiskEngineInput(
            deepfake_score=0.95,
            speaker_similarity=0.20,
            liveness_score=0.40,
            replay_probability=0.50,
            caller_verification_status=False,
            conversation_risk=0.10,
            model_confidence=0.42,  # Low confidence!
            audio_quality=0.60,
        )
        res: FinalRiskDecisionResult = engine.evaluate(inp)

        assert res.action == "CHALLENGE", f"Expected CHALLENGE due to low confidence safety override, got {res.action}"
        assert res.action != "BLOCK"
        assert "LOW_MODEL_CONFIDENCE" in res.signals
        assert res.requires_human_verification is True

    def test_caller_id_spoofing_signal(self, engine):
        """
        Scenario 7: Caller-ID spoofing signal.
        Verified caller-ID metadata contrasts with synthetic audio, or unverified carrier status.
        """
        inp = FinalRiskEngineInput(
            deepfake_score=0.85,
            speaker_similarity=0.10,
            liveness_score=0.60,
            caller_verification_status=True,  # Telephony claimed verified
            model_confidence=0.90,
        )
        res: FinalRiskDecisionResult = engine.evaluate(inp)

        assert "POTENTIAL_CALLER_ID_SPOOFING" in res.signals
        assert res.risk_score >= 60

    def test_financial_scam_context(self, engine):
        """
        Scenario 8: Financial scam context.
        High-risk conversation intent (OTP/wire transfer request, risk=0.92) combined with synthetic speech (0.88).
        -> Non-linear compounding penalty triggers VOICE_CLONE_SOCIAL_ENGINEERING_SYNERGY -> CRITICAL BLOCK.
        """
        inp = FinalRiskEngineInput(
            deepfake_score=0.88,
            speaker_similarity=0.89,
            liveness_score=0.40,
            caller_verification_status=False,
            conversation_risk=0.92,  # High-risk financial / credential intent
            model_confidence=0.92,
        )
        res: FinalRiskDecisionResult = engine.evaluate(inp)

        assert res.risk_level == "CRITICAL"
        assert res.action == "BLOCK"
        assert "HIGH_CONVERSATION_RISK" in res.signals
        assert "VOICE_CLONE_SOCIAL_ENGINEERING_SYNERGY" in res.signals
        assert res.risk_score >= 90

    def test_conflicting_model_outputs(self, engine):
        """
        Scenario 9: Conflicting model outputs.
        High acoustic liveness (0.95 live physical acoustic emission) contradicts elevated deepfake score (0.65).
        -> Identifies CONFLICTING_MODEL_SIGNALS, sets requires_human_verification = True, action CHALLENGE.
        """
        inp = FinalRiskEngineInput(
            deepfake_score=0.68,
            speaker_similarity=0.85,
            liveness_score=0.95,  # High liveness!
            replay_probability=0.05,
            caller_verification_status=True,
            conversation_risk=0.05,
            model_confidence=0.85,
        )
        res: FinalRiskDecisionResult = engine.evaluate(inp)

        assert "CONFLICTING_MODEL_SIGNALS" in res.signals
        assert res.requires_human_verification is True
        assert res.action in ["CHALLENGE", "WARN"]

    def test_configurable_policy_and_versioning(self):
        """
        Requirement: Configurable policy engine and policy versioning.
        """
        custom_policy = PolicyConfig(
            policy_version="2026.10-custom-fintech",
            threshold_allow_max=20,  # Stricter allow threshold
            threshold_monitor_max=40,
            threshold_challenge_max=60,
            threshold_warn_max=75,
            threshold_critical_min=76,
        )
        custom_engine = FinalRiskDecisionEngine(policy_config=custom_policy)

        inp = FinalRiskEngineInput(
            deepfake_score=0.15,  # Raw points ~ 15
            speaker_similarity=0.90,
            liveness_score=0.95,
            caller_verification_status=True,
            model_confidence=0.95,
        )
        res = custom_engine.evaluate(inp)

        assert res.policy_version == "2026.10-custom-fintech"
        assert "2026.10-custom-fintech" in res.explanation
        d = res.to_dict()
        assert d["action"] in ["ALLOW", "MONITOR", "CHALLENGE", "WARN", "BLOCK"]

    def test_exact_return_schema(self, engine):
        """
        Requirement: Exact return contract
        {
          "risk_score": 0-100,
          "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
          "action": "ALLOW | MONITOR | CHALLENGE | WARN | BLOCK",
          "confidence": 0-1,
          "signals": [],
          "explanation": ""
        }
        """
        inp = FinalRiskEngineInput(
            deepfake_score=0.05,
            speaker_similarity=0.95,
            liveness_score=0.98,
            caller_verification_status=True,
            model_confidence=0.96,
        )
        res = engine.evaluate(inp)
        d = res.to_dict()

        assert "risk_score" in d
        assert "risk_level" in d
        assert "action" in d
        assert "confidence" in d
        assert "signals" in d
        assert "explanation" in d

        assert isinstance(d["risk_score"], int)
        assert 0 <= d["risk_score"] <= 100
        assert d["risk_level"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        assert d["action"] in ["ALLOW", "MONITOR", "CHALLENGE", "WARN", "BLOCK"]
        assert 0.0 <= d["confidence"] <= 1.0
        assert isinstance(d["signals"], list)
        assert isinstance(d["explanation"], str)

    def test_never_claim_certainty_and_preserve_scores(self, engine):
        """
        Requirement:
        1. Never claim certainty.
        2. Preserve individual model scores.
        3. Explain why the decision was made.
        """
        inp = FinalRiskEngineInput(
            deepfake_score=0.91,
            speaker_similarity=0.82,
            liveness_score=0.45,
            replay_probability=0.55,
            caller_verification_status=False,
            conversation_risk=0.88,
            model_confidence=0.93,
            audio_quality=0.80,
            caller_id="+18005550199",
            session_id="test_sess_001",
        )
        res = engine.evaluate(inp)

        # 1. Never claim certainty
        assert "does not assert absolute certainty" in res.explanation
        assert "probabilistic" in res.explanation.lower()

        # 2. Preserve individual scores
        scores = res.individual_scores
        assert "deepfake_score" in scores
        assert scores["deepfake_score"] == 0.91
        assert "speaker_similarity" in scores
        assert scores["speaker_similarity"] == 0.82
        assert "liveness_score" in scores
        assert scores["liveness_score"] == 0.45
        assert "replay_probability" in scores
        assert scores["replay_probability"] == 0.55
        assert "caller_verification_status" in scores
        assert scores["caller_verification_status"] is False
        assert "conversation_risk" in scores
        assert scores["conversation_risk"] == 0.88

        # 3. Explain why decision was made
        assert "Contributing" in res.explanation
        assert len(res.contributing_signals) > 0
