"""MF-END-14 — shot_anchor_v1: target full-scene anchor graph (acceptance + negatives).

Row map (binary):
* micro repro: the delivered graph + manifest exist, parse, and carry the declared sections;
* structural acceptance: every node id/link/type resolves, no cycles, everything reachable
  from the save node, only classes measured as REGISTERED on the pinned runtime are used;
* source-facts binding: the graph keeps the measured facts of the sealed MF-END-13 artifact
  (window BOOK, source sha, holder ROLE-BOOK-P1 -> PROP-BOOK, camera static, no cuts) and
  exposes NO camera/zoom/crop parameter (no new camera is inferred);
* role map: every visible person incl. the partial edge person P4 and the prop carry a
  measured source evidence and an explicit disposition; P4 keeps its partial policy;
* conditioning-only extra references: reference images 2..4 are chained on BOTH positive and
  negative conditioning AFTER the keyframe latent; they never drive canvas or the edit base;
* alpha policy: each of the 4 staged images is composited ONCE through the measured
  mask-inversion path; the output is declared opaque RGB;
* dimensions policy: declared canvas (640x368, /16) equals the staged keyframe geometry; the
  references are aspect-preserving resizes with no crop/stretch;
* distilled pins: the graph pins the DISTILLED installed checkpoint + 4-step/cfg-1 profile;
* golden request: every declared parameter's golden binding equals the value the graph carries
  and the frozen prompt hash equals the frozen constant;
* manifest: model/node/workflow hashes, licenses and sources are complete + the workflow hash
  equals the delivered graph bytes; the real GPU run receipt + tensor-preview equality + the
  overlays for review are recorded (skips when the evidence artifact is absent);
* negative controls: deliberately broken graphs (missing required input, unknown class,
  dangling link, cycle, unreachable node, invalid enum), the task's three UNREGISTERED node
  names, and anchor-contract mutations (canvas /16, alpha inversion, holder swap, partial
  dropped, camera invented, canvas-from-link, base swap) are each refused.

No render, no GPU, no network, no ffmpeg here.  The real anchor produced through this graph is
recorded in the manifest (`golden_run`) and re-checked by hash.
"""

from __future__ import annotations

import copy as _copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = PROJECT_ROOT / "app" / "media_workflows" / "shot_anchor_v1.json"
MANIFEST_PATH = PROJECT_ROOT / "app" / "media_workflows" / "shot_anchor_v1.manifest.json"

SCHEMA_VERSION = "mf.shot_anchor.graph.v1"
GRAPH_ID = "shot_anchor_v1"

#: Classes measured as registered on the pinned runtime (`/object_info`, 0.37.0) and used here.
CLASS_SET = frozenset({
    "CLIPLoader", "CLIPTextEncode", "CFGGuider", "ConditioningZeroOut", "EmptyFlux2LatentImage",
    "EmptyImage", "Flux2Scheduler", "GetImageSize", "ImageCompositeMasked", "InvertMask",
    "KSamplerSelect", "LoadImage", "RandomNoise", "ReferenceLatent", "ResizeImageMaskNode",
    "SamplerCustomAdvanced", "SaveImage", "UNETLoader", "VAEDecode", "VAEEncode", "VAELoader",
})

#: Node names the task explicitly measured as NOT registered — must never be usable here.
UNREGISTERED_NODES = ("Flux2KleinEditModel/Apply", "TrackToMask", "Sam2Segmentation")

DISTILLED_UNET = "flux-2-klein-4b-fp8.safetensors"
BASE_UNET = "flux-2-klein-base-4b-fp8.safetensors"
TEXT_ENCODER = "qwen_3_4b.safetensors"
VAE_FILE = "flux2-vae.safetensors"
BASE_ONLY_VAE = "full_encoder_small_decoder.safetensors"

