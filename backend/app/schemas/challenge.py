from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ChallengeStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class ChallengeTriggerReason(str, Enum):
    HIGH_RISK = "HIGH_RISK"
    CRITICAL_RISK = "CRITICAL_RISK"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INCONCLUSIVE_IDENTITY = "INCONCLUSIVE_IDENTITY"
    MANUAL_REQUEST = "MANUAL_REQUEST"


DEFAULT_CONSENT_DISCLOSURE = (
    "Explicit User Consent: By participating in this challenge-response verification, "
    "you authorize VIGIL-AI to record and analyze this specific short speech segment "
    "strictly in ephemeral memory for real-time deepfake, biometric speaker identity, "
    "and acoustic liveness verification. Raw audio is purged immediately upon analysis."
)

CHALLENGE_PLATFORM_DISCLAIMER = (
    "Challenge-response verification is an adaptive, defense-in-depth security barrier "
    "against automated replay and pre-rendered synthetic speech. It is not an absolute "
    "guarantee against low-latency, real-time voice-to-voice generative models."
)


class ChallengeGenerationRequest(BaseModel):
    session_id: Optional[str] = None
    trigger_reason: ChallengeTriggerReason = ChallengeTriggerReason.MANUAL_REQUEST
    custom_ttl_seconds: Optional[float] = Field(default=12.0, ge=3.0, le=60.0)


class ChallengeItem(BaseModel):
    challenge_id: str
    prompt_text: str
    expected_phrase: str
    created_at: float
    expires_at: float
    ttl_seconds: float
    disclosure_notice: str = DEFAULT_CONSENT_DISCLOSURE
    status: ChallengeStatus = ChallengeStatus.PENDING


class ChallengeVerificationRequest(BaseModel):
    challenge_id: str
    user_consent: bool = Field(
        ...,
        description="Explicit user consent authorizing ephemeral recording and analysis of the response speech segment."
    )
    claimed_speaker_id: Optional[str] = None
    audio_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded 16kHz PCM or WAV audio bytes of the response."
    )
    turn_taking_latency_ms: Optional[float] = Field(
        default=None,
        description="Measured interval between challenge prompt finish and response speech onset."
    )


class ChallengeVerificationResponse(BaseModel):
    challenge_id: str
    challenge_status: ChallengeStatus
    deepfake_probability: float = Field(..., ge=0.0, le=1.0)
    speaker_similarity: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    liveness: float = Field(..., ge=0.0, le=1.0)
    risk_score: int = Field(..., ge=0, le=100)
    risk_level: str
    recommended_action: str
    user_warning: Optional[str] = None
    independent_verification_recommended: bool = False
    reasons: List[str] = Field(default_factory=list)
    disclaimer: str = CHALLENGE_PLATFORM_DISCLAIMER

    def to_dict(self) -> Dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "challenge_status": self.challenge_status.value,
            "deepfake_probability": round(self.deepfake_probability, 3),
            "speaker_similarity": round(self.speaker_similarity, 3) if self.speaker_similarity is not None else None,
            "liveness": round(self.liveness, 3),
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "recommended_action": self.recommended_action,
            "user_warning": self.user_warning,
            "independent_verification_recommended": self.independent_verification_recommended,
            "reasons": self.reasons,
            "disclaimer": self.disclaimer,
        }
