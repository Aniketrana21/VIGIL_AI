import base64
import struct
import time
from dataclasses import dataclass
from typing import Optional, Tuple, Union

MAGIC_HEADER = b"VIGI"  # 0x56494749
HEADER_FORMAT = ">4sQQII"  # Magic (4s), Sequence (uint64), Timestamp (uint64), SampleRate (uint32), Length (uint32)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 4 + 8 + 8 + 4 + 4 = 28 bytes


@dataclass
class AudioChunk:
    """
    Standard Audio Chunk transported over network WebSocket.
    Guarantees sequence tracking, timestamping, and raw PCM encapsulation.
    """
    sequence_id: int
    timestamp_ms: int
    sample_rate: int
    channels: int
    pcm_bytes: bytes

    @property
    def num_samples(self) -> int:
        return len(self.pcm_bytes) // 2

    @property
    def duration_ms(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return (self.num_samples / self.sample_rate) * 1000.0

    def serialize_binary(self) -> bytes:
        """
        Packs the chunk into a 28-byte binary header followed by raw PCM bytes:
        [Magic(4B)][Sequence(8B)][Timestamp(8B)][SampleRate(4B)][Length(4B)][PCM Bytes...]
        """
        payload_len = len(self.pcm_bytes)
        header = struct.pack(
            HEADER_FORMAT,
            MAGIC_HEADER,
            self.sequence_id,
            self.timestamp_ms,
            self.sample_rate,
            payload_len,
        )
        return header + self.pcm_bytes

    @classmethod
    def deserialize_binary(cls, data: bytes) -> Tuple[Optional["AudioChunk"], Optional[str]]:
        """
        Unpacks binary data into AudioChunk.
        Returns (AudioChunk, None) or (None, error_reason). Never crashes.
        """
        if len(data) < HEADER_SIZE:
            return None, f"Data size ({len(data)}B) smaller than header size ({HEADER_SIZE}B)"

        try:
            magic, seq, ts, sr, length = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
            if magic != MAGIC_HEADER:
                return None, f"Invalid magic header: {magic!r}, expected {MAGIC_HEADER!r}"
            payload = data[HEADER_SIZE : HEADER_SIZE + length]
            if len(payload) != length:
                return None, f"Payload length mismatch: expected {length}B, got {len(payload)}B"
            if len(payload) % 2 != 0:
                return None, f"Payload size ({len(payload)}B) is not aligned to 16-bit PCM (multiple of 2)"

            return cls(
                sequence_id=seq,
                timestamp_ms=ts,
                sample_rate=sr,
                channels=1,
                pcm_bytes=payload,
            ), None
        except Exception as e:
            return None, f"Binary deserialization error: {str(e)}"

    def to_dict(self) -> dict:
        return {
            "type": "AUDIO_CHUNK",
            "sequence_id": self.sequence_id,
            "timestamp_ms": self.timestamp_ms,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "pcm_base64": base64.b64encode(self.pcm_bytes).decode("ascii"),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Tuple[Optional["AudioChunk"], Optional[str]]:
        try:
            seq = data.get("sequence_id")
            ts = data.get("timestamp_ms", int(time.time() * 1000))
            sr = data.get("sample_rate", 16000)
            ch = data.get("channels", 1)
            b64_str = data.get("pcm_base64")

            if seq is None or b64_str is None:
                return None, "Missing required fields 'sequence_id' or 'pcm_base64'"

            pcm_bytes = base64.b64decode(b64_str)
            if len(pcm_bytes) % 2 != 0:
                return None, f"Decoded PCM size ({len(pcm_bytes)}B) is not a multiple of 2"

            return cls(
                sequence_id=int(seq),
                timestamp_ms=int(ts),
                sample_rate=int(sr),
                channels=int(ch),
                pcm_bytes=pcm_bytes,
            ), None
        except Exception as e:
            return None, f"JSON deserialization error: {str(e)}"


# CamelCase aliases for Kotlin client parity
AudioChunk.serializeBinary = AudioChunk.serialize_binary
AudioChunk.deserializeBinary = AudioChunk.deserialize_binary
