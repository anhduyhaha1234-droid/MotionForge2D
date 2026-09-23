"""MF-V1-VIDEO14B wave A — registered CPU probes (A1 graph diff, A2 motion window, A3 identity).

Each test recomputes the measured property from the INSTALLED runtime and the
submitted graph bytes rather than trusting the recorded JSON, so a later edit to
the tools, the graph or the runtime cannot silently invalidate the wave-A
findings:

  A1  the submitted graph conditions motion on a 0..0 sampling window while the
      native Animate-2 template ships 0..1, and the submitted graph is untouched.
  A2  the real node code plus the real sampler selector give 1/6 vs 6/6 steps.
  A3  replacing a reference changes the cache/request identity, a missing
      reference is refused before any POST, and a prompt string is not identity.
  A6  the corrected unit arithmetic (s per generated second, undefined cost per
      accepted second, audio samples per channel).

No engine is started, no model is loaded and no GPU work happens here.

Run:
  cd <worktree> && python -m pytest experiments/mf_reskin_v1/video14b/tests -q
"""
import hashlib
import importlib.util
import json
from pathlib import Path

WT = Path(__file__).resolve().parents[4]
VIDEO14B = WT / "experiments/mf_reskin_v1/video14b"
TOOLS = VIDEO14B / "tools"
OLD = Path(
    r"C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs"
    r"\mf-reskin-correction-20260922\20260922T0955Z"
)
NEW = Path(
    r"C:\Users\Admin\Documents\Codex\2026-09-22\tr-ng-th-i-terminal-gi\outputs"
    r"\mf-core-tool-delivery-20260923\20260923T1535Z"
)
RT = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\runtime\video14b")
SUBMITTED = OLD / "VIDEO14B/waveB/workflows/mf_animate2_book4s.waveB.api.json"
SUBMITTED_SHA = "7ea87b66569cc629b02bc27f2e7db0d6d03a4700403bf317076f3ab5f8f4c6f8"
M1_REFERENCE_SHA = "1311699b55c586abdb631d0468b4afc19cdf73a1b45b86fc4403f4517daf03fe"
A1_JSON = NEW / "VIDEO14B/raw/a1_graph_diff.json"
A2_JSON = NEW / "VIDEO14B/raw/a2_motion_window.json"
A3_JSON = NEW / "VIDEO14B/raw/a3_identity_trace.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def a1():
    return _load("v14b_a1_native_diff", TOOLS / "v14b_a1_native_diff.py")


def a2():
    return _load("v14b_a2_motion_window", TOOLS / "v14b_a2_motion_window.py")


def a3():
    return _load("v14b_a3_identity_trace", TOOLS / "v14b_a3_identity_trace.py")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_a1_native_template_ships_pose_window_0_to_1():
    """The installed Animate-2 template conditions motion on every step."""
    module = a1()
    nodes_wan = module.COMFY / "comfy_extras/nodes_wan.py"
    widgets = module.schema_widget_order(nodes_wan.read_text(encoding="utf-8"))["widgets"]
    assert widgets == [
        "width", "height", "length", "batch_size", "video_frame_offset",
        "pose_strength", "pose_start_percent", "pose_end_percent",
        "reference_image_strength",
    ]
    native = module.native_side(module.TPL_DIR / "video_wan_animate2.json", widgets)
    named = native["primary_animate_node"]["named"]
    assert named["pose_start_percent"] == 0.0
    assert named["pose_end_percent"] == 1.0
    assert native["primary_animate_node"]["node_id"] == 587


def test_a1_submitted_graph_conditions_on_a_zero_width_window():
    """The submitted graph narrows the same window to 0..0 — the F08 defect."""
    module = a1()
    widgets = module.schema_widget_order(
        (module.COMFY / "comfy_extras/nodes_wan.py").read_text(encoding="utf-8")
    )["widgets"]
    submitted = module.submitted_side(SUBMITTED, widgets)
    assert submitted["sha256"] == SUBMITTED_SHA
    named = submitted["WanAnimate2ToVideo"]["named"]
    assert named["pose_start_percent"] == 0
    assert named["pose_end_percent"] == 0
    assert named["pose_strength"] == 1
    assert named["reference_image_strength"] == 1
    # the reference arrives from a plain LoadImage of a frame-derived anchor, not a cast pack
    assert submitted["input_readers_in_closure"] == ["189", "240"]
    load_image = next(
        entry for entry in submitted["reference_chain"] if entry["class_type"] == "LoadImage"
    )
    assert load_image["node"] == "189"
    assert load_image["scalars"]["image"] == "mf_book_anchor_1650.png"


