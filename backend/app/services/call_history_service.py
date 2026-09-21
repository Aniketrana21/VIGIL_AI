"""
VIGIL-AI: Call History & Behavioral Velocity Analytics Service.
Aggregates historical call volume, burst frequency (1h, 24h, 7d), average duration,
suspicious security events, and historical failed verifications dynamically from Supabase PostgreSQL.
Detects behavioral call flood anomalies (e.g. 5+ calls in 1 hour or 10+ in 24 hours).
Zero hardcoded phone numbers.
"""
from typing import Optional, Dict
from datetime import datetime, timezone, timedelta
from app.core.logging import logger
from app.db.connection import get_db_pool
from app.schemas.telecom_screening import CallHistorySummary
from app.services.call_record_service import CallRecordService


class CallHistoryService:
    """Service for computing multi-window call velocity and behavioral anomalies dynamically."""

    async def get_history_summary(
        self,
        normalized_number: str,
        caller_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> CallHistorySummary:
        """
        Retrieves call history statistics across 1-hour, 24-hour, and 7-day windows.
        Flags behavioral velocity anomalies dynamically for the given caller and user.
        """
        pool = await get_db_pool()

        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    # Query statistics scoped to number and optionally user
                    call_stats = await conn.fetchrow("""
                        SELECT 
                            COUNT(*) AS total_calls,
                            COUNT(*) FILTER (WHERE started_at >= NOW() - INTERVAL '1 hour') AS calls_1h,
                            COUNT(*) FILTER (WHERE started_at >= NOW() - INTERVAL '24 hours') AS calls_24h,
                            COUNT(*) FILTER (WHERE started_at >= NOW() - INTERVAL '7 days') AS calls_7d,
                            COALESCE(AVG(duration_seconds) FILTER (WHERE duration_seconds IS NOT NULL), 0)::int AS avg_duration,
                            COUNT(*) FILTER (WHERE final_action = 'BLOCK' OR call_status = 'blocked') AS blocked_calls
                        FROM public.calls
                        WHERE (normalized_number = $1 OR (caller_id IS NOT NULL AND caller_id = $2::uuid))
                          AND ($3::uuid IS NULL OR user_id = $3::uuid);
                    """, normalized_number, caller_id, user_id)

                    total_calls = call_stats["total_calls"] if call_stats else 0
                    calls_1h = call_stats["calls_1h"] if call_stats else 0
                    calls_24h = call_stats["calls_24h"] if call_stats else 0
                    calls_7d = call_stats["calls_7d"] if call_stats else 0
                    avg_duration = call_stats["avg_duration"] if call_stats else 0
                    blocked_calls = call_stats["blocked_calls"] if call_stats else 0

                    # Suspicious risk events
                    susp_row = await conn.fetchval("""
                        SELECT COUNT(re.id)
                        FROM public.risk_events re
                        JOIN public.calls c ON c.id = re.call_id
                        WHERE c.normalized_number = $1
                          AND ($2::uuid IS NULL OR c.user_id = $2::uuid)
                          AND re.risk_level IN ('HIGH', 'CRITICAL');
                    """, normalized_number, user_id)
                    suspicious_events = susp_row or 0

                    # Failed verification attempts
                    failed_row = await conn.fetchval("""
                        SELECT COUNT(ve.id)
                        FROM public.verification_events ve
                        JOIN public.calls c ON c.id = ve.call_id
                        WHERE c.normalized_number = $1
                          AND ($2::uuid IS NULL OR c.user_id = $2::uuid)
                          AND ve.result = 'FAILED';
                    """, normalized_number, user_id)
                    failed_verifications = failed_row or 0

                    # Behavioral Anomaly Detection
                    anomaly = False
                    anomaly_reason = None
                    if calls_1h >= 5:
                        anomaly = True
                        anomaly_reason = f"Rapid burst call flood: {calls_1h} calls in last 1 hour (robocall/harassment pattern)"
                    elif calls_24h >= 10:
                        anomaly = True
                        anomaly_reason = f"High-frequency call flood: {calls_24h} calls in last 24 hours"

                    return CallHistorySummary(
                        total_calls=total_calls,
                        calls_last_1h=calls_1h,
                        calls_last_24h=calls_24h,
                        calls_last_7d=calls_7d,
                        average_call_duration_sec=avg_duration,
                        suspicious_events=suspicious_events,
                        failed_verifications=failed_verifications,
                        blocked_calls=blocked_calls,
                        behavioral_anomaly=anomaly,
                        behavioral_anomaly_reason=anomaly_reason
                    )
            except Exception as e:
                logger.warning(f"Database query error in CallHistoryService ({e}). Using memory fallback.")

        # Fallback to computing dynamically from in-memory call records
        return self._compute_memory_history(normalized_number, user_id)

    def _compute_memory_history(self, normalized_number: str, user_id: Optional[str] = None) -> CallHistorySummary:
        """Computes history dynamically from in-memory recorded calls without any static data."""
        matching_calls = [
            c for c in CallRecordService._memory_calls.values()
            if c.get("normalized_number") == normalized_number and
               (user_id is None or c.get("user_id") == user_id)
        ]

        if not matching_calls:
            return CallHistorySummary()

        now = datetime.now(timezone.utc)
        one_h_ago = now - timedelta(hours=1)
        one_d_ago = now - timedelta(days=1)
        seven_d_ago = now - timedelta(days=7)

        total_calls = len(matching_calls)
        calls_1h = sum(1 for c in matching_calls if c.get("started_at", now) >= one_h_ago)
        calls_24h = sum(1 for c in matching_calls if c.get("started_at", now) >= one_d_ago)
        calls_7d = sum(1 for c in matching_calls if c.get("started_at", now) >= seven_d_ago)
        blocked = sum(1 for c in matching_calls if c.get("final_action") in ["BLOCK", "TERMINATE"])

        durations = [c.get("average_call_duration", 0) for c in matching_calls if c.get("average_call_duration")]
        avg_dur = sum(durations) // len(durations) if durations else 0

        anomaly = False
        anomaly_reason = None
        if calls_1h >= 5:
            anomaly = True
            anomaly_reason = f"Rapid burst call flood: {calls_1h} calls in last 1 hour"
        elif calls_24h >= 10:
            anomaly = True
            anomaly_reason = f"High-frequency call flood: {calls_24h} calls in last 24 hours"

        return CallHistorySummary(
            total_calls=total_calls,
            calls_last_1h=calls_1h,
            calls_last_24h=calls_24h,
            calls_last_7d=calls_7d,
            average_call_duration_sec=avg_dur,
            suspicious_events=0,
            failed_verifications=0,
            blocked_calls=blocked,
            behavioral_anomaly=anomaly,
            behavioral_anomaly_reason=anomaly_reason
        )


call_history_service = CallHistoryService()