STEPS = 4
CFG = 1.0
SAMPLER = "euler"
CANVAS = (640, 368)
REF_LONGER = 368
NEUTRAL_RGB = (128, 128, 128)
NEUTRAL_INT = 8421504  # 0x808080, the EmptyImage `color` widget
SEED = 2026092501

#: Frozen constants of the delivered anchor request (measured / build-recorded).
FACTS_DIGEST = "b286377c2ba583dffe19b43dd0fac0530eb8a3b77af4d06aac876c645234191b"
TRACK_DIGEST = "47e327e94d8c3d53d77ac6e5794d1da3c52f6ae35f790a6d4f5d8eacb235492d"
SOURCE_SHA = "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc"
KEYFRAME_FILE = "sa_v1_keyframe_book_f000.png"
KEYFRAME_SHA = "3f0d090a9c022fe136542c9f017b1f7cde40b1f79e80b92541846ed0e0a9c8c0"
REF_FILES = ("sa_v1_ref_p1_boy_hacker.png", "sa_v1_ref_p2_dan_choi.png",
             "sa_v1_ref_p3_gau_nau_back.png")
REF_SHAS = ("a2ad4db98ac733c969260d052f35e737c37eef664b1b36d5a6fd9a7254006821",
            "2ffc245346340b4cc95ffa4c5ac9f3ad3e4485927a655e6a47ab960e5c848969",
            "49e99094d802495dd92e1dbab87125806efcb077f0be37125738b7218a63096f")
PROMPT_SHA256 = "8e48cfbe5d81fad581cc237fd803a7c39039c4633fb89cba27e0c742c9fe0b09"
HOLDER_SUBJECT = "ROLE-BOOK-P1"
HOLDER_OBJECT = "PROP-BOOK"
PARTIAL_ROLE = "ROLE-BOOK-P4-EDGE"
PERSON_ROLES = ("ROLE-BOOK-P1", "ROLE-BOOK-P2", "ROLE-BOOK-P3", PARTIAL_ROLE)

#: Forbidden parameter-name fragments: the anchor may not expose a new camera/geometry control.
FORBIDDEN_PARAM_FRAGMENTS = ("camera", "zoom", "crop", "pan", "letterbox", "resample")

RUNTIME_HEAD = "73c9bad4d21e7addbe1d13bc92eee0f1431b017d"
EVIDENCE_ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     "20260927T163824Z")
#: live /object_info dumped BY THIS task's isolated server (its input dir holds the staged files)
RUNTIME_OBJECT_INFO_LIVE = EVIDENCE_ROOT / "tasks/MF-END-14/raw/object_info_live.json"
#: the accepted proof's dump (pinned runtime; taken BEFORE this task staged its inputs)
RUNTIME_OBJECT_INFO = EVIDENCE_ROOT / "proof/evidence/P3_object_info_gpu.json"

MODEL_SHA256 = {
    "flux-2-klein-4b-fp8.safetensors":
        "97ed34fe0567e436200f2faee3939b88f2b5d99f8af2a4dc16532c4245c0ccb6",
    "qwen_3_4b.safetensors":
        "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a",
    "flux2-vae.safetensors":
        "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3",
}


# ── the single validator (also imported by the run tooling) ───────────────────


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


def save_node_ids(graph: dict) -> tuple[str, ...]:
    return tuple(nid for nid, n in graph.items() if n.get("class_type") == "SaveImage")


# ── helpers ───────────────────────────────────────────────────────────────────


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _graph_doc() -> dict:
    return _load(GRAPH_PATH)


def _nodes_by_id(doc: dict) -> dict:
    return doc["graph"]


def _find(doc: dict, class_type: str) -> list[tuple[str, dict]]:
    return [(nid, n) for nid, n in _nodes_by_id(doc).items() if n["class_type"] == class_type]


def _one(doc: dict, class_type: str) -> dict:
    hits = _find(doc, class_type)
    assert len(hits) == 1, f"expected exactly one {class_type}, got {len(hits)}"
    return hits[0][1]


