"""Data models for tribo-test results."""

import os
import re
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import savgol_filter
from scipy.ndimage import uniform_filter1d, median_filter


@dataclass
class TribSample:
    """One loaded tribo-test sample."""
    filepath: str
    name: str
    date: str = ""
    num_points: int = 0
    time_ms: np.ndarray = field(default_factory=lambda: np.array([]))
    friction: np.ndarray = field(default_factory=lambda: np.array([]))
    friction_path_m: np.ndarray = field(default_factory=lambda: np.array([]))
    friction_smooth: np.ndarray = field(default_factory=lambda: np.array([]))

    smooth_enabled: bool = False
    smooth_method: str = "savgol"
    smooth_window: int = 21
    smooth_polyorder: int = 3

    # Wear data (from scar analyzer)
    wear_L: float = 0.0
    wear_W: float = 0.0
    wear_h: float = 0.0
    wear_S: float = 0.0
    wear_V: float = 0.0
    # Tribological wear metrics
    wear_D_m: float = 0.0
    wear_A_J: float = 0.0
    wear_P_W: float = 0.0
    wear_I_h: float = 0.0
    wear_I_A: float = 0.0
    wear_eps: float = 0.0
    wear_k: float = 0.0
    wear_mu_avg: float = 0.0
    wear_mu_std: float = 0.0
    wear_mu_cov: float = 0.0
    wear_V_D: float = 0.0
    wear_eps_V: float = 0.0    # volume wear resistance D/V (m/μm³)
    wear_p_MPa: float = 0.0
    wear_t_steady_s: float = 0.0
    wear_mu_amplitude: float = 0.0
    wear_stick_slip: str = ""

    # Instrument specification errors
    wear_mu_err: float = 0.02
    wear_D_err: float = 0.0  # 1% of D_m, computed

    # Measurement errors (propagated)
    err_h_mm: float = 0.0
    err_S_mm2: float = 0.0
    err_V_mm3: float = 0.0
    err_L_mm: float = 0.0
    err_W_mm: float = 0.0
    wear_A_err: float = 0.0
    wear_P_err: float = 0.0
    wear_p_err: float = 0.0
    err_grav_delta_m: float = 0.1  # balance precision (mg)
    wear_k_err: float = 0.0
    wear_I_h_err: float = 0.0
    wear_I_A_err: float = 0.0
    wear_eps_err: float = 0.0
    wear_V_D_err: float = 0.0
    wear_eps_V_err: float = 0.0

    # Gravimetric wear data
    grav_m_before_mg: float = 0.0   # mass before test (mg)
    grav_m_after_mg: float = 0.0    # mass after test (mg)
    grav_density_g_cm3: float = 0.0 # material density (g/cm³)
    grav_error_mg: float = 0.0      # balance precision (mg)
    # Computed gravimetric results
    grav_delta_m_mg: float = 0.0    # mass loss (mg)
    grav_V_mm3: float = 0.0         # wear volume (mm³)
    grav_delta_V_mm3: float = 0.0   # volume error (mm³)
    grav_k_mm3_N_m: float = 0.0     # specific wear rate (mm³/N·m)
    grav_delta_k: float = 0.0       # specific wear rate error

    source_file: str = ""

    # Cache for friction regimes
    _regimes_cache: list = field(default_factory=list)


@dataclass
class TestParams:
    """Experimental parameters for disc-on-plane geometry."""
    disk_diameter_mm: float = 60.0
    load_mN: float = 200.0
    test_time_s: float = 1500.0
    rotation_speed_rev_s: float = 0.5
    track_width_mm: float = 0.0
    dt: float = 0.0  # time step between data points (s)
    edge_radius_mm: float = 0.0  # disc edge rounding radius (mm)