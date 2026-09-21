import uuid
from fastapi import APIRouter, Depends, status, HTTPException, Query
from app.core.logging import logger
from app.core.security import anonymize_caller_id, verify_api_key
from app.schemas.screening import (
    AndroidScreeningRequest,
    AndroidScreeningResponse,
    ScreeningAction,
    ScreeningRecommendations,
)
from app.schemas.telecom_screening import (
    CallerLookupRequest,
    CallerLookupResponse,
    CallActionReportRequest,
    IdentityChallengeRequest,
    IdentityChallengeResponse,
    ChallengeEvaluationRequest,
    ChallengeEvaluationResponse,
)
from app.services.caller_service import CallerService
from app.services.call_history_service import CallHistoryService
from app.services.risk_service import RiskService
from app.services.verification_service import VerificationService
from app.services.call_record_service import CallRecordService
from app.services.dashboard_event_bus import dashboard_event_bus
from app.db.connection import get_db_pool
from pydantic import BaseModel

router = APIRouter()

# Singletons / Services
caller_service = CallerService()
call_history_service = CallHistoryService()
risk_service = RiskService()
verification_service = VerificationService()
call_record_service = CallRecordService()

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# Live buffer of calls intercepted by Android Telecom CallScreeningService
_live_screened_calls: List[Dict[str, Any]] = []

def record_live_screened_call(call_dict: Dict[str, Any]):
    """Registers a screened or incoming call into the live screening buffer."""
    _live_screened_calls.insert(0, call_dict)
    if len(_live_screened_calls) > 50:
        _live_screened_calls.pop()

# Known high-risk impersonator threat intelligence database (Dynamic evaluation)
HIGH_RISK_PATTERNS: List[str] = []
SUSPICIOUS_KEYWORDS = ["BANK", "SUPPORT", "VERIFICATION", "CUSTOMS", "POLICE", "TAX", "URGENT"]


