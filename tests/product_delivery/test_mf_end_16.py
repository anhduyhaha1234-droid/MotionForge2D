"""MF-END-16 — wan_shot_v1 + model_profiles: profile và phép đo chất lượng/chi phí.

Row map (binary):
* micro repro: the three delivered JSONs exist, parse, and carry the declared sections;
* structural: every node id/link/type resolves, no cycles, everything reachable from the two
  save nodes, only classes measured as REGISTERED on the pinned runtime are used (offline
  validation against the proof's live /object_info dump when present);
* pinned variant: the graph is the cache-OFF wiring (no WanAnimate2Cache node; 672:591/672:592
  take the model straight from 672:588) and equals the run graph modulo the save-prefix knob;
* geometry pin: the P3B_PAD ResizeAndPadImage 640x368 (area, centered) feeds pose_video and the
  size authority; the portrait 482x854 crop node does not exist anywhere;
* checkpoint variant pin: exactly the INT8 convrot checkpoint + rank64 LoRA + the three
  auxiliary files; no other variant is named;
* case binding: 4 measured cases carry source/anchor/prompt/seed/graph/receipt/output hashes
  matching the frozen constants (and, when the proof root is present, the files on disk);
* frame mapping: exact spans 120/120/102/18 with the identity maps, the OCC cut at 102, the
  360-frame assembly, the 4+4 pad policy and the chunk/trim semantics are all declared;
* measurement: every cost figure matches the receipt arithmetic; RAM is NOT_MEASURED (never
  guessed); cache on/off and overlap 8<->16 are pixel-identical (max_abs 0);
* accepted-second cost: accepted_seconds = 0 and the per-accepted-second cost is UNDEFINED —
  the test refuses any fabricated denominator;
* profiles: benchmark status and eligibility are separate fields; Wan is
  ELIGIBLE_PENDING_QUALITY_OWNER, VACE is INELIGIBLE (watermark blocker); no best/newest claim;
* negatives: mutated graphs (missing input, unknown class, dangling link, cycle, unreachable
  node, invalid enum, re-added cache node, unwired pad, portrait resize restored, checkpoint
  swap, steps change, prefix divergence, missing seed) and mutated claims/profile docs
  (quality accepted, invented denominator, best-model claim, VACE marked eligible) are refused.

No GPU, no network, no render here.  Everything is offline validation of delivered bytes.
"""

from __future__ import annotations

import copy as _copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = PROJECT_ROOT / "app" / "media_workflows" / "wan_shot_v1.json"
MANIFEST_PATH = PROJECT_ROOT / "app" / "media_workflows" / "wan_shot_v1.manifest.json"
PROFILES_PATH = PROJECT_ROOT / "app" / "media_workflows" / "model_profiles.json"

SCHEMA_VERSION = "mf.wan_shot.graph.v1"
MANIFEST_SCHEMA_VERSION = "mf.wan_shot.manifest.v1"
PROFILES_SCHEMA_VERSION = "mf.model_profiles.v1"
GRAPH_ID = "wan_shot_v1"

#: classes measured as REGISTERED on the pinned runtime (0.37.0) and relevant to this profile
CLASS_SET = frozenset({
    "BasicScheduler", "CLIPLoader", "CLIPTextEncode", "CLIPVisionEncode", "CLIPVisionLoader",
    "ComfyMathExpression", "ComfySwitchNode", "ConcatenateVideo", "ContextWindowsManual",
    "CreateList", "CreateVideo", "EndLoop", "GetImageSize", "GetItemFromList",
    "GetVideoComponents", "ImageFromBatch", "ImageStitch", "KSamplerSelect", "LoadAudio",
    "LoadImage", "LoadVideo", "LoraLoaderModelOnly", "ModelSamplingSD3", "PrimitiveInt",
    "RebatchImages", "ResizeAndPadImage", "ResizeImageMaskNode", "SamplerCustom", "SaveVideo",
    "StartLoop", "TrimVideoLatent", "UNETLoader", "VAEDecode", "VAELoader", "WanAnimate2ToVideo",
})

#: the graph's full class set (delivered; 33 classes over 63 nodes)
DELIVERED_GRAPH_CLASSES = frozenset({
    "BasicScheduler", "CLIPLoader", "CLIPTextEncode", "CLIPVisionEncode", "CLIPVisionLoader",
    "ComfyMathExpression", "ComfySwitchNode", "ContextWindowsManual", "CreateList",
    "CreateVideo", "EndLoop", "GetImageSize", "GetItemFromList", "GetVideoComponents",
    "ImageFromBatch", "ImageStitch", "KSamplerSelect", "LoadImage", "LoadVideo",
    "LoraLoaderModelOnly", "ModelSamplingSD3", "PrimitiveInt", "RebatchImages",
    "ResizeAndPadImage", "ResizeImageMaskNode", "SamplerCustom", "SaveVideo", "StartLoop",
    "TrimVideoLatent", "UNETLoader", "VAEDecode", "VAELoader", "WanAnimate2ToVideo",
})

UNET = "wan_animate_2_int8_convrot.safetensors"
LORA = "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"
TEXT_ENCODER = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
CLIP_VISION = "clip_vision_h.safetensors"
VAE_FILE = "Wan2_1_VAE_bf16.safetensors"
CHALLENGER_UNET = "wan2.1_vace_14B_fp16.safetensors"

STEPS = 6
SAMPLER = "lcm"
CFG = 1
SHIFT = 5
CONTEXT_LENGTH = 21
CONTEXT_OVERLAP = 8
SAVE_PREFIX = "wan_shot_v1/book"

