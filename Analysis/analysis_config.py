"""Shared configuration for the indoor golf shot analysis package.

This file is the main place to control:
- where the data is read from
- where plots are written to
- how clubs are ordered in plots
- which metrics are analysed
- the default style of each plot family

Keeping these settings in one file makes the rest of the code easier to
maintain and avoids repeated definitions across multiple scripts.
"""

from pathlib import Path

# Base folders relative to the Analysis/ folder.
# The scripts assume they are run from inside ./Analysis.
DATA_FOLDER = Path("../SwingData/Indoor")
FORESIGHT_FOLDER = Path("../SwingData/Foresight")
PLOT_ROOT = Path("../Plot/Indoor")

# Shared club ordering used across all summary and comparison plots.
# Unknown clubs are placed at the end.
CLUB_ORDER = [
    "driver",
    "3w", "5w", "7w",
    "2h", "3h", "4h", "5h",
    "2i", "3i", "4i", "5i", "6i", "7i", "8i", "9i",
    "pw", "aw", "gw", "sw", "lw",
]

# Optional model ordering inside one club family.
# Any model not listed here is sorted after the known models.
MODEL_ORDER = {
    "245": 0,
    "sc": 1,
    "241": 2,
    "241_11": 3,
    "241_10": 4,
    "241_9": 5,
    "50": 6,
    "50_11": 7,
    "50_10": 8,
    "50_9": 9,
    "54": 10,
    "54_11": 11,
    "54_10": 12,
    "54_9": 14,
    "58": 15,
    "58_11": 16,
    "58_10": 17,
    "58_9": 18,
}



# Exact club-label selection across the whole analysis package.
# Labels use the same format as the plot labels, i.e. "club model".
# Examples:
#   "8i 245"
#   "8i 241"
#   "driver ping"
#
# If this list is not empty, ONLY these exact labels are analysed and plotted.
# Matching is case-insensitive.
SELECTED_CLUB_LABELS = [
    "LW 58_9",
    "LW 58_10",
    "LW 58_11",
    "LW 58",
    "SW 54_9",
    "SW 54_10",
    "SW 54_11",
    "SW 54",
    "GW 50_9",
    "GW 50_10",
    "GW 50_11",
    "GW 50",
    "PW 241_9",
    "PW 241_10",
    "PW 241_11",
    "PW 241",
    "9i 241_11",
    "9i 241",
    "8i 241_11",
    "8i 241",
    "8i 245",
    "7i 245",
    "6i 245",
    "5i 245",
    "4i 245",
    "4H Maverik",
    "5W TS2",
    "3W TS2",
    "Driver Ping", 
]

# Common metric definitions used for session-vs-history and trend plots.
# The dictionary structure keeps titles, labels and output file names together.
METRICS = {
    "Carry [m]": {
        "short_name": "carry",
        "ylabel": "Carry Distance (m)",
        "title": "Carry Distance",
    },
    "Club Speed [mph]": {
        "short_name": "club_speed",
        "ylabel": "Club Speed (mph)",
        "title": "Club Speed",
    },
    "Ball Speed [mph]": {
        "short_name": "ball_speed",
        "ylabel": "Ball Speed (mph)",
        "title": "Ball Speed",
    },
    "Descent V [deg]": {
        "short_name": "descent_v",
        "ylabel": "Descent Angle (deg)",
        "title": "Descent Angle",
    },
    "Height [m]": {
        "short_name": "height",
        "ylabel": "Peak Height (m)",
        "title": "Peak Height",
    },
    "Spin [rpm]": {
        "short_name": "spin",
        "ylabel": "Spin (rpm)",
        "title": "Spin",
    },
}

# Metrics used in the session-to-session trend analysis.
TREND_METRICS = {
    key: METRICS[key]
    for key in [
        "Club Speed [mph]",
        "Ball Speed [mph]",
        "Descent V [deg]",
        "Height [m]",
        "Spin [rpm]",
    ]
}

# Metrics used when indoor data is compared against Foresight reference data.
FORESIGHT_COMPARISON_METRICS = {
    "Ball Speed [mph]": {
        "short_name": "foresight_ball_speed",
        "ylabel": "Ball Speed (mph)",
        "title": "Ball Speed",
    },
    "Spin [rpm]": {
        "short_name": "foresight_backspin",
        "ylabel": "Backspin (rpm)",
        "title": "Backspin",
    },
    "Carry [m]": {
        "short_name": "foresight_carry",
        "ylabel": "Carry Distance (m)",
        "title": "Carry Distance",
    },
}

