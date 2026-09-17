"""
VIGIL-AI: Dedicated ML Model Microservice.
Provides isolated, horizontally scalable model serving for WavLM-AASIST voice clone detection
and ECAPA-TDNN speaker verification.
"""
import base64
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import numpy as np

from app.core.config import settings
from app.core.logging import logger
from app.pipeline.deepfake_detector import DeepfakeModelRegistry
from app.pipeline.speaker_encoder import SpeakerModelRegistry

app = FastAPI(
    title="VIGIL-AI Model Serving Microservice",
    description="Standalone neural inference service for anti-spoofing and speaker biometrics.",
    version="2026.09.1",
)

START_TIME = time.time()


class AudioInferenceRequest(BaseModel):
    audio_base64: Optional[str] = Field(None, description="Base64-encoded 16-bit 16kHz PCM audio bytes")
    audio_samples: Optional[List[float]] = Field(None, description="Float32 audio waveform samples [-1.0, 1.0]")
    sample_rate: int = Field(16000, description="Sampling rate in Hz")


class DeepfakeInferenceResponse(BaseModel):
    label: str
    spoof_probability: float
    bonafide_probability: float
    confidence: float
    model_version: str
    inference_latency_ms: float


class SpeakerEmbeddingResponse(BaseModel):
    model_version: str
    embedding_dim: int
    embedding: List[float]
    latency_ms: float


def parse_audio(request: AudioInferenceRequest) -> np.ndarray:
    """Decodes input audio from base64 PCM or raw float list."""
    if request.audio_samples is not None and len(request.audio_samples) > 0:
        return np.array(request.audio_samples, dtype=np.float32)
    if request.audio_base64:
        pcm_bytes = base64.b64decode(request.audio_base64)
        int16_data = np.frombuffer(pcm_bytes, dtype=np.int16)
        return (int16_data / 32768.0).astype(np.float32)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either audio_base64 or audio_samples must be provided.")


@app.get("/health", status_code=status.HTTP_200_OK)
@app.get("/health/live", status_code=status.HTTP_200_OK)
async def liveness():
    return {"status": "UP", "service": "vigil-model-service", "uptime_seconds": round(time.time() - START_TIME, 1)}


@app.get("/health/models", status_code=status.HTTP_200_OK)
@app.get("/models", status_code=status.HTTP_200_OK)
async def model_readiness():
    return {
        "status": "HEALTHY",
        "models": {
            "deepfake_detector": DeepfakeModelRegistry.get_model_info(),
            "speaker_verifier": SpeakerModelRegistry.get_encoder().get_model_info(),
        },
        "device": settings.INFERENCE_DEVICE,
    }


@app.post("/predict/deepfake", response_model=DeepfakeInferenceResponse)
async def predict_deepfake(request: AudioInferenceRequest):
    """Executes voice anti-spoofing detection on audio chunk."""
    audio = parse_audio(request)
    detector = DeepfakeModelRegistry.get_detector()
    result = detector.predict(audio)
    return DeepfakeInferenceResponse(
        label=result.label,
        spoof_probability=result.spoof_probability,
        bonafide_probability=result.bonafide_probability,
        confidence=result.confidence,
        model_version=result.model_version,
        inference_latency_ms=result.inference_latency_ms,
    )


@app.post("/predict/speaker-embedding", response_model=SpeakerEmbeddingResponse)
async def predict_speaker_embedding(request: AudioInferenceRequest):
    """Extracts 192-dimensional ECAPA-TDNN biometric embedding vector."""
    audio = parse_audio(request)
    encoder = SpeakerModelRegistry.get_encoder()
    t0 = time.perf_counter()
    emb = encoder.encode(audio)
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return SpeakerEmbeddingResponse(
        model_version=encoder.MODEL_VERSION,
        embedding_dim=encoder.embedding_dim,
        embedding=emb.tolist(),
        latency_ms=round(latency_ms, 2),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
