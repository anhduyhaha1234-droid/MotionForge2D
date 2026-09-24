"""MF-V1-VIDEO14B round C — registered checks for V00 (R9 colour), V01 (R10 F09), V02 (role refs).

These pin the MEASURED properties of the round-C correction, on the code AND on the round's
own evidence, so a later edit cannot quietly undo them.  Nothing here starts an engine, loads
a model, or does GPU work; nothing writes media.

Run:
  cd <worktree> && python -m pytest experiments/mf_reskin_v1/video14b/tests -q
"""
import hashlib
import importlib.util
import json
import os
import re
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(WT, "tools")
EV = ("C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/"
      "mf-core-tool-delivery-20260924/20260924T1055Z/VIDEO14B")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ev(name):
    return json.loads(open(os.path.join(EV, "raw", name), encoding="utf-8").read())


# --------------------------------------------------------------------------- V00

def test_v00_export_carries_colour_metadata_and_detects_its_loss():
    dec = load(os.path.join(TOOLS, "v14b_export_decode.py"), "mf_v14b_dec_roundC")
    # the pinned tag set, and the filter form that mirrors it
    assert dec.COLOR_TAGS == {"color_range": "tv", "color_space": "bt709",
                              "color_primaries": "bt709", "color_transfer": "iec61966-2-1"}
    assert dec.color_filter_args(dec.COLOR_TAGS) == ["-vf", dec.SETPARAMS]
    assert dec.color_filter_args(None) == []

    src = open(os.path.join(TOOLS, "v14b_export_decode.py"), encoding="utf-8").read()
    main_body = src.split("def main()")[1]
    # the tags are attached as FRAME metadata; the encoder-option form is gone, because it
    # made ffmpeg insert a range conversion on the unspecified NUT input (measured: native
    # planes shifted up to 32, RGB MAE 6.3725, and only tv/bt709 survived)
    assert '"-color_range"' not in main_body, "colour tags must not go back to encoder options"
    assert "*tag_args" in main_body
    assert '"--no-color-tags" in sys.argv' in src
    # the F06 properties must survive the R9 change
    assert "-frames:v" not in main_body
    vf_call = re.search(r'"-vf"\s*,\s*select_filter\(([^)]*)\)', main_body)
    assert vf_call is not None and vf_call.group(1).split(",")[0].strip() == "keep"

    fixed = ev("v00_tag_roundtrip.json")
    ctl = ev("v00_tag_roundtrip_negative_control.json")
    for rec in (fixed, ctl):
        assert rec["checks"]["output_frame_count_is_120"] is True
        assert rec["checks"]["pixel_map_is_identity_0_to_119"] is True
        assert rec["checks"]["crop_is_pure_translation"] is True
        assert rec["checks"]["native_yuv_identical_0_to_119"] is True
        assert rec["checks"]["rgb_identical_with_matching_tags"] is True
        assert rec["checks"]["contract"]["pts_is_i_times_512"] is True
        assert rec["color_roundtrip"]["native_planes"]["max_abs_diff"] == 0
    # the fix: all four tags on the clip, and both RGB comparisons identical
    assert fixed["checks"]["color_tags_preserved"] is True
    assert fixed["color_tags"]["clip"] == fixed["color_tags"]["expected_from_raw"]
    assert fixed["checks"]["rgb_identical_with_own_tags"] is True
    assert fixed["checks"]["detector_fired_on_tag_loss"] is False
    assert fixed["clip_probe"]["width"] == 640 and fixed["clip_probe"]["height"] == 360
    # the negative control: tags absent, RGB differs, detector fires
    assert all(v is None for v in ctl["color_tags"]["clip"].values())
    assert ctl["checks"]["color_tags_preserved"] is False
    assert ctl["checks"]["rgb_identical_with_own_tags"] is False
    assert ctl["color_roundtrip"]["rgb_each_side_own_tags"]["maxabs_max"] > 0
    assert ctl["checks"]["detector_fired_on_tag_loss"] is True

    # the reviewer's own numbers, reproduced pre-fix on the M1 clip
    pre = ev("v00_pre_fix_baseline.json")
    m1 = pre["rgb_comparison"]["old_candidate_m1_clip"]
    assert round(m1["decoded_with_its_own_absent_tags_vs_raw"]["mae_mean"], 4) == 2.1182
    assert m1["decoded_with_its_own_absent_tags_vs_raw"]["maxabs_max"] == 18
    assert m1["decoded_with_source_tags_forced_vs_raw"]["maxabs_max"] == 0
    assert m1["decoded_with_source_tags_forced_vs_raw"]["identical_frames"] == 120

    # the new candidate is a NEW artifact, and both historical candidates are untouched
    freeze = ev("v00_candidate_freeze.json")
    assert freeze["sha256"] not in (
        "5c2175ae73056ea6552b7b50432f618f7255a09f7cf9e5c695a870fe22286a6d",
        "55daef67162601a073a2f9de0988b95008b08cbe16e4a36f5567981dba776d04")
    assert os.path.isfile(freeze["path"])
    assert sha256(freeze["path"]) == freeze["sha256"]
    assert sha256(freeze["negative_control"]["path"]) == freeze["negative_control"]["sha256"]
    assert freeze["colour_tags"] == fixed["color_tags"]["clip"]


# --------------------------------------------------------------------------- V01