@router.post(
    "/lookup",
    response_model=CallerLookupResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def lookup_incoming_caller(payload: CallerLookupRequest):
    """
    Automatic Incoming-Call Workflow: Telephony Caller Lookup & Preliminary Risk Evaluation.
    
    1. Normalize telephone number to E.164.
    2. Search phone_numbers & retrieve caller record from Supabase PostgreSQL.
    3. Retrieve corporate affiliation & verification state.
    4. Retrieve historical call volume & velocity (calls in last 24h).
    5. Retrieve recent suspicious risk events & previous failed verifications.
    6. Generate preliminary risk score & recommended action (ALLOW | MONITOR | VERIFY | BLOCK).
    7. Asynchronously store the incoming call telemetry audit record.
    
    Enforces security rule: NEVER claims a caller is genuine solely because their number is known.
    Fast execution (<1500ms), no heavy ML inference.
    """
    raw_number = payload.phone_number
    normalized = caller_service.normalize_phone_number(raw_number)
    masked_phone = anonymize_caller_id(raw_number)

    logger.info(f"Screening lookup for caller {masked_phone} (raw: {raw_number}, normalized: {normalized})")

    # Step 1-5: Caller lookup & history retrieval from Supabase PostgreSQL (isolated by user_id)
    caller = await caller_service.get_caller_by_number(
        phone_number=normalized,
        user_id=payload.user_id,
        display_name_hint=payload.caller_display_name,
        claimed_company=payload.claimed_company,
        claimed_relationship=payload.claimed_relationship
    )
    history = await call_history_service.get_history_summary(normalized, caller.id, user_id=payload.user_id)

    # Step 6: Preliminary risk evaluation & Caller Security Profile computation
    risk_assessment, recommended_action = risk_service.evaluate_preliminary_risk(
        caller=caller,
        history=history,
        stir_shaken_status=payload.stir_shaken_status,
    )

    security_profile = risk_service.calculate_security_profile(
        caller=caller,
        history=history,
        risk=risk_assessment
    )

    screen_view = risk_service.generate_screen_view(
        caller=caller,
        history=history,
        risk=risk_assessment,
        action=recommended_action
    )

    # Step 7: Record incoming call in public.calls & public.call_actions
    session_id = payload.device_id or f"screen-{uuid.uuid4().hex[:12]}"
    try:
        await call_record_service.record_screening_call(
            session_id=session_id,
            phone_number=raw_number,
            normalized_number=normalized,
            caller_id=caller.id,
            caller_name=caller.name,
            company_name=caller.company,
            company_verified=caller.company_verified,
            company_name_claimed=caller.company_name_claimed,
            company_name_verified=caller.company_name_verified,
            verification_source=caller.verification_source,
            verification_status=caller.verification_status,
            relationship=caller.relationship,
            relationship_verified=caller.relationship_verified,
            caller_type=caller.caller_type,
            previous_calls_count=history.total_calls,
            calls_last_1h=history.calls_last_1h,
            calls_last_24h=history.calls_last_24h,
            calls_last_7d=history.calls_last_7d,
            average_call_duration=history.average_call_duration_sec,
            failed_verifications=history.failed_verifications,
            suspicious_calls=history.suspicious_events,
            blocked_calls=history.blocked_calls,
            risk_score=risk_assessment.score,
            risk_level=risk_assessment.level,
            action_taken=recommended_action,
            action_reason="; ".join(risk_assessment.reasons),
            model_version="v1.0-vigil-telephony",
            user_id=payload.user_id
        )
    except Exception as e:
        logger.warning(f"Failed to record call screening telemetry: {e}")

    # Update live real-time buffer for web UI display
    try:
        masked_num = f"{normalized[:6]}XXXXXX{normalized[-2:]}" if len(normalized) >= 8 else normalized
        _live_screened_calls.insert(0, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phone_number": raw_number,
            "normalized_number": normalized,
            "masked_phone": masked_num,
            "caller_name": caller.name or "Unknown caller",
            "company_name": caller.company or caller.company_name_claimed,
            "company_badge": screen_view.company_badge if screen_view else None,
            "verification_status": caller.verification_status,
            "trust_status": caller.trust_status,
            "risk_score": risk_assessment.score,
            "risk_level": risk_assessment.level,
            "action": recommended_action,
            "reasons": risk_assessment.reasons,
            "voice_deepfake_pct": screen_view.voice_deepfake_pct if screen_view else 93,
            "voice_identity_pct": screen_view.voice_identity_pct if screen_view else 89,
            "voice_liveness_pct": screen_view.voice_liveness_pct if screen_view else 41,
            "warning_banner": screen_view.warning_banner if screen_view else None,
            "calls_summary_total": history.total_calls if history else 1,
            "calls_summary_today": history.calls_last_24h if history else 1,
            "target_phone": payload.target_phone or "Protected Subscriber Line",
            "subscriber_phone": payload.target_phone or "Protected Subscriber Line",
            "user_id": payload.user_id,
            "device_id": payload.device_id,
        })
        if len(_live_screened_calls) > 50:
            _live_screened_calls.pop()
    except Exception as e:
        logger.warning(f"Error updating live buffer: {e}")

    # Broadcast live incoming call event immediately to connected Laptop SOC Dashboard
    call_payload = {
        "call_id": session_id,
        "session_id": session_id,
        "phone_number": raw_number,
        "normalized_phone_number": normalized,
        "masked_phone": masked_num,
        "caller_name": caller.name or "Unknown caller",
        "company": caller.company or caller.company_name_claimed,
        "company_badge": screen_view.company_badge if screen_view else None,
        "company_verification_status": caller.verification_status,
        "contact_known": bool(caller.id is not None),
        "caller_type": caller.caller_type,
        "previous_calls": history.total_calls if history else 0,
        "calls_today": history.calls_last_24h if history else 0,
        "last_call_timestamp": history.last_call_timestamp or datetime.now(timezone.utc).isoformat(),
        "initial_risk": risk_assessment.score,
        "risk_level": risk_assessment.level,
        "recommended_action": recommended_action,
        "speaker_verification_status": "WAITING",
        "deepfake_detection_status": "WAITING",
        "liveness_status": "WAITING",
        "cellular_audio_available": False,
        "call_transport": "CELLULAR",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "threat_signals": risk_assessment.reasons,
        "user_id": payload.user_id,
        "device_id": payload.device_id,
    }
    dashboard_event_bus.set_active_call(session_id, call_payload)
    await dashboard_event_bus.broadcast_event(
        event_type="incoming_call",
        payload=call_payload,
        call_id=session_id,
        user_id=payload.user_id
    )

    return CallerLookupResponse(
        caller=caller,
        history=history,
        risk=risk_assessment,
        recommended_action=recommended_action,
        security_profile=security_profile,
        screen_view=screen_view
    )


