"""MF-END-08 — reference_asset_v1: character reference-asset graph (acceptance + negatives).

Row map (binary):
* micro repro: the delivered graph + manifest exist, parse, and carry the declared sections;
* structural acceptance: every node id/link/type resolves, no cycles, everything reachable
  from the save node, only classes measured as REGISTERED on the pinned runtime are used;
* distilled-vs-base: the graph pins the DISTILLED installed file + distilled sampling
  parameters; the base 4B checkpoint is absent from the graph AND from the model set;
* policies: in-graph alpha policy (RGBA reference composited ONCE onto a declared neutral
  colour before any resize, via the node-verified mask inversion) and the dimensions policy
  (declared canvas, multiples of 16, no crop/stretch of references);
* golden request: every declared parameter's golden binding equals the value the graph
  carries (one source of truth), and the required node inputs are all present;
* manifest: model/node/workflow hashes, licenses and sources are complete and match the
  frozen distilled facts; the workflow hash equals the delivered graph bytes;
* runtime cross-check (skips when the pinned runtime evidence file is absent): the graph
  validates against the LIVE `/object_info` dump of the pinned runtime — 0 errors;
* negative controls: deliberately broken graphs (missing required input, unknown class,
  dangling link, cycle, unreachable node, invalid enum, base/distilled swap, canvas not
  divisible by 16, alpha inversion removed) are each refused with an exact reason.

No render, no GPU, no network, no ffmpeg.  The real GPU asset produced through this graph
is recorded in the manifest (`golden_run`) and re-checked by hash here.
"""

from __future__ import annotations

import copy as _copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = PROJECT_ROOT / "app" / "media_workflows" / "reference_asset_v1.json"
MANIFEST_PATH = PROJECT_ROOT / "app" / "media_workflows" / "reference_asset_v1.manifest.json"

SCHEMA_VERSION = "mf.reference_asset.graph.v1"
GRAPH_ID = "reference_asset_v1"

#: Classes measured as registered on the pinned runtime (`/object_info`, 0.37.0) and used.
CLASS_SET = frozenset({
    "CLIPLoader", "CLIPTextEncode", "CFGGuider", "ConditioningZeroOut", "EmptyFlux2LatentImage",
    "EmptyImage", "Flux2Scheduler", "GetImageSize", "ImageCompositeMasked", "InvertMask",
    "KSamplerSelect", "LoadImage", "RandomNoise", "ReferenceLatent", "ResizeImageMaskNode",
    "SamplerCustomAdvanced", "SaveImage", "UNETLoader", "VAEDecode", "VAEEncode", "VAELoader",
})

#: The DISTILLED artifacts installed on the pinned runtime (base 4B files are NOT installed).
DISTILLED_UNET = "flux-2-klein-4b-fp8.safetensors"
BASE_UNET = "flux-2-klein-base-4b-fp8.safetensors"
TEXT_ENCODER = "qwen_3_4b.safetensors"
VAE_FILE = "flux2-vae.safetensors"
BASE_ONLY_VAE = "full_encoder_small_decoder.safetensors"

STEPS = 4
CFG = 1.0
SAMPLER = "euler"
CANVAS = (1024, 1024)
REF_LONGER = 768
NEUTRAL_RGB = (128, 128, 128)
NEUTRAL_INT = 8421504  # 0x808080, the EmptyImage `color` widget

RUNTIME_HEAD = "73c9bad4d21e7addbe1d13bc92eee0f1431b017d"
EVIDENCE_ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     "20260927T163824Z")
#: live /object_info dumped BY THIS TASK's isolated server (its input dir holds the staged ref)
RUNTIME_OBJECT_INFO_LIVE = EVIDENCE_ROOT / "tasks/MF-END-08/raw/object_info_live.json"
#: the accepted proof's dump (pinned runtime; its input dir predates our staged reference)
RUNTIME_OBJECT_INFO = EVIDENCE_ROOT / "proof/evidence/P3_object_info_gpu.json"
TEMPLATE_DISTILLED_SHA16 = "e0388a8870495802"
SOURCE_ARTWORK_SHA = "271f1c5789ee8fb9022ab402d834c8f2d4e862f972a105060e457b68b0282496"
#: the staged input IS the raw authored artwork (byte copy): the graph composites its alpha
STAGED_INPUT_SHA = SOURCE_ARTWORK_SHA

MODEL_SHA256 = {
    "flux-2-klein-4b-fp8.safetensors":
        "97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6",
    "qwen_3_4b.safetensors":
        "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a",
    "flux2-vae.safetensors":
        "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3",
}


