import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from app.core.logging import logger
from app.core.security import anonymize_caller_id


# Dedicated Structured Audit Logger
audit_logger = logging.getLogger("vigil.audit")


@dataclass
class PolicyConfig:
    """
    Configurable Decision Policy for VIGIL-AI Final Risk Engine (Phase 12).
    Supports runtime threshold tuning, weighting, and strict policy versioning.
    """
    policy_version: str = "2026.09.1-production"

    # Risk Score Range Cutoffs (0 - 100)
    threshold_allow_max: int = 34
    threshold_monitor_max: int = 49
    threshold_challenge_max: int = 69
    threshold_warn_max: int = 84
    threshold_critical_min: int = 85

    # Safety Thresholds
    min_confidence_for_blocking: float = 0.60
    high_uncertainty_threshold: float = 0.60
    low_audio_quality_cutoff: float = 0.40

    # Configurable Component Weights
    weight_deepfake: float = 55.0
    weight_liveness: float = 35.0
    weight_speaker_mismatch: float = 30.0
    weight_unverified_caller: float = 15.0
    weight_conversation_risk: float = 30.0
    weight_poor_audio: float = 10.0

    # Synergies and Penalties
    targeted_clone_synergy_penalty: float = 35.0
    credential_social_engineering_penalty: float = 25.0
    historical_incident_penalty: float = 20.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "threshold_allow_max": self.threshold_allow_max,
            "threshold_monitor_max": self.threshold_monitor_max,
            "threshold_challenge_max": self.threshold_challenge_max,
            "threshold_warn_max": self.threshold_warn_max,
            "threshold_critical_min": self.threshold_critical_min,
            "min_confidence_for_blocking": self.min_confidence_for_blocking,
        }


@dataclass
class FinalRiskEngineInput:
    """
    Comprehensive Input Payload for Phase 12 Final Risk Engine.
    Combines all constituent model indicators, telephony metadata, and conversation context.
    """
    deepfake_score: float  # 0.0 to 1.0 (spoof probability)
    speaker_similarity: Optional[float] = None  # 0.0 to 1.0 or None if unenrolled
    liveness_score: float = 1.0  # 0.0 (replay/dead) to 1.0 (live vocal tract)
    replay_probability: Optional[float] = None  # 0.0 to 1.0
    caller_verification_status: bool = True  # STIR/SHAKEN or carrier verified
    conversation_risk: float = 0.0  # 0.0 to 1.0 from Phase 11 Conversation Intelligence
    model_confidence: float = 1.0  # 0.0 to 1.0
    audio_quality: float = 1.0  # 0.0 (low SNR/clipping) to 1.0 (clean)
    historical_signals: List[str] = field(default_factory=list)  # past incidents in session
    caller_id: Optional[str] = None
    session_id: Optional[str] = None


@dataclass
class FinalRiskDecisionResult:
    """
    Standardized Phase 12 Return Contract:
    {
      "risk_score": 0-100,
      "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
      "action": "ALLOW | MONITOR | CHALLENGE | WARN | BLOCK",
      "confidence": 0-1,
      "signals": [],
      "explanation": ""
    }
    """
    risk_score: int
    risk_level: str
    action: str
    confidence: float
    signals: List[str]
    explanation: str

    # Extended audit metadata (preserved for full explainability)
    individual_scores: Dict[str, Any] = field(default_factory=dict)
    contributing_signals: List[str] = field(default_factory=list)
    policy_version: str = "2026.09.1-production"
    requires_human_verification: bool = False
    timestamp: float = field(default_factory=time.time)

    @property
    def recommended_action(self) -> str:
        """Backward compatibility alias for Phase 6-11 consumers."""
        return self.action

    def to_dict(self) -> Dict[str, Any]:
        """Conforms strictly to Phase 12 JSON contract."""
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "action": self.action,
            "confidence": round(self.confidence, 3),
            "signals": self.signals,
            "explanation": self.explanation,
        }

    def to_extended_dict(self) -> Dict[str, Any]:
        """Provides full audit breakdown including raw constituent scores."""
        d = self.to_dict()
        d["recommended_action"] = self.action
        d["individual_scores"] = self.individual_scores
        d["contributing_signals"] = self.contributing_signals
        d["policy_version"] = self.policy_version
        d["requires_human_verification"] = self.requires_human_verification
        d["timestamp"] = self.timestamp
        return d


