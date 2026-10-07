"""Historic 2D shot-distribution analysis using independent skew-normal fits.

For each club/model this script uses the full historic data only (no per-session
breakdown) and creates one plot with:
- all historic shots as a scatter plot
- the historic mean marker
- 1σ / 2σ / 3σ-like probability contours derived from skew-normal fits on
  lateral distance and carry distance

In addition, it exports a historical summary CSV and creates two summary plots:
- carry distance on the x-axis and club on the y-axis
- lateral displacement on the x-axis and club on the y-axis

The x and y marginals are fitted independently with scipy.stats.skewnorm. The
resulting 2D density is therefore axis-aligned rather than rotated like the 2D
Gaussian covariance ellipses in GaussianAnalysis_260322.py, but it can capture
skew in both lateral and carry distributions.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
from scipy.stats import skewnorm

from analysis_config import PLOT_ROOT, X_COL, Y_COL, GAUSSIAN_STYLE, GAUSSIAN_SUMMARY_STYLE
from analysis_io import load_all_sessions, prepare_gaussian_data
from analysis_utils import (
    build_master_club_table,
    build_label,
    sanitize_filename,
    ensure_folder,
    apply_plot_style,
)


OUTPUT_FOLDER = PLOT_ROOT / "swing_skew_normal"
HISTORIC_SUMMARY_CSV = OUTPUT_FOLDER / "skewnormal_historic_summary.csv"
HISTORIC_DISTANCE_SUMMARY_PLOT = OUTPUT_FOLDER / "skewnormal_historic_distance_summary.png"
HISTORIC_LATERAL_SUMMARY_PLOT = OUTPUT_FOLDER / "skewnormal_historic_lateral_summary.png"

# Coverage probabilities corresponding to a 2D Gaussian radius of 1σ / 2σ / 3σ.
SIGMA_COVERAGES_2D = {
    1.0: 1.0 - np.exp(-0.5 * 1.0 ** 2),
    2.0: 1.0 - np.exp(-0.5 * 2.0 ** 2),
    3.0: 1.0 - np.exp(-0.5 * 3.0 ** 2),
}

# Equal-tail quantiles matching a standard normal ±nσ interval in 1D.
SIGMA_INTERVALS_1D = {
    1.0: (0.15865525393145707, 0.8413447460685429),
    2.0: (0.02275013194817921, 0.9772498680518208),
    3.0: (0.0013498980316300933, 0.9986501019683699),
}

SKEW_2D_STYLE = dict(GAUSSIAN_STYLE)
SKEW_2D_STYLE.update({
    "figsize": (7.5, 6.5),
    "save_dpi": 220,
    "grid_alpha": 0.28,
    "scatter_label": "Historic shots",
    "history_mean_label": "Historic mean",
    "min_history_points": 8,
    "grid_points": 260,
    "fit_padding_fraction": 0.10,
    "ppf_tail_probability": 0.001,
    "show_density_fill": False,
    "density_fill_alpha": 0.18,
    "title_prefix": "Historic Skew-Normal Fit",
})

SKEW_SUMMARY_STYLE = dict(GAUSSIAN_SUMMARY_STYLE)
SKEW_SUMMARY_STYLE.update({
    "title_distance": "Historic Skew-Normal Distance Summary",
    "title_lateral": "Historic Skew-Normal Lateral Summary",
})


def fit_skew_normal(values):
    """Fit a 1D skew-normal distribution and return (shape, loc, scale)."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.ndim != 1:
        raise ValueError("Input values must be one-dimensional")
    if len(values) < 3:
        raise ValueError("At least three values are required for a skew-normal fit")

    shape, loc, scale = skewnorm.fit(values)
    scale = float(abs(scale))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid skew-normal scale parameter")
    return float(shape), float(loc), scale


def _finite_ppf(shape, loc, scale, q, fallback):
    """Return a finite skew-normal quantile, otherwise a fallback value."""
    out = skewnorm.ppf(q, shape, loc=loc, scale=scale)
    if np.isfinite(out):
        return float(out)
    return float(fallback)



def skew_interval(shape, loc, scale, n_sigma=1.0):
    """Return the equal-tail interval corresponding to ±nσ in a standard normal."""
    q_low, q_high = SIGMA_INTERVALS_1D[float(n_sigma)]
    low = _finite_ppf(shape, loc, scale, q_low, loc)
    high = _finite_ppf(shape, loc, scale, q_high, loc)
    return float(min(low, high)), float(max(low, high))



