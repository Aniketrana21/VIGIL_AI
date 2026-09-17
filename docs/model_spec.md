# VIGIL-AI: AI Model Specification & Pipeline Interfaces
**Model Architectures, Input/Output Tensor Contracts, and Python Abstractions**

---

## 1. Pipeline Overview & Processing Sequence

The VIGIL-AI real-time analysis pipeline executes in a strict forward sequence with deterministic latency bounds:

```
[Raw Audio Chunk (PCM 16-bit 16kHz)]
                |
                v
1. Preprocessor & Normalizer (Float32 Tensor [-1.0, 1.0], Peak Guard)
                |
                v
2. Silero VAD (ONNX Runtime) ---> [Silence / Comfort Noise Dropped]
                |
                v (Speech detected)
3. Sliding Window Chunker (Buffer: 1.5s / 24,000 samples; Hop: 0.5s / 8,000 samples)
                |
                +-----------------------+-----------------------+
                |                       |                       |
                v                       v                       v
4. Anti-Spoofing / Deepfake    5. Speaker Verifier     6. Acoustic Liveness
   (WavLM / AASIST Backbone)      (ECAPA-TDNN)            (Spectral & RIR)
   Tensor: [1, 24000]             Tensor: [1, 24000]      Tensor: [1, 24000]
   Output: P(synth), Uncert.      Output: [1, 192] Emb    Output: P(replay)
                |                       |                       |
                +-----------------------+-----------------------+
                                        |
                                        v
                    7. Multi-Factor Bayesian Risk Engine
                       (Combines scores + Uncertainty + Context)
                                        |
                                        v
                       Decision: ALLOW | CHALLENGE | WARN | BLOCK
```

---

## 2. Python Abstract Base Classes (ABCs)

### 2.1. Base Audio Processor Interface
```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import torch

class BaseAudioProcessor(ABC):
    """Abstract base class for all audio pipeline stages."""

    @abstractmethod
    def initialize(self, device: str = "cpu") -> None:
        """Load weights, ONNX sessions, or allocate GPU memory."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset internal streaming states, ring buffers, or caches."""
        pass

    @abstractmethod
    def get_latency_stats(self) -> Dict[str, float]:
        """Return running latency metrics (P50, P95, P99)."""
        pass
```

### 2.2. VAD Interface
```python
from dataclasses import dataclass

@dataclass
class VADResult:
    is_speech: bool
    speech_probability: float
    latency_ms: float

class BaseVAD(BaseAudioProcessor):
    @abstractmethod
    def process_frame(self, audio_frame: torch.Tensor, sample_rate: int = 16000) -> VADResult:
        """
        Processes a 32ms-64ms frame (512 or 1024 samples).
        Args:
            audio_frame: Float32 Tensor of shape [1, frame_len] or [frame_len].
        Returns:
            VADResult with speech detection boolean and probability.
        """
        pass
```

### 2.3. Anti-Spoofing & Deepfake Detector Interface
```python
@dataclass
class AntiSpoofResult:
    is_synthetic: bool
    synthetic_probability: float
    epistemic_uncertainty: float
    aleatoric_uncertainty: float
    feature_anomalies: Dict[str, float]
    latency_ms: float

class BaseAntiSpoofModel(BaseAudioProcessor):
    @abstractmethod
    def predict(self, audio_window: torch.Tensor) -> AntiSpoofResult:
        """
        Evaluates a 1.5s-2.0s sliding window for synthetic artifacts.
        Args:
            audio_window: Float32 Tensor of shape [1, 24000] (normalized to [-1.0, 1.0]).
        Returns:
            AntiSpoofResult containing probabilities, uncertainty, and forensic flags.
        """
        pass
```

