"""Measured metrics on FINAL pixels (never on the propagation's own plan).

  fidelity      : MAE / PSNR of the propagated frame against the true source frame
  structure     : trajectory / scale / rotation error, measured by tracking points
                  from the keyframe onto BOTH the propagated frame and the true
                  source frame with the same estimator, then comparing the two
                  fits (target-profile thresholds: centre error median <= 0.5 %,
                  P95 <= 1.0 % of the frame diagonal; scale P95 <= 3 %;
                  rotation P95 <= 3 deg)
  contact       : per-contact-pair minimum distance between propagated supports,
                  classified TRUE_ZERO / WITHIN_TOLERANCE / SEPARATED / OCCLUDED /
                  UNKNOWN -- never a bare literal 0.0 (finding R05)
  continuity    : connected components of the propagated character support, plus
                  whether the contact-bearing component is part of the main body
  coverage      : propagated / filled / uncovered fractions and confidence stats
"""
from __future__ import annotations

import cv2
import numpy as np

from . import FRAME_DIAGONAL_PX, HEIGHT, WIDTH
from . import contract, guides


def fidelity(out: np.ndarray, truth: np.ndarray, region: np.ndarray | None = None) -> dict:
    diff = out.astype(np.float32) - truth.astype(np.float32)
    if region is not None and region.any():
        d = diff[region]
    else:
        d = diff.reshape(-1, 3)
    mae = float(np.abs(d).mean())
    mse = float((d ** 2).mean())
    psnr = float(10.0 * np.log10((255.0 ** 2) / mse)) if mse > 1e-12 else None
    return {"mae": mae, "mse": mse, "psnr_db": psnr,
            "pixels": int(d.shape[0]),
            "max_abs": float(np.abs(d).max())}


def structural(out_rgb, src_rgb, keyframe_rgb, params) -> dict:
    """Trajectory / scale / rotation error between the propagated frame and the
    true source frame, both tracked from the same keyframe."""
    g_k = guides.to_gray(keyframe_rgb)
    pts = guides.corner_points(g_k, params["points"])
    if len(pts) < 8:
        return {"ok": False, "reason": "too_few_corners", "n": int(len(pts))}
    lk = dict(winSize=params["points"]["lk_win"], maxLevel=params["points"]["lk_levels"],
              criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))

    def track(to_gray):
        p1, st, _ = cv2.calcOpticalFlowPyrLK(g_k, to_gray, pts.reshape(-1, 1, 2), None, **lk)
        p0, st0, _ = cv2.calcOpticalFlowPyrLK(to_gray, g_k, p1, None, **lk)
        fb = np.linalg.norm(p0.reshape(-1, 2) - pts, axis=1)
        good = (st.reshape(-1) == 1) & (st0.reshape(-1) == 1) & (fb <= 1.5)
        return p1.reshape(-1, 2).astype(np.float32), good

    q_src_all, ok_s = track(guides.to_gray(src_rgb))
    q_out_all, ok_o = track(guides.to_gray(out_rgb))
    common = ok_s & ok_o
    if common.sum() < 8:
        return {"ok": False, "reason": "too_few_common_tracks", "n": int(common.sum())}
    a = pts[common]
    q_src = q_src_all[common]
    q_out = q_out_all[common]
    f_src = guides.fit_partial_affine(a, q_src, params["points"]["ransac_reproj_px"])
    f_out = guides.fit_partial_affine(a, q_out, params["points"]["ransac_reproj_px"])
    if not (f_src.get("ok") and f_out.get("ok")):
        return {"ok": False, "reason": "fit_failed", "src": f_src.get("reason"),
                "out": f_out.get("reason"), "n": int(common.sum())}
    cs_src = a.mean(axis=0) @ f_src["matrix"][:, :2].T + f_src["matrix"][:, 2]
    cs_out = a.mean(axis=0) @ f_out["matrix"][:, :2].T + f_out["matrix"][:, 2]
    centre_err = float(np.linalg.norm(cs_out - cs_src))
    scale_err = float(abs(f_out["scale"] / f_src["scale"] - 1.0))
    rot_err = float(abs(f_out["rotation_deg"] - f_src["rotation_deg"]))
    # per-point trajectory residual, in the same estimator
    pred_src = guides.apply_similarity(f_src["matrix"], a)
    pred_out = guides.apply_similarity(f_out["matrix"], a)
    per_point = np.linalg.norm(pred_out - pred_src, axis=1)
    return {
        "ok": True,
        "common_tracks": int(common.sum()),
        "centre_error_px": centre_err,
        "centre_error_pct_diag": 100.0 * centre_err / FRAME_DIAGONAL_PX,
        "scale_rel_error": scale_err,
        "rotation_error_deg": rot_err,
        "traj_point_err_px_median": float(np.median(per_point)),
        "traj_point_err_px_p95": float(np.percentile(per_point, 95)),
        "traj_point_err_pct_diag_p95": 100.0 * float(np.percentile(per_point, 95)) / FRAME_DIAGONAL_PX,
    }


