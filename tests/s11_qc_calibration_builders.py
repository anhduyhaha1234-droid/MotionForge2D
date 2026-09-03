"""S11-T06A2 raw QC calibration builders — deterministic raw inputs and
measured raw values (W4).

Owned module — every metric gets a deterministic SEEDED input generator
(``generate_*``) plus a raw measurement function (``measure_*``) that
returns the RAW value of that input and nothing else.  ``build_all_
calibration`` runs the real measurements ONCE per perturbation level and
writes the four committed calibration JSON files byte-deterministically.

Boundary (lane-A GAP-4/R2/R6): this module is the measurement source for
later-wave policy (T03A owns the policy files) — it never derives,
encodes or names any policy itself.  Raw facts only.  The self-test's
binary scan guards this file and the committed JSON.

Determinism convention (lane-B §1.1, measured S11): within one machine +
one ffmpeg build every output repeats byte-for-byte (asserted ×2 by
self-test hash); no hard cross-machine hash is ever asserted.

No network, no committed binaries: the only media touched is the T06A1
no-audio builder consumed read-only (``build_no_audio_source`` +
``probe_facts``) and rebuilt into a caller temp dir at runtime.

Coverage (production plan C6-F1 partition):
- trajectory_cut.json             -> trajectory_drift, cut_drift
- contact_zorder_clipping.json    -> contact_break, z_order_error,
                                     silhouette_clipping
- identity_halo_flicker.json      -> identity_drift, edge_halo,
                                     temporal_flicker
- av_sync.json                    -> av_sync_drift, no_audio_source_fact
"""

from __future__ import annotations

import json
import math
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from s11_qc_media_builders import (  # noqa: E402 - consume, never modify
    build_no_audio_source,
    probe_facts,
)

__all__ = [
    "CALIBRATION_FIXTURES",
    "CALIBRATION_REVISION",
    "build_all_calibration",
    "iter_calibration_fixtures",
    "load_calibration_fixture",
    "resolve_measurement",
    "resolve_source",
]

#: Revision of every raw measurement function in this module.  Later-wave
#: policy work cites this revision in its provenance (T03A contract: cite
#: the true builder/measurement record).
CALIBRATION_REVISION = "1.0.0"

#: Canonical fixture order — the suite builds/verifies exactly this set.
CALIBRATION_FIXTURES: tuple[str, ...] = (
    "trajectory_cut",
    "contact_zorder_clipping",
    "identity_halo_flicker",
    "av_sync",
)

#: Committed calibration directory.
CALIBRATION_DIR = (
    Path(__file__).resolve().parent / "fixtures" / "s11_qc" / "calibration"
)

#: Frame dimensions used by the synthetic inputs (measured S11
#: convention: small frames keep the suite cheap).
_FRAME_W = 100
_FRAME_H = 100


def _source_ref(fn: Callable[..., Any]) -> str:
    return f"s11_qc_calibration_builders.py:{fn.__name__}"


def _result_ref(fn: Callable[..., Any]) -> str:
    return f"s11_qc_calibration_builders.py:{fn.__name__}"


def resolve_source(reference: str) -> Callable[..., Any]:
    """Resolve a record's source-reference to the real generator."""
    name = reference.split(":")[-1]
    fn = getattr(sys.modules[__name__], name, None)
    assert callable(fn), f"source reference does not resolve: {reference!r}"
    return fn


def resolve_measurement(reference: str) -> Callable[..., Any]:
    """Resolve a record's result-reference to the real measurement fn."""
    name = reference.split(":")[-1]
    fn = getattr(sys.modules[__name__], name, None)
    assert callable(fn), (
        f"result reference does not resolve: {reference!r}"
    )
    return fn


# ── trajectory / cut ───────────────────────────────────────────────────────

def generate_trajectory_drift_input(
    seed: int, drift_px_per_frame: float, frames: int = 64,
) -> dict[str, Any]:
    """Reference straight run + drifted run; drift grows linearly with
    time at ``drift_px_per_frame`` px/frame (raw input only)."""
    x0 = 10.0 + float(seed % 5)
    t = np.arange(frames, dtype=np.float64)
    reference = x0 + 0.5 * t
    drifted = reference + drift_px_per_frame * t
    return {"reference_x": reference, "drifted_x": drifted}


def measure_trajectory_drift(inp: dict[str, Any]) -> float:
    """Raw: mean absolute horizontal deviation (px) of the drifted path
    from the reference path over the whole window."""
    delta = np.abs(inp["drifted_x"] - inp["reference_x"])
    return float(np.mean(delta))


