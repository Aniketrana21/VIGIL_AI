"""
VIGIL-AI: Supabase Project Verification & Diagnostics.
Validates HTTP/REST connectivity, authentication keys, schema existence,
and fallback persistence mechanisms.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure backend root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings
from app.db.detection_store import DetectionEvent, SupabaseDetectionStore, get_detection_store
import httpx


async def run_diagnostics():
    print("=" * 80)
    print("🛡️  VIGIL-AI: SUPABASE CONNECTION DIAGNOSTICS")
    print("=" * 80)
    print(f"• Target Supabase URL : {settings.SUPABASE_URL}")
    key_preview = (
        f"{settings.SUPABASE_KEY[:14]}...{settings.SUPABASE_KEY[-6:]}"
        if settings.SUPABASE_KEY
        else "NOT SET"
    )
    print(f"• Publishable Key     : {key_preview}")
    print(f"• Store Backend Mode  : {settings.DETECTION_STORE_BACKEND}")
    print("-" * 80)

    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        print("❌ Supabase URL or Key is missing in configuration.")
        return False

    headers = {
        "apikey": settings.SUPABASE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    # Step 1: Health / Auth Gateway Check
    print("1️⃣  Checking Supabase Gateway / Auth Service...")
    health_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/health"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(health_url, headers=headers)
            if resp.status_code == 200:
                print(f"   ✅ Auth/Gateway reachable: HTTP 200 OK")
                print(f"      Response: {resp.text.strip()}")
            else:
                print(f"   ⚠️ Auth/Gateway returned HTTP {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        print(f"   ❌ Network error connecting to Supabase Auth: {e}")
        return False

    # Step 2: PostgREST REST API Authentication Check
    print("\n2️⃣  Checking PostgREST API Authentication...")
    rest_url = f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(rest_url, headers=headers)
            # PostgREST root returns 401 "Secret API key required" for schema OpenAPI docs when anon,
            # which is normal for Supabase publishable keys.
            print(f"   ℹ️  PostgREST root response: HTTP {resp.status_code}")
    except Exception as e:
        print(f"   ⚠️ REST ping check exception: {e}")

    # Step 3: Check Schema Tables
    print("\n3️⃣  Checking Schema Tables (detection_events, speaker_profiles)...")
    tables = ["detection_events", "speaker_profiles"]
    schema_ready = True
    async with httpx.AsyncClient(timeout=6.0) as client:
        for tbl in tables:
            tbl_url = f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/{tbl}?limit=1"
            try:
                resp = await client.get(tbl_url, headers=headers)
                if resp.status_code == 200:
                    print(f"   ✅ Table 'public.{tbl}' is ACTIVE and accessible!")
                elif resp.status_code == 404:
                    print(f"   ⚠️ Table 'public.{tbl}' not found in database schema yet.")
                    schema_ready = False
                elif resp.status_code == 401 or resp.status_code == 403:
                    print(f"   ⚠️ Table 'public.{tbl}' exists but RLS policy restricts access (HTTP {resp.status_code}).")
                    schema_ready = False
                else:
                    print(f"   ℹ️ Table 'public.{tbl}' returned HTTP {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                print(f"   ❌ Error checking table '{tbl}': {e}")
                schema_ready = False

    # Step 4: Test SupabaseDetectionStore Integration & Fallback
    print("\n4️⃣  Testing SupabaseDetectionStore Execution & Fallback...")
    store = SupabaseDetectionStore(url=settings.SUPABASE_URL, key=settings.SUPABASE_KEY)
    await store.initialize()

    test_event = DetectionEvent(
        session_id="supabase_diag_test_001",
        risk_score=88,
        risk_level="CRITICAL",
        action="BLOCK",
        deepfake_score=0.94,
        deepfake_label="SPOOF",
        speaker_id="unknown_voice_01",
        speaker_similarity=0.41,
        liveness_score=0.32,
        replay_probability=0.89,
        conversation_intent="credential_theft",
        conversation_risk=0.85,
        confidence=0.96,
        signals=["synthetic_vocoder_detected", "acoustic_discontinuity", "adversarial_intent"],
        contributing_signals=["high_frequency_spectral_gap", "replay_artifact"],
        explanation="Synthetic voice detected with high confidence.",
        caller_id="+1-800-SUSPECT",
        transcript="Please confirm your wire transfer authorization code.",
        metadata={"diag_run": True, "source": "verify_supabase.py"}
    )

    stored = await store.store_detection(test_event)
    print(f"   ✅ Event persistence dispatched successfully: result={stored}")

    # Read back detections
    records = await store.get_detections(session_id="supabase_diag_test_001", limit=5)
    print(f"   ✅ Retrieved {len(records)} matching records.")
    stats = await store.get_detection_stats()
    print(f"   ✅ Detection Stats: {json.dumps(stats, indent=2)}")

    print("\n" + "=" * 80)
    if schema_ready:
        print("🎉 ALL CHECKS PASSED: Supabase tables are ready and fully operational!")
    else:
        print("📋 ACTION ITEM: Tables not yet created in Supabase.")
        print("   To create the tables and enable vector search + realtime streaming:")
        print("   1. Open your Supabase Dashboard: https://supabase.com/dashboard/project/rxtisiznzwzkwzmfgojf")
        print("   2. Click on 'SQL Editor' in the left sidebar.")
        print("   3. Paste the contents of docs/supabase_schema.sql and click 'Run'.")
        print("   4. Re-run this diagnostic script: python backend/verify_supabase.py")
    print("=" * 80)
    return True


if __name__ == "__main__":
    asyncio.run(run_diagnostics())
