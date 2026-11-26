"""Friction path computation."""

import math
import numpy as np

from models import TribSample, TestParams


def compute_friction_path(sample: TribSample, params: TestParams) -> np.ndarray:
    """s(t) = omega * R * t"""
    omega = 2.0 * math.pi * params.rotation_speed_rev_s
    R = (params.disk_diameter_mm / 2.0) / 1000.0
    t_s = sample.time_ms / 1000.0
    sample.friction_path_m = omega * R * t_s
    return sample.friction_path_m