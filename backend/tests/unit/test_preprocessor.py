import numpy as np
import pytest
import torch
from app.core.security import secure_zero_memory
from app.pipeline.preprocessor import AudioPreprocessor
from tests.fixtures.audio_generator import float_to_pcm16_bytes, generate_sine_wave


def test_preprocessor_pcm_conversion():
    preprocessor = AudioPreprocessor(target_sample_rate=16000)
    sine = generate_sine_wave(freq=440.0, duration_seconds=1.0, sample_rate=16000, amplitude=0.7)
    raw_bytes = float_to_pcm16_bytes(sine)

    result = preprocessor.process_raw_bytes(raw_bytes, source_sample_rate=16000, source_channels=1)

    assert result.sample_rate == 16000
    assert len(result.audio_tensor) == 16000
    assert isinstance(result.audio_tensor, torch.Tensor)
    assert result.peak_level_db < 0.0
    assert result.latency_ms > 0.0


def test_preprocessor_resampling():
    preprocessor = AudioPreprocessor(target_sample_rate=16000)
    # Generate 44.1kHz audio
    sine_44k = generate_sine_wave(freq=440.0, duration_seconds=1.0, sample_rate=44100, amplitude=0.5)
    raw_bytes = float_to_pcm16_bytes(sine_44k)

    result = preprocessor.process_raw_bytes(raw_bytes, source_sample_rate=44100, source_channels=1)

    assert result.sample_rate == 16000
    # Resampled 1 second of audio should be close to 16,000 samples
    assert abs(len(result.audio_tensor) - 16000) <= 5


def test_secure_zero_memory():
    # Test bytearray wiping
    b = bytearray(b"\x01\x02\x03\x04")
    secure_zero_memory(b)
    assert b == bytearray(b"\x00\x00\x00\x00")

    # Test numpy wiping
    arr = np.ones((10,), dtype=np.float32)
    secure_zero_memory(arr)
    assert np.all(arr == 0.0)

    # Test torch tensor wiping
    t = torch.ones((10,), dtype=torch.float32)
    secure_zero_memory(t)
    assert torch.all(t == 0.0)
