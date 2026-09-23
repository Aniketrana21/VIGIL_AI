"""
VIGIL-AI Audio Processing Utilities.
Provides robust multi-format audio byte decoding (WAV, WEBM, OGG, MP3, AAC, FLAC, PCM).
"""
import io
from typing import Tuple
import numpy as np
import soundfile as sf

from app.core.logging import logger


def load_audio_bytes(content: bytes, target_sr: int = 16000) -> Tuple[np.ndarray, int]:
    """
    Decodes arbitrary audio file bytes into float32 mono NumPy array [-1.0, 1.0] and sample rate.
    Tries multiple decoders (soundfile, pydub, scipy, raw pcm fallback).
    """
    if not content:
        raise ValueError("Audio content buffer is empty.")

    # 1. Try SoundFile (handles standard WAV, FLAC, OGG, AIFF, etc.)
    try:
        with io.BytesIO(content) as f:
            data, sr = sf.read(f)
            if data.ndim > 1:
                data = np.mean(data, axis=1)
            audio_np = data.astype(np.float32)
            if len(audio_np) > 0:
                return audio_np, int(sr)
    except Exception as e_sf:
        logger.debug(f"SoundFile decode failed ({e_sf}). Trying PyDub fallback...")

    # 2. Try PyDub (handles WebM, MP3, AAC, OGG, M4A, etc.)
    try:
        from pydub import AudioSegment
        with io.BytesIO(content) as f:
            seg = AudioSegment.from_file(f)
            seg = seg.set_channels(1)
            sr = seg.frame_rate
            raw = seg.get_array_of_samples()
            data = np.array(raw, dtype=np.float32)
            # Normalize depending on sample width (8-bit, 16-bit, 24-bit, 32-bit)
            max_val = float(1 << (seg.sample_width * 8 - 1))
            if max_val > 0:
                data = data / max_val
            if len(data) > 0:
                return data, int(sr)
    except Exception as e_pydub:
        logger.debug(f"PyDub decode failed ({e_pydub}). Trying Raw PCM fallback...")

    # 3. Fallback: Parse as raw 16-bit LE PCM bytes
    try:
        audio_np = np.frombuffer(content, dtype=np.int16).astype(np.float32) / 32768.0
        if len(audio_np) > 0:
            return audio_np, target_sr
    except Exception as e_pcm:
        logger.error(f"Raw PCM parsing failed: {e_pcm}")

    raise ValueError("Unrecognized audio format: could not decode audio bytes.")
