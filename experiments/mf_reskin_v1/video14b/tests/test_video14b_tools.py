#!/usr/bin/env python
"""MF-V1-VIDEO14B — regression tests for the task's own tools.

These tests cover the defects this task actually hit, so a future edit cannot silently
reintroduce them:
  * the delta verifier compared a LIST POSITION against a NODE ID (its verdict could never pass);
  * the run copy was re-serialised in the wrong style, shrinking the released file by 35 KB;
  * a declared preimage that did not match the leaf-level delta (whole-list vs per-leaf);
  * the licence-excluded CausVid LoRAs must stay unreachable from the run configuration;
  * an MSYS path (/c/Users/...) silently made every staged file look MISSING.

No model file is read and no engine is started: every test here is off-line and fast.

Run:  cd <worktree>  &&  python -m pytest experiments/mf_reskin_v1/video14b/tests -q
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

import pytest

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = ("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
      "mf-reskin-model-upgrade-20260922/20260922T0345Z/VIDEO14B")
RUN = os.path.join(WT, "workflows", "run")
OFFICIAL = os.path.join(WT, "workflows", "official")
EXCLUDED = ("Wan21_CausVid_14B_T2V_lora_rank32.safetensors",
            "Wan21_CausVid_bidirect2_T2V_1_3B_lora_rank32.safetensors")
ANIMATE2_RUN = os.path.join(RUN, "mf_animate2_book4s.json")
VACE_RUN = os.path.join(RUN, "mf_vace14b_book4s.json")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return load(os.path.join(WT, "tools", "make_run_workflows.py"), "mf_make_run_workflows")


@pytest.fixture(scope="module")
def validator():
    return load(os.path.join(EV, "tools", "validate_downloads.py"), "mf_validate_downloads")


@pytest.fixture(scope="module")
def exclusions():
    return load(os.path.join(EV, "tools", "verify_exclusions.py"), "mf_verify_exclusions")


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def nodes_of(doc, scope="top"):
    if scope == "top":
        return doc["nodes"]
    for sg in doc["definitions"]["subgraphs"]:
        if sg["name"] == scope:
            return sg["nodes"]
    raise AssertionError("subgraph not found: %s" % scope)


def find(doc, node_id, scope="top"):
    return next(n for n in nodes_of(doc, scope) if n["id"] == node_id)


# ---------------------------------------------------------------- delta verifier

def test_resolve_node_returns_document_node_not_list_position(gen):
    """The original bug: a subgraph's internal position 36 is not node id 36."""
    doc = {"nodes": [{"id": 240}],
           "definitions": {"subgraphs": [{"name": "sg", "nodes": [{"id": 597}, {"id": 604}]}]}}
    parts = "definitions/subgraphs/0/nodes/1/widgets_values/2".split("/")
    assert gen.resolve_node(doc, parts, parts.index("nodes"))["id"] == 604
    assert gen.resolve_node(doc, "nodes/0/mode".split("/"), 0)["id"] == 240


def test_verify_delta_accepts_exactly_the_declared_set(gen):
    declared = [{"node_id": 3, "scope": "top", "index": 2, "old": 4, "new": 20},
                {"node_id": 107, "scope": "top", "kind": "mode", "index": None, "old": 0, "new": 4}]
    doc = {"nodes": [{"id": 3, "widgets_values": [1, "fixed", 20]}, {"id": 107, "mode": 4}]}
    delta = [{"path": "/nodes/0/widgets_values/2", "old": 4, "new": 20},
             {"path": "/nodes/1/mode", "old": 0, "new": 4}]
    assert gen.verify_delta(delta, declared, "t.json", doc) == (2, 2)


def test_verify_delta_rejects_undeclared_change(gen):
    doc = {"nodes": [{"id": 3, "widgets_values": [1, "fixed", 20]}]}
    delta = [{"path": "/nodes/0/widgets_values/2", "old": 4, "new": 20},
             {"path": "/nodes/0/widgets_values/1", "old": "randomize", "new": "fixed"}]
    with pytest.raises(SystemExit, match="UNDECLARED DELTA"):
        gen.verify_delta(delta, [{"node_id": 3, "scope": "top", "index": 2, "old": 4, "new": 20}],
                         "t.json", doc)


