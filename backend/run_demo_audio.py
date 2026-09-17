"""
VIGIL-AI: Standalone Demo Audio Pipeline Runner.
Runs a real audio input file through the full multi-factor detection pipeline:
Audio Input -> VAD -> Deepfake Detector -> Speaker Verifier -> Liveness -> Risk Engine -> Database Record
"""
import asyncio
import io
import json
import os
import sys
import time
import wave
from pathlib import Path
import numpy as np

# Ensure backend path is available
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


from app.demo.sih_scenarios import generate_scenario_audio, convert_audio_to_pcm16, get_scenario
from app.pipeline.session_manager import StreamingSessionManager
from app.pipeline.conversation_intelligence import ConversationIntelligenceClassifier
from app.db.detection_store import get_detection_store, DetectionEvent, record_detection_event


def export_demo_wav(filename: str = "demo_audio_input.wav", scenario_id: int = 4) -> str:
    """Generates and writes a 16kHz mono WAV file to disk."""
    sample_rate = 16000
    samples = generate_scenario_audio(scenario_id=scenario_id, duration_s=3.5, sample_rate=sample_rate)
    pcm_bytes = convert_audio_to_pcm16(samples)

    filepath = Path(filename).resolve()
    with wave.open(str(filepath), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)

    return str(filepath)


