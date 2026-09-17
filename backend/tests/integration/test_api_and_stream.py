import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.pipeline.orchestrator import StreamingPipelineOrchestrator
from tests.fixtures.audio_generator import float_to_pcm16_bytes, generate_synthetic_speech_mock

client = TestClient(app)


def test_health_endpoints():
    # 1. Test liveness probe
    live_resp = client.get("/api/v1/health/live")
    assert live_resp.status_code == 200
    assert live_resp.json()["status"] == "UP"

    # 2. Test readiness probe
    ready_resp = client.get("/api/v1/health/ready")
    assert ready_resp.status_code == 200
    assert ready_resp.json()["status"] == "READY"
    assert ready_resp.json()["sample_rate"] == 16000


def test_android_screening_endpoint():
    # 1. Normal safe call
    safe_payload = {
        "device_id": "test_android_device_001",
        "phone_number": "+919123456789",
        "caller_display_name": "Family Member",
        "stir_shaken_status": 1,
        "carrier_code": "404-45",
        "timestamp": 1726500000000,
    }
    resp = client.post("/api/v1/screening/evaluate", json=safe_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "ALLOW"
    assert data["risk_score"] < 0.50
    assert data["recommendations"]["reject_call"] is False

    # 2. High risk blacklisted / suspicious institution call
    spam_payload = {
        "device_id": "test_android_device_001",
        "phone_number": "+919876543210",
        "caller_display_name": "SBI Bank Security Customs Verification",
        "stir_shaken_status": 2,  # Failed STIR/SHAKEN
        "carrier_code": "404-45",
        "timestamp": 1726500000000,
    }
    resp_spam = client.post("/api/v1/screening/evaluate", json=spam_payload)
    assert resp_spam.status_code == 200
    data_spam = resp_spam.json()
    assert data_spam["action"] in ["WARN", "BLOCK"]
    assert data_spam["risk_score"] >= 0.70


def test_streaming_orchestrator_end_to_end():
    # Test streaming pipeline directly with 2 seconds of audio
    orchestrator = StreamingPipelineOrchestrator(session_id="test_integration_session")

    # Generate 2.0s of mock audio (1.5s window should be triggered)
    mock_audio = generate_synthetic_speech_mock(duration_seconds=2.0, inject_vocoder_artifacts=True)
    raw_pcm = float_to_pcm16_bytes(mock_audio)

    # Ingest in chunks of 500ms (16,000 bytes each)
    chunk_size = 16000
    all_verdicts = []

    for i in range(0, len(raw_pcm), chunk_size):
        chunk = raw_pcm[i : i + chunk_size]
        verdicts = orchestrator.process_pcm_bytes(chunk)
        all_verdicts.extend(verdicts)

    # We expect at least one verdict emitted
    assert len(all_verdicts) >= 1

    v = all_verdicts[0]
    assert v.decision in ["ALLOW", "WARN", "BLOCK", "CHALLENGE", "UNCERTAIN"]
    assert 0.0 <= v.composite_risk_score <= 1.0
    assert v.latency_metrics.total_pipeline_latency_ms > 0.0
    assert v.uncertainty.total_uncertainty > 0.0

    orchestrator.cleanup()
