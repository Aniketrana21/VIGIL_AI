import time
from dataclasses import dataclass
from typing import Optional, Tuple, Union
import numpy as np
from app.pipeline.audio_chunk import AudioChunk


@dataclass
class ValidationResult:
    is_valid: bool
    chunk: Optional[AudioChunk] = None
    error_message: Optional[str] = None
    samples_float32: Optional[np.ndarray] = None


class AudioChunkValidator:
    """
    Validates incoming audio chunks from network streams.
    Ensures backend resilience: Malformed or hostile packets are safely rejected
    without ever throwing unhandled exceptions or crashing the server.
    """

    def __init__(self, expected_sample_rate: int = 16000, max_chunk_duration_ms: float = 1000.0):
        self.expected_sample_rate = expected_sample_rate
        self.max_chunk_duration_ms = max_chunk_duration_ms
        self._raw_sequence_counter = 0

    def validate_raw(self, raw_input: Union[bytes, str, dict]) -> ValidationResult:
        """
        Ingests either raw binary bytes or parsed dictionary and executes full validation.
        """
        try:
            chunk: Optional[AudioChunk] = None
            err: Optional[str] = None

            if isinstance(raw_input, bytes):
                if raw_input.startswith(b"VIGI"):
                    chunk, err = AudioChunk.deserialize_binary(raw_input)
                    if err:
                        return ValidationResult(is_valid=False, error_message=err)
                elif len(raw_input) >= 28 and len(raw_input) <= 64:
                    # Packet size matches binary header, but magic header is missing/corrupt
                    return ValidationResult(is_valid=False, error_message="Corrupted binary header or bad magic")
                elif len(raw_input) >= 320 and len(raw_input) % 2 == 0:
                    # Valid raw PCM: at least 10ms (160 samples = 320 bytes) and 16-bit aligned
                    seq = self._raw_sequence_counter
                    self._raw_sequence_counter += 1
                    chunk = AudioChunk(
                        sequence_id=seq,
                        timestamp_ms=int(time.time() * 1000),
                        sample_rate=self.expected_sample_rate,
                        channels=1,
                        pcm_bytes=raw_input,
                    )
                    err = None
                else:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Invalid raw bytes length ({len(raw_input)}B) not aligned or too small for PCM",
                    )
            elif isinstance(raw_input, dict):
                chunk, err = AudioChunk.from_dict(raw_input)
            elif isinstance(raw_input, str):
                import json
                try:
                    d = json.loads(raw_input)
                    chunk, err = AudioChunk.from_dict(d)
                except Exception as e:
                    return ValidationResult(is_valid=False, error_message=f"JSON parse failure: {e}")
            else:
                return ValidationResult(is_valid=False, error_message=f"Unsupported raw input type: {type(raw_input)}")

            if chunk is None or err:
                return ValidationResult(is_valid=False, error_message=err or "Unknown parsing failure")

            # Validate sample rate
            if chunk.sample_rate != self.expected_sample_rate:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Sample rate {chunk.sample_rate}Hz != expected {self.expected_sample_rate}Hz",
                )

            # Validate byte alignment (16-bit PCM requires even number of bytes)
            if len(chunk.pcm_bytes) % 2 != 0:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"PCM byte length ({len(chunk.pcm_bytes)}) not aligned to 16-bit samples",
                )

            # Validate chunk duration limit (prevent client flooding with giant 100MB chunk)
            if chunk.duration_ms > self.max_chunk_duration_ms:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Chunk duration {chunk.duration_ms:.1f}ms exceeds maximum limit {self.max_chunk_duration_ms}ms",
                )

            # Safe conversion to float32 normalized [-1.0, 1.0]
            samples_int16 = np.frombuffer(chunk.pcm_bytes, dtype=np.int16)
            samples_float = samples_int16.astype(np.float32) / 32768.0

            # Guard against NaN / Inf values
            if not np.all(np.isfinite(samples_float)):
                return ValidationResult(
                    is_valid=False,
                    error_message="Audio samples contain non-finite numbers (NaN or Inf)",
                )

            return ValidationResult(
                is_valid=True,
                chunk=chunk,
                samples_float32=samples_float,
            )

        except Exception as e:
            # Catch-all to guarantee backend NEVER crashes on malformed audio
            return ValidationResult(
                is_valid=False,
                error_message=f"Unexpected validator exception: {str(e)}",
            )
