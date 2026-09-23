"""
VIGIL-AI Publication-Quality Evaluation Plotter.

Generates:
1. ROC Curves (ASVspoof 5, ASVspoof 2021, In-the-Wild, IndianLangVoice)
2. Detection Error Tradeoff (DET) Curves (Normal Deviate scale)
3. Confusion Matrices (annotated heatmaps)
4. EER Comparison Bar Charts across datasets & attack families
5. Latency Distribution & Real-Time Factor (RTF)
6. Robustness under Noise (SNR) and Codec Compression
"""

import os
from pathlib import Path
try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive headless backend
    import matplotlib.pyplot as plt
except ImportError:
    matplotlib = None
    plt = None
import numpy as np
import scipy.stats
import sklearn.metrics


class ResearchPlotter:
    """
    Generates high-resolution, dark-mode cybersecurity-themed diagnostic figures.
    """

    def __init__(self, output_dir: str = "reports/plots"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._setup_style()

    def _setup_style(self):
        plt.style.use("dark_background")
        plt.rcParams.update({
            "font.family": "sans-serif",
            "font.size": 10,
            "axes.labelsize": 11,
            "axes.titlesize": 12,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "figure.titlesize": 14,
            "figure.dpi": 300,
            "savefig.dpi": 300,
            "axes.edgecolor": "#334155",
            "grid.color": "#1e293b",
            "grid.linestyle": "--",
            "grid.alpha": 0.6,
        })

    def plot_roc_curves(
        self, dataset_curves: Dict[str, Tuple[np.ndarray, np.ndarray, float]], output_filename: str = "roc_curve.png"
    ) -> str:
        """
        Plots ROC curves with AUC labels for multiple benchmark datasets.
        dataset_curves: {name: (y_true, y_scores, roc_auc)}
        """
        fig, ax = plt.subplots(figsize=(8, 6))
        colors = ["#06b6d4", "#10b981", "#a855f7", "#f59e0b", "#f43f5e"]

        for idx, (name, (y_true, y_scores, auc_val)) in enumerate(dataset_curves.items()):
            fpr, tpr, _ = sklearn.metrics.roc_curve(y_true, y_scores)
            color = colors[idx % len(colors)]
            ax.plot(fpr, tpr, label=f"{name} (AUC = {auc_val:.3f})", color=color, linewidth=2)

        ax.plot([0, 1], [0, 1], "r--", alpha=0.5, label="Chance (AUC = 0.500)")
        ax.set_xlim([-0.02, 1.02])
        ax.set_ylim([-0.02, 1.02])
        ax.set_xlabel("False Positive Rate (FAR / FPR)")
        ax.set_ylabel("True Positive Rate (Detection Recall)")
        ax.set_title("Receiver Operating Characteristic (ROC) — VIGIL-AI Benchmarks")
        ax.grid(True)
        ax.legend(loc="lower right", framealpha=0.8, edgecolor="#475569")

        out_path = self.output_dir / output_filename
        fig.tight_layout()
        fig.savefig(out_path)
        plt.close(fig)
        return str(out_path)

    def plot_det_curves(
        self, dataset_curves: Dict[str, Tuple[np.ndarray, np.ndarray]], output_filename: str = "det_curve.png"
    ) -> str:
        """
        Plots Detection Error Tradeoff (DET) curves on normal deviate (probit) scale.
        """
        fig, ax = plt.subplots(figsize=(8, 6))
        colors = ["#06b6d4", "#10b981", "#a855f7", "#f59e0b"]

        for idx, (name, (y_true, y_scores)) in enumerate(dataset_curves.items()):
            fpr, fnr, _ = sklearn.metrics.det_curve(y_true, y_scores)
            # Clip near 0 and 1 to prevent probit infinities
            fpr = np.clip(fpr, 1e-4, 1.0 - 1e-4)
            fnr = np.clip(fnr, 1e-4, 1.0 - 1e-4)

            # Probit transform (standard normal inverse CDF)
            x_probit = scipy.stats.norm.ppf(fpr)
            y_probit = scipy.stats.norm.ppf(fnr)

            color = colors[idx % len(colors)]
            ax.plot(x_probit, y_probit, label=name, color=color, linewidth=2)

        # Scale tick marks
        ticks = [0.001, 0.01, 0.05, 0.20, 0.50]
        tick_locs = scipy.stats.norm.ppf(ticks)
        tick_labels = [f"{t * 100:.1f}%" for t in ticks]

        ax.set_xticks(tick_locs)
        ax.set_xticklabels(tick_labels)
        ax.set_yticks(tick_locs)
        ax.set_yticklabels(tick_labels)

        ax.set_xlabel("False Alarm Rate (FAR)")
        ax.set_ylabel("Miss Rate (FRR)")
        ax.set_title("Detection Error Tradeoff (DET) — Multi-Benchmark Comparison")
        ax.grid(True)
        ax.legend(loc="upper right", framealpha=0.8, edgecolor="#475569")

        out_path = self.output_dir / output_filename
        fig.tight_layout()
        fig.savefig(out_path)
        plt.close(fig)
        return str(out_path)

    def plot_confusion_matrix(
        self, cm: List[List[int]], title: str = "VIGIL-AI Confusion Matrix", output_filename: str = "confusion_matrix.png"
    ) -> str:
        """
        Plots an annotated confusion matrix heatmap.
        cm: [[TN, FP], [FN, TP]]
        """
        fig, ax = plt.subplots(figsize=(6, 5))
        cm_arr = np.array(cm)

        cax = ax.matshow(cm_arr, cmap="Blues", alpha=0.85)
        fig.colorbar(cax)

        classes = ["Bonafide (Real)", "Spoof (Synthetic)"]
        ax.set_xticks([0, 1])
        ax.set_yticks([0, 1])
        ax.set_xticklabels(classes)
        ax.set_yticklabels(classes)

        total = np.sum(cm_arr)
        for i in range(2):
            for j in range(2):
                val = cm_arr[i, j]
                pct = (val / max(1, total)) * 100.0
                color = "white" if val > (total * 0.3) else "black"
                ax.text(j, i, f"{val}\n({pct:.1f}%)", ha="center", va="center", color=color, fontweight="bold")

        ax.set_xlabel("Predicted Security Verdict")
        ax.set_ylabel("Ground Truth")
        ax.set_title(title, pad=15)

        out_path = self.output_dir / output_filename
        fig.tight_layout()
        fig.savefig(out_path)
        plt.close(fig)
        return str(out_path)

    def plot_eer_comparison(
        self, dataset_eers: Dict[str, float], output_filename: str = "eer_comparison.png"
    ) -> str:
        """
        Bar chart comparing Equal Error Rate across benchmarks.
        """
        fig, ax = plt.subplots(figsize=(8, 5))
        names = list(dataset_eers.keys())
        eers = [dataset_eers[k] for k in names]

        colors = ["#10b981", "#06b6d4", "#a855f7", "#f59e0b"][:len(names)]
        bars = ax.bar(names, eers, color=colors, width=0.55, edgecolor="#475569")

        for bar, eer in zip(bars, eers):
            yval = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2.0, yval + 0.15, f"{eer:.2f}%", ha="center", va="bottom", fontweight="bold")

        ax.set_ylabel("Equal Error Rate (EER %)")
        ax.set_title("VIGIL-AI Cross-Dataset EER Comparison (Lower is Better)")
        ax.set_ylim([0, max(eers) * 1.3])
        ax.grid(axis="y", linestyle="--", alpha=0.5)

        out_path = self.output_dir / output_filename
        fig.tight_layout()
        fig.savefig(out_path)
        plt.close(fig)
        return str(out_path)

    def plot_latency_distribution(
        self, latencies_ms: List[float], output_filename: str = "latency_distribution.png"
    ) -> str:
        """
        Histogram & density plot of inference latencies and Real-Time Factor.
        """
        fig, ax = plt.subplots(figsize=(8, 5))
        lat_arr = np.array(latencies_ms)

        ax.hist(lat_arr, bins=25, color="#06b6d4", edgecolor="#1e293b", alpha=0.75, density=True)
        mean_lat = np.mean(lat_arr)
        p95 = np.percentile(lat_arr, 95)

        ax.axvline(mean_lat, color="#10b981", linestyle="--", linewidth=2, label=f"Mean Latency: {mean_lat:.1f}ms")
        ax.axvline(p95, color="#f59e0b", linestyle=":", linewidth=2, label=f"95th Percentile: {p95:.1f}ms")
        ax.axvline(100.0, color="#f43f5e", linestyle="-", linewidth=1.5, label="100ms Hard Budget Ceiling")

        ax.set_xlabel("Inference Latency per 2.0s Audio Window (ms)")
        ax.set_ylabel("Density")
        ax.set_title("Inference Latency Profile & Real-Time Headroom")
        ax.grid(True)
        ax.legend(loc="upper right", framealpha=0.8, edgecolor="#475569")

        out_path = self.output_dir / output_filename
        fig.tight_layout()
        fig.savefig(out_path)
        plt.close(fig)
        return str(out_path)

    def plot_noise_compression_robustness(
        self, snr_eers: Dict[float, float], output_filename: str = "robustness_noise_compression.png"
    ) -> str:
        """
        Plots EER degradation across varying SNR noise conditions.
        """
        fig, ax = plt.subplots(figsize=(8, 5))
        snrs = sorted(list(snr_eers.keys()), reverse=True)
        eers = [snr_eers[s] for s in snrs]

        ax.plot(snrs, eers, marker="o", color="#a855f7", linewidth=2.5, markersize=8)
        for s, e in zip(snrs, eers):
            ax.annotate(f"{e:.1f}%", (s, e), textcoords="offset points", xytext=(0, 10), ha="center", fontweight="bold")

        ax.set_xlabel("Signal-to-Noise Ratio (dB) — Higher is Cleaner")
        ax.set_ylabel("Equal Error Rate (EER %)")
        ax.set_title("VIGIL-AI Acoustic Robustness vs Background Noise")
        ax.invert_xaxis()  # 25dB (clean) -> 0dB (severe noise)
        ax.grid(True)

        out_path = self.output_dir / output_filename
        fig.tight_layout()
        fig.savefig(out_path)
        plt.close(fig)
        return str(out_path)
