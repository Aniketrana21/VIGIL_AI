"""
VIGIL-AI Defensive Adversarial Acoustic Transformations Library.

Implements controlled acoustic perturbations to stress-test our own detector:
1. Additive Noise (SNR 30 dB to -5 dB)
2. Codec Compression (quantization bit depths 8 to 2 bits)
3. Resampling (16kHz down to 6kHz and restored)
4. Volume Changes (-18 dB to +12 dB)
5. Reverberation (Room Impulse Response RT60 50ms to 600ms)
6. Clipping (Hard non-linear saturation threshold 1.0 to 0.15)
7. Spectral Perturbation (Parametric notch filter & spectral tilt)
8. Time-Domain Perturbation (Micro-dropout temporal jitter 0% to 25%)

Objective: Strictly defensive evaluation of our own detector.
"""

from typing import List, Optional, Tuple, Union
import numpy as np
import scipy.signal


class AdversarialTransforms:
    """
    Parametric transformation primitives for defensive robustness stress-testing.
    """

    def __init__(self, sample_rate: int = 16000, seed: Optional[int] = None):
        self.sample_rate = sample_rate
        if seed is not None:
            np.random.seed(seed)

    @staticmethod
    def _ensure_numpy(audio: Union[np.ndarray, List[float]]) -> np.ndarray:
        arr = np.asarray(audio, dtype=np.float32).flatten()
        if len(arr) == 0:
            return np.zeros(32000, dtype=np.float32)
        return arr

    # 1. Additive Noise
    @classmethod
    def apply_additive_noise(
        cls, audio: np.ndarray, snr_db: float = 10.0, noise_type: str = "white"
    ) -> np.ndarray:
        """Adds noise at specified SNR (dB)."""
        y = cls._ensure_numpy(audio).copy()
        signal_power = np.mean(y ** 2)
        if signal_power <= 1e-9:
            return y

        noise_power = signal_power / (10.0 ** (snr_db / 10.0))
        if noise_type == "pink":
            # 1/f pink noise approximation
            white = np.random.normal(0, 1, len(y))
            b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
            a = [1, -2.494956002, 2.017265875, -0.522189400]
            raw_noise = scipy.signal.lfilter(b, a, white)
            raw_noise = raw_noise / (np.std(raw_noise) + 1e-9)
            noise = raw_noise * np.sqrt(noise_power)
        else:
            noise = np.random.normal(0, np.sqrt(noise_power), size=len(y))

        return np.clip(y + noise, -1.0, 1.0).astype(np.float32)

    # 2. Codec Compression / Bit-Depth Quantization
    @classmethod
    def apply_codec_compression(cls, audio: np.ndarray, bit_depth: int = 4) -> np.ndarray:
        """Simulates lossy codec quantization across varying bit depths."""
        y = cls._ensure_numpy(audio).copy()
        levels = 2 ** max(1, min(16, bit_depth))
        quantized = np.round(y * (levels / 2.0)) / (levels / 2.0)
        return np.clip(quantized, -1.0, 1.0).astype(np.float32)

    # 3. Resampling Degradation
    @classmethod
    def apply_resampling(
        cls, audio: np.ndarray, orig_sr: int = 16000, target_sr: int = 8000
    ) -> np.ndarray:
        """Downsamples to target_sr and resamples back to orig_sr to evaluate band-limiting."""
        y = cls._ensure_numpy(audio).copy()
        orig_len = len(y)
        downsampled_len = int(orig_len * (target_sr / orig_sr))
        downsampled = scipy.signal.resample(y, downsampled_len)
        restored = scipy.signal.resample(downsampled, orig_len)
        return np.clip(restored, -1.0, 1.0).astype(np.float32)

    # 4. Volume / Gain Changes
    @classmethod
    def apply_volume_change(cls, audio: np.ndarray, gain_db: float = 0.0) -> np.ndarray:
        """Scales audio amplitude by gain in dB."""
        y = cls._ensure_numpy(audio).copy()
        factor = 10.0 ** (gain_db / 20.0)
        return np.clip(y * factor, -1.0, 1.0).astype(np.float32)

    # 5. Reverberation (Room Impulse Response)
    @classmethod
    def apply_reverberation(
        cls, audio: np.ndarray, sample_rate: int = 16000, rt60_ms: float = 200.0
    ) -> np.ndarray:
        """Simulates room acoustics with specified RT60 decay time."""
        y = cls._ensure_numpy(audio).copy()
        decay_samples = int((rt60_ms / 1000.0) * sample_rate)
        if decay_samples <= 1:
            return y

        # Exponential decay synthetic RIR
        t = np.linspace(0, 1, decay_samples)
        rir = np.exp(-6.9 * t) * np.random.normal(0, 0.25, decay_samples)
        rir[0] = 1.0  # Direct sound path

        reverb = scipy.signal.convolve(y, rir, mode="same")
        mixed = 0.65 * y + 0.35 * reverb
        return np.clip(mixed, -1.0, 1.0).astype(np.float32)

    # 6. Non-linear Clipping / Saturation
    @classmethod
    def apply_clipping(cls, audio: np.ndarray, clip_threshold: float = 0.5) -> np.ndarray:
        """Applies hard amplitude clipping saturation."""
        y = cls._ensure_numpy(audio).copy()
        th = max(0.05, min(1.0, clip_threshold))
        clipped = np.clip(y, -th, th) / th  # Normalize back to [-1, 1]
        return clipped.astype(np.float32)

    # 7. Spectral Perturbation (Notch filter / spectral tilt)
    @classmethod
    def apply_spectral_perturbation(
        cls,
        audio: np.ndarray,
        sample_rate: int = 16000,
        notch_freq_hz: float = 2500.0,
        q: float = 5.0,
        q_factor: Optional[float] = None,
    ) -> np.ndarray:
        """Applies parametric notch filter suppressing specific resonant frequency bands."""
        y = cls._ensure_numpy(audio).copy()
        effective_q = q_factor if q_factor is not None else q
        nyquist = sample_rate / 2.0
        w0 = min(notch_freq_hz / nyquist, 0.95)
        b, a = scipy.signal.iirnotch(w0, effective_q)
        filtered = scipy.signal.lfilter(b, a, y)
        return np.clip(filtered, -1.0, 1.0).astype(np.float32)

    # 8. Time-Domain Perturbation (Micro-dropouts & temporal jitter)
    @classmethod
    def apply_time_domain_perturbation(
        cls, audio: np.ndarray, dropout_rate_pct: float = 10.0, dropout_window_samples: int = 160
    ) -> np.ndarray:
        """Simulates bursty packet loss dropouts and temporal discontinuities."""
        y = cls._ensure_numpy(audio).copy()
        perturbed = y.copy()
        rate = max(0.0, min(50.0, dropout_rate_pct)) / 100.0

        for i in range(0, len(perturbed) - dropout_window_samples, dropout_window_samples * 2):
            if np.random.uniform(0, 1) < rate:
                # Zero out short window (10ms packet dropout)
                perturbed[i:i + dropout_window_samples] = 0.0

        return perturbed.astype(np.float32)


# Alias for backward compatibility
AdversarialTransformations = AdversarialTransforms