# ---------------------------------------------------------------------------
# Plot style dictionaries
# ---------------------------------------------------------------------------
# The fontsize keys were added explicitly so axis-title size, axis-label size
# and tick-label size can be changed from one central location.
#
# Meaning of the keys:
# - title_fontsize: plot title size
# - label_fontsize: x/y axis label size
# - tick_fontsize: x/y tick label size
# - legend_fontsize: legend text size
# ---------------------------------------------------------------------------

SESSION_VS_HISTORY_STYLE = {
    "figsize": (14, 7),
    "history_fmt": "o-",
    "session_fmt": "s--",
    "capsize": 4,
    "grid_alpha": 0.3,
    "xtick_rotation": 45,
    "history_label": "Overall history",
    "history_linewidth": 1.8,
    "session_linewidth": 1.8,
    "save_dpi": 200,
    "show_legend": True,
    "title_fontsize": 13,
    "label_fontsize": 11,
    "tick_fontsize": 10,
    "legend_fontsize": 10,
    "x_minor_grid_step_m": 10.0,
    "show_minor_grid": True,
    "mean_connect_linewidth": 1.5,
}

TREND_STYLE = {
    "figsize": (14, 7),
    "fmt": "o-",
    "capsize": 4,
    "linewidth": 1.8,
    "markersize": 6,
    "grid_alpha": 0.3,
    "save_dpi": 200,
    "show_count_labels": False,
    "count_label_fontsize": 8,
    "date_rotation": 45,
    "tight_layout": True,
    "date_format": "%Y-%m-%d",
    "title_fontsize": 13,
    "label_fontsize": 11,
    "tick_fontsize": 10,
    "legend_fontsize": 10,
    "min_sessions_to_plot": 1,
    "ylim": None,
}

GAUSSIAN_STYLE = {
    "figsize": (9.5, 8),
    "save_dpi": 220,
    "close_after_save": True,
    "scatter_marker": "o",
    "scatter_size": 34,
    "scatter_alpha": 0.9,
    "scatter_linewidth": 0.5,
    "scatter_label": "Session shots",
    "mean_marker": "x",
    "mean_size": 110,
    "mean_linewidth": 2.0,
    "history_mean_label": "History mean",
    "sigma1_color": "tab:orange",
    "sigma2_color": "tab:red",
    "sigma3_color": "tab:purple",
    "sigma1_linestyle": "-",
    "sigma2_linestyle": "--",
    "sigma3_linestyle": ":",
    "sigma_linewidth": 1.8,
    "sigma1_label": "1σ",
    "sigma2_label": "2σ",
    "sigma3_label": "3σ",
    "grid_alpha": 0.28,
    "axis_line_alpha": 0.7,
    "axis_linewidth": 1.0,
    "equal_aspect": False,
    "show_legend": True,
    "xlim": None,
    "ylim": None,
    "center_x_zero": True,
    "x_margin_frac": 0.08,
    "y_margin_frac": 0.08,
    "min_x_margin": 1.0,
    "min_y_margin": 2.0,
    "n_sigma_for_limits": 3.0,
    "min_history_points": 5,
    "min_session_points": 1,
    "title_fontsize": 13,
    "label_fontsize": 11,
    "tick_fontsize": 10,
    "legend_fontsize": 10,
}

GAUSSIAN_SUMMARY_STYLE = {
    "figsize": (9, 13.5),
    "save_dpi": 300,
    "close_after_save": True,
    "grid_alpha": 1.0,
    "grid_linewidth": 3.0,
    "mean_marker": "o",
    "mean_markersize": 10,
    "mean_linewidth": 1.8,
    "sigma1_linewidth": 5.0,
    "sigma2_linewidth": 9.0,
    "club_label_fontsize": 20,
    "show_legend": False,
    "x_margin": 5.0,
    "tight_layout": True,
    "title_fontsize": 13,
    "label_fontsize": 16,
    "tick_fontsize": 20,
    "legend_fontsize": 10,
}

FORESIGHT_STYLE = {
    "figsize": (14, 7),
    "history_fmt": "o-",
    "foresight_fmt": "D",
    "capsize": 4,
    "grid_alpha": 0.3,
    "xtick_rotation": 45,
    "history_linewidth": 1.8,
    "foresight_markersize": 7,
    "save_dpi": 200,
    "show_legend": True,
    "title_fontsize": 13,
    "label_fontsize": 11,
    "tick_fontsize": 10,
    "legend_fontsize": 10,
}

# Columns used in the Gaussian analysis.
# X = lateral direction, Y = carry distance.
X_COL = "Lateral [m]"
Y_COL = "Carry [m]"

# Foresight file handling.
FORESIGHT_GLOB = "*.CSV"
FORESIGHT_DISTANCE_UNIT = "m"