class FinalRiskDecisionEngine:
    """
    Unified Phase 12 Risk Decision Engine for VIGIL-AI.

    Features:
    1. Multi-signal synthesis: Deepfake + Speaker + Liveness + Caller ID + Conversation + History.
    2. Configurable policy engine with versioning (`PolicyConfig`).
    3. Low-confidence safety override: Never issues irreversible BLOCK solely on low-confidence ML.
    4. Conflicting signal mediation: Recommends CHALLENGE or human verification when signals conflict.
    5. Preserves all raw constituent scores in `individual_scores`.
    6. Never claims 100% certainty; expresses probabilistic confidence bounds.
    7. Secure structured audit logging with masked caller PII.
    """

    def __init__(self, policy_config: Optional[PolicyConfig] = None):
        self.policy = policy_config or PolicyConfig()

    def update_policy(self, new_policy: PolicyConfig) -> None:
        """Updates the active policy at runtime."""
        self.policy = new_policy
        logger.info(f"Updated VIGIL-AI Decision Policy to version: {self.policy.policy_version}")

    def evaluate(self, inp: FinalRiskEngineInput) -> FinalRiskDecisionResult:
        """
        Executes policy rules and non-linear risk synthesis.
        """
        signals: List[str] = []
        contrib: List[str] = []
        total_points = 0.0

        # Extract and clamp input values
        p_df = max(0.0, min(1.0, float(inp.deepfake_score)))
        sim = float(inp.speaker_similarity) if inp.speaker_similarity is not None else None
        liveness = max(0.0, min(1.0, float(inp.liveness_score)))
        replay_prob = max(0.0, min(1.0, float(inp.replay_probability))) if inp.replay_probability is not None else (1.0 - liveness)
        caller_verified = bool(inp.caller_verification_status)
        conv_risk = max(0.0, min(1.0, float(inp.conversation_risk)))
        conf = max(0.0, min(1.0, float(inp.model_confidence)))
        qual = max(0.0, min(1.0, float(inp.audio_quality)))
        history = list(inp.historical_signals or [])

        # Preserve constituent model scores
        individual_scores: Dict[str, Any] = {
            "deepfake_score": round(p_df, 3),
            "speaker_similarity": round(sim, 3) if sim is not None else None,
            "liveness_score": round(liveness, 3),
            "replay_probability": round(replay_prob, 3),
            "caller_verification_status": caller_verified,
            "conversation_risk": round(conv_risk, 3),
            "model_confidence": round(conf, 3),
            "audio_quality": round(qual, 3),
            "historical_signals_count": len(history),
        }

        # -------------------------------------------------------------
        # 1. Deepfake Acoustic Spoof Evaluation
        # -------------------------------------------------------------
        if p_df >= 0.85:
            df_pts = self.policy.weight_deepfake * (0.80 + 0.20 * ((p_df - 0.85) / 0.15))
            total_points += df_pts
            signals.append("HIGH_SYNTHETIC_PROBABILITY")
            contrib.append(f"High synthetic speech probability ({int(p_df * 100)}% spoof)")
        elif p_df >= 0.50:
            df_pts = self.policy.weight_deepfake * (0.35 + 0.45 * ((p_df - 0.50) / 0.35))
            total_points += df_pts
            signals.append("MODERATE_SYNTHETIC_PROBABILITY")
            contrib.append(f"Moderate synthetic speech probability ({int(p_df * 100)}% spoof)")
        else:
            df_pts = self.policy.weight_deepfake * 0.25 * (p_df / 0.50)
            total_points += df_pts

        # -------------------------------------------------------------
        # 2. Acoustic Liveness & Loudspeaker Replay Evaluation
        # -------------------------------------------------------------
        if liveness < 0.50 or replay_prob >= 0.60:
            replay_factor = max(1.0 - liveness, replay_prob)
            live_pts = self.policy.weight_liveness * replay_factor
            if replay_prob >= 0.65:
                live_pts += 15.0  # Definite replay attack penalty
                signals.append("REPLAY_ATTACK_DETECTED")
                contrib.append(f"Acoustic replay attack detected ({int(replay_prob * 100)}% replay prob)")
            else:
                signals.append("LOW_LIVENESS")
                contrib.append(f"Low acoustic liveness ({int(liveness * 100)}% liveness)")
            total_points += live_pts

        # -------------------------------------------------------------
        # 3. Speaker Verification & Targeted Clone Attack Synergy
        # -------------------------------------------------------------
        if sim is not None:
            if sim < 0.75:
                # Definite biometric mismatch
                mismatch_ratio = max(0.0, 1.0 - sim)
                spk_pts = self.policy.weight_speaker_mismatch * min(1.0, mismatch_ratio / 0.60)
                total_points += spk_pts
                signals.append("SPEAKER_MISMATCH")
                contrib.append(f"Biometric voice mismatch with claimed speaker ({int(sim * 100)}% match)")
            elif sim >= 0.85 and p_df >= 0.75:
                # TARGETED CLONE ATTACK SYNERGY:
                # High speaker resemblance to enrolled victim + synthetic vocoder artifacts
                total_points += self.policy.targeted_clone_synergy_penalty
                signals.append("TARGETED_CLONE_DETECTED")
                contrib.append(f"Targeted voice clone detected (matches enrolled voiceprint {int(sim * 100)}% with synthetic speech)")
        else:
            # Unenrolled / Unknown speaker
            signals.append("UNKNOWN_SPEAKER")
            contrib.append("Speaker is un-enrolled / anonymous")
            total_points += 5.0

        # -------------------------------------------------------------
        # 4. Caller ID & Carrier Attestation Status
        # -------------------------------------------------------------
        if not caller_verified:
            total_points += self.policy.weight_unverified_caller
            signals.append("CALLER_ID_UNVERIFIED")
            contrib.append("Caller ID unverified / STIR-SHAKEN carrier attestation missing")

        # -------------------------------------------------------------
        # 5. Conversation Risk & Social Engineering Context
        # -------------------------------------------------------------
        if conv_risk >= 0.80:
            total_points += self.policy.weight_conversation_risk
            signals.append("HIGH_CONVERSATION_RISK")
            contrib.append(f"High-risk conversational intent ({int(conv_risk * 100)}% intent risk)")
            # Synergy: Voice clone + Credential theft intent
            if p_df >= 0.70:
                total_points += self.policy.credential_social_engineering_penalty
                signals.append("VOICE_CLONE_SOCIAL_ENGINEERING_SYNERGY")
                contrib.append("Critical threat: Voice clone actively attempting credential/money solicitation")
        elif conv_risk >= 0.50:
            total_points += self.policy.weight_conversation_risk * 0.50
            signals.append("MODERATE_CONVERSATION_RISK")
            contrib.append(f"Moderate conversational risk ({int(conv_risk * 100)}% intent risk)")

        # -------------------------------------------------------------
        # 6. Audio Quality / SNR / Clipping
        # -------------------------------------------------------------
        if qual < self.policy.low_audio_quality_cutoff:
            total_points += self.policy.weight_poor_audio
            signals.append("POOR_AUDIO_QUALITY")
            contrib.append(f"Degraded audio quality or low SNR ({int(qual * 100)}% quality)")

        # -------------------------------------------------------------
        # 7. Historical Signals
        # -------------------------------------------------------------
        for h in history:
            h_upper = str(h).upper()
            total_points += self.policy.historical_incident_penalty
            if h_upper not in signals:
                signals.append(h_upper)
                contrib.append(f"Historical incident flag: {h_upper}")

        # -------------------------------------------------------------
        # 8. Composite Risk Score (Clamped 0 - 100)
        # -------------------------------------------------------------
        raw_risk_score = int(round(max(0.0, min(100.0, total_points))))

        # -------------------------------------------------------------
        # 9. Initial Risk Level & Action Mapping
        # -------------------------------------------------------------
        if raw_risk_score <= self.policy.threshold_allow_max:
            risk_level = "LOW"
            action = "ALLOW"
        elif raw_risk_score <= self.policy.threshold_monitor_max:
            risk_level = "LOW"
            action = "MONITOR"
        elif raw_risk_score <= self.policy.threshold_challenge_max:
            risk_level = "MEDIUM"
            action = "CHALLENGE"
        elif raw_risk_score <= self.policy.threshold_warn_max:
            risk_level = "HIGH"
            action = "WARN"
        else:
            risk_level = "CRITICAL"
            action = "BLOCK"

        # Refinement: Unknown speaker with clean audio should be monitored/allowed rather than blocked
        if "UNKNOWN_SPEAKER" in signals and p_df < 0.35 and liveness >= 0.70 and caller_verified and conv_risk < 0.30:
            if action in ["CHALLENGE", "WARN"]:
                action = "MONITOR"
                risk_level = "LOW"

        # Severe replay attack policy override
        if "REPLAY_ATTACK_DETECTED" in signals and action in ["ALLOW", "MONITOR"]:
            action = "WARN"
            risk_level = "HIGH"

        # -------------------------------------------------------------
        # 10. Ambiguous / Conflicting Signal Detection
        # -------------------------------------------------------------
        requires_human_verification = False
        # Case A: Pristine live acoustic emission (liveness >= 0.90) but deepfake model flags moderate spoof
        if liveness >= 0.90 and 0.50 <= p_df < 0.85:
            signals.append("CONFLICTING_MODEL_SIGNALS")
            contrib.append("Conflicting outputs: High acoustic liveness contrasts with deepfake score")
            requires_human_verification = True
            action = "CHALLENGE"
            risk_level = "MEDIUM" if raw_risk_score <= 60 else "HIGH"

        # Case B: Verified caller ID but high deepfake score -> Potential caller ID spoofing
        if caller_verified and p_df >= 0.80:
            signals.append("POTENTIAL_CALLER_ID_SPOOFING")
            contrib.append("Carrier-verified caller ID with synthetic speech indicates potential caller-ID spoofing")

        # -------------------------------------------------------------
        # 11. Safety Override: Avoid Irreversible Action on Low Confidence
        # -------------------------------------------------------------
        is_low_confidence = conf < self.policy.min_confidence_for_blocking
        if is_low_confidence:
            signals.append("LOW_MODEL_CONFIDENCE")
            contrib.append(f"Model confidence is insufficient ({int(conf * 100)}% confidence)")
            requires_human_verification = True

            # Downgrade irreversible BLOCK
            if action == "BLOCK":
                action = "CHALLENGE"
                risk_level = "HIGH"
                contrib.append("Safety safeguard: BLOCK downgraded to CHALLENGE due to low model confidence")
            elif action == "WARN":
                action = "CHALLENGE"
            elif action == "ALLOW" and "POOR_AUDIO_QUALITY" in signals:
                action = "MONITOR"

        # -------------------------------------------------------------
        # 12. Explanation Formatting (Never Claim Certainty)
        # -------------------------------------------------------------
        explanation = self._build_explanation(
            risk_score=raw_risk_score,
            risk_level=risk_level,
            action=action,
            confidence=conf,
            contributing=contrib,
            requires_human_verification=requires_human_verification,
        )

        result = FinalRiskDecisionResult(
            risk_score=raw_risk_score,
            risk_level=risk_level,
            action=action,
            confidence=round(conf, 3),
            signals=signals,
            explanation=explanation,
            individual_scores=individual_scores,
            contributing_signals=contrib,
            policy_version=self.policy.policy_version,
            requires_human_verification=requires_human_verification,
        )

        # -------------------------------------------------------------
        # 13. Secure Audit Logging (PII Masked)
        # -------------------------------------------------------------
        self._log_decision_audit(inp, result)

        return result

    def _build_explanation(
        self,
        risk_score: int,
        risk_level: str,
        action: str,
        confidence: float,
        contributing: List[str],
        requires_human_verification: bool,
    ) -> str:
        """
        Constructs an explainable rationale that explicitly preserves probabilistic uncertainty
        and avoids claims of absolute certainty.
        """
        lines = [
            f"VIGIL-AI Policy Evaluation ({self.policy.policy_version}):",
            f"Estimated Risk Score: {risk_score}/100 [{risk_level} RISK] (Confidence: {int(confidence * 100)}%)",
            f"Recommended Action: {action}",
            "",
            "Key Contributing Factors:",
        ]

        if contributing:
            for c in contributing:
                lines.append(f"  • {c}")
        else:
            lines.append("  • All acoustic, biometric, telephony, and conversational signals nominal.")

        if requires_human_verification:
            lines.append("")
            lines.append("⚠️ Ambiguity Warning: Independent human/out-of-band verification recommended.")

        lines.append("")
        lines.append("Note: Probabilistic ML assessment. VIGIL-AI does not assert absolute certainty; policy avoids unilateral irreversible action on uncertain data.")
        return "\n".join(lines)

    def _log_decision_audit(self, inp: FinalRiskEngineInput, res: FinalRiskDecisionResult) -> None:
        """Logs structured JSON audit trail with PII pseudonymization."""
        masked_caller = anonymize_caller_id(inp.caller_id or "UNKNOWN")
        audit_entry = {
            "timestamp": res.timestamp,
            "policy_version": res.policy_version,
            "session_id": inp.session_id or "anonymous",
            "caller": masked_caller,
            "risk_score": res.risk_score,
            "risk_level": res.risk_level,
            "action": res.action,
            "confidence": res.confidence,
            "signals": res.signals,
            "requires_human_verification": res.requires_human_verification,
        }
        audit_logger.info(json.dumps(audit_entry))


# Global singleton
_final_risk_engine_instance: Optional[FinalRiskDecisionEngine] = None


def get_final_risk_engine(policy: Optional[PolicyConfig] = None) -> FinalRiskDecisionEngine:
    global _final_risk_engine_instance
    if _final_risk_engine_instance is None or policy is not None:
        _final_risk_engine_instance = FinalRiskDecisionEngine(policy_config=policy)
    return _final_risk_engine_instance
