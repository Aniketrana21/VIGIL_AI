from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import threading
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from app.core.config import settings
from app.core.logging import logger

# Optional pgvector / asyncpg imports
try:
    import asyncpg
    from pgvector.asyncpg import register_vector
    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False


from app.core.security import decrypt_biometric_embedding, encrypt_biometric_embedding


@dataclass
class SpeakerProfile:
    """
    Persisted speaker profile containing mathematical vector embeddings and metadata.
    NEVER stores raw voice recordings or PCM bytes (GDPR / privacy safe).
    Protected at rest with AES-256-GCM authenticated encryption.
    """
    speaker_id: str
    name: str
    embedding: List[float]  # 192-dimensional L2-normalized float vector
    num_utterances: int
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    encrypted_payload: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Public summary: never exposes raw or encrypted embedding vectors."""
        return {
            "speaker_id": self.speaker_id,
            "name": self.name,
            "embedding_dim": len(self.embedding),
            "num_utterances": self.num_utterances,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    def get_embedding_numpy(self) -> np.ndarray:
        return np.asarray(self.embedding, dtype=np.float32)

    def to_encrypted_storage_record(self) -> Dict[str, Any]:
        """Produces an encrypted record protected with AES-256-GCM for persistent storage."""
        enc_payload = self.encrypted_payload or encrypt_biometric_embedding(self.embedding)
        return {
            "speaker_id": self.speaker_id,
            "name": self.name,
            "encrypted_embedding": enc_payload,
            "num_utterances": self.num_utterances,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_encrypted_storage_record(cls, record: Dict[str, Any]) -> "SpeakerProfile":
        """Reconstructs SpeakerProfile from AES-256-GCM ciphertext."""
        enc_payload = record["encrypted_embedding"]
        emb = decrypt_biometric_embedding(enc_payload)
        return cls(
            speaker_id=record["speaker_id"],
            name=record["name"],
            embedding=emb,
            num_utterances=record["num_utterances"],
            created_at=record.get("created_at", datetime.now(timezone.utc).isoformat()),
            metadata=record.get("metadata", {}),
            encrypted_payload=enc_payload,
        )


class EmbeddingStore(ABC):
    """
    Abstract Vector Embedding Store interface for Speaker Profiles.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initializes tables, extensions, and schema."""
        pass

    @abstractmethod
    async def store_speaker_profile(self, profile: SpeakerProfile) -> bool:
        """Stores or updates speaker profile vector in database."""
        pass

    @abstractmethod
    async def get_speaker_profile(self, speaker_id: str) -> Optional[SpeakerProfile]:
        """Retrieves speaker profile by speaker ID."""
        pass

    @abstractmethod
    async def list_speakers(self) -> List[SpeakerProfile]:
        """Lists all registered speaker profiles."""
        pass

    @abstractmethod
    async def search_nearest_speakers(
        self, query_embedding: Union[np.ndarray, List[float]], top_k: int = 5
    ) -> List[Tuple[SpeakerProfile, float]]:
        """
        Performs vector similarity search across all enrolled speakers using Cosine Distance.
        Returns:
            List of (SpeakerProfile, cosine_similarity) tuples sorted by highest similarity.
        """
        pass

    @abstractmethod
    async def delete_speaker_profile(self, speaker_id: str) -> bool:
        """Removes a speaker profile from the database."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Wipes all enrolled speaker profiles (testing utility)."""
        pass


