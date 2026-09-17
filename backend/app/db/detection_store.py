"""
VIGIL-AI: Detection Events Persistence Store.
Stores all real-time voice cloning detections, biometric verifications, acoustic liveness scores,
and multi-signal risk verdicts into PostgreSQL (with SQLite / relational local DB fallback).
"""
from abc import ABC, abstractmethod
import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.core.logging import logger

try:
    import asyncpg
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False


@dataclass
class DetectionEvent:
    """Standard persisted record for every detection evaluation."""
    session_id: str
    risk_score: int
    risk_level: str
    action: str
    deepfake_score: Optional[float] = None
    deepfake_label: Optional[str] = None
    speaker_id: Optional[str] = None
    speaker_similarity: Optional[float] = None
    liveness_score: Optional[float] = None
    replay_probability: Optional[float] = None
    conversation_intent: Optional[str] = None
    conversation_risk: Optional[float] = None
    confidence: float = 1.0
    signals: List[str] = field(default_factory=list)
    contributing_signals: List[str] = field(default_factory=list)
    explanation: str = ""
    caller_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "deepfake_score": self.deepfake_score,
            "deepfake_label": self.deepfake_label,
            "speaker_id": self.speaker_id,
            "speaker_similarity": self.speaker_similarity,
            "liveness_score": self.liveness_score,
            "replay_probability": self.replay_probability,
            "conversation_intent": self.conversation_intent,
            "conversation_risk": self.conversation_risk,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "action": self.action,
            "confidence": round(self.confidence, 3),
            "signals": self.signals,
            "contributing_signals": self.contributing_signals,
            "explanation": self.explanation,
            "caller_id": self.caller_id,
            "metadata": self.metadata,
        }


class DetectionStore(ABC):
    """Abstract interface for detection event persistence."""

    @abstractmethod
    async def store_detection(self, event: DetectionEvent) -> bool:
        pass

    @abstractmethod
    async def get_detections(self, session_id: Optional[str] = None, limit: int = 50) -> List[DetectionEvent]:
        pass

    @abstractmethod
    async def get_detection_stats(self) -> Dict[str, Any]:
        pass


