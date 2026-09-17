"""mf_keyframe_reskin_v1 core: graph template, deterministic seeds, cutout recipe,
and the vision-free geometry/appearance metrics required by `KEYFRAME_SPEC.md` §1.3.

Everything here is deterministic and works from bytes. The active model on this
route has **no vision**, so no function in this module is allowed to produce a
qualitative verdict: every output is a number, a mask, or a hash.

Two independent things live here:

1. **Graph construction** — `resolve_graph()` turns the pinned template
   `workflows/mf_keyframe_reskin_v1.json` into a per-anchor ComfyUI API graph.
   Structure conditioning is mandatory (Route A): the frozen GOLDEN keyframe is
   the img2img init image and `denoise < 1.0` always. `graph_shape_hash()`
   hashes the resolved graph with the per-frame values normalised, so all 56
   renders provably share ONE pipeline shape.

2. **Measurement** — geometry drift (edge agreement, derived foreground IoU,
   scale/centroid, contact-anchor coverage) and appearance change (histogram,
   texture energy, flat-region fraction, unique colours). The foreground
   derivation in `foreground_mask()` is applied *identically* to the source
   keyframe and to the reskin frame, which is what makes the IoU meaningful.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import cv2
import numpy as np

from .pinning import canonical_json, hash_workflow

FRAME_W, FRAME_H = 640, 360
FRAME_DIAGONAL = float((FRAME_W ** 2 + FRAME_H ** 2) ** 0.5)   # 734.5749...
INIT_SIZE = (1024, 576)                                        # exactly 16:9, same px budget as 768x768
CANNY_LO, CANNY_HI = 100, 200                                  # fixed; identical for both images
CONTACT_BAND_RADIUS = 2                                        # px dilation defining the contact band
FG_TOL = 12                                                    # border-flood colour tolerance, calibrated on the SOURCE then frozen
                                                               # (raw/211_derivation_probe.json: median IoU 0.559 vs the frozen
                                                               #  non-background mask union; tol 12 beat 16/22/30/40 and the
                                                               #  edge-enclosure variant)
SEED_BASE = 20260917
SHAPE_TOKENS = {"init_image": "<INIT>", "seed": "<SEED>", "text": "<TEXT>", "prefix": "<PREFIX>"}

# --- Route A pipeline (the only route used to produce artwork) --------------
PIPELINE = "sdxl-img2img"
SAMPLER = "euler"
SCHEDULER = "normal"
STEPS = 20
CFG = 6.0


# --------------------------------------------------------------------------
# graph construction
# --------------------------------------------------------------------------
def load_template(path: str | os.PathLike[str]) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _subst(node: Any, params: dict) -> Any:
    if isinstance(node, dict):
        return {k: _subst(v, params) for k, v in node.items()}
    if isinstance(node, list):
        return [_subst(v, params) for v in node]
    if isinstance(node, str) and node.startswith("__") and node.endswith("__"):
        key = node[2:-2]
        if key not in params:
            raise KeyError(f"template placeholder {node} has no parameter")
        return params[key]
    return node


def resolve_graph(template: dict, params: dict) -> dict:
    """Instantiate the pinned template for one anchor."""
    graph = _subst(template, params)
    _validate_reskin_graph(graph, params)
    return graph


def _validate_reskin_graph(graph: dict, params: dict) -> None:
    classes = {n.get("class_type") for n in graph.values()}
    if "LoadImage" not in classes:
        raise ValueError("reskin graph must contain LoadImage (structure conditioning)")
    if "VAEEncode" not in classes:
        raise ValueError("reskin graph must VAE-encode an init image (not an EmptyLatentImage)")
    if "EmptyLatentImage" in classes:
        raise ValueError("reskin graph must not be text-to-image (EmptyLatentImage present)")
    ksampler = [n for n in graph.values() if n.get("class_type") == "KSampler"]
    if len(ksampler) != 1:
        raise ValueError("reskin graph must contain exactly one KSampler")
    denoise = float(ksampler[0]["inputs"]["denoise"])
    if not 0.0 < denoise < 1.0:
        raise ValueError(f"denoise must be strictly between 0 and 1, got {denoise}")
    if params.get("init_image"):
        li = [n for n in graph.values() if n.get("class_type") == "LoadImage"]
        if li[0]["inputs"]["image"] != params["init_image"]:
            raise ValueError("LoadImage must name the staged frozen keyframe")


def graph_shape_hash(graph: dict) -> str:
    """Hash of the resolved graph with the per-anchor VALUES normalised.

    Proves every render in the set ran the SAME pipeline shape: same node
    classes, same links, same resolutions, same sampler/steps/cfg/scheduler, and
    the same denoise. Only the per-anchor data (init image, seed, prompt text and
    output prefix) is masked out — those are recorded verbatim in each run
    record, not hidden.
    """
    g = json.loads(json.dumps(graph))
    for node in g.values():
        ct = node.get("class_type")
        if ct == "LoadImage":
            node["inputs"]["image"] = SHAPE_TOKENS["init_image"]
        elif ct == "KSampler":
            node["inputs"]["seed"] = SHAPE_TOKENS["seed"]
        elif ct == "CLIPTextEncode":
            node["inputs"]["text"] = SHAPE_TOKENS["text"]
        elif ct == "SaveImage":
            node["inputs"]["filename_prefix"] = SHAPE_TOKENS["prefix"]
    return hash_workflow(g)


def deterministic_seed(tag: str, frame_id: int, base: int = SEED_BASE) -> int:
    """Reproducible per-anchor seed; never reused across anchors."""
    material = f"{tag}|{frame_id}|{base}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big") & 0x7FFFFFFF


def build_params(tag: str, frame_id: int, init_image: str, positive: str, negative: str,
                 denoise: float, prefix: str, seed: int | None = None) -> dict:
    return {
        "init_image": init_image,
        "positive": positive,
        "negative": negative,
        "seed": deterministic_seed(tag, frame_id) if seed is None else int(seed),
        "steps": STEPS,
        "cfg": CFG,
        "sampler_name": SAMPLER,
        "scheduler": SCHEDULER,
        "denoise": float(denoise),
        "prefix": prefix,
    }


# --------------------------------------------------------------------------
# per-role cutouts — recipe proven byte-identical to GOLDEN's make_references.py
# --------------------------------------------------------------------------
def role_cutout(frame_bgr: np.ndarray, mask_index: np.ndarray, index: int,
                bbox_xywh) -> np.ndarray:
    """RGBA cutout = frame pixels where the mask index equals this role's index,
    cropped to the frozen legend bbox. Same recipe as GOLDEN `make_references.py`."""
    m = (mask_index == index)
    x, y, w, h = [int(v) for v in bbox_xywh]
    rgba = np.dstack([frame_bgr, (m * 255).astype(np.uint8)])
    return rgba[y:y + h, x:x + w]


def read_mask_index(path: str | os.PathLike[str]) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"mask index not decodable: {path}")
    return img


def read_bgr(path: str | os.PathLike[str]) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"image not decodable: {path}")
    return img


# --------------------------------------------------------------------------
# masks / agreement
# --------------------------------------------------------------------------
def gray_of(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def canny_edges(gray: np.ndarray) -> np.ndarray:
    """Canny with the frozen, documented thresholds (identical for both images)."""
    g = cv2.GaussianBlur(gray, (5, 5), 1.4)
    return cv2.Canny(g, CANNY_LO, CANNY_HI)


def iou(a: np.ndarray, b: np.ndarray) -> float:
    A, B = a > 0, b > 0
    union = int(np.count_nonzero(A | B))
    if union == 0:
        return 1.0
    return float(np.count_nonzero(A & B)) / float(union)


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    x = a.astype(np.float64).ravel()
    y = b.astype(np.float64).ravel()
    x -= x.mean()
    y -= y.mean()
    denom = float(np.sqrt((x * x).sum() * (y * y).sum()))
    if denom == 0.0:
        return 0.0
    return float((x * y).sum() / denom)


def foreground_mask_edge(bgr: np.ndarray) -> np.ndarray:
    """Edge-enclosure variant, kept only to document why it was NOT chosen.

    Measured against the frozen non-background mask union on the 56 SOURCE
    keyframes it is poor (median IoU ~0.4): enclosing the drawing's outer contour
    also captures background patches that the contour closes off. Recorded as a
    rejected candidate in `raw/211_derivation_probe.json`.
    """
    gray = gray_of(bgr)
    h, w = gray.shape[:2]
    g = cv2.GaussianBlur(gray, (0, 0), 1.2)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    m8 = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    thr = cv2.adaptiveThreshold(m8, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, -6)
    barrier = cv2.dilate(thr, np.ones((5, 5), np.uint8), iterations=1)
    barrier = cv2.morphologyEx(barrier, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))

    ff = barrier.copy()
    ff_mask = np.zeros((h + 2, w + 2), np.uint8)
    for sx, sy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if ff[sy, sx] == 0:
            cv2.floodFill(ff, ff_mask, (sx, sy), 255)
    fg = cv2.bitwise_not(ff)
    return _clean_mask(fg)


def _clean_mask(fg: np.ndarray, min_area_frac: float = 0.002) -> np.ndarray:
    h, w = fg.shape[:2]
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    out = np.zeros_like(fg)
    min_area = min_area_frac * h * w
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            out[lab == i] = 255
    return out


def foreground_mask(bgr: np.ndarray, tol: int = FG_TOL) -> np.ndarray:
    """Deterministic subject mask: everything not reachable from the frame border
    by a colour-similar flood.

    Border-seeded flood fill (fixed range, per-channel tolerance `tol`) defines
    the background as the region connected to the frame edge whose colours are
    similar to the edge colours; the subject is the complement. The SAME function
    with the SAME tolerance is applied to the source keyframe and to the reskin
    frame — that is what makes the IoU between them meaningful.

    `tol` is calibrated on the source only (see `raw/211_derivation_probe.json`)
    and then frozen for every measurement in this round.

    Degenerate input: a uniform frame (e.g. a blank black transition frame) has no
    border-dissimilar region at all, so the result is an empty mask. That is the
    correct answer for such a frame and it is reported as a degenerate source
    anchor rather than silently repaired.
    """
    h, w = bgr.shape[:2]
    sw, sh = 320, 180
    small = cv2.resize(bgr, (sw, sh), interpolation=cv2.INTER_AREA)
    ff = small.copy()
    ff_mask = np.zeros((sh + 2, sw + 2), np.uint8)
    flags = 8 | cv2.FLOODFILL_FIXED_RANGE
    diff = (tol, tol, tol)
    for x in range(sw):
        for y in (0, sh - 1):
            if ff_mask[y + 1, x + 1] == 0:
                cv2.floodFill(ff, ff_mask, (x, y), (0, 0, 0), diff, diff, flags)
    for y in range(sh):
        for x in (0, sw - 1):
            if ff_mask[y + 1, x + 1] == 0:
                cv2.floodFill(ff, ff_mask, (x, y), (0, 0, 0), diff, diff, flags)
    bg = (ff_mask[1:-1, 1:-1] > 0).astype(np.uint8)
    fg_small = ((1 - bg) * 255).astype(np.uint8)
    fg = cv2.resize(fg_small, (w, h), interpolation=cv2.INTER_NEAREST)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return _clean_mask(fg)


def bbox_of(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return (0, 0, 0, 0)
    return (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))


def centroid_of(mask: np.ndarray) -> tuple[float, float]:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return (float("nan"), float("nan"))
    return (float(xs.mean()), float(ys.mean()))


def envelope_iou(m1: np.ndarray, m2: np.ndarray, size=(128, 72)) -> float:
    """Scale/translation-normalised silhouette-envelope agreement, aspect preserving.

    Each mask is cropped to its own bbox and fitted (aspect ratio preserved,
    centred) onto a common canvas, so this measures *shape* agreement and is
    insensitive to pure global drift — which the bbox/centroid metrics carry
    instead. Aspect ratio is preserved on purpose: a fixed-stretch resize would
    map any rectangle onto the whole canvas and report IoU 1.0 for shapes that
    are nothing alike.
    """
    cw, ch = size
    out = []
    for m in (m1, m2):
        x, y, w, h = bbox_of(m)
        canvas = np.zeros((ch, cw), np.uint8)
        if w == 0 or h == 0:
            out.append(canvas)
            continue
        crop = m[y:y + h, x:x + w]
        scale = min(cw / float(w), ch / float(h))
        nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
        small = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_NEAREST)
        ox, oy = (cw - nw) // 2, (ch - nh) // 2
        canvas[oy:oy + nh, ox:ox + nw] = (small > 0).astype(np.uint8) * 255
        out.append(canvas)
    return iou(out[0], out[1])


def contact_band(mask_index: np.ndarray, idx_a: int, idx_b: int,
                 radius: int = CONTACT_BAND_RADIUS) -> np.ndarray:
    """Pixels on the shared boundary between two frozen role masks."""
    a = (mask_index == idx_a).astype(np.uint8)
    b = (mask_index == idx_b).astype(np.uint8)
    k = np.ones((2 * radius + 1, 2 * radius + 1), np.uint8)
    da = cv2.dilate(a, k)
    db = cv2.dilate(b, k)
    return (((da > 0) & (b > 0)) | ((db > 0) & (a > 0))).astype(np.uint8)


def coverage(band: np.ndarray, mask: np.ndarray) -> tuple[int, int, float]:
    total = int(np.count_nonzero(band))
    if total == 0:
        return 0, 0, float("nan")
    covered = int(np.count_nonzero((band > 0) & (mask > 0)))
    return total, covered, covered / total


# --------------------------------------------------------------------------
# appearance change (must be more than a palette swap)
# --------------------------------------------------------------------------
def colour_hist(bgr: np.ndarray, bins: int = 32) -> np.ndarray:
    h = []
    for c in range(3):
        hh = cv2.calcHist([bgr], [c], None, [bins], [0, 256]).ravel()
        h.append(hh / max(1.0, hh.sum()))
    return np.concatenate(h)


def hist_l1(bgr_a: np.ndarray, bgr_b: np.ndarray, mask: np.ndarray | None = None) -> float:
    if mask is not None and np.count_nonzero(mask) > 0:
        a = cv2.calcHist([bgr_a], [0, 1, 2], mask, [32, 32, 32], [0, 256] * 3).ravel()
        b = cv2.calcHist([bgr_b], [0, 1, 2], mask, [32, 32, 32], [0, 256] * 3).ravel()
        a = a / max(1.0, a.sum())
        b = b / max(1.0, b.sum())
        return float(np.abs(a - b).sum())
    return float(np.abs(colour_hist(bgr_a) - colour_hist(bgr_b)).sum())


def texture_energy(bgr: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Mean local standard deviation (9x9) — a texture/frequency statistic, not a palette one."""
    gray = gray_of(bgr).astype(np.float32)
    mean = cv2.blur(gray, (9, 9))
    sq = cv2.blur(gray * gray, (9, 9))
    var = np.clip(sq - mean * mean, 0.0, None)
    std = np.sqrt(var)
    if mask is not None and np.count_nonzero(mask) > 0:
        return float(std[mask > 0].mean())
    return float(std.mean())


