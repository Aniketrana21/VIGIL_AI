"""
VIGIL-AI Phase 7: Async Inference Pipeline — Producer-Consumer Architecture.

4-stage non-blocking pipeline with bounded queues, backpressure,
temporal result smoothing, and fine-grained latency profiling.

Stages:
  1. Preprocessor Worker  — validation, buffering, window slicing
  2. ML Inference Worker   — micro-batched VAD, deepfake, speaker, liveness
  3. Risk Engine Worker    — multi-signal synthesis + EMA smoothing
  4. Result Streamer Worker — non-blocking telemetry broadcast
"""
import asyncio
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Union

import numpy as np
import torch

from app.core.config import settings
from app.core.logging import logger
from app.pipeline.audio_buffer import AudioBuffer
from app.pipeline.deepfake_detector import DeepfakeDetector, DeepfakeModelRegistry, DetectionResult
from app.pipeline.device import DeviceManager
from app.pipeline.liveness import AcousticLivenessDetector
from app.pipeline.risk_engine import MultiFactorRiskEngine, RiskEngineInput, RiskEvaluationResult
from app.pipeline.silero_vad import SileroStreamingVAD
from app.pipeline.speaker_service import SpeakerVerificationResult, SpeakerVerificationService
from app.pipeline.vad_interface import VADDecision, VADInterface
from app.pipeline.validator import AudioChunkValidator, ValidationResult


# ──────────────────────────────────────────────────────────
# Latency Profiler
# ──────────────────────────────────────────────────────────

@dataclass
class LatencyProfile:
    """Fine-grained latency measurements for a single pipeline cycle."""
    capture_ts: float = 0.0       # timestamp when chunk arrived at WebSocket
    preprocess_ms: float = 0.0
    vad_ms: float = 0.0
    deepfake_ms: float = 0.0
    speaker_ms: float = 0.0
    liveness_ms: float = 0.0
    risk_engine_ms: float = 0.0
    smoothing_ms: float = 0.0
    total_inference_ms: float = 0.0
    end_to_end_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "preprocess_ms": round(self.preprocess_ms, 2),
            "vad_ms": round(self.vad_ms, 2),
            "deepfake_ms": round(self.deepfake_ms, 2),
            "speaker_ms": round(self.speaker_ms, 2),
            "liveness_ms": round(self.liveness_ms, 2),
            "risk_engine_ms": round(self.risk_engine_ms, 2),
            "smoothing_ms": round(self.smoothing_ms, 2),
            "total_inference_ms": round(self.total_inference_ms, 2),
            "end_to_end_ms": round(self.end_to_end_ms, 2),
        }


@dataclass
class PipelineMetrics:
    """Aggregate pipeline health metrics for dashboard."""
    queue_depth: int = 0
    dropped_chunks: int = 0
    total_chunks_processed: int = 0
    total_windows_inferred: int = 0
    avg_end_to_end_ms: float = 0.0
    avg_inference_ms: float = 0.0
    peak_end_to_end_ms: float = 0.0
    peak_inference_ms: float = 0.0
    is_gpu_enabled: bool = False
    device_name: str = "cpu"

    def to_dict(self) -> dict:
        return {
            "queue_depth": self.queue_depth,
            "dropped_chunks": self.dropped_chunks,
            "total_chunks_processed": self.total_chunks_processed,
            "total_windows_inferred": self.total_windows_inferred,
            "avg_end_to_end_ms": round(self.avg_end_to_end_ms, 2),
            "avg_inference_ms": round(self.avg_inference_ms, 2),
            "peak_end_to_end_ms": round(self.peak_end_to_end_ms, 2),
            "peak_inference_ms": round(self.peak_inference_ms, 2),
            "is_gpu_enabled": self.is_gpu_enabled,
            "device_name": self.device_name,
        }


# ──────────────────────────────────────────────────────────
# Temporal EMA Result Smoother
# ──────────────────────────────────────────────────────────

class ResultSmoother:
    """
    Exponential Moving Average filter to prevent flickering on consecutive windows.
    smoothed_val = alpha * new_val + (1 - alpha) * prev_val
    """

    def __init__(self, alpha: float = 0.35):
        self.alpha = max(0.01, min(1.0, alpha))
        self._state: Dict[str, float] = {}

    def smooth(self, key: str, value: float) -> float:
        if key not in self._state:
            self._state[key] = value
        else:
            self._state[key] = self.alpha * value + (1.0 - self.alpha) * self._state[key]
        return self._state[key]

    def get(self, key: str, default: float = 0.0) -> float:
        return self._state.get(key, default)

    def reset(self) -> None:
        self._state.clear()


