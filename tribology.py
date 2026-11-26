"""Tribological wear calculations."""

import math
import numpy as np

from models import TribSample, TestParams
from friction_path import compute_friction_path
from wear_calc import calc_gravimetric_error


def compute_tribology_wear(sample: TribSample, params: TestParams, h_mm: float, V_mm3: float, V_mm3_edge: float = 0.0) -> dict:
    """
    Compute tribological wear metrics.

    Returns dict with:
    - D_m: sliding distance (m)
    - A_J: friction work (J) — integral μ·F·ds
    - P_W: friction power (W)
    - I_h: wear intensity per distance (μm/m)
    - I_A: wear intensity per work (μm/J)
    - eps: wear resistance (m/μm)
    - k: Archard wear coefficient (mm³/N·m)
    - mu_avg: average friction coefficient
    - mu_std: std of friction coefficient
    - mu_cov: coefficient of variation
    - I_V: volume wear intensity V/D (μm³/m)
    - eps_V: volume wear resistance D/V (m/μm³)
    - V_D: wear volume per distance (mm³/m)
    - p_MPa: contact pressure (MPa)
    - t_steady_s: time to steady state (s)
    - mu_amplitude: fluctuation amplitude
    - stick_slip: stick-slip detected (bool)
    """
    if len(sample.friction) == 0:
        return {}

    # Ensure friction path is computed
    if len(sample.friction_path_m) != len(sample.friction):
        compute_friction_path(sample, params)

    if len(sample.friction_path_m) == 0:
        return {}

    mu_data = sample.friction_smooth if sample.smooth_enabled and len(sample.friction_smooth) > 0 else sample.friction
    mu_avg = float(np.mean(mu_data))
    mu_std = float(np.std(mu_data))
    mu_cov = mu_std / mu_avg if mu_avg > 0 else 0.0

    # Sliding distance D (meters)
    D_m = float(sample.friction_path_m[-1]) if len(sample.friction_path_m) > 0 else 0.0

    # Time array (s)
    t_s = float(len(sample.friction)) * params.dt if params.dt else 0.0

    # Normal force (N)
    F_N = params.load_mN / 1000.0

    # Integral friction work A = Σ F_N * μ_i * Δs_i (J)
    # More accurate than F_N * μ_avg * D
    if D_m > 0 and len(mu_data) > 1 and len(sample.friction_path_m) > 1:
        ds = np.diff(sample.friction_path_m)
        mu_mid = (mu_data[:-1] + mu_data[1:]) / 2.0
        A_J = float(F_N * np.sum(mu_mid * ds))
    elif D_m > 0:
        A_J = F_N * mu_avg * D_m
    else:
        A_J = 0.0

    # Friction power P = A / t (W)
    P_W = A_J / t_s if t_s > 0 else 0.0

    # Wear depth h in μm
    h_um = h_mm * 1000.0

    # Wear intensity per distance (μm/m)
    I_h = h_um / D_m if D_m > 0 else 0.0

    # Wear intensity per work (μm/J)
    I_A = h_um / A_J if A_J > 0 else 0.0

    # Wear resistance (m/μm)
    eps = 1.0 / I_h if I_h > 0 else 0.0

    # Archard wear coefficient k = V / (F_N * D) (mm³/N·m)
    k = V_mm3 / (F_N * D_m) if D_m > 0 and F_N > 0 else 0.0

    # V/D — wear volume per distance (mm³/m), uses unfirom volume
    V_mm3_for_V = V_mm3_edge if V_mm3_edge > 0 else V_mm3
    V_D = V_mm3_for_V / D_m if D_m > 0 else 0.0

    # Volume wear resistance ε_V = D/V (m/μm³)
    eps_V = D_m / (V_mm3_for_V * 1e9) if V_mm3_for_V > 0 and D_m > 0 else 0.0

    # Contact pressure p = F_N / (π * (D_ball/2)²) (MPa)
    R_mm = params.disk_diameter_mm / 2.0 if hasattr(params, 'disk_diameter_mm') else 30.0
    contact_area_mm2 = math.pi * R_mm * R_mm
    p_MPa = F_N / contact_area_mm2 if contact_area_mm2 > 0 else 0.0

    # Dynamic analysis
    t_steady_s, mu_amplitude, stick_slip = _analyze_friction_dynamics(mu_data, params)

    # Friction regime detection
    _, _, regimes = detect_friction_regimes(mu_data, sample.friction_path_m)

    return {
        "D_m": D_m,
        "A_J": A_J,
        "P_W": P_W,
        "I_h": I_h,
        "I_A": I_A,
        "eps": eps,
        "k": k,
        "mu_avg": mu_avg,
        "mu_std": mu_std,
        "mu_cov": mu_cov,
        "eps_V": eps_V,
        "V_D": V_D,
        "p_MPa": p_MPa,
        "t_steady_s": t_steady_s,
        "mu_amplitude": mu_amplitude,
        "stick_slip": stick_slip,
        "regimes": regimes,
    }


