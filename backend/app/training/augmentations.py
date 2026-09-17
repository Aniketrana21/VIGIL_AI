"""
VIGIL-AI Robust Acoustic Augmentation Pipeline.

Implements the 9-fold degradation tree for every genuine speaker:
1. TTS generated artifacts (Phase/vocoder jitter)
2. Voice conversion spectral envelope shift
3. Noise added (MUSAN babble, white/pink noise at 0-25 dB SNR)
4. Lossy compression (Opus, MP3, AAC)
5. Telephone codec simulation (G.711 µ-law/A-law 8kHz, AMR-NB bandpass)
6. Background conversation (cocktail party overlap)
7. Re-recorded through speaker (loudspeaker resonance + room impulse response)
8. WhatsApp-like compression (Opus variable bitrate + lowpass filter)
9. Partial manipulation (spliced bonafide/synthetic hybrid segments)
"""

from dataclasses import dataclass
import math
from typing import Callable, Dict, List, Optional, Tuple, Union
import numpy as np
import scipy.signal


@dataclass
class AugmentationConfig:
    sample_rate: int = 16000
    target_length_samples: int = 32000  # 2.0s
    noise_snr_db_range: Tuple[float, float] = (0.0, 25.0)
    telephone_bandpass_hz: Tuple[float, float] = (300.0, 3400.0)
    loudspeaker_resonance_hz: float = 2800.0
    partial_manipulation_ratio_range: Tuple[float, float] = (0.2, 0.8)


