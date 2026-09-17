"""
Unit Tests for Phase 14 Research-Grade Evaluation Suite.

Validates:
1. IndianLangVoice multi-lingual dataset loader across 6 linguistic families.
2. ResearchEvaluationSuite executes across ASVspoof 5, ASVspoof 2021, In-the-Wild, and IndianLangVoice.
3. Known vs Unseen attack generalization experiment produces valid degradation gap.
4. Comprehensive metric calculation (EER, ROC-AUC, FAR, FRR, RTF).
5. Plotting pipeline generates all 6 publication-ready diagnostic charts.
"""

from pathlib import Path
import numpy as np
import pytest
from app.evaluation.benchmark_suite import ResearchEvaluationSuite
from app.evaluation.plotter import ResearchPlotter
from app.training.dataset_loaders import Label
from app.training.indian_dataset_loader import IndianLanguage, IndianLanguageDatasetLoader


class TestPhase14ResearchEvaluationSuite:

    @pytest.fixture
    def suite(self) -> ResearchEvaluationSuite:
        return ResearchEvaluationSuite()

    @pytest.fixture
    def plotter(self, tmp_path) -> ResearchPlotter:
        return ResearchPlotter(output_dir=str(tmp_path))

    def test_indian_language_loader_diversity(self):
        """Verify IndianLangVoice covers 6 linguistic families, code-switching, and regional accents."""
        loader = IndianLanguageDatasetLoader()
        trials = loader.generate_benchmark_split(count=120)
        assert len(trials) == 120

        languages = {t.language for t in trials}
        assert len(languages) == 6
        assert "Hindi" in languages
        assert "Tamil" in languages
        assert "Telugu" in languages
        assert "Bengali" in languages
        assert "Marathi" in languages
        assert "Indian-English" in languages

        # Verify presence of code-switched trials
        code_switched = [t for t in trials if t.is_code_switched]
        assert len(code_switched) > 0

        # Verify bonafide and spoof distributions
        bonafide = [t for t in trials if t.label == Label.BONAFIDE]
        spoof = [t for t in trials if t.label == Label.SPOOF]
        assert len(bonafide) == 60
        assert len(spoof) == 60

    def test_dataset_evaluation_full_metrics(self, suite):
        """Verify DetailedMetrics calculation (EER, ROC-AUC, FAR, FRR, RTF, confusion matrix)."""
        trials = suite.asv5_loader.generate_synthetic_benchmark_split(count=40)
        metrics, (y_true, y_scores, lats) = suite.evaluate_dataset("ASVspoof 5", trials)

        assert metrics.dataset_name == "ASVspoof 5"
        assert metrics.total_trials == 40
        assert 0.0 <= metrics.eer_percent <= 100.0
        assert 0.0 <= metrics.roc_auc <= 1.0
        assert 0.0 <= metrics.precision <= 100.0
        assert 0.0 <= metrics.recall <= 100.0
        assert 0.0 <= metrics.f1_score <= 100.0
        assert 0.0 <= metrics.far <= 100.0
        assert 0.0 <= metrics.frr <= 100.0
        assert len(metrics.confusion_matrix) == 2
        assert len(metrics.confusion_matrix[0]) == 2
        assert metrics.latency_mean_ms > 0.0
        assert metrics.real_time_factor < 0.1  # Fast real-time factor

    def test_known_vs_unseen_attack_experiment(self, suite):
        """Verify known attack vs zero-shot unseen attack generalization experiment."""
        result = suite.run_known_vs_unseen_experiment(samples_per_group=30)
        assert result.known_attacks_eer >= 0.0
        assert result.unseen_attacks_eer >= 0.0
        assert len(result.held_out_attack_families) > 0
        assert isinstance(result.generalization_gap_eer, float)

    def test_noise_compression_stress_test(self, suite):
        """Verify SNR noise degradation curves across multiple levels."""
        snr_results = suite.run_noise_compression_stress_test(snr_levels=[25.0, 10.0, 0.0])
        assert 25.0 in snr_results
        assert 10.0 in snr_results
        assert 0.0 in snr_results
        for snr, eer in snr_results.items():
            assert 0.0 <= eer <= 100.0

    def test_publication_plots_generation(self, plotter, tmp_path):
        """Verify ResearchPlotter generates all 6 mandated diagnostic charts."""
        y_true = np.array([0, 0, 0, 1, 1, 1])
        y_scores = np.array([0.1, 0.2, 0.3, 0.8, 0.85, 0.9])

        # 1. ROC curve
        roc_path = plotter.plot_roc_curves({"Bench": (y_true, y_scores, 1.0)}, "test_roc.png")
        assert Path(roc_path).exists()
        assert Path(roc_path).stat().st_size > 1000

        # 2. DET curve
        det_path = plotter.plot_det_curves({"Bench": (y_true, y_scores)}, "test_det.png")
        assert Path(det_path).exists()

        # 3. Confusion matrix
        cm_path = plotter.plot_confusion_matrix([[3, 0], [0, 3]], "Test CM", "test_cm.png")
        assert Path(cm_path).exists()

        # 4. EER comparison
        eer_path = plotter.plot_eer_comparison({"ASVspoof 5": 1.2, "In-the-Wild": 4.5}, "test_eer.png")
        assert Path(eer_path).exists()

        # 5. Latency distribution
        lat_path = plotter.plot_latency_distribution([8.5, 9.2, 11.0, 14.2, 8.9], "test_lat.png")
        assert Path(lat_path).exists()

        # 6. Robustness under noise
        noise_path = plotter.plot_noise_compression_robustness({25.0: 1.0, 15.0: 2.5, 0.0: 12.0}, "test_noise.png")
        assert Path(noise_path).exists()
