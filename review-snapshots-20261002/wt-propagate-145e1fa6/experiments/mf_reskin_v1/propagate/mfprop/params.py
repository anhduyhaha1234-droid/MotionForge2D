"""Frozen propagation parameters.

Discipline (acceptance P-A17): ONE parameter set is shared by all seven windows and
by every ablation run.  It was authored before any holdout metric was computed and
is never adjusted after seeing W07_HOLDOUT numbers.  The hash of this file is
recorded in the evidence; a change invalidates the run.
"""
from __future__ import annotations

PARAMS = {
    "version": "propagate-params-1",
    # --- optical flow (dense guide) -----------------------------------------
    "farneback": {"pyr_scale": 0.5, "levels": 4, "winsize": 21, "iterations": 3,
                  "poly_n": 5, "poly_sigma": 1.2, "flags": 0},
    "fb_consistency_tol_px": 1.5,      # forward/backward flow agreement tolerance
    # --- edges (edge guide) --------------------------------------------------
    "edge": {"sobel_ksize": 3, "adaptive_percentile": 85.0, "snap_band_px": 2},
    # --- masks (mask guide) --------------------------------------------------
    "mask": {"min_role_area_px": 40, "boundary_band_px": 1},
    # --- points (point guide) ------------------------------------------------
    "points": {"max_corners": 220, "quality": 0.01, "min_distance": 8,
               "lk_win": (21, 21), "lk_levels": 3, "lk_max_err": 18.0,
               "ransac_reproj_px": 2.0, "min_tracked": 8},
    # --- reconciliation ------------------------------------------------------
    "reconcile": {"agree_tol_px": 1.5},
    # --- group constraint ----------------------------------------------------
    "group": {"deviation_tol_px": 2.0},        # members of G_BOOK_MAN_HANDS
    "role": {"deviation_tol_px": 4.0},         # non-group roles (local motion bound)
    # --- confidence weights (renormalised over enabled guides) ---------------
    "confidence": {"chain": 0.35, "flow": 0.20, "edge": 0.15, "reconcile": 0.15, "role": 0.15},
    "flow_conf_scale_px": 1.5,
    "edge_conf_scale": 0.35,
    # --- resets --------------------------------------------------------------
    "reset": {
        "mad_multiplier": 8.0,          # d_mad > max(floor, multiplier * window median)
        "mad_floor": 20.0,              # abs floor on the 0..255 grey scale; calibrated so that
                                        # measured continuous motion (walking/camera) does not fire
        "chain_invalid_frac": 0.50,     # chain-invalid fraction spike
        "role_area_drop_frac": 0.50,    # propagated role area collapse vs anchor
    },
    # --- memory --------------------------------------------------------------
    "max_frames_resident": 32,
}

GUIDES = ("flow", "point", "mask", "edge")


def params() -> dict:
    import copy
    return copy.deepcopy(PARAMS)


def params_hash() -> str:
    import hashlib
    import json
    blob = json.dumps(PARAMS, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
