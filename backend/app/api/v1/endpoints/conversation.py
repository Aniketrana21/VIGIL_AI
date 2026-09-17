import base64
import time
from fastapi import APIRouter, Depends, HTTPException, status
import numpy as np
import torch

from app.core.logging import logger
from app.core.security import verify_api_key
from app.pipeline.conversation_intelligence import get_conversation_classifier
from app.schemas.conversation import ConversationAnalysisRequest, ConversationIntelligenceOutput

router = APIRouter()


@router.post(
    "/analyze",
    response_model=ConversationIntelligenceOutput,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def analyze_conversation(payload: ConversationAnalysisRequest):
    """
    Phase 11 Conversation Intelligence Analysis Endpoint.

    Evaluates caller speech transcript or audio chunk using contextual intent analysis.
    Identifies high-risk scam/social engineering intents (e.g. OTP requests, emergency money requests,
    UPI solicitation, account takeovers) while contextually distinguishing benign informational questions.

    Output schema conforms to Phase 11 specification:
    {
      "intent": "FINANCIAL_REQUEST",
      "risk_signal": 0.88,
      "evidence": "request for money transfer"
    }
    """
    if not payload.user_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Explicit user consent is required for speech-to-text and conversational intent analysis.",
        )

    classifier = get_conversation_classifier()

    # Mode 1: Direct text transcript analysis
    if payload.transcript is not None:
        result = classifier.classify_intent(payload.transcript)
        
        # Persist conversation risk verdict to DB if consented
        try:
            from app.db.detection_store import DetectionEvent, record_detection_event
            risk_val = int(round(result.risk_signal * 100))
            threat_lvl = "CRITICAL" if risk_val >= 80 else ("HIGH" if risk_val >= 50 else ("MEDIUM" if risk_val >= 25 else "LOW"))
            act = "BLOCK" if risk_val >= 80 else ("WARN" if risk_val >= 50 else ("CHALLENGE" if risk_val >= 25 else "ALLOW"))
            
            evt = DetectionEvent(
                session_id=f"conv-{int(time.time())}" if "time" in globals() else "conv-session",
                risk_score=risk_val,
                risk_level=threat_lvl,
                action=act,
                conversation_intent=result.intent.value,
                conversation_risk=round(result.risk_signal, 3),
                confidence=0.95,
                signals=result.signals,
                contributing_signals=[result.evidence],
                explanation=f"Transcript: \"{payload.transcript}\" | Analysis: {result.evidence}",
                metadata={"transcript": payload.transcript, "source": "conversation_intelligence"},
            )
            record_detection_event(evt)
        except Exception as e:
            logger.debug(f"Conversation analysis DB save notice: {e}")

        return ConversationIntelligenceOutput(
            intent=result.intent,
            risk_signal=result.risk_signal,
            evidence=result.evidence,
        )

    # Mode 2: Audio base64 processing via Whisper ASR
    if payload.audio_base64:
        try:
            raw_bytes = base64.b64decode(payload.audio_base64)
            if len(raw_bytes) >= 44 and raw_bytes[:4] == b"RIFF":
                pcm = np.frombuffer(raw_bytes[44:], dtype=np.int16)
            else:
                pcm = np.frombuffer(raw_bytes, dtype=np.int16)
            float_pcm = pcm.astype(np.float32) / 32768.0
            audio_tensor = torch.from_numpy(float_pcm)
        except Exception as e:
            logger.warning(f"Failed to decode base64 audio in conversation endpoint: {e}")
            audio_tensor = torch.zeros(16000, dtype=torch.float32)

        result = classifier.analyze_audio(
            audio=audio_tensor,
            user_consent=payload.user_consent,
            store_transcript_consented=payload.store_transcript_consented,
        )
        return ConversationIntelligenceOutput(
            intent=result.intent,
            risk_signal=result.risk_signal,
            evidence=result.evidence,
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Either 'transcript' or 'audio_base64' payload must be provided for conversation analysis.",
    )
