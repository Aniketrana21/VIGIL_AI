import os
import wave
import numpy as np
import pytest
from app.core.config import settings
from app.db.embedding_store import (
    EmbeddingStore,
    InMemoryVectorEmbeddingStore,
    SpeakerProfile,
    get_embedding_store,
    set_embedding_store,
)
from app.pipeline.deepfake_detector import DeepfakeModelRegistry
from app.pipeline.session_manager import StreamingSessionManager
from app.pipeline.speaker_encoder import (
    ECAPATDNNEncoder,
    SpeakerEncoder,
    SpeakerModelRegistry,
)
from app.pipeline.speaker_service import (
    SpeakerEnrollmentResult,
    SpeakerEnrollmentService,
    SpeakerThresholdCalibrator,
    SpeakerVerificationResult,
    SpeakerVerificationService,
)


def generate_speaker_utterance(
    f0: float = 130.0,
    duration_sec: float = 1.5,
    sample_rate: int = 16000,
    jitter: float = 0.0,
) -> np.ndarray:
    """Generates synthetic harmonic speech with controlled fundamental frequency and formants."""
    n_samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, n_samples, endpoint=False)
    signal = np.zeros(n_samples, dtype=np.float32)

    # Harmonics
    for h in range(1, 8):
        f = (f0 + jitter) * h
        if f < sample_rate / 2:
            signal += (0.4 / h) * np.sin(2 * np.pi * f * t).astype(np.float32)

    # Formant filtering (resonant vocal cavities)
    f1 = 500.0 + f0
    f2 = 1500.0 + f0 * 2
    signal += 0.3 * np.sin(2 * np.pi * f1 * t).astype(np.float32)
    signal += 0.2 * np.sin(2 * np.pi * f2 * t).astype(np.float32)

    # Speech syllable amplitude envelope
    envelope = 0.5 * (1.0 + np.sin(2 * np.pi * 3.0 * t))
    signal *= envelope.astype(np.float32)

    max_val = np.max(np.abs(signal)) + 1e-6
    return (signal / max_val * 0.8).astype(np.float32)


def generate_cloned_voice_of_speaker(
    f0: float = 130.0,
    duration_sec: float = 2.0,
    sample_rate: int = 16000,
) -> np.ndarray:
    """
    Generates a voice clone that mimics Speaker A's vocal tract pitch (130Hz)
    BUT contains neural vocoder artifacts (sharp 6.0kHz cutoff and vocoder phase dispersion).
    """
    n_samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, n_samples, endpoint=False)
    signal = np.zeros(n_samples, dtype=np.float32)

    # Incoherent phase randomized harmonics (neural vocoder artifact)
    for h in range(1, 8):
        phase = np.random.uniform(-np.pi, np.pi)
        signal += (0.4 / h) * np.sin(2 * np.pi * f0 * h * t + phase).astype(np.float32)

    # Formant filtering
    f1 = 500.0 + f0
    f2 = 1500.0 + f0 * 2
    signal += 0.3 * np.sin(2 * np.pi * f1 * t).astype(np.float32)
    signal += 0.2 * np.sin(2 * np.pi * f2 * t).astype(np.float32)

    # Speech syllable amplitude envelope
    envelope = 0.5 * (1.0 + np.sin(2 * np.pi * 3.0 * t))
    signal *= envelope.astype(np.float32)

    # Sharp vocoder cutoff above 6.0kHz
    fft = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate)
    fft[freqs > 6000] *= 0.005
    cloned_audio = np.fft.irfft(fft, n=n_samples).astype(np.float32)

    max_val = np.max(np.abs(cloned_audio)) + 1e-6
    return (cloned_audio / max_val * 0.8).astype(np.float32)