def _save_ids(doc: dict) -> tuple[str, ...]:
    return save_node_ids(_nodes_by_id(doc))


def _role_map(doc: dict) -> dict:
    return {r["role_id"]: r for r in doc["role_map"]["roles"]}


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
    for key in ("derived_from", "source_facts", "role_map", "parameters", "alpha_policy",
                "dimensions_policy", "graph", "tensor_preview", "golden_request",
                "output_contract"):
        assert key in doc, f"missing section {key}"
    assert doc["parameters"] and doc["graph"]


def test_micro_repro_save_node_is_the_only_output() -> None:
    assert len(_save_ids(_graph_doc())) == 1


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
    """Prefer the dump taken by THIS task's isolated server (its input dir holds the staged
    files) -> 0 errors, 0 warnings.  Otherwise fall back to the accepted proof's dump, where
    the tolerated rows are exactly the LoadImage `image` enums that predate our staging."""
    doc = _graph_doc()
    if RUNTIME_OBJECT_INFO_LIVE.exists():
        rep = validate_graph(_nodes_by_id(doc), _load(RUNTIME_OBJECT_INFO_LIVE), _save_ids(doc))
        assert rep["errors"] == [], rep["errors"]
        assert rep["warnings"] == [], rep["warnings"]
        assert rep["unreachable"] == []
        return
    if not RUNTIME_OBJECT_INFO.exists():
        pytest.skip("pinned runtime /object_info dump not present on this host")
    rep = validate_graph(_nodes_by_id(doc), _load(RUNTIME_OBJECT_INFO), _save_ids(doc))
    enum_rows = [e for e in rep["errors"] if "LoadImage" in e and "not in" in e]
    assert len(rep["errors"]) == len(enum_rows) == 4, rep["errors"]
    for name in (KEYFRAME_FILE, *REF_FILES):
        assert any(name in e for e in enum_rows), f"missing enum row for {name}"
    assert rep["unreachable"] == []


# ── distilled pins ────────────────────────────────────────────────────────────


def test_graph_pins_the_distilled_checkpoint_and_params() -> None:
    doc = _graph_doc()
    assert _one(doc, "UNETLoader")["inputs"]["unet_name"] == DISTILLED_UNET
    clip = _one(doc, "CLIPLoader")["inputs"]
    assert clip["clip_name"] == TEXT_ENCODER and clip["type"] == "flux2"
    assert _one(doc, "VAELoader")["inputs"]["vae_name"] == VAE_FILE
    assert _one(doc, "Flux2Scheduler")["inputs"]["steps"] == STEPS
    assert float(_one(doc, "CFGGuider")["inputs"]["cfg"]) == CFG
    assert _one(doc, "KSamplerSelect")["inputs"]["sampler_name"] == SAMPLER


def test_graph_never_names_a_base_4b_artifact() -> None:
    blob = json.dumps(_graph_doc()["graph"])
    assert BASE_UNET not in blob and BASE_ONLY_VAE not in blob


# ── alpha policy ──────────────────────────────────────────────────────────────


