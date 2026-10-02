"""DELTA-F6 probe #6 (READ-ONLY): structure/size anatomy of the non-pixel
blocks of the real R4 identity_drift composed args, so the transport
compaction can be designed against MEASURED numbers (not guesses)."""
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
from app.services.qc_evidence import sources as src  # noqa: E402

st = json.loads(
    (EVID.parent / "MF-DEMO-E2E-R4" / "raw" / "state.json").read_text(encoding="utf-8")
)
pid, vid = st["project_id"], st["video_id"]


def _sz(v: object) -> int:
    return len(json.dumps(v, separators=(",", ":")).encode("utf-8"))


def _anatomy(node, prefix: str, out: dict, depth: int = 0) -> None:
    if depth > 3:
        out[prefix + "/…"] = _sz(node)
        return
    if isinstance(node, dict):
        for k in sorted(node):
            _anatomy(node[k], f"{prefix}/{k}", out, depth + 1)
    elif isinstance(node, list):
        out[f"{prefix}[n={len(node)}]"] = _sz(node)
        if node:
            _anatomy(node[0], f"{prefix}[0]", out, depth + 1)
    else:
        out[prefix] = _sz(node)


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

out: dict = {}
for key in (
    "identity_measurements",
    "cast_pin",
    "render_observation",
    "evidence_provenance",
    "pin_coverage",
    "measured_coverage",
):
    _anatomy(args[key], key, out)
plan = {
    "identity_row_0": {k: _sz(v) for k, v in (args["identity_measurements"][0]).items()},
    "cast_coverage_row_0": {
        k: _sz(v) for k, v in (args["cast_pin"]["cast_coverage"][0]).items()
    },
    "role_obs_row_0": {
        k: _sz(v) for k, v in (args["cast_pin"]["role_observations"][0]).items()
    },
    "pin_row_0": {k: _sz(v) for k, v in (args["pin_coverage"]["cast_coverage"][0]).items()},
    "verdict_row0": _sz(args["identity_measurements"][0]["verdict"]),
    "verdict_row0_status": args["identity_measurements"][0]["verdict"].get("status"),
}
(EVID / "raw" / "probe6_anatomy.json").write_text(
    json.dumps({"anatomy": out, "rows": plan}, indent=1, ensure_ascii=False),
    encoding="utf-8",
)
for k, v in sorted(out.items(), key=lambda kv: -kv[1])[:60]:
    print(f"{v:7d}  {k}")
print("__ROWS__")
for name, rows in plan.items():
    print(name, json.dumps(rows))