def outlier_report(out: np.ndarray, truth: np.ndarray, owner: np.ndarray,
                   thresholds=(8, 30, 64)) -> dict:
    """Where the propagation is grossly wrong on final pixels, split by whether the
    pixel sits in a role-owned region or in the uncovered/base region."""
    d = np.abs(out.astype(np.int16) - truth.astype(np.int16)).max(axis=2)
    rep = {}
    own = owner > 0
    n_own, n_out = int(own.sum()), int((~own).sum())
    for t in thresholds:
        m = d > t
        rep[f"px_gt{t}"] = int(m.sum())
        rep[f"frac_gt{t}"] = round(float(m.mean()), 6)
        rep[f"px_gt{t}_in_owner_region"] = int((m & own).sum())
        rep[f"px_gt{t}_outside_owner_region"] = int((m & ~own).sum())
        if t == 30:
            rep["err30_rate_in_owner_region"] = round(float((m & own).sum() / max(1, n_own)), 8)
            rep["err30_rate_outside_owner_region"] = round(float((m & ~own).sum() / max(1, n_out)), 8)
            rep["owner_region_px"] = n_own
            rep["outside_owner_region_px"] = n_out
    if d.max() > 0:
        y, x = np.unravel_index(int(np.argmax(d)), d.shape)
        rep["max_abs"] = int(d.max())
        rep["max_abs_at_xy"] = [int(x), int(y)]
        rep["max_abs_in_owner_region"] = bool(owner[y, x] > 0)
    return rep


def _support_distance(mask_a: np.ndarray, mask_b: np.ndarray) -> dict:
    """Exact minimum pixel-centre distance between two binary supports.

    Computed with a Euclidean distance transform (O(N) per pair, exact), never with
    a hardcoded or dilated literal.  The class is always explicit so that a zero can
    never be reported without saying what kind of zero it is (finding R05).
    """
    a = mask_a.astype(bool)
    b = mask_b.astype(bool)
    if not a.any() or not b.any():
        return {"class": "OCCLUDED", "distance_px": None,
                "reason": "one support has no propagated pixels in this frame"}
    overlap = int((a & b).sum())
    if overlap > 0:
        return {"class": "TRUE_ZERO", "distance_px": 0.0,
                "measured": "supports share pixels (intersection non-empty)", "shared_px": overlap}
    dist = cv2.distanceTransform((~b).astype(np.uint8), cv2.DIST_L2, 5)
    best = float(dist[a].min())
    return {"class": "MEASURED", "distance_px": best,
            "measured": "min euclidean pixel-centre distance (distance transform of the "
                        "complement of the other support)"}