class TestPhase5SpeakerVerification:
    """Comprehensive test matrix for Phase 5 Speaker Verification & Anti-Spoofing Independence."""

    @pytest.fixture(autouse=True)
    def setup_services(self):
        self.store = InMemoryVectorEmbeddingStore()
        set_embedding_store(self.store)

        self.encoder = SpeakerModelRegistry.get_encoder()
        self.enroll_svc = SpeakerEnrollmentService(encoder=self.encoder, store=self.store, min_utterances=3)
        self.verify_svc = SpeakerVerificationService(
            encoder=self.encoder,
            store=self.store,
            match_threshold=0.75,
            unknown_threshold=0.60,
        )

    def test_speaker_encoder_interface_and_warmup(self):
        """Validates SpeakerEncoder interface contract, warmup, and strict L2-normalization."""
        warmup_ms = self.encoder.warmup(device="cpu")
        assert warmup_ms > 0.0
        assert isinstance(self.encoder, SpeakerEncoder)

        # Vector dimension check
        test_audio = np.random.normal(0, 0.1, 16000).astype(np.float32)
        emb = self.encoder.encode(test_audio)
        assert emb.shape == (192,)
        assert abs(np.linalg.norm(emb) - 1.0) < 1e-4, "Speaker embedding must be unit-normalized (L2 norm == 1.0)"

    @pytest.mark.asyncio
    async def test_multi_utterance_enrollment_enforcement(self):
        """Requirement 4: Require multiple enrollment utterances (>= 3)."""
        u1 = generate_speaker_utterance(f0=130.0)
        u2 = generate_speaker_utterance(f0=132.0)

        # Attempting with < 3 utterances must be rejected
        with pytest.raises(ValueError, match="at least 3"):
            await self.enroll_svc.enroll_speaker("alice", "Alice Smith", [u1, u2])

        # 3 utterances must succeed and produce an L2-normalized centroid
        u3 = generate_speaker_utterance(f0=131.0)
        result = await self.enroll_svc.enroll_speaker("alice", "Alice Smith", [u1, u2, u3])

        assert isinstance(result, SpeakerEnrollmentResult)
        assert result.success is True
        assert result.speaker_id == "alice"
        assert result.num_utterances == 3
        assert result.intra_speaker_consistency >= 0.70

    @pytest.mark.asyncio
    async def test_same_speaker_verification(self):
        """Test Case 1: Same speaker yields high similarity and match=True."""
        # 1. Enroll Alice
        u1 = generate_speaker_utterance(f0=130.0)
        u2 = generate_speaker_utterance(f0=132.0)
        u3 = generate_speaker_utterance(f0=131.0)
        await self.enroll_svc.enroll_speaker("alice", "Alice Smith", [u1, u2, u3])

        # 2. Candidate utterance from Alice
        cand_alice = generate_speaker_utterance(f0=131.5)
        res = await self.verify_svc.verify(cand_alice, claimed_speaker_id="alice")

        assert isinstance(res, SpeakerVerificationResult)
        assert res.match is True
        assert res.speaker_id == "alice"
        assert res.similarity >= 0.75
        assert res.confidence >= 0.50

        # Conformance to required schema
        d = res.to_dict()
        assert "speaker_id" in d
        assert "similarity" in d
        assert "match" in d
        assert "confidence" in d

    @pytest.mark.asyncio
    async def test_different_speaker_rejection(self):
        """Test Case 2: Different speaker yields low similarity and match=False."""
        # 1. Enroll Alice (130Hz)
        u1 = generate_speaker_utterance(f0=130.0)
        u2 = generate_speaker_utterance(f0=132.0)
        u3 = generate_speaker_utterance(f0=131.0)
        await self.enroll_svc.enroll_speaker("alice", "Alice Smith", [u1, u2, u3])

        # 2. Candidate utterance from Bob (350Hz - distinct fundamental and formants)
        cand_bob = generate_speaker_utterance(f0=350.0)
        res = await self.verify_svc.verify(cand_bob, claimed_speaker_id="alice")

        assert res.match is False
        assert res.speaker_id == "UNKNOWN"
        assert res.similarity < self.verify_svc.match_threshold
        assert res.confidence < 0.40

    @pytest.mark.asyncio
    async def test_cloned_speaker_independence(self):
        """
        Test Case 3: Cloned speaker demonstrating signal independence.
        CRITICAL SPECIFICATION:
        Speaker similarity does NOT prove that audio is genuine.
        A cloned voice of Alice may match Alice's speaker profile (high similarity),
        BUT the deepfake detector must flag it as synthetic (high spoof probability).
        Both signals must remain strictly independent.
        """
        # 1. Enroll Alice
        u1 = generate_speaker_utterance(f0=130.0)
        u2 = generate_speaker_utterance(f0=132.0)
        u3 = generate_speaker_utterance(f0=131.0)
        await self.enroll_svc.enroll_speaker("alice", "Alice Smith", [u1, u2, u3])

        # 2. Generate a synthetic voice clone of Alice
        cloned_alice = generate_cloned_voice_of_speaker(f0=130.0, duration_sec=2.0)

        # 3. Evaluate on Speaker Verification Service (Signal 1: Identity)
        spk_res = await self.verify_svc.verify(cloned_alice, claimed_speaker_id="alice")

        # 4. Evaluate on Deepfake Anti-Spoofing Detector (Signal 2: Authenticity)
        df_detector = DeepfakeModelRegistry.get_detector()
        df_res = df_detector.predict(cloned_alice)

        # Identity Signal: Cloned voice sounds like Alice -> High similarity / Match
        assert spk_res.similarity >= 0.70, f"Cloned voice failed to match Alice's identity (sim={spk_res.similarity})"

        # Anti-Spoofing Signal: Artifacts present -> Detected as synthetic clone
        assert df_res.spoof_probability >= 0.55, f"Deepfake engine failed to detect clone (spoof_prob={df_res.spoof_probability})"
        assert df_res.label in ["spoof", "uncertain"]

        # Confirm independence: Speaker match is True, but Spoof is True
        print(f"\n[INDEPENDENCE CHECK] Speaker Match: {spk_res.match} (Sim: {spk_res.similarity:.2f}) | Spoof Prob: {df_res.spoof_probability:.2f} ({df_res.label.upper()})")

    @pytest.mark.asyncio
    async def test_noisy_speaker_graceful_handling(self):
        """Test Case 4: Noisy speaker evaluates without exceptions and degrades confidence gracefully."""
        u1 = generate_speaker_utterance(f0=130.0)
        u2 = generate_speaker_utterance(f0=132.0)
        u3 = generate_speaker_utterance(f0=131.0)
        await self.enroll_svc.enroll_speaker("alice", "Alice Smith", [u1, u2, u3])

        # Add Gaussian noise
        clean = generate_speaker_utterance(f0=131.0)
        noise = np.random.normal(0, 0.25, len(clean)).astype(np.float32)
        noisy = clean + noise

        res_clean = await self.verify_svc.verify(clean, claimed_speaker_id="alice")
        res_noisy = await self.verify_svc.verify(noisy, claimed_speaker_id="alice")

        assert not np.isnan(res_noisy.similarity)
        assert not np.isnan(res_noisy.confidence)
        # Noise should slightly lower similarity/confidence relative to clean
        assert res_noisy.confidence <= res_clean.confidence

    @pytest.mark.asyncio
    async def test_short_utterance_safety(self):
        """Test Case 5: Short utterance (< 0.4s) is padded safely and handled without crashing."""
        short_audio = np.random.normal(0, 0.1, 1600).astype(np.float32)  # 100ms
        res = await self.verify_svc.verify(short_audio, claimed_speaker_id="alice")

        assert isinstance(res, SpeakerVerificationResult)
        assert not np.isnan(res.similarity)
        assert res.match is False

    @pytest.mark.asyncio
    async def test_unknown_speaker_openset(self):
        """Test Case 6: Unknown / unenrolled speaker returns speaker_id='UNKNOWN' and match=False."""
        # Clear store so no speakers are enrolled
        await self.store.clear()

        audio = generate_speaker_utterance(f0=160.0)
        res = await self.verify_svc.verify(audio)  # 1:N open search with empty gallery

        assert res.match is False
        assert res.speaker_id == "UNKNOWN"
        assert res.similarity == 0.0

        # Now enroll Alice (130Hz) and test an unknown visitor (350Hz)
        u1 = generate_speaker_utterance(f0=130.0)
        u2 = generate_speaker_utterance(f0=132.0)
        u3 = generate_speaker_utterance(f0=131.0)
        await self.enroll_svc.enroll_speaker("alice", "Alice Smith", [u1, u2, u3])

        visitor = generate_speaker_utterance(f0=350.0)
        res_visitor = await self.verify_svc.verify(visitor)  # 1:N open search

        assert res_visitor.match is False
        assert res_visitor.speaker_id == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_zero_raw_voice_storage(self):
        """
        Requirements 1 & 2:
        Never store raw voice recordings by default.
        Store embeddings securely.
        """
        u1 = generate_speaker_utterance(f0=130.0)
        u2 = generate_speaker_utterance(f0=132.0)
        u3 = generate_speaker_utterance(f0=131.0)
        await self.enroll_svc.enroll_speaker("alice", "Alice Smith", [u1, u2, u3])

        profile = await self.store.get_speaker_profile("alice")
        assert profile is not None
        assert isinstance(profile.embedding, list)
        assert len(profile.embedding) == 192

        # Verify NO raw audio bytes, buffers, or waveforms are stored
        for key, val in profile.metadata.items():
            assert not isinstance(val, (bytes, bytearray, np.ndarray))
            assert "pcm" not in key.lower()
            assert "raw" not in key.lower()

    def test_threshold_calibration_utility(self):
        """Requirement 9: Calibrate thresholds using validation data."""
        # Simulated validation score distributions
        genuine_scores = [0.82, 0.85, 0.88, 0.91, 0.94, 0.96]
        impostor_scores = [0.25, 0.32, 0.41, 0.49, 0.55, 0.62]

        calib = SpeakerThresholdCalibrator.compute_eer(genuine_scores, impostor_scores)
        assert "eer" in calib
        assert "eer_threshold" in calib
        assert "recommended_match_threshold" in calib
        assert 0.50 <= calib["recommended_match_threshold"] <= 0.85

    @pytest.mark.asyncio
    async def test_streaming_session_speaker_telemetry(self):
        """Validates that StreamingSessionManager emits independent speaker verification telemetry."""
        path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "speech_sample.wav")
        with wave.open(path, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
            speech = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

        # Enroll Alice using reference speech slices
        u1 = speech
        u2 = speech
        u3 = speech
        await self.enroll_svc.enroll_speaker("alice", "Alice Smith", [u1, u2, u3])

        session = StreamingSessionManager(
            session_id="stream_speaker_test",
            sample_rate=16000,
            claimed_speaker_id="alice",
            speaker_verifier=self.verify_svc,
        )

        from app.pipeline.audio_chunk import AudioChunk
        chunk_size = 1600

        telemetry = {}
        for i in range(0, 32000, chunk_size):
            chunk_bytes = (speech[i : i + chunk_size] * 32767.0).astype(np.int16).tobytes()
            ac = AudioChunk(
                sequence_id=(i // chunk_size) + 1,
                timestamp_ms=1726500000000 + i * 10,
                sample_rate=16000,
                channels=1,
                pcm_bytes=chunk_bytes,
            )
            _, telemetry = session.ingest_packet(ac.serializeBinary())

        assert "speaker" in telemetry
        spk_telem = telemetry["speaker"]
        assert "speaker_id" in spk_telem
        assert "similarity" in spk_telem
        assert "match" in spk_telem
        assert "confidence" in spk_telem
        assert spk_telem["speaker_id"] == "alice"
        assert spk_telem["match"] is True
