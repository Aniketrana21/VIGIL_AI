from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import numpy as np
import torch


@dataclass
class PreprocessorResult:
    audio_tensor: torch.Tensor  # Float32 normalized [-1.0, 1.0]
    sample_rate: int
    peak_level_db: float
    latency_ms: float


@dataclass
class VADResult:
    is_speech: bool
    speech_probability: float
    latency_ms: float


@dataclass
class AntiSpoofResult:
    is_synthetic: bool
    synthetic_probability: float
    epistemic_uncertainty: float
    aleatoric_uncertainty: float
    feature_anomalies: Dict[str, float] = field(default_factory=dict)
    latency_ms: float = 0.0


@dataclass
class SpeakerVerificationResult:
    claimed_speaker_id: Optional[str]
    cosine_similarity: float
    is_match: bool
    threshold: float
    embedding: torch.Tensor
    latency_ms: float


@dataclass
class LivenessResult:
    is_live_acoustic: bool
    replay_probability: float
    channel_distortion_score: float
    sub_band_dispersion: float
    latency_ms: float
    liveness_score: Optional[float] = None
    confidence: float = 1.0
    signals: Dict[str, float] = field(default_factory=dict)
    disclaimer: str = "Liveness detection estimates acoustic and interactional indicators; it does NOT prove human presence."

    def __post_init__(self):
        if self.liveness_score is None:
            self.liveness_score = round(float(max(0.0, min(1.0, 1.0 - self.replay_probability))), 3)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "liveness_score": round(self.liveness_score or 0.0, 3),
            "replay_probability": round(self.replay_probability, 3),
            "confidence": round(self.confidence, 3),
            "signals": self.signals,
            "latency_ms": round(self.latency_ms, 2),
            "disclaimer": self.disclaimer,
        }


class BaseAudioProcessor(ABC):
    """Abstract base class for all audio pipeline stages."""

    @abstractmethod
    def initialize(self, device: str = "cpu") -> None:
        """Load weights, initialize ONNX sessions, or allocate hardware buffers."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset internal streaming state between distinct calls/sessions."""
        pass

    @abstractmethod
    def get_latency_stats(self) -> Dict[str, float]:
        """Return running latency metrics."""
        pass
