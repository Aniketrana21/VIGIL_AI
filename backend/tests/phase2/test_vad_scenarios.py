import os
import wave
import numpy as np
import pytest
from app.pipeline.silero_vad import SileroModelRegistry, SileroStreamingVAD
from app.pipeline.vad_interface import VADDecision


def load_speech_sample() -> np.ndarray:
    """Loads a genuine 16kHz speech sample fixture."""
    fixture_path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "speech_sample.wav")
    with wave.open(fixture_path, "rb") as wf:
        n = wf.getnframes()
        raw = wf.readframes(n)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return samples


def generate_silence_audio(duration_sec: float = 1.0, sample_rate: int = 16000, digital: bool = True) -> np.ndarray:
    """Synthesizes digital zeros or low-level ambient quiet (-65 dBFS)."""
    n_samples = int(duration_sec * sample_rate)
    if digital:
        return np.zeros(n_samples, dtype=np.float32)
    # Extremely low ambient floor (~ -65 dBFS)
    return np.random.normal(0, 0.0005, n_samples).astype(np.float32)


def generate_background_noise(duration_sec: float = 1.0, sample_rate: int = 16000) -> np.ndarray:
    """Synthesizes stationary white/Gaussian ambient background noise."""
    n_samples = int(duration_sec * sample_rate)
    noise = np.random.normal(0, 0.05, n_samples).astype(np.float32)
    return np.clip(noise, -0.2, 0.2)


def generate_music_audio(duration_sec: float = 1.0, sample_rate: int = 16000) -> np.ndarray:
    """
    Synthesizes musical polyphonic chord (A major triad: 440Hz, 554.37Hz, 659.25Hz)
    without human speech formant characteristics.
    """
    n_samples = int(duration_sec * sample_rate)
    t = np.linspace(0, duration_sec, n_samples, endpoint=False)
    chord = (
        0.33 * np.sin(2 * np.pi * 440.0 * t) +
        0.33 * np.sin(2 * np.pi * 554.37 * t) +
        0.33 * np.sin(2 * np.pi * 659.25 * t)
    )
    return chord.astype(np.float32)


def generate_mixed_speech_noise(snr_db: float = 15.0) -> np.ndarray:
    """Blends genuine speech audio with additive background noise at a specific SNR."""
    speech = load_speech_sample()
    duration_sec = len(speech) / 16000.0
    noise = generate_background_noise(duration_sec, 16000)
    
    speech_power = np.mean(speech ** 2)
    noise_power = np.mean(noise ** 2)
    target_noise_power = speech_power / (10.0 ** (snr_db / 10.0))
    noise_scaled = noise * np.sqrt(target_noise_power / (noise_power + 1e-12))
    
    mixed = speech + noise_scaled
    mixed = mixed / (np.max(np.abs(mixed)) + 1e-6) * 0.8
    return mixed.astype(np.float32)


