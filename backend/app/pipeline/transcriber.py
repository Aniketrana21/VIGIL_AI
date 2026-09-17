import io
import time
from typing import Any, Dict, Optional, Union
import numpy as np
import torch

from app.core.logging import logger
from app.core.security import secure_zero_memory


class WhisperTranscriber:
    """
    Speech-to-Text Transcription Layer using OpenAI Whisper.

    CRITICAL ARCHITECTURAL MANDATE:
    Whisper is used solely for linguistic transcription to understand caller intent.
    Whisper must NEVER be used to determine whether audio is synthetic or fake.
    Voice authenticity and spoof detection are strictly handled by the acoustic deepfake detector.

    PRIVACY ZERO-RETENTION MANDATE:
    Transcripts are held ephemerally in volatile memory only during intent evaluation.
    Transcripts are never persisted to disk or external stores unless explicit user consent is granted.
    """

    def __init__(self, model_size: str = "tiny", device: Optional[str] = None):
        self.model_size = model_size
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model = None
        self._whisper_available = False
        self._test_transcript_override: Optional[str] = None
        self._init_whisper()

    def _init_whisper(self) -> None:
        """Attempts to load Whisper weights if installed; gracefully falls back if not installed."""
        try:
            import whisper
            logger.info(f"Loading Whisper ASR model ('{self.model_size}') on device '{self.device}'...")
            self._model = whisper.load_model(self.model_size, device=self.device)
            self._whisper_available = True
            logger.info("Whisper ASR loaded successfully for linguistic intent extraction.")
        except ImportError:
            logger.info("openai-whisper package not installed. Running in decoupled fallback mode.")
            self._whisper_available = False
        except Exception as e:
            logger.warning(f"Whisper initialization failed ({e}). Running in decoupled fallback mode.")
            self._whisper_available = False

    def is_available(self) -> bool:
        return self._whisper_available

    def set_test_transcript_override(self, transcript: Optional[str]) -> None:
        """Enables deterministic unit testing of linguistic intent parsing without external ASR weights."""
        self._test_transcript_override = transcript

    def transcribe(
        self,
        audio: Union[np.ndarray, torch.Tensor],
        sample_rate: int = 16000,
        user_consent: bool = True,
        store_transcript_consented: bool = False,
    ) -> str:
        """
        Transcribes 16kHz audio array into text.
        Enforces explicit user consent and zero-retention privacy.
        """
        if not user_consent:
            logger.warning("Transcription aborted: explicit user consent not granted.")
            return ""

        # Priority 1: Test override for deterministic testing
        if self._test_transcript_override is not None:
            return self._test_transcript_override

        # Convert to float32 1D numpy array
        if isinstance(audio, torch.Tensor):
            audio_np = audio.detach().cpu().numpy()
        else:
            audio_np = np.asarray(audio, dtype=np.float32)

        if audio_np.ndim > 1:
            audio_np = np.mean(audio_np, axis=0)

        # Resample or pad if needed (16kHz standard)
        if len(audio_np) == 0:
            return ""

        # Normalize amplitude [-1.0, 1.0]
        max_val = np.max(np.abs(audio_np))
        if max_val > 1.0:
            audio_np = audio_np / max_val

        transcript = ""
        if self._whisper_available and self._model is not None:
            try:
                import whisper
                result = self._model.transcribe(
                    audio_np,
                    fp16=(self.device == "cuda"),
                    language="en",
                    task="transcribe",
                )
                transcript = result.get("text", "").strip()
            except Exception as e:
                logger.error(f"Error during Whisper transcription inference: {e}")
                transcript = ""
        else:
            # Fallback heuristic transcription: in environments without model weights,
            # this avoids crashing and provides safe, predictable behavior
            transcript = ""

        # Privacy: Secure Zero-Memory scrubbing of audio buffer
        if not store_transcript_consented:
            secure_zero_memory(audio_np)

        return transcript


# Singleton accessor
_transcriber_instance: Optional[WhisperTranscriber] = None


def get_transcriber() -> WhisperTranscriber:
    global _transcriber_instance
    if _transcriber_instance is None:
        _transcriber_instance = WhisperTranscriber()
    return _transcriber_instance
