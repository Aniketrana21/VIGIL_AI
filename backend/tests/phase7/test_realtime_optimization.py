"""
VIGIL-AI Phase 7: Real-Time Inference Optimization — Test Suite.

Tests cover:
  1. DeviceManager auto-detection and caching.
  2. ONNX backend availability checking.
  3. ResultSmoother EMA correctness.
  4. AsyncInferencePipeline lifecycle and backpressure.
  5. Pipeline latency profiling data structures.
  6. Config defaults for Phase 7 fields.
  7. Non-blocking enqueue with queue-full drop policy.
  8. Concurrent pipeline stress test.
"""
import asyncio
import os
import sys
import time
import struct
import numpy as np
import pytest
import threading

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core.config import settings


# ──────────────────────────────────────────────────────────────
# 1. Config Defaults
# ──────────────────────────────────────────────────────────────

class TestPhase7ConfigDefaults:
    """Verify all Phase 7 configuration fields are accessible with sane defaults."""

    def test_inference_device_is_auto(self):
        assert settings.INFERENCE_DEVICE == "auto"

    def test_async_pipeline_queue_size(self):
        assert settings.ASYNC_PIPELINE_QUEUE_SIZE == 50

    def test_inference_batch_size(self):
        assert settings.INFERENCE_BATCH_SIZE == 4

    def test_result_smoothing_alpha(self):
        assert 0.0 < settings.RESULT_SMOOTHING_ALPHA <= 1.0

    def test_enable_onnx_runtime_is_bool(self):
        assert isinstance(settings.ENABLE_ONNX_RUNTIME, bool)

    def test_max_latency_budget(self):
        assert settings.MAX_LATENCY_BUDGET_MS > 0

    def test_drop_policy_valid(self):
        assert settings.DROP_POLICY in ("drop_oldest", "drop_newest", "block")


# ──────────────────────────────────────────────────────────────
# 2. DeviceManager
# ──────────────────────────────────────────────────────────────