def test_v01_f09_positive_fixture_has_full_provenance_and_stays_fail_closed():
    src = open(os.path.join(TOOLS, "v14b_f09_cases.py"), encoding="utf-8").read()
    # the hard-coded port that contradicted the classifier is gone
    # the port is resolved, never remembered: no listener row and no epoch literal may
    # carry a fixed port again (the docstrings may still explain the old 8210 defect)
    assert "127.0.0.1:8210" not in src
    assert '"port": 8210' not in src
    assert "def listeners_before(port: int)" in src
    assert "def full_ev(port: int)" in src
    assert "resolve_classifier_port" in src and "self_exit_receipts" in src
    assert "runs/{RUN_ID}" in src or "f\"runs/{RUN_ID}\"" in src

    cases = ev("v01_f09_cases.json")
    assert cases["all_match_expected"] is True
    assert cases["positive_case_full_provenance"] is True
    assert all(cases["positive_case_provenance"].values())
    by = {c["case"]: c for c in cases["cases"]}
    assert by["valid_own_chain"]["verdict"].startswith("SHUTDOWN_CONFIRMED")
    assert by["valid_own_chain"]["returncode"] == 0
    assert by["valid_own_chain"]["collateral_removed"] == []
    assert by["valid_own_chain"]["self_exit_evidence"], "the own-client exit needs its receipt"
    assert len(by["valid_own_chain"]["receipt_files"]) == 2
    classes = {v["class"] for v in by["valid_own_chain"]["pid_classification"].values()}
    assert "own_client_process_exited_after_engine_stop" in classes
    for name in ("no_authority", "missing_chain", "timeout_probe"):
        assert by[name]["verdict"] == "SHUTDOWN_UNPROVEN"
        assert by[name]["returncode"] == 1
        assert by[name]["matches_expected"] is True
    assert "port_probe_timeout_10035" in by["timeout_probe"]["unproven_reason"]
    for c in cases["cases"]:
        assert c["self_audit_no_kill_path"]["kills_process"] is False

    # the real end state is filed separately from the synthetic fixtures
    real = ev("v01_real_endstate_recheck.json")
    assert real["synthetic"] is False and real["separate_from_synthetic_fixtures"] is True
    assert real["kill_audit"]["kills_process"] is False
    assert real["engine_started"] is False and real["pid_stopped_by_this_tool"] is False
    assert real["verdict_basis"]["engine_port_refused"] is True


# --------------------------------------------------------------------------- V02

def test_v02_role_refs_frozen_from_the_test_only_target_design():
    ref = ev("v02_role_ref_freeze.json")
    assert ref["test_only"] is True and ref["published"] is False
    assert ref["user_approved"] is False and ref["approved_library_pack_exists"] is False
    assert list(ref["roles"]) == ["BOOK", "TURN", "OCC"]
    assert all(ref["checks"].values()), ref["checks"]
    assert ref["verdict"] == "ROLE_REFS_FROZEN_TEST_ONLY"
    assert len(set(ref["frozen_role_to_ref_sha256"].values())) == 1
    assert ref["assets"]["target_design"]["sha256"] != ref["assets"]["source_identity"]["sha256"]
    assert ref["assets"]["target_design"]["target_vs_source"]["max_abs"] > 0
    for role in ("BOOK", "TURN", "OCC"):
        row = ref["roles"][role]
        assert row["frozen_ref_sha256"] == ref["assets"]["target_design"]["sha256"]
        assert row["ref_differs_from_this_roles_source"] is True
        assert row["residual_target_vs_role_frame"]["max_abs"] > 0
        assert os.path.isfile(row["role_frame_png"])
        assert sha256(row["role_frame_png"]) == row["role_frame_sha256"]
    # the measured negative result: no role crop was invented
    assert ref["checks"]["no_role_crop_fabricated"] is True
    assert all(ref["roles"][r]["role_specific_crop_roi"]["role_specific_region"] is False
               for r in ("BOOK", "TURN", "OCC"))
    # the trace and the canonical diff
    trace = ref["loadimage_to_reference_encoder_trace"]
    assert trace["animate_graph_file_sha256"] == "ff134923db899b3a9b84baf05fa2c51c8caeb6420075b1765af979400dc7c02f"
    assert any(c["reaches_clip_vision_encode"] for c in trace["animate_reference_chains"])
    assert any(b["load_image_node"] == "134" for b in trace["vace_reference_bindings"])
    assert ref["canonical_graph_diff"]["differing_fields"] == [
        {"field": "672:587.inputs.pose_end_percent", "baseline": 0, "candidate": 1}]

    # re-running the freeze reproduces the mapping byte-for-byte
    rerun = ev("v02_role_ref_freeze_rerun.json")
    assert rerun["frozen_role_to_ref_sha256"] == ref["frozen_role_to_ref_sha256"]
    assert rerun["roles"] == ref["roles"]
    assert rerun["visual_observation_input"]["sheet_sha256"] == \
        ref["visual_observation_input"]["sheet_sha256"]

    # the visual statement is a separate artifact and is NOT a quality verdict
    obs = ev("v02_visual_observation.json")
    assert obs["label"] == "VISUAL_OBSERVATION_ONLY__NOT_A_QUALITY_VERDICT"
    assert obs["open_item_not_a_pass"]
    assert set(obs["panels"]) == {
        "FROZEN TARGET ref (test-only cast asset)",
        "SOURCE identity (what it must differ from)",
        "BOOK window frame 0", "TURN window frame 0", "OCC window frame 0"}
