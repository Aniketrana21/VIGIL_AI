-- ============================================================================
-- VIGIL-AI: PRODUCTION SUPABASE POSTGRESQL DATABASE SCHEMA
-- Architecture: Multi-Tenant Zero-Trust Voice Security Operations Center (SOC)
-- Target: Supabase PostgreSQL 15+ with pgvector 0.5+
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 0. EXTENSIONS
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ----------------------------------------------------------------------------
-- 1. ENUMERATIONS & CUSTOM DOMAINS
-- ----------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE caller_type_enum AS ENUM ('individual', 'organization', 'automated_bot', 'unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE trust_status_enum AS ENUM ('trusted', 'neutral', 'suspicious', 'blocked', 'under_review');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE call_direction_enum AS ENUM ('inbound', 'outbound', 'internal');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE call_status_enum AS ENUM ('ringing', 'in_progress', 'completed', 'dropped', 'blocked', 'escalated');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE risk_level_enum AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE call_action_enum AS ENUM ('ALLOW', 'SILENCE', 'WARN', 'CHALLENGE', 'BLOCK', 'ESCALATE');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE verification_type_enum AS ENUM ('voice_biometric', 'challenge_response', 'sms_otp', 'telephony_reputation', 'agent_manual');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE verification_result_enum AS ENUM ('PASSED', 'FAILED', 'INCONCLUSIVE', 'BYPASSED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE consent_status_enum AS ENUM ('opted_in', 'opted_out', 'withdrawn', 'exempt');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ----------------------------------------------------------------------------
-- 2. HELPER FUNCTIONS & TRIGGERS
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- 3. CORE IDENTITY: USERS & TENANCY
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'analyst' CHECK (role IN ('admin', 'analyst', 'operator', 'auditor')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_active ON public.users (LOWER(email)) WHERE deleted_at IS NULL;

-- ----------------------------------------------------------------------------
-- 3b. USER DEVICES & INSTALLATIONS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    device_uuid TEXT NOT NULL,
    installation_id UUID NOT NULL,
    platform VARCHAR(32) NOT NULL DEFAULT 'android',
    app_version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    push_token TEXT,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_device_user_uuid UNIQUE (user_id, device_uuid)
);
CREATE INDEX IF NOT EXISTS idx_devices_user_id ON public.devices (user_id);

-- ----------------------------------------------------------------------------
-- 4. ORGANIZATIONS: COMPANIES & VERIFICATION
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    domain VARCHAR(255),
    industry VARCHAR(128),
    website TEXT,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    verification_source VARCHAR(128),
    reputation_score INT CHECK (reputation_score IS NULL OR (reputation_score BETWEEN 0 AND 100)),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_domain ON public.companies (LOWER(domain)) WHERE deleted_at IS NULL AND domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_companies_name_trgm ON public.companies USING gin (name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS public.company_verifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES public.companies(id) ON DELETE CASCADE,
    verifier_user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    verification_method VARCHAR(64) NOT NULL, -- e.g., 'duns', 'domain_ssl', 'telecom_registry', 'manual_audit'
    evidence_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_comp_verif_company ON public.company_verifications (company_id, verified_at DESC);

-- ----------------------------------------------------------------------------
-- 5. CALLER PROFILES & MULTI-PHONE DIRECTORY
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.callers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    first_name VARCHAR(128),
    last_name VARCHAR(128),
    profile_photo_url TEXT,
    caller_type caller_type_enum NOT NULL DEFAULT 'unknown',
    company_id UUID REFERENCES public.companies(id) ON DELETE SET NULL,
    company_name_claimed TEXT,
    company_name_verified BOOLEAN DEFAULT FALSE,
    verification_source VARCHAR(64) DEFAULT 'caller_claim',
    verification_status VARCHAR(32) DEFAULT 'UNVERIFIED',
    relationship VARCHAR(32) DEFAULT 'UNKNOWN',
    relationship_verified BOOLEAN DEFAULT FALSE,
    notes TEXT,
    trust_status trust_status_enum NOT NULL DEFAULT 'neutral',
    is_vip BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_callers_user_trust ON public.callers (user_id, trust_status) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_callers_display_name_trgm ON public.callers USING gin (display_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_callers_company ON public.callers (company_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS public.phone_numbers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    caller_id UUID NOT NULL REFERENCES public.callers(id) ON DELETE CASCADE,
    phone_number VARCHAR(64) NOT NULL,
    country_code VARCHAR(8) NOT NULL DEFAULT '+1',
    normalized_number VARCHAR(32) NOT NULL, -- Strict E.164 (e.g. +14155552671)
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    carrier VARCHAR(128),
    line_type VARCHAR(32) CHECK (line_type IS NULL OR line_type IN ('mobile', 'landline', 'voip', 'toll_free', 'unknown')),
    verification_method VARCHAR(64),
    reputation_score INT CHECK (reputation_score IS NULL OR (reputation_score BETWEEN 0 AND 100)),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_caller_normalized_number UNIQUE (caller_id, normalized_number)
);
-- High-speed B-Tree lookup for real-time incoming call identity resolution (<1ms over millions of rows)
CREATE INDEX IF NOT EXISTS idx_phone_numbers_normalized ON public.phone_numbers (normalized_number);
CREATE INDEX IF NOT EXISTS idx_phone_numbers_caller_primary ON public.phone_numbers (caller_id, is_primary);

-- ----------------------------------------------------------------------------
-- 6. AI REGISTRY: MODEL VERSIONS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.model_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name VARCHAR(128) NOT NULL,
    version_tag VARCHAR(64) NOT NULL,
    model_type VARCHAR(64) NOT NULL CHECK (model_type IN ('speaker_embedding', 'deepfake_detector', 'vad', 'liveness', 'intent_classifier')),
    embedding_dim INT CHECK (embedding_dim IS NULL OR embedding_dim > 0),
    checksum VARCHAR(128),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    release_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_model_name_version UNIQUE (model_name, version_tag)
);
CREATE INDEX IF NOT EXISTS idx_model_versions_active ON public.model_versions (model_type, is_active);

-- Seed baseline model versions if not already registered
INSERT INTO public.model_versions (model_name, version_tag, model_type, embedding_dim, release_notes)
VALUES 
    ('Vigil-ECAPA-TDNN', 'v1.0', 'speaker_embedding', 192, 'Production 192-dim acoustic voice embedding'),
    ('Vigil-WavLM-AASIST', 'v1.0', 'deepfake_detector', NULL, 'Dual-stream temporal-spectral deepfake anti-spoofing engine'),
    ('Silero-VAD', 'v4.0', 'vad', NULL, 'Low-latency streaming voice activity detector')
ON CONFLICT (model_name, version_tag) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 7. BIOMETRICS: SPEAKER PROFILES & PGVECTOR EMBEDDINGS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.speaker_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    speaker_id VARCHAR(128) UNIQUE,
    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
    name VARCHAR(255) DEFAULT 'Enrolled Speaker',
    caller_id UUID REFERENCES public.callers(id) ON DELETE CASCADE,
    embedding vector(192) NOT NULL,
    embedding_model_id UUID REFERENCES public.model_versions(id) ON DELETE SET NULL,
    embedding_version VARCHAR(64) NOT NULL DEFAULT 'v1.0',
    num_utterances INT NOT NULL DEFAULT 1 CHECK (num_utterances >= 1),
    enrollment_count INT NOT NULL DEFAULT 1 CHECK (enrollment_count >= 1),
    speaker_confidence FLOAT NOT NULL DEFAULT 1.0 CHECK (speaker_confidence BETWEEN 0.0 AND 1.0),
    encrypted_payload TEXT, -- Zero-Knowledge AES-256-GCM ciphertext backup (never raw audio)
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_speaker_profiles_caller ON public.speaker_profiles (caller_id) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_speaker_profiles_user ON public.speaker_profiles (user_id);

-- Approximate Nearest Neighbor (ANN) HNSW index with cosine distance operator
-- Tuned for sub-millisecond similarity queries across 100k+ speaker voice vectors
CREATE INDEX IF NOT EXISTS idx_speaker_profiles_vector_hnsw 
ON public.speaker_profiles USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- ----------------------------------------------------------------------------
-- 8. CALLS: CENTRAL CALL HISTORY
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    device_id UUID REFERENCES public.devices(id) ON DELETE SET NULL,
    caller_id UUID REFERENCES public.callers(id) ON DELETE SET NULL,
    phone_number_id UUID REFERENCES public.phone_numbers(id) ON DELETE SET NULL,
    session_id VARCHAR(128) NOT NULL UNIQUE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    duration_seconds INT CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    direction call_direction_enum NOT NULL DEFAULT 'inbound',
    call_status call_status_enum NOT NULL DEFAULT 'ringing',
    caller_name_at_time TEXT,
    phone_number_at_time VARCHAR(32),
    normalized_number VARCHAR(32),
    previous_calls_count INT DEFAULT 0,
    company_name_at_time TEXT,
    company_verified_at_time BOOLEAN DEFAULT FALSE,
    caller_type VARCHAR(64),
    company_name_claimed TEXT,
    company_name_verified BOOLEAN DEFAULT FALSE,
    verification_source VARCHAR(64) DEFAULT 'caller_claim',
    verification_status VARCHAR(32) DEFAULT 'UNVERIFIED',
    relationship VARCHAR(32) DEFAULT 'UNKNOWN',
    relationship_verified BOOLEAN DEFAULT FALSE,
    calls_last_1_hour INT DEFAULT 0,
    calls_last_24_hours INT DEFAULT 0,
    calls_last_7_days INT DEFAULT 0,
    average_call_duration INT DEFAULT 0,
    failed_verifications INT DEFAULT 0,
    suspicious_calls INT DEFAULT 0,
    blocked_calls INT DEFAULT 0,
    speaker_similarity FLOAT,
    deepfake_probability FLOAT,
    liveness_score FLOAT,
    replay_probability FLOAT,
    model_confidence FLOAT,
    action_reason TEXT,
    model_version VARCHAR(64),
    overall_risk_score INT CHECK (overall_risk_score IS NULL OR (overall_risk_score BETWEEN 0 AND 100)),
    overall_risk_level risk_level_enum,
    final_action call_action_enum,
    live_transcript TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- High-throughput composite indexes for SOC live queries & timeline filters
CREATE INDEX IF NOT EXISTS idx_calls_user_started ON public.calls (user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_caller_started ON public.calls (caller_id, started_at DESC) WHERE caller_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_calls_normalized_number ON public.calls (normalized_number, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_status_risk ON public.calls (call_status, overall_risk_level);
CREATE INDEX IF NOT EXISTS idx_calls_session_id ON public.calls (session_id);

-- ----------------------------------------------------------------------------
-- 9. VOICE ANALYSIS WINDOWS (High-Volume Stream Engine)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.voice_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id UUID NOT NULL REFERENCES public.calls(id) ON DELETE CASCADE,
    window_start_ms INT NOT NULL CHECK (window_start_ms >= 0),
    window_end_ms INT NOT NULL CHECK (window_end_ms >= window_start_ms),
    deepfake_probability FLOAT NOT NULL CHECK (deepfake_probability BETWEEN 0.0 AND 1.0),
    bonafide_probability FLOAT NOT NULL CHECK (bonafide_probability BETWEEN 0.0 AND 1.0),
    speaker_similarity FLOAT CHECK (speaker_similarity IS NULL OR (speaker_similarity BETWEEN -1.0 AND 1.0)),
    liveness_score FLOAT CHECK (liveness_score IS NULL OR (liveness_score BETWEEN 0.0 AND 1.0)),
    replay_probability FLOAT CHECK (replay_probability IS NULL OR (replay_probability BETWEEN 0.0 AND 1.0)),
    model_version VARCHAR(64) NOT NULL DEFAULT 'v1.0',
    inference_latency_ms FLOAT CHECK (inference_latency_ms >= 0.0),
    confidence FLOAT NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0.0 AND 1.0),
    vad_speech_confidence FLOAT CHECK (vad_speech_confidence IS NULL OR (vad_speech_confidence BETWEEN 0.0 AND 1.0)),
    spectral_entropy FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Composite index for fast chronological audio timeline rendering & waterfall spectrogram replay
CREATE INDEX IF NOT EXISTS idx_voice_analysis_call_window ON public.voice_analysis (call_id, window_start_ms ASC);
CREATE INDEX IF NOT EXISTS idx_voice_analysis_deepfake_anomaly ON public.voice_analysis (call_id, deepfake_probability DESC);

-- ----------------------------------------------------------------------------
-- 10. SECURITY TELEMETRY: RISK EVENTS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.risk_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id UUID NOT NULL REFERENCES public.calls(id) ON DELETE CASCADE,
    event_type VARCHAR(64) NOT NULL, -- e.g., 'synthetic_vocoder', 'spectral_gap', 'speaker_mismatch', 'replay_attack'
    risk_score INT NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    risk_level risk_level_enum NOT NULL,
    reason TEXT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0.0 AND 1.0),
    contributing_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_risk_events_call ON public.risk_events (call_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_risk_events_level ON public.risk_events (risk_level, created_at DESC);

-- ----------------------------------------------------------------------------
-- 11. POLICY ENFORCEMENT: CALL ACTIONS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.call_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id UUID NOT NULL REFERENCES public.calls(id) ON DELETE CASCADE,
    action call_action_enum NOT NULL,
    reason TEXT NOT NULL,
    risk_score INT NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    triggered_by VARCHAR(64) NOT NULL DEFAULT 'risk_engine', -- 'risk_engine' | 'policy_rule' | 'soc_operator'
    performed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_call_actions_call ON public.call_actions (call_id, performed_at ASC);
CREATE INDEX IF NOT EXISTS idx_call_actions_action ON public.call_actions (action, performed_at DESC);

-- ----------------------------------------------------------------------------
-- 12. VERIFICATION & ADAPTIVE CHALLENGE-RESPONSE
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.verification_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id UUID NOT NULL REFERENCES public.calls(id) ON DELETE CASCADE,
    verification_type verification_type_enum NOT NULL,
    result verification_result_enum NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0.0 AND 1.0),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_verification_events_call ON public.verification_events (call_id, created_at ASC);

CREATE TABLE IF NOT EXISTS public.challenge_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id UUID NOT NULL REFERENCES public.calls(id) ON DELETE CASCADE,
    challenge_type VARCHAR(64) NOT NULL DEFAULT 'interactive_phonetic_phrase',
    prompt TEXT NOT NULL,
    expected_response_type VARCHAR(64) NOT NULL DEFAULT 'vocal_repetition',
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PASSED', 'FAILED', 'EXPIRED')),
    response_latency_ms FLOAT,
    similarity_score FLOAT CHECK (similarity_score IS NULL OR (similarity_score BETWEEN 0.0 AND 1.0)),
    expires_at TIMESTAMPTZ NOT NULL,
    evaluated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_challenge_sessions_call ON public.challenge_sessions (call_id, status);

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

-- ----------------------------------------------------------------------------
-- 13. PRIVACY, CONSENT & OBJECT STORAGE METADATA (NO RAW AUDIO IN DB)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.audio_record_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id UUID NOT NULL REFERENCES public.calls(id) ON DELETE CASCADE,
    storage_bucket VARCHAR(64) NOT NULL DEFAULT 'vigil-quarantine-audio',
    storage_object_key TEXT NOT NULL UNIQUE, -- Reference in S3 / Supabase Storage
    file_format VARCHAR(16) NOT NULL DEFAULT 'wav',
    file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes > 0),
    sha256_checksum VARCHAR(64) NOT NULL,
    retention_state VARCHAR(32) NOT NULL DEFAULT 'active' CHECK (retention_state IN ('active', 'quarantined', 'archived', 'marked_for_deletion', 'purged')),
    retention_until TIMESTAMPTZ NOT NULL,
    consent_state consent_status_enum NOT NULL DEFAULT 'opted_in',
    is_encrypted_at_rest BOOLEAN NOT NULL DEFAULT TRUE,
    kms_key_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    purged_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_audio_retention ON public.audio_record_references (retention_state, retention_until) 
WHERE retention_state != 'purged';

CREATE TABLE IF NOT EXISTS public.privacy_consent_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    caller_id UUID NOT NULL REFERENCES public.callers(id) ON DELETE CASCADE,
    consent_type VARCHAR(64) NOT NULL, -- 'biometric_voiceprint_collection', 'call_recording_analysis', 'metadata_sharing'
    status consent_status_enum NOT NULL DEFAULT 'opted_in',
    jurisdiction VARCHAR(32) NOT NULL DEFAULT 'GDPR_CCPA',
    consent_notice_version VARCHAR(32) NOT NULL DEFAULT '2026.1',
    ip_address INET,
    user_agent TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    withdrawn_at TIMESTAMPTZ,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_privacy_consent_caller ON public.privacy_consent_records (caller_id, status);

-- ----------------------------------------------------------------------------
-- 14. COMPLIANCE & SECURITY AUDIT LOGS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    action VARCHAR(64) NOT NULL, -- e.g., 'CALL_TERMINATED', 'SPEAKER_PROFILE_DELETED', 'CONSENT_REVOKED'
    resource_type VARCHAR(64) NOT NULL,
    resource_id UUID,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address INET,
    severity VARCHAR(16) NOT NULL DEFAULT 'INFO' CHECK (severity IN ('DEBUG', 'INFO', 'WARN', 'CRITICAL')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON public.audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON public.audit_logs (resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON public.audit_logs (actor_id, created_at DESC);

-- ----------------------------------------------------------------------------
-- 15. UPDATED_AT TRIGGER ASSIGNMENTS
-- ----------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_users_timestamp ON public.users;
CREATE TRIGGER trg_users_timestamp BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();

DROP TRIGGER IF EXISTS trg_companies_timestamp ON public.companies;
CREATE TRIGGER trg_companies_timestamp BEFORE UPDATE ON public.companies FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();

DROP TRIGGER IF EXISTS trg_callers_timestamp ON public.callers;
CREATE TRIGGER trg_callers_timestamp BEFORE UPDATE ON public.callers FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();

DROP TRIGGER IF EXISTS trg_phone_numbers_timestamp ON public.phone_numbers;
CREATE TRIGGER trg_phone_numbers_timestamp BEFORE UPDATE ON public.phone_numbers FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();

DROP TRIGGER IF EXISTS trg_speaker_profiles_timestamp ON public.speaker_profiles;
CREATE TRIGGER trg_speaker_profiles_timestamp BEFORE UPDATE ON public.speaker_profiles FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();

-- ----------------------------------------------------------------------------
-- 16. BACKWARD COMPATIBILITY: DETECTION_EVENTS BRIDGE
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.detection_events (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deepfake_score FLOAT,
    deepfake_label TEXT,
    speaker_id TEXT,
    speaker_similarity FLOAT,
    liveness_score FLOAT,
    replay_probability FLOAT,
    conversation_intent TEXT,
    conversation_risk FLOAT,
    risk_score INT NOT NULL,
    risk_level TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    contributing_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    explanation TEXT DEFAULT '',
    caller_id TEXT,
    transcript TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_detection_events_session ON public.detection_events(session_id);
CREATE INDEX IF NOT EXISTS idx_detection_events_timestamp ON public.detection_events(timestamp DESC);

-- ----------------------------------------------------------------------------
-- 17. ROW LEVEL SECURITY (RLS) POLICIES
-- ----------------------------------------------------------------------------
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.callers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.phone_numbers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.model_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.speaker_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.voice_analysis ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.risk_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.call_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.verification_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.challenge_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audio_record_references ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.privacy_consent_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.detection_events ENABLE ROW LEVEL SECURITY;

-- 17.1 Public / Publishable key policies (for development & authorized anon/authenticated clients)
CREATE POLICY "Allow anon/authenticated read callers" ON public.callers FOR SELECT TO anon, authenticated USING (deleted_at IS NULL);
CREATE POLICY "Allow anon/authenticated insert callers" ON public.callers FOR INSERT TO anon, authenticated WITH CHECK (true);
CREATE POLICY "Allow anon/authenticated update callers" ON public.callers FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

CREATE POLICY "Allow anon/authenticated read phone_numbers" ON public.phone_numbers FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow anon/authenticated insert phone_numbers" ON public.phone_numbers FOR INSERT TO anon, authenticated WITH CHECK (true);

CREATE POLICY "Allow anon/authenticated read companies" ON public.companies FOR SELECT TO anon, authenticated USING (deleted_at IS NULL);

CREATE POLICY "Allow anon/authenticated read model_versions" ON public.model_versions FOR SELECT TO anon, authenticated USING (is_active = true);

CREATE POLICY "Allow anon/authenticated read speaker_profiles" ON public.speaker_profiles FOR SELECT TO anon, authenticated USING (is_active = true);
CREATE POLICY "Allow anon/authenticated insert speaker_profiles" ON public.speaker_profiles FOR INSERT TO anon, authenticated WITH CHECK (true);

CREATE POLICY "Allow anon/authenticated all calls" ON public.calls FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon/authenticated all voice_analysis" ON public.voice_analysis FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon/authenticated all risk_events" ON public.risk_events FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon/authenticated all call_actions" ON public.call_actions FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon/authenticated all verification_events" ON public.verification_events FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon/authenticated all challenge_sessions" ON public.challenge_sessions FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon/authenticated all detection_events" ON public.detection_events FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon/authenticated all audit_logs" ON public.audit_logs FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);

-- ----------------------------------------------------------------------------
-- 18. SUPABASE REALTIME REPLICATION PUBLICATION
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
        CREATE PUBLICATION supabase_realtime;
    END IF;
END $$;

ALTER PUBLICATION supabase_realtime ADD TABLE public.calls;
ALTER PUBLICATION supabase_realtime ADD TABLE public.call_actions;
ALTER PUBLICATION supabase_realtime ADD TABLE public.risk_events;
ALTER PUBLICATION supabase_realtime ADD TABLE public.detection_events;