def flat_fraction(bgr: np.ndarray, thresh: float = 2.0) -> float:
    """Fraction of pixels that sit in a locally flat (single-colour) patch.

    A flat-colour source is dominated by these; a photographic render is not.
    This separates a real medium change from a palette swap.
    """
    gray = gray_of(bgr).astype(np.float32)
    mean = cv2.blur(gray, (5, 5))
    sq = cv2.blur(gray * gray, (5, 5))
    std = np.sqrt(np.clip(sq - mean * mean, 0.0, None))
    return float(np.count_nonzero(std < thresh)) / float(std.size)


def unique_colour_ratio(bgr: np.ndarray) -> float:
    q = (bgr // 8).astype(np.uint8)
    idx = (q[:, :, 0].astype(np.uint32) << 16) | (q[:, :, 1].astype(np.uint32) << 8) | q[:, :, 2]
    return float(np.unique(idx).size) / float(idx.size)


def pixel_l1(bgr_a: np.ndarray, bgr_b: np.ndarray, mask: np.ndarray | None = None) -> float:
    d = np.abs(bgr_a.astype(np.int16) - bgr_b.astype(np.int16))
    if mask is not None and np.count_nonzero(mask) > 0:
        return float(d[mask > 0].mean())
    return float(d.mean())


def appearance_stats(src_bgr: np.ndarray, res_bgr: np.ndarray, mask: np.ndarray | None = None) -> dict:
    return {
        "hist_l1": hist_l1(src_bgr, res_bgr, mask),
        "hist_l1_global": hist_l1(src_bgr, res_bgr, None),
        "texture_energy_src": texture_energy(src_bgr, mask),
        "texture_energy_reskin": texture_energy(res_bgr, mask),
        "texture_entropy_delta": texture_energy(res_bgr, mask) - texture_energy(src_bgr, mask),
        "flat_fraction_src": flat_fraction(src_bgr),
        "flat_fraction_reskin": flat_fraction(res_bgr),
        "flat_fraction_delta": flat_fraction(src_bgr) - flat_fraction(res_bgr),
        "unique_colour_ratio_src": unique_colour_ratio(src_bgr),
        "unique_colour_ratio_reskin": unique_colour_ratio(res_bgr),
        "unique_colour_ratio": unique_colour_ratio(res_bgr) / max(1e-9, unique_colour_ratio(src_bgr)),
        "pixel_l1": pixel_l1(src_bgr, res_bgr, mask),
    }


def masked_edges(edges: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Canny edge map restricted to a region (used with the frozen masks)."""
    return cv2.bitwise_and(edges, edges, mask=(mask > 0).astype(np.uint8) * 255)


def content_contrast(bgr: np.ndarray, subject: np.ndarray) -> float:
    """Mean local texture energy inside a region divided by the value outside it.

    Measured with the FROZEN mask as the region, so no derivation is involved:
    if the reskin kept the geometry, its structural content must be concentrated
    where the frozen masks say the subject is, in the same proportion the source
    had. Robust to the flat-colour -> photographic medium change (it is a ratio).
    """
    te = texture_energy_map(bgr)
    sub = subject > 0
    inn = float(te[sub].mean()) if np.count_nonzero(sub) else float("nan")
    out = float(te[~sub].mean()) if np.count_nonzero(~sub) else float("nan")
    if not np.isfinite(inn) or not np.isfinite(out) or out <= 0:
        return float("nan")
    return inn / out


def texture_energy_map(bgr: np.ndarray, ksize: int = 9) -> np.ndarray:
    gray = gray_of(bgr).astype(np.float32)
    mean = cv2.blur(gray, (ksize, ksize))
    sq = cv2.blur(gray * gray, (ksize, ksize))
    return np.sqrt(np.clip(sq - mean * mean, 0.0, None))


def summarise(values: list[float]) -> dict:
    v = [float(x) for x in values if x is not None and not (isinstance(x, float) and np.isnan(x))]
    if not v:
        return {"n": 0, "min": None, "median": None, "mean": None, "max": None, "stdev": None}
    a = np.array(v, dtype=np.float64)
    return {
        "n": len(v),
        "min": float(a.min()),
        "median": float(np.median(a)),
        "mean": float(a.mean()),
        "max": float(a.max()),
        "stdev": float(a.std(ddof=0)),
    }


def write_json_atomic(path: str | os.PathLike[str], payload: Any, indent: int = 1) -> None:
    p = str(path)
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    tmp = f"{p}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=indent, sort_keys=True, ensure_ascii=False)
    os.replace(tmp, p)


def sha256_file(path: str | os.PathLike[str], chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def canonical(obj: Any) -> str:
    return canonical_json(obj)


# ==========================================================================
# continuation-03 — fix 1: a degenerate SOURCE frame is not perfect geometry
# ==========================================================================
DEGENERATE_SOURCE_CODE = "degenerate_source_frame"

DEGENERATE_CONSEQUENCE = (
    "a uniform source frame has no subject at all: foreground_mask() returns an empty "
    "mask, bbox_of() returns (0, 0, 0, 0) and iou(empty, empty) is 1.0 by definition, so "
    "every geometry metric computed on such an anchor is vacuous and must never be read "
    "as agreement"
)


def frame_degeneracy(bgr: np.ndarray) -> dict:
    """Is this frame *measurable at all*?

    Defect found by this worker in continuation-02 and corrected here: `CAM_4212`
    f4212 and f4227 are pure black transition frames, and with them in the set the
    geometry metrics returned vacuous values (``iou(empty, empty) == 1.0``,
    ``bbox_area_ratio == 1.0`` from ``max(1, 0) / max(1, 0)``) which *inflated* the
    aggregate. A degenerate anchor is therefore marked with the stable code
    `degenerate_source_frame`, excluded from every gate
    (`eligible_for_gates == False`) and reported in its own list.

    It is not repaired, not interpolated, not re-frozen and never counted as a win.
    The frozen fixture stays frozen: this is a measurement correction, not a change
    to the fixture, the window set or GOLDEN's artifacts.
    """
    flat = bgr.reshape(-1, 3)
    per_channel_std = flat.astype(np.int16).std(0)
    n_colours = int(np.unique(flat, axis=0).shape[0])
    reasons: list[str] = []
    if float(per_channel_std.max()) == 0.0:
        reasons.append("zero_variance_every_channel")
    if n_colours <= 1:
        reasons.append("single_colour_frame")
    return {
        "degenerate": bool(reasons),
        "exclusion_code": DEGENERATE_SOURCE_CODE if reasons else None,
        "reasons": reasons,
        "per_channel_std_max": float(per_channel_std.max()),
        "unique_colours": n_colours,
        "mean_gray": float(gray_of(bgr).mean()),
        "consequence": DEGENERATE_CONSEQUENCE if reasons else None,
    }


def anchor_eligibility(src_bgr: np.ndarray) -> dict:
    """Gate eligibility of one anchor, decided from the SOURCE frame only."""
    d = frame_degeneracy(src_bgr)
    return {
        "eligible_for_gates": not d["degenerate"],
        "exclusion_code": d["exclusion_code"],
        "degeneracy": d,
        "note": ("degenerate anchors are excluded from the gates and reported separately; "
                 "they are never counted as geometry that held"),
    }


# ==========================================================================
# continuation-03 — fix 2: the frozen mask union is the SUBJECT, derivation-free
# ==========================================================================
def frozen_subject_union(mask_index: np.ndarray, legend: list[dict],
                         kinds: dict[str, str],
                         exclude_kinds: tuple[str, ...] = ("background",)) -> np.ndarray:
    """The frozen (GOLDEN SAM-2) mask union, used as the SUBJECT region.

    Fix 2 of continuation-03. Nothing here is derived: `mask_index` and `legend`
    are frozen fixture bytes and `kinds` is the frozen `kind_structural` table, so
    the subject definition cannot carry the medium bias of a per-frame
    `foreground_mask()` call.

    Measured bias that motivated the fix (continuation-02, `raw/212_source_baseline.json`):
    the derived foreground matches this union at median IoU **0.559** (min 0.027)
    over the 54 measurable anchors, and on `WALK_7927` f7927 it covers **0 of the
    3,170** contact-band pixels of the SOURCE itself - i.e. `fg_iou` and the
    derived envelope were measuring the derivation, not the reskin.

    `kinds.get(role_id)` returning `None` (a role absent from the window table) is
    INCLUDED, matching the union the continuation-02 artifacts already reported as
    `nonbg`, so the corrected numbers stay comparable with the frozen ones.
    """
    out = np.zeros(mask_index.shape, np.uint8)
    for entry in legend:
        if kinds.get(entry["role_id"]) in exclude_kinds:
            continue
        out[mask_index == int(entry["index"])] = 255
    return out


def layout_shift(src_bgr: np.ndarray, res_bgr: np.ndarray, margin: int = 24) -> dict:
    """Derivation-free layout drift: the translation that best aligns the two frames.

    The gradient-magnitude map of the source's central patch is matched inside the
    reskin's with `cv2.matchTemplate`, searching +/-`margin` px. No mask is
    derived anywhere, so this is immune to the subject-derivation bias, and it is
    a direct measurement of KEYFRAME_SPEC 1.2 ``layout / framing must NOT change``.
    A peak that sits off centre means the render moved.
    """
    def grad(bgr: np.ndarray) -> np.ndarray:
        g = cv2.GaussianBlur(gray_of(bgr), (5, 5), 1.4)
        return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0),
                             cv2.Sobel(g, cv2.CV_32F, 0, 1))

    gs, gr = grad(src_bgr), grad(res_bgr)
    h, w = gs.shape[:2]
    ph, pw = int(h * 0.5), int(w * 0.5)
    y0, x0 = (h - ph) // 2, (w - pw) // 2
    patch = gs[y0:y0 + ph, x0:x0 + pw]
    ys, xs = max(0, y0 - margin), max(0, x0 - margin)
    ye, xe = min(h, y0 + ph + margin), min(w, x0 + pw + margin)
    window = gr[ys:ye, xs:xe]
    if window.shape[0] < ph or window.shape[1] < pw:
        return {"dx": None, "dy": None, "px": None, "pct_diag": None, "peak_corr": None}
    r = cv2.matchTemplate(window, patch, cv2.TM_CCOEFF_NORMED)
    _, peak, _, loc = cv2.minMaxLoc(r)
    dx, dy = float(loc[0] + xs - x0), float(loc[1] + ys - y0)
    return {"dx": dx, "dy": dy, "px": float(np.hypot(dx, dy)),
            "pct_diag": 100.0 * float(np.hypot(dx, dy)) / FRAME_DIAGONAL,
            "peak_corr": float(peak)}


def edge_density_in(edges: np.ndarray, region: np.ndarray) -> float:
    """Fraction of a frozen region that carries detected structure."""
    n = int(np.count_nonzero(region))
    if n == 0:
        return float("nan")
    return float(np.count_nonzero((edges > 0) & (region > 0))) / float(n)


def geometry_metrics_frozen_subject(src_bgr: np.ndarray, res_bgr: np.ndarray,
                                    subject: np.ndarray) -> dict:
    """PRIMARY geometry family (continuation-03): the frozen mask union IS the subject.

    `subject` comes from `frozen_subject_union()` — frozen fixture bytes, no
    per-frame derivation — so none of these rows can be biased by the
    flat-colour -> photographic medium change in the way `fg_iou` and the derived
    envelope were.

    Rows:
      edge_iou_in_frozen_subject   Canny agreement restricted to the frozen subject
                                   region: derivation-free on BOTH sides (frozen
                                   region, frozen thresholds).
      edge_corr_in_frozen_subject  the same agreement as a correlation.
      edge_density_src/reskin      share of the frozen subject region that carries
                                   detected structure, and their ratio: 1.0 means
                                   the reskin put its structure where the frozen
                                   subject is, in the same proportion.
      content_contrast_src/reskin  subject/background local-texture-energy ratio
                                   measured with the frozen region (threshold-free,
                                   robust to the medium change), and their ratio.
      layout_shift_*               whole-frame translation, derivation-free.
    """
    e_s = canny_edges(gray_of(src_bgr))
    e_r = canny_edges(gray_of(res_bgr))
    ccs = content_contrast(src_bgr, subject)
    ccr = content_contrast(res_bgr, subject)
    ds = edge_density_in(e_s, subject)
    dr = edge_density_in(e_r, subject)
    gs = gray_of(src_bgr).astype(np.float32)
    gr = gray_of(res_bgr).astype(np.float32)
    sub = subject > 0
    corr = pearson(np.where(sub, gs, 0.0), np.where(sub, gr, 0.0))
    shift = layout_shift(src_bgr, res_bgr)
    return {
        "subject_definition": "frozen_mask_union(kind_structural != 'background')",
        "subject_derivation": "none (frozen fixture bytes)",
        "subject_px": int(np.count_nonzero(subject)),
        "edge_iou_in_frozen_subject": iou(masked_edges(e_s, subject), masked_edges(e_r, subject)),
        "edge_iou_full_frame": iou(e_s, e_r),
        "edge_corr_in_frozen_subject": corr,
        "edge_density_src": ds,
        "edge_density_reskin": dr,
        "edge_density_ratio": (dr / ds) if (ds and np.isfinite(ds) and ds > 0) else float("nan"),
        "content_contrast_src": ccs,
        "content_contrast_reskin": ccr,
        "content_contrast_ratio": (ccr / ccs) if (ccs and np.isfinite(ccs) and ccs > 0) else float("nan"),
        "layout_shift_px": shift["px"],
        "layout_shift_pct_diag": shift["pct_diag"],
        "layout_shift_peak_corr": shift["peak_corr"],
    }


DERIVED_BIAS_NOTE = (
    "the per-frame foreground_mask() derivation recovers the frozen subject at median IoU "
    "0.559 (min 0.027, n=54) on the SOURCE itself and covers 0 of WALK_7927 f7927's 3,170 "
    "contact-band pixels, so these rows measure the derivation as well as the reskin. They "
    "are reported for continuity with continuation-02 and are NOT the primary gate."
)


def geometry_metrics_derived_foreground(src_bgr: np.ndarray, res_bgr: np.ndarray,
                                        subject: np.ndarray,
                                        fg_src: np.ndarray | None = None,
                                        fg_res: np.ndarray | None = None) -> dict:
    """SECONDARY geometry family: subject = a mask DERIVED per frame. Bias-labelled.

    Kept because continuation-02's frozen gate is defined on these rows, so the
    pre-registered rule can still be applied unchanged — but the frozen subject is
    reported next to each row as the fair reference, which is what exposes the
    derivation bias instead of hiding it.
    """
    fg_src = foreground_mask(src_bgr) if fg_src is None else fg_src
    fg_res = foreground_mask(res_bgr) if fg_res is None else fg_res
    bb_s, bb_r = bbox_of(fg_src), bbox_of(fg_res)
    c_s, c_r = centroid_of(fg_src), centroid_of(fg_res)
    dx, dy = c_r[0] - c_s[0], c_r[1] - c_s[1]
    shift = float((dx * dx + dy * dy) ** 0.5) if (np.isfinite(dx) and np.isfinite(dy)) else float("nan")
    return {
        "bias": DERIVED_BIAS_NOTE,
        "fg_iou": iou(fg_src, fg_res),
        "envelope_iou": envelope_iou(fg_src, fg_res),
        "bbox_area_ratio": (float(max(1, bb_r[2] * bb_r[3]))
                            / float(max(1, bb_s[2] * bb_s[3]))),
        "bbox_w_ratio": float(bb_r[2]) / float(max(1, bb_s[2])),
        "bbox_h_ratio": float(bb_r[3]) / float(max(1, bb_s[3])),
        "centroid_shift_px": shift,
        "centroid_shift_pct_diag": 100.0 * shift / FRAME_DIAGONAL if np.isfinite(shift) else float("nan"),
        # the fair in-source references: derived mask vs the FROZEN subject
        "fg_vs_frozen_subject_iou_source": iou(fg_src, subject),
        "fg_vs_frozen_subject_iou_reskin": iou(fg_res, subject),
        "envelope_vs_frozen_subject_source": envelope_iou(subject, fg_src),
        "envelope_vs_frozen_subject_reskin": envelope_iou(subject, fg_res),
        "fg_fraction_src": float(np.count_nonzero(fg_src)) / fg_src.size,
        "fg_fraction_reskin": float(np.count_nonzero(fg_res)) / fg_res.size,
        "fg_bbox_src": list(bb_s),
        "fg_bbox_reskin": list(bb_r),
    }


def highpass(gray: np.ndarray, ksize: int = 9) -> np.ndarray:
    g = gray.astype(np.float32)
    return g - cv2.blur(g, (ksize, ksize))


def lut_remap(src_bgr: np.ndarray, res_bgr: np.ndarray,
              mask: np.ndarray | None = None) -> np.ndarray:
    """Apply the best per-channel monotone LUT (fitted src->res) to `src_bgr`."""
    sel = slice(None) if mask is None else (mask > 0)
    out = np.zeros_like(src_bgr)
    for c in range(3):
        s = src_bgr[:, :, c][sel].astype(np.uint8).ravel()
        r = res_bgr[:, :, c][sel].astype(np.uint8).ravel()
        if s.size == 0:
            return src_bgr.copy()
        hist_s = np.bincount(s, minlength=256).astype(np.float64)
        hist_r = np.bincount(r, minlength=256).astype(np.float64)
        cdf_s = np.cumsum(hist_s) / max(1.0, hist_s.sum())
        cdf_r = np.cumsum(hist_r) / max(1.0, hist_r.sum())
        lut = np.searchsorted(cdf_r, cdf_s, side="left").clip(0, 255).astype(np.uint8)
        out[:, :, c] = lut[src_bgr[:, :, c]]
    return out


def palette_lut_residual(src_bgr: np.ndarray, res_bgr: np.ndarray,
                         mask: np.ndarray | None = None) -> dict:
    """Best per-channel monotone LUT from src to res, and its residual.

    A palette-only change IS exactly such a mapping, so a near-zero residual means
    the change could be palette-only; a large residual means it cannot be.
    """
    sel = slice(None) if mask is None else (mask > 0)
    remapped = lut_remap(src_bgr, res_bgr, mask)
    d = np.abs(remapped.astype(np.int16) - res_bgr.astype(np.int16))
    dz = d if mask is None else d[mask > 0]
    return {
        "residual": float(dz.mean()) / 255.0 if dz.size else float("nan"),
        "within_16_fraction": (float(np.count_nonzero(dz <= 16)) / float(dz.size)
                               if dz.size else float("nan")),
        "pixels": int(dz.size),
    }


def structure_after_lut(src_bgr: np.ndarray, res_bgr: np.ndarray,
                        mask: np.ndarray | None = None) -> dict:
    """Is the render's STRUCTURE explained by a colour remap of the source?

    `KEYFRAME_SPEC` hard constraint: "a palette-only or histogram-only change is
    NOT a reskin". A pixel-wise colour mapping reproduces both the colours and the
    structure of the source, so comparing `LUT(source)` with the render is a
    direct, threshold-free test:

      edge_iou_lut_vs_render / highpass_corr_lut_vs_render near 1.0
          => the render could be a pure colour remap (NOT a reskin)
      both well below 1.0
          => the render contains structure the source never had
    """
    lut_src = lut_remap(src_bgr, res_bgr, mask)
    e_lut = canny_edges(gray_of(lut_src))
    e_res = canny_edges(gray_of(res_bgr))
    e_src = canny_edges(gray_of(src_bgr))
    return {
        "edge_iou_lut_vs_render": iou(e_lut, e_res),
        "edge_iou_src_vs_render": iou(e_src, e_res),
        "edge_iou_lut_vs_src": iou(e_lut, e_src),
        "highpass_corr_lut_vs_render": pearson(highpass(gray_of(lut_src)),
                                               highpass(gray_of(res_bgr))),
        "highpass_corr_src_vs_render": pearson(highpass(gray_of(src_bgr)),
                                               highpass(gray_of(res_bgr))),
    }
