import asyncio
import asyncpg

async def update_schema():
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
        -- 1. Add requested call history telemetry columns to calls table
        ALTER TABLE public.calls 
            ADD COLUMN IF NOT EXISTS normalized_number VARCHAR(32),
            ADD COLUMN IF NOT EXISTS previous_calls_count INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS company_name_at_time TEXT,
            ADD COLUMN IF NOT EXISTS company_verified_at_time BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS caller_type VARCHAR(64),
            ADD COLUMN IF NOT EXISTS speaker_similarity FLOAT,
            ADD COLUMN IF NOT EXISTS deepfake_probability FLOAT,
            ADD COLUMN IF NOT EXISTS liveness_score FLOAT,
            ADD COLUMN IF NOT EXISTS replay_probability FLOAT,
            ADD COLUMN IF NOT EXISTS model_confidence FLOAT,
            ADD COLUMN IF NOT EXISTS action_reason TEXT,
            ADD COLUMN IF NOT EXISTS model_version VARCHAR(64);

        CREATE INDEX IF NOT EXISTS idx_calls_normalized_number ON public.calls (normalized_number, started_at DESC);

        -- 2. Create identity_challenges table for adaptive authentication
        CREATE TABLE IF NOT EXISTS public.identity_challenges (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            call_id UUID REFERENCES public.calls(id) ON DELETE CASCADE,
            caller_id UUID REFERENCES public.callers(id) ON DELETE CASCADE,
            challenge_type VARCHAR(64) NOT NULL DEFAULT 'phonetic_utterance',
            prompt TEXT NOT NULL,
            expected_response TEXT,
            status VARCHAR(32) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PASSED', 'FAILED', 'EXPIRED')),
            response_latency_ms FLOAT,
            similarity_score FLOAT,
            expires_at TIMESTAMPTZ NOT NULL,
            evaluated_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_identity_challenges_caller ON public.identity_challenges (caller_id, status);
        CREATE INDEX IF NOT EXISTS idx_identity_challenges_call ON public.identity_challenges (call_id, status);
        ALTER TABLE public.identity_challenges ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS "Allow anon/authenticated all identity_challenges" ON public.identity_challenges;
        CREATE POLICY "Allow anon/authenticated all identity_challenges" ON public.identity_challenges FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
    """
    await conn.execute(sql)
    print("Calls and identity_challenges schema updated in Supabase successfully!")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(update_schema())
