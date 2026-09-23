"""
VIGIL-AI: Real Model Inference & Provenance Verification Test.
CRITICAL CONSTRAINT: ZERO MOCKING ALLOWED.
This test verifies that real AI models are loaded and executed on real audio files,
and that provenance metadata is genuinely produced by running inference.
"""
import os
import time
import pytest
import soundfile as sf
import numpy as np
import torch
from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.speaker_encoder import SpeakerModelRegistry, SpeechBrainECAPATDNNEncoder
from app.pipeline.deepfake_detector import DeepfakeModelRegistry, WavLMAASISTDetector


class TestRealModelInferenceProvenance:
    """Verifies that actual model inference executes without mocks, fallbacks, or synthetic substitutes."""

    @pytest.fixture(autouse=True)
    def check_audio_fixture(self):
        self.wav_path = os.path.join(
            os.path.dirname(__file__), "..", "fixtures", "speech_sample.wav"
        )
        assert os.path.exists(self.wav_path), f"Real test audio file not found at {self.wav_path}"
        self.audio, self.sr = sf.read(self.wav_path)
        assert len(self.audio) > 0, "Input audio is empty"
        assert self.sr == 16000, f"Expected 16kHz sample rate, got {self.sr}"
        self.duration_sec = len(self.audio) / self.sr
        assert self.duration_sec > 0.0, "Audio duration must be greater than 0"

    def test_stage2_ecapa_tdnn_real_neural_inference(self):
        """
        STAGE 2 VERIFICATION:
        1. Model must be genuine SpeechBrain ECAPA-TDNN loaded from disk.
        2. Must execute on real audio without mocking.
        3. Must produce 192-dimensional unit-normalized embedding.
        4. Latency must be strictly positive.
        5. Cosine similarity must reflect actual acoustic distance.
        """
        encoder = SpeakerModelRegistry.get_encoder()

        # 1. Assert encoder is the genuine SpeechBrain ECAPA-TDNN implementation
        assert isinstance(
            encoder, SpeechBrainECAPATDNNEncoder
        ), f"Expected SpeechBrainECAPATDNNEncoder, got {type(encoder)}"

        info = encoder.get_model_info()
        assert info["name"] == "SpeechBrain ECAPA-TDNN"
        assert "ECAPA-TDNN" in info["version"]
        assert info["embedding_dim"] == 192
        assert info["inference_source"] in ["MODEL_INFERENCE", "BACKEND_MODEL"]
        assert info["status"] == "READY"

        # 2. Verify model weights exist on disk
        model_path = info.get("model_path")
        assert model_path is not None and os.path.exists(model_path), f"Model path {model_path} does not exist"
        ckpt_path = os.path.join(model_path, "embedding_model.ckpt")
        assert os.path.exists(ckpt_path), f"Checkpoint embedding_model.ckpt not found at {ckpt_path}"
        assert os.path.getsize(ckpt_path) > 50_000_000, f"Checkpoint size unexpectedly small: {os.path.getsize(ckpt_path)} bytes"

        # 3. Perform real neural forward pass
        t0 = time.perf_counter()
        emb_a = encoder.encode(self.audio, sample_rate=self.sr)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        assert latency_ms > 0.0, "Latency must be strictly positive"
        assert isinstance(emb_a, np.ndarray), "Embedding must be a numpy ndarray"
        assert emb_a.shape == (192,), f"Embedding dimension must be exactly (192,), got {emb_a.shape}"
        assert emb_a.dtype == np.float32, f"Embedding dtype must be float32, got {emb_a.dtype}"

        # 4. Assert L2 normalization ||e||_2 == 1.0
        norm = float(np.linalg.norm(emb_a))
        assert abs(norm - 1.0) < 1e-3, f"Embedding must be L2 unit-normalized, got norm={norm}"

        # 5. Assert embedding is not degenerate (not all zeros or constant)
        assert not np.all(emb_a == 0), "Embedding contains only zeros"
        assert np.std(emb_a) > 1e-4, "Embedding has zero variance"

        # 6. Self-similarity test (Person A vs Person A must be 1.0)
        self_sim = float(np.dot(emb_a, emb_a))
        assert abs(self_sim - 1.0) < 1e-3, f"Self-similarity must be 1.0, got {self_sim}"

        # 7. Cross-similarity test with different audio (Person A vs Person B)
        t = np.linspace(0, self.duration_sec, len(self.audio), endpoint=False)
        different_speaker_audio = (0.5 * np.sin(2 * np.pi * 340 * t) + 0.3 * np.sin(2 * np.pi * 680 * t)).astype(np.float32)
        emb_b = encoder.encode(different_speaker_audio, sample_rate=self.sr)
        diff_sim = float(np.dot(emb_a, emb_b))

        # Different acoustic signal must have distinct embedding
        assert diff_sim < 0.90, f"Different speaker similarity too high: {diff_sim}"
        assert diff_sim != self_sim, "Model produced identical embeddings for distinct audio"

    def test_stage1_deepfake_detector_neural_inference(self):
        """
        STAGE 1 VERIFICATION:
        1. Model must be registered and ready.
        2. Forward pass executes through PyTorch neural network.
        3. Real inference latency > 0.
        4. Probabilities are strictly bounded in [0.0, 1.0].
        """
        detector = DeepfakeModelRegistry.get_detector()
        info = detector.get_model_info()

        assert info["status"] == "READY"
        assert info["target_sample_rate"] == 16000
        assert info["input_length_samples"] > 0

        # Perform forward pass on real audio
        t0 = time.perf_counter()
        res = detector.predict(self.audio)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert elapsed_ms > 0.0
        assert res.inference_latency_ms >= 0.0
        assert 0.0 <= res.spoof_probability <= 1.0
        assert 0.0 <= res.bonafide_probability <= 1.0
        assert 0.0 <= res.confidence <= 1.0
        assert res.label in ["bonafide", "spoof", "uncertain"]

    def test_voice_analysis_api_e2e_real_inference_provenance(self):
        """
        FULL PIPELINE E2E PROVENANCE TEST (ZERO MOCKING):
        Submits real speech_sample.wav to /api/v1/voice_analysis/voice.
        Verifies all stages report honest provenance without mocks.
        """
        client = TestClient(app)
        with open(self.wav_path, "rb") as f:
            resp = client.post(
                "/api/v1/voice_analysis/voice",
                files={"audio_file": ("speech_sample.wav", f, "audio/wav")},
            )

        assert resp.status_code == 200, f"API failed with status {resp.status_code}: {resp.text}"
        data = resp.json()

        # 1. Root telemetry
        assert "request_id" in data and len(data["request_id"]) > 0
        assert data["inference_source"] in ["BACKEND_MODEL", "MODEL_INFERENCE"]
        assert data["analysis_latency_ms"] > 0.0

        # 2. Stage 1 Provenance
        assert "stage1" in data and data["stage1"] is not None
        s1 = data["stage1"]
        assert s1["inference_source"] == "MODEL_INFERENCE"
        assert s1["model"] is not None
        assert s1["model_version"] is not None
        assert 0.0 <= s1["clone_probability"] <= 1.0
        assert s1["latency_ms"] > 0.0

        # 3. Stage 2 Provenance
        assert "stage2" in data and data["stage2"] is not None
        s2 = data["stage2"]
        assert s2["inference_source"] == "MODEL_INFERENCE"
        assert s2["model"] == "SpeechBrain ECAPA-TDNN"
        assert s2["embedding_dim"] == 192
        assert 0.0 <= s2["similarity_score"] <= 1.0
        assert s2["threshold"] == 0.65
        assert s2["latency_ms"] > 0.0

        # 4. Stage 3 Provenance
        assert "stage3" in data and data["stage3"] is not None
        s3 = data["stage3"]
        assert s3["inference_source"] == "RULE_ENGINE"
        assert s3["engine"] is not None
        assert s3["latency_ms"] >= 0.0

        # 5. Risk Decision Consistency
        assert data["threat_level"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        assert data["action"] in ["ALLOW", "MONITOR", "CHALLENGE", "BLOCK"]
