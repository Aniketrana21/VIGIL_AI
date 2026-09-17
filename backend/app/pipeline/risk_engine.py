import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import torch

from app.core.config import settings
from app.core.logging import logger
from app.pipeline.interfaces import (
    AntiSpoofResult,
    LivenessResult,
    SpeakerVerificationResult,
    VADResult,
)
from app.schemas.risk import (
    DecisionState,
    DeepfakeMetrics,
    LatencyBreakdown,
    LivenessMetrics,
    RiskVerdict,
    SpeakerVerificationMetrics,
    UncertaintyMetrics,
    VoiceActivityMetrics,
)


@dataclass
class RiskEngineInput:
    """
    Standard input payload for the VIGIL-AI Multi-Signal Risk Engine.
    Combines acoustic deepfake detection, biometric speaker verification,
    acoustic liveness analysis, telephony metadata, audio quality, contextual signals,
    and historical signals.
    """
    deepfake_probability: float
    speaker_similarity: Optional[float] = None
    liveness_score: float = 1.0  # 1.0 = live vocal tract acoustic emission, 0.0 = loudspeaker replay
    replay_probability: Optional[float] = None  # 0.0 to 1.0
    caller_verified: bool = True  # STIR/SHAKEN A-attestation or telephony verification
    conversation_risk: float = 0.0  # 0.0 to 1.0 from Phase 11 Conversation Intelligence
    audio_quality: float = 1.0  # 0.0 = severely clipped/degraded/low-SNR, 1.0 = pristine studio
    model_confidence: float = 1.0  # 0.0 to 1.0 confidence score
    contextual_signals: List[str] = field(default_factory=list)  # e.g. ["FINANCIAL_REQUEST"]
    historical_signals: List[str] = field(default_factory=list)  # e.g. ["PREVIOUS_CHALLENGE_FAILED"]
    caller_id: Optional[str] = None
    session_id: Optional[str] = None

    @property
    def deepfake_score(self) -> float:
        return self.deepfake_probability

    @property
    def caller_verification_status(self) -> bool:
        return self.caller_verified


@dataclass
class RiskEvaluationResult:
    """
    Standard output payload of the Multi-Signal Risk Engine.
    Transparent, human-explainable, non-linear, and policy-versioned.
    Conforms to Phase 12 specification:
    {
      "risk_score": 0-100,
      "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
      "action": "ALLOW | MONITOR | CHALLENGE | WARN | BLOCK",
      "confidence": 0-1,
      "signals": [],
      "explanation": ""
    }
    """
    risk_score: int  # 0-100
    risk_level: str  # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    recommended_action: str  # "ALLOW" | "MONITOR" | "CHALLENGE" | "WARN" | "BLOCK"
    signals: List[str]  # e.g. ["HIGH_SYNTHETIC_PROBABILITY", "SPEAKER_MISMATCH", ...]
    confidence: float  # 0.0 to 1.0
    contributing_signals: List[str] = field(default_factory=list)  # Formatted human-readable descriptions
    explanation: str = ""
    individual_scores: Dict[str, Any] = field(default_factory=dict)
    policy_version: str = "2026.09.1-production"
    requires_human_verification: bool = False

    @property
    def action(self) -> str:
        return self.recommended_action

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "action": self.action,
            "recommended_action": self.recommended_action,
            "signals": self.signals,
            "confidence": round(self.confidence, 3),
            "contributing_signals": self.contributing_signals,
            "explanation": self.explanation or self.format_explanation(),
            "individual_scores": self.individual_scores,
            "policy_version": self.policy_version,
            "requires_human_verification": self.requires_human_verification,
        }

    def format_explanation(self) -> str:
        lines = [
            f"VIGIL-AI Risk Score: {self.risk_score}/100 [{self.risk_level} RISK]",
            f"Action: {self.action} (Confidence: {int(self.confidence * 100)}%)",
            f"Recommended action: {self.action}",
            "",
            "Contributing signals:",
        ]
        if self.contributing_signals:
            for sig in self.contributing_signals:
                lines.append(f"✓ {sig}")
        else:
            lines.append("✓ No abnormal threat signals detected (nominal)")
        lines.append("")
        lines.append("Note: Probabilistic ML assessment. VIGIL-AI does not assert 100% certainty; policy avoids unilateral irreversible action on uncertain data.")
        return "\n".join(lines)


