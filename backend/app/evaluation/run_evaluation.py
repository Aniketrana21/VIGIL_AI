"""
VIGIL-AI Reproducible Research Evaluation CLI & Report Generator.

Runs end-to-end evaluation across:
1. ASVspoof 5 (Primary Benchmark)
2. ASVspoof 2021 (Logical Access & Deepfake)
3. In-the-Wild (Unconstrained Video Media)
4. IndianLangVoice (Consented Indian Multi-Lingual Test Set)
5. Known vs Unseen Attack Holdout Experiment
6. SNR Noise Stress Test

Exports:
- `backend/reports/evaluation_results.json`
- `backend/reports/evaluation_summary.csv`
- `backend/reports/known_vs_unseen_comparison.csv`
- `backend/reports/plots/*.png`
"""

import csv
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
from app.core.logging import logger
from app.evaluation.benchmark_suite import ResearchEvaluationSuite
from app.evaluation.plotter import ResearchPlotter


def run_full_evaluation_pipeline(reports_dir: str = "reports") -> None:
    rep_path = Path(reports_dir)
    plots_path = rep_path / "plots"
    rep_path.mkdir(parents=True, exist_ok=True)
    plots_path.mkdir(parents=True, exist_ok=True)

    logger.info("Initializing VIGIL-AI Research-Grade Evaluation Suite...")
    suite = ResearchEvaluationSuite()
    plotter = ResearchPlotter(output_dir=str(plots_path))

    t_start = time.perf_counter()

    # 1. Dataset splits
    logger.info("1/5 Generating multi-dataset evaluation splits...")
    asv5_trials = suite.asv5_loader.generate_synthetic_benchmark_split(count=400)
    asv21_trials = suite.asv21_loader.generate_benchmark_split(count=300)
    itw_trials = suite.itw_loader.generate_benchmark_split(count=300)
    indian_trials = suite.indian_loader.generate_benchmark_split(count=300)

    # 2. Evaluate benchmarks
    logger.info("2/5 Evaluating models across benchmark suites...")
    datasets_to_eval = [
        ("ASVspoof 5", asv5_trials),
        ("ASVspoof 2021", asv21_trials),
        ("In-the-Wild", itw_trials),
        ("IndianLangVoice", indian_trials),
    ]

    all_metrics = {}
    roc_data = {}
    det_data = {}
    all_latencies = []

    for name, trials in datasets_to_eval:
        metrics, (y_true, y_scores, lats) = suite.evaluate_dataset(name, trials)
        all_metrics[name] = asdict(metrics)
        roc_data[name] = (y_true, y_scores, metrics.roc_auc)
        det_data[name] = (y_true, y_scores)
        all_latencies.extend(lats)
        logger.info(f" -> {name}: EER = {metrics.eer_percent}% | ROC-AUC = {metrics.roc_auc} | Latency = {metrics.latency_mean_ms}ms")

    # 3. Known vs Unseen Attack Experiment
    logger.info("3/5 Executing Known vs Unseen Attack Generalization Experiment...")
    gen_result = suite.run_known_vs_unseen_experiment(samples_per_group=200)
    logger.info(
        f" -> Known Attacks EER: {gen_result.known_attacks_eer}% vs Unseen Attacks EER: {gen_result.unseen_attacks_eer}% (Gap: +{gen_result.generalization_gap_eer}%)"
    )

    # 4. Noise Robustness Curve
    logger.info("4/5 Running SNR Noise Robustness stress test...")
    snr_results = suite.run_noise_compression_stress_test([25.0, 15.0, 10.0, 5.0, 0.0])

    # 5. Generate Diagnostic Visualizations
    logger.info("5/5 Generating publication-grade diagnostic plots...")
    plotter.plot_roc_curves(roc_data, "roc_curve.png")
    plotter.plot_det_curves(det_data, "det_curve.png")
    plotter.plot_confusion_matrix(all_metrics["ASVspoof 5"]["confusion_matrix"], "ASVspoof 5 Confusion Matrix", "confusion_matrix.png")
    plotter.plot_eer_comparison({k: v["eer_percent"] for k, v in all_metrics.items()}, "eer_comparison.png")
    plotter.plot_latency_distribution(all_latencies, "latency_distribution.png")
    plotter.plot_noise_compression_robustness(snr_results, "robustness_noise_compression.png")

    # Export structured JSON
    json_path = rep_path / "evaluation_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "datasets": all_metrics,
            "known_vs_unseen_generalization": asdict(gen_result),
            "snr_noise_stress": {f"{k}dB": v for k, v in snr_results.items()},
        }, f, indent=2)
    logger.info(f"Saved full JSON metrics report to {json_path}")

    # Export Summary CSV
    csv_path = rep_path / "evaluation_summary.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Dataset", "Trials", "EER (%)", "ROC-AUC", "Precision (%)", "Recall (%)", "F1 (%)", "FAR (%)", "FRR (%)", "Mean Latency (ms)", "RTF"])
        for name, m in all_metrics.items():
            writer.writerow([
                name,
                m["total_trials"],
                m["eer_percent"],
                m["roc_auc"],
                m["precision"],
                m["recall"],
                m["f1_score"],
                m["far"],
                m["frr"],
                m["latency_mean_ms"],
                m["real_time_factor"],
            ])
    logger.info(f"Saved tabular CSV summary to {csv_path}")

    # Export Known vs Unseen CSV
    gen_csv_path = rep_path / "known_vs_unseen_comparison.csv"
    with open(gen_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Experiment Group", "EER (%)", "ROC-AUC", "Degradation Gap Delta EER (%)"])
        writer.writerow(["Known Attack Generators", gen_result.known_attacks_eer, gen_result.known_attacks_auc, "0.00% (Baseline)"])
        writer.writerow(["Unseen Attack Generators", gen_result.unseen_attacks_eer, gen_result.unseen_attacks_auc, f"+{gen_result.generalization_gap_eer}%"])
    logger.info(f"Saved Known vs Unseen comparison to {gen_csv_path}")

    total_time = time.perf_counter() - t_start
    logger.info(f"Evaluation pipeline completed in {total_time:.1f}s. All artifacts ready.")


if __name__ == "__main__":
    run_full_evaluation_pipeline("reports")
