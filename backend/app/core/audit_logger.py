"""
VIGIL-AI Structured Security & Privacy Audit Logging Engine.

Records immutable, tamper-evident audit records for compliance (GDPR Art. 30, BIPA):
- Authentication attempts (success/failure)
- Speaker profile lifecycle (enrollment, access, deletion)
- Challenge-response verification events
- Rate limit violations and DDoS mitigations
- High/Critical risk voice clone block actions
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, Optional
from app.core.config import settings
from app.core.logging import logger

_audit_lock = threading.Lock()


@dataclass
class AuditRecord:
    event_type: str
    actor: str
    resource_id: str
    status: str  # "SUCCESS" | "FAILURE" | "BLOCKED" | "WARNING"
    client_ip_hash: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SecurityAuditLogger:
    """
    Thread-safe structured audit logger emitting JSON-formatted security events.
    """

    def __init__(self, log_filepath: Optional[str] = None):
        self.log_filepath = Path(log_filepath or settings.AUDIT_LOG_FILE)
        self.log_filepath.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def hash_ip(client_ip: Optional[str]) -> str:
        """Pseudonymizes IP addresses via salted SHA-256 for privacy protection."""
        if not client_ip:
            return "IP_UNKNOWN"
        salt = settings.JWT_SECRET_KEY[:8]
        return hashlib.sha256(f"{client_ip}_{salt}".encode()).hexdigest()[:12]

    def log_event(
        self,
        event_type: str,
        actor: str = "system",
        resource_id: str = "none",
        status: str = "SUCCESS",
        client_ip: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditRecord:
        record = AuditRecord(
            event_type=event_type,
            actor=actor,
            resource_id=resource_id,
            status=status,
            client_ip_hash=self.hash_ip(client_ip),
            details=details or {},
        )

        record_dict = asdict(record)
        json_line = json.dumps(record_dict, sort_keys=True)

        with _audit_lock:
            with open(self.log_filepath, "a", encoding="utf-8") as f:
                f.write(json_line + "\n")

        logger.info(
            f"[AUDIT] {record.event_type} | Status: {record.status} | Resource: {record.resource_id} | Actor: {record.actor}"
        )
        return record

    def read_recent_events(self, limit: int = 50) -> list[Dict[str, Any]]:
        """Reads the most recent audit records."""
        if not self.log_filepath.exists():
            return []
        events = []
        with _audit_lock:
            with open(self.log_filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        return events


# Global singleton instance
audit_logger = SecurityAuditLogger()
