import pytest
import torch
from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.conversation_intelligence import ConversationIntelligenceClassifier, get_conversation_classifier
from app.pipeline.risk_engine import MultiFactorRiskEngine, RiskEngineInput
from app.pipeline.transcriber import WhisperTranscriber
from app.schemas.conversation import CallerIntent, ConversationIntelligenceOutput


@pytest.fixture
def classifier():
    return ConversationIntelligenceClassifier()


@pytest.fixture
def risk_engine():
    return MultiFactorRiskEngine()


class TestPhase11ConversationIntelligence:
    """
    Test Suite for VIGIL-AI Phase 11: Conversation Intelligence.
    Validates Whisper ASR decoupling, contextual intent parsing,
    exact return schemas, privacy zero-retention, and risk compounding.
    """

    def test_whisper_decoupled_from_fake_detection(self):
        """
        Architectural Requirement:
        Do not use Whisper to determine whether audio is fake.
        Whisper is used strictly to understand what the caller is asking for (ASR).
        """
        transcriber = WhisperTranscriber()
        # Verify Whisper transcribes without outputting acoustic spoof scores
        dummy_audio = torch.zeros(16000, dtype=torch.float32)
        transcriber.set_test_transcript_override("Hello, I am calling regarding my account.")
        transcript = transcriber.transcribe(dummy_audio, user_consent=True)

        assert isinstance(transcript, str)
        assert transcript == "Hello, I am calling regarding my account."
        # Confirm transcriber exposes zero deepfake scoring interfaces
        assert not hasattr(transcriber, "spoof_probability")
        assert not hasattr(transcriber, "is_synthetic")
        assert not hasattr(transcriber, "predict_spoof")

    def test_contextual_otp_request_vs_question(self, classifier):
        """
        Core Specification Requirement:
        Do not make decisions based solely on keywords. Use context.
        - "Send me the OTP" -> High-risk authentication request.
        - "What's an OTP?" -> Informational, not automatically malicious.
        """
        # Case A: Imperative demand for authentication credential
        res_demand = classifier.classify_intent("Send me the OTP")
        assert res_demand.intent == CallerIntent.OTP_REQUEST.value
        assert res_demand.risk_signal >= 0.85
        assert "otp" in res_demand.evidence.lower() or "one-time" in res_demand.evidence.lower()

        # Case B: Informational inquiry regarding definition
        res_question = classifier.classify_intent("What's an OTP?")
        assert res_question.intent == CallerIntent.INFORMATIONAL_QUERY.value
        assert res_question.risk_signal <= 0.15
        assert "informational" in res_question.evidence.lower() or "concept" in res_question.evidence.lower()

        # Case C: Educational variation
        res_explain = classifier.classify_intent("Can you explain what an OTP is?")
        assert res_explain.intent == CallerIntent.INFORMATIONAL_QUERY.value
        assert res_explain.risk_signal <= 0.15

    def test_all_high_risk_intents(self, classifier):
        """
        Validates detection across all required high-risk intent categories:
        - money transfer
        - UPI request
        - OTP request
        - password request
        - bank credential request
        - emergency money request
        - identity verification request
        - confidential information request
        - account takeover attempt
        """
        test_cases = [
            (
                "Please make an immediate money transfer of 50,000 to this account.",
                CallerIntent.FINANCIAL_REQUEST.value,
                0.80,
            ),
            (
                "Send 5,000 rupees to my UPI ID at okhdfcbank right now.",
                CallerIntent.UPI_REQUEST.value,
                0.85,
            ),
            (
                "Read out the 6-digit OTP code you just received on your phone.",
                CallerIntent.OTP_REQUEST.value,
                0.85,
            ),
            (
                "Give me your online banking password and transaction PIN.",
                CallerIntent.PASSWORD_REQUEST.value,
                0.85,
            ),
            (
                "Provide your 16-digit debit card number, CVV code, and expiry date.",
                CallerIntent.BANK_CREDENTIAL_REQUEST.value,
                0.85,
            ),
            (
                "Mom I had an accident and I am in the hospital please send money urgently!",
                CallerIntent.EMERGENCY_MONEY_REQUEST.value,
                0.90,
            ),
            (
                "Verify your identity by sending your Aadhaar number and SSN details.",
                CallerIntent.IDENTITY_VERIFICATION_REQUEST.value,
                0.80,
            ),
            (
                "Email me the confidential source code and internal customer database immediately.",
                CallerIntent.CONFIDENTIAL_INFO_REQUEST.value,
                0.85,
            ),
            (
                "Bypass 2FA and reset the account password so I can take over.",
                CallerIntent.ACCOUNT_TAKEOVER_ATTEMPT.value,
                0.85,
            ),
        ]

        for phrase, expected_intent, min_risk in test_cases:
            res = classifier.classify_intent(phrase)
            assert res.intent == expected_intent, f"Failed on '{phrase}': expected {expected_intent}, got {res.intent}"
            assert res.risk_signal >= min_risk, f"Risk score too low for '{phrase}': {res.risk_signal} < {min_risk}"
            assert len(res.evidence) > 0

    def test_benign_and_educational_phrases(self, classifier):
        """
        Ensures benign everyday talk and educational security warnings are not misclassified as attacks.
        """
        # Casual conversation
        res_casual = classifier.classify_intent("Hey how are you doing? Are we still meeting for lunch today?")
        assert res_casual.intent == CallerIntent.BENIGN_CONVERSATION.value
        assert res_casual.risk_signal < 0.10

        # Educational advisory
        res_advisory = classifier.classify_intent("Remember to never share your password or OTP with anyone claiming to be bank staff.")
        assert res_advisory.intent == CallerIntent.BENIGN_CONVERSATION.value
        assert res_advisory.risk_signal < 0.10

    def test_exact_return_schema(self, classifier):
        """
        Requirement: Exact return contract
        {
          "intent": "FINANCIAL_REQUEST",
          "risk_signal": 0.88,
          "evidence": "request for money transfer"
        }
        """
        res = classifier.classify_intent("I need you to authorize a wire transfer of funds immediately.")
        d = res.to_dict()

        assert "intent" in d
        assert "risk_signal" in d
        assert "evidence" in d
        assert isinstance(d["intent"], str)
        assert isinstance(d["risk_signal"], float)
        assert isinstance(d["evidence"], str)
        assert 0.0 <= d["risk_signal"] <= 1.0

        # Validate with Pydantic model
        output_model = ConversationIntelligenceOutput(**d)
        assert output_model.intent == d["intent"]
        assert output_model.risk_signal == d["risk_signal"]

    def test_privacy_zero_retention(self):
        """
        Privacy Requirement:
        Do not permanently store transcripts unless explicitly required and consented to.
        When store_transcript_consented=False, transcript is stripped from output.
        """
        transcriber = WhisperTranscriber()
        transcriber.set_test_transcript_override("Please send the money right away.")
        classifier = ConversationIntelligenceClassifier(transcriber=transcriber)

        audio = torch.zeros(16000, dtype=torch.float32)

        # 1. Ephemeral analysis without retention consent
        res_ephemeral = classifier.analyze_audio(
            audio=audio,
            user_consent=True,
            store_transcript_consented=False,
        )
        assert res_ephemeral.transcript is None  # Scrubbed from memory

        # 2. When user consent is withheld entirely
        res_no_consent = classifier.analyze_audio(
            audio=audio,
            user_consent=False,
            store_transcript_consented=False,
        )
        assert res_no_consent.risk_signal == 0.0
        assert "consent withheld" in res_no_consent.evidence.lower()

    def test_risk_engine_synergy_with_conversation(self, risk_engine):
        """
        Validates integration into the MultiFactorRiskEngine:
        - Synthetic speech (spoof >= 0.70) + Credential request (OTP/Emergency) -> Non-linear compounding CRITICAL BLOCK.
        """
        # Case A: Synthetic voice clone requesting an OTP
        input_attack = RiskEngineInput(
            deepfake_probability=0.88,
            speaker_similarity=0.89,  # Targeted clone
            liveness_score=0.90,
            caller_verified=True,
            contextual_signals=["OTP_REQUEST"],
        )
        res_attack = risk_engine.evaluate_risk(input_attack)

        assert res_attack.risk_level == "CRITICAL"
        assert res_attack.risk_score >= 85
        assert res_attack.recommended_action == "BLOCK"
        assert "VOICE_CLONE_SOCIAL_ENGINEERING_SYNERGY" in res_attack.signals
        assert any("OTP_REQUEST" in s for s in res_attack.signals)

        # Case B: Clean human voice asking an informational question
        input_clean = RiskEngineInput(
            deepfake_probability=0.05,
            speaker_similarity=0.90,
            liveness_score=0.95,
            caller_verified=True,
            contextual_signals=["INFORMATIONAL_QUERY"],
        )
        res_clean = risk_engine.evaluate_risk(input_clean)

        assert res_clean.risk_level == "LOW"
        assert res_clean.recommended_action == "ALLOW"

    def test_rest_endpoint_conversation_analysis(self):
        """
        Validates POST /api/v1/conversation/analyze REST endpoint.
        """
        client = TestClient(app)
        headers = {"X-API-Key": "vigil-ai-hackathon-demo-key-2026"}

        # 1. Text transcript analysis: OTP request
        resp = client.post(
            "/api/v1/conversation/analyze",
            headers=headers,
            json={
                "transcript": "Send me the OTP right now.",
                "user_consent": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "OTP_REQUEST"
        assert data["risk_signal"] >= 0.85
        assert "evidence" in data

        # 2. Informational inquiry: What's an OTP?
        resp_info = client.post(
            "/api/v1/conversation/analyze",
            headers=headers,
            json={
                "transcript": "What's an OTP?",
                "user_consent": True,
            },
        )
        assert resp_info.status_code == 200
        data_info = resp_info.json()
        assert data_info["intent"] == "INFORMATIONAL_QUERY"
        assert data_info["risk_signal"] <= 0.15

        # 3. Withheld user consent
        resp_denied = client.post(
            "/api/v1/conversation/analyze",
            headers=headers,
            json={
                "transcript": "Send me the money",
                "user_consent": False,
            },
        )
        assert resp_denied.status_code == 400
        assert "consent" in resp_denied.json()["detail"].lower()
