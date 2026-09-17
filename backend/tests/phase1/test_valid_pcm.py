import numpy as np
import pytest
from app.pipeline.audio_chunk import AudioChunk
from app.pipeline.session_manager import StreamingSessionManager
from tests.fixtures.audio_generator import float_to_pcm16_bytes, generate_sine_wave


def test_valid_pcm_serialization_and_windowing():
    # 1. Generate 1.0s of valid 16kHz sine wave
    sine = generate_sine_wave(freq=440.0, duration_seconds=1.0, sample_rate=16000, amplitude=0.6)
    pcm_bytes = float_to_pcm16_bytes(sine)

    chunk = AudioChunk(
        sequence_id=1,
        timestamp_ms=1726500000000,
        sample_rate=16000,
        channels=1,
        pcm_bytes=pcm_bytes,
    )

    # 2. Verify binary pack and unpack
    packed = chunk.serializeBinary()
    unpacked, err = AudioChunk.deserialize_binary(packed)

    assert err is None
    assert unpacked is not None
    assert unpacked.sequence_id == 1
    assert unpacked.sample_rate == 16000
    assert unpacked.pcm_bytes == pcm_bytes
    assert unpacked.num_samples == 16000
    assert round(unpacked.duration_ms) == 1000

    # 3. Verify window generation in session (2.0s window with 50% overlap = 1.0s hop)
    session = StreamingSessionManager(session_id="valid_pcm_session", sample_rate=16000, window_seconds=2.0)

    # Chunk 1 (1.0s = 16,000 samples) -> Should not trigger 2.0s window yet
    windows1, telem1 = session.ingest_packet(packed)
    assert len(windows1) == 0
    assert telem1["packets_received"] == 1
    assert telem1["packets_dropped"] == 0

    # Chunk 2 (1.0s = 16,000 samples, total 32,000 samples) -> Triggers 2.0s window (32,000 samples)
    chunk2 = AudioChunk(sequence_id=2, timestamp_ms=1726500001000, sample_rate=16000, channels=1, pcm_bytes=pcm_bytes)
    windows2, telem2 = session.ingest_packet(chunk2.serializeBinary())

    assert len(windows2) == 1
    assert len(windows2[0]) == 32000  # Exactly 2 seconds at 16kHz
    assert telem2["packets_received"] == 2
    assert telem2["total_windows_generated"] == 1
    assert telem2["audio_state"] in ["RECEIVING", "SILENCE"]

    session.close()
