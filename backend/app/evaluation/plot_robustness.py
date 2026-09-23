"""
VIGIL-AI Adversarial Robustness Plotter.

Visualizes defensive detector performance curves across 8 acoustic transformations:
1. Additive noise (SNR sweep)
2. Codec compression (bit depth sweep)
3. Resampling (sampling rate sweep)
4. Volume changes (gain sweep)
5. Reverberation (RT60 sweep)
6. Amplitude clipping (saturation threshold sweep)
7. Spectral perturbation (notch filter frequency sweep)
8. Time-domain perturbation (micro-dropout sweep)
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from pathlib import Path
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    matplotlib = None
    plt = None
import numpy as np

from app.evaluation.adversarial_evaluator import TransformationSummary


class RobustnessPlotter:
    """
    Plots sensitivity profiles and breakdown curves under controlled transformations.
    """

    def __init__(self, output_dir: str = "reports/plots"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._setup_style()

    def _setup_style(self):
        plt.style.use("dark_background")
        plt.rcParams.update({
            "font.family": "sans-serif",
            "font.size": 9,
            "axes.labelsize": 9,
            "axes.titlesize": 10,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "figure.titlesize": 12,
            "figure.dpi": 300,
            "savefig.dpi": 300,
            "axes.edgecolor": "#334155",
            "grid.color": "#1e293b",
            "grid.linestyle": "--",
            "grid.alpha": 0.6,
        })

    def plot_all_transformations(
        self,
        summaries: Dict[str, TransformationSummary],
        output_filename: str = "adversarial_robustness_profile.png",
    ) -> str:
        """
        Creates an 8-panel diagnostic figure visualizing degradation curves across all transformations.
        """
        fig, axes = plt.subplots(2, 4, figsize=(16, 8))
        axes_flat = axes.flatten()

        color_rob = "#06b6d4"  # Cyan for Robustness Score
        color_th = "#eab308"   # Gold for breakdown boundary

        transform_keys = [
            ("additive_noise", "Additive Noise (SNR)", "SNR (dB)", True),
            ("codec_compression", "Codec Compression", "Bit Depth (bits)", False),
            ("resampling", "Resampling Bandwidth", "Sampling Rate (Hz)", False),
            ("volume_changes", "Volume / Gain Scaling", "Gain (dB)", False),
            ("reverberation", "Reverberation (RT60)", "RT60 (ms)", False),
            ("clipping", "Amplitude Clipping", "Clip Threshold", False),
            ("spectral_perturbation", "Spectral Notch Filter", "Notch Freq (Hz)", False),
            ("time_domain_perturbation", "Time Micro-Dropouts", "Dropout Rate (%)", False),
        ]

        for i, (key, title, xlabel, invert_x) in enumerate(transform_keys):
            ax = axes_flat[i]
            if key not in summaries:
                ax.text(0.5, 0.5, f"No Data: {key}", ha="center", va="center", color="#94a3b8")
                continue

            summary = summaries[key]
            pts = summary.points
            if not pts:
                continue

            x_vals = [float(p.parameter_value) for p in pts]
            rob_scores = [p.robustness_score for p in pts]

            ax.plot(
                x_vals,
                rob_scores,
                color=color_rob,
                marker="o",
                linewidth=2.2,
                markersize=6,
                label="Robustness ($R_s$)",
            )

            # Annotate data points
            for x, r in zip(x_vals, rob_scores):
                ax.annotate(
                    f"{r:.2f}",
                    (x, r),
                    textcoords="offset points",
                    xytext=(0, 6),
                    ha="center",
                    fontsize=7,
                    color="#94a3b8",
                )

            # Baseline and Failure Thresholds
            min_x, max_x = min(x_vals), max(x_vals)
            ax.plot([min_x, max_x], [1.0, 1.0], color="#10b981", linestyle="--", linewidth=1.0, alpha=0.7, label="Clean Baseline")
            ax.plot([min_x, max_x], [0.6, 0.6], color=color_th, linestyle=":", linewidth=1.2, alpha=0.8, label="Breakdown Threshold (0.6)")

            ax.set_title(title, fontweight="bold", color="#e2e8f0", pad=6)
            ax.set_xlabel(xlabel, color="#cbd5e1")
            ax.set_ylabel("Robustness Score ($R_s$)", color=color_rob)
            ax.set_ylim([-0.05, 1.15])
            ax.grid(True)

            if invert_x:
                ax.invert_xaxis()

        fig.suptitle(
            "VIGIL-AI Anti-Spoofing Detector: Adversarial Acoustic Robustness Profile\n"
            "(Defensive Sensitivity Characterization across 8 Controlled Physical Transformations)",
            fontweight="bold",
            color="#f8fafc",
            y=0.98,
        )
        fig.subplots_adjust(top=0.88, bottom=0.08, left=0.06, right=0.95, hspace=0.35, wspace=0.35)

        out_path = self.output_dir / output_filename
        fig.savefig(out_path)
        plt.close(fig)
        return str(out_path)

    def plot_radar_summary(
        self,
        summaries: Dict[str, TransformationSummary],
        output_filename: str = "adversarial_radar_summary.png",
    ) -> str:
        """
        Plots a radar chart summarizing detector resilience across all 8 transform axes.
        """
        categories = []
        resilience_scores = []

        labels_map = {
            "additive_noise": "Additive Noise\n(0 dB)",
            "codec_compression": "Codec Comp.\n(4-bit)",
            "resampling": "Resampling\n(8 kHz)",
            "volume_changes": "Volume Gain\n(±12 dB)",
            "reverberation": "Reverberation\n(300 ms)",
            "clipping": "Hard Clipping\n(0.5 thresh)",
            "spectral_perturbation": "Spectral Notch\n(2.5 kHz)",
            "time_domain_perturbation": "Micro-Dropouts\n(10%)",
        }

        for k, label in labels_map.items():
            categories.append(label)
            if k in summaries and summaries[k].points:
                mean_rob = np.mean([p.robustness_score for p in summaries[k].points])
                resilience_scores.append(float(mean_rob))
            else:
                resilience_scores.append(1.0)

        num_vars = len(categories)
        angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
        resilience_scores += resilience_scores[:1]
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))
        ax.set_facecolor("#0f172a")

        ax.plot(angles, resilience_scores, color="#06b6d4", linewidth=2.5, linestyle="solid")
        ax.fill(angles, resilience_scores, color="#06b6d4", alpha=0.25)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, color="#e2e8f0", size=8.5)
        ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
        ax.set_yticklabels(["0.2", "0.4", "0.6", "0.8", "1.0"], color="#94a3b8", size=8)
        ax.set_ylim(0, 1.08)
        ax.grid(color="#334155", linestyle="--", alpha=0.7)

        ax.set_title(
            "VIGIL-AI Defensive Resilience Profile Across 8 Acoustic Attack Vectors\n"
            "(Mean Robustness Score $R_s = \\mathrm{Acc}_{\\mathrm{perturbed}} / \\mathrm{Acc}_{\\mathrm{clean}}$)",
            size=11,
            fontweight="bold",
            color="#f8fafc",
            pad=20,
        )

        out_path = self.output_dir / output_filename
        fig.subplots_adjust(top=0.85, bottom=0.10, left=0.10, right=0.90)
        fig.savefig(out_path)
        plt.close(fig)
        return str(out_path)
