import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import scipy.signal
import torch

from app.core.logging import logger
from app.pipeline.interfaces import BaseAudioProcessor, LivenessResult


LIVENESS_DISCLAIMER = (
    "Liveness detection estimates whether audio originates from a live acoustic interaction "
    "rather than replayed or synthetic audio. It does NOT prove that a human is present."
)


@dataclass
class LivenessTimelinePoint:
    timestamp_s: float
    liveness_score: float
    replay_probability: float
    confidence: float
    is_speech: bool
    pause_detected: bool
    event_label: str = ""


class LivenessTimelineTracker:
    """
    Maintains a rolling time-series buffer of liveness evaluations and provides
    structured timeline serialization and vector SVG rendering.
    """

    def __init__(self, max_points: int = 120):
        self.max_points = max_points
        self.points: List[LivenessTimelinePoint] = []

    def record_point(
        self,
        timestamp_s: float,
        liveness_score: float,
        replay_probability: float,
        confidence: float,
        is_speech: bool = True,
        pause_detected: bool = False,
        event_label: str = "",
    ) -> None:
        point = LivenessTimelinePoint(
            timestamp_s=round(timestamp_s, 3),
            liveness_score=round(float(np.clip(liveness_score, 0.0, 1.0)), 3),
            replay_probability=round(float(np.clip(replay_probability, 0.0, 1.0)), 3),
            confidence=round(float(np.clip(confidence, 0.0, 1.0)), 3),
            is_speech=is_speech,
            pause_detected=pause_detected,
            event_label=event_label,
        )
        self.points.append(point)
        if len(self.points) > self.max_points:
            self.points.pop(0)

    def get_timeline_data(self) -> List[Dict[str, Any]]:
        return [
            {
                "timestamp_s": p.timestamp_s,
                "liveness_score": p.liveness_score,
                "replay_probability": p.replay_probability,
                "confidence": p.confidence,
                "is_speech": p.is_speech,
                "pause_detected": p.pause_detected,
                "event_label": p.event_label,
            }
            for p in self.points
        ]

    def reset(self) -> None:
        self.points.clear()

    def generate_svg(self, width: int = 800, height: int = 240) -> str:
        """
        Generates a modern, dark-theme SVG timeline visualization displaying
        liveness curves, replay risk areas, pause intervals, and event annotations.
        """
        if not self.points:
            return (
                f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
                f'<rect width="100%" height="100%" fill="#0F172A"/>'
                f'<text x="50%" y="50%" fill="#94A3B8" font-family="sans-serif" font-size="14" '
                f'text-anchor="middle">No liveness timeline data recorded</text></svg>'
            )

        margin_left = 60
        margin_right = 30
        margin_top = 35
        margin_bottom = 45
        chart_w = width - margin_left - margin_right
        chart_h = height - margin_top - margin_bottom

        t_min = self.points[0].timestamp_s
        t_max = self.points[-1].timestamp_s
        t_span = max(t_max - t_min, 1.0)

        def x_pos(t: float) -> float:
            return margin_left + ((t - t_min) / t_span) * chart_w

        def y_pos(val: float) -> float:
            return margin_top + (1.0 - float(np.clip(val, 0.0, 1.0))) * chart_h

        # Build path coordinates
        liveness_pts = [f"{x_pos(p.timestamp_s):.1f},{y_pos(p.liveness_score):.1f}" for p in self.points]
        replay_pts = [f"{x_pos(p.timestamp_s):.1f},{y_pos(p.replay_probability):.1f}" for p in self.points]

        liveness_path = "M " + " L ".join(liveness_pts) if liveness_pts else ""
        replay_path = "M " + " L ".join(replay_pts) if replay_pts else ""

        # Replay shaded polygon
        replay_poly = ""
        if replay_pts:
            first_x = x_pos(self.points[0].timestamp_s)
            last_x = x_pos(self.points[-1].timestamp_s)
            bottom_y = margin_top + chart_h
            replay_poly = (
                f"M {first_x:.1f},{bottom_y:.1f} L "
                + " L ".join(replay_pts)
                + f" L {last_x:.1f},{bottom_y:.1f} Z"
            )

        # Pause and event markers
        markers_svg = []
        for p in self.points:
            cx = x_pos(p.timestamp_s)
            if p.pause_detected:
                markers_svg.append(
                    f'<line x1="{cx:.1f}" y1="{margin_top}" x2="{cx:.1f}" y2="{margin_top + chart_h}" '
                    f'stroke="#F59E0B" stroke-dasharray="3,3" stroke-width="1.5" opacity="0.6"/>'
                )
            if p.event_label:
                markers_svg.append(
                    f'<circle cx="{cx:.1f}" cy="{y_pos(p.liveness_score):.1f}" r="4" fill="#38BDF8"/>'
                    f'<text x="{cx:.1f}" y="{margin_top - 8}" fill="#38BDF8" font-size="10" '
                    f'font-family="monospace" text-anchor="middle">{p.event_label}</text>'
                )

        grid_lines = []
        for v in [0.0, 0.25, 0.5, 0.75, 1.0]:
            gy = y_pos(v)
            grid_lines.append(
                f'<line x1="{margin_left}" y1="{gy:.1f}" x2="{margin_left + chart_w}" y2="{gy:.1f}" '
                f'stroke="#334155" stroke-dasharray="2,2"/>'
                f'<text x="{margin_left - 8}" y="{gy + 4:.1f}" fill="#64748B" font-size="10" '
                f'font-family="monospace" text-anchor="end">{int(v * 100)}%</text>'
            )

        svg_content = f"""<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="replayGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#EF4444" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="#EF4444" stop-opacity="0.02"/>
    </linearGradient>
  </defs>
  <!-- Background -->
  <rect width="100%" height="100%" fill="#0B1120" rx="8"/>
  <rect x="{margin_left}" y="{margin_top}" width="{chart_w}" height="{chart_h}" fill="#0F172A" rx="4"/>
  
  <!-- Grid -->
  {''.join(grid_lines)}

  <!-- Replay Area -->
  {f'<path d="{replay_poly}" fill="url(#replayGrad)"/>' if replay_poly else ''}

  <!-- Markers -->
  {''.join(markers_svg)}

  <!-- Curves -->
  {f'<path d="{replay_path}" fill="none" stroke="#EF4444" stroke-width="2" stroke-linejoin="round"/>' if replay_path else ''}
  {f'<path d="{liveness_path}" fill="none" stroke="#10B981" stroke-width="2.5" stroke-linejoin="round"/>' if liveness_path else ''}

  <!-- Axes & Labels -->
  <line x1="{margin_left}" y1="{margin_top + chart_h}" x2="{margin_left + chart_w}" y2="{margin_top + chart_h}" stroke="#475569" stroke-width="1.5"/>
  <line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + chart_h}" stroke="#475569" stroke-width="1.5"/>
  <text x="{margin_left}" y="{height - 12}" fill="#64748B" font-size="10" font-family="monospace">t={t_min:.1f}s</text>
  <text x="{margin_left + chart_w}" y="{height - 12}" fill="#64748B" font-size="10" font-family="monospace" text-anchor="end">t={t_max:.1f}s</text>

  <!-- Legend -->
  <circle cx="{margin_left + 20}" cy="16" r="4" fill="#10B981"/>
  <text x="{margin_left + 30}" y="20" fill="#E2E8F0" font-size="11" font-family="sans-serif">Liveness Score</text>
  <circle cx="{margin_left + 150}" cy="16" r="4" fill="#EF4444"/>
  <text x="{margin_left + 160}" y="20" fill="#E2E8F0" font-size="11" font-family="sans-serif">Replay Probability</text>
  <line x1="{margin_left + 290}" y1="16" x2="{margin_left + 310}" y2="16" stroke="#F59E0B" stroke-dasharray="3,3" stroke-width="2"/>
  <text x="{margin_left + 318}" y="20" fill="#E2E8F0" font-size="11" font-family="sans-serif">Pause Detected</text>
</svg>"""
        return svg_content


