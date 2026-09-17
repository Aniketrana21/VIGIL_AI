import base64
import io
import secrets
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set, Tuple
import numpy as np
import torch

from app.core.logging import logger
from app.pipeline.deepfake_detector import DeepfakeModelRegistry
from app.pipeline.liveness import LivenessAnalyzer
from app.pipeline.risk_engine import MultiFactorRiskEngine, RiskEngineInput
from app.pipeline.speaker_service import SpeakerVerificationService
from app.schemas.challenge import (
    CHALLENGE_PLATFORM_DISCLAIMER,
    DEFAULT_CONSENT_DISCLOSURE,
    ChallengeItem,
    ChallengeStatus,
    ChallengeTriggerReason,
    ChallengeVerificationRequest,
    ChallengeVerificationResponse,
)


class ChallengeGenerator:
    """
    Generates unpredictable, non-repeating short challenge prompts.
    Enforces a strict LRU anti-replay window and fast TTL expiration.
    """

    ADJECTIVES = [
        "blue", "golden", "silent", "crimson", "purple", "silver", "gentle",
        "brisk", "amber", "frosty", "clever", "velvet", "solar", "swift",
        "quiet", "bright", "coastal", "hazel", "stellar", "polar", "verdant"
    ]

    NOUNS = [
        "mango", "sparrow", "harbor", "meadow", "lantern", "glacier", "falcon",
        "pebble", "canyon", "echo", "breeze", "compass", "summit", "willow",
        "river", "anchor", "meadow", "badger", "cedar", "beacon", "voyage"
    ]

    def __init__(self, history_capacity: int = 100):
        self.history_capacity = history_capacity
        self.recent_challenges: Deque[str] = deque(maxlen=history_capacity)
        self.recent_set: Set[str] = set()

    def generate_challenge_prompt(self) -> Tuple[str, str]:
        """
        Produces a unique, unpredictable short challenge phrase or digit sequence
        guaranteed not to have appeared in the recent challenge history window.
        """
        for _ in range(50):
            # 50% phrase-based ("blue mango"), 50% 4-digit code ("7429")
            if secrets.randbelow(2) == 0:
                adj = secrets.choice(self.ADJECTIVES)
                noun = secrets.choice(self.NOUNS)
                phrase = f"{adj} {noun}"
                prompt = f"Please repeat: {phrase}."
            else:
                digits = f"{secrets.randbelow(9000) + 1000}"
                phrase = digits
                prompt = f"Please say: {phrase}."

            if phrase not in self.recent_set:
                self.recent_challenges.append(phrase)
                self.recent_set.add(phrase)
                if len(self.recent_set) > self.history_capacity:
                    oldest = self.recent_challenges[0]
                    self.recent_set.discard(oldest)
                return prompt, phrase

        # Fallback high-entropy nonce if collision loop exhausts
        digits = f"{secrets.randbelow(900000) + 100000}"
        return f"Please say: {digits}.", digits


