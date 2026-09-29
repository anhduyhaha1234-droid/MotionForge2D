"""Bidirectional gather propagation of approved keyframe appearance onto final pixels.

Why it is shaped this way
-------------------------
* GATHER, never forward splat.  For every output pixel exactly one source
  coordinate is produced by chaining dense backward flows from the owning
  keyframe, so the persisted sample map is one authoritative (anchor, sx, sy) per
  output pixel and repeated forward splatting of the appearance cannot occur.
  (C-lesson: forward splat / small support image causes blur-halo.)
* Bidirectional: every anchor-to-anchor segment is chained from BOTH ends; frames
  left of the meeting point sample the left keyframe, frames right of it sample
  the right keyframe, and the meeting frame itself is reconciled per pixel with an
  explicit rule whose agreement/conflict counts are persisted.
* Hard resets: a measured or annotated discontinuity splits the segment; each side
  then samples exactly one keyframe and nothing is blended across the split.
* One constrained interaction group: members of `G_BOOK_MAN_HANDS` are pinned to a
  single group solve (one transform, not three independent solves); the deviation
  an independent per-member solve *would* have produced is measured and reported.
  Non-group roles receive a bounded local-motion residual (A_r = T_g^-1 . T_r).
* Composite is premultiplied alpha at role boundaries:
  out = a * C_role + (1 - a) * C_base, where a is the sub-pixel coverage of the
  owning role mask carried from the keyframe.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from . import FRAME_DIAGONAL_PX, HEIGHT, WIDTH, pts_of, time_of
from . import contract, guides

SUB_RANGE_TOL = 0.0


@dataclass
class FrameOut:
    frame_id: int
    out_rgb: np.ndarray            # (H,W,3) uint8 final pixels
    anchor_side: np.ndarray        # (H,W) uint8, 0 = left keyframe, 1 = right keyframe
    anchor_id: np.ndarray          # (H,W) uint8, 0/1 -> absolute frame id via anchors[side]
    sx: np.ndarray                 # (H,W) float32 source x inside the owning keyframe (base layer)
    sy: np.ndarray                 # (H,W) float32 source y inside the owning keyframe
    owner_sx: np.ndarray           # (H,W) float32 sampling coordinate of the owner layer
    owner_sy: np.ndarray           # (H,W) float32 sampling coordinate of the owner layer
    valid: np.ndarray              # (H,W) uint8 1 = chained, 2 = propagation-filled
    conf: np.ndarray               # (H,W) uint8 per-sample confidence
    role_owner: np.ndarray         # (H,W) uint8 owning mask index (0 = base layer)
    alpha: np.ndarray              # (H,W) float32 premultiplied coverage of owner
    stats: dict = field(default_factory=dict)


# --------------------------------------------------------------- small helpers
def _nearest_valid_fill(field: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Replace invalid entries of a 2-channel field by the value at the nearest
    valid pixel (measured nearest neighbour, not a guess)."""
    inv = (valid == 0)
    if not inv.any() or not (valid > 0).any():
        return field, inv.astype(np.uint8)
    src = (valid > 0).astype(np.uint8)
    _, lbl = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
    vy, vx = np.nonzero(valid > 0)
    iy, ix = np.nonzero(inv)
    vl = lbl[vy, vx]
    order = np.argsort(vl)
    vl_sorted = vl[order]
    pos = np.searchsorted(vl_sorted, lbl[iy, ix])
    pos = np.clip(pos, 0, len(order) - 1)
    pick = order[pos]
    out = field.copy()
    out[iy, ix] = field[vy[pick], vx[pick]]
    return out, inv.astype(np.uint8)


