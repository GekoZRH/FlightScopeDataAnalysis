"""2D Gaussian analysis for indoor pitching or partial-swing data.

This script reads all CSV files from ../PitchingData/Indoor and performs the
same historical Gaussian analysis used for the full swing data.

It follows the global club and model selection defined in analysis_config.py:
- only club/model labels listed in SELECTED_CLUB_LABELS are included
- model ordering follows MODEL_ORDER
- club ordering follows CLUB_ORDER

In addition to the Gaussian carry/lateral analysis, it also exports a per
club/model mean-value table for roll, descent angle and spin.

The distance summary plot is annotated with:
- mean distance
- 1σ min and 1σ max distance
- mean roll
- mean descent angle
- mean spin
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

from analysis_config import PLOT_ROOT, X_COL, Y_COL, GAUSSIAN_STYLE, GAUSSIAN_SUMMARY_STYLE
from readfiles import read_shot_file
from analysis_io import prepare_base_data
from analysis_stats import compute_mean_and_cov
from analysis_utils import (
    build_master_club_table,
    build_label,
    sanitize_filename,
    ensure_folder,
    apply_plot_style,
)
from swing_Gaussian_analysis import (
    ellipse_points_from_cov,
    ellipse_patch_from_cov,
    compute_axis_limits,
)


PITCHING_DATA_FOLDER = Path("../PitchingData/Indoor")
OUTPUT_FOLDER = PLOT_ROOT / "pitching_Gaussian_analysis"
HISTORIC_SUMMARY_CSV = OUTPUT_FOLDER / "pitching_gaussian_historic_summary.csv"
HISTORIC_DISTANCE_SUMMARY_PLOT = OUTPUT_FOLDER / "pitching_gaussian_historic_distance_summary.png"
HISTORIC_LATERAL_SUMMARY_PLOT = OUTPUT_FOLDER / "pitching_gaussian_historic_lateral_summary.png"
PITCHING_METRICS_SUMMARY_CSV = OUTPUT_FOLDER / "pitching_metrics_summary.csv"

METRIC_COLUMNS = {
    "Roll [m]": "roll_m",
    "Descent V [deg]": "descent_v_deg",
    "Spin [rpm]": "spin_rpm",
}


def load_all_pitching_sessions(data_folder=PITCHING_DATA_FOLDER):
    """Read all pitching/partial-swing CSV files and concatenate them into one DataFrame."""
    files = sorted(Path(data_folder).glob("*.csv"))
    if not files:
        raise RuntimeError(f"No CSV files found in {data_folder}")

    frames = []
    for file in files:
        print(f"Loading pitching file: {file}")
        frames.append(read_shot_file(file))
    return pd.concat(frames, ignore_index=True)


def prepare_pitching_gaussian_data(df, x_col=X_COL, y_col=Y_COL):
    """Prepare pitching data using the shared base-data filter and selected labels."""
    out = prepare_base_data(df, require_session_date=True).copy()
    for col in [x_col, y_col]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["session_date", x_col, y_col]).copy()
    return out


def gaussian_summary_row(df, club, model, n_points=2001):
    """Compute one historical Gaussian summary row for a single club/model."""
    label = build_label(club, model)
    history_df = df[(df["Club"] == club) & (df["Model"] == model)].copy()
    if len(history_df) < 2:
        return None

    history_points = history_df[[X_COL, Y_COL]].to_numpy(dtype=float)
    try:
        mu, cov = compute_mean_and_cov(history_points)
    except ValueError:
        return None

    pts_1s = ellipse_points_from_cov(mu=mu, cov=cov, n_std=1.0, n_points=n_points)
    pts_2s = ellipse_points_from_cov(mu=mu, cov=cov, n_std=2.0, n_points=n_points)

    return {
        "club": club,
        "model": model,
        "label": label,
        "n_shots": len(history_df),
        "mean_distance_m": mu[1],
        "distance_1sigma_min_m": float(np.min(pts_1s[:, 1])),
        "distance_1sigma_max_m": float(np.max(pts_1s[:, 1])),
        "distance_2sigma_min_m": float(np.min(pts_2s[:, 1])),
        "distance_2sigma_max_m": float(np.max(pts_2s[:, 1])),
        "mean_lateral_m": mu[0],
        "lateral_1sigma_left_m": float(np.min(pts_1s[:, 0])),
        "lateral_1sigma_right_m": float(np.max(pts_1s[:, 0])),
        "lateral_2sigma_left_m": float(np.min(pts_2s[:, 0])),
        "lateral_2sigma_right_m": float(np.max(pts_2s[:, 0])),
    }


def export_historic_summary_csv(df, output_csv=HISTORIC_SUMMARY_CSV):
    """Export the historical Gaussian summary table to CSV."""
    output_csv = Path(output_csv)
    ensure_folder(output_csv.parent)

    rows = []
    master = build_master_club_table(df)
    for _, row in master.iterrows():
        summary = gaussian_summary_row(df, row["Club"], row["Model"])
        if summary is not None:
            rows.append(summary)

    summary_df = pd.DataFrame(rows)
    if summary_df.empty:
        raise RuntimeError(
            "No valid pitching Gaussian history summary could be created. "
            "Check SELECTED_CLUB_LABELS and MODEL_ORDER in analysis_config.py."
        )

    summary_df.to_csv(output_csv, index=False)
    print(f"Saved pitching Gaussian summary CSV: {output_csv}")
    return summary_df


def export_pitching_metrics_summary(df, output_csv=PITCHING_METRICS_SUMMARY_CSV):
    """Export a compact per club/model mean-value table."""
    output_csv = Path(output_csv)
    ensure_folder(output_csv.parent)

    master = build_master_club_table(df)
    rows = []

    for _, row in master.iterrows():
        club = row["Club"]
        model = row["Model"]
        label = row["label"]
        club_df = df[(df["Club"] == club) & (df["Model"] == model)].copy()

        out = {
            "club": club,
            "model": model,
            "label": label,
            "n_total_shots": int(len(club_df)),
        }

        for source_col, prefix in METRIC_COLUMNS.items():
            values = (
                pd.to_numeric(club_df[source_col], errors="coerce").dropna()
                if source_col in club_df.columns
                else pd.Series(dtype=float)
            )
            out[f"mean_{prefix}"] = float(values.mean()) if len(values) > 0 else np.nan

        rows.append(out)

    summary_df = pd.DataFrame(rows)
    if summary_df.empty:
        raise RuntimeError("No valid pitching metrics summary could be created")

    summary_df.to_csv(output_csv, index=False)
    print(f"Saved pitching metrics summary CSV: {output_csv}")
    return summary_df


def _prepare_sorted_summary_df(summary_df):
    """Sort the Gaussian summary table in the shared club/model order."""
    if summary_df is None or len(summary_df) == 0:
        raise RuntimeError("Pitching Gaussian summary is empty")

    plot_df = summary_df.copy()
    master = build_master_club_table(
        plot_df.rename(columns={"club": "Club", "model": "Model"})[["Club", "Model"]]
    )
    master = master.rename(columns={"Club": "club", "Model": "model"})[
        ["club", "model", "club_sort", "model_sort", "label"]
    ]
    plot_df = plot_df.merge(master, on=["club", "model", "label"], how="left")
    plot_df = plot_df.sort_values(["club_sort", "model_sort", "label"]).reset_index(drop=True)
    return plot_df


def _apply_summary_x_grid(ax, style):
    """Apply major and minor x-axis grid lines to a summary axis."""
    ax.grid(True, axis="x", alpha=style["grid_alpha"])
    if style.get("show_minor_grid", True):
        step = float(style.get("x_minor_grid_step_m", 10.0))
        if step > 0:
            ax.xaxis.set_minor_locator(MultipleLocator(step))
            ax.grid(True, which="minor", axis="x", alpha=style.get("grid_alpha", 0.25) * 0.6)


def _merge_distance_and_metric_summaries(summary_df, metrics_df):
    """Merge Gaussian distance summary with per-club mean metric summary."""
    plot_df = _prepare_sorted_summary_df(summary_df)
    if metrics_df is None or len(metrics_df) == 0:
        plot_df["mean_roll_m"] = np.nan
        plot_df["mean_descent_v_deg"] = np.nan
        plot_df["mean_spin_rpm"] = np.nan
        return plot_df

    metric_cols = ["club", "model", "label", "mean_roll_m", "mean_descent_v_deg", "mean_spin_rpm"]
    available_cols = [col for col in metric_cols if col in metrics_df.columns]
    merged = plot_df.merge(metrics_df[available_cols], on=["club", "model", "label"], how="left")
    return merged


def _format_number(value, decimals=1):
    """Format one numeric annotation value."""
    if pd.isna(value) or not np.isfinite(value):
        return "nan"
    return f"{float(value):.{int(decimals)}f}"


def plot_historic_distance_summary(summary_df, metrics_df=None, output_file=HISTORIC_DISTANCE_SUMMARY_PLOT, style=None):
    """Plot mean carry together with 1σ and 2σ carry ranges for each club/model.

    The plot is annotated with the mean distance, the -1σ and +1σ distance
    values, and the mean roll, descent angle, and spin values.
    """
    if style is None:
        style = GAUSSIAN_SUMMARY_STYLE

    plot_df = _merge_distance_and_metric_summaries(summary_df, metrics_df)
    y = np.arange(len(plot_df))
    fig, ax = plt.subplots(figsize=style["figsize"])

    ax.hlines(
        y,
        plot_df["distance_2sigma_min_m"],
        plot_df["distance_2sigma_max_m"],
        linewidth=style["sigma2_linewidth"],
        alpha=0.7,
        label="2σ range",
    )
    ax.hlines(
        y,
        plot_df["distance_1sigma_min_m"],
        plot_df["distance_1sigma_max_m"],
        linewidth=style["sigma1_linewidth"],
        alpha=0.95,
        label="1σ range",
    )
    ax.plot(
        plot_df["mean_distance_m"],
        y,
        linestyle="None",
        marker=style["mean_marker"],
        markersize=style["mean_markersize"],
        label="Mean distance",
    )

    # Numeric annotations for mean and ±1σ distance.
    distance_fs = style.get("annotation_fontsize_distance", 16)
    metrics_fs = style.get("annotation_fontsize_metrics", 12)
    mean_dx = style.get("annotate_mean_dx_m", 0.7)
    sigma_dx = style.get("annotate_sigma_dx_m", 0.7)
    metrics_dx = style.get("annotate_metrics_dx_m", 4.0)

    for i, row in plot_df.iterrows():
        y_pos = y[i]

        ax.text(
            float(row["mean_distance_m"]) + mean_dx,
            y_pos + 0.4,
            _format_number(row["mean_distance_m"], 0),
            va="center",
            ha="center",
            fontsize=distance_fs,
            weight='bold',
        )

        ax.text(
            float(row["distance_1sigma_min_m"]) - sigma_dx,
            y_pos - 0.3,
            _format_number(row["distance_1sigma_min_m"], 0),
            va="center",
            ha="right",
            fontsize=distance_fs,
        )

        ax.text(
            float(row["distance_1sigma_max_m"]) + sigma_dx,
            y_pos - 0.3,
            _format_number(row["distance_1sigma_max_m"], 0),
            va="center",
            ha="left",
            fontsize=distance_fs,
        )

        ax.text(
            float(row["distance_2sigma_min_m"]) - 2*sigma_dx,
            y_pos + 0.4,
            _format_number(row["distance_2sigma_min_m"], 0),
            va="center",
            ha="right",
            fontsize=metrics_fs,
        )

        ax.text(
            float(row["distance_2sigma_max_m"]) + 2*sigma_dx,
            y_pos + 0.4,
            _format_number(row["distance_2sigma_max_m"], 0),
            va="center",
            ha="left",
            fontsize=metrics_fs,
        )

        metrics_text = (
            f"roll {_format_number(row.get('mean_roll_m', np.nan), 1)} m\n"
            f"spin {_format_number(row.get('mean_spin_rpm', np.nan), 0)}"
        )
        ax.text(
            float(row["distance_2sigma_max_m"]) + metrics_dx,
            y_pos,
            metrics_text,
            va="center",
            ha="left",
            fontsize=metrics_fs,
        )

    ax.set_yticks(y)
    ax.set_yticklabels(plot_df["label"], fontsize=style.get("club_label_fontsize", style.get("tick_fontsize", 10)))
    ax.invert_yaxis()
    ax.set_xlabel("Carry Distance (m)", fontsize=style.get("label_fontsize", 11))
    ax.set_ylabel("Club", fontsize=style.get("label_fontsize", 11))
    ax.set_xticks([20,30,40,50,60,70,80,90,100,110,120])
    ax.set_title("Pitching Gaussian Distance Summary", fontsize=style.get("title_fontsize", 13))
    ax.tick_params(axis="x", labelsize=style.get("tick_fontsize", 10))
    _apply_summary_x_grid(ax, style)

    ax.grid(True, axis="y", alpha=style.get("grid_alpha", 0.25))

    x_min = float(np.nanmin(plot_df["distance_2sigma_min_m"])) - style.get("x_margin", 5.0)
    x_max = float(np.nanmax(plot_df["distance_2sigma_max_m"])) + style.get("x_margin", 5.0)
    x_max = x_max + style.get("annotation_right_extra_m", 15.0)
    ax.set_xlim(15, 125)

    # if style.get("show_legend", True):
    #     ax.legend(fontsize=style.get("legend_fontsize", 10))

    if style.get("tight_layout", True):
        fig.tight_layout()

    output_file = Path(output_file)
    ensure_folder(output_file.parent)
    fig.savefig(output_file, dpi=style["save_dpi"])
    print(f"Saved plot: {output_file}")
    if style.get("close_after_save", True):
        plt.close(fig)


def plot_historic_lateral_summary(summary_df, output_file=HISTORIC_LATERAL_SUMMARY_PLOT, style=None):
    """Plot mean lateral offset together with 1σ and 2σ lateral ranges for each club/model."""
    if style is None:
        style = GAUSSIAN_SUMMARY_STYLE

    plot_df = _prepare_sorted_summary_df(summary_df)
    y = np.arange(len(plot_df))
    fig, ax = plt.subplots(figsize=style["figsize"])

    ax.hlines(
        y,
        plot_df["lateral_2sigma_left_m"],
        plot_df["lateral_2sigma_right_m"],
        linewidth=style["sigma2_linewidth"],
        alpha=0.7,
        label="2σ range",
    )
    ax.hlines(
        y,
        plot_df["lateral_1sigma_left_m"],
        plot_df["lateral_1sigma_right_m"],
        linewidth=style["sigma1_linewidth"],
        alpha=0.95,
        label="1σ range",
    )
    ax.plot(
        plot_df["mean_lateral_m"],
        y,
        linestyle="-",
        linewidth=style.get("mean_connect_linewidth", 1.5),
        marker=style["mean_marker"],
        markersize=style["mean_markersize"],
        label="Mean lateral",
    )

    ax.set_yticks(y)
    ax.set_yticklabels(plot_df["label"], fontsize=style.get("club_label_fontsize", style.get("tick_fontsize", 10)))
    ax.invert_yaxis()
    ax.set_xlabel("Lateral Distance (m)", fontsize=style.get("label_fontsize", 11))
    ax.set_ylabel("Club", fontsize=style.get("label_fontsize", 11))
    ax.set_title("Pitching Gaussian Lateral Summary", fontsize=style.get("title_fontsize", 13))
    ax.tick_params(axis="x", labelsize=style.get("tick_fontsize", 10))
    _apply_summary_x_grid(ax, style)

    x_min = float(np.nanmin(plot_df["lateral_2sigma_left_m"])) - style.get("x_margin", 5.0)
    x_max = float(np.nanmax(plot_df["lateral_2sigma_right_m"])) + style.get("x_margin", 5.0)
    ax.set_xlim(x_min, x_max)

    if style.get("show_legend", True):
        ax.legend(fontsize=style.get("legend_fontsize", 10))

    if style.get("tight_layout", True):
        fig.tight_layout()

    output_file = Path(output_file)
    ensure_folder(output_file.parent)
    fig.savefig(output_file, dpi=style["save_dpi"])
    print(f"Saved plot: {output_file}")
    if style.get("close_after_save", True):
        plt.close(fig)


def plot_session_vs_history_gaussian(df, session_date, club, model, output_folder, style=None):
    """Plot one club/model Gaussian chart for one pitching session date."""
    if style is None:
        style = GAUSSIAN_STYLE

    label = build_label(club, model)
    history_df = df[(df["Club"] == club) & (df["Model"] == model)].copy()
    session_df = history_df[history_df["session_date"] == session_date].copy()

    if len(history_df) < style.get("min_history_points", 5) or len(session_df) < style.get("min_session_points", 1):
        return

    history_points = history_df[[X_COL, Y_COL]].to_numpy(dtype=float)
    session_points = session_df[[X_COL, Y_COL]].to_numpy(dtype=float)

    try:
        mu, cov = compute_mean_and_cov(history_points)
    except ValueError:
        return

    x_min, x_max, y_min, y_max = compute_axis_limits(
        mu=mu,
        cov=cov,
        history_points=history_points,
        session_points=session_points,
        xlim=style.get("xlim"),
        ylim=style.get("ylim"),
        n_std=style.get("n_sigma_for_limits", 3.0),
        x_margin_frac=style.get("x_margin_frac", 0.08),
        y_margin_frac=style.get("y_margin_frac", 0.08),
        min_x_margin=style.get("min_x_margin", 1.0),
        min_y_margin=style.get("min_y_margin", 2.0),
        center_x_zero=style.get("center_x_zero", True),
    )

    fig, ax = plt.subplots(figsize=style["figsize"])

    ax.scatter(
        session_points[:, 0],
        session_points[:, 1],
        s=style["scatter_size"],
        alpha=style["scatter_alpha"],
        marker=style["scatter_marker"],
        linewidths=style["scatter_linewidth"],
        label=f'{style.get("scatter_label", "Session shots")} ({session_date})',
    )
    ax.scatter(
        [mu[0]],
        [mu[1]],
        marker=style["mean_marker"],
        s=style["mean_size"],
        linewidths=style["mean_linewidth"],
        label=style.get("history_mean_label", "History mean"),
        zorder=5,
    )

    for n_std, color_key, ls_key, label_key in [
        (1.0, "sigma1_color", "sigma1_linestyle", "sigma1_label"),
        (2.0, "sigma2_color", "sigma2_linestyle", "sigma2_label"),
        (3.0, "sigma3_color", "sigma3_linestyle", "sigma3_label"),
    ]:
        ax.add_patch(ellipse_patch_from_cov(
            mu,
            cov,
            n_std=n_std,
            edgecolor=style[color_key],
            linestyle=style[ls_key],
            linewidth=style["sigma_linewidth"],
            label=style.get(label_key, f"{int(n_std)}σ"),
        ))

    ax.axvline(0.0, alpha=style["axis_line_alpha"], linewidth=style["axis_linewidth"])
    ax.axhline(mu[1], alpha=0.20, linewidth=0.8)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_xlabel(X_COL, fontsize=style.get("label_fontsize", 11))
    ax.set_ylabel(Y_COL, fontsize=style.get("label_fontsize", 11))
    ax.set_title(f"{label}: Pitching session {session_date} vs history", fontsize=style.get("title_fontsize", 13))
    ax.tick_params(axis="both", labelsize=style.get("tick_fontsize", 10))
    ax.grid(True, alpha=style["grid_alpha"])

    if style.get("equal_aspect", False):
        ax.set_aspect("equal", adjustable="box")
    if style.get("show_legend", True):
        ax.legend(fontsize=style.get("legend_fontsize", 10))

    fig.tight_layout()
    session_folder = ensure_folder(Path(output_folder) / str(session_date))
    outfile = session_folder / f"pitching_gaussian_{sanitize_filename(label)}.png"
    fig.savefig(outfile, dpi=style["save_dpi"])
    print(f"Saved plot: {outfile}")
    if style.get("close_after_save", True):
        plt.close(fig)


def run_all_gaussian_plots(df, output_folder=OUTPUT_FOLDER, style=None):
    """Generate Gaussian session plots for all pitching session dates and club/models."""
    if style is None:
        style = GAUSSIAN_STYLE

    master = build_master_club_table(df)
    sessions = sorted(df["session_date"].dropna().unique())
    for session_date in sessions:
        print(f"Creating pitching Gaussian plots for session {session_date}")
        for _, row in master.iterrows():
            plot_session_vs_history_gaussian(df, session_date, row["Club"], row["Model"], output_folder, style)


def main():
    """Entry point when the script is run directly."""
    apply_plot_style(GAUSSIAN_STYLE)
    df = load_all_pitching_sessions()
    data = prepare_pitching_gaussian_data(df, x_col=X_COL, y_col=Y_COL)
    run_all_gaussian_plots(data, output_folder=OUTPUT_FOLDER, style=GAUSSIAN_STYLE)
    summary_df = export_historic_summary_csv(data, output_csv=HISTORIC_SUMMARY_CSV)
    metrics_df = export_pitching_metrics_summary(data, output_csv=PITCHING_METRICS_SUMMARY_CSV)
    plot_historic_distance_summary(
        summary_df,
        metrics_df=metrics_df,
        output_file=HISTORIC_DISTANCE_SUMMARY_PLOT,
        style=GAUSSIAN_SUMMARY_STYLE,
    )
    plot_historic_lateral_summary(summary_df, output_file=HISTORIC_LATERAL_SUMMARY_PLOT, style=GAUSSIAN_SUMMARY_STYLE)


if __name__ == "__main__":
    main()
