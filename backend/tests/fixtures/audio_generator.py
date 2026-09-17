import math
import numpy as np
import torch


def generate_sine_wave(
    freq: float = 440.0,
    duration_seconds: float = 1.0,
    sample_rate: int = 16000,
    amplitude: float = 0.5,
) -> np.ndarray:
    """Generates a pure sine tone as a float32 numpy array."""
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    waveform = amplitude * np.sin(2 * np.pi * freq * t)
    return waveform.astype(np.float32)


def generate_synthetic_speech_mock(
    duration_seconds: float = 1.5,
    sample_rate: int = 16000,
    inject_vocoder_artifacts: bool = True,
) -> np.ndarray:
    """
    Generates synthetic speech-like harmonic signal with formants.
    If inject_vocoder_artifacts is True, injects high-frequency cutoff and phase jitter.
    """
    n_samples = int(sample_rate * duration_seconds)
    t = np.linspace(0, duration_seconds, n_samples, endpoint=False)

    # Fundamental frequency + harmonics (f0 ~ 130 Hz)
    f0 = 130.0
    signal = np.zeros(n_samples, dtype=np.float32)
    for harmonic in range(1, 8):
        harmonic_amp = 0.3 / harmonic
        phase_offset = np.random.uniform(-np.pi, np.pi) if inject_vocoder_artifacts else 0.0
        signal += (harmonic_amp * np.sin(2 * np.pi * (f0 * harmonic) * t + phase_offset)).astype(np.float32)

    # Add subtle amplitude modulation (syllable envelope at 4 Hz)
    envelope = 0.5 * (1.0 + np.sin(2 * np.pi * 4.0 * t))
    signal *= envelope.astype(np.float32)

    if inject_vocoder_artifacts:
        # Sharp high-frequency cutoff (zero out above 6000Hz)
        fft = np.fft.rfft(signal)
        freqs = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate)
        fft[freqs > 6000] *= 0.01
        signal = np.fft.irfft(fft, n=n_samples).astype(np.float32)

    # Normalize
    max_val = np.max(np.abs(signal))
    if max_val > 0:
        signal = 0.8 * (signal / max_val)

    return signal


def float_to_pcm16_bytes(audio: np.ndarray) -> bytes:
    """Converts a float32 [-1.0, 1.0] audio array into signed 16-bit linear PCM little-endian bytes."""
    int16_audio = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    return int16_audio.tobytes()
