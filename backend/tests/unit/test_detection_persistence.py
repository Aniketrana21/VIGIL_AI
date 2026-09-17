"""
Unit tests for Detection Events Database Persistence.
Verifies that voice deepfake detection, speaker verification, and multi-signal risk verdicts
are automatically persisted into PostgreSQL / SQLite database upon detection.
"""
import os
import pytest
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.db.detection_store import (
    DetectionEvent,
    SQLiteDetectionStore,
    get_detection_store,
    set_detection_store,
    record_detection_event,
)
from app.pipeline.session_manager import StreamingSessionManager


@pytest.fixture
def test_db_path(tmp_path):
    db_file = str(tmp_path / "test_detections.db")
    store = SQLiteDetectionStore(db_path=db_file)
    set_detection_store(store)
    yield store
    # Cleanup
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass


@pytest.fixture
def client(test_db_path):
    return TestClient(app)


class TestDetectionPersistence:

    @pytest.mark.asyncio
    async def test_store_and_retrieve_detection_event(self, test_db_path):
        """Verifies database insertion and query retrieval of detection events."""
        event = DetectionEvent(
            session_id="session-alpha-1234",
            risk_score=91,
            risk_level="CRITICAL",
            action="BLOCK",
            deepfake_score=0.94,
            deepfake_label="spoof",
            speaker_id="victim_alice",
            speaker_similarity=0.88,
            liveness_score=0.22,
            replay_probability=0.78,
            conversation_intent="OTP_REQUEST",
            conversation_risk=0.90,
            confidence=0.92,
            signals=["HIGH_SYNTHETIC_PROBABILITY", "TARGETED_CLONE_DETECTED"],
            contributing_signals=["Synthetic speech probability: 94%"],
            explanation="Critical synthetic voice clone attempting authentication fraud.",
            caller_id="+9198****10",
            metadata={"source": "pytest"},
        )

        success = await test_db_path.store_detection(event)
        assert success is True
        assert event.id is not None and event.id > 0

        # Retrieve records
        records = await test_db_path.get_detections(session_id="session-alpha-1234")
        assert len(records) == 1
        r = records[0]
        assert r.session_id == "session-alpha-1234"
        assert r.risk_score == 91
        assert r.risk_level == "CRITICAL"
        assert r.action == "BLOCK"
        assert r.deepfake_score == 0.94
        assert r.deepfake_label == "spoof"
        assert r.conversation_intent == "OTP_REQUEST"
        assert "HIGH_SYNTHETIC_PROBABILITY" in r.signals

    @pytest.mark.asyncio
    async def test_detection_statistics_aggregation(self, test_db_path):
        """Verifies aggregate counts across risk levels."""
        # Insert a critical blocked event
        await test_db_path.store_detection(DetectionEvent(
            session_id="s1", risk_score=95, risk_level="CRITICAL", action="BLOCK"
        ))
        # Insert a low allow event
        await test_db_path.store_detection(DetectionEvent(
            session_id="s2", risk_score=15, risk_level="LOW", action="ALLOW"
        ))
        # Insert a high warn event
        await test_db_path.store_detection(DetectionEvent(
            session_id="s3", risk_score=75, risk_level="HIGH", action="WARN"
        ))

        stats = await test_db_path.get_detection_stats()
        assert stats["total_detections"] == 3
        assert stats["critical_risk_count"] == 1
        assert stats["high_risk_count"] == 1
        assert stats["blocked_actions_count"] == 1

    @pytest.mark.asyncio
    async def test_streaming_session_automatically_persists_detection(self, test_db_path):
        """Verifies that live speech processing in session_manager automatically inserts records into database."""
        session = StreamingSessionManager(
            session_id="streaming-auto-db-test",
            sample_rate=16000,
            window_seconds=1.0,
            filter_silence_downstream=False,
            claimed_speaker_id="test_spk",
        )

        # Ingest 4 chunks of 500ms (8000 samples each = 16000 bytes)
        sample_rate = 16000
        for i in range(5):
            t = np.linspace(i * 0.5, (i + 1) * 0.5, 8000, endpoint=False)
            speech_signal = (0.5 * np.sin(2 * np.pi * 220 * t) + 0.3 * np.sin(2 * np.pi * 440 * t))
            pcm_bytes = (speech_signal * 32767).astype(np.int16).tobytes()
            session.ingest_packet(pcm_bytes)

        # Check that event entered the database
        records = await test_db_path.get_detections(session_id="streaming-auto-db-test")
        assert len(records) >= 1
        record = records[0]
        assert record.session_id == "streaming-auto-db-test"
        assert record.risk_score >= 0
        assert record.action in ["ALLOW", "MONITOR", "CHALLENGE", "WARN", "BLOCK"]
        assert record.explanation != ""

    def test_screening_rest_endpoint_persists_and_queries(self, client, test_db_path):
        """Verifies that the screening API endpoint records detections and exposes history."""
        headers = {"X-API-Key": settings.API_KEY}

        # 1. Trigger high-risk call screening
        req_payload = {
            "phone_number": "+919876543210",  # Blacklisted number
            "caller_display_name": "STATE BANK SUPPORT",
            "device_id": "android-pixel-test-01",
            "stir_shaken_status": 2,  # Failed cryptographic validation
            "timestamp": 1726500000,
        }
        res = client.post("/api/v1/screening/evaluate", json=req_payload, headers=headers)
        assert res.status_code == 200
        assert res.json()["action"] == "BLOCK"

        # 2. Query detections from database
        res_list = client.get("/api/v1/screening/detections?session_id=android-pixel-test-01", headers=headers)
        assert res_list.status_code == 200
        data = res_list.json()
        assert data["count"] >= 1
        assert data["detections"][0]["action"] == "BLOCK"

        # 3. Query stats
        res_stats = client.get("/api/v1/screening/stats", headers=headers)
        assert res_stats.status_code == 200
        stats = res_stats.json()
        assert stats["total_detections"] >= 1
        assert stats["blocked_actions_count"] >= 1