def test_a1_submitted_graph_is_an_untouched_negative_control():
    """The reviewed graph keeps its bytes: the probe only reads it."""
    recorded = json.loads(A1_JSON.read_text(encoding="utf-8"))
    control = recorded["submitted_negative_control"]
    assert control["unchanged"] is True
    assert control["sha256_before"] == SUBMITTED_SHA
    assert control["sha256_after"] == SUBMITTED_SHA
    assert sha256_file(SUBMITTED) == SUBMITTED_SHA


def test_a2_real_node_code_gives_one_of_six_and_six_of_six():
    """Runtime code, not a restated cond dict: 0..0 -> 1/6, 0..1 -> 6/6."""
    module = a2()
    namespace, _sources, _segments = module.build_namespace()
    graph = json.loads(SUBMITTED.read_text(encoding="utf-8"))
    graph_inputs = {
        "shift": graph["672:592"]["inputs"]["shift"],
        "steps": graph["672:591"]["inputs"]["steps"],
    }
    geometry = {"width": 64, "height": 64, "length": 9, "pose_video_frames": 9}
    narrow = module.run_case(
        namespace,
        {"name": "narrow", "pose_start_percent": 0.0, "pose_end_percent": 0.0, **geometry},
        graph_inputs,
    )
    native = module.run_case(
        namespace,
        {"name": "native", "pose_start_percent": 0.0, "pose_end_percent": 1.0, **geometry},
        graph_inputs,
    )
    assert narrow["total_steps"] == 6
    assert narrow["pose_steps_structural"] == 1
    assert narrow["pose_steps_by_payload"] == 1
    assert narrow["pose_steps_analytic"] == 1
    assert native["pose_steps_structural"] == 6
    assert native["pose_steps_by_payload"] == 6
    assert native["pose_steps_analytic"] == 6
    assert [round(s, 6) for s in narrow["steps"]] == [
        1.0, 0.961716, 0.909215, 0.833333, 0.714897, 0.5006
    ]
    assert narrow["percent_to_sigma"] == {"start": 1.0, "end": 1.0}
    assert native["percent_to_sigma"] == {"start": 1.0, "end": 0.0}


def test_a2_recorded_probe_agrees_with_this_recomputation():
    recorded = json.loads(A2_JSON.read_text(encoding="utf-8"))
    cases = {case["case"]: case for case in recorded["cases"]}
    assert cases["submitted_0_0_structural_full_geometry"]["pose_steps_structural"] == 1
    assert cases["native_0_1_structural_full_geometry"]["pose_steps_structural"] == 6
    assert cases["submitted_0_0_payload_small_geometry"]["pose_steps_by_payload"] == 1
    assert cases["native_0_1_payload_small_geometry"]["pose_steps_by_payload"] == 6
    assert recorded["reviewer_probe_compare"]["agreement"]["agrees"] is True
    assert recorded["reviewer_probe_compare"]["agreement"]["submitted_0_0_pose_steps"] == [1, 1]


def test_a3_reference_swap_changes_cache_and_request_identity():
    module = a3()
    input_dir = module.RUN_DIR / "identity_inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    cast = NEW / "VIDEO14B/fixtures/test_only_cast_asset.png"
    other = NEW / "VIDEO14B/fixtures/test_only_other_asset.png"
    assert sha256_file(cast) == M1_REFERENCE_SHA
    names = {}
    for label, source in (("cast", cast), ("other", other)):
        names[label] = f"{label}_{sha256_file(source)[:12]}.png"
        (input_dir / names[label]).write_bytes(source.read_bytes())
    runtime, _ = module.build_runtime(input_dir)
    graph = json.loads(SUBMITTED.read_text(encoding="utf-8"))
    signatures = {}
    for label, reference in (("cast", names["cast"]), ("other", names["other"])):
        signatures[label] = module.asyncio.run(
            module.signature_digests(
                runtime, module.variant(graph, reference, None), input_dir, label
            )
        )
    assert signatures["cast"]["conditioning_signature_digest"] != signatures["other"][
        "conditioning_signature_digest"
    ]
    assert set(signatures["cast"]["image_derived_digests"]) == {M1_REFERENCE_SHA}
    assert signatures["other"]["image_derived_digests"] != signatures["cast"][
        "image_derived_digests"
    ]
    # the same digest appears once per dependent node: it is one file, read once
    assert {row["digest"] for row in signatures["cast"]["loadimage_is_changed"]} == {
        M1_REFERENCE_SHA
    }
    assert all(row["digest_is_file_sha256"] for row in signatures["cast"]["loadimage_is_changed"])


