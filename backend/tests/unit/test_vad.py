import torch
import pytest
from app.pipeline.vad import SileroVADDetector
from tests.fixtures.audio_generator import generate_sine_wave


def test_vad_silence_vs_speech():
    vad = SileroVADDetector(confidence_threshold=0.40)

    # 1. Silence test
    silence = torch.zeros(1600, dtype=torch.float32)
    silence_res = vad.process_frame(silence)
    assert not silence_res.is_speech
    assert silence_res.speech_probability < 0.30
    assert silence_res.latency_ms >= 0.0

    # 2. Active audible signal test
    tone = generate_sine_wave(freq=300.0, duration_seconds=0.1, amplitude=0.8)
    tone_tensor = torch.from_numpy(tone)
    tone_res = vad.process_frame(tone_tensor)
    assert tone_res.speech_probability > silence_res.speech_probability