#: frozen graph/prompt/receipt constants (measured; see the manifest for provenance)
RUN_GRAPH_SHA = "4247f9e8b233da4b6213c3254b637abd4d2e6c17b307b32cddb9b7b17bbd4759"  # p6nocache
PREDECESSOR_GRAPH_SHA = "b2ab500748d5163797ccef71e6ed9e078682440a656afd6ae4ab4cf43234a36d"  # p3b
TEMPLATE_SHA = "6e92d82b20cb2d9b1e6a9fe0e8d9cddc88ea81fdf4151ef4c6b62e21cf158fa5"
PROMPT_SHAS = {
    "BOOK": "540d16b7b7300c40b3768bd589e963b03bf400e8aa6010ef2068d2161676bd9d",
    "TURN": "eca92d5eb298827aa7ffb61874efa07c4fe28ba0d3aa59c8d8aac77ff88bca2d",
    "OCC_SEG1": "b2a1e176eaaa3f4df07c927921c6a7fbb64d9ca0c9d2705d17be7e5038f33516",
    "OCC_SEG2": "dd00d8acee0e3ce1d4f9b73e25bc283310717bac5a63a0f96d9c5ca22ac65c53",
}
OUTPUT_SHAS = {
    "BOOK": "dfc4e37b81ba4252635581a6f75fef1084324dcd7af9015e3ea3e2c86b90d77f",
    "BOOK_PINNED_VARIANT": "be83cf705a7a8769a307aaf1c3292e314d612b2aaecf946d8c366674c2fe866b",
    "TURN": "f0b2d6e0dc90b12f31e19e0e8efa97086facaf059def95401dbd0f08de5559c6",
    "OCC_SEG1": "b9b1cdb989f43ffbee7ea72f52005e86b44d0219d3a49719a6964f53f7f55cc4",
    "OCC_SEG2": "7db4734bf73e267737ff9b17b4579792f9fd44d8140e0724cc364576a55098a7",
    "ASSEMBLY": "6878becc7e1db4c561253fb3ab79a85aacf0ecf685f7ea10dbac0e5b834a750e",
    "VACE": "691a8530e3f4bdbbf13fb99ffee9abc4e64b43b3617597736098c8d13a756611",
}
SOURCE_SHAS = {
    "BOOK": "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
    "TURN": "cf7cfbf0553701d43a1324b782e2b774e0c4141e2c566a50bbdb0d7769f88017",
    "OCC_WINDOW": "80079401b696870dabe6710e0bed4087f422e79ce660c043c8e4eeb795e8efd2",
    "OCC_SEG1": "a283d23704e352f7ca3fdc618f8b8275de939b4d0c1eb590fc48c6f825949784",
    "OCC_SEG2": "eec74ec5b9eb38ceb433352b01505ffc9185ddbd0ee593679472dd4344137328",
}
ANCHOR_SHAS = {
    "BOOK": "aa08747048c42af56c9e5109b7a041d2f8d95bf7c79544017ef38b98bbb6455e",
    "TURN": "0820e3cbe9df4d4d290159e7079de25108899e1ca636a5a2ea57d04e9699aeec",
    "OCC_SEG1": "ca5e85a4b66a329dd25f33dd30ad3ac501589b5a09ac14bd177c573e2c64f542",
    "OCC_SEG2": "81920361f5bb59b2fb97e055c26f46bb0dafd980042d6719104461d7747648bf",
}
MODEL_SHAS = {
    UNET: "0580ecdd65e47e97c30df9670d13a6c4a131d26de5a1faf2ccc78392d5167584",
    LORA: "85c4a61c30e0497aa44b91d93a893b624708461a56fe5485183b28fa07e2dfb3",
    TEXT_ENCODER: "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
    CLIP_VISION: "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161",
    VAE_FILE: "1ab9a32cc2c740f6e39d80d367ce5dcc28db8c71b79b28670546b8973e9d75f9",
    CHALLENGER_UNET: "f202a5c59b8a91ada1862c46a038214f1f7f216c61ec8350d25f69b919da4307",
}
COST_TABLE = {
    "wan_cache_on_warm": (154.67, 38.67, 10973),
    "wan_cache_off_warm": (135.21, 33.8, 10763),
    "wan_cache_off_turn": (134.94, 33.73, 10855),
    "wan_cache_off_occ_seg1": (120.55, 30.14, 10875),
    "wan_cache_off_occ_seg2": (31.21, 7.8, 10931),
    "wan_warm_overlap16": (155.0, 38.75, 11224),
    "vace_14b_fp16": (1174.24, 291.13, 11680),
}

EVIDENCE_ROOT = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z"
)
PROOF_ROOT = EVIDENCE_ROOT / "proof"
RUN_ROOT = EVIDENCE_ROOT / "tasks" / "MF-END-16"
REVERIFY_RAW = RUN_ROOT / "raw" / "evidence_reverify.json"
#: the /object_info captured ON the GPU server with the shared read-only models root
#: (P0_object_info.json was captured without the models root: its model-name option lists are
#: empty/['pixel_space'], so validating model names against it is a false negative — see F-note)
OBJECT_INFO_PIN = PROOF_ROOT / "evidence" / "P3_object_info_gpu.json"


# ── the single validator (structural + optional /object_info) ─────────────────


def _enum_values(decl: Any) -> list | None:
    if not isinstance(decl, list) or not decl:
        return None
    if isinstance(decl[0], list):
        return decl[0] or None
    if decl[0] == "COMBO" and len(decl) > 1 and isinstance(decl[1], dict):
        return decl[1].get("options") or None
    return None


#: widgets whose option list is a SNAPSHOT of the server input directory at capture time, not a
#: semantic enum: the delivered graph's golden input file is staged at run time, so membership
#: there is a false negative (the exact filenames + hashes are asserted by the case-binding rows).
FILE_WIDGET_EXEMPT = {
    ("LoadImage", "image"),
    ("LoadVideo", "file"),
    ("LoadAudio", "audio"),
}


def _dynamic_combo_options(decl: Any) -> list | None:
    if isinstance(decl, list) and decl and decl[0] == "COMFY_DYNAMICCOMBO_V3" and len(decl) > 1:
        return decl[1].get("options") or None
    return None


