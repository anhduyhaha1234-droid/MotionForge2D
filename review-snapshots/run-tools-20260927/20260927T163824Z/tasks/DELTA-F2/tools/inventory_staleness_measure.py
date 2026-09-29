"""DELTA-F2 — measure WHY test_mf_end_28::test_28_2_builder_is_deterministic is red.

Hypothesis to test (not to assume): the row fails only because this fix changes
``app/adapters/media_engine/comfy.py``, which changes the generated
``backend.app_tree_sha256`` recorded in the COMMITTED
``packaging/demo/inventory.json`` — i.e. an expected generated-artifact
staleness that the integration owner clears by re-running the builder on the
union tree, not a defect of this patch.

Measures, in one run:
  1. fresh build on the PATCHED tree vs the committed inventory: every differing
     field path (excluding the two self-referential fields the test excludes);
  2. fresh build with the BASE bytes of comfy.py substituted (verified restore in
     ``finally``): ``backend.app_tree_sha256`` must equal the COMMITTED value —
     proving the committed artifact is exactly fresh for the base tree and that
     this patch is the sole cause of the delta.

Writes raw/inventory_staleness.json.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F2")
EV = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    r"20260927T163824Z/tasks/DELTA-F2"
)
BUILDER = WT / "packaging" / "demo" / "build_demo_package_inventory.py"
INVENTORY = WT / "packaging" / "demo" / "inventory.json"
COMFY = WT / "app" / "adapters" / "media_engine" / "comfy.py"
BASE_COMMIT = "951543664ed10e0dfaaff1f50f937b9624386074"
STAMP = "2026-09-29T00:00:00+00:00"
SELF_REFERENTIAL = ("generated_at_utc", "source_head")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(out_dir: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(BUILDER), "--out-dir", str(out_dir), "--generated-at", STAMP],
        cwd=str(WT), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"builder rc={proc.returncode}: {proc.stderr[-1500:]}")
    return json.loads((out_dir / "inventory.json").read_text(encoding="utf-8"))


def strip(payload: dict) -> dict:
    out = dict(payload)
    for key in SELF_REFERENTIAL:
        out.pop(key, None)
    return out


def flatten(prefix: str, value: object, out: dict) -> None:
    if isinstance(value, dict):
        for key in sorted(value):
            flatten(f"{prefix}.{key}" if prefix else str(key), value[key], out)
    elif isinstance(value, list):
        out[prefix] = json.dumps(value, sort_keys=True)
    else:
        out[prefix] = value


def main() -> int:
    committed_raw = INVENTORY.read_text(encoding="utf-8")
    committed = json.loads(committed_raw)
    patched_bytes = COMFY.read_bytes()
    patched_sha = sha(patched_bytes)
    result: dict = {
        "committed_inventory": {"path": str(INVENTORY), "sha256": sha(committed_raw.encode()),
                                "source_head": committed.get("source_head"),
                                "app_tree_sha256": committed["backend"]["app_tree_sha256"]},
        "patched_comfy_sha256": patched_sha,
    }
    tmp = Path(tempfile.mkdtemp(prefix="deltaf2_inv_", dir=r"C:/Users/Admin/AppData/Local/Temp"))
    try:
        fresh_patched = build(tmp / "patched")
        result["fresh_patched_app_tree_sha256"] = fresh_patched["backend"]["app_tree_sha256"]
        flat_c, flat_f = {}, {}
        flatten("", strip(committed), flat_c)
        flatten("", strip(fresh_patched), flat_f)
        diff = sorted(k for k in set(flat_c) | set(flat_f)
                      if flat_c.get(k) != flat_f.get(k))
        result["patched_vs_committed_differing_fields"] = {
            k: {"committed": flat_c.get(k), "fresh": flat_f.get(k)} for k in diff}

        base_bytes = subprocess.run(
            ["git", "show", f"{BASE_COMMIT}:app/adapters/media_engine/comfy.py"],
            cwd=str(WT), capture_output=True, check=True).stdout
        try:
            COMFY.write_bytes(base_bytes)
            fresh_base = build(tmp / "base")
        finally:
            COMFY.write_bytes(patched_bytes)
        restored = COMFY.read_bytes()
        result["restore_verified"] = sha(restored) == patched_sha
        result["fresh_base_app_tree_sha256"] = fresh_base["backend"]["app_tree_sha256"]
        result["base_build_matches_committed"] = (
            fresh_base["backend"]["app_tree_sha256"]
            == committed["backend"]["app_tree_sha256"])
        result["patched_build_equals_test_message_hash"] = (
            fresh_patched["backend"]["app_tree_sha256"] == "21b5e983df7ce28ab10ac248121f03e068a4e37bdf9df31857c4c32d1776f63d")
        result["determinism_patched_two_runs_identical"] = (
            build(tmp / "patched2")["backend"]["app_tree_sha256"]
            == fresh_patched["backend"]["app_tree_sha256"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert result["restore_verified"], "RESTORE FAILED — comfy.py not byte-identical"
    (EV / "raw").mkdir(parents=True, exist_ok=True)
    (EV / "raw" / "inventory_staleness.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