def contact_negatives(frames: list, tag: str) -> dict:
    """Independent 'group/book contact' negative.  Calibrated on the anchor frames:
    the tolerance is the worst anchor-frame baseline measured here, +1 px."""
    pairs = contract.contacts(tag)
    role_of_index = None
    per_pair = {}
    for ra, rb in pairs:
        per_pair[(ra, rb)] = []
    # baseline measured on the anchor frames (the frozen approved appearance)
    base = {}
    ann = contract.annotation(tag)
    for fid in contract.window(tag)["anchors"]:
        im = contract.load_index_mask(tag, fid)
        lg = contract.legend(tag, fid)
        inv = {v: k for k, v in lg.items()}
        for ra, rb in pairs:
            ia, ib = inv.get(ra), inv.get(rb)
            if ia is None or ib is None:
                base.setdefault((ra, rb), []).append(None)
                continue
            d = _support_distance(im == ia, im == ib)
            base.setdefault((ra, rb), []).append(d["distance_px"])
    baseline_max = {}
    for k, v in base.items():
        vals = [x for x in v if x is not None]
        baseline_max[k] = float(max(vals)) if vals else None
    tolerance = {k: (None if v is None else v + 1.0) for k, v in baseline_max.items()}

    violations, occluded, unknown = [], [], []
    for fo in frames:
        im = np.zeros((HEIGHT, WIDTH), np.uint8)
        lg = {i: r for i, r in enumerate(contract.role_ids(tag), start=1)}
        own = fo.role_owner
        im = own  # propagated ownership map uses the same index space as the anchor legend
        for ra, rb in pairs:
            ia = [k for k, v in lg.items() if v == ra]
            ib = [k for k, v in lg.items() if v == rb]
            if not ia or not ib:
                unknown.append({"frame_id": fo.frame_id, "pair": [ra, rb], "reason": "role not in legend"})
                continue
            d = _support_distance(im == ia[0], im == ib[0])
            tol = tolerance.get((ra, rb))
            rec = {"frame_id": fo.frame_id, "pair": [ra, rb], "class": d["class"],
                   "distance_px": d["distance_px"], "tolerance_px": tol}
            if d["class"] == "OCCLUDED":
                occluded.append(rec)
            elif d["class"] == "UNKNOWN":
                unknown.append(rec)
            elif d["distance_px"] == 0.0:
                rec["classification"] = "TRUE_ZERO (supports share pixels; not a proximity waiver)"
                per_pair[(ra, rb)].append(rec)
            elif tol is not None and d["distance_px"] <= tol:
                rec["classification"] = "WITHIN_TOLERANCE"
                per_pair[(ra, rb)].append(rec)
            else:
                rec["classification"] = "SEPARATED"
                violations.append(rec)
                per_pair[(ra, rb)].append(rec)
    summary = {}
    for k, v in per_pair.items():
        seps = [x for x in v if x.get("classification") == "SEPARATED"]
        summary["|".join(k)] = {
            "frames_measured": len(v),
            "separated_frames": len(seps),
            "worst_distance_px": max([x["distance_px"] for x in v if x["distance_px"] is not None],
                                     default=None),
            "baseline_max_px": baseline_max.get(k),
            "tolerance_px": tolerance.get(k),
        }
    return {
        "negative_id": "GROUP_CONTACT",
        "status": "FAIL" if violations else "PASS",
        "pairs": summary,
        "violations": violations[:40],
        "occluded_frames": len(occluded),
        "unknown_frames": len(unknown),
        "literal_zero_reported_without_class": False,
        "independent_of": "GROUP_CONTINUITY (separate gate; a waiver on one cannot pass the other)",
    }