def build_density_grid(x_values, y_values, x_params, y_params, style):
    """Build a 2D density grid from independent x/y skew-normal marginals."""
    x_values = np.asarray(x_values, dtype=float)
    y_values = np.asarray(y_values, dtype=float)

    shape_x, loc_x, scale_x = x_params
    shape_y, loc_y, scale_y = y_params

    p_tail = float(style.get("ppf_tail_probability", 0.001))
    pad_frac = float(style.get("fit_padding_fraction", 0.10))
    n_grid = int(style.get("grid_points", 260))

    x_min_ppf = _finite_ppf(shape_x, loc_x, scale_x, p_tail, np.min(x_values))
    x_max_ppf = _finite_ppf(shape_x, loc_x, scale_x, 1.0 - p_tail, np.max(x_values))
    y_min_ppf = _finite_ppf(shape_y, loc_y, scale_y, p_tail, np.min(y_values))
    y_max_ppf = _finite_ppf(shape_y, loc_y, scale_y, 1.0 - p_tail, np.max(y_values))

    x_min = min(np.min(x_values), x_min_ppf)
    x_max = max(np.max(x_values), x_max_ppf)
    y_min = min(np.min(y_values), y_min_ppf)
    y_max = max(np.max(y_values), y_max_ppf)

    x_span = max(x_max - x_min, 1.0)
    y_span = max(y_max - y_min, 1.0)
    x_pad = pad_frac * x_span
    y_pad = pad_frac * y_span

    x = np.linspace(x_min - x_pad, x_max + x_pad, n_grid)
    y = np.linspace(y_min - y_pad, y_max + y_pad, n_grid)
    xx, yy = np.meshgrid(x, y)

    pdf_x = skewnorm.pdf(xx, shape_x, loc=loc_x, scale=scale_x)
    pdf_y = skewnorm.pdf(yy, shape_y, loc=loc_y, scale=scale_y)
    density = pdf_x * pdf_y
    return x, y, xx, yy, density



def density_levels_from_grid(density, x, y, coverages):
    """Compute contour density thresholds that enclose given probability masses."""
    if density.ndim != 2:
        raise ValueError("density must be a 2D array")

    dx = float(np.mean(np.diff(x)))
    dy = float(np.mean(np.diff(y)))
    cell_area = dx * dy

    flat = density.ravel()
    order = np.argsort(flat)[::-1]
    density_sorted = flat[order]
    prob_sorted = density_sorted * cell_area
    cdf_sorted = np.cumsum(prob_sorted)
    total_prob = float(cdf_sorted[-1]) if len(cdf_sorted) else 0.0
    if total_prob <= 0:
        raise ValueError("Density grid has non-positive total probability")
    cdf_sorted = cdf_sorted / total_prob

    levels = []
    for coverage in coverages:
        idx = int(np.searchsorted(cdf_sorted, coverage, side="left"))
        idx = min(max(idx, 0), len(density_sorted) - 1)
        levels.append(float(density_sorted[idx]))
    return levels



def compute_axis_limits_from_grid_and_points(x_values, y_values, x_grid, y_grid, style):
    """Compute plot limits that include data and the full fit grid."""
    x_abs_max = max(np.nanmax(np.abs(x_values)), np.nanmax(np.abs(x_grid)))
    x_margin = max(style.get("min_x_margin", 1.0), style.get("x_margin_frac", 0.08) * max(x_abs_max, 1e-9))
    if style.get("center_x_zero", True):
        x_max = x_abs_max + x_margin
        x_min = -x_max
    else:
        x_min = float(min(np.nanmin(x_values), np.nanmin(x_grid)) - x_margin)
        x_max = float(max(np.nanmax(x_values), np.nanmax(x_grid)) + x_margin)

    y_min_raw = float(min(np.nanmin(y_values), np.nanmin(y_grid)))
    y_max_raw = float(max(np.nanmax(y_values), np.nanmax(y_grid)))
    y_range = y_max_raw - y_min_raw
    y_margin = max(style.get("min_y_margin", 2.0), style.get("y_margin_frac", 0.08) * max(y_range, 1e-9))
    y_min = y_min_raw - y_margin
    y_max = y_max_raw + y_margin
    return x_min, x_max, y_min, y_max