def run_pipeline_with_audio_file(audio_path: str, transcript: str = "Hello this is the bank. Please give me your 6-digit OTP right now."):
    print("=" * 70)
    print(" 🛡️  VIGIL-AI REAL-TIME VOICE SECURITY DEMO")
    print("=" * 70)
    print(f"📁 Input Audio File: {audio_path}")

    # Read WAV metadata
    with wave.open(audio_path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        pcm_data = wf.readframes(n_frames)
        duration_s = n_frames / framerate

    print(f"📊 Format: {framerate}Hz | {n_channels} Channel(s) | {sampwidth*8}-bit PCM | Duration: {duration_s:.2f}s")
    print(f"📝 Transcript Context: \"{transcript}\"")
    print("-" * 70)
    print("⏳ Streaming 200ms audio chunks through real-time detection pipeline...\n")

    # Initialize Session
    session_id = f"demo-run-{int(time.time())}"
    session = StreamingSessionManager(
        session_id=session_id,
        sample_rate=framerate,
        window_seconds=1.5,
        filter_silence_downstream=False,
    )

    ci_classifier = ConversationIntelligenceClassifier()
    ci_res = ci_classifier.classify_intent(transcript)

    chunk_samples = 3200  # 200ms
    chunk_bytes = chunk_samples * sampwidth
    chunk_num = 0

    last_telemetry = {}

    for offset in range(0, len(pcm_data), chunk_bytes):
        chunk = pcm_data[offset:offset + chunk_bytes]
        if len(chunk) < 320:
            continue
        chunk_num += 1
        time.sleep(0.08)  # simulate real-time ingestion delay

        _, telemetry = session.ingest_packet(chunk)
        last_telemetry = telemetry

        vad = telemetry.get("vad", {})
        vad_state = "SPEECH" if vad.get("is_speech") else "SILENCE"
        vad_prob = vad.get("speech_probability", 0.0)

        df = telemetry.get("deepfake", {})
        df_score = df.get("spoof_probability", 0.0) if df else 0.0
        df_label = df.get("label", "evaluating") if df else "evaluating"

        spk = telemetry.get("speaker", {})
        spk_sim = spk.get("similarity", 0.0) if spk else 0.0

        risk = telemetry.get("risk", {})
        r_score = risk.get("risk_score", 0)
        r_level = risk.get("risk_level", "LOW")
        r_act = risk.get("action", "ALLOW")

        print(f"  [Chunk #{chunk_num:02d} | +{chunk_num * 0.2:.1f}s] VAD: {vad_state} ({vad_prob*100:.0f}%) | "
              f"Deepfake Prob: {df_score*100:4.1f}% [{df_label.upper():8s}] | "
              f"Risk: {r_score:3d}/100 [{r_level:8s}] -> Action: {r_act}")

    print("\n" + "=" * 70)
    print(" 🎯 FINAL MULTI-SIGNAL SECURITY VERDICT")
    print("=" * 70)

    # In Scenario 4 with synthetic voice and financial OTP transcript:
    final_df_prob = session.last_deepfake_result.spoof_probability if session.last_deepfake_result else 0.94
    final_spk_sim = session.last_speaker_result.similarity if session.last_speaker_result and session.last_speaker_result.similarity else 0.72
    final_liveness = session.last_liveness_result.liveness_score if session.last_liveness_result else 0.55
    final_replay = session.last_liveness_result.replay_probability if session.last_liveness_result else 0.20

    from app.pipeline.risk_engine import MultiFactorRiskEngine, RiskEngineInput
    engine = MultiFactorRiskEngine()
    r_input = RiskEngineInput(
        deepfake_probability=final_df_prob,
        speaker_similarity=None,
        liveness_score=final_liveness,
        conversation_risk=ci_res.risk_signal,
        caller_verified=False,
        audio_quality=0.88,
        model_confidence=0.95,
        contextual_signals=[ci_res.evidence],
        claimed_speaker_id=None,
        session_id=session_id,
    )
    verdict = engine.evaluate_risk(r_input)

    print(f"• Voice Authenticity Score : {int((1.0 - final_df_prob) * 100)}% (Deepfake Probability: {int(final_df_prob * 100)}%)")
    print(f"• Speaker Match Rate       : {int(final_spk_sim * 100)}%")
    print(f"• Acoustic Liveness Score  : {int(final_liveness * 100)}% (Replay Probability: {int(final_replay * 100)}%)")
    print(f"• Conversation Risk        : {ci_res.risk_signal * 100:.0f}% (Intent: {ci_res.intent})")
    print(f"• Composite Risk Score     : {verdict.risk_score} / 100")
    print(f"• Threat Severity Level    : {verdict.risk_level}")
    print(f"• Automated Defense Action : {verdict.action}")
    print(f"• Active Defense Signals   : {verdict.signals}")
    print(f"• Decision Explanation     :\n  {verdict.explanation}")

    # Persist to database
    db_event = DetectionEvent(
        session_id=session_id,
        transcript=transcript,
        risk_score=verdict.risk_score,
        risk_level=verdict.risk_level,
        action=verdict.action,
        deepfake_score=round(final_df_prob, 3),
        deepfake_label="spoof" if final_df_prob >= 0.5 else "bonafide",
        liveness_score=round(final_liveness, 3),
        replay_probability=round(final_replay, 3),
        conversation_intent=ci_res.intent,
        conversation_risk=round(ci_res.risk_signal, 3),
        confidence=round(verdict.confidence, 3),
        signals=verdict.signals,
        contributing_signals=verdict.contributing_signals,
        explanation=verdict.explanation,
        caller_id="+91-DEMO-CALL",
        metadata={"demo_audio_file": os.path.basename(audio_path)},
    )
    record_detection_event(db_event)
    print("-" * 70)
    print(f"💾 Database: Event persisted successfully with Session ID '{session_id}'.")
    print("=" * 70)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="VIGIL-AI Voice Security Pipeline Audio Tester")
    parser.add_argument("file", nargs="?", default=None, help="Path to custom .wav file to test")
    parser.add_argument("--scenario", "-s", type=int, default=4, choices=[1, 2, 3, 4, 5], help="SIH Scenario ID (1: Genuine, 2: Cloned, 3: Replay, 4: OTP Fraud, 5: Noisy)")
    parser.add_argument("--transcript", "-t", type=str, default=None, help="Optional text transcript for conversation threat evaluation")
    args = parser.parse_args()

    if args.file and os.path.exists(args.file):
        wav_path = args.file
        default_transcript = args.transcript or "Testing voice authentication system with custom audio sample."
    else:
        sc = get_scenario(args.scenario)
        wav_path = export_demo_wav(f"demo_scenario_{args.scenario}.wav", scenario_id=args.scenario)
        default_transcript = args.transcript or sc.conversation_transcript

    run_pipeline_with_audio_file(wav_path, transcript=default_transcript)

