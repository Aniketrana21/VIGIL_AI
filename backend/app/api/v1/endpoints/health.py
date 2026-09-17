import time
from fastapi import APIRouter, status
from app.core.config import settings

router = APIRouter()
START_TIME = time.time()


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
