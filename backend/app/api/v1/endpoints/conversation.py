import base64
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
