"""
VIGIL-AI Unit & Integration Tests: Automatic Incoming-Call Workflow
Validates the 12 mandatory screening and security scenarios:
1. Known caller
2. Unknown caller
3. Known suspicious caller
4. Caller with verified company
5. Caller with unverified company
6. Repeated caller
7. High-frequency caller
8. Number with previous failed verification
9. ML confidence low
10. ML service unavailable
11. Database unavailable
12. Call screening timeout (<1500ms)
"""
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, patch

from app.schemas.telecom_screening import (
    CallerDetails,
    CallHistorySummary,
    CallerLookupRequest,
    CallerLookupResponse,
)
from app.services.caller_service import CallerService
from app.services.call_history_service import CallHistoryService
from app.services.risk_service import RiskService
from app.services.verification_service import VerificationService
from app.services.call_record_service import CallRecordService


@pytest.fixture
def caller_service():
    return CallerService()


@pytest.fixture
def history_service():
    return CallHistoryService()


@pytest.fixture
def risk_service():
    return RiskService()


@pytest.fixture
def verification_service():
    return VerificationService()


# -----------------------------------------------------------------------------
# Scenario 1: Known Caller
# Rule: Never claims caller is genuine solely because phone number is known!
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_1_known_caller(caller_service, history_service, risk_service):
    # Rahul Sharma (+919876543221)
    phone = "+919876543221"
    normalized = caller_service.normalize_phone_number(phone)
    caller = await caller_service.get_caller_by_number(normalized)
    assert caller.name == "Rahul Sharma"
    assert caller.id is not None

    history = await history_service.get_history_summary(normalized, caller.id)
    risk, action = risk_service.evaluate_preliminary_risk(caller, history)

    # Security constraint: Baseline risk is NEVER 0 because numbers can be spoofed!
    assert risk.score > 0
    assert any("Known enrolled" in r for r in risk.reasons)
    assert action in ["ALLOW", "MONITOR", "VERIFY"]


# -----------------------------------------------------------------------------
# Scenario 2: Unknown Caller
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_2_unknown_caller(caller_service, history_service, risk_service):
    phone = "+919999900001"
    normalized = caller_service.normalize_phone_number(phone)
    caller = await caller_service.get_caller_by_number(normalized)
    
    assert caller.id is None
    assert caller.caller_type == "unknown"

    history = await history_service.get_history_summary(normalized, caller.id)
    risk, action = risk_service.evaluate_preliminary_risk(caller, history)

    assert risk.level in ["LOW", "MEDIUM"]
    assert any("unknown" in r.lower() or "unenrolled" in r.lower() for r in risk.reasons)
    assert action in ["ALLOW", "MONITOR"]


# -----------------------------------------------------------------------------
# Scenario 3: Known Suspicious Caller
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_3_known_suspicious_caller(caller_service, history_service, risk_service):
    phone = "+919876543210"  # Flagged Impersonator
    normalized = caller_service.normalize_phone_number(phone)
    caller = await caller_service.get_caller_by_number(normalized)
    
    assert caller.trust_status == "suspicious"

    history = await history_service.get_history_summary(normalized, caller.id)
    risk, action = risk_service.evaluate_preliminary_risk(caller, history)

    assert risk.score >= 70
    assert risk.level in ["HIGH", "CRITICAL"]
    assert action in ["VERIFY", "BLOCK"]
    assert any("SUSPICIOUS" in r for r in risk.reasons)


# -----------------------------------------------------------------------------
# Scenario 4: Caller with Verified Company
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_4_caller_with_verified_company(caller_service, history_service, risk_service):
    phone = "+14155552671"  # Sarah Connor, Apex Global Financial
    normalized = caller_service.normalize_phone_number(phone)
    caller = await caller_service.get_caller_by_number(normalized)

    assert caller.company == "Apex Global Financial"
    assert caller.company_verified is True

    history = await history_service.get_history_summary(normalized, caller.id)
    risk, action = risk_service.evaluate_preliminary_risk(caller, history, stir_shaken_status=1)

    assert risk.score <= 30
    assert any("verified organization" in r.lower() for r in risk.reasons)
    assert action == "ALLOW"


# -----------------------------------------------------------------------------
# Scenario 5: Caller with Unverified Company
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_5_caller_with_unverified_company(caller_service, history_service, risk_service):
    caller = CallerDetails(
        id="11111111-1111-1111-1111-111111111111",
        name="John Doe",
        phone="+919811122233",
        company="Global Wealth Bank",
        company_verified=False,  # Unverified!
        trust_status="neutral"
    )
    history = CallHistorySummary(total_calls=1, calls_last_24h=1)
    risk, action = risk_service.evaluate_preliminary_risk(caller, history)

    # Must be penalized for unverified corporate claim
    assert any("UNVERIFIED" in r for r in risk.reasons)
    assert risk.score >= 40


