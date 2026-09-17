import asyncio
import json
from typing import Optional
import uuid
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from app.core.logging import logger
from app.core.security import sanitize_identifier
from app.pipeline.async_pipeline import AsyncInferencePipeline
from app.pipeline.session_manager import StreamingSessionManager

router = APIRouter()


@router.websocket("/ingest")
async def websocket_audio_ingest(
    websocket: WebSocket,
    session_id: Optional[str] = Query(None),
):
    """
    Phase 7 Real-Time Streaming Audio Ingestion Endpoint.
    Non-blocking async producer-consumer pipeline:
    - WebSocket receive loop strictly enqueues raw data (never blocks on inference).
    - Background workers handle preprocessing, ML inference, risk synthesis, and result smoothing.
    - Telemetry is streamed back asynchronously.
    Falls back to synchronous StreamingSessionManager for text/JSON messages.
    """
    await websocket.accept()

    if session_id:
        try:
            clean_session_id = sanitize_identifier(session_id)
        except Exception:
            clean_session_id = str(uuid.uuid4())
    else:
        clean_session_id = str(uuid.uuid4())

    logger.info(f"Audio ingestion stream started: session {clean_session_id}")

    # Create async pipeline for binary streaming
    pipeline = AsyncInferencePipeline(session_id=clean_session_id, sample_rate=16000, window_seconds=2.0)
    await pipeline.start()

    # Fallback synchronous session for text/JSON control messages
    sync_session = StreamingSessionManager(session_id=clean_session_id, sample_rate=16000, window_seconds=2.0)

    # Background task: drain telemetry from pipeline and send to WebSocket
    async def telemetry_streamer():
        while pipeline._running:
            try:
                event = pipeline.get_latest_telemetry()
                if event:
                    await websocket.send_text(json.dumps(event))
                else:
                    await asyncio.sleep(0.05)
            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as e:
                logger.debug(f"Telemetry streamer error: {e}")
                await asyncio.sleep(0.1)

    streamer_task = asyncio.create_task(telemetry_streamer())

    # Send initial handshake
    try:
        await websocket.send_text(json.dumps({
            "type": "TELEMETRY",
            "data": sync_session.get_telemetry()
        }))
    except Exception:
        pass

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message and message["bytes"]:
                raw_bytes = message["bytes"]
                # Non-blocking enqueue — never blocks the WebSocket receive loop
                pipeline.enqueue_raw(raw_bytes)

            elif "text" in message and message["text"]:
                try:
                    text_data = message["text"]
                    parsed = json.loads(text_data)

                    msg_type = parsed.get("type", "")

                    if msg_type == "PING":
                        await websocket.send_text(json.dumps({
                            "type": "PONG",
                            "timestamp": parsed.get("timestamp", 0)
                        }))
                    elif msg_type in ["AUDIO_CHUNK", "CHUNK"]:
                        windows, telemetry = sync_session.ingest_packet(parsed)
                        resp = {
                            "type": "TELEMETRY",
                            "windows_count": len(windows),
                            "data": telemetry,
                        }
                        await websocket.send_text(json.dumps(resp))
                    elif msg_type == "CONFIG":
                        sample_rate = parsed.get("data", {}).get("sample_rate", 16000)
                        window_sec = parsed.get("data", {}).get("window_seconds", 2.0)
                        sync_session = StreamingSessionManager(
                            session_id=session_id,
                            sample_rate=sample_rate,
                            window_seconds=window_sec
                        )
                        await websocket.send_text(json.dumps({
                            "type": "CONFIG_ACK",
                            "data": sync_session.get_telemetry()
                        }))
                    elif msg_type == "PIPELINE_METRICS":
                        # Return pipeline health metrics on demand
                        metrics = pipeline.get_pipeline_metrics()
                        await websocket.send_text(json.dumps({
                            "type": "PIPELINE_METRICS",
                            "data": metrics.to_dict()
                        }))
                    else:
                        windows, telemetry = sync_session.ingest_packet(parsed)
                        await websocket.send_text(json.dumps({
                            "type": "TELEMETRY",
                            "windows_count": len(windows),
                            "data": telemetry,
                        }))

                except Exception as e:
                    logger.warning(f"Error handling text frame: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "ERROR",
                        "error": str(e),
                        "data": sync_session.get_telemetry(error=str(e))
                    }))

    except (WebSocketDisconnect, RuntimeError) as e:
        logger.info(f"Ingest client disconnected: session {session_id} ({e})")
    except Exception as e:
        logger.error(f"Unexpected streaming ingest error in session {session_id}: {e}", exc_info=True)
    finally:
        streamer_task.cancel()
        try:
            await streamer_task
        except (asyncio.CancelledError, Exception):
            pass
        await pipeline.stop()
        sync_session.close()
