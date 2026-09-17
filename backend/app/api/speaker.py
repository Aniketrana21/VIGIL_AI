import base64
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, status
import numpy as np
from pydantic import BaseModel, Field
from app.db.embedding_store import get_embedding_store
from app.pipeline.speaker_service import SpeakerEnrollmentService, SpeakerVerificationService

router = APIRouter(prefix="/api/v1/speaker", tags=["Speaker Verification"])


class SpeakerEnrollRequest(BaseModel):
    speaker_id: str = Field(..., description="Unique speaker identifier (e.g. 'alice_101')", min_length=2)
    name: str = Field(..., description="Display name of the speaker", min_length=1)
    utterances_base64: List[str] = Field(
        ...,
        description="List of base64-encoded raw 16-bit 16kHz PCM audio utterances (minimum 3 required)",
        min_length=1
    )
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class SpeakerEnrollResponse(BaseModel):
    success: bool
    speaker_id: str
    name: str
    num_utterances: int
    intra_speaker_consistency: float
    message: str


class SpeakerVerifyRequest(BaseModel):
    pcm_base64: str = Field(..., description="Base64-encoded raw 16-bit 16kHz PCM candidate audio")
    claimed_speaker_id: Optional[str] = Field(None, description="Optional claimed speaker ID for 1:1 verification")


class SpeakerVerifyResponse(BaseModel):
    speaker_id: str
    similarity: float
    match: bool
    confidence: float
    latency_ms: Optional[float] = None


class SpeakerProfileSummary(BaseModel):
    speaker_id: str
    name: str
    num_utterances: int
    created_at: str
    metadata: Dict[str, Any]


def _decode_pcm_base64(b64_str: str) -> np.ndarray:
    try:
        raw_bytes = base64.b64decode(b64_str)
        int16_arr = np.frombuffer(raw_bytes, dtype=np.int16)
        return int16_arr.astype(np.float32) / 32768.0
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid base64 PCM audio: {str(e)}"
        )


@router.post("/enroll", response_model=SpeakerEnrollResponse)
async def enroll_speaker(request: SpeakerEnrollRequest):
    """
    Enrolls a speaker profile using multiple voice utterances (minimum 3).
    Privacy Note: Raw voice recordings are discarded immediately after embedding extraction.
    Only unit-normalized 192-dim mathematical vectors are persisted.
    """
    if len(request.utterances_base64) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Speaker enrollment requires at least 3 distinct utterances, but received {len(request.utterances_base64)}."
        )

    utterance_arrays = [_decode_pcm_base64(b64) for b64 in request.utterances_base64]
    
    # Check that utterances have sufficient speech duration (>= 0.4s = 6400 samples)
    for idx, u in enumerate(utterance_arrays):
        if len(u) < 6400:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Enrollment utterance {idx + 1} is too short ({len(u)/16000:.2f}s). Minimum 0.40s required."
            )

    enrollment_svc = SpeakerEnrollmentService()
    try:
        res = await enrollment_svc.enroll_speaker(
            speaker_id=request.speaker_id,
            name=request.name,
            utterances=utterance_arrays,
            metadata=request.metadata,
        )
        if not res.success:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=res.message)
        return SpeakerEnrollResponse(**res.to_dict())
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.post("/verify", response_model=SpeakerVerifyResponse)
async def verify_speaker(request: SpeakerVerifyRequest):
    """
    Evaluates candidate speech against an enrolled speaker (1:1) or all enrolled speakers (1:N).
    Returns cosine similarity, match decision, and confidence.
    """
    audio = _decode_pcm_base64(request.pcm_base64)
    if len(audio) < 4000:  # < 0.25s
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Candidate audio is too short for reliable speaker verification. Minimum 0.25s required."
        )

    verification_svc = SpeakerVerificationService()
    res = await verification_svc.verify(
        audio=audio,
        claimed_speaker_id=request.claimed_speaker_id,
    )
    return SpeakerVerifyResponse(**res.to_extended_dict())


@router.get("/profiles", response_model=List[SpeakerProfileSummary])
async def list_speaker_profiles():
    """Lists enrolled speaker profiles without exposing raw embedding vectors."""
    store = get_embedding_store()
    profiles = await store.list_speakers()
    return [
        SpeakerProfileSummary(
            speaker_id=p.speaker_id,
            name=p.name,
            num_utterances=p.num_utterances,
            created_at=p.created_at,
            metadata=p.metadata,
        )
        for p in profiles
    ]


@router.delete("/profiles/{speaker_id}")
async def delete_speaker_profile(speaker_id: str):
    """Deletes an enrolled speaker profile."""
    store = get_embedding_store()
    deleted = await store.delete_speaker_profile(speaker_id.strip().lower())
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Speaker '{speaker_id}' not found.")
    return {"status": "success", "message": f"Speaker profile '{speaker_id}' deleted."}
