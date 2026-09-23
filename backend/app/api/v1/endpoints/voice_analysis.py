"""
VIGIL-AI Unified 6-Step Voice Analysis API Endpoint.
Processes live microphone recordings or audio files through:
1. Speech-to-Text Transcription ('what user say')
2. Anti-Spoofing Deepfake Engine (Genuine vs Cloned Voice)
3. Local SQLite Biometric DB Speaker Matching (Person Name & Similarity 0.XXX)
4. AI Spam & Intent Analysis (OTP Request, Financial Fraud, Phishing)
5. Multi-Factor Risk Assessment & Action Verdict
"""
import io
import time
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
import numpy as np
import soundfile as sf
from pydantic import BaseModel, Field

from app.core.logging import logger
from app.db.embedding_store import get_embedding_store
from app.pipeline.conversation_intelligence import ConversationIntelligenceClassifier
from app.pipeline.deepfake_detector import DeepfakeModelRegistry
from app.pipeline.speaker_encoder import SpeakerModelRegistry
from app.pipeline.transcriber import get_transcriber

from app.core.audio_utils import load_audio_bytes

router = APIRouter()


class Stage1Detail(BaseModel):
    inference_source: str = Field("MODEL_INFERENCE", description="Provenance of Stage 1 result")
    model: str = Field(..., description="Name of anti-spoofing model")
    model_version: str = Field(..., description="Version of anti-spoofing model")
    is_clone: bool = Field(..., description="True if synthetic deepfake detected")
    clone_status: str = Field(..., description="'CLONED / SYNTHETIC VOICE' or 'GENUINE VOICE'")
    clone_probability: float = Field(..., description="Probability of clone (0.0 to 1.0)")
    genuine_probability: float = Field(..., description="Probability of genuine human voice (0.0 to 1.0)")
    confidence: float = Field(..., description="Confidence of model inference (0.0 to 1.0)")
    latency_ms: float = Field(..., description="Execution latency of Stage 1 in ms")


class Stage2Detail(BaseModel):
    inference_source: str = Field("MODEL_INFERENCE", description="Provenance of Stage 2 result")
    model: str = Field(..., description="Name of speaker verification model")
    model_version: str = Field(..., description="Version of speaker verification model")
    embedding_dim: int = Field(192, description="Dimensionality of extracted speaker embedding")
    similarity_score: float = Field(..., description="Cosine similarity score (0.0 to 1.0)")
    threshold: float = Field(0.65, description="Decision threshold for match")
    is_matched: bool = Field(..., description="True if voice matches enrolled profile")
    matched_person_name: Optional[str] = Field(None, description="Name of matched enrolled person")
    latency_ms: float = Field(..., description="Execution latency of Stage 2 in ms")


class Stage3Detail(BaseModel):
    inference_source: str = Field("RULE_ENGINE", description="Provenance of Stage 3 result: RULE_ENGINE")
    engine: str = Field("Conversation Intelligence Intent Classifier", description="Engine identifier")
    intent: str = Field(..., description="Detected conversational intent")
    is_spam: bool = Field(..., description="True if scam/fraud intent detected")
    spam_score: float = Field(..., description="Spam risk score (0.0 to 1.0)")
    contributing_signals: List[str] = Field(default_factory=list, description="Specific triggers detected")
    analysis: str = Field(..., description="Human explanation of analysis")
    latency_ms: float = Field(..., description="Execution latency of Stage 3 in ms")


class VoiceAnalysisResultResponse(BaseModel):
    request_id: str = Field(..., description="Unique request tracing ID")
    inference_source: str = Field("BACKEND_MODEL", description="Overall execution provenance")
    transcript: str = Field(..., description="What the user said (Speech-to-Text)")
    is_clone: bool = Field(..., description="True if voice is cloned/synthetic deepfake")
    clone_status: str = Field(..., description="'CLONED / SYNTHETIC VOICE' or 'GENUINE VOICE'")
    clone_probability: float = Field(..., description="Probability of deepfake cloning (0.0 to 1.0)")

    is_db_matched: bool = Field(..., description="True if voice matches an enrolled person in local DB")
    matched_person_name: Optional[str] = Field(None, description="Name of person matched in DB")
    similarity_score: float = Field(..., description="Biometric similarity score (0.XXX)")

    caller_intent: str = Field(..., description="Detected intent e.g., OTP_REQUEST, FINANCIAL_FRAUD, INFORMATIONAL")
    is_spam: bool = Field(..., description="True if spam/phishing intent detected")
    spam_score: float = Field(..., description="Spam risk score (0.0 to 1.0)")
    spam_analysis: str = Field(..., description="Human explanation of spam/fraud risk")

    risk_score: float = Field(..., description="Overall compound risk score (0 to 100)")
    threat_level: str = Field(..., description="'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'")
    action: str = Field(..., description="'ALLOW', 'MONITOR', 'CHALLENGE', 'BLOCK'")
    analysis_latency_ms: float = Field(..., description="Total processing time in ms")

    stage1: Optional[Stage1Detail] = Field(None, description="Detailed Stage 1 telemetry")
    stage2: Optional[Stage2Detail] = Field(None, description="Detailed Stage 2 telemetry")
    stage3: Optional[Stage3Detail] = Field(None, description="Detailed Stage 3 telemetry")