def skew_summary_row(df, club, model):
    """Compute one historical skew-normal summary row for a single club/model."""
    label = build_label(club, model)
    history_df = df[(df["Club"] == club) & (df["Model"] == model)].copy()
    if len(history_df) < 3:
        return None

    x_values = history_df[X_COL].to_numpy(dtype=float)
    y_values = history_df[Y_COL].to_numpy(dtype=float)

    try:
        x_params = fit_skew_normal(x_values)
        y_params = fit_skew_normal(y_values)
    except ValueError:
        return None

    x_mean = float(skewnorm.mean(*x_params))
    y_mean = float(skewnorm.mean(*y_params))
    if not np.isfinite(x_mean):
        x_mean = float(np.mean(x_values))
    if not np.isfinite(y_mean):
        y_mean = float(np.mean(y_values))

    x1_low, x1_high = skew_interval(*x_params, n_sigma=1.0)
    x2_low, x2_high = skew_interval(*x_params, n_sigma=2.0)
    y1_low, y1_high = skew_interval(*y_params, n_sigma=1.0)
    y2_low, y2_high = skew_interval(*y_params, n_sigma=2.0)

    return {
        "club": club,
        "model": model,
        "label": label,
        "n_shots": len(history_df),
        "mean_distance_m": y_mean,
        "distance_1sigma_min_m": y1_low,
        "distance_1sigma_max_m": y1_high,
        "distance_2sigma_min_m": y2_low,
        "distance_2sigma_max_m": y2_high,
        "mean_lateral_m": x_mean,
        "lateral_1sigma_left_m": x1_low,
        "lateral_1sigma_right_m": x1_high,
        "lateral_2sigma_left_m": x2_low,
        "lateral_2sigma_right_m": x2_high,
        "x_shape": x_params[0],
        "x_loc": x_params[1],
        "x_scale": x_params[2],
        "y_shape": y_params[0],
        "y_loc": y_params[1],
        "y_scale": y_params[2],
    }



def export_historic_summary_csv(df, output_csv=HISTORIC_SUMMARY_CSV):
    """Export the historical skew-normal summary table to CSV."""
    output_csv = Path(output_csv)
    ensure_folder(output_csv.parent)

    rows = []
    master = build_master_club_table(df)
    for _, row in master.iterrows():
        summary = skew_summary_row(df, row["Club"], row["Model"])
        if summary is not None:
            rows.append(summary)

    summary_df = pd.DataFrame(rows)
    if summary_df.empty:
        raise RuntimeError("No valid skew-normal history summary could be created")

    summary_df.to_csv(output_csv, index=False)
    print(f"Saved historic skew-normal summary CSV: {output_csv}")
    return summary_df



def _prepare_sorted_summary_df(summary_df):
    """Sort the skew-normal summary table in the common club/model order."""
    if summary_df is None or len(summary_df) == 0:
        raise RuntimeError("Historic skew-normal summary is empty")

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



def plot_historic_distance_summary(summary_df, output_file=HISTORIC_DISTANCE_SUMMARY_PLOT, style=None):
    """Plot mean carry together with 1σ and 2σ carry ranges for each club/model."""
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

    ax.set_yticks(y)
    ax.set_yticklabels(plot_df["label"], fontsize=style.get("club_label_fontsize", style.get("tick_fontsize", 10)))
    ax.invert_yaxis()
    ax.set_xlabel("Carry Distance (m)", fontsize=style.get("label_fontsize", 11))
    ax.set_ylabel("Club", fontsize=style.get("label_fontsize", 11))
    ax.set_title(style.get("title_distance", "Historic Skew-Normal Distance Summary"), fontsize=style.get("title_fontsize", 13))
    ax.tick_params(axis="x", labelsize=style.get("tick_fontsize", 10))
    _apply_summary_x_grid(ax, style)

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



def plot_historic_lateral_summary(summary_df, output_file=HISTORIC_LATERAL_SUMMARY_PLOT, style=None):
    """Plot mean lateral offset together with 1σ and 2σ lateral ranges for each club/model."""
    if style is None:
        style = SKEW_SUMMARY_STYLE

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
    ax.set_title(style.get("title_lateral", "Historic Skew-Normal Lateral Summary"), fontsize=style.get("title_fontsize", 13))
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



