"""Wind and elevation carry-adjustment charts for the indoor golf dataset.

This script estimates carry-distance adjustments for each selected club/model as a
function of:
1. target height difference (uphill / downhill)
2. headwind / tailwind speed

The script is intentionally transparent and easy to tune:
- the elevation model is geometric and uses the measured descent angle
- the wind model is empirical and uses measured flight time and peak height
- all user-adjustable assumptions are grouped near the top of the file

Outputs
-------
The script writes three files into ../Plot/Indoor/WindElevationAdjustment/
- carry_adjustment_summary.csv
- carry_adjustment_elevation_chart.csv
- carry_adjustment_wind_chart.csv

It also writes two quick-look PNG plots:
- carry_adjustment_elevation_chart.png
- carry_adjustment_wind_chart.png

Notes
-----
Elevation model
    carry_change_per_1m_height = 1 / tan(descent_angle)
    uphill is negative, downhill is positive

Wind model
    carry_change_per_1mps_wind = a + b * flight_time_s + c * peak_height_m

    Separate coefficient sets are used for tailwind and headwind to capture the
    usual asymmetry that headwind hurts more than an equal tailwind helps.

    The default coefficients were chosen from the user's own launch-monitor
    dataset and are meant as a practical starting point rather than a full
    aerodynamic solver.
"""

from __future__ import annotations

from pathlib import Path
import math
from typing import Iterable, List

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from analysis_config import PLOT_ROOT
from analysis_io import load_all_sessions, prepare_base_data
from analysis_utils import build_master_club_table, build_label, ensure_folder, apply_plot_style


# ---------------------------------------------------------------------------
# User-adjustable settings
# ---------------------------------------------------------------------------
OUTPUT_FOLDER = PLOT_ROOT / "WindElevationAdjustment"
LOCAL_FALLBACK_GLOB = "Golf Lesson -*_windows-1252.csv"

# Positive values only. The script automatically creates both uphill/downhill
# and headwind/tailwind columns.
HEIGHT_DIFFERENCES_M: List[float] = [1.0, 2.0, 5.0, 10.0]
WIND_SPEEDS_KMH: List[float] = [5.0, 10.0, 20.0]

# Optional extra wind speeds in m/s if preferred. Leave empty to only use km/h.
WIND_SPEEDS_MPS: List[float] = []

# Robust aggregation for club-level statistics.
# Supported: "mean" or "median"
AGGREGATION_METHOD = "mean"

# Elevation model settings.
MIN_DESCENT_DEG = 5.0
MAX_DESCENT_DEG = 85.0

# Empirical wind model.
# Sensitivity in carry meters per 1 m/s wind speed.
# Formula: sensitivity = intercept + flight_time_coeff * flight_time_s
#                        + peak_height_coeff * peak_height_m
# Negative results are clipped to zero.
TAILWIND_MODEL = {
    "intercept": 0.22338827,
    "flight_time_coeff": -0.56338722,
    "peak_height_coeff": 0.19971129,
}
HEADWIND_MODEL = {
    "intercept": 0.29436174,
    "flight_time_coeff": -0.49391676,
    "peak_height_coeff": 0.19633605,
}