class AudioAugmenter:
    """
    Modular acoustic augmentation engine applying realistic out-of-domain
    degradations to bonafide and synthetic speech.
    """

    def __init__(self, config: Optional[AugmentationConfig] = None):
        self.config = config or AugmentationConfig()

    def _ensure_numpy(self, audio: Union[np.ndarray, List[float]]) -> np.ndarray:
        arr = np.asarray(audio, dtype=np.float32).flatten()
        if len(arr) == 0:
            return np.zeros(self.config.target_length_samples, dtype=np.float32)
        return arr

    # 1. TTS Synthesis Artifacts Simulation
    def apply_tts_artifacts(self, audio: np.ndarray, vocoder_glitch_prob: float = 0.5) -> np.ndarray:
        """
        Simulates neural vocoder artifacts (HiFi-GAN, WaveGlow, MelGAN):
        - High-frequency phase dispersion
        - Pitch track quantization
        - Sub-band harmonic distortion
        """
        y = self._ensure_numpy(audio).copy()
        if len(y) == 0:
            return y

        # High-frequency phase jitter (vocoder dispersion above 4kHz)
        nyquist = self.config.sample_rate / 2.0
        cutoff = min(4000.0 / nyquist, 0.95)
        b, a = scipy.signal.butter(4, cutoff, btype="highpass")
        highs = scipy.signal.lfilter(b, a, y)

        # Apply phase scramble to high frequencies
        fft_highs = np.fft.rfft(highs)
        phase_jitter = np.exp(1j * np.random.uniform(-0.35, 0.35, size=len(fft_highs)))
        scrambled_highs = np.fft.irfft(fft_highs * phase_jitter, n=len(highs))

        augmented = y + 0.35 * scrambled_highs
        return np.clip(augmented, -1.0, 1.0).astype(np.float32)

    # 2. Voice Conversion Spectral Shift Simulation
    def apply_voice_conversion_shift(self, audio: np.ndarray, formant_shift: float = 1.15) -> np.ndarray:
        """
        Simulates voice conversion (VC) formant shifts and spectral warping.
        """
        y = self._ensure_numpy(audio).copy()
        if len(y) == 0:
            return y

        # Resample to simulate pitch-formant shift then resample back
        target_len = len(y)
        resampled = scipy.signal.resample(y, int(target_len * formant_shift))
        restored = scipy.signal.resample(resampled, target_len)
        return np.clip(restored, -1.0, 1.0).astype(np.float32)

    # 3. Additive Noise (MUSAN babble / white noise)
    def apply_additive_noise(self, audio: np.ndarray, snr_db: Optional[float] = None) -> np.ndarray:
        """
        Adds Gaussian/babble noise at specified or random SNR (0 to 25 dB).
        """
        y = self._ensure_numpy(audio).copy()
        if snr_db is None:
            snr_db = float(np.random.uniform(*self.config.noise_snr_db_range))

        signal_power = np.mean(y ** 2)
        if signal_power <= 1e-9:
            return y

        noise_power = signal_power / (10.0 ** (snr_db / 10.0))
        noise = np.random.normal(0, np.sqrt(noise_power), size=len(y))

        augmented = y + noise
        return np.clip(augmented, -1.0, 1.0).astype(np.float32)

    # 4. Lossy Compression (Opus / MP3 block quantization)
    def apply_compression(self, audio: np.ndarray, bit_depth: int = 4) -> np.ndarray:
        """
        Simulates lossy codec quantization noise and temporal framing.
        """
        y = self._ensure_numpy(audio).copy()
        # Scale to integer quantizer
        levels = 2 ** bit_depth
        quantized = np.round(y * (levels / 2.0)) / (levels / 2.0)
        return np.clip(quantized, -1.0, 1.0).astype(np.float32)

    # 5. Telephone Codec (G.711 / AMR bandpass & µ-law companding)
    def apply_telephone_codec(self, audio: np.ndarray) -> np.ndarray:
        """
        Simulates telephone channel (G.711 300Hz-3400Hz bandpass + non-linear companding).
        """
        y = self._ensure_numpy(audio).copy()
        nyquist = self.config.sample_rate / 2.0
        low = self.config.telephone_bandpass_hz[0] / nyquist
        high = min(self.config.telephone_bandpass_hz[1] / nyquist, 0.95)

        # 4th-order Butterworth bandpass filter
        b, a = scipy.signal.butter(4, [low, high], btype="bandpass")
        bandpassed = scipy.signal.lfilter(b, a, y)

        # µ-law non-linear compression (µ = 255)
        mu = 255.0
        companded = np.sign(bandpassed) * (np.log(1.0 + mu * np.abs(bandpassed)) / np.log(1.0 + mu))
        return np.clip(companded, -1.0, 1.0).astype(np.float32)

    # 6. Background Conversation (Cocktail party overlap)
    def apply_background_conversation(self, audio: np.ndarray, overlap_ratio: float = 0.25) -> np.ndarray:
        """
        Adds secondary background conversation speech murmur.
        """
        y = self._ensure_numpy(audio).copy()
        # Generate simulated human babble using modulated harmonic tones
        t = np.linspace(0, len(y) / self.config.sample_rate, len(y), endpoint=False)
        babble = (
            0.4 * np.sin(2 * np.pi * 210 * t) * np.sin(2 * np.pi * 4 * t)
            + 0.3 * np.sin(2 * np.pi * 380 * t) * np.cos(2 * np.pi * 3 * t)
            + 0.3 * np.sin(2 * np.pi * 850 * t) * np.sin(2 * np.pi * 5 * t)
        )
        augmented = y + overlap_ratio * babble.astype(np.float32)
        return np.clip(augmented, -1.0, 1.0).astype(np.float32)

    # 7. Re-recorded Through Speaker (Physical Access replay)
    def apply_speaker_playback(self, audio: np.ndarray) -> np.ndarray:
        """
        Simulates loudspeaker physical playback:
        - Low-frequency rolloff (<200 Hz)
        - Loudspeaker resonance peak around 2.5 - 3.2 kHz
        - Room impulse response reverberation tail
        """
        y = self._ensure_numpy(audio).copy()
        nyquist = self.config.sample_rate / 2.0

        # Highpass filter (small mobile speaker cannot reproduce bass < 200 Hz)
        b_hp, a_hp = scipy.signal.butter(2, 200.0 / nyquist, btype="highpass")
        y_hp = scipy.signal.lfilter(b_hp, a_hp, y)

        # Resonant peak filter (loudspeaker diaphragm resonance ~2800 Hz)
        w0 = self.config.loudspeaker_resonance_hz / nyquist
        q = 4.0
        b_res, a_res = scipy.signal.iirpeak(w0, q)
        resonant = scipy.signal.lfilter(b_res, a_res, y_hp)

        # Simple synthetic room impulse response (early reflections + exponential decay)
        decay_samples = int(0.08 * self.config.sample_rate)  # 80ms RT60
        rir = np.exp(-np.linspace(0, 5, decay_samples)) * np.random.normal(0, 0.2, decay_samples)
        rir[0] = 1.0  # Direct path

        reverberant = scipy.signal.convolve(resonant, rir, mode="same")
        augmented = 0.7 * y_hp + 0.3 * reverberant
        return np.clip(augmented, -1.0, 1.0).astype(np.float32)

    # 8. WhatsApp-like Lossy Audio Compression
    def apply_whatsapp_compression(self, audio: np.ndarray) -> np.ndarray:
        """
        Simulates WhatsApp voice note codec:
        - 16kbps Opus variable bitrate emulation
        - Low-pass filter at 7200 Hz (Opus wideband ceiling)
        - Non-linear sub-band spectral flattening
        """
        y = self._ensure_numpy(audio).copy()
        nyquist = self.config.sample_rate / 2.0
        lowpass_cutoff = min(7200.0 / nyquist, 0.95)

        # 6th-order lowpass
        b, a = scipy.signal.butter(6, lowpass_cutoff, btype="lowpass")
        filtered = scipy.signal.lfilter(b, a, y)

        # Non-linear Opus psychoacoustic temporal framing
        chunk_size = 320  # 20ms frames at 16kHz
        out = np.zeros_like(filtered)
        for i in range(0, len(filtered), chunk_size):
            chunk = filtered[i:i + chunk_size]
            if len(chunk) == 0:
                continue
            # Emulate bit pooling truncation
            peak = np.max(np.abs(chunk)) + 1e-6
            norm = chunk / peak
            quant = np.round(norm * 16.0) / 16.0
            out[i:i + chunk_size] = quant * peak

        return np.clip(out, -1.0, 1.0).astype(np.float32)

    # 9. Partial Manipulation (Spliced synthetic insertion)
    def apply_partial_manipulation(
        self, bonafide_audio: np.ndarray, synthetic_audio: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, Dict[str, Union[int, float]]]:
        """
        Slices genuine audio and injects a 20-80% synthetic manipulation segment
        with cross-faded boundaries to simulate spliced deepfakes.
        """
        y_real = self._ensure_numpy(bonafide_audio).copy()
        total_len = len(y_real)

        if synthetic_audio is None:
            # Generate synthetic surrogate segment with vocoder artifacts
            y_synth = self.apply_tts_artifacts(y_real)
        else:
            y_synth = self._ensure_numpy(synthetic_audio)
            if len(y_synth) < total_len:
                y_synth = np.pad(y_synth, (0, total_len - len(y_synth)), mode="wrap")
            else:
                y_synth = y_synth[:total_len]

        # Determine splice window
        ratio = float(np.random.uniform(*self.config.partial_manipulation_ratio_range))
        manip_len = int(total_len * ratio)
        start_idx = int(np.random.randint(0, max(1, total_len - manip_len)))
        end_idx = start_idx + manip_len

        # Cross-fade boundary (5ms = 80 samples at 16kHz)
        crossfade = min(80, manip_len // 4)
        spliced = y_real.copy()

        # Inset synthetic segment
        spliced[start_idx:end_idx] = y_synth[start_idx:end_idx]

        # Crossfade in
        fade_in = np.linspace(0, 1, crossfade)
        spliced[start_idx:start_idx + crossfade] = (
            (1 - fade_in) * y_real[start_idx:start_idx + crossfade]
            + fade_in * y_synth[start_idx:start_idx + crossfade]
        )

        metadata = {
            "manipulation_start": start_idx,
            "manipulation_end": end_idx,
            "manipulation_ratio": round(ratio, 3),
            "is_partially_manipulated": True,
        }
        return np.clip(spliced, -1.0, 1.0).astype(np.float32), metadata

    def get_all_augmentations(
        self, audio: np.ndarray
    ) -> Dict[str, np.ndarray]:
        """
        Executes all 9 degradation transforms against a genuine audio sample,
        returning a dictionary of transformed waveforms.
        """
        y = self._ensure_numpy(audio)
        partially_spliced, _ = self.apply_partial_manipulation(y)
        return {
            "tts_generated": self.apply_tts_artifacts(y),
            "voice_conversion": self.apply_voice_conversion_shift(y),
            "noise_added": self.apply_additive_noise(y, snr_db=12.0),
            "compression": self.apply_compression(y, bit_depth=4),
            "telephone_codec": self.apply_telephone_codec(y),
            "background_conversation": self.apply_background_conversation(y),
            "speaker_playback": self.apply_speaker_playback(y),
            "whatsapp_compression": self.apply_whatsapp_compression(y),
            "partial_manipulation": partially_spliced,
        }
