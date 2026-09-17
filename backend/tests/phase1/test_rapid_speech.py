import time
import pytest
from app.pipeline.audio_chunk import AudioChunk
from app.pipeline.session_manager import StreamingSessionManager
from tests.fixtures.audio_generator import float_to_pcm16_bytes, generate_synthetic_speech_mock


def test_rapid_speech_burst_and_backpressure():
    # Configure buffer with max_buffer_samples = 1.5s (< 2.0s analysis window) to trigger backpressure
    session = StreamingSessionManager(session_id="burst_session", sample_rate=16000, window_seconds=2.0)
    session.buffer.max_buffer_samples = int(16000 * 1.5)

    # Generate 100ms chunks of active speech
    speech_pcm = float_to_pcm16_bytes(generate_synthetic_speech_mock(duration_seconds=0.1, sample_rate=16000))

    start_time = time.perf_counter()
    # Rapidly inject 60 packets (6 seconds of audio into a 2.5s buffer)
    for seq in range(1, 61):
        chunk = AudioChunk(
            sequence_id=seq,
            timestamp_ms=1000 + seq * 100,
            sample_rate=16000,
            channels=1,
            pcm_bytes=speech_pcm,
        )
        session.ingest_packet(chunk.serializeBinary())

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    stats = session.buffer.get_stats()

    # Backpressure must have triggered because 6s of audio exceeded the 2.5s max buffer
    assert stats["packets_dropped"] > 0
    assert stats["packets_received"] == 60
    # Buffer length in memory must be capped within max_buffer_samples
    assert stats["current_buffer_samples"] <= session.buffer.max_buffer_samples
    # Throughput test: 60 packets processed in under 500ms
    assert elapsed_ms < 500.0

    session.close()
