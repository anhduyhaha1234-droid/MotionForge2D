"""DELTA-F6 probe #8 (READ-ONLY): measure the AGGRESSIVE identity_drift
transport projection against the real R4 args + verify the transported form
still satisfies the frozen detector's integrity checks and spawns."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
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


def _raw(v: object) -> int:
    return len(json.dumps(v, separators=(",", ":")))


def _esc(v: object) -> int:
    return len(subprocess.list2cmdline([json.dumps(v, separators=(",", ":"))]))


def _tp(matrix):
    return [[int(v) if float(v).is_integer() else v for v in row] for row in matrix]


def _tp_crop(crop):
    px = _tp(crop["pixels"])
    return {"pixels": px, "width": crop["width"], "height": crop["height"]}


def project(args: dict) -> dict:
    out = dict(args)
    # (1) pixels: exact integral form
    ref = dict(out["pinned_reference"])
    rc = _tp_crop(ref["crop"])
    ref["crop"] = rc
    ref["sha256"] = M.crop_sha256(rc["pixels"])
    ref["crop_revision"] = M.crop_revision(rc["pixels"])
    out["pinned_reference"] = ref
    out["frames"] = [
        {**row, "crop": _tp_crop(row["crop"]), "sha256": M.crop_sha256(_tp_crop(row["crop"])["pixels"])}
        for row in out["frames"]
    ]
    # (2) slim shared identity metadata (per-frame + expected_metadata)
    cast = dict(out["cast_pin"])
    meta = dict(cast.get("expected_metadata") or {})
    meta.pop("reference_sha256", None)
    meta.pop("reference_slot_source", None)
    cast["expected_metadata"] = meta
    out["frames"] = [{**row, "metadata": dict(meta)} for row in out["frames"]]
    # (3) per-role measurements: measured facts only
    out["identity_measurements"] = [
        {
            "object_role_id": row["object_role_id"],
            "rendered_frames": [
                {
                    "frame_index": f["frame_index"],
                    "sha256": f["sha256"],
                    "distance_to_own_reference_px": f["distance_to_own_reference_px"],
                }
                for f in row["rendered_frames"]
            ],
            "frames_measured": list(row["frames_measured"]),
            "reference_distance_max_px": row["reference_distance_max_px"],
            "max_adjacent_distance_px": row["max_adjacent_distance_px"],
            "measured_distance_px": row["measured_distance_px"],
            "verdict": row["verdict"],
        }
        for row in out["identity_measurements"]
    ]
    # (4) cast_pin: one place per fact
    cast["cast_coverage"] = [
        {
            "object_role_id": row["object_role_id"],
            "character_id": row["character_id"],
            "pack_version_id": row["pack_version_id"],
            "pose_slot": row["pose_slot"],
            "reference_artifact": {
                k: row["reference_artifact"][k]
                for k in ("artifact_id", "sha256", "bytes_reverified")
                if k in row["reference_artifact"]
            },
            "segment_row_ids": row["segment_row_ids"],
            "compatible": row["compatible"],
            "compatibility_reasons": row["compatibility_reasons"],
        }
        for row in cast["cast_coverage"]
    ]
    cast["role_observations"] = [
        {
            "object_role_id": row["object_role_id"],
            "rendered_frames": [f["frame_index"] for f in row["rendered_frames"]],
            "measured_distance_px": row["measured_distance_px"],
            "verdict": {
                k: row["verdict"].get(k) for k in ("status", "code", "value", "unit")
            }
            if isinstance(row["verdict"], dict)
            else row["verdict"],
        }
        for row in cast["role_observations"]
    ]
    for long_key in ("cast_contract_scope", "coverage_scope_meaning", "primary_role_rule",
                     "measurement_note"):
        if long_key in cast and isinstance(cast[long_key], str):
            cast[long_key] = cast[long_key][:64]
    out["cast_pin"] = cast
    # (5) pin_coverage: rows live in cast_pin.cast_coverage
    pc = dict(out["pin_coverage"])
    pc["cast_coverage_digest"] = M.content_digest(pc.pop("cast_coverage", []))
    pc["full_record_at"] = "cast_pin.cast_coverage"
    out["pin_coverage"] = pc
    # (6) measured_coverage: compact per-role summary
    mc = dict(out["measured_coverage"])
    mc["per_role"] = {
        role: {
            "measured_distance_px": row["measured_distance_px"],
            "verdict": {
                k: (row["verdict"] or {}).get(k) for k in ("status", "code", "value", "unit")
            }
            if isinstance(row["verdict"], dict)
            else row["verdict"],
            "reference_artifact_id": row["reference_artifact_id"],
            "reference_pose_slot": row["reference_pose_slot"],
            "frames_measured": list(row["frames_measured"]),
        }
        for role, row in mc["per_role"].items()
    }
    out["measured_coverage"] = mc
    # (7) render observation: one copy of the render facts (digest for detail)
    obs = dict(out["render_observation"])
    facts = dict(obs.get("producer_facts") or {})
    fm = dict(facts.get("frame_metadata") or {})
    chunks = fm.pop("per_chunk_evidence", None)
    if chunks is not None:
        fm["per_chunk_evidence_count"] = len(chunks)
        fm["per_chunk_evidence_digest"] = M.content_digest(chunks)
    facts["frame_metadata"] = fm
    obs["producer_facts"] = facts
    out["render_observation"] = obs
    # (8) provenance: no second copy of the render role facts
    prov = dict(out["evidence_provenance"])
    fam = dict(prov.get("families") or {})
    art = dict(fam.get("artifact") or {})
    if "render_role_facts" in art:
        art["render_role_facts"] = {
            "digest": M.content_digest(art["render_role_facts"]),
            "same_facts_at": "render_observation.producer_facts",
        }
    fam["artifact"] = art
    prov["families"] = fam
    out["evidence_provenance"] = prov
    return out


st = json.loads(
    (EVID.parent / "MF-DEMO-E2E-R4" / "raw" / "state.json").read_text(encoding="utf-8")
)
pid, vid = st["project_id"], st["video_id"]
factory = create_session_factory(create_engine_for_path(MFR4 / "data" / "motionforge.db"))
with factory() as s:
    scope = src.load_scope(
        s, workspace_id=str(DEFAULT_WORKSPACE_ID), project_id=pid, video_item_id=vid
    )
    ctx = C._Context(session=s, managed_root=MFR4 / "artifacts", scope=scope)
    old_ok, old_206 = C.ARGV_CEILING_SPAWN_OK_BYTES, C.ARGV_CEILING_WINERROR_206_BYTES
    C.ARGV_CEILING_SPAWN_OK_BYTES = 10**9
    C.ARGV_CEILING_WINERROR_206_BYTES = 10**9
    try:
        args = C._identity_drift(ctx)
    finally:
        C.ARGV_CEILING_SPAWN_OK_BYTES, C.ARGV_CEILING_WINERROR_206_BYTES = old_ok, old_206

t = project(args)


def det_sha(crop):
    return hashlib.sha256(
        json.dumps(crop["pixels"], separators=(",", ":")).encode()
    ).hexdigest()


# the frozen detector's own integrity gate on the projected bytes
sys.path.insert(0, str(WT))
from app.services.qc_checks import identity_drift as det  # noqa: E402

out_det = det.detect(t)
print("SIZES before", _raw(args), _esc(args), "after", _raw(t), _esc(t))
# spawn the REAL child through the runner with the projected payload
from app.services.qc_checks import runner as qcr  # noqa: E402

try:
    run = qcr.run_detector(
        "identity_drift", args=t, deadline_sec=120.0, capture_cap_bytes=4_000_000
    )
    child = {"status": run.status, "code": run.code, "run_sec": round(run.run_sec, 3),
             "stderr_tail": run.stderr_tail[-200:],
             "measured_distance": run.output.get("measured_distance")}
except Exception as exc:  # noqa: BLE001
    child = {"error_type": type(exc).__name__, "error": str(exc)[:200]}
report = {
    "before_raw": _raw(args), "before_escaped": _esc(args),
    "after_raw": _raw(t), "after_escaped": _esc(t),
    "after_escaped_plus_runner_overhead": _esc(t) + 2000,
    "per_key_after": {k: _raw(v) for k, v in sorted(t.items(), key=lambda kv: -_raw(kv[1]))},
    "hash_ok": det_sha(t["pinned_reference"]["crop"]) == t["pinned_reference"]["sha256"]
    and all(det_sha(f["crop"]) == f["sha256"] for f in t["frames"]),
    "in_process_detect": {
        "status": out_det["status"], "code": out_det["code"],
        "measured_distance": out_det["measured_distance"],
        "identity_flip": out_det["identity_flip"], "items": len(out_det["items"]),
    },
    "child_run": child,
    "child_matches_in_process": (
        child.get("measured_distance") == out_det["measured_distance"]
    ),
    "primary_role_row_distance": t["identity_measurements"][0]["measured_distance_px"],
}
(EVID / "raw" / "probe8_aggressive_projection.json").write_text(
    json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8"
)
print(json.dumps({k: report[k] for k in (
    "before_raw", "after_raw", "before_escaped", "after_escaped",
    "after_escaped_plus_runner_overhead", "hash_ok", "in_process_detect",
    "child_run", "child_matches_in_process", "primary_role_row_distance")}, indent=1))
print(json.dumps(report["per_key_after"]))
