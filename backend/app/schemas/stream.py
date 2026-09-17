from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from app.schemas.risk import RiskVerdict


class ClientMessageType(str, Enum):
    CONFIG = "CONFIG"
    AUDIO_CHUNK = "AUDIO_CHUNK"
    PING = "PING"


class ServerMessageType(str, Enum):
    VERDICT = "VERDICT"
    PONG = "PONG"
    ERROR = "ERROR"
    STATUS = "STATUS"


class StreamContext(BaseModel):
    channel_type: str = "WEBRTC"
    caller_id: Optional[str] = None
    call_direction: str = "INCOMING"


class StreamConfigData(BaseModel):
    sample_rate: int = Field(default=16000, description="Audio sample rate (Hz)")
    channels: int = Field(default=1, description="Number of channels (1=Mono)")
    encoding: str = Field(default="PCM_16BIT", description="PCM encoding")
    target_speaker_id: Optional[str] = Field(default=None, description="UUID of claimed enrolled speaker")
    context: Optional[StreamContext] = Field(default_factory=StreamContext)


class StreamConfigMessage(BaseModel):
    type: ClientMessageType = ClientMessageType.CONFIG
    data: StreamConfigData


class AudioChunkData(BaseModel):
    sequence_id: int
    timestamp_ms: int
    pcm_base64: str


class AudioChunkMessage(BaseModel):
    type: ClientMessageType = ClientMessageType.AUDIO_CHUNK
    data: AudioChunkData


class PingMessage(BaseModel):
    type: ClientMessageType = ClientMessageType.PING
    data: Dict[str, Any] = Field(default_factory=dict)


class ServerVerdictMessage(BaseModel):
    type: ServerMessageType = ServerMessageType.VERDICT
    session_id: str
    sequence_id: int
    timestamp: int
    data: RiskVerdict


class ServerErrorMessage(BaseModel):
    type: ServerMessageType = ServerMessageType.ERROR
    error_code: str
    message: str
    fatal: bool = False