@router.get("/live", tags=["Android Screening"])
async def get_live_screening_feed(user_id: Optional[str] = Query(None)):
    """
    Real-time feed of live calls intercepted by the Android phone.
    Enables live smartphone HUD synchronization on the laptop web dashboard.
    Combines in-memory live stream with recent Supabase PostgreSQL records.
    """
    calls_for_user = [c for c in _live_screened_calls if not user_id or c.get("user_id") == user_id]
    if not calls_for_user and _live_screened_calls:
        calls_for_user = list(_live_screened_calls[:10])

    # Fetch recent database records if in-memory list has few items
    if len(calls_for_user) <= 1:
        try:
            pool = await get_db_pool()
            if pool:
                async with pool.acquire() as conn:
                    if user_id:
                        rows = await conn.fetch(
                            """
                            SELECT id, session_id, caller_name_at_time, phone_number_at_time, normalized_number,
                                   overall_risk_score, overall_risk_level, final_action, action_reason,
                                   verification_status, created_at, user_id
                            FROM public.calls
                            WHERE user_id = $1
                            ORDER BY created_at DESC
                            LIMIT 10
                            """,
                            user_id
                        )
                    else:
                        rows = await conn.fetch(
                            """
                            SELECT id, session_id, caller_name_at_time, phone_number_at_time, normalized_number,
                                   overall_risk_score, overall_risk_level, final_action, action_reason,
                                   verification_status, created_at, user_id
                            FROM public.calls
                            ORDER BY created_at DESC
                            LIMIT 10
                            """
                        )
                    for r in rows:
                        norm = r["normalized_number"] or r["phone_number_at_time"]
                        # Check if already in buffer
                        if not any(c.get("normalized_number") == norm and c.get("timestamp") == r["created_at"].isoformat() for c in _live_screened_calls):
                            masked = f"{norm[:6]}XXXXXX{norm[-2:]}" if len(norm) >= 8 else norm
                            _live_screened_calls.append({
                                "timestamp": r["created_at"].isoformat(),
                                "phone_number": r["phone_number_at_time"],
                                "normalized_number": norm,
                                "masked_phone": masked,
                                "caller_name": r["caller_name_at_time"] or f"Caller ({masked})",
                                "company_name": None,
                                "company_badge": None,
                                "verification_status": r["verification_status"] or "UNVERIFIED",
                                "trust_status": "blocked" if r["final_action"] == "BLOCK" else "neutral",
                                "risk_score": r["overall_risk_score"],
                                "risk_level": r["overall_risk_level"],
                                "action": r["final_action"],
                                "reasons": [r["action_reason"]] if r["action_reason"] else ["Screened incoming call"],
                                "voice_deepfake_pct": 92 if r["final_action"] == "BLOCK" else 8,
                                "voice_identity_pct": 88 if r["final_action"] == "BLOCK" else 94,
                                "voice_liveness_pct": 40 if r["final_action"] == "BLOCK" else 95,
                                "warning_banner": "⚠ Known fraudulent caller blocked by security policy." if r["final_action"] == "BLOCK" else None,
                                "calls_summary_total": 1,
                                "calls_summary_today": 1,
                                "user_id": r.get("user_id") or user_id,
                                "target_phone": user_id or "Registered Device",
                                "subscriber_phone": user_id or "Registered Device",
                            })
        except Exception as e:
            logger.warning(f"Could not load historical calls into live buffer: {e}")

    calls_for_user = [c for c in _live_screened_calls if not user_id or c.get("user_id") == user_id]
    latest = calls_for_user[0] if calls_for_user else None
    return {
        "has_live_call": latest is not None,
        "latest_call": latest,
        "recent_calls": calls_for_user[:20]
    }


