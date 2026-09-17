# VIGIL-AI: Complete Setup & Deployment Guide

Welcome to the comprehensive setup, configuration, and operations runbook for **VIGIL-AI** — the enterprise real-time voice deepfake and synthetic impersonation defense platform.

---

## 1. End-to-End System Architecture

```
                 [Android Device / Telecom Caller / Web Client]
                                       │
                         Raw 16kHz PCM Audio Stream
                         (TLS 1.3 / WSS Ingest)
                                       │
                                       ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │                    VIGIL-AI STREAMING BACKEND                          │
  │                                                                        │
  │   [Streaming Ingestion Layer] (WebSocket Non-Blocking Buffer)          │
  │                │                                                       │
  │                ▼                                                       │
  │   [Silero Streaming VAD] (Silero-VAD-v4.0)                             │
  │   • Voice Activity Detection, silence gating & RMS telemetry           │
  │                │                                                       │
  │                ▼ (Active Speech Windows)                               │
  │   ┌──────────────────────────────────────────────────────────────┐     │
  │   │              MULTI-MODEL INFERENCE PIPELINE                  │     │
  │   │                                                              │     │
  │   │  ├──► [Deepfake Detector] (Vigil-WavLM-AASIST-v1.0)          │     │
  │   │  │    • Neural vocoder & phase synthetic artifact detection  │     │
  │   │  │                                                           │     │
  │   │  ├──► [Speaker Verifier]  (Vigil-ECAPA-TDNN-v1.0)            │     │
  │   │  │    • 192-dim unit-normalized cosine biometric match       │     │
  │   │  │                                                           │     │
  │   │  ├──► [Acoustic Liveness] (Vigil-AcousticLiveness-v1.0)      │     │
  │   │  │    • Loudspeaker replay, PAPR, pause entropy & decay      │     │
  │   │  │                                                           │     │
  │   │  └──► [Conversation Intelligence] (OpenAI-Whisper-Base-v1.0) │     │
  │   │       • Speech transcript & high-risk intent classification  │     │
  │   └──────────────────────────────┬───────────────────────────────┘     │
  │                                  │                                     │
  │                                  ▼                                     │
  │   [Caller Verification Metadata] (STIR/SHAKEN A-Attestation)           │
  │                                  │                                     │
  │                                  ▼                                     │
  │   [Multi-Signal Risk Decision Engine] (Policy: 2026.09.1-production)   │
  │   • Weighted Signal Synthesis & Compound Penalties                     │
  │   • Graceful Degradation & Low-Confidence Guardrails                   │
  │   • Transparent Human Explanations & Audit Logs                        │
  │                                  │                                     │
  │             ┌────────────────────┼────────────────────┐                │
  │             ↓                    ↓                    ↓                │
  │           ALLOW              CHALLENGE              BLOCK              │
  │                              (Adaptive Nonce)                          │
  └──────────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │         REAL-TIME VOICE SECURITY OPERATIONS CENTER (SOC)               │
  │         React 19 + TypeScript + Tailwind CSS v4 Dashboard              │
  │   • Live Voice Authenticity, Speaker Match & Liveness Gauges           │
  │   • Real-Time Oscilloscope & Threat Signals Audit Timeline             │
  │   • Operator Action Controls: [VERIFY] [CHALLENGE] [WARN] [BLOCK]      │
  │   • Degraded Network / Offline Recovery State Banners                  │
  └────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Prerequisites & Environment

### Minimum Requirements:
- **Operating System**: Linux (Ubuntu 22.04+ / Debian 12), macOS (13+), or Windows 10/11 with WSL2 / PowerShell 7.
- **Python**: Version `3.10` to `3.13` (64-bit).
- **Node.js**: Version `20.x` or higher with `npm`.
- **Containerization**: Docker Engine `24.0+` and Docker Compose `v2.20+`.
- **RAM**: Minimum 4 GB (8 GB recommended for GPU acceleration).
- **Hardware Acceleration (Optional)**: NVIDIA GPU with CUDA 12+ or Apple Silicon MPS.

---

## 3. Local Development Quickstart

### Step 3.1: Clone & Configure Backend
```bash
git clone https://github.com/Aniketrana21/VIGIL_AI.git
cd VIGIL_AI/backend

# Create virtual environment
python -m venv venv
source venv/bin/activate    # On Windows: .\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Create .env from template
cp .env.example .env
```

### Step 3.2: Run Backend Server
```bash
# Start FastAPI backend on port 8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
The server will start at `http://127.0.0.1:8000`.
- Swagger Docs: `http://127.0.0.1:8000/docs`
- Health Probe: `http://127.0.0.1:8000/api/v1/health/live`
- Model Readiness Probe: `http://127.0.0.1:8000/api/v1/health/models`

