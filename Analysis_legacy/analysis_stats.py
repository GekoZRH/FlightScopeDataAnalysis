"""Statistical helper functions used across the golf analysis package."""

import numpy as np


def compute_history_stats(df, metric_col, prefix="history"):
    """Compute mean, standard deviation and count for each club/model history.

    The output is one row per club/model combination.
    """
    if metric_col not in df.columns:
        raise ValueError(f"Expected column '{metric_col}' not found in data")

    data = df.dropna(subset=[metric_col]).copy()
    return (
        data.groupby(["Club", "Model"])[metric_col]
        .agg(["mean", "std", "count"])
        .reset_index()
        .rename(columns={
            "mean": f"{prefix}_mean",
            "std": f"{prefix}_std",
            "count": f"{prefix}_count",
        })
    )


def compute_session_stats(df, metric_col):
    """Compute mean, standard deviation and count for each session and club/model."""
    if metric_col not in df.columns:
        raise ValueError(f"Expected column '{metric_col}' not found in data")

    data = df.dropna(subset=["session_date", metric_col]).copy()
    return (
        data.groupby(["session_date", "Club", "Model"])[metric_col]
        .agg(["mean", "std", "count"])
        .reset_index()
        .rename(columns={
            "mean": "session_mean",
            "std": "session_std",
            "count": "session_count",
        })
    )


def compute_mean_and_cov(points):
    """Compute the mean vector and 2x2 covariance matrix of 2D shot data.

    A very small diagonal value is added to the covariance matrix for numerical
    stability, which helps avoid plotting issues for nearly collinear data.
    """
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("Points must have shape (N, 2)")
    if len(points) < 2:
        raise ValueError("At least two points are required to compute covariance")

    mu = np.mean(points, axis=0)
    cov = np.cov(points.T)
    cov = np.asarray(cov, dtype=float)
    if cov.shape != (2, 2):
        raise ValueError("Covariance must be 2x2")

    return mu, cov + np.eye(2) * 1e-9