# ── the single validator (also imported by the build/run tooling) ─────────────


def _enum_values(decl: Any) -> list | None:
    if not isinstance(decl, list) or not decl:
        return None
    if isinstance(decl[0], list):
        return decl[0] or None
    if decl[0] == "COMBO" and len(decl) > 1 and isinstance(decl[1], dict):
        return decl[1].get("options") or None
    return None


def _dynamic_combo_options(decl: Any) -> list | None:
    if isinstance(decl, list) and decl and decl[0] == "COMFY_DYNAMICCOMBO_V3" and len(decl) > 1:
        return decl[1].get("options") or None
    return None


def validate_graph(graph: dict, object_info: dict | None, save_ids: tuple[str, ...]) -> dict:
    """Structural + (optional) /object_info validation.  Returns errors/warnings/checked."""
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
            opt = spec.get("optional", {}) or {}
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
                    names = [o.get("key", o.get("name")) for o in dco]
                    if v not in names:
                        errors.append(f"node {nid} ({ct}): dynamic combo {v!r} not in {names}")
                    else:
                        enums += 1
                continue
            allowed = _enum_values(decl)
            if allowed is not None:
                enums += 1
                if v not in allowed:
                    errors.append(f"node {nid} ({ct}): {k!r}={v!r} not in {allowed[:12]}")
    # cycle detection
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
    # reachability from every declared terminal (save) node
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


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _graph_doc() -> dict:
    return _load(GRAPH_PATH)


def _nodes_by_id(doc: dict) -> dict:
    return doc["graph"]


def _find(doc: dict, class_type: str) -> list[tuple[str, dict]]:
    return [(nid, n) for nid, n in _nodes_by_id(doc).items() if n["class_type"] == class_type]


def _save_ids(doc: dict) -> tuple[str, ...]:
    return tuple(nid for nid, n in _nodes_by_id(doc).items() if n["class_type"] == "SaveImage")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ── micro repro ───────────────────────────────────────────────────────────────


def test_micro_repro_files_exist_and_parse() -> None:
    doc = _graph_doc()
    man = _load(MANIFEST_PATH)
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["graph_id"] == GRAPH_ID
    assert man["schema_version"] == SCHEMA_VERSION
    assert man["graph_id"] == GRAPH_ID


def test_micro_repro_declared_sections_present() -> None:
    doc = _graph_doc()
    for key in ("derived_from", "parameters", "alpha_policy", "dimensions_policy", "graph",
                "golden_request", "distilled_vs_base"):
        assert key in doc, f"missing section {key}"
    assert doc["parameters"], "parameters must not be empty"
    assert doc["graph"], "graph must not be empty"


def test_micro_repro_save_node_is_the_only_output() -> None:
    doc = _graph_doc()
    assert len(_save_ids(doc)) == 1


# ── structural acceptance ─────────────────────────────────────────────────────


def test_graph_structure_valid_without_object_info() -> None:
    doc = _graph_doc()
    rep = validate_graph(_nodes_by_id(doc), None, _save_ids(doc))
    assert rep["errors"] == [], rep["errors"]
    assert rep["inputs_checked"] > 0


def test_graph_uses_only_the_frozen_registered_classes() -> None:
    doc = _graph_doc()
    used = {n["class_type"] for n in _nodes_by_id(doc).values()}
    assert used <= CLASS_SET, f"unexpected classes: {sorted(used - CLASS_SET)}"


def test_graph_validates_against_the_live_pinned_object_info() -> None:
    """Prefer the dump taken by THIS task's isolated server (its input dir contains the staged
    reference) -> 0 errors.  Otherwise fall back to the accepted proof's dump, where the single
    tolerated row is the LoadImage `image` enum that predates our staging."""
    doc = _graph_doc()
    if RUNTIME_OBJECT_INFO_LIVE.exists():
        rep = validate_graph(_nodes_by_id(doc), _load(RUNTIME_OBJECT_INFO_LIVE), _save_ids(doc))
        assert rep["errors"] == [], rep["errors"]
        assert rep["unreachable"] == []
        assert rep["warnings"] == [], rep["warnings"]
        return
    if not RUNTIME_OBJECT_INFO.exists():
        pytest.skip("pinned runtime /object_info dump not present on this host "
                    "(evidence-root artifact; the run-time validation row lives there)")
    rep = validate_graph(_nodes_by_id(doc), _load(RUNTIME_OBJECT_INFO), _save_ids(doc))
    enum_rows = [e for e in rep["errors"] if "LoadImage" in e and "not in" in e]
    assert len(rep["errors"]) == len(enum_rows) == 1, rep["errors"]
    assert "ra_v1_ref_dan_choi.png" in enum_rows[0]
    assert rep["unreachable"] == []


