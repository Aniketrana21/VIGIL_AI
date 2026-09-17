import io
import time
import uuid
from typing import List
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
import numpy as np
import soundfile as sf
import torch
from app.core.logging import logger
from app.core.security import verify_api_key
from app.pipeline.speaker_verifier import ECAPASpeakerVerifier

router = APIRouter()
speaker_verifier = ECAPASpeakerVerifier()

# In-memory mock store for enrolled voiceprints
ENROLLED_PROFILES = {}


@router.post("/register", status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_api_key)])
async def enroll_speaker_voiceprint(
    speaker_label: str = Form(..., description="Human label, e.g., 'CEO', 'Mom'"),
    audio_files: List[UploadFile] = File(..., description="1-3 clean WAV audio reference files"),
):
    """
    Enrolls a trusted speaker voiceprint by computing and averaging 192-d ECAPA-TDNN embeddings.
    Enforces privacy by storing only the non-invertible 192-d vector; raw WAVs are discarded immediately.
    """
    if not audio_files:
        raise HTTPException(status_code=400, detail="At least one WAV file must be provided for enrollment.")

    embeddings = []
    for file in audio_files:
        content = await file.read()
        try:
            with io.BytesIO(content) as f:
                data, sr = sf.read(f)
                if data.ndim > 1:
                    data = np.mean(data, axis=1)
                audio_tensor = torch.from_numpy(data.astype(np.float32)).unsqueeze(0)
                emb = speaker_verifier.extract_embedding(audio_tensor)
                embeddings.append(emb)
        except Exception as e:
            logger.error(f"Failed to read audio file {file.filename}: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Invalid audio format in {file.filename}: {str(e)}")

    # Average and L2 re-normalize
    avg_emb = torch.stack(embeddings).mean(dim=0)
    avg_emb = torch.nn.functional.normalize(avg_emb, p=2, dim=0)

    speaker_id = str(uuid.uuid4())
    ENROLLED_PROFILES[speaker_id] = {
        "speaker_id": speaker_id,
        "speaker_label": speaker_label,
        "embedding": avg_emb,
        "created_at": time.time(),
    }

    logger.info(f"Speaker '{speaker_label}' enrolled successfully with ID {speaker_id}")

    return {
        "speaker_id": speaker_id,
        "speaker_label": speaker_label,
        "embedding_dim": 192,
        "status": "ENROLLED",
        "message": "Voice biometric profile created. Raw audio safely purged.",
    }
