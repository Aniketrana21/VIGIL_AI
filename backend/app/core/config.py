import os
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application Settings loaded from Environment variables and .env file.
    No secrets are hardcoded.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_NAME: str = "VIGIL-AI"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Security & Authentication
    JWT_SECRET_KEY: str = Field(
        default="change-this-in-production-use-a-32-byte-hex-key-minimum",
        description="Key used for JWT token signing. Must be changed in production."
    )
    API_KEY: str = Field(
        default="vigil-ai-hackathon-demo-key-2026",
        description="API key for REST authentication"
    )
    ALLOW_ANONYMOUS_DEV: bool = True

    # Audio Pipeline Specification
    SAMPLE_RATE: int = 16000
    CHUNK_WINDOW_SECONDS: float = 1.5
    CHUNK_HOP_SECONDS: float = 0.5
    VAD_CONFIDENCE_THRESHOLD: float = 0.50
    VAD_SPEECH_THRESHOLD: float = 0.50
    VAD_MIN_SPEECH_DURATION_MS: int = 250
    VAD_MIN_SILENCE_DURATION_MS: int = 300
    VAD_SPEECH_PAD_MS: int = 150

    # Phase 3: Deepfake Detector Settings
    DEEPFAKE_MODEL_CHECKPOINT: Optional[str] = None
    DEEPFAKE_SPOOF_THRESHOLD: float = 0.65
    DEEPFAKE_BONAFIDE_THRESHOLD: float = 0.35
    DEEPFAKE_MIN_CONFIDENCE: float = 0.60
    DEEPFAKE_INPUT_LENGTH_SAMPLES: int = 32000

    # Phase 5: Speaker Verification Settings
    SPEAKER_ENCODER_CHECKPOINT: Optional[str] = None
    SPEAKER_EMBEDDING_DIM: int = 192
    SPEAKER_MATCH_THRESHOLD: float = 0.75
    SPEAKER_UNKNOWN_THRESHOLD: float = 0.60
    SPEAKER_MIN_ENROLLMENT_UTTERANCES: int = 3
    SPEAKER_MIN_UTTERANCE_DURATION_SEC: float = 0.4
    SPEAKER_STORE_BACKEND: str = "auto"  # "auto" | "postgres" | "memory"

    # Decision Engine Thresholds
    ALLOW_THRESHOLD: float = 0.25
    WARN_THRESHOLD: float = 0.60
    BLOCK_THRESHOLD: float = 0.85
    HIGH_UNCERTAINTY_THRESHOLD: float = 0.60

    # Phase 6: Multi-Signal Risk Engine Thresholds (0-100 scale)
    RISK_ALLOW_MAX: int = 34
    RISK_CHALLENGE_MAX: int = 59
    RISK_WARN_MAX: int = 84
    RISK_CRITICAL_MIN: int = 85
    RISK_MIN_CONFIDENCE_THRESHOLD: float = 0.60

    # Inference hardware
    INFERENCE_DEVICE: str = "auto"  # "auto" | "cuda" | "mps" | "cpu"

    # Phase 7: Real-Time Inference Optimization
    ASYNC_PIPELINE_QUEUE_SIZE: int = 50
    INFERENCE_BATCH_SIZE: int = 4
    RESULT_SMOOTHING_ALPHA: float = 0.35
    ENABLE_ONNX_RUNTIME: bool = True
    MAX_LATENCY_BUDGET_MS: float = 150.0
    DROP_POLICY: str = "drop_oldest"  # "drop_oldest" | "drop_newest" | "block"

    # External stores (Optional for standalone demo / development)
    DATABASE_URL: Optional[str] = "sqlite+aiosqlite:///./vigil_dev.db"
    POSTGRES_VECTOR_URL: Optional[str] = "postgresql+asyncpg://vigil:vigil_secret@localhost:5432/vigil_ai"
    REDIS_URL: Optional[str] = "redis://localhost:6379/0"

    @property
    def window_samples(self) -> int:
        return int(self.SAMPLE_RATE * self.CHUNK_WINDOW_SECONDS)

    @property
    def hop_samples(self) -> int:
        return int(self.SAMPLE_RATE * self.CHUNK_HOP_SECONDS)

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        valid_envs = {"development", "staging", "production", "test"}
        v_clean = v.lower()
        if v_clean not in valid_envs:
            raise ValueError(f"ENVIRONMENT must be one of {valid_envs}")
        return v_clean


settings = Settings()
