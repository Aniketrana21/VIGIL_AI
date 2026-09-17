"""
VIGIL-AI Defensive Adversarial Robustness Evaluator.

Executes:
1. Clean Audio Baseline Profiling
2. Parameterized Transformation Sweeps:
   - Additive Noise (30 to -5 dB SNR)
   - Codec Compression (8 to 2 bits)
   - Resampling (16kHz down to 6kHz)
   - Volume Changes (-18 dB to +12 dB)
   - Reverberation (RT60 50ms to 600ms)
   - Clipping (1.0 down to 0.15 threshold)
   - Spectral Perturbation (1000Hz to 6000Hz notch filters)
   - Time-Domain Perturbation (0% to 25% dropout rate)
3. Computes Robustness Score, Score Drift, EER Degradation, Label Flip Rate, and Breakdown Points.
4. Generates structured JSON and CSV robustness reports.
"""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import numpy as np
from app.core.logging import logger
from app.evaluation.adversarial_transforms import AdversarialTransforms
from app.pipeline.deepfake_detector import DeepfakeDetector, WavLMAASISTDetector
from app.training.augmentations import AudioAugmenter, AugmentationConfig
from app.training.dataset_loaders import Label, TrialMetadata
from app.training.evaluator import compute_eer


@dataclass
class RobustnessPoint:
    transformation: str
    parameter_value: Union[float, int, str]
    eer_percent: float
    accuracy_percent: float
    robustness_score: float  # [0, 1] relative to clean baseline
    mean_score_drift: float  # Mean absolute delta in spoof probability
    label_flip_rate_pct: float


@dataclass
class TransformationSummary:
    transformation: str
    baseline_eer: float
    worst_eer: float
    average_robustness_score: float
    breakdown_point: Optional[Union[float, int, str]]
    points: List[RobustnessPoint]

    @property
    def transformation_name(self) -> str:
        return self.transformation



