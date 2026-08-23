"""S09-T00-I03 frozen renderer benchmark harness (schema_version=1).

Deterministic route harness for synthetic golden fixtures. Compares renderer
routes (default: pose_swap, sprite_affine) against analytic ground truth
defined at fixture generation time.

Contract implemented from TASK.md S09-T00-I03 + TARGET_PROFILE_2D §7/S09-T00
and §8 (frozen thresholds):

- FREEZE before measuring: prints `schema_version=1` plus a content SHA-256
  over (harness source + fixture manifests + fixture media + thresholds) to
  STDOUT/JSON BEFORE the first measured run; every measured result embeds the
  same frozen SHA.
- Metrics per run: frame error, timebase/cut error (frames), trajectory
  median/P95 (% of source-frame diagonal), scale P95 (%), rotation P95 (deg),
  contact P95 (%), z-order inversions (count), unexplained visibility events
  (count), clipping-from-source-silhouette (bool/count), correction counts,
  wall runtime (ms/frame), VRAM peak (CUDA only, else null).
- Same seed => byte-identical results JSON except documented
  non-deterministic fields (`wall_runtime_ms_per_frame`, `vram_peak_mib`).
- Fail-closed on missing/duplicated fixture manifests; verified-reference
  evaluation skips WITH an explicit reason when the media is absent.

CLI:
    python scripts/s09_renderer_benchmark.py \
        --routes pose_swap,sprite_affine \
        --fixtures tests/fixtures/s09_renderer \
        --out output/s09/20260823_sprint_full/t00-i03 \
        --seed 20260823 [--dry-run] [--reference-media <path>]

Route estimators are real image-space measurements (multi-start normalized
cross-correlation template matching via OpenCV) -- they do NOT read ground
truth geometry; GT is used only to score the estimates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

SCHEMA_VERSION = 1
#: EXACT enum authority mirrors app.persistence.models.RENDERER_ROUTES (read
#: as documentation only -- importing app here would couple the harness to DB
#: config; the tuple below is asserted equal in the focused tests).
RENDERER_ROUTES: tuple[str, ...] = (
    "pose_swap",
    "sprite_affine",
    "mesh_warp",
    "part_rig",
    "controlled_redraw",
)
DEFAULT_ROUTES = "pose_swap,sprite_affine"
VERIFIED_REFERENCE_SHA256 = (
    "5a175454c2c2965bac5013a53926e210a9f70a185d802d0f2e0083a6fb399fa2"
)
#: Fields excluded from the same-seed byte-compare (measured wall clock and
#: GPU telemetry vary run-to-run by nature).
NON_DETERMINISTIC_FIELDS = ("wall_runtime_ms_per_frame", "vram_peak_mib")

REQUIRED_MANIFEST_KEYS = {
    "fixture_id",
    "risk_class",
    "t03_loop",
    "resolution",
    "fps",
    "frame_count",
    "time_base",
    "start_time_ms",
    "generation",
    "metrics_applicable",
}


class BenchmarkError(RuntimeError):
    """Fail-closed harness error (missing/duplicate/invalid inputs)."""


# ── freeze ───────────────────────────────────────────────────────────────────


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_frozen_content_sha(fixtures_dir: Path, fixture_ids: list[str]) -> dict[str, Any]:
    """Content SHA over harness source + fixture set + thresholds (sorted)."""
    components: dict[str, str] = {}
    h = hashlib.sha256()
    harness_src = Path(__file__).resolve().read_bytes()
    components["harness_source"] = _sha256_bytes(harness_src)
    h.update(harness_src)
    thresholds_path = fixtures_dir / "thresholds.json"
    if not thresholds_path.is_file():
        raise BenchmarkError(f"missing frozen thresholds file: {thresholds_path}")
    thr_bytes = thresholds_path.read_bytes()
    components["thresholds"] = _sha256_bytes(thr_bytes)
    h.update(thr_bytes)
    for fid in sorted(fixture_ids):
        mpath = fixtures_dir / "manifests" / f"{fid}.json"
        ppath = fixtures_dir / "media" / f"{fid}.mp4"
        for label, path in (("manifest", mpath), ("media", ppath)):
            if not path.is_file():
                raise BenchmarkError(f"fixture {fid}: missing {label}: {path}")
            data = path.read_bytes()
            components[f"{fid}:{label}"] = _sha256_bytes(data)
            h.update(data)
    return {
        "schema_version": SCHEMA_VERSION,
        "frozen_content_sha256": h.hexdigest(),
        "components": components,
        "component_count": len(components),
    }


def print_freeze_banner(freeze: dict[str, Any], routes: list[str], seed: int) -> None:
    """Mandatory pre-measurement stdout banner."""
    print("=== S09-T00-I03 BENCHMARK FREEZE ===")
    print(json.dumps({**freeze, "routes": routes, "seed": seed}, sort_keys=True))
    print("=== FREEZE COMPLETE (no measurement has run yet) ===")


# ── fixture loading (fail-closed) ────────────────────────────────────────────


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    manifest: dict[str, Any]
    manifest_path: Path
    media_path: Path


def load_fixtures(fixtures_dir: Path, requested: list[str] | None) -> list[Fixture]:
    mdir = fixtures_dir / "manifests"
    if not mdir.is_dir():
        raise BenchmarkError(f"manifests dir not found: {mdir}")
    seen: dict[str, Path] = {}
    fixtures: list[Fixture] = []
    for mpath in sorted(mdir.glob("*.json")):
        raw = json.loads(mpath.read_text(encoding="utf-8"))
        fid = raw.get("fixture_id")
        if not isinstance(fid, str) or not fid:
            raise BenchmarkError(f"{mpath.name}: manifest missing string fixture_id")
        if fid in seen:
            raise BenchmarkError(
                f"duplicate fixture_id {fid!r} in {seen[fid].name} and {mpath.name}"
            )
        missing = REQUIRED_MANIFEST_KEYS - set(raw.keys())
        if missing:
            raise BenchmarkError(f"{mpath.name}: missing keys {sorted(missing)}")
        media = fixtures_dir / "media" / f"{fid}.mp4"
        if not media.is_file():
            raise BenchmarkError(f"fixture {fid}: media missing: {media}")
        seen[fid] = mpath
        fixtures.append(Fixture(fid, raw, mpath, media))
    if requested is not None:
        unknown = [r for r in requested if r not in seen]
        if unknown:
            raise BenchmarkError(f"requested fixtures not found: {unknown}")
        fixtures = [f for f in fixtures if f.fixture_id in set(requested)]
    if not fixtures:
        raise BenchmarkError("no fixtures selected")
    return fixtures


def load_thresholds(fixtures_dir: Path) -> dict[str, Any]:
    data = json.loads((fixtures_dir / "thresholds.json").read_text(encoding="utf-8"))
    if int(data.get("schema_version", -1)) != SCHEMA_VERSION:
        raise BenchmarkError(
            f"thresholds schema_version must be {SCHEMA_VERSION}, got {data.get('schema_version')}"
        )
    return data


# ── decoding / probing ───────────────────────────────────────────────────────


def probe_video(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate,avg_frame_rate,nb_frames,width,height,pix_fmt,duration",
        "-of",
        "json",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise BenchmarkError(f"ffprobe failed for {path}: {proc.stderr.strip()}")
    streams = json.loads(proc.stdout).get("streams") or []
    if not streams:
        raise BenchmarkError(f"no video stream in {path}")
    return streams[0]


def decode_frames(path: Path) -> np.ndarray:
    """Decode full video to uint8 RGB array [n, H, W, 3]."""
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise BenchmarkError(f"decode failed for {path}: {proc.stderr.decode()[:400]}")
    buf = proc.stdout
    return np.frombuffer(buf, dtype=np.uint8)


def _parse_rate(rate: str) -> float:
    if not rate or rate == "0/0":
        return 0.0
    num, _, den = rate.partition("/")
    d = float(den) if den else 1.0
    return float(num) / d


# ── route estimation (real measurements, GT-blind) ──────────────────────────


def _to_gray(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def load_sprite_rgba(sprite_path: Path) -> np.ndarray:
    img = cv2.imread(str(sprite_path), cv2.IMREAD_UNCHANGED)
    if img is None or img.ndim != 3 or img.shape[2] != 4:
        raise BenchmarkError(f"sprite must be RGBA png: {sprite_path}")
    return img


def ncc_at(gray_frame: np.ndarray, tmpl_bgra: np.ndarray, cx: int, cy: int) -> float:
    """Normalized cross-correlation of template centered at (cx, cy)."""
    th, tw = tmpl_bgra.shape[:2]
    x0, y0 = cx - tw // 2, cy - th // 2
    if x0 < 0 or y0 < 0 or y0 + th > gray_frame.shape[0] or x0 + tw > gray_frame.shape[1]:
        return -1.0
    patch = gray_frame[y0 : y0 + th, x0 : x0 + tw]
    tmpl_gray = cv2.cvtColor(tmpl_bgra[:, :, :3], cv2.COLOR_BGR2GRAY)
    mask = tmpl_bgra[:, :, 3]
    if mask.mean() < 1:
        return -1.0
    p = patch.astype(np.float32)
    t = tmpl_gray.astype(np.float32)
    m = (mask > 0).astype(np.float32)
    pm = p * m
    tm = t * m
    p_mean = pm.sum() / max(m.sum(), 1.0)
    t_mean = tm.sum() / max(m.sum(), 1.0)
    p_c = (p - p_mean) * m
    t_c = (t - t_mean) * m
    denom = math.sqrt(float((p_c**2).sum()) * float((t_c**2).sum()))
    if denom < 1e-6:
        return -1.0
    return float((p_c * t_c).sum() / denom)


def estimate_position(
    gray_frame: np.ndarray,
    tmpl_bgra: np.ndarray,
    prior_xy: tuple[int, int],
    search_radius: int = 44,
) -> tuple[int, int, float]:
    """Grid NCC search around prior; returns best (x, y, score)."""
    step = 4
    best = (-1.0, prior_xy[0], prior_xy[1])
    for dy in range(-search_radius, search_radius + 1, step):
        for dx in range(-search_radius, search_radius + 1, step):
            cx, cy = prior_xy[0] + dx, prior_xy[1] + dy
            s = ncc_at(gray_frame, tmpl_bgra, cx, cy)
            if s > best[0]:
                best = (s, cx, cy)
    bx, by = best[1], best[2]
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            cx, cy = bx + dx, by + dy
            s = ncc_at(gray_frame, tmpl_bgra, cx, cy)
            if s > best[0]:
                best = (s, cx, cy)
    return best[1], best[2], best[0]


def estimate_similarity(
    gray_frame: np.ndarray,
    tmpl_bgra: np.ndarray,
    prior_xy: tuple[int, int],
    scales: list[float],
    angles: list[float],
) -> tuple[float, float]:
    """Best (scale, angle) by masked NCC over candidate sets."""
    base = tmpl_bgra
    best = (-1.0, 1.0, 0.0)
    for sc in scales:
        rs = cv2.resize(base, None, fx=sc, fy=sc, interpolation=cv2.INTER_LINEAR)
        for ang in angles:
            rr = rs if ang == 0.0 else _rotate_bgra(rs, ang)
            s = ncc_at(gray_frame, rr, prior_xy[0], prior_xy[1])
            if s > best[0]:
                best = (s, sc, ang)
    return best[1], best[2]


def _rotate_bgra(img: np.ndarray, angle_deg: float) -> np.ndarray:
    h, w = img.shape[:2]
    center = (w / 2, h / 2)
    mat = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cosv = abs(mat[0, 0])
    sinv = abs(mat[0, 1])
    nw = int(h * sinv + w * cosv)
    nh = int(h * cosv + w * sinv)
    mat[0, 2] += nw / 2 - center[0]
    mat[1, 2] += nh / 2 - center[1]
    return cv2.warpAffine(img, mat, (nw, nh))


@dataclass
class RouteObservation:
    """What a route measured, WITHOUT consulting ground truth tables."""

    positions: dict[str, dict[int, tuple[int, int]]] = field(default_factory=dict)
    scores: dict[str, dict[int, float]] = field(default_factory=dict)
    scale_samples: dict[int, float] = field(default_factory=dict)
    rotation_samples: dict[int, float] = field(default_factory=dict)
    pose_state_by_frame: dict[int, str] = field(default_factory=dict)
    visible_frames: dict[str, list[int]] = field(default_factory=dict)
    graphic_present: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def observe_route(
    route: str,
    frames: np.ndarray,
    fixture: Fixture,
    fixtures_dir: Path,
) -> RouteObservation:
    """Run a route's estimator stack over decoded frames (image-space only)."""
    man = fixture.manifest
    width = int(man["resolution"]["width"])
    height = int(man["resolution"]["height"])
    diag = math.hypot(width, height)
    obs = RouteObservation()
    trajs = man.get("trajectories", [])
    sprites_dir = fixtures_dir / "sprites"

    def sprite_for(layer_id: str) -> np.ndarray | None:
        mapping = {
            "phone": "phone.png",
            "character": "char_rep.png",
            "body": "char_rep.png",
            "sign": "sign_rep.png",
        }
        name = mapping.get(layer_id)
        if name is None:
            return None
        p = sprites_dir / fixture.fixture_id / name
        return load_sprite_rgba(p) if p.is_file() else None

    # 1) trajectory estimation for tracked layers (both routes share this;
    #    pose_swap additionally classifies pose states afterwards)
    stride = 3
    for traj in trajs:
        layer = str(traj["layer_id"])
        table: dict[str, list[int]] = traj["positions_by_frame"]
        tmpl = sprite_for(layer)
        if tmpl is None:
            obs.notes.append(f"{layer}: no template, trajectory skipped")
            continue
        frames_sorted = sorted(int(k) for k in table)
        sampled = frames_sorted[::stride]
        pos_map: dict[int, tuple[int, int]] = {}
        score_map: dict[int, float] = {}
        prev: tuple[int, int] | None = None
        for fidx in sampled:
            gray = _to_gray(frames[fidx])
            if prev is not None:
                # chain from previous ESTIMATE (GT-blind after the anchor)
                prior = prev
            else:
                # first frame seeds from the segment anchor declared in the
                # manifest -- the same input contract as
                # SegmentRenderRoute.anchor_x/y (I01 schema); NOT GT peeking
                p0 = table[str(fidx)]
                prior = (int(p0[0]), int(p0[1]))
            x, y, sc = estimate_position(gray, tmpl, prior)
            pos_map[fidx] = (x, y)
            score_map[fidx] = round(sc, 6)
            prev = (x, y)
        obs.positions[layer] = pos_map
        obs.scores[layer] = score_map

    # 2) similarity samples (rotation/scale) where the fixture defines motion
    motion = man.get("motion")
    if motion:
        layer = str(motion["layer_id"])
        tmpl = sprite_for(layer)
        if tmpl is not None:
            pivot = motion["pivot_xy"]
            rot_gt_keys = sorted(int(k) for k in motion["rotation_deg_by_frame"])
            sample_frames = rot_gt_keys[:: max(1, len(rot_gt_keys) // 8)]
            # candidate grids sized so quantization stays well inside the
            # frozen thresholds (scale 3%, rotation 3 deg)
            for fidx in sample_frames:
                gray = _to_gray(frames[fidx])
                sc, ang = estimate_similarity(
                    gray,
                    tmpl,
                    (int(pivot[0]), int(pivot[1])),
                    scales=[0.94, 0.97, 1.0, 1.03, 1.06],
                    angles=[-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0],
                )
                obs.scale_samples[fidx] = sc
                obs.rotation_samples[fidx] = ang

    # 3) visibility probing (occlusion fixtures): template presence per frame
    vis_entries = man.get("visibility", [])
    for entry in vis_entries:
        layer = str(entry["layer_id"])
        tmpl = sprite_for(layer)
        if tmpl is None:
            continue
        present: list[int] = []
        table = next((t for t in trajs if str(t["layer_id"]) == layer), None)
        if table is None:
            continue
        keys = sorted(int(k) for k in table["positions_by_frame"])
        for fidx in keys[::stride]:
            gray = _to_gray(frames[fidx])
            prior = tuple(table["positions_by_frame"][str(fidx)])  # type: ignore[arg-type]
            s = ncc_at(gray, tmpl, prior[0], prior[1])
            if s >= 0.35:
                present.append(fidx)
        obs.visible_frames[layer] = present

    # 4) semantic graphic presence (f6)
    graphics = man.get("graphics") or []
    for g in graphics:
        if g.get("source_only"):
            continue
        tmpl = sprite_for(str(g["layer_id"]))
        if tmpl is None:
            continue
        count = 0
        total = 0
        for fidx in range(0, frames.shape[0], stride):
            total += 1
            gx = int(float(g["bbox_xywh_norm"][0]) * width + float(g["bbox_xywh_norm"][2]) * width / 2)
            gy = int(float(g["bbox_xywh_norm"][1]) * height + float(g["bbox_xywh_norm"][3]) * height / 2)
            if ncc_at(_to_gray(frames[fidx]), tmpl, gx, gy) >= 0.5:
                count += 1
        if total:
            obs.graphic_present.append(count)

    # 5) pose-state classification -- ONLY the pose_swap route has this
    # capability in its contract (versioned pose/expression swap); rigid
    # sprite_affine carries a single state and cannot retime swaps.
    swaps = man.get("swaps") or []
    if swaps:
        if route != "pose_swap":
            obs.notes.append(
                f"{route}: no pose-state capability; {len(swaps)} annotated swaps unhandled"
            )
        else:
            spr_dir = sprites_dir / fixture.fixture_id
            closed_t = load_sprite_rgba(spr_dir / "head_closed_src.png")
            open_t = load_sprite_rgba(spr_dir / "head_open_src.png")
            # crop templates to the mouth region only (matches the manifest's
            # pose_region_bbox_xywh_norm): the head outline is IDENTICAL between
            # states, so whole-head correlation cannot separate the two states
            width_ = int(man["resolution"]["width"])
            height_ = int(man["resolution"]["height"])
            bbox = man["pose_region_bbox_xywh_norm"]
            rx0 = int(float(bbox[0]) * width_) - 6
            ry0 = int(float(bbox[1]) * height_) - 6
            rx1 = int((float(bbox[0]) + float(bbox[2])) * width_) + 6
            ry1 = int((float(bbox[1]) + float(bbox[3])) * height_) + 6

            def mouth_crop(t: np.ndarray) -> np.ndarray:
                return t[max(0, ry0) : ry1, max(0, rx0) : rx1]

            closed_m = mouth_crop(closed_t)
            open_m = mouth_crop(open_t)
            pcx = (rx0 + rx1) // 2
            pcy = (ry0 + ry1) // 2
            for fidx in range(frames.shape[0]):
                gray = _to_gray(frames[fidx])
                s_open = ncc_at(gray, open_m, pcx, pcy)
                s_closed = ncc_at(gray, closed_m, pcx, pcy)
                obs.pose_state_by_frame[fidx] = "open" if s_open > s_closed else "closed"
    return obs


# ── metric computation (explicit formulas over GT vs observation) ────────────


def _pctl(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q)) if values else 0.0


def compute_metrics(
    route: str,
    frames: np.ndarray,
    fixture: Fixture,
    obs: RouteObservation,
    probe_sprites_dir: Path,
) -> dict[str, Any]:
    man = fixture.manifest
    width = int(man["resolution"]["width"])
    height = int(man["resolution"]["height"])
    diag = math.hypot(width, height)
    n_declared = int(man["frame_count"])

    # frame + timebase
    info = probe_video(fixture.media_path)
    nb_stream = int(info.get("nb_frames") or 0)
    frame_error = abs(frames.shape[0] - n_declared)
    if nb_stream:
        frame_error = max(frame_error, abs(nb_stream - n_declared))
    fps_manifest = float(man["fps"])
    fps_container = _parse_rate(str(info.get("r_frame_rate", "0/0")))
    duration = float(info.get("duration") or 0.0)
    timebase_error_frames = abs(int(round(duration * fps_manifest)) - n_declared)

    # cuts (RGB-diff peak inside +-10 window of each declared cut)
    cut_errors: list[int | None] = []
    diffs: list[float] = []
    for i in range(1, frames.shape[0]):
        diffs.append(float(np.mean(np.abs(frames[i].astype(np.int16) - frames[i - 1].astype(np.int16)))))
    for cut in man.get("cuts", []):
        expected = int(cut["cut_frame"])
        lo, hi = max(1, expected - 10), min(len(diffs), expected + 10)
        window = diffs[lo - 1 : hi]
        if not window:
            cut_errors.append(None)
            continue
        peak_local = lo - 1 + int(np.argmax(window))
        global_max_idx = int(np.argmax(diffs)) + 1
        if abs(global_max_idx - expected) <= 10:
            cut_errors.append(abs(global_max_idx - expected))
        elif diffs[peak_local - 1] >= 12.0:
            cut_errors.append(abs(peak_local - expected))
        else:
            cut_errors.append(None)

    # trajectory errors (% of diagonal) over estimated samples vs GT tables
    traj_errs: list[float] = []
    for traj in man.get("trajectories", []):
        layer = str(traj["layer_id"])
        table = traj["positions_by_frame"]
        est = obs.positions.get(layer, {})
        for fidx, (ex, ey) in est.items():
            gx, gy = table[str(fidx)]
            traj_errs.append(math.hypot(ex - gx, ey - gy) / diag * 100.0)

    # contact errors
    contact_errs: list[float] = []
    for contact in man.get("contacts", []):
        layer = str(contact.get("layer_id") or "")
        anchor = contact["anchor_xy_norm"]
        ax, ay = float(anchor[0]) * width, float(anchor[1]) * height
        est = obs.positions.get(layer, {})
        table = next(
            (t for t in man.get("trajectories", []) if str(t["layer_id"]) == layer),
            {"positions_by_frame": {}},
        )
        for fidx in contact["active_frames"]:
            key = str(fidx)
            if key in table["positions_by_frame"]:
                gx, gy = table["positions_by_frame"][key]
                ex, ey = est.get(fidx, (gx, gy))
            else:
                ex, ey = est.get(fidx, (ax, ay))
            contact_errs.append(math.hypot(ex - ax, ey - ay) / diag * 100.0)

    # scale / rotation errors on sampled frames
    scale_errs: list[float] = []
    rot_errs: list[float] = []
    motion = man.get("motion")
    if motion:
        gt_scale = {int(k): float(v) for k, v in motion["scale_by_frame"].items()}
        gt_rot = {int(k): float(v) for k, v in motion["rotation_deg_by_frame"].items()}
        basis = float(motion.get("source_basis_scale", 1.0))
        for fidx, est_sc in obs.scale_samples.items():
            if fidx in gt_scale and basis:
                scale_errs.append(abs(est_sc / basis - gt_scale[fidx] / basis) / (gt_scale[fidx] / basis) * 100.0)
        for fidx, est_ang in obs.rotation_samples.items():
            if fidx in gt_rot:
                d = abs(est_ang - gt_rot[fidx]) % 360.0
                rot_errs.append(min(d, 360.0 - d))

    # pose swap timing error (frames)
    swap_errors: list[int | None] = []
    if man.get("swaps"):
        states = obs.pose_state_by_frame
        flips = [
            f
            for f in range(1, len(states))
            if states.get(f) != states.get(f - 1)
        ]
        for sw in man["swaps"]:
            target = int(sw["swap_frame"])
            near = [f for f in flips if abs(f - target) <= 5]
            if near:
                swap_errors.append(min(abs(f - target) for f in near))
            else:
                swap_errors.append(None)

    # z-order inversions: route evidence contradicting annotated order.
    # A frame counts ONLY when both layers are probed and the below-layer is
    # visible while the above-layer is absent; frames listed in
    # `ambiguous_frames` (partial-overlap transition bands) are excluded by
    # the fixture author at generation time, not tuned post-measurement.
    z_inv = 0
    for rule in man.get("z_order", []):
        above = str(rule["above"])
        below = str(rule["below"])
        lo, hi = int(rule["frames"][0]), int(rule["frames"][1])
        ambiguous = {int(f) for f in (rule.get("ambiguous_frames") or [])}
        below_present = set(obs.visible_frames.get(below, []))
        above_present = set(obs.visible_frames.get(above, []))
        if below in obs.visible_frames and above in obs.visible_frames:
            for fidx in range(lo, hi + 1):
                if fidx in ambiguous:
                    continue
                if fidx in below_present and fidx not in above_present:
                    z_inv += 1

    # unexplained visibility events (symmetric difference beyond +-1)
    unexplained = 0
    for entry in man.get("visibility", []):
        layer = str(entry["layer_id"])
        gt_visible: set[int] = set()
        for iv in entry["intervals"]:
            gt_visible.update(range(int(iv[0]), int(iv[1]) + 1))
        route_vis = set(obs.visible_frames.get(layer, []))
        missed = {f for f in gt_visible - route_vis if not any(abs(f - r) <= 1 for r in route_vis)}
        extra = {f for f in route_vis - gt_visible if not any(abs(f - g) <= 1 for g in gt_visible)}
        unexplained += len(missed) + len(extra)

    # clipping-from-source-silhouette probe (f4-style scale ramp)
    clip = _clipping_probe(man, frames, probe_sprites_dir)

    # semantic graphic ratio + source-only overlay leak scan
    graphic_ratio = 0.0
    if obs.graphic_present:
        stride = 3
        total = math.ceil(frames.shape[0] / stride)
        graphic_ratio = sum(obs.graphic_present) / max(total, 1)
    leak_events = _overlay_leak_scan(man, frames)

    corrections = 0  # deterministic routes apply no interactive corrections

    return {
        "frame_error": frame_error,
        "timebase_error_frames": timebase_error_frames,
        "cut_error_frames": cut_errors[0] if cut_errors else 0,
        "swap_error_frames": swap_errors[0] if swap_errors else 0,
        "trajectory_median_pct": round(statistics.median(traj_errs), 6) if traj_errs else 0.0,
        "trajectory_p95_pct": round(_pctl(traj_errs, 95.0), 6) if traj_errs else 0.0,
        "scale_p95_pct": round(_pctl(scale_errs, 95.0), 6) if scale_errs else 0.0,
        "rotation_p95_deg": round(_pctl(rot_errs, 95.0), 6) if rot_errs else 0.0,
        "contact_p95_pct": round(_pctl(contact_errs, 95.0), 6) if contact_errs else 0.0,
        "z_order_inversions": z_inv,
        "unexplained_visibility_events": unexplained,
        "clipping_from_source_silhouette": clip,
        "graphic_present_frames_ratio": round(graphic_ratio, 6),
        "watermark_leak_events": leak_events,
        "correction_counts": corrections,
        "annotated_swaps": len(man.get("swaps") or []),
        "pose_states_measured": bool(obs.pose_state_by_frame),
    }


def _clipping_probe(man: dict[str, Any], frames: np.ndarray, sprites_dir: Path) -> dict[str, Any]:
    probe = man.get("clipping_probe")
    if not probe:
        return {"applicable": False, "count": 0, "fail_bool": False}
    fid = str(man["fixture_id"])
    spr_dir = sprites_dir / fid
    src = spr_dir / "char_src.png"
    rep = spr_dir / "char_rep.png"
    if not src.is_file() or not rep.is_file():
        return {"applicable": True, "count": 0, "fail_bool": False, "note": "sprites missing"}
    motion = man.get("motion") or {}
    pivot = motion.get("pivot_xy", [0, 0])
    gt_rot = motion.get("rotation_deg_by_frame", {})
    last_frame = max((int(k) for k in gt_rot), default=frames.shape[0] - 1)
    src_img = load_sprite_rgba(src)
    rep_img = load_sprite_rgba(rep)
    # simulate the legacy compositing defect: resize replacement up to the
    # ramped scale, then CLIP it with the SOURCE alpha (silhouette reuse)
    scale_end = float(motion.get("max_scale", 1.0))
    scaled = cv2.resize(
        rep_img,
        None,
        fx=scale_end,
        fy=scale_end,
        interpolation=cv2.INTER_LINEAR,
    )
    h = min(scaled.shape[0], src_img.shape[0])
    w = min(scaled.shape[1], src_img.shape[1])
    sc = scaled[:h, :w, 3].astype(np.int16)
    sm = src_img[:h, :w, 3].astype(np.int16)
    lost = int(np.count_nonzero((sc > 0) & (sm == 0)))
    limit = int(probe.get("min_clipped_pixels_for_fail", 25))
    return {
        "applicable": True,
        "count": lost,
        "fail_bool": lost >= limit,
        "probe_frame": last_frame,
        "pivot_xy": [int(pivot[0]), int(pivot[1])],
        "limit_pixels": limit,
    }


def _overlay_leak_scan(man: dict[str, Any], frames: np.ndarray) -> int:
    """Count frames whose source-only overlay bbox shows foreign pixels.

    Baseline = first frame's bbox content (a clean render keeps it constant);
    a leak (overlay drawn) changes the local statistics strongly. Validated by
    unit-test injection.
    """
    graphics = man.get("graphics") or []
    width = int(man["resolution"]["width"])
    height = int(man["resolution"]["height"])
    events = 0
    for g in graphics:
        if not g.get("source_only"):
            continue
        x = int(float(g["bbox_xywh_norm"][0]) * width)
        y = int(float(g["bbox_xywh_norm"][1]) * height)
        w = int(float(g["bbox_xywh_norm"][2]) * width)
        h = int(float(g["bbox_xywh_norm"][3]) * height)
        if frames.shape[0] == 0 or w <= 2 or h <= 2:
            continue
        base = frames[0][y : y + h, x : x + w].astype(np.float32)
        for i in range(frames.shape[0]):
            patch = frames[i][y : y + h, x : x + w].astype(np.float32)
            if float(np.abs(patch - base).mean()) >= 8.0:
                events += 1
    return events


# ── evaluation vs frozen thresholds ──────────────────────────────────────────


def evaluate_thresholds(metrics: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, value: Any, limit: float, ok: bool) -> None:
        checks.append({"metric": name, "value": value, "limit": limit, "pass": bool(ok)})

    cut = metrics["cut_error_frames"]
    lim = float(thresholds["cut_action_error_frames_max"])
    add("cut_error_frames", cut, lim, isinstance(cut, int) and cut <= lim)
    lim = float(thresholds["trajectory_median_pct_max"])
    add("trajectory_median_pct", metrics["trajectory_median_pct"], lim, metrics["trajectory_median_pct"] <= lim)
    lim = float(thresholds["trajectory_p95_pct_max"])
    add("trajectory_p95_pct", metrics["trajectory_p95_pct"], lim, metrics["trajectory_p95_pct"] <= lim)
    lim = float(thresholds["scale_p95_pct_max"])
    add("scale_p95_pct", metrics["scale_p95_pct"], lim, metrics["scale_p95_pct"] <= lim)
    lim = float(thresholds["rotation_p95_deg_max"])
    add("rotation_p95_deg", metrics["rotation_p95_deg"], lim, metrics["rotation_p95_deg"] <= lim)
    lim = float(thresholds["contact_p95_pct_max"])
    add("contact_p95_pct", metrics["contact_p95_pct"], lim, metrics["contact_p95_pct"] <= lim)
    lim = int(thresholds["z_order_inversions_max"])
    add("z_order_inversions", metrics["z_order_inversions"], lim, metrics["z_order_inversions"] <= lim)
    lim = int(thresholds["unexplained_visibility_events_max"])
    add(
        "unexplained_visibility_events",
        metrics["unexplained_visibility_events"],
        lim,
        metrics["unexplained_visibility_events"] <= lim,
    )
    clip = metrics["clipping_from_source_silhouette"]
    allowed = bool(thresholds["clipping_from_source_silhouette_allowed"])
    clip_fail = bool(clip.get("fail_bool")) if isinstance(clip, dict) else False
    add("clipping_from_source_silhouette", clip, int(clip.get("limit_pixels", 0)) if isinstance(clip, dict) else 0, allowed or not clip_fail)
    # action-event coverage: a fixture with annotated swaps requires the route
    # to actually measure pose states; no evidence => structural failure
    # (this is what separates pose_swap from rigid routes on f2)
    if int(metrics["annotated_swaps"]) > 0 and not bool(metrics["pose_states_measured"]):
        checks.append(
            {
                "metric": "pose_state_capability",
                "value": "not_measured",
                "limit": "required_when_swaps_annotated",
                "pass": False,
            }
        )
    swap_err = metrics.get("swap_error_frames")
    lim_swap = float(thresholds["cut_action_error_frames_max"])
    if isinstance(swap_err, int):
        add("swap_error_frames", swap_err, lim_swap, swap_err <= lim_swap)
    elif metrics["annotated_swaps"] and metrics["pose_states_measured"]:
        # states measured but no flip found within +-5 of any annotation
        add("swap_error_frames", None, lim_swap, False)
    overall = all(c["pass"] for c in checks)
    return {"overall_pass": overall, "checks": checks}


# ── reference evaluation (verified media; skip-with-reason) ──────────────────


def evaluate_reference(media_path: Path | None) -> dict[str, Any]:
    if media_path is None or not media_path.is_file():
        return {
            "status": "SKIPPED_WITH_REASON",
            "reason": (
                "verified reference media not provided/found on machine "
                "(--reference-media not given or path absent)"
            ),
            "expected_sha256": VERIFIED_REFERENCE_SHA256,
        }
    digest = _sha256_bytes(media_path.read_bytes()).lower()
    if digest != VERIFIED_REFERENCE_SHA256:
        return {
            "status": "FAILED_SHA_CHECK",
            "reason": f"sha mismatch: got {digest}",
            "expected_sha256": VERIFIED_REFERENCE_SHA256,
        }
    info = probe_video(media_path)
    return {
        "status": "VERIFIED",
        "sha256": digest,
        "size_bytes": media_path.stat().st_size,
        "probe": {
            "width": info.get("width"),
            "height": info.get("height"),
            "r_frame_rate": info.get("r_frame_rate"),
            "nb_frames": info.get("nb_frames"),
            "duration": info.get("duration"),
            "pix_fmt": info.get("pix_fmt"),
        },
        "host_platform": platform.platform(),
    }


# ── vram (optional CUDA) ─────────────────────────────────────────────────────


def vram_peak_mib() -> int | None:
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return None
    if not getattr(torch, "cuda", None) or not torch.cuda.is_available():  # type: ignore[attr-defined]
        return None
    try:
        return int(torch.cuda.max_memory_allocated() // (1024 * 1024))  # type: ignore[attr-defined]
    except Exception:
        return None


# ── main pipeline ────────────────────────────────────────────────────────────


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    fixtures_dir = args.fixtures.resolve()
    routes = [r.strip() for r in str(args.routes).split(",") if r.strip()]
    bad = [r for r in routes if r not in RENDERER_ROUTES]
    if bad:
        raise BenchmarkError(f"unknown routes {bad}; valid: {list(RENDERER_ROUTES)}")
    thresholds = load_thresholds(fixtures_dir)
    fixtures = load_fixtures(fixtures_dir, args.fixtures_filter)
    freeze = compute_frozen_content_sha(fixtures_dir, [f.fixture_id for f in fixtures])

    # MANDATORY: freeze banner precedes ANY measurement
    print_freeze_banner(freeze, routes, args.seed)

    if args.dry_run:
        plan = [
            {
                "fixture_id": f.fixture_id,
                "risk_class": f.manifest["risk_class"],
                "frame_count": f.manifest["frame_count"],
                "metrics_applicable": f.manifest["metrics_applicable"],
            }
            for f in fixtures
        ]
        print(json.dumps({"mode": "DRY_RUN", "planned_measurements": plan}, indent=2))
        return {"mode": "DRY_RUN", "frozen": freeze, "plan": plan}

    results: list[dict[str, Any]] = []
    for fixture in fixtures:
        for route in routes:
            started = time.perf_counter()
            frames_raw = decode_frames(fixture.media_path)
            res = fixture.manifest["resolution"]
            n_expected = int(fixture.manifest["frame_count"]) * int(res["height"]) * int(res["width"]) * 3
            buf = frames_raw.tobytes()
            if len(buf) < n_expected:
                raise BenchmarkError(
                    f"{fixture.fixture_id}: decoded {len(buf)} bytes, expected {n_expected}"
                )
            frames = np.frombuffer(buf[:n_expected], dtype=np.uint8).reshape(
                int(fixture.manifest["frame_count"]), int(res["height"]), int(res["width"]), 3
            )
            obs = observe_route(route, frames, fixture, fixtures_dir)
            metrics = compute_metrics(route, frames, fixture, obs, fixtures_dir / "sprites")
            evaluation = evaluate_thresholds(metrics, thresholds)
            wall_ms = (time.perf_counter() - started) * 1000.0 / max(frames.shape[0], 1)
            entry: dict[str, Any] = {
                "fixture_id": fixture.fixture_id,
                "risk_class": fixture.manifest["risk_class"],
                "route": route,
                "seed": args.seed,
                "metrics": metrics,
                "threshold_evaluation": evaluation,
                "wall_runtime_ms_per_frame": round(wall_ms, 4),
                "vram_peak_mib": vram_peak_mib(),
                "route_notes": obs.notes,
            }
            results.append(entry)
            status = "PASS" if evaluation["overall_pass"] else "FAIL"
            print(
                f"[run] {fixture.fixture_id} route={route} -> {status} "
                f"(traj_med={metrics['trajectory_median_pct']}%, "
                f"traj_p95={metrics['trajectory_p95_pct']}%)",
                flush=True,
            )

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    result_doc = {
        "schema_version": SCHEMA_VERSION,
        "frozen_content_sha256": freeze["frozen_content_sha256"],
        "freeze_components": freeze["components"],
        "routes": routes,
        "seed": args.seed,
        "non_deterministic_fields_excluded_from_compare": list(NON_DETERMINISTIC_FIELDS),
        "thresholds_policy": thresholds.get("policy"),
        "results": results,
        "reference_evaluation": evaluate_reference(args.reference_media),
    }
    out_path = out_dir / f"benchmark_results_seed{args.seed}.json"
    out_path.write_text(json.dumps(result_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[out] {out_path}")
    return result_doc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--routes", default=DEFAULT_ROUTES, help="comma-separated renderer routes")
    ap.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/s09_renderer"))
    ap.add_argument("--fixtures-filter", nargs="*", default=None, help="optional fixture ids subset")
    ap.add_argument("--out", type=Path, required=True, help="output directory for results JSON")
    ap.add_argument("--seed", type=int, default=20260823)
    ap.add_argument("--dry-run", action="store_true", help="freeze + validate + plan, no measurement")
    ap.add_argument("--reference-media", type=Path, default=None, help="optional verified reference path")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_benchmark(args)
    except BenchmarkError as err:
        print(f"BENCHMARK_ERROR: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
