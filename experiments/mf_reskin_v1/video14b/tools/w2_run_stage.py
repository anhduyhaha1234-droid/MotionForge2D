"""MF-V1-VIDEO14B wave-2 stage runner.

Imports the FROZEN MF-V1-COMFY adapter read-only from the other task's worktree
(commit cc3222b1bed6680480ab6d63fb869b02d749259b) and points it at THIS task's
engine (127.0.0.1:8210), runtime and stage root. Exactly one adapter exists in
the project; nothing is written inside wt-comfy.

usage:
  python w2_run_stage.py <api_graph.json> <stage_dir_name> <workflow_id> \
      <run_out_dir> [--timeout 3600] [--reserve-vram-declared 1.0] \
      [--attempt-id <declared-attempt-id>]

Writes into <run_out_dir>: run_record.json (argv/cwd/port/epoch/pins/timing/
resources/status/failure/artifacts/terminal_outputs) and adapter_stage_output.json.

Output contract (row F05; COMFY HANDOFF section 1.2): the only publishable
artifact is what the SERVER itself wrote (`type == "output"`) on a node THIS
runner declares in `RunSpec.terminal_outputs`.  `allowed_types` may only narrow
`mf_comfy.adapter.PUBLISHABLE_SERVER_TYPES = ("output",)`; it can never promote an
`input` preview of what we sent into a result.  See `declared_terminal_outputs()`.

`--attempt-id` is the declared identity of this work item; pass the SAME value to
resume that attempt (a resume that cannot declare it is refused by design).  Left
empty, a fresh anonymous attempt is minted -- the pre-existing behaviour.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import time
from pathlib import Path

PKG = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\wt-comfy\experiments\mf_reskin_v1\comfy")
sys.path.insert(0, str(PKG))
from mf_comfy import (  # noqa: E402
    ComfyStageAdapter, GpuStageGate, HttpTransport, InstanceEpoch, InstanceLease,
    ResourceSampler, RunSpec, StagePaths, hash_workflow,
    sha256_file,
)
from mf_comfy.adapter import PUBLISHABLE_SERVER_TYPES  # noqa: E402

RT = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\runtime\video14b")
BASE = "http://127.0.0.1:8210"
NODE_INVENTORY_SHA256 = "d9e8e25aa7c6b32fd67100fb7a5bef58c37686414cbf7de5172b2c67b1b63da3"
OWNER = "video14b"

# --------------------------------------------------------------- F05 output contract
# The engine's own SAVE nodes: these are the nodes that write a file into the
# server's output directory, so they are the only nodes that may publish a
# product.  A LoadVideo / CreateVideo / PreviewImage node reads or previews and is
# never a result, however the history entry spells it (the reviewer's defect was a
# history whose only artifact was `type: "input", filename: source.png`).
# `is_output_node=True` for all seven in the pinned ComfyUI 0.28.2 checkout.
SAVE_NODE_KINDS: dict[str, tuple[str, str]] = {
    "SaveImage": ("images", "image"),
    "SaveImageAdvanced": ("images", "image"),
    "SaveAnimatedPNG": ("images", "image"),
    "SaveAnimatedWEBP": ("images", "image"),
    "SaveVideo": ("videos", "video"),
    "SaveWEBM": ("videos", "video"),
    "VHS_VideoCombine": ("videos", "video"),
}

# Only the server's own written output is publishable, and a caller may only
# NARROW that set -- never widen it back to an `input` preview.
ALLOWED_SERVER_TYPES: tuple = tuple(PUBLISHABLE_SERVER_TYPES)


def declared_terminal_outputs(graph: dict) -> dict:
    """`RunSpec.terminal_outputs` for `graph`: its save nodes and nothing else.

    A save node is declared even when a downstream node also consumes its output
    -- the write still happened, and the adapter reads the history's `outputs`
    keyed by node, not a serialised dataflow.  A node absent from
    `SAVE_NODE_KINDS` (a loader, a preview, a codec helper) is deliberately NOT
    declared: an artifact it carries is ignored rather than staged, and a run that
    produces nothing on a declared node fails with the adapter's typed
    `ArtifactMissing` instead of publishing a preview under a product's name.
    """
    declared: dict[str, dict] = {}
    for node_id, node in (graph or {}).items():
        kinds = SAVE_NODE_KINDS.get(str((node or {}).get("class_type") or ""))
        if kinds is None:
            continue
        declared[str(node_id)] = {
            "kind": kinds[0], "media_type": kinds[1],
            "server_types": ALLOWED_SERVER_TYPES,
        }
    return declared


def build_run_spec(graph: dict, workflow_id: str, pins: dict, timeout: float,
                   attempt_id: str = "", owner: str = OWNER,
                   node_inventory_sha256: str = NODE_INVENTORY_SHA256) -> RunSpec:
    """The single place this stage builds a `RunSpec`.

    The output contract is declared here, not inferred from whatever the history
    happens to carry: `allowed_types` is the publishable-narrowed set and
    `terminal_outputs` names the graph's own save nodes.
    """
    return RunSpec(
        stage_id=OWNER,
        workflow_id=workflow_id,
        graph=graph,
        workflow_sha256=hash_workflow(graph),
        node_inventory_sha256=node_inventory_sha256,
        model_pins=pins,
        stage_timeout_s=timeout,
        poll_s=2.0,
        allowed_types=ALLOWED_SERVER_TYPES,
        attempt_id=attempt_id,
        owner=owner or OWNER,
        terminal_outputs=declared_terminal_outputs(graph),
    )


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def main() -> int:
    graph_path = _p(sys.argv[1])
    stage_name = sys.argv[2]
    workflow_id = sys.argv[3]
    out_dir = _p(sys.argv[4])
    timeout = float(sys.argv[sys.argv.index("--timeout") + 1]) if "--timeout" in sys.argv else 3600.0
    attempt_id = sys.argv[sys.argv.index("--attempt-id") + 1] if "--attempt-id" in sys.argv else ""
    out_dir.mkdir(parents=True, exist_ok=True)

    graph = json.loads(graph_path.read_text(encoding="utf-8"))

    # model pins: hash every file the graph loads, measured here, now.
    pins: dict[str, str] = {}
    for node in graph.values():
        ins = node.get("inputs") or {}
        for key in ("unet_name", "ckpt_name", "lora_name", "clip_name", "vae_name"):
            val = ins.get(key)
            if isinstance(val, str):
                sub = {"unet_name": "diffusion_models", "ckpt_name": "checkpoints",
                       "lora_name": "loras", "clip_name": "text_encoders",
                       "vae_name": "vae"}[key]
                cand = RT / "models" / sub / val
                if not cand.is_file():
                    # normalise known alternative locations
                    alt = RT / "models" / ("clip_vision" if "clip_vision" in val else sub) / val
                    cand = alt
                pins[val] = sha256_file(cand)

    transport = HttpTransport(BASE, http_timeout_s=120)
    epoch = InstanceEpoch(RT / "instance_epoch.json")
    rec = epoch.read()
    if not rec:
        print("REFUSED: no instance epoch on disk", file=sys.stderr)
        return 2
    paths = StagePaths(RT / "output" / stage_name)
    lease = InstanceLease(RT / "leases", instance_id=rec["instance_id"], owner=OWNER)
    gate = GpuStageGate(RT / "leases" / "gpu_stage.lock", timeout_s=60.0)
    adapter = ComfyStageAdapter(transport, paths, lease=lease, gate=gate, epoch=epoch,
                                sampler=ResourceSampler(interval_s=2.0), owner=OWNER)
    adapter.instance_epoch = rec

    spec = build_run_spec(graph, workflow_id, pins, timeout, attempt_id=attempt_id)
    terminal_outputs = declared_terminal_outputs(graph)
    if not terminal_outputs:
        # Fail closed BEFORE any POST: a graph with no save node cannot publish
        # anything, so submitting it could only stage something that is not a
        # product (F05).  Extend SAVE_NODE_KINDS deliberately if a new save node
        # type is used -- an empty declaration is never silently widened.
        print(json.dumps({"status": "refused_no_terminal_output",
                          "graph": str(graph_path),
                          "save_node_kinds": sorted(SAVE_NODE_KINDS)}, indent=1))
        return 3

    t0 = time.time()
    try:
        out = adapter.run(spec)
        outd = dataclasses.asdict(out)
        rc = 0
    except Exception as exc:  # typed failures are evidence, not crashes
        outd = {
            "status": "raised",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "error_dict": getattr(exc, "to_dict", lambda: None)(),
        }
        rc = 1
    wall = round(time.time() - t0, 3)

    record = {
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "port": 8210,
        "base_url": BASE,
        "stage_root": str(paths.root),
        "workflow_id": workflow_id,
        "workflow_path": str(graph_path),
        "service_epoch": rec,
        "declared_reserve_vram_gb": 1.0,
        "node_inventory_sha256": NODE_INVENTORY_SHA256,
        "graph_sha256": hash_workflow(graph),
        "model_pins": pins,
        "attempt_id": attempt_id,
        "allowed_types": list(spec.allowed_types),
        "terminal_outputs": terminal_outputs,
        "wall_s": wall,
        "result": outd,
    }
    out_dir.joinpath("run_record.json").write_text(
        json.dumps(record, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    out_dir.joinpath("adapter_stage_output.json").write_text(
        json.dumps(outd, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"status": outd.get("status"), "prompt_id": outd.get("prompt_id"),
                      "timing": outd.get("timing"), "resources": outd.get("resources"),
                      "wall_s": wall, "error": outd.get("error"),
                      "artifacts": [(a.get("kind"), a.get("staged_path"), a.get("sha256"),
                                     a.get("size_bytes"), a.get("decode_verified"))
                                    for a in (outd.get("artifacts") or [])]},
                     indent=1, default=str))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
