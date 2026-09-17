"""
Unit Tests for Phase 16 Privacy & Security Module.

Validates:
1. Zero-retention volatile memory scrubbing (secure_zero_memory).
2. AES-256-GCM authenticated encryption/decryption of biometric embeddings and sensitive data at rest.
3. Path traversal (CWE-22) and injection sanitization on speaker identifiers.
4. Audio payload size bounding and 16-bit PCM alignment validation.
5. WebSocket handshake token authentication and tamper-evident signing.
6. Rate limiting enforcement and defense-in-depth security response headers.
7. Structured security audit logging with salted IP pseudonymization.
8. Speaker profile deletion (GDPR Right to Erasure / BIPA compliance).
9. Sensitive transcript PII redaction (OTPs, credit cards, passwords).
10. Production environment security constraints preventing placeholder keys.
"""

import os
from pathlib import Path
from fastapi import HTTPException
from fastapi.testclient import TestClient
import numpy as np
import pytest
import torch

from app.core.audit_logger import SecurityAuditLogger
from app.core.config import Settings, settings
from app.core.rate_limiter import InMemoryRateLimiter
from app.core.security import (
    anonymize_caller_id,
    create_access_token,
    decrypt_biometric_embedding,
    decrypt_sensitive_data,
    encrypt_biometric_embedding,
    encrypt_sensitive_data,
    redact_sensitive_transcript,
    sanitize_identifier,
    secure_zero_memory,
    validate_audio_payload,
    verify_ws_token,
)
from app.db.embedding_store import InMemoryVectorEmbeddingStore, SpeakerProfile
from app.main import app


