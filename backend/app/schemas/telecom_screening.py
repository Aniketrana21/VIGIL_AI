from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CallerDetails(BaseModel):
    id: Optional[str] = None
    name: str = "Unknown caller"
    phone: str
    company: Optional[str] = None
    company_verified: bool = False
    
    # Advanced Company Verification Architecture
    company_name_claimed: Optional[str] = None
    company_name_verified: bool = False
    verification_source: str = "caller_claim"  # caller_claim | dkim_sip | corporate_pki | manual_verified
    verification_status: str = "UNVERIFIED"  # UNVERIFIED | VERIFIED | SUSPICIOUS | DISPUTED
    
    # Caller Relationship
    relationship: str = "UNKNOWN"  # FAMILY | FRIEND | COLLEAGUE | CUSTOMER | BANK | DELIVERY | UNKNOWN | OTHER
    relationship_verified: bool = False
    claimed_relationship_warning: Optional[str] = None
    
    trust_status: str = "neutral"
    caller_type: str = "unknown"
    is_vip: bool = False


class CallHistorySummary(BaseModel):
    total_calls: int = 0
    calls_last_1h: int = 0
    calls_last_24h: int = 0
    calls_last_7d: int = 0
    average_call_duration_sec: int = 0
    suspicious_events: int = 0
    failed_verifications: int = 0
    blocked_calls: int = 0
    behavioral_anomaly: bool = False
    behavioral_anomaly_reason: Optional[str] = None
    last_call_timestamp: Optional[str] = None


class RiskAssessment(BaseModel):
    score: int = Field(..., ge=0, le=100)
    level: str  # SAFE | LOW | MEDIUM | HIGH | CRITICAL
    reasons: List[str] = Field(default_factory=list)


class CallerSecurityProfile(BaseModel):
    """
    Caller Security Profile / Reputation (Never called 'truth score').
    Provides clear holistic trust assessment across identity, history, and biometrics.
    """
    identity_status: str = "Unverified"  # Verified | Partially Verified | Unverified
    phone_status: str = "Known"  # Known | Unknown | Suspicious | Spoof Risk
    history_label: str = "0 calls"
    recent_risk_label: str = "Low"  # Low | Medium | High | Critical
    company_verification_label: str = "None"  # Verified | Unverified | None
    speaker_similarity_pct: Optional[int] = None
    deepfake_probability_pct: Optional[int] = None
    liveness_pct: Optional[int] = None
    current_risk_score: int = 0


class IncomingCallScreenView(BaseModel):
    """
    Structured payload for rendering the VIGIL-AI incoming call security screen
    (for Normal Call vs High-Risk Alert states).
    """
    screen_type: str = "NORMAL_INCOMING"  # NORMAL_INCOMING | HIGH_RISK_ALERT
    header_title: str = "INCOMING CALL"   # INCOMING CALL | 🚨 HIGH-RISK CALL
    caller_name: str
    masked_phone: str
    company_display: Optional[str] = None
    company_badge: Optional[str] = None  # e.g. "⚠ UNVERIFIED ASSOCIATION"
    calls_summary_total: int = 0
    calls_summary_today: int = 0
    voice_identity_pct: Optional[int] = None
    voice_deepfake_pct: Optional[int] = None
    voice_liveness_pct: Optional[int] = None
    risk_badge: str = "🟢 LOW RISK"
    warning_banner: Optional[str] = None
    available_actions: List[str] = Field(default_factory=lambda: ["ACCEPT", "DECLINE"])


class CallerLookupRequest(BaseModel):
    phone_number: str
    caller_display_name: Optional[str] = None
    claimed_company: Optional[str] = None
    claimed_relationship: Optional[str] = None
    stir_shaken_status: int = Field(default=0, description="0=Not Verified, 1=Passed, 2=Failed")
    carrier_code: Optional[str] = None
    device_id: Optional[str] = None
    installation_id: Optional[str] = None
    user_id: Optional[str] = None
    target_phone: Optional[str] = None


class CallerLookupResponse(BaseModel):
    caller: CallerDetails
    history: CallHistorySummary
    risk: RiskAssessment
    recommended_action: str  # ALLOW | MONITOR | VERIFY | BLOCK
    security_profile: Optional[CallerSecurityProfile] = None
    screen_view: Optional[IncomingCallScreenView] = None


class CallActionReportRequest(BaseModel):
    session_id: Optional[str] = None
    phone_number: str
    caller_name: Optional[str] = None
    action: str  # ALLOW | SILENCE | WARN | CHALLENGE | BLOCK | ESCALATE
    reason: str
    risk_score: int = 0
    performed_at: Optional[str] = None
    device_id: Optional[str] = None
    user_id: Optional[str] = None


class IdentityChallengeRequest(BaseModel):
    caller_id: Optional[str] = None
    call_id: Optional[str] = None
    challenge_type: str = "phonetic_utterance"


class IdentityChallengeResponse(BaseModel):
    challenge_id: str
    prompt: str
    expires_in_sec: int
    expected_response_type: str


class ChallengeEvaluationRequest(BaseModel):
    challenge_id: str
    response_transcript: str
    response_latency_ms: Optional[float] = None
    audio_liveness_score: Optional[float] = None


class ChallengeEvaluationResponse(BaseModel):
    challenge_id: str
    status: str  # PASSED | FAILED | EXPIRED
    similarity_score: float
    reason: str