def test_alpha_policy_is_wired_once_per_staged_image() -> None:
    doc = _graph_doc()
    assert doc["alpha_policy"]["composite_applied_in_graph"] is True
    assert doc["alpha_policy"]["composite_times_per_image"] == 1
    assert tuple(doc["alpha_policy"]["neutral_rgb"]) == NEUTRAL_RGB
    g = _nodes_by_id(doc)
    assert len(_find(doc, "InvertMask")) == 4
    assert len(_find(doc, "ImageCompositeMasked")) == 4
    for prefix in ("KEY", "R1", "R2", "R3"):
        load, inv, comp = f"{prefix}_LOAD", f"{prefix}_INV", f"{prefix}_COMP"
        assert g[load]["class_type"] == "LoadImage"
        assert g[inv]["inputs"]["mask"] == [load, 1]  # LoadImage MASK slot (1-alpha)
        ci = g[comp]["inputs"]
        assert ci["mask"] == [inv, 0], f"{comp}: mask must be the inverted load mask"
        assert ci["source"] == [load, 0] and ci["destination"] == [f"{prefix}_BG", 0]
        assert ci["x"] == 0 and ci["y"] == 0 and ci["resize_source"] is False
        bg = g[f"{prefix}_BG"]["inputs"]
        assert bg["color"] == NEUTRAL_INT
        assert bg["width"] == [f"{prefix}_SIZE", 0] and bg["height"] == [f"{prefix}_SIZE", 1]
    # the keyframe latent is encoded from the COMPOSITE (never the raw load)
    assert g["KEY_ENC"]["inputs"]["pixels"] == ["KEY_COMP", 0]
    # the refs resize from the COMPOSITE
    for i in (1, 2, 3):
        assert g[f"R{i}_RES"]["inputs"]["input"] == [f"R{i}_COMP", 0]


def test_alpha_policy_output_side_is_opaque_and_declared() -> None:
    out = _graph_doc()["alpha_policy"]["output"]
    assert out["channel_count"] == 3
    assert out["alpha_synthesized"] is False
    assert out["owner_of_background_removal"].strip() != ""


# ── dimensions policy ─────────────────────────────────────────────────────────


def test_dimensions_policy_canvas_ref_resize_and_layout_pin() -> None:
    doc = _graph_doc()
    assert tuple(doc["dimensions_policy"]["canvas_wh"]) == CANVAS
    w, h = CANVAS
    assert w % 16 == 0 and h % 16 == 0, "EmptyFlux2LatentImage requires /16 canvas"
    latent = _nodes_by_id(doc)["LATENT"]["inputs"]
    sigmas = _nodes_by_id(doc)["SIGMAS"]["inputs"]
    assert (latent["width"], latent["height"]) == (w, h)
    assert (sigmas["width"], sigmas["height"]) == (w, h)
    assert doc["dimensions_policy"]["crop_applied"] is False
    assert doc["dimensions_policy"]["stretch_applied"] is False
    for i in (1, 2, 3):
        res = _nodes_by_id(doc)[f"R{i}_RES"]["inputs"]
        assert res["resize_type"] == "scale longer dimension"
        assert res["resize_type.longer_size"] == REF_LONGER
        assert res["scale_method"] == "area"


def test_canvas_equals_the_staged_keyframe_geometry() -> None:
    doc = _graph_doc()
    key = doc["golden_request"]["staged_inputs"][0]
    assert key["file"] == KEYFRAME_FILE and key["sha256"] == KEYFRAME_SHA
    assert tuple(key["dims"]) == CANVAS, "canvas must be the source keyframe geometry"
    assert key["mode"] == "RGB"


# ── source-facts binding ──────────────────────────────────────────────────────


def test_source_facts_bind_the_sealed_artifact() -> None:
    sf = _graph_doc()["source_facts"]
    assert sf["artifact_schema"] == "mf.source_interaction_facts.v1"
    assert sf["artifact_digest"] == FACTS_DIGEST
    assert sf["track_artifact_digest"] == TRACK_DIGEST
    assert sf["window_id"] == "BOOK"
    assert sf["source_sha256"] == SOURCE_SHA
    assert sf["keyframe"]["sha256"] == KEYFRAME_SHA
    assert sf["holder"]["subject_role_id"] == HOLDER_SUBJECT
    assert sf["holder"]["object_role_id"] == HOLDER_OBJECT
    assert sf["holder"]["all_kind"] == "grasp" and sf["holder"]["contact_intervals"] == 7
    assert sf["occlusion"]["order"] == "in_front_of"
    assert sf["occlusion"]["occluder_role_id"] == HOLDER_OBJECT
    assert sf["occlusion"]["occludee_role_id"] == HOLDER_SUBJECT
    assert sf["camera"]["classification"] == "static"
    assert sf["camera"]["cut_frames"] == []
    assert sf["book_state_at_keyframe"].startswith("closed")