# -----------------------------------------------------------------------------
# Scenario 6: Repeated Caller
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_6_repeated_caller(history_service):
    # Rahul Sharma has 47 total historical calls
    history = await history_service.get_history_summary("+919876543221")
    assert history.total_calls == 47
    assert history.calls_last_24h == 4


# -----------------------------------------------------------------------------
# Scenario 7: High-Frequency Caller (Call Flood Anomaly)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_7_high_frequency_caller(caller_service, history_service, risk_service):
    phone = "+919800000001"  # 12 calls in last 24h
    caller = await caller_service.get_caller_by_number(phone)
    history = await history_service.get_history_summary(phone)

    assert history.calls_last_24h >= 10

    risk, action = risk_service.evaluate_preliminary_risk(caller, history)
    assert any("High-frequency call flood detected" in r for r in risk.reasons)
    assert risk.score >= 50


# -----------------------------------------------------------------------------
# Scenario 8: Number with Previous Failed Verification
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_8_number_with_previous_failed_verification(caller_service, history_service, risk_service):
    phone = "+919800000002"  # 2 failed verification attempts
    caller = await caller_service.get_caller_by_number(phone)
    history = await history_service.get_history_summary(phone)

    assert history.failed_verifications == 2

    risk, action = risk_service.evaluate_preliminary_risk(caller, history)
    assert any("failed 2 previous biometric" in r for r in risk.reasons)
    assert risk.level in ["HIGH", "CRITICAL"]
    assert action in ["VERIFY", "BLOCK"]


# -----------------------------------------------------------------------------
# Scenario 9: ML Confidence Low (VoIP Audio Pipeline)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_9_ml_confidence_low():
    from app.pipeline.risk_engine import MultiFactorRiskEngine, RiskEngineInput
    engine = MultiFactorRiskEngine()

    # Deepfake detector returned low confidence (e.g. noisy audio or short segment)
    engine_input = RiskEngineInput(
        deepfake_probability=0.45,
        speaker_similarity=0.60,
        liveness_score=0.40,
        conversation_risk=0.20,
        caller_verified=False,
        model_confidence=0.35
    )
    result = engine.evaluate_risk(engine_input)

    # In low confidence / ambiguous zone, action must NOT be a blind ALLOW or unconfirmed genuine claim
    assert result.action in ["MONITOR", "CHALLENGE", "WARN", "VERIFY"]


# -----------------------------------------------------------------------------
# Scenario 10: ML Service Unavailable (Cellular Screening Decoupling)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_10_ml_service_unavailable(caller_service, history_service, risk_service):
    """
    CRITICAL ARCHITECTURE RULE:
    Cellular call screening MUST NOT depend on heavy ML models.
    If ML engine is offline or uninitialized, screening continues with 100% reliability.
    """
    with patch("app.pipeline.deepfake_detector.DeepfakeModelRegistry.get_detector", side_effect=RuntimeError("ML Service Offline")):
        # Cellular screening lookup does NOT invoke ML models
        caller = await caller_service.get_caller_by_number("+919876543221")
        history = await history_service.get_history_summary("+919876543221")
        risk, action = risk_service.evaluate_preliminary_risk(caller, history)

        assert caller is not None
        assert action in ["ALLOW", "MONITOR", "VERIFY"]


# -----------------------------------------------------------------------------
# Scenario 11: Database Unavailable (Fail-Safe Degradation)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_11_database_unavailable(caller_service, history_service, risk_service):
    """
    When Supabase PostgreSQL connection fails or pool is unreachable,
    the services MUST fail safely and never throw unhandled exceptions.
    """
    with patch("app.db.connection.get_db_pool", return_value=None):
        caller = await caller_service.get_caller_by_number("+919899991234")
        history = await history_service.get_history_summary("+919899991234")
        risk, action = risk_service.evaluate_preliminary_risk(caller, history)

        # Must return valid objects, not None or crash
        assert isinstance(caller, CallerDetails)
        assert isinstance(history, CallHistorySummary)
        assert action in ["ALLOW", "MONITOR"]


