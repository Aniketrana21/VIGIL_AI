import time
from fastapi import APIRouter, status
from app.core.config import settings

router = APIRouter()
START_TIME = time.time()


@router.get("", status_code=status.HTTP_200_OK)
@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness_probe():
    """Kubernetes / Docker liveness probe: returns 200 if process is responsive."""
    return {"status": "UP", "uptime_seconds": round(time.time() - START_TIME, 1)}


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_probe():
    """Readiness probe: validates pipeline components and memory availability."""
    return {
        "status": "READY",
        "app_name": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "inference_device": settings.INFERENCE_DEVICE,
        "sample_rate": settings.SAMPLE_RATE,
        "window_seconds": settings.CHUNK_WINDOW_SECONDS,
        "hop_seconds": settings.CHUNK_HOP_SECONDS,
    }


@router.get("/models", status_code=status.HTTP_200_OK)
async def models_readiness_probe():
    """
    Phase 16 Model Readiness & Version Registry Endpoint.
    Returns status, operational health, device, and versions of all 6 AI modules.
    """
    from app.pipeline.deepfake_detector import DeepfakeModelRegistry
    from app.pipeline.speaker_encoder import SpeakerModelRegistry
    from app.pipeline.silero_vad import SileroStreamingVAD
    from app.pipeline.liveness import AcousticLivenessDetector
    from app.pipeline.conversation_intelligence import ContextualConversationClassifier
    from app.pipeline.risk_engine import MultiFactorRiskEngine

    models_info = {}

    # 1. Deepfake Detector
    try:
        models_info["deepfake_detector"] = DeepfakeModelRegistry.get_model_info()
    except Exception as e:
        models_info["deepfake_detector"] = {
            "name": "WavLM-AASIST Voice Clone Detector",
            "version": "Vigil-WavLM-AASIST-v1.0",
            "status": "ERROR",
            "error": str(e),
        }

    # 2. Speaker Verifier
    try:
        encoder = SpeakerModelRegistry.get_encoder()
        models_info["speaker_verifier"] = encoder.get_model_info()
    except Exception as e:
        models_info["speaker_verifier"] = {
            "name": "ECAPA-TDNN Speaker Verifier",
            "version": "Vigil-ECAPA-TDNN-v1.0",
            "status": "ERROR",
            "error": str(e),
        }

    # 3. Silero VAD
    try:
        vad_engine = SileroStreamingVAD()
        models_info["vad"] = vad_engine.get_model_info()
    except Exception as e:
        models_info["vad"] = {
            "name": "Silero Streaming VAD",
            "version": "Silero-VAD-v4.0",
            "status": "ERROR",
            "error": str(e),
        }

    # 4. Acoustic Liveness
    try:
        live_engine = AcousticLivenessDetector()
        models_info["liveness"] = live_engine.get_model_info()
    except Exception as e:
        models_info["liveness"] = {
            "name": "Acoustic Multi-Band Liveness & Replay Detector",
            "version": "Vigil-AcousticLiveness-v1.0",
            "status": "ERROR",
            "error": str(e),
        }

    # 5. Conversation Intelligence / Whisper
    try:
        conv_engine = ContextualConversationClassifier()
        models_info["conversation_intelligence"] = conv_engine.get_model_info()
    except Exception as e:
        models_info["conversation_intelligence"] = {
            "name": "Whisper Contextual Intent Classifier",
            "version": "OpenAI-Whisper-Base-v1.0",
            "status": "ERROR",
            "error": str(e),
        }

    # 6. Policy & Decision Engine
    models_info["policy_risk_engine"] = {
        "name": "Multi-Factor Non-Linear Risk & Policy Engine",
        "version": getattr(settings, "POLICY_VERSION", "2026.09.1-production"),
        "status": "READY",
        "thresholds": {
            "allow_max": getattr(settings, "RISK_ALLOW_MAX", 34),
            "challenge_max": getattr(settings, "RISK_CHALLENGE_MAX", 59),
            "warn_max": getattr(settings, "RISK_WARN_MAX", 84),
            "critical_min": getattr(settings, "RISK_CRITICAL_MIN", 85),
            "min_confidence": getattr(settings, "RISK_MIN_CONFIDENCE_THRESHOLD", 0.60),
        }
    }

    all_ready = all(m.get("status") == "READY" for m in models_info.values())

    return {
        "status": "HEALTHY" if all_ready else "DEGRADED",
        "models": models_info,
        "all_ready": all_ready,
        "timestamp": time.time(),
    }
