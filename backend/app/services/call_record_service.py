"""
VIGIL-AI: Central Call Telemetry & Persistence Service.
Stores complete audit records for every incoming call:
- caller identity, company affiliation, verification state, relationship authenticity
- behavioral metrics: calls in 1h, 24h, 7d, average duration, blocked calls count
- telephony metadata, STIR/SHAKEN results
- real-time ML telemetry (speaker similarity, deepfake probability, liveness, replay)
- risk engine scores, levels, reasons, and policy actions.
Persists strictly to Supabase PostgreSQL (never storing raw audio).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from app.core.logging import logger
from app.db.connection import get_db_pool

DEFAULT_SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"


class CallRecordService:
    """Service to create, update, and finalize comprehensive call records in Supabase PostgreSQL."""

    # In-memory store fallback for offline tests
    _memory_calls: Dict[str, Dict[str, Any]] = {}

    async def record_screening_call(
        self,
        session_id: str,
        phone_number: str,
        normalized_number: str,
        caller_id: Optional[str] = None,
        caller_name: Optional[str] = None,
        company_name: Optional[str] = None,
        company_verified: bool = False,
        company_name_claimed: Optional[str] = None,
        company_name_verified: bool = False,
        verification_source: str = "caller_claim",
        verification_status: str = "UNVERIFIED",
        relationship: str = "UNKNOWN",
        relationship_verified: bool = False,
        caller_type: str = "unknown",
        previous_calls_count: int = 0,
        calls_last_1h: int = 0,
        calls_last_24h: int = 0,
        calls_last_7d: int = 0,
        average_call_duration: int = 0,
        failed_verifications: int = 0,
        suspicious_calls: int = 0,
        blocked_calls: int = 0,
        risk_score: int = 0,
        risk_level: str = "LOW",
        action_taken: str = "ALLOW",
        action_reason: str = "Screened via Telecom framework",
        model_version: str = "v1.0-vigil-telephony",
        user_id: Optional[str] = None,
        device_id: Optional[str] = None
    ) -> str:
        """
        Creates or updates a record for an incoming screened call in public.calls and public.call_actions.
        Returns the call UUID.
        """
        call_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        resolved_user_id = user_id or DEFAULT_SYSTEM_USER_ID

        call_data = {
            "id": call_id,
            "session_id": session_id,
            "user_id": resolved_user_id,
            "device_id": device_id,
            "caller_id": caller_id,
            "caller_name_at_time": caller_name,
            "phone_number_at_time": phone_number,
            "normalized_number": normalized_number,
            "started_at": now,
            "direction": "inbound",
            "call_status": "blocked" if action_taken == "BLOCK" else "ringing",
            "previous_calls_count": previous_calls_count,
            "company_name_at_time": company_name,
            "company_verified_at_time": company_verified,
            "company_name_claimed": company_name_claimed or company_name,
            "company_name_verified": company_name_verified,
            "verification_source": verification_source,
            "verification_status": verification_status,
            "relationship": relationship,
            "relationship_verified": relationship_verified,
            "calls_last_1_hour": calls_last_1h,
            "calls_last_24_hours": calls_last_24h,
            "calls_last_7_days": calls_last_7d,
            "average_call_duration": average_call_duration,
            "failed_verifications": failed_verifications,
            "suspicious_calls": suspicious_calls,
            "blocked_calls": blocked_calls,
            "caller_type": caller_type,
            "overall_risk_score": risk_score,
            "overall_risk_level": risk_level,
            "final_action": action_taken,
            "action_reason": action_reason,
            "model_version": model_version,
            "created_at": now
        }
        self._memory_calls[session_id] = call_data

        pool = await get_db_pool()
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    c_id_uuid = uuid.UUID(caller_id) if caller_id else None
                    u_id_uuid = uuid.UUID(resolved_user_id)
                    d_id_uuid = uuid.UUID(device_id) if device_id else None

                    query = """
                        INSERT INTO public.calls (
                            id, user_id, device_id, caller_id, session_id, started_at, direction, call_status,
                            caller_name_at_time, phone_number_at_time, normalized_number,
                            previous_calls_count, company_name_at_time, company_verified_at_time,
                            company_name_claimed, company_name_verified, verification_source, verification_status,
                            relationship, relationship_verified, calls_last_1_hour, calls_last_24_hours, calls_last_7_days,
                            average_call_duration, failed_verifications, suspicious_calls, blocked_calls,
                            caller_type, overall_risk_score, overall_risk_level, final_action,
                            action_reason, model_version, created_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, 'inbound', $7,
                            $8, $9, $10,
                            $11, $12, $13,
                            $14, $15, $16, $17,
                            $18, $19, $20, $21, $22,
                            $23, $24, $25, $26,
                            $27, $28, $29, $30,
                            $31, $32, $33
                        )
                        ON CONFLICT (session_id) DO UPDATE SET
                            caller_name_at_time = EXCLUDED.caller_name_at_time,
                            overall_risk_score = EXCLUDED.overall_risk_score,
                            overall_risk_level = EXCLUDED.overall_risk_level,
                            final_action = EXCLUDED.final_action,
                            action_reason = EXCLUDED.action_reason
                        RETURNING id;
                    """
                    row = await conn.fetchrow(
                        query,
                        uuid.UUID(call_id),
                        u_id_uuid,
                        d_id_uuid,
                        c_id_uuid,
                        session_id,
                        now,
                        "blocked" if action_taken == "BLOCK" else "ringing",
                        caller_name,
                        phone_number,
                        normalized_number,
                        previous_calls_count,
                        company_name,
                        company_verified,
                        company_name_claimed or company_name,
                        company_name_verified,
                        verification_source,
                        verification_status,
                        relationship,
                        relationship_verified,
                        calls_last_1h,
                        calls_last_24h,
                        calls_last_7d,
                        average_call_duration,
                        failed_verifications,
                        suspicious_calls,
                        blocked_calls,
                        caller_type,
                        risk_score,
                        risk_level,
                        action_taken,
                        action_reason,
                        model_version,
                        now
                    )
                    if row:
                        call_id = str(row["id"])

                    # Append into public.call_actions
                    action_query = """
                        INSERT INTO public.call_actions (
                            call_id, action, reason, risk_score, triggered_by, performed_at
                        ) VALUES ($1, $2, $3, $4, 'screening_manager', $5);
                    """
                    await conn.execute(
                        action_query,
                        uuid.UUID(call_id),
                        action_taken,
                        action_reason,
                        risk_score,
                        now
                    )
            except Exception as e:
                logger.warning(f"Error persisting call record in Supabase ({e}). Stored in memory.")

        return call_id

    async def update_voip_telemetry(
        self,
        session_id: str,
        speaker_similarity: Optional[float] = None,
        deepfake_probability: Optional[float] = None,
        liveness_score: Optional[float] = None,
        replay_probability: Optional[float] = None,
        model_confidence: Optional[float] = None,
        duration_seconds: Optional[int] = None,
        final_action: Optional[str] = None
    ):
        """Updates real-time ML and voice analysis telemetry once VoIP audio analysis is performed."""
        now = datetime.now(timezone.utc)
        if session_id in self._memory_calls:
            c = self._memory_calls[session_id]
            if speaker_similarity is not None: c["speaker_similarity"] = speaker_similarity
            if deepfake_probability is not None: c["deepfake_probability"] = deepfake_probability
            if liveness_score is not None: c["liveness_score"] = liveness_score
            if replay_probability is not None: c["replay_probability"] = replay_probability
            if model_confidence is not None: c["model_confidence"] = model_confidence
            if duration_seconds is not None:
                c["duration_seconds"] = duration_seconds
                c["ended_at"] = now
            if final_action: c["final_action"] = final_action

        pool = await get_db_pool()
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE public.calls
                        SET speaker_similarity = COALESCE($2, speaker_similarity),
                            deepfake_probability = COALESCE($3, deepfake_probability),
                            liveness_score = COALESCE($4, liveness_score),
                            replay_probability = COALESCE($5, replay_probability),
                            model_confidence = COALESCE($6, model_confidence),
                            duration_seconds = COALESCE($7, duration_seconds),
                            ended_at = CASE WHEN $7 IS NOT NULL THEN $8 ELSE ended_at END,
                            final_action = COALESCE($9, final_action),
                            call_status = CASE WHEN $7 IS NOT NULL THEN 'completed' ELSE call_status END
                        WHERE session_id = $1;
                    """, session_id, speaker_similarity, deepfake_probability, liveness_score,
                       replay_probability, model_confidence, duration_seconds, now, final_action)
            except Exception as e:
                logger.warning(f"Error updating VoIP telemetry in Supabase ({e})")