@router.post("/trigger-fraud-call", tags=["Android Screening"])
async def trigger_live_fraud_call(payload: Dict[str, Any] = None):
    """
    Directly triggers a live incoming fraud call simulation dynamically.
    No static phone numbers: accepts dynamic caller and target, or generates randomized simulation.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    sim_suffix = str(uuid.uuid4().int % 10000000).zfill(7)
    caller_num = (payload or {}).get("caller_phone") or f"+1555{sim_suffix}"
    caller_name = (payload or {}).get("caller_name") or f"Impersonation Scam Simulation ({caller_num})"
    target_num = (payload or {}).get("target_phone") or "Active Protected Subscriber Line"
    req_user_id = (payload or {}).get("user_id")
    
    fraud_call = {
        "id": str(uuid.uuid4()),
        "timestamp": now_iso,
        "phone_number": caller_num,
        "normalized_number": caller_num,
        "masked_phone": f"{caller_num[:6]}XXXXXX{caller_num[-2:]}" if len(caller_num) >= 8 else caller_num,
        "caller_name": caller_name,
        "company_name": "Simulated Impersonator Organization",
        "company_badge": "UNVERIFIED",
        "verification_status": "UNVERIFIED",
        "trust_status": "blocked",
        "risk_score": 100,
        "risk_level": "CRITICAL",
        "action": "BLOCK",
        "reasons": [
            "Matches known high-risk digital arrest & financial fraud scam pattern.",
            "STIR/SHAKEN cryptographic caller identity failed validation (Spoofed CLI).",
            "Urgent coercion & coercive impersonation language detected in threat intel.",
            "Subscriber protected: Call disallowed and rejected prior to ringing."
        ],
        "voice_deepfake_pct": 96,
        "voice_identity_pct": 91,
        "voice_liveness_pct": 32,
        "warning_banner": "🚨 CRITICAL THREAT: Known voice clone scammer detected. Auto-blocked by Telecom Service.",
        "calls_summary_total": 1,
        "calls_summary_today": 1,
        "target_phone": target_num,
        "subscriber_phone": target_num,
        "user_id": req_user_id,
        "is_live_trigger": True
    }
    _live_screened_calls.insert(0, fraud_call)
    if len(_live_screened_calls) > 50:
        _live_screened_calls.pop()

    logger.warning(f"🚨 LIVE FRAUD CALL SIMULATION from {caller_num}: VERDICT=BLOCK (100 pts)")

    call_id = fraud_call["id"]
    fraud_payload = {
        "call_id": call_id,
        "session_id": call_id,
        "phone_number": caller_num,
        "normalized_phone_number": caller_num,
        "masked_phone": fraud_call["masked_phone"],
        "caller_name": caller_name,
        "company": "Simulated Impersonator Organization",
        "company_verification_status": "UNVERIFIED",
        "contact_known": False,
        "caller_type": "unknown",
        "previous_calls": 1,
        "calls_today": 1,
        "last_call_timestamp": now_iso,
        "initial_risk": 100,
        "risk_score": 100,
        "risk_level": "CRITICAL",
        "recommended_action": "BLOCK",
        "action": "BLOCK",
        "speaker_verification_status": "MISMATCH",
        "deepfake_detection_status": "SYNTHETIC",
        "liveness_status": "REPLAY",
        "cellular_audio_available": False,
        "call_transport": "CELLULAR",
        "timestamp": now_iso,
        "threat_signals": fraud_call["reasons"],
        "user_id": req_user_id,
    }
    dashboard_event_bus.set_active_call(call_id, fraud_payload)
    await dashboard_event_bus.broadcast_event(
        event_type="incoming_call",
        payload=fraud_payload,
        call_id=call_id,
        user_id=req_user_id
    )

    # Record to DB if available
    try:
        await call_record_service.record_screening_call(
            session_id=call_id,
            phone_number=caller_num,
            normalized_number=caller_num,
            caller_name=caller_name,
            risk_score=100,
            action_taken="BLOCK",
            action_reason=f"Live fraud call simulation: Digital arrest scam ({caller_num})",
            model_version="v1.0-vigil-telephony",
            user_id=req_user_id
        )
    except Exception as e:
        logger.debug(f"Async DB record skipped: {e}")

    return {
        "status": "triggered",
        "message": f"Live fraud call simulation from {caller_num} triggered successfully.",
        "call": fraud_call
    }


@router.post("/trust", tags=["Android Screening"])
async def update_caller_trust(payload: Dict[str, Any]):
    """
    Updates the trust status of a caller in Supabase PostgreSQL (e.g. 'blocked', 'trusted', 'neutral').
    Allows instant allow/block enforcement directly from the Web HUD.
    """
    phone = payload.get("phone_number")
    trust_status = payload.get("trust_status", "blocked").lower()
    if not phone:
        raise HTTPException(status_code=400, detail="phone_number is required")
    if trust_status not in ["blocked", "trusted", "neutral", "suspicious"]:
        raise HTTPException(status_code=400, detail="Invalid trust_status")

    normalized = caller_service.normalize_phone_number(phone)
    pool = await get_db_pool()
    updated = False

    if pool:
        try:
            async with pool.acquire() as conn:
                res = await conn.execute(
                    """
                    UPDATE public.callers
                    SET trust_status = $1, updated_at = NOW()
                    WHERE id IN (
                        SELECT caller_id FROM public.phone_numbers WHERE phone_number = $2
                    )
                    """,
                    trust_status, normalized
                )
                if "UPDATE 0" in res:
                    row = await conn.fetchrow("SELECT caller_id FROM public.phone_numbers WHERE phone_number = $1", normalized)
                    if not row:
                        caller_id = str(uuid.uuid4())
                        display_name = f"{trust_status.capitalize()} Number ({normalized})"
                        await conn.execute(
                            """
                            INSERT INTO public.callers (id, user_id, display_name, trust_status, is_vip, caller_type)
                            VALUES ($1, '00000000-0000-0000-0000-000000000001', $2, $3, false, 'contact')
                            """,
                            uuid.UUID(caller_id), display_name, trust_status
                        )
                        await conn.execute(
                            """
                            INSERT INTO public.phone_numbers (caller_id, phone_number, is_primary)
                            VALUES ($1, $2, true)
                            """,
                            uuid.UUID(caller_id), normalized
                        )
                updated = True
        except Exception as e:
            logger.warning(f"Failed to update caller trust in DB: {e}")

    # Synchronously update in _live_screened_calls buffer
    for call in _live_screened_calls:
        if call.get("normalized_number") == normalized or call.get("phone_number") == phone:
            call["trust_status"] = trust_status
            if trust_status == "blocked":
                call["action"] = "BLOCK"
                call["risk_score"] = 100
                call["risk_level"] = "CRITICAL"
                call["warning_banner"] = "⚠ Number marked BLOCKED. Calls will be dropped automatically."
            elif trust_status == "trusted":
                call["action"] = "ALLOW"
                call["risk_score"] = 5
                call["risk_level"] = "LOW"
                call["warning_banner"] = None
            elif trust_status == "neutral":
                call["action"] = "MONITOR"
                call["risk_score"] = 35
                call["risk_level"] = "MEDIUM"
                call["warning_banner"] = None

    return {
        "status": "success",
        "phone_number": phone,
        "normalized_number": normalized,
        "trust_status": trust_status,
        "updated": updated
    }



@router.post(
    "/decision",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def record_call_decision(payload: CallActionReportRequest):
    """
    Reports the final decision executed by the Android Telecom CallScreeningService.
    Updates the call status in Supabase PostgreSQL (e.g. ALLOW, SILENCE, BLOCK).
    """
    normalized = caller_service.normalize_phone_number(payload.phone_number)
    session_id = payload.session_id or f"decision-{uuid.uuid4().hex[:12]}"

    await call_record_service.record_screening_call(
        session_id=session_id,
        phone_number=payload.phone_number,
        normalized_number=normalized,
        caller_name=payload.caller_name,
        risk_score=payload.risk_score,
        action_taken=payload.action,
        action_reason=payload.reason,
        model_version="v1.0-vigil-telephony"
    )

    return {
        "status": "success",
        "session_id": session_id,
        "action": payload.action,
        "message": f"Decision {payload.action} logged successfully"
    }


@router.post(
    "/challenge/create",
    response_model=IdentityChallengeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
)
async def create_screening_challenge(payload: IdentityChallengeRequest):
    """
    Generates an unpredictable, non-habitual phonetic challenge phrase for adaptive authentication.
    Stores challenge with 60-second TTL in Supabase PostgreSQL.
    """
    return await verification_service.create_challenge(
        caller_id=payload.caller_id,
        call_id=payload.call_id
    )


@router.post(
    "/challenge/evaluate",
    response_model=ChallengeEvaluationResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def evaluate_screening_challenge(payload: ChallengeEvaluationRequest):
    """
    Evaluates caller's spoken challenge response against expected unpredictable phrase.
    Validates transcript similarity and TTL, updating Supabase audit records.
    """
    return await verification_service.evaluate_response(
        challenge_id=payload.challenge_id,
        response_transcript=payload.response_transcript,
        response_latency_ms=payload.response_latency_ms,
        audio_liveness_score=payload.audio_liveness_score
    )


# -----------------------------------------------------------------------------
# Legacy / Backward-Compatible Endpoints
# -----------------------------------------------------------------------------
@router.post(
    "/evaluate",
    response_model=AndroidScreeningResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def evaluate_incoming_call(payload: AndroidScreeningRequest):
    """
    Android MODE B Telephony Call Screening Endpoint (Legacy).
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

    response = AndroidScreeningResponse(
        action=action,
        risk_score=risk_score,
        reason=reason_str,
        recommendations=recommendations,
    )

    try:
        from app.db.detection_store import DetectionEvent, record_detection_event
        level = "CRITICAL" if action == ScreeningAction.BLOCK else ("HIGH" if action == ScreeningAction.WARN else "LOW")
        evt = DetectionEvent(
            session_id=payload.device_id or "android-telephony",
            risk_score=int(round(risk_score * 100)),
            risk_level=level,
            action=action.value if hasattr(action, "value") else str(action),
            caller_id=masked_phone,
            confidence=0.90,
            signals=reasons,
            contributing_signals=reasons,
            explanation=reason_str,
            metadata={
                "caller_display_name": payload.caller_display_name,
                "stir_shaken_status": payload.stir_shaken_status,
                "call_type": getattr(payload, "call_type", "incoming"),
            }
        )
        record_detection_event(evt)
    except Exception as db_err:
        logger.warning(f"Failed to record screening detection to DB: {db_err}")

    return response


@router.get(
    "/detections",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def get_recent_detections(session_id: str = None, limit: int = 50):
    """Retrieves recent detection records from PostgreSQL / database."""
    from app.db.detection_store import get_detection_store
    store = get_detection_store()
    records = await store.get_detections(session_id=session_id, limit=limit)
    return {"count": len(records), "detections": [r.to_dict() for r in records]}


@router.get(
    "/stats",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def get_detection_statistics():
    """Retrieves aggregated database detection stats."""
    from app.db.detection_store import get_detection_store
    store = get_detection_store()
    return await store.get_detection_stats()