def _fit_bundle(tracks, loc_i: int, anchor_index_map: np.ndarray, role_ids: list[str],
                group_members: set[str], p: dict) -> dict:
    """One anchor->frame fit for all points, one per role, and one group solve."""
    base = {"ok": False, "reason": "point_guide_disabled"}
    pts_a = tracks["points"].get(0)
    pts_f = tracks["points"].get(loc_i)
    alive = tracks["alive"].get(loc_i)
    n_pts = 0 if pts_a is None else len(pts_a)
    if pts_a is None or pts_f is None or n_pts == 0:
        return {"ref": base, "by_role": {}, "group": base, "tracked_points": 0}
    good = alive if alive is not None else np.ones(n_pts, bool)
    src, dst = pts_a[good], pts_f[good]
    ref = guides.fit_partial_affine(src, dst, p["points"]["ransac_reproj_px"])
    ref["tracked_points"] = int(good.sum())
    by_role = {}
    if ref.get("ok") and len(src):
        sy = np.clip(np.rint(src[:, 1]).astype(int), 0, HEIGHT - 1)
        sx = np.clip(np.rint(src[:, 0]).astype(int), 0, WIDTH - 1)
        owner_idx = anchor_index_map[sy, sx]
        for idx in range(1, len(role_ids) + 1):
            inside = owner_idx == idx
            if inside.sum() >= 4:
                f = guides.fit_partial_affine(src[inside], dst[inside], p["points"]["ransac_reproj_px"])
                if f.get("ok") and f["inliers"] >= 3:
                    by_role[role_ids[idx - 1]] = f
    group = base
    if group_members and ref.get("ok"):
        gm = np.zeros((HEIGHT, WIDTH), np.uint8)
        for idx in range(1, len(role_ids) + 1):
            if role_ids[idx - 1] in group_members:
                gm |= (anchor_index_map == idx).astype(np.uint8)
        inside = gm[np.clip(np.rint(src[:, 1]).astype(int), 0, HEIGHT - 1),
                    np.clip(np.rint(src[:, 0]).astype(int), 0, WIDTH - 1)] > 0
        if inside.sum() >= 4:
            group = guides.fit_partial_affine(src[inside], dst[inside], p["points"]["ransac_reproj_px"])
            group["n_group_points"] = int(inside.sum())
    return {"ref": ref, "by_role": by_role, "group": group, "tracked_points": int(good.sum())}


def _role_shift(coords: np.ndarray, gf: dict, rf: dict) -> np.ndarray:
    """A_r = T_g^-1 . T_r applied to anchor coordinates (identity when no fit)."""
    if not (gf and gf.get("ok") and rf and rf.get("ok")):
        return coords
    ginv = guides.invert_similarity(gf["matrix"])
    rinv = guides.invert_similarity(rf["matrix"])
    h = ginv[:2, :2] @ rinv[:2, :2]
    t = ginv[:2, 2] + ginv[:2, :2] @ rinv[:2, 2]
    x = coords[..., 0] * h[0, 0] + coords[..., 1] * h[1, 0] + t[0]
    y = coords[..., 0] * h[0, 1] + coords[..., 1] * h[1, 1] + t[1]
    return np.stack([x, y], axis=-1).astype(np.float32)


def _clamp_dev(base: np.ndarray, shifted: np.ndarray, tol: float) -> tuple[np.ndarray, dict]:
    dev = shifted - base
    mag = np.linalg.norm(dev, axis=-1)
    scale = np.where(mag > 1e-6, np.minimum(1.0, tol / np.maximum(mag, 1e-6)), 1.0)
    out = (base + dev * scale[..., None]).astype(np.float32)
    return out, {
        "deviation_px_median": float(np.median(mag)),
        "deviation_px_p95": float(np.percentile(mag, 95)),
        "deviation_px_max": float(mag.max()),
        "clamped_px": int((mag > tol).sum()),
        "clamped_frac": float((mag > tol).mean()),
    }


