import base64
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
import numpy as np
from pydantic import BaseModel, Field
from app.core.audit_logger import audit_logger
from app.core.security import sanitize_identifier, validate_audio_payload, verify_api_key
from app.db.embedding_store import get_embedding_store
from app.pipeline.speaker_service import SpeakerEnrollmentService, SpeakerVerificationService

router = APIRouter(prefix="/api/v1/speaker", tags=["Speaker Verification"])


class SpeakerEnrollRequest(BaseModel):
    speaker_id: str = Field(..., description="Unique speaker identifier (e.g. 'alice_101')", min_length=2, max_length=64)
    name: str = Field(..., description="Display name of the speaker", min_length=1, max_length=128)
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
        validate_audio_payload(raw_bytes)
        int16_arr = np.frombuffer(raw_bytes, dtype=np.int16)
        return int16_arr.astype(np.float32) / 32768.0
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid base64 PCM audio: {str(e)}"
        )


@router.post("/enroll", response_model=SpeakerEnrollResponse)
async def enroll_speaker(request: SpeakerEnrollRequest, http_request: Request, _auth: bool = Depends(verify_api_key)):
    """
    Enrolls a speaker profile using multiple voice utterances (minimum 3).
    Privacy Note: Raw voice recordings are discarded immediately after embedding extraction.
    Only unit-normalized 192-dim mathematical vectors are persisted (encrypted at rest).
    """
    clean_speaker_id = sanitize_identifier(request.speaker_id)

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
            speaker_id=clean_speaker_id,
            name=request.name.strip(),
            utterances=utterance_arrays,
            metadata=request.metadata,
        )
        if not res.success:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=res.message)

        client_ip = http_request.client.host if http_request.client else "127.0.0.1"
        audit_logger.log_event(
            event_type="SPEAKER_ENROLLED",
            actor="authenticated_client",
            resource_id=clean_speaker_id,
            status="SUCCESS",
            client_ip=client_ip,
            details={"num_utterances": res.num_utterances, "consistency": res.intra_speaker_consistency},
        )
        return SpeakerEnrollResponse(**res.to_dict())
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))


@router.post("/verify", response_model=SpeakerVerifyResponse)
async def verify_speaker(request: SpeakerVerifyRequest, _auth: bool = Depends(verify_api_key)):
    """
    Evaluates candidate speech against an enrolled speaker (1:1) or all enrolled speakers (1:N).
    Returns cosine similarity, match decision, and confidence.
    """
    claimed_id = sanitize_identifier(request.claimed_speaker_id) if request.claimed_speaker_id else None
    audio = _decode_pcm_base64(request.pcm_base64)
    if len(audio) < 4000:  # < 0.25s
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Candidate audio is too short for reliable speaker verification. Minimum 0.25s required."
        )

    verification_svc = SpeakerVerificationService()
    res = await verification_svc.verify(
        audio=audio,
        claimed_speaker_id=claimed_id,
    )
    return SpeakerVerifyResponse(**res.to_extended_dict())


@router.get("/profiles", response_model=List[SpeakerProfileSummary])
async def list_speaker_profiles(http_request: Request, _auth: bool = Depends(verify_api_key)):
    """Lists enrolled speaker profiles without exposing raw embedding vectors."""
    store = get_embedding_store()
    profiles = await store.list_speakers()

    client_ip = http_request.client.host if http_request.client else "127.0.0.1"
    audit_logger.log_event(
        event_type="SPEAKER_PROFILES_ACCESSED",
        actor="authenticated_client",
        resource_id="all_profiles",
        status="SUCCESS",
        client_ip=client_ip,
        details={"count": len(profiles)},
    )

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
async def delete_speaker_profile(speaker_id: str, http_request: Request, _auth: bool = Depends(verify_api_key)):
    """
    Permanently deletes an enrolled speaker profile (GDPR Right to Erasure / BIPA compliance).
    Securely removes vector embeddings and associated metadata.
    """
    clean_id = sanitize_identifier(speaker_id)
    store = get_embedding_store()
    deleted = await store.delete_speaker_profile(clean_id.lower())
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Speaker '{clean_id}' not found.")

    client_ip = http_request.client.host if http_request.client else "127.0.0.1"
    audit_logger.log_event(
        event_type="SPEAKER_DELETED",
        actor="authenticated_client",
        resource_id=clean_id,
        status="SUCCESS",
        client_ip=client_ip,
        details={"action": "permanent_biometric_purge"},
    )
    return {"status": "success", "message": f"Speaker profile '{clean_id}' permanently deleted."}