class TestPhase2VADScenarios:
    """Comprehensive test matrix for Phase 2 Voice Activity Detection."""

    @pytest.fixture(autouse=True)
    def setup_vad(self):
        self.vad = SileroStreamingVAD(
            speech_threshold=0.50,
            min_speech_duration_ms=200,
            min_silence_duration_ms=250,
            speech_pad_ms=150,
            sample_rate=16000,
        )
        self.vad.reset()

    def test_singleton_model_reuse(self):
        """Requirement 4: Do not create a new model for every audio chunk."""
        model1, core1 = SileroModelRegistry.get_model()
        model2, core2 = SileroModelRegistry.get_model()
        assert model1 is model2
        assert core1 is core2

        vad_a = SileroStreamingVAD()
        vad_b = SileroStreamingVAD()
        assert vad_a.core_model is vad_b.core_model

    def test_scenario_speech(self):
        """Scenario 1: Speech audio is detected as speech with high probability."""
        speech = load_speech_sample()
        # Feed in streaming 100ms chunks (1600 samples)
        chunk_size = 1600
        decisions = []
        for i in range(0, len(speech), chunk_size):
            chunk = speech[i : i + chunk_size]
            d = self.vad.is_speech(chunk)
            decisions.append(d)

        speech_detected = any(d.is_speech for d in decisions)
        max_prob = max(d.speech_probability for d in decisions)
        assert speech_detected, "Speech audio was not detected as speech"
        assert max_prob >= 0.85, f"Speech probability {max_prob} was unexpectedly low for genuine speech"

    def test_scenario_silence(self):
        """Scenario 2: Digital and low ambient silence are classified as non-speech."""
        # Digital silence
        silence_digital = generate_silence_audio(duration_sec=1.0, digital=True)
        res_dig = self.vad.is_speech(silence_digital)
        assert res_dig.is_speech is False
        assert res_dig.speech_probability < 0.20

        # Ambient low-level quiet
        silence_ambient = generate_silence_audio(duration_sec=1.0, digital=False)
        res_amb = self.vad.is_speech(silence_ambient)
        assert res_amb.is_speech is False
        assert res_amb.speech_probability < 0.20

    def test_scenario_background_noise(self):
        """Scenario 3: Stationary background noise alone is not identified as speech."""
        noise = generate_background_noise(duration_sec=1.0)
        chunk_size = 1600
        speech_flags = []
        for i in range(0, len(noise), chunk_size):
            chunk = noise[i : i + chunk_size]
            d = self.vad.is_speech(chunk)
            speech_flags.append(d.is_speech)

        # White/Gaussian noise should not trigger sustained speech
        assert sum(speech_flags) == 0, f"Background noise triggered speech: {speech_flags}"

    def test_scenario_music(self):
        """Scenario 4: Polyphonic music triad does not trigger speech."""
        music = generate_music_audio(duration_sec=1.0)
        res = self.vad.is_speech(music)
        # Non-vocal chords have distinct spectral characteristics from human phonation
        assert res.speech_probability < 0.45

    def test_scenario_mixed_speech_and_noise(self):
        """Scenario 5: Speech embedded in noise is reliably detected."""
        mixed = generate_mixed_speech_noise(snr_db=15.0)
        chunk_size = 1600
        speech_detected = False
        max_prob = 0.0
        for i in range(0, len(mixed), chunk_size):
            chunk = mixed[i : i + chunk_size]
            d = self.vad.is_speech(chunk)
            if d.speech_probability > max_prob:
                max_prob = d.speech_probability
            if d.is_speech:
                speech_detected = True

        assert speech_detected, f"Speech was missed in noisy environment (+15dB SNR, max_prob={max_prob})"

    def test_context_padding_and_state_tracking(self):
        """Requirements 2 & 5: Preserves pre-speech and post-speech context and maintains state."""
        # Feed 0.5s silence -> 1.0s speech -> 1.0s silence
        silence1 = generate_silence_audio(0.5)
        speech = load_speech_sample()[:16000]  # 1.0s
        silence2 = generate_silence_audio(1.0)

        stream = np.concatenate((silence1, speech, silence2))
        chunk_size = 1600  # 100ms
        results = []

        for i in range(0, len(stream), chunk_size):
            chunk = stream[i : i + chunk_size]
            d = self.vad.is_speech(chunk)
            results.append(d)

        # Check that start_time and end_time timestamps were captured
        speech_results = [r for r in results if r.is_speech and r.start_time is not None]
        assert len(speech_results) > 0, "No speech segment timestamp recorded"
        first_speech = speech_results[0]
        assert first_speech.start_time is not None

        # Output schema check
        schema_dict = first_speech.to_dict()
        assert "is_speech" in schema_dict
        assert "speech_probability" in schema_dict
        assert "start_time" in schema_dict
        assert "end_time" in schema_dict
        assert isinstance(schema_dict["is_speech"], bool)
        assert isinstance(schema_dict["speech_probability"], float)

    def test_vad_latency_measurement(self):
        """Requirement 9: Real-time latency measurement."""
        chunk = load_speech_sample()[:1600]  # 100ms
        for _ in range(5):
            self.vad.is_speech(chunk)

        stats = self.vad.get_latency_stats()
        assert "p50" in stats
        assert "p95" in stats
        assert stats["p50"] > 0.0
        # Neural VAD on 100ms CPU audio should easily finish in under 20ms
        assert stats["p95"] < 25.0, f"VAD latency {stats['p95']}ms exceeded budget"
