from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
from scipy.stats import skewnorm

from analysis_config import PLOT_ROOT, GAUSSIAN_SUMMARY_STYLE
from analysis_io import load_all_sessions, prepare_base_data
from analysis_utils import (
    build_master_club_table,
    build_label,
    sanitize_filename,
    ensure_folder,
    apply_plot_style,
)


OUTPUT_FOLDER = PLOT_ROOT / "swing_carry_skew_normal"
CARRY_COLUMN = "Carry [m]"
HISTORIC_SUMMARY_CSV = OUTPUT_FOLDER / "carry_skewnormal_historic_summary.csv"
HISTORIC_DISTANCE_SUMMARY_PLOT = OUTPUT_FOLDER / "carry_skewnormal_historic_distance_summary.png"


SKEW_HIST_STYLE = {
    "figsize": (9, 6),
    "save_dpi": 220,
    "title_fontsize": 13,
    "label_fontsize": 11,
    "tick_fontsize": 10,
    "legend_fontsize": 10,
    "grid_alpha": 0.30,
    "hist_bins": "auto",
    "hist_density": True,
    "hist_alpha": 0.65,
    "fit_linewidth": 2.2,
    "min_points_to_fit": 5,
    "show_mean_line": True,
    "mean_linestyle": "--",
    "mean_linewidth": 1.4,
    "show_median_line": False,
    "median_linestyle": ":",
    "median_linewidth": 1.2,
    "x_padding_fraction": 0.08,
    "tight_layout": True,
}

SKEW_SUMMARY_STYLE = dict(GAUSSIAN_SUMMARY_STYLE)
SKEW_SUMMARY_STYLE.update({
    "figsize": (14, 7),
    "title_distance": "Historic Carry Skew-Normal Summary",
    "annotation_fontsize_distance": 16,
    "annotation_fontsize_sigma2": 12,
    "annotate_mean_dx_m": 0.7,
    "annotate_sigma_dx_m": 0.7,
})

SIGMA_INTERVALS_1D = {
    1.0: (0.15865525393145707, 0.8413447460685429),
    2.0: (0.02275013194817921, 0.9772498680518208),
}


