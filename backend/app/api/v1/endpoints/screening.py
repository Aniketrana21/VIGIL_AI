from fastapi import APIRouter, Depends, status
from app.core.logging import logger
from app.core.security import anonymize_caller_id, verify_api_key
from app.schemas.screening import (
    AndroidScreeningRequest,
    AndroidScreeningResponse,
    ScreeningAction,
    ScreeningRecommendations,
)

router = APIRouter()

# Known high-risk impersonator threat intelligence database (Mock / In-memory demo)
HIGH_RISK_PATTERNS = ["+919876543210", "+18005550199"]
SUSPICIOUS_KEYWORDS = ["BANK", "SUPPORT", "VERIFICATION", "CUSTOMS", "POLICE", "TAX", "URGENT"]


@router.post(
    "/evaluate",
    response_model=AndroidScreeningResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def evaluate_incoming_call(payload: AndroidScreeningRequest):
    """
    Android MODE B Telephony Call Screening Endpoint.
    Invoked by Android VigilCallScreeningService via Telecom framework.
    Evaluates caller reputation, carrier STIR/SHAKEN status, and identity markers.
    """
    masked_phone = anonymize_caller_id(payload.phone_number)
    display_name = (payload.caller_display_name or "").upper()

    logger.info(
        f"Incoming call screening request from device {payload.device_id}: caller {masked_phone}, name '{display_name}'"
    )

    risk_score = 0.10
    reasons = []

    # 1. Threat intel check
    if payload.phone_number in HIGH_RISK_PATTERNS:
        risk_score += 0.80
        reasons.append("Number matches known voice clone scam blacklist.")

    # 2. STIR/SHAKEN carrier verification check
    # 0 = Unverified, 1 = Passed (A), 2 = Failed
    if payload.stir_shaken_status == 2:
        risk_score += 0.40
        reasons.append("STIR/SHAKEN cryptographic caller identity failed validation.")
    elif payload.stir_shaken_status == 0:
        risk_score += 0.15
        reasons.append("STIR/SHAKEN carrier verification not present.")

    # 3. High-risk impersonation keyword heuristics
    for kw in SUSPICIOUS_KEYWORDS:
        if kw in display_name:
            risk_score += 0.35
            reasons.append(f"Caller display name contains sensitive institution keyword '{kw}'.")
            break

    risk_score = round(min(1.0, risk_score), 2)

    # Determine action and recommendations
    if risk_score >= 0.85:
        action = ScreeningAction.BLOCK
        recommendations = ScreeningRecommendations(
            reject_call=True,
            silence_ringer=True,
            display_warning_hud=False,
        )
        reason_str = "BLOCKED: " + "; ".join(reasons)
    elif risk_score >= 0.50:
        action = ScreeningAction.WARN
        recommendations = ScreeningRecommendations(
            reject_call=False,
            silence_ringer=False,
            display_warning_hud=True,
            hud_warning_text="WARNING: Potential high-risk impersonation or unverified caller.",
        )
        reason_str = "WARN: " + "; ".join(reasons)
    else:
        action = ScreeningAction.ALLOW
        recommendations = ScreeningRecommendations(
            reject_call=False,
            silence_ringer=False,
            display_warning_hud=False,
        )
        reason_str = "ALLOW: Low risk indicators."

    return AndroidScreeningResponse(
        action=action,
        risk_score=risk_score,
        reason=reason_str,
        recommendations=recommendations,
    )
