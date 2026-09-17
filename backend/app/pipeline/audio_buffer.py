import collections
import time
from typing import Dict, List, Optional, Tuple
import numpy as np
import torch
from app.core.security import secure_zero_memory
from app.pipeline.audio_chunk import AudioChunk


class AudioBuffer:
    """
    Real-Time Jitter Buffer, Resequencer, and Overlapping Analysis Window Generator.
    
    Axioms & Requirements:
    1. A network packet != an ML analysis window.
    2. Jitter buffer handles out-of-order packets and reconstructs continuous PCM stream.
    3. Detects dropped, reordered, and duplicate packets.
    4. Enforces backpressure: drops oldest audio when backlog exceeds max_buffer_seconds.
    5. Slices continuous stream into 2.0-second analysis windows with configurable overlap.
    6. Zero-retention memory hygiene on consumed or evicted frames.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        window_seconds: float = 2.0,
        overlap_ratio: float = 0.50,
        max_buffer_seconds: float = 4.0,
        resequence_window_size: int = 10,
    ):
        self.sample_rate = sample_rate
        self.window_seconds = window_seconds
        self.overlap_ratio = overlap_ratio
        self.window_samples = int(sample_rate * window_seconds)
        self.hop_samples = int(self.window_samples * (1.0 - overlap_ratio))
        self.max_buffer_samples = int(sample_rate * max_buffer_seconds)
        self.resequence_window_size = resequence_window_size

        # In-memory contiguous stream buffer (float32 [-1.0, 1.0])
        self.contiguous_buffer = np.zeros(0, dtype=np.float32)

        # Jitter resequencing queue: maps sequence_id -> (timestamp, samples)
        self.jitter_queue: Dict[int, Tuple[int, np.ndarray]] = {}
        self.last_contiguous_seq = -1

        # Operational statistics
        self.packets_received = 0
        self.packets_dropped = 0
        self.packets_reordered = 0
        self.packets_duplicate = 0

    def reset(self) -> None:
        """Purges and zero-fills internal memory buffers."""
        if len(self.contiguous_buffer) > 0:
            secure_zero_memory(self.contiguous_buffer)
        self.contiguous_buffer = np.zeros(0, dtype=np.float32)

        for _, samples in self.jitter_queue.values():
            secure_zero_memory(samples)
        self.jitter_queue.clear()

        self.last_contiguous_seq = -1
        self.packets_received = 0
        self.packets_dropped = 0
        self.packets_reordered = 0
        self.packets_duplicate = 0

    def insert_chunk(self, chunk: AudioChunk, samples_float: np.ndarray) -> List[np.ndarray]:
        """
        Inserts an incoming audio packet into the jitter buffer, resequences if necessary,
        flushes into contiguous buffer, handles backpressure, and returns any complete
        2-second analysis windows ready for downstream analysis.
        """
        self.packets_received += 1
        seq = chunk.sequence_id

        # 1. Duplicate check
        if seq in self.jitter_queue or (self.last_contiguous_seq != -1 and seq <= self.last_contiguous_seq):
            self.packets_duplicate += 1
            return []

        # 2. Reordering & Jitter detection
        if self.last_contiguous_seq != -1 and seq != self.last_contiguous_seq + 1:
            if seq < self.last_contiguous_seq + self.resequence_window_size:
                self.packets_reordered += 1

        # Store in jitter queue
        self.jitter_queue[seq] = (chunk.timestamp_ms, samples_float)

        # 3. Drain jitter queue in sequential order into contiguous buffer
        self._drain_jitter_queue()

        # 4. Enforce Backpressure
        if len(self.contiguous_buffer) > self.max_buffer_samples:
            overflow_samples = len(self.contiguous_buffer) - self.max_buffer_samples
            # Estimate dropped packet count from overflow samples
            dropped_est = max(1, overflow_samples // (chunk.num_samples if chunk.num_samples > 0 else 1600))
            self.packets_dropped += dropped_est

            # Securely zero evicted memory and trim buffer
            secure_zero_memory(self.contiguous_buffer[:overflow_samples])
            self.contiguous_buffer = self.contiguous_buffer[overflow_samples:]

        # 5. Extract 2.0-second overlapping analysis windows
        analysis_windows: List[np.ndarray] = []
        while len(self.contiguous_buffer) >= self.window_samples:
            window = self.contiguous_buffer[: self.window_samples].copy()
            analysis_windows.append(window)

            # Advance by hop_samples
            advance = self.hop_samples
            secure_zero_memory(self.contiguous_buffer[:advance])
            self.contiguous_buffer = self.contiguous_buffer[advance:]

        return analysis_windows

    def _drain_jitter_queue(self) -> None:
        """
        Drains strictly sequential packets from the jitter queue into the contiguous buffer.
        If a gap persists longer than `resequence_window_size`, skips the missing sequence
        and records a dropped packet.
        """
        if not self.jitter_queue:
            return

        sorted_seqs = sorted(self.jitter_queue.keys())

        # Initialize sequence tracking if first packet
        if self.last_contiguous_seq == -1:
            self.last_contiguous_seq = sorted_seqs[0] - 1

        for seq in sorted_seqs:
            expected_seq = self.last_contiguous_seq + 1

            if seq == expected_seq:
                # In-order packet
                _, samples = self.jitter_queue.pop(seq)
                self.contiguous_buffer = np.concatenate((self.contiguous_buffer, samples))
                self.last_contiguous_seq = seq
            elif seq > expected_seq:
                # Sequence gap detected (potential packet loss or reordering)
                gap_size = seq - expected_seq
                if len(self.jitter_queue) >= self.resequence_window_size or gap_size > self.resequence_window_size:
                    # Timeout / gap exceeded: declare dropped packets and skip gap
                    self.packets_dropped += gap_size
                    _, samples = self.jitter_queue.pop(seq)
                    self.contiguous_buffer = np.concatenate((self.contiguous_buffer, samples))
                    self.last_contiguous_seq = seq
                else:
                    # Wait for missing sequence to arrive in next batch
                    break
            else:
                # Old/duplicate packet already passed
                self.jitter_queue.pop(seq)

    def get_stats(self) -> dict:
        """Returns real-time buffer metrics and packet health."""
        buf_duration_ms = (len(self.contiguous_buffer) / self.sample_rate) * 1000.0 if self.sample_rate > 0 else 0.0
        return {
            "sample_rate": self.sample_rate,
            "window_duration_seconds": self.window_seconds,
            "hop_duration_seconds": self.hop_samples / self.sample_rate,
            "current_buffer_ms": round(buf_duration_ms, 1),
            "current_buffer_samples": len(self.contiguous_buffer),
            "packets_received": self.packets_received,
            "packets_dropped": self.packets_dropped,
            "packets_reordered": self.packets_reordered,
            "packets_duplicate": self.packets_duplicate,
            "last_sequence_id": self.last_contiguous_seq,
        }
