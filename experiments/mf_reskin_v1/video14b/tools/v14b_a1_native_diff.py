"""A1 — export/verify the NATIVE Wan Animate-2 graph against the SUBMITTED wave-B graph.

Structural diff only: pose window, pose-video source and frame count, reference
wiring, size/crop, sampler/scheduler/steps/shift and the model pins.  The
submitted graph is the negative control and is never modified (its bytes are
hashed before and after this script runs).

The widget -> input mapping is not guessed: it is parsed out of the INSTALLED
runtime's own ``comfy_extras/nodes_wan.py`` schema (``WanAnimate2ToVideo``), and
a template node is paired with the submitted node by identity — the subgraph
node ``587`` exports as ``<subgraph-instance-id>:587``, which is the submitted
``672:587`` — so a value can only line up with the input the runtime reads.

CPU only: no server, no model load, no inference.

usage:
  python v14b_a1_native_diff.py [--out <a1_graph_diff.json>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

RT = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\runtime\video14b")
COMFY = RT / "ComfyUI"
TPL_DIR = RT / "venv/Lib/site-packages/comfyui_workflow_templates_json/templates"
OLD = Path(
    r"C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs"
    r"\mf-reskin-correction-20260922\20260922T0955Z"
)
NEW = Path(
    r"C:\Users\Admin\Documents\Codex\2026-09-22\tr-ng-th-i-terminal-gi\outputs"
    r"\mf-core-tool-delivery-20260923\20260923T1535Z"
)
WT = Path(__file__).resolve().parent.parent

SUBMITTED = OLD / "VIDEO14B/waveB/workflows/mf_animate2_book4s.waveB.api.json"
SUBMITTED_SIBLINGS = (
    "mf_animate2_book4s.api.json",
    "mf_animate2_book4s.fixed.api.json",
    "mf_animate2_book4s.shim.api.json",
    "mf_animate2_book4s.waveB.api.json",
    "mf_animate2_book4s.waveB.patch.json",
)
NATIVE_TEMPLATES = ("video_wan_animate2.json", "video_wan_animate2_distilled.json")

WIDGET_TYPES = {"Int", "Float", "String", "Boolean", "Combo"}
FIELDS_OF_INTEREST = (
    "pose_start_percent",
    "pose_end_percent",
    "pose_strength",
    "reference_image_strength",
    "width",
    "height",
    "length",
    "batch_size",
    "video_frame_offset",
)
# template node ids -> label, resolved by CLASS so a re-numbered template still reads
LABELLED_CLASSES = {
    "WanAnimate2ToVideo": "WanAnimate2ToVideo",
    "WanAnimate2Cache": "WanAnimate2Cache",
    "BasicScheduler": "BasicScheduler",
    "ModelSamplingSD3": "ModelSamplingSD3",
    "KSamplerSelect": "KSamplerSelect",
    "ContextWindowsManual": "ContextWindowsManual",
    "LoadImage": "LoadImage",
    "LoadVideo": "LoadVideo",
    "UNETLoader": "UNETLoader",
    "LoraLoaderModelOnly": "LoraLoaderModelOnly",
    "CLIPLoader": "CLIPLoader",
    "CLIPVisionLoader": "CLIPVisionLoader",
    "VAELoader": "VAELoader",
    "PrimitiveInt": "PrimitiveInt",
    "SaveVideo": "SaveVideo",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical_sha(obj: object) -> str:
    return sha256_bytes(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def is_link(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


def walk_links(value: object, key: str = "") -> list[tuple[str, str, int]]:
    """Every ``[node_id, slot]`` link inside ``value``, with its input key path."""
    found: list[tuple[str, str, int]] = []
    if is_link(value):
        found.append((key, str(value[0]), int(value[1])))
    elif isinstance(value, dict):
        for sub_key, sub in value.items():
            found += walk_links(sub, f"{key}.{sub_key}" if key else str(sub_key))
    elif isinstance(value, list):
        for index, sub in enumerate(value):
            found += walk_links(sub, f"{key}[{index}]")
    return found


def ancestors(graph: dict, node_id: str) -> list[dict]:
    """Ordered ancestor walk from ``node_id`` (breadth first, links only)."""
    seen: list[str] = []
    queue = [node_id]
    chain: list[dict] = []
    while queue:
        current = queue.pop(0)
        if current in seen or current not in graph:
            continue
        seen.append(current)
        node = graph[current]
        links = walk_links(node.get("inputs") or {})
        for _, src, _slot in links:
            queue.append(src)
        chain.append(
            {
                "node": current,
                "class_type": node.get("class_type"),
                "scalars": {
                    k: v
                    for k, v in (node.get("inputs") or {}).items()
                    if isinstance(v, (str, int, float, bool))
                },
                "links": [{"input": k, "from": s, "slot": t} for k, s, t in links],
            }
        )
    return chain


def schema_widget_order(nodes_wan_text: str) -> dict:
    """``WanAnimate2ToVideo`` input order as the installed runtime declares it."""
    match = re.search(r"class WanAnimate2ToVideo\(.*?\n(.*?)\nclass ", nodes_wan_text, re.S)
    if match is None:
        raise SystemExit("WanAnimate2ToVideo class not found in nodes_wan.py")
    block = match.group(1)
    inputs = re.findall(r"io\.(\w+)\.Input\(\s*\"([a-z_0-9]+)\"", block)
    widgets = [name for kind, name in inputs if kind in WIDGET_TYPES]
    links = [name for kind, name in inputs if kind not in WIDGET_TYPES]
    return {"inputs": [n for _, n in inputs], "widgets": widgets, "links": links}


def zip_widgets(widgets: list[str], values: list) -> dict | None:
    if len(widgets) != len(values):
        return None
    return dict(zip(widgets, values))


def template_nodes(template: dict) -> list[dict]:
    """Every node of the template, tagged with the (sub)graph that holds it."""
    found = [
        {"node": node, "graph": "top-level"}
        for node in template.get("nodes") or []
    ]
    for subgraph in (template.get("definitions") or {}).get("subgraphs") or []:
        for node in subgraph.get("nodes") or []:
            found.append(
                {
                    "node": node,
                    "graph": subgraph.get("name") or subgraph.get("id"),
                    "subgraph_id": subgraph.get("id"),
                }
            )
    return found


def native_side(path: Path, widgets: list[str]) -> dict:
    template = json.loads(path.read_text(encoding="utf-8"))
    nodes = template_nodes(template)
    out: dict = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "format": "ui (frontend) template",
        "nodes": len(nodes),
        "subgraphs": [
            {
                "id": subgraph.get("id"),
                "name": subgraph.get("name"),
                "nodes": len(subgraph.get("nodes") or []),
            }
            for subgraph in (template.get("definitions") or {}).get("subgraphs") or []
        ],
        "by_class": {},
    }
    for entry in nodes:
        node = entry["node"]
        label = LABELLED_CLASSES.get(node.get("type") or "")
        if label is None:
            continue
        record = {
            "node_id": node.get("id"),
            "graph": entry["graph"],
            "widgets_values": node.get("widgets_values"),
        }
        if label == "WanAnimate2ToVideo":
            record["named"] = zip_widgets(widgets, node.get("widgets_values") or [])
        out["by_class"].setdefault(label, []).append(record)
    animate = out["by_class"].get("WanAnimate2ToVideo") or []
    primary = next((a for a in animate if a["node_id"] == 587), None)
    if primary is None and animate:
        primary = animate[-1]
    out["primary_animate_node"] = primary
    out["primary_id_correspondence"] = (
        f"template subgraph node {primary['node_id']} exports as the api id "
        f"{'672:' + str(primary['node_id'])} in the submitted graph"
        if primary
        else None
    )
    return out


def submitted_side(path: Path, widgets: list[str]) -> dict:
    graph = json.loads(path.read_text(encoding="utf-8"))
    node = graph["672:587"]
    scalars = {k: v for k, v in node["inputs"].items() if isinstance(v, (str, int, float, bool))}
    chain = ancestors(graph, "672:587")
    by_id = {entry["node"]: entry for entry in chain}
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "canonical_sha256": canonical_sha(graph),
        "format": "api (prompt)",
        "nodes": len(graph),
        "class_histogram": {
            cls: sum(1 for n in graph.values() if n["class_type"] == cls)
            for cls in sorted({n["class_type"] for n in graph.values()})
        },
        "WanAnimate2ToVideo": {
            "node_id": "672:587",
            "class_type": node["class_type"],
            "named": {k: scalars[k] for k in FIELDS_OF_INTEREST if k in scalars},
            "linked": {
                k: v for k, v in node["inputs"].items() if not isinstance(v, (str, int, float, bool))
            },
            "widget_value_count": len(scalars),
            "widget_order_matches_runtime": set(scalars) == set(widgets),
        },
        "wiring": {
            k: {"from": v[0], "slot": v[1], "from_class": graph[v[0]]["class_type"]}
            for k, v in node["inputs"].items()
            if is_link(v) and v[0] in graph
        },
        "sampler_family": {
            key: graph[key]["inputs"]
            for key in ("672:591", "672:592", "672:593", "672:594", "672:597")
            if key in graph
        },
        "loaders": {
            key: graph[key]["inputs"]
            for key in ("672:578", "672:579", "672:580", "672:583", "672:584")
            if key in graph
        },
        "outputs": {
            key: graph[key]["inputs"]
            for key, value in graph.items()
            if value["class_type"] in {"SaveVideo", "CreateVideo", "VHS_VideoCombine"}
        },
        "reference_chain": [
            chain_entry
            for chain_entry in chain
            if chain_entry["node"] in {"189", "672:590", "672:589", "672:584", "672:598", "672:599"}
        ],
        "input_readers_in_closure": sorted(
            chain_entry["node"]
            for chain_entry in chain
            if chain_entry["class_type"] in {"LoadImage", "LoadVideo"}
        ),
        "clip_vision_source": by_id.get("672:589", {}).get("links"),
    }


def diff_rows(native: dict, submitted: dict, widgets: list[str]) -> list[dict]:
    primary = native.get("primary_animate_node") or {}
    native_named = primary.get("named") or {}
    sub_linked = submitted["WanAnimate2ToVideo"]["linked"]
    submitted_named = submitted["WanAnimate2ToVideo"]["named"]
    rows: list[dict] = []
    for field in widgets:
        if field in submitted_named:
            sub_value: object = submitted_named[field]
        elif field in sub_linked:
            sub_value = f"linked:{json.dumps(sub_linked[field])}"
        else:
            sub_value = None
        rows.append(
            {
                "field": field,
                "native": native_named.get(field),
                "submitted": sub_value,
                "delta": native_named.get(field) != sub_value,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(NEW / "VIDEO14B/raw/a1_graph_diff.json"))
    args = parser.parse_args()

    nodes_wan_path = COMFY / "comfy_extras/nodes_wan.py"
    nodes_wan_text = nodes_wan_path.read_text(encoding="utf-8")
    schema = schema_widget_order(nodes_wan_text)
    widgets = schema["widgets"]

    window_lines = [
        {"line": index, "text": line.strip()}
        for index, line in enumerate(nodes_wan_text.splitlines(), start=1)
        if ("pose_start_percent > 0.0" in line)
        or ("pose_end_percent < 1.0" in line)
        or ('pose_values["pose_video_latent"]' in line)
        or ("windowed(positive)" in line)
    ]

    submitted_before = sha256_file(SUBMITTED)
    native = [native_side(TPL_DIR / name, widgets) for name in NATIVE_TEMPLATES]
    for entry in native:
        twin = WT / "workflows/official" / Path(entry["path"]).name
        if twin.is_file():
            entry["tree_copy"] = {
                "path": str(twin),
                "bytes": twin.stat().st_size,
                "sha256": sha256_file(twin),
                "byte_identical_to_installed_template": sha256_file(twin) == entry["sha256"],
            }
    submitted = submitted_side(SUBMITTED, widgets)
    siblings = [
        {
            "name": name,
            "bytes": (SUBMITTED.parent / name).stat().st_size,
            "sha256": sha256_file(SUBMITTED.parent / name),
        }
        for name in SUBMITTED_SIBLINGS
        if (SUBMITTED.parent / name).is_file()
    ]
    submitted_after = sha256_file(SUBMITTED)
    run_graph = WT / "workflows/run/mf_animate2_book4s.json"

    result = {
        "scope": "A1 structural diff, CPU only: no engine started, no model loaded, no inference",
        "runtime": {
            "ComfyUI": str(COMFY),
            "nodes_wan.py": {"sha256": sha256_file(nodes_wan_path)},
            "model_sampling.py": {"sha256": sha256_file(COMFY / "comfy/model_sampling.py")},
            "samplers.py": {"sha256": sha256_file(COMFY / "comfy/samplers.py")},
            "WanAnimate2ToVideo_pose_window_lines": window_lines,
        },
        "widget_order": {
            "source": "installed runtime schema WanAnimate2ToVideo.define_schema",
            "inputs": schema["inputs"],
            "widgets": schema["widgets"],
            "link_inputs": schema["links"],
            "template_widget_count_matches": all(
                all(
                    node["named"] is not None
                    for node in (entry["by_class"].get("WanAnimate2ToVideo") or [])
                )
                for entry in native
            ),
        },
        "native": native,
        "submitted": submitted,
        "submitted_siblings": siblings,
        "submitted_negative_control": {
            "path": str(SUBMITTED),
            "sha256_before": submitted_before,
            "sha256_after": submitted_after,
            "unchanged": submitted_before == submitted_after,
        },
        "local_run_graph": {
            "path": str(run_graph),
            "sha256": sha256_file(run_graph) if run_graph.is_file() else None,
        },
        "field_diff_vs_template_0": diff_rows(native[0], submitted, widgets),
        "field_diff_vs_template_1": diff_rows(native[1], submitted, widgets),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out),
                "widgets": widgets,
                "diff_vs_native_0": result["field_diff_vs_template_0"],
                "native_primary": {
                    entry["path"].split("/")[-1]: entry["primary_animate_node"] for entry in native
                },
                "negative_control_unchanged": result["submitted_negative_control"]["unchanged"],
                "submitted_named": submitted["WanAnimate2ToVideo"]["named"],
                "submitted_widget_order_matches_runtime": submitted["WanAnimate2ToVideo"][
                    "widget_order_matches_runtime"
                ],
                "reference_chain": submitted["reference_chain"],
                "input_readers_in_closure": submitted["input_readers_in_closure"],
                "sampler_family": submitted["sampler_family"],
                "loaders": submitted["loaders"],
                "siblings": siblings,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