def test_no_camera_parameter_exists_no_new_camera_inferred() -> None:
    doc = _graph_doc()
    for param in doc["parameters"]:
        low = param["name"].lower()
        assert not any(frag in low for frag in FORBIDDEN_PARAM_FRAGMENTS), (
            f"parameter {param['name']!r} exposes a geometry/camera control")
    # the canvas parameters are declared constants, not links to any node
    for key in ("width", "height"):
        v = _nodes_by_id(doc)["LATENT"]["inputs"][key]
        assert isinstance(v, int), f"canvas {key} must be a declared constant, not a link"


# ── role map ──────────────────────────────────────────────────────────────────


def test_role_map_covers_every_person_incl_partial_and_the_prop() -> None:
    roles = _role_map(_graph_doc())
    for rid in PERSON_ROLES:
        assert rid in roles, f"role map misses {rid}"
        assert roles[rid]["source_evidence"], f"{rid} has no measured source evidence"
        assert roles[rid]["disposition"].strip() != ""
    assert HOLDER_OBJECT in roles, "the prop (held object) must be mapped"
    for rid in ("ROLE-BOOK-P1", "ROLE-BOOK-P2", "ROLE-BOOK-P3"):
        assert roles[rid]["target_ref"] is not None, f"{rid} has no target reference"
    # placeholder refs must not claim appearance
    for rid in ("ROLE-BOOK-P1", "ROLE-BOOK-P3"):
        assert roles[rid]["target_ref"]["appearance_claim"] is False
    assert roles["ROLE-BOOK-P2"]["target_ref"]["appearance_claim"] is True


def test_role_map_keeps_the_partial_person_policy() -> None:
    roles = _role_map(_graph_doc())
    p4 = roles[PARTIAL_ROLE]
    assert p4["target_ref"] is None, "the partial edge person has no frozen reference"
    disp = p4["disposition"].lower()
    assert "keep" in disp and "not completed" in disp and "not removed" in disp
    assert p4["source_evidence"]["border_touch"] is True


def test_holder_disposition_is_bound_in_the_map_and_the_prompt() -> None:
    roles = _role_map(_graph_doc())
    assert "holding" in roles[HOLDER_SUBJECT]["disposition"].lower()
    prompt = _nodes_by_id(_graph_doc())["PROMPT"]["inputs"]["text"]
    assert "keep the book closed" in prompt
    assert "PARTIALLY inside the frame" in prompt
    assert "reference image 2" in prompt and "reference image 3" in prompt
    assert "reference image 4" in prompt


# ── conditioning-only extra references ────────────────────────────────────────


def test_extra_references_are_conditioning_only_chained_after_the_keyframe() -> None:
    doc = _graph_doc()
    g = _nodes_by_id(doc)
    assert g["KPOS"]["inputs"]["conditioning"] == ["PROMPT", 0]
    assert g["KPOS"]["inputs"]["latent"] == ["KEY_ENC", 0]
    assert g["KNEG"]["inputs"]["conditioning"] == ["NEG_ZERO", 0]
    assert g["KNEG"]["inputs"]["latent"] == ["KEY_ENC", 0]
    prev_p, prev_n = "KPOS", "KNEG"
    for i in (1, 2, 3):
        assert g[f"R{i}_POS"]["class_type"] == "ReferenceLatent"
        assert g[f"R{i}_POS"]["inputs"]["conditioning"] == [prev_p, 0]
        assert g[f"R{i}_POS"]["inputs"]["latent"] == [f"R{i}_ENC", 0]
        assert g[f"R{i}_NEG"]["inputs"]["conditioning"] == [prev_n, 0]
        assert g[f"R{i}_NEG"]["inputs"]["latent"] == [f"R{i}_ENC", 0]
        prev_p, prev_n = f"R{i}_POS", f"R{i}_NEG"
    guider = _one(doc, "CFGGuider")["inputs"]
    assert guider["positive"] == ["R3_POS", 0] and guider["negative"] == ["R3_NEG", 0]
    # no reference drives canvas / edit base: latent_image is the declared empty latent
    assert _nodes_by_id(doc)["SAMPLE"]["inputs"]["latent_image"] == ["LATENT", 0]
    blob = json.dumps(g["LATENT"]["inputs"])
    for i in (1, 2, 3):
        assert f"R{i}_" not in blob, "a reference must never drive the canvas"


