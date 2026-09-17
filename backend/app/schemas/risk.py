from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class DecisionState(str, Enum):
    ALLOW = "ALLOW"
    CHALLENGE = "CHALLENGE"
    WARN = "WARN"
    BLOCK = "BLOCK"
    UNCERTAIN = "UNCERTAIN"


class UncertaintyMetrics(BaseModel):
    aleatoric_score: float = Field(..., ge=0.0, le=1.0, description="Data/noise uncertainty (entropy)")
    epistemic_score: float = Field(..., ge=0.0, le=1.0, description="Model ignorance / OOD uncertainty")
    total_uncertainty: float = Field(..., ge=0.0, le=1.0, description="Calibrated combined uncertainty")


class VoiceActivityMetrics(BaseModel):
    is_speech: bool = Field(..., description="Speech presence flag")
    speech_probability: float = Field(..., ge=0.0, le=1.0)


class DeepfakeMetrics(BaseModel):
    is_synthetic: bool
    synthetic_probability: float = Field(..., ge=0.0, le=1.0)
    architecture_detected: str = "AASIST_WAVLM_FUSION"
    anomaly_breakdown: Dict[str, float] = Field(default_factory=dict)


class SpeakerVerificationMetrics(BaseModel):
    enrolled_match: bool
    cosine_similarity: float = Field(..., ge=-1.0, le=1.0)
    threshold: float = 0.65
    claimed_speaker_id: Optional[str] = None


class LivenessMetrics(BaseModel):
    is_live_acoustic: bool
    replay_probability: float = Field(..., ge=0.0, le=1.0)
    channel_dispersion_detected: bool = False
    liveness_score: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class LatencyBreakdown(BaseModel):
    preprocessing_ms: float
    vad_ms: float
    antispoof_ms: float
    speaker_verify_ms: float
    liveness_ms: float
    decision_engine_ms: float
    total_pipeline_latency_ms: float


class RiskVerdict(BaseModel):
    decision: DecisionState
    composite_risk_score: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    uncertainty: UncertaintyMetrics
    voice_activity: VoiceActivityMetrics
    deepfake_analysis: DeepfakeMetrics
    speaker_verification: Optional[SpeakerVerificationMetrics] = None
    liveness_analysis: LivenessMetrics
    explainability_reasons: List[str] = Field(default_factory=list)
    latency_metrics: LatencyBreakdown
