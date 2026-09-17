# VIGIL-AI: Architecture & System Design Document
**AI-Powered Real-Time Detection and Prevention of Voice Cloning Impersonation Attacks**  
*SIH Project Technical Blueprint — Version 1.0*

---

## 1. Executive Summary & Objective

Modern generative voice synthesis (e.g., ElevenLabs, XTTS, VALL-E, OpenVoice) can replicate a human speaker's timbre, prosody, and emotional inflections with fewer than 3 seconds of reference audio. This capability has fueled a surge in:
- High-value wire-transfer authorization fraud (CEO voice cloning).
- Family emergency distress scams (impersonating children, spouses).
- Social engineering attacks against banking OTPs and customer care centers.

**VIGIL-AI** is an industrial-grade, streaming defense-in-depth platform designed to analyze near-real-time voice streams and caller metadata to classify speech into five definitive states:
1. **GENUINE**
2. **SYNTHETIC / CLONED**
3. **REPLAYED**
4. **SUSPICIOUS / ELEVATED RISK**
5. **UNCERTAIN (Out-of-Distribution / High Ambiguity)**

### Core Architectural Axiom: Never Claim 100% Detection
Adversarial attacks, acoustic room noise, low-bitrate cellular codecs (AMR-NB at 4.75kbps), and transmission packet loss create intrinsic uncertainty. Every VIGIL-AI inference exposes:
- A point prediction with an explicit uncertainty metric (entropy & epistemic variance).
- Explainability factor breakdown (e.g., spectral phase incoherence, vocoder artifact density).
- End-to-end inference latency tracing (P50, P95, P99).

---

## 2. Platform Realities: The Two-Mode Operational Architecture

A critical failure point in voice security solutions is assuming third-party mobile applications can intercept live cellular call audio. Modern operating systems (specifically Android 10+ / API 29 through Android 15) strictly forbid third-party applications from capturing two-way telephone audio due to sandbox isolation and regulatory privacy mandates.

To address this, VIGIL-AI implements two distinct operational modes:

```
                                +-------------------------------------------+
                                |                 VIGIL-AI                  |
                                +---------------------+---------------------+
                                                      |
                         +----------------------------+----------------------------+
                         |                                                         |
                         v                                                         v
          +------------------------------+                          +------------------------------+
          |            MODE A            |                          |            MODE B            |
          |       Demo / VoIP / WebRTC   |                          |  Android Cellular Telephony  |
          +------------------------------+                          +------------------------------+
          | • Live PCM Audio Ingestion   |                          | • Pre-Call Screening         |
          | • Full AI Pipeline Analysis  |                          | • TelecomManager Integration |
          | • WebSocket Streaming        |                          | • Caller Metadata & Spam Risk|
          | • Near Real-Time Scoring     |                          | • Ambient / Speaker Mic Mode |
          +------------------------------+                          +------------------------------+
```

### Mode A: Demo / VoIP / WebRTC Stream Ingestion
- **Target Environments:** WhatsApp calls (via accessibility/companion where permitted), customer support softphones, Zoom/Teams bots, custom WebRTC clients, and demo evaluation harnesses.
- **Data Flow:** High-resolution audio (16kHz+ PCM) is streamed via WebSockets into the backend AI pipeline.
- **Capabilities:** Sub-second continuous streaming evaluation, voice activity detection (VAD), deepfake artifact detection, speaker verification, acoustic liveness analysis, and instant mitigation (warning tones, session tear-down).

### Mode B: Android Cellular Telephony Integration
- **Target Environments:** Standard carrier cellular voice calls (GSM/VoLTE/VoNR).
- **Platform Constraints (Android 10+):**
  - `AudioSource.VOICE_CALL`, `VOICE_DOWNLINK`, and `VOICE_UPLINK` require the privileged signature permission `android.permission.CAPTURE_AUDIO_OUTPUT`.
  - Google Play policy strictly prohibits non-system apps from recording call audio via `AccessibilityService`.
- **VIGIL-AI Solution for Mode B:**
  1. **Pre-Call Screening (`CallScreeningService` + `RoleManager.ROLE_CALL_SCREENING`):**
     - Intercepts incoming calls *before* the phone rings.
     - Performs real-time lookup of caller ID, STIR/SHAKEN carrier attestation levels (A, B, or C), and national threat intelligence databases.
     - Can programmatically silence, reject, or flag the call before connection.
  2. **In-Call Contextual Heads-Up Display (HUD):**
     - A foreground system alert overlay (`SYSTEM_ALERT_WINDOW`) warns the user about elevated impersonation risks.
  3. **Acoustic Loudspeaker Mode (User-Assisted):**
     - When the user places the call on speakerphone, VIGIL-AI captures ambient audio via `AudioRecord(MediaRecorder.AudioSource.MIC)` for continuous deepfake screening.

