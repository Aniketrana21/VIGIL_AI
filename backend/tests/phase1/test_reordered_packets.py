import numpy as np
import pytest
from app.pipeline.audio_chunk import AudioChunk
from app.pipeline.session_manager import StreamingSessionManager
from tests.fixtures.audio_generator import float_to_pcm16_bytes, generate_sine_wave


def test_reordered_packets_resequencing():
    session = StreamingSessionManager(session_id="reorder_session", sample_rate=16000, window_seconds=2.0)

    # Generate 5 chunks of 200ms audio (3200 samples each)
    pcm_chunks = [
        float_to_pcm16_bytes(generate_sine_wave(freq=300.0 + i * 50, duration_seconds=0.2, sample_rate=16000))
        for i in range(6)
    ]

    # Transmit out-of-order: [1, 3, 2, 5, 4, 6]
    transmit_order = [1, 3, 2, 5, 4, 6]

    for seq in transmit_order:
        chunk = AudioChunk(
            sequence_id=seq,
            timestamp_ms=1000 + seq * 200,
            sample_rate=16000,
            channels=1,
            pcm_bytes=pcm_chunks[seq - 1],
        )
        session.ingest_packet(chunk.serializeBinary())

    stats = session.buffer.get_stats()

    # Verify reordering was detected
    assert stats["packets_reordered"] > 0
    assert stats["packets_received"] == 6
    # Resequencing successfully assembled all contiguous packets
    assert stats["last_sequence_id"] == 6

    session.close()
