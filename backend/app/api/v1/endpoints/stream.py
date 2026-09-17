import base64
import json
import time
import uuid
from typing import Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from app.core.logging import logger
from app.core.security import secure_zero_memory
from app.pipeline.orchestrator import StreamingPipelineOrchestrator
from app.schemas.stream import (
    ClientMessageType,
    ServerErrorMessage,
    ServerMessageType,
    ServerVerdictMessage,
    StreamConfigData,
)

router = APIRouter()


@router.websocket("/ws")
async def websocket_audio_stream_endpoint(websocket: WebSocket):
    """
    Real-Time WebSocket Audio Stream Pipeline Endpoint (MODE A / Ingest).
    Accepts raw binary PCM little-endian audio frames or Base64 JSON chunks.
    Emits continuous real-time RiskVerdicts as 500ms sliding hops are completed.
    """
    await websocket.accept()

    session_id = str(uuid.uuid4())
    logger.info(f"WebSocket client connected. Session ID: {session_id}")

    # Session state
    config = StreamConfigData()
    orchestrator = StreamingPipelineOrchestrator(session_id=session_id)
    sequence_counter = 0

    try:
        while True:
            # Handle incoming message: binary frame or text frame
            message = await websocket.receive()

            if "bytes" in message and message["bytes"]:
                # Binary raw PCM chunk received
                raw_bytes = message["bytes"]
                sequence_counter += 1

                verdicts = orchestrator.process_pcm_bytes(
                    raw_pcm=raw_bytes,
                    source_sample_rate=config.sample_rate,
                    source_channels=config.channels,
                )

                for verdict in verdicts:
                    verdict_msg = ServerVerdictMessage(
                        type=ServerMessageType.VERDICT,
                        session_id=session_id,
                        sequence_id=sequence_counter,
                        timestamp=int(time.time() * 1000),
                        data=verdict,
                    )
                    await websocket.send_text(verdict_msg.model_dump_json())

            elif "text" in message and message["text"]:
                # Text JSON frame received
                try:
                    payload = json.loads(message["text"])
                except json.JSONDecodeError:
                    err = ServerErrorMessage(
                        error_code="INVALID_JSON",
                        message="Malformed JSON received.",
                        fatal=False,
                    )
                    await websocket.send_text(err.model_dump_json())
                    continue

                msg_type = payload.get("type")

                if msg_type == ClientMessageType.CONFIG:
                    config = StreamConfigData(**payload.get("data", {}))
                    logger.info(f"Session {session_id} configured: {config.model_dump()}")
                    await websocket.send_text(
                        json.dumps({
                            "type": ServerMessageType.STATUS,
                            "session_id": session_id,
                            "message": "Configuration accepted. Ready for audio stream.",
                        })
                    )

                elif msg_type == ClientMessageType.PING:
                    pong = {
                        "type": ServerMessageType.PONG,
                        "timestamp": int(time.time() * 1000),
                    }
                    await websocket.send_text(json.dumps(pong))

                elif msg_type == ClientMessageType.AUDIO_CHUNK:
                    chunk_data = payload.get("data", {})
                    pcm_b64 = chunk_data.get("pcm_base64", "")
                    raw_bytes = base64.b64decode(pcm_b64)
                    sequence_counter = chunk_data.get("sequence_id", sequence_counter + 1)

                    verdicts = orchestrator.process_pcm_bytes(
                        raw_pcm=raw_bytes,
                        source_sample_rate=config.sample_rate,
                        source_channels=config.channels,
                    )

                    for verdict in verdicts:
                        verdict_msg = ServerVerdictMessage(
                            type=ServerMessageType.VERDICT,
                            session_id=session_id,
                            sequence_id=sequence_counter,
                            timestamp=int(time.time() * 1000),
                            data=verdict,
                        )
                        await websocket.send_text(verdict_msg.model_dump_json())

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected cleanly: session {session_id}")
    except Exception as e:
        logger.error(f"Error in streaming session {session_id}: {str(e)}", exc_info=True)
        try:
            err = ServerErrorMessage(
                error_code="INTERNAL_PIPELINE_ERROR",
                message=str(e),
                fatal=True,
            )
            await websocket.send_text(err.model_dump_json())
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:
            pass
    finally:
        orchestrator.cleanup()
        logger.info(f"Session {session_id} memory purged.")
