import pytest
import numpy as np
import torch
from app.pipeline.risk_engine import (
    MultiFactorRiskEngine,
    RiskEngineInput,
    RiskEvaluationResult,
)
from app.pipeline.session_manager import StreamingSessionManager


class TestPhase6MultiSignalRiskEngine:
    """
    Exhaustive verification of VIGIL-AI's Phase 6 Multi-Signal Risk Engine:
    - Non-linear multi-signal synthesis (deepfake, speaker, liveness, caller ID, audio quality, confidence)
    - Targeted clone attack synergy
    - Low-confidence safety override (prefer CHALLENGE over BLOCK)
    - Human-explainable output formatting with checkmarks
    - Real-time streaming session telemetry integration
    """

    def test_clean_allow(self):
        """Pristine authentic call from matching enrolled speaker with valid caller ID."""
        engine = MultiFactorRiskEngine()
        risk_input = RiskEngineInput(
            deepfake_probability=0.04,
            speaker_similarity=0.92,
            liveness_score=0.98,
            caller_verified=True,
            audio_quality=0.95,
            model_confidence=0.96,
            contextual_signals=[],
        )
        result: RiskEvaluationResult = engine.evaluate_risk(risk_input)

        assert result.risk_score <= 34
        assert result.risk_level == "LOW"
        assert result.recommended_action == "ALLOW"
        assert "HIGH_SYNTHETIC_PROBABILITY" not in result.signals
        assert "SPEAKER_MISMATCH" not in result.signals
        assert "LOW_LIVENESS" not in result.signals
        assert "CALLER_ID_UNVERIFIED" not in result.signals

    def test_conclusive_deepfake_block(self):
        """Conclusive synthetic voice with high confidence and unverified caller."""
        engine = MultiFactorRiskEngine()
        risk_input = RiskEngineInput(
            deepfake_probability=0.96,
            speaker_similarity=0.15,
            liveness_score=0.20,
            caller_verified=False,
            audio_quality=0.85,
            model_confidence=0.94,
            contextual_signals=[],
        )
        result: RiskEvaluationResult = engine.evaluate_risk(risk_input)

        assert result.risk_score >= 85
        assert result.risk_level == "CRITICAL"
        assert result.recommended_action == "BLOCK"
        assert "HIGH_SYNTHETIC_PROBABILITY" in result.signals
        assert "CALLER_ID_UNVERIFIED" in result.signals
        assert "LOW_LIVENESS" in result.signals
        assert "SPEAKER_MISMATCH" in result.signals

    def test_targeted_clone_detection_synergy(self):
        """
        Attacker cloning an enrolled VIP victim:
        High speaker similarity (matches enrolled profile) AND high synthetic speech.
        Triggers TARGETED_CLONE_DETECTED and non-linear escalation penalty.
        """
        engine = MultiFactorRiskEngine()
        risk_input = RiskEngineInput(
            deepfake_probability=0.88,
            speaker_similarity=0.89,  # Matches enrolled victim!
            liveness_score=0.70,
            caller_verified=True,
            audio_quality=0.90,
            model_confidence=0.92,
        )
        result: RiskEvaluationResult = engine.evaluate_risk(risk_input)

        assert "TARGETED_CLONE_DETECTED" in result.signals
        assert "HIGH_SYNTHETIC_PROBABILITY" in result.signals
        # Synergy penalty pushes it straight to CRITICAL / BLOCK
        assert result.risk_score >= 85
        assert result.risk_level == "CRITICAL"
        assert result.recommended_action == "BLOCK"

    def test_low_confidence_safety_override(self):
        """
        CRITICAL SAFETY RULE:
        If model confidence is low, the system MUST prefer CHALLENGE / VERIFY
        rather than pretending the call is definitely fake or blindly blocking.
        """
        engine = MultiFactorRiskEngine()
        # High raw threat parameters that would normally result in a BLOCK
        risk_input = RiskEngineInput(
            deepfake_probability=0.94,
            speaker_similarity=0.20,
            liveness_score=0.35,
            caller_verified=False,
            audio_quality=0.50,
            model_confidence=0.45,  # Low confidence (< 0.60 threshold)
        )
        result: RiskEvaluationResult = engine.evaluate_risk(risk_input)

        assert "LOW_MODEL_CONFIDENCE" in result.signals
        # Must be CHALLENGE, never BLOCK
        assert result.recommended_action == "CHALLENGE"
        assert result.risk_score >= 60  # Raw score is high, but action is safely throttled

    def test_speaker_mismatch_only(self):
        """Natural human voice, but speaking on behalf of an identity that doesn't match."""
        engine = MultiFactorRiskEngine()
        risk_input = RiskEngineInput(
            deepfake_probability=0.08,  # Bonafide natural human
            speaker_similarity=0.22,    # Severe biometric mismatch
            liveness_score=0.95,
            caller_verified=True,
            audio_quality=0.92,
            model_confidence=0.90,
        )
        result: RiskEvaluationResult = engine.evaluate_risk(risk_input)

        assert "SPEAKER_MISMATCH" in result.signals
        assert "HIGH_SYNTHETIC_PROBABILITY" not in result.signals
        assert result.recommended_action == "CHALLENGE"
        assert result.risk_level in ["MEDIUM", "HIGH"]

    def test_low_liveness_replay_attack(self):
        """Acoustic replay attack via external loudspeaker."""
        engine = MultiFactorRiskEngine()
        risk_input = RiskEngineInput(
            deepfake_probability=0.20,
            speaker_similarity=None,
            liveness_score=0.15,  # Severe loudspeaker dispersion / low PAPR
            caller_verified=True,
            audio_quality=0.88,
            model_confidence=0.85,
        )
        result: RiskEvaluationResult = engine.evaluate_risk(risk_input)

        assert "LOW_LIVENESS" in result.signals
        assert result.risk_score >= 35
        assert result.recommended_action in ["CHALLENGE", "WARN"]

    def test_unverified_caller_and_financial_request(self):
        """Contextual risk escalation when financial transaction is mentioned from unverified caller."""
        engine = MultiFactorRiskEngine()
        risk_input = RiskEngineInput(
            deepfake_probability=0.30,
            speaker_similarity=None,
            liveness_score=0.85,
            caller_verified=False,
            audio_quality=0.85,
            model_confidence=0.88,
            contextual_signals=["FINANCIAL_REQUEST"],
        )
        result: RiskEvaluationResult = engine.evaluate_risk(risk_input)

        assert "CALLER_ID_UNVERIFIED" in result.signals
        assert "FINANCIAL_REQUEST" in result.signals
        assert result.risk_score >= 35
        assert result.recommended_action in ["CHALLENGE", "WARN"]

    def test_explainable_output_formatting(self):
        """
        Verify human-explainable format:
        Risk Score: 91

        Contributing signals:
        ✓ Synthetic speech probability: 94%
        ✓ Low liveness: 37%
        ✓ Caller verification failed
        ✓ Speaker mismatch: 21%
        Recommended action: CHALLENGE
        """
        engine = MultiFactorRiskEngine()
        risk_input = RiskEngineInput(
            deepfake_probability=0.94,
            speaker_similarity=0.79,  # Mismatch: 21%
            liveness_score=0.37,
            caller_verified=False,
            audio_quality=0.90,
            model_confidence=0.55,  # Forces CHALLENGE due to low confidence
        )
        result: RiskEvaluationResult = engine.evaluate_risk(risk_input)

        explanation = result.format_explanation()
        assert f"Risk Score: {result.risk_score}" in explanation
        assert "Contributing signals:" in explanation
        assert "✓ Synthetic speech probability: 94%" in explanation
        assert "✓ Low liveness: 37%" in explanation
        assert "✓ Caller verification failed" in explanation
        assert "✓ Speaker mismatch: 21%" in explanation
        assert "Recommended action: CHALLENGE" in explanation

    def test_streaming_session_risk_telemetry(self):
        """Live audio ingestion through StreamingSessionManager produces active risk telemetry."""
        session = StreamingSessionManager(
            session_id="test_phase6_session",
            sample_rate=16000,
            window_seconds=1.0,
            claimed_speaker_id="spk_alice",
        )

        # Ingest 16000 samples (1 second of synthetic sinusoidal harmonics)
        t = np.linspace(0, 1.0, 16000, endpoint=False, dtype=np.float32)
        # Synthetic buzz
        harmonics = 0.5 * np.sin(2 * np.pi * 440 * t) + 0.3 * np.sin(2 * np.pi * 880 * t) + 0.2 * np.sin(2 * np.pi * 1320 * t)
        pcm_bytes = (harmonics * 32767).astype(np.int16).tobytes()

        # Ingest in chunks
        chunk_size = 3200 * 2  # 200ms
        telemetry = {}
        for i in range(0, len(pcm_bytes), chunk_size):
            _, telemetry = session.ingest_packet(pcm_bytes[i : i + chunk_size])

        assert "risk" in telemetry
        risk = telemetry["risk"]
        assert "risk_score" in risk
        assert 0 <= risk["risk_score"] <= 100
        assert risk["risk_level"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        assert risk["recommended_action"] in ["ALLOW", "CHALLENGE", "WARN", "BLOCK"]
        assert isinstance(risk["signals"], list)
        assert isinstance(risk["confidence"], float)
        assert "explanation" in risk
        session.close()
