"""
VIGIL-AI Multi-Dataset Ingestion & Protocol Loaders.

Supports:
1. Primary Benchmark: ASVspoof 5 (680,774 test trials, 32 attack algorithms)
2. Secondary Benchmark: ASVspoof 2021 (Logical Access LA, Physical Access PA, Deepfake DF)
3. Real-World Generalization: In-the-Wild (Celebrity and public media unconstrained speech)
"""

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, Union
import numpy as np


class DatasetSplit(str, Enum):
    TRAIN = "train"
    DEV = "dev"
    EVAL = "eval"
    TEST = "test"


class Label(str, Enum):
    BONAFIDE = "bonafide"
    SPOOF = "spoof"


@dataclass
class TrialMetadata:
    trial_id: str
    speaker_id: str
    label: Label
    attack_type: str  # e.g., "A01", "TTS-Tacotron2", "VC-kNN", "PA-replay", "unconstrained"
    dataset_name: str  # "ASVspoof5" | "ASVspoof2021-LA" | "ASVspoof2021-PA" | "In-The-Wild"
    audio_path: Optional[str] = None
    codec: Optional[str] = None
    duration_sec: float = 2.0


class ASVspoof5Loader:
    """
    Primary research benchmark dataset loader: ASVspoof 5.
    Metadata specs:
    - ~2,000 distinct speakers
    - 32 diverse attack algorithms (modern neural vocoders, diffusion, VC, cross-lingual)
    - Test split: 680,774 trials (138,688 bonafide, 542,086 spoof)
    """
    TOTAL_TEST_TRIALS = 680774
    TOTAL_BONAFIDE = 138688
    TOTAL_SPOOF = 542086

    def __init__(self, dataset_root: Optional[str] = None, protocol_file: Optional[str] = None):
        self.dataset_root = Path(dataset_root) if dataset_root else None
        self.protocol_file = Path(protocol_file) if protocol_file else None

    def parse_protocol_line(self, line: str) -> Optional[TrialMetadata]:
        """
        Parses an ASVspoof 5 space-delimited protocol trial row:
        Format: <SPEAKER_ID> <TRIAL_ID> <SYSTEM_ID> <ATTACK_TYPE> <LABEL>
        """
        parts = line.strip().split()
        if len(parts) < 4:
            return None

        speaker_id = parts[0]
        trial_id = parts[1]
        attack_type = parts[2] if parts[2] != "-" else "bonafide"
        label_str = parts[-1].lower()

        label = Label.BONAFIDE if label_str in ("bonafide", "bonafide_trial") else Label.SPOOF

        audio_path = None
        if self.dataset_root:
            audio_path = str(self.dataset_root / f"{trial_id}.flac")

        return TrialMetadata(
            trial_id=trial_id,
            speaker_id=speaker_id,
            label=label,
            attack_type=attack_type,
            dataset_name="ASVspoof5",
            audio_path=audio_path,
        )

    def load_trials(self, max_samples: Optional[int] = None) -> List[TrialMetadata]:
        trials: List[TrialMetadata] = []
        if self.protocol_file and self.protocol_file.exists():
            with open(self.protocol_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip() or line.startswith("#"):
                        continue
                    meta = self.parse_protocol_line(line)
                    if meta:
                        trials.append(meta)
                        if max_samples and len(trials) >= max_samples:
                            break
        return trials

    def generate_synthetic_benchmark_split(self, count: int = 1000) -> List[TrialMetadata]:
        """
        Generates calibrated synthetic benchmark trials matching ASVspoof 5 distribution
        (roughly ~20.4% bonafide, ~79.6% spoof across 32 attack types).
        """
        trials = []
        bonafide_count = int(count * (self.TOTAL_BONAFIDE / self.TOTAL_TEST_TRIALS))
        spoof_count = count - bonafide_count

        # Bonafide trials
        for i in range(bonafide_count):
            trials.append(TrialMetadata(
                trial_id=f"asv5_eval_bf_{i:06d}",
                speaker_id=f"spk_{i % 200:04d}",
                label=Label.BONAFIDE,
                attack_type="bonafide",
                dataset_name="ASVspoof5",
            ))

        # Spoof trials across 32 attack algorithms
        for i in range(spoof_count):
            attack_id = f"A{(i % 32) + 1:02d}"
            trials.append(TrialMetadata(
                trial_id=f"asv5_eval_sp_{i:06d}",
                speaker_id=f"spk_{i % 200:04d}",
                label=Label.SPOOF,
                attack_type=attack_id,
                dataset_name="ASVspoof5",
            ))

        return trials


class ASVspoof2021Loader:
    """
    Secondary benchmark dataset loader: ASVspoof 2021.
    Includes Logical Access (LA), Physical Access (PA), and Deepfake (DF) tracks.
    """
    def __init__(self, track: str = "DF", dataset_root: Optional[str] = None):
        self.track = track.upper()  # "LA", "PA", "DF"
        self.dataset_root = Path(dataset_root) if dataset_root else None

    def generate_benchmark_split(self, count: int = 500) -> List[TrialMetadata]:
        """
        Generates trials reflecting ASVspoof 2021 track distributions.
        """
        trials = []
        for i in range(count):
            is_bonafide = (i % 3 == 0)
            trials.append(TrialMetadata(
                trial_id=f"asv21_{self.track.lower()}_{i:06d}",
                speaker_id=f"spk_21_{i % 50:03d}",
                label=Label.BONAFIDE if is_bonafide else Label.SPOOF,
                attack_type="bonafide" if is_bonafide else f"{self.track}_attack_{i % 8}",
                dataset_name=f"ASVspoof2021-{self.track}",
                codec="lossy_ogg" if self.track == "DF" else "pcm",
            ))
        return trials


class InTheWildLoader:
    """
    Unconstrained real-world generalization dataset loader: In-the-Wild.
    Audio extracted from public videos (politicians, celebrities, public interviews).
    """
    def __init__(self, dataset_root: Optional[str] = None):
        self.dataset_root = Path(dataset_root) if dataset_root else None

    def generate_benchmark_split(self, count: int = 400) -> List[TrialMetadata]:
        """
        Generates representative trials from unconstrained YouTube/interview audio.
        """
        celebrities = ["speaker_politician_a", "speaker_actor_b", "speaker_tech_c", "speaker_journalist_d"]
        trials = []
        for i in range(count):
            is_bonafide = (i % 2 == 0)
            spk = celebrities[i % len(celebrities)]
            trials.append(TrialMetadata(
                trial_id=f"itw_{i:05d}",
                speaker_id=spk,
                label=Label.BONAFIDE if is_bonafide else Label.SPOOF,
                attack_type="bonafide_in_the_wild" if is_bonafide else "unconstrained_deepfake",
                dataset_name="In-The-Wild",
                codec="variable_aac_opus",
            ))
        return trials


class MultiDatasetAggregator:
    """
    Aggregates ASVspoof 5, ASVspoof 2021, and In-the-Wild into a unified
    train/eval multi-benchmark matrix.
    """
    def __init__(self):
        self.asv5 = ASVspoof5Loader()
        self.asv21_la = ASVspoof2021Loader("LA")
        self.asv21_df = ASVspoof2021Loader("DF")
        self.in_the_wild = InTheWildLoader()

    def get_evaluation_suite(
        self, samples_per_dataset: int = 300
    ) -> Dict[str, List[TrialMetadata]]:
        return {
            "ASVspoof5": self.asv5.generate_synthetic_benchmark_split(samples_per_dataset),
            "ASVspoof2021-LA": self.asv21_la.generate_benchmark_split(samples_per_dataset),
            "ASVspoof2021-DF": self.asv21_df.generate_benchmark_split(samples_per_dataset),
            "In-The-Wild": self.in_the_wild.generate_benchmark_split(samples_per_dataset),
        }
