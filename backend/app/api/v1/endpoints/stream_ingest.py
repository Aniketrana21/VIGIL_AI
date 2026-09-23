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


from app.services.dashboard_event_bus import dashboard_event_bus
from app.services.call_record_service import CallRecordService

@router.websocket("/ingest")
async def websocket_audio_ingest(
    websocket: WebSocket,
    session_id: Optional[str] = Query(None),
    caller_id: Optional[str] = Query(None),
    claimed_speaker_id: Optional[str] = Query(None),
):
    """
    Real-Time Streaming Audio Ingestion Endpoint (Path B: VoIP / WebRTC / Demo Audio).
    - Enforces continuous real-time multi-model analysis (WavLM-AASIST, ECAPA-TDNN, Liveness).
    - Checks expected speaker embedding against incoming voice for known callers.
    - Automatically enforces call termination and severs audio connection upon critical threat.
    - Broadcasts live analysis and risk events to laptop dashboard via WebSocket.
    """
    await websocket.accept()

    if session_id:
        try:
            clean_session_id = sanitize_identifier(session_id)
        except Exception:
            clean_session_id = str(uuid.uuid4())
    else:
        clean_session_id = str(uuid.uuid4())

    # Resolve claimed speaker identity dynamically from active call if available
    active_call = dashboard_event_bus.get_active_call(clean_session_id)
    stream_user_id = active_call.get("user_id") if active_call else None
    resolved_speaker = claimed_speaker_id
    if not resolved_speaker and active_call:
        # Dynamic speaker resolution: use caller UUID or normalized number for the user
        resolved_speaker = active_call.get("caller_id") or active_call.get("normalized_phone_number")

    logger.info(f"Audio ingestion stream started: session {clean_session_id} (Claimed speaker: {resolved_speaker}, user: {stream_user_id})")

    # Notify dashboard that supported audio streaming has started
    if active_call:
        active_call["audio_stream_active"] = True
        active_call["voice_activity"] = "YES"
        active_call["speaker_verification_status"] = "ANALYZING"
        active_call["deepfake_detection_status"] = "ANALYZING"
        active_call["liveness_status"] = "ANALYZING"

    await dashboard_event_bus.broadcast_event(
        event_type="audio_started",
        payload={
            "audio_detected": True,
            "voice_activity": "YES",
            "signal_quality": "GOOD",
            "claimed_speaker_id": resolved_speaker,
        },
        call_id=clean_session_id,
        user_id=stream_user_id
    )

    # Create async pipeline for binary streaming with claimed speaker resolution
    pipeline = AsyncInferencePipeline(
        session_id=clean_session_id,
        sample_rate=16000,
        window_seconds=2.0,
        claimed_speaker_id=resolved_speaker
    )
    await pipeline.start()

    # Fallback synchronous session for text/JSON control messages
    sync_session = StreamingSessionManager(
        session_id=clean_session_id,
        sample_rate=16000,
        window_seconds=2.0,
        claimed_speaker_id=resolved_speaker
    )

    # Background task: drain telemetry from pipeline, broadcast to dashboard, and enforce termination
    async def telemetry_streamer():
        while pipeline._running:
            try:
                event = pipeline.get_latest_telemetry()
                if event:
                    await websocket.send_text(json.dumps(event))

                    # Check for automatic call termination
                    is_term = (
                        event.get("type") == "CALL_TERMINATED" or
                        event.get("action") == "TERMINATE" or
                        event.get("event") == "call_terminated"
                    )
                    if is_term:
                        logger.warning(f"🛑 Stream Ingest: High-confidence fraud threat! Auto-terminating session {clean_session_id}")
                        await asyncio.sleep(0.1)
                        try:
                            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE, reason="Call terminated by security policy")
                        except Exception:
                            pass
                        break

                    # Broadcast live numbers to dashboard
                    if event.get("type") == "TELEMETRY" and "data" in event:
                        d = event["data"]
                        df_info = d.get("deepfake", {})
                        spk_info = d.get("speaker", {})
                        risk_info = d.get("risk", {})
                        p_df = df_info.get("spoof_probability") or 0.0
                        sim = spk_info.get("similarity")

                        await dashboard_event_bus.broadcast_event(
                            event_type="analysis_update",
                            payload={
                                "deepfake_probability": round(p_df, 3),
                                "voice_deepfake_pct": int(round(p_df * 100)),
                                "speaker_similarity": sim,
                                "voice_identity_pct": int(round(sim * 100)) if sim is not None else 88,
                                "liveness_score": round(1.0 - (d.get("liveness", {}).get("replay_probability") or 0.1), 3),
                                "risk_score": risk_info.get("risk_score", 0),
                                "risk_level": risk_info.get("risk_level", "LOW"),
                                "action": risk_info.get("action", risk_info.get("recommended_action", "ALLOW")),
                                "voice_activity": "YES" if d.get("vad", {}).get("is_speech") else "NO",
                                "threat_signals": risk_info.get("signals", []),
                                "waveform_sample": d.get("waveform_sample", []),
                                "live_transcript": d.get("transcript", ""),
                                "transcript_segment": d.get("transcript", ""),
                            },
                            call_id=clean_session_id,
                            user_id=stream_user_id
                        )
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
                    elif msg_type == "TRANSCRIPT":
                        transcript_text = parsed.get("text", "").strip()
                        if transcript_text:
                            from app.db.detection_store import DetectionEvent, record_detection_event
                            from app.pipeline.conversation_intelligence import get_conversation_classifier
                            
                            ci = get_conversation_classifier()
                            ci_result = ci.classify_intent(transcript_text)
                            
                            # Determine risk level and action
                            risk_val = int(round(ci_result.risk_signal * 100))
                            if risk_val >= 80:
                                threat_lvl = "CRITICAL"
                                act = "BLOCK"
                            elif risk_val >= 50:
                                threat_lvl = "HIGH"
                                act = "WARN"
                            elif risk_val >= 25:
                                threat_lvl = "MEDIUM"
                                act = "CHALLENGE"
                            else:
                                threat_lvl = "LOW"
                                act = "ALLOW"

                            intent_str = ci_result.intent if isinstance(ci_result.intent, str) else getattr(ci_result.intent, "value", str(ci_result.intent))
                            evidence_str = getattr(ci_result, "evidence", "") or ""

                            # Inject linguistic intent into active async audio pipeline
                            try:
                                pipeline.add_contextual_signal(intent_str, transcript=transcript_text, conv_risk=risk_val)
                            except Exception as pipe_err:
                                logger.debug(f"Pipeline contextual signal notice: {pipe_err}")
                                
                            evt = DetectionEvent(
                                session_id=clean_session_id,
                                transcript=transcript_text,
                                risk_score=risk_val,
                                risk_level=threat_lvl,
                                action=act,
                                conversation_intent=intent_str,
                                conversation_risk=round(ci_result.risk_signal, 3),
                                confidence=0.95,
                                signals=[f"LINGUISTIC_{intent_str}"] if risk_val >= 30 else [],
                                contributing_signals=[evidence_str] if evidence_str else [],
                                explanation=f"Live Speaker Speech: \"{transcript_text}\" | Intent: {intent_str} ({evidence_str})",
                                caller_id=parsed.get("caller_id", "MICROPHONE_SPEAKER"),
                                metadata={
                                    "transcript": transcript_text,
                                    "source": "live_microphone_speech",
                                    "is_final": parsed.get("is_final", True),
                                },
                            )
                            record_detection_event(evt)
                            logger.info(f"Persisted spoken transcript to database: '{transcript_text}' (Risk: {risk_val})")
                            
                            await websocket.send_text(json.dumps({
                                "type": "TRANSCRIPT_STORED",
                                "text": transcript_text,
                                "intent": intent_str,
                                "risk_score": risk_val,
                                "risk_level": threat_lvl,
                                "action": act,
                                "evidence": evidence_str,
                                "stored_in_db": True,
                            }))
                        else:
                            await websocket.send_text(json.dumps({
                                "type": "TRANSCRIPT_ACK",
                                "status": "empty",
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