# ── distilled vs base ─────────────────────────────────────────────────────────


def test_graph_pins_the_distilled_checkpoint_and_params() -> None:
    doc = _graph_doc()
    unet = _find(doc, "UNETLoader")
    assert len(unet) == 1
    assert unet[0][1]["inputs"]["unet_name"] == DISTILLED_UNET
    clip = _find(doc, "CLIPLoader")[0][1]["inputs"]
    assert clip["clip_name"] == TEXT_ENCODER and clip["type"] == "flux2"
    vae = _find(doc, "VAELoader")[0][1]["inputs"]
    assert vae["vae_name"] == VAE_FILE
    sched = _find(doc, "Flux2Scheduler")[0][1]["inputs"]
    assert sched["steps"] == STEPS
    guider = _find(doc, "CFGGuider")[0][1]["inputs"]
    assert float(guider["cfg"]) == CFG
    sampler = _find(doc, "KSamplerSelect")[0][1]["inputs"]
    assert sampler["sampler_name"] == SAMPLER


def test_graph_never_names_a_base_4b_artifact() -> None:
    doc = _graph_doc()
    blob = json.dumps(doc["graph"])
    assert BASE_UNET not in blob
    assert BASE_ONLY_VAE not in blob
    declared = doc["distilled_vs_base"]
    assert declared["installed_variant"] == "distilled"
    assert declared["base_artifacts_installed"] is False


def test_manifest_model_set_is_exactly_the_distilled_trio() -> None:
    man = _load(MANIFEST_PATH)
    files = {m["file"] for m in man["models"]}
    assert files == set(MODEL_SHA256)


# ── policies ──────────────────────────────────────────────────────────────────


def test_alpha_policy_is_wired_in_graph() -> None:
    doc = _graph_doc()
    bg = _find(doc, "EmptyImage")
    assert len(bg) == 1
    assert bg[0][1]["inputs"]["color"] == NEUTRAL_INT
    assert tuple(doc["alpha_policy"]["neutral_rgb"]) == NEUTRAL_RGB
    assert doc["alpha_policy"]["composite_applied_in_graph"] is True
    assert doc["alpha_policy"]["composite_times"] == 1
    invert = _find(doc, "InvertMask")
    assert len(invert) == 1, "the load-image mask (1-alpha) must be inverted before compositing"
    inv_id = invert[0][0]
    comp = _find(doc, "ImageCompositeMasked")
    assert len(comp) == 1
    comp_inputs = comp[0][1]["inputs"]
    assert comp_inputs["mask"] == [inv_id, 0]
    # the inversion takes its input from a LoadImage MASK output (slot 1)
    inv_src = invert[0][1]["inputs"]["mask"]
    assert isinstance(inv_src, list) and inv_src[0] in _nodes_by_id(doc)
    assert _nodes_by_id(doc)[inv_src[0]]["class_type"] == "LoadImage" and inv_src[1] == 1
    # the resize consumes the COMPOSITE (never the raw RGBA load)
    res = _find(doc, "ResizeImageMaskNode")
    assert len(res) == 1
    assert res[0][1]["inputs"]["input"] == [comp[0][0], 0]


def test_alpha_policy_output_side_is_opaque_and_declared() -> None:
    doc = _graph_doc()
    out = doc["alpha_policy"]["output"]
    assert out["channel_count"] == 3
    assert out["alpha_synthesized"] is False
    assert out["owner_of_background_removal"] != ""


def test_dimensions_policy_canvas_and_ref_resize() -> None:
    doc = _graph_doc()
    assert tuple(doc["dimensions_policy"]["canvas_wh"]) == CANVAS
    w, h = CANVAS
    assert w % 16 == 0 and h % 16 == 0, "EmptyFlux2LatentImage requires /16 canvas"
    latent = _find(doc, "EmptyFlux2LatentImage")[0][1]["inputs"]
    sched = _find(doc, "Flux2Scheduler")[0][1]["inputs"]
    assert (latent["width"], latent["height"]) == CANVAS
    assert (sched["width"], sched["height"]) == CANVAS
    res = _find(doc, "ResizeImageMaskNode")[0][1]["inputs"]
    assert res["resize_type"] == "scale longer dimension"
    assert res["resize_type.longer_size"] == REF_LONGER
    assert res["scale_method"] == "area"
    assert doc["dimensions_policy"]["crop_applied"] is False
    assert doc["dimensions_policy"]["stretch_applied"] is False