def test_verify_delta_rejects_declared_change_that_did_not_apply(gen):
    doc = {"nodes": [{"id": 3, "widgets_values": [1, "fixed", 20]}]}
    delta = [{"path": "/nodes/0/widgets_values/2", "old": 4, "new": 20}]
    with pytest.raises(SystemExit, match="DECLARED CHANGE NOT OBSERVED"):
        gen.verify_delta(delta, [{"node_id": 3, "scope": "top", "index": 2, "old": 4, "new": 20},
                                 {"node_id": 68, "scope": "top", "index": 0, "old": 16, "new": 30}],
                         "t.json", doc)


def test_verify_delta_rejects_preimage_mismatch(gen):
    doc = {"nodes": [{"id": 3, "widgets_values": [1, "fixed", 20]}]}
    delta = [{"path": "/nodes/0/widgets_values/2", "old": 4, "new": 20}]
    with pytest.raises(SystemExit, match="PREIMAGE MISMATCH"):
        gen.verify_delta(delta, [{"node_id": 3, "scope": "top", "index": 2, "old": 4, "new": 21}],
                         "t.json", doc)


# ---------------------------------------------------------------- serialisation

@pytest.mark.parametrize("name", ["video_wan_animate2.json", "video_wan_vace_14B_v2v.json"])
def test_serialiser_is_byte_faithful_on_the_released_file(gen, name):
    """The run copy must differ from the released bytes ONLY by the declared changes, which is
    only true if the serialisation style reproduces the released file exactly."""
    text = open(os.path.join(OFFICIAL, name), encoding="utf-8").read()
    assert gen.serialize_like_source(json.loads(text), text, name) == text


def test_run_copies_are_the_generators_own_output_and_deterministic(gen):
    before = {p: sha256(p) for p in (ANIMATE2_RUN, VACE_RUN)}
    assert gen.main() == 0
    assert {p: sha256(p) for p in (ANIMATE2_RUN, VACE_RUN)} == before


def test_run_copies_grew_by_the_declared_prompt_text_and_never_shrank(gen):
    """A silent re-format once shrank the released 162,740 B file into a 127,647 B run copy."""
    for name, run_path, official in (("mf_animate2_book4s.json", ANIMATE2_RUN, "video_wan_animate2.json"),
                                     ("mf_vace14b_book4s.json", VACE_RUN, "video_wan_vace_14B_v2v.json")):
        size_run = os.path.getsize(run_path)
        size_released = os.path.getsize(os.path.join(OFFICIAL, official))
        assert size_run >= size_released, "%s shrank: %d < %d" % (name, size_run, size_released)


# ---------------------------------------------------------------- the run configuration

def test_animate2_run_copy_never_names_a_licence_excluded_lora():
    blob = open(ANIMATE2_RUN, encoding="utf-8").read()
    assert [f for f in EXCLUDED if f in blob] == []


def test_vace_run_copy_bypasses_the_unlicensed_lora(exclusions):
    doc = json.load(open(VACE_RUN, encoding="utf-8"))
    node = next(n for n in doc["nodes"] if n["id"] == 107)
    assert node["type"] == "LoraLoader"
    assert node["mode"] == 4, "the unlicensed CausVid LoRA must be bypassed, not active"
    # every remaining mention must be non-executing (bypassed node or documentation note)
    for scope, n in exclusions.iter_nodes(doc):
        blob = json.dumps(n.get("widgets_values"), ensure_ascii=False) if n.get("widgets_values") else ""
        if any(f in blob for f in EXCLUDED):
            assert exclusions.classify(n) != "EXECUTABLE_REFERENCE", (scope, n.get("id"))


def test_vace_run_copy_declares_source_geometry_length_fps_and_non_lora_sampler():
    doc = json.load(open(VACE_RUN, encoding="utf-8"))
    assert find(doc, 49)["widgets_values"][:5] == [640, 368, 121, 1, 1]
    assert find(doc, 68)["widgets_values"][0] == 30
    sampler = find(doc, 3)["widgets_values"]
    assert sampler[2] == 20 and sampler[3] == 6.0, "steps/cfg must be the released non-LoRA default"
    assert sampler[4:6] == ["uni_pc", "simple"], "sampler/scheduler stay as released"
    assert find(doc, 145)["widgets_values"][0] == "mf_book_f1650_1770_drive_121f.mp4"
    assert find(doc, 134)["widgets_values"][0] == "mf_book_anchor_1650.png"