def fit_skew_normal(values):
    """Fit a skew-normal distribution and return (shape, loc, scale)."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.ndim != 1:
        raise ValueError("Input values must be one-dimensional")
    if len(values) < 3:
        raise ValueError("At least three values are required for a fit")

    shape, loc, scale = skewnorm.fit(values)
    scale = float(abs(scale))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid skew-normal scale parameter")
    return float(shape), float(loc), scale



def _x_grid_from_data(values, padding_fraction=0.08, points=600):
    """Create a plotting grid that slightly extends beyond the data range."""
    vmin = float(np.min(values))
    vmax = float(np.max(values))
    span = vmax - vmin
    if span <= 0:
        span = max(abs(vmin), 1.0)
    padding = span * padding_fraction
    return np.linspace(vmin - padding, vmax + padding, points)



def _finite_ppf(shape, loc, scale, q, fallback):
    value = skewnorm.ppf(q, shape, loc=loc, scale=scale)
    if np.isfinite(value):
        return float(value)
    return float(fallback)



def skew_interval(shape, loc, scale, n_sigma=1.0):
    q_low, q_high = SIGMA_INTERVALS_1D[float(n_sigma)]
    low = _finite_ppf(shape, loc, scale, q_low, loc)
    high = _finite_ppf(shape, loc, scale, q_high, loc)
    return float(min(low, high)), float(max(low, high))



def _format_number(value, decimals=0):
    if pd.isna(value) or not np.isfinite(value):
        return "nan"
    return f"{float(value):.{int(decimals)}f}"



def plot_carry_histogram_with_skew_fit(club, model, values, style, save_folder):
    """Create one carry histogram with overlaid skew-normal fit."""
    label = build_label(club, model)
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    if len(values) < style.get("min_points_to_fit", 5):
        print(f"Skipping {label}: only {len(values)} valid carry values")
        return

    shape, loc, scale = fit_skew_normal(values)
    x = _x_grid_from_data(values, padding_fraction=style.get("x_padding_fraction", 0.08))
    pdf = skewnorm.pdf(x, shape, loc=loc, scale=scale)

    mean_val = float(skewnorm.mean(shape, loc=loc, scale=scale))
    if not np.isfinite(mean_val):
        mean_val = float(np.mean(values))
    median_val = float(np.median(values))
    std_val = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0

    fig, ax = plt.subplots(figsize=style["figsize"])

    ax.hist(
        values,
        bins=style.get("hist_bins", "auto"),
        density=style.get("hist_density", True),
        alpha=style.get("hist_alpha", 0.65),
        label=f"Historic carry (n={len(values)})",
    )
    ax.plot(
        x,
        pdf,
        linewidth=style.get("fit_linewidth", 2.2),
        label="Skew-normal fit",
    )

    if style.get("show_mean_line", True):
        ax.axvline(
            mean_val,
            linestyle=style.get("mean_linestyle", "--"),
            linewidth=style.get("mean_linewidth", 1.4),
            label=f"Mean = {mean_val:.1f} m",
        )

    if style.get("show_median_line", False):
        ax.axvline(
            median_val,
            linestyle=style.get("median_linestyle", ":"),
            linewidth=style.get("median_linewidth", 1.2),
            label=f"Median = {median_val:.1f} m",
        )

    ax.set_title(f"Historic Carry Distance — {label}", fontsize=style.get("title_fontsize", 13))
    ax.set_xlabel("Carry Distance (m)", fontsize=style.get("label_fontsize", 11))
    ax.set_ylabel("Probability Density", fontsize=style.get("label_fontsize", 11))
    ax.tick_params(axis="both", labelsize=style.get("tick_fontsize", 10))
    ax.grid(True, alpha=style.get("grid_alpha", 0.30))

    stats_text = (
        f"n = {len(values)}\n"
        f"mean = {mean_val:.1f} m\n"
        f"std = {std_val:.1f} m\n"
        f"shape = {shape:.2f}\n"
        f"loc = {loc:.2f}\n"
        f"scale = {scale:.2f}"
    )
    ax.text(
        0.98,
        0.98,
        stats_text,
        transform=ax.transAxes,
        ha="right",
        va="top",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85),
    )

    ax.legend()

    if style.get("tight_layout", True):
        plt.tight_layout()

    ensure_folder(save_folder)
    outfile = Path(save_folder) / f"carry_hist_skewnorm_{sanitize_filename(label)}.png"
    plt.savefig(outfile, dpi=style.get("save_dpi", 220))
    plt.close(fig)
    print(f"Saved plot: {outfile}")



def carry_skew_summary_row(data, club, model):
    """Compute historical carry summary from a 1D skew-normal fit."""
    label = build_label(club, model)
    club_data = data[(data["Club"] == club) & (data["Model"] == model)].copy()
    values = club_data[CARRY_COLUMN].to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 3:
        return None

    try:
        shape, loc, scale = fit_skew_normal(values)
    except ValueError:
        return None

    mean_distance = float(skewnorm.mean(shape, loc=loc, scale=scale))
    if not np.isfinite(mean_distance):
        mean_distance = float(np.mean(values))

    d1_low, d1_high = skew_interval(shape, loc, scale, n_sigma=1.0)
    d2_low, d2_high = skew_interval(shape, loc, scale, n_sigma=2.0)

    return {
        "club": club,
        "model": model,
        "label": label,
        "n_shots": len(values),
        "mean_distance_m": mean_distance,
        "distance_1sigma_min_m": d1_low,
        "distance_1sigma_max_m": d1_high,
        "distance_2sigma_min_m": d2_low,
        "distance_2sigma_max_m": d2_high,
        "shape": shape,
        "loc": loc,
        "scale": scale,
    }



def export_historic_summary_csv(data, output_csv=HISTORIC_SUMMARY_CSV):
    """Export one carry skew-normal summary row per club/model."""
    output_csv = Path(output_csv)
    ensure_folder(output_csv.parent)

    rows = []
    master = build_master_club_table(data)
    for _, row in master.iterrows():
        summary = carry_skew_summary_row(data, row["Club"], row["Model"])
        if summary is not None:
            rows.append(summary)

    summary_df = pd.DataFrame(rows)
    if summary_df.empty:
        raise RuntimeError("No valid carry skew-normal history summary could be created")

    summary_df.to_csv(output_csv, index=False)
    print(f"Saved carry skew-normal summary CSV: {output_csv}")
    return summary_df



def _prepare_sorted_summary_df(summary_df):
    if summary_df is None or len(summary_df) == 0:
        raise RuntimeError("Carry skew-normal summary is empty")

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
    ax.grid(True, axis="x", alpha=style["grid_alpha"])
    if style.get("show_minor_grid", True):
        step = float(style.get("x_minor_grid_step_m", 10.0))
        if step > 0:
            ax.xaxis.set_minor_locator(MultipleLocator(step))
            ax.grid(True, which="minor", axis="x", alpha=style.get("grid_alpha", 0.25) * 0.6)



def plot_historic_distance_summary(summary_df, output_file=HISTORIC_DISTANCE_SUMMARY_PLOT, style=None):
    """Plot mean carry together with annotated 1σ and 2σ ranges."""
    if style is None:
        style = SKEW_SUMMARY_STYLE

    plot_df = _prepare_sorted_summary_df(summary_df)
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

    distance_fs = style.get("annotation_fontsize_distance", 16)
    sigma2_fs = style.get("annotation_fontsize_sigma2", 12)
    mean_dx = style.get("annotate_mean_dx_m", 0.7)
    sigma_dx = style.get("annotate_sigma_dx_m", 0.7)

    for i, row in plot_df.iterrows():
        y_pos = y[i]
        ax.text(
            float(row["mean_distance_m"]) + mean_dx,
            y_pos + 0.35,
            _format_number(row["mean_distance_m"], 0),
            va="center",
            ha="center",
            fontsize=distance_fs,
            weight="bold",
        )
        ax.text(
            float(row["distance_1sigma_min_m"]) - sigma_dx,
            y_pos - 0.25,
            _format_number(row["distance_1sigma_min_m"], 0),
            va="center",
            ha="right",
            fontsize=distance_fs,
        )
        ax.text(
            float(row["distance_1sigma_max_m"]) + sigma_dx,
            y_pos - 0.25,
            _format_number(row["distance_1sigma_max_m"], 0),
            va="center",
            ha="left",
            fontsize=distance_fs,
        )
        ax.text(
            float(row["distance_2sigma_min_m"]) - 2.0 * sigma_dx,
            y_pos + 0.35,
            _format_number(row["distance_2sigma_min_m"], 0),
            va="center",
            ha="right",
            fontsize=sigma2_fs,
        )
        ax.text(
            float(row["distance_2sigma_max_m"]) + 2.0 * sigma_dx,
            y_pos + 0.35,
            _format_number(row["distance_2sigma_max_m"], 0),
            va="center",
            ha="left",
            fontsize=sigma2_fs,
        )

    ax.set_yticks(y)
    ax.set_yticklabels(plot_df["label"], fontsize=style.get("club_label_fontsize", style.get("tick_fontsize", 10)))
    ax.invert_yaxis()
    ax.set_xlabel("Carry Distance (m)", fontsize=style.get("label_fontsize", 11))
    ax.set_ylabel("Club", fontsize=style.get("label_fontsize", 11))
    ax.set_title(style.get("title_distance", "Historic Carry Skew-Normal Summary"), fontsize=style.get("title_fontsize", 13))
    ax.tick_params(axis="x", labelsize=style.get("tick_fontsize", 10))
    _apply_summary_x_grid(ax, style)
    ax.grid(True, axis="y", alpha=style.get("grid_alpha", 0.25))
    x_min = float(np.nanmin(plot_df["distance_2sigma_min_m"])) - style.get("x_margin", 5.0)
    x_max = float(np.nanmax(plot_df["distance_2sigma_max_m"])) + style.get("x_margin", 5.0)
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



def run_carry_skew_normal_analysis(df, output_folder=OUTPUT_FOLDER, style=SKEW_HIST_STYLE):
    """Generate one historic carry histogram with skew-normal fit per club/model."""
    data = prepare_base_data(df, require_session_date=False).copy()
    if CARRY_COLUMN not in data.columns:
        raise ValueError(f"Expected column '{CARRY_COLUMN}' not found in data")

    data[CARRY_COLUMN] = np.asarray(data[CARRY_COLUMN])
    data[CARRY_COLUMN] = np.where(pd_isna(data[CARRY_COLUMN]), np.nan, data[CARRY_COLUMN])
    data[CARRY_COLUMN] = data[CARRY_COLUMN].astype(float)
    data = data[np.isfinite(data[CARRY_COLUMN])].copy()

    if data.empty:
        raise RuntimeError("No valid carry-distance data available after filtering")

    master = build_master_club_table(data)

    for _, row in master.iterrows():
        club_data = data[(data["Club"] == row["Club"]) & (data["Model"] == row["Model"])].copy()
        values = club_data[CARRY_COLUMN].to_numpy(dtype=float)
        plot_carry_histogram_with_skew_fit(
            row["Club"],
            row["Model"],
            values,
            style,
            output_folder,
        )

    return data



def pd_isna(values):
    import pandas as pd
    return pd.isna(values)



def main():
    """Entry point when the script is run directly."""
    apply_plot_style(SKEW_HIST_STYLE)
    df = load_all_sessions()
    data = run_carry_skew_normal_analysis(df, OUTPUT_FOLDER, SKEW_HIST_STYLE)
    summary_df = export_historic_summary_csv(data, output_csv=HISTORIC_SUMMARY_CSV)
    plot_historic_distance_summary(summary_df, output_file=HISTORIC_DISTANCE_SUMMARY_PLOT, style=SKEW_SUMMARY_STYLE)


if __name__ == "__main__":
    main()
