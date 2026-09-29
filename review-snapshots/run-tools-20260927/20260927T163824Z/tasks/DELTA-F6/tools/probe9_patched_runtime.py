"""DELTA-F6 probe #9 (READ-ONLY w.r.t. the tree): run the PATCHED composer on
the live R4 runtime and measure both fixes end to end.

* F-R4-1: `_cut_drift` must now observe the REAL cuts [0, 120, 240].
* F-R4-2: `_identity_drift` must walk its measured transport ladder, report the
  level + escaped bytes, persist the full set, and the REAL child must spawn
  through runner.run_detector and reproduce the in-process measurement.
Writes only the transport evidence file under the R4 runtime managed root
(what the app itself writes at composition time).
"""
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
from app.services.qc_evidence import sources as src  # noqa: E402
from app.services.qc_checks import identity_drift as det  # noqa: E402
from app.services.qc_checks import runner as qcr  # noqa: E402

st = json.loads(
    (EVID.parent / "MF-DEMO-E2E-R4" / "raw" / "state.json").read_text(encoding="utf-8")
)
pid, vid = st["project_id"], st["video_id"]


def _esc(v: object) -> int:
    return len(subprocess.list2cmdline([json.dumps(v, separators=(",", ":"))]))


out: dict = {"at": "probe9", "video_id": vid}
factory = create_session_factory(create_engine_for_path(MFR4 / "data" / "motionforge.db"))
with factory() as s:
    scope = src.load_scope(
        s, workspace_id=str(DEFAULT_WORKSPACE_ID), project_id=pid, video_item_id=vid
    )
    ctx = C._Context(session=s, managed_root=MFR4 / "artifacts", scope=scope)

    # ── F-R4-1 ────────────────────────────────────────────────────────────
    try:
        cuts = C._cut_drift(ctx)
        out["cut_drift"] = {
            "ok": True,
            "observed_frames": [c.get("observed_frame") for c in cuts["cut_observations"]],
            "render_cuts_ms": cuts["render_cuts_ms"],
            "planned_cuts_ms": cuts["planned_cuts_ms"],
            "reasons": [c.get("reason") for c in cuts["cut_observations"]],
            "peaks": [
                {
                    "boundary": c.get("boundary_frame"),
                    "peak_frame": c.get("peak_frame"),
                    "delta": c.get("delta"),
                    "neighbour_max_delta": c.get("neighbour_max_delta"),
                    "search_span": c.get("search_span"),
                }
                for c in cuts["cut_observations"]
            ],
        }
    except Exception as exc:  # noqa: BLE001
        out["cut_drift"] = {
            "ok": False,
            "code": str(getattr(exc, "code", "")),
            "message": str(exc)[:300],
        }

    # ── F-R4-2 ────────────────────────────────────────────────────────────
    try:
        args = C._identity_drift(ctx)
        budget = args.get("payload_budget") or {}
        out["identity"] = {
            "ok": True,
            "escaped_bytes": _esc(args),
            "transport_level": budget.get("transport_level"),
            "reductions": budget.get("reductions"),
            "levels_tried": budget.get("levels_tried"),
            "within_limit": budget.get("within_limit"),
            "full_evidence_file": budget.get("full_evidence_file"),
        }
        inproc = det.detect(args)
        out["identity"]["in_process"] = {
            "status": inproc["status"],
            "measured_distance": inproc["measured_distance"],
            "items": len(inproc["items"]),
        }
        try:
            run = qcr.run_detector(
                "identity_drift", args=args, deadline_sec=120.0,
                capture_cap_bytes=4_000_000,
            )
            out["identity"]["child"] = {
                "status": run.status, "code": run.code,
                "run_sec": round(run.run_sec, 3),
                "measured_distance": run.output.get("measured_distance"),
                "matches_in_process": (
                    run.output.get("measured_distance") == inproc["measured_distance"]
                ),
            }
        except Exception as exc:  # noqa: BLE001
            out["identity"]["child"] = {
                "error_type": type(exc).__name__, "error": str(exc)[:200]
            }
        # the persisted full-evidence file is the digest-bound reference
        record = budget.get("full_evidence_file")
        if record:
            path = MFR4 / "artifacts" / record["relative_path"]
            data = path.read_bytes()
            out["identity"]["file_sha_matches"] = (
                hashlib.sha256(data).hexdigest() == record["sha256"]
                and len(data) == record["size_bytes"]
            )
    except Exception as exc:  # noqa: BLE001
        out["identity"] = {
            "ok": False,
            "code": str(getattr(exc, "code", "")),
            "message": str(exc)[:300],
        }

(EVID / "raw" / "probe9_patched_runtime.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8"
)
print(json.dumps(out, indent=1)[:2600])
