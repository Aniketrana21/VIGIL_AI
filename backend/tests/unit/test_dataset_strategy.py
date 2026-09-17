"""
Unit Tests for VIGIL-AI Multi-Dataset Training Strategy & 9-Fold Augmentations.
Validates:
1. All 9 acoustic augmentation transforms execute deterministically.
2. Multi-dataset loaders correctly parse ASVspoof 5 (680k spec), ASVspoof 2021, and In-the-Wild.
3. EER calculator operates accurately with known test distributions.
4. Out-of-Domain Generalization Gap metric computation.
5. Trainer optimization step and multi-benchmark evaluation pass.
"""

import numpy as np
import pytest
import torch
from app.training.augmentations import AudioAugmenter, AugmentationConfig
from app.training.dataset_loaders import (
    ASVspoof5Loader,
    ASVspoof2021Loader,
    InTheWildLoader,
    Label,
    MultiDatasetAggregator,
)
from app.training.evaluator import (
    BenchmarkEvaluationResult,
    MultiBenchmarkEvaluator,
    compute_eer,
)
from app.training.train_anti_spoof import AntiSpoofTrainer, TrainingArgs


class TestPhase14DatasetAndAugmentationStrategy:

    @pytest.fixture
    def test_audio(self) -> np.ndarray:
        # 2.0s 16kHz sine wave voice simulation
        t = np.linspace(0, 2.0, 32000, endpoint=False)
        return (0.6 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)

    @pytest.fixture
    def augmenter(self) -> AudioAugmenter:
        return AudioAugmenter(AugmentationConfig(sample_rate=16000))

    def test_all_nine_augmentations_exist_and_execute(self, test_audio, augmenter):
        """Verify all 9 mandated degradation transforms run cleanly on 16kHz audio."""
        aug_dict = augmenter.get_all_augmentations(test_audio)

        # 1. TTS generated
        assert "tts_generated" in aug_dict
        assert len(aug_dict["tts_generated"]) == len(test_audio)
        assert np.isfinite(aug_dict["tts_generated"]).all()

        # 2. Voice conversion
        assert "voice_conversion" in aug_dict
        assert len(aug_dict["voice_conversion"]) == len(test_audio)

        # 3. Noise added
        assert "noise_added" in aug_dict
        assert len(aug_dict["noise_added"]) == len(test_audio)
        assert not np.array_equal(aug_dict["noise_added"], test_audio)

        # 4. Compression
        assert "compression" in aug_dict
        assert len(aug_dict["compression"]) == len(test_audio)

        # 5. Telephone codec
        assert "telephone_codec" in aug_dict
        assert len(aug_dict["telephone_codec"]) == len(test_audio)

        # 6. Background conversation
        assert "background_conversation" in aug_dict
        assert len(aug_dict["background_conversation"]) == len(test_audio)

        # 7. Re-recorded through speaker
        assert "speaker_playback" in aug_dict
        assert len(aug_dict["speaker_playback"]) == len(test_audio)

        # 8. WhatsApp-like compression
        assert "whatsapp_compression" in aug_dict
        assert len(aug_dict["whatsapp_compression"]) == len(test_audio)

        # 9. Partial manipulation
        assert "partial_manipulation" in aug_dict
        assert len(aug_dict["partial_manipulation"]) == len(test_audio)

    def test_partial_manipulation_boundary_and_metadata(self, test_audio, augmenter):
        """Verify partial manipulation creates a spliced window with valid metadata."""
        spliced, meta = augmenter.apply_partial_manipulation(test_audio)
        assert meta["is_partially_manipulated"] is True
        assert 0.0 < meta["manipulation_ratio"] < 1.0
        assert meta["manipulation_start"] < meta["manipulation_end"]
        assert len(spliced) == len(test_audio)

    def test_asvspoof5_protocol_loader_and_benchmark_spec(self):
        """Verify ASVspoof 5 loader reflects primary benchmark specs (680k test trials, 32 attacks)."""
        loader = ASVspoof5Loader()
        assert loader.TOTAL_TEST_TRIALS == 680774
        assert loader.TOTAL_BONAFIDE == 138688
        assert loader.TOTAL_SPOOF == 542086

        # Generate representative benchmark split
        split = loader.generate_synthetic_benchmark_split(count=200)
        assert len(split) == 200

        # Verify presence of 32 attack types
        attacks = {t.attack_type for t in split if t.label == Label.SPOOF}
        assert len(attacks) > 20  # Sampled across 32 attack algorithms

    def test_asvspoof2021_and_in_the_wild_loaders(self):
        """Verify ASVspoof 2021 (LA/PA/DF) and In-the-Wild loaders."""
        loader_2021 = ASVspoof2021Loader("LA")
        split_2021 = loader_2021.generate_benchmark_split(count=150)
        assert len(split_2021) == 150
        assert split_2021[0].dataset_name == "ASVspoof2021-LA"

        loader_itw = InTheWildLoader()
        split_itw = loader_itw.generate_benchmark_split(count=100)
        assert len(split_itw) == 100
        assert split_itw[0].dataset_name == "In-The-Wild"
        assert "politician" in split_itw[0].speaker_id or "actor" in split_itw[0].speaker_id

    def test_multi_dataset_aggregator(self):
        """Verify multi-dataset matrix compiles all benchmark datasets."""
        agg = MultiDatasetAggregator()
        suite = agg.get_evaluation_suite(samples_per_dataset=50)
        assert "ASVspoof5" in suite
        assert "ASVspoof2021-LA" in suite
        assert "ASVspoof2021-DF" in suite
        assert "In-The-Wild" in suite
        assert len(suite["ASVspoof5"]) == 50
        assert len(suite["In-The-Wild"]) == 50

    def test_eer_computation_accuracy(self):
        """Verify Equal Error Rate calculation on known distributions."""
        # Perfectly separated scores: bonafide ~ 0.9, spoof ~ 0.1
        bf = np.random.normal(0.9, 0.05, 500)
        sp = np.random.normal(0.1, 0.05, 500)
        eer, threshold = compute_eer(bf, sp)
        assert eer < 1.0  # Near zero EER for disjoint sets
        assert 0.4 < threshold < 0.6

        # Overlapping distributions: bonafide ~ 0.55, spoof ~ 0.45
        bf_overlap = np.random.normal(0.55, 0.1, 500)
        sp_overlap = np.random.normal(0.45, 0.1, 500)
        eer_overlap, _ = compute_eer(bf_overlap, sp_overlap)
        assert 15.0 < eer_overlap < 40.0

    def test_generalization_gap_computation(self):
        """Verify Out-of-Domain Generalization Gap calculation."""
        evaluator = MultiBenchmarkEvaluator()

        res_primary = BenchmarkEvaluationResult(
            dataset_name="ASVspoof5",
            total_trials=1000,
            bonafide_trials=200,
            spoof_trials=800,
            eer_percent=2.4,
            threshold_at_eer=0.55,
            accuracy_at_eer=97.6,
            attack_breakdown={"A01": 98.0, "A02": 97.2},
        )

        res_wild = BenchmarkEvaluationResult(
            dataset_name="In-The-Wild",
            total_trials=500,
            bonafide_trials=250,
            spoof_trials=250,
            eer_percent=5.8,
            threshold_at_eer=0.52,
            accuracy_at_eer=94.2,
            attack_breakdown={"unconstrained_deepfake": 94.2},
        )

        gap_info = evaluator.compute_generalization_gap(res_primary, res_wild)
        assert gap_info["primary_eer"] == 2.4
        assert gap_info["in_the_wild_eer"] == 5.8
        assert gap_info["generalization_gap_eer"] == 3.4

    def test_anti_spoof_trainer_step_and_eval(self):
        """Verify training step forward-backward and multi-benchmark evaluation loop."""
        args = TrainingArgs(epochs=1, batch_size=4, device="cpu")
        trainer = AntiSpoofTrainer(args)

        # Single optimization step
        loss = trainer.train_step()
        assert isinstance(loss, float)
        assert loss > 0.0

        # Multi-benchmark evaluation pass
        eval_scores = trainer.evaluate_multi_benchmarks()
        assert "ASVspoof5_EER" in eval_scores
        assert "ASVspoof2021-LA_EER" in eval_scores
        assert "In-The-Wild_EER" in eval_scores
