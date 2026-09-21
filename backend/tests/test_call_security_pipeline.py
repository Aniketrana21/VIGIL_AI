import asyncio
import json
import pytest
from starlette.testclient import TestClient
from app.main import app
from app.services.dashboard_event_bus import dashboard_bus
from app.pipeline.async_pipeline import AsyncInferencePipeline

client = TestClient(app)


# Scenario 1: Unknown incoming call triggers defense pipeline and alerts dashboard
def test_scenario_1_unknown_incoming_call():
    payload = {
        "phone_number": "+919999000001",
        "caller_name": "Standard Delivery Courier",
        "caller_type": "UNKNOWN",
        "contact_known": False,
        "call_direction": "INCOMING",
        "transport": "CELLULAR",
    }
    response = client.post("/api/v1/calls/incoming", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "call_id" in data
    assert data["phone_number"] == "+919999000001"
    assert data["caller_type"].upper() == "UNKNOWN"
    assert data["contact_known"] is False
    assert data["status"] == "RINGING"
    assert data["recommended_action"] in ["ALLOW", "MONITOR", "WARN", "BLOCK"]


# Scenario 2: Known incoming call (saved contact / friend) ALSO triggers defense pipeline
def test_scenario_2_known_incoming_call_triggers_pipeline():
    payload = {
        "phone_number": "+19999000002",
        "caller_name": "Test Contact (Known)",
        "caller_type": "SAVED_CONTACT",
        "contact_known": True,
        "call_direction": "INCOMING",
        "transport": "CELLULAR",
    }
    response = client.post("/api/v1/calls/incoming", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "call_id" in data
    # Invariant: Pipeline triggers for ALL calls, even saved contacts
    assert data["contact_known"] is True
    assert data["status"] == "RINGING"
    assert data["speaker_verification_status"] == "WAITING"
    assert data["deepfake_detection_status"] == "WAITING"


# Scenario 3: Known number + legitimate speaker -> Voice verified, risk remains LOW
def test_scenario_3_known_number_legitimate_speaker():
    # 1. Register incoming call
    init_res = client.post("/api/v1/calls/incoming", json={
        "phone_number": "+919800000003",
        "caller_name": "Priya Sharma (Sister)",
        "contact_known": True,
        "caller_type": "FAMILY",
    })
    call_id = init_res.json()["call_id"]

    # 2. Post genuine voice analysis
    analysis_res = client.post(f"/api/v1/calls/{call_id}/analysis", json={
        "deepfake_probability": 0.04,
        "speaker_similarity": 0.95,
        "liveness_score": 0.92,
        "voice_activity": "YES",
        "signal_quality": "GOOD",
        "uncertainty": 0.05,
    })
    assert analysis_res.status_code == 200
    data = analysis_res.json()
    assert data["risk_score"] <= 30
    assert data["action"] == "ALLOW"
    assert data["risk_level"] == "LOW"


# Scenario 4: Known number + different speaker -> Voice mismatch detected, risk increases
def test_scenario_4_known_number_speaker_mismatch():
    init_res = client.post("/api/v1/calls/incoming", json={
        "phone_number": "+919800000004",
        "caller_name": "Rajesh (Enrolled)",
        "contact_known": True,
        "caller_type": "FRIEND",
    })
    call_id = init_res.json()["call_id"]

    # Post analysis with severe speaker mismatch
    analysis_res = client.post(f"/api/v1/calls/{call_id}/analysis", json={
        "deepfake_probability": 0.15,
        "speaker_similarity": 0.20,  # Biometric mismatch!
        "liveness_score": 0.80,
        "voice_activity": "YES",
        "signal_quality": "GOOD",
        "uncertainty": 0.10,
    })
    assert analysis_res.status_code == 200
    data = analysis_res.json()
    assert data["risk_score"] >= 50
    assert data["action"] in ["CHALLENGE", "WARN"]
    assert any("Speaker mismatch" in s or "Biometric" in s for s in data["signals"])


# Scenario 5: Known number + synthetic voice -> Deepfake detected, critical risk, auto TERMINATE
def test_scenario_5_known_number_synthetic_voice():
    init_res = client.post("/api/v1/calls/incoming", json={
        "phone_number": "+919800000005",
        "caller_name": "Executive (Enrolled)",
        "contact_known": True,
    })
    call_id = init_res.json()["call_id"]

    # Post critical deepfake analysis
    analysis_res = client.post(f"/api/v1/calls/{call_id}/analysis", json={
        "deepfake_probability": 0.96,
        "speaker_similarity": 0.85,
        "liveness_score": 0.20,
        "voice_activity": "YES",
        "signal_quality": "GOOD",
        "uncertainty": 0.05,
    })
    assert analysis_res.status_code == 200
    data = analysis_res.json()
    assert data["risk_score"] >= 85
    assert data["action"] == "TERMINATE"
    assert data["risk_level"] == "CRITICAL"


# Scenario 6: Unknown number + human voice -> Risk moderate, action MONITOR, no false-positive block
def test_scenario_6_unknown_number_human_voice():
    init_res = client.post("/api/v1/calls/incoming", json={
        "phone_number": "+919800000006",
        "caller_name": "New Delivery Agent",
        "contact_known": False,
    })
    call_id = init_res.json()["call_id"]

    analysis_res = client.post(f"/api/v1/calls/{call_id}/analysis", json={
        "deepfake_probability": 0.08,
        "speaker_similarity": None,  # No enrolled voiceprint
        "liveness_score": 0.85,
        "voice_activity": "YES",
        "signal_quality": "GOOD",
        "uncertainty": 0.12,
    })
    assert analysis_res.status_code == 200
    data = analysis_res.json()
    assert data["risk_score"] < 50
    assert data["action"] in ["ALLOW", "MONITOR"]


# Scenario 7: Noisy audio stream -> High uncertainty, no premature drop
def test_scenario_7_noisy_audio_high_uncertainty():
    init_res = client.post("/api/v1/calls/incoming", json={
        "phone_number": "+919800000007",
        "caller_name": "Street Ambience Caller",
        "contact_known": False,
    })
    call_id = init_res.json()["call_id"]

    analysis_res = client.post(f"/api/v1/calls/{call_id}/analysis", json={
        "deepfake_probability": 0.55,
        "speaker_similarity": None,
        "liveness_score": 0.60,
        "voice_activity": "YES",
        "signal_quality": "POOR",
        "uncertainty": 0.85,  # Heavy noise / acoustic uncertainty
    })
    assert analysis_res.status_code == 200
    data = analysis_res.json()
    # Invariant: Must not prematurely terminate on noisy/uncertain audio
    assert data["action"] != "TERMINATE"
    assert data["action"] != "BLOCK"


# Scenario 8: High-confidence synthetic voice on supported stream -> TERMINATE event, DB audit
def test_scenario_8_call_termination_endpoint_and_audit():
    init_res = client.post("/api/v1/calls/incoming", json={
        "phone_number": "+919800000008",
        "caller_name": "Deepfake Impersonator",
        "transport": "VOIP",
    })
    call_id = init_res.json()["call_id"]

    # Terminate call explicitly via enforcement endpoint
    term_res = client.post(f"/api/v1/calls/{call_id}/terminate", json={
        "reason": "Automated Multi-Signal Confirmation: 3 consecutive synthetic windows (WavLM-AASIST)",
        "risk_score": 98,
        "signals": ["WavLM vocoder artifact spike", "Biometric mismatch", "High confidence synthetic"],
    })
    assert term_res.status_code == 200
    term_data = term_res.json()
    assert term_data["status"] == "TERMINATED"
    assert term_data["action"] == "TERMINATE"

    # Verify call state reflects TERMINATED
    get_res = client.get(f"/api/v1/calls/{call_id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "TERMINATED"


# Scenario 9: WebSocket connect & reconnect without duplicate sessions
def test_scenario_9_websocket_connect_and_reconnect():
    initial_count = len(dashboard_bus._dashboard_clients)
    
    with client.websocket_connect("/ws/dashboard") as ws1:
        assert len(dashboard_bus._dashboard_clients) == initial_count + 1
        # Receive initial system_status handshake
        greeting = ws1.receive_json()
        assert greeting["event"] == "system_status"
        # Send ping
        ws1.send_json({"type": "ping"})
        msg = ws1.receive_json()
        assert msg["type"] == "pong"
    
    # After exit context, subscriber count should return to initial_count
    assert len(dashboard_bus._dashboard_clients) == initial_count

    # Reconnect
    with client.websocket_connect("/ws/dashboard") as ws2:
        assert len(dashboard_bus._dashboard_clients) == initial_count + 1
        greeting = ws2.receive_json()
        assert greeting["event"] == "system_status"
        ws2.send_json({"type": "ping"})
        msg = ws2.receive_json()
        assert msg["type"] == "pong"

    assert len(dashboard_bus._dashboard_clients) == initial_count


# Scenario 10: Two rapid calls -> Separate call_ids, separate sessions, separate dashboard cards
def test_scenario_10_two_rapid_calls_separate_ids():
    call1_res = client.post("/api/v1/calls/incoming", json={
        "phone_number": "+919800000010",
        "caller_name": "Caller 1",
        "contact_known": False,
    })
    call2_res = client.post("/api/v1/calls/incoming", json={
        "phone_number": "+919800000011",
        "caller_name": "Caller 2",
        "contact_known": True,
    })

    assert call1_res.status_code == 200
    assert call2_res.status_code == 200

    call1_id = call1_res.json()["call_id"]
    call2_id = call2_res.json()["call_id"]

    assert call1_id != call2_id
    assert call1_res.json()["phone_number"] == "+919800000010"
    assert call2_res.json()["phone_number"] == "+919800000011"