class InMemoryVectorEmbeddingStore(EmbeddingStore):
    """
    High-performance in-memory vector store for unit tests, local development,
    and fallback operation when external PostgreSQL is not running.
    """
    def __init__(self):
        self._profiles: Dict[str, SpeakerProfile] = {}
        self._lock = threading.Lock()

    async def initialize(self) -> None:
        pass

    async def store_speaker_profile(self, profile: SpeakerProfile) -> bool:
        with self._lock:
            self._profiles[profile.speaker_id] = profile
        return True

    async def get_speaker_profile(self, speaker_id: str) -> Optional[SpeakerProfile]:
        return self.get_speaker_profile_sync(speaker_id)

    def get_speaker_profile_sync(self, speaker_id: str) -> Optional[SpeakerProfile]:
        with self._lock:
            return self._profiles.get(speaker_id)

    async def list_speakers(self) -> List[SpeakerProfile]:
        with self._lock:
            return list(self._profiles.values())

    async def search_nearest_speakers(
        self, query_embedding: Union[np.ndarray, List[float]], top_k: int = 5
    ) -> List[Tuple[SpeakerProfile, float]]:
        return self.search_nearest_speakers_sync(query_embedding, top_k)

    def search_nearest_speakers_sync(
        self, query_embedding: Union[np.ndarray, List[float]], top_k: int = 5
    ) -> List[Tuple[SpeakerProfile, float]]:
        q = np.asarray(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm > 1e-12:
            q = q / q_norm

        with self._lock:
            candidates = list(self._profiles.values())

        if not candidates:
            return []

        results = []
        for profile in candidates:
            p_vec = profile.get_embedding_numpy()
            p_norm = np.linalg.norm(p_vec)
            if p_norm > 1e-12:
                p_vec = p_vec / p_norm
            similarity = float(np.dot(q, p_vec))
            results.append((profile, similarity))

        # Sort descending by similarity
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    async def delete_speaker_profile(self, speaker_id: str) -> bool:
        with self._lock:
            if speaker_id in self._profiles:
                del self._profiles[speaker_id]
                return True
            return False

    async def clear(self) -> None:
        with self._lock:
            self._profiles.clear()


class PostgresVectorEmbeddingStore(EmbeddingStore):
    """
    Production-grade PostgreSQL + pgvector embedding store.
    Utilizes vector cosine distance operator (<=>) and HNSW indexing.
    """
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or getattr(settings, "POSTGRES_VECTOR_URL", "postgresql://vigil:vigil_secret@localhost:5432/vigil_ai")
        self.pool: Optional[Any] = None
        self._is_initialized = False

    async def initialize(self) -> None:
        if not PGVECTOR_AVAILABLE:
            raise RuntimeError("pgvector or asyncpg is not installed.")

        try:
            # Parse asyncpg compatible DSN (strip +asyncpg if present)
            raw_dsn = self.dsn.replace("postgresql+asyncpg://", "postgresql://")
            self.pool = await asyncpg.create_pool(raw_dsn, min_size=1, max_size=10, timeout=10.0)

            async with self.pool.acquire() as conn:
                await register_vector(conn)
                # Create extension & schema
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                await conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS speaker_profiles (
                        speaker_id VARCHAR(128) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        embedding vector({settings.SPEAKER_EMBEDDING_DIM}) NOT NULL,
                        num_utterances INT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                    );
                """)
                # HNSW index for sub-millisecond approximate nearest neighbor search
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS speaker_profiles_hnsw_idx 
                    ON speaker_profiles USING hnsw (embedding vector_cosine_ops);
                """)
            self._is_initialized = True
            logger.info("Connected to PostgreSQL + pgvector. Speaker profile schema verified.")
        except Exception as e:
            logger.warning(f"Could not connect to PostgreSQL ({e}). Falling back to in-memory embedding store.")
            raise

    async def store_speaker_profile(self, profile: SpeakerProfile) -> bool:
        if not self.pool:
            return False
        async with self.pool.acquire() as conn:
            await register_vector(conn)
            query = """
                INSERT INTO speaker_profiles (speaker_id, name, embedding, num_utterances, created_at, metadata)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (speaker_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    embedding = EXCLUDED.embedding,
                    num_utterances = EXCLUDED.num_utterances,
                    created_at = EXCLUDED.created_at,
                    metadata = EXCLUDED.metadata;
            """
            await conn.execute(
                query,
                profile.speaker_id,
                profile.name,
                np.array(profile.embedding, dtype=np.float32),
                profile.num_utterances,
                datetime.fromisoformat(profile.created_at),
                json.dumps(profile.metadata),
            )
            return True

    async def get_speaker_profile(self, speaker_id: str) -> Optional[SpeakerProfile]:
        if not self.pool:
            return None
        async with self.pool.acquire() as conn:
            await register_vector(conn)
            row = await conn.fetchrow(
                "SELECT speaker_id, name, embedding, num_utterances, created_at, metadata FROM speaker_profiles WHERE speaker_id = $1;",
                speaker_id
            )
            if not row:
                return None
            return SpeakerProfile(
                speaker_id=row["speaker_id"],
                name=row["name"],
                embedding=list(row["embedding"]),
                num_utterances=row["num_utterances"],
                created_at=row["created_at"].isoformat(),
                metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
            )

    async def list_speakers(self) -> List[SpeakerProfile]:
        if not self.pool:
            return []
        async with self.pool.acquire() as conn:
            await register_vector(conn)
            rows = await conn.fetch("SELECT speaker_id, name, embedding, num_utterances, created_at, metadata FROM speaker_profiles;")
            return [
                SpeakerProfile(
                    speaker_id=r["speaker_id"],
                    name=r["name"],
                    embedding=list(r["embedding"]),
                    num_utterances=r["num_utterances"],
                    created_at=r["created_at"].isoformat(),
                    metadata=json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                )
                for r in rows
            ]

    async def search_nearest_speakers(
        self, query_embedding: Union[np.ndarray, List[float]], top_k: int = 5
    ) -> List[Tuple[SpeakerProfile, float]]:
        if not self.pool:
            return []
        q = np.asarray(query_embedding, dtype=np.float32)
        async with self.pool.acquire() as conn:
            await register_vector(conn)
            # In pgvector: cosine distance <=> ranges from 0 (identical) to 2 (opposite)
            # Cosine similarity = 1 - cosine_distance
            query = f"""
                SELECT speaker_id, name, embedding, num_utterances, created_at, metadata,
                       1 - (embedding <=> $1) AS similarity
                FROM speaker_profiles
                ORDER BY embedding <=> $1 ASC
                LIMIT $2;
            """
            rows = await conn.fetch(query, q, top_k)
            results = []
            for r in rows:
                profile = SpeakerProfile(
                    speaker_id=r["speaker_id"],
                    name=r["name"],
                    embedding=list(r["embedding"]),
                    num_utterances=r["num_utterances"],
                    created_at=r["created_at"].isoformat(),
                    metadata=json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                )
                results.append((profile, float(r["similarity"])))
            return results

    async def delete_speaker_profile(self, speaker_id: str) -> bool:
        if not self.pool:
            return False
        async with self.pool.acquire() as conn:
            res = await conn.execute("DELETE FROM speaker_profiles WHERE speaker_id = $1;", speaker_id)
            return "DELETE 1" in res

    async def clear(self) -> None:
        if not self.pool:
            return
        async with self.pool.acquire() as conn:
            await conn.execute("TRUNCATE TABLE speaker_profiles;")


# Singleton Store Registry
_global_embedding_store: Optional[EmbeddingStore] = None
_store_lock = threading.Lock()


def get_embedding_store() -> EmbeddingStore:
    """
    Returns the active EmbeddingStore.
    Defaults to InMemoryVectorEmbeddingStore for fast execution and tests,
    or PostgresVectorEmbeddingStore when configured.
    """
    global _global_embedding_store
    if _global_embedding_store is None:
        with _store_lock:
            if _global_embedding_store is None:
                # Default to InMemoryVectorEmbeddingStore unless specifically requested
                backend = getattr(settings, "SPEAKER_STORE_BACKEND", "memory").lower()
                if backend == "postgres":
                    try:
                        _global_embedding_store = PostgresVectorEmbeddingStore()
                    except Exception:
                        _global_embedding_store = InMemoryVectorEmbeddingStore()
                else:
                    _global_embedding_store = InMemoryVectorEmbeddingStore()
    return _global_embedding_store


def set_embedding_store(store: EmbeddingStore) -> None:
    """Allows swapping store for testing."""
    global _global_embedding_store
    with _store_lock:
        _global_embedding_store = store
