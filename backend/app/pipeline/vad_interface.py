from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math
import time
from typing import Any, Dict, Optional
import numpy as np


@dataclass
class VADDecision:
    is_speech: bool
    speech_probability: float
    confidence: float = 0.0
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    rms_db: float = -100.0
    zero_crossing_rate: float = 0.0
    spectral_entropy: float = 0.0
    latency_ms: float = 0.0

    def __post_init__(self):
        if self.confidence == 0.0 and self.speech_probability > 0.0:
            self.confidence = self.speech_probability
        elif self.speech_probability == 0.0 and self.confidence > 0.0:
            self.speech_probability = self.confidence

    def to_dict(self) -> Dict[str, Any]:
        """Returns standard Phase 2 VAD output schema."""
        return {
            "is_speech": self.is_speech,
            "speech_probability": round(self.speech_probability, 3),
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


class VADInterface(ABC):
    """
    Abstract Voice Activity Detection (VAD) Interface.
    Decouples VAD algorithm (Silero, Simple Energy, WebRTC VAD, etc.) from the audio pipeline.
    """

    @abstractmethod
    def is_speech(self, audio_samples: np.ndarray, sample_rate: int = 16000) -> VADDecision:
        """
        Evaluates an audio frame or window for human speech phonation.
        Args:
            audio_samples: Float32 array normalized to [-1.0, 1.0].
            sample_rate: Sample rate in Hz (default 16000).
        Returns:
            VADDecision containing boolean classification, timestamps, and acoustic metrics.
        """
        pass

    def reset(self) -> None:
        """Resets streaming states if applicable."""
        pass


class SimpleVAD(VADInterface):
    """
    Production-grade baseline VAD implementation using acoustic energy,
    zero-crossing rate (ZCR), and normalized spectral entropy.
    Runs in sub-millisecond time.
    """

    def __init__(self, energy_threshold_db: float = -42.0, speech_prob_threshold: float = 0.45):
        self.energy_threshold_db = energy_threshold_db
        self.speech_prob_threshold = speech_prob_threshold
        self.total_samples_processed = 0

    def reset(self) -> None:
        self.total_samples_processed = 0

    def is_speech(self, audio_samples: np.ndarray, sample_rate: int = 16000) -> VADDecision:
        t0 = time.perf_counter()
        if len(audio_samples) == 0:
            return VADDecision(
                is_speech=False,
                speech_probability=0.0,
                confidence=0.0,
                rms_db=-100.0,
                zero_crossing_rate=0.0,
                spectral_entropy=0.0,
                latency_ms=0.0,
            )

        start_sec = round(self.total_samples_processed / sample_rate, 3)
        self.total_samples_processed += len(audio_samples)
        end_sec = round(self.total_samples_processed / sample_rate, 3)

        # 1. Compute RMS energy in dBFS
        rms = np.sqrt(np.mean(audio_samples ** 2) + 1e-12)
        rms_db = 20.0 * math.log10(max(rms, 1e-6))

        # 2. Compute Zero Crossing Rate (ZCR)
        zcr = np.mean(np.abs(np.diff(np.sign(audio_samples)))) / 2.0 if len(audio_samples) > 1 else 0.0

        # 3. Compute Spectral Entropy
        if len(audio_samples) >= 128:
            fft_mag = np.abs(np.fft.rfft(audio_samples))
            sum_mag = np.sum(fft_mag) + 1e-12
            norm_mag = fft_mag / sum_mag
            spec_entropy = -np.sum(norm_mag * np.log2(norm_mag + 1e-12)) / np.log2(len(norm_mag) + 1e-12)
        else:
            spec_entropy = 0.5

        # Heuristic scoring function:
        energy_factor = float(np.clip((rms_db - self.energy_threshold_db) / 25.0, 0.0, 1.0))
        entropy_factor = float(np.clip(1.0 - abs(spec_entropy - 0.65) * 2.0, 0.0, 1.0))
        zcr_factor = 1.0 if zcr < 0.35 else 0.5

        speech_score = float(np.clip(0.65 * energy_factor + 0.35 * entropy_factor * zcr_factor, 0.0, 1.0))
        is_speech_bool = speech_score >= self.speech_prob_threshold and rms_db > self.energy_threshold_db
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return VADDecision(
            is_speech=is_speech_bool,
            speech_probability=round(speech_score, 3),
            confidence=round(speech_score, 3),
            start_time=start_sec if is_speech_bool else None,
            end_time=end_sec if is_speech_bool else None,
            rms_db=round(rms_db, 2),
            zero_crossing_rate=round(float(zcr), 3),
            spectral_entropy=round(float(spec_entropy), 3),
            latency_ms=round(latency_ms, 2),
        )