def generate_cut_drift_input(
    seed: int, offset_frames: int, reference_cut: int = 90,
) -> dict[str, Any]:
    """Reference scene boundary (frame index) vs detected boundary shifted
    by ``offset_frames`` (side chosen by seed parity — magnitude is the
    perturbation)."""
    side = 1 if seed % 2 == 0 else -1
    detected = int(reference_cut) + side * int(offset_frames)
    return {
        "reference_cut": int(reference_cut),
        "detected_cut": detected,
    }


def measure_cut_drift(inp: dict[str, Any]) -> int:
    """Raw: absolute cut-position deviation in frames."""
    return abs(int(inp["detected_cut"]) - int(inp["reference_cut"]))


# ── contact / z-order / clipping ───────────────────────────────────────────

def generate_contact_break_input(
    seed: int, base_gap_px: float, frames: int = 48,
) -> dict[str, Any]:
    """Two rigid silhouettes whose vertical gap (px) is constant over the
    window; perturbation = gap magnitude."""
    gap = float(base_gap_px)
    gaps = np.full(frames, gap, dtype=np.float64)
    return {"gap_px_per_frame": gaps}


def measure_contact_break(inp: dict[str, Any]) -> float:
    """Raw: minimum vertical gap (px) between the two silhouettes across
    the contact window."""
    return float(np.min(inp["gap_px_per_frame"]))


def generate_z_order_error_input(
    seed: int, swapped_pairs: int,
) -> dict[str, Any]:
    """Reference layer order vs observed order with ``swapped_pairs``
    adjacent pairs exchanged in place (perturbation = number of swapped
    pairs; each swap displaces exactly two layers)."""
    reference = [
        "bg", "char", "fg", "ui", "particle",
        "shadow", "highlight", "outline",
    ]
    observed = list(reference)
    k = int(swapped_pairs)
    for i in range(k):
        pos = (i * 2) % (len(observed) - 1)
        observed[pos], observed[pos + 1] = (
            observed[pos + 1], observed[pos],
        )
    return {"reference_order": reference, "observed_order": observed}


def measure_z_order_error(inp: dict[str, Any]) -> int:
    """Raw: count of layers whose position differs from the reference
    order."""
    ref = inp["reference_order"]
    obs = inp["observed_order"]
    return sum(1 for a, b in zip(ref, obs) if a != b)


def generate_silhouette_clipping_input(
    seed: int, clip_px: float,
) -> dict[str, Any]:
    """Silhouette rectangle shifted right by ``clip_px`` inside a
    ``_FRAME_W``-wide frame; part of it exits the frame (raw input)."""
    x0 = 20.0 + float(clip_px)
    x1 = 80.0 + float(clip_px)
    y0 = 30.0
    y1 = 70.0
    area = (x1 - x0) * (y1 - y0)
    return {
        "frame_w": float(_FRAME_W),
        "frame_h": float(_FRAME_H),
        "x0": x0, "x1": x1, "y0": y0, "y1": y1,
        "area_px": area,
    }


def measure_silhouette_clipping(inp: dict[str, Any]) -> float:
    """Raw: clipped pixel ratio — silhouette area outside the frame
    divided by total silhouette area (0..1)."""
    clipped_left = max(0.0, -inp["x0"])
    clipped_right = max(0.0, inp["x1"] - inp["frame_w"])
    clipped_top = max(0.0, -inp["y0"])
    clipped_bottom = max(0.0, inp["y1"] - inp["frame_h"])
    clipped = (clipped_left + clipped_right) * (inp["y1"] - inp["y0"]) + (
        (clipped_top + clipped_bottom) * (inp["x1"] - inp["x0"])
    )
    return float(clipped / inp["area_px"])


# ── identity / halo / flicker ──────────────────────────────────────────────

def generate_identity_drift_input(
    seed: int, noise_amp_px: float,
) -> dict[str, Any]:
    """Reference identity anchor + drifted anchor at a seed-fixed angle
    and perturbation-scaled distance (raw input)."""
    ref = np.array([50.0, 50.0], dtype=np.float64)
    angle = float(seed % 360) * math.pi / 180.0
    unit = np.array([math.cos(angle), math.sin(angle)], dtype=np.float64)
    drifted = ref + float(noise_amp_px) * unit
    return {"reference": ref, "drifted": drifted}


def measure_identity_drift(inp: dict[str, Any]) -> float:
    """Raw: euclidean distance (px) between reference and drifted
    identity anchors."""
    return float(np.linalg.norm(inp["drifted"] - inp["reference"]))