### 2.4. Speaker Verification Interface
```python
@dataclass
class SpeakerVerificationResult:
    claimed_speaker_id: Optional[str]
    cosine_similarity: float
    is_match: bool
    threshold: float
    embedding: torch.Tensor  # Shape [192]
    latency_ms: float

class BaseSpeakerVerifier(BaseAudioProcessor):
    @abstractmethod
    def extract_embedding(self, audio_window: torch.Tensor) -> torch.Tensor:
        """
        Extracts 192-dimensional d-vector.
        Args:
            audio_window: Float32 Tensor [1, 24000]
        Returns:
            Float32 Tensor [192]
        """
        pass

    @abstractmethod
    def verify(
        self, 
        audio_window: torch.Tensor, 
        enrolled_embedding: torch.Tensor,
        threshold: float = 0.65
    ) -> SpeakerVerificationResult:
        """Compares incoming window embedding against an enrolled voiceprint."""
        pass
```

### 2.5. Acoustic Liveness & Replay Detector Interface
```python
@dataclass
class LivenessResult:
    is_live_acoustic: bool
    replay_probability: float
    channel_distortion_score: float
    sub_band_dispersion: float
    latency_ms: float

class BaseLivenessDetector(BaseAudioProcessor):
    @abstractmethod
    def evaluate(self, audio_window: torch.Tensor) -> LivenessResult:
        """
        Detects secondary loudspeaker transmission and room impulse anomalies.
        """
        pass
```

---

## 3. Tensor Contracts & Shapes

| Pipeline Stage | Input Tensor Shape | Input Type / Range | Output Tensor / Value | Output Range |
|---|---|---|---|---|
| **Audio Ingestion** | `bytes` (little-endian) | 16-bit PCM | Float32 `[N]` | `[-1.0, 1.0]` |
| **Silero VAD** | `[1, 512]` (32ms at 16kHz) | Float32 `[-1.0, 1.0]` | Scalar `prob` | `[0.0, 1.0]` |
| **Sliding Window** | `[1, 24000]` (1.5s at 16kHz)| Float32 `[-1.0, 1.0]` | `[1, 24000]` | Continuous stream |
| **WavLM / AASIST** | `[1, 24000]` | Float32 `[-1.0, 1.0]` | `logits: [1, 2]` | Unnormalized logits |
| **ECAPA-TDNN** | `[1, 24000]` | Float32 `[-1.0, 1.0]` | `embedding: [1, 192]` | Unit hypersphere $\|v\|=1$ |
| **Liveness STFT** | `[1, 24000]` | Float32 `[-1.0, 1.0]` | Spectrogram `[1, 257, 94]` | Power spec dB |

---

## 4. Uncertainty & Calibration Mathematics

A core requirement of VIGIL-AI is that **no prediction is made without an explicit quantification of uncertainty**.

### 4.1. Total Uncertainty Estimation
We decompose uncertainty into two types:
1. **Aleatoric Uncertainty (Data Noise / Channel Corruption):**
   Estimated via temperature-scaled predictive entropy:
   $$\mathcal{H}(p) = -\sum_{c \in \{\text{real}, \text{synth}\}} p_c \log_2(p_c)$$
   Normalized to $[0.0, 1.0]$:
   $$U_{\text{aleatoric}} = \frac{\mathcal{H}(p)}{\log_2(2)} = \mathcal{H}(p)$$

2. **Epistemic Uncertainty (Model Ignorance / Out-of-Distribution Data):**
   Estimated via Monte Carlo Dropout (MCD) or an ensemble variance over $M=5$ forward passes with stochastic sub-network activation:
   $$\sigma_{\text{epistemic}}^2 = \frac{1}{M} \sum_{m=1}^M (p_m - \bar{p})^2$$
   $$U_{\text{epistemic}} = \min(1.0, 2 \cdot \sqrt{\sigma_{\text{epistemic}}^2})$$

3. **Total Calibrated Uncertainty:**
   $$U_{\text{total}} = \alpha \cdot U_{\text{aleatoric}} + (1 - \alpha) \cdot U_{\text{epistemic}}, \quad \text{where } \alpha = 0.5$$

When $U_{\text{total}} > 0.60$, the decision engine forces a state transition to **UNCERTAIN / CHALLENGE**, preventing false positive alerts on poor cellular connections or noisy environments.
