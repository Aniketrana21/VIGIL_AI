"""
VIGIL-AI Defensive Security and Privacy Hardening Module.

Implements:
1. Volatile Memory Scrubbing (Zero-Retention privacy mandate)
2. AES-256-GCM Authenticated Encryption for Biometric Embeddings at Rest
3. Strict Identifier and Path Sanitization (Path Traversal & Injection Prevention)
4. API Key & JWT Token Authentication / Scopes
5. WebSocket Handshake Authentication Verification
6. Audio Payload Size & Alignment Validation
7. Sensitive PII & Transcript Redaction
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Union
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader
import numpy as np
import torch
from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Strict regex for speaker IDs, session IDs, and file handles: alphanumeric, hyphens, underscores only (2 to 64 chars)
SAFE_IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{2,64}$")


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


def sanitize_identifier(identifier: str) -> str:
    """
    Strict validation against Path Traversal (CWE-22) and Command/SQL Injection (CWE-89).
    Rejects any input containing '..', '/', '\\', null bytes, or non-whitelisted characters.
    """
    if not identifier or not isinstance(identifier, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Identifier cannot be empty.",
        )

    clean_id = identifier.strip()
    if "\x00" in clean_id or ".." in clean_id or "/" in clean_id or "\\" in clean_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Security violation: Path traversal or injection sequence detected.",
        )

    if not SAFE_IDENTIFIER_REGEX.match(clean_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Identifier must be 2-64 characters alphanumeric, hyphens, or underscores only.",
        )

    return clean_id


def _get_encryption_key(key_hex: Optional[str] = None) -> bytes:
    """Derives 32-byte key for AES-256-GCM."""
    raw_hex = key_hex or settings.BIOMETRIC_ENCRYPTION_KEY
    try:
        key_bytes = bytes.fromhex(raw_hex)
        if len(key_bytes) != 32:
            return hashlib.sha256(key_bytes).digest()
        return key_bytes
    except ValueError:
        return hashlib.sha256(raw_hex.encode("utf-8")).digest()


def encrypt_sensitive_data(plaintext: str, key_hex: Optional[str] = None) -> str:
    """
    Encrypts arbitrary sensitive strings at rest using AES-256-GCM.
    Returns: Base64-encoded string format: [12-byte Nonce][Ciphertext + 16-byte Tag]
    """
    key = _get_encryption_key(key_hex)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit standard GCM nonce
    data = plaintext.encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, data, None)
    payload = nonce + ciphertext
    return base64.urlsafe_b64encode(payload).decode("utf-8")


def decrypt_sensitive_data(ciphertext_b64: str, key_hex: Optional[str] = None) -> str:
    """
    Decrypts AES-256-GCM encrypted strings. Authenticates ciphertext integrity.
    """
    key = _get_encryption_key(key_hex)
    payload = base64.urlsafe_b64decode(ciphertext_b64.encode("utf-8"))
    if len(payload) < 28:  # 12 nonce + 16 auth tag minimum
        raise ValueError("Malformed ciphertext: payload length too short.")
    nonce = payload[:12]
    ciphertext = payload[12:]
    aesgcm = AESGCM(key)
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode("utf-8")


def encrypt_biometric_embedding(embedding: List[float], key_hex: Optional[str] = None) -> str:
    """
    Encrypts sensitive 192-dimensional floating-point speaker embeddings at rest using AES-256-GCM.
    GDPR Article 9 & BIPA compliance: raw vectors are never stored in plaintext on disk.
    """
    arr = np.asarray(embedding, dtype=np.float32)
    raw_bytes = arr.tobytes()
    key = _get_encryption_key(key_hex)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, raw_bytes, None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_biometric_embedding(encrypted_b64: str, key_hex: Optional[str] = None) -> List[float]:
    """
    Decrypts AES-256-GCM protected biometric embeddings into standard float vectors.
    """
    key = _get_encryption_key(key_hex)
    payload = base64.urlsafe_b64decode(encrypted_b64.encode("utf-8"))
    if len(payload) < 28:
        raise ValueError("Invalid encrypted biometric embedding payload.")
    nonce = payload[:12]
    ciphertext = payload[12:]
    aesgcm = AESGCM(key)
    raw_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    arr = np.frombuffer(raw_bytes, dtype=np.float32)
    return arr.tolist()


def validate_audio_payload(raw_bytes: bytes, max_bytes: Optional[int] = None) -> None:
    """
    Validates uploaded or streamed audio payloads against DoS, memory exhaustion, and alignment flaws.
    """
    limit = max_bytes or settings.MAX_AUDIO_PAYLOAD_BYTES
    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio payload is empty.",
        )
    if len(raw_bytes) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Audio payload ({len(raw_bytes)} bytes) exceeds max allowed limit ({limit} bytes).",
        )
    if len(raw_bytes) % 2 != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed 16-bit PCM audio payload: byte length must be even.",
        )


def create_access_token(data: Dict[str, Any], expires_delta_sec: int = 3600) -> str:
    """Creates signed HMAC-SHA256 session token with expiration."""
    payload = data.copy()
    payload["exp"] = int(time.time()) + expires_delta_sec
    payload_json = json.dumps(payload, sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    sig = hmac.new(
        settings.JWT_SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{payload_b64}.{sig}"


def verify_ws_token(token: Optional[str]) -> bool:
    """
    Validates token for WebSocket handshake.
    If no token is provided and WS_AUTH_REQUIRED is disabled, allows anonymous connections in development mode.
    If a token is provided, strictly validates its HMAC signature and expiration.
    """
    if not token:
        return not settings.WS_AUTH_REQUIRED and settings.ENVIRONMENT == "development"

    try:
        parts = token.split(".")
        if len(parts) != 2:
            # Check if it's the raw API key
            return hmac.compare_digest(token, settings.API_KEY)

        payload_b64, sig = parts
        expected_sig = hmac.new(
            settings.JWT_SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected_sig):
            return False

        # Check expiration
        padding = "=" * (4 - (len(payload_b64) % 4))
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding).decode())
        if payload.get("exp", 0) < int(time.time()):
            return False

        return True
    except Exception:
        return False


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

    if not hmac.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key provided.",
        )

    return True


def redact_sensitive_transcript(text: str) -> str:
    """
    Redacts sensitive financial PII (OTPs, card numbers, passwords, PINs) from text.
    Ensures zero leak of authentication secrets in transcripts and logs.
    """
    if not text:
        return ""
    # Redact 4-8 digit numeric codes (OTPs, PINs)
    redacted = re.sub(r"\b\d{4,8}\b", "[REDACTED_OTP]", text)
    # Redact 16-digit credit card sequences
    redacted = re.sub(r"\b(?:\d[ -]*?){13,16}\b", "[REDACTED_CARD]", redacted)
    # Redact passwords mentioned in context
    redacted = re.sub(r"(?i)(password|passcode|secret|pin)\s*(is|:|=)\s*\S+", r"\1 \2 [REDACTED]", redacted)
    return redacted