def generate_edge_halo_input(
    seed: int, halo_radius_px: float, grid: int = 200, inner_r: float = 40.0,
) -> dict[str, Any]:
    """Filled disc (radius ``inner_r``) + concentric halo ring of base
    width ``halo_radius_px`` (raw input, sampled on a discrete grid)."""
    r = float(halo_radius_px)
    center = np.array([grid / 2.0, grid / 2.0], dtype=np.float64)
    y, x = np.mgrid[0:grid, 0:grid]
    dist = np.sqrt((x - center[0]) ** 2 + (y - center[1]) ** 2)
    ring = (dist >= inner_r) & (dist < inner_r + r)
    return {
        "inner_radius": float(inner_r),
        "halo_radius_px": r,
        "ring_area_px": float(np.count_nonzero(ring)),
    }


def measure_edge_halo(inp: dict[str, Any]) -> float:
    """Raw: mean halo width (px) — ring area / inner circumference."""
    circumference = 2.0 * math.pi * inp["inner_radius"]
    return float(inp["ring_area_px"] / circumference)


def generate_temporal_flicker_input(
    seed: int, flicker_amp: float, frames: int = 128,
) -> dict[str, Any]:
    """Per-frame luminance series: constant base + perturbation-scaled
    seed-fixed waveform (raw input)."""
    phase = float(seed % 8)
    t = np.arange(frames, dtype=np.float64)
    waveform = np.sin(2.0 * math.pi * (t + phase) / 16.0)
    luminance = 100.0 + float(flicker_amp) * waveform
    return {"luminance": luminance, "flicker_amp": float(flicker_amp)}


def measure_temporal_flicker(inp: dict[str, Any]) -> float:
    """Raw: mean inter-frame luminance delta (nondimensional level)."""
    return float(np.mean(np.abs(np.diff(inp["luminance"]))))


# ── A/V sync / NO_AUDIO ────────────────────────────────────────────────────

def generate_av_sync_input(
    seed: int, offset_sec: float, fps: float = 30.0, frames: int = 180,
) -> dict[str, Any]:
    """Video frame timeline + audio event timeline delayed by
    ``offset_sec`` (perturbation = the raw drift magnitude)."""
    video_pts = np.arange(frames, dtype=np.float64) / fps
    audio_pts = video_pts + float(offset_sec)
    return {"video_pts": video_pts, "audio_pts": audio_pts}


def measure_av_sync_drift(inp: dict[str, Any]) -> float:
    """Raw: median audio-vs-video timestamp deviation (seconds)."""
    return float(np.median(inp["audio_pts"] - inp["video_pts"]))


def generate_no_audio_input(
    seed: int, duration_sec: float,
) -> dict[str, Any]:
    """Build a REAL T06A1 no-audio media file into a fresh caller temp
    dir (raw media input; consumed builder is read-only)."""
    dest = Path(tempfile.mkdtemp(prefix="s11qc-noaudio-"))
    media = build_no_audio_source(dest / "no_audio_source.mp4",
                                  duration=duration_sec)
    return {"media_path": str(media), "temp_dir": str(dest)}


def measure_no_audio_source(inp: dict[str, Any]) -> int:
    """Raw: REAL audio-stream count measured by ffprobe on the built
    media (0 for the no-audio source).  Best-effort cleanup of the caller
    temp dir after probing."""
    try:
        facts = probe_facts(Path(inp["media_path"]))
        return sum(
            1 for s in facts.get("streams", [])
            if s.get("codec_type") == "audio"
        )
    finally:
        shutil.rmtree(Path(inp["temp_dir"]), ignore_errors=True)


def no_audio_measure_duration_sec(inp: dict[str, Any]) -> float:
    """Companion raw fact: REAL probed duration (seconds) of the built
    no-audio media (used for the raw duration levels, not the count)."""
    facts = probe_facts(Path(inp["media_path"]))
    return float(facts.get("duration_sec") or 0.0)


# ── fixture definitions ────────────────────────────────────────────────────

