from fastapi import APIRouter, Depends, HTTPException, status
from app.core.logging import logger
from app.core.security import verify_api_key
from app.pipeline.challenge_service import get_challenge_service
from app.schemas.challenge import (
    ChallengeGenerationRequest,
    ChallengeItem,
    ChallengeStatus,
    ChallengeVerificationRequest,
    ChallengeVerificationResponse,
)

router = APIRouter()


@router.post(
    "/generate",
    response_model=ChallengeItem,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_api_key)],
)
async def generate_challenge(payload: ChallengeGenerationRequest):
    """
    Generates an unpredictable, non-repeating short challenge phrase or digit sequence.
    Enforces strict fast TTL expiration.
    """
    service = get_challenge_service()
    challenge = service.create_challenge(
        session_id=payload.session_id,
        trigger_reason=payload.trigger_reason,
        ttl_seconds=payload.custom_ttl_seconds,
    )
    return challenge


@router.post(
    "/verify",
    response_model=ChallengeVerificationResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def verify_challenge_response(payload: ChallengeVerificationRequest):
    """
    Verifies user challenge response audio across deepfake detector, speaker verifier,
    and acoustic liveness module with mandatory consent verification.
    """
    if not payload.user_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Explicit user consent is strictly required to record and verify challenge response audio.",
        )

    service = get_challenge_service()
    result = service.verify_response(payload)
    return result


@router.get(
    "/{challenge_id}/status",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def get_challenge_status(challenge_id: str):
    """
    Retrieves the current status and TTL expiration state of an active challenge.
    """
    service = get_challenge_service()
    challenge = service.active_challenges.get(challenge_id)
    if not challenge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Challenge '{challenge_id}' not found or already purged.",
        )

    return {
        "challenge_id": challenge.challenge_id,
        "status": challenge.status.value,
        "prompt_text": challenge.prompt_text,
        "expires_at": challenge.expires_at,
        "ttl_seconds": challenge.ttl_seconds,
    }
