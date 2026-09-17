import time
from typing import Dict, List, Optional
import numpy as np
import torch
from app.core.config import settings
from app.core.security import secure_zero_memory
from app.pipeline.interfaces import BaseAudioProcessor


class StreamingChunker(BaseAudioProcessor):
    """
    Manages an in-memory sliding window ring buffer for near real-time streaming audio.
    Default parameters: 1.5s window (24,000 samples at 16kHz) with 500ms hop (8,000 samples).
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        window_seconds: float = 1.5,
        hop_seconds: float = 0.5,
    ):
        self.sample_rate = sample_rate
        self.window_samples = int(sample_rate * window_seconds)
        self.hop_samples = int(sample_rate * hop_seconds)
        self.buffer = np.zeros(0, dtype=np.float32)
        self.latencies: list[float] = []

    def initialize(self, device: str = "cpu") -> None:
        self.reset()

    def reset(self) -> None:
        if len(self.buffer) > 0:
            secure_zero_memory(self.buffer)
        self.buffer = np.zeros(0, dtype=np.float32)
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

    def append_audio(self, new_audio: torch.Tensor) -> List[torch.Tensor]:
        """
        Appends new audio samples to the internal ring buffer.
        Returns a list of complete analysis windows (each of length `window_samples`)
        that are ready for processing according to `hop_samples`.
        """
        start_time = time.perf_counter()

        new_samples = new_audio.detach().cpu().numpy()
        self.buffer = np.concatenate((self.buffer, new_samples))

        ready_windows: List[torch.Tensor] = []

        while len(self.buffer) >= self.window_samples:
            # Extract 1.5s window
            window_slice = self.buffer[: self.window_samples].copy()
            ready_windows.append(torch.from_numpy(window_slice).unsqueeze(0))

            # Advance by hop_samples
            advance = self.hop_samples
            # Zero out the consumed portion for privacy
            secure_zero_memory(self.buffer[:advance])
            self.buffer = self.buffer[advance:]

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        self.latencies.append(latency_ms)

        return ready_windows
