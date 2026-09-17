from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CallerIntent(str, Enum):
    """
    Standardized taxonomy of caller intents for VIGIL-AI conversation intelligence.
    Identifies high-risk scam/fraud patterns vs benign informational discourse.
    """
    MONEY_TRANSFER = "MONEY_TRANSFER"
    FINANCIAL_REQUEST = "FINANCIAL_REQUEST"
    UPI_REQUEST = "UPI_REQUEST"
    OTP_REQUEST = "OTP_REQUEST"
    PASSWORD_REQUEST = "PASSWORD_REQUEST"
    BANK_CREDENTIAL_REQUEST = "BANK_CREDENTIAL_REQUEST"
    EMERGENCY_MONEY_REQUEST = "EMERGENCY_MONEY_REQUEST"
    IDENTITY_VERIFICATION_REQUEST = "IDENTITY_VERIFICATION_REQUEST"
    CONFIDENTIAL_INFO_REQUEST = "CONFIDENTIAL_INFO_REQUEST"
    ACCOUNT_TAKEOVER_ATTEMPT = "ACCOUNT_TAKEOVER_ATTEMPT"
    INFORMATIONAL_QUERY = "INFORMATIONAL_QUERY"
    BENIGN_CONVERSATION = "BENIGN_CONVERSATION"


class ConversationIntelligenceOutput(BaseModel):
    """
    Exact output schema mandated by Phase 11 specification:
    {
      "intent": "FINANCIAL_REQUEST",
      "risk_signal": 0.88,
      "evidence": "request for money transfer"
    }
    """
    intent: str = Field(..., description="Classified caller intent (e.g. FINANCIAL_REQUEST, OTP_REQUEST, INFORMATIONAL_QUERY)")
    risk_signal: float = Field(..., ge=0.0, le=1.0, description="Normalized contextual risk score between 0.0 and 1.0")
    evidence: str = Field(..., description="Explanatory syntactic and pragmatic evidence explaining the classification")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "risk_signal": round(self.risk_signal, 2),
            "evidence": self.evidence,
        }


class ConversationAnalysisRequest(BaseModel):
    """
    Request model for conversation intelligence analysis.
    Supports either raw text transcript or base64 PCM audio payload.
    """
    transcript: Optional[str] = Field(None, description="Optional raw text transcript to analyze directly")
    audio_base64: Optional[str] = Field(None, description="Optional base64-encoded 16kHz audio chunk for Whisper ASR")
    user_consent: bool = Field(True, description="Explicit user consent for ephemeral speech-to-text processing")
    store_transcript_consented: bool = Field(
        False,
        description="Mandatory consent flag to persist transcript. Strictly False by default under Zero-Retention mandate."
    )
