import os
import wave
import numpy as np
import pytest
import torch
from app.pipeline.deepfake_detector import (
    DeepfakeDetector,
    DeepfakeModelRegistry,
    DetectionResult,
    WavLMAASISTDetector,
)
from app.pipeline.session_manager import StreamingSessionManager


def load_test_speech_fixture() -> np.ndarray:
    """Loads 2-second reference speech audio."""
    path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "speech_sample.wav")
    with wave.open(path, "rb") as wf:
        n = wf.getnframes()
        raw = wf.readframes(n)
        return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def generate_synthetic_clone_audio(duration_sec: float = 2.0, sample_rate: int = 16000) -> np.ndarray:
    """
    Generates synthetic speech with characteristic vocoder artifacts:
    - Phase incoherence / jitter
    - Sharp high-frequency cutoff above 6.5kHz
    """
    n_samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, n_samples, endpoint=False)
    f0 = 130.0
    signal = np.zeros(n_samples, dtype=np.float32)

    # Incoherent phase randomized harmonics
    for h in range(1, 9):
        phase = np.random.uniform(-np.pi, np.pi)
        signal += (0.25 / h) * np.sin(2 * np.pi * f0 * h * t + phase).astype(np.float32)

    # Envelope modulation
    envelope = 0.5 * (1.0 + np.sin(2 * np.pi * 3.0 * t))
    signal *= envelope.astype(np.float32)

    # Apply sharp vocoder cutoff at 6.0kHz
    fft = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate)
    fft[freqs > 6000] *= 0.005
    artifact_audio = np.fft.irfft(fft, n=n_samples).astype(np.float32)
    max_val = np.max(np.abs(artifact_audio)) + 1e-6
    return (artifact_audio / max_val * 0.8).astype(np.float32)


