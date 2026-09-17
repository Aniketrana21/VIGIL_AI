"""
Unit tests for Phase 18: SIH Demonstration Mode.
Verifies all 5 deterministic SIH scenarios through the actual ML pipeline:
1. Scenario 1: Genuine speaker -> LOW RISK, ALLOW
2. Scenario 2: Synthetic voice clone -> HIGH synthetic probability, CHALLENGE/WARN
3. Scenario 3: Replay attack -> LOW liveness, HIGH replay probability, CHALLENGE
4. Scenario 4: Synthetic voice + financial OTP fraud -> CRITICAL risk, BLOCK
5. Scenario 5: Noisy/compressed genuine voice -> Reduced confidence, avoids false fake -> MONITOR/CHALLENGE
Zero faked metrics: All audio runs through WavLM-AASIST, ECAPA-TDNN, Liveness, and Risk Engine.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.db.detection_store import SQLiteDetectionStore, set_detection_store
from app.demo.sih_scenarios import SIH_SCENARIOS, generate_scenario_audio


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "sih_demo_test.db")
    store = SQLiteDetectionStore(db_path=db_file)
    set_detection_store(store)
    return store


@pytest.fixture
def client(test_db):
    return TestClient(app)


class TestSIHDemoMode:

    def test_list_demo_scenarios(self, client):
        """Verifies scenario registry lists all 5 SIH scenarios with complete metadata."""
        res = client.get("/api/v1/demo/scenarios")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 5
        assert data["demo_mode"] is True
        scenarios = data["scenarios"]
        assert len(scenarios) == 5

        ids = [s["id"] for s in scenarios]
        assert sorted(ids) == [1, 2, 3, 4, 5]

        # Verify Scenario 1
        s1 = next(s for s in scenarios if s["id"] == 1)
        assert "Genuine Speaker" in s1["title"]
        assert s1["expected_action"] == "ALLOW"
        assert s1["expected_risk_level"] == "LOW"

        # Verify Scenario 4
        s4 = next(s for s in scenarios if s["id"] == 4)
        assert "Financial Fraud" in s4["title"]
        assert s4["expected_action"] == "BLOCK"
        assert s4["expected_risk_level"] == "CRITICAL"

    def test_scenario_1_genuine_speaker(self, client, test_db):
        """Scenario 1: Genuine speaker -> Expected: LOW RISK, ALLOW."""
        res = client.post("/api/v1/demo/run", json={"scenario_id": 1})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "SUCCESS"
        assert data["demo_mode"] is True

        metrics = data["metrics"]
        assert metrics["action"] == "ALLOW"
        assert metrics["risk_level"] == "LOW"
        assert metrics["risk_score"] < 35
        assert metrics["deepfake_probability"] <= 20
        assert metrics["liveness"] >= 70

        # Check database entry
        stored = test_db.get_detections_sync(session_id=data["session_id"])
        assert len(stored) >= 1
        assert stored[0].action == "ALLOW"
        assert stored[0].risk_level == "LOW"

    def test_scenario_2_synthetic_cloned_speech(self, client, test_db):
        """Scenario 2: Synthetic/cloned speech -> Expected: HIGH synthetic probability, CHALLENGE/WARN."""
        res = client.post("/api/v1/demo/run", json={"scenario_id": 2})
        assert res.status_code == 200
        data = res.json()

        metrics = data["metrics"]
        assert metrics["deepfake_probability"] >= 80
        assert metrics["action"] in ["WARN", "CHALLENGE"]
        assert metrics["risk_level"] in ["MEDIUM", "HIGH"]

        # Check database entry
        stored = test_db.get_detections_sync(session_id=data["session_id"])
        assert len(stored) >= 1
        assert stored[0].deepfake_score >= 0.80

    def test_scenario_3_replay_attack(self, client, test_db):
        """Scenario 3: Replay attack -> Expected: LOW liveness, HIGH replay probability, CHALLENGE."""
        res = client.post("/api/v1/demo/run", json={"scenario_id": 3})
        assert res.status_code == 200
        data = res.json()

        metrics = data["metrics"]
        assert metrics["liveness"] <= 35
        assert metrics["action"] == "CHALLENGE"

        # Check database entry
        stored = test_db.get_detections_sync(session_id=data["session_id"])
        assert len(stored) >= 1
        assert stored[0].replay_probability >= 0.65
        assert stored[0].action == "CHALLENGE"

    def test_scenario_4_synthetic_financial_fraud(self, client, test_db):
        """Scenario 4: Synthetic voice + financial request -> Expected: CRITICAL risk, BLOCK."""
        res = client.post("/api/v1/demo/run", json={"scenario_id": 4})
        assert res.status_code == 200
        data = res.json()

        metrics = data["metrics"]
        assert metrics["risk_score"] >= 85
        assert metrics["risk_level"] == "CRITICAL"
        assert metrics["action"] == "BLOCK"
        assert data["conversation"]["intent"] == "OTP_REQUEST"

        # Check database entry
        stored = test_db.get_detections_sync(session_id=data["session_id"])
        assert len(stored) >= 1
        assert stored[0].action == "BLOCK"
        assert stored[0].risk_level == "CRITICAL"

    def test_scenario_5_noisy_compressed_genuine_speech(self, client, test_db):
        """
        Scenario 5: Noisy/compressed genuine speech.
        Expected: Model confidence decreases but system should avoid falsely claiming it is synthetic.
        """
        res = client.post("/api/v1/demo/run", json={"scenario_id": 5})
        assert res.status_code == 200
        data = res.json()

        metrics = data["metrics"]
        assert metrics["deepfake_probability"] <= 45
        assert metrics["action"] != "BLOCK"  # NEVER false block genuine caller
        assert metrics["confidence"] <= 0.65  # Confidence correctly reflects degraded SNR

        # Check database entry
        stored = test_db.get_detections_sync(session_id=data["session_id"])
        assert len(stored) >= 1
        assert stored[0].deepfake_score <= 0.45
        assert stored[0].action != "BLOCK"
