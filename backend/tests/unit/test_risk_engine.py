import pytest
import torch
from app.pipeline.interfaces import (
    AntiSpoofResult,
    LivenessResult,
    SpeakerVerificationResult,
    VADResult,
)
from app.pipeline.risk_engine import MultiFactorRiskEngine
from app.schemas.risk import DecisionState


def test_risk_engine_clean_allow():
    engine = MultiFactorRiskEngine()

    vad = VADResult(is_speech=True, speech_probability=0.9, latency_ms=5.0)
    antispoof = AntiSpoofResult(
        is_synthetic=False,
        synthetic_probability=0.10,
        epistemic_uncertainty=0.15,
        aleatoric_uncertainty=0.15,
        latency_ms=50.0,
    )
    liveness = LivenessResult(
        is_live_acoustic=True,
        replay_probability=0.10,
        channel_distortion_score=0.10,
        sub_band_dispersion=0.10,
        latency_ms=10.0,
    )

    verdict = engine.evaluate(vad_res=vad, antispoof_res=antispoof, liveness_res=liveness)
    assert verdict.decision == DecisionState.ALLOW
    assert verdict.composite_risk_score < 0.25
    assert verdict.confidence > 0.80


def test_risk_engine_conclusive_block():
    engine = MultiFactorRiskEngine()

    vad = VADResult(is_speech=True, speech_probability=0.95, latency_ms=5.0)
    antispoof = AntiSpoofResult(
        is_synthetic=True,
        synthetic_probability=0.92,
        epistemic_uncertainty=0.10,
        aleatoric_uncertainty=0.12,
        feature_anomalies={"phase_incoherence": 0.85},
        latency_ms=50.0,
    )
    liveness = LivenessResult(
        is_live_acoustic=False,
        replay_probability=0.88,
        channel_distortion_score=0.80,
        sub_band_dispersion=0.75,
        latency_ms=10.0,
    )

    verdict = engine.evaluate(vad_res=vad, antispoof_res=antispoof, liveness_res=liveness, context_telephony_risk=0.8)
    assert verdict.decision == DecisionState.BLOCK
    assert verdict.composite_risk_score >= 0.85
    assert len(verdict.explainability_reasons) > 0


def test_risk_engine_uncertainty_override():
    # When uncertainty is high, the system must NOT jump to a false confident decision
    engine = MultiFactorRiskEngine()

    vad = VADResult(is_speech=True, speech_probability=0.70, latency_ms=5.0)
    antispoof = AntiSpoofResult(
        is_synthetic=True,
        synthetic_probability=0.70,
        epistemic_uncertainty=0.85,  # High epistemic ignorance / low SNR
        aleatoric_uncertainty=0.75,
        latency_ms=50.0,
    )
    liveness = LivenessResult(
        is_live_acoustic=True,
        replay_probability=0.20,
        channel_distortion_score=0.20,
        sub_band_dispersion=0.20,
        latency_ms=10.0,
    )

    verdict = engine.evaluate(vad_res=vad, antispoof_res=antispoof, liveness_res=liveness)
    assert verdict.decision == DecisionState.UNCERTAIN
    assert verdict.uncertainty.total_uncertainty >= 0.60
