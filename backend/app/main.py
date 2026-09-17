from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.v1.endpoints import challenge, conversation, enroll, health, screening, stream, stream_ingest
from app.core.config import settings
from app.core.logging import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: eagerly loads all ML models and warms up hardware at startup."""
    logger.info(f"Starting {settings.APP_NAME} in '{settings.ENVIRONMENT}' environment...")
    logger.info(f"Pipeline configured for {settings.SAMPLE_RATE}Hz audio with {settings.CHUNK_WINDOW_SECONDS}s sliding window.")

    # Phase 7: Eager persistent model loading & warmup
    import time
    startup_t0 = time.perf_counter()

    # 1. Resolve hardware device
    from app.pipeline.device import DeviceManager
    device = DeviceManager.resolve()
    dev_info = DeviceManager.get_info()
    logger.info(f"Hardware: {dev_info.device_type.upper()} — {dev_info.device_name} (GPU: {'ON' if dev_info.gpu_enabled else 'OFF'})")

    # 2. Warmup Silero VAD (loads JIT model)
    from app.pipeline.silero_vad import SileroStreamingVAD
    vad = SileroStreamingVAD(sample_rate=settings.SAMPLE_RATE)
    logger.info("Silero VAD model loaded & warmed up.")

    # 3. Warmup WavLM+AASIST Deepfake Detector
    from app.pipeline.deepfake_detector import DeepfakeModelRegistry
    detector = DeepfakeModelRegistry.get_detector()
    logger.info(f"Deepfake Detector loaded & warmed up ({detector.__class__.__name__}).")

    # 4. Warmup ECAPA-TDNN Speaker Encoder
    from app.pipeline.speaker_encoder import SpeakerModelRegistry
    encoder = SpeakerModelRegistry.get_encoder()
    logger.info(f"Speaker Encoder loaded & warmed up ({encoder.__class__.__name__}).")

    # 5. ONNX status
    from app.pipeline.onnx_backend import ONNXStatus
    onnx_info = ONNXStatus.to_dict()
    logger.info(f"ONNX Runtime: {'available' if onnx_info['onnx_active'] else 'not available'}")

    startup_ms = (time.perf_counter() - startup_t0) * 1000.0
    logger.info(f"All models loaded and warmed up in {startup_ms:.0f}ms. Ready for inference.")

    yield

    logger.info(f"Shutting down {settings.APP_NAME}. Purging remaining resources.")


app = FastAPI(
    title=settings.APP_NAME,
    description="AI-Powered Real-Time Detection and Prevention of Voice Cloning Impersonation Attacks",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust to specific frontend domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "type": "https://errors.vigilai.security/internal-error",
            "title": "Internal Server Error",
            "status": 500,
            "detail": "An unexpected server error occurred while processing the request.",
        },
    )


from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api import speaker

# Register API v1 routes
app.include_router(health.router, prefix="/api/v1/health", tags=["Health"])
app.include_router(screening.router, prefix="/api/v1/screening", tags=["Android Screening"])
app.include_router(enroll.router, prefix="/api/v1/enrollment", tags=["Biometric Enrollment"])
app.include_router(challenge.router, prefix="/api/v1/challenge", tags=["Challenge-Response"])
app.include_router(conversation.router, prefix="/api/v1/conversation", tags=["Conversation Intelligence"])
app.include_router(speaker.router)
app.include_router(stream.router, prefix="/api/v1/stream", tags=["Streaming WebSocket"])
app.include_router(stream_ingest.router, prefix="/api/v1/stream", tags=["Audio Ingestion"])

# Mount static files for web dashboard
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_dashboard():
        return FileResponse(str(static_dir / "index.html"))
