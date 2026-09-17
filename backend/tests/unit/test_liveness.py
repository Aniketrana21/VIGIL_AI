import math
import numpy as np
import pytest
import scipy.signal
import torch

from app.pipeline.liveness import LIVENESS_DISCLAIMER, LivenessAnalyzer, LivenessTimelineTracker


SAMPLE_RATE = 16000
WINDOW_DURATION_S = 1.5
WINDOW_SAMPLES = int(SAMPLE_RATE * WINDOW_DURATION_S)


def create_formant_speech(
    duration_s: float = 1.5,
    f0: float = 130.0,
    syllable_rate_hz: float = 4.0,
    papr_db_target: float = 16.0,
) -> np.ndarray:
    """
    Synthesizes speech-like audio with human-like vocal tract formants
    and natural syllabic envelope modulation.
    """
    t = np.linspace(0, duration_s, int(SAMPLE_RATE * duration_s), endpoint=False)

    # Glottal pulse train with micro-jitter
    jitter = 1.0 + 0.02 * np.sin(2 * np.pi * 3.7 * t)
    pulse = np.sin(2 * np.pi * f0 * jitter * t)

    # Formant filtering (vocal tract resonance peaks at 700Hz, 1220Hz, 2600Hz)
    sos = scipy.signal.butter(2, [300, 3400], btype="bandpass", fs=SAMPLE_RATE, output="sos")
    voiced = scipy.signal.sosfilt(sos, pulse)

    # Syllabic envelope modulation (3 - 6 Hz theta cadence)
    envelope = 0.5 * (1.0 + np.sin(2 * np.pi * syllable_rate_hz * t)) ** 2
    speech = voiced * envelope

    # Inject natural near-field acoustic dynamics to reach target PAPR
    rms = np.sqrt(np.mean(speech ** 2) + 1e-12)
    peak = np.max(np.abs(speech)) + 1e-9
    current_papr_db = 10.0 * np.log10((peak ** 2) / (rms ** 2 + 1e-12))

    # Scale dynamics
    gain_boost = 10.0 ** ((papr_db_target - current_papr_db) / 20.0)
    speech = speech * gain_boost
    peak = np.max(np.abs(speech))
    if peak > 0.95:
        speech = speech * (0.95 / peak)

    return speech.astype(np.float32)


@pytest.fixture
def liveness_analyzer():
    analyzer = LivenessAnalyzer(sample_rate=SAMPLE_RATE)
    analyzer.reset()
    return analyzer