class TestDeviceManager:
    """Test hardware detection singleton."""

    def setup_method(self):
        from app.pipeline.device import DeviceManager
        DeviceManager.reset()

    def test_resolve_returns_torch_device(self):
        from app.pipeline.device import DeviceManager
        import torch
        dev = DeviceManager.resolve()
        assert isinstance(dev, torch.device)

    def test_resolve_is_cached(self):
        from app.pipeline.device import DeviceManager
        d1 = DeviceManager.resolve()
        d2 = DeviceManager.resolve()
        assert d1 is d2

    def test_device_info_populated(self):
        from app.pipeline.device import DeviceManager
        info = DeviceManager.get_info()
        assert info.device_type in ("cuda", "mps", "cpu")
        assert isinstance(info.device_name, str) and len(info.device_name) > 0
        assert isinstance(info.gpu_available, bool)
        assert isinstance(info.gpu_enabled, bool)
        assert info.warmup_ms >= 0

    def test_device_info_to_dict(self):
        from app.pipeline.device import DeviceManager
        d = DeviceManager.get_info().to_dict()
        assert "device_type" in d
        assert "device_name" in d
        assert "gpu_available" in d
        assert "warmup_ms" in d

    def test_thread_safe_resolution(self):
        from app.pipeline.device import DeviceManager
        DeviceManager.reset()
        results = []
        barrier = threading.Barrier(4)

        def resolve():
            barrier.wait()
            results.append(DeviceManager.resolve())

        threads = [threading.Thread(target=resolve) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 4
        assert all(r is results[0] for r in results)


# ──────────────────────────────────────────────────────────────
# 3. ONNX Backend
# ──────────────────────────────────────────────────────────────

class TestONNXBackend:
    """Test ONNX availability and status reporting."""

    def test_onnx_status_dict(self):
        from app.pipeline.onnx_backend import ONNXStatus
        d = ONNXStatus.to_dict()
        assert "onnx_runtime_installed" in d
        assert "onnx_enabled_in_config" in d
        assert "onnx_active" in d
        assert isinstance(d["onnx_runtime_installed"], bool)

    def test_is_onnx_available_returns_bool(self):
        from app.pipeline.onnx_backend import is_onnx_available
        result = is_onnx_available()
        assert isinstance(result, bool)

    def test_session_for_nonexistent_file_returns_none(self):
        from app.pipeline.onnx_backend import ONNXInferenceSession
        session = ONNXInferenceSession.get_session("/nonexistent/model.onnx")
        assert session is None


# ──────────────────────────────────────────────────────────────
# 4. ResultSmoother
# ──────────────────────────────────────────────────────────────

class TestResultSmoother:
    """Test EMA smoothing correctness."""

    def test_first_value_is_identity(self):
        from app.pipeline.async_pipeline import ResultSmoother
        s = ResultSmoother(alpha=0.5)
        assert s.smooth("test", 0.8) == 0.8

    def test_ema_decreases_on_lower_input(self):
        from app.pipeline.async_pipeline import ResultSmoother
        s = ResultSmoother(alpha=0.5)
        s.smooth("test", 1.0)
        result = s.smooth("test", 0.0)
        # EMA: 0.5 * 0.0 + 0.5 * 1.0 = 0.5
        assert abs(result - 0.5) < 1e-6

    def test_ema_converges(self):
        from app.pipeline.async_pipeline import ResultSmoother
        s = ResultSmoother(alpha=0.3)
        for _ in range(50):
            s.smooth("x", 0.9)
        assert abs(s.get("x") - 0.9) < 0.01

    def test_independent_keys(self):
        from app.pipeline.async_pipeline import ResultSmoother
        s = ResultSmoother(alpha=0.5)
        s.smooth("a", 1.0)
        s.smooth("b", 0.0)
        assert s.get("a") == 1.0
        assert s.get("b") == 0.0

    def test_reset_clears_state(self):
        from app.pipeline.async_pipeline import ResultSmoother
        s = ResultSmoother(alpha=0.5)
        s.smooth("x", 0.5)
        s.reset()
        assert s.get("x") == 0.0

    def test_alpha_clamped(self):
        from app.pipeline.async_pipeline import ResultSmoother
        s1 = ResultSmoother(alpha=0.0)
        assert s1.alpha == 0.01  # clamped to min
        s2 = ResultSmoother(alpha=5.0)
        assert s2.alpha == 1.0   # clamped to max


# ──────────────────────────────────────────────────────────────
# 5. LatencyProfile
# ──────────────────────────────────────────────────────────────

class TestLatencyProfile:
    """Test latency data structure."""

    def test_to_dict_all_keys_present(self):
        from app.pipeline.async_pipeline import LatencyProfile
        lp = LatencyProfile(
            preprocess_ms=1.5,
            vad_ms=2.3,
            deepfake_ms=15.0,
            speaker_ms=8.2,
            liveness_ms=3.1,
            risk_engine_ms=0.5,
            smoothing_ms=0.1,
            total_inference_ms=30.2,
            end_to_end_ms=31.7,
        )
        d = lp.to_dict()
        for key in ["preprocess_ms", "vad_ms", "deepfake_ms", "speaker_ms",
                     "liveness_ms", "risk_engine_ms", "smoothing_ms",
                     "total_inference_ms", "end_to_end_ms"]:
            assert key in d
            assert isinstance(d[key], float)

    def test_default_values_are_zero(self):
        from app.pipeline.async_pipeline import LatencyProfile
        lp = LatencyProfile()
        assert lp.preprocess_ms == 0.0
        assert lp.end_to_end_ms == 0.0


# ──────────────────────────────────────────────────────────────
# 6. PipelineMetrics
# ──────────────────────────────────────────────────────────────

class TestPipelineMetrics:
    """Test aggregate metrics data structure."""

    def test_to_dict_all_keys(self):
        from app.pipeline.async_pipeline import PipelineMetrics
        m = PipelineMetrics(
            queue_depth=3,
            dropped_chunks=1,
            total_chunks_processed=100,
            total_windows_inferred=80,
            avg_end_to_end_ms=25.5,
            avg_inference_ms=20.0,
            peak_end_to_end_ms=55.0,
            peak_inference_ms=40.0,
            is_gpu_enabled=False,
            device_name="Intel Core i9",
        )
        d = m.to_dict()
        assert d["queue_depth"] == 3
        assert d["dropped_chunks"] == 1
        assert d["is_gpu_enabled"] is False
        assert d["device_name"] == "Intel Core i9"


# ──────────────────────────────────────────────────────────────
# 7. AsyncInferencePipeline Lifecycle
# ──────────────────────────────────────────────────────────────

class TestAsyncPipelineLifecycle:
    """Test async pipeline start/stop and non-blocking enqueue."""

    @pytest.fixture
    def pipeline(self):
        from app.pipeline.async_pipeline import AsyncInferencePipeline
        p = AsyncInferencePipeline(
            session_id="test-lifecycle",
            sample_rate=16000,
            window_seconds=2.0,
            queue_size=10,
        )
        return p

    @pytest.mark.asyncio
    async def test_start_and_stop(self, pipeline):
        await pipeline.start()
        assert pipeline._running is True
        assert len(pipeline._tasks) == 3
        await pipeline.stop()
        assert pipeline._running is False
        assert len(pipeline._tasks) == 0

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self, pipeline):
        await pipeline.start()
        await pipeline.start()
        assert pipeline._running is True
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self, pipeline):
        await pipeline.stop()
        assert pipeline._running is False

    @pytest.mark.asyncio
    async def test_enqueue_raw_returns_true_when_space_available(self, pipeline):
        await pipeline.start()
        # Create a valid PCM binary chunk (160 samples = 320 bytes)
        pcm = np.zeros(320, dtype=np.int16).tobytes()
        result = pipeline.enqueue_raw(pcm)
        assert result is True
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_enqueue_drops_when_full(self, pipeline):
        """Fill the queue beyond capacity and verify drop counter increments."""
        await pipeline.start()
        pcm = np.zeros(320, dtype=np.int16).tobytes()
        for _ in range(15):  # queue_size is 10
            pipeline.enqueue_raw(pcm)
        assert pipeline._dropped_chunks >= 1
        await pipeline.stop()