# -----------------------------------------------------------------------------
# Scenario 12: Call Screening Timeout (<1500ms SLA)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_12_call_screening_timeout(caller_service, history_service, risk_service):
    """
    Telecom CallScreeningService SLA requires lookup to complete well under 1500ms.
    """
    t0 = time.perf_counter()
    
    phone = "+919876543221"
    normalized = caller_service.normalize_phone_number(phone)
    caller = await caller_service.get_caller_by_number(normalized)
    history = await history_service.get_history_summary(normalized, caller.id)
    risk, action = risk_service.evaluate_preliminary_risk(caller, history)
    
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # Ensure complete execution completes within 1500ms budget
    assert elapsed_ms < 1500.0, f"Screening pipeline took {elapsed_ms:.1f}ms, exceeding 1500ms SLA"


# -----------------------------------------------------------------------------
# Adaptive Challenge-Response Tests (Non-Habitual Utterances)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_challenge_response_unpredictable_phrase(verification_service):
    # Prompt must NOT be habitual
    prompt1, exp1 = verification_service.generate_prompt()
    prompt2, exp2 = verification_service.generate_prompt()

    assert prompt1 != prompt2
    assert "repeat" in prompt1.lower()

    # Create challenge
    challenge = await verification_service.create_challenge(ttl_seconds=60)
    assert challenge.challenge_id is not None
    assert challenge.expires_in_sec == 60

    # Evaluate matching response
    eval_pass = await verification_service.evaluate_response(
        challenge_id=challenge.challenge_id,
        response_transcript=challenge.prompt.replace("Please repeat clearly: '", "").replace("'", "")
    )
    assert eval_pass.status == "PASSED"
    assert eval_pass.similarity_score >= 0.70

    # Evaluate mismatched response
    challenge2 = await verification_service.create_challenge(ttl_seconds=60)
    eval_fail = await verification_service.evaluate_response(
        challenge_id=challenge2.challenge_id,
        response_transcript="hello this is an ordinary habitual greeting"
    )
    assert eval_fail.status == "FAILED"
    assert eval_fail.similarity_score < 0.50


# -----------------------------------------------------------------------------
# End-to-End FastAPI Telephony Screening Contract Test
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_api_screening_lookup_contract():
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/screening/lookup",
            json={
                "phone_number": "+91 98765 43221",
                "caller_display_name": "Rahul Sharma",
                "stir_shaken_status": 0
            },
            headers={"X-API-Key": "dev-vigil-secret-key-change-in-prod"}
        )
        assert response.status_code == 200
        data = response.json()

        # Exact structure requested in prompt
        assert "caller" in data
        assert "history" in data
        assert "risk" in data
        assert "recommended_action" in data

        assert data["caller"]["name"] == "Rahul Sharma"
        assert data["caller"]["phone"] == "+919876543221"
        assert data["caller"]["company"] == "ABC Technologies"
        assert data["caller"]["company_verified"] is False

        assert data["history"]["total_calls"] == 47
        assert data["history"]["calls_last_24h"] == 4
        assert data["history"]["suspicious_events"] == 3

        assert data["risk"]["score"] == 72
        assert data["risk"]["level"] == "HIGH"
        assert data["recommended_action"] == "VERIFY"


@pytest.mark.asyncio
async def test_api_call_decision_and_challenge_flow():
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Report Decision
        dec_resp = await ac.post(
            "/api/v1/screening/decision",
            json={
                "phone_number": "+919876543221",
                "caller_name": "Rahul Sharma",
                "action": "VERIFY",
                "reason": "Preliminary risk HIGH; company unverified",
                "risk_score": 72
            },
            headers={"X-API-Key": "dev-vigil-secret-key-change-in-prod"}
        )
        assert dec_resp.status_code == 200
        assert dec_resp.json()["status"] == "success"

        # 2. Create Dynamic Challenge
        chal_resp = await ac.post(
            "/api/v1/screening/challenge/create",
            json={"caller_id": None, "call_id": None},
            headers={"X-API-Key": "dev-vigil-secret-key-change-in-prod"}
        )
        assert chal_resp.status_code == 201
        chal_data = chal_resp.json()
        assert "challenge_id" in chal_data
        assert "prompt" in chal_data

        # 3. Evaluate Dynamic Challenge
        eval_resp = await ac.post(
            "/api/v1/screening/challenge/evaluate",
            json={
                "challenge_id": chal_data["challenge_id"],
                "response_transcript": chal_data["prompt"].replace("Please repeat clearly: '", "").replace("'", ""),
                "response_latency_ms": 120.0
            },
            headers={"X-API-Key": "dev-vigil-secret-key-change-in-prod"}
        )
        assert eval_resp.status_code == 200
        assert eval_resp.json()["status"] == "PASSED"