# ──────────────────────────────────────────────────────────
# Async Inference Pipeline
# ──────────────────────────────────────────────────────────

class AsyncInferencePipeline:
    """
    Non-blocking producer-consumer pipeline for streaming voice security analysis.

    Stages:
    ┌──────────┐    ┌─────────────┐    ┌─────────────┐    ┌──────────────┐    ┌──────────────┐
    │ WebSocket │--->│ Preprocessor│--->│ ML Inference │--->│ Risk Engine  │--->│ Result Stream│
    │ Receive   │    │ Worker      │    │ Worker       │    │ Worker       │    │ Worker       │
    └──────────┘    └─────────────┘    └─────────────┘    └──────────────┘    └──────────────┘
       raw_queue      window_queue      inference_queue     telemetry_queue
    """

    def __init__(
        self,
        session_id: str,
        sample_rate: int = 16000,
        window_seconds: float = 2.0,
        overlap_ratio: float = 0.50,
        claimed_speaker_id: Optional[str] = None,
        queue_size: Optional[int] = None,
        batch_size: Optional[int] = None,
        smoothing_alpha: Optional[float] = None,
    ):
        self.session_id = session_id
        self.sample_rate = sample_rate
        self.window_seconds = window_seconds
        self.overlap_ratio = overlap_ratio
        self.claimed_speaker_id = claimed_speaker_id
        self.created_at = time.time()

        qs = queue_size or getattr(settings, "ASYNC_PIPELINE_QUEUE_SIZE", 50)
        self.batch_size = batch_size or getattr(settings, "INFERENCE_BATCH_SIZE", 4)
        alpha = smoothing_alpha or getattr(settings, "RESULT_SMOOTHING_ALPHA", 0.35)

        # Bounded async queues with backpressure
        self.raw_queue: asyncio.Queue = asyncio.Queue(maxsize=qs)
        self.window_queue: asyncio.Queue = asyncio.Queue(maxsize=qs)
        self.inference_queue: asyncio.Queue = asyncio.Queue(maxsize=qs)
        self.telemetry_queue: asyncio.Queue = asyncio.Queue(maxsize=qs)

        # Audio components (reuse persistent singletons)
        self.validator = AudioChunkValidator(expected_sample_rate=sample_rate)
        self.buffer = AudioBuffer(
            sample_rate=sample_rate,
            window_seconds=window_seconds,
            overlap_ratio=overlap_ratio,
        )
        self.vad: VADInterface = SileroStreamingVAD(
            speech_threshold=getattr(settings, "VAD_SPEECH_THRESHOLD", 0.50),
            min_speech_duration_ms=getattr(settings, "VAD_MIN_SPEECH_DURATION_MS", 250),
            min_silence_duration_ms=getattr(settings, "VAD_MIN_SILENCE_DURATION_MS", 300),
            speech_pad_ms=getattr(settings, "VAD_SPEECH_PAD_MS", 150),
            sample_rate=sample_rate,
        )
        self.deepfake_detector: DeepfakeDetector = DeepfakeModelRegistry.get_detector()
        self.speaker_verifier = SpeakerVerificationService()
        self.liveness_detector = AcousticLivenessDetector(sample_rate=sample_rate)
        self.risk_engine = MultiFactorRiskEngine()
        self.smoother = ResultSmoother(alpha=alpha)

        # Metrics tracking
        self._dropped_chunks = 0
        self._total_processed = 0
        self._total_inferred = 0
        self._latency_history: Deque[LatencyProfile] = deque(maxlen=100)
        self._lock = threading.Lock()

        # Duplicate window suppression (hash of last N windows)
        self._recent_window_hashes: Deque[int] = deque(maxlen=20)

        # Latest state for telemetry snapshot
        self._last_vad: Optional[VADDecision] = None
        self._last_deepfake: Optional[DetectionResult] = None
        self._last_speaker: Optional[SpeakerVerificationResult] = None
        self._last_risk: Optional[RiskEvaluationResult] = None
        self._last_latency: Optional[LatencyProfile] = None
        self._audio_state = "IDLE"
        self._connection_state = "CONNECTED"
        self._contextual_signals: List[str] = []
        self._conversational_risk_score: int = 0
        self._last_transcript: str = ""

        # Worker tasks
        self._tasks: List[asyncio.Task] = []
        self._running = False

    def add_contextual_signal(self, signal: str, transcript: Optional[str] = None, conv_risk: int = 0) -> None:
        """Injects linguistic scam/fraud intent from spoken speech into the streaming risk engine."""
        with self._lock:
            if signal and signal not in self._contextual_signals:
                self._contextual_signals.append(signal)
            if conv_risk > self._conversational_risk_score:
                self._conversational_risk_score = conv_risk
            if transcript:
                self._last_transcript = transcript
            logger.info(f"Session {self.session_id} received contextual signal: {signal} (Conv Risk: {conv_risk})")

    async def start(self) -> None:
        """Launch background workers."""
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._preprocessing_worker()),
            asyncio.create_task(self._ml_inference_worker()),
            asyncio.create_task(self._risk_engine_worker()),
        ]
        logger.info(f"AsyncPipeline started for session {self.session_id} ({len(self._tasks)} workers)")

    async def stop(self) -> None:
        """Gracefully stop all workers."""
        self._running = False
        self._connection_state = "DISCONNECTED"
        self._audio_state = "IDLE"
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        self.buffer.reset()
        self.vad.reset()
        self.smoother.reset()
        self._recent_window_hashes.clear()
        logger.info(f"AsyncPipeline stopped for session {self.session_id}")

    def enqueue_raw(self, raw_data: Union[bytes, str, dict]) -> bool:
        """
        Non-blocking enqueue of a raw audio packet.
        Returns False and increments dropped_chunks if the queue is full.
        """
        try:
            self.raw_queue.put_nowait((raw_data, time.perf_counter()))
            return True
        except asyncio.QueueFull:
            # Backpressure: drop_oldest policy
            drop_policy = getattr(settings, "DROP_POLICY", "drop_oldest")
            if drop_policy == "drop_oldest":
                try:
                    self.raw_queue.get_nowait()  # discard oldest
                except asyncio.QueueEmpty:
                    pass
                try:
                    self.raw_queue.put_nowait((raw_data, time.perf_counter()))
                except asyncio.QueueFull:
                    pass
            with self._lock:
                self._dropped_chunks += 1
            return False

    def get_latest_telemetry(self) -> Optional[dict]:
        """Non-blocking poll for the latest telemetry event."""
        try:
            return self.telemetry_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def get_pipeline_metrics(self) -> PipelineMetrics:
        """Current aggregate pipeline health."""
        device_info = DeviceManager.get_info()
        with self._lock:
            latencies = list(self._latency_history)
            e2e = [lp.end_to_end_ms for lp in latencies] if latencies else [0.0]
            inf = [lp.total_inference_ms for lp in latencies] if latencies else [0.0]
            return PipelineMetrics(
                queue_depth=self.raw_queue.qsize() + self.window_queue.qsize(),
                dropped_chunks=self._dropped_chunks,
                total_chunks_processed=self._total_processed,
                total_windows_inferred=self._total_inferred,
                avg_end_to_end_ms=sum(e2e) / len(e2e),
                avg_inference_ms=sum(inf) / len(inf),
                peak_end_to_end_ms=max(e2e),
                peak_inference_ms=max(inf),
                is_gpu_enabled=device_info.gpu_enabled,
                device_name=device_info.device_name,
            )

    # ──────────────── Stage 1: Preprocessing Worker ────────────────

    async def _preprocessing_worker(self) -> None:
        """Validates, buffers, and slices overlapping analysis windows."""
        while self._running:
            try:
                raw_data, capture_ts = await asyncio.wait_for(
                    self.raw_queue.get(), timeout=0.5
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                continue

            t0 = time.perf_counter()

            val_res: ValidationResult = self.validator.validate_raw(raw_data)
            if not val_res.is_valid:
                continue

            samples = val_res.samples_float32
            ready_windows = self.buffer.insert_chunk(val_res.chunk, samples)
            vad_decision = self.vad.is_speech(samples, sample_rate=self.sample_rate)
            self._last_vad = vad_decision

            if vad_decision.is_speech:
                self._audio_state = "RECEIVING"
            else:
                self._audio_state = "SILENCE"

            preprocess_ms = (time.perf_counter() - t0) * 1000.0

            with self._lock:
                self._total_processed += 1

            # Emit speech windows (with duplicate suppression)
            if ready_windows and vad_decision.is_speech:
                for win in ready_windows:
                    win_hash = hash(win.tobytes()[:256])
                    if win_hash in self._recent_window_hashes:
                        continue
                    self._recent_window_hashes.append(win_hash)

                    try:
                        self.window_queue.put_nowait({
                            "window": win,
                            "capture_ts": capture_ts,
                            "preprocess_ms": preprocess_ms,
                            "vad_decision": vad_decision,
                        })
                    except asyncio.QueueFull:
                        try:
                            self.window_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        try:
                            self.window_queue.put_nowait({
                                "window": win,
                                "capture_ts": capture_ts,
                                "preprocess_ms": preprocess_ms,
                                "vad_decision": vad_decision,
                            })
                        except asyncio.QueueFull:
                            pass
            elif not vad_decision.is_speech:
                # Emit silence telemetry (no ML inference)
                self._emit_silence_telemetry(preprocess_ms, capture_ts)

    # ──────────────── Stage 2: ML Inference Worker ────────────────

    async def _ml_inference_worker(self) -> None:
        """Runs micro-batched inference across all ML models on active speech windows."""
        while self._running:
            try:
                item = await asyncio.wait_for(
                    self.window_queue.get(), timeout=0.5
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                continue

            window = item["window"]
            capture_ts = item["capture_ts"]
            preprocess_ms = item["preprocess_ms"]
            vad_decision = item["vad_decision"]

            profile = LatencyProfile(capture_ts=capture_ts, preprocess_ms=preprocess_ms)
            profile.vad_ms = vad_decision.latency_ms

            # Deepfake inference
            t1 = time.perf_counter()
            df_result = self.deepfake_detector.predict(window)
            profile.deepfake_ms = (time.perf_counter() - t1) * 1000.0
            self._last_deepfake = df_result

            # Speaker verification
            t2 = time.perf_counter()
            spk_result = None
            try:
                spk_result = self.speaker_verifier.verify_sync(
                    window, claimed_speaker_id=self.claimed_speaker_id
                )
                self._last_speaker = spk_result
            except Exception as e:
                logger.debug(f"Speaker verification skipped: {e}")
            profile.speaker_ms = (time.perf_counter() - t2) * 1000.0

            # Acoustic liveness
            t3 = time.perf_counter()
            try:
                window_tensor = torch.from_numpy(window).unsqueeze(0).float()
                liveness_res = self.liveness_detector.evaluate(window_tensor)
                liveness_score = round(1.0 - liveness_res.replay_probability, 3)
            except Exception:
                liveness_score = 1.0
            profile.liveness_ms = (time.perf_counter() - t3) * 1000.0

            profile.total_inference_ms = profile.vad_ms + profile.deepfake_ms + profile.speaker_ms + profile.liveness_ms

            with self._lock:
                self._total_inferred += 1

            try:
                self.inference_queue.put_nowait({
                    "profile": profile,
                    "df_result": df_result,
                    "spk_result": spk_result,
                    "liveness_score": liveness_score,
                    "vad_decision": vad_decision,
                })
            except asyncio.QueueFull:
                try:
                    self.inference_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self.inference_queue.put_nowait({
                        "profile": profile,
                        "df_result": df_result,
                        "spk_result": spk_result,
                        "liveness_score": liveness_score,
                        "vad_decision": vad_decision,
                    })
                except asyncio.QueueFull:
                    pass

    # ──────────────── Stage 3: Risk Engine Worker ────────────────

    async def _risk_engine_worker(self) -> None:
        """Applies multi-signal synthesis, EMA smoothing, and emits risk verdicts."""
        while self._running:
            try:
                item = await asyncio.wait_for(
                    self.inference_queue.get(), timeout=0.5
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                continue

            t0 = time.perf_counter()
            profile: LatencyProfile = item["profile"]
            df_result: DetectionResult = item["df_result"]
            spk_result: Optional[SpeakerVerificationResult] = item["spk_result"]
            liveness_score: float = item["liveness_score"]
            vad_decision: VADDecision = item["vad_decision"]

            # EMA smoothing on key signals
            t_smooth = time.perf_counter()
            smoothed_spoof = self.smoother.smooth("spoof_prob", df_result.spoof_probability)
            smoothed_liveness = self.smoother.smooth("liveness", liveness_score)
            smoothed_confidence = self.smoother.smooth("confidence", df_result.confidence)
            profile.smoothing_ms = (time.perf_counter() - t_smooth) * 1000.0

            # Build risk input with smoothed values
            spk_sim = None
            if spk_result and self.claimed_speaker_id:
                spk_sim = spk_result.similarity

            audio_qual = 1.0
            if vad_decision:
                audio_qual = min(1.0, max(0.2, (vad_decision.rms_db + 60.0) / 60.0))

            with self._lock:
                active_context = list(self._contextual_signals)
                conv_score = self._conversational_risk_score
                last_trans = self._last_transcript

            risk_input = RiskEngineInput(
                deepfake_probability=smoothed_spoof,
                speaker_similarity=spk_sim,
                liveness_score=smoothed_liveness,
                caller_verified=True,
                audio_quality=round(audio_qual, 3),
                model_confidence=smoothed_confidence,
                contextual_signals=active_context,
            )
            risk_result = self.risk_engine.evaluate_risk(risk_input)

            # Elevate composite risk if conversational scam/fraud intent is detected
            if conv_score > risk_result.risk_score:
                elevated_score = max(risk_result.risk_score, conv_score)
                elevated_level = "CRITICAL" if elevated_score >= 80 else ("HIGH" if elevated_score >= 50 else ("MEDIUM" if elevated_score >= 30 else "LOW"))
                elevated_action = "BLOCK" if elevated_score >= 80 else ("WARN" if elevated_score >= 50 else ("CHALLENGE" if elevated_score >= 30 else "ALLOW"))
                expl_prefix = f"Linguistic Threat ({', '.join(active_context)}): Spoken speech \"{last_trans}\"\n" if last_trans else ""
                risk_result = RiskEvaluationResult(
                    risk_score=elevated_score,
                    risk_level=elevated_level,
                    recommended_action=elevated_action,
                    confidence=max(risk_result.confidence, 0.95),
                    signals=list(set(risk_result.signals + active_context)),
                    contributing_signals=risk_result.contributing_signals + [f"Linguistic threat score: {conv_score}/100"],
                    explanation=expl_prefix + risk_result.explanation,
                )

            self._last_risk = risk_result

            profile.risk_engine_ms = (time.perf_counter() - t0) * 1000.0
            profile.end_to_end_ms = (time.perf_counter() - profile.capture_ts) * 1000.0
            self._last_latency = profile

            # Persist real-time detection event to database
            try:
                from app.db.detection_store import DetectionEvent, record_detection_event
                evt = DetectionEvent(
                    session_id=self.session_id,
                    transcript=self._last_transcript or None,
                    risk_score=risk_result.risk_score,
                    risk_level=risk_result.risk_level,
                    action=risk_result.action,
                    deepfake_score=round(df_result.spoof_probability, 3),
                    deepfake_label=df_result.label,
                    speaker_id=self.claimed_speaker_id,
                    speaker_similarity=spk_sim,
                    liveness_score=round(liveness_score, 3),
                    replay_probability=round(1.0 - liveness_score, 3),
                    confidence=risk_result.confidence,
                    signals=risk_result.signals,
                    contributing_signals=risk_result.contributing_signals,
                    explanation=risk_result.explanation,
                    metadata={
                        "source": "live_microphone_audio",
                        "audio_quality": round(audio_qual, 3),
                        "latency_ms": round(profile.end_to_end_ms, 2),
                    },
                )
                record_detection_event(evt)
            except Exception as e:
                logger.debug(f"Async pipeline DB save notice: {e}")

            # Emit full telemetry
            telemetry = self._build_full_telemetry(profile)
            try:
                self.telemetry_queue.put_nowait(telemetry)
            except asyncio.QueueFull:
                try:
                    self.telemetry_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self.telemetry_queue.put_nowait(telemetry)
                except asyncio.QueueFull:
                    pass

    # ──────────────── Telemetry Construction ────────────────

    def _emit_silence_telemetry(self, preprocess_ms: float, capture_ts: float) -> None:
        """Emit minimal telemetry when no speech is detected (skip ML inference)."""
        profile = LatencyProfile(
            capture_ts=capture_ts,
            preprocess_ms=preprocess_ms,
            end_to_end_ms=(time.perf_counter() - capture_ts) * 1000.0,
        )
        telemetry = self._build_full_telemetry(profile)
        try:
            self.telemetry_queue.put_nowait(telemetry)
        except asyncio.QueueFull:
            pass

    def _build_full_telemetry(self, profile: LatencyProfile) -> dict:
        """Construct the full dashboard telemetry payload."""
        buf_stats = self.buffer.get_stats()
        metrics = self.get_pipeline_metrics()
        device_info = DeviceManager.get_info()

        vad_info = {}
        if self._last_vad:
            vad_info = {
                "is_speech": self._last_vad.is_speech,
                "speech_probability": self._last_vad.speech_probability,
                "confidence": self._last_vad.speech_probability,
                "start_time": self._last_vad.start_time,
                "end_time": self._last_vad.end_time,
                "latency_ms": self._last_vad.latency_ms,
                "rms_db": self._last_vad.rms_db,
                "zero_crossing_rate": self._last_vad.zero_crossing_rate,
                "spectral_entropy": self._last_vad.spectral_entropy,
            }

        deepfake_info = {}
        if self._last_deepfake:
            deepfake_info = {
                "label": self._last_deepfake.label,
                "spoof_probability": self._last_deepfake.spoof_probability,
                "bonafide_probability": self._last_deepfake.bonafide_probability,
                "confidence": self._last_deepfake.confidence,
                "inference_latency_ms": self._last_deepfake.inference_latency_ms,
                "model_version": self._last_deepfake.model_version,
                "timeline": [],
            }
        else:
            deepfake_info = {
                "label": "uncertain", "spoof_probability": 0.0,
                "bonafide_probability": 0.0, "confidence": 0.0,
                "inference_latency_ms": 0.0, "model_version": "Vigil-WavLM-AASIST-v1.0",
                "timeline": [],
            }

        speaker_info = {}
        if self._last_speaker:
            speaker_info = {
                "speaker_id": self._last_speaker.speaker_id,
                "similarity": self._last_speaker.similarity,
                "match": self._last_speaker.match,
                "confidence": self._last_speaker.confidence,
                "latency_ms": self._last_speaker.latency_ms,
                "claimed_speaker_id": self.claimed_speaker_id,
            }
        else:
            speaker_info = {
                "speaker_id": "UNKNOWN", "similarity": 0.0,
                "match": False, "confidence": 0.0, "latency_ms": 0.0,
                "claimed_speaker_id": self.claimed_speaker_id,
            }

        risk_info = self._last_risk.to_dict() if self._last_risk else {
            "risk_score": 0, "risk_level": "LOW", "recommended_action": "ALLOW",
            "signals": [], "confidence": 1.0, "contributing_signals": [],
            "explanation": "",
        }

        return {
            "type": "TELEMETRY",
            "data": {
                "session_id": self.session_id,
                "connection_state": self._connection_state,
                "audio_state": self._audio_state,
                "sample_rate": self.sample_rate,
                "chunk_duration_ms": 0,
                "buffer_size_ms": buf_stats["current_buffer_ms"],
                "buffer_size_samples": buf_stats["current_buffer_samples"],
                "window_duration_seconds": self.window_seconds,
                "total_windows_generated": buf_stats.get("total_windows", 0),
                "total_speech_windows_sent": self._total_inferred,
                "total_silence_windows_suppressed": self._total_processed - self._total_inferred,
                "latency_ms": round(profile.end_to_end_ms, 2),
                "packets_received": buf_stats["packets_received"],
                "packets_dropped": buf_stats["packets_dropped"],
                "packets_reordered": buf_stats["packets_reordered"],
                "packets_duplicate": buf_stats["packets_duplicate"],
                "vad": vad_info,
                "deepfake": deepfake_info,
                "speaker": speaker_info,
                "risk": risk_info,
                "pipeline": {
                    "latency": profile.to_dict(),
                    "metrics": metrics.to_dict(),
                    "device": device_info.to_dict(),
                    "smoothing_alpha": self.smoother.alpha,
                },
                "error": None,
                "timestamp": int(time.time() * 1000),
            },
        }