def detect_resets(grays, frame_ids, ann_cuts, p) -> list[dict]:
    """Measured + annotated discontinuity detection inside one segment."""
    rs = p["reset"]
    diffs = []
    for i in range(1, len(grays)):
        a = cv2.resize(grays[i - 1], (320, 180), interpolation=cv2.INTER_AREA).astype(np.int16)
        b = cv2.resize(grays[i], (320, 180), interpolation=cv2.INTER_AREA).astype(np.int16)
        diffs.append(float(np.abs(a - b).mean()))
    med = float(np.median(diffs)) if diffs else 0.0
    thr = max(rs["mad_floor"], rs["mad_multiplier"] * med) if med > 0 else rs["mad_floor"]
    ann = {int(c["frame_id"]): c for c in ann_cuts}
    events = []
    for i, fid in enumerate(frame_ids):
        if i == 0:
            if fid in ann:
                events.append({"frame_id": fid, "kind": "annotated_cut_at_segment_start",
                               "scene_score": ann[fid].get("scene_score"),
                               "mad_measured": None, "mad_threshold": round(thr, 4),
                               "action": "segment boundary; no chain crosses it"})
            continue
        d = diffs[i - 1]
        if fid in ann:
            events.append({"frame_id": fid, "kind": "annotated_cut",
                           "scene_score": ann[fid].get("scene_score"),
                           "mad_measured": round(d, 4), "mad_threshold": round(thr, 4),
                           "action": "hard reset; chains on either side sample one keyframe each"})
        elif d > thr:
            events.append({"frame_id": fid, "kind": "measured_discontinuity",
                           "mad_measured": round(d, 4), "mad_threshold": round(thr, 4),
                           "window_median_mad": round(med, 4),
                           "action": "hard reset; chains on either side sample one keyframe each"})
    return events


# ------------------------------------------------------------------- chains
def chain_from_left(flows_bwd: dict, frame_ids: list[int], a_abs: int) -> dict:
    coords = {a_abs: guides.identity_coords((HEIGHT, WIDTH))}
    valid = {a_abs: np.ones((HEIGHT, WIDTH), np.uint8)}
    fbv = {a_abs: np.zeros((HEIGHT, WIDTH), np.float32)}
    for f in frame_ids[1:]:
        p = guides.identity_coords((HEIGHT, WIDTH)) + flows_bwd[f]
        c, w = guides.bilinear(coords[f - 1], p)
        v, _ = guides.bilinear(valid[f - 1].astype(np.float32), p)
        fb_s, _ = guides.bilinear(fbv[f - 1], p)
        ok = (w > 0.999) & (v > 0.999)
        coords[f] = np.where(ok[..., None], c, guides.identity_coords((HEIGHT, WIDTH)))
        valid[f] = ok.astype(np.uint8)
        fbv[f] = np.where(ok, fb_s, 0.0).astype(np.float32)
    return {"coords": coords, "valid": valid, "fb": fbv}


def chain_from_right(flows_fwd: dict, frame_ids: list[int], b_abs: int) -> dict:
    coords = {b_abs: guides.identity_coords((HEIGHT, WIDTH))}
    valid = {b_abs: np.ones((HEIGHT, WIDTH), np.uint8)}
    fbv = {b_abs: np.zeros((HEIGHT, WIDTH), np.float32)}
    for f in reversed(frame_ids[:-1]):
        p = guides.identity_coords((HEIGHT, WIDTH)) + flows_fwd[f]
        c, w = guides.bilinear(coords[f + 1], p)
        v, _ = guides.bilinear(valid[f + 1].astype(np.float32), p)
        fb_s, _ = guides.bilinear(fbv[f + 1], p)
        ok = (w > 0.999) & (v > 0.999)
        coords[f] = np.where(ok[..., None], c, guides.identity_coords((HEIGHT, WIDTH)))
        valid[f] = ok.astype(np.uint8)
        fbv[f] = np.where(ok, fb_s, 0.0).astype(np.float32)
    return {"coords": coords, "valid": valid, "fb": fbv}


