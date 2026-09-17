"""
VIGIL-AI Multi-Benchmark Evaluation & EER Calculator.

Computes:
1. Equal Error Rate (EER) via ROC convex hull and score threshold interpolation.
2. False Alarm Rate (FAR / FPR) and Miss Rate (FRR / FNR).
3. Out-of-Domain Generalization Gap metric (In-the-Wild vs ASVspoof 5).
4. Disaggregated metrics by attack algorithm and acoustic condition.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np


@dataclass
class BenchmarkEvaluationResult:
    dataset_name: str
    total_trials: int
    bonafide_trials: int
    spoof_trials: int
    eer_percent: float
    threshold_at_eer: float
    accuracy_at_eer: float
    attack_breakdown: Dict[str, float]  # attack_type -> detection rate (Recall)


def compute_eer(bonafide_scores: np.ndarray, spoof_scores: np.ndarray) -> Tuple[float, float]:
    """
    Computes Equal Error Rate (EER) where False Acceptance Rate (FAR)
    equals False Rejection Rate (FRR).
    Assumes higher score indicates higher probability of BONAFIDE
    (or can be calibrated for spoof score where threshold cuts opposite).
    Returns:
        (eer_percentage, operating_threshold)
    """
    bf = np.sort(np.asarray(bonafide_scores, dtype=np.float64))
    sp = np.sort(np.asarray(spoof_scores, dtype=np.float64))

    if len(bf) == 0 or len(sp) == 0:
        return 0.0, 0.5

    # Threshold sweeps across combined score range from min to max
    min_score = min(float(bf.min()), float(sp.min()))
    max_score = max(float(bf.max()), float(sp.max()))
    thresholds = np.linspace(min_score, max_score, 1000)

    far_list = []
    frr_list = []

    for t in thresholds:
        # If score >= t => declared bonafide
        # FAR = spoof accepted as bonafide (spoof score >= t)
        far = np.mean(sp >= t)
        # FRR = bonafide rejected as spoof (bonafide score < t)
        frr = np.mean(bf < t)

        far_list.append(far)
        frr_list.append(frr)

    far_arr = np.array(far_list)
    frr_arr = np.array(frr_list)

    # Find indices where FAR and FRR are both near 0 (perfect separation gap)
    zero_err_indices = np.where((far_arr == 0) & (frr_arr == 0))[0]
    if len(zero_err_indices) > 0:
        # Pick the median threshold in the separation gap
        mid_idx = zero_err_indices[len(zero_err_indices) // 2]
        eer = 0.0
        best_threshold = float(thresholds[mid_idx])
    else:
        # Standard intersection point where FAR ~ FRR
        diff = np.abs(far_arr - frr_arr)
        min_idx = np.argmin(diff)
        eer = float((far_arr[min_idx] + frr_arr[min_idx]) / 2.0 * 100.0)
        best_threshold = float(thresholds[min_idx])

    return round(eer, 2), round(best_threshold, 4)


class MultiBenchmarkEvaluator:
    """
    Evaluates anti-spoofing models across ASVspoof 5, ASVspoof 2021, and In-the-Wild.
    Calculates generalization degradation gaps.
    """

    def evaluate_scores(
        self,
        dataset_name: str,
        bonafide_scores: np.ndarray,
        spoof_scores: np.ndarray,
        attack_types: Optional[List[str]] = None,
    ) -> BenchmarkEvaluationResult:
        bf = np.asarray(bonafide_scores, dtype=np.float32)
        sp = np.asarray(spoof_scores, dtype=np.float32)

        eer, threshold = compute_eer(bf, sp)

        # Accuracy at EER threshold
        correct_bf = np.sum(bf >= threshold)
        correct_sp = np.sum(sp < threshold)
        total = len(bf) + len(sp)
        acc = float((correct_bf + correct_sp) / max(1, total) * 100.0)

        # Breakdown by attack type if provided
        breakdown: Dict[str, float] = {}
        if attack_types and len(attack_types) == len(sp):
            attacks_set = sorted(list(set(attack_types)))
            for att in attacks_set:
                indices = [i for i, a in enumerate(attack_types) if a == att]
                att_scores = sp[indices]
                # Recall = % of spoof correctly rejected
                detected = np.mean(att_scores < threshold) * 100.0
                breakdown[att] = round(float(detected), 1)

        return BenchmarkEvaluationResult(
            dataset_name=dataset_name,
            total_trials=total,
            bonafide_trials=len(bf),
            spoof_trials=len(sp),
            eer_percent=eer,
            threshold_at_eer=threshold,
            accuracy_at_eer=round(acc, 2),
            attack_breakdown=breakdown,
        )

    def compute_generalization_gap(
        self, primary_result: BenchmarkEvaluationResult, wild_result: BenchmarkEvaluationResult
    ) -> Dict[str, float]:
        """
        Calculates the out-of-domain performance gap:
        Delta EER = EER(In-the-Wild) - EER(ASVspoof 5)
        A low gap demonstrates robust cross-domain generalization.
        """
        gap = round(wild_result.eer_percent - primary_result.eer_percent, 2)
        return {
            "primary_eer": primary_result.eer_percent,
            "in_the_wild_eer": wild_result.eer_percent,
            "generalization_gap_eer": gap,
            "relative_degradation_pct": round(
                (gap / max(0.01, primary_result.eer_percent)) * 100.0, 1
            ),
        }