---

## 3. High-Level System Architecture Diagram

```mermaid
graph TD
    subgraph ClientLayer["Client Layer"]
        MA["Mode A: WebRTC / Web Dashboard<br/>(React + AudioWorklet)"]
        MB["Mode B: Android Native Service<br/>(CallScreeningService + RoleManager)"]
    end

    subgraph GatewayLayer["API & Ingestion Gateway"]
        GW["FastAPI Gateway / Reverse Proxy"]
        AUTH["Auth & Rate Limiter<br/>(JWT + Redis Token Bucket)"]
        WS_MGR["WebSocket Connection Pool<br/>(Session & Heartbeat Manager)"]
    end

    subgraph Pipeline["Streaming AI Inference Engine"]
        PRE["1. Audio Preprocessing & Normalization<br/>(16kHz Mono, Peak Guard, LUFS)"]
        VAD["2. Voice Activity Detection<br/>(Silero VAD ONNX, <15ms)"]
        CHUNK["3. Streaming Sliding-Window Chunker<br/>(1.5s Window, 500ms Hop)"]
        
        subgraph DeepAnalysis["Parallel Forensic Analyzers"]
            DF["4. Deepfake / Anti-Spoofing<br/>(WavLM / AASIST Spectro-Temporal GAT)"]
            SV["5. Speaker Verification<br/>(ECAPA-TDNN 192-d Embeddings)"]
            LIVE["6. Acoustic Liveness / Replay<br/>(RIR Anomaly & Sub-band Dispersion)"]
        end
        
        CTX["7. Contextual Telephony Risk Engine<br/>(Caller Meta, Velocity, STIR/SHAKEN)"]
        FUSION["8. Multi-Factor Bayesian Decision Engine<br/>(Temperature-Scaled Uncertainty)"]
    end

    subgraph StorageLayer["Data & State Persistence"]
        REDIS[("Redis In-Memory Store<br/>(Sessions, Ephemeral Audio Buffers)")]
        PG[("PostgreSQL + pgvector<br/>(Enrolled Voiceprints, Telephony Audit Logs)")]
    end

    MA -->|PCM Audio Stream (WebSocket)| GW
    MB -->|Telephony Metadata RPC (REST)| GW
    MB -.->|Ambient Mic PCM (WebSocket)| GW
    
    GW --> AUTH
    AUTH --> WS_MGR
    WS_MGR --> PRE
    
    PRE --> VAD
    VAD -->|Active Speech Frames| CHUNK
    CHUNK --> DF
    CHUNK --> SV
    CHUNK --> LIVE
    
    DF --> FUSION
    SV --> FUSION
    LIVE --> FUSION
    CTX --> FUSION
    
    SV <-->|Cosine Search| PG
    WS_MGR <-->|Session State| REDIS
    
    FUSION -->|ALLOW / CHALLENGE / WARN / BLOCK| WS_MGR
    WS_MGR -->|Real-time Verdict & Telemetry| MA
    WS_MGR -.->|HUD Warning Overlay Event| MB
```

---

## 4. Detailed Component Descriptions

### 4.1. Audio Ingestion & Preprocessing
- **Resampling:** Ingested audio is resampled to 16,000 Hz, 16-bit linear PCM mono.
- **Normalization:** Real-time peak clipping protection with ITU-R BS.1770-4 integrated loudness normalization target (-23 LUFS ± 1.0 LUFS).
- **Buffering Policy:** Ephemeral in-memory ring buffers. To ensure total compliance with data protection laws (e.g., India DPDP Act 2023, EU GDPR), audio bytes are processed in memory and zeroed immediately after inference. No raw voice audio is persisted to disk unless explicit forensic capture is enabled by admin policy.

### 4.2. Voice Activity Detection (VAD)
- **Model:** Silero VAD (ONNX Runtime engine).
- **Latency Budget:** < 15ms per 32ms frame chunk.
- **Behavior:** Strips silence, background white noise, and comfort noise. Prevents model hallucination and reduces downstream computation by 40–60%.

