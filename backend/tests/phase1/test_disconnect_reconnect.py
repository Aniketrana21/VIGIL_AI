import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.pipeline.audio_chunk import AudioChunk
from tests.fixtures.audio_generator import float_to_pcm16_bytes, generate_sine_wave

client = TestClient(app)


def test_network_disconnect_and_reconnect():
    pcm = float_to_pcm16_bytes(generate_sine_wave(freq=440.0, duration_seconds=0.1, sample_rate=16000))
    chunk = AudioChunk(sequence_id=1, timestamp_ms=1000, sample_rate=16000, channels=1, pcm_bytes=pcm)

    # 1. First Connection
    with client.websocket_connect("/api/v1/stream/ingest") as ws1:
        init_resp = json.loads(ws1.receive_text())
        assert init_resp["type"] == "TELEMETRY"
        assert init_resp["data"]["connection_state"] == "CONNECTED"

        # Send audio chunk
        ws1.send_bytes(chunk.serializeBinary())
        telem_resp = json.loads(ws1.receive_text())
        assert telem_resp["data"]["packets_received"] == 1
        # Close / Disconnect
        ws1.close()

    # 2. Immediate Reconnect (Second Connection)
    with client.websocket_connect("/api/v1/stream/ingest") as ws2:
        init_resp2 = json.loads(ws2.receive_text())
        assert init_resp2["type"] == "TELEMETRY"
        # New fresh session initialized
        assert init_resp2["data"]["packets_received"] == 0
        assert init_resp2["data"]["connection_state"] == "CONNECTED"

        chunk2 = AudioChunk(sequence_id=1, timestamp_ms=2000, sample_rate=16000, channels=1, pcm_bytes=pcm)
        ws2.send_bytes(chunk2.serializeBinary())

        telem_resp2 = json.loads(ws2.receive_text())
        assert telem_resp2["data"]["packets_received"] == 1
        ws2.close()
