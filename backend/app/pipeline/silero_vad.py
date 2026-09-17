import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import torch
from app.core.config import settings
from app.core.logging import logger
from app.pipeline.vad_interface import SimpleVAD, VADDecision, VADInterface


class SileroModelRegistry:
    """
    Singleton registry managing the Silero VAD PyTorch JIT model.
    Loads the underlying neural network once on startup and shares it across all sessions.
    Guarantees thread-safe stateless forward passes.
    """
    _instance_lock = threading.Lock()
    _model = None
    _underlying_model = None
    _is_initialized = False

    @classmethod
    def get_model(cls) -> Tuple[Optional[Any], Optional[Any]]:
        """Returns (jit_wrapper_model, underlying_core_model)."""
        if not cls._is_initialized:
            with cls._instance_lock:
                if not cls._is_initialized:
                    cls._load_model()
        return cls._model, cls._underlying_model

    @classmethod
    def _load_model(cls) -> None:
        try:
            logger.info("Loading Silero VAD PyTorch JIT model from snakers4/silero-vad...")
            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                trust_repo=True,
                onnx=False,
            )
            model.eval()
            cls._model = model
            # Extract underlying recursive script module for stateless multi-session forward passes
            if hasattr(model, "_model"):
                cls._underlying_model = model._model
            else:
                cls._underlying_model = model
            cls._is_initialized = True
            logger.info("Silero VAD PyTorch JIT model successfully loaded into memory.")
        except Exception as e:
            logger.warning(f"Failed to load Silero VAD via torch.hub ({e}). Falling back to adaptive acoustic engine.")
            cls._model = None
            cls._underlying_model = None
            cls._is_initialized = True