### Step 3.3: Configure & Run Frontend
In a new terminal:
```bash
cd VIGIL_AI/frontend

# Install node dependencies
npm install

# Start Vite development server
npm run dev
```
The frontend dev server will launch at `http://localhost:5173`.
To compile the production bundle directly into backend static assets:
```bash
npm run build
```

---

## 4. Production Docker Compose Deployment (5 Services)

VIGIL-AI includes an enterprise `docker-compose.yml` orchestrating 5 interconnected microservices:

1. **`backend`**: FastAPI application server, streaming orchestrator, and WebSocket pipeline.
2. **`postgres`**: PostgreSQL 16 with `pgvector` extension for encrypted biometric voiceprint storage.
3. **`redis`**: Redis 7 Alpine for high-speed rate-limiting and session state caching.
4. **`frontend`**: Nginx web server serving compiled React 19 SOC assets and reverse-proxying API/WebSocket traffic.
5. **`model-service`**: Standalone ML inference microservice for scaling heavy neural computations.

### Launching with Docker Compose:
```bash
cd VIGIL_AI

# Build and start all 5 containers in detached mode
docker compose up -d --build

# View container statuses
docker compose ps
```

### Service Map:
| Service | Container Name | Port Mapping | Description |
| :--- | :--- | :--- | :--- |
| **Frontend SOC Dashboard** | `vigil_frontend` | `http://localhost:3000` | Nginx reverse proxy + React Dashboard |
| **Backend REST & WS** | `vigil_backend` | `http://localhost:8000` | FastAPI application server |
| **Model Microservice** | `vigil_model_service` | `http://localhost:8001` | Dedicated ML inference worker |
| **Vector Database** | `vigil_postgres` | `localhost:5432` | PostgreSQL 16 + pgvector |
| **Session Cache** | `vigil_redis` | `localhost:6379` | Redis 7 Alpine in-memory cache |

### Stopping Services:
```bash
docker compose down
```

---

## 5. Configuration Reference (`.env`)

No credentials or model paths are hardcoded. All settings are loaded via Pydantic settings from environment variables or `.env`:

| Environment Variable | Default Value | Description |
| :--- | :--- | :--- |
| `ENVIRONMENT` | `development` | `development`, `staging`, `production`, or `test` |
| `HOST` | `0.0.0.0` | API bind address |
| `PORT` | `8000` | API port |
| `JWT_SECRET_KEY` | *(Set in .env)* | 32-byte hex secret for token signing |
| `API_KEY` | *(Set in .env)* | API key for REST authentication |
| `BIOMETRIC_ENCRYPTION_KEY` | *(Set in .env)* | 32-byte hex key for AES-256-GCM encryption of voiceprints |
| `RATE_LIMIT_PER_MINUTE` | `120` | Max requests per IP per minute before HTTP 429 |
| `MAX_AUDIO_PAYLOAD_BYTES`| `10485760` (10MB) | Maximum audio payload size per request |
| `WS_AUTH_REQUIRED` | `false` | When `true`, WebSocket connections require token parameter |
| `DATABASE_URL` | `sqlite+aiosqlite:///./vigil_dev.db` | PostgreSQL or SQLite connection URI |
| `POSTGRES_VECTOR_URL` | `postgresql+asyncpg://...` | PostgreSQL pgvector database URI |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis caching & rate limiting URI |
| `MODEL_SERVICE_URL` | `null` (Optional) | Remote model microservice (e.g. `http://model-service:8001`) |
| `DEEPFAKE_MODEL_CHECKPOINT` | `null` (Optional) | Path to fine-tuned WavLM+AASIST weights |
| `SPEAKER_ENCODER_CHECKPOINT` | `null` (Optional) | Path to fine-tuned ECAPA-TDNN weights |
| `INFERENCE_DEVICE` | `auto` | `auto`, `cuda`, `mps`, or `cpu` |

---

## 6. Health & Model Readiness Endpoints

### 6.1 Liveness Probe (`GET /api/v1/health/live`)
Returns HTTP 200 if the process is responsive:
```json
{
  "status": "UP",
  "uptime_seconds": 342.5
}
```

### 6.2 Component Readiness Probe (`GET /api/v1/health/ready`)
Validates pipeline initialization:
```json
{
  "status": "READY",
  "app_name": "VIGIL-AI",
  "environment": "production",
  "inference_device": "cpu",
  "sample_rate": 16000,
  "window_seconds": 1.5,
  "hop_seconds": 0.5
}
```

