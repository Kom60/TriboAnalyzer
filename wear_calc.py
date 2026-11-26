"""Wear parameter calculations for disc-on-plane geometry.

Formulas (2.25)-(2.27):
    h = R - sqrt(R^2 - L^2 / 4)
    S_BCD = R^2 * arcsin(L / (2R)) - L*(R - h) / 2
    V = S_BCD * W
"""

import math
import numpy as np

# ======================================================================
# Instrument specification constants
# ======================================================================
INSTRUMENT_SPECS = {
    "mu_error": 0.02,
    "load_error_mN": 10.0,
    "D_rel_error": 0.01,
    "calib_px_error": 1.0,
    "calib_rel_error": 0.01,
    "balance_error_mg": 0.1,
}
def calc_wear_depth(R_mm: float, L_mm: float) -> float:
    """h = R - sqrt(R^2 - L^2/4)"""
    arg = R_mm ** 2 - L_mm ** 2 / 4.0
    if arg < 0:
        return 0.0
    return R_mm - math.sqrt(arg)


def calc_wear_area(R_mm: float, L_mm: float, h_mm: float) -> float:
    """S_BCD = R^2 * arcsin(L / (2R)) - L*(R - h) / 2"""
    denom = 2.0 * R_mm
    if denom == 0:
        return 0.0
    arg = max(-1.0, min(1.0, L_mm / denom))
    return R_mm ** 2 * math.asin(arg) - L_mm * (R_mm - h_mm) / 2.0


def calc_wear_volume(S_mm2: float, W_mm: float) -> float:
    """V = S_BCD * W"""
    return S_mm2 * W_mm


def calc_wear_volume_edge_radius(S_mm2: float, W_mm: float, L_mm: float, r_mm: float) -> float:
    """
    Wear volume with disc edge radius correction (Eq. 3.3).
    
    V = S_BCD * W + π/2 * r² * (L - 2r)
    
    The second term accounts for material displaced by the rounded
    disc edge of radius r. Returns V_mm3.
    """
    V_prism = S_mm2 * W_mm
    if r_mm <= 0 or L_mm <= 2 * r_mm:
        return V_prism
    correction = (math.pi / 2.0) * r_mm * r_mm * (L_mm - 2.0 * r_mm)
    return V_prism + correction


def calc_wear_errors(R_mm: float, L_mm: float, W_mm: float, dL: float, dW: float):
    """
    Estimate h, S, V errors from L/W measurement uncertainty via
    analytic partial derivatives.
    Returns (h_err, S_err, V_err).
    """
    arg = R_mm**2 - L_mm**2 / 4.0
    if arg <= 0:
        return (0.0, 0.0, 0.0)

    sqrt_arg = math.sqrt(arg)
    h_mm = R_mm - sqrt_arg

    dh_dL = L_mm / (4.0 * sqrt_arg)
    err_h = abs(dh_dL * dL)

    denom = 2.0 * R_mm
    if denom == 0:
        return (err_h, 0.0, 0.0)

    arg_asin = max(-1.0, min(1.0, L_mm / denom))
    asin_val = math.asin(arg_asin)
    S_mm2 = R_mm**2 * asin_val - L_mm * (R_mm - h_mm) / 2.0

    dasin_dL = 1.0 / (2.0 * R_mm * math.sqrt(1.0 - arg_asin**2)) if abs(arg_asin) < 1 else 0.0
    dS_dL = R_mm**2 * dasin_dL - (R_mm - h_mm) / 2.0 - L_mm / 2.0 * (-dh_dL)
    err_S = abs(dS_dL * dL)

    V_mm3 = S_mm2 * W_mm
    dV_dS = W_mm
    dV_dW = S_mm2
    err_V = math.sqrt((dV_dS * err_S)**2 + (dV_dW * dW)**2)

    return (err_h, err_S, err_V)


def calc_wear_all(R_mm: float, L_mm: float, W_mm: float) -> dict:
    """Calculate all wear parameters at once. Returns dict."""
    h = calc_wear_depth(R_mm, L_mm)
    S = calc_wear_area(R_mm, L_mm, h)
    V = calc_wear_volume(S, W_mm)
    return {"R": R_mm, "L": L_mm, "W": W_mm, "h": h, "S": S, "V": V}


