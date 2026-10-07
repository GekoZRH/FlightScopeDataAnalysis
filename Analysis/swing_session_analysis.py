"""Session-vs-history plots for the main indoor shot metrics.

For each session date and each metric, this script overlays:
- the historical mean ± standard deviation for every club/model
- the current session mean ± standard deviation for the same club/model

The output is written into one subfolder per training session.
"""

from pathlib import Path
import matplotlib.pyplot as plt

from analysis_config import PLOT_ROOT, METRICS, SESSION_VS_HISTORY_STYLE
from analysis_io import load_all_sessions, prepare_base_data
from analysis_stats import compute_history_stats, compute_session_stats
from analysis_utils import build_master_club_table, ensure_folder, apply_plot_style


OUTPUT_FOLDER = PLOT_ROOT / "swing_sessions"


def plot_session_vs_history(master_table, history_stats, session_stats, session_date, metric_cfg, plot_style=None, save_folder=None):
    """Plot one metric for one session against the full historical statistics."""
    if plot_style is None:
        plot_style = SESSION_VS_HISTORY_STYLE

    # Join the global history and the selected session onto the same club table
    # so all clubs appear in one consistent order on the x-axis.
    session_df = session_stats[session_stats["session_date"] == session_date].copy()
    plot_df = (
        master_table.merge(history_stats, on=["Club", "Model"], how="left")
        .merge(session_df[["Club", "Model", "session_mean", "session_std", "session_count"]], on=["Club", "Model"], how="left")
    )

    x = list(range(len(plot_df)))
    fig, ax = plt.subplots(figsize=plot_style["figsize"])

    # Historical mean ± sigma for all available club/model combinations.
    ax.errorbar(
        x,
        plot_df["history_mean"],
        yerr=plot_df["history_std"].fillna(0),
        fmt=plot_style["history_fmt"],
        capsize=plot_style["capsize"],
        linewidth=plot_style["history_linewidth"],
        label=plot_style["history_label"],
    )

    # Overlay the selected session only where session values are available.
    session_mask = plot_df["session_mean"].notna()
    x_session = [i for i, flag in enumerate(session_mask) if flag]
    ax.errorbar(
        x_session,
        plot_df.loc[session_mask, "session_mean"],
        yerr=plot_df.loc[session_mask, "session_std"].fillna(0),
        fmt=plot_style["session_fmt"],
        capsize=plot_style["capsize"],
        linewidth=plot_style["session_linewidth"],
        label=f"Session {session_date}",
    )

    ax.set_xticks(x)
    ax.set_xticklabels(plot_df["label"], rotation=plot_style["xtick_rotation"], ha="right")
    ax.set_xlabel("Club / Model", fontsize=plot_style.get("label_fontsize", 11))
    ax.set_ylabel(metric_cfg["ylabel"], fontsize=plot_style.get("label_fontsize", 11))
    ax.set_title(
        f'{metric_cfg["title"]}: Session {session_date} vs Overall History',
        fontsize=plot_style.get("title_fontsize", 13),
    )
    ax.tick_params(axis="both", labelsize=plot_style.get("tick_fontsize", 10))
    ax.grid(True, alpha=plot_style["grid_alpha"])

    if plot_style["show_legend"]:
        ax.legend(fontsize=plot_style.get("legend_fontsize", 10))

    fig.tight_layout()

    if save_folder is not None:
        ensure_folder(save_folder)
        outfile = Path(save_folder) / f'{metric_cfg["short_name"]}_session_vs_history.png'
        fig.savefig(outfile, dpi=plot_style["save_dpi"], bbox_inches="tight")
        print(f"Saved plot: {outfile}")

    plt.close(fig)


def run_metric_analysis(df, metric_col, metric_cfg, root_folder=None, plot_style=None):
    """Run the session-vs-history analysis for one metric across all sessions."""
    if plot_style is None:
        plot_style = SESSION_VS_HISTORY_STYLE

    history_stats = compute_history_stats(df, metric_col)
    session_stats = compute_session_stats(df, metric_col)
    if session_stats.empty:
        print(f"No valid data for metric: {metric_col}")
        return

    master_table = build_master_club_table(df)
    sessions = sorted(session_stats["session_date"].unique())
    print(f"{metric_cfg['title']}: found {len(sessions)} session(s)")

    for session_date in sessions:
        save_folder = None
        if root_folder is not None:
            save_folder = Path(root_folder) / str(session_date)
        plot_session_vs_history(
            master_table=master_table,
            history_stats=history_stats,
            session_stats=session_stats,
            session_date=session_date,
            metric_cfg=metric_cfg,
            plot_style=plot_style,
            save_folder=save_folder,
        )


def main():
    """Entry point when the script is run directly."""
    apply_plot_style(SESSION_VS_HISTORY_STYLE)
    df = prepare_base_data(load_all_sessions())
    for metric_col, metric_cfg in METRICS.items():
        run_metric_analysis(df, metric_col, metric_cfg, root_folder=OUTPUT_FOLDER, plot_style=SESSION_VS_HISTORY_STYLE)


if __name__ == "__main__":
    main()
