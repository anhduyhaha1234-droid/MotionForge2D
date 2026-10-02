"""DELTA-F6 probe #10 (READ-ONLY): level-by-level trace of the transport
ladder on the real R4 identity set (full set via a patched fit predicate)."""
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
from app.services.qc_evidence import sources as src  # noqa: E402

st = json.loads(
    (EVID.parent / "MF-DEMO-E2E-R4" / "raw" / "state.json").read_text(encoding="utf-8")
)


def _esc(v: object) -> int:
    return len(subprocess.list2cmdline([json.dumps(v, separators=(",", ":"))]))


def _keys(args: dict) -> dict:
    return {k: len(json.dumps(v, separators=(",", ":"))) for k, v in args.items()}


factory = create_session_factory(create_engine_for_path(MFR4 / "data" / "motionforge.db"))
with factory() as s:
    scope = src.load_scope(
        s,
        workspace_id=str(DEFAULT_WORKSPACE_ID),
        project_id=st["project_id"],
        video_item_id=st["video_id"],
    )
    ctx = C._Context(session=s, managed_root=MFR4 / "artifacts", scope=scope)
    real_fits = C._identity_transport_fits
    C._identity_transport_fits = lambda _a: True  # take the FULL pre-transport set
    try:
        args = C._identity_drift(ctx)
    finally:
        C._identity_transport_fits = real_fits

trace = [{"level": "L0", "escaped": _esc(args), "keys": _keys(args)}]
for name, reducer in C._IDENTITY_TRANSPORT_LEVELS:
    applied = reducer(args)
    trace.append({"level": name, "escaped": _esc(args), "applied": applied,
                  "keys": _keys(args)})
report = {
    "target_escaped_max": C.ARGV_CEILING_SPAWN_OK_BYTES
    - C.ARGV_RUNNER_COMMANDLINE_OVERHEAD_BYTES
    - C.ARGV_OUTPUT_BINDING_RESERVE_BYTES,
    "ladder": [{k: v for k, v in step.items() if k != "keys"} for step in trace],
    "final_keys": trace[-1]["keys"],
}
(EVID / "raw" / "probe10_ladder_trace.json").write_text(
    json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8"
)
print("TARGET_ESCAPED_MAX", report["target_escaped_max"])
for step in trace:
    print(f"{step['level']}: escaped={step['escaped']}  applied={step.get('applied')}")
print("FINAL KEYS", json.dumps(trace[-1]["keys"]))