def validate_graph(graph: dict, object_info: dict | None, save_ids: tuple[str, ...]) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    checked_inputs = 0
    enums = 0
    ids = set(graph)
    for nid, node in graph.items():
        if not isinstance(node, dict):
            errors.append(f"node {nid}: not an object")
            continue
        ct = node.get("class_type")
        if not isinstance(ct, str):
            errors.append(f"node {nid}: class_type is not a string")
            continue
        given = node.get("inputs")
        if not isinstance(given, dict):
            errors.append(f"node {nid} ({ct}): inputs missing")
            continue
        if object_info is not None:
            if ct not in object_info:
                errors.append(f"node {nid}: class_type {ct!r} not in /object_info")
                continue
            spec = object_info[ct].get("input", {}) or {}
            req = spec.get("required", {}) or {}
            for k in req:
                if k not in given:
                    errors.append(f"node {nid} ({ct}): missing required input {k!r}")
        for k, v in given.items():
            base_key = k.split(".", 1)[0]
            if object_info is not None:
                spec = object_info[ct].get("input", {}) or {}
                req = spec.get("required", {}) or {}
                opt = spec.get("optional", {}) or {}
                if base_key not in req and base_key not in opt:
                    warnings.append(f"node {nid} ({ct}): input {k!r} not declared by the engine")
                    continue
            checked_inputs += 1
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                if v[0] not in ids:
                    errors.append(f"node {nid} ({ct}): input {k!r} links to missing node {v[0]!r}")
                continue
            if object_info is None:
                continue
            decl = (object_info[ct].get("input", {}).get("required", {}) or {}).get(base_key)
            if decl is None:
                decl = (object_info[ct].get("input", {}).get("optional", {}) or {}).get(base_key)
            dco = _dynamic_combo_options(decl)
            if dco is not None:
                if k == base_key:
                    enums += 1
                    if (ct, base_key) in FILE_WIDGET_EXEMPT:
                        continue
                    names = [o.get("key", o.get("name")) for o in dco]
                    if v not in names:
                        errors.append(f"node {nid} ({ct}): dynamic combo {v!r} not in {names}")
                continue
            allowed = _enum_values(decl)
            if allowed is not None:
                enums += 1
                if (ct, base_key) in FILE_WIDGET_EXEMPT:
                    continue
                if v not in allowed:
                    errors.append(f"node {nid} ({ct}): {k!r}={v!r} not in {allowed[:12]}")
    colour = {n: 0 for n in ids}

    def dfs(n: str, stack: list[str]) -> None:
        colour[n] = 1
        for v in graph[n].get("inputs", {}).values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] in ids:
                if colour[v[0]] == 1:
                    errors.append(f"cycle: {' -> '.join(stack + [v[0]])}")
                elif colour[v[0]] == 0:
                    dfs(v[0], stack + [v[0]])
        colour[n] = 2

    for n in sorted(ids):
        if colour[n] == 0:
            dfs(n, [n])
    live: set[str] = set()

    def reach(n: str) -> None:
        if n in live:
            return
        live.add(n)
        for v in graph[n].get("inputs", {}).values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] in ids:
                reach(v[0])

    for s in save_ids:
        if s in ids:
            reach(s)
    unreachable = sorted(ids - live)
    for n in unreachable:
        errors.append(f"node {n}: unreachable from the declared output node(s)")
    return {"errors": errors, "warnings": warnings, "enum_checked": enums,
            "inputs_checked": checked_inputs, "nodes": len(ids), "unreachable": unreachable}


# ── the wan_shot_v1 contract predicate ────────────────────────────────────────


def wan_contract_violations(doc: dict) -> list[str]:
    """Deliberately broken graphs must fail here; the delivered doc must be clean."""
    out: list[str] = []
    graph = doc.get("graph")
    if not isinstance(graph, dict) or not graph:
        return ["graph section missing/empty"]
    joined = json.dumps(graph)
    if "WanAnimate2Cache" in joined:
        out.append("cache node present although the pinned variant is cache-off")
    for nid in ("672:591", "672:592"):
        node = graph.get(nid)
        if not node or node.get("inputs", {}).get("model") != ["672:588", 0]:
            out.append(f"{nid} must take the model straight from 672:588")
    pad = graph.get("P3B_PAD")
    if not pad or pad.get("class_type") != "ResizeAndPadImage":
        out.append("P3B_PAD ResizeAndPadImage missing")
    else:
        ins = pad.get("inputs", {})
        if ins.get("target_width") != 640 or ins.get("target_height") != 368:
            out.append("P3B_PAD target must be exactly 640x368")
        if ins.get("padding_color") != "black" or ins.get("interpolation") != "area":
            out.append("P3B_PAD must declare black padding + area interpolation")
        if list(ins.get("image", [])) != ["672:595", 0]:
            out.append("P3B_PAD must read the source frames")
    wan = graph.get("672:587", {}).get("inputs", {})
    if wan.get("pose_video") != ["P3B_PAD", 0]:
        out.append("WanAnimate2ToVideo.pose_video must be fed by P3B_PAD")
    size = graph.get("672:596", {}).get("inputs", {})
    if size.get("image") != ["P3B_PAD", 0]:
        out.append("the size authority node must read P3B_PAD")
    for nid in ("672:596", "672:599"):
        if graph.get(nid, {}).get("inputs", {}).get("image") == ["672:600", 0]:
            out.append(f"{nid} still points at the removed portrait node 672:600")
    if "672:600" in graph:
        out.append("node 672:600 (portrait 482x854 crop) must not exist")
    if "482" in joined and "854" in joined:
        out.append("a 482x854 geometry is still referenced")
    if graph.get("672:578", {}).get("inputs", {}).get("unet_name") != UNET:
        out.append("the pinned checkpoint variant must be the INT8 convrot file")
    if graph.get("672:579", {}).get("inputs", {}).get("lora_name") != LORA:
        out.append("the pinned LoRA must be the rank64 distill file")
    sched = graph.get("672:591", {}).get("inputs", {})
    if sched.get("steps") != STEPS or sched.get("scheduler") != "simple":
        out.append("the pinned schedule is 6 steps / simple")
    if graph.get("672:592", {}).get("inputs", {}).get("shift") != SHIFT:
        out.append("the pinned shift is 5")
    if graph.get("672:593", {}).get("inputs", {}).get("sampler_name") != SAMPLER:
        out.append("the pinned sampler is lcm")
    sampler = graph.get("672:597", {}).get("inputs", {})
    if sampler.get("cfg") != CFG:
        out.append("the pinned cfg is 1")
    if not isinstance(sampler.get("noise_seed"), int):
        out.append("the seed must be present as an int")
    if graph.get("672:586", {}).get("inputs", {}).get("context_length") != CONTEXT_LENGTH:
        out.append("the context length must be 21")
    if graph.get("672:586", {}).get("inputs", {}).get("context_overlap") != CONTEXT_OVERLAP:
        out.append("the context overlap must be 8")
    for nid in ("246", "292"):
        if graph.get(nid, {}).get("inputs", {}).get("filename_prefix") != SAVE_PREFIX:
            out.append(f"save node {nid} must carry the declared prefix")
    claims = doc.get("claims", {})
    if claims.get("quality_accepted") is not False:
        out.append("claims.quality_accepted must be false (QUALITY_ACCEPTED=0)")
    return out