class TestLivenessModule:
    """
    Comprehensive tests for VIGIL-AI Phase 9 Liveness-Analysis Module.
    """

    def test_live_microphone(self, liveness_analyzer):
        """
        1. Live Microphone Test:
        Simulates direct near-field vocal tract speech with uncompressed PAPR (> 13 dB),
        natural syllabic modulation rhythm, and natural pause characteristics.
        Expectation: High liveness score (>= 0.65), low replay probability (<= 0.35), high confidence.
        """
        raw_audio = create_formant_speech(
            duration_s=WINDOW_DURATION_S,
            f0=125.0,
            syllable_rate_hz=4.5,
            papr_db_target=17.0,
        )
        audio_tensor = torch.from_numpy(raw_audio)

        result = liveness_analyzer.evaluate(
            audio_window=audio_tensor,
            is_speech=True,
            turn_taking_latency_ms=450.0,  # Natural conversational turn latency
        )

        assert result.liveness_score >= 0.65, f"Expected high liveness for live mic, got {result.liveness_score}"
        assert result.replay_probability <= 0.35, f"Expected low replay prob for live mic, got {result.replay_probability}"
        assert result.confidence >= 0.70, f"Expected high confidence for clean live audio, got {result.confidence}"
        assert result.is_live_acoustic is True
        assert result.disclaimer == LIVENESS_DISCLAIMER

    def test_speaker_playback(self, liveness_analyzer):
        """
        2. Speaker Playback Test:
        Simulates replay through a consumer loudspeaker:
        - Severe dynamic range compression / clipping (PAPR < 7 dB)
        - Transducer harmonic distortion (2nd and 3rd harmonics)
        - Transducer high-frequency roll-off above 7 kHz.
        Expectation: Elevated replay probability (>= 0.60), low liveness score (<= 0.45).
        """
        base_audio = create_formant_speech(duration_s=WINDOW_DURATION_S, f0=140.0)

        # Apply loudspeaker dynamic range compression (soft clipping / limiting)
        compressed = np.tanh(base_audio * 4.5)

        # Add 2nd and 3rd harmonic transducer distortion
        distorted = compressed + 0.25 * (compressed ** 2) + 0.15 * (compressed ** 3)

        # Transducer steep low-pass filter (cut off above 6500 Hz)
        sos_lp = scipy.signal.butter(4, 6500, btype="lowpass", fs=SAMPLE_RATE, output="sos")
        speaker_audio = scipy.signal.sosfilt(sos_lp, distorted)

        # Normalize to prevent overflow
        speaker_audio = speaker_audio / (np.max(np.abs(speaker_audio)) + 1e-9) * 0.90
        audio_tensor = torch.from_numpy(speaker_audio.astype(np.float32))

        result = liveness_analyzer.evaluate(audio_window=audio_tensor, is_speech=True)

        assert result.replay_probability >= 0.55, f"Expected high replay probability, got {result.replay_probability}"
        assert result.liveness_score <= 0.48, f"Expected degraded liveness for speaker playback, got {result.liveness_score}"
        assert result.channel_distortion_score >= 0.50

    def test_recorded_audio(self, liveness_analyzer):
        """
        3. Recorded Audio Test:
        Simulates pre-recorded playback featuring secondary room reverberation tails
        (double reverberation: recording room + playback room reflection peaks).
        Expectation: Elevated reverberation evidence and increased replay probability.
        """
        base_audio = create_formant_speech(duration_s=WINDOW_DURATION_S, f0=130.0)

        # Synthesize double room impulse response (reflections at 18ms, 42ms, 85ms)
        rir = np.zeros(int(SAMPLE_RATE * 0.12), dtype=np.float32)
        rir[0] = 1.0
        rir[int(0.018 * SAMPLE_RATE)] = 0.55
        rir[int(0.042 * SAMPLE_RATE)] = 0.40
        rir[int(0.085 * SAMPLE_RATE)] = 0.25

        reverbed = scipy.signal.fftconvolve(base_audio, rir)[: len(base_audio)]
        reverbed = reverbed / (np.max(np.abs(reverbed)) + 1e-9) * 0.90

        audio_tensor = torch.from_numpy(reverbed.astype(np.float32))

        result = liveness_analyzer.evaluate(audio_window=audio_tensor, is_speech=True)

        assert result.signals["reverberation_evidence"] >= 0.40, (
            f"Expected elevated reverberation evidence, got {result.signals['reverberation_evidence']}"
        )
        assert result.replay_probability >= 0.45

    def test_synthetic_speech(self, liveness_analyzer):
        """
        4. Synthetic Speech Test:
        Simulates synthetic TTS characteristics:
        - Rigid, perfectly periodic glottal train with zero micro-pitch jitter
        - Artificially uniform pause intervals (entropy = 0)
        - Robotic monotone cadence.
        Expectation: Synthetic speech marker is flagged; liveness score is suppressed.
        """
        t = np.linspace(0, WINDOW_DURATION_S, WINDOW_SAMPLES, endpoint=False)

        # Monotone periodic wave without natural neuromuscular jitter
        f0 = 150.0
        synth_audio = 0.8 * np.sin(2 * np.pi * f0 * t)

        audio_tensor = torch.from_numpy(synth_audio.astype(np.float32))

        result = liveness_analyzer.evaluate(audio_window=audio_tensor, is_speech=True)

        # Synthetic marker should reflect low jitter / phase uniformity
        assert result.signals["synthetic_marker"] >= 0.40, (
            f"Expected synthetic speech marker >= 0.40, got {result.signals['synthetic_marker']}"
        )
        assert result.liveness_score <= 0.55

    def test_noisy_audio(self, liveness_analyzer):
        """
        5. Noisy Audio Test:
        Evaluates degraded audio with low Signal-to-Noise Ratio (heavy additive Gaussian noise).
        Expectation: Confidence score drops significantly (e.g. <= 0.65), reflecting
        epistemic and aleatoric uncertainty rather than falsely confident decisions.
        """
        clean_speech = create_formant_speech(duration_s=WINDOW_DURATION_S, f0=120.0)

        # Add heavy noise (SNR approx 3-5 dB)
        noise = np.random.normal(0.0, 0.25, size=clean_speech.shape).astype(np.float32)
        noisy_audio = clean_speech * 0.3 + noise

        audio_tensor = torch.from_numpy(noisy_audio.astype(np.float32))

        result = liveness_analyzer.evaluate(audio_window=audio_tensor, is_speech=True)

        assert result.confidence <= 0.65, (
            f"Expected degraded confidence for noisy audio, got {result.confidence}"
        )
        assert result.signals["snr_db"] < 15.0

    def test_timeline_visualization(self, liveness_analyzer):
        """
        6. Timeline Visualization Test:
        Feeds sequential frames over time, checks rolling time-series points,
        and ensures valid vector SVG rendering with curves, markers, and axes.
        """
        liveness_analyzer.reset()

        # Simulate 6 sequential evaluation frames
        for step in range(6):
            t_offset = step * 0.5
            is_pause = (step == 2 or step == 3)

            if is_pause:
                frame = np.random.normal(0.0, 0.005, size=WINDOW_SAMPLES).astype(np.float32)
                is_sp = False
            else:
                frame = create_formant_speech(duration_s=WINDOW_DURATION_S, f0=130.0 + step * 5)
                is_sp = True

            tensor = torch.from_numpy(frame)
            liveness_analyzer.evaluate(
                audio_window=tensor,
                is_speech=is_sp,
                timestamp_s=t_offset,
            )

        timeline_data = liveness_analyzer.get_timeline_data()
        assert len(timeline_data) == 6, f"Expected 6 timeline records, got {len(timeline_data)}"

        # Verify timeline data fields
        first_point = timeline_data[0]
        assert "timestamp_s" in first_point
        assert "liveness_score" in first_point
        assert "replay_probability" in first_point
        assert "confidence" in first_point
        assert "is_speech" in first_point
        assert "pause_detected" in first_point

        # Verify SVG generation
        svg = liveness_analyzer.get_timeline_visualization_svg(width=800, height=240)
        assert svg.startswith("<svg"), "Output must be valid SVG element"
        assert "</svg>" in svg
        assert 'stroke="#10B981"' in svg  # Liveness path stroke
        assert 'stroke="#EF4444"' in svg  # Replay path stroke
        assert "Liveness Score" in svg
        assert "Replay Probability" in svg

    def test_response_timing_and_challenge_behavior(self, liveness_analyzer):
        """
        7. Response Timing & Optional Challenge-Response Behavior:
        - Instant sub-50ms turn-taking indicates automated soundboard/bot.
        - Natural turn latency (300-800ms) indicates human conversational alignment.
        """
        speech = create_formant_speech(duration_s=WINDOW_DURATION_S)
        tensor = torch.from_numpy(speech)

        # Case A: Instant bot response (< 50ms)
        res_bot = liveness_analyzer.evaluate(
            audio_window=tensor,
            turn_taking_latency_ms=25.0,  # Robotic instant trigger
            is_speech=True,
        )
        assert res_bot.signals["turn_timing_score"] <= 0.20

        # Case B: Natural human turn-taking (450ms)
        res_human = liveness_analyzer.evaluate(
            audio_window=tensor,
            turn_taking_latency_ms=450.0,
            is_speech=True,
            timestamp_s=2.5,
            challenge_prompt_end_time_s=2.0,  # 500ms response to challenge prompt
        )
        assert res_human.signals["turn_timing_score"] >= 0.90
        assert res_human.signals.get("challenge_verified") == 1.0

    def test_disclaimer_and_no_human_presence_claim(self, liveness_analyzer):
        """
        8. Platform Mandate: Do not claim liveness proves a human is present.
        """
        speech = create_formant_speech(duration_s=WINDOW_DURATION_S)
        tensor = torch.from_numpy(speech)
        result = liveness_analyzer.evaluate(audio_window=tensor)

        # Verify disclaimer text explicitly explicitly denies human proof
        assert "does NOT prove" in result.disclaimer
        assert "human is present" in result.disclaimer

        d = result.to_dict()
        assert "liveness_score" in d
        assert "replay_probability" in d
        assert "confidence" in d
        assert 0.0 <= d["liveness_score"] <= 1.0
        assert 0.0 <= d["replay_probability"] <= 1.0
        assert 0.0 <= d["confidence"] <= 1.0
