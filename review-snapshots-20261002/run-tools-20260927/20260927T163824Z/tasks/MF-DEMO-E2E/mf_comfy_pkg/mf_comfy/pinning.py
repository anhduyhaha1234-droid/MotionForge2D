"""Hash pinning: workflow, node inventory, model files.

The adapter refuses to run a workflow whose graph hash, node-inventory hash or
model hashes do not match the pinned values recorded for the engine.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from .errors import ModelPinMismatch, NodeInventoryPinMismatch, WorkflowPinMismatch


def sha256_file(path: str | os.PathLike[str], chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_workflow(graph: dict) -> str:
    """Content hash of a workflow in ComfyUI API format (node id -> node)."""
    return hashlib.sha256(canonical_json(graph).encode("utf-8")).hexdigest()


def load_workflow(path: str | os.PathLike[str]) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def node_inventory(object_info: dict) -> dict:
    """Stable inventory of what the server can actually run.

    Only the fields the adapter depends on: class name, required/optional input
    names, and return types. Cosmetic fields (tooltips, display names, category)
    are excluded so the hash tracks executable capability, not doc churn.
    """
    inv: dict[str, dict] = {}
    for cls, spec in sorted((object_info or {}).items()):
        if not isinstance(spec, dict):
            continue
        inputs = spec.get("input") or {}
        inv[cls] = {
            "required": sorted((inputs.get("required") or {}).keys()),
            "optional": sorted((inputs.get("optional") or {}).keys()),
            "return_types": spec.get("output") or [],
            "output_node": bool(spec.get("output_node")),
            "python_module": spec.get("python_module") or "",
        }
    return inv


def hash_node_inventory(object_info: dict) -> str:
    return hashlib.sha256(canonical_json(node_inventory(object_info)).encode("utf-8")).hexdigest()


def hash_models(paths: dict[str, str]) -> dict[str, str]:
    return {name: sha256_file(p) for name, p in sorted(paths.items())}


def verify_workflow_pin(graph: dict, pinned_sha: str) -> str:
    actual = hash_workflow(graph)
    if pinned_sha and actual != pinned_sha:
        raise WorkflowPinMismatch(
            "workflow graph hash does not match the pinned hash",
            expected=pinned_sha,
            actual=actual,
        )
    return actual


def verify_node_inventory_pin(object_info: dict, pinned_sha: str) -> str:
    actual = hash_node_inventory(object_info)
    if pinned_sha and actual != pinned_sha:
        raise NodeInventoryPinMismatch(
            "server node inventory does not match the pinned hash",
            expected=pinned_sha,
            actual=actual,
        )
    return actual


def verify_model_pins(pins: dict[str, str], actual: dict[str, str]) -> dict[str, str]:
    bad = {}
    for name, expected in (pins or {}).items():
        got = actual.get(name)
        if got != expected:
            bad[name] = {"expected": expected, "actual": got}
    if bad:
        raise ModelPinMismatch("model file hash mismatch", mismatches=bad)
    return actual


def inventory_missing_classes(object_info: dict, classes: Iterable[str]) -> list[str]:
    present = set(object_info or {})
    return sorted(c for c in classes if c not in present)