def compute_wear_metrics_and_errors(
    sample: "TribSample",
    params: "TestParams",
    R: float, L: float, W: float,
    V: float, V_edge: float,
    px_per_mm: float,
    trib: dict,
    calib_rel_error: float = 0.01,
) -> dict:
    """Set error/derived fields on *sample* after wear computation.

    Takes the already-computed *trib* dict, sets geometry-error fields,
    relative systematic errors, and derived propagated errors on *sample*.
    Returns a dict of relative errors so callers can use them if needed.
    """
    h = calc_wear_depth(R, L)

    mu_avg = trib.get("mu_avg", 0.0)
    mu_std = trib.get("mu_std", 0.0)
    sample.wear_mu_err = math.sqrt((mu_avg * 0.02) ** 2 + mu_std ** 2)
    sample.wear_D_err = INSTRUMENT_SPECS["D_rel_error"] * trib.get("D_m", 0.0)

    dL_abs = INSTRUMENT_SPECS["calib_px_error"] / px_per_mm
    dW_abs = INSTRUMENT_SPECS["calib_px_error"] / px_per_mm
    dL = math.sqrt(dL_abs ** 2 + (calib_rel_error * L) ** 2)
    dW = math.sqrt(dW_abs ** 2 + (calib_rel_error * W) ** 2)
    h_err, S_err, V_err = calc_wear_errors(R, L, W, dL, dW)

    sample.err_h_mm = h_err
    sample.err_S_mm2 = S_err
    sample.err_V_mm3 = V_err
    sample.err_L_mm = dL
    sample.err_W_mm = dW

    V_final = V_edge if V_edge > 0 else V
    F_N = params.load_mN / 1000.0

    rel_V = V_err / V_final if V_final > 0 else 0.0
    rel_h = h_err / h if h > 0 else 0.0
    rel_D = INSTRUMENT_SPECS["D_rel_error"]
    rel_F = (INSTRUMENT_SPECS["load_error_mN"] / 1000.0) / F_N if F_N > 0 else 0.0

    mu_avg = trib.get("mu_avg", 0.0)
    rel_mu = INSTRUMENT_SPECS["mu_error"] / mu_avg if mu_avg > 0 else 0.0
    rel_A = math.sqrt(rel_F**2 + rel_D**2 + rel_mu**2)

    k = trib.get("k", 0.0)
    I_h = trib.get("I_h", 0.0)
    I_A = trib.get("I_A", 0.0)
    eps = trib.get("eps", 0.0)
    V_D = trib.get("V_D", 0.0)
    eps_V = trib.get("eps_V", 0.0)
    A_J = trib.get("A_J", 0.0)
    P_W = trib.get("P_W", 0.0)
    p_MPa = trib.get("p_MPa", 0.0)

    sample.wear_k_err = k * math.sqrt(rel_V**2 + rel_F**2 + rel_D**2) if k > 0 else 0.0
    sample.wear_I_h_err = I_h * math.sqrt(rel_h**2 + rel_D**2) if I_h > 0 else 0.0
    sample.wear_I_A_err = I_A * math.sqrt(rel_h**2 + rel_A**2) if I_A > 0 else 0.0
    sample.wear_eps_err = eps * math.sqrt(rel_h**2 + rel_D**2) if eps > 0 else 0.0
    sample.wear_V_D_err = V_D * math.sqrt(rel_V**2 + rel_D**2) if V_D > 0 else 0.0
    sample.wear_eps_V_err = eps_V * math.sqrt(rel_V**2 + rel_D**2) if eps_V > 0 else 0.0
    sample.wear_A_err = A_J * rel_A if A_J > 0 else 0.0
    sample.wear_P_err = P_W * rel_A if P_W > 0 else 0.0
    sample.wear_p_err = p_MPa * rel_F if p_MPa > 0 else 0.0

    return {
        "rel_V": rel_V,
        "rel_h": rel_h,
        "rel_D": rel_D,
        "rel_F": rel_F,
        "rel_mu": rel_mu,
    }


# ======================================================================
# Gravimetric wear
# ======================================================================

def calc_gravimetric(m_before_mg: float, m_after_mg: float,
                     density_g_cm3: float, error_mg: float,
                     load_mN: float, path_m: float) -> dict:
    """
    Gravimetric wear calculation.

    Parameters:
        m_before_mg  — mass before test (mg)
        m_after_mg   — mass after test (mg)
        density_g_cm3 — material density (g/cm³)
        error_mg     — balance precision (mg)
        load_mN      — normal load (mN)
        path_m       — sliding distance (m)

    Returns dict with:
        delta_m_mg   — mass loss (mg) = m_before - m_after
        V_mm3        — wear volume (mm³) = Δm / ρ
                                (1 mg / (g/cm³) = 1 mm³)
        delta_V_mm3  — volume error (mm³) = δm / ρ
        k_mm3_N_m    — specific wear rate (mm³/N·m) = V / (F_N × D)
        delta_k      — specific wear rate error = ΔV / (F_N × D)
    """
    delta_m = m_before_mg - m_after_mg  # mg
    V_mm3 = delta_m / density_g_cm3 if density_g_cm3 > 0 else 0.0  # 1 mg/(g/cm³) = 1 mm³
    delta_V = error_mg / density_g_cm3 if density_g_cm3 > 0 else 0.0

    F_N = load_mN / 1000.0  # N
    F_D = F_N * path_m       # N·m

    k = V_mm3 / F_D if F_D > 0 else 0.0
    delta_k = delta_V / F_D if F_D > 0 else 0.0

    return {
        "delta_m_mg": delta_m,
        "V_mm3": V_mm3,
        "delta_V_mm3": delta_V,
        "k_mm3_N_m": k,
        "delta_k": delta_k,
    }


# ======================================================================
# Error propagation and calibration
# ======================================================================


def calc_gravimetric_error(V_mm3: float, delta_V_mm3: float,
                           F_N: float, D_m: float) -> dict:
    """
    Propagate gravimetric errors to specific wear rate k.
    
    k = V / (F_N * D)
    delta_k = delta_V / (F_N * D)
    """
    k = V_mm3 / (F_N * D_m) if F_N * D_m > 0 else 0.0
    delta_k = delta_V_mm3 / (F_N * D_m) if F_N * D_m > 0 else 0.0
    return {"k_mm3_N_m": k, "delta_k": delta_k}


def calibrate_px_per_mm(measured_px: float, reference_mm: float) -> float:
    """Calculate calibration factor px/mm from known reference."""
    if reference_mm <= 0:
        return 0.0
    return measured_px / reference_mm


def calc_calibration_error(px: float, ref_mm: float, err_px: float, err_ref_mm: float) -> float:
    """Error in calibration factor px/mm."""
    # px_per_mm = px / ref_mm
    # d(px_per_mm)/dpx = 1/ref_mm
    # d(px_per_mm)/dref = -px/ref_mm^2
    if ref_mm <= 0:
        return 0.0
    return math.sqrt((err_px / ref_mm)**2 + (px * err_ref_mm / ref_mm**2)**2)
