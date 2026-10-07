"""Data loading and pre-processing helpers.

The functions here separate file handling from the plotting logic. This keeps
plot scripts focused on analysis and makes the data preparation steps easier to
understand and modify.
"""

from pathlib import Path
import pandas as pd

from analysis_config import DATA_FOLDER, FORESIGHT_FOLDER, FORESIGHT_GLOB, FORESIGHT_DISTANCE_UNIT, SELECTED_CLUB_LABELS
from readfiles import read_shot_file, read_foresight_file




def _normalize_selected_labels():
    """Return selected full club labels as normalized lowercase strings."""
    return [str(label).strip().lower() for label in SELECTED_CLUB_LABELS if str(label).strip()]

def load_all_sessions(data_folder=DATA_FOLDER):
    """Read all indoor swing CSV files and concatenate them into one DataFrame."""
    files = sorted(Path(data_folder).glob("*.csv"))
    if not files:
        raise RuntimeError(f"No CSV files found in {data_folder}")

    frames = []
    for file in files:
        print(f"Loading file: {file}")
        frames.append(read_shot_file(file))
    return pd.concat(frames, ignore_index=True)


def load_foresight_reference(folder=FORESIGHT_FOLDER, pattern=FORESIGHT_GLOB, distance_unit=FORESIGHT_DISTANCE_UNIT):
    """Read all Foresight reference files and concatenate them into one DataFrame."""
    files = sorted(Path(folder).glob(pattern))
    if not files:
        raise RuntimeError(f"No Foresight reference files found in {folder} with pattern {pattern}")

    frames = []
    for file in files:
        print(f"Loading Foresight reference file: {file}")
        frame = read_foresight_file(file, distance_unit=distance_unit)
        frame["reference_file"] = file.name
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)



def prepare_base_data(df, require_session_date=True):
    """Clean the basic club/model/session structure used by most analyses.

    This function makes sure the expected identifier columns exist and strips
    empty club names that would otherwise create meaningless plot entries.

    If SELECTED_CLUB_LABELS in analysis_config.py is not empty, the returned
    data is filtered so only those exact club/model labels remain.
    """
    required = ["Club", "Model"]
    if require_session_date:
        required = ["session_date"] + required
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    out = df.copy()
    out["Club"] = out["Club"].fillna("").astype(str).str.strip()
    out["Model"] = out["Model"].fillna("").astype(str).str.strip()
    out = out[out["Club"] != ""].copy()

    selected_labels = _normalize_selected_labels()
    if selected_labels:
        out["label"] = out.apply(lambda row: f"{row['Club']} {row['Model']}".strip().lower(), axis=1)
        out = out[out["label"].isin(selected_labels)].copy()
        out = out.drop(columns=["label"])

    return out



def prepare_gaussian_data(df, x_col, y_col):
    """Prepare numeric x/y columns for the Gaussian shot-distribution analysis."""
    out = prepare_base_data(df)
    for col in [x_col, y_col]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["session_date", x_col, y_col]).copy()
    return out


def prepare_trend_data(df):
    """Convert session_date to datetime for trend plots and drop invalid rows."""
    out = prepare_base_data(df)
    out["session_date"] = pd.to_datetime(out["session_date"], errors="coerce")
    out = out.dropna(subset=["session_date"]).copy()
    return out


def prepare_foresight_data(df):
    """Prepare Foresight reference data without requiring session_date."""
    return prepare_base_data(df, require_session_date=False)