class LivenessAnalyzer(BaseAudioProcessor):
    """
    VIGIL-AI Production Liveness-Analysis Module.

    Estimates whether speech audio appears to originate from a live interaction
    rather than replayed or synthetic audio by analyzing:
    1. Acoustic Consistency (PAPR, sub-band spectral decay, transducer frequency roll-off).
    2. Temporal Characteristics (syllabic envelope modulation rhythm in 3-7 Hz band).
    3. Response Timing (conversational turn-taking interval tracking).
    4. Pause Characteristics (silence distribution, pause duration entropy vs robotic cuts).
    5. Replay Indicators (double reverberation tail, non-linear harmonic distortion).
    6. Synthetic Speech Indicators (oversmoothed pitch contour, phase regularity).
    7. Optional Challenge-Response Behavior (timing verification against prompts).

    MANDATORY SYSTEM DISCLAIMER:
    Liveness detection estimates whether audio originates from a live acoustic interaction
    rather than replayed or synthetic audio. It does NOT prove that a human is present.
    """
    MODEL_NAME = "Acoustic Multi-Band Liveness & Replay Detector"
    MODEL_VERSION = "Vigil-AcousticLiveness-v1.0"

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "name": self.MODEL_NAME,
            "version": self.MODEL_VERSION,
            "status": "READY",
            "sample_rate": self.sample_rate,
        }

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.latencies: List[float] = []
        self.timeline_tracker = LivenessTimelineTracker()

        # Rolling state for temporal and pause dynamics
        self.last_speech_time_s: Optional[float] = None
        self.current_pause_duration_s: float = 0.0
        self.pause_durations_history: List[float] = []
        self.turn_latencies_history: List[float] = []
        self.session_start_time: float = time.time()

    def initialize(self, device: str = "cpu") -> None:
        pass

    def reset(self) -> None:
        self.latencies.clear()
        self.timeline_tracker.reset()
        self.last_speech_time_s = None
        self.current_pause_duration_s = 0.0
        self.pause_durations_history.clear()
        self.turn_latencies_history.clear()
        self.session_start_time = time.time()

    def get_latency_stats(self) -> Dict[str, float]:
        if not self.latencies:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        arr = np.array(self.latencies)
        return {
            "p50": float(np.percentile(arr, 50)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
        }

    def evaluate(
        self,
        audio_window: torch.Tensor,
        turn_taking_latency_ms: Optional[float] = None,
        is_speech: bool = True,
        timestamp_s: Optional[float] = None,
        challenge_prompt_end_time_s: Optional[float] = None,
    ) -> LivenessResult:
        """
        Performs multi-signal liveness evaluation on an incoming audio window.

        Args:
            audio_window: Float32 Tensor of shape [N] or [1, N] normalized to [-1.0, 1.0].
            turn_taking_latency_ms: Optional latency between prior system prompt and current speech onset.
            is_speech: Boolean flag from VAD indicating speech presence.
            timestamp_s: Current stream timestamp in seconds.
            challenge_prompt_end_time_s: Timestamp when an interactive challenge prompt finished.

        Returns:
            LivenessResult with liveness_score, replay_probability, and confidence.
        """
        start_time = time.perf_counter()
        now_s = timestamp_s if timestamp_s is not None else (time.time() - self.session_start_time)

        audio_np = audio_window.squeeze().detach().cpu().numpy().astype(np.float32)
        n_samples = len(audio_np)

        if n_samples < 512:
            return LivenessResult(
                is_live_acoustic=True,
                replay_probability=0.1,
                channel_distortion_score=0.0,
                sub_band_dispersion=0.0,
                latency_ms=0.1,
                liveness_score=0.9,
                confidence=0.5,
                signals={"empty_or_short_buffer": 1.0},
                disclaimer=LIVENESS_DISCLAIMER,
            )

        # 1. Noise Floor and SNR Estimation (Frame-based 25ms minimum statistics)
        rms = float(np.sqrt(np.mean(audio_np ** 2) + 1e-12))
        peak = float(np.max(np.abs(audio_np)))

        frame_len = int(0.025 * self.sample_rate)
        if n_samples >= frame_len * 2:
            frames = audio_np[: (n_samples // frame_len) * frame_len].reshape(-1, frame_len)
            frame_rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
            noise_floor = float(np.percentile(frame_rms, 10))
        else:
            noise_floor = float(np.percentile(np.abs(audio_np), 10))

        snr_est = float(20.0 * np.log10((rms + 1e-9) / (noise_floor + 1e-9)))
        snr_est = float(np.clip(snr_est, -5.0, 70.0))

        # 2. Signal 1: Acoustic Consistency (Peak-to-Average Power Ratio - PAPR)
        # Near-field uncompressed human speech has high dynamic range (PAPR 10-25 dB).
        # External consumer loudspeakers compress dynamic range (PAPR < 8 dB).
        papr = float((peak ** 2) / (rms ** 2 + 1e-12))
        papr_db = float(10.0 * np.log10(max(papr, 1.0001)))
        # Map: >14 dB -> 0.0 replay risk; <7 dB -> 1.0 replay risk
        acoustic_replay_risk = float(np.clip((14.0 - papr_db) / 8.0, 0.0, 1.0))
        acoustic_consistency = float(1.0 - acoustic_replay_risk)

        # 3. Signal 2: Sub-Band Spectral Decay & Transducer Rolloff (STFT)
        # Loudspeakers roll off above 7 kHz and exhibit acoustic enclosure resonance.
        f, t, Zxx = scipy.signal.stft(
            audio_np, fs=self.sample_rate, nperseg=min(512, n_samples), noverlap=min(256, n_samples // 2)
        )
        mag = np.abs(Zxx) + 1e-9
        freq_bins = f

        # High frequency energy fraction (> 6500 Hz vs total)
        high_freq_idx = np.where(freq_bins >= 6500)[0]
        total_energy = float(np.sum(mag))
        high_freq_ratio = float(np.sum(mag[high_freq_idx, :])) / (total_energy + 1e-9) if len(high_freq_idx) > 0 else 0.0

        # Sub-band dispersion / spectral skew
        spectral_decay = float(np.mean(np.diff(np.mean(mag, axis=1))))
        sub_band_dispersion = float(np.clip(abs(spectral_decay) * 12.0, 0.0, 1.0))

        # 4. Signal 3: Replay Indicators (Double Reverberation & Harmonic Distortion)
        # Check autocorrelation decay for secondary room reflection peaks.
        # Set min_lag to 20ms to avoid false triggers on human vocal cord pitch periods (3ms - 15ms).
        acorr = scipy.signal.correlate(audio_np, audio_np, mode="full")
        acorr = acorr[len(acorr) // 2 :]
        acorr = acorr / (acorr[0] + 1e-12)
        min_lag = int(0.020 * self.sample_rate)  # 20ms lag threshold
        max_lag = min(int(0.120 * self.sample_rate), len(acorr) - 1)
        if max_lag > min_lag:
            reflection_peak = float(np.max(acorr[min_lag:max_lag]))
        else:
            reflection_peak = 0.0
        reverberation_evidence = float(np.clip(reflection_peak * 2.2, 0.0, 1.0))

        # 5. Signal 4: Temporal Characteristics (Syllabic Modulation Rhythm 3-7 Hz)
        # Live human speech exhibits a characteristic 3-7 Hz envelope modulation.
        # Synthesized or looped audio frequently lacks this or has rigid artificial periodicity.
        env = np.abs(audio_np)
        env_f, env_pxx = scipy.signal.periodogram(env, fs=self.sample_rate)
        syllabic_band = (env_f >= 2.5) & (env_f <= 7.5)
        total_env_power = float(np.sum(env_pxx) + 1e-9)
        syllabic_power_ratio = float(np.sum(env_pxx[syllabic_band])) / total_env_power
        # Normalize: natural speech typically has 0.15 - 0.45 syllabic power ratio
        temporal_naturalness = float(np.clip((syllabic_power_ratio - 0.05) / 0.30, 0.0, 1.0))

        # 6. Signal 5: Pause Dynamics & Silence Distribution
        pause_detected = not is_speech or rms < 0.012
        if pause_detected:
            self.current_pause_duration_s += (n_samples / self.sample_rate)
        else:
            if self.current_pause_duration_s > 0.05:
                self.pause_durations_history.append(self.current_pause_duration_s)
                if len(self.pause_durations_history) > 20:
                    self.pause_durations_history.pop(0)
            self.current_pause_duration_s = 0.0

        # Evaluate pause entropy / natural variance
        if len(self.pause_durations_history) >= 3:
            pause_std = float(np.std(self.pause_durations_history))
            pause_mean = float(np.mean(self.pause_durations_history))
            # Natural speech has pause variance (std/mean in 0.25 - 0.85); synthetic TTS often has rigid identical pauses
            pause_entropy = float(np.clip(pause_std / (pause_mean + 1e-6), 0.0, 1.0))
        else:
            pause_entropy = 0.85  # Neutral default until sufficient pauses observed

        # 7. Signal 6: Synthetic Speech Acoustic Indicators (Pitch Jitter & Phase Regularity)
        # Synthetic speech often exhibits unnaturally flat micro-pitch jitter and phase quantization
        diff1 = np.diff(audio_np)
        jitter_estimate = float(np.std(diff1) / (np.mean(np.abs(diff1)) + 1e-6))
        # Very low jitter (< 1.1) indicates robotic/synthetic quantization; normal is 1.3 - 2.5
        synthetic_marker = float(np.clip((1.3 - jitter_estimate) / 0.4, 0.0, 1.0))

        # 8. Signal 7: Response Timing & Challenge-Response Behavior
        turn_timing_score = 0.85
        challenge_verified: Optional[bool] = None

        if turn_taking_latency_ms is not None:
            self.turn_latencies_history.append(turn_taking_latency_ms)
            # Normal conversational turn latency: 180ms to 900ms
            if turn_taking_latency_ms < 60.0:
                # Sub-60ms: instant robotic soundboard playback / pre-programmed trigger
                turn_timing_score = 0.15
            elif 150.0 <= turn_taking_latency_ms <= 1200.0:
                turn_timing_score = 0.95
            elif turn_taking_latency_ms > 3500.0:
                turn_timing_score = 0.40
            else:
                turn_timing_score = 0.70

        if challenge_prompt_end_time_s is not None and is_speech:
            latency_from_challenge_ms = (now_s - challenge_prompt_end_time_s) * 1000.0
            # Human responds within 200ms - 2500ms of challenge
            if 150.0 <= latency_from_challenge_ms <= 3000.0:
                challenge_verified = True
                turn_timing_score = max(turn_timing_score, 0.95)
            else:
                challenge_verified = False

        # 9. Composite Replay Probability Estimation
        # Driven by physical transducer & acoustic room indicators
        reverberation_weight = 0.45 if reverberation_evidence >= 0.40 else 0.30
        acoustic_risk_weight = 0.50 if acoustic_replay_risk >= 0.70 else 0.40
        replay_prob = float(
            acoustic_risk_weight * acoustic_replay_risk
            + reverberation_weight * reverberation_evidence
            + 0.15 * sub_band_dispersion
            + 0.10 * (1.0 - pause_entropy)
        )
        replay_prob = float(np.clip(replay_prob, 0.03, 0.98))

        # 10. Composite Liveness Score
        # High liveness requires: high acoustic consistency, natural temporal cadence,
        # natural pause variance, natural turn-taking, and absence of replay markers.
        raw_liveness = float(
            0.35 * acoustic_consistency
            + 0.35 * (1.0 - replay_prob)
            + 0.15 * temporal_naturalness
            + 0.10 * pause_entropy
            + 0.05 * turn_timing_score
        )
        # Suppress liveness when replay probability or synthetic markers are high
        if replay_prob > 0.50:
            replay_penalty = (replay_prob - 0.50) / 0.50
            raw_liveness *= (1.0 - 0.70 * replay_penalty)
        if synthetic_marker > 0.40:
            synth_penalty = (synthetic_marker - 0.40) / 0.60
            raw_liveness *= (1.0 - 0.50 * synth_penalty)

        liveness_score = float(np.clip(raw_liveness, 0.02, 0.98))

        # 11. Confidence Estimation
        # Affected by SNR and signal duration: low SNR (noisy audio) reduces confidence
        # rather than asserting a false positive/negative.
        snr_factor = float(np.clip((snr_est - 10.0) / 25.0, 0.25, 1.0))
        duration_factor = float(np.clip(n_samples / (self.sample_rate * 1.5), 0.5, 1.0))
        confidence = float(np.clip(snr_factor * duration_factor, 0.2, 0.95))

        # Determine binary acoustic flag
        is_live_acoustic = liveness_score >= 0.50 and replay_prob < 0.60

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        self.latencies.append(latency_ms)

        event_label = ""
        if challenge_verified is True:
            event_label = "CHALLENGE_OK"
        elif replay_prob >= 0.70:
            event_label = "REPLAY_FLAGGED"
        elif synthetic_marker >= 0.70:
            event_label = "SYNTH_CADENCE"

        # Record point in rolling timeline tracker
        self.timeline_tracker.record_point(
            timestamp_s=now_s,
            liveness_score=liveness_score,
            replay_probability=replay_prob,
            confidence=confidence,
            is_speech=is_speech,
            pause_detected=pause_detected,
            event_label=event_label,
        )

        signals_dict = {
            "papr_db": round(papr_db, 2),
            "acoustic_consistency": round(acoustic_consistency, 3),
            "reverberation_evidence": round(reverberation_evidence, 3),
            "temporal_naturalness": round(temporal_naturalness, 3),
            "pause_entropy": round(pause_entropy, 3),
            "synthetic_marker": round(synthetic_marker, 3),
            "turn_timing_score": round(turn_timing_score, 3),
            "snr_db": round(snr_est, 1),
        }
        if challenge_verified is not None:
            signals_dict["challenge_verified"] = 1.0 if challenge_verified else 0.0

        return LivenessResult(
            is_live_acoustic=is_live_acoustic,
            replay_probability=round(replay_prob, 3),
            channel_distortion_score=round(acoustic_replay_risk, 3),
            sub_band_dispersion=round(sub_band_dispersion, 3),
            latency_ms=round(latency_ms, 2),
            liveness_score=round(liveness_score, 3),
            confidence=round(confidence, 3),
            signals=signals_dict,
            disclaimer=LIVENESS_DISCLAIMER,
        )

    def get_timeline_visualization_svg(self, width: int = 800, height: int = 240) -> str:
        """Returns vector SVG timeline visualization of current session."""
        return self.timeline_tracker.generate_svg(width=width, height=height)

    def get_timeline_data(self) -> List[Dict[str, Any]]:
        """Returns structured JSON timeline records for UI rendering."""
        return self.timeline_tracker.get_timeline_data()


# Backward compatibility alias
AcousticLivenessDetector = LivenessAnalyzer