def compute_tribology_wear_with_errors(sample: TribSample, params: TestParams,
                                        h_mm: float, V_mm3: float,
                                        V_mm3_edge: float = 0.0,
                                        err_h_mm: float = 0.0, err_V_mm3: float = 0.0,
                                        err_D_m: float = 0.0, err_mu: float = 0.0,
                                        err_load_mN: float = 0.0) -> dict:
    """
    Compute tribological wear metrics with error propagation.
    
    Parameters:
        err_h_mm: error in wear depth h (mm)
        err_V_mm3: error in wear volume V (mm³)
        err_D_m: error in sliding distance D (m)
        err_mu: error in friction coefficient
        err_load_mN: error in load (mN)
    
    Returns dict with values and errors for all metrics.
    """
    base = compute_tribology_wear(sample, params, h_mm, V_mm3, V_mm3_edge)
    if not base:
        return {}
    
    D_m = base["D_m"]
    A_J = base["A_J"]
    F_N = params.load_mN / 1000.0
    mu_avg = base["mu_avg"]
    h_um = h_mm * 1000.0
    
    # Error propagation
    # I_h = h_um / D_m
    err_I_h = 0.0
    if D_m > 0:
        err_I_h = math.sqrt((1000.0 * err_h_mm / D_m)**2 + (h_um * err_D_m / D_m**2)**2)
    
    # I_A = h_um / A_J
    err_I_A = 0.0
    if A_J > 0:
        # dA = F_N * D * dmu + mu * D * dF + mu * F_N * dD
        err_A = math.sqrt((F_N * D_m * err_mu)**2 + 
                          (mu_avg * D_m * err_load_mN / 1000.0)**2 + 
                          (mu_avg * F_N * err_D_m)**2)
        err_I_A = math.sqrt((1000.0 * err_h_mm / A_J)**2 + (h_um * err_A / A_J**2)**2)
    
    # eps = 1 / I_h
    err_eps = 0.0
    I_h = base["I_h"]
    if I_h > 0:
        err_eps = err_I_h / I_h**2
    
    # k = V / (F_N * D)
    grav_err = calc_gravimetric_error(V_mm3, err_V_mm3, F_N, D_m)
    k = grav_err["k_mm3_N_m"]
    err_k = grav_err["delta_k"]
    
    # Add D and load errors to k
    if F_N * D_m > 0:
        # k = V / (F_N * D)
        # dk = sqrt((dV/(FN*D))^2 + (V*dF/(FN^2*D))^2 + (V*dD/(FN*D^2))^2)
        err_k = math.sqrt(err_k**2 + 
                          (V_mm3 * err_load_mN / 1000.0 / (F_N**2 * D_m))**2 +
                          (V_mm3 * err_D_m / (F_N * D_m**2))**2)
    
    # V_D = V / D
    V_D = base["V_D"]
    err_V_D = 0.0
    if D_m > 0:
        err_V_D = math.sqrt((err_V_mm3 / D_m)**2 + (V_mm3 * err_D_m / D_m**2)**2)
    
    # p_MPa = F_N / (pi * R^2)
    p_MPa = base["p_MPa"]
    err_p = 0.0
    if hasattr(params, 'disk_diameter_mm') and params.disk_diameter_mm > 0:
        # Assuming no error in diameter for now
        err_p = p_MPa * (err_load_mN / params.load_mN) if params.load_mN > 0 else 0.0
    
    result = base.copy()
    result.update({
        "err_I_h": err_I_h,
        "err_I_A": err_I_A,
        "err_eps": err_eps,
        "err_k": err_k,
        "err_V_D": err_V_D,
        "err_p_MPa": err_p,
        "err_D_m": err_D_m,
        "err_A_J": err_A if A_J > 0 else 0.0,
    })
    return result


