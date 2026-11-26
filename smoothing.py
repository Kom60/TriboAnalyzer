"""Smoothing functions for friction data."""

import numpy as np
from scipy.signal import savgol_filter
from scipy.ndimage import uniform_filter1d, median_filter

from models import TribSample

SMOOTH_METHODS = {
    "savgol": "Савицкий-Голей",
    "moving": "Скользящее среднее",
    "median": "Медианный фильтр",
}


def apply_smoothing(sample: TribSample) -> np.ndarray:
    """Apply smoothing to friction data based on sample settings."""
    data = sample.friction
    n = len(data)
    if n < 3 or not sample.smooth_enabled:
        sample.friction_smooth = data.copy()
        return sample.friction_smooth

    w = sample.smooth_window
    if w > n:
        w = n if n % 2 == 1 else n - 1
    if w < 3:
        w = 3
    if w % 2 == 0:
        w += 1

    method = sample.smooth_method
    if method == "savgol":
        poly = min(sample.smooth_polyorder, w - 1)
        sample.friction_smooth = savgol_filter(data, w, poly)
    elif method == "moving":
        sample.friction_smooth = uniform_filter1d(data, size=w)
    elif method == "median":
        sample.friction_smooth = median_filter(data, size=w)
    else:
        sample.friction_smooth = data.copy()

    return sample.friction_smooth