### 4.3. Streaming Sliding-Window Chunking
- **Window Size:** 1.5 seconds (24,000 samples at 16kHz).
- **Hop Size:** 0.5 seconds (8,000 samples at 16kHz).
- **Context Accumulation:** Maintains a temporal history of up to 5 consecutive chunks (2.5s window) to track prosody drift and spectral discontinuity over time.

### 4.4. Deepfake & Anti-Spoofing Detection
- **Primary Backbone:** Fine-tuned `WavLM-Large` / `wav2vec 2.0` cross-attentive model.
- **Architecture:** AASIST (Audio Anti-Spoofing using Integrated Spectro-Temporal Graph Attention).
- **Forensic Signatures Inspected:**
  1. High-frequency roll-off typical of neural vocoders (HiFi-GAN, WaveGlow).
  2. Phase inconsistencies across harmonic overtones.
  3. Formant unnaturalness and robotic micro-jitter anomalies.

### 4.5. Speaker Verification & Enrollment (Biometric Verification)
- **Model:** ECAPA-TDNN (Emphasized Channel Attention, Propagation and Aggregation Time Delay Neural Network).
- **Embedding Size:** 192-dimensional vector.
- **Database Search:** Indexed via `pgvector` with HNSW (Hierarchical Navigable Small World) index for sub-5ms cosine similarity search against enrolled family or executive profiles.
- **Behavior:** Detects if an attacker is claiming to be Person X while acoustic voiceprints diverge significantly.

### 4.6. Acoustic Liveness & Replay Analysis
- **Goal:** Differentiate between genuine live microphone proximity and acoustic playback through physical speakers (soundbar, smartphone loudspeaker, PC speakers).
- **Signals:**
  1. Room Impulse Response (RIR) multi-path reverberation analysis.
  2. Sub-band spectral dispersion and pop filter proximity effects (plosives: /p/, /b/, /t/).
  3. Characteristic harmonic distortion added by consumer audio transducers.

### 4.7. Contextual Risk & Bayesian Decision Engine
- **Input Factors:**
  - $P_{\text{deepfake}} \in [0.0, 1.0]$: Anti-spoofing probability.
  - $U_{\text{model}} \in [0.0, 1.0]$: Epistemic & aleatoric model uncertainty.
  - $S_{\text{speaker}} \in [0.0, 1.0]$: Speaker match cosine similarity (if profile exists).
  - $L_{\text{liveness}} \in [0.0, 1.0]$: Liveness acoustic confidence.
  - $R_{\text{context}} \in [0.0, 1.0]$: Telephony risk (STIR/SHAKEN status, caller reputation, call duration).
- **Decision Matrix:**
  - **ALLOW:** $P_{\text{deepfake}} < 0.20$ and $U_{\text{model}} < 0.35$ and $L_{\text{liveness}} > 0.70$.
  - **WARN:** $0.40 \le P_{\text{deepfake}} < 0.75$ or $R_{\text{context}} > 0.60$.
  - **CHALLENGE:** High uncertainty ($U_{\text{model}} \ge 0.60$) or speaker mismatch ($S_{\text{speaker}} < 0.45$ for claimed identity). Triggers secondary interactive phrase verification.
  - **BLOCK:** $P_{\text{deepfake}} \ge 0.85$ with $U_{\text{model}} < 0.40$.

---

## 5. End-to-End Latency Budget

To maintain seamless interaction without disrupting conversations, the total latency budget for each 500ms audio chunk is strictly capped:

| Pipeline Stage | Algorithm / Component | Target Latency (P50) | Upper Bound (P99) |
|---|---|---|---|
| Ingestion & Framing | AudioWorklet / WebSocket framing | 15 ms | 25 ms |
| Normalization & Resampling | Torchaudio / Numpy vector ops | 5 ms | 10 ms |
| Voice Activity Detection | Silero VAD (ONNX Runtime) | 12 ms | 20 ms |
| Deepfake / Anti-Spoofing | AASIST / WavLM (ONNX INT8 / TensorRT) | 120 ms | 180 ms |
| Speaker Verification | ECAPA-TDNN (ONNX) | 45 ms | 70 ms |
| Liveness & Replay Check | Spectral dispersion & FFT analysis | 18 ms | 30 ms |
| Decision Engine & Scoring | Bayesian Policy Aggregator | 5 ms | 10 ms |
| WebSocket Serialization | JSON / Binary RPC message | 5 ms | 15 ms |
| **Total End-to-End** | **Full Streaming Loop** | **~225 ms** | **< 360 ms** |

*Note: Because our hop size is 500 ms, an inference execution latency of < 360 ms ensures zero backlog build-up in streaming buffers.*