class AdversarialRobustnessEvaluator:
    """
    Defensive evaluator measuring detector resilience under controlled acoustic stress.
    """

    def __init__(self, detector: Optional[DeepfakeDetector] = None):
        self.detector = detector or WavLMAASISTDetector(device="cpu")
        self.augmenter = AudioAugmenter(AugmentationConfig(sample_rate=16000))
        self.transforms = AdversarialTransforms()

    def generate_eval_batch(self, count: int = 100) -> Tuple[List[np.ndarray], List[int]]:
        """
        Generates paired clean bonafide and spoof audio signals.
        0 = Bonafide, 1 = Spoof
        """
        t = np.linspace(0, 2.0, 32000, endpoint=False)
        audios = []
        labels = []

        half = count // 2
        for i in range(half):
            # Clean bonafide voice harmonic
            f0 = 130.0 + (i * 3.0)
            voice = (0.5 * np.sin(2 * np.pi * f0 * t)).astype(np.float32)
            audios.append(voice)
            labels.append(0)

        for i in range(half):
            # Clean synthetic/spoof voice
            f0 = 150.0 + (i * 4.0)
            base = (0.5 * np.sin(2 * np.pi * f0 * t)).astype(np.float32)
            spoofed = self.augmenter.apply_tts_artifacts(base)
            audios.append(spoofed)
            labels.append(1)

        return audios, labels

    def profile_clean_baseline(
        self, sample_count: int = 100
    ) -> Tuple[List[np.ndarray], List[int], List[float], float, float]:
        """
        Convenience helper: generates clean batch and evaluates baseline in one call.
        Returns:
            (audios, labels, clean_scores, baseline_eer, baseline_acc)
        """
        audios, labels = self.generate_eval_batch(sample_count)
        eer, acc, scores = self.evaluate_clean_baseline(audios, labels)
        return audios, labels, scores, eer, acc

    @staticmethod
    def _find_breakdown_point(
        points: List[RobustnessPoint], failure_threshold: float = 0.6
    ) -> Optional[Union[float, int, str]]:
        """Finds the first parameter value where robustness drops below failure_threshold or EER exceeds 20%."""
        for p in points:
            if p.robustness_score < failure_threshold or p.eer_percent >= 20.0:
                return p.parameter_value
        return None

    def evaluate_clean_baseline(
        self, audios: List[np.ndarray], labels: List[int]
    ) -> Tuple[float, float, List[float]]:
        """
        Computes baseline metrics on unperturbed clean audio.
        Returns:
            (baseline_eer, baseline_accuracy, clean_scores)
        """
        scores = []
        for a in audios:
            res = self.detector.predict(a)
            scores.append(res.spoof_probability)

        scores_arr = np.array(scores)
        labels_arr = np.array(labels)

        bf_scores = 1.0 - scores_arr[labels_arr == 0]
        sp_scores = 1.0 - scores_arr[labels_arr == 1]
        eer, th_bf = compute_eer(bf_scores, sp_scores)

        th_spoof = 1.0 - th_bf
        preds = (scores_arr >= th_spoof).astype(int)
        acc = float(np.mean(preds == labels_arr) * 100.0)

        return eer, acc, scores

    def evaluate_sweep(
        self,
        transformation_name: str,
        param_values: List[Union[float, int, str]],
        transform_fn: Callable[[np.ndarray, Any], np.ndarray],
        audios: List[np.ndarray],
        labels: List[int],
        clean_scores: List[float],
        baseline_eer: float,
        baseline_acc: float,
    ) -> TransformationSummary:
        """
        Applies parameterized sweep of a single transformation and records degradation.
        """
        points: List[RobustnessPoint] = []
        labels_arr = np.array(labels)
        clean_scores_arr = np.array(clean_scores)
        clean_preds = (clean_scores_arr >= 0.5).astype(int)

        breakdown_point = None

        for val in param_values:
            perturbed_scores = []
            for a in audios:
                a_pert = transform_fn(a, val)
                res = self.detector.predict(a_pert)
                perturbed_scores.append(res.spoof_probability)

            p_scores_arr = np.array(perturbed_scores)

            # EER under perturbation
            bf_scores = 1.0 - p_scores_arr[labels_arr == 0]
            sp_scores = 1.0 - p_scores_arr[labels_arr == 1]
            eer, th_bf = compute_eer(bf_scores, sp_scores)

            th_spoof = 1.0 - th_bf
            p_preds = (p_scores_arr >= th_spoof).astype(int)
            acc = float(np.mean(p_preds == labels_arr) * 100.0)

            # Metrics
            score_drift = float(np.mean(np.abs(p_scores_arr - clean_scores_arr)))
            flip_rate = float(np.mean(p_preds != clean_preds) * 100.0)
            robustness_score = round(max(0.0, min(1.0, (acc / max(1e-3, baseline_acc)))), 3)

            # Check breakdown threshold (EER > 20% or robustness < 0.6)
            if breakdown_point is None and (eer >= 20.0 or robustness_score < 0.6):
                breakdown_point = val

            points.append(RobustnessPoint(
                transformation=transformation_name,
                parameter_value=val,
                eer_percent=eer,
                accuracy_percent=round(acc, 2),
                robustness_score=robustness_score,
                mean_score_drift=round(score_drift, 3),
                label_flip_rate_pct=round(flip_rate, 2),
            ))

        worst_eer = max([p.eer_percent for p in points]) if points else baseline_eer
        avg_rob = round(float(np.mean([p.robustness_score for p in points])), 3) if points else 1.0

        return TransformationSummary(
            transformation=transformation_name,
            baseline_eer=baseline_eer,
            worst_eer=worst_eer,
            average_robustness_score=avg_rob,
            breakdown_point=breakdown_point,
            points=points,
        )

    def run_all_sweeps(self, sample_count: int = 80) -> Dict[str, TransformationSummary]:
        """Alias for run_complete_adversarial_suite."""
        return self.run_complete_adversarial_suite(samples_count=sample_count)

    def run_complete_adversarial_suite(
        self, samples_count: int = 80
    ) -> Dict[str, TransformationSummary]:
        """
        Executes defensive robustness testing across all 8 controlled transformation axes.
        """
        logger.info("Generating paired clean audio batch for adversarial robustness testing...")
        audios, labels = self.generate_eval_batch(samples_count)

        logger.info("Measuring clean audio baseline performance...")
        baseline_eer, baseline_acc, clean_scores = self.evaluate_clean_baseline(audios, labels)
        logger.info(f"Clean Baseline: EER = {baseline_eer}% | Accuracy = {baseline_acc}%")

        summaries: Dict[str, TransformationSummary] = {}

        # 1. Additive Noise Sweep (SNR dB)
        logger.info("Evaluating Robustness: Additive Noise (SNR 25 to -5 dB)...")
        summaries["additive_noise"] = self.evaluate_sweep(
            "Additive Noise",
            [25.0, 15.0, 10.0, 5.0, 0.0, -5.0],
            lambda a, v: self.transforms.apply_additive_noise(a, snr_db=v),
            audios, labels, clean_scores, baseline_eer, baseline_acc,
        )

        # 2. Codec Compression Sweep (Bit depth)
        logger.info("Evaluating Robustness: Codec Compression (8 to 2 bits)...")
        summaries["codec_compression"] = self.evaluate_sweep(
            "Codec Compression",
            [8, 6, 4, 3, 2],
            lambda a, v: self.transforms.apply_codec_compression(a, bit_depth=v),
            audios, labels, clean_scores, baseline_eer, baseline_acc,
        )

        # 3. Resampling Sweep (Sampling rate in Hz)
        logger.info("Evaluating Robustness: Resampling Band-Limiting (16k to 6k Hz)...")
        summaries["resampling"] = self.evaluate_sweep(
            "Resampling",
            [16000, 12000, 8000, 6000],
            lambda a, v: self.transforms.apply_resampling(a, orig_sr=16000, target_sr=v),
            audios, labels, clean_scores, baseline_eer, baseline_acc,
        )

        # 4. Volume / Gain Changes (Gain dB)
        logger.info("Evaluating Robustness: Volume / Gain Scaling (-18 to +12 dB)...")
        summaries["volume_changes"] = self.evaluate_sweep(
            "Volume Scaling",
            [-18.0, -12.0, -6.0, 0.0, 6.0, 12.0],
            lambda a, v: self.transforms.apply_volume_change(a, gain_db=v),
            audios, labels, clean_scores, baseline_eer, baseline_acc,
        )

        # 5. Reverberation Sweep (RT60 in ms)
        logger.info("Evaluating Robustness: Reverberation (RT60 50 to 600 ms)...")
        summaries["reverberation"] = self.evaluate_sweep(
            "Reverberation",
            [50.0, 150.0, 300.0, 600.0],
            lambda a, v: self.transforms.apply_reverberation(a, rt60_ms=v),
            audios, labels, clean_scores, baseline_eer, baseline_acc,
        )

        # 6. Clipping Saturation (Clip threshold)
        logger.info("Evaluating Robustness: Non-linear Amplitude Clipping (1.0 to 0.15)...")
        summaries["clipping"] = self.evaluate_sweep(
            "Amplitude Clipping",
            [1.0, 0.8, 0.5, 0.3, 0.15],
            lambda a, v: self.transforms.apply_clipping(a, clip_threshold=v),
            audios, labels, clean_scores, baseline_eer, baseline_acc,
        )

        # 7. Spectral Perturbation (Notch filter frequency Hz)
        logger.info("Evaluating Robustness: Spectral Notch Filtering (1000 to 5000 Hz)...")
        summaries["spectral_perturbation"] = self.evaluate_sweep(
            "Spectral Notch",
            [1000.0, 2000.0, 3000.0, 4000.0, 5000.0],
            lambda a, v: self.transforms.apply_spectral_perturbation(a, notch_freq_hz=v),
            audios, labels, clean_scores, baseline_eer, baseline_acc,
        )

        # 8. Time-Domain Perturbation (Dropout rate %)
        logger.info("Evaluating Robustness: Time-Domain Micro-Dropouts (0% to 25%)...")
        summaries["time_domain_perturbation"] = self.evaluate_sweep(
            "Time Dropouts",
            [0.0, 5.0, 10.0, 15.0, 25.0],
            lambda a, v: self.transforms.apply_time_domain_perturbation(a, dropout_rate_pct=v),
            audios, labels, clean_scores, baseline_eer, baseline_acc,
        )

        return summaries

    def export_reports(
        self, summaries: Dict[str, TransformationSummary], output_dir: str = "reports"
    ) -> Tuple[str, str]:
        """
        Saves full JSON and CSV robustness reports.
        """
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)

        json_file = out_p / "adversarial_robustness_report.json"
        csv_file = out_p / "adversarial_summary.csv"

        # JSON Export
        data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "transformations": {k: asdict(v) for k, v in summaries.items()},
        }
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # CSV Export
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            import csv
            writer = csv.writer(f)
            writer.writerow([
                "Transformation",
                "Parameter",
                "EER (%)",
                "Accuracy (%)",
                "Robustness Score",
                "Score Drift",
                "Label Flip Rate (%)",
            ])
            for t_key, summary in summaries.items():
                for pt in summary.points:
                    writer.writerow([
                        pt.transformation,
                        pt.parameter_value,
                        pt.eer_percent,
                        pt.accuracy_percent,
                        pt.robustness_score,
                        pt.mean_score_drift,
                        pt.label_flip_rate_pct,
                    ])

        logger.info(f"Adversarial robustness reports saved to {json_file} and {csv_file}")
        return str(json_file), str(csv_file)


# Alias for convenience
AdversarialEvaluator = AdversarialRobustnessEvaluator

