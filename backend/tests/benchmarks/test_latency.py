import time
import numpy as np
import pytest
from app.pipeline.orchestrator import StreamingPipelineOrchestrator
from tests.fixtures.audio_generator import float_to_pcm16_bytes, generate_synthetic_speech_mock


def test_streaming_latency_budget():
    """
    Latency Regression Benchmark:
    Validates that P95 end-to-end pipeline execution time stays strictly within
    the 360ms budget for each 1.5s analysis window.
    """
    orchestrator = StreamingPipelineOrchestrator(session_id="benchmark_session")

    # Generate 5 seconds of audio
    audio = generate_synthetic_speech_mock(duration_seconds=5.0, sample_rate=16000)
    raw_pcm = float_to_pcm16_bytes(audio)

    # 500ms chunks (8000 samples = 16000 bytes)
    chunk_bytes = 16000
    latencies = []

    for i in range(0, len(raw_pcm), chunk_bytes):
        chunk = raw_pcm[i : i + chunk_bytes]
        t0 = time.perf_counter()
        verdicts = orchestrator.process_pcm_bytes(chunk)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if verdicts:
            latencies.append(verdicts[0].latency_metrics.total_pipeline_latency_ms)

    orchestrator.cleanup()

    assert len(latencies) > 0
    p50 = float(np.percentile(latencies, 50))
    p95 = float(np.percentile(latencies, 95))

    print(f"\n[BENCHMARK] P50 Latency: {p50:.2f}ms | P95 Latency: {p95:.2f}ms")

    # Assert P95 is well below our 360ms budget
    assert p95 < 360.0, f"P95 latency ({p95}ms) exceeded 360ms upper bound!"
