# VIGIL-AI: Security, Privacy & Compliance Specification
**Zero-Retention Audio Handling, Biometric Security, Threat Model, and DPDP / GDPR Compliance**

---

## 1. Zero-Retention Audio Handling Architecture

Voice recordings are classified as sensitive biometric personal data. Persisting raw voice audio creates catastrophic liability in the event of database breach.

### Strict Data Retention Rules
```
                                INCOMING AUDIO STREAM
                                         |
                                         v
                         +-------------------------------+
                         |   Ephemeral In-Memory Buffer  |
                         |   (RAM only; ring buffer)     |
                         +---------------+---------------+
                                         |
                                         v
                         +-------------------------------+
                         |   AI Feature & Risk Extraction|
                         +---------------+---------------+
                                         |
                       +-----------------+-----------------+
                       |                                   |
                       v                                   v
             [ Feature Vectors ]                 [ Raw Audio Bytes ]
             - 192-d Speaker Embedding           - Overwrite buffer with 0x00
             - Anomaly & Risk Scores             - Trigger Garbage Collection
             - Zero Speech Audio Retained        - NEVER written to disk
```

1. **No Disk Writes for Live Streams:** Raw audio chunks received over WebSocket or REST are processed exclusively in volatile RAM.
2. **Deterministic Memory Overwrite:** Immediately after model inference completes for a sliding window, the underlying byte buffer is zero-filled (`bytearray.clear()` / in-place memset) before deallocation.
3. **No Audio in Logs:** Under no circumstances are raw audio payloads, base64 waveforms, or transcripts printed to log files or standard output.

---

## 2. Voice Biometric Protection (Speaker Embeddings)

Speaker verification relies on 192-dimensional floating-point embeddings produced by ECAPA-TDNN:

1. **Irreversibility:** The 192-dimensional embedding is a non-invertible representation of vocal tract resonances; a raw audio waveform cannot be reconstructed from this vector.
2. **Encrypted Storage:** Enrolled embeddings stored in PostgreSQL (`pgvector`) are encrypted at rest using AES-256-GCM. The encryption key is derived from an external KMS or environment master secret (`ENCRYPTION_MASTER_KEY`).
3. **User Revocation Rights:** When a user deletes an enrolled contact or profile, the associated vector is purged (`DELETE FROM voiceprints WHERE id = :id`) and the index is recalculated.

---

## 3. Threat Model (STRIDE Analysis)

| Threat Category | Attack Vector | VIGIL-AI Countermeasure |
|---|---|---|
| **Spoofing (Identity)** | Adversary uses ElevenLabs/VALL-E clone to impersonate family member or CEO. | WavLM/AASIST anti-spoofing model detects vocoder artifacts; ECAPA-TDNN flags speaker voiceprint deviation. |
| **Tampering** | Man-in-the-Middle (MiTM) tampering with audio packets in transit. | Mandatory TLS 1.3 encryption on WebSockets (`wss://`) and REST; HMAC SHA-256 packet integrity checks. |
| **Repudiation** | Attacker denies attempting a voice cloning attack. | Cryptographically signed telemetry audit log containing decision factors, timestamps, and model uncertainty (without saving audio). |
| **Information Disclosure** | Leakage of private phone calls or voiceprints. | Ephemeral RAM-only buffer architecture; zero audio persistence; encrypted vector storage at rest. |
| **Denial of Service (DoS)** | Attacker floods WebSocket endpoint with high-bitrate continuous streams to exhaust GPU/CPU. | Redis token-bucket rate limiting; Silero VAD early drop of silence; max 1 concurrent stream per authenticated session. |
| **Elevation of Privilege** | Attacker manipulates CallScreening metadata to whitelist spoofed numbers. | STIR/SHAKEN cryptographic attestation verification; phone reputation cross-checks. |

---

## 4. Adversarial Audio Attacks & Robustness

Adversaries may attempt to bypass anti-spoofing models by injecting:
1. **Adversarial Noise Perturbations (FGSM / PGD):**
   - *Mitigation:* Audio preprocessing applies a perceptual band-pass filter (80Hz to 7600Hz) and subtle random dither injection during inference to disrupt adversarial gradients.
2. **Physical Replay via Loudspeaker:**
   - *Mitigation:* The acoustic liveness detector inspects room impulse responses, transducer distortion, and sub-band phase dispersion.
3. **Code-Switching & Prosodic Mimicry:**
   - *Mitigation:* Multi-hop sliding window (500ms hop over 1.5s window) tracks temporal continuity across phoneme boundaries.

---

## 5. Secret Management & Configuration Hygiene

To comply with enterprise security standards:
1. **Zero Hardcoded Secrets:** All credentials, database URIs, JWT secrets, and API keys are injected via environment variables.
2. **Pydantic Validation:** The application crashes on startup (`exit code 1`) if mandatory secrets (e.g., `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`) are empty or match default insecure strings.
3. **Separation of Environments:** Distinct `.env.development`, `.env.staging`, and `.env.production` profiles.

---

## 6. Regulatory & Legal Compliance

### 6.1. India Digital Personal Data Protection (DPDP) Act 2023
- **Data Minimization:** Only metadata (risk score, confidence, phone hash) is logged.
- **Notice & Consent:** The Android client explicitly alerts the user before any screening or ambient recording initiates.
- **Right to Erasure:** Enrolled voice biometric vectors are permanently deleted upon user request.

### 6.2. EU General Data Protection Regulation (GDPR - Article 9)
- Biometric data processing is strictly constrained to security and fraud-prevention purposes.
- Zero audio retention ensures no secondary voice processing occurs without explicit consent.