def _analyze_friction_dynamics(mu_data, params) -> tuple:
    """
    Analyze friction dynamics:
    - Time to steady state (s)
    - μ fluctuation amplitude
    - Stick-slip detection
    """
    if len(mu_data) < 10:
        return (0.0, 0.0, "Нет данных")

    mu_arr = np.array(mu_data, dtype=float)
    n = len(mu_arr)

    # --- Time to steady state ---
    # Method: sliding window std deviation drops below threshold
    # Use last 20% as reference stable region
    tail = max(1, n // 5)
    mu_ref = np.mean(mu_arr[-tail:])
    std_ref = np.std(mu_arr[-tail:])

    # Sliding window from start
    win = max(1, n // 20)
    for i in range(0, n - tail, win):
        chunk = mu_arr[i:i + win]
        if np.std(chunk) < 2.0 * std_ref and abs(np.mean(chunk) - mu_ref) < 0.5 * mu_ref:
            t_steady_s = float(i) * (params.dt if params.dt else 0.0)
            break
    else:
        t_steady_s = float(n) * (params.dt if params.dt else 0.0)

    # --- μ fluctuation amplitude ---
    # Peak-to-peak of smoothed signal
    mu_amplitude = float(np.percentile(mu_arr, 95) - np.percentile(mu_arr, 5))

    # --- Stick-slip detection (derivative-based) ---
    # Look for periodic rapid rises followed by drops (sawtooth pattern)
    # Simple heuristic: count sign changes of second derivative that are large
    d1 = np.diff(mu_arr)
    d2 = np.diff(d1)

    # Large jumps (both rising and falling)
    threshold = 3.0 * np.std(d1) if np.std(d1) > 0 else 0.01
    large_jumps = np.sum(np.abs(d1) > threshold)

    # Stick-slip if many large jumps relative to data length
    slip_ratio = large_jumps / n if n > 0 else 0
    derivative_stick = slip_ratio > 0.05  # >5% of points are large jumps

    # FFT-based stick-slip detection: look for a dominant periodic peak
    # in the 1-20 Hz range (typical stick-slip frequencies)
    fft_stick = False
    if len(mu_arr) > 200:
        n_fft = len(mu_arr)
        yf = np.fft.rfft(mu_arr - mu_arr.mean())
        xf = np.fft.rfftfreq(n_fft, d=params.dt if params.dt > 0 else 1.0)
        power = np.abs(yf)
        # Exclude DC and very low frequencies
        mask = (xf > 0.5) & (xf < 50.0)
        if np.any(mask):
            peak_idx = np.argmax(power[mask])
            peak_power = power[mask][peak_idx]
            mean_power = np.mean(power[mask])
            if peak_power > 3 * mean_power:
                fft_stick = True

    stick_slip = derivative_stick or fft_stick

    return (t_steady_s, mu_amplitude, "Да" if stick_slip else "Нет")


def detect_friction_regimes(mu_data, path_m):
    """
    Detect friction regimes: running-in, steady-state, severe wear.
    Returns (running_in_end_idx, severe_start_idx, regimes_list).
    """
    from scipy.ndimage import uniform_filter1d

    mu = np.array(mu_data, dtype=float)
    n = len(mu)
    if n < 50:
        return (0, n, [("приработка", 0, n)])

    win = max(5, n // 50)
    mu_s = uniform_filter1d(mu, size=win)
    dmu = np.gradient(mu_s)
    sigma = np.std(mu[n // 4: -n // 4]) if n // 4 < n // 2 else np.std(mu)
    thresh = max(sigma * 0.3, 1e-6)

    # Running-in end: first point where |dmu| < thresh for a sustained stretch
    run_in_end = 0
    for i in range(n // 10, n // 2):
        stretch = min(win, n - i)
        if np.all(np.abs(dmu[i:i + stretch]) < thresh * 2):
            run_in_end = max(0, i - win)
            break
    if run_in_end == 0 and n > 10:
        run_in_end = n // 8

    # Severe start: reverse search for sustained positive dmu
    severe_start = n
    for i in range(n - 1, n // 2, -1):
        stretch = min(win, i)
        if np.all(dmu[i - stretch:i] > thresh):
            severe_start = min(n, i + win)
            break
    if severe_start == n and n > 10:
        severe_start = n - n // 8

    regimes = []
    if run_in_end > 1:
        regimes.append(("приработка", 0, run_in_end))
    if severe_start > run_in_end + 1:
        regimes.append(("стационар", run_in_end, severe_start))
    if severe_start < n - 1:
        regimes.append(("износ", severe_start, n))

    return (run_in_end, severe_start, regimes)