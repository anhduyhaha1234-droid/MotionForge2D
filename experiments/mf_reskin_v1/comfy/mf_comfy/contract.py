"""Stage input/output contract objects.

`generated` is distinct from `validated`, `accepted` and `published`: the adapter
may only ever reach `validated`. Acceptance/publication belong to MotionForge.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "mf.comfy.stage.contract/1"

STAGE_STATES = [
    {"state": "submitted", "meaning": "prompt accepted by the server, prompt_id recorded",
     "authority": "adapter"},
    {"state": "queued", "meaning": "prompt proven present in /queue (running or pending)",
     "authority": "adapter"},
    {"state": "generated", "meaning": "server history contains terminal output records",
     "authority": "server history"},
    {"state": "validated", "meaning": "artifacts fetched, hashed, decoded, path-scoped",
     "authority": "adapter"},
    {"state": "failed", "meaning": "typed failure recorded; attempt terminal",
     "authority": "adapter"},
    {"state": "unresolved", "meaning": "outcome not provable (ambiguous after submit / epoch lost); "
                                       "never resolved by resubmitting", "authority": "adapter"},
    {"state": "accepted", "meaning": "NOT the adapter's to set", "authority": "MotionForge"},
    {"state": "published", "meaning": "NOT the adapter's to set", "authority": "MotionForge (S12)"},
]

LIFECYCLE = {
    "happy_path": ["submitted", "queued", "generated", "validated"],
    "ambiguous_path": ["submitted", "unresolved"],
    "failure_path": ["submitted", "failed"],
    "forbidden": ["submitted -> submitted (blind resubmit)", "failed -> accepted (adapter cannot accept)"],
}


@dataclass
class StageInput:
    stage_id: str
    project_id: str = ""
    job_id: str = ""
    attempt_id: str = ""
    shot_id: str = ""
    source_sha256: str = ""
    source_frame_range: list[int] = field(default_factory=list)
    reference_assets: dict[str, str] = field(default_factory=dict)
    workflow_id: str = ""
    workflow_sha256: str = ""
    node_inventory_sha256: str = ""
    model_hashes: dict[str, str] = field(default_factory=dict)
    seed: int | None = None
    params: dict[str, Any] = field(default_factory=dict)
    staging_root: str = ""
    requested_quality: str = "preview"
    cost_ceiling: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StageOutput:
    status: str
    stage_id: str
    prompt_id: str | None = None
    instance_epoch: dict = field(default_factory=dict)
    workflow_id: str = ""
    workflow_sha256: str = ""
    node_inventory_sha256: str = ""
    model_hashes: dict[str, str] = field(default_factory=dict)
    artifacts: list[dict] = field(default_factory=list)
    timing: dict = field(default_factory=dict)
    resources: dict = field(default_factory=dict)
    source_map: dict = field(default_factory=dict)
    failure: dict | None = None
    notes: list[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


def build_stage_contract(
    *,
    stage_id: str,
    engine: dict,
    capabilities: dict,
    input_manifest: dict,
    output_manifest: dict,
    source_map: dict,
    typed_failures: list[dict],
    resource_policy: dict,
    path_policy: dict,
    stage_root: str,
) -> dict:
    """Assemble `COMFY_STAGE_CONTRACT.json` — the read-only handoff artifact."""
    return {
        "schema": SCHEMA,
        "stage_id": stage_id,
        "engine": engine,
        "capability": capabilities,
        "input_manifest": input_manifest,
        "output_manifest": output_manifest,
        "source_map": source_map,
        "lifecycle": {
            "states": STAGE_STATES,
            "transitions": LIFECYCLE,
            "completion_authority": "/history/{prompt_id} (websocket is progress-only)",
        },
        "typed_failures": typed_failures,
        "resource_policy": resource_policy,
        "path_policy": path_policy,
        "stage_root": stage_root,
        "handoff": {
            "read_only_for": ["product manager", "MotionForge API"],
            "stable_keys": ["schema", "stage_id", "engine", "capability", "input_manifest",
                            "output_manifest", "source_map", "lifecycle", "typed_failures",
                            "resource_policy", "path_policy"],
            "motion_authority": "MotionForge (source clock/PTS). ComfyUI output is an unpromoted stage artifact.",
        },
    }


def write_json(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False, ensure_ascii=False)