### 6.3 Comprehensive Model Readiness Probe (`GET /api/v1/health/models`)
Inspects and exposes live version metadata and operational readiness for all 6 AI modules:
```json
{
  "status": "HEALTHY",
  "all_ready": true,
  "models": {
    "deepfake_detector": {
      "name": "WavLM-AASIST Voice Clone Detector",
      "version": "Vigil-WavLM-AASIST-v1.0",
      "status": "READY",
      "device": "cpu",
      "checkpoint_loaded": false
    },
    "speaker_verifier": {
      "name": "ECAPA-TDNN Speaker Verifier",
      "version": "Vigil-ECAPA-TDNN-v1.0",
      "status": "READY",
      "embedding_dim": 192
    },
    "vad": {
      "name": "Silero Streaming VAD",
      "version": "Silero-VAD-v4.0",
      "status": "READY"
    },
    "liveness": {
      "name": "Acoustic Multi-Band Liveness & Replay Detector",
      "version": "Vigil-AcousticLiveness-v1.0",
      "status": "READY"
    },
    "conversation_intelligence": {
      "name": "Whisper Contextual Intent Classifier",
      "version": "OpenAI-Whisper-Base-v1.0",
      "status": "READY"
    },
    "policy_risk_engine": {
      "name": "Multi-Factor Non-Linear Risk & Policy Engine",
      "version": "2026.09.1-production",
      "status": "READY",
      "thresholds": {
        "allow_max": 34,
        "challenge_max": 59,
        "warn_max": 84,
        "critical_min": 85,
        "min_confidence": 0.60
      }
    }
  }
}
```

---

## 7. Graceful Degradation & Fail-Safe Modes

VIGIL-AI implements robust graceful degradation contracts across all failure modes:

| Failure Scenario | Automatic System Behavior | Security Invariant |
| :--- | :--- | :--- |
| **Deepfake Model Offline** | Pipeline sets `deepfake_model_available = False`, flags `DEEPFAKE_MODEL_UNAVAILABLE`, and continues using acoustic liveness, speaker match, telephony attestation, and conversation intelligence. | The call is **never** blindly assumed genuine; protections remain active. |
| **Speaker Model Offline** | If a speaker identity is claimed, the engine flags `SPEAKER_IDENTITY_UNVERIFIED` and sets similarity to `None`. | The system **never** pretends identity was verified; downgrades `ALLOW` to `CHALLENGE` or `MONITOR`. |
| **Low Confidence (< 60%)** | Safety guardrail overrides irreversible `BLOCK` or `ALLOW` actions, converting verdict to `CHALLENGE / VERIFY` with `requires_human_verification = True`. | Prevents automated false positives on noisy or uncertain audio. |
| **Network Interruption** | React SOC dashboard detects disconnection or offline state and presents a prominent Amber/Red **Network Degradation Banner**, buffering audio locally until reconnection. | Operator is immediately notified of degraded telemetry. |

---

## 8. Verification & Testing

### Running Integration & Security Tests:
```bash
# Run Phase 16 final integration tests
python -m pytest backend/tests/unit/test_final_integration.py -v

# Run full project test suite
python -m pytest backend/tests/unit -v
```

### Manual Verification Commands:
```bash
# 1. Check live model versions and health
curl -s http://localhost:8000/api/v1/health/models | jq .

# 2. Test dedicated model service
curl -s http://localhost:8001/models | jq .

# 3. Query persisted detection events from PostgreSQL / DB
curl -s -H "X-API-Key: vigil_dev_secret_key_2026" "http://localhost:8000/api/v1/screening/detections?limit=10" | jq .

# 4. Query aggregated detection statistics
curl -s -H "X-API-Key: vigil_dev_secret_key_2026" "http://localhost:8000/api/v1/screening/stats" | jq .

# 5. Verify Docker Compose configuration
docker compose config
```

---

## 9. PostgreSQL Detection Events Storage & Schema

VIGIL-AI automatically records every real-time voice cloning detection, speaker verification, acoustic liveness evaluation, and multi-factor risk verdict directly into **PostgreSQL** (with zero-configuration SQLite relational database fallback).

### Database Schema (`detection_events` Table):
```sql
CREATE TABLE IF NOT EXISTS detection_events (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    deepfake_score FLOAT,
    deepfake_label VARCHAR(32),
    speaker_id VARCHAR(128),
    speaker_similarity FLOAT,
    liveness_score FLOAT,
    replay_probability FLOAT,
    conversation_intent VARCHAR(64),
    conversation_risk FLOAT,
    risk_score INT NOT NULL,
    risk_level VARCHAR(32) NOT NULL,
    action VARCHAR(32) NOT NULL,
    confidence FLOAT NOT NULL,
    signals JSONB DEFAULT '[]'::jsonb,
    contributing_signals JSONB DEFAULT '[]'::jsonb,
    explanation TEXT,
    caller_id VARCHAR(64),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_detection_session ON detection_events(session_id);
CREATE INDEX IF NOT EXISTS idx_detection_timestamp ON detection_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_detection_risk_level ON detection_events(risk_level);
CREATE INDEX IF NOT EXISTS idx_detection_action ON detection_events(action);
```

### Privacy Guarantee:
- **Zero Raw PCM Storage**: Audio waveforms are completely excluded from the database; only structured mathematical risk metrics, confidence values, and explainable signals are retained.
- **Masked Caller IDs**: Phone numbers are securely salted and anonymized (`+91***10`) prior to persistence.