class SileroStreamingVAD(VADInterface):
    """
    Production-quality streaming Voice Activity Detection using Silero VAD.
    
    Features:
    - Shared neural weights: Does NOT reload model per chunk.
    - Thread-safe streaming state per session (recurrent state + context tensor).
    - Configurable speech threshold, min speech duration, min silence duration, and context padding.
    - High-precision latency tracking (p50, p95, current latency).
    - Robust handling of silence, stationary background noise, and music.
    - Strict output schema: {is_speech, speech_probability, start_time, end_time}.
    """

    def __init__(
        self,
        speech_threshold: float = 0.50,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 300,
        speech_pad_ms: int = 150,
        sample_rate: int = 16000,
        energy_noise_floor_db: float = -55.0,
    ):
        self.speech_threshold = speech_threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.speech_pad_ms = speech_pad_ms
        self.sample_rate = sample_rate
        self.energy_noise_floor_db = energy_noise_floor_db

        self.min_speech_samples = int(sample_rate * (min_speech_duration_ms / 1000.0))
        self.min_silence_samples = int(sample_rate * (min_silence_duration_ms / 1000.0))
        self.speech_pad_samples = int(sample_rate * (speech_pad_ms / 1000.0))

        # Model reference from singleton
        self.wrapper_model, self.core_model = SileroModelRegistry.get_model()
        self.fallback_vad = SimpleVAD() if self.core_model is None else None

        # Per-session streaming recurrent state & context
        self.state = torch.zeros(2, 1, 128, dtype=torch.float32)
        self.context = torch.zeros(1, 64, dtype=torch.float32)
        self.sub_buffer = np.zeros(0, dtype=np.float32)

        # Stream state machine
        self.current_sample = 0
        self.triggered = False
        self.temp_end = 0
        self.speech_start_sample: Optional[int] = None
        self.speech_end_sample: Optional[int] = None
        self.accumulated_speech_samples = 0

        # Latency tracking
        self.latencies: List[float] = []
        self.last_latency_ms = 0.0

    def reset(self) -> None:
        """Resets streaming states and session timestamps."""
        self.state = torch.zeros(2, 1, 128, dtype=torch.float32)
        self.context = torch.zeros(1, 64, dtype=torch.float32)
        self.sub_buffer = np.zeros(0, dtype=np.float32)
        self.current_sample = 0
        self.triggered = False
        self.temp_end = 0
        self.speech_start_sample = None
        self.speech_end_sample = None
        self.accumulated_speech_samples = 0
        self.latencies.clear()
        self.last_latency_ms = 0.0
        if self.fallback_vad:
            self.fallback_vad.reset()

    def get_latency_stats(self) -> Dict[str, float]:
        """Returns latency statistics in milliseconds."""
        if not self.latencies:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "last": self.last_latency_ms}
        arr = np.array(self.latencies)
        return {
            "p50": round(float(np.percentile(arr, 50)), 2),
            "p95": round(float(np.percentile(arr, 95)), 2),
            "p99": round(float(np.percentile(arr, 99)), 2),
            "last": round(self.last_latency_ms, 2),
        }

    def is_speech(self, audio_samples: np.ndarray, sample_rate: int = 16000) -> VADDecision:
        """
        Evaluates an audio chunk (or sliding window) for speech activity.
        Maintains streaming recurrent state and applies context padding.
        """
        t0 = time.perf_counter()

        if len(audio_samples) == 0:
            return VADDecision(
                is_speech=False,
                speech_probability=0.0,
                start_time=None,
                end_time=None,
                rms_db=-100.0,
                latency_ms=0.0,
            )

        # Fallback if neural model unavailable
        if self.core_model is None:
            res = self.fallback_vad.is_speech(audio_samples, sample_rate=sample_rate)
            self.last_latency_ms = res.latency_ms
            self.latencies.append(self.last_latency_ms)
            return res

        # 1. Compute acoustic metrics
        rms = np.sqrt(np.mean(audio_samples ** 2) + 1e-12)
        rms_db = 20.0 * math.log10(max(rms, 1e-6))
        zcr = np.mean(np.abs(np.diff(np.sign(audio_samples)))) / 2.0 if len(audio_samples) > 1 else 0.0

        # Spectral entropy
        if len(audio_samples) >= 128:
            fft_mag = np.abs(np.fft.rfft(audio_samples))
            sum_mag = np.sum(fft_mag) + 1e-12
            norm_mag = fft_mag / sum_mag
            spec_entropy = -np.sum(norm_mag * np.log2(norm_mag + 1e-12)) / np.log2(len(norm_mag) + 1e-12)
        else:
            spec_entropy = 0.5

        # 2. Digital Silence Guard
        if rms_db < self.energy_noise_floor_db:
            # Below acoustic floor: definitely silence, fast-path
            self.current_sample += len(audio_samples)
            if self.triggered:
                if not self.temp_end:
                    self.temp_end = self.current_sample
                if self.current_sample - self.temp_end >= self.min_silence_samples:
                    self.triggered = False
                    self.speech_end_sample = self.temp_end + self.speech_pad_samples
                    self.temp_end = 0
                    self.accumulated_speech_samples = 0

            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.last_latency_ms = elapsed_ms
            self.latencies.append(elapsed_ms)

            start_t = round(self.speech_start_sample / sample_rate, 3) if self.speech_start_sample is not None else None
            end_t = round(self.speech_end_sample / sample_rate, 3) if self.speech_end_sample is not None else None

            return VADDecision(
                is_speech=self.triggered,
                speech_probability=0.01,
                start_time=start_t,
                end_time=end_t,
                rms_db=round(rms_db, 2),
                zero_crossing_rate=round(float(zcr), 3),
                spectral_entropy=round(float(spec_entropy), 3),
                latency_ms=round(elapsed_ms, 2),
            )

        # 3. Stream through Silero VAD in 512-sample (32ms) sub-frames
        all_samples = np.concatenate((self.sub_buffer, audio_samples)) if len(self.sub_buffer) > 0 else audio_samples
        sub_frame_size = 512
        num_sub_frames = len(all_samples) // sub_frame_size

        sub_frame_probs = []

        with torch.no_grad():
            for i in range(num_sub_frames):
                frame_data = all_samples[i * sub_frame_size : (i + 1) * sub_frame_size]
                self.current_sample += sub_frame_size

                # Convert to Float32 Tensor [1, 512]
                frame_tensor = torch.from_numpy(frame_data).unsqueeze(0).to(torch.float32)

                # Feed context + frame into core model
                x = torch.cat([self.context, frame_tensor], dim=1)
                out, new_state = self.core_model(x, self.state)
                self.state = new_state
                self.context = x[:, -64:]

                prob = float(out.item())
                sub_frame_probs.append(prob)

                # State Machine with Min Speech / Silence Durations and Context Padding
                if prob >= self.speech_threshold:
                    if self.temp_end:
                        self.temp_end = 0  # Speech resumed within silence window

                    if not self.triggered:
                        self.accumulated_speech_samples += sub_frame_size
                        if self.accumulated_speech_samples >= self.min_speech_samples:
                            self.triggered = True
                            # Preserve pre-speech context padding
                            self.speech_start_sample = max(
                                0, self.current_sample - self.speech_pad_samples - self.accumulated_speech_samples
                            )
                            self.speech_end_sample = None
                    else:
                        self.speech_end_sample = None

                elif prob < max(0.20, self.speech_threshold - 0.15):
                    if self.triggered:
                        if not self.temp_end:
                            self.temp_end = self.current_sample

                        if self.current_sample - self.temp_end >= self.min_silence_samples:
                            # Preserve post-speech context padding
                            self.triggered = False
                            self.speech_end_sample = self.temp_end + self.speech_pad_samples
                            self.temp_end = 0
                            self.accumulated_speech_samples = 0
                    else:
                        self.accumulated_speech_samples = 0

        # Preserve leftover samples (< 512) for next chunk
        leftover = len(all_samples) % sub_frame_size
        self.sub_buffer = all_samples[-leftover:] if leftover > 0 else np.zeros(0, dtype=np.float32)

        # Compute representative speech probability for this chunk
        if sub_frame_probs:
            speech_prob = float(np.mean(sub_frame_probs))
        else:
            speech_prob = 0.0

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.last_latency_ms = elapsed_ms
        self.latencies.append(elapsed_ms)

        start_t = round(self.speech_start_sample / sample_rate, 3) if self.speech_start_sample is not None else None
        end_t = round(self.speech_end_sample / sample_rate, 3) if self.speech_end_sample is not None else None

        return VADDecision(
            is_speech=self.triggered or (speech_prob >= self.speech_threshold),
            speech_probability=round(speech_prob, 3),
            start_time=start_t,
            end_time=end_t,
            rms_db=round(rms_db, 2),
            zero_crossing_rate=round(float(zcr), 3),
            spectral_entropy=round(float(spec_entropy), 3),
            latency_ms=round(elapsed_ms, 2),
        )
