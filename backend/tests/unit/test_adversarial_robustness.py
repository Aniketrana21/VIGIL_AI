"""
Unit Tests for Phase 15 Defensive Adversarial Robustness Module.

Validates:
1. Mathematical correctness and numerical stability of all 8 acoustic transformations:
   - Additive noise (SNR sweep)
   - Codec compression (Bit depth quantization)
   - Resampling (Bandwidth limitation)
   - Volume changes (Gain scaling)
   - Reverberation (Room impulse response)
   - Clipping (Non-linear saturation)
   - Spectral perturbation (IIR Notch filtering)
   - Time-domain perturbation (Micro-dropouts)
2. Robustness metrics evaluation (Robustness Score, Mean Score Drift, Label Flip Rate, Breakdown Points).
3. Report export functionality (JSON schema & CSV format).
4. Diagnostic plotting generation (8-panel profile and radar summary).
"""

import json
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
from pathlib import Path
import numpy as np
import pytest

from app.evaluation.adversarial_evaluator import AdversarialEvaluator, TransformationSummary, RobustnessPoint
from app.evaluation.adversarial_transforms import AdversarialTransformations
from app.evaluation.plot_robustness import RobustnessPlotter


class TestPhase15AdversarialTransforms:

    @pytest.fixture
    def transforms(self) -> AdversarialTransformations:
        return AdversarialTransformations(sample_rate=16000, seed=42)

    @pytest.fixture
    def test_audio(self) -> np.ndarray:
        # 1-second 440 Hz test tone + harmonic with gentle noise
        t = np.linspace(0, 1.0, 16000, endpoint=False)
        sig = 0.6 * np.sin(2 * np.pi * 440 * t) + 0.3 * np.sin(2 * np.pi * 880 * t)
        return sig.astype(np.float32)

    def test_additive_noise(self, transforms, test_audio):
        noisy = transforms.apply_additive_noise(test_audio, snr_db=10.0)
        assert len(noisy) == len(test_audio)
        assert not np.isnan(noisy).any()
        assert not np.isclose(noisy, test_audio).all()
        # Max amplitude within safe limits
        assert np.max(np.abs(noisy)) <= 1.01

    def test_codec_compression(self, transforms, test_audio):
        compressed_4bit = transforms.apply_codec_compression(test_audio, bit_depth=4)
        assert len(compressed_4bit) == len(test_audio)
        assert not np.isnan(compressed_4bit).any()
        # Quantized levels should be discrete
        unique_levels = len(np.unique(np.round(compressed_4bit, 3)))
        assert unique_levels <= 16

    def test_resampling(self, transforms, test_audio):
        resampled_8k = transforms.apply_resampling(test_audio, orig_sr=16000, target_sr=8000)
        assert len(resampled_8k) == len(test_audio)
        assert not np.isnan(resampled_8k).any()
        # High frequency content (880Hz) or sharp gradients attenuated
        assert not np.allclose(resampled_8k, test_audio)

    def test_volume_changes(self, transforms, test_audio):
        quieter = transforms.apply_volume_change(test_audio, gain_db=-12.0)
        louder = transforms.apply_volume_change(test_audio, gain_db=6.0)

        assert np.max(np.abs(quieter)) < np.max(np.abs(test_audio))
        assert np.max(np.abs(louder)) <= 1.0  # Clipped to [-1.0, 1.0]

    def test_reverberation(self, transforms, test_audio):
        reverbed = transforms.apply_reverberation(test_audio, rt60_ms=200.0)
        assert len(reverbed) == len(test_audio)
        assert not np.isnan(reverbed).any()
        assert np.max(np.abs(reverbed)) <= 1.01

    def test_clipping(self, transforms, test_audio):
        threshold = 0.4
        clipped = transforms.apply_clipping(test_audio, clip_threshold=threshold)
        assert len(clipped) == len(test_audio)
        assert np.max(np.abs(clipped)) <= 1.0 + 1e-5
        assert np.sum(np.isclose(np.abs(clipped), 1.0, atol=1e-3)) > 0

    def test_spectral_perturbation(self, transforms, test_audio):
        notched = transforms.apply_spectral_perturbation(test_audio, notch_freq_hz=440.0, q_factor=15.0)
        assert len(notched) == len(test_audio)
        assert not np.isnan(notched).any()
        # 440 Hz component was suppressed, so energy must decrease
        assert np.mean(notched ** 2) < np.mean(test_audio ** 2)

    def test_time_domain_perturbation(self, transforms, test_audio):
        dropped = transforms.apply_time_domain_perturbation(test_audio, dropout_rate_pct=15.0)
        assert len(dropped) == len(test_audio)
        assert not np.isnan(dropped).any()
        # Some zeros should have been inserted
        zeros_count = np.count_nonzero(dropped == 0.0)
        assert zeros_count > 0


