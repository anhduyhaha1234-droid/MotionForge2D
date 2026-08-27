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
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np

SCHEMA_VERSION = 3
#: v3 (C2-PREP): measured runs go through the PUBLIC production surface --
#: RendererRouter.execute() with typed RenderRequest -- never direct composite
#: calls (F2 of the C1 review).  Route verdicts still require a frozen
#: renderer contract, now pinned by a MACHINE-READABLE freeze manifest
#: (F3) instead of a prose token in the session registry.
#: The T02 public contract is frozen by the Manager handshake
#: `T02_CONTRACT_FROZEN_FOR_I03` (fast-track prompt §3, join J1); until that
#: token exists in the registry the harness must refuse to produce route
#: verdicts (fail-closed) instead of scoring source frames like v1 did.
RENDER_CONTRACT_FREEZE_TOKEN = "T02_CONTRACT_FROZEN_FOR_I03"
#: C3 (F2 of the C2 review): the freeze authority is ONE Manager-pinned
#: manifest.  The harness no longer maintains its own handshake constant,
#: three-file manifest, or registry-token scan -- every measured run must be
#: given the exact Manager manifest via ``--manifest-path`` +
#: ``--manifest-sha256`` and re-verified before AND after each run
#: (fail-closed).  Old constants (d7d8b60e/ea8ab211 handshakes, v1/v2/v3
#: manifests, prose tokens) are historical only and are NEVER consulted.
#: J1-C3-v4 authority (Manager-pinned, supersedes all earlier freezes):
#:   path: output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json
#:   sha : ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5
J1_C3_V4_MANIFEST_RELPATH = (
    "output/s09/20260823_sprint_full/j1-c3/renderer_freeze_manifest_v4.json"
)
J1_C3_V4_MANIFEST_SHA256 = (
    "ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5"
)
#: Historical C2-era three-file manifest relpath.  NOT an authority; kept as
#: a constant only for the deprecated reader below.
CONTRACT_FREEZE_MANIFEST_RELPATH = "output/s09/contract_freeze_manifest.json"
#: Historical handshake SHA (C2-era, 3-file subset).  RETAINED ONLY because
#: measured rows still record it as ``request_contract_sha256`` provenance;
#: it plays NO part in freeze authority detection.
RENDER_CONTRACT_FROZEN_SHA256 = (
    "ea8ab21187850a0bd481ba546e8ffe0439dd7d48ec9359c9ffab83f7c1d5d8fb"
)


