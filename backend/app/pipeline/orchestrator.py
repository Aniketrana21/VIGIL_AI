from typing import List, Optional, Union
import torch
from app.core.config import settings
from app.core.security import secure_zero_memory
from app.pipeline.antispoof import AntiSpoofModel
from app.pipeline.chunker import StreamingChunker
from app.pipeline.liveness import AcousticLivenessDetector
from app.pipeline.preprocessor import AudioPreprocessor
from app.pipeline.risk_engine import MultiFactorRiskEngine
from app.pipeline.speaker_verifier import ECAPASpeakerVerifier
from app.pipeline.vad import SileroVADDetector
from app.schemas.risk import RiskVerdict


class StreamingPipelineOrchestrator:
    """
    Coordinates the end-to-end streaming detection pipeline for an active session.
    Manages stateful sliding chunking, VAD, feature extraction, and risk decisions.
    """

    def __init__(
        self,
        session_id: str,
        target_speaker_embedding: Optional[torch.Tensor] = None,
        claimed_speaker_id: Optional[str] = None,
        context_telephony_risk: float = 0.0,
    ):
        self.session_id = session_id
        self.target_speaker_embedding = target_speaker_embedding
        self.claimed_speaker_id = claimed_speaker_id
        self.context_telephony_risk = context_telephony_risk

        # Pipeline modules
        self.preprocessor = AudioPreprocessor(target_sample_rate=settings.SAMPLE_RATE)
        self.vad = SileroVADDetector(confidence_threshold=settings.VAD_CONFIDENCE_THRESHOLD)
        self.chunker = StreamingChunker(
            sample_rate=settings.SAMPLE_RATE,
            window_seconds=settings.CHUNK_WINDOW_SECONDS,
            hop_seconds=settings.CHUNK_HOP_SECONDS,
        )
        self.antispoof = AntiSpoofModel(sample_rate=settings.SAMPLE_RATE)
        self.speaker_verifier = ECAPASpeakerVerifier(sample_rate=settings.SAMPLE_RATE)
        self.liveness = AcousticLivenessDetector(sample_rate=settings.SAMPLE_RATE)
        self.risk_engine = MultiFactorRiskEngine()

    def process_pcm_bytes(
        self,
        raw_pcm: Union[bytes, bytearray],
        source_sample_rate: int = 16000,
        source_channels: int = 1,
    ) -> List[RiskVerdict]:
        """
        Ingests a stream packet of raw PCM bytes and returns verdicts for all completed sliding windows.
        """
        # 1. Preprocess and resample to 16kHz float32
        prep_res = self.preprocessor.process_raw_bytes(
            raw_pcm,
            source_sample_rate=source_sample_rate,
            source_channels=source_channels,
        )

        # 2. Append normalized audio to sliding window ring buffer
        ready_windows = self.chunker.append_audio(prep_res.audio_tensor)
        verdicts: List[RiskVerdict] = []

        # 3. For each ready 1.5s window, execute the full analysis pipeline
        for window in ready_windows:
            # VAD analysis
            vad_res = self.vad.process_frame(window)

            # Requirement 1: Do not send silence segments to the deepfake model
            if not vad_res.is_speech:
                verdict = RiskVerdict(
                    decision=DecisionState.ALLOW,
                    composite_risk_score=0.0,
                    confidence=1.0,
                    total_uncertainty=0.0,
                    aleatoric_uncertainty=0.0,
                    epistemic_uncertainty=0.0,
                    explainability_reasons=["Silence detected: deepfake model evaluation bypassed"],
                    vad_probability=vad_res.speech_probability,
                    synthetic_probability=0.0,
                    replay_probability=0.0,
                    speaker_metrics=None,
                    latency_ms=round(prep_res.latency_ms + vad_res.latency_ms, 2),
                )
                verdicts.append(verdict)
                secure_zero_memory(window)
                continue

            # Anti-spoofing / deepfake artifact detection
            antispoof_res = self.antispoof.predict(window)

            # Acoustic liveness & replay detection
            liveness_res = self.liveness.evaluate(window)

            # Speaker verification (if target voiceprint enrolled)
            speaker_res = None
            if self.target_speaker_embedding is not None and self.claimed_speaker_id:
                speaker_res = self.speaker_verifier.verify(
                    audio_window=window,
                    enrolled_embedding=self.target_speaker_embedding,
                    claimed_speaker_id=self.claimed_speaker_id,
                )

            # Bayesian risk aggregation & policy decision
            verdict = self.risk_engine.evaluate(
                vad_res=vad_res,
                antispoof_res=antispoof_res,
                liveness_res=liveness_res,
                speaker_res=speaker_res,
                context_telephony_risk=self.context_telephony_risk,
                preprocessing_latency_ms=prep_res.latency_ms,
            )
            verdicts.append(verdict)

            # Enforce zero-retention memory hygiene on the window
            secure_zero_memory(window)

        return verdicts

    def cleanup(self) -> None:
        """Wipes internal buffers and resets state for privacy compliance."""
        self.chunker.reset()
        self.preprocessor.reset()
        self.vad.reset()
        self.antispoof.reset()
        self.speaker_verifier.reset()
        self.liveness.reset()
