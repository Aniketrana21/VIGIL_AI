import asyncio
import asyncpg

async def update_schema_reputation():
    conn = await asyncpg.connect(
        host="aws-0-ap-northeast-1.pooler.supabase.com",
        port=6543,
        user="postgres.rxtisiznzwzkwzmfgojf",
        password="VIGIL_AI@06$",
        database="postgres",
        timeout=10,
        statement_cache_size=0
    )
    sql = """
        -- 1. Add company verification & relationship columns to callers
        ALTER TABLE public.callers
            ADD COLUMN IF NOT EXISTS company_name_claimed TEXT,
            ADD COLUMN IF NOT EXISTS company_name_verified BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS verification_source VARCHAR(64) DEFAULT 'caller_claim',
            ADD COLUMN IF NOT EXISTS verification_status VARCHAR(32) DEFAULT 'UNVERIFIED',
            ADD COLUMN IF NOT EXISTS relationship VARCHAR(32) DEFAULT 'UNKNOWN',
            ADD COLUMN IF NOT EXISTS relationship_verified BOOLEAN DEFAULT FALSE;

        -- 2. Add behavioral & claimed identity columns to calls table
        ALTER TABLE public.calls
            ADD COLUMN IF NOT EXISTS company_name_claimed TEXT,
            ADD COLUMN IF NOT EXISTS company_name_verified BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS verification_source VARCHAR(64) DEFAULT 'caller_claim',
            ADD COLUMN IF NOT EXISTS verification_status VARCHAR(32) DEFAULT 'UNVERIFIED',
            ADD COLUMN IF NOT EXISTS relationship VARCHAR(32) DEFAULT 'UNKNOWN',
            ADD COLUMN IF NOT EXISTS relationship_verified BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS calls_last_1_hour INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS calls_last_24_hours INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS calls_last_7_days INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS average_call_duration INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS failed_verifications INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS suspicious_calls INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS blocked_calls INT DEFAULT 0;

        CREATE INDEX IF NOT EXISTS idx_calls_started_1h ON public.calls (normalized_number, started_at);
    """
    await conn.execute(sql)
    print("Caller reputation and behavioral telemetry schema applied to Supabase successfully!")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(update_schema_reputation())