def _record(
    *,
    metric: str,
    unit: str,
    seed: int,
    source: Callable[..., Any],
    measure: Callable[..., Any],
    monotonic: str,
    levels: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    """Assemble one metric record: every level's raw value comes from
    RUNNING the real measurement on the deterministic generator output."""
    return {
        "metric": metric,
        "unit": unit,
        "deterministic_seed": seed,
        "source_reference": _source_ref(source),
        "result_reference": _result_ref(measure),
        "measurement_function_revision": CALIBRATION_REVISION,
        "monotonic": monotonic,
        "perturbation_levels": levels,
    }


def build_trajectory_cut_fixture() -> dict[str, Any]:
    """trajectory_drift + cut_drift — T03B partition."""
    trajectory_levels: list[dict[str, Any]] = []
    for i, amp in enumerate([0.5, 1.0, 2.0, 4.0], start=1):
        inp = generate_trajectory_drift_input(seed=11001,
                                              drift_px_per_frame=amp)
        trajectory_levels.append({
            "level": i,
            "perturbation": {"drift_px_per_frame": amp},
            "raw_value": round(measure_trajectory_drift(inp), 9),
        })
    cut_levels: list[dict[str, Any]] = []
    for i, off in enumerate([1, 3, 6, 12], start=1):
        inp = generate_cut_drift_input(seed=11002, offset_frames=off)
        cut_levels.append({
            "level": i,
            "perturbation": {"offset_frames": off},
            "raw_value": measure_cut_drift(inp),
        })
    return {
        "fixture_type": "s11_qc_calibration",
        "schema_version": 1,
        "fixture_id": "trajectory_cut",
        "metrics": [
            _record(
                metric="trajectory_drift",
                unit="px",
                seed=11001,
                source=generate_trajectory_drift_input,
                measure=measure_trajectory_drift,
                monotonic="increasing",
                levels=trajectory_levels,
            ),
            _record(
                metric="cut_drift",
                unit="frame",
                seed=11002,
                source=generate_cut_drift_input,
                measure=measure_cut_drift,
                monotonic="increasing",
                levels=cut_levels,
            ),
        ],
    }


def build_contact_zorder_clipping_fixture() -> dict[str, Any]:
    """contact_break + z_order_error + silhouette_clipping — T03C."""
    contact_levels: list[dict[str, Any]] = []
    for i, gap in enumerate([2.0, 4.0, 8.0, 16.0], start=1):
        inp = generate_contact_break_input(seed=11003, base_gap_px=gap)
        contact_levels.append({
            "level": i,
            "perturbation": {"base_gap_px": gap},
            "raw_value": round(measure_contact_break(inp), 9),
        })
    z_levels: list[dict[str, Any]] = []
    for i, swapped in enumerate([1, 2, 3, 4], start=1):
        inp = generate_z_order_error_input(seed=11004, swapped_pairs=swapped)
        z_levels.append({
            "level": i,
            "perturbation": {"swapped_pairs": swapped},
            "raw_value": measure_z_order_error(inp),
        })
    clip_levels: list[dict[str, Any]] = []
    for i, clip in enumerate([25.0, 30.0, 40.0, 50.0], start=1):
        inp = generate_silhouette_clipping_input(seed=11005, clip_px=clip)
        clip_levels.append({
            "level": i,
            "perturbation": {"clip_px": clip},
            "raw_value": round(measure_silhouette_clipping(inp), 9),
        })
    return {
        "fixture_type": "s11_qc_calibration",
        "schema_version": 1,
        "fixture_id": "contact_zorder_clipping",
        "metrics": [
            _record(
                metric="contact_break",
                unit="px",
                seed=11003,
                source=generate_contact_break_input,
                measure=measure_contact_break,
                monotonic="increasing",
                levels=contact_levels,
            ),
            _record(
                metric="z_order_error",
                unit="count",
                seed=11004,
                source=generate_z_order_error_input,
                measure=measure_z_order_error,
                monotonic="increasing",
                levels=z_levels,
            ),
            _record(
                metric="silhouette_clipping",
                unit="ratio",
                seed=11005,
                source=generate_silhouette_clipping_input,
                measure=measure_silhouette_clipping,
                monotonic="increasing",
                levels=clip_levels,
            ),
        ],
    }


def build_identity_halo_flicker_fixture() -> dict[str, Any]:
    """identity_drift + edge_halo + temporal_flicker — T03D."""
    id_levels: list[dict[str, Any]] = []
    for i, amp in enumerate([1.0, 2.0, 4.0, 8.0], start=1):
        inp = generate_identity_drift_input(seed=11006, noise_amp_px=amp)
        id_levels.append({
            "level": i,
            "perturbation": {"noise_amp_px": amp},
            "raw_value": round(measure_identity_drift(inp), 9),
        })
    halo_levels: list[dict[str, Any]] = []
    for i, radius in enumerate([1.0, 2.0, 4.0, 8.0], start=1):
        inp = generate_edge_halo_input(seed=11007, halo_radius_px=radius)
        halo_levels.append({
            "level": i,
            "perturbation": {"halo_radius_px": radius},
            "raw_value": round(measure_edge_halo(inp), 9),
        })
    flicker_levels: list[dict[str, Any]] = []
    for i, amp in enumerate([0.05, 0.1, 0.2, 0.4], start=1):
        inp = generate_temporal_flicker_input(seed=11008, flicker_amp=amp)
        flicker_levels.append({
            "level": i,
            "perturbation": {"flicker_amp": amp},
            "raw_value": round(measure_temporal_flicker(inp), 9),
        })
    return {
        "fixture_type": "s11_qc_calibration",
        "schema_version": 1,
        "fixture_id": "identity_halo_flicker",
        "metrics": [
            _record(
                metric="identity_drift",
                unit="px",
                seed=11006,
                source=generate_identity_drift_input,
                measure=measure_identity_drift,
                monotonic="increasing",
                levels=id_levels,
            ),
            _record(
                metric="edge_halo",
                unit="px",
                seed=11007,
                source=generate_edge_halo_input,
                measure=measure_edge_halo,
                monotonic="increasing",
                levels=halo_levels,
            ),
            _record(
                metric="temporal_flicker",
                unit="level",
                seed=11008,
                source=generate_temporal_flicker_input,
                measure=measure_temporal_flicker,
                monotonic="increasing",
                levels=flicker_levels,
            ),
        ],
    }


def build_av_sync_fixture() -> dict[str, Any]:
    """av_sync_drift (synthetic timeline) + no_audio_source_fact (REAL
    ffprobe measurement on a freshly built T06A1 no-audio media)."""
    av_levels: list[dict[str, Any]] = []
    for i, offset in enumerate([0.05, 0.1, 0.25, 0.5], start=1):
        inp = generate_av_sync_input(seed=11009, offset_sec=offset)
        av_levels.append({
            "level": i,
            "perturbation": {"offset_sec": offset},
            "raw_value": round(measure_av_sync_drift(inp), 9),
        })
    noa_levels: list[dict[str, Any]] = []
    for i, duration in enumerate([1.0, 2.0, 4.0], start=1):
        inp = generate_no_audio_input(seed=11010, duration_sec=duration)
        # probe duration FIRST (media still present), then the count
        # measurement which cleans up the caller temp dir
        duration_sec = no_audio_measure_duration_sec(inp)
        count = measure_no_audio_source(inp)
        noa_levels.append({
            "level": i,
            "perturbation": {"duration_sec": duration},
            "raw_value": count,
            "measured_duration_sec": round(duration_sec, 3),
        })
    return {
        "fixture_type": "s11_qc_calibration",
        "schema_version": 1,
        "fixture_id": "av_sync",
        "metrics": [
            _record(
                metric="av_sync_drift",
                unit="s",
                seed=11009,
                source=generate_av_sync_input,
                measure=measure_av_sync_drift,
                monotonic="increasing",
                levels=av_levels,
            ),
            _record(
                metric="no_audio_source_fact",
                unit="count",
                seed=11010,
                source=generate_no_audio_input,
                measure=measure_no_audio_source,
                monotonic="constant",
                levels=noa_levels,
            ),
        ],
    }


_BUILDERS: dict[str, Callable[[], dict[str, Any]]] = {
    "trajectory_cut": build_trajectory_cut_fixture,
    "contact_zorder_clipping": build_contact_zorder_clipping_fixture,
    "identity_halo_flicker": build_identity_halo_flicker_fixture,
    "av_sync": build_av_sync_fixture,
}


def build_all_calibration(dest_dir: Path) -> dict[str, Path]:
    """ONE command builds the four calibration fixtures (real raw
    measurements) into ``dest_dir`` and writes them as sorted deterministic
    JSON.  Returns ``{fixture_id: path}`` in canonical order.  Two builds
    on the same machine produce byte-identical files (self-test ×2)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    built: dict[str, Path] = {}
    for fixture_id in CALIBRATION_FIXTURES:
        doc = _BUILDERS[fixture_id]()
        path = dest / f"{fixture_id}.json"
        path.write_text(
            json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        built[fixture_id] = path
    return built


def load_calibration_fixture(fixture_id: str) -> dict[str, Any]:
    """Load one committed calibration fixture (schema verified by the
    self-test)."""
    path = CALIBRATION_DIR / f"{fixture_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"calibration fixture missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def iter_calibration_fixtures() -> list[dict[str, Any]]:
    """All committed calibration fixtures in canonical order."""
    return [load_calibration_fixture(f) for f in CALIBRATION_FIXTURES]