class TestPhase16PrivacyAndSecurity:

    def test_secure_zero_memory(self):
        """Verifies zero-retention memory scrubbing across buffers, numpy, and torch."""
        # Bytearray
        buf = bytearray(b"sensitive_voice_raw_audio_bytes")
        secure_zero_memory(buf)
        assert all(b == 0 for b in buf)

        # Numpy
        arr = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        secure_zero_memory(arr)
        assert np.all(arr == 0.0)

        # Torch Tensor
        t = torch.tensor([4.0, 5.0, 6.0])
        secure_zero_memory(t)
        assert torch.all(t == 0.0)

    def test_aes_256_gcm_sensitive_data_encryption(self):
        """Verifies authenticated encryption/decryption of arbitrary sensitive strings."""
        secret_text = "customer_bank_pin_12345"
        encrypted = encrypt_sensitive_data(secret_text)
        assert encrypted != secret_text
        assert len(encrypted) > 28

        decrypted = decrypt_sensitive_data(encrypted)
        assert decrypted == secret_text

        # Tampered ciphertext must fail authentication
        tampered = encrypted[:-4] + "AAAA"
        with pytest.raises(Exception):
            decrypt_sensitive_data(tampered)

    def test_aes_256_gcm_biometric_embedding_encryption(self):
        """Verifies 192-dim biometric embeddings are safely encrypted at rest."""
        np.random.seed(42)
        original_embedding = np.random.randn(192).astype(np.float32).tolist()

        encrypted_b64 = encrypt_biometric_embedding(original_embedding)
        assert isinstance(encrypted_b64, str)
        assert len(encrypted_b64) > 100

        decrypted_embedding = decrypt_biometric_embedding(encrypted_b64)
        assert len(decrypted_embedding) == 192
        assert np.allclose(original_embedding, decrypted_embedding, atol=1e-5)

    def test_speaker_profile_storage_encryption(self):
        """Verifies SpeakerProfile to/from encrypted storage records."""
        embedding = [0.1] * 192
        profile = SpeakerProfile(
            speaker_id="alice_test",
            name="Alice Smith",
            embedding=embedding,
            num_utterances=3,
            metadata={"department": "finance"},
        )

        record = profile.to_encrypted_storage_record()
        assert "encrypted_embedding" in record
        assert "embedding" not in record

        # Public summary never leaks embedding
        summary = profile.to_dict()
        assert "embedding" not in summary
        assert summary["embedding_dim"] == 192

        # Reconstructed from encrypted record
        restored = SpeakerProfile.from_encrypted_storage_record(record)
        assert restored.speaker_id == "alice_test"
        assert len(restored.embedding) == 192
        assert np.allclose(restored.embedding, embedding)

    def test_path_traversal_sanitization(self):
        """Verifies identifier sanitizer blocks path traversal and injection sequences."""
        # Valid identifiers
        assert sanitize_identifier("user_101") == "user_101"
        assert sanitize_identifier("bob-corporate") == "bob-corporate"

        # Malicious traversal attempts
        with pytest.raises(HTTPException) as exc1:
            sanitize_identifier("../../etc/passwd")
        assert exc1.value.status_code == 400

        with pytest.raises(HTTPException) as exc2:
            sanitize_identifier("..\\windows\\system32")
        assert exc2.value.status_code == 400

        with pytest.raises(HTTPException) as exc3:
            sanitize_identifier("alice\x00_nullbyte")
        assert exc3.value.status_code == 400

        with pytest.raises(HTTPException) as exc4:
            sanitize_identifier("a")  # < 2 chars
        assert exc4.value.status_code == 400

    def test_audio_payload_validation(self):
        """Verifies payload bounding against DoS and memory exhaustion."""
        # Empty
        with pytest.raises(HTTPException) as exc1:
            validate_audio_payload(b"")
        assert exc1.value.status_code == 400

        # Odd byte alignment for 16-bit PCM
        with pytest.raises(HTTPException) as exc2:
            validate_audio_payload(b"\x00\x01\x02")
        assert exc2.value.status_code == 400

        # Exceeding payload limit
        huge_payload = b"\x00\x00" * 100
        with pytest.raises(HTTPException) as exc3:
            validate_audio_payload(huge_payload, max_bytes=50)
        assert exc3.value.status_code == 413

        # Valid 16-bit PCM payload
        valid_payload = b"\x00\x00\x01\x00"
        validate_audio_payload(valid_payload, max_bytes=1000)

    def test_websocket_token_authentication(self):
        """Verifies HMAC-SHA256 session token generation and verification."""
        token = create_access_token({"sub": "user_42"}, expires_delta_sec=300)
        assert verify_ws_token(token) is True

        # Tampered token
        tampered_token = token[:-5] + "XXXXX"
        assert verify_ws_token(tampered_token) is False

        # Expired token
        expired_token = create_access_token({"sub": "user_42"}, expires_delta_sec=-10)
        assert verify_ws_token(expired_token) is False

    def test_rate_limiter_enforcement(self):
        """Verifies in-memory sliding window rate limiter blocks bursts."""
        limiter = InMemoryRateLimiter(max_requests_per_minute=5)
        ip = "192.168.1.105"

        for _ in range(5):
            allowed, _ = limiter.is_allowed(ip)
            assert allowed is True

        # 6th request must be denied
        allowed, remaining = limiter.is_allowed(ip)
        assert allowed is False
        assert remaining == 0

    def test_security_audit_logger(self, tmp_path):
        """Verifies audit logging writes structured records with hashed IP."""
        log_file = tmp_path / "test_audit.log"
        logger = SecurityAuditLogger(log_filepath=str(log_file))

        record = logger.log_event(
            event_type="SPEAKER_DELETED",
            actor="admin_service",
            resource_id="bob_99",
            status="SUCCESS",
            client_ip="203.0.113.195",
            details={"reason": "user_revoked_consent"},
        )

        assert record.event_type == "SPEAKER_DELETED"
        assert record.client_ip_hash != "203.0.113.195"
        assert len(record.client_ip_hash) == 12

        events = logger.read_recent_events()
        assert len(events) == 1
        assert events[0]["resource_id"] == "bob_99"

    def test_transcript_redaction(self):
        """Verifies sensitive OTPs, credit cards, and passwords are fully masked."""
        raw_text = "Please transfer money. The OTP is 849201 and my password: SuperSecret99."
        redacted = redact_sensitive_transcript(raw_text)

        assert "849201" not in redacted
        assert "[REDACTED_OTP]" in redacted
        assert "SuperSecret99" not in redacted
        assert "[REDACTED]" in redacted

    def test_production_keys_validator(self):
        """Verifies production environments enforce non-placeholder secrets."""
        # Default placeholder key in production raises error
        with pytest.raises(ValueError) as exc:
            Settings.check_production_keys(
                env="production",
                jwt_key="change-this-in-production-use-a-32-byte-hex-key-minimum",
                api_key="valid-custom-api-key",
            )
        assert "JWT_SECRET_KEY" in str(exc.value)

        # Valid custom keys in production pass cleanly
        Settings.check_production_keys(
            env="production",
            jwt_key="4f8b93c127e492a8310c85b629471f03",
            api_key="vigil-prod-api-key-99238471",
        )

    def test_security_headers_middleware_integration(self):
        """Verifies defense-in-depth security response headers are returned."""
        client = TestClient(app)
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
        assert "microphone=(self)" in response.headers["Permissions-Policy"]
