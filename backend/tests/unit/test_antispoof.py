import torch
import pytest
from app.pipeline.antispoof import AntiSpoofModel
from tests.fixtures.audio_generator import generate_synthetic_speech_mock


def test_antispoof_uncertainty_and_prediction():
    model = AntiSpoofModel(sample_rate=16000)

    # 1. Evaluate synthetic vocoded speech
    audio = generate_synthetic_speech_mock(duration_seconds=1.5, inject_vocoder_artifacts=True)
    audio_tensor = torch.from_numpy(audio).unsqueeze(0)

    res = model.predict(audio_tensor)

    # Validate output contracts
    assert 0.0 < res.synthetic_probability < 1.0
    assert 0.0 <= res.epistemic_uncertainty <= 1.0
    assert 0.0 <= res.aleatoric_uncertainty <= 1.0
    assert "phase_incoherence" in res.feature_anomalies
    assert res.latency_ms > 0.0

    # Critical requirement check: model must NEVER claim absolute 100% certainty
    assert res.synthetic_probability != 1.0
    assert res.synthetic_probability != 0.0