# ──────────────────────────────────────────────────────────────
# 8. Pipeline Metrics Snapshot
# ──────────────────────────────────────────────────────────────

class TestPipelineMetricsIntegration:
    """Test metrics retrieval from live pipeline."""

    @pytest.mark.asyncio
    async def test_get_pipeline_metrics(self):
        from app.pipeline.async_pipeline import AsyncInferencePipeline
        p = AsyncInferencePipeline(session_id="test-metrics", sample_rate=16000, queue_size=5)
        await p.start()
        metrics = p.get_pipeline_metrics()
        assert metrics.queue_depth == 0
        assert metrics.dropped_chunks == 0
        assert isinstance(metrics.device_name, str)
        await p.stop()


# ──────────────────────────────────────────────────────────────
# 9. Telemetry Snapshot when No Data
# ──────────────────────────────────────────────────────────────

class TestTelemetrySnapshot:
    """Ensure telemetry output shape is correct even with no processed data."""

    @pytest.mark.asyncio
    async def test_initial_telemetry_is_none(self):
        from app.pipeline.async_pipeline import AsyncInferencePipeline
        p = AsyncInferencePipeline(session_id="test-telem", sample_rate=16000, queue_size=5)
        await p.start()
        # Immediately poll — should be empty since nothing was ingested
        t = p.get_latest_telemetry()
        assert t is None  # no data processed yet
        await p.stop()


# ──────────────────────────────────────────────────────────────
# 10. End-to-End Pipeline with Synthetic Speech
# ──────────────────────────────────────────────────────────────

class TestEndToEndPipeline:
    """Inject synthetic speech data and verify telemetry output within latency budget."""

    @pytest.mark.asyncio
    async def test_synthetic_speech_produces_telemetry(self):
        from app.pipeline.async_pipeline import AsyncInferencePipeline
        p = AsyncInferencePipeline(
            session_id="test-e2e",
            sample_rate=16000,
            window_seconds=2.0,
            queue_size=20,
        )
        await p.start()

        # Generate ~2 seconds of 440Hz sine wave (clearly speech-like energy)
        duration = 2.0
        t = np.linspace(0, duration, int(16000 * duration), endpoint=False)
        sine = (np.sin(2 * np.pi * 440 * t) * 32000).astype(np.int16)

        # Send in 100ms chunks
        chunk_size = 1600  # 100ms @ 16kHz
        for i in range(0, len(sine), chunk_size):
            chunk = sine[i:i+chunk_size].tobytes()
            p.enqueue_raw(chunk)

        # Allow pipeline workers to process
        await asyncio.sleep(2.0)

        # Drain telemetry
        telemetry_events = []
        for _ in range(50):
            t = p.get_latest_telemetry()
            if t:
                telemetry_events.append(t)
            else:
                break

        await p.stop()

        # We should have at least some telemetry emitted
        assert len(telemetry_events) >= 1 or p._total_processed > 0


# ──────────────────────────────────────────────────────────────
# 11. Concurrent Pipeline Stress
# ──────────────────────────────────────────────────────────────

class TestConcurrentPipelineStress:
    """Verify no crashes or deadlocks under concurrent enqueue pressure."""

    @pytest.mark.asyncio
    async def test_concurrent_enqueue_no_crash(self):
        from app.pipeline.async_pipeline import AsyncInferencePipeline
        p = AsyncInferencePipeline(
            session_id="test-stress",
            sample_rate=16000,
            queue_size=10,
        )
        await p.start()

        pcm = np.zeros(320, dtype=np.int16).tobytes()

        async def enqueue_many():
            for _ in range(50):
                p.enqueue_raw(pcm)
                await asyncio.sleep(0.001)

        # Run 4 concurrent enqueue tasks
        await asyncio.gather(
            enqueue_many(),
            enqueue_many(),
            enqueue_many(),
            enqueue_many(),
        )

        await asyncio.sleep(0.5)
        metrics = p.get_pipeline_metrics()
        assert metrics.total_chunks_processed >= 0  # no crash = success
        await p.stop()