# ── golden request / manifest ─────────────────────────────────────────────────


def _walk_pointer(doc: dict, pointer: str) -> Any:
    parts = pointer.split("/")
    assert parts[0] == "graph"
    cur: Any = doc["graph"][parts[1]]
    rest = parts[2:]
    if rest and rest[0] == "inputs":
        rest = rest[1:]
    if not rest:
        return cur
    for p in rest:
        cur = cur["inputs"][p]
    return cur


def test_golden_bindings_equal_the_values_the_graph_carries() -> None:
    doc = _graph_doc()
    for name, entry in doc["golden_request"]["bindings"].items():
        got = _walk_pointer(doc, entry["pointer"])
        assert got == entry["value"], (
            f"parameter {name}: graph has {got!r}, golden says {entry['value']!r}")


def test_parameters_point_into_the_graph_and_mirrors_hold() -> None:
    doc = _graph_doc()
    for param in doc["parameters"]:
        _walk_pointer(doc, param["pointer"])
        if param.get("golden") is not None:
            assert _walk_pointer(doc, param["pointer"]) == param["golden"], param["name"]
        for mirror in param.get("mirrors", []):
            assert _walk_pointer(doc, mirror) == _walk_pointer(doc, param["pointer"]), (
                f"{param['name']} mirror drift")


def test_frozen_prompt_hash_and_staged_input_invariants() -> None:
    doc = _graph_doc()
    prompt = _nodes_by_id(doc)["PROMPT"]["inputs"]["text"]
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == PROMPT_SHA256
    assert doc["golden_request"]["prompt_sha256"] == PROMPT_SHA256
    staged = doc["golden_request"]["staged_inputs"]
    assert [s["file"] for s in staged] == [KEYFRAME_FILE, *REF_FILES]
    assert [s["sha256"] for s in staged] == [KEYFRAME_SHA, *REF_SHAS]
    assert all(s["mode"] == "RGB" for s in staged)