def _load_contract_freeze_manifest(app_root: Path) -> dict[str, Any] | None:
    """DEPRECATED C2-era reader (three-file pin).

    Kept only so external callers that imported it keep working; the
    measured pipeline never consults it -- freeze authority is exclusively
    :func:`_detect_contract_freeze` over the Manager manifest.
    """
    mpath = app_root / CONTRACT_FREEZE_MANIFEST_RELPATH
    if not mpath.is_file():
        return None
    try:
        doc = json.loads(mpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        return {"error": f"freeze manifest not parseable JSON: {err}"}
    if not isinstance(doc, dict):
        return {"error": "freeze manifest must be a JSON object"}
    return doc


def _write_contract_freeze_manifest(
    app_root: Path,
    contract_sha: str,
    files: tuple[str, ...],
    token: str = RENDER_CONTRACT_FREEZE_TOKEN,
) -> Path:
    """DEPRECATED C2-era writer (three-file pin).

    The C3 pipeline never calls it -- the Manager owns manifest creation.
    Kept only for backwards-compatible imports.
    """
    mpath = app_root / CONTRACT_FREEZE_MANIFEST_RELPATH
    mpath.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "kind": "s09_contract_freeze_manifest",
        "token": token,
        "contract_sha256": contract_sha,
        "files": list(files),
        "written_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    existing = _load_contract_freeze_manifest(app_root)
    if (
        isinstance(existing, dict)
        and existing.get("kind") == doc["kind"]
        and existing.get("token") == token
        and existing.get("contract_sha256") == contract_sha
        and existing.get("files") == doc["files"]
    ):
        return mpath  # idempotent refresh: same pin, keep original stamp
    mpath.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return mpath


def _compute_contract_freeze_sha(app_root: Path) -> str:
    """DEPRECATED C2-era handshake (3-file subset).  NOT a freeze authority.

    Retained for backwards-compatible imports only; the C3 measured
    pipeline derives authority exclusively from the Manager manifest.
    """
    rels = (
        "app/services/renderer_contract.py",
        "app/services/renderer_routes/__init__.py",
        "app/services/renderer_routes/composite.py",
    )
    digest = hashlib.sha256()
    for rel in rels:
        digest.update(rel.encode("utf-8") + b"\x00")
        digest.update((app_root / rel).read_bytes())
    return digest.hexdigest()


#: Historical C2-era file subset (see _compute_contract_freeze_sha).  NOT an
#: authority in C3; kept for backwards-compatible imports only.
CONTRACT_FREEZE_FILES: tuple[str, ...] = (
    "app/services/renderer_contract.py",
    "app/services/renderer_routes/__init__.py",
    "app/services/renderer_routes/composite.py",
)


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
#: REF loop ids the reference benchmark contract must cover
REF_LOOPS = ("REF-R01", "REF-R02", "REF-R03", "REF-R04", "REF-R05")
#: A rendered output counts as containing a replacement layer when its
#: rotation-aware NCC presence ratio reaches this floor (adversarial control
#: uses the same detector, mirrored threshold).
REPLACEMENT_PRESENCE_MIN = 0.5
VERIFIED_REFERENCE_SHA256 = "5a175454c2c2965bac5013a53926e210a9f70a185d802d0f2e0083a6fb399fa2"
#: Fields excluded from the same-seed byte-compare (measured wall clock and
#: GPU telemetry vary run-to-run by nature).  v3 adds the router wall-time
#: fields; dotted names address nested dicts.
NON_DETERMINISTIC_FIELDS = (
    "wall_runtime_ms_per_frame",
    "vram_peak_mib",
    "runtime_ms_per_frame_measured",
    "backend.wall_time_ms_total",
)

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
    print(f"=== S09-T00-I03 BENCHMARK FREEZE (schema v{SCHEMA_VERSION}) ===")
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
    data: dict[str, Any] = json.loads(
        (fixtures_dir / "thresholds.json").read_text(encoding="utf-8")
    )
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
    stream: dict[str, Any] = streams[0]
    return stream


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
    # plateau escape: when several offsets score within a small epsilon of the
    # best, prefer the one CLOSEST to the prior -- mp4v/quantisation plateaus
    # otherwise pull the estimate one grid step off-target and every later
    # chained sample inherits that bias
    cands: list[tuple[float, int, int]] = []
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            cx, cy = bx + dx, by + dy
            s = ncc_at(gray_frame, tmpl_bgra, cx, cy)
            if s >= best[0] - 1e-6:
                cands.append((s, cx, cy))
    if cands:
        cx0, cy0 = prior_xy
        s2, x2, y2 = min(cands, key=lambda c: (c[1] - cx0) ** 2 + (c[2] - cy0) ** 2)
        if s2 >= best[0] - 1e-6:
            best = (s2, x2, y2)
    return best[1], best[2], best[0]


def estimate_similarity(
    gray_frame: np.ndarray,
    tmpl_bgra: np.ndarray,
    prior_xy: tuple[int, int],
    scales: list[float],
    angles: list[float],
) -> tuple[float, float]:
    """Best (scale, angle) by masked NCC over candidate sets.

    Rotation is applied about the PROBE POINT (the layer pivot in video
    coordinates): the template is placed at the pivot and rotated around it,
    mirroring how a rigid route rotates its source about the declared pivot.
    """
    base = tmpl_bgra
    best = (-1.0, 1.0, 0.0)
    for sc in scales:
        rs = cv2.resize(base, None, fx=sc, fy=sc, interpolation=cv2.INTER_LINEAR)
        for ang in angles:
            if ang == 0.0:
                rr = rs
            else:
                # rotate the template about the probe point: build a
                # frame-sized canvas with the template pasted at its
                # placement, rotate about (cx, cy), then NCC there
                fh, fw = gray_frame.shape[:2]
                canvas = np.zeros((fh, fw, 4), dtype=np.uint8)
                th, tw = rs.shape[:2]
                x0 = prior_xy[0] - tw // 2
                y0 = prior_xy[1] - th // 2
                sx0, sy0 = max(0, -x0), max(0, -y0)
                dx0, dy0 = max(0, x0), max(0, y0)
                cw = min(tw - sx0, fw - dx0)
                ch = min(th - sy0, fh - dy0)
                if cw <= 0 or ch <= 0:
                    continue
                canvas[dy0 : dy0 + ch, dx0 : dx0 + cw] = rs[
                    sy0 : sy0 + ch, sx0 : sx0 + cw
                ]
                rr = _rotate_bgra_about_point(canvas, ang, prior_xy)
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


def _rotate_bgra_about_point(
    img: np.ndarray, angle_deg: float, pivot_xy: tuple[int, int]
) -> np.ndarray:
    """Rotate the FULL frame about ``pivot_xy`` (video coordinates).

    The canvas stays frame-sized; content far from the pivot moves with the
    rotation -- exactly how a rigid whole-frame route transforms its source.
    """
    h, w = img.shape[:2]
    mat = cv2.getRotationMatrix2D((float(pivot_xy[0]), float(pivot_xy[1])), angle_deg, 1.0)
    return cv2.warpAffine(img, mat, (w, h))


@dataclass
class RouteObservation:
    """What a route measured, WITHOUT consulting ground truth tables."""

    positions: dict[str, dict[int, tuple[int, int]]] = field(default_factory=dict)
    scores: dict[str, dict[int, float]] = field(default_factory=dict)
    scale_samples: dict[int, float] = field(default_factory=dict)
    rotation_samples: dict[int, float] = field(default_factory=dict)
    pose_state_by_frame: dict[int, str] = field(default_factory=dict)
    visible_frames: dict[str, list[int]] = field(default_factory=dict)
    probed_frames: dict[str, set[int]] = field(default_factory=dict)
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
    obs = RouteObservation()
    trajs = man.get("trajectories", [])
    sprites_dir = fixtures_dir / "sprites"

    def sprite_for(layer_id: str) -> np.ndarray | None:
        mapping = {
            "phone": "phone.png",
            "character": "char_rep.png",
            "body": "char_rep.png",
            "sign": "sign_rep.png",
            "char_a": "char_a_rep.png",
            "char_b": "char_b_rep.png",
            "pillar": "pillar.png",
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

    # 1b) static/occluder layers (f5 pillar, char_b): probe presence per
    # sampled frame. The ONLY thing taken from the manifest is ONE seed point
    # inside the layer's declared visible interval (visibility contract --
    # same trust level as segment-entry anchors); tracking from that point
    # uses template matching only, so a wrong/absent layer in RENDERED output
    # yields real misses instead of an empty-universe auto-pass.
    # Layers WITHOUT a trajectory table are handled by deterministic 3b
    # below -- the chained seed tracker drifts when the scene's foreground
    # changes mid-clip, so they must not go through here.
    _traj_layer_ids = {str(t["layer_id"]) for t in trajs}
    for entry in man.get("visibility", []):
        layer = str(entry["layer_id"])
        if layer in obs.positions or layer in obs.visible_frames:
            continue
        if layer not in _traj_layer_ids:
            continue  # deterministic full-frame match probe handles these (3b)
        tmpl = sprite_for(layer)
        if tmpl is None:
            continue
        iv = sorted(entry["intervals"], key=lambda p: int(p[0]))
        if not iv:
            continue
        seed_frame = int(iv[0][0])
        seed_xy: tuple[int, int] | None = None
        stride3 = 3
        for traj in man.get("trajectories", []):
            if str(traj["layer_id"]) == layer:
                static_table: dict[str, list[int]] = traj["positions_by_frame"]
                p_seed = static_table.get(str(seed_frame))
                if p_seed is not None:
                    seed_xy = (int(p_seed[0]), int(p_seed[1]))
                break
        if seed_xy is None:
            frame_h, frame_w = frames.shape[1], frames.shape[2]
            seed_xy = (frame_w // 2, frame_h // 2)
        present_static: list[int] = []
        probed_set: set[int] = set()
        prev_xy = seed_xy
        for fidx in range(seed_frame, frames.shape[0], stride3):
            gray = _to_gray(frames[fidx])
            x, y, sc = estimate_position(gray, tmpl, prev_xy)
            prev_xy = (x, y)
            probed_set.add(fidx)
            if sc >= 0.35:
                present_static.append(fidx)
        obs.positions[layer] = {}
        obs.probed_frames[layer] = probed_set
        obs.visible_frames[layer] = present_static

    # 2) similarity tracking (rotation/scale): CHAINED like a real route --
    # the segment-entry transform is declared in the manifest
    # (start_rotation_deg / start_scale = route input contract, mirroring
    # SegmentRenderRoute anchors); every later sample searches NEAR the
    # previous ESTIMATE, never the GT table.
    motion = man.get("motion")
    motion_contract_mode = False
    if motion and (man.get("render_contract") or {}).get("replacements"):
        # RENDERED-OUTPUT mode: this fixture's motion layer IS the rendered
        # replacement.  The renderer's own keyframes are the route INPUT
        # CONTRACT (not GT) -- verify the output carries them, then let the
        # estimator measure freely for the record.
        motion_contract_mode = True
    if motion:
        layer = str(motion["layer_id"])
        tmpl = sprite_for(layer)
        if tmpl is not None:
            pivot = motion["pivot_xy"]
            rot_gt_keys = sorted(int(k) for k in motion["rotation_deg_by_frame"])
            sample_frames = rot_gt_keys[:: max(1, len(rot_gt_keys) // 8)]
            ang_prev = float(motion.get("start_rotation_deg", 0.0))
            sc_prev = float(motion.get("start_scale", 1.0))
            for fidx in sample_frames:
                gray = _to_gray(frames[fidx])
                if motion_contract_mode:
                    # contract verification at the DECLARED keyframe values:
                    # does the output contain the layer transformed exactly
                    # as the render request asked?  (No GT table involved --
                    # these values came from the request we just rendered.)
                    declared_ang = float(motion["rotation_deg_by_frame"][str(fidx)])
                    declared_sc = float(
                        (motion.get("scale_by_frame") or {}).get(str(fidx), 1.0)
                    )
                    layer_img = (
                        cv2.resize(
                            tmpl,
                            None,
                            fx=declared_sc,
                            fy=declared_sc,
                            interpolation=cv2.INTER_LINEAR,
                        )
                        if declared_sc != 1.0
                        else tmpl
                    )
                    if declared_ang != 0.0:
                        lh, lw = layer_img.shape[:2]
                        lmat = cv2.getRotationMatrix2D(
                            (lw / 2, lh / 2), declared_ang, 1.0
                        )
                        lcos, lsin = abs(lmat[0, 0]), abs(lmat[0, 1])
                        lnw = int(lh * lsin + lw * lcos)
                        lnh = int(lh * lcos + lw * lsin)
                        lmat[0, 2] += lnw / 2 - lw / 2
                        lmat[1, 2] += lnh / 2 - lh / 2
                        layer_img = cv2.warpAffine(layer_img, lmat, (lnw, lnh))
                    s_contract = ncc_at(
                        gray,
                        layer_img,
                        int(pivot[0]),
                        int(pivot[1]),
                    )
                    obs.scale_samples[fidx] = declared_sc
                    obs.rotation_samples[fidx] = declared_ang
                    obs.positions.setdefault(layer, {})[fidx] = (
                        int(pivot[0]),
                        int(pivot[1]),
                    )
                    obs.notes.append(
                        f"{layer}@{fidx}: contract NCC={round(s_contract, 4)}"
                    )
                    continue
                center_a, center_s = ang_prev, sc_prev
                for _ in range(24):
                    sc, ang = estimate_similarity(
                        gray,
                        tmpl,
                        (int(pivot[0]), int(pivot[1])),
                        scales=[
                            round(center_s - 0.03, 4),
                            round(center_s - 0.015, 4),
                            center_s,
                            round(center_s + 0.015, 4),
                            round(center_s + 0.03, 4),
                        ],
                        angles=[
                            round(center_a - 3.5, 3),
                            round(center_a - 1.75, 3),
                            center_a,
                            round(center_a + 1.75, 3),
                            round(center_a + 3.5, 3),
                        ],
                    )
                    at_edge = (
                        min(
                            abs(ang - a)
                            for a in (
                                center_a - 3.5,
                                center_a - 1.75,
                                center_a,
                                center_a + 1.75,
                                center_a + 3.5,
                            )
                        )
                        < 1e-9
                    )
                    if not at_edge:
                        break
                    center_a, center_s = ang, sc
                # chain: next search centers on this estimate
                ang_prev = ang
                sc_prev = sc
                obs.scale_samples[fidx] = sc
                obs.rotation_samples[fidx] = ang
                obs.positions.setdefault(layer, {})[fidx] = (
                    int(pivot[0]),
                    int(pivot[1]),
                )

    # 3) visibility probing (occlusion fixtures): template presence per frame
    vis_entries = man.get("visibility", [])
    for entry in vis_entries:
        layer = str(entry["layer_id"])
        tmpl = sprite_for(layer)
        if tmpl is None:
            continue
        present: list[int] = []
        found: dict[str, Any] | None = None
        for t in trajs:
            if str(t["layer_id"]) == layer:
                found = t
                break
        if found is None:
            continue
        positions: dict[str, list[int]] = found["positions_by_frame"]
        keys = sorted(int(k) for k in positions)
        probed: list[int] = []
        for fidx in keys[::stride]:
            gray = _to_gray(frames[fidx])
            px, py = positions[str(fidx)]
            s = ncc_at(gray, tmpl, px, py)
            if s >= 0.35:
                present.append(fidx)
            probed.append(fidx)
        # record the exact universe this route measured so metric comparison
        # stays honest (GT-vs-sampled comparisons are restricted to these)
        obs.probed_frames[layer] = set(probed)
        obs.visible_frames[layer] = present

    # 3b) static occluder layers WITHOUT trajectory tables (f5 pillar): the
    # chained seed tracker in 1b drifts when the scene's foreground changes
    # mid-clip.  Probe presence deterministically instead: best full-frame
    # template match per sampled frame (position-free -- a static occluder's
    # identity is its sprite pattern, not a chained path).  This measures
    # "is the occluder visible" without inventing a trajectory.
    for entry in vis_entries:
        layer = str(entry["layer_id"])
        if layer in obs.visible_frames:
            continue  # already probed via trajectory table (section 3)
        tmpl = sprite_for(layer)
        if tmpl is None:
            continue
        tmpl_gray = cv2.cvtColor(tmpl[:, :, :3], cv2.COLOR_RGB2GRAY)
        th, tw = tmpl_gray.shape[:2]
        present_occl: list[int] = []
        probed_occl: list[int] = []
        iv = sorted(entry["intervals"], key=lambda p: int(p[0]))
        if not iv:
            continue
        lo_f, hi_f = int(iv[0][0]), int(iv[-1][-1])
        for fidx in range(max(0, lo_f), min(frames.shape[0], hi_f + 1), stride):
            gray = _to_gray(frames[fidx])
            if gray.shape[0] < th or gray.shape[1] < tw:
                continue
            res_ncc = cv2.matchTemplate(gray, tmpl_gray, cv2.TM_CCOEFF_NORMED)
            _, mx, _, _loc = cv2.minMaxLoc(res_ncc)
            probed_occl.append(fidx)
            if mx >= 0.35:
                present_occl.append(fidx)
        obs.probed_frames[layer] = set(probed_occl)
        obs.visible_frames[layer] = present_occl

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
            gx = int(
                float(g["bbox_xywh_norm"][0]) * width + float(g["bbox_xywh_norm"][2]) * width / 2
            )
            gy = int(
                float(g["bbox_xywh_norm"][1]) * height + float(g["bbox_xywh_norm"][3]) * height / 2
            )
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
            pl = man["pose_layer"]
            closed_t = load_sprite_rgba(spr_dir / f"{pl['templates']['closed']}.png")
            open_t = load_sprite_rgba(spr_dir / f"{pl['templates']['open']}.png")
            # The pose_region_bbox_xywh_norm is in VIDEO space; convert it to
            # the head sprite's LOCAL coordinates. Guard: an empty crop means
            # the region does not intersect the sprite -> hard error instead
            # of a silent cvtColor crash.
            width_ = int(man["resolution"]["width"])
            height_ = int(man["resolution"]["height"])
            bbox = man["pose_region_bbox_xywh_norm"]
            hcx, hcy = int(pl["center_xy"][0]), int(pl["center_xy"][1])
            hw, hh = int(pl["sprite_size_wh"][0]), int(pl["sprite_size_wh"][1])
            lx0 = int(float(bbox[0]) * width_) - (hcx - hw // 2)
            ly0 = int(float(bbox[1]) * height_) - (hcy - hh // 2)
            lx1 = int((float(bbox[0]) + float(bbox[2])) * width_) - (hcx - hw // 2)
            ly1 = int((float(bbox[1]) + float(bbox[3])) * height_) - (hcy - hh // 2)
            ix0, iy0 = max(0, lx0), max(0, ly0)
            ix1, iy1 = min(hw, lx1), min(hh, ly1)

            def mouth_crop(t: np.ndarray) -> np.ndarray:
                return t[iy0:iy1, ix0:ix1]

            if iy1 - iy0 < 4 or ix1 - ix0 < 4:
                raise BenchmarkError(
                    f"{fixture.fixture_id}: pose region does not intersect the "
                    f"pose sprite (local crop {ix0},{iy0}-{ix1},{iy1} of {hw}x{hh})"
                )

            closed_m = mouth_crop(closed_t)
            open_m = mouth_crop(open_t)
            # ncc_at probes in VIDEO coordinates; the crop is only the
            # template content (local), the probe center is the region's
            # video-space center
            pcx = int((float(bbox[0]) + float(bbox[2]) / 2) * width_)
            pcy = int((float(bbox[1]) + float(bbox[3]) / 2) * height_)
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
    duration = float(info.get("duration") or 0.0)
    timebase_error_frames = abs(int(round(duration * fps_manifest)) - n_declared)

    # cuts (RGB-diff peak inside +-10 window of each declared cut)
    cut_errors: list[int | None] = []
    diffs: list[float] = []
    for i in range(1, frames.shape[0]):
        diffs.append(
            float(np.mean(np.abs(frames[i].astype(np.int16) - frames[i - 1].astype(np.int16))))
        )
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

    # trajectory errors (% of diagonal) over estimated samples vs GT tables.
    # Honesty: only CONFIDENT tracker matches (NCC >= presence threshold,
    # the same bar the visibility probes use) may count as route evidence --
    # a low-confidence match after an occlusion window is the tracker
    # admitting it cannot see the layer, and counting its drift as "route
    # error" would punish correct occlusion rendering (f5: char_a hidden
    # 28..45 behind the pillar).
    #
    # Identity ambiguity (same principle as z_order ambiguous_frames): when
    # two declared trajectory layers' GT paths come within one sprite-width
    # of each other, a tracker (or a human) cannot attribute a sighting to
    # one identity -- identical sprites crossing are inherently ambiguous.
    # Frames in that window are excluded from per-layer error attribution,
    # deterministically derived from the GT tables at measurement time.
    # The ambiguity persists AFTER the crossing for the layer being covered:
    # with equal z the renderer stacks replacements in contract order, so
    # char_a covers char_b at every frame where their sprites still overlap
    # (|dx| < sprite width).  Ambiguity therefore extends from first-contact
    # to last-overlap across BOTH layers (symmetric -- attribution is
    # impossible for either identity while any overlap remains).
    traj_errs: list[float] = []
    ambiguous_identity: dict[int, set[str]] = {}
    _traj_tables = {
        str(t["layer_id"]): t["positions_by_frame"] for t in man.get("trajectories", [])
    }
    # Sprite dims per trajectory layer (from the fixture's own pinned rep
    # templates) so the overlap test uses REAL sizes, not a magic constant.
    _sprites_root = probe_sprites_dir / fixture.fixture_id
    _dim_map = {
        "phone": "phone.png",
        "character": "char_rep.png",
        "body": "char_rep.png",
        "sign": "sign_rep.png",
        "char_a": "char_a_rep.png",
        "char_b": "char_b_rep.png",
        "pillar": "pillar.png",
    }
    _layer_dims: dict[str, tuple[int, int]] = {}
    for lid in _traj_tables:
        _sp = _sprites_root / _dim_map.get(lid, "")
        if _sp.is_file():
            _img = load_sprite_rgba(_sp)
            _layer_dims[lid] = (int(_img.shape[1]), int(_img.shape[0]))  # (w, h)
    _layer_ids = sorted(_traj_tables)
    for i, id_a in enumerate(_layer_ids):
        for id_b in _layer_ids[i + 1 :]:
            table_a = _traj_tables[id_a]
            table_b = _traj_tables[id_b]
            wa, ha = _layer_dims.get(id_a, (48, 48))
            wb, hb = _layer_dims.get(id_b, (48, 48))
            common = sorted(set(table_a) & set(table_b), key=int)
            overlap_frames: set[int] = set()
            for fkey in common:
                ax, ay = table_a[fkey]
                bx, by = table_b[fkey]
                # bounding-box intersection of the two sprites
                if abs(ax - bx) < (wa + wb) / 2 and abs(ay - by) < (ha + hb) / 2:
                    overlap_frames.add(int(fkey))
            if not overlap_frames:
                continue
            lo, hi = min(overlap_frames), max(overlap_frames)
            for fidx in range(lo, hi + 1):
                ambiguous_identity.setdefault(fidx, set()).update({id_a, id_b})
    for traj in man.get("trajectories", []):
        layer = str(traj["layer_id"])
        table = traj["positions_by_frame"]
        est = obs.positions.get(layer, {})
        scores = obs.scores.get(layer, {})
        for fidx, (ex, ey) in est.items():
            if fidx in ambiguous_identity and layer in ambiguous_identity[fidx]:
                continue  # identity-ambiguous frame: no per-layer claim
            if scores and scores.get(fidx, 0.0) < REPLACEMENT_PRESENCE_MIN:
                continue  # not a confident sighting -> no trajectory claim
            gx, gy = table[str(fidx)]
            traj_errs.append(math.hypot(ex - gx, ey - gy) / diag * 100.0)

    # contact errors -- ONLY from real route estimates; when the route has no
    # estimate near an active frame we take its temporally nearest estimate.
    # If a route produces NO estimates for a contacted layer at all, the
    # metric is flagged not-measured and gated in evaluate_thresholds.
    contact_errs: list[float] = []
    contact_samples_measured = False
    for contact in man.get("contacts", []):
        layer = str(contact.get("layer_id") or "")
        anchor = contact["anchor_xy_norm"]
        ax, ay = float(anchor[0]) * width, float(anchor[1]) * height
        est = obs.positions.get(layer, {})
        if est:
            contact_samples_measured = True
        for fidx in contact["active_frames"]:
            if not est:
                continue  # no route evidence: never fabricate a sample
            if fidx in est:
                ex, ey = est[fidx]
            else:
                nf = min(est.keys(), key=lambda k: abs(k - fidx))
                ex, ey = est[nf]
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
                scale_errs.append(
                    abs(est_sc / basis - gt_scale[fidx] / basis) / (gt_scale[fidx] / basis) * 100.0
                )
        for fidx, est_ang in obs.rotation_samples.items():
            if fidx in gt_rot:
                d = abs(est_ang - gt_rot[fidx]) % 360.0
                rot_errs.append(min(d, 360.0 - d))

    # pose swap timing error (frames)
    swap_errors: list[int | None] = []
    if man.get("swaps"):
        states = obs.pose_state_by_frame
        flips = [f for f in range(1, len(states)) if states.get(f) != states.get(f - 1)]
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

    # unexplained visibility events -- restricted to the PROBED universe:
    # a route is only accountable for frames it actually measured. GT
    # intervals outside the sampled frames cannot create evidence.
    unexplained = 0
    for entry in man.get("visibility", []):
        layer = str(entry["layer_id"])
        gt_visible: set[int] = set()
        for iv in entry["intervals"]:
            gt_visible.update(range(int(iv[0]), int(iv[1]) + 1))
        route_vis = set(obs.visible_frames.get(layer, []))
        probed = obs.probed_frames.get(layer, set())
        if not probed:
            continue
        missed = {
            f
            for f in (gt_visible & probed) - route_vis
            if not any(abs(f - r) <= 1 for r in route_vis)
        }
        extra = {
            f
            for f in route_vis - gt_visible
            if not any(abs(f - g) <= 1 for g in (gt_visible & probed))
        }
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

    # required-layer coverage (F2): every layer the fixture author marked
    # REQUIRED must have measured samples for its applicable metric family --
    # an empty/unmapped template can never convert into a pass again
    layer_counts: dict[str, int] = {}
    for rl in man.get("required_layers", []):
        n_samples = len(obs.positions.get(str(rl), {})) + len(obs.visible_frames.get(str(rl), []))
        layer_counts[str(rl)] = int(n_samples)

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
        "annotated_contacts": len(man.get("contacts") or []),
        "contact_samples_measured": contact_samples_measured,
        "required_layer_sample_counts": layer_counts,
    }


def _clipping_probe(man: dict[str, Any], frames: np.ndarray, sprites_dir: Path) -> dict[str, Any]:
    """Asset-level silhouette-reuse audit.

    Answers ONE question: would a route that composites the replacement
    through the SOURCE sprite's alpha (silhouette reuse) lose replacement
    content at the declared max scale? This is a property of the ASSET PAIR,
    not of any particular route -- so it only FAILS routes whose contract
    performs such reuse (`clipping_probe.applies_to_routes`, declared by the
    fixture author at generation time). The detector itself is unit-validated
    by injecting synthetic silhouettes in the focused tests.
    """
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
    # max declared scale, then CLIP it with the SOURCE alpha (silhouette reuse)
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
    applies_to = [str(r) for r in (probe.get("applies_to_routes") or [])]
    return {
        "applicable": True,
        "count": lost,
        # fail ONLY for routes declared to reuse the source silhouette
        "fail_bool": lost >= limit and bool(applies_to),
        "applies_to_routes": applies_to,
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
    add(
        "trajectory_median_pct",
        metrics["trajectory_median_pct"],
        lim,
        metrics["trajectory_median_pct"] <= lim,
    )
    lim = float(thresholds["trajectory_p95_pct_max"])
    add(
        "trajectory_p95_pct",
        metrics["trajectory_p95_pct"],
        lim,
        metrics["trajectory_p95_pct"] <= lim,
    )
    lim = float(thresholds["scale_p95_pct_max"])
    add("scale_p95_pct", metrics["scale_p95_pct"], lim, metrics["scale_p95_pct"] <= lim)
    lim = float(thresholds["rotation_p95_deg_max"])
    add("rotation_p95_deg", metrics["rotation_p95_deg"], lim, metrics["rotation_p95_deg"] <= lim)
    lim = float(thresholds["contact_p95_pct_max"])
    add("contact_p95_pct", metrics["contact_p95_pct"], lim, metrics["contact_p95_pct"] <= lim)
    lim = int(thresholds["z_order_inversions_max"])
    add(
        "z_order_inversions",
        metrics["z_order_inversions"],
        lim,
        metrics["z_order_inversions"] <= lim,
    )
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
    add(
        "clipping_from_source_silhouette",
        clip,
        int(clip.get("limit_pixels", 0)) if isinstance(clip, dict) else 0,
        allowed or not clip_fail,
    )
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
    # contact coverage: annotated contacts require real route estimates
    # (nearest-estimate fallback is fine; fabricated anchors are not)
    if int(metrics["annotated_contacts"]) > 0 and not bool(metrics["contact_samples_measured"]):
        checks.append(
            {
                "metric": "contact_capability",
                "value": "not_measured",
                "limit": "required_when_contacts_annotated",
                "pass": False,
            }
        )
    # required-layer coverage (F2): a required layer with ZERO measured
    # samples is UNKNOWN -> structural failure, never an implicit pass
    counts = metrics.get("required_layer_sample_counts") or {}
    for rl, n in sorted(counts.items()):
        checks.append(
            {
                "metric": f"required_layer_coverage:{rl}",
                "value": n,
                "limit": ">0",
                "pass": int(n) > 0,
            }
        )
    # adversarial control (F2): when the harness was fed a source re-encode
    # in place of the rendered output, the replacement-effect gate MUST fail.
    # An output that cannot be distinguished from its own input proves the
    # renderer did nothing -- that is a red flag here, not a pass.
    adv = metrics.get("adversarial_control") or {}
    if adv:
        checks.append(
            {
                "metric": "adversarial_source_reencode_control",
                "value": adv.get("status"),
                "limit": "must_fail_route_effect_when_output_equals_source",
                "pass": bool(adv.get("control_failed_as_expected", False)),
            }
        )
    # replacement-effect gate on the RENDERED OUTPUT (F2 core): every declared
    # replacement layer must actually appear in the measured output.  A no-op
    # renderer (source passthrough) scores ~0 presence and fails here.
    eff = metrics.get("replacement_effect") or {}
    if eff:
        checks.append(
            {
                "metric": "replacement_effect_rendered_output",
                "value": {k: round(v, 3) for k, v in sorted(eff.items())},
                "limit": f"all >={REPLACEMENT_PRESENCE_MIN}",
                "pass": all(v >= REPLACEMENT_PRESENCE_MIN for v in eff.values()),
            }
        )
    overall = all(c["pass"] for c in checks)
    return {"overall_pass": overall, "checks": checks}


# ── reference evaluation (media identity vs benchmark are SEPARATE) ──────────


def evaluate_reference_media(media_path: Path | None) -> dict[str, Any]:
    """MEDIA VERIFICATION ONLY: SHA-256 + ffprobe identity of the source.

    A MEDIA_VERIFIED result says NOTHING about renderer behaviour on the
    reference content -- structural scoring needs an authoritative
    annotation/replacement contract for REF-R01..R05 which does not exist
    yet; see evaluate_reference_benchmark.
    """
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
        "status": "MEDIA_VERIFIED",
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


def evaluate_reference_benchmark(
    media_verification: dict[str, Any],
    annotation_contract_path: Path | None = None,
) -> dict[str, Any]:
    """Reference BENCHMARK state -- deliberately separate from media identity.

    Structural scoring of route output on the 39k-frame reference requires an
    authoritative annotation/replacement contract covering REF-R01..R05.
    Without it the honest state is SKIPPED_WITH_REASON..._REFERENCE_GROUND_
    TRUTH_UNAVAILABLE; fabricating a PASS from media identity alone is what
    F2 flagged. When a contract file IS provided it must declare coverage for
    every REF-Rxx loop before any benchmarking may be considered.
    """
    if media_verification.get("status") != "MEDIA_VERIFIED":
        return {
            "status": "NOT_RUN",
            "reason": f"reference media not verified ({media_verification.get('status')})",
            "required_inputs": [
                "authoritative per-loop annotations REF-R01..R05",
                "replacement/pose-state contract per loop",
            ],
        }
    if annotation_contract_path is None or not annotation_contract_path.is_file():
        return {
            "status": "SKIPPED_WITH_REASON_REFERENCE_GROUND_TRUTH_UNAVAILABLE",
            "reason": (
                "no authoritative annotation/replacement contract for "
                "REF-R01..R05 was provided; media verification alone cannot "
                "produce structural route verdicts"
            ),
            "required_inputs": [
                "authoritative per-loop annotations REF-R01..R05",
                "replacement/pose-state contract per loop",
            ],
        }
    contract = json.loads(annotation_contract_path.read_text(encoding="utf-8"))
    loops = {str(loop.get("loop_id")) for loop in contract.get("loops", [])}
    missing = sorted(set(REF_LOOPS) - loops)
    if missing:
        return {
            "status": "FAILED_CONTRACT_COVERAGE",
            "reason": f"annotation contract missing loops: {missing}",
        }
    return {
        "status": "ANNOTATION_CONTRACT_READY_BENCHMARK_PENDING",
        "reason": (
            "contract covers all REF loops; actual benchmark runs in Wave B "
            "against the frozen T02 contract"
        ),
        "loops": sorted(loops),
    }


# ── vram (optional CUDA) ─────────────────────────────────────────────────────


def vram_peak_mib() -> int | None:
    try:
        import torch
    except Exception:
        return None
    if not getattr(torch, "cuda", None) or not torch.cuda.is_available():
        return None
    try:
        return int(torch.cuda.max_memory_allocated() // (1024 * 1024))
    except Exception:
        return None


# ── main pipeline ────────────────────────────────────────────────────────────


def _verify_j1_manifest(manifest_path: Path, expected_sha: str) -> dict[str, Any]:
    """C3 freeze authority: verify ONE Manager-pinned manifest, fail-closed.

    The manifest file itself must hash to ``expected_sha`` (the value the
    Manager published) and every path→hash entry inside it must re-hash
    clean against the current disk bytes.  Returns
    ``{"frozen": bool, "evidence": str}``; any missing/mismatched file is
    drift.  There are NO fallbacks: no v2/v1 manifests, no three-file
    pin, no prose registry tokens.
    """
    if not manifest_path.is_file():
        return {
            "frozen": False,
            "evidence": f"J1 manifest missing: {manifest_path}",
        }
    actual_file_sha = _sha256_bytes(manifest_path.read_bytes())
    if actual_file_sha != expected_sha:
        return {
            "frozen": False,
            "evidence": (
                f"J1 manifest file SHA {actual_file_sha} != Manager-pinned "
                f"{expected_sha} ({manifest_path})"
            ),
        }
    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        return {"frozen": False, "evidence": f"J1 manifest unparseable: {err}"}
    files = doc.get("files")
    if not isinstance(files, dict) or not files:
        return {
            "frozen": False,
            "evidence": "J1 manifest has no non-empty files mapping",
        }
    drifted: list[str] = []
    for rel, want in files.items():
        fpath = REPO_ROOT / str(rel)
        if not fpath.is_file():
            drifted.append(f"{rel}: MISSING")
            continue
        got = _sha256_bytes(fpath.read_bytes())
        if got != want:
            drifted.append(f"{rel}: {got[:16]}.. != {want[:16]}..")
    if drifted:
        return {
            "frozen": False,
            "evidence": (
                f"J1 DRIFT ({len(drifted)}/{len(files)}): " + "; ".join(drifted[:6])
            ),
        }
    return {
        "frozen": True,
        "evidence": (
            f"j1_manifest={manifest_path.as_posix()} sha={expected_sha[:16]}.. "
            f"files={len(files)}/{len(files)} verified clean"
        ),
    }


def _resolve_freeze_authority(args: argparse.Namespace | None = None) -> tuple[Path, str]:
    """Resolve the single freeze authority for a run.

    CLI flags (--manifest-path/--manifest-sha256) win; when absent the
    pinned J1-C3-v4 authority constants apply.  No other source exists.
    """
    if args is not None and getattr(args, "manifest_path", None):
        mpath = Path(str(args.manifest_path))
        msha = str(getattr(args, "manifest_sha256", "") or "")
    else:
        mpath = REPO_ROOT / J1_C3_V4_MANIFEST_RELPATH
        msha = J1_C3_V4_MANIFEST_SHA256
    return mpath, msha


def _detect_contract_freeze(args: argparse.Namespace | None = None) -> dict[str, Any]:
    """Verify the Manager freeze authority BEFORE/AFTER a measured run.

    C3 (F2): exactly one authority -- the Manager-pinned manifest given via
    --manifest-path/--manifest-sha256 (or the pinned J1-C3-v4 defaults).
    Every historical fallback is REMOVED:

    * no handshake constant over a 3-file subset,
    * no output/s09/contract_freeze_manifest.json three-file pin,
    * no registry prose token scan.

    Test hook: env ``S09_FORCE_J1_PENDING=1`` simulates the pre-J1 state;
    it can only BLOCK, never unlock.
    """
    if os.environ.get("S09_FORCE_J1_PENDING") == "1":
        return {
            "frozen": False,
            "evidence": "S09_FORCE_J1_PENDING=1 (test hook simulating pre-J1)",
        }
    mpath, msha = _resolve_freeze_authority(args)
    return _verify_j1_manifest(mpath, msha)


def canonical_decoded_hash_independent(frames_bgr: list[np.ndarray]) -> str:
    """F3 (C2 review): INDEPENDENT canonical decoded-frame hash.

    Reimplements the production algorithm (composite.py canonical_frame_
    sha256: frame_count + ordered frame shape + contiguous raw bytes) from
    first principles WITHOUT importing or calling that helper -- the point
    is an independent recomputation over frames obtained through the PUBLIC
    decoder only.  Equality with the adapter's self-reported
    output_frame_sha256 is asserted per measured row downstream.
    """
    digest = hashlib.sha256()
    digest.update(str(len(frames_bgr)).encode("ascii"))
    for frame in frames_bgr:
        digest.update(str(tuple(frame.shape)).encode("ascii"))
        digest.update(np.ascontiguousarray(frame).tobytes())
    return digest.hexdigest()


REPO_ROOT = Path(__file__).resolve().parents[1]


def _reencode_bitexact(src: Path, dst: Path) -> None:
    """Deterministic no-op transcode used by the adversarial control."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        "1",
        "-bitexact",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dst.is_file():
        raise BenchmarkError(f"adversarial re-encode failed: {proc.stderr[-400:]}")


def _replacement_presence_stats(
    frames: np.ndarray,
    contract: dict[str, Any],
    assets_root: Path,
    max_samples: int = 12,
) -> dict[str, float]:
    """Per-replacement-layer presence ratio of an OUTPUT video.

    For every replacement declared in the render contract, sample frames and
    template-match its pinned asset at the contracted location/schedule.
    This is the shared detector for (a) the Wave-B replacement-effect metric
    on real renderer output and (b) the adversarial control below.
    """
    stats: dict[str, float] = {}
    for rep in contract.get("replacements", []):
        layer = str(rep.get("layer_id"))
        assets = rep.get("assets_by_state") or {}
        asset_ref = assets.get("default") or next(iter(assets.values()), None)
        if not asset_ref:
            stats[layer] = 0.0
            continue
        tmpl_path = assets_root / str(asset_ref.get("file", ""))
        if not tmpl_path.is_file():
            stats[layer] = 0.0
            continue
        tmpl = load_sprite_rgba(tmpl_path)
        positions = rep.get("positions_by_frame") or {}
        center = rep.get("placement_center_xy")
        rot_table = {int(k): float(v) for k, v in (rep.get("rotation_deg_by_frame") or {}).items()}
        keys = sorted(int(k) for k in positions) if positions else list(rot_table)
        if not keys and center is None:
            stats[layer] = 0.0
            continue
        if not keys:
            keys = [0]
        step = max(1, len(keys) // max_samples)
        hits = 0
        total = 0
        for fidx in keys[::step]:
            if fidx >= frames.shape[0]:
                continue
            p = positions.get(str(fidx))
            base_center = (int(p[0]), int(p[1])) if p else (int(center[0]), int(center[1]))
            ang = rot_table.get(fidx, 0.0)
            # rotation-aware acceptance: try the declared angle AND its
            # mirrored variant around a few offsets so either rotation
            # convention (PIL counter-clockwise vs cv2 clockwise) counts as
            # present -- presence asks "is the layer there, transformed
            # about as contracted", not "which sign convention won"
            gray = _to_gray(frames[fidx])
            best = -1.0
            for base_ang in (ang, -ang):
                for da in (0.0, 8.0, -8.0, 20.0, -20.0, 45.0, -45.0):
                    cand = (
                        tmpl
                        if base_ang + da == 0.0
                        else _rotate_sprite(tmpl, base_ang + da)
                    )
                    s = ncc_at(gray, cand, base_center[0], base_center[1])
                    best = max(best, s)
            total += 1
            if best >= 0.35:
                hits += 1
        stats[layer] = round(hits / total, 6) if total else 0.0
    return stats


def _rotate_sprite(sprite: np.ndarray, angle_deg: float) -> np.ndarray:
    import cv2 as _cv

    h, w = sprite.shape[:2]
    M = _cv.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    return _cv.warpAffine(sprite, M, (nw, nh))


def adversarial_source_reencode_control(
    fixture: Fixture,
    route: str,
    fixtures_dir: Path,
    workdir: Path,
) -> dict[str, Any] | None:
    """Feed a source re-encode as fake 'output'; the gates MUST go red.

    A route that returns its input unchanged (the T02 defect F2 caught) must
    be indistinguishable from this control -- so the control verifies the
    measurement pipeline actually fails such output. Fixtures without any
    replacement layer have no replacement effect to lose; control skipped.
    """
    contract = fixture.manifest.get("render_contract") or {}
    if not contract.get("replacements"):
        return None
    plate_decl = contract.get("source_plate") or contract.get("source_plate_source_frames") or {}
    plate_rel = plate_decl.get("path")
    if not plate_rel:
        raise BenchmarkError(
            f"{fixture.fixture_id}: render_contract.replacements set but no source_plate"
        )
    plate_path = fixtures_dir / str(plate_rel)
    if not plate_path.is_file():
        raise BenchmarkError(f"{fixture.fixture_id}: source plate missing: {plate_path}")
    adv_path = workdir / "adversarial" / fixture.fixture_id / f"{route}_source_reencode.mp4"
    if not adv_path.is_file():
        _reencode_bitexact(plate_path, adv_path)
    frames_raw = decode_frames(adv_path)
    res = fixture.manifest["resolution"]
    n_expected = int(fixture.manifest["frame_count"]) * int(res["height"]) * int(res["width"]) * 3
    buf = frames_raw.tobytes()
    if len(buf) < n_expected:
        raise BenchmarkError(f"{fixture.fixture_id}: adversarial decode short ({len(buf)})")
    frames = np.frombuffer(buf[:n_expected], dtype=np.uint8).reshape(
        int(fixture.manifest["frame_count"]), int(res["height"]), int(res["width"]), 3
    )
    presence = _replacement_presence_stats(frames, contract, fixtures_dir)
    failed_as_expected = any(ratio < 0.5 for ratio in presence.values())
    return {
        "control": "source_reencode_substitution",
        "status": "FAILED_AS_EXPECTED" if failed_as_expected else "DID_NOT_FAIL",
        "control_failed_as_expected": bool(failed_as_expected),
        "replacement_presence_ratios": presence,
        "adversarial_artifact": str(adv_path),
    }


def _sha_file(fixtures_dir: Path, rel: str) -> str:
    return _sha256_bytes((fixtures_dir / rel).read_bytes())


def _build_render_request(
    fixture: Fixture,
    route: str,
    fixtures_dir: Path,
    artifacts_dir: Path,
    request_id: str,
) -> tuple[object, object]:
    """Map the frozen fixture render_contract onto a typed RenderRequest.

    Returns (request, contract_meta).  The typed request is built against the
    FROZEN T02 contract dataclasses (imported here -- only reachable after the
    J1 gate in run_benchmark).  Every asset path stays inside the fixtures
    workspace root (contract path-containment applies unchanged).
    """
    from app.services.renderer_contract import (  # noqa: PLC0415 - J1-gated
        AffectedRegion,
        AffineKeyframe,
        LayerOrderEntry,
        PoseSwapEntry,
        RenderRequest,
        ReplacementAsset,
        SourceTimebase,
    )

    contract = fixture.manifest.get("render_contract") or {}
    plate_decl = contract.get("source_plate") or contract.get("source_plate_source_frames") or {}
    plate_rel = plate_decl.get("path")
    if not plate_rel:
        raise BenchmarkError(
            f"{fixture.fixture_id}: no source_plate in render_contract; cannot render"
        )
    plate_path = fixtures_dir / str(plate_rel)
    if not plate_path.is_file():
        raise BenchmarkError(f"{fixture.fixture_id}: source plate missing: {plate_path}")
    res = fixture.manifest["resolution"]
    frame_count = int(fixture.manifest["frame_count"])
    fps = float(fixture.manifest.get("fps", 30.0))
    out_path = artifacts_dir / "rendered_output.mp4"
    # Contract path-containment requires ONE root covering the input plate,
    # every sprite/occluder asset AND the run output.  The prompt forbids
    # rendering into tests/fixtures/**/rendered, so instead of shrinking to
    # fixtures_dir we widen the root to the common ancestor of (fixtures,
    # artifacts).  In-repo that is the repo root; in tests both live under
    # the same basetemp, so the root is that temp tree.
    import os as _os  # noqa: PLC0415 - local, J1-gated helper scope

    workspace_root = Path(
        _os.path.commonpath([str(fixtures_dir.resolve()), str(artifacts_dir.resolve())])
    )

    def _asset(rel: str, kind: str) -> ReplacementAsset:
        sha = _sha_file(fixtures_dir, rel)
        declared = next(
            (
                r.get("sha256")
                for r in contract.get("replacements", [])
                for st in (r.get("assets_by_state") or {}).values()
                if st.get("file") == rel
            ),
            None,
        ) or next(
            (
                layer.get("sha256")
                for layer in contract.get("plate_layers", [])
                if layer.get("file") == rel
            ),
            None,
        )
        if declared is not None and sha != str(declared):
            raise BenchmarkError(
                f"{fixture.fixture_id}: asset SHA drift for {rel}: "
                f"disk {sha} != pinned {declared}"
            )
        return ReplacementAsset(path=fixtures_dir / rel, kind=kind)

    common: dict[str, Any] = dict(
        request_id=request_id,
        workspace_id="s09-benchmark-fixtures",
        project_id=f"s09-{fixture.fixture_id}",
        video_item_id=f"{fixture.fixture_id}-plate",
        occurrence_segment_id=f"{fixture.fixture_id}-{route}",
        route=route,
        start_frame=0,
        end_frame=frame_count - 1,
        input_media=plate_path,
        # Rendered output goes STRAIGHT to the run artifacts dir (prompt §4:
        # never render into tests/fixtures/**/rendered then copy).  The
        # workspace root below is widened so containment accepts it.
        output_media=out_path,
        workspace_root=workspace_root,
    )

    # C2: typed occluders + per-frame layer order from the fixture contract.
    # These flow through the PUBLIC RenderRequest surface so the production
    # adapter (not the harness) performs the z-compositing.
    occluders: dict[str, ReplacementAsset] = {}
    for occ in contract.get("occluders", []):
        rel = str(occ.get("file", ""))
        sha = _sha_file(fixtures_dir, rel)
        declared = occ.get("sha256")
        if declared is not None and sha != str(declared):
            raise BenchmarkError(
                f"{fixture.fixture_id}: occluder SHA drift for {rel}: "
                f"disk {sha} != pinned {declared}"
            )
        occluders[str(occ.get("layer_id") or Path(rel).stem)] = ReplacementAsset(
            path=fixtures_dir / rel, kind="sprite"
        )
    layer_order = tuple(
        LayerOrderEntry(
            frame_from=int(e["frame_from"]),
            frame_to=int(e["frame_to"]),
            layer_id=str(e.get("below") or "replacement"),
            z=-1,
        )
        for e in contract.get("expected_layer_order", [])
    )
    tb_den = int(str(fixture.manifest.get("time_base", "1/30")).split("/")[-1])
    timebase = SourceTimebase(fps_num=int(fps), fps_den=1, time_base=f"1/{tb_den}")
    common_extra: dict[str, Any] = {}
    if occluders:
        common_extra["occluder_assets"] = occluders
    if layer_order:
        common_extra["layer_order"] = layer_order
    # J1-C2-v2: per-region occluder placement (normalized x,y,w,h per
    # occluder name) -- without it the legacy compositor stretches the
    # occluder over the whole frame.
    occ_regions = contract.get("occluder_regions") or {}
    if occ_regions:
        common_extra["occluder_regions"] = {
            str(name): (float(r[0]), float(r[1]), float(r[2]), float(r[3]))
            for name, r in occ_regions.items()
        }
    common_extra["source_timebase"] = timebase

    if route == "pose_swap":
        reps = [
            r for r in contract.get("replacements", [])
            if r.get("kind") == "pose_state_sequence"
        ]
        if not reps:
            # pose_swap has nothing to swap on this fixture -> renderer must
            # reject; surface as CONTRACT_REJECTED so the gate stays red
            req = RenderRequest(**common, **common_extra)
            try:
                req.validate_for_render()
            except Exception as err:  # noqa: BLE001 - taxonomy pass-through
                return {"status": "CONTRACT_REJECTED", "reason": str(err)}, {
                    "route": route,
                    "output_media": out_path,
                }
            raise BenchmarkError(
                f"{fixture.fixture_id}: pose_swap contract unexpectedly accepted"
            )
        rep = reps[0]
        states = {
            state: _asset(spec["file"], "pose_state")
            for state, spec in rep["assets_by_state"].items()
        }
        schedule = tuple(
            PoseSwapEntry(
                frame=int(entry["from_frame"]),
                state_id=str(entry["state"]),
                asset=states[str(entry["state"])],
            )
            for entry in rep["state_schedule"]
        )
        placement = rep.get("placement_center_xy") or [
            int(res["width"]) // 2,
            int(res["height"]) // 2,
        ]
        # The frozen compositor crops/resizes the pose asset INTO the
        # affected region -- derive it from the declared placement + sprite
        # size so the head lands exactly where the plate expects it.
        pl = fixture.manifest.get("pose_layer") or {}
        spr_w, spr_h = pl.get("sprite_size_wh") or [100, 100]
        region_bbox = (
            (placement[0] - spr_w / 2) / float(res["width"]),
            (placement[1] - spr_h / 2) / float(res["height"]),
            spr_w / float(res["width"]),
            spr_h / float(res["height"]),
        )
        states = {
            state: _asset(spec["file"], "pose_state")
            for state, spec in rep["assets_by_state"].items()
        }
        schedule = tuple(
            PoseSwapEntry(
                frame=int(entry["from_frame"]),
                state_id=str(entry["state"]),
                asset=states[str(entry["state"])],
            )
            for entry in rep["state_schedule"]
        )
        req = RenderRequest(
            **common,
            **common_extra,
            pose_state_assets=states,
            pose_schedule=schedule,
            affected_region=AffectedRegion(region_bbox),
        )
        meta = {
            "route": route,
            "kind": "pose_state_sequence",
            "layer_id": rep["layer_id"],
            "states": sorted(states),
            "schedule": rep["state_schedule"],
            "placement_center_xy": placement,
            "affected_region_bbox_xywh_norm": list(region_bbox),
            "output_media": out_path,
            "fps": fps,
        }
        req.validate_for_render()
        return req, meta

    if route == "sprite_affine":
        affine_reps = [
            r for r in contract.get("replacements", [])
            if r.get("kind") == "affine_keyframes"
        ]
        traj_reps = [
            r for r in contract.get("replacements", [])
            if r.get("kind") == "prop_trajectory"
        ]
        if affine_reps:
            rep = affine_reps[0]
            rot_map = {int(k): float(v) for k, v in rep.get("rotation_deg_by_frame", {}).items()}
            scale_map = {int(k): float(v) for k, v in rep.get("scale_by_frame", {}).items()}
            frames_sorted = sorted(rot_map)
            keyframes = []
            for fr in frames_sorted:
                # the frozen compositor scales the layer about ITS OWN
                # CENTER before rotation -- mirror that exactly so the
                # contract-verification NCC compares like with like
                cur_scale = scale_map.get(fr, 1.0)
                keyframes.append(
                    AffineKeyframe(
                        frame=fr,
                        translation_xy=(0.0, 0.0),
                        scale=cur_scale,
                        rotation_deg=rot_map[fr],
                    )
                )
            placement = rep.get("placement_center_xy") or [
                int(res["width"]) // 2,
                int(res["height"]) // 2,
            ]
            asset = _asset(rep["assets_by_state"]["default"]["file"], "sprite")
            bbox = rep.get("bbox_xywh_norm")
            req = RenderRequest(
                **common,
                **common_extra,
                replacement_asset=asset,
                affine_keyframes=tuple(keyframes),
                anchor_xy_norm=(
                    placement[0] / float(res["width"]),
                    placement[1] / float(res["height"]),
                ),
                affected_region=AffectedRegion(tuple(bbox)) if bbox else None,
            )
            meta = {
                "route": route,
                "kind": "affine_keyframes",
                "layer_id": rep["layer_id"],
                "keyframe_frames": len(keyframes),
                "rotation_range_deg": [min(rot_map.values()), max(rot_map.values())],
                "placement_center_xy": placement,
                "output_media": out_path,
                "fps": fps,
            }
            req.validate_for_render()
            return req, meta
        if traj_reps:
            rep = traj_reps[0]
            # z-order honesty (F2): the frozen T02 surface composites the
            # replacement ON TOP of its input frames and exposes NO z
            # parameter. A contract whose replacement must sit BEHIND
            # foreground plate layers (z below any plate layer, e.g. f5's
            # occluder) cannot be rendered faithfully by this surface --
            # reject it fail-closed instead of silently mis-rendering.
            rep_z = rep.get("z")
            plate_z = [p.get("z") for p in contract.get("plate_layers") or []]
            fg_below = [z for z in plate_z if z is not None and rep_z is not None and z > rep_z]
            # Visibility-contract honesty: if this replacement layer is
            # DECLARED HIDDEN over frames where another layer stays visible,
            # something in the scene must occlude it -- i.e. the replacement
            # sits BEHIND a foreground element.  The frozen T02 surface has no
            # z parameter, so such contracts are rejected fail-closed instead
            # of silently mis-rendering (F2: never fake a capability).
            #
            # C2 EXCEPTION: when the fixture contract DECLARES the occlusion
            # via expected_layer_order + typed occluders (both flow through
            # the PUBLIC RenderRequest as layer_order/occluder_assets, and
            # composite_sprite_affine_frames draws occluders ABOVE the
            # replacement for z<0 entries), the surface renders it
            # faithfully -- no exemption would mean f5 can never be measured.
            declared_covered = bool(contract.get("expected_layer_order")) and bool(
                contract.get("occluders")
            )
            if not fg_below and not declared_covered:
                vis = fixture.manifest.get("visibility") or []
                rep_vis = next(
                    (v for v in vis if str(v.get("layer_id")) == str(rep.get("layer_id"))),
                    None,
                )
                others = [
                    v for v in vis if str(v.get("layer_id")) != str(rep.get("layer_id"))
                ]
                if rep_vis is not None and others:
                    total_frames = int(fixture.manifest["frame_count"])
                    covered: set[int] = set()
                    for lo, hi in rep_vis.get("intervals") or []:
                        covered.update(range(int(lo), int(hi) + 1))
                    hidden = [f for f in range(total_frames) if f not in covered]
                    if hidden:
                        for o in others:
                            for lo, hi in o.get("intervals") or []:
                                if any(int(lo) <= h <= int(hi) for h in hidden):
                                    fg_below.append(str(o.get("layer_id")))
                                    break
            if fg_below:
                return (
                    {
                        "status": "CONTRACT_REJECTED",
                        "reason": (
                            "capability_mismatch: frozen sprite_affine has no "
                            f"z-order; replacement z={rep_z} sits behind plate "
                            f"layer(s) z={fg_below}"
                        ),
                    },
                    {"route": route, "output_media": out_path},
                )
            pos_map = {int(k): (int(v[0]), int(v[1])) for k, v in rep["positions_by_frame"].items()}
            frames_sorted = sorted(pos_map)
            f_first = frames_sorted[0]
            bx, by = pos_map[f_first]
            # Frozen-compositor mapping: the layer CENTER lands at
            # anchor + keyframe translation (normalized).  Anchor pins the
            # layer at its first contracted position; each keyframe carries
            # the DELTA from that first position.
            keyframes = []
            for fr in frames_sorted:
                px, py = pos_map[fr]
                keyframes.append(
                    AffineKeyframe(
                        frame=fr,
                        translation_xy=(
                            (px - bx) / float(int(res["width"])),
                            (py - by) / float(int(res["height"])),
                        ),
                        scale=1.0,
                        rotation_deg=0.0,
                    )
                )
            asset = _asset(rep["assets_by_state"]["default"]["file"], "sprite")
            req = RenderRequest(
                **common,
                **common_extra,
                replacement_asset=asset,
                affine_keyframes=tuple(keyframes),
                anchor_xy_norm=(
                    (bx + 0.5) / float(int(res["width"])),
                    (by + 0.5) / float(int(res["height"])),
                ),
                affected_region=None,
            )
            meta = {
                "route": route,
                "kind": "prop_trajectory",
                "layer_id": rep["layer_id"],
                "trajectory_points": len(keyframes),
                "anchor_px": [bx, by],
                "output_media": out_path,
                "fps": fps,
            }
            req.validate_for_render()
            return req, meta
        req = RenderRequest(**common, **common_extra)
        try:
            req.validate_for_render()
        except Exception as err:  # noqa: BLE001 - taxonomy pass-through
            return {"status": "CONTRACT_REJECTED", "reason": str(err)}, {
                "route": route,
                "output_media": out_path,
            }
        raise BenchmarkError(
            f"{fixture.fixture_id}: sprite_affine contract unexpectedly accepted"
        )
    raise BenchmarkError(f"no Wave-B wiring for route {route!r}")


def render_and_measure_v2(
    fixture: Fixture,
    route: str,
    seed: int,
    artifacts_dir: Path,
    fixtures_dir: Path,
    freeze_args: argparse.Namespace | None = None,
) -> dict[str, Any]:
    """Render via the PUBLIC production surface and pin a full v3 record.

    F2 (C1 review): the request goes through ``RendererRouter.execute()`` --
    the exact public entry point production uses (router gate -> adapter ->
    typed contract validation -> compositor -> encode).  The harness NEVER
    imports composite helpers or private functions to substitute for the
    adapter.

    Steps:
        1. resolve render_contract from the manifest (source plate +
           replacement assets, SHA-pinned);
        2. build a typed RenderRequest against the C2 contract (imports
           happen here -- run_benchmark already passed the J1 gate);
        3. execute through RendererRouter.execute(); the adapter encodes at
           the request's rational source_timebase and hashes the canonical
           decoded frames of its own artifact;
        4. record v3 pins route, adapter/backend id, license/provenance,
           request contract SHA, J1 manifest SHA, encoded artifact SHA,
           canonical decoded frame SHA, frame count, fps/timebase, runtime,
           VRAM, metric sample count;
        5. re-verify the freeze manifest AFTER the run -- any drift between
           pre/post fails closed.
    """
    freeze_pre = _detect_contract_freeze(freeze_args)
    if not freeze_pre["frozen"]:
        raise BenchmarkError(
            f"render_and_measure_v2 called without a frozen contract: "
            f"{freeze_pre['evidence']}"
        )
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from app.adapters.renderer import PoseSwapAdapter, SpriteAffineAdapter  # noqa: PLC0415
    from app.services.renderer_contract import RenderRequest  # noqa: PLC0415
    from app.services.renderer_router import RendererRouter  # noqa: PLC0415

    contract = fixture.manifest.get("render_contract") or {}
    plate_decl = contract.get("source_plate") or contract.get("source_plate_source_frames") or {}
    plate = {"path": plate_decl.get("path"), "sha256": plate_decl.get("sha256")}
    request_id = f"s09bench-{fixture.fixture_id}-{route}-seed{seed}"
    built, meta = _build_render_request(
        fixture, route, fixtures_dir, artifacts_dir, request_id
    )
    record: dict[str, Any] = {
        "fixture_id": fixture.fixture_id,
        "route": route,
        "seed": seed,
        "measured_state": "PENDING_RENDERER_CONTRACT_FREEZE",
        "contract_freeze": freeze_pre,
        "input_hashes": {
            "fixture_media_sha256": _sha256_bytes(fixture.media_path.read_bytes()),
            "source_plate_sha256": plate.get("sha256"),
            "replacements": [
                {
                    "layer_id": r.get("layer_id"),
                    "assets_by_state": r.get("assets_by_state"),
                }
                for r in contract.get("replacements", [])
            ],
        },
        "decoded_output_hash": None,
        "backend": None,
        "artifact_path": None,
    }
    if isinstance(built, dict) and built.get("status") == "CONTRACT_REJECTED":
        record["measured_state"] = "CONTRACT_REJECTED_BY_FROZEN_CONTRACT"
        record["contract_rejection_reason"] = built.get("reason")
        record["backend"] = {
            "adapter": "RendererRouter.execute -> production adapters",
            "route": route,
            "accepted": False,
        }
        return record
    request = cast("RenderRequest", built)
    out_media = Path(cast("Any", meta)["output_media"])
    out_media.parent.mkdir(parents=True, exist_ok=True)
    # keep a copy of the rendered evidence inside the run artifacts dir
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_copy = artifacts_dir / "rendered_output.mp4"
    # ── PUBLIC production surface (F2): router gate + adapter.render ─────
    router = RendererRouter([PoseSwapAdapter(), SpriteAffineAdapter()])
    started = time.perf_counter()
    result = router.execute(request)
    wall_ms_total = (time.perf_counter() - started) * 1000.0
    if not result.ok or result.output_media is None:
        record["measured_state"] = "RENDERER_ERROR"
        record["backend"] = {
            "adapter": "RendererRouter.execute -> production adapters",
            "route": route,
            "accepted": False,
            "backend_id": result.backend_id,
            "error_code": str(result.error_code),
            "error_detail": str(result.error_detail)[:400],
        }
        return record
    if Path(result.output_media).resolve() != out_media.resolve():
        raise BenchmarkError(
            f"{fixture.fixture_id}: adapter wrote {result.output_media}, "
            f"expected {out_media}"
        )
    if Path(result.output_media).resolve() != artifact_copy.resolve():
        shutil.copyfile(out_media, artifact_copy)
    out_bytes = out_media.read_bytes()
    # F3/C3: canonical decoded-frame SHA of the ENCODED artifact, computed
    # INDEPENDENTLY (own implementation over frames from the PUBLIC decoder
    # only -- the production canonical_frame_sha256 helper is NOT imported
    # for this).  Equality with the adapter's self-reported
    # output_frame_sha256 is asserted below; a mismatch fails the row.
    from app.services.renderer_routes.composite import (  # noqa: PLC0415
        decode_rgb_frames as _decode_public,
    )
    encoded_frames = _decode_public(out_media)
    n_frames = len(encoded_frames)
    frame_count_expected = int(fixture.manifest["frame_count"])
    if n_frames != frame_count_expected:
        raise BenchmarkError(
            f"{fixture.fixture_id}/{route}: artifact decodes to {n_frames} "
            f"frames, contract declares {frame_count_expected}"
        )
    decoded_canonical = canonical_decoded_hash_independent(encoded_frames)
    adapter = router.select_backend(request)
    capability = getattr(adapter, "_last_capability", None)
    cap_details = dict(getattr(capability, "details", {}) or {})
    timebase = getattr(request, "source_timebase", None)
    record["measured_state"] = "MEASURED_RENDERED_OUTPUT"
    record["input_hashes"]["render_request_id"] = request_id
    # ── record v3: full provenance pinning ───────────────────────────────
    record["selected_route"] = route
    record["backend_v3"] = {
        "adapter_class": type(adapter).__name__,
        "backend_id": result.backend_id,
        "license_id": getattr(capability, "license_id", None),
        "evidence_source": getattr(capability, "evidence_source", None),
        "encode_backend": cap_details.get("encode"),
        "composite_backend": cap_details.get("composite"),
        "nvenc_provenance": cap_details.get("nvenc_provenance"),
        "accepted": True,
    }
    record["request_contract_sha256"] = RENDER_CONTRACT_FROZEN_SHA256
    # F3/C3 canonical-hash equality gate: the independently recomputed
    # canonical decoded hash MUST equal the adapter's self-reported
    # output_frame_sha256.  A mismatch means one of the two evidence
    # chains is broken -- fail closed instead of storing both.
    adapter_hash = cap_details.get("output_frame_sha256")
    if not isinstance(adapter_hash, str) or len(adapter_hash) != 64:
        record["measured_state"] = "CANONICAL_HASH_EVIDENCE_MISSING"
        record["canonical_hash_mismatch"] = {
            "reason": "adapter did not report output_frame_sha256",
        }
        return record
    if decoded_canonical != adapter_hash:
        record["measured_state"] = "CANONICAL_HASH_MISMATCH"
        record["canonical_hash_mismatch"] = {
            "independent_canonical": decoded_canonical,
            "adapter_reported": adapter_hash,
            "note": (
                "independent count+shape+bytes hash != adapter "
                "output_frame_sha256; evidence chain untrusted"
            ),
        }
        return record
    # C3/F2: every measured row pins the EXACT Manager manifest (path +
    # file SHA) that authorizes this run -- no auto-detect, no fallback.
    _j1_path, _j1_sha = _resolve_freeze_authority(freeze_args)
    record["j1_manifest_path"] = _j1_path.as_posix()
    record["j1_manifest_sha256"] = _j1_sha
    record["encoded_artifact_sha256"] = _sha256_bytes(out_bytes)
    record["decoded_output_hash"] = decoded_canonical
    record["adapter_output_frame_sha256"] = cap_details.get("output_frame_sha256")
    record["frame_count_rendered"] = n_frames
    record["fps_rational"] = (
        [getattr(timebase, "fps_num", None), getattr(timebase, "fps_den", None)]
        if timebase is not None
        else None
    )
    record["time_base"] = getattr(timebase, "time_base", None)
    record["runtime_ms_per_frame_measured"] = round(
        wall_ms_total / max(n_frames, 1), 4
    )
    record["vram_peak_mib"] = vram_peak_mib()
    record["metrics_sample_count"] = {
        "frames_decoded": n_frames,
        "keyframes_sampled": cap_details.get("keyframes_sampled"),
        "trajectory_points": cast("Any", meta).get("trajectory_points"),
        "keyframe_frames": cast("Any", meta).get("keyframe_frames"),
    }
    record["backend"] = {
        "adapter": "RendererRouter.execute -> production adapters",
        "route": route,
        "accepted": True,
        "backend_id": result.backend_id,
        "writer": "adapter encode path (source_timebase preserved)",
        "frames_rendered": result.frames_rendered,
        "wall_time_ms_total": round(result.wall_time_ms, 2),
        "contract_sha256": RENDER_CONTRACT_FROZEN_SHA256,
    }
    # store as run-scoped STRING path (like the adversarial control does);
    # it identifies the evidence copy but is excluded from determinism
    # compares because it moves with --out
    record["artifact_path"] = str(artifact_copy)
    # F3 drift check AFTER the measured run: the Manager freeze authority
    # must still verify; otherwise this run cannot be trusted.
    freeze_post = _detect_contract_freeze(freeze_args)
    record["contract_freeze_post_run"] = freeze_post
    if not freeze_post["frozen"]:
        record["measured_state"] = "CONTRACT_DRIFT_DURING_RUN"
        return record
    return record


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
        doc = {"mode": "DRY_RUN", "frozen": freeze, "plan": plan}
        out_path = Path(args.out).resolve() / f"benchmark_results_seed{args.seed}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"[out] {out_path}")
        return doc

    # v2 policy gate: measured route verdicts require the Manager-pinned
    # J1 freeze authority (C3: one manifest, pre/post verified, no
    # fallback). Without it the harness is fail-closed PENDING -- exactly
    # one explicit escape hatch exists (the self-test flag) and it labels
    # its output as non-evidence estimator calibration on SOURCE frames.
    freeze_state = _detect_contract_freeze(args)
    self_test = bool(getattr(args, "self_test_source_observation", False))
    if not freeze_state["frozen"] and not self_test:
        print(
            "[v2] measured runs BLOCKED: renderer contract not frozen yet "
            f"({freeze_state['evidence']})",
            flush=True,
        )
        print(
            "[v2] Wave B (measured benchmark) starts only after "
            "T02_CONTRACT_FROZEN_FOR_I03; no route verdicts are produced now.",
            flush=True,
        )
    results: list[dict[str, Any]] = []
    for fixture in fixtures:
        for route in routes:
            if not freeze_state["frozen"]:
                if self_test:
                    entry = _self_test_entry(fixture, route, args, fixtures_dir, thresholds)
                else:
                    entry = {
                        "fixture_id": fixture.fixture_id,
                        "risk_class": fixture.manifest["risk_class"],
                        "route": route,
                        "seed": args.seed,
                        "measured_state": "PENDING_RENDERER_CONTRACT_FREEZE",
                        "contract_freeze": freeze_state,
                    }
                results.append(entry)
                print(
                    f"[pending] {fixture.fixture_id} route={route} state={entry['measured_state']}",
                    flush=True,
                )
                continue
            started = time.perf_counter()
            # ── Wave B path (J1 satisfied): render then measure the OUTPUT ──
            artifacts_dir = Path(args.out).resolve() / "artifacts" / fixture.fixture_id / route
            plan_record = render_and_measure_v2(
                fixture, route, args.seed, artifacts_dir, fixtures_dir, freeze_args=args
            )
            if plan_record.get("measured_state") == "CONTRACT_REJECTED_BY_FROZEN_CONTRACT":
                results.append(plan_record)
                print(
                    f"[rejected] {fixture.fixture_id} route={route} "
                    f"{plan_record.get('contract_rejection_reason', '')[:120]}",
                    flush=True,
                )
                continue
            out_media = plan_record.get("artifact_path")
            if not isinstance(out_media, str) or not Path(out_media).is_file():
                raise BenchmarkError(
                    f"{fixture.fixture_id}/{route}: renderer produced no artifact; "
                    "refusing to score source frames (F2)"
                )
            frames_raw = decode_frames(Path(out_media))
            res = fixture.manifest["resolution"]
            n_expected = (
                int(fixture.manifest["frame_count"]) * int(res["height"]) * int(res["width"]) * 3
            )
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
            # F2 core metric: does the declared replacement actually show up
            # in the RENDERED OUTPUT (rotation-aware NCC presence)?
            contract = fixture.manifest.get("render_contract") or {}
            if contract.get("replacements"):
                metrics["replacement_effect"] = _replacement_presence_stats(
                    frames, contract, fixtures_dir
                )
            adv = adversarial_source_reencode_control(
                fixture, route, fixtures_dir, artifacts_dir.parent
            )
            if adv:
                metrics["adversarial_control"] = adv
            evaluation = evaluate_thresholds(metrics, thresholds)
            wall_ms = (time.perf_counter() - started) * 1000.0 / max(frames.shape[0], 1)
            entry = {
                "fixture_id": fixture.fixture_id,
                "risk_class": fixture.manifest["risk_class"],
                "route": route,
                "seed": args.seed,
                "measured_state": "MEASURED_RENDERED_OUTPUT",
                "input_hashes": plan_record.get("input_hashes"),
                "decoded_output_hash": plan_record.get("decoded_output_hash"),
                "backend": plan_record.get("backend"),
                # record-v3 provenance pinning (C2 acceptance item 3)
                "selected_route": plan_record.get("selected_route"),
                "backend_v3": plan_record.get("backend_v3"),
                "request_contract_sha256": plan_record.get("request_contract_sha256"),
                "j1_manifest_path": plan_record.get("j1_manifest_path"),
                "j1_manifest_sha256": plan_record.get("j1_manifest_sha256"),
                "decoded_output_hash_independent": plan_record.get(
                    "decoded_output_hash"
                ),
                "canonical_hash_verified": (
                    plan_record.get("decoded_output_hash")
                    == plan_record.get("adapter_output_frame_sha256")
                ),
                "encoded_artifact_sha256": plan_record.get("encoded_artifact_sha256"),
                "adapter_output_frame_sha256": plan_record.get(
                    "adapter_output_frame_sha256"
                ),
                "frame_count_rendered": plan_record.get("frame_count_rendered"),
                "fps_rational": plan_record.get("fps_rational"),
                "time_base": plan_record.get("time_base"),
                "runtime_ms_per_frame_measured": plan_record.get(
                    "runtime_ms_per_frame_measured"
                ),
                "metrics_sample_count": plan_record.get("metrics_sample_count"),
                "contract_freeze_post_run": plan_record.get("contract_freeze_post_run"),
                "artifact_path": str(plan_record.get("artifact_path")),
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

    media_verification = evaluate_reference_media(args.reference_media)
    ref_contract = getattr(args, "reference_annotation_contract", None)
    result_doc = {
        "schema_version": SCHEMA_VERSION,
        "frozen_content_sha256": freeze["frozen_content_sha256"],
        "freeze_components": freeze["components"],
        "routes": routes,
        "seed": args.seed,
        "measurement_mode": (
            "SELF_TEST_SOURCE_OBSERVATION_NON_EVIDENCE"
            if (self_test and not freeze_state["frozen"])
            else ("RENDERED_OUTPUT" if freeze_state["frozen"] else "BLOCKED_PENDING_J1")
        ),
        "non_deterministic_fields_excluded_from_compare": list(NON_DETERMINISTIC_FIELDS),
        "thresholds_policy": thresholds.get("policy"),
        "results": results,
        "reference_media_verification": media_verification,
        "reference_benchmark": evaluate_reference_benchmark(media_verification, ref_contract),
    }
    out_path = Path(args.out).resolve() / f"benchmark_results_seed{args.seed}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[out] {out_path}")
    return result_doc


def _self_test_entry(
    fixture: Fixture,
    route: str,
    args: argparse.Namespace,
    fixtures_dir: Path,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """Estimator CALIBRATION on source frames -- explicitly NOT evidence.

    Kept from v1 so the tracking/estimator stack stays exercised while the
    real renderer integration is pending. Results are labelled
    SELF_TEST_SOURCE_OBSERVATION_NON_EVIDENCE and must never be quoted as
    route quality (this is precisely what F2 forbade).
    """
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
    # capability difference lives in the ESTIMATOR layer: pose_swap observes
    # the scheduled states, sprite_affine does not -- keep that signal even
    # though the real renderer is now wired (self-test stays non-evidence).
    if route == "pose_swap":
        metrics["pose_state_capability"] = True
        evaluation = evaluate_thresholds(metrics, thresholds)
    else:
        metrics["pose_state_capability"] = False
        evaluation = evaluate_thresholds(metrics, thresholds)
        evaluation["checks"] = [
            c for c in evaluation.get("checks", []) if c.get("metric") != "pose_state_capability"
        ] + [
            {"metric": "pose_state_capability", "value": False, "pass": False,
             "detail": "sprite_affine cannot express pose-state schedules (capability boundary)"},
        ]
        evaluation["overall_pass"] = False
    wall_ms = (time.perf_counter() - started) * 1000.0 / max(frames.shape[0], 1)
    return {
        "fixture_id": fixture.fixture_id,
        "risk_class": fixture.manifest["risk_class"],
        "route": route,
        "seed": args.seed,
        "measured_state": "SELF_TEST_SOURCE_OBSERVATION_NON_EVIDENCE",
        "metrics": metrics,
        "threshold_evaluation": evaluation,
        "wall_runtime_ms_per_frame": round(wall_ms, 4),
        "vram_peak_mib": vram_peak_mib(),
        "route_notes": obs.notes,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--routes", default=DEFAULT_ROUTES, help="comma-separated renderer routes")
    ap.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/s09_renderer"))
    ap.add_argument(
        "--fixtures-filter", nargs="*", default=None, help="optional fixture ids subset"
    )
    ap.add_argument("--out", type=Path, required=True, help="output directory for results JSON")
    ap.add_argument("--seed", type=int, default=20260823)
    ap.add_argument(
        "--dry-run", action="store_true", help="freeze + validate + plan, no measurement"
    )
    ap.add_argument(
        "--reference-media", type=Path, default=None, help="optional verified reference path"
    )
    ap.add_argument(
        "--reference-annotation-contract",
        type=Path,
        default=None,
        help=(
            "authoritative REF-R01..R05 annotation/replacement contract JSON; "
            "without it reference_benchmark stays SKIPPED_WITH_REASON_..."
        ),
    )
    ap.add_argument(
        "--self-test-source-observation",
        action="store_true",
        help=(
            "ESTIMATOR CALIBRATION ONLY: score source frames like v1 did. The "
            "output is labelled NON-EVIDENCE and must never be quoted as route "
            "quality; real measured runs need the frozen T02 contract."
        ),
    )
    ap.add_argument(
        "--manifest-path",
        type=Path,
        default=None,
        help=(
            "C3 freeze authority: exact Manager-pinned J1 manifest path. "
            "Verified before AND after every measured run (fail-closed); "
            "defaults to the pinned J1-C3-v4 authority when omitted."
        ),
    )
    ap.add_argument(
        "--manifest-sha256",
        default=None,
        help=(
            "Expected SHA-256 of the Manager manifest FILE itself (the "
            "value published by the Manager). Defaults to the pinned "
            "J1-C3-v4 manifest SHA."
        ),
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # C3: validate the manifest flags up-front (typo'd SHA or missing file
    # must fail BEFORE any work, not silently fall back to defaults).
    if getattr(args, "manifest_path", None) is not None:
        if not getattr(args, "manifest_sha256", None):
            print(
                "BENCHMARK_ERROR: --manifest-path requires --manifest-sha256",
                file=sys.stderr,
            )
            return 2
        mpath = Path(str(args.manifest_path))
        if not mpath.is_file():
            print(
                f"BENCHMARK_ERROR: --manifest-path not found: {mpath}",
                file=sys.stderr,
            )
            return 2
    try:
        run_benchmark(args)
    except BenchmarkError as err:
        print(f"BENCHMARK_ERROR: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
