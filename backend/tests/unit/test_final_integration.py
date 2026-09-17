"""
Unit and Integration Tests for Phase 16: Final Integration.
Verifies:
1. Configurable architecture with zero hardcoded keys
2. Model version exposure on every ML component
3. Model readiness check endpoint (/api/v1/health/models)
4. Graceful degradation when deepfake or speaker models are offline
5. Low confidence safety guardrails (< 0.60) forcing CHALLENGE
6. Unique session ID propagation
7. Non-empty, transparent explanation on every risk verdict
8. Model microservice health and schema compliance
"""
import pytest
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.pipeline.deepfake_detector import DeepfakeModelRegistry, WavLMAASISTDetector
from app.pipeline.speaker_encoder import SpeakerModelRegistry, ECAPATDNNEncoder
from app.pipeline.silero_vad import SileroStreamingVAD
from app.pipeline.liveness import AcousticLivenessDetector
from app.pipeline.conversation_intelligence import ContextualConversationClassifier
from app.pipeline.risk_engine import MultiFactorRiskEngine, RiskEngineInput
from app.pipeline.session_manager import StreamingSessionManager
from app.model_service import app as model_service_app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def model_client():
    return TestClient(model_service_app)


class TestPhase16FinalIntegration:

    def test_every_model_exposes_version_and_metadata(self):
        """Requirement 4: Every ML model must expose a version."""
        # 1. Deepfake Detector
        df = DeepfakeModelRegistry.get_detector()
        df_info = df.get_model_info() if hasattr(df, "get_model_info") else DeepfakeModelRegistry.get_model_info()
        assert "version" in df_info
        assert "WavLM-AASIST" in df_info["version"] or "Vigil" in df_info["version"]
        assert df_info["status"] == "READY"

        # 2. Speaker Verifier
        spk = SpeakerModelRegistry.get_encoder()
        spk_info = spk.get_model_info()
        assert "version" in spk_info
        assert "ECAPA-TDNN" in spk_info["version"] or "Vigil" in spk_info["version"]
        assert spk_info["embedding_dim"] == 192

        # 3. Silero VAD
        vad = SileroStreamingVAD()
        vad_info = vad.get_model_info()
        assert "version" in vad_info
        assert "Silero-VAD" in vad_info["version"]

        # 4. Acoustic Liveness
        liveness = AcousticLivenessDetector()
        live_info = liveness.get_model_info()
        assert "version" in live_info
        assert "AcousticLiveness" in live_info["version"]

        # 5. Conversation Intelligence / Whisper
        conv = ContextualConversationClassifier()
        conv_info = conv.get_model_info()
        assert "version" in conv_info
        assert "Whisper" in conv_info["version"]

        # 6. Policy & Risk Engine
        engine = MultiFactorRiskEngine()
        assert hasattr(settings, "POLICY_VERSION")
        assert "2026.09" in settings.POLICY_VERSION

    def test_health_and_model_readiness_endpoints(self, client):
        """Requirements 7 & 8: Health endpoints and model readiness checks."""
        # Liveness probe
        res_live = client.get("/api/v1/health/live")
        assert res_live.status_code == 200
        assert res_live.json()["status"] == "UP"

        # Readiness probe
        res_ready = client.get("/api/v1/health/ready")
        assert res_ready.status_code == 200
        assert res_ready.json()["status"] == "READY"

        # Model readiness probe
        res_models = client.get("/api/v1/health/models")
        assert res_models.status_code == 200
        data = res_models.json()
        assert data["status"] in ["HEALTHY", "DEGRADED"]
        models = data["models"]
        assert "deepfake_detector" in models
        assert "speaker_verifier" in models
        assert "vad" in models
        assert "liveness" in models
        assert "conversation_intelligence" in models
        assert "policy_risk_engine" in models
        assert models["deepfake_detector"]["status"] == "READY"
        assert models["speaker_verifier"]["status"] == "READY"

    def test_graceful_degradation_when_deepfake_model_unavailable(self):
        """Requirement 9: If deepfake model unavailable, continue with reduced signals."""
        engine = MultiFactorRiskEngine()
        risk_input = RiskEngineInput(
            deepfake_probability=None,
            deepfake_model_available=False,
            speaker_similarity=0.92,
            liveness_score=0.95,
            caller_verified=True,
            audio_quality=0.90,
            model_confidence=0.80,
            contextual_signals=[],
        )

        res = engine.evaluate_risk(risk_input)
        assert res is not None
        assert "DEEPFAKE_MODEL_UNAVAILABLE" in res.signals
        assert any("degraded mode" in s.lower() for s in res.contributing_signals)
        # Should still reach a decisive, safe action without crashing
        assert res.action in ["ALLOW", "MONITOR", "CHALLENGE"]
        assert res.individual_scores["deepfake_score"] is None
        assert res.individual_scores["deepfake_model_available"] is False

    def test_graceful_degradation_when_speaker_model_unavailable(self):
        """Requirement 9: If speaker model unavailable, do not pretend identity was verified."""
        engine = MultiFactorRiskEngine()
        risk_input = RiskEngineInput(
            deepfake_probability=0.08,
            speaker_similarity=None,
            speaker_model_available=False,
            claimed_speaker_id="corporate_cfo_user",
            liveness_score=0.95,
            caller_verified=True,
            audio_quality=0.90,
            model_confidence=0.90,
            contextual_signals=[],
        )

        res = engine.evaluate_risk(risk_input)
        assert res is not None
        assert "SPEAKER_IDENTITY_UNVERIFIED" in res.signals
        # Security invariant: An unverified claimed identity must NEVER be allowed!
        assert res.action != "ALLOW"
        assert res.action in ["CHALLENGE", "MONITOR"]
        assert any("claimed identity NOT verified" in s for s in res.contributing_signals)

    def test_low_confidence_safeguard_forces_challenge(self):
        """Requirement 9: If confidence is low, CHALLENGE / VERIFY."""
        engine = MultiFactorRiskEngine()
        # Even with high synthetic probability, if confidence is low, do not blindly BLOCK
        risk_input = RiskEngineInput(
            deepfake_probability=0.92,
            speaker_similarity=0.20,
            liveness_score=0.85,
            caller_verified=True,
            audio_quality=0.80,
            model_confidence=0.42,  # Below 0.60 threshold
            contextual_signals=[],
        )

        res = engine.evaluate_risk(risk_input)
        assert "LOW_MODEL_CONFIDENCE" in res.signals
        assert res.action == "CHALLENGE"
        assert res.requires_human_verification is True

    def test_every_risk_decision_has_explanation(self):
        """Requirement 5: Every risk decision must have an explanation."""
        engine = MultiFactorRiskEngine()
        risk_input = RiskEngineInput(
            deepfake_probability=0.94,
            speaker_similarity=0.88,
            liveness_score=0.25,
            caller_verified=False,
            audio_quality=0.75,
            model_confidence=0.92,
            contextual_signals=["FINANCIAL_REQUEST"],
        )

        res = engine.evaluate_risk(risk_input)
        assert res.explanation != ""
        assert "VIGIL-AI Risk Score" in res.explanation
        assert "Contributing signals:" in res.explanation
        assert "Probabilistic ML assessment" in res.explanation
        assert "Recommended action:" in res.explanation

    def test_every_streaming_session_has_id(self):
        """Requirement 6: Every streaming session must have an ID."""
        session_id = "test-session-uuid-9999"
        session = StreamingSessionManager(session_id=session_id)
        assert session.session_id == session_id

        # Ingest nominal audio
        sample_rate = 16000
        chunk = (0.1 * np.random.randn(8000)).astype(np.float32)
        _, telemetry = session.ingest_packet(chunk.tobytes())

        assert telemetry["session_id"] == session_id
        assert "vad" in telemetry
        assert "deepfake" in telemetry
        assert "speaker" in telemetry
        assert "liveness" in telemetry
        assert "risk" in telemetry

    def test_configuration_and_no_hardcoded_keys(self):
        """Requirements 1, 2, 3: Everything configurable, no hardcoded keys."""
        assert hasattr(settings, "JWT_SECRET_KEY")
        assert hasattr(settings, "API_KEY")
        assert hasattr(settings, "BIOMETRIC_ENCRYPTION_KEY")
        assert hasattr(settings, "RATE_LIMIT_PER_MINUTE")
        assert hasattr(settings, "MAX_AUDIO_PAYLOAD_BYTES")
        assert hasattr(settings, "MODEL_SERVICE_URL")

        # Test production keys validator rejects default dev keys
        with pytest.raises(ValueError, match="Production security violation"):
            settings.check_production_keys(
                env="production",
                jwt_key="change-this-in-production",
                api_key="vigil-ai-hackathon-demo-key-2026",
            )

    def test_standalone_model_service_microservice(self, model_client):
        """Verifies dedicated model-service container endpoints."""
        # Health
        res = model_client.get("/health")
        assert res.status_code == 200
        assert res.json()["service"] == "vigil-model-service"

        # Models metadata
        res_models = model_client.get("/models")
        assert res_models.status_code == 200
        assert "deepfake_detector" in res_models.json()["models"]
        assert "speaker_verifier" in res_models.json()["models"]

        # Inference test
        dummy_samples = (0.05 * np.sin(np.linspace(0, 1.0, 16000))).tolist()
        res_pred = model_client.post(
            "/predict/deepfake",
            json={"audio_samples": dummy_samples, "sample_rate": 16000},
        )
        assert res_pred.status_code == 200
        assert "spoof_probability" in res_pred.json()
        assert "model_version" in res_pred.json()