class TestPhase3DeepfakeDetector:
    """Comprehensive test matrix for Phase 3 Voice Anti-Spoofing Detector."""

    @pytest.fixture(autouse=True)
    def setup_detector(self):
        self.detector = WavLMAASISTDetector(
            device="cpu",
            spoof_threshold=0.65,
            bonafide_threshold=0.35,
            min_confidence=0.55,
        )

    def test_model_interface_and_warmup(self):
        """Requirements 10 & 11: Interface contract and warmup execution."""
        warmup_ms = self.detector.warmup(device="cpu")
        assert warmup_ms > 0.0
        assert isinstance(self.detector, DeepfakeDetector)
        assert self.detector.MODEL_VERSION == "Vigil-WavLM-AASIST-v1.0"

        # Singleton registry test
        det1 = DeepfakeModelRegistry.get_detector()
        det2 = DeepfakeModelRegistry.get_detector()
        assert det1 is det2

    def test_16khz_audio_normalization(self):
        """Requirement 2: Correct zero-mean unit-variance normalization."""
        # Unnormalized high-DC audio
        raw = np.random.normal(loc=5.0, scale=3.0, size=32000).astype(np.float32)
        norm_tensor, rms_db, is_silence = self.detector._normalize_and_pad(raw)

        norm_np = norm_tensor.numpy()
        assert abs(np.mean(norm_np)) < 1e-3, "Normalized audio mean is not zero"
        assert abs(np.std(norm_np) - 1.0) < 1e-2, "Normalized audio std is not unit variance"
        assert not is_silence

    def test_short_audio_padding(self):
        """Requirements 3 & 4: Fixed input length and safe short audio padding."""
        short_audio = np.random.normal(0, 0.2, 1600).astype(np.float32)  # 100ms
        res = self.detector.predict(short_audio)

        assert isinstance(res, DetectionResult)
        assert res.label in ["bonafide", "spoof", "uncertain"]
        assert 0.0 <= res.spoof_probability <= 1.0
        assert 0.0 <= res.bonafide_probability <= 1.0
        assert res.inference_latency_ms > 0.0

    def test_silence_safety(self):
        """Requirement 5: Digital and ambient silence safe handling."""
        # Digital silence
        digital_silence = np.zeros(32000, dtype=np.float32)
        res_dig = self.detector.predict(digital_silence)
        assert res_dig.label == "uncertain"
        assert res_dig.confidence <= 0.20
        assert not np.isnan(res_dig.spoof_probability)

        # Ambient low-level noise
        ambient_quiet = np.random.normal(0, 0.0001, 32000).astype(np.float32)
        res_amb = self.detector.predict(ambient_quiet)
        assert res_amb.label == "uncertain"

    def test_batch_inference_parity(self):
        """Requirement 6: Batch inference parity with single-item predictions."""
        audio1 = generate_synthetic_clone_audio(2.0)
        audio2 = load_test_speech_fixture()

        batch_results = self.detector.predict_batch([audio1, audio2])
        assert len(batch_results) == 2

        res1 = self.detector.predict(audio1)
        res2 = self.detector.predict(audio2)

        assert batch_results[0].label == res1.label
        assert abs(batch_results[0].spoof_probability - res1.spoof_probability) < 0.05
        assert abs(batch_results[1].bonafide_probability - res2.bonafide_probability) < 0.05

    def test_confidence_threshold_uncertainty(self):
        """Requirement 14: Do not return binary fake/real when confidence is insufficient."""
        low_confidence_detector = WavLMAASISTDetector(
            device="cpu",
            min_confidence=0.99,  # Unattainably high confidence threshold
        )
        audio = load_test_speech_fixture()
        res = low_confidence_detector.predict(audio)
        assert res.label == "uncertain", f"Expected 'uncertain' on low confidence, got '{res.label}'"

    def test_synthetic_vs_bonafide_separation(self):
        """Test detection differentiation between synthetic vocoder artifacts and bonafide speech."""
        synth_audio = generate_synthetic_clone_audio(2.0)
        res_synth = self.detector.predict(synth_audio)

        bonafide_audio = load_test_speech_fixture()
        res_bonafide = self.detector.predict(bonafide_audio)

        # Synthetic speech should exhibit higher spoof probability than bonafide speech
        assert res_synth.spoof_probability > res_bonafide.spoof_probability
        schema = res_synth.to_dict()
        assert "label" in schema
        assert "spoof_probability" in schema
        assert "bonafide_probability" in schema
        assert "confidence" in schema
        assert "inference_latency_ms" in schema
        assert "model_version" in schema

    def test_streaming_session_deepfake_timeline(self):
        """Requirement 16: Streaming inference over WebSocket session with timeline generation."""
        session = StreamingSessionManager(
            session_id="phase3_stream_test",
            sample_rate=16000,
            window_seconds=2.0,
            deepfake_detector=self.detector,
        )

        speech = load_test_speech_fixture()  # 2.0s = 32,000 samples
        chunk_size = 1600  # 100ms chunks

        from app.pipeline.audio_chunk import AudioChunk
        # Stream speech chunks using binary protocol
        for i in range(0, len(speech), chunk_size):
            chunk_bytes = (speech[i : i + chunk_size] * 32767.0).astype(np.int16).tobytes()
            ac = AudioChunk(
                sequence_id=(i // chunk_size) + 1,
                timestamp_ms=1726500000000 + i * 10,
                sample_rate=16000,
                channels=1,
                pcm_bytes=chunk_bytes,
            )
            windows, telemetry = session.ingest_packet(ac.serializeBinary())

        # Telemetry should contain deepfake results and timeline
        assert "deepfake" in telemetry
        df_telem = telemetry["deepfake"]
        assert "spoof_probability" in df_telem
        assert "bonafide_probability" in df_telem
        assert "confidence" in df_telem
        assert "timeline" in df_telem
        assert len(df_telem["timeline"]) > 0

        # Timeline event structure verification
        first_event = df_telem["timeline"][0]
        assert "time" in first_event
        assert "label" in first_event
        assert "spoof_probability" in first_event
        assert "confidence" in first_event
        assert first_event["label"] in ["BONAFIDE", "SUSPICIOUS", "SPOOF", "UNCERTAIN"]
