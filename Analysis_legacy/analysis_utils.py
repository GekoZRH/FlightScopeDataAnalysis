"""Utility helpers shared by several analysis scripts.

Most functions in this file are intentionally small and focused. They mainly
handle repetitive infrastructure tasks such as sorting clubs, creating output
folders and applying a consistent matplotlib font setup.
"""

import re
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

from analysis_config import CLUB_ORDER, MODEL_ORDER, SELECTED_CLUB_LABELS


def club_sort_key(club_name):
    """Return a stable sort index for one club name.

    Clubs listed in CLUB_ORDER keep the desired order. Unknown club names are
    pushed to the end so they do not break the plotting logic.
    """
    try:
        return CLUB_ORDER.index(club_name)
    except ValueError:
        return 999


def model_sort_key(model_name):
    """Return a stable sort key for one club model.

    Known model names follow MODEL_ORDER. Missing or unknown model names are
    placed after the known models.
    """
    if pd.isna(model_name):
        return (999, "")
    m = str(model_name).strip().lower()
    return (MODEL_ORDER.get(m, 999), m)


def build_label(club, model):
    """Build a human-readable label such as '7i 245' or 'driver'."""
    model = "" if pd.isna(model) else str(model).strip()
    if model == "":
        return str(club)
    return f"{club} {model}"




def normalize_selected_labels():
    """Return selected full club labels as normalized lowercase strings."""
    return [str(label).strip().lower() for label in SELECTED_CLUB_LABELS if str(label).strip()]


def filter_master_club_table(master):
    """Filter a club/model summary table by selected exact club labels.

    If SELECTED_CLUB_LABELS is empty the input table is returned unchanged.
    """
    selected_labels = normalize_selected_labels()
    if not selected_labels:
        return master.reset_index(drop=True)

    out = master.copy()
    if "label" not in out.columns:
        out["label"] = out.apply(lambda row: build_label(row["Club"], row["Model"]), axis=1)
    out["__label_norm__"] = out["label"].astype(str).str.strip().str.lower()
    out = out[out["__label_norm__"].isin(selected_labels)].copy()
    out = out.drop(columns=["__label_norm__"])
    return out.reset_index(drop=True)

def build_master_club_table(*dfs):
    """Create one combined club/model table from one or more DataFrames.

    The returned table is used as the common backbone for consistent plot order.
    It contains one row per unique club/model combination and also stores sort
    keys and a display label.
    """
    frames = []
    for df in dfs:
        if df is None or df.empty:
            continue
        frames.append(df[["Club", "Model"]].drop_duplicates().copy())

    if not frames:
        return pd.DataFrame(columns=["Club", "Model", "club_sort", "model_sort", "label"])

    master = pd.concat(frames, ignore_index=True).drop_duplicates().copy()
    master["club_sort"] = master["Club"].apply(club_sort_key)
    master["model_sort"] = master["Model"].apply(model_sort_key)
    master = master.sort_values(by=["club_sort", "model_sort", "Model"]).reset_index(drop=True)
    master["label"] = master.apply(lambda row: build_label(row["Club"], row["Model"]), axis=1)
    master = filter_master_club_table(master)
    return master


def sanitize_filename(text):
    """Convert arbitrary text into a safe file name.

    This is mainly used for output plots where club labels may contain spaces or
    special characters.
    """
    text = str(text)
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text.strip("_") or "plot"


def ensure_folder(folder):
    """Create a folder and all missing parent folders if necessary."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def session_folder(root, session_date):
    """Return the output folder for one session date and create it if needed."""
    return ensure_folder(Path(root) / str(session_date))


def apply_plot_style(style):
    """Apply shared matplotlib font sizes from one style dictionary.

    This provides a single place to control axis-title, axis-label and tick
    sizes. The user can change the values in analysis_config.py and all plots
    using this helper will follow automatically.
    """
    plt.rcParams.update({
        "axes.titlesize": style.get("title_fontsize", 13),
        "axes.labelsize": style.get("label_fontsize", 11),
        "xtick.labelsize": style.get("tick_fontsize", 10),
        "ytick.labelsize": style.get("tick_fontsize", 10),
        "legend.fontsize": style.get("legend_fontsize", 10),
    })
