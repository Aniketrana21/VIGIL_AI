import numpy as np
import pytest
from app.pipeline.audio_chunk import AudioChunk
from app.pipeline.session_manager import StreamingSessionManager
from tests.fixtures.audio_generator import float_to_pcm16_bytes


def test_silence_and_long_silence_handling():
    session = StreamingSessionManager(session_id="silence_session", sample_rate=16000, window_seconds=2.0)

    # 1. 100ms pure digital silence
    silence_pcm = float_to_pcm16_bytes(np.zeros(1600, dtype=np.float32))

    chunk = AudioChunk(sequence_id=1, timestamp_ms=1000, sample_rate=16000, channels=1, pcm_bytes=silence_pcm)
    _, telem = session.ingest_packet(chunk.serializeBinary())

    assert telem["audio_state"] == "SILENCE"
    assert telem["vad"]["is_speech"] is False
    assert telem["vad"]["rms_db"] < -50.0

    # 2. Long silence: simulate 30 consecutive silence packets (3 seconds)
    for seq in range(2, 32):
        c = AudioChunk(sequence_id=seq, timestamp_ms=1000 + seq * 100, sample_rate=16000, channels=1, pcm_bytes=silence_pcm)
        session.ingest_packet(c.serializeBinary())

    final_telem = session.get_telemetry()
    assert final_telem["audio_state"] == "SILENCE"
    assert final_telem["packets_received"] == 31
    assert final_telem["packets_dropped"] == 0

    session.close()