def plot_historic_skewnormal_2d(df, club, model, output_folder, style=None):
    """Create one historic x/y scatter plot with skew-normal density contours."""
    if style is None:
        style = SKEW_2D_STYLE

    label = build_label(club, model)
    history_df = df[(df["Club"] == club) & (df["Model"] == model)].copy()
    if len(history_df) < style.get("min_history_points", 8):
        print(f"Skipping {label}: only {len(history_df)} valid historic shots")
        return

    x_values = history_df[X_COL].to_numpy(dtype=float)
    y_values = history_df[Y_COL].to_numpy(dtype=float)

    try:
        x_params = fit_skew_normal(x_values)
        y_params = fit_skew_normal(y_values)
    except ValueError as exc:
        print(f"Skipping {label}: {exc}")
        return

    x_grid, y_grid, xx, yy, density = build_density_grid(x_values, y_values, x_params, y_params, style)
    coverage_pairs = sorted(SIGMA_COVERAGES_2D.items(), key=lambda item: item[0], reverse=True)
    coverages = [coverage for _, coverage in coverage_pairs]
    levels_desc = density_levels_from_grid(density, x_grid, y_grid, coverages)

    contour_specs = [
        (3.0, levels_desc[0], style["sigma3_color"], style["sigma3_linestyle"], style.get("sigma3_label", "3σ")),
        (2.0, levels_desc[1], style["sigma2_color"], style["sigma2_linestyle"], style.get("sigma2_label", "2σ")),
        (1.0, levels_desc[2], style["sigma1_color"], style["sigma1_linestyle"], style.get("sigma1_label", "1σ")),
    ]

    mean_x = float(np.mean(x_values))
    mean_y = float(np.mean(y_values))

    x_min, x_max, y_min, y_max = compute_axis_limits_from_grid_and_points(
        x_values, y_values, x_grid, y_grid, style
    )

    fig, ax = plt.subplots(figsize=style["figsize"])

    ax.scatter(
        x_values,
        y_values,
        s=style["scatter_size"],
        alpha=style["scatter_alpha"],
        marker=style["scatter_marker"],
        linewidths=style["scatter_linewidth"],
        label=f'{style.get("scatter_label", "Historic shots")} (n={len(history_df)})',
    )

    ax.scatter(
        [mean_x],
        [mean_y],
        marker=style["mean_marker"],
        s=style["mean_size"],
        linewidths=style["mean_linewidth"],
        label=style.get("history_mean_label", "Historic mean"),
        zorder=5,
    )

    if style.get("show_density_fill", False):
        ax.contourf(xx, yy, density, levels=20, alpha=style.get("density_fill_alpha", 0.18))

    for _, level, color, linestyle, label_text in contour_specs:
        cs = ax.contour(
            xx,
            yy,
            density,
            levels=[level],
            colors=[color],
            linestyles=[linestyle],
            linewidths=style["sigma_linewidth"],
        )
        if cs.collections:
            cs.collections[0].set_label(label_text)

    ax.axvline(0.0, alpha=style["axis_line_alpha"], linewidth=style["axis_linewidth"])
    ax.axhline(mean_y, alpha=0.20, linewidth=0.8)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_xlabel(X_COL, fontsize=style.get("label_fontsize", 11))
    ax.set_ylabel(Y_COL, fontsize=style.get("label_fontsize", 11))
    ax.set_title(f"{label}: {style.get('title_prefix', 'Historic Skew-Normal Fit')}", fontsize=style.get("title_fontsize", 13))
    ax.tick_params(axis="both", labelsize=style.get("tick_fontsize", 10))
    ax.grid(True, alpha=style.get("grid_alpha", 0.28))

    stats_text = (
        f"n = {len(history_df)}\n"
        f"mean lateral = {mean_x:.1f} m\n"
        f"mean carry = {mean_y:.1f} m\n"
        f"x-shape = {x_params[0]:.2f}\n"
        f"y-shape = {y_params[0]:.2f}"
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

    if style.get("equal_aspect", False):
        ax.set_aspect("equal", adjustable="box")
    if style.get("show_legend", True):
        ax.legend(fontsize=style.get("legend_fontsize", 10))

    fig.tight_layout()
    output_folder = ensure_folder(Path(output_folder))
    outfile = output_folder / f"skewnormal_history_{sanitize_filename(label)}.png"
    fig.savefig(outfile, dpi=style["save_dpi"])
    print(f"Saved plot: {outfile}")
    if style.get("close_after_save", True):
        plt.close(fig)



def run_all_historic_skewnormal_plots(df, output_folder=OUTPUT_FOLDER, style=None):
    """Generate one historic skew-normal x/y plot per club/model."""
    if style is None:
        style = SKEW_2D_STYLE

    data = prepare_gaussian_data(df, X_COL, Y_COL)
    if data.empty:
        raise RuntimeError("No valid lateral/carry data available after filtering")

    master = build_master_club_table(data)
    for _, row in master.iterrows():
        plot_historic_skewnormal_2d(
            data,
            row["Club"],
            row["Model"],
            output_folder,
            style=style,
        )
    return data



def main():
    """Entry point when the script is run directly."""
    apply_plot_style(SKEW_2D_STYLE)
    df = load_all_sessions()
    data = run_all_historic_skewnormal_plots(df, OUTPUT_FOLDER, SKEW_2D_STYLE)
    summary_df = export_historic_summary_csv(data, output_csv=HISTORIC_SUMMARY_CSV)
    plot_historic_distance_summary(summary_df, output_file=HISTORIC_DISTANCE_SUMMARY_PLOT, style=SKEW_SUMMARY_STYLE)
    plot_historic_lateral_summary(summary_df, output_file=HISTORIC_LATERAL_SUMMARY_PLOT, style=SKEW_SUMMARY_STYLE)


if __name__ == "__main__":
    main()