def test_manifest_models_nodes_workflow_and_runtime() -> None:
    man = _load(MANIFEST_PATH)
    files = {m["file"] for m in man["models"]}
    assert files == set(MODEL_SHA256), f"model set drift: {sorted(files)}"
    for m in man["models"]:
        assert m["sha256"] == MODEL_SHA256[m["file"]]
        assert m["bytes"] > 0 and m["license"].strip() and m["source"].startswith("http")
        assert m["why_used"].strip()
    doc = _graph_doc()
    used = {n["class_type"] for n in _nodes_by_id(doc).values()}
    covered = {e["class_type"] for e in man["nodes"]}
    assert used <= covered, f"classes without a node-source record: {sorted(used - covered)}"
    for e in man["nodes"]:
        assert e["sha256"] and all(len(v) == 64 for v in e["sha256"].values())
        assert e["runtime_head"] == RUNTIME_HEAD
    assert man["runtime"]["head"] == RUNTIME_HEAD
    assert man["runtime"]["porcelain_clean"] is True
    assert man["runtime"]["source_read_only"] is True
    assert man["workflow"]["graph_file"] == "app/media_workflows/shot_anchor_v1.json"
    assert man["workflow"]["graph_file_sha256"] == sha256_file(GRAPH_PATH)
    canonical = json.dumps(doc["graph"], sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    assert man["workflow"]["graph_object_sha256"] == hashlib.sha256(canonical).hexdigest()


def test_manifest_golden_run_is_the_real_anchor() -> None:
    man = _load(MANIFEST_PATH)
    run = man["golden_run"]
    assert run["declared_gpu_jobs"] == 1
    assert len(run["prompt_id"]) == 36
    assert run["graph_object_sha256"] == man["workflow"]["graph_object_sha256"]
    assert run["completed"] is True
    a = run["asset"]
    assert len(a["sha256"]) == 64 and a["dims"] == list(CANVAS) and a["file"].endswith(".png")
    assert run["shutdown"]["phase"] == "POST_STOP_VERIFIED"
    px = run["prefix_job_cpu_only"]["pixel_comparison"]
    assert len(px) == 7
    assert all(v.get("pixels_match_offline_expectation") is True for v in px.values())
    assert run["review"]["verdict"] in {"PASS", "FAIL"}
    assert run["review"]["artifacts"]["side_by_side"].strip() != ""
    assert run["review"]["artifacts"]["overlay_source"].strip() != ""
    assert run["review"]["artifacts"]["overlay_anchor"].strip() != ""


# ── negative controls ─────────────────────────────────────────────────────────


def _broken(kind: str) -> dict:
    doc = _graph_doc()
    g = _copy.deepcopy(doc["graph"])
    if kind == "missing_required_input":
        del g["SAVE"]["inputs"]["images"]
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
        pytest.skip("no /object_info dump: the object_info-dependent refusals need one")
    errs = _refusal(_broken(kind), None)
    assert any(needle in e for e in errs), f"{kind}: no refusal containing {needle!r} in {errs}"


@pytest.mark.parametrize("class_name", UNREGISTERED_NODES)
def test_negative_control_unregistered_task_nodes_are_refused(class_name: str) -> None:
    """The task names three nodes that are NOT registered; wiring one in must be refused."""
    g = _copy.deepcopy(_graph_doc()["graph"])
    g["BOGUS"] = {"class_type": class_name, "inputs": {}}
    errs = _refusal(g, None)
    assert any("not in /object_info" in e and class_name in e for e in errs), errs


def test_negative_control_structural_refusals_without_object_info() -> None:
    for kind, needle in (("dangling_link", "links to missing node"), ("cycle", "cycle"),
                         ("unreachable_node", "unreachable")):
        errs = validate_graph(_broken(kind), None, _save_ids(_graph_doc()))["errors"]
        assert any(needle in e for e in errs), f"{kind}: {errs}"


# ── anchor contract predicate ─────────────────────────────────────────────────


def anchor_contract_ok(doc: dict) -> bool:
    """The delivered contract as ONE boolean; every mutated anchor doc must fail it."""
    g = doc["graph"]
    try:
        w = g["LATENT"]["inputs"]["width"]
        h = g["LATENT"]["inputs"]["height"]
        if not (isinstance(w, int) and isinstance(h, int) and w % 16 == 0 and h % 16 == 0):
            return False
        if (w, h) != tuple(doc["golden_request"]["staged_inputs"][0]["dims"]):
            return False
        # alpha wiring per image
        for prefix in ("KEY", "R1", "R2", "R3"):
            if g[f"{prefix}_COMP"]["inputs"]["mask"] != [f"{prefix}_INV", 0]:
                return False
            if g[f"{prefix}_INV"]["inputs"]["mask"] != [f"{prefix}_LOAD", 1]:
                return False
            if g[f"{prefix}_BG"]["inputs"]["color"] != NEUTRAL_INT:
                return False
        # keys
        sf = doc["source_facts"]
        if sf["artifact_digest"] != FACTS_DIGEST or sf["window_id"] != "BOOK":
            return False
        if sf["holder"]["subject_role_id"] != HOLDER_SUBJECT:
            return False
        if sf["camera"]["classification"] != "static" or sf["camera"]["cut_frames"] != []:
            return False
        if not sf["book_state_at_keyframe"].lower().startswith("closed"):
            return False
        for param in doc["parameters"]:
            if any(frag in param["name"].lower() for frag in FORBIDDEN_PARAM_FRAGMENTS):
                return False
        roles = _role_map_from(doc)
        for rid in PERSON_ROLES:
            if rid not in roles:
                return False
        if "keep" not in roles[PARTIAL_ROLE]["disposition"].lower():
            return False
        if "not completed" not in roles[PARTIAL_ROLE]["disposition"].lower():
            return False
        for rid in ("ROLE-BOOK-P1", "ROLE-BOOK-P2", "ROLE-BOOK-P3"):
            if roles[rid]["target_ref"] is None:
                return False
        # references are conditioning-only: canvas stays declared, latent_image is LATENT
        if g["SAMPLE"]["inputs"]["latent_image"] != ["LATENT", 0]:
            return False
        if any(isinstance(v, list) for v in (g["LATENT"]["inputs"]["width"],
                                             g["LATENT"]["inputs"]["height"])):
            return False
        if BASE_UNET in json.dumps(g) or BASE_ONLY_VAE in json.dumps(g):
            return False
    except (KeyError, TypeError, IndexError, AttributeError):
        return False
    return True


def _role_map_from(doc: dict) -> dict:
    return {r["role_id"]: r for r in doc["role_map"]["roles"]}


def _anchor_mutation(kind: str) -> dict:
    doc = _copy.deepcopy(_graph_doc())
    if kind == "canvas_not_divisible_by_16":
        doc["graph"]["LATENT"]["inputs"]["width"] = 643
        doc["graph"]["SIGMAS"]["inputs"]["width"] = 643
    elif kind == "canvas_from_link":
        doc["graph"]["LATENT"]["inputs"]["width"] = ["R1_SIZE", 0]
    elif kind == "alpha_inversion_removed":
        doc["graph"]["KEY_COMP"]["inputs"]["mask"] = ["KEY_LOAD", 1]
    elif kind == "holder_swap":
        doc["source_facts"]["holder"]["subject_role_id"] = PARTIAL_ROLE
    elif kind == "partial_dropped":
        for r in doc["role_map"]["roles"]:
            if r["role_id"] == PARTIAL_ROLE:
                r["disposition"] = "completed into the frame at the same position"
    elif kind == "partial_removed":
        doc["role_map"]["roles"] = [r for r in doc["role_map"]["roles"]
                                    if r["role_id"] != PARTIAL_ROLE]
    elif kind == "camera_invented":
        doc["parameters"].append({"name": "camera_pan_px",
                                  "pointer": "graph/NOISE/inputs/noise_seed", "type": "int",
                                  "rule": "pan", "golden": 0})
    elif kind == "book_state_changed":
        doc["source_facts"]["book_state_at_keyframe"] = "open, two pages spread"
    elif kind == "base_swap":
        doc["graph"]["UNET"]["inputs"]["unet_name"] = BASE_UNET
    elif kind == "ref_used_as_canvas":
        doc["graph"]["LATENT"]["inputs"]["width"] = ["R1_SIZE", 0]
        doc["graph"]["LATENT"]["inputs"]["height"] = ["R1_SIZE", 1]
    else:  # pragma: no cover
        raise AssertionError(f"unknown mutation {kind}")
    return doc


def test_anchor_contract_passes_delivered_and_refuses_every_mutation() -> None:
    assert anchor_contract_ok(_graph_doc()) is True
    for kind in ("canvas_not_divisible_by_16", "canvas_from_link", "alpha_inversion_removed",
                 "holder_swap", "partial_dropped", "partial_removed", "camera_invented",
                 "book_state_changed", "base_swap", "ref_used_as_canvas"):
        assert anchor_contract_ok(_anchor_mutation(kind)) is False, (
            f"{kind}: the mutated anchor document was NOT refused")