class TestPhase15AdversarialEvaluator:

    @pytest.fixture
    def evaluator(self) -> AdversarialEvaluator:
        return AdversarialEvaluator()

    def test_baseline_profiling(self, evaluator):
        clean_audios, labels, clean_scores, eer, acc = evaluator.profile_clean_baseline(sample_count=20)
        assert len(clean_audios) == 20
        assert len(labels) == 20
        assert len(clean_scores) == 20
        assert 0.0 <= eer <= 100.0
        assert 0.0 <= acc <= 100.0
        assert all(0.0 <= s <= 1.0 for s in clean_scores)

    def test_single_sweep_evaluation(self, evaluator):
        clean_audios, labels, clean_scores, eer, acc = evaluator.profile_clean_baseline(sample_count=20)
        summary = evaluator.evaluate_sweep(
            "Additive Noise",
            [20.0, 5.0],
            lambda a, v: evaluator.transforms.apply_additive_noise(a, snr_db=v),
            clean_audios,
            labels,
            clean_scores,
            eer,
            acc,
        )
        assert summary.transformation_name == "Additive Noise"
        assert len(summary.points) == 2
        for pt in summary.points:
            assert isinstance(pt, RobustnessPoint)
            assert 0.0 <= pt.robustness_score <= 1.0
            assert pt.mean_score_drift >= 0.0
            assert 0.0 <= pt.label_flip_rate_pct <= 100.0

    def test_breakdown_point_logic(self, evaluator):
        pts = [
            RobustnessPoint("Noise", 20.0, 5.0, 95.0, 1.0, 0.02, 0.0),
            RobustnessPoint("Noise", 10.0, 12.0, 88.0, 0.88, 0.10, 5.0),
            RobustnessPoint("Noise", 0.0, 35.0, 60.0, 0.45, 0.35, 30.0),  # < 0.6 threshold
        ]
        breakdown = evaluator._find_breakdown_point(pts, failure_threshold=0.6)
        assert breakdown == 0.0

    def test_run_all_sweeps_and_export(self, evaluator, tmp_path):
        # Fast sweep with 16 samples
        summaries = evaluator.run_all_sweeps(sample_count=16)
        assert len(summaries) == 8
        assert "additive_noise" in summaries
        assert "codec_compression" in summaries
        assert "resampling" in summaries
        assert "volume_changes" in summaries
        assert "reverberation" in summaries
        assert "clipping" in summaries
        assert "spectral_perturbation" in summaries
        assert "time_domain_perturbation" in summaries

        # Export to temp directory
        json_path, csv_path = evaluator.export_reports(summaries, output_dir=str(tmp_path))
        assert Path(json_path).exists()
        assert Path(csv_path).exists()

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert "transformations" in data
            assert len(data["transformations"]) == 8

        # Test Plotting
        plotter = RobustnessPlotter(output_dir=str(tmp_path))
        profile_path = plotter.plot_all_transformations(summaries, "test_profile.png")
        radar_path = plotter.plot_radar_summary(summaries, "test_radar.png")

        assert Path(profile_path).exists()
        assert Path(radar_path).exists()
        assert Path(profile_path).stat().st_size > 1000
        assert Path(radar_path).stat().st_size > 1000
