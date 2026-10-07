"""Session-to-session trend plots for selected metrics.

For each club/model, the script plots the average value per session together
with the corresponding standard deviation.
"""

from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from analysis_config import PLOT_ROOT, TREND_METRICS, TREND_STYLE
from analysis_io import load_all_sessions, prepare_trend_data
from analysis_stats import compute_session_stats
from analysis_utils import build_master_club_table, build_label, sanitize_filename, ensure_folder, apply_plot_style


OUTPUT_FOLDER = PLOT_ROOT / "swing_trend_analysis"


def plot_metric_trend_for_club(club, model, club_stats, metric_cfg, style, save_folder):
    """Plot one metric over time for one club/model."""
    label = build_label(club, model)
    club_stats = club_stats.sort_values("session_date").copy()
    if len(club_stats) < style.get("min_sessions_to_plot", 1):
        return

    x = club_stats["session_date"]
    y = club_stats["session_mean"]
    yerr = club_stats["session_std"].fillna(0)

    fig, ax = plt.subplots(figsize=style["figsize"])
    ax.errorbar(x, y, yerr=yerr, fmt=style["fmt"], capsize=style["capsize"],
                linewidth=style["linewidth"], markersize=style["markersize"])
    ax.set_title(f'{metric_cfg["title"]} over Time — {label}', fontsize=style.get("title_fontsize", 13))
    ax.set_xlabel("Session Date", fontsize=style.get("label_fontsize", 11))
    ax.set_ylabel(metric_cfg["ylabel"], fontsize=style.get("label_fontsize", 11))
    ax.tick_params(axis="both", labelsize=style.get("tick_fontsize", 10))
    ax.grid(True, alpha=style["grid_alpha"])

    if style.get("ylim") is not None:
        ax.set_ylim(style["ylim"])

    ax.xaxis.set_major_formatter(mdates.DateFormatter(style["date_format"]))
    plt.setp(ax.get_xticklabels(), rotation=style["date_rotation"], ha="right")

    # Optional shot-count annotations can help judge how reliable each point is.
    if style.get("show_count_labels", False):
        for _, row in club_stats.iterrows():
            ax.annotate(
                f'n={int(row["session_count"])}',
                (row["session_date"], row["session_mean"]),
                textcoords="offset points",
                xytext=(0, 6),
                ha="center",
                fontsize=style["count_label_fontsize"],
            )

    if style.get("tight_layout", True):
        plt.tight_layout()

    ensure_folder(save_folder)
    outfile = Path(save_folder) / f'{metric_cfg["short_name"]}_{sanitize_filename(label)}.png'
    plt.savefig(outfile, dpi=style["save_dpi"])
    plt.close(fig)
    print(f"Saved plot: {outfile}")


def run_metric_trend_analysis(df, metric_col, metric_cfg, output_folder, style):
    """Generate all club/model trend plots for one metric."""
    stats = compute_session_stats(df, metric_col)
    if stats.empty:
        print(f"No valid data for {metric_col}")
        return

    master = build_master_club_table(stats)
    metric_folder = Path(output_folder) / metric_cfg["short_name"]

    for _, row in master.iterrows():
        club_stats = stats[(stats["Club"] == row["Club"]) & (stats["Model"] == row["Model"])].copy()
        if not club_stats.empty:
            plot_metric_trend_for_club(row["Club"], row["Model"], club_stats, metric_cfg, style, metric_folder)


def main():
    """Entry point when the script is run directly."""
    apply_plot_style(TREND_STYLE)
    df = prepare_trend_data(load_all_sessions())
    for metric_col, metric_cfg in TREND_METRICS.items():
        print(f"Running trend analysis for: {metric_col}")
        run_metric_trend_analysis(df, metric_col, metric_cfg, OUTPUT_FOLDER, TREND_STYLE)


if __name__ == "__main__":
    main()
