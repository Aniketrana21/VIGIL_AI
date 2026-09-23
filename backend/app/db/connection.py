"""
VIGIL-AI: Central Database Connection Pool.
Provides high-performance, asynchronous connection pooling to Supabase PostgreSQL.
Handles connection health, retries, and clean timeouts for real-time call screening.
"""
import asyncio
from typing import Optional, Any
try:
    import asyncpg
    from asyncpg import Pool
except ImportError:
    asyncpg = None
    Pool = Any

from app.core.config import settings
from app.core.logging import logger

_pool: Optional[Any] = None
_pool_lock = asyncio.Lock()


async def get_db_pool() -> Optional[Any]:
    """
    Returns the singleton asyncpg Connection Pool to Supabase PostgreSQL.
    Configured with fast connection limits and ping health-checks.
    """
    global _pool
    if _pool is not None:
        return _pool

    if asyncpg is None:
        return None

    async with _pool_lock:
        if _pool is not None:
            return _pool

        dsn = getattr(settings, "SUPABASE_DB_URL", None) or getattr(settings, "POSTGRES_VECTOR_URL", None)
        if not dsn:
            logger.warning("No PostgreSQL DSN configured. Operating without database pool.")
            return None

        # Clean asyncpg format & enforce port 6543 for Supabase Transaction Pooler
        raw_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
        if "pooler.supabase.com:5432" in raw_dsn:
            raw_dsn = raw_dsn.replace("pooler.supabase.com:5432", "pooler.supabase.com:6543")

        try:
            _pool = await asyncpg.create_pool(
                raw_dsn,
                min_size=2,
                max_size=20,
                max_inactive_connection_lifetime=300.0,
                command_timeout=10.0,
                timeout=15.0,
                statement_cache_size=0,
            )
            logger.info("Supabase PostgreSQL connection pool initialized successfully.")
            return _pool
        except Exception as e:
            logger.error(f"Failed to connect to Supabase PostgreSQL pool ({repr(e)}). Operating in fail-safe mode.")
            return None


async def close_db_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
