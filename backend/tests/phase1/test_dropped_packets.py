import pytest
from app.pipeline.audio_chunk import AudioChunk
from app.pipeline.session_manager import StreamingSessionManager
from tests.fixtures.audio_generator import float_to_pcm16_bytes, generate_sine_wave


def test_dropped_packets_detection():
    session = StreamingSessionManager(session_id="dropped_packets_session", sample_rate=16000)

    # 100ms chunk (1600 samples = 3200 bytes)
    sample_pcm = float_to_pcm16_bytes(generate_sine_wave(freq=440.0, duration_seconds=0.1, sample_rate=16000))

    # Send packets 1, 2
    for seq in [1, 2]:
        chunk = AudioChunk(sequence_id=seq, timestamp_ms=1000 + seq * 100, sample_rate=16000, channels=1, pcm_bytes=sample_pcm)
        session.ingest_packet(chunk.serializeBinary())

    assert session.buffer.packets_received == 2
    assert session.buffer.packets_dropped == 0

    # Intentionally drop packets 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15 and send packet 20 (> resequence_window_size gap)
    chunk_jump = AudioChunk(sequence_id=20, timestamp_ms=3000, sample_rate=16000, channels=1, pcm_bytes=sample_pcm)
    _, telem = session.ingest_packet(chunk_jump.serializeBinary())

    # Verify dropped packets were registered
    assert telem["packets_dropped"] > 0
    assert telem["packets_received"] == 3

    session.close()
