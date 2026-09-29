"""DELTA-F6 probe #7 (READ-ONLY): prototype the identity_drift transport
compaction on the REAL R4 args and MEASURE raw + escaped sizes.

The functions below mirror the intended compose.py change 1:1 so the measured
sizes are the projected post-fix sizes (not estimates).
"""
from __future__ import annotations

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

st = json.loads(
    (EVID.parent / "MF-DEMO-E2E-R4" / "raw" / "state.json").read_text(encoding="utf-8")
)
pid, vid = st["project_id"], st["video_id"]


def _raw(v: object) -> int:
    return len(json.dumps(v, separators=(",", ":")))


def _esc(v: object) -> int:
    return len(subprocess.list2cmdline([json.dumps(v, separators=(",", ":"))]))


# ── the candidate transport ─────────────────────────────────────────────────
def _tp(matrix):
    """Integral pixels in their exact integral JSON form."""
    out = []
    for row in matrix:
        out.append([int(v) if float(v).is_integer() else v for v in row])
    return out


def _tp_crop(crop):
    return {"pixels": _tp(crop["pixels"]), "width": crop["width"], "height": crop["height"]}


def transport(args: dict) -> dict:
    out = dict(args)
    # 1) raw pixel payloads: exact integral form (hashes recomputed on it)
    ref = dict(out["pinned_reference"])
    ref_crop = _tp_crop(ref["crop"])
    ref["crop"] = ref_crop
    ref["sha256"] = M.crop_sha256(ref_crop["pixels"])
    ref["crop_revision"] = M.crop_revision(ref_crop["pixels"])
    out["pinned_reference"] = ref
    frames = []
    for row in out["frames"]:
        frames.append({**row, "crop": _tp_crop(row["crop"]),
                       "sha256": M.crop_sha256(_tp_crop(row["crop"])["pixels"])})
    out["frames"] = frames
    # 2) per-role measurement rows: one place per fact
    slim = []
    for row in out["identity_measurements"]:
        slim.append(
            {
                "object_role_id": row["object_role_id"],
                "reference_artifact_id": row["reference_artifact_id"],
                "reference_pose_slot": row["reference_pose_slot"],
                "frames_measured": list(row["frames_measured"]),
                "rendered_frames": [
                    {
                        "frame_index": f["frame_index"],
                        "sha256": f["sha256"],
                        "distance_to_own_reference_px": f["distance_to_own_reference_px"],
                    }
                    for f in row["rendered_frames"]
                ],
                "reference_distance_max_px": row["reference_distance_max_px"],
                "max_adjacent_distance_px": row["max_adjacent_distance_px"],
                "measured_distance_px": row["measured_distance_px"],
                "verdict": row["verdict"],
            }
        )
    out["identity_measurements"] = slim
    # 3) cast_pin: keep every asserted field; frame lists become indices
    pin = dict(out["cast_pin"])
    pin["cast_coverage"] = [
        {
            "object_role_id": row["object_role_id"],
            "character_id": row["character_id"],
            "pack_version_id": row["pack_version_id"],
            "pose_slot": row["pose_slot"],
            "reference_asset_id": row["reference_asset_id"],
            "reference_slot_mapping": row["reference_slot_mapping"],
            "reference_artifact": row["reference_artifact"],
            "segment_row_ids": row["segment_row_ids"],
            "compatibility": row["compatibility"],
        }
        for row in pin["cast_coverage"]
    ]
    pin["role_observations"] = [
        {
            "object_role_id": row["object_role_id"],
            "reference_artifact_id": row["reference_artifact_id"],
            "reference_pose_slot": row["reference_pose_slot"],
            "rendered_frames": [f["frame_index"] for f in row["rendered_frames"]],
            "measured_distance_px": row["measured_distance_px"],
            "verdict": row["verdict"],
            "full_measurement_at": row["full_measurement_at"],
        }
        for row in pin["role_observations"]
    ]
    out["cast_pin"] = pin
    # 4) pin_coverage: per-role pins already live in cast_pin.cast_coverage
    pc = dict(out["pin_coverage"])
    pc["cast_coverage_digest"] = M.content_digest(pc.pop("cast_coverage"))
    pc["full_record_at"] = "cast_pin.cast_coverage"
    out["pin_coverage"] = pc
    # 5) render_observation producer_facts: digest the per-chunk detail
    obs_out = dict(out["render_observation"])
    facts = dict(obs_out.get("producer_facts") or {})
    fm = dict(facts.get("frame_metadata") or {})
    chunks = fm.pop("per_chunk_evidence", None)
    if chunks is not None:
        fm["per_chunk_evidence_count"] = len(chunks)
        fm["per_chunk_evidence_digest"] = M.content_digest(chunks)
    facts["frame_metadata"] = fm
    obs_out["producer_facts"] = facts
    out["render_observation"] = obs_out
    # 6) provenance: the render role facts are the observation's own facts
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


factory = create_session_factory(create_engine_for_path(MFR4 / "data" / "motionforge.db"))
with factory() as s:
    scope = src.load_scope(
        s, workspace_id=str(DEFAULT_WORKSPACE_ID), project_id=pid, video_item_id=vid
    )
    ctx = C._Context(session=s, managed_root=MFR4 / "artifacts", scope=scope)
    old_ok = C.ARGV_CEILING_SPAWN_OK_BYTES
    C.ARGV_CEILING_SPAWN_OK_BYTES = 10**9
    try:
        args = C._identity_drift(ctx)
    finally:
        C.ARGV_CEILING_SPAWN_OK_BYTES = old_ok

t = transport(args)
before = {k: _raw(v) for k, v in sorted(args.items(), key=lambda kv: -_raw(kv[1]))}
after = {k: _raw(v) for k, v in sorted(t.items(), key=lambda kv: -_raw(kv[1]))}

# pixel-level consistency proof: detector-side hash verification on the
# transported form (mirrors app.services.qc_checks.identity_drift._crop_sha256)
import hashlib  # noqa: E402


def det_sha(crop):
    return hashlib.sha256(
        json.dumps(crop["pixels"], separators=(",", ":")).encode()
    ).hexdigest()


verified = det_sha(t["pinned_reference"]["crop"]) == t["pinned_reference"]["sha256"]
v_frames = all(det_sha(f["crop"]) == f["sha256"] for f in t["frames"])

report = {
    "before_raw": _raw(args),
    "after_raw": _raw(t),
    "before_escaped": _esc(args),
    "after_escaped": _esc(t),
    "delta": _raw(args) - _raw(t),
    "per_key_before": before,
    "per_key_after": after,
    "detector_hash_verifies_reference": verified,
    "detector_hash_verifies_frames": v_frames,
    "authority_preserved": {
        "frames": len(t["frames"]),
        "role_measurements": len(t["identity_measurements"]),
        "roles": len(t["cast_pin"]["cast_coverage"]),
        "role_observations": len(t["cast_pin"]["role_observations"]),
        "pin_coverage_count": t["pin_coverage"]["count"],
        "measured_coverage_count": t["measured_coverage"]["count"],
    },
}
(EVID / "raw" / "probe7_transport_prototype.json").write_text(
    json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8"
)
print(json.dumps(report["authority_preserved"]))
print("RAW", report["before_raw"], "->", report["after_raw"], " ESCAPED",
      report["before_escaped"], "->", report["after_escaped"])
print("HASH_OK", verified, v_frames)
for k in after:
    print(f"{after[k]:7d}  {k}   (was {before.get(k)})")