def test_animate2_run_copy_declares_120f_inputs_and_pinned_seed_control():
    doc = json.load(open(ANIMATE2_RUN, encoding="utf-8"))
    assert find(doc, 240)["widgets_values"][0] == "mf_book_f1650_1770_drive_120f.mp4"
    assert find(doc, 189)["widgets_values"][0] == "mf_book_anchor_1650.png"
    sub = "Motion Transfer (Wan Animate 2)"
    assert find(doc, 597, sub)["widgets_values"][2] == "fixed"
    # the driving clip must be referenced by node id 240, and the internal 121st frame is cut by
    # ImageFromBatch 670 (start 0) - the one-frame-slip branch 604 is the other side of 671
    assert find(doc, 670, sub)["widgets_values"] == [0, 4096]
    assert find(doc, 604, sub)["widgets_values"] == [1, 4096]


def test_released_model_file_names_are_kept_verbatim():
    """The matched released set must not be hand-mixed: the loader widgets are untouched."""
    animate = open(ANIMATE2_RUN, encoding="utf-8").read()
    assert "wan_animate_2_int8_convrot.safetensors" in animate
    assert "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors" in animate
    vace = open(VACE_RUN, encoding="utf-8").read()
    assert "wan2.1_vace_14B_fp16.safetensors" in vace


def test_excluded_weights_are_outside_the_engine_model_search_path():
    runtime = "C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b"
    models = os.path.join(runtime, "models")
    hits = [os.path.join(r, f) for r, _d, fs in os.walk(models) for f in fs if f in EXCLUDED]
    assert hits == []
    quarantine = os.path.join(runtime, "excluded_unlicensed_weights")
    assert sorted(os.listdir(quarantine)) == sorted(EXCLUDED)


# ---------------------------------------------------------------- path handling

@pytest.mark.parametrize("given,expected", [
    ("/c/Users/Admin/rt", "C:/Users/Admin/rt"),
    ("C:/Users/Admin/rt", "C:/Users/Admin/rt"),
    ("C:\\Users\\Admin\\rt", "C:/Users/Admin/rt"),
    ("/d/x", "D:/x"),
])
def test_native_runtime_normalises_msys_paths(validator, given, expected):
    assert validator.native_runtime(given) == expected


def test_msys_runtime_path_resolves_rather_than_reporting_everything_missing(validator):
    """Regression: the MSYS form once produced 9 MISSING / 0 PASS instead of a path error."""
    msys = "/c/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b"
    native = "C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b"
    assert validator.native_runtime(msys) == native
    for rel, _repo, _path in validator.MAP:
        assert os.path.isfile(os.path.join(validator.native_runtime(msys), "models", rel))


def test_exclusion_classifier_distinguishes_notes_bypass_and_executable(exclusions):
    assert exclusions.classify({"type": "MarkdownNote", "mode": 0}) == "DOCUMENTATION_TEXT_NOTE_NOT_EXECUTED"
    assert exclusions.classify({"type": "LoraLoader", "mode": 4}) == "BYPASSED_OR_MUTED_NOT_EXECUTED"
    assert exclusions.classify({"type": "LoraLoader", "mode": 2}) == "BYPASSED_OR_MUTED_NOT_EXECUTED"
    assert exclusions.classify({"type": "LoraLoader", "mode": 0}) == "EXECUTABLE_REFERENCE"


# ---------------------------------------------------------------- the GPU path (cheap, no model)

def test_task_local_venv_torch_declares_sm_120():
    runtime = "C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b"
    py = os.path.join(runtime, "venv", "Scripts", "python.exe")
    if not os.path.isfile(py):
        pytest.skip("task-local venv not present")
    code = ("import json,torch;print(json.dumps({'v':torch.__version__,'cuda':torch.version.cuda,"
            "'sm120':'sm_120' in torch.cuda.get_arch_list(),'avail':torch.cuda.is_available()}))")
    out = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr
    info = json.loads(out.stdout)
    assert info["sm120"] is True, info
    assert info["avail"] is True, info
    assert info["cuda"].startswith("13."), info
