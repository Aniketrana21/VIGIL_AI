from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ScreeningAction(str, Enum):
    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"


class ScreeningRecommendations(BaseModel):
    reject_call: bool = False
    silence_ringer: bool = False
    display_warning_hud: bool = False
    hud_warning_text: Optional[str] = None


class AndroidScreeningRequest(BaseModel):
    device_id: str
    phone_number: str
    caller_display_name: Optional[str] = None
    stir_shaken_status: int = Field(default=0, description="0=Not Verified, 1=Passed, 2=Failed")
    carrier_code: Optional[str] = None
    timestamp: int


class AndroidScreeningResponse(BaseModel):
    action: ScreeningAction
    risk_score: float = Field(..., ge=0.0, le=1.0)
    reason: str
    recommendations: ScreeningRecommendations