# ------------------------------------------------------------- segment driver
def propagate_segment(tag: str, win: dict, a_abs: int, b_abs: int, bundles: dict,
                      params: dict, guides_on: set[str],
                      single_side: bool = False) -> tuple[list[FrameOut], dict]:
    """Propagate the frames a_abs..b_abs of one anchor-to-anchor segment.

    `single_side=True` is used for the window tail (frames after the last anchor):
    only the left chain exists there, so no reconciliation is possible and any
    frame that a reset puts beyond the last keyframe is reported as UNPROPAGATED
    instead of being filled with a guess.
    """
    p = params
    frames = bundles["frames"]
    n = int(frames.shape[0])
    assert n == b_abs - a_abs + 1, "segment frame count mismatch"
    frame_ids = list(range(a_abs, b_abs + 1))
    grays = [guides.to_gray(frames[i]) for i in range(n)]
    edges = [guides.edge_magnitude(grays[i], p["edge"]) for i in range(n)]
    edge_bins = [guides.edge_mask(edges[i], p["edge"])[0] for i in range(n)]

    use_flow = "flow" in guides_on
    use_point = "point" in guides_on
    use_mask = "mask" in guides_on
    use_edge = "edge" in guides_on

    # ---- flow guide ---------------------------------------------------------
    fwd, bwd = {}, {}
    for i in range(n - 1):
        if use_flow:
            f01, f10, _ = guides.flow_pair(grays[i], grays[i + 1], p["farneback"])
        else:
            f01 = np.zeros((HEIGHT, WIDTH, 2), np.float32)
            f10 = np.zeros((HEIGHT, WIDTH, 2), np.float32)
        fwd[frame_ids[i]] = f01
        bwd[frame_ids[i + 1]] = f10
    zero = np.zeros((HEIGHT, WIDTH, 2), np.float32)
    flows_fwd = {fid: fwd.get(fid, zero) for fid in frame_ids}
    flows_bwd = {fid: bwd.get(fid, zero) for fid in frame_ids}

    # ---- point guide --------------------------------------------------------
    role_ids = win["role_ids"]
    group_members = set(win.get("group_members") or [])
    active_left = bundles["left"].get("active_idx") or list(range(1, len(role_ids) + 1))
    active_right = bundles["right"].get("active_idx") or list(range(1, len(role_ids) + 1))
    if use_point:
        t_left = guides.track_chain(grays, 0, p["points"])
        t_right = guides.track_chain(grays[::-1], 0, p["points"])
    else:
        empty = {"points": {}, "alive": {}, "fb_err": {}, "start_idx": 0}
        t_left = empty
        empty2 = {"points": {}, "alive": {}, "fb_err": {}, "start_idx": 0}
        t_right = empty2
    fits_left, fits_right = {}, {}
    for i, fid in enumerate(frame_ids):
        fits_left[fid] = _fit_bundle(t_left, i, bundles["left"]["index_map"], role_ids,
                                     group_members, p) if use_point else \
            {"ref": {"ok": False, "reason": "point_guide_disabled"}, "by_role": {}, "group": {"ok": False},
             "tracked_points": 0}
        j = n - 1 - i
        fits_right[fid] = _fit_bundle(t_right, j, bundles["right"]["index_map"], role_ids,
                                      group_members, p) if use_point else \
            {"ref": {"ok": False, "reason": "point_guide_disabled"}, "by_role": {}, "group": {"ok": False},
             "tracked_points": 0}

    # ---- resets -------------------------------------------------------------
    resets = detect_resets(grays, frame_ids, contract.cuts_inside(tag), p)
    split_at = sorted({e["frame_id"] for e in resets
                       if e["kind"] in ("annotated_cut", "measured_discontinuity")})
    ranges, start = [], a_abs
    for rf in split_at:
        if a_abs < rf <= b_abs:
            ranges.append((start, rf - 1))
            start = rf
    ranges.append((start, b_abs))
    ranges = [(s, e) for (s, e) in ranges if s <= e]
    range_of = {fid: (s, e) for (s, e) in ranges for fid in range(s, e + 1)}
    meetings = {r: {r[0] + (r[1] - r[0]) // 2, r[0] + (r[1] - r[0]) // 2 + 1} for r in ranges}

    # ---- chains -------------------------------------------------------------
    L = chain_from_left(flows_bwd, frame_ids, a_abs)
    if single_side:
        zc = {f: np.zeros((HEIGHT, WIDTH, 2), np.float32) for f in frame_ids}
        zv = {f: np.zeros((HEIGHT, WIDTH), np.uint8) for f in frame_ids}
        zf = {f: np.zeros((HEIGHT, WIDTH), np.float32) for f in frame_ids}
        R = {"coords": zc, "valid": zv, "fb": zf}
    else:
        R = chain_from_right(flows_fwd, frame_ids, b_abs)

    depth = bundles["depth"]
    cw = p["confidence"]
    outs: list[FrameOut] = []
    seg = {"tag": tag, "segment": [a_abs, b_abs], "resets": resets, "ranges": ranges,
           "meeting_frames": sorted({m for v in meetings.values() for m in v}),
           "single_side": bool(single_side), "reset_split_frames": [],
           "role_deviation": {}, "group_constraint": {}, "frames": []}

    for i, fid in enumerate(frame_ids):
        s, e = range_of[fid]
        mid = e if single_side else s + (e - s) // 2
        if single_side and (s, e) != ranges[0]:
            # no keyframe exists beyond this reset: explicit failure, not a guess
            zero = np.zeros((HEIGHT, WIDTH), np.float32)
            outs.append(FrameOut(
                fid, np.full((HEIGHT, WIDTH, 3), 255, np.uint8) * np.array([1, 0, 1], np.uint8),
                np.zeros((HEIGHT, WIDTH), np.uint8), np.zeros((HEIGHT, WIDTH), np.uint8),
                zero, zero, zero, zero, np.zeros((HEIGHT, WIDTH), np.uint8),
                np.zeros((HEIGHT, WIDTH), np.uint8), np.zeros((HEIGHT, WIDTH), np.uint8),
                zero, {"frame_id": fid, "pts": pts_of(fid), "time_s": round(time_of(fid), 6),
                       "status": "UNPROPAGATED_NO_KEYFRAME_BEYOND_RESET",
                       "sub_range": [s, e], "reset_split": True,
                       "chain_valid_frac": 0.0, "filled_px": HEIGHT * WIDTH, "filled_frac": 1.0,
                       "conf_mean": 0.0, "conf_p05": 0.0, "role_px": 0,
                       "owning_keyframe": None, "owning_side": None, "is_meeting_frame": False,
                       "owner_alpha_mean_where_owner": None,
                       "reconcile_both_valid_px": 0, "reconcile_agree_px": 0,
                       "reconcile_conflict_px": 0, "reconcile_conflict_frac_of_both": None,
                       "reconcile_agree_px_median": None, "reconcile_left_win_frac": None,
                       "role_consistency_conflict_px": 0, "edge_snapped_px": 0,
                       "boundary_on_edge_frac": None, "role_deviation": {}, "group_constraint": {}}))
            seg["frames"].append(outs[-1].stats)
            seg["reset_split_frames"].append(fid)
            continue
        lc, lv, lfb = L["coords"][fid], L["valid"][fid], L["fb"][fid]
        rc, rv, rfb = R["coords"][fid], R["valid"][fid], R["fb"][fid]
        is_meeting = fid in meetings[(s, e)]

        # ---- reconciliation (persisted for every frame) ---------------------
        both = (lv > 0) & (rv > 0)
        agree = np.linalg.norm(lc - rc, axis=-1).astype(np.float32)
        conflict = both & (agree > p["reconcile"]["agree_tol_px"])
        w_l = (np.full((HEIGHT, WIDTH), abs(fid - s) + 0.5, np.float32)
               / max(1.0, float(abs(fid - s) + abs(fid - e) + 1)))
        conf_l = np.exp(-lfb / p["flow_conf_scale_px"]).astype(np.float32)
        conf_r = np.exp(-rfb / p["flow_conf_scale_px"]).astype(np.float32)
        score_l = conf_l * (1.0 - w_l)
        score_r = conf_r * w_l
        winner_left = score_l >= score_r

        if is_meeting and both.any():
            use_left = (lv > 0) & (~both | winner_left)
            coords = np.where(use_left[..., None], lc, rc).astype(np.float32)
            side = np.where(use_left, 0, 1).astype(np.uint8)
            used_valid = np.where(use_left, lv, rv).astype(np.uint8)
            used_fb = np.where(use_left, lfb, rfb).astype(np.float32)
        elif fid <= mid:
            coords, side, used_valid, used_fb = lc, np.zeros((HEIGHT, WIDTH), np.uint8), lv, lfb
            winner_left = np.ones((HEIGHT, WIDTH), bool)
        else:
            coords, side, used_valid, used_fb = rc, np.ones((HEIGHT, WIDTH), np.uint8), rv, rfb
            winner_left = np.zeros((HEIGHT, WIDTH), bool)

        anchor_side_left = bool(fid <= mid) or (is_meeting and side.mean() < 0.5)
        anchor_a = bundles["left"] if anchor_side_left else bundles["right"]
        fits = (fits_left if anchor_side_left else fits_right)[fid]

        # ---- role ownership + bounded local motion --------------------------
        role_owner = np.zeros((HEIGHT, WIDTH), np.uint8)
        alpha = np.zeros((HEIGHT, WIDTH), np.float32)
        owner_coords = coords
        snapped = 0
        role_dev_report, group_report = {}, {}
        if use_point and fits["ref"].get("ok"):
            best_depth = np.full((HEIGHT, WIDTH), -1, np.int16)
            for idx in (active_left if anchor_side_left else active_right):
                rid = role_ids[idx - 1]
                if rid in group_members and group_members:
                    rcoords = coords
                    if fits["by_role"].get(rid) and fits["group"].get("ok"):
                        would = _role_shift(coords, fits["group"], fits["by_role"][rid])
                        would_dev = np.linalg.norm(would - coords, axis=-1)
                        group_report[rid] = {
                            "pinned_to_group_solve": True,
                            "independent_solve_would_deviate_px_median": float(np.median(would_dev)),
                            "independent_solve_would_deviate_px_p95": float(np.percentile(would_dev, 95)),
                            "independent_solve_would_deviate_px_max": float(would_dev.max()),
                            "applied_deviation_px_max": 0.0,
                        }
                else:
                    shifted = _role_shift(coords, fits["ref"], fits["by_role"].get(rid))
                    rcoords, dev = _clamp_dev(coords, shifted, p["role"]["deviation_tol_px"])
                    if fits["by_role"].get(rid):
                        role_dev_report[rid] = dev
                if not use_mask:
                    rcoords = coords
                m_near, in_ok = guides.sample_nearest(anchor_a["index_map"], rcoords)
                hit = (m_near == idx) & (in_ok > 0)
                # edge guide: snap the carried role boundary onto real target edges
                if use_mask and use_edge and hit.any():
                    hit_snap = guides.snap_mask_to_edges(hit.astype(np.uint8), edge_bins[i],
                                                         p["edge"]["snap_band_px"]) > 0
                    snapped += int((hit_snap != hit).sum())
                else:
                    hit_snap = hit
                cov, _ = guides.bilinear(hit_snap.astype(np.float32), rcoords)
                d = depth.get(rid, 0)
                take = hit_snap & (d >= best_depth)
                role_owner = np.where(take, idx, role_owner).astype(np.uint8)
                alpha = np.where(take, np.clip(cov, 0.0, 1.0), alpha).astype(np.float32)
                owner_coords = np.where(take[..., None], rcoords, owner_coords).astype(np.float32)
                best_depth = np.where(take, d, best_depth).astype(np.int16)
        role_owner = np.where((used_valid > 0) | (role_owner > 0), role_owner, 0).astype(np.uint8)
        # edge-guide contribution measured on the FINAL mask, against the target edges
        boundary_on_edge = None
        if (role_owner > 0).any():
            m = (role_owner > 0).astype(np.uint8)
            k = np.ones((3, 3), np.uint8)
            band_px = (m > 0) & (cv2.erode(m, k, iterations=1) == 0)
            if band_px.any():
                boundary_on_edge = float(edge_bins[i][band_px].mean())

        # ---- visibility / new-view events (occlusion-class resets) -----------
        visibility_events = []
        min_area_ratio = None
        if use_mask:
            counts = anchor_a.get("counts")
            if counts is None:
                counts = np.bincount(anchor_a["index_map"].ravel(),
                                     minlength=len(role_ids) + 1)
                anchor_a["counts"] = counts
            m_at, ok_at = guides.sample_nearest(anchor_a["index_map"], coords)
            for idx in (active_left if anchor_side_left else active_right):
                a_area = int(counts[idx])
                if a_area < p["mask"]["min_role_area_px"]:
                    continue
                ratio = float((( m_at == idx) & (ok_at > 0)).sum()) / float(a_area)
                if min_area_ratio is None or ratio < min_area_ratio:
                    min_area_ratio = ratio
                if ratio < (1.0 - p["reset"]["role_area_drop_frac"]):
                    visibility_events.append({
                        "frame_id": fid, "kind": "visibility_or_occlusion_event",
                        "role_id": role_ids[idx - 1], "anchor_area_px": a_area,
                        "measured_area_px": int(((m_at == idx) & (ok_at > 0)).sum()),
                        "area_ratio": round(ratio, 6),
                        "threshold": round(1.0 - p["reset"]["role_area_drop_frac"], 6),
                        "response": "role excluded from ownership in this frame (hard event, "
                                    "no blending across it); pixels fall back to the keyframe base layer",
                    })
                    role_owner = np.where(role_owner == idx, 0, role_owner).astype(np.uint8)
                    a_map = np.where(role_owner > 0, a_map, 0.0).astype(np.float32)

        # ---- appearance sampling (single authoritative map) -----------------
        anchor_rgb = anchor_a["rgb"].astype(np.float32)
        c_owner, _ = guides.bilinear(anchor_rgb, owner_coords)
        c_base, _ = guides.bilinear(anchor_rgb, coords)
        has_owner = (role_owner > 0) & use_mask
        a_map = np.where(has_owner, alpha, 0.0).astype(np.float32)
        out_rgb = np.clip(a_map[..., None] * c_owner + (1.0 - a_map[..., None]) * c_base, 0, 255).astype(np.uint8)

        # ---- confidence ------------------------------------------------------
        c_chain = (used_valid > 0).astype(np.float32)
        c_flow = np.exp(-used_fb / p["flow_conf_scale_px"]).astype(np.float32)
        if use_edge:
            emag, _ = guides.bilinear(edges[i], coords)
            c_edge = np.clip(emag / p["edge_conf_scale"], 0.0, 1.0)
        else:
            c_edge = np.ones((HEIGHT, WIDTH), np.float32)
        c_rec = np.where(both, np.exp(-agree / p["reconcile"]["agree_tol_px"]), 1.0).astype(np.float32)
        m_l, ok_l = guides.sample_nearest(bundles["left"]["index_map"], lc)
        m_r, ok_r = guides.sample_nearest(bundles["right"]["index_map"], rc)
        mismatch = (ok_l > 0) & (ok_r > 0) & (m_l != m_r)
        c_role = np.where(mismatch, 0.5, 1.0).astype(np.float32)
        parts = {"chain": (c_chain, cw["chain"])}
        if use_flow:
            parts["flow"] = (c_flow, cw["flow"])
        if use_edge:
            parts["edge"] = (c_edge, cw["edge"])
        parts["reconcile"] = (c_rec, cw["reconcile"])
        if use_mask:
            parts["role"] = (c_role, cw["role"])
        wsum = sum(w for _, w in parts.values())
        conf_f = sum(v * w for v, w in parts.values()) / wsum
        conf = np.clip(np.rint(conf_f * 255.0), 0, 255).astype(np.uint8)

        # ---- fill invalid samples from the SAME keyframe (never the target) ---
        valid_map = np.ones((HEIGHT, WIDTH), np.uint8)
        if (used_valid == 0).any():
            filled, holes = _nearest_valid_fill(np.stack([coords[..., 0], coords[..., 1]], -1),
                                                used_valid)
            coords = filled
            # a hole has no valid chain, so no role can own it: drop the owner claim
            role_owner = np.where(holes > 0, 0, role_owner).astype(np.uint8)
            a_map = np.where(holes > 0, 0.0, a_map).astype(np.float32)
            c_base, _ = guides.bilinear(anchor_rgb, coords)
            c_owner = np.where(holes[..., None] > 0, c_base, c_owner)
            out_rgb = np.clip(a_map[..., None] * c_owner + (1.0 - a_map[..., None]) * c_base,
                              0, 255).astype(np.uint8)
            valid_map = np.where(holes > 0, 2, 1).astype(np.uint8)
            owner_coords = np.where(holes[..., None] > 0, coords, owner_coords).astype(np.float32)
            conf = np.where(holes > 0, 0, conf).astype(np.uint8)

        stats = {
            "frame_id": fid, "pts": pts_of(fid), "time_s": round(time_of(fid), 6),
            "owning_keyframe": int(anchor_a["frame_id"]),
            "owning_side": "left" if anchor_side_left else "right",
            "sub_range": [s, e], "is_meeting_frame": bool(is_meeting),
            "chain_valid_frac": float((used_valid > 0).mean()),
            "filled_px": int((valid_map == 2).sum()),
            "filled_frac": float((valid_map == 2).mean()),
            "conf_mean": round(float(conf.mean() / 255.0), 6),
            "conf_p05": round(float(np.percentile(conf, 5) / 255.0), 6),
            "role_px": int((role_owner > 0).sum()),
            "owner_alpha_mean_where_owner": round(float(a_map[role_owner > 0].mean()), 6)
            if (role_owner > 0).any() else None,
            "reconcile_both_valid_px": int(both.sum()),
            "reconcile_agree_px": int((both & ~conflict).sum()),
            "reconcile_conflict_px": int(conflict.sum()),
            "reconcile_conflict_frac_of_both": round(float(conflict.sum() / max(1, both.sum())), 6),
            "reconcile_agree_px_median": round(float(np.median(agree[both])), 6) if both.any() else None,
            "reconcile_left_win_frac": round(float(winner_left.mean()), 6),
            "role_consistency_conflict_px": int(mismatch.sum()),
            "edge_snapped_px": int(snapped),
            "boundary_on_edge_frac": boundary_on_edge,
            "visibility_events": visibility_events,
            "min_role_area_ratio": min_area_ratio,
            "role_deviation": role_dev_report,
            "group_constraint": group_report,
        }
        outs.append(FrameOut(fid, out_rgb, side, side.copy(), coords[..., 0].astype(np.float32),
                             coords[..., 1].astype(np.float32),
                             owner_coords[..., 0].astype(np.float32),
                             owner_coords[..., 1].astype(np.float32), valid_map, conf, role_owner,
                             a_map, stats))
        seg["frames"].append(stats)
        for k, v in group_report.items():
            seg["group_constraint"].setdefault(k, []).append({"frame_id": fid, **v})
        for k, v in role_dev_report.items():
            seg["role_deviation"].setdefault(k, []).append({"frame_id": fid, **v})
    return outs, seg
