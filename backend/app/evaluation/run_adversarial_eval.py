"""
VIGIL-AI Adversarial Robustness Evaluation CLI.

Executes defensive sensitivity sweeps against 8 controlled acoustic transformations:
1. Additive noise
2. Codec compression
3. Resampling
4. Volume changes
5. Reverberation
6. Clipping
7. Spectral perturbation
8. Time-domain perturbation

Exports:
- `reports/adversarial_robustness_report.json`
- `reports/adversarial_summary.csv`
- `reports/plots/adversarial_robustness_profile.png`
- `reports/plots/adversarial_radar_summary.png`
"""

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from pathlib import Path
import time
from app.core.logging import logger
from app.evaluation.adversarial_evaluator import AdversarialEvaluator
from app.evaluation.plot_robustness import RobustnessPlotter


def run_adversarial_evaluation(sample_count: int = 100, output_dir: str = "reports") -> None:
    rep_path = Path(output_dir)
    plots_path = rep_path / "plots"
    rep_path.mkdir(parents=True, exist_ok=True)
    plots_path.mkdir(parents=True, exist_ok=True)

    logger.info("Initializing VIGIL-AI Defensive Adversarial Robustness Evaluator...")
    t_start = time.perf_counter()

    evaluator = AdversarialEvaluator()
    plotter = RobustnessPlotter(output_dir=str(plots_path))

    # Run sweeps across all 8 transformations
    logger.info(f"Running acoustic transformation sweeps on {sample_count} evaluation trials...")
    summaries = evaluator.run_all_sweeps(sample_count=sample_count)

    # Export structured reports
    json_path, csv_path = evaluator.export_reports(summaries, output_dir=str(rep_path))

    # Generate diagnostic plots
    logger.info("Generating adversarial sensitivity diagnostic figures...")
    profile_png = plotter.plot_all_transformations(summaries, "adversarial_robustness_profile.png")
    radar_png = plotter.plot_radar_summary(summaries, "adversarial_radar_summary.png")

    total_time = time.perf_counter() - t_start
    logger.info(
        f"Adversarial Robustness Evaluation completed in {total_time:.2f}s.\n"
        f"  JSON: {json_path}\n"
        f"  CSV: {csv_path}\n"
        f"  Profile: {profile_png}\n"
        f"  Radar: {radar_png}"
    )


if __name__ == "__main__":
    run_adversarial_evaluation(sample_count=100, output_dir="reports")
