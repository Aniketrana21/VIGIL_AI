import torch
import pytest
from app.pipeline.chunker import StreamingChunker


def test_chunker_sliding_window():
    # 16kHz, 1.5s window = 24,000 samples, 0.5s hop = 8,000 samples
    chunker = StreamingChunker(sample_rate=16000, window_seconds=1.5, hop_seconds=0.5)

    # 1. Send 10,000 samples (< 24,000) -> Should return 0 ready windows
    audio_part1 = torch.zeros(10000, dtype=torch.float32)
    windows1 = chunker.append_audio(audio_part1)
    assert len(windows1) == 0

    # 2. Send another 15,000 samples (total 25,000) -> Should yield ready window(s)
    audio_part2 = torch.zeros(15000, dtype=torch.float32)
    windows2 = chunker.append_audio(audio_part2)
    assert len(windows2) >= 1
    assert windows2[0].shape == (1, 24000)

    # 3. Buffer reset clears memory
    chunker.reset()
    assert len(chunker.buffer) == 0