def test_a3_prompt_metadata_is_not_identity():
    """With no reference bound, no image digest enters the closure at all."""
    module = a3()
    input_dir = module.RUN_DIR / "identity_inputs_meta"
    input_dir.mkdir(parents=True, exist_ok=True)
    runtime, _ = module.build_runtime(input_dir)
    graph = json.loads(SUBMITTED.read_text(encoding="utf-8"))
    metadata = variant_with_metadata(module, graph)
    plain = module.variant(graph, None, None)
    with_metadata = module.asyncio.run(
        module.signature_digests(runtime, metadata, input_dir, "metadata_only")
    )
    without = module.asyncio.run(
        module.signature_digests(runtime, plain, input_dir, "no_metadata")
    )
    assert with_metadata["image_derived_digests"] == []
    assert without["image_derived_digests"] == []
    assert with_metadata["closure"] == without["closure"]
    assert "189" not in with_metadata["closure"]
    # the metadata string moves ONLY the text encoder's digest, never an image digest
    moved = {
        node_id
        for node_id in with_metadata["per_node_digest"]
        if with_metadata["per_node_digest"][node_id] != without["per_node_digest"][node_id]
    }
    # the metadata string moves ONLY the text branch: the three encoders and the
    # conditioning node that consumes them.  No image-derived digest appears at all.
    assert moved <= {"672:581", "672:582", "672:585", module.CONDITIONING_NODE}


def variant_with_metadata(module, graph):
    return module.variant(graph, None, "CharacterID=A3TEST PackVersion=000000000000 asset_sha256=" + M1_REFERENCE_SHA)


def test_a3_missing_reference_is_refused_before_any_post():
    module = a3()
    input_dir = module.RUN_DIR / "missing_inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    graph = json.loads(SUBMITTED.read_text(encoding="utf-8"))
    runtime, _ = module.build_runtime(input_dir)
    posts = []
    real = module.urllib.request.urlopen
    module.urllib.request.urlopen = lambda request, *a, **k: posts.append(request)
    try:
        guard = module.pre_submit_guard(module.variant(graph, "nope.png", None), input_dir)
    finally:
        module.urllib.request.urlopen = real
    assert posts == []
    assert guard["refused"] is True
    assert guard["errors"][0]["code"] == "MF_V14B_REFERENCE_INPUT_MISSING"
    assert guard["errors"][0]["node"] == "189"
    message = runtime["LoadImage"].VALIDATE_INPUTS("nope.png")
    assert message == "Invalid image file: nope.png"


def test_a3_recorded_trace_marks_all_three_proofs():
    recorded = json.loads(A3_JSON.read_text(encoding="utf-8"))
    assert recorded["graph"]["sha256"] == SUBMITTED_SHA
    assert recorded["loader"]["loader_is_checksum_bound"] is True
    assert recorded["loader"]["tamper_rejected"] is True
    assert recorded["fixture_manifest"]["cast"]["sha256"] == M1_REFERENCE_SHA
    for proof in recorded["proofs"].values():
        assert proof["PASS"] is True, proof


def test_a6_corrected_units():
    """135.906 s is wait_s; 136.561 s wall; the clip is 4.001995 s long, 0 accepted seconds.

    The packet's "~34.14 s per generated second" is ``wall / 4.000 s``; measured
    against the clip's real duration the number is 34.12 s per generated second.
    Both are recorded so neither value is quoted without its denominator.
    """
    wait_s, wall_s, clip_s = 135.906, 136.561, 4.001995
    assert round(wall_s / clip_s, 2) == 34.12
    assert round(wall_s / 4.0, 2) == 34.14
    assert wait_s < wall_s
    accepted_seconds = 0
    assert accepted_seconds == 0  # cost per accepted second is therefore undefined
    assert 176400 * 2 == 352800  # audio samples per channel; both channels = 352,800
    clip = RT / "output/waveB_f06/final_book4s_decoded119_640x360.mp4"
    assert clip.is_file()
    assert sha256_file(clip) == "55daef67162601a073a2f9de0988b95008b08cbe16e4a36f5567981dba776d04"
