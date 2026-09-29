"""DELTA-F4 recon probe — measure the REAL id spaces before touching anything.

Runs the EXISTING F1 test infrastructure on the current tree and reports:
plan members, render_authority mapping (layer_id/role_id), the persisted v2
authority role_mappings, and the REAL route pins (`_resolve_canonical_render_pins`)
with managed_root = the seeded artifacts root.  Read-only wrt source.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F4")
sys.path.insert(0, str(WT / "tests" / "product_delivery"))
sys.path.insert(0, str(WT))

import test_delta_f1 as t  # noqa: E402

from app.api.routes import s10_full_apply as routes  # noqa: E402
from app.services.s09_approval import S09ApprovalRepository  # noqa: E402


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="f4-probe-measure-"))
    factory, seed, artifacts, scene_pk = t._seed_world(tmp)
    run_id, plan = t._submit(factory, seed, scene_pk)
    out: dict = {"run_id": run_id, "tmp": str(tmp)}
    out["plan_members"] = {
        c["chunk_id"]: list(c.get("member_layer_ids") or []) for c in plan["chunks"]
    }
    ra = plan.get("render_authority") or {}
    out["render_authority_keys"] = sorted(ra.keys())
    out["render_authority_mapping"] = ra.get("mapping")
    with factory() as s:
        v2 = S09ApprovalRepository(s).full_apply_authority(
            seed["checkpoint_id"], seed["workspace_id"]
        )
    out["v2_keys"] = sorted(v2.keys())
    out["v2_source"] = v2.get("source")
    rms = v2.get("role_mappings") or []
    out["v2_role_mappings"] = rms
    with factory() as s:
        pins = routes._resolve_canonical_render_pins(
            s,
            workspace_id=seed["workspace_id"],
            project_id=seed["project_id"],
            video_item_id=seed["video_item_id"],
            apply_checkpoint_id=seed["checkpoint_id"],
            authority=v2,
            managed_root=artifacts,
        )
    out["pins"] = pins
    out["pins_replacement_keys"] = sorted((pins.get("replacement_assets") or {}).keys())
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
