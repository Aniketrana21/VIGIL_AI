import ctypes
import hashlib
import hmac
import secrets
from typing import Optional, Union
import numpy as np
import torch
from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def secure_zero_memory(target: Union[bytearray, memoryview, np.ndarray, torch.Tensor]) -> None:
    """
    Overwrites the memory buffer with zeros to enforce the zero-retention privacy mandate.
    Guarantees no raw audio residues linger in process memory longer than necessary.
    """
    if isinstance(target, (bytearray, memoryview)):
        for i in range(len(target)):
            target[i] = 0
    elif isinstance(target, np.ndarray):
        target.fill(0)
    elif isinstance(target, torch.Tensor):
        target.zero_()


def anonymize_caller_id(phone_number: str) -> str:
    """
    One-way SHA-256 pseudonymization of phone numbers for audit logs to protect PII.
    Leaves only the country code and last 2 digits for operational triage.
    """
    if not phone_number or len(phone_number) < 4:
        return "ANONYMOUS"
    salt = settings.JWT_SECRET_KEY[:8]
    digest = hashlib.sha256(f"{phone_number}_{salt}".encode()).hexdigest()[:12]
    masked = f"{phone_number[:3]}***{phone_number[-2:]} (hash:{digest})"
    return masked


async def verify_api_key(
    x_api_key: Optional[str] = Security(api_key_header),
) -> bool:
    """
    Validates the X-API-Key header against the configured secret.
    Allows anonymous access in development mode if enabled.
    """
    if settings.ALLOW_ANONYMOUS_DEV and settings.ENVIRONMENT == "development":
        return True

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required authentication header 'X-API-Key'.",
        )

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key provided.",
        )

    return True
