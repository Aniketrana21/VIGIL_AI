"""
VIGIL-AI: Adaptive Identity Challenge-Response Verification Service.
Generates unpredictable, non-habitual phonetic challenge prompts to thwart replay
and voice cloning synthesis attacks.
Security Constraint: NEVER treat a phrase that a person habitually says as a secure credential.
Persists verification challenges and evaluation events to Supabase PostgreSQL.
"""
import uuid
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
import difflib

from app.core.logging import logger
from app.db.connection import get_db_pool
from app.schemas.telecom_screening import (
    IdentityChallengeResponse,
    ChallengeEvaluationResponse
)


class VerificationService:
    """Adaptive Challenge-Response verification service for high-risk or suspicious calls."""

    # Unpredictable phonetic word banks (phonetically balanced, low-confusion)
    ADJECTIVES = [
        "crimson", "amber", "sapphire", "emerald", "silver", "golden", "silent",
        "swift", "velvet", "frosty", "clever", "solar", "polar", "verdant", "rustic"
    ]
    NOUNS = [
        "falcon", "glacier", "harbor", "meadow", "lantern", "beacon", "canyon",
        "compass", "pebble", "willow", "sparrow", "summit", "badger", "anchor"
    ]
    ACTIONS = [
        "crosses", "touches", "circles", "guards", "echoes", "climbs", "follows",
        "reaches", "nests upon", "sweeps across"
    ]
    OBJECTS = [
        "seven bridges", "marble stairs", "quiet shores", "autumn trees",
        "open skies", "crystal rivers", "granite peaks", "evening horizons"
    ]

    # In-memory storage fallback for testing and offline execution
    _memory_challenges: Dict[str, Dict[str, Any]] = {}

    def generate_prompt(self) -> Tuple[str, str]:
        """
        Creates a dynamic, unpredictable challenge phrase.
        Example: 'Sapphire falcon circles marble stairs'
        Never uses habitual greetings or common phrases.
        """
        adj = secrets.choice(self.ADJECTIVES)
        noun = secrets.choice(self.NOUNS)
        act = secrets.choice(self.ACTIONS)
        obj = secrets.choice(self.OBJECTS)
        num = secrets.randbelow(90) + 10  # 2-digit entropy suffix

        expected_response = f"{adj} {noun} {act} {obj} {num}".lower()
        prompt = f"Please repeat clearly: '{adj.capitalize()} {noun} {act} {obj} {num}'"
        return prompt, expected_response

    async def create_challenge(
        self,
        caller_id: Optional[str] = None,
        call_id: Optional[str] = None,
        ttl_seconds: int = 60
    ) -> IdentityChallengeResponse:
        """
        Creates and stores a dynamic challenge in Supabase PostgreSQL.
        Enforces strict TTL (default 60 seconds).
        """
        challenge_id = str(uuid.uuid4())
        prompt, expected_response = self.generate_prompt()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        pool = await get_db_pool()
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    # Caller_id and call_id must be valid UUIDs if provided
                    c_id = uuid.UUID(caller_id) if caller_id else None
                    cl_id = uuid.UUID(call_id) if call_id else None

                    await conn.execute("""
                        INSERT INTO public.identity_challenges (
                            id, call_id, caller_id, challenge_type, prompt, 
                            expected_response, status, expires_at, created_at
                        ) VALUES ($1, $2, $3, 'phonetic_utterance', $4, $5, 'PENDING', $6, $7);
                    """, uuid.UUID(challenge_id), cl_id, c_id, prompt, expected_response, expires_at, now)
            except Exception as e:
                logger.warning(f"Failed to persist identity challenge to Supabase ({e}). Using memory fallback.")

        # Fallback tracking
        self._memory_challenges[challenge_id] = {
            "id": challenge_id,
            "caller_id": caller_id,
            "call_id": call_id,
            "prompt": prompt,
            "expected_response": expected_response,
            "status": "PENDING",
            "expires_at": expires_at,
            "created_at": now
        }

        return IdentityChallengeResponse(
            challenge_id=challenge_id,
            prompt=prompt,
            expires_in_sec=ttl_seconds,
            expected_response_type="spoken_audio"
        )

    async def evaluate_response(
        self,
        challenge_id: str,
        response_transcript: str,
        response_latency_ms: Optional[float] = None,
        audio_liveness_score: Optional[float] = None
    ) -> ChallengeEvaluationResponse:
        """
        Evaluates the caller's spoken response transcript against expected phrase.
        Computes normalized similarity score and verifies TTL.
        Updates Supabase PostgreSQL and appends a verification_event.
        """
        now = datetime.now(timezone.utc)
        record = self._memory_challenges.get(challenge_id)
        expected = None
        call_id = None

        pool = await get_db_pool()
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT id, call_id, expected_response, status, expires_at 
                        FROM public.identity_challenges 
                        WHERE id = $1;
                    """, uuid.UUID(challenge_id))
                    if row:
                        expected = row["expected_response"]
                        expires_at = row["expires_at"]
                        call_id = row["call_id"]
                        current_status = row["status"]
            except Exception as e:
                logger.warning(f"Error reading identity challenge from DB ({e}). Falling back to memory.")

        if expected is None and record:
            expected = record["expected_response"]
            expires_at = record["expires_at"]
            call_id = record.get("call_id")
            current_status = record["status"]

        if not expected:
            return ChallengeEvaluationResponse(
                challenge_id=challenge_id,
                status="FAILED",
                similarity_score=0.0,
                reason="Challenge ID not recognized or already purged."
            )

        # Check Expiration (TTL)
        if now > expires_at:
            self._update_status(challenge_id, "EXPIRED", 0.0, response_latency_ms)
            return ChallengeEvaluationResponse(
                challenge_id=challenge_id,
                status="EXPIRED",
                similarity_score=0.0,
                reason="Challenge time-to-live expired (possible synthetic audio buffering delay)."
            )

        # Compute Text Similarity (normalized Levenshtein / SequenceMatcher)
        norm_expected = " ".join(expected.strip().lower().split())
        norm_actual = " ".join(response_transcript.strip().lower().split())

        matcher = difflib.SequenceMatcher(None, norm_expected, norm_actual)
        similarity = round(float(matcher.ratio()), 3)

        # Evaluate Pass Criteria
        # Must achieve at least 0.70 similarity and if liveness is provided, >= 0.50
        passed = (similarity >= 0.70)
        reasons = []

        if not passed:
            reasons.append(f"Spoken phrase similarity ({similarity:.2f}) was below acceptance threshold 0.70.")
        else:
            reasons.append(f"Spoken phrase matched challenge prompt with {similarity:.1%} similarity.")

        if audio_liveness_score is not None:
            if audio_liveness_score < 0.50:
                passed = False
                reasons.append(f"Acoustic liveness check failed ({audio_liveness_score:.2f} < 0.50).")
            else:
                reasons.append(f"Acoustic liveness confirmed ({audio_liveness_score:.2f}).")

        final_status = "PASSED" if passed else "FAILED"
        reason_str = " ".join(reasons)

        # Update in database and memory
        await self._persist_evaluation_result(
            challenge_id=challenge_id,
            call_id=str(call_id) if call_id else None,
            status=final_status,
            similarity=similarity,
            latency_ms=response_latency_ms,
            reason=reason_str
        )

        return ChallengeEvaluationResponse(
            challenge_id=challenge_id,
            status=final_status,
            similarity_score=similarity,
            reason=reason_str
        )

    async def _persist_evaluation_result(
        self,
        challenge_id: str,
        call_id: Optional[str],
        status: str,
        similarity: float,
        latency_ms: Optional[float],
        reason: str
    ):
        """Records evaluation to identity_challenges and appends verification_events in Supabase."""
        now = datetime.now(timezone.utc)
        if challenge_id in self._memory_challenges:
            self._memory_challenges[challenge_id]["status"] = status
            self._memory_challenges[challenge_id]["similarity_score"] = similarity

        pool = await get_db_pool()
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    # Update identity_challenges
                    await conn.execute("""
                        UPDATE public.identity_challenges
                        SET status = $2,
                            similarity_score = $3,
                            response_latency_ms = $4,
                            evaluated_at = $5
                        WHERE id = $1;
                    """, uuid.UUID(challenge_id), status, similarity, latency_ms, now)

                    # Append to verification_events if linked to a call
                    if call_id:
                        await conn.execute("""
                            INSERT INTO public.verification_events (
                                call_id, verification_type, result, confidence, details, created_at
                            ) VALUES (
                                $1, 'challenge_response', $2, $3, $4::jsonb, $5
                            );
                        """, uuid.UUID(call_id), status, min(1.0, similarity), 
                           f'{{"reason": "{reason}", "challenge_id": "{challenge_id}"}}', now)
            except Exception as e:
                logger.warning(f"Failed to record verification result in Supabase ({e})")

    def _update_status(self, challenge_id: str, status: str, similarity: float, latency_ms: Optional[float]):
        if challenge_id in self._memory_challenges:
            self._memory_challenges[challenge_id]["status"] = status
            self._memory_challenges[challenge_id]["similarity_score"] = similarity