# -----------------------------------------------------------------------------
# Security Rule 22: Company Verification Architecture
# Never automatically trust caller-provided company claims ("I'm from Microsoft")
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_claimed_company_unverified_architecture(caller_service):
    # Caller claims "Microsoft"
    caller = await caller_service.get_caller_by_number(
        phone_number="+919811122233",
        claimed_company="Microsoft"
    )
    # Must NOT save verified=True
    assert caller.company == "Microsoft"
    assert caller.company_verified is False
    assert caller.company_name_claimed == "Microsoft"
    assert caller.company_name_verified is False
    assert caller.verification_source == "caller_claim"
    assert caller.verification_status == "UNVERIFIED"


# -----------------------------------------------------------------------------
# Security Rule 23: Caller Relationship Verification
# "Dad" and "Unknown caller claiming to be Dad" must NOT be treated the same!
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_claimed_relationship_unverified_penalty(caller_service, history_service, risk_service):
    # Caller claims to be "FAMILY" (e.g. Dad), but is unverified
    caller = await caller_service.get_caller_by_number(
        phone_number="+919811122233",
        display_name_hint="Dad",
        claimed_relationship="FAMILY"
    )
    assert caller.relationship == "FAMILY"
    assert caller.relationship_verified is False
    assert caller.claimed_relationship_warning is not None
    assert "UNVERIFIED CLAIM" in caller.claimed_relationship_warning

    history = await history_service.get_history_summary(caller.phone)
    risk, action = risk_service.evaluate_preliminary_risk(caller, history)

    # Risk must be penalized for unverified high-trust claim
    assert any("High-trust relationship 'FAMILY' claimed WITHOUT" in r for r in risk.reasons)
    assert risk.score >= 50


# -----------------------------------------------------------------------------
# Security Rule 24: Call Behavior & Velocity Anomaly Analytics
# Rapid burst call flood detection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_behavioral_anomaly_call_flood(caller_service, history_service, risk_service):
    # +919876543210 has 6 calls in the last 1 hour
    history = await history_service.get_history_summary("+919876543210")
    assert history.calls_last_1h >= 5
    assert history.behavioral_anomaly is True
    assert "Rapid burst call flood" in history.behavioral_anomaly_reason

    caller = await caller_service.get_caller_by_number("+919876543210")
    risk, action = risk_service.evaluate_preliminary_risk(caller, history)

    assert any("Rapid burst call flood" in r for r in risk.reasons)
    assert risk.level == "CRITICAL"
    assert action == "BLOCK"


# -----------------------------------------------------------------------------
# Feature 21: Caller Security Profile / Reputation (Not 'truth score')
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_caller_security_profile_generation(caller_service, history_service, risk_service):
    caller = await caller_service.get_caller_by_number("+919876543221")
    history = await history_service.get_history_summary("+919876543221")
    risk, action = risk_service.evaluate_preliminary_risk(caller, history)

    profile = risk_service.calculate_security_profile(caller, history, risk)

    assert profile.identity_status in ["Partially Verified", "Verified", "Unverified"]
    assert profile.phone_status == "Known"
    assert "47 calls" in profile.history_label
    assert profile.recent_risk_label == "High"
    assert profile.company_verification_label == "Unverified"
    assert profile.current_risk_score == 72


# -----------------------------------------------------------------------------
# Feature 20: Incoming Call Screen Views (Normal vs High-Risk Alert)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_incoming_call_screens_normal_vs_suspicious(caller_service, history_service, risk_service):
    # Normal / Low-Risk Screen: Sarah Connor (Apex Global, verified)
    caller_safe = await caller_service.get_caller_by_number("+14155552671")
    history_safe = await history_service.get_history_summary("+14155552671")
    risk_safe, action_safe = risk_service.evaluate_preliminary_risk(caller_safe, history_safe, stir_shaken_status=1)

    screen_safe = risk_service.generate_screen_view(caller_safe, history_safe, risk_safe, action_safe)
    assert screen_safe.screen_type == "NORMAL_INCOMING"
    assert screen_safe.header_title == "INCOMING CALL"
    assert screen_safe.available_actions == ["ACCEPT", "DECLINE"]

    # High-Risk Alert Screen: Flagged Impersonator
    caller_bad = await caller_service.get_caller_by_number("+919876543210")
    history_bad = await history_service.get_history_summary("+919876543210")
    risk_bad, action_bad = risk_service.evaluate_preliminary_risk(caller_bad, history_bad)

    screen_bad = risk_service.generate_screen_view(caller_bad, history_bad, risk_bad, action_bad)
    assert screen_bad.screen_type == "HIGH_RISK_ALERT"
    assert screen_bad.header_title == "🚨 HIGH-RISK CALL"
    assert screen_bad.warning_banner is not None
    assert screen_bad.available_actions == ["VERIFY CALLER", "SILENCE", "BLOCK"]


