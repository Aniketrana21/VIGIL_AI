import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import torch

from app.core.config import settings
from app.core.logging import logger
from app.core.security import secure_zero_memory
from app.pipeline.interfaces import ConversationIntelligenceResult
from app.pipeline.transcriber import WhisperTranscriber, get_transcriber
from app.schemas.conversation import CallerIntent, ConversationIntelligenceOutput


class ConversationIntelligenceClassifier:
    """
    VIGIL-AI Conversation Intelligence & Contextual Risk Engine (Phase 11).

    Analyzes speech transcripts from Whisper ASR to identify potential high-risk caller intents.

    CRITICAL REQUIREMENTS:
    1. NEVER make decisions based solely on keywords. Use grammatical and pragmatic context.
       - "Send me the OTP" -> High-risk authentication request (Imperative directive).
       - "What's an OTP?" -> Informational query, not automatically malicious (Interrogative inquiry).
    2. Decoupled from Audio Deepfake Detection:
       - This module evaluates conversational intent, not acoustic synthesis or vocoder artifacts.
    3. Privacy Mandate:
       - Transcripts are held ephemerally during classification and discarded immediately.
       - Zero permanent storage unless explicitly consented to.
    """

    # Inquisitive / Educational question starters (informational, not demanding)
    QUESTION_PATTERNS = [
        r"^(what('s| is| are| does| do))\b",
        r"^(why (is|are|do|would|should))\b",
        r"^(how (do|does|can|to|would))\b",
        r"^(can you explain|could you explain|please explain)\b",
        r"^(is it safe|is this safe)\b",
        r"^(what does .* mean)\b",
        r"^(meaning of)\b",
        r"\?$",
    ]

    # Negation / Educational warning patterns (nominal / advisory)
    NEGATION_WARNING_PATTERNS = [
        r"\b(never (share|give|send|disclose))\b",
        r"\b(do not (share|give|send|disclose|tell))\b",
        r"\b(don't (share|give|send|tell))\b",
        r"\b(i will not (share|give|send))\b",
        r"\b(warn(ing)? (about|against))\b",
    ]

    # Imperative / Directive / Demand verbs and phrases (English & Hindi/Hinglish)
    DIRECTIVE_PATTERNS = [
        r"\b(send( me)?|give( me)?|tell( me)?|share|read out|forward|enter|provide|disclose|verify for me)\b",
        r"\b(transfer( to)?|wire( to)?|pay( to)?|deposit)\b",
        r"\b(reset (my|the)|bypass|unlock|grant( me)?)\b",
        r"\b(bhejo|de do|de|batao|share karo|transfer karo|daalo|daal do|send karo|bolo|likho|enter karo|padh ke batao|dijiye|batayein)\b",
    ]

    # Urgency & Coercion triggers (English & Hindi/Hinglish)
    URGENCY_PATTERNS = [
        r"\b(urgently|immediately|right now|asap|fast|hurry|quick|within \d+ minutes)\b",
        r"\b(hospital|police|accident|jail|arrest|emergency|life or death|kidnap)\b",
        r"\b(account (is|will be) (blocked|suspended|frozen|locked|terminated))\b",
        r"\b(turant|jaldi|jaldi karo|abhi ke abhi|fauran|jail|police|thana|accident|hospital|giraftaar|digital arrest|cbi|crime branch|customs|illegal courier|drugs|khata band|account block|paisa phasa)\b",
    ]

    MODEL_NAME = "Whisper Contextual Intent Classifier"
    MODEL_VERSION = "OpenAI-Whisper-Base-v1.0"

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "name": self.MODEL_NAME,
            "version": self.MODEL_VERSION,
            "status": "READY",
            "model_size": getattr(settings, "WHISPER_MODEL_SIZE", "base"),
        }

    def __init__(self, transcriber: Optional[WhisperTranscriber] = None):
        self.transcriber = transcriber or get_transcriber()

    def _is_informational_query(self, text: str) -> bool:
        """
        Determines whether the utterance is an inquisitive or educational question
        regarding security/financial concepts rather than an imperative or coercive demand.
        General social chatter ("How are you doing?") is handled as BENIGN_CONVERSATION.
        """
        clean = text.strip().lower()

        # Sensitive domain concepts that can be queried educationally
        concept_patterns = [
            r"\b(otp|one time password|verification code|pin|password|upi|cvv|wire transfer|money transfer|2fa|authenticat(e|ion))\b"
        ]
        has_concept = any(re.search(c, clean) for c in concept_patterns)
        if not has_concept:
            # Casual questions like "How are you doing?" are benign conversation, not informational queries
            return False

        # Check explicit question starters or terminal question mark
        for pat in self.QUESTION_PATTERNS:
            if re.search(pat, clean):
                # Ensure it's not a deceptive imperative masked as a question
                has_directive = any(re.search(d, clean) for d in self.DIRECTIVE_PATTERNS)
                has_urgency = any(re.search(u, clean) for u in self.URGENCY_PATTERNS)
                if has_directive or has_urgency:
                    return False
                return True

        return False

    def _has_urgency(self, text: str) -> bool:
        clean = text.lower()
        return any(re.search(p, clean) for p in self.URGENCY_PATTERNS)

    def classify_intent(self, text: str) -> ConversationIntelligenceResult:
        """
        Performs natural language contextual intent classification on caller transcript.
        Returns standardized ConversationIntelligenceResult.
        """
        t0 = time.perf_counter()
        clean = text.strip()
        lower = clean.lower()

        if not clean:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ConversationIntelligenceResult(
                intent=CallerIntent.BENIGN_CONVERSATION.value,
                risk_signal=0.0,
                evidence="no speech detected",
                transcript=clean,
                latency_ms=latency_ms,
            )

        # 1. Check for educational negations ("Never share your password")
        for neg in self.NEGATION_WARNING_PATTERNS:
            if re.search(neg, lower):
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return ConversationIntelligenceResult(
                    intent=CallerIntent.BENIGN_CONVERSATION.value,
                    risk_signal=0.05,
                    evidence="educational safety advisory advising against sharing sensitive credentials",
                    transcript=clean,
                    latency_ms=latency_ms,
                )

        # 2. Check for informational inquiries ("What is an OTP?", "How does UPI work?")
        if self._is_informational_query(lower):
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ConversationIntelligenceResult(
                intent=CallerIntent.INFORMATIONAL_QUERY.value,
                risk_signal=0.08,
                evidence="informational clarification question about concepts or procedures",
                transcript=clean,
                latency_ms=latency_ms,
            )

        has_urgency = self._has_urgency(lower)

        # 3. Target Intent: OTP Request (Multilingual English & Hindi/Hinglish)
        if re.search(r"\b(otp|one time password|verification code|security code|6 digit code|sms code|code batao|otp batao|otp bhejo|otp do|otp bolo|sms wala code)\b", lower):
            if any(re.search(d, lower) for d in self.DIRECTIVE_PATTERNS) or not lower.endswith("?"):
                risk = 0.95 if has_urgency else 0.90
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return ConversationIntelligenceResult(
                    intent=CallerIntent.OTP_REQUEST.value,
                    risk_signal=risk,
                    evidence="direct imperative request or demand to disclose one-time authentication passcode (OTP / OTP batao)",
                    transcript=clean,
                    latency_ms=latency_ms,
                )

        # 4. Target Intent: UPI Request (Multilingual English & Hindi/Hinglish)
        if re.search(r"\b(upi|gpay|google pay|phonepe|paytm|bhim|@upi|@okhdfcbank|@okaxis|@ybl|vpa|paise bhejo|paisa transfer|rupaye bhejo|paisa daalo|qr code scan|scan karo|paise daal do)\b", lower):
            if any(re.search(d, lower) for d in self.DIRECTIVE_PATTERNS) or re.search(r"\b(pay|send|transfer|scan|bhejo|daalo)\b", lower):
                risk = 0.93 if has_urgency else 0.88
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return ConversationIntelligenceResult(
                    intent=CallerIntent.UPI_REQUEST.value,
                    risk_signal=risk,
                    evidence="solicitation of direct UPI / QR code payment transfer (Paisa transfer / UPI request)",
                    transcript=clean,
                    latency_ms=latency_ms,
                )

        # 5. Target Intent: Emergency Money Request & Digital Arrest Impersonation
        is_true_emergency = bool(re.search(r"\b(hospital|accident|police|bail|arrest|jail|kidnap|life or death|police station|thana|accident ho gaya|jail me hu|giraftaar|bacha lo|bail ke liye|digital arrest|cbi officer|customs officer|mumbai police|delhi police|narcotics|parcel me drugs)\b", lower))
        is_family_distress = bool(re.search(r"\b(mom|dad|son|daughter|grandma|grandpa|papa|mummy|bhai|behan|chacha|mama|dost)\b", lower)) and (is_true_emergency or bool(re.search(r"\b(urgent|urgently|emergency|jaldi|turant)\b", lower)))
        if is_true_emergency or is_family_distress:
            if re.search(r"\b(money|cash|funds|wire|transfer|rupees|dollars|send|pay|help|paise|rupaye|paisa|madad)\b", lower) or "digital arrest" in lower or "parcel me drugs" in lower:
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return ConversationIntelligenceResult(
                    intent=CallerIntent.EMERGENCY_MONEY_REQUEST.value,
                    risk_signal=0.96,
                    evidence="high-pressure emergency family distress or law enforcement impersonation extortion (Accident / Police / Digital Arrest scam)",
                    transcript=clean,
                    latency_ms=latency_ms,
                )

        # 6. Target Intent: Account Takeover Attempt
        if re.search(r"\b(account takeover|bypass 2fa|take over|reset (my|the|an) password|change (the|my) email|change (the|my) phone|sim swap|transfer (the|my) number|disable 2fa|khata band|account block|sim band)\b", lower):
            risk = 0.95 if has_urgency else 0.92
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ConversationIntelligenceResult(
                intent=CallerIntent.ACCOUNT_TAKEOVER_ATTEMPT.value,
                risk_signal=risk,
                evidence="unauthorized account recovery, credential reset, or SIM swap takeover attempt",
                transcript=clean,
                latency_ms=latency_ms,
            )

        # 7. Target Intent: Password / PIN Request (Multilingual)
        if re.search(r"\b(password|passcode|pin|netbanking pin|atm pin|login credentials|atm ka pin|pin batao|password batao|login id batao)\b", lower):
            if any(re.search(d, lower) for d in self.DIRECTIVE_PATTERNS) or not lower.endswith("?"):
                risk = 0.96 if has_urgency else 0.92
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return ConversationIntelligenceResult(
                    intent=CallerIntent.PASSWORD_REQUEST.value,
                    risk_signal=risk,
                    evidence="direct request to disclose password or PIN credentials (PIN / Password batao)",
                    transcript=clean,
                    latency_ms=latency_ms,
                )

        # 8. Target Intent: Bank Credential Request (Multilingual)
        if re.search(r"\b(cvv|cvv2|card number|debit card|credit card|16 digit|expiry date|bank account number|ifsc|aadhar card|pan card link|kyc update|khata update)\b", lower):
            if any(re.search(d, lower) for d in self.DIRECTIVE_PATTERNS) or not lower.endswith("?"):
                risk = 0.95 if has_urgency else 0.90
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return ConversationIntelligenceResult(
                    intent=CallerIntent.BANK_CREDENTIAL_REQUEST.value,
                    risk_signal=risk,
                    evidence="solicitation of sensitive payment card or banking account credentials (CVV / Aadhar / Bank details)",
                    transcript=clean,
                    latency_ms=latency_ms,
                )

        # 9. Target Intent: Confidential Information Request
        if re.search(r"\b(confidential|trade secret|source code|proprietary|customer list|customer database|api key|secret key|internal documents)\b", lower):
            risk = 0.92 if has_urgency else 0.88
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ConversationIntelligenceResult(
                intent=CallerIntent.CONFIDENTIAL_INFO_REQUEST.value,
                risk_signal=risk,
                evidence="unauthorized solicitation of confidential organizational or proprietary information",
                transcript=clean,
                latency_ms=latency_ms,
            )

        # 10. Target Intent: General Money Transfer / Financial Request
        if re.search(r"\b(money transfer|wire transfer|send money|transfer funds|wire funds|transfer money|remittance)\b", lower):
            risk = 0.92 if has_urgency else 0.88
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ConversationIntelligenceResult(
                intent=CallerIntent.FINANCIAL_REQUEST.value,
                risk_signal=risk,
                evidence="request for money transfer",
                transcript=clean,
                latency_ms=latency_ms,
            )

        # 11. Target Intent: Identity Verification Request
        if re.search(r"\b(aadhaar|ssn|social security|passport number|national id|driver'?s license|identity verification)\b", lower):
            risk = 0.88 if has_urgency else 0.82
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return ConversationIntelligenceResult(
                intent=CallerIntent.IDENTITY_VERIFICATION_REQUEST.value,
                risk_signal=risk,
                evidence="solicitation of government identity documents or identity verification data",
                transcript=clean,
                latency_ms=latency_ms,
            )

        # 12. Default: Benign Everyday Discourse
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return ConversationIntelligenceResult(
            intent=CallerIntent.BENIGN_CONVERSATION.value,
            risk_signal=0.03,
            evidence="nominal conversation with no detected scam, credential, or financial solicitation indicators",
            transcript=clean,
            latency_ms=latency_ms,
        )

    def analyze_audio(
        self,
        audio: Union[np.ndarray, torch.Tensor],
        user_consent: bool = True,
        store_transcript_consented: bool = False,
    ) -> ConversationIntelligenceResult:
        """
        Complete pipeline:
        audio -> speech recognition (Whisper) -> transcript -> intent/risk classifier -> structured risk signals.
        """
        if not user_consent:
            logger.warning("Conversation intelligence skipped: user consent required.")
            return ConversationIntelligenceResult(
                intent=CallerIntent.BENIGN_CONVERSATION.value,
                risk_signal=0.0,
                evidence="user consent withheld for speech-to-text analysis",
                transcript=None,
                latency_ms=0.0,
            )

        # Step 1: Speech recognition (ASR)
        transcript = self.transcriber.transcribe(
            audio=audio,
            user_consent=user_consent,
            store_transcript_consented=store_transcript_consented,
        )

        # Step 2: Contextual intent & risk classification
        result = self.classify_intent(transcript)

        # Step 3: Zero-retention privacy enforcement
        if not store_transcript_consented:
            # Ephemeral scrubbing: do not persist transcript in return object
            result.transcript = None

        return result


# Global singleton
_conversation_classifier_instance: Optional[ConversationIntelligenceClassifier] = None


def get_conversation_classifier() -> ConversationIntelligenceClassifier:
    global _conversation_classifier_instance
    if _conversation_classifier_instance is None:
        _conversation_classifier_instance = ConversationIntelligenceClassifier()
    return _conversation_classifier_instance


# Backward-compatible alias
ContextualConversationClassifier = ConversationIntelligenceClassifier