class MultiFactorRiskEngine:
    """
    Multi-Signal Risk & Decision Policy Engine for VIGIL-AI.
    Combines:
    1. Deepfake probability (WavLM + AASIST)
    2. Speaker similarity (ECAPA-TDNN)
    3. Liveness score (Acoustic decay / loudspeaker replay)
    4. Caller verification status (STIR/SHAKEN)
    5. Audio quality / SNR
    6. Model confidence
    7. Contextual risk signals (e.g. FINANCIAL_REQUEST)

    Key Safety Rule:
    When model confidence is low, the engine prefers CHALLENGE / VERIFY rather than
    blindly assuming fake or issuing an unverified BLOCK.
    """

    def __init__(
        self,
        allow_max: int = getattr(settings, "RISK_ALLOW_MAX", 34),
        challenge_max: int = getattr(settings, "RISK_CHALLENGE_MAX", 59),
        warn_max: int = getattr(settings, "RISK_WARN_MAX", 84),
        critical_min: int = getattr(settings, "RISK_CRITICAL_MIN", 85),
        min_confidence_threshold: float = getattr(settings, "RISK_MIN_CONFIDENCE_THRESHOLD", 0.60),
        high_uncertainty_threshold: float = getattr(settings, "HIGH_UNCERTAINTY_THRESHOLD", 0.60),
    ):
        self.allow_max = allow_max
        self.challenge_max = challenge_max
        self.warn_max = warn_max
        self.critical_min = critical_min
        self.min_confidence_threshold = min_confidence_threshold
        self.high_uncertainty_threshold = high_uncertainty_threshold

        # Backward compatibility thresholds for legacy evaluate()
        self.allow_threshold = getattr(settings, "ALLOW_THRESHOLD", 0.35)
        self.warn_threshold = getattr(settings, "WARN_THRESHOLD", 0.60)
        self.block_threshold = getattr(settings, "BLOCK_THRESHOLD", 0.85)

    def evaluate_risk(self, risk_input: RiskEngineInput) -> RiskEvaluationResult:
        """
        Primary Phase 6 Multi-Signal evaluation function.
        Applies transparent, non-linear scoring rules and safety safeguards.
        """
        signals: List[str] = []
        contrib: List[str] = []

        total_points = 0.0

        p_df = max(0.0, min(1.0, float(risk_input.deepfake_probability)))
        sim = float(risk_input.speaker_similarity) if risk_input.speaker_similarity is not None else None
        liveness = max(0.0, min(1.0, float(risk_input.liveness_score)))
        caller_verified = bool(risk_input.caller_verified)
        audio_qual = max(0.0, min(1.0, float(risk_input.audio_quality)))
        conf = max(0.0, min(1.0, float(risk_input.model_confidence)))
        context_signals = [str(s).strip().upper() for s in (risk_input.contextual_signals or [])]

        # 1. Deepfake Probability Scoring
        if p_df >= 0.85:
            # High synthetic threat: adds 45 - 60 points
            df_pts = 45.0 + 15.0 * ((p_df - 0.85) / 0.15)
            total_points += df_pts
            signals.append("HIGH_SYNTHETIC_PROBABILITY")
            contrib.append(f"Synthetic speech probability: {int(round(p_df * 100))}%")
        elif p_df >= 0.50:
            # Moderate synthetic threat: adds 20 - 40 points
            df_pts = 20.0 + 20.0 * ((p_df - 0.50) / 0.35)
            total_points += df_pts
            signals.append("MODERATE_SYNTHETIC_PROBABILITY")
            contrib.append(f"Synthetic speech probability: {int(round(p_df * 100))}%")
        else:
            # Minor or clean
            df_pts = 15.0 * (p_df / 0.50)
            total_points += df_pts

        # 2. Acoustic Liveness (Replay Attack) Scoring
        if liveness < 0.50:
            # Low liveness (< 0.50): loudspeaker replay attack
            live_pts = 40.0 * ((0.50 - liveness) / 0.50)
            if liveness < 0.25:
                live_pts += 10.0  # Severe replay distortion bonus
            total_points += live_pts
            signals.append("LOW_LIVENESS")
            contrib.append(f"Low liveness: {int(round(liveness * 100))}%")

        # 3. Caller Verification Status
        if not caller_verified:
            total_points += 15.0
            signals.append("CALLER_ID_UNVERIFIED")
            contrib.append("Caller verification failed")

        # 4. Speaker Verification & Targeted Clone Attack Synergy
        if sim is not None:
            if sim < 0.85:
                # Discrepancy with claimed identity
                mismatch_ratio = 1.0 - max(0.0, sim)
                mismatch_pct = int(round(mismatch_ratio * 100))
                spk_pts = 35.0 * min(1.0, mismatch_ratio / 0.60)
                total_points += spk_pts
                signals.append("SPEAKER_MISMATCH")
                contrib.append(f"Speaker mismatch: {mismatch_pct}%")

            # TARGETED CLONE DETECTION:
            # Attacker cloning an enrolled victim has HIGH similarity (>= 0.85) AND HIGH synthetic probability (>= 0.85).
            if sim >= 0.85 and p_df >= 0.85:
                total_points += 40.0  # Non-linear synergy penalty
                signals.append("TARGETED_CLONE_DETECTED")
                contrib.append("Targeted voice clone detected (matching enrolled voiceprint with synthetic speech)")

        # 5. Audio Quality / SNR / Clipping
        if audio_qual < 0.40:
            total_points += 10.0
            signals.append("POOR_AUDIO_QUALITY")
            contrib.append(f"Degraded audio quality: {int(round(audio_qual * 100))}%")

        # 6. Contextual Risk Signals (Phase 11 Conversation Intelligence)
        high_risk_credential_or_financial = False
        for ctx in context_signals:
            if ctx in ["FINANCIAL_REQUEST", "MONEY_TRANSFER"]:
                total_points += 15.0
                high_risk_credential_or_financial = True
                if "FINANCIAL_REQUEST" not in signals:
                    signals.append("FINANCIAL_REQUEST")
                    contrib.append("High-risk financial transaction requested")
            elif ctx in ["OTP_REQUEST", "PASSWORD_REQUEST", "BANK_CREDENTIAL_REQUEST"]:
                total_points += 20.0
                high_risk_credential_or_financial = True
                if ctx not in signals:
                    signals.append(ctx)
                    contrib.append(f"High-risk authentication credential request ({ctx})")
            elif ctx in ["EMERGENCY_MONEY_REQUEST", "ACCOUNT_TAKEOVER_ATTEMPT"]:
                total_points += 25.0
                high_risk_credential_or_financial = True
                if ctx not in signals:
                    signals.append(ctx)
                    contrib.append(f"Severe social engineering threat ({ctx})")
            elif ctx == "UPI_REQUEST":
                total_points += 15.0
                high_risk_credential_or_financial = True
                if "UPI_REQUEST" not in signals:
                    signals.append("UPI_REQUEST")
                    contrib.append("Direct UPI / VPA payment solicitation detected")
            elif ctx in ["IDENTITY_VERIFICATION_REQUEST", "CONFIDENTIAL_INFO_REQUEST"]:
                total_points += 15.0
                if ctx not in signals:
                    signals.append(ctx)
                    contrib.append(f"Sensitive information solicitation ({ctx})")
            else:
                total_points += 10.0
                if ctx not in signals:
                    signals.append(ctx)
                    contrib.append(f"Contextual alert: {ctx}")

        # Compounding synergy: Voice clone + Credential/Emergency money solicitation = Escalated Threat
        if high_risk_credential_or_financial and p_df >= 0.70:
            total_points += 25.0
            if "VOICE_CLONE_SOCIAL_ENGINEERING_SYNERGY" not in signals:
                signals.append("VOICE_CLONE_SOCIAL_ENGINEERING_SYNERGY")
                contrib.append("Critical threat: Synthetic voice clone attempting credential/financial social engineering")

        # 7. Model Confidence & Safety Assessment
        is_low_confidence = conf < self.min_confidence_threshold
        if is_low_confidence:
            if "LOW_MODEL_CONFIDENCE" not in signals:
                signals.append("LOW_MODEL_CONFIDENCE")
                contrib.append(f"Low model confidence: {int(round(conf * 100))}%")

        # 8. Bounded Composite Risk Score (0-100)
        risk_score = int(round(max(0.0, min(100.0, total_points))))

        # 9. Risk Level & Default Action Mapping
        if risk_score <= self.allow_max:
            risk_level = "LOW"
            action = "ALLOW"
        elif risk_score <= self.challenge_max:
            risk_level = "MEDIUM"
            action = "CHALLENGE"
        elif risk_score <= self.warn_max:
            risk_level = "HIGH"
            action = "WARN"
        else:
            risk_level = "CRITICAL"
            action = "BLOCK"

        # Biometric mismatch policy override: Never allow unverified identity
        if "SPEAKER_MISMATCH" in signals and action == "ALLOW":
            action = "CHALLENGE"
            risk_level = "MEDIUM"

        # Replay attack policy override: Never blindly allow severe replay attacks
        if "LOW_LIVENESS" in signals and liveness < 0.30 and action == "ALLOW":
            action = "CHALLENGE"
            risk_level = "MEDIUM"

        # 10. Low-Confidence Safety Safeguard:
        # If model confidence is low, the system MUST prefer CHALLENGE / VERIFY
        # rather than pretending the call is definitely fake or blindly blocking.
        if is_low_confidence:
            if action in ["BLOCK", "WARN"]:
                action = "CHALLENGE"
            elif risk_score > self.allow_max and action == "ALLOW":
                action = "CHALLENGE"

        individual_scores = {
            "deepfake_score": round(p_df, 3),
            "speaker_similarity": round(sim, 3) if sim is not None else None,
            "liveness_score": round(liveness, 3),
            "replay_probability": round(risk_input.replay_probability if risk_input.replay_probability is not None else (1.0 - liveness), 3),
            "caller_verification_status": caller_verified,
            "conversation_risk": round(risk_input.conversation_risk, 3),
            "model_confidence": round(conf, 3),
            "audio_quality": round(audio_qual, 3),
        }
        requires_human = is_low_confidence or (liveness >= 0.90 and 0.50 <= p_df < 0.85)

        result = RiskEvaluationResult(
            risk_score=risk_score,
            risk_level=risk_level,
            recommended_action=action,
            signals=signals,
            confidence=conf,
            contributing_signals=contrib,
            individual_scores=individual_scores,
            policy_version="2026.09.1-production",
            requires_human_verification=requires_human,
        )
        result.explanation = result.format_explanation()
        return result

    def evaluate(
        self,
        vad_res: VADResult,
        antispoof_res: AntiSpoofResult,
        liveness_res: LivenessResult,
        speaker_res: Optional[SpeakerVerificationResult] = None,
        context_telephony_risk: float = 0.0,
        preprocessing_latency_ms: float = 0.0,
    ) -> RiskVerdict:
        """
        Legacy adapter maintaining full backward compatibility with existing orchestrator
        and unit tests, while delegating core reasoning to evaluate_risk.
        """
        start_time = time.perf_counter()

        # Uncertainty calculation
        total_uncertainty = 0.5 * antispoof_res.aleatoric_uncertainty + 0.5 * antispoof_res.epistemic_uncertainty
        total_uncertainty = round(float(total_uncertainty), 3)
        confidence = round(float(max(0.0, min(1.0, 1.0 - total_uncertainty))), 3)

        # Map to RiskEngineInput
        liveness_score = getattr(
            liveness_res,
            "liveness_score",
            round(float(max(0.0, min(1.0, 1.0 - liveness_res.replay_probability))), 3),
        )
        speaker_sim = speaker_res.cosine_similarity if (speaker_res and speaker_res.claimed_speaker_id) else None
        caller_verified = (context_telephony_risk < 0.50)
        audio_qual = round(float(max(0.0, min(1.0, 1.0 - antispoof_res.aleatoric_uncertainty))), 3)

        ctx_signals = []
        if context_telephony_risk >= 0.70:
            ctx_signals.append("HIGH_TELEPHONY_RISK")

        risk_input = RiskEngineInput(
            deepfake_probability=antispoof_res.synthetic_probability,
            speaker_similarity=speaker_sim,
            liveness_score=liveness_score,
            caller_verified=caller_verified,
            audio_quality=audio_qual,
            model_confidence=confidence,
            contextual_signals=ctx_signals,
        )

        phase6_eval = self.evaluate_risk(risk_input)

        # Map phase 6 action to legacy DecisionState
        if not vad_res.is_speech:
            decision = DecisionState.ALLOW
        elif total_uncertainty >= self.high_uncertainty_threshold:
            decision = DecisionState.UNCERTAIN
        elif phase6_eval.recommended_action == "BLOCK":
            decision = DecisionState.BLOCK
        elif phase6_eval.recommended_action == "WARN":
            decision = DecisionState.WARN
        elif phase6_eval.recommended_action == "CHALLENGE":
            decision = DecisionState.CHALLENGE
        else:
            decision = DecisionState.ALLOW

        composite_risk_score = round(phase6_eval.risk_score / 100.0, 3)

        # Build explainability list
        reasons: List[str] = [f"✓ {c}" for c in phase6_eval.contributing_signals]
        if not vad_res.is_speech:
            reasons.append("No active speech detected in audio frame")
        if total_uncertainty >= self.high_uncertainty_threshold:
            reasons.append(f"High environmental noise or poor SNR resulted in high decision uncertainty ({total_uncertainty:.2f})")

        decision_engine_ms = (time.perf_counter() - start_time) * 1000.0

        speaker_metrics = None
        if speaker_res:
            speaker_metrics = SpeakerVerificationMetrics(
                enrolled_match=speaker_res.is_match,
                cosine_similarity=speaker_res.cosine_similarity,
                threshold=speaker_res.threshold,
                claimed_speaker_id=speaker_res.claimed_speaker_id,
            )

        total_pipeline_ms = (
            preprocessing_latency_ms
            + vad_res.latency_ms
            + antispoof_res.latency_ms
            + (speaker_res.latency_ms if speaker_res else 0.0)
            + liveness_res.latency_ms
            + decision_engine_ms
        )

        return RiskVerdict(
            decision=decision,
            composite_risk_score=composite_risk_score,
            confidence=confidence,
            uncertainty=UncertaintyMetrics(
                aleatoric_score=antispoof_res.aleatoric_uncertainty,
                epistemic_score=antispoof_res.epistemic_uncertainty,
                total_uncertainty=total_uncertainty,
            ),
            voice_activity=VoiceActivityMetrics(
                is_speech=vad_res.is_speech,
                speech_probability=vad_res.speech_probability,
            ),
            deepfake_analysis=DeepfakeMetrics(
                is_synthetic=antispoof_res.is_synthetic,
                synthetic_probability=antispoof_res.synthetic_probability,
                architecture_detected="AASIST_WAVLM_FUSION",
                anomaly_breakdown=antispoof_res.feature_anomalies,
            ),
            speaker_verification=speaker_metrics,
            liveness_analysis=LivenessMetrics(
                is_live_acoustic=liveness_res.is_live_acoustic,
                replay_probability=liveness_res.replay_probability,
                channel_dispersion_detected=liveness_res.replay_probability > 0.65,
                liveness_score=getattr(liveness_res, "liveness_score", round(1.0 - liveness_res.replay_probability, 3)),
                confidence=getattr(liveness_res, "confidence", 1.0),
            ),
            explainability_reasons=reasons,
            latency_metrics=LatencyBreakdown(
                preprocessing_ms=round(preprocessing_latency_ms, 2),
                vad_ms=round(vad_res.latency_ms, 2),
                antispoof_ms=round(antispoof_res.latency_ms, 2),
                speaker_verify_ms=round(speaker_res.latency_ms, 2) if speaker_res else 0.0,
                liveness_ms=round(liveness_res.latency_ms, 2),
                decision_engine_ms=round(decision_engine_ms, 2),
                total_pipeline_latency_ms=round(total_pipeline_ms, 2),
            ),
        )