class PostgresDetectionStore(DetectionStore):
    """
    Production-grade PostgreSQL persistence store for voice detection events.
    Utilizes connection pooling and parameterized batch queries.
    """
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or getattr(settings, "POSTGRES_VECTOR_URL", "postgresql://vigil:vigil_secret@localhost:5432/vigil_ai")
        self.pool: Optional[Any] = None
        self._is_initialized = False

    async def initialize(self) -> None:
        if not POSTGRES_AVAILABLE:
            raise RuntimeError("asyncpg is not installed for PostgreSQL support.")

        raw_dsn = self.dsn.replace("postgresql+asyncpg://", "postgresql://")
        self.pool = await asyncpg.create_pool(raw_dsn, min_size=1, max_size=10, timeout=5.0)

        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS detection_events (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(128) NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    deepfake_score FLOAT,
                    deepfake_label VARCHAR(32),
                    speaker_id VARCHAR(128),
                    speaker_similarity FLOAT,
                    liveness_score FLOAT,
                    replay_probability FLOAT,
                    conversation_intent VARCHAR(64),
                    conversation_risk FLOAT,
                    risk_score INT NOT NULL,
                    risk_level VARCHAR(32) NOT NULL,
                    action VARCHAR(32) NOT NULL,
                    confidence FLOAT,
                    signals JSONB NOT NULL DEFAULT '[]'::jsonb,
                    contributing_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
                    explanation TEXT,
                    caller_id VARCHAR(128),
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                );
                CREATE INDEX IF NOT EXISTS detection_events_session_idx ON detection_events (session_id);
                CREATE INDEX IF NOT EXISTS detection_events_timestamp_idx ON detection_events (timestamp DESC);
                CREATE INDEX IF NOT EXISTS detection_events_risk_level_idx ON detection_events (risk_level);
            """)
        self._is_initialized = True
        logger.info("Connected to PostgreSQL. detection_events table initialized.")

    async def store_detection(self, event: DetectionEvent) -> bool:
        if not self.pool:
            return False
        try:
            async with self.pool.acquire() as conn:
                query = """
                    INSERT INTO detection_events (
                        session_id, timestamp, deepfake_score, deepfake_label,
                        speaker_id, speaker_similarity, liveness_score, replay_probability,
                        conversation_intent, conversation_risk, risk_score, risk_level,
                        action, confidence, signals, contributing_signals, explanation,
                        caller_id, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                    RETURNING id;
                """
                ts = datetime.fromisoformat(event.timestamp) if isinstance(event.timestamp, str) else event.timestamp
                row = await conn.fetchrow(
                    query,
                    event.session_id,
                    ts,
                    event.deepfake_score,
                    event.deepfake_label,
                    event.speaker_id,
                    event.speaker_similarity,
                    event.liveness_score,
                    event.replay_probability,
                    event.conversation_intent,
                    event.conversation_risk,
                    event.risk_score,
                    event.risk_level,
                    event.action,
                    event.confidence,
                    json.dumps(event.signals),
                    json.dumps(event.contributing_signals),
                    event.explanation,
                    event.caller_id,
                    json.dumps(event.metadata),
                )
                if row:
                    event.id = row["id"]
                return True
        except Exception as e:
            logger.error(f"Failed to store detection event to PostgreSQL: {e}")
            return False

    async def get_detections(self, session_id: Optional[str] = None, limit: int = 50) -> List[DetectionEvent]:
        if not self.pool:
            return []
        async with self.pool.acquire() as conn:
            if session_id:
                rows = await conn.fetch(
                    "SELECT * FROM detection_events WHERE session_id = $1 ORDER BY timestamp DESC LIMIT $2;",
                    session_id, limit
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM detection_events ORDER BY timestamp DESC LIMIT $1;",
                    limit
                )
            results = []
            for r in rows:
                results.append(DetectionEvent(
                    id=r["id"],
                    session_id=r["session_id"],
                    timestamp=r["timestamp"].isoformat(),
                    deepfake_score=r["deepfake_score"],
                    deepfake_label=r["deepfake_label"],
                    speaker_id=r["speaker_id"],
                    speaker_similarity=r["speaker_similarity"],
                    liveness_score=r["liveness_score"],
                    replay_probability=r["replay_probability"],
                    conversation_intent=r["conversation_intent"],
                    conversation_risk=r["conversation_risk"],
                    risk_score=r["risk_score"],
                    risk_level=r["risk_level"],
                    action=r["action"],
                    confidence=r["confidence"],
                    signals=json.loads(r["signals"]) if isinstance(r["signals"], str) else r["signals"],
                    contributing_signals=json.loads(r["contributing_signals"]) if isinstance(r["contributing_signals"], str) else r["contributing_signals"],
                    explanation=r["explanation"] or "",
                    caller_id=r["caller_id"],
                    metadata=json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                ))
            return results

    async def get_detection_stats(self) -> Dict[str, Any]:
        if not self.pool:
            return {"total": 0}
        async with self.pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM detection_events;")
            critical = await conn.fetchval("SELECT COUNT(*) FROM detection_events WHERE risk_level = 'CRITICAL';")
            high = await conn.fetchval("SELECT COUNT(*) FROM detection_events WHERE risk_level = 'HIGH';")
            blocked = await conn.fetchval("SELECT COUNT(*) FROM detection_events WHERE action = 'BLOCK';")
            return {
                "backend": "postgresql",
                "total_detections": total,
                "critical_risk_count": critical,
                "high_risk_count": high,
                "blocked_actions_count": blocked,
            }


class SQLiteDetectionStore(DetectionStore):
    """
    Robust local relational database store using SQLite.
    Guarantees that detection events enter a database table even in local or air-gapped environments.
    """
    def __init__(self, db_path: str = "vigil_detections.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS detection_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    deepfake_score REAL,
                    deepfake_label TEXT,
                    speaker_id TEXT,
                    speaker_similarity REAL,
                    liveness_score REAL,
                    replay_probability REAL,
                    conversation_intent TEXT,
                    conversation_risk REAL,
                    risk_score INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    action TEXT NOT NULL,
                    confidence REAL,
                    signals TEXT NOT NULL,
                    contributing_signals TEXT NOT NULL,
                    explanation TEXT,
                    caller_id TEXT,
                    metadata TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_detection_session ON detection_events (session_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_detection_timestamp ON detection_events (timestamp DESC);")
            conn.commit()

    def store_detection_sync(self, event: DetectionEvent) -> bool:
        """Synchronous write method directly inserting detection into SQLite."""
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO detection_events (
                    session_id, timestamp, deepfake_score, deepfake_label,
                    speaker_id, speaker_similarity, liveness_score, replay_probability,
                    conversation_intent, conversation_risk, risk_score, risk_level,
                    action, confidence, signals, contributing_signals, explanation,
                    caller_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.session_id,
                event.timestamp,
                event.deepfake_score,
                event.deepfake_label,
                event.speaker_id,
                event.speaker_similarity,
                event.liveness_score,
                event.replay_probability,
                event.conversation_intent,
                event.conversation_risk,
                event.risk_score,
                event.risk_level,
                event.action,
                event.confidence,
                json.dumps(event.signals),
                json.dumps(event.contributing_signals),
                event.explanation,
                event.caller_id,
                json.dumps(event.metadata),
            ))
            event.id = cursor.lastrowid
            conn.commit()
            return True

    async def store_detection(self, event: DetectionEvent) -> bool:
        return await asyncio.to_thread(self.store_detection_sync, event)

    def get_detections_sync(self, session_id: Optional[str] = None, limit: int = 50) -> List[DetectionEvent]:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if session_id:
                cursor.execute("SELECT * FROM detection_events WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?", (session_id, limit))
            else:
                cursor.execute("SELECT * FROM detection_events ORDER BY timestamp DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                results.append(DetectionEvent(
                    id=r["id"],
                    session_id=r["session_id"],
                    timestamp=r["timestamp"],
                    deepfake_score=r["deepfake_score"],
                    deepfake_label=r["deepfake_label"],
                    speaker_id=r["speaker_id"],
                    speaker_similarity=r["speaker_similarity"],
                    liveness_score=r["liveness_score"],
                    replay_probability=r["replay_probability"],
                    conversation_intent=r["conversation_intent"],
                    conversation_risk=r["conversation_risk"],
                    risk_score=r["risk_score"],
                    risk_level=r["risk_level"],
                    action=r["action"],
                    confidence=r["confidence"],
                    signals=json.loads(r["signals"]) if r["signals"] else [],
                    contributing_signals=json.loads(r["contributing_signals"]) if r["contributing_signals"] else [],
                    explanation=r["explanation"] or "",
                    caller_id=r["caller_id"],
                    metadata=json.loads(r["metadata"]) if r["metadata"] else {},
                ))
            return results

    async def get_detections(self, session_id: Optional[str] = None, limit: int = 50) -> List[DetectionEvent]:
        return await asyncio.to_thread(self.get_detections_sync, session_id, limit)

    async def get_detection_stats(self) -> Dict[str, Any]:
        def _sync_stats():
            with self._lock, sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM detection_events;")
                total = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM detection_events WHERE risk_level = 'CRITICAL';")
                critical = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM detection_events WHERE risk_level = 'HIGH';")
                high = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM detection_events WHERE action = 'BLOCK';")
                blocked = cursor.fetchone()[0]
                return {
                    "backend": "sqlite",
                    "db_path": self.db_path,
                    "total_detections": total,
                    "critical_risk_count": critical,
                    "high_risk_count": high,
                    "blocked_actions_count": blocked,
                }
        return await asyncio.to_thread(_sync_stats)

    def get_detection_by_id_sync(self, event_id: int) -> Optional[DetectionEvent]:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM detection_events WHERE id = ?", (event_id,))
            r = cursor.fetchone()
            if not r:
                return None
            return DetectionEvent(
                id=r["id"],
                session_id=r["session_id"],
                timestamp=r["timestamp"],
                deepfake_score=r["deepfake_score"],
                deepfake_label=r["deepfake_label"],
                speaker_id=r["speaker_id"],
                speaker_similarity=r["speaker_similarity"],
                liveness_score=r["liveness_score"],
                replay_probability=r["replay_probability"],
                conversation_intent=r["conversation_intent"],
                conversation_risk=r["conversation_risk"],
                risk_score=r["risk_score"],
                risk_level=r["risk_level"],
                action=r["action"],
                confidence=r["confidence"],
                signals=json.loads(r["signals"]) if r["signals"] else [],
                contributing_signals=json.loads(r["contributing_signals"]) if r["contributing_signals"] else [],
                explanation=r["explanation"] or "",
                caller_id=r["caller_id"],
                metadata=json.loads(r["metadata"]) if r["metadata"] else {},
            )

    def delete_detection_sync(self, event_id: int) -> bool:
        """Deletes a detection record by its primary key ID."""
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM detection_events WHERE id = ?", (event_id,))
            conn.commit()
            return cursor.rowcount > 0

    def update_detection_sync(self, event_id: int, updates: Dict[str, Any]) -> bool:
        """Updates fields of an existing detection record."""
        valid_cols = {
            "risk_score", "risk_level", "action", "deepfake_score", "deepfake_label",
            "speaker_id", "speaker_similarity", "liveness_score", "replay_probability",
            "conversation_intent", "conversation_risk", "confidence", "explanation", "caller_id"
        }
        filtered = {k: v for k, v in updates.items() if k in valid_cols}
        if "signals" in updates:
            filtered["signals"] = json.dumps(updates["signals"])
        if "metadata" in updates:
            filtered["metadata"] = json.dumps(updates["metadata"])

        if not filtered:
            return False

        set_clauses = [f"{k} = ?" for k in filtered.keys()]
        values = list(filtered.values()) + [event_id]

        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            query = f"UPDATE detection_events SET {', '.join(set_clauses)} WHERE id = ?"
            cursor.execute(query, tuple(values))
            conn.commit()
            return cursor.rowcount > 0

    def clear_detections_sync(self) -> int:
        """Deletes all detection records from SQLite."""
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM detection_events;")
            count = cursor.rowcount
            conn.commit()
            return count



# Global Store Singleton
_detection_store_instance: Optional[DetectionStore] = None
_detection_store_lock = threading.Lock()


def get_detection_store() -> DetectionStore:
    """Factory creating or returning the configured DetectionStore instance."""
    global _detection_store_instance
    with _detection_store_lock:
        if _detection_store_instance is None:
            # Default to SQLite local database, upgradeable to PostgreSQL
            _detection_store_instance = SQLiteDetectionStore(db_path="vigil_detections.db")
    return _detection_store_instance


def set_detection_store(store: DetectionStore) -> None:
    global _detection_store_instance
    with _detection_store_lock:
        _detection_store_instance = store


def record_detection_event(event: DetectionEvent) -> None:
    """
    Dispatcher to record a detection event into PostgreSQL or SQLite database.
    Does not crash on transient DB errors.
    """
    try:
        store = get_detection_store()
        if hasattr(store, "store_detection_sync"):
            store.store_detection_sync(event)
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(store.store_detection(event))
        except RuntimeError:
            asyncio.run(store.store_detection(event))
    except Exception as e:
        logger.warning(f"Failed to record detection event to database: {e}")