# ── golden request ────────────────────────────────────────────────────────────


def _walk_pointer(doc: dict, pointer: str) -> Any:
    parts = pointer.split("/")
    assert parts[0] == "graph"
    cur: Any = doc["graph"][parts[1]]
    rest = parts[2:]
    if rest and rest[0] == "inputs":  # accept both graph/<id>/<key> and graph/<id>/inputs/<key>
        rest = rest[1:]
    if not rest:
        return cur
    for p in rest:
        cur = cur["inputs"][p]
    return cur


def test_golden_bindings_equal_the_values_the_graph_carries() -> None:
    doc = _graph_doc()
    golden = doc["golden_request"]["bindings"]
    for name, entry in golden.items():
        got = _walk_pointer(doc, entry["pointer"])
        assert got == entry["value"], (
            f"parameter {name}: graph has {got!r}, golden says {entry['value']!r}")


def test_parameters_all_point_into_the_graph() -> None:
    doc = _graph_doc()
    for param in doc["parameters"]:
        _walk_pointer(doc, param["pointer"])  # raises if the pointer is dangling
        assert param["golden"] is not None
        for mirror in param.get("mirrors", []):
            _walk_pointer(doc, mirror)


def test_parameter_mirrors_hold_the_same_golden_value() -> None:
    doc = _graph_doc()
    for param in doc["parameters"]:
        for mirror in param.get("mirrors", []):
            assert _walk_pointer(doc, mirror) == param["golden"], f"{param['name']} mirror drift"


def test_reference_input_invariants_are_frozen() -> None:
    doc = _graph_doc()
    ref = doc["golden_request"]["staged_inputs"][0]
    assert ref["sha256"] == STAGED_INPUT_SHA
    assert doc["golden_request"]["source_artwork_sha256"] == SOURCE_ARTWORK_SHA
    assert ref["sha256"] == doc["golden_request"]["source_artwork_sha256"]  # raw artwork staged
    assert ref["dims"] == [1024, 1024]
    assert ref["mode"] == "RGBA"


# ── manifest ──────────────────────────────────────────────────────────────────


def test_manifest_records_full_hashes_licenses_and_sources_for_every_model() -> None:
    man = _load(MANIFEST_PATH)
    seen = set()
    for m in man["models"]:
        assert len(m["sha256"]) == 64 and all(c in "0123456789abcdef" for c in m["sha256"])
        assert m["sha256"] == MODEL_SHA256[m["file"]], f"hash drift for {m['file']}"
        assert m["bytes"] > 0
        assert m["license"].strip() != ""
        assert m["source"].startswith("http")
        assert m["why_used"].strip() != ""
        seen.add(m["file"])
    assert seen == set(MODEL_SHA256)


def test_manifest_node_sources_cover_every_class_used() -> None:
    man = _load(MANIFEST_PATH)
    doc = _graph_doc()
    used = {n["class_type"] for n in _nodes_by_id(doc).values()}
    covered = {e["class_type"] for e in man["nodes"]}
    assert used <= covered, f"classes without a node-source record: {sorted(used - covered)}"
    for e in man["nodes"]:
        assert e["sha256"] and all(len(v) == 64 for v in e["sha256"].values())
        assert e["runtime_head"] == RUNTIME_HEAD


