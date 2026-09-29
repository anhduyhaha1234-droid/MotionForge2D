"""DELTA-F6 probe (READ-ONLY): ground truth for F-R4-1 / F-R4-2 on the R4
runtime (#7 code + Temp/mfr4 DB/artifacts, still on disk).

Prints:
  A) identity_drift per-key byte breakdown + crop geometry of the real video
     (raises the composer's argv ceiling in RAM only; no writes).
  B) cut_drift: the DEFAULT window (expect the typed refusal), then the
     window with BOTH truncations raised (compose.MAX_WINDOW_FRAMES and
     measure.MAX_WINDOW_FRAMES) -> are the real cuts (119->120, 239->240)
     observable once nothing truncates?
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

EVID = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/DELTA-F6"
)
MFR4 = Path("C:/Users/Admin/AppData/Local/Temp/mfr4")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F6")

os.environ.setdefault("MOTIONFORGE_ROOT", str(MFR4))
sys.path.insert(0, str(WT))

from app.persistence import (  # noqa: E402
    DEFAULT_WORKSPACE_ID,
    create_engine_for_path,
    create_session_factory,
)
from app.services.qc_evidence import compose as C  # noqa: E402
from app.services.qc_evidence import measure as M  # noqa: E402
from app.services.qc_evidence import sources as src  # noqa: E402

st = json.loads(
    (EVID.parent / "MF-DEMO-E2E-R4" / "raw" / "state.json").read_text(encoding="utf-8")
)
pid, vid = st["project_id"], st["video_id"]
WS = str(DEFAULT_WORKSPACE_ID)
DB = MFR4 / "data" / "motionforge.db"
out: dict = {"project_id": pid, "video_id": vid, "at": "probe5"}


def _sz(v: object) -> int:
    return len(json.dumps(v, separators=(",", ":")).encode("utf-8"))


factory = create_session_factory(create_engine_for_path(DB))
with factory() as s:
    scope = src.load_scope(s, workspace_id=WS, project_id=pid, video_item_id=vid)
    ctx = C._Context(session=s, managed_root=MFR4 / "artifacts", scope=scope)

    # ── A) identity_drift size anatomy ────────────────────────────────────
    old_ok, old_206 = C.ARGV_CEILING_SPAWN_OK_BYTES, C.ARGV_CEILING_WINERROR_206_BYTES
    C.ARGV_CEILING_SPAWN_OK_BYTES = 10**9
    C.ARGV_CEILING_WINERROR_206_BYTES = 10**9
    try:
        args = C._identity_drift(ctx)
    finally:
        C.ARGV_CEILING_SPAWN_OK_BYTES, C.ARGV_CEILING_WINERROR_206_BYTES = old_ok, old_206
    breakdown = {str(k): _sz(v) for k, v in args.items()}
    frames = args.get("frames") or []
    frame_anatomy = []
    for row in frames:
        crop = row.get("crop") or {}
        px = crop.get("pixels") or []
        values = [v for r in px for v in r]
        frame_anatomy.append(
            {
                "frame_index": row.get("frame_index"),
                "crop_w": crop.get("width"),
                "crop_h": crop.get("height"),
                "pixel_count": len(values),
                "crop_bytes": _sz(crop),
                "row_bytes_smallest": min(
                    (_sz([v]) for v in values), default=None
                ),
                "all_float": all(isinstance(v, float) for v in values),
                "all_integral": all(float(v).is_integer() for v in values),
                "pixel_bytes_total": sum(len(json.dumps(v)) + 1 for v in values),
            }
        )
    ref = args.get("pinned_reference") or {}
    ref_crop = ref.get("crop") or {}
    ref_values = [v for r in (ref_crop.get("pixels") or []) for v in r]
    measurements = args.get("identity_measurements") or []
    out["identity"] = {
        "total_bytes": _sz(args),
        "per_key_bytes": breakdown,
        "frames_anatomy": frame_anatomy,
        "frame_count": len(frames),
        "reference_crop": {
            "w": ref_crop.get("width"),
            "h": ref_crop.get("height"),
            "pixel_count": len(ref_values),
            "crop_bytes": _sz(ref_crop),
            "all_integral": all(float(v).is_integer() for v in ref_values),
        },
        "measurement_rows": len(measurements),
        "measurement_keys": sorted(measurements[0]) if measurements else [],
    }

    # ── B) cut_drift: default vs both-truncations-raised ─────────────────
    def _cut_probe(label: str, wide: bool) -> dict:
        old_c, old_m, old_ctx = C.MAX_WINDOW_FRAMES, M.MAX_WINDOW_FRAMES, ctx.max_frames
        if wide:
            C.MAX_WINDOW_FRAMES = 4096
            M.MAX_WINDOW_FRAMES = 4096
            ctx.max_frames = 4096
        try:
            try:
                res = C._cut_drift(ctx)
                cuts = res.get("cut_observations") or []
                return {
                    "ok": True,
                    "observed_frames": [c.get("observed_frame") for c in cuts],
                    "render_cuts_ms": res.get("render_cuts_ms"),
                    "planned_cuts_ms": res.get("planned_cuts_ms"),
                    "reasons": [c.get("reason") for c in cuts],
                    "search_spans": {
                        str(c.get("boundary_frame")): c.get("search_span")
                        for c in cuts
                    },
                    "peak": [
                        {
                            "boundary": c.get("boundary_frame"),
                            "peak_frame": c.get("peak_frame"),
                            "delta": c.get("delta"),
                            "runner_up_delta": c.get("runner_up_delta"),
                            "neighbour_max_delta": c.get("neighbour_max_delta"),
                            "measured_frames": c.get("measured_frames"),
                        }
                        for c in cuts
                    ],
                }
            except Exception as exc:  # noqa: BLE001
                details = dict(getattr(exc, "details", {}) or {})
                return {
                    "ok": False,
                    "code": str(getattr(exc, "code", "")),
                    "message": str(exc)[:300],
                    "reason": details.get("reason"),
                    "search_span": details.get("search_span"),
                    "decoded_frames": details.get("decoded_frames"),
                    "measured": {
                        "measured_frames": (details.get("measured") or {}).get(
                            "measured_frames"
                        ),
                        "deltas": (details.get("measured") or {}).get("deltas"),
                    },
                }
        finally:
            C.MAX_WINDOW_FRAMES, M.MAX_WINDOW_FRAMES, ctx.max_frames = (
                old_c,
                old_m,
                old_ctx,
            )

    out["cut_default"] = _cut_probe("default", wide=False)
    out["cut_wide_both_fixed"] = _cut_probe("wide", wide=True)

out["constants"] = {
    "compose_MAX_WINDOW_FRAMES": C.MAX_WINDOW_FRAMES,
    "measure_MAX_WINDOW_FRAMES": M.MAX_WINDOW_FRAMES,
    "argv_ceiling_spawn_ok": old_ok,
    "argv_ceiling_winerror206": old_206,
}
(EVID / "raw" / "probe5_identity_cut_anatomy.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8"
)
print(json.dumps(out["identity"]["per_key_bytes"], indent=0))
print("TOTAL", out["identity"]["total_bytes"])
print("FRAMES", json.dumps(out["identity"]["frames_anatomy"], indent=0)[:1200])
print("REF", json.dumps(out["identity"]["reference_crop"]))
print("CUT_DEFAULT", json.dumps(out["cut_default"])[:900])
print("CUT_WIDE", json.dumps(out["cut_wide_both_fixed"])[:1500])