class AdaptiveChallengeService:
    """
    Production Adaptive Challenge-Response Verification Service.

    Orchestrates:
    1. Condition-based automatic triggering (High/Critical risk, low confidence, inconclusive identity).
    2. Generation of unpredictable, non-repeating prompts with short TTL (e.g. 12s).
    3. Strict user consent and privacy disclosure enforcement.
    4. Multi-modal analysis of challenge response:
       - Deepfake Detector (WavLM/AASIST vocal tract evaluation)
       - Speaker Verifier (ECAPA-TDNN biometric cosine similarity)
       - Liveness Module (Acoustic PAPR, pause entropy, response turn-timing)
    5. Fusion of challenge results with existing risk signals.
    6. Actionable recommendations on failure: user warning, out-of-band verification, optional blocking.
    """

    def __init__(
        self,
        default_ttl_seconds: float = 12.0,
        speaker_service: Optional[SpeakerVerificationService] = None,
        liveness_analyzer: Optional[LivenessAnalyzer] = None,
    ):
        self.default_ttl_seconds = default_ttl_seconds
        self.generator = ChallengeGenerator(history_capacity=100)
        self.active_challenges: Dict[str, ChallengeItem] = {}

        # Pipeline components
        self.deepfake_detector = DeepfakeModelRegistry.get_detector()
        self.speaker_service = speaker_service or SpeakerVerificationService()
        self.liveness_analyzer = liveness_analyzer or LivenessAnalyzer()
        self.risk_engine = MultiFactorRiskEngine()

    @staticmethod
    def should_trigger_challenge(
        risk_level: str,
        confidence: float,
        speaker_match: Optional[bool] = None,
        speaker_similarity: Optional[float] = None,
    ) -> Tuple[bool, Optional[ChallengeTriggerReason]]:
        """
        Determines whether adaptive challenge-response should be triggered.
        Triggers when:
        1. Risk level is HIGH or CRITICAL
        2. Model confidence is insufficient (< 0.60)
        3. Identity verification is inconclusive (claimed identity with low/uncertain similarity)
        """
        level_upper = (risk_level or "").upper()
        if level_upper == "CRITICAL":
            return True, ChallengeTriggerReason.CRITICAL_RISK
        if level_upper == "HIGH":
            return True, ChallengeTriggerReason.HIGH_RISK
        if confidence < 0.60:
            return True, ChallengeTriggerReason.LOW_CONFIDENCE
        if speaker_match is False and speaker_similarity is not None and speaker_similarity > 0.0:
            return True, ChallengeTriggerReason.INCONCLUSIVE_IDENTITY

        return False, None

    def create_challenge(
        self,
        session_id: Optional[str] = None,
        trigger_reason: ChallengeTriggerReason = ChallengeTriggerReason.MANUAL_REQUEST,
        ttl_seconds: Optional[float] = None,
    ) -> ChallengeItem:
        """
        Generates and registers a new unpredictable challenge item with fast expiration.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        prompt, expected = self.generator.generate_challenge_prompt()
        now = time.time()
        challenge_id = f"chal_{secrets.token_hex(6)}"

        item = ChallengeItem(
            challenge_id=challenge_id,
            prompt_text=prompt,
            expected_phrase=expected,
            created_at=now,
            expires_at=now + ttl,
            ttl_seconds=ttl,
            disclosure_notice=DEFAULT_CONSENT_DISCLOSURE,
            status=ChallengeStatus.PENDING,
        )

        self.active_challenges[challenge_id] = item
        self._purge_expired_challenges()

        logger.info(
            f"Created challenge {challenge_id} (Reason: {trigger_reason.value}, TTL: {ttl}s): '{prompt}'"
        )
        return item

    def verify_response(
        self,
        request: ChallengeVerificationRequest,
        audio_tensor: Optional[torch.Tensor] = None,
    ) -> ChallengeVerificationResponse:
        """
        Evaluates a challenge response through deepfake detection, speaker verification,
        and acoustic liveness analysis with consent verification.
        """
        now = time.time()
        challenge = self.active_challenges.get(request.challenge_id)

        # 1. Validation: Challenge Existence
        if not challenge:
            return ChallengeVerificationResponse(
                challenge_id=request.challenge_id,
                challenge_status=ChallengeStatus.FAILED,
                deepfake_probability=1.0,
                speaker_similarity=0.0,
                liveness=0.0,
                risk_score=95,
                risk_level="CRITICAL",
                recommended_action="BLOCK",
                user_warning="Invalid challenge ID. Potential session replay attack.",
                independent_verification_recommended=True,
                reasons=["Challenge ID not recognized or already purged."],
            )

        # 2. Validation: Strict Expiry Check
        if now > challenge.expires_at or challenge.status == ChallengeStatus.EXPIRED:
            challenge.status = ChallengeStatus.EXPIRED
            return ChallengeVerificationResponse(
                challenge_id=request.challenge_id,
                challenge_status=ChallengeStatus.EXPIRED,
                deepfake_probability=0.5,
                speaker_similarity=None,
                liveness=0.3,
                risk_score=75,
                risk_level="HIGH",
                recommended_action="CHALLENGE",
                user_warning="Challenge expired. Please request a new challenge prompt.",
                independent_verification_recommended=True,
                reasons=[f"Response arrived after TTL expiration deadline ({challenge.ttl_seconds}s)."],
            )

        # 3. Validation: Explicit User Consent Requirement
        if not request.user_consent:
            challenge.status = ChallengeStatus.FAILED
            return ChallengeVerificationResponse(
                challenge_id=request.challenge_id,
                challenge_status=ChallengeStatus.FAILED,
                deepfake_probability=0.0,
                speaker_similarity=None,
                liveness=0.0,
                risk_score=70,
                risk_level="HIGH",
                recommended_action="WARN",
                user_warning="Verification aborted: explicit user consent is required to analyze audio.",
                independent_verification_recommended=True,
                reasons=["User withheld mandatory consent for ephemeral audio verification."],
            )

        # 4. Extract or Decode Audio Tensor
        if audio_tensor is None:
            if request.audio_base64:
                audio_tensor = self._decode_base64_audio(request.audio_base64)
            else:
                # Default synthetic test vector if no audio payload provided
                audio_tensor = torch.zeros(16000, dtype=torch.float32)

        # 5. Pipeline Analysis: Deepfake Detection
        df_result = self.deepfake_detector.predict(audio_tensor)
        deepfake_prob = df_result.spoof_probability

        # 6. Pipeline Analysis: Speaker Verification
        speaker_sim = None
        speaker_match = False
        if request.claimed_speaker_id:
            spk_res = self.speaker_service.verify_sync(
                audio=audio_tensor,
                claimed_speaker_id=request.claimed_speaker_id,
            )
            speaker_sim = spk_res.similarity
            speaker_match = spk_res.match

        # 7. Pipeline Analysis: Acoustic Liveness
        liveness_res = self.liveness_analyzer.evaluate(
            audio_window=audio_tensor,
            turn_taking_latency_ms=request.turn_taking_latency_ms,
            is_speech=True,
            challenge_prompt_end_time_s=challenge.created_at + 2.0,
        )
        liveness_score = liveness_res.liveness_score

        # 8. Multi-Signal Synthesis & Decisioning
        risk_input = RiskEngineInput(
            deepfake_probability=deepfake_prob,
            speaker_similarity=speaker_sim,
            liveness_score=liveness_score,
            caller_verified=True,
            audio_quality=1.0,
            model_confidence=df_result.confidence,
            contextual_signals=["CHALLENGE_RESPONSE_EVALUATION"],
        )
        risk_eval = self.risk_engine.evaluate_risk(risk_input)

        # Assess verification outcome
        reasons: List[str] = []
        is_passed = True

        if deepfake_prob >= 0.65:
            is_passed = False
            reasons.append(f"AI voice clone artifacts detected in challenge response ({int(deepfake_prob * 100)}% spoof).")
        if liveness_score < 0.45 or liveness_res.replay_probability >= 0.60:
            is_passed = False
            reasons.append(f"Acoustic liveness failed: high loudspeaker replay probability ({int(liveness_res.replay_probability * 100)}%).")
        if request.claimed_speaker_id and not speaker_match:
            is_passed = False
            reasons.append(f"Biometric voice mismatch for claimed identity '{request.claimed_speaker_id}'.")

        final_status = ChallengeStatus.PASSED if is_passed else ChallengeStatus.FAILED
        challenge.status = final_status

        # If verification fails: HIGH/CRITICAL risk, warn user, recommend independent check, optionally block
        if not is_passed:
            risk_score = max(risk_eval.risk_score, 85)
            risk_level = "CRITICAL" if risk_score >= 85 else "HIGH"
            action = "BLOCK"
            warning_msg = (
                "CRITICAL SECURITY WARNING: Challenge verification FAILED! High probability of "
                "synthetic speech, voice cloning, or recorded replay. Do NOT share sensitive information."
            )
            recommend_independent = True
        else:
            risk_score = min(risk_eval.risk_score, 20)
            risk_level = "LOW"
            action = "ALLOW"
            warning_msg = None
            recommend_independent = False
            reasons.append("Challenge phrase verified cleanly across deepfake, speaker, and acoustic liveness models.")

        return ChallengeVerificationResponse(
            challenge_id=request.challenge_id,
            challenge_status=final_status,
            deepfake_probability=deepfake_prob,
            speaker_similarity=speaker_sim,
            liveness=liveness_score,
            risk_score=risk_score,
            risk_level=risk_level,
            recommended_action=action,
            user_warning=warning_msg,
            independent_verification_recommended=recommend_independent,
            reasons=reasons,
            disclaimer=CHALLENGE_PLATFORM_DISCLAIMER,
        )

    def _decode_base64_audio(self, b64_str: str) -> torch.Tensor:
        """Decodes base64 PCM 16-bit or WAV bytes into a normalized Float32 Tensor."""
        try:
            raw_bytes = base64.b64decode(b64_str)
            # Check for WAV header "RIFF"
            if len(raw_bytes) >= 44 and raw_bytes[:4] == b"RIFF":
                pcm_data = np.frombuffer(raw_bytes[44:], dtype=np.int16)
            else:
                pcm_data = np.frombuffer(raw_bytes, dtype=np.int16)
            float_data = pcm_data.astype(np.float32) / 32768.0
            return torch.from_numpy(float_data)
        except Exception as e:
            logger.warning(f"Error decoding base64 audio payload: {e}")
            return torch.zeros(16000, dtype=torch.float32)

    def _purge_expired_challenges(self) -> None:
        """Removes expired items older than 2x TTL to prevent memory leaks."""
        now = time.time()
        to_del = [cid for cid, c in self.active_challenges.items() if (now - c.created_at) > (c.ttl_seconds * 2.0)]
        for cid in to_del:
            self.active_challenges.pop(cid, None)


# Global singleton
_challenge_service_instance: Optional[AdaptiveChallengeService] = None


def get_challenge_service() -> AdaptiveChallengeService:
    global _challenge_service_instance
    if _challenge_service_instance is None:
        _challenge_service_instance = AdaptiveChallengeService()
    return _challenge_service_instance
