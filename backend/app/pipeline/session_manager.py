import time
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import torch
from app.core.config import settings
from app.core.logging import logger
from app.pipeline.audio_buffer import AudioBuffer
from app.pipeline.deepfake_detector import DeepfakeDetector, DeepfakeModelRegistry, DetectionResult
from app.pipeline.interfaces import LivenessResult
from app.pipeline.liveness import AcousticLivenessDetector
from app.pipeline.risk_engine import MultiFactorRiskEngine, RiskEngineInput, RiskEvaluationResult



from app.pipeline.silero_vad import SileroStreamingVAD
from app.pipeline.speaker_service import SpeakerVerificationResult, SpeakerVerificationService
from app.pipeline.vad_interface import VADDecision, VADInterface
from app.pipeline.validator import AudioChunkValidator, ValidationResult


class StreamingSessionManager:
    """
    Manages stateful streaming audio ingestion for an active client connection.
    Coordinates validation, jitter buffering, window slicing, Silero VAD,
    WavLM+AASIST voice cloning detection, ECAPA-TDNN speaker verification,
    silence gating, and real-time telemetry.
    """

    def __init__(
        self,
        session_id: str,
        sample_rate: int = 16000,
        window_seconds: float = 2.0,
        overlap_ratio: float = 0.50,
        vad_engine: Optional[VADInterface] = None,
        deepfake_detector: Optional[DeepfakeDetector] = None,
        speaker_verifier: Optional[SpeakerVerificationService] = None,
        claimed_speaker_id: Optional[str] = None,
        filter_silence_downstream: bool = True,
    ):
        self.session_id = session_id
        self.sample_rate = sample_rate
        self.window_seconds = window_seconds
        self.overlap_ratio = overlap_ratio
        self.claimed_speaker_id = claimed_speaker_id
        self.filter_silence_downstream = filter_silence_downstream

        self.validator = AudioChunkValidator(expected_sample_rate=sample_rate)
        self.buffer = AudioBuffer(
            sample_rate=sample_rate,
            window_seconds=window_seconds,
            overlap_ratio=overlap_ratio,
        )

        # Initialize SileroStreamingVAD with configurable settings
        self.vad = vad_engine or SileroStreamingVAD(
            speech_threshold=getattr(settings, "VAD_SPEECH_THRESHOLD", 0.50),
            min_speech_duration_ms=getattr(settings, "VAD_MIN_SPEECH_DURATION_MS", 250),
            min_silence_duration_ms=getattr(settings, "VAD_MIN_SILENCE_DURATION_MS", 300),
            speech_pad_ms=getattr(settings, "VAD_SPEECH_PAD_MS", 150),
            sample_rate=sample_rate,
        )

        # Initialize Deepfake Detector from singleton registry
        self.deepfake_detector = deepfake_detector or DeepfakeModelRegistry.get_detector()

        # Initialize Speaker Verification Service
        self.speaker_verifier = speaker_verifier or SpeakerVerificationService()

        # Initialize Liveness Detector & Multi-Signal Risk Engine
        self.liveness_detector = AcousticLivenessDetector(sample_rate=sample_rate)
        self.risk_engine = MultiFactorRiskEngine()

        # Telemetry & States
        self.created_at = time.time()
        self.last_packet_time = 0.0
        self.connection_state = "CONNECTED"
        self.audio_state = "IDLE"  # IDLE | SPEECH / RECEIVING | SILENCE
        self.last_chunk_duration_ms = 0.0
        self.last_latency_ms = 0.0
        self.last_vad_decision: Optional[VADDecision] = None
        self.last_deepfake_result: Optional[DetectionResult] = None
        self.last_speaker_result: Optional[SpeakerVerificationResult] = None
        self.last_liveness_result: Optional[LivenessResult] = None
        self.last_risk_result: Optional[RiskEvaluationResult] = None
        self.deepfake_timeline: List[Dict[str, Any]] = []

        self.total_windows_generated = 0
        self.total_speech_windows_sent = 0
        self.total_silence_windows_suppressed = 0

    def ingest_packet(self, raw_data: Union[bytes, str, dict]) -> Tuple[List[np.ndarray], dict]:
        """
        Processes an incoming raw audio packet.
        Returns:
            (ready_windows, telemetry_dict)
        Guaranteed to never raise an unhandled exception.
        Suppresses long silence windows from deepfake evaluation.
        """
        start_time = time.perf_counter()
        now = time.time()
        self.last_packet_time = now

        # 1. Validate packet
        val_res: ValidationResult = self.validator.validate_raw(raw_data)
        if not val_res.is_valid:
            logger.warning(
                f"Session {self.session_id} rejected invalid chunk: {val_res.error_message}",
                extra={"session_id": self.session_id},
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return [], self.get_telemetry(processing_latency_ms=elapsed_ms, error=val_res.error_message)

        chunk = val_res.chunk
        samples = val_res.samples_float32
        self.last_chunk_duration_ms = chunk.duration_ms

        # 2. Insert into Jitter AudioBuffer
        ready_windows = self.buffer.insert_chunk(chunk, samples)
        self.total_windows_generated += len(ready_windows)

        # 3. Streaming VAD evaluation on current audio samples
        self.last_vad_decision = self.vad.is_speech(samples, sample_rate=self.sample_rate)

        # 4. Update Audio State
        if self.last_vad_decision.is_speech:
            self.audio_state = "RECEIVING"
        else:
            self.audio_state = "SILENCE"

        # 5. Silence Filtering & Deepfake Evaluation:
        # Requirement 1: Do not send silence segments to deepfake model
        speech_count = len([w for w in ready_windows if self.last_vad_decision.is_speech])
        self.total_speech_windows_sent += speech_count
        should_process = ready_windows and (
            not self.filter_silence_downstream or (self.last_vad_decision and self.last_vad_decision.is_speech)
        )
        if should_process:
            latest_speech_window = ready_windows[-1]
            df_available = True
            spk_available = True
            df_prob = None
            conf = 1.0

            # 1. Evaluate newest active speech window with Deepfake Detector (Signal 1)
            try:
                if self.deepfake_detector:
                    df_res = self.deepfake_detector.predict(latest_speech_window)
                    self.last_deepfake_result = df_res
                    df_prob = df_res.spoof_probability
                    conf = df_res.confidence

                    # Timecode for timeline: MM:SS
                    elapsed_sec = int(now - self.created_at)
                    time_str = f"{int(elapsed_sec // 60):02d}:{int(elapsed_sec % 60):02d}"

                    # Timeline label mapping: BONAFIDE | SUSPICIOUS | SPOOF | UNCERTAIN
                    if df_res.label == "spoof":
                        display_label = "SPOOF"
                    elif df_res.spoof_probability >= 0.50:
                        display_label = "SUSPICIOUS"
                    elif df_res.label == "bonafide":
                        display_label = "BONAFIDE"
                    else:
                        display_label = "UNCERTAIN"

                    self.deepfake_timeline.append({
                        "time": time_str,
                        "label": display_label,
                        "spoof_probability": df_res.spoof_probability,
                        "bonafide_probability": df_res.bonafide_probability,
                        "confidence": df_res.confidence,
                        "latency_ms": df_res.inference_latency_ms,
                    })
                    if len(self.deepfake_timeline) > 20:
                        self.deepfake_timeline.pop(0)
                else:
                    df_available = False
            except Exception as e:
                logger.warning(f"Deepfake detector unavailable in session {self.session_id}: {e}")
                df_available = False

            # 2. Evaluate Speaker Verification (Signal 2 - Independent orthogonal biometric identity)
            spk_sim = None
            try:
                if self.speaker_verifier:
                    spk_res = self.speaker_verifier.verify_sync(
                        latest_speech_window, claimed_speaker_id=self.claimed_speaker_id
                    )
                    self.last_speaker_result = spk_res
                    if spk_res and (getattr(spk_res, "speaker_id", None) or getattr(spk_res, "claimed_speaker_id", None)):
                        spk_sim = spk_res.similarity
                else:
                    spk_available = False
            except Exception as e:
                logger.warning(f"Speaker verification error in session {self.session_id}: {e}")
                spk_available = False

            # 3. Evaluate Acoustic Liveness (Signal 3 - Physical vocal emission vs replay)
            try:
                window_tensor = torch.from_numpy(latest_speech_window).unsqueeze(0).float()
                liveness_res = self.liveness_detector.evaluate(window_tensor)
                self.last_liveness_result = liveness_res
                liveness_score = getattr(liveness_res, "liveness_score", round(1.0 - liveness_res.replay_probability, 3))
            except Exception as e:
                logger.warning(f"Liveness evaluation error in session {self.session_id}: {e}")
                liveness_score = 1.0

            # 4. Evaluate Multi-Signal Risk Engine (Phase 6 - Non-linear synthesis with graceful degradation)
            try:
                audio_qual = 1.0
                if self.last_vad_decision:
                    audio_qual = min(1.0, max(0.2, (self.last_vad_decision.rms_db + 60.0) / 60.0))

                risk_input = RiskEngineInput(
                    deepfake_probability=df_prob,
                    speaker_similarity=spk_sim,
                    liveness_score=liveness_score,
                    caller_verified=True,
                    audio_quality=round(audio_qual, 3),
                    model_confidence=conf if df_available else 0.50,
                    contextual_signals=[],
                    claimed_speaker_id=self.claimed_speaker_id,
                    deepfake_model_available=df_available,
                    speaker_model_available=spk_available,
                    session_id=self.session_id,
                )
                self.last_risk_result = self.risk_engine.evaluate_risk(risk_input)

                # Persist detection event into PostgreSQL / SQLite database
                try:
                    from app.db.detection_store import DetectionEvent, record_detection_event
                    replay_prob = self.last_liveness_result.replay_probability if self.last_liveness_result else round(1.0 - liveness_score, 3)
                    df_lbl = self.last_deepfake_result.label if self.last_deepfake_result else None
                    spk_id = self.last_speaker_result.speaker_id if self.last_speaker_result else self.claimed_speaker_id
                    evt = DetectionEvent(
                        session_id=self.session_id,
                        risk_score=self.last_risk_result.risk_score,
                        risk_level=self.last_risk_result.risk_level,
                        action=self.last_risk_result.action,
                        deepfake_score=df_prob,
                        deepfake_label=df_lbl,
                        speaker_id=spk_id,
                        speaker_similarity=spk_sim,
                        liveness_score=liveness_score,
                        replay_probability=replay_prob,
                        confidence=self.last_risk_result.confidence,
                        signals=self.last_risk_result.signals,
                        contributing_signals=self.last_risk_result.contributing_signals,
                        explanation=self.last_risk_result.explanation,
                        metadata={
                            "audio_quality": round(audio_qual, 3),
                        },
                    )
                    record_detection_event(evt)
                except Exception as db_err:
                    logger.debug(f"Detection event db persistence notice: {db_err}")
            except Exception as e:
                logger.warning(f"Risk evaluation error in session {self.session_id}: {e}")

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        self.last_latency_ms = elapsed_ms

        telemetry = self.get_telemetry(processing_latency_ms=elapsed_ms)
        return ready_windows, telemetry

    def get_telemetry(self, processing_latency_ms: float = 0.0, error: Optional[str] = None) -> dict:
        """Constructs live dashboard metrics with Phase 2 VAD, Phase 3 Deepfake, and Phase 5 Speaker details."""
        buf_stats = self.buffer.get_stats()
        vad_info = {}
        if self.last_vad_decision:
            vad_info = {
                "is_speech": self.last_vad_decision.is_speech,
                "speech_probability": self.last_vad_decision.speech_probability,
                "confidence": self.last_vad_decision.speech_probability,
                "start_time": self.last_vad_decision.start_time,
                "end_time": self.last_vad_decision.end_time,
                "latency_ms": self.last_vad_decision.latency_ms,
                "rms_db": self.last_vad_decision.rms_db,
                "zero_crossing_rate": self.last_vad_decision.zero_crossing_rate,
                "spectral_entropy": self.last_vad_decision.spectral_entropy,
            }

        deepfake_info = {}
        if self.last_deepfake_result:
            deepfake_info = {
                "label": self.last_deepfake_result.label,
                "spoof_probability": self.last_deepfake_result.spoof_probability,
                "bonafide_probability": self.last_deepfake_result.bonafide_probability,
                "confidence": self.last_deepfake_result.confidence,
                "inference_latency_ms": self.last_deepfake_result.inference_latency_ms,
                "model_version": self.last_deepfake_result.model_version,
                "timeline": list(self.deepfake_timeline),
            }
        else:
            deepfake_info = {
                "label": "uncertain",
                "spoof_probability": 0.0,
                "bonafide_probability": 0.0,
                "confidence": 0.0,
                "inference_latency_ms": 0.0,
                "model_version": "Vigil-WavLM-AASIST-v1.0",
                "timeline": list(self.deepfake_timeline),
            }

        speaker_info = {}
        if self.last_speaker_result:
            speaker_info = {
                "speaker_id": self.last_speaker_result.speaker_id,
                "similarity": self.last_speaker_result.similarity,
                "match": self.last_speaker_result.match,
                "confidence": self.last_speaker_result.confidence,
                "latency_ms": self.last_speaker_result.latency_ms,
                "claimed_speaker_id": self.claimed_speaker_id,
            }
        else:
            speaker_info = {
                "speaker_id": "UNKNOWN",
                "similarity": 0.0,
                "match": False,
                "confidence": 0.0,
                "latency_ms": 0.0,
                "claimed_speaker_id": self.claimed_speaker_id,
            }

        risk_info = {}
        if self.last_risk_result:
            risk_info = self.last_risk_result.to_dict()
        else:
            default_risk = RiskEvaluationResult(
                risk_score=0,
                risk_level="LOW",
                recommended_action="ALLOW",
                signals=[],
                confidence=1.0,
                contributing_signals=[],
            )
            risk_info = default_risk.to_dict()

        liveness_info = {}
        if self.last_liveness_result:
            liveness_info = {
                "liveness_score": self.last_liveness_result.liveness_score,
                "replay_probability": self.last_liveness_result.replay_probability,
                "confidence": self.last_liveness_result.confidence,
                "is_live_acoustic": self.last_liveness_result.is_live_acoustic,
                "signals": self.last_liveness_result.signals,
                "disclaimer": self.last_liveness_result.disclaimer,
                "timeline_svg": self.liveness_detector.get_timeline_visualization_svg(width=720, height=190),
            }

        return {
            "session_id": self.session_id,
            "connection_state": self.connection_state,
            "audio_state": self.audio_state,
            "sample_rate": self.sample_rate,
            "chunk_duration_ms": round(self.last_chunk_duration_ms, 1),
            "buffer_size_ms": buf_stats["current_buffer_ms"],
            "buffer_size_samples": buf_stats["current_buffer_samples"],
            "window_duration_seconds": self.window_seconds,
            "total_windows_generated": self.total_windows_generated,
            "total_speech_windows_sent": self.total_speech_windows_sent,
            "total_silence_windows_suppressed": self.total_silence_windows_suppressed,
            "latency_ms": round(processing_latency_ms or self.last_latency_ms, 2),
            "packets_received": buf_stats["packets_received"],
            "packets_dropped": buf_stats["packets_dropped"],
            "packets_reordered": buf_stats["packets_reordered"],
            "packets_duplicate": buf_stats["packets_duplicate"],
            "vad": vad_info,
            "deepfake": deepfake_info,
            "speaker": speaker_info,
            "liveness": liveness_info,
            "risk": risk_info,
            "error": error,
            "timestamp": int(time.time() * 1000),
        }

    def close(self) -> None:
        """Purges memory, resets VAD states, and closes session."""
        self.connection_state = "DISCONNECTED"
        self.audio_state = "IDLE"
        self.buffer.reset()
        if self.vad:
            self.vad.reset()
        self.deepfake_timeline.clear()
        self.last_deepfake_result = None
        self.last_speaker_result = None
        self.last_risk_result = None
        logger.info(f"Session {self.session_id} memory cleanly wiped.")
