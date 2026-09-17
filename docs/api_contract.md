# VIGIL-AI: API & Streaming Protocol Specification
**REST Endpoints, Real-Time WebSocket Streaming Protocol, and Data Contracts**

---

## 1. Overview & Transport Protocol

VIGIL-AI exposes two primary communication interfaces:
1. **Streaming Audio WebSocket (`/api/v1/stream/ws`):** Bi-directional, low-overhead binary/JSON protocol for sub-second chunk ingestion and real-time risk assessment feeds.
2. **REST API (`/api/v1/...`):** Management interface for Android `CallScreeningService` telemetry, voiceprint enrollment, session tracking, and system health.

All endpoints require TLS 1.3 in production (`wss://` and `https://`). Authentication is enforced via JWT Bearer tokens or high-entropy API keys passed in headers or WebSocket connection query parameters.

---

## 2. Real-Time Streaming WebSocket Protocol

- **Endpoint:** `/api/v1/stream/ws`
- **Query Parameters:**
  - `session_id`: UUIDv4 string (optional; auto-generated if absent).
  - `target_speaker_id`: UUIDv4 string (optional; enrolled voiceprint to verify against).
  - `token`: JWT authentication token.

### 2.1. Client-to-Server Message Types

#### Message A: Session Configuration (JSON)
Must be sent immediately upon connection before any audio frames are transmitted.
```json
{
  "type": "CONFIG",
  "data": {
    "sample_rate": 16000,
    "channels": 1,
    "encoding": "PCM_16BIT",
    "target_speaker_id": "8f3b6c20-7f21-4f12-9c12-32b7e5101a01",
    "context": {
      "channel_type": "WEBRTC",
      "caller_id": "+919876543210",
      "call_direction": "INCOMING"
    }
  }
}
```

#### Message B: Audio Chunk (Binary Frame or Base64 JSON)
Preferred: **Raw Binary WebSocket frames** containing 16-bit linear PCM little-endian samples at 16,000 Hz.
- Each binary chunk should represent between 100ms and 500ms of audio (e.g., 3,200 to 16,000 bytes).

Alternative (Base64 JSON for debug/testing harnesses):
```json
{
  "type": "AUDIO_CHUNK",
  "data": {
    "sequence_id": 42,
    "timestamp_ms": 1726500000000,
    "pcm_base64": "UklGRi4AAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA..."
  }
}
```

#### Message C: Control & Heartbeat (JSON)
```json
{
  "type": "PING",
  "data": {
    "timestamp": 1726500001000
  }
}
```

---

### 2.2. Server-to-Client Message Types

#### Message A: Streaming Risk Verdict (JSON)
Emitted every 500ms as sliding-window evaluation completes.
```json
{
  "type": "VERDICT",
  "session_id": "b73a4d92-12f8-4e0a-b362-e61298c47f3b",
  "sequence_id": 42,
  "timestamp": 1726500001250,
  "data": {
    "decision": "WARN",
    "composite_risk_score": 0.74,
    "confidence": 0.88,
    "uncertainty": {
      "aleatoric_score": 0.12,
      "epistemic_score": 0.14,
      "total_uncertainty": 0.13
    },
    "voice_activity": {
      "is_speech": true,
      "speech_probability": 0.96
    },
    "deepfake_analysis": {
      "is_synthetic": true,
      "synthetic_probability": 0.82,
      "architecture_detected": "NEURAL_VOCODER_DIFFUSION",
      "anomaly_breakdown": {
        "phase_incoherence": 0.78,
        "spectral_rolloff_anomaly": 0.85,
        "pitch_jitter_irregularity": 0.42
      }
    },
    "speaker_verification": {
      "enrolled_match": false,
      "cosine_similarity": 0.38,
      "threshold": 0.65,
      "claimed_speaker_id": "8f3b6c20-7f21-4f12-9c12-32b7e5101a01"
    },
    "liveness_analysis": {
      "is_live_acoustic": false,
      "replay_probability": 0.71,
      "channel_dispersion_detected": true
    },
    "explainability_reasons": [
      "Significant unnatural phase discontinuities detected in 4kHz-8kHz frequency range",
      "Acoustic impulse response indicates loudspeaker replay resonance",
      "Speaker voiceprint does not match enrolled profile for target contact"
    ],
    "latency_metrics": {
      "vad_ms": 11.2,
      "preprocessing_ms": 4.1,
      "antispoof_ms": 128.5,
      "speaker_verify_ms": 42.0,
      "liveness_ms": 19.3,
      "decision_engine_ms": 3.4,
      "total_pipeline_latency_ms": 208.5
    }
  }
}
```

#### Message B: Heartbeat Pong (JSON)
```json
{
  "type": "PONG",
  "data": {
    "client_timestamp": 1726500001000,
    "server_timestamp": 1726500001015
  }
}
```

#### Message C: Error Message (JSON)
```json
{
  "type": "ERROR",
  "error_code": "BUFFER_OVERFLOW",
  "message": "Client stream ingestion rate exceeds processing capacity",
  "fatal": false
}
```

---

## 3. REST API Specification

### 3.1. Health & Readiness Probes
- `GET /api/v1/health/live`: Returns HTTP 200 `{ "status": "UP" }`.
- `GET /api/v1/health/ready`: Validates DB connection, Redis pool, and PyTorch model memory residency.

### 3.2. Android Mode B Telephony Screening
- **Endpoint:** `POST /api/v1/screening/evaluate`
- **Request Body:**
```json
{
  "device_id": "android_9a8b7c6d5e",
  "phone_number": "+919876543210",
  "caller_display_name": "SBI Bank Support",
  "stir_shaken_status": 0,
  "carrier_code": "404-45",
  "timestamp": 1726500000000
}
```
- **Response:**
```json
{
  "action": "WARN",
  "risk_score": 0.82,
  "reason": "Unverified caller claiming high-risk financial identity; STIR/SHAKEN unauthenticated",
  "recommendations": {
    "reject_call": false,
    "silence_ringer": false,
    "display_warning_hud": true,
    "hud_warning_text": "WARNING: Potential bank impersonation call."
  }
}
```

### 3.3. Speaker Voiceprint Enrollment
- **Endpoint:** `POST /api/v1/enrollment/register`
- **Content-Type:** `multipart/form-data`
- **Parameters:**
  - `user_id`: UUIDv4
  - `speaker_label`: String (e.g., "Father", "CEO John Doe")
  - `audio_files`: List of 3 to 5 WAV files (minimum 5s clean speech each)
- **Response:**
```json
{
  "speaker_id": "8f3b6c20-7f21-4f12-9c12-32b7e5101a01",
  "speaker_label": "CEO John Doe",
  "embedding_dim": 192,
  "status": "ENROLLED",
  "snr_db": 28.4,
  "created_at": "2026-09-16T21:35:00Z"
}
```

---

## 4. Standard Error Structure

All HTTP error responses adhere to RFC 7807 (Problem Details for HTTP APIs):
```json
{
  "type": "https://errors.vigilai.security/invalid-audio-format",
  "title": "Invalid Audio Format",
  "status": 400,
  "detail": "Expected 16000Hz 16-bit single-channel linear PCM, but received 44100Hz stereo.",
  "instance": "/api/v1/stream/ws",
  "timestamp": "2026-09-16T21:35:10Z"
}
```