def case_rows(doc: dict) -> dict:
    return {c["case_id"]: c for c in doc.get("cases", [])}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024 * 4), b""):
            h.update(chunk)
    return h.hexdigest()


def _doc() -> dict:
    return _load(GRAPH_PATH)


def _manifest() -> dict:
    return _load(MANIFEST_PATH)


def _profiles() -> dict:
    return _load(PROFILES_PATH)


# ── micro repro ───────────────────────────────────────────────────────────────


def test_micro_repro_files_exist_and_parse() -> None:
    for path in (GRAPH_PATH, MANIFEST_PATH, PROFILES_PATH):
        assert path.is_file(), f"missing {path}"
        assert json.loads(path.read_text(encoding="utf-8"))


def test_micro_repro_declared_sections_present() -> None:
    doc = _doc()
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["graph_id"] == GRAPH_ID
    for section in ("derived_from", "runtime_pin", "checkpoint_variant", "parameters",
                    "cases", "frame_mapping", "failure_taxonomy", "output_contract",
                    "claims", "graph", "node_roles"):
        assert section in doc, f"missing section {section}"
    man = _manifest()
    assert man["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert man["graph_id"] == GRAPH_ID
    prof = _profiles()
    assert prof["schema_version"] == PROFILES_SCHEMA_VERSION


def test_micro_repro_node_count_and_save_nodes() -> None:
    doc = _doc()
    graph = doc["graph"]
    assert len(graph) == 63
    saves = [nid for nid, n in graph.items() if n.get("class_type") == "SaveVideo"]
    assert saves == ["246", "292"]
    assert set(doc["node_roles"]) == set(graph)


# ── structural acceptance ─────────────────────────────────────────────────────


def test_graph_structure_valid_without_object_info() -> None:
    res = validate_graph(_doc()["graph"], None, ("246", "292"))
    assert res["errors"] == []
    assert res["nodes"] == 63


def test_graph_uses_only_the_frozen_registered_classes() -> None:
    classes = {n["class_type"] for n in _doc()["graph"].values()}
    assert classes == DELIVERED_GRAPH_CLASSES
    assert classes <= CLASS_SET


def test_graph_validates_against_the_live_pinned_object_info() -> None:
    if not OBJECT_INFO_PIN.is_file():
        pytest.skip("pinned /object_info dump not present")
    res = validate_graph(_doc()["graph"], _load(OBJECT_INFO_PIN), ("246", "292"))
    assert res["errors"] == []
    assert res["unreachable"] == []
    assert res["enum_checked"] > 0


def test_graph_delivered_passes_the_contract_predicate() -> None:
    assert wan_contract_violations(_doc()) == []


# ── pinned variant / run-graph equivalence ────────────────────────────────────


def test_pinned_variant_is_cache_off_wiring() -> None:
    graph = _doc()["graph"]
    assert "672:594" not in graph
    assert graph["672:591"]["inputs"]["model"] == ["672:588", 0]
    assert graph["672:592"]["inputs"]["model"] == ["672:588", 0]
    assert graph["672:588"]["class_type"] == "ComfySwitchNode"


def test_graph_equals_the_run_graph_modulo_the_prefix_knob() -> None:
    run_graph_path = PROOF_ROOT / "graphs" / "animate2_book.p6nocache.api.json"
    if not run_graph_path.is_file():
        pytest.skip("proof run graph not present on this host")
    run_graph = _load(run_graph_path)
    delivered = _copy.deepcopy(_doc()["graph"])
    differing = [
        k for k in run_graph
        if json.dumps(run_graph[k], sort_keys=True) != json.dumps(delivered[k], sort_keys=True)
    ]
    assert sorted(differing) == ["246", "292"]
    delivered["246"]["inputs"]["filename_prefix"] = run_graph["246"]["inputs"]["filename_prefix"]
    delivered["292"]["inputs"]["filename_prefix"] = run_graph["292"]["inputs"]["filename_prefix"]
    assert json.dumps(delivered, sort_keys=True) == json.dumps(run_graph, sort_keys=True)


def test_manifest_graph_hash_equals_delivered_bytes() -> None:
    man = _manifest()
    assert man["workflow"]["graph_file"] == "app/media_workflows/wan_shot_v1.json"
    assert man["workflow"]["graph_file_sha256"] == _sha256_file(GRAPH_PATH)
    assert man["workflow"]["graph_file_bytes"] == GRAPH_PATH.stat().st_size
    assert man["workflow"]["node_count"] == 63
    assert man["workflow"]["template_sha256"] == TEMPLATE_SHA
    assert man["workflow"]["accepted_predecessor_graph"]["sha256"] == PREDECESSOR_GRAPH_SHA
    assert man["workflow"]["pinned_variant_graph"]["sha256"] == RUN_GRAPH_SHA


# ── geometry pin ──────────────────────────────────────────────────────────────


def test_geometry_pad_feeds_pose_and_size() -> None:
    graph = _doc()["graph"]
    pad = graph["P3B_PAD"]
    assert pad["class_type"] == "ResizeAndPadImage"
    assert pad["inputs"]["image"] == ["672:595", 0]
    assert (pad["inputs"]["target_width"], pad["inputs"]["target_height"]) == (640, 368)
    assert graph["672:587"]["inputs"]["pose_video"] == ["P3B_PAD", 0]
    assert graph["672:587"]["inputs"]["width"] == ["672:596", 0]
    assert graph["672:587"]["inputs"]["height"] == ["672:596", 1]
    assert graph["672:596"]["inputs"]["image"] == ["P3B_PAD", 0]
    assert graph["672:599"]["inputs"]["image"] == ["P3B_PAD", 0]


def test_portrait_resize_node_is_gone() -> None:
    joined = json.dumps(_doc()["graph"])
    assert "672:600" not in _doc()["graph"]
    assert "482" not in joined or "854" not in joined


def test_frame_mapping_is_exact() -> None:
    fm = _doc()["frame_mapping"]
    segs = {s["unit"]: s for s in fm["segments"]}
    assert segs["BOOK"]["source_span"] == [0, 120] and segs["BOOK"]["output_span"] == [0, 120]
    assert segs["TURN"]["source_span"] == [0, 120] and segs["TURN"]["output_span"] == [0, 120]
    assert segs["OCC_SEG1"]["source_span"] == [0, 102]
    assert segs["OCC_SEG1"]["output_span"] == [0, 102]
    assert segs["OCC_SEG2"]["source_span"] == [102, 120]
    assert segs["OCC_SEG2"]["output_span"] == [0, 18]
    assert fm["cut_map"]["OCC"]["cut_frames"] == [102]
    assert fm["assembly"]["total_frames"] == 360
    assert sum(s["frames"] for s in fm["segments"]) == 360
    assert fm["assembly"]["order"] == ["BOOK", "TURN", "OCC_SEG1", "OCC_SEG2"]


def test_pad_policy_and_chunk_semantics_declared() -> None:
    fm = _doc()["frame_mapping"]
    assert "4 rows top" in fm["timebase"]["pad"] and "4 rows bottom" in fm["timebase"]["pad"]
    assert fm["timebase"]["source_dims_wh"] == [640, 360]
    assert fm["timebase"]["output_dims_wh"] == [640, 368]
    assert "does NOT crop" in fm["assembly"]["note"]
    chunk = fm["chunk_semantics"]
    assert chunk["context_length"] == CONTEXT_LENGTH and chunk["context_overlap"] == CONTEXT_OVERLAP
    assert "4n+1" in chunk["node_shape"]
    assert "pixel-identical" in chunk["overlap_inert_measured"]


# ── checkpoint variant + models ───────────────────────────────────────────────


def test_checkpoint_variant_pin() -> None:
    graph = _doc()["graph"]
    assert graph["672:578"]["inputs"]["unet_name"] == UNET
    assert graph["672:579"]["inputs"]["lora_name"] == LORA
    assert graph["672:580"]["inputs"]["clip_name"] == TEXT_ENCODER
    assert graph["672:583"]["inputs"]["clip_name"] == CLIP_VISION
    assert graph["672:584"]["inputs"]["vae_name"] == VAE_FILE
    assert graph["672:578"]["inputs"]["weight_dtype"] == "default"
    assert graph["672:597"]["inputs"]["noise_seed"] == 582699151003550


def test_models_table_binds_measured_full_hashes_and_licenses() -> None:
    models = {m["file"]: m for m in _manifest()["models"]}
    for name, sha in MODEL_SHAS.items():
        assert name in models, f"model row missing: {name}"
        row = models[name]
        assert row["sha256"] == sha
        assert row["license"] == "apache-2.0"
        assert row["source"]["hf_lfs_oid_equals_measured_sha256"] is True
        assert row["source"]["repo"] in (
            "Comfy-Org/Wan-Animate-2", "Comfy-Org/Wan_2.1_ComfyUI_repackaged")
    assert models[UNET]["role"] == "unet"
    assert models[CHALLENGER_UNET]["source"]["repo"] == "Comfy-Org/Wan_2.1_ComfyUI_repackaged"


# ── case binding ──────────────────────────────────────────────────────────────


def test_cases_bind_the_frozen_sources_and_anchors() -> None:
    rows = case_rows(_doc())
    assert set(rows) == {"BOOK", "TURN", "OCC_SEG1", "OCC_SEG2"}
    assert rows["BOOK"]["source"]["sha256"] == SOURCE_SHAS["BOOK"]
    assert rows["TURN"]["source"]["sha256"] == SOURCE_SHAS["TURN"]
    assert rows["OCC_SEG1"]["source"]["sha256"] == SOURCE_SHAS["OCC_SEG1"]
    assert rows["OCC_SEG2"]["source"]["sha256"] == SOURCE_SHAS["OCC_SEG2"]
    assert rows["BOOK"]["anchor"]["sha256"] == ANCHOR_SHAS["BOOK"]
    assert rows["TURN"]["anchor"]["sha256"] == ANCHOR_SHAS["TURN"]
    assert rows["OCC_SEG1"]["anchor"]["sha256"] == ANCHOR_SHAS["OCC_SEG1"]
    assert rows["OCC_SEG2"]["anchor"]["sha256"] == ANCHOR_SHAS["OCC_SEG2"]
    assert rows["OCC_SEG1"]["source"]["frames"] == 102
    assert rows["OCC_SEG2"]["source"]["frames"] == 18


def test_cases_bind_prompts_seeds_graphs_and_receipts() -> None:
    rows = case_rows(_doc())
    for case_id in ("BOOK", "TURN", "OCC_SEG1", "OCC_SEG2"):
        assert rows[case_id]["prompt_sha256"] == PROMPT_SHAS[case_id]
        assert rows[case_id]["graph_evidence"]["sha256"]
        assert rows[case_id]["receipt"]["prompt_id"]
        assert rows[case_id]["receipt"]["cache"] in ("on", "off")
        assert rows[case_id]["output_main"]["sha256"]
    assert rows["BOOK"]["seed"] == 582699151003550
    assert rows["BOOK"]["output_main"]["sha256"] == OUTPUT_SHAS["BOOK"]
    assert rows["TURN"]["output_main"]["sha256"] == OUTPUT_SHAS["TURN"]
    assert rows["OCC_SEG1"]["output_main"]["sha256"] == OUTPUT_SHAS["OCC_SEG1"]
    assert rows["OCC_SEG2"]["output_main"]["sha256"] == OUTPUT_SHAS["OCC_SEG2"]
    assert rows["BOOK"]["pinned_variant_run"]["sha256"] == OUTPUT_SHAS["BOOK_PINNED_VARIANT"]


def test_manifest_golden_runs_cover_every_accepted_artifact() -> None:
    man = _manifest()
    runs = {r["case"]: r for r in man["golden_runs"]}
    assert runs["BOOK"]["output_main_sha256"] == OUTPUT_SHAS["BOOK"]
    assert runs["TURN"]["output_main_sha256"] == OUTPUT_SHAS["TURN"]
    assert runs["OCC_SEG1"]["output_main_sha256"] == OUTPUT_SHAS["OCC_SEG1"]
    assert runs["OCC_SEG2"]["output_main_sha256"] == OUTPUT_SHAS["OCC_SEG2"]
    assert runs["ASSEMBLY_v13"]["output_main_sha256"] == OUTPUT_SHAS["ASSEMBLY"]
    assert runs["VACE_challenger"]["output_main_sha256"] == OUTPUT_SHAS["VACE"]
    assert runs["BOOK_pinned_variant"]["output_main_sha256"] == OUTPUT_SHAS["BOOK_PINNED_VARIANT"]
    for row in runs.values():
        assert row["prompt_id"], f"run {row['case']} lost its prompt_id"


def test_inputs_frozen_bind_the_source_windows() -> None:
    frozen = _manifest()["inputs_frozen"]
    got = {row["rel"]: row["sha256"] for row in frozen["sources"]}
    assert got["inputs/BOOK_src.mp4"] == SOURCE_SHAS["BOOK"]
    assert got["inputs/TURN_795_src.mp4"] == SOURCE_SHAS["TURN"]
    assert got["inputs/OCC_14768_src.mp4"] == SOURCE_SHAS["OCC_WINDOW"]
    assert got["inputs/p5fix2_occ_seg1.mp4"] == SOURCE_SHAS["OCC_SEG1"]
    assert got["inputs/p5fix2_occ_seg2.mp4"] == SOURCE_SHAS["OCC_SEG2"]
    anchors = {row["rel"]: row["sha256"] for row in frozen["anchors"]}
    assert anchors["inputs/anchor_book_p2_00001_.png"] == ANCHOR_SHAS["BOOK"]
    assert anchors["inputs/anchor_occ_seg2_p5fix2_00001_.png"] == ANCHOR_SHAS["OCC_SEG2"]
    staging = frozen["assembly_staging"]
    assert len(staging) == 4 and all(row["sha256"] == row["byte_identical_to"] for row in staging)


# ── measurement + accepted cost ───────────────────────────────────────────────


def test_cost_table_arithmetic_matches_receipts() -> None:
    cost = _manifest()["measurement"]["cost_table"]
    for key, (wall, rate, vram) in COST_TABLE.items():
        assert key in cost, f"missing cost row {key}"
        assert cost[key]["server_side_wall_s"] == wall
        assert cost[key]["s_per_output_second"] == rate
        assert cost[key]["vram_peak_mib"] == vram
    assert abs(cost["wan_cache_on_warm"]["server_side_wall_s"] / 4.0 - 38.67) < 0.01
    assert abs(cost["wan_cache_off_warm"]["server_side_wall_s"] / 4.0 - 33.8) < 0.01
    assert cost["wan_cold"]["s_per_output_second"] == 596.95
    assert cost["wan_cold"]["second_recorded_wall"]["s_per_output_second"] == 598.58
    assert cost["vace_14b_fp16"]["s_per_output_second"] == 291.13
    peaks = _manifest()["measurement"]["vram_summary"]["per_run_peaks_mib"]
    assert peaks["p3b_cache_on"] == 10973
    assert peaks["p6_cache_off"] == 10763
    assert peaks["p5_overlap16"] == 11224


def test_determinism_and_ram_are_reported_honestly() -> None:
    m = _manifest()["measurement"]
    assert m["determinism"]["cache_on_vs_off"]["max_abs"] == 0
    assert m["determinism"]["overlap_8_vs_16"]["max_abs"] == 0
    assert m["ram_peak"]["status"] == "NOT_MEASURED"
    assert "never" in m["ram_peak"]["policy"]


def test_accepted_second_cost_is_undefined_not_invented() -> None:
    m = _manifest()["measurement"]["accepted_cost"]
    assert m["accepted_seconds"] == 0
    assert m["cost_per_accepted_second"] == "UNDEFINED"
    assert _doc()["claims"]["quality_accepted"] is False
    assert _manifest()["claims"]["quality_accepted"] is False
    assert _profiles()["claims"]["quality_accepted"] is False


# ── profiles ──────────────────────────────────────────────────────────────────


def test_profiles_separate_benchmark_from_eligibility() -> None:
    prof = _profiles()
    assert len(prof["profiles"]) == 2
    ids = {p["id"]: p for p in prof["profiles"]}
    wan = ids["wan_animate2_int8_pad640x368_cacheoff"]
    vace = ids["vace_14b_fp16_book"]
    assert wan["benchmark"]["status"] == "COMPLETE"
    assert wan["eligibility"]["status"] == "ELIGIBLE_PENDING_QUALITY_OWNER"
    assert vace["benchmark"]["status"] == "COMPLETE_TECHNICAL"
    assert vace["eligibility"]["status"] == "INELIGIBLE"
    assert any("watermark" in b.lower() for b in vace["eligibility"]["blockers"])
    assert wan["eligibility"]["hard_gate_rows"], "hard gate rows required"


def test_wan_profile_carries_measured_numbers() -> None:
    wan = {p["id"]: p for p in _profiles()["profiles"]}["wan_animate2_int8_pad640x368_cacheoff"]
    m = wan["measured"]
    assert m["warm_s_per_output_second"] == 38.67
    assert m["cache_off_s_per_output_second"] == 33.8
    assert m["cold_s_per_output_second"] == 596.95
    assert m["ram_peak"] == "NOT_MEASURED"
    assert wan["cost"]["accepted_seconds"] == 0
    assert wan["cost"]["cost_per_accepted_second"] == "UNDEFINED"


def test_selection_is_by_gates_not_by_name_or_time() -> None:
    sel = _profiles()["selection"]
    assert sel["chosen"] == "wan_animate2_int8_pad640x368_cacheoff"
    blob = json.dumps(_profiles()).lower()
    for claim in ("best model", "newest model", "fastest model"):
        assert claim not in blob, f"recency/name claim leaked: {claim}"
    assert _profiles()["claims"]["no_best_newest_claim"] is True


def test_failure_taxonomy_preserves_the_known_defects() -> None:
    rows = {f["id"]: f for f in _doc()["failure_taxonomy"]}
    for fid in ("F1_GEOMETRY_CROP", "F2_PROMPT_CARRYOVER", "F3_SEGMENT_AT_CUT",
                "F4_WATERMARK_COPY", "F5_BOOK_STATE", "F6_RAM_INSTRUMENT",
                "F7_SEAM_FLAG_BOOK", "F8_TURN_TRANSIENT_GLYPH"):
        assert fid in rows, f"missing failure row {fid}"
        assert rows[fid]["evidence"], f"{fid} lost its evidence refs"
    assert rows["F4_WATERMARK_COPY"]["status"] == "OPEN_PRODUCT_BLOCKER"
    assert rows["F1_GEOMETRY_CROP"]["status"] == "FIXED_VERIFIED"


def test_assignment_of_repairs_matches_the_measured_rounds() -> None:
    rows = {f["id"]: f for f in _doc()["failure_taxonomy"]}
    assert "P3 -> P3B" in rows["F1_GEOMETRY_CROP"]["where"]
    assert "P5 -> P5fix" in rows["F2_PROMPT_CARRYOVER"]["where"]
    assert "P5fix2 -> P5fix3" in rows["F3_SEGMENT_AT_CUT"]["where"]


# ── evidence cross-checks (skipped when the run root is absent) ───────────────


def test_reverify_evidence_all_match() -> None:
    if not REVERIFY_RAW.is_file():
        pytest.skip("reverify raw not present")
    d = _load(REVERIFY_RAW)
    assert d["verdict"] == "PASS"
    assert d["mismatches"] == 0
    assert all(row["verdict"] == "MATCH" for row in d["rows"])
    assert d["runtime"]["head_match"] and d["runtime"]["porcelain_clean"]
    assert all(v == "refused" for v in d["ports"].values())


def test_proof_output_bytes_still_match_the_bound_hashes() -> None:
    if not PROOF_ROOT.is_dir():
        pytest.skip("proof root not present")
    pairs = [
        (PROOF_ROOT / "output/p3b/animate2_book_p3b_00001_.mp4", OUTPUT_SHAS["BOOK"]),
        (PROOF_ROOT / "output/p6_book_nocache/animate2_book_nocache_00001_.mp4",
         OUTPUT_SHAS["BOOK_PINNED_VARIANT"]),
        (PROOF_ROOT / "output/p5fix_turn/animate2_turn_p5fix_00001_.mp4", OUTPUT_SHAS["TURN"]),
        (PROOF_ROOT / "output/p5fix2_occ_seg1/animate2_occ_seg1_p5fix2_00001_.mp4",
         OUTPUT_SHAS["OCC_SEG1"]),
        (PROOF_ROOT / "output/p5fix3_occ_seg2/animate2_occ_seg2_p5fix3_00001_.mp4",
         OUTPUT_SHAS["OCC_SEG2"]),
        (PROOF_ROOT / "output/p7/assembly_v13_00001_.mp4", OUTPUT_SHAS["ASSEMBLY"]),
    ]
    for path, want in pairs:
        assert path.is_file(), f"missing {path}"
        assert _sha256_file(path) == want, f"hash drift on {path.name}"


# ── negative controls ─────────────────────────────────────────────────────────


CONTRACT_MUTATIONS = [
    ("pad_target_changed",
     lambda g: g["P3B_PAD"]["inputs"].update({"target_width": 482, "target_height": 854})),
    ("pad_unwired", lambda g: g["672:587"]["inputs"].__setitem__("pose_video", ["672:595", 0])),
    ("size_points_at_dead_node",
     lambda g: g["672:596"]["inputs"].__setitem__("image", ["672:600", 0])),
    ("checkpoint_swap", lambda g: g["672:578"]["inputs"].__setitem__("unet_name", CHALLENGER_UNET)),
    ("steps_changed", lambda g: g["672:591"]["inputs"].__setitem__("steps", 4)),
    ("prefix_diverged",
     lambda g: g["292"]["inputs"].__setitem__("filename_prefix", "other/prefix")),
    ("seed_removed", lambda g: g["672:597"]["inputs"].pop("noise_seed", None)),
    ("context_changed", lambda g: g["672:586"]["inputs"].__setitem__("context_overlap", 16)),
    ("lora_swapped",
     lambda g: g["672:579"]["inputs"].__setitem__("lora_name", "some_other_lora.safetensors")),
]


@pytest.mark.parametrize("name,mutate", CONTRACT_MUTATIONS, ids=[m[0] for m in CONTRACT_MUTATIONS])
def test_negative_control_contract_refusals(name: str, mutate) -> None:
    doc = _copy.deepcopy(_doc())
    mutate(doc["graph"])
    assert wan_contract_violations(doc), f"mutation {name} was NOT refused"
    assert wan_contract_violations(_doc()) == [], "the delivered doc must stay clean"


def test_negative_control_cache_node_readded() -> None:
    doc = _copy.deepcopy(_doc())
    doc["graph"]["672:594"] = {
        "class_type": "WanAnimate2Cache",
        "inputs": {"device": "gpu", "dtype": "int8", "model": ["672:588", 0]},
    }
    assert wan_contract_violations(doc)


def test_negative_control_cache_rewire_without_node() -> None:
    doc = _copy.deepcopy(_doc())
    doc["graph"]["672:591"]["inputs"]["model"] = ["672:594", 0]
    assert wan_contract_violations(doc)


STRUCTURAL_NEGATIVES = [
    ("dangling_link", lambda g: g["246"]["inputs"].__setitem__("video", ["9999", 0])),
    ("cycle", lambda g: g["672:578"]["inputs"].__setitem__("unet_name", ["672:579", 0])),
    ("unreachable_node",
     lambda g: g.__setitem__("ORPHAN", {"class_type": "PrimitiveInt", "inputs": {"value": 1}})),
]


@pytest.mark.parametrize(
    "name,mutate", STRUCTURAL_NEGATIVES, ids=[m[0] for m in STRUCTURAL_NEGATIVES]
)
def test_negative_control_validator_refusals_without_object_info(name: str, mutate) -> None:
    graph = _copy.deepcopy(_doc()["graph"])
    mutate(graph)
    res = validate_graph(graph, None, ("246", "292"))
    assert res["errors"], f"structural mutation {name} was NOT refused"


def _stub_object_info() -> dict:
    """All delivered classes present; only SaveVideo/KSamplerSelect carry real constraints."""
    stub: dict = {c: {"input": {"required": {}}} for c in DELIVERED_GRAPH_CLASSES}
    stub["SaveVideo"] = {"input": {"required": {
        "video": ["VIDEO"], "filename_prefix": ["STRING", {"default": ""}]}}}
    stub["KSamplerSelect"] = {"input": {"required": {
        "sampler_name": [["lcm", "euler", "ddim"]]}}}
    return stub


def test_negative_control_missing_required_input_is_refused() -> None:
    graph = _copy.deepcopy(_doc()["graph"])
    graph["246"]["inputs"].pop("video")
    res = validate_graph(graph, _stub_object_info(), ("246", "292"))
    assert any("missing required input" in e for e in res["errors"])


def test_negative_control_bad_enum_is_refused() -> None:
    graph = _copy.deepcopy(_doc()["graph"])
    graph["672:593"]["inputs"]["sampler_name"] = "totally_not_a_sampler"
    res = validate_graph(graph, _stub_object_info(), ("246", "292"))
    assert any("sampler_name" in e and "not in" in e for e in res["errors"])


def test_negative_control_unknown_class_is_refused() -> None:
    graph = _copy.deepcopy(_doc()["graph"])
    graph["246"]["class_type"] = "TotallyUnknownNode"
    res = validate_graph(graph, _stub_object_info(), ("246", "292"))
    assert any("not in /object_info" in e for e in res["errors"])


def test_negative_control_unregistered_task_nodes_are_refused() -> None:
    object_info = {"PrimitiveInt": {"input": {"required": {"value": ["INT", {"default": 0}]}}}}
    for class_name in ("Flux2KleinEditModel/Apply", "TrackToMask", "Sam2Segmentation"):
        graph = {"1": {"class_type": class_name, "inputs": {}}}
        res = validate_graph(graph, object_info, ("1",))
        assert any("not in /object_info" in e for e in res["errors"])


def _profile_doc_ok(prof: dict) -> bool:
    blob = json.dumps(prof).lower()
    if any(t in blob for t in ("best model", "newest model", "fastest model")):
        return False
    for p in prof["profiles"]:
        cost = p["cost"]
        if cost["accepted_seconds"] == 0 and cost["cost_per_accepted_second"] != "UNDEFINED":
            return False
        if p["id"] == "vace_14b_fp16_book" and p["eligibility"]["status"] == "ELIGIBLE":
            return False
    return True


def test_negative_control_profile_claims_are_refused() -> None:
    prof = _profiles()
    # a fabricated denominator with zero accepted seconds must be refused
    bad = _copy.deepcopy(prof)
    bad["profiles"][0]["cost"]["cost_per_accepted_second"] = 33.8
    assert not _profile_doc_ok(bad)
    # VACE marked eligible must be refused
    bad2 = _copy.deepcopy(prof)
    bad2["profiles"][1]["eligibility"]["status"] = "ELIGIBLE"
    assert not _profile_doc_ok(bad2)
    # a best-model claim must be refused
    bad3 = _copy.deepcopy(prof)
    bad3["selection"]["rationale"] = "chosen because it is the best model"
    assert not _profile_doc_ok(bad3)
    assert _profile_doc_ok(prof), "the delivered profile doc must pass its own predicate"