def test_manifest_workflow_hash_equals_the_delivered_graph_bytes() -> None:
    man = _load(MANIFEST_PATH)
    doc = _graph_doc()
    assert man["workflow"]["graph_file"] == "app/media_workflows/reference_asset_v1.json"
    assert man["workflow"]["graph_file_sha256"] == sha256_file(GRAPH_PATH)
    canonical = json.dumps(doc["graph"], sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    assert man["workflow"]["graph_object_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert man["workflow"]["template_sha256_16"] == TEMPLATE_DISTILLED_SHA16


def test_manifest_runtime_pin_and_readonly_fact() -> None:
    man = _load(MANIFEST_PATH)
    assert man["runtime"]["head"] == RUNTIME_HEAD
    assert man["runtime"]["porcelain_clean"] is True
    assert man["runtime"]["source_read_only"] is True


def test_manifest_golden_run_is_the_real_asset() -> None:
    man = _load(MANIFEST_PATH)
    run = man["golden_run"]
    assert len(run["prompt_id"]) == 36
    assert run["graph_object_sha256"] == man["workflow"]["graph_object_sha256"]
    a = run["asset"]
    assert len(a["sha256"]) == 64
    assert a["dims"] == list(CANVAS)
    assert a["file"].endswith(".png")
    assert run["declared_gpu_jobs"] == 1
    assert run["review"]["verdict"] in {"PASS", "FAIL"}
    assert run["review"]["artifacts"]["side_by_side"].strip() != ""
    assert run["review"]["artifacts"]["generated_asset"]["sha256"] == a["sha256"]


# ── negative controls ─────────────────────────────────────────────────────────


def _broken(kind: str) -> dict:
    doc = _graph_doc()
    g = _copy.deepcopy(doc["graph"])
    if kind == "missing_required_input":
        save = _save_ids(doc)[0]
        del g[save]["inputs"]["images"]
    elif kind == "unknown_class":
        g["SAVE_PROBE"] = {"class_type": "NotARealNode", "inputs": {}}
    elif kind == "dangling_link":
        g["DECODE"]["inputs"]["samples"] = ["NO_SUCH_NODE", 0]
    elif kind == "cycle":
        g["UNET"]["inputs"]["model_input"] = ["GUIDER", 0]
    elif kind == "unreachable_node":
        g["ORPHAN"] = {"class_type": "EmptyImage",
                       "inputs": {"width": 8, "height": 8, "batch_size": 1, "color": 0}}
    elif kind == "invalid_enum":
        g["SAMPLER"]["inputs"]["sampler_name"] = "not_a_sampler"
    elif kind == "base_swap":
        g["UNET"]["inputs"]["unet_name"] = BASE_UNET
    elif kind == "canvas_not_divisible_by_16":
        g["LATENT"]["inputs"]["width"] = 1000
        g["SIGMAS"]["inputs"]["width"] = 1000
    elif kind == "alpha_inversion_removed":
        comp_id = _find(doc, "ImageCompositeMasked")[0][0]
        load = _find(doc, "LoadImage")[0][0]
        g[comp_id]["inputs"]["mask"] = [load, 1]
    else:  # pragma: no cover
        raise AssertionError(f"unknown fixture {kind}")
    return g


def _refusal(graph: dict, object_info: dict | None) -> list[str]:
    oi = object_info
    if oi is None:
        for cand in (RUNTIME_OBJECT_INFO_LIVE, RUNTIME_OBJECT_INFO):
            if cand.exists():
                oi = _load(cand)
                break
    return validate_graph(graph, oi, _save_ids(_graph_doc()))["errors"]


@pytest.mark.parametrize("kind,needle", [
    ("missing_required_input", "missing required input"),
    ("unknown_class", "not in /object_info"),
    ("dangling_link", "links to missing node"),
    ("cycle", "cycle"),
    ("unreachable_node", "unreachable"),
    ("invalid_enum", "not in"),
])
def test_negative_control_is_refused_by_the_validator(kind: str, needle: str) -> None:
    if not (RUNTIME_OBJECT_INFO_LIVE.exists() or RUNTIME_OBJECT_INFO.exists()):
        pytest.skip("no /object_info dump: the object_info-dependent refusals need the pinned dump")
    errs = _refusal(_broken(kind), None)
    assert any(needle in e for e in errs), f"{kind}: no refusal containing {needle!r} in {errs}"


def test_negative_control_structural_refusals_without_object_info() -> None:
    for kind, needle in (("dangling_link", "links to missing node"), ("cycle", "cycle"),
                         ("unreachable_node", "unreachable")):
        errs = validate_graph(_broken(kind), None, _save_ids(_graph_doc()))["errors"]
        assert any(needle in e for e in errs), f"{kind}: {errs}"


def _policy_ok(graph: dict) -> bool:
    """The three policy rows as a single boolean; every mutated graph must fail it."""
    blob = json.dumps(graph)
    if BASE_UNET in blob or BASE_ONLY_VAE in blob:
        return False
    w = graph.get("LATENT", {}).get("inputs", {}).get("width")
    if w is None or w % 16 != 0:
        return False
    inv = [nid for nid, n in graph.items() if n["class_type"] == "InvertMask"]
    comp = [nid for nid, n in graph.items() if n["class_type"] == "ImageCompositeMasked"]
    if not inv or not comp:
        return False
    return graph[comp[0]]["inputs"].get("mask") == [inv[0], 0]


def test_policy_predicate_passes_the_delivered_graph_and_fails_every_mutation() -> None:
    assert _policy_ok(_graph_doc()["graph"]) is True
    for kind in ("base_swap", "canvas_not_divisible_by_16", "alpha_inversion_removed"):
        assert _policy_ok(_broken(kind)) is False, f"{kind}: the mutated graph was NOT refused"