# Plot style.
STYLE = {
    "figsize": (12, 7),
    "save_dpi": 220,
    "grid_alpha": 0.28,
    "title_fontsize": 13,
    "label_fontsize": 11,
    "tick_fontsize": 10,
    "legend_fontsize": 10,
    "tight_layout": True,
    "line_width": 1.8,
    "marker": "o",
    "marker_size": 5,
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def aggregate_series(series: pd.Series, method: str = "mean") -> float:
    """Aggregate one numeric series with the selected robust statistic."""
    values = pd.to_numeric(series, errors="coerce")
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return float("nan")
    if method == "median":
        return float(np.median(values))
    if method == "mean":
        return float(np.mean(values))
    raise ValueError(f"Unsupported aggregation method: {method}")



def kmh_to_mps(speed_kmh: float) -> float:
    """Convert km/h to m/s."""
    return float(speed_kmh) / 3.6



def elevation_sensitivity_from_descent(descent_deg: float) -> float:
    """Return carry change in meters per 1 m target height difference.

    Uses the geometric relation:
        delta_carry = delta_height / tan(descent_angle)
    """
    descent_deg = float(descent_deg)
    if not np.isfinite(descent_deg):
        return float("nan")
    descent_deg = min(max(descent_deg, MIN_DESCENT_DEG), MAX_DESCENT_DEG)
    tan_val = math.tan(math.radians(descent_deg))
    if abs(tan_val) < 1e-9:
        return float("nan")
    return 1.0 / tan_val



def wind_sensitivity_per_mps(flight_time_s: float, peak_height_m: float, coeffs: dict) -> float:
    """Return carry change in meters per 1 m/s wind speed.

    This is an empirical club-level model meant to be easy to tune.
    """
    value = (
        float(coeffs["intercept"])
        + float(coeffs["flight_time_coeff"]) * float(flight_time_s)
        + float(coeffs["peak_height_coeff"]) * float(peak_height_m)
    )
    return max(0.0, value)





def load_sessions_with_fallback() -> pd.DataFrame:
    """Load indoor sessions from the configured folder or local uploaded CSV files."""
    try:
        return load_all_sessions()
    except RuntimeError as exc:
        local_files = sorted(Path(__file__).resolve().parent.glob(LOCAL_FALLBACK_GLOB))
        if not local_files:
            raise
        print(f"Primary data folder unavailable ({exc}). Falling back to local CSV files.")
        from readfiles_260322 import read_shot_file
        frames = []
        for file in local_files:
            print(f"Loading local fallback file: {file}")
            frames.append(read_shot_file(file))
        return pd.concat(frames, ignore_index=True)


def build_club_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Build one row of carry / trajectory statistics per club/model."""
    required_cols = ["Carry [m]", "Descent V [deg]", "Flight Time [sec]", "Height [m]"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Expected column '{col}' not found in data")

    rows = []
    master = build_master_club_table(df)
    for _, row in master.iterrows():
        club = row["Club"]
        model = row["Model"]
        label = build_label(club, model)
        club_df = df[(df["Club"] == club) & (df["Model"] == model)].copy()
        if club_df.empty:
            continue

        carry_m = aggregate_series(club_df["Carry [m]"], AGGREGATION_METHOD)
        descent_deg = aggregate_series(club_df["Descent V [deg]"], AGGREGATION_METHOD)
        flight_time_s = aggregate_series(club_df["Flight Time [sec]"], AGGREGATION_METHOD)
        peak_height_m = aggregate_series(club_df["Height [m]"], AGGREGATION_METHOD)
        shot_count = int(club_df["Carry [m]"].notna().sum())

        elevation_sens = elevation_sensitivity_from_descent(descent_deg)
        tailwind_sens = wind_sensitivity_per_mps(flight_time_s, peak_height_m, TAILWIND_MODEL)
        headwind_sens = wind_sensitivity_per_mps(flight_time_s, peak_height_m, HEADWIND_MODEL)

        rows.append({
            "Club": club,
            "Model": model,
            "label": label,
            "n_shots": shot_count,
            "avg_carry_m": carry_m,
            "avg_descent_deg": descent_deg,
            "avg_flight_time_s": flight_time_s,
            "avg_peak_height_m": peak_height_m,
            "elevation_m_per_m": elevation_sens,
            "tailwind_m_per_mps": tailwind_sens,
            "headwind_m_per_mps": headwind_sens,
        })

    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("No club summary could be created")
    return out



def build_elevation_chart(summary_df: pd.DataFrame, height_differences_m: Iterable[float]) -> pd.DataFrame:
    """Create uphill and downhill carry-adjustment columns."""
    out = summary_df[[
        "label", "n_shots", "avg_carry_m", "avg_descent_deg", "elevation_m_per_m"
    ]].copy()

    for dh in height_differences_m:
        dh = float(dh)
        out[f"uphill_{dh:g}m"] = -dh * out["elevation_m_per_m"]
        out[f"downhill_{dh:g}m"] = dh * out["elevation_m_per_m"]

    return out



def build_wind_chart(summary_df: pd.DataFrame, wind_speeds_kmh: Iterable[float], wind_speeds_mps: Iterable[float]) -> pd.DataFrame:
    """Create headwind and tailwind carry-adjustment columns."""
    out = summary_df[[
        "label", "n_shots", "avg_carry_m", "avg_flight_time_s", "avg_peak_height_m",
        "tailwind_m_per_mps", "headwind_m_per_mps"
    ]].copy()

    for speed_kmh in wind_speeds_kmh:
        speed_kmh = float(speed_kmh)
        speed_mps = kmh_to_mps(speed_kmh)
        out[f"tailwind_{speed_kmh:g}kmh"] = speed_mps * out["tailwind_m_per_mps"]
        out[f"headwind_{speed_kmh:g}kmh"] = -speed_mps * out["headwind_m_per_mps"]

    for speed_mps in wind_speeds_mps:
        speed_mps = float(speed_mps)
        out[f"tailwind_{speed_mps:g}mps"] = speed_mps * out["tailwind_m_per_mps"]
        out[f"headwind_{speed_mps:g}mps"] = -speed_mps * out["headwind_m_per_mps"]

    return out



def _plot_adjustment_lines(
    chart_df: pd.DataFrame,
    x_cols: List[str],
    title: str,
    xlabel: str,
    output_file: Path,
    style: dict,
) -> None:
    """Create a quick-look multi-line chart for the selected adjustment columns."""
    fig, ax = plt.subplots(figsize=style["figsize"])
    x = np.arange(len(chart_df))

    for col in x_cols:
        ax.plot(
            x,
            chart_df[col],
            marker=style.get("marker", "o"),
            markersize=style.get("marker_size", 5),
            linewidth=style.get("line_width", 1.8),
            label=col,
        )

    ax.axhline(0.0, linewidth=1.0, alpha=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(chart_df["label"], rotation=45, ha="right")
    ax.set_title(title, fontsize=style.get("title_fontsize", 13))
    ax.set_xlabel("Club / Model", fontsize=style.get("label_fontsize", 11))
    ax.set_ylabel(xlabel, fontsize=style.get("label_fontsize", 11))
    ax.tick_params(axis="both", labelsize=style.get("tick_fontsize", 10))
    ax.grid(True, alpha=style.get("grid_alpha", 0.28))
    ax.legend(fontsize=style.get("legend_fontsize", 10), ncol=2)

    if style.get("tight_layout", True):
        fig.tight_layout()

    ensure_folder(output_file.parent)
    fig.savefig(output_file, dpi=style.get("save_dpi", 220), bbox_inches="tight")
    plt.close(fig)
    print(f"Saved plot: {output_file}")


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------
def main() -> None:
    """Run the wind and elevation carry-adjustment workflow."""
    apply_plot_style(STYLE)
    ensure_folder(OUTPUT_FOLDER)

    df = prepare_base_data(load_sessions_with_fallback())
    summary_df = build_club_summary(df)
    elevation_df = build_elevation_chart(summary_df, HEIGHT_DIFFERENCES_M)
    wind_df = build_wind_chart(summary_df, WIND_SPEEDS_KMH, WIND_SPEEDS_MPS)

    summary_file = OUTPUT_FOLDER / "carry_adjustment_summary.csv"
    elevation_file = OUTPUT_FOLDER / "carry_adjustment_elevation_chart.csv"
    wind_file = OUTPUT_FOLDER / "carry_adjustment_wind_chart.csv"

    summary_df.to_csv(summary_file, index=False)
    elevation_df.to_csv(elevation_file, index=False)
    wind_df.to_csv(wind_file, index=False)

    print(f"Saved summary table: {summary_file}")
    print(f"Saved elevation chart table: {elevation_file}")
    print(f"Saved wind chart table: {wind_file}")

    elevation_cols = [
        col for col in elevation_df.columns
        if col.startswith("uphill_") or col.startswith("downhill_")
    ]
    wind_cols = [
        col for col in wind_df.columns
        if col.startswith("tailwind_") or col.startswith("headwind_")
    ]

    _plot_adjustment_lines(
        elevation_df,
        elevation_cols,
        title="Carry Adjustment vs Height Difference",
        xlabel="Carry adjustment (m)",
        output_file=OUTPUT_FOLDER / "carry_adjustment_elevation_chart.png",
        style=STYLE,
    )
    _plot_adjustment_lines(
        wind_df,
        wind_cols,
        title="Carry Adjustment vs Wind Speed",
        xlabel="Carry adjustment (m)",
        output_file=OUTPUT_FOLDER / "carry_adjustment_wind_chart.png",
        style=STYLE,
    )


if __name__ == "__main__":
    main()
