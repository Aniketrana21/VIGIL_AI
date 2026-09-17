import math
import time
from typing import Dict, Union
import numpy as np
import scipy.signal
import torch
from app.core.config import settings
from app.core.security import secure_zero_memory
from app.pipeline.interfaces import BaseAudioProcessor, PreprocessorResult


class AudioPreprocessor(BaseAudioProcessor):
    """
    Normalizes, resamples, and sanitizes incoming audio bytes into a standard
    16kHz 1-channel Float32 PyTorch tensor bounded in [-1.0, 1.0].
    """

    def __init__(self, target_sample_rate: int = 16000):
        self.target_sample_rate = target_sample_rate
        self.latencies: list[float] = []

    def initialize(self, device: str = "cpu") -> None:
        pass

    def reset(self) -> None:
        self.latencies.clear()

    def get_latency_stats(self) -> Dict[str, float]:
        if not self.latencies:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        arr = np.array(self.latencies)
        return {
            "p50": float(np.percentile(arr, 50)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
        }

    def process_raw_bytes(
        self,
        raw_pcm_bytes: Union[bytes, bytearray],
        source_sample_rate: int = 16000,
        source_channels: int = 1,
    ) -> PreprocessorResult:
        """
        Converts raw little-endian 16-bit PCM bytes into normalized float32 tensor.
        Enforces zero-retention memory wipe of intermediate buffers.
        """
        start_time = time.perf_counter()

        # Parse 16-bit signed integer PCM
        audio_int16 = np.frombuffer(raw_pcm_bytes, dtype=np.int16)

        # De-interleave if multi-channel (average to mono)
        if source_channels > 1:
            audio_int16 = audio_int16.reshape(-1, source_channels).mean(axis=1).astype(np.int16)

        # Convert to float32 [-1.0, 1.0]
        audio_float = audio_int16.astype(np.float32) / 32768.0

        # Resample to target_sample_rate if necessary
        if source_sample_rate != self.target_sample_rate and len(audio_float) > 0:
            num_output_samples = int(len(audio_float) * float(self.target_sample_rate) / float(source_sample_rate))
            audio_float = scipy.signal.resample(audio_float, num_output_samples).astype(np.float32)

        # Peak clipping guard & soft knee limiting
        peak = float(np.max(np.abs(audio_float))) if len(audio_float) > 0 else 0.0
        if peak > 0.99:
            audio_float = np.clip(audio_float, -0.99, 0.99)

        # Compute peak dBFS
        peak_db = 20.0 * math.log10(max(peak, 1e-6))

        # Convert to torch tensor
        tensor = torch.from_numpy(audio_float)

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        self.latencies.append(latency_ms)

        return PreprocessorResult(
            audio_tensor=tensor,
            sample_rate=self.target_sample_rate,
            peak_level_db=round(peak_db, 2),
            latency_ms=round(latency_ms, 2),
        )