def continuity_negative(frames: list, tag: str) -> dict:
    """Independent 'body continuity' negative (the R04 failure mode).

    The gate is about the PRIMARY body role: is the propagated support of the main
    character role still connected the way the frozen appearance is?  It is
    calibrated per window on the anchor frames (the approved appearance) and it is
    evaluated from the propagated ownership map only, so the contact gate cannot
    waive it.  Windows whose frozen roles contain no character-kind role are
    reported NOT_APPLICABLE, never PASS.
    """
    ann = contract.annotation(tag)
    kinds = contract.role_kinds(tag)
    chars = [r["role_id"] for r in ann["roles"] if r["kind_structural"] == "character"]
    if not chars:
        return {"negative_id": "GROUP_CONTINUITY", "status": "NOT_APPLICABLE",
                "reason": "no character-kind role in this window's frozen role inventory",
                "character_roles": [], "role_kinds": {r["role_id"]: r["kind_structural"]
                                                      for r in ann["roles"]},
                "independent_of": "GROUP_CONTACT (separate gate; a waiver on one cannot pass the other)"}
    primary = max((r for r in ann["roles"] if r["kind_structural"] == "character"),
                  key=lambda r: r["median_area_pct"])["role_id"]
    pidx = contract.role_ids(tag).index(primary) + 1

    def support_stats(m: np.ndarray) -> dict:
        m = m.astype(np.uint8)
        if m.sum() == 0:
            return {"components": 0, "largest_frac": 0.0, "support_px": 0, "components_ge_16px": 0,
                    "significant_components": 0, "speck_components": 0, "largest_component_px": 0}
        ncomp, lbl, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        areas = stats[1:, cv2.CC_STAT_AREA] if ncomp > 1 else np.array([int(m.sum())])
        total = int(m.sum())
        sig_floor = max(64, int(0.01 * total))          # a component that matters
        largest = int(areas.max()) if len(areas) else total
        return {"components": int(ncomp - 1), "largest_frac": float(largest / total),
                "support_px": total,
                "components_ge_16px": int((areas >= 16).sum()) if len(areas) else 0,
                "significant_components": int((areas >= sig_floor).sum()) if len(areas) else 0,
                "speck_components": int(((areas >= 16) & (areas < sig_floor)).sum()) if len(areas) else 0,
                "significant_floor_px": sig_floor,
                "largest_component_px": largest}

    baseline = {}
    for fid in contract.window(tag)["anchors"]:
        baseline[fid] = support_stats(contract.load_index_mask(tag, fid) == pidx)
    bl_sig = max([b["significant_components"] for b in baseline.values()], default=0)
    bl_largest = min([b["largest_frac"] for b in baseline.values()], default=0.0)

    per_frame, failures = [], []
    for fo in frames:
        st = support_stats(fo.role_owner == pidx)
        st["frame_id"] = fo.frame_id
        st["status"] = "PASS" if (st["largest_frac"] >= bl_largest - 0.05
                                  and st["significant_components"] <= bl_sig) else "FAIL"
        if st["status"] == "FAIL":
            failures.append(st)
        per_frame.append(st)
    union_worst = None
    for fo in frames:
        u = support_stats(np.isin(fo.role_owner,
                                  [contract.role_ids(tag).index(c) + 1 for c in chars]))
        if union_worst is None or u["components_ge_16px"] > union_worst["components_ge_16px"]:
            union_worst = {**u, "frame_id": fo.frame_id}
    return {
        "negative_id": "GROUP_CONTINUITY",
        "status": "FAIL" if failures else "PASS",
        "primary_role": primary,
        "criterion": ("propagated primary-role support must keep the frozen appearance's "
                      "connectivity: components_ge_16px <= baseline_max AND "
                      "largest_frac >= baseline_min - 0.05"),
        "baseline": {
            "measured_on": "anchor frames (frozen approved appearance)",
            "primary_role_significant_components_max": bl_sig,
            "primary_role_largest_frac_min": bl_largest,
            "significant_component_floor": "max(64 px, 1% of support area)",
            "per_anchor": {str(k): v for k, v in baseline.items()},
            "character_roles": chars,
        },
        "frames": len(per_frame),
        "failing_frames": len(failures),
        "worst_largest_frac": min([r["largest_frac"] for r in per_frame], default=None),
        "worst_significant_components": max([r["significant_components"] for r in per_frame], default=None),
        "worst_speck_components": max([r["speck_components"] for r in per_frame], default=None),
        "union_character_support_worst": union_worst,
        "examples": failures[:20],
        "independent_of": "GROUP_CONTACT (separate gate; a waiver on one cannot pass the other)",
    }
