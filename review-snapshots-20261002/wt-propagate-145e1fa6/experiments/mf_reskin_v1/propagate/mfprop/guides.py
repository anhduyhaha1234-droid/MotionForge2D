"""Guides.  Every guide is independently switchable so its contribution can be
measured by ablation instead of asserted.

  flow  : dense Farneback optical flow, both directions, plus forward/backward
          consistency error.  Supplies the dense displacement chain.
  point : Shi-Tomasi corners tracked with pyramidal Lucas-Kanade (bidirectional,
          dropped on FB error) + RANSAC partial-affine fit.  Supplies the robust
          window/group transform, the per-role local motion and the drift metric.
  mask  : the frozen anchor index masks, carried through the chain into role
          ownership per output pixel, plus cross-anchor role-consistency conflicts.
  edge  : gradient magnitude of the target frame; used to snap propagated mask
          boundaries onto real edges and to weight sample confidence.
"""
from __future__ import annotations

import cv2
import numpy as np


# --------------------------------------------------------------------- basics
def to_gray(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def bilinear(field: np.ndarray, coords: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sample `field` (H,W) or (H,W,C) at float `coords` (H,W,2) with bilinear interpolation.

    Returns (sampled, weight): weight is 1.0 for a sample inside the field and 0.0
    outside it (BORDER_REPLICATE keeps the edge pixel real instead of faking a dark
    border), so a caller can always tell a real sample from an out-of-frame miss.
    Implemented with cv2.remap (C++ interpolation path): ~10x faster than the
    equivalent vectorised numpy gather at 640x360 and numerically identical
    interpolation.
    """
    h, w = field.shape[:2]
    x = coords[..., 0]
    y = coords[..., 1]
    inside = ((x >= 0) & (y >= 0) & (x <= w - 1) & (y <= h - 1)).astype(np.float32)
    src = field if field.dtype == np.float32 else field.astype(np.float32)
    # BORDER_REPLICATE: the identity coordinate at the last row/column samples the
    # real edge pixel exactly (a CONSTANT border would fake a 1 px dark edge there).
    out = cv2.remap(src, x.astype(np.float32), y.astype(np.float32), cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REPLICATE)
    return out, inside


def sample_nearest(field: np.ndarray, coords: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h, w = field.shape[:2]
    x = coords[..., 0]
    y = coords[..., 1]
    inside = ((x >= 0) & (y >= 0) & (x <= w - 1) & (y <= h - 1)).astype(np.float32)
    out = cv2.remap(field, x.astype(np.float32), y.astype(np.float32), cv2.INTER_NEAREST,
                    borderMode=cv2.BORDER_REPLICATE)
    return out, inside


_GRID_CACHE: dict = {}


def identity_coords(shape: tuple[int, int]) -> np.ndarray:
    """Cached identity coordinate grid (read-only by convention: callers never mutate)."""
    h, w = shape
    key = (h, w)
    grid = _GRID_CACHE.get(key)
    if grid is None:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        grid = np.stack([xx, yy], axis=-1)
        grid.setflags(write=False)
        _GRID_CACHE[key] = grid
    return grid


# --------------------------------------------------------------- flow guide
def flow_pair(g0: np.ndarray, g1: np.ndarray, fp: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """F01[x] = displacement of the point at x in g0 to g1; F10 = inverse direction."""
    flow01 = cv2.calcOpticalFlowFarneback(g0, g1, None, fp["pyr_scale"], fp["levels"],
                                          fp["winsize"], fp["iterations"], fp["poly_n"],
                                          fp["poly_sigma"], fp["flags"])
    flow10 = cv2.calcOpticalFlowFarneback(g1, g0, None, fp["pyr_scale"], fp["levels"],
                                          fp["winsize"], fp["iterations"], fp["poly_n"],
                                          fp["poly_sigma"], fp["flags"])
    coords = identity_coords(g0.shape) + flow01
    back, _ = bilinear(flow10, coords)
    fb_err = np.linalg.norm(back + flow01, axis=-1)
    return flow01.astype(np.float32), flow10.astype(np.float32), fb_err.astype(np.float32)


# --------------------------------------------------------------- edge guide
def edge_magnitude(gray: np.ndarray, ek: dict) -> np.ndarray:
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=ek["sobel_ksize"])
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=ek["sobel_ksize"])
    mag = np.sqrt(gx * gx + gy * gy)
    return (mag / 255.0).astype(np.float32)


def edge_mask(mag: np.ndarray, ek: dict) -> tuple[np.ndarray, float]:
    thr = float(np.percentile(mag, ek["adaptive_percentile"]))
    return (mag >= thr).astype(np.uint8), thr


def snap_mask_to_edges(mask: np.ndarray, edge_bin: np.ndarray, band: int) -> np.ndarray:
    """Boundary refinement.  Only pixels within `band` of the boundary may move:

      * interior  (>= band+1 px inside)  -> always kept;
      * boundary band pixels            -> kept only where the target frame has an
                                           edge within 1 px (unsupported stubs drop);
      * on-edge pixels adjacent (<=1 px) to the mask -> adopted (the mask grows onto
                                           the real edge).
    """
    m = (mask > 0)
    k = np.ones((3, 3), np.uint8)
    interior = cv2.erode(m.astype(np.uint8), k, iterations=band + 1) > 0
    band_px = m & ~interior
    e_near = cv2.dilate(edge_bin.astype(np.uint8), k, iterations=1) > 0
    m_near = cv2.dilate(m.astype(np.uint8), k, iterations=1) > 0
    out = interior | (band_px & e_near) | (~m & e_near & m_near)
    return out.astype(np.uint8)


# -------------------------------------------------------------- point guide
def corner_points(gray: np.ndarray, pp: dict) -> np.ndarray:
    pts = cv2.goodFeaturesToTrack(gray, maxCorners=pp["max_corners"], qualityLevel=pp["quality"],
                                  minDistance=pp["min_distance"], blockSize=7)
    if pts is None:
        return np.zeros((0, 2), dtype=np.float32)
    return pts.reshape(-1, 2).astype(np.float32)


def track_chain(grays: list[np.ndarray], start_idx: int, pp: dict,
                mask: np.ndarray | None = None) -> dict:
    """Track corners of grays[start_idx] through the sequence in one direction.

    Returns {'points': {step: (n,2) array}, 'alive': {step: bool array},
             'fb_err': {step: (n,) array}} with steps as absolute frame indexes.
    Bidirectional LK check: a point survives only while |fwd| and |bwd| agree.
    """
    g0 = grays[start_idx]
    pts = corner_points(g0, pp)
    if mask is not None and len(pts):
        keep = mask[np.clip(pts[:, 1].astype(int), 0, mask.shape[0] - 1),
                    np.clip(pts[:, 0].astype(int), 0, mask.shape[1] - 1)] > 0
        pts = pts[keep]
    out = {"points": {}, "alive": {}, "fb_err": {}, "start_idx": start_idx}
    cur = pts
    alive = np.ones(len(cur), dtype=bool)
    out["points"][start_idx] = cur.copy()
    out["alive"][start_idx] = alive.copy()
    out["fb_err"][start_idx] = np.zeros(len(cur), dtype=np.float32)
    for step in range(start_idx + 1, len(grays)):
        prev = grays[step - 1]
        nxt = grays[step]
        if len(cur) == 0:
            break
        p1, st1, e1 = cv2.calcOpticalFlowPyrLK(prev, nxt, cur.reshape(-1, 1, 2), None,
                                               winSize=pp["lk_win"], maxLevel=pp["lk_levels"],
                                               criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
        p0, st0, _ = cv2.calcOpticalFlowPyrLK(nxt, prev, p1, None,
                                              winSize=pp["lk_win"], maxLevel=pp["lk_levels"],
                                              criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
        fb = np.linalg.norm(p0.reshape(-1, 2) - cur, axis=1)
        good = ((st1.reshape(-1) == 1) & (st0.reshape(-1) == 1)
                & (fb <= float(pp.get("fb_consistency", 1.5))))
        alive = alive & good
        cur = p1.reshape(-1, 2).astype(np.float32)
        out["points"][step] = cur.copy()
        out["alive"][step] = alive.copy()
        out["fb_err"][step] = fb.astype(np.float32)
    return out


def fit_partial_affine(src: np.ndarray, dst: np.ndarray, reproj: float) -> dict:
    """RANSAC similarity (rotation+uniform scale+translation) mapping src -> dst."""
    if len(src) < 3:
        return {"ok": False, "reason": "too_few_points", "n": int(len(src))}
    m, inl = cv2.estimateAffinePartial2D(src.reshape(-1, 1, 2), dst.reshape(-1, 1, 2),
                                         method=cv2.RANSAC, ransacReprojThreshold=reproj,
                                         maxIters=3000, confidence=0.995)
    if m is None:
        return {"ok": False, "reason": "ransac_failed", "n": int(len(src))}
    inl = inl.reshape(-1).astype(bool) if inl is not None else np.ones(len(src), bool)
    pred = (src @ m[:, :2].T) + m[:, 2]
    res = np.linalg.norm(pred - dst, axis=1)
    return {
        "ok": True,
        "matrix": m.astype(np.float64),
        "inliers": int(inl.sum()),
        "n": int(len(src)),
        "inlier_ratio": float(inl.sum() / max(1, len(src))),
        "residual_px_median": float(np.median(res[inl])) if inl.any() else None,
        "residual_px_p95": float(np.percentile(res[inl], 95)) if inl.any() else None,
        "scale": float(np.sqrt(m[0, 0] ** 2 + m[0, 1] ** 2)),
        "rotation_deg": float(np.degrees(np.arctan2(m[0, 1], m[0, 0]))),
        "translation": [float(m[0, 2]), float(m[1, 2])],
        "inlier_mask": inl.astype(np.uint8).tolist(),
    }


def invert_similarity(m: np.ndarray) -> np.ndarray:
    """Invert a 2x3 partial affine (rotation/scale/translation) to a 2x3 inverse."""
    a = m[:2, :2]
    t = m[:2, 2]
    ai = np.linalg.inv(a)
    out = np.zeros((2, 3), dtype=np.float64)
    out[:2, :2] = ai
    out[:2, 2] = -ai @ t
    return out


def apply_similarity(m: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return (pts @ m[:2, :2].T) + m[:2, 2]