@router.post(
    "/voice",
    response_model=VoiceAnalysisResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze live microphone voice through 6-step AI pipeline",
)
async def analyze_voice_sample(
    audio_file: UploadFile = File(..., description="Live recorded audio from microphone or test WAV"),
    text_hint: Optional[str] = Form(None, description="Optional manual transcript hint"),
):
    """
    Executes complete 6-step voice & risk analysis with strict provenance tracking:
    1. Transcribes audio ('what user say')
    2. Stage 1: WavLM-AASIST Anti-Spoofing Deepfake Engine (MODEL_INFERENCE)
    3. Stage 2: SpeechBrain ECAPA-TDNN 192-dim Biometric Speaker Verification (MODEL_INFERENCE)
    4. Stage 3: Conversation Intelligence Intent & Scam Classifier (RULE_ENGINE)
    5. Compound multi-factor risk verdict & action decision
    """
    t0 = time.perf_counter()
    request_id = f"req-{uuid.uuid4().hex[:10]}"
    content = await audio_file.read()

    if not content:
        raise HTTPException(status_code=400, detail="Empty audio file submitted.")

    # 1. Load Audio Bytes to Float32 NumPy Array
    try:
        audio_np, sr = load_audio_bytes(content)
    except Exception as e:
        logger.error(f"Could not decode audio content: {e}")
        raise HTTPException(status_code=400, detail=f"Could not parse audio sample: {str(e)}")

    if len(audio_np) == 0:
        raise HTTPException(status_code=400, detail="Could not extract valid audio samples.")

    # ══════════════════════════════════════════════════════════════════
    # STAGE 1: Anti-Spoofing Deepfake Engine (Real Neural Model)
    # ══════════════════════════════════════════════════════════════════
    t_s1 = time.perf_counter()
    detector = DeepfakeModelRegistry.get_detector()
    deepfake_res = detector.predict(audio_np)
    s1_latency = round((time.perf_counter() - t_s1) * 1000.0, 2)

    clone_prob = float(deepfake_res.spoof_probability)
    genuine_prob = float(deepfake_res.bonafide_probability)
    is_clone = deepfake_res.label == "spoof" or clone_prob >= 0.65
    clone_status = "CLONED / SYNTHETIC VOICE" if is_clone else "GENUINE VOICE"

    stage1_detail = Stage1Detail(
        inference_source="MODEL_INFERENCE",
        model=getattr(detector, "MODEL_NAME", "WavLM-AASIST Voice Clone Detector"),
        model_version=getattr(detector, "MODEL_VERSION", "Vigil-WavLM-AASIST-v1.0"),
        is_clone=is_clone,
        clone_status=clone_status,
        clone_probability=round(clone_prob, 3),
        genuine_probability=round(genuine_prob, 3),
        confidence=round(float(deepfake_res.confidence), 3),
        latency_ms=s1_latency,
    )

    # ══════════════════════════════════════════════════════════════════
    # STAGE 2: SpeechBrain ECAPA-TDNN 192-dim Speaker Verification
    # ══════════════════════════════════════════════════════════════════
    t_s2 = time.perf_counter()
    encoder = SpeakerModelRegistry.get_encoder()
    store = get_embedding_store()

    live_embedding = encoder.encode(audio_np, sample_rate=sr)
    nearest_candidates = await store.search_nearest_speakers(live_embedding, top_k=1)
    s2_latency = round((time.perf_counter() - t_s2) * 1000.0, 2)

    SIMILARITY_THRESHOLD = 0.65
    is_db_matched = False
    matched_person_name = None
    similarity_score = 0.0

    if nearest_candidates:
        best_profile, raw_sim = nearest_candidates[0]
        # Calibrate raw similarity range [0.400, 0.850] into biometric scale [0.0, 0.999]
        BASE_LOW = 0.400
        BASE_HIGH = 0.850
        if raw_sim >= BASE_LOW:
            calibrated = (raw_sim - BASE_LOW) / (BASE_HIGH - BASE_LOW)
        else:
            calibrated = 0.0
        similarity_score = round(float(np.clip(calibrated, 0.0, 0.999)), 3)
        if similarity_score >= SIMILARITY_THRESHOLD:
            is_db_matched = True
            matched_person_name = best_profile.name

    encoder_info = encoder.get_model_info() if hasattr(encoder, "get_model_info") else {}
    stage2_detail = Stage2Detail(
        inference_source="MODEL_INFERENCE",
        model=encoder_info.get("name", "SpeechBrain ECAPA-TDNN"),
        model_version=encoder_info.get("version", "speechbrain/spkrec-ecapa-voxceleb"),
        embedding_dim=int(encoder_info.get("embedding_dim", 192)),
        similarity_score=similarity_score,
        threshold=SIMILARITY_THRESHOLD,
        is_matched=is_db_matched,
        matched_person_name=matched_person_name,
        latency_ms=s2_latency,
    )

    # ══════════════════════════════════════════════════════════════════
    # STAGE 3: Speech-to-Text Transcription & Intent / Scam Classifier
    # ══════════════════════════════════════════════════════════════════
    t_s3 = time.perf_counter()
    if text_hint and len(text_hint.strip()) > 0:
        transcript = text_hint.strip()
    else:
        transcriber = get_transcriber()
        transcript = transcriber.transcribe(audio_np, sample_rate=sr)

    ci_classifier = ConversationIntelligenceClassifier()
    ci_result = ci_classifier.classify_intent(transcript)
    s3_latency = round((time.perf_counter() - t_s3) * 1000.0, 2)

    caller_intent = ci_result.intent.value if hasattr(ci_result.intent, "value") else str(ci_result.intent)
    spam_score = float(ci_result.risk_signal)
    is_spam = (spam_score >= 0.5) or (caller_intent in ["OTP_REQUEST", "FINANCIAL_FRAUD", "URGENT_SCAM"])

    contributing_signals = []
    if caller_intent == "OTP_REQUEST":
        contributing_signals.append("OTP_SOLICITATION")
    elif caller_intent == "FINANCIAL_FRAUD":
        contributing_signals.append("FINANCIAL_FRAUD_KEYWORD")
    elif caller_intent == "URGENT_SCAM":
        contributing_signals.append("URGENT_COERCION")

    if is_spam:
        spam_analysis = f"High Scam Risk: Detected {caller_intent} in caller speech."
    else:
        spam_analysis = "Nominal Speech: No spam or extortion intent detected."

    stage3_detail = Stage3Detail(
        inference_source="RULE_ENGINE",
        engine="Conversation Intelligence Intent Classifier",
        intent=caller_intent,
        is_spam=is_spam,
        spam_score=round(spam_score, 3),
        contributing_signals=contributing_signals,
        analysis=spam_analysis,
        latency_ms=s3_latency,
    )

    # ══════════════════════════════════════════════════════════════════
    # MULTI-FACTOR RISK VERDICT
    # ══════════════════════════════════════════════════════════════════
    if is_clone:
        # Cloned Voice -> CRITICAL THREAT & MANDATORY BLOCK
        raw_risk = 95.0 + (clone_prob * 4.0)
        threat_level = "CRITICAL"
        action = "BLOCK"
    elif not is_db_matched:
        # Unknown / Unenrolled Caller -> HIGH RISK & MANDATORY CHALLENGE / WARN
        raw_risk = 85.0
        threat_level = "HIGH"
        action = "CHALLENGE"
    else:
        # Verified Enrolled Person -> LOW THREAT
        raw_risk = 10.0
        threat_level = "LOW"
        action = "ALLOW"

    # Apply Spam / Fraud Penalty
    if is_spam:
        raw_risk = min(99.0, raw_risk + 35.0)
        if raw_risk >= 85.0:
            threat_level = "CRITICAL" if is_clone else "HIGH"
            action = "BLOCK" if is_clone else "WARN"
        elif raw_risk >= 60.0:
            threat_level = "HIGH"
            action = "WARN"

    final_risk_score = round(float(np.clip(raw_risk, 5.0, 99.0)), 1)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    return VoiceAnalysisResultResponse(
        request_id=request_id,
        inference_source="BACKEND_MODEL",
        transcript=transcript,
        is_clone=is_clone,
        clone_status=clone_status,
        clone_probability=round(clone_prob, 3),
        is_db_matched=is_db_matched,
        matched_person_name=matched_person_name,
        similarity_score=similarity_score,
        caller_intent=caller_intent,
        is_spam=is_spam,
        spam_score=round(spam_score, 3),
        spam_analysis=spam_analysis,
        risk_score=final_risk_score,
        threat_level=threat_level,
        action=action,
        analysis_latency_ms=elapsed_ms,
        stage1=stage1_detail,
        stage2=stage2_detail,
        stage3=stage3_detail,
    )
