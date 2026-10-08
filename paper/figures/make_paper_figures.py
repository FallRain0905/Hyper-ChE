"""Create publication-ready figures for the HyperChE paper.

The script intentionally keeps the plotting data local and contains no
credentials or service configuration.  It writes vector PDF files and
300-dpi PNG previews into the same directory as this script.
"""

from pathlib import Path
import csv

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


OUT = Path(__file__).resolve().parent

SYSTEMS = ["B0", "B1", "B2", "F0", "F1"]
METRICS = ["Hit@5", "MRR", "gNDCG@5", "CFR@5"]
DATA = OUT.parents[1] / "experiments" / "final_v1"
SYSTEM_IDS = {"B0": "original_hypergraph", "B1": "chem_prompt_graph",
              "B2": "chem_prompt_hypergraph", "F0": "normalized_final_no_rerank",
              "F1": "normalized_final"}


def load_values():
    with (DATA / "retrieval/shared_retrieval_summary_retained.csv").open(encoding="utf-8-sig", newline="") as stream:
        ranking = {row["system"]: row for row in csv.DictReader(stream)
                   if row["relevance_threshold"] == "grade>=2"}
    with (DATA / "cfr/composite_fact_recall_retained.csv").open(encoding="utf-8-sig", newline="") as stream:
        facts = {row["system"]: row for row in csv.DictReader(stream)}
    return {label: [float(ranking[system][key]) for key in METRICS[:3]] +
            [float(facts[system]["Composite Fact Recall@5"])]
            for label, system in SYSTEM_IDS.items()}


VALUES = load_values()

# A color-blind friendly palette.  F1 is highlighted because it is the final
# normalized system, while F0 is retained as the controlled no-rerank view.
COLORS = {
    "B0": "#6C8EBF",
    "B1": "#4C9F70",
    "B2": "#E39A3B",
    "F0": "#8A6BBE",
    "F1": "#C95757",
}


def setup_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9.5,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 8.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": "#D9D9D9",
            "grid.linewidth": 0.65,
            "grid.alpha": 0.8,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
        }
    )


def save(fig: plt.Figure, stem: str) -> None:
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.png", dpi=300, bbox_inches="tight")
    # Keep the manuscript's figure imports synchronized with regenerated data.
    fig.savefig(OUT.parent / "latex" / "figures" / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def main_results() -> None:
    x = np.arange(len(METRICS))
    width = 0.145
    fig, ax = plt.subplots(figsize=(7.3, 4.35), constrained_layout=True)

    offsets = (np.arange(len(SYSTEMS)) - (len(SYSTEMS) - 1) / 2) * width
    for system, offset in zip(SYSTEMS, offsets):
        vals = VALUES[system]
        bars = ax.bar(
            x + offset,
            vals,
            width,
            label=system,
            color=COLORS[system],
            edgecolor="white",
            linewidth=0.45,
        )
        # Labels on the two final systems make the main comparison easy to
        # inspect while avoiding a dense label field for every bar.
        if system in {"F0", "F1"}:
            for bar, value in zip(bars, vals):
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.012,
                    f"{value:.3f}",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    rotation=90,
                    color="#333333",
                )

    ax.set_ylim(0, 0.75)
    ax.set_ylabel("Metric value")
    ax.set_xticks(x, METRICS)
    ax.set_title("Main retrieval results under the shared qrels protocol")
    ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.02), frameon=False)
    ax.text(
        0.0,
        -0.18,
        "B0/B1/B2: retained comparison views; F0/F1: normalized final views.",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8,
        color="#555555",
    )
    save(fig, "main_results_four_metrics")


def rerank_ablation() -> None:
    x = np.arange(len(METRICS))
    width = 0.32
    f0 = np.array(VALUES["F0"])
    f1 = np.array(VALUES["F1"])
    fig, ax = plt.subplots(figsize=(7.4, 4.2), constrained_layout=True)
    bars0 = ax.bar(x - width / 2, f0, width, label="F0 (no rerank)", color=COLORS["F0"], edgecolor="white")
    bars1 = ax.bar(x + width / 2, f1, width, label="F1 (deterministic rerank)", color=COLORS["F1"], edgecolor="white")

    for bars in (bars0, bars1):
        for bar in bars:
            value = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + 0.012,
                f"{value:.4f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    delta_pp = (f1 - f0) * 100.0
    for i, delta in enumerate(delta_pp):
        label = f"{delta:+.2f} pp" if abs(delta) >= 0.005 else "0.00 pp"
        top = max(f0[i], f1[i]) + 0.075
        ax.annotate(
            label,
            xy=(x[i], top),
            ha="center",
            va="bottom",
            fontsize=8,
            color="#444444",
        )

    ax.set_ylim(0, 0.78)
    ax.set_ylabel("Metric value")
    ax.set_xticks(x, METRICS)
    ax.set_title("Controlled F0/F1 reranking ablation")
    # Keep the legend outside the axes so it cannot obscure the value labels
    # or the delta annotation over the first metric.
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False)
    ax.text(
        0.0,
        -0.18,
        "Both systems use the same hybrid RRF top-50 candidate pool; only reranking is toggled.",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8,
        color="#555555",
    )
    save(fig, "f0_f1_rerank_ablation")


if __name__ == "__main__":
    setup_style()
    main_results()
    rerank_ablation()
    print(f"Wrote figures to {OUT}")
