#!/usr/bin/env python
"""MF-V1-VIDEO14B wave A — regression tests for the three reviewer corrections.

  F05  test_runner_declares_terminal_outputs_and_rejects_input_only_history
  F06  test_export_drops_decoded_padding_not_bframe_packet
  F07  test_geometry_padding_roundtrip_preserves_content_rect
  F09  test_shutdown_missing_or_ambiguous_authority_is_unproven

F05 is the output-contract boundary shared with MF-V1-COMFY: the runner must
declare `RunSpec.terminal_outputs` and may never widen `allowed_types` back to an
`input` preview (the reviewer's `input-only-result.json` is the reference defect).

Each test pins the MEASURED defect the independent review reported and the exact
property that must now hold, so a later edit cannot reintroduce it.

No engine is started, no model is loaded and no GPU work happens here.  The F06
test re-runs the exporter only when MF_V14B_REAL=1 (it decodes and re-encodes real
frames); by default it checks the recorded run evidence, which was produced by the
same code on the same inputs.

Run:
  cd <worktree> && python -m pytest experiments/mf_reskin_v1/video14b/tests -q
  MF_V14B_REAL=1 python -m pytest ... -q      # adds the fresh export re-run
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

import pytest

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(WT, "tools")
EV = ("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
      "mf-reskin-correction-20260922/20260922T0955Z/VIDEO14B")
RAW = ("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
       "mf-reskin-model-upgrade-20260922/20260922T0345Z/VIDEO14B/wave2/media/"
       "raw_vace14b_book4s_121f.mp4")
FILM = ("C:/Users/Admin/MotionForge2D/projects/2dc14177a212/"
        "Tại_sao_thật_tệ_khi_ĐỨNG_TÊN_HỘ_công_ty_.mp4")
OUT_DIR = "C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/output/waveA_f06"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dec():
    return load(os.path.join(TOOLS, "v14b_export_decode.py"), "mf_v14b_export_decode")


@pytest.fixture(scope="module")
def geo():
    return load(os.path.join(TOOLS, "v14b_geometry.py"), "mf_v14b_geometry")


@pytest.fixture(scope="module")
def shut():
    return load(os.path.join(TOOLS, "w2_classify_shutdown.py"), "mf_w2_classify_shutdown")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------------- F06

def test_export_drops_decoded_padding_not_bframe_packet(dec):
    """The delivered clip must be decoded indices 0..119, never a packet count.

    The reviewer's pixel map proved the old export produced decoded 0..118 + 120
    (raw 119 dropped, the pad kept).  Index selection must therefore be expressed on
    decoded presentation frames, and a single lossless intermediate must separate
    the selection from encode loss.
    """
    # 1. index logic is on decoded frames, not on a packet budget
    assert dec.presentation_indices(121, 120) == list(range(120))
    assert dec.selected_out_decoded_index(121, 120) == [120]
    assert dec.PAD_DECODED_INDEX == 120
    assert "between(n\\,0\\,119)" in dec.select_filter(120)
    assert "setpts=N/30/TB" in dec.select_filter(120)

    # 2. the module's EXECUTION PATH must not contain the old packet-cutting shape
    #    (the module docstring quotes the old command as the defect description, so
    #    only the code below the docstring is inspected)
    src = open(os.path.join(TOOLS, "v14b_export_decode.py"), encoding="utf-8").read()
    main_body = src.split("def main()")[1]
    assert "-frames:v" not in main_body, "packet-count cutting must not come back"
    assert "select_filter(keep)" in main_body, \
        "selection must go through the decoded-frame select filter"
    assert "-c:v\", \"copy\"" not in main_body and "-c:v', 'copy'" not in main_body, \
        "the video stream must not be stream-copied for selection"

    # 3. the recorded run measured a 120-frame CFR clip whose pixel map is identity
    rec = json.loads(open(os.path.join(EV, "raw", "f06_export_record.json"),
                          encoding="utf-8").read())
    assert rec["checks"]["output_frame_count_is_120"] is True
    assert rec["checks"]["pixel_map_is_identity_0_to_119"] is True
    assert rec["checks"]["dropped_frame_absent_from_output"] is True
    assert rec["checks"]["lossless_intermediate_matches_raw_0_to_119"] is True
    assert rec["decoded_frames_raw"] == 121
    assert rec["selected_decoded_indices"] == list(range(120))
    assert rec["dropped_decoded_indices"] == [120]

    pm = json.loads(open(os.path.join(EV, "raw", "f06_pixel_map.json"),
                         encoding="utf-8").read())
    assert len(pm) == 120
    assert pm[-1] == {"output_frame": 119, "matching_raw_decoded_frames": [119]}
    assert all(e["matching_raw_decoded_frames"] == [e["output_frame"]] for e in pm)

    clip = rec["clip_probe"]
    assert clip["presentation_frame_count"] == 120
    assert clip["presentation_pts_first"] == 0
    assert clip["presentation_pts_last"] == 60928
    assert clip["presentation_delta_set"] == [512]
    assert clip["r_frame_rate"] == "30/1"
    assert float(clip["duration"]) == 4.0
    # the raw render really is a valid CFR file (the old "impossible PTS" claim)
    raw = rec["raw_render_probe"]
    assert raw["presentation_frame_count"] == 121
    assert raw["presentation_pts_first"] == 0
    assert raw["presentation_pts_last"] == 61440
    assert raw["presentation_delta_set"] == [512]
    # encode loss is recorded separately and is zero for the lossless re-encode
    assert rec["encode_loss_vs_intermediate"]["mae_max"] == 0.0
    assert rec["encode_loss_vs_intermediate"]["identical_frames"] == 120


@pytest.mark.skipif(os.environ.get("MF_V14B_REAL") != "1",
                    reason="set MF_V14B_REAL=1 to re-run the real export")
def test_export_rerun_on_real_raw_render(dec, tmp_path):
    """Fresh run of the same exporter on the real 121-frame render."""
    out = tmp_path / "out"
    ev = tmp_path / "ev"
    work = tmp_path / "work"
    argv = [sys.executable, os.path.join(TOOLS, "v14b_export_decode.py"),
            RAW, FILM, str(out).replace("\\", "/"), str(ev).replace("\\", "/"),
            str(work).replace("\\", "/")]
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    rec = json.loads((ev / "f06_export_record.json").read_text(encoding="utf-8"))
    assert rec["checks"]["pixel_map_is_identity_0_to_119"] is True
    assert rec["checks"]["dropped_frame_absent_from_output"] is True
    assert rec["checks"]["output_frame_count_is_120"] is True


# ------------------------------------------------------------------------- F07

def test_geometry_padding_roundtrip_preserves_content_rect(geo):
    """pad 360 -> 368 by translation, crop back -> identical content at identical
    coordinates.  368 is the generation canvas, never the expected geometry, and a
    resampled (stretched) control must fail this same test."""
    rec = geo.prove_roundtrip()
    assert rec["verdict"] == "PASS"
    assert rec["source_geometry"] == [640, 360]
    assert rec["generation_canvas"] == [640, 368]
    for k in ("padded_height_is_368", "roundtrip_is_byte_identical",
              "roundtrip_sha256_equal", "content_rect_preserved_at_same_coordinates",
              "top_pad_bar_is_blank", "bottom_pad_bar_is_blank",
              "row0_marker_lands_on_canvas_row_4",
              "last_content_row_lands_on_canvas_row_363",
              "column0_unchanged", "column639_unchanged", "no_rescale_in_pad_path"):
        assert rec["checks"][k] is True, k
    assert rec["row0_marker_canvas_row"] == 4
    assert rec["last_content_row_canvas_row"] == 363
    assert rec["roundtrip_sha256"] == rec["grid_sha256"]
    # crop-back is the inverse: it returns 360, so 368 is not the expected value
    assert geo.crop_image(geo.pad_image(geo.synthetic_grid())).size == (640, 360)

    # the defect the review reported: 360 -> 368 by RESAMPLING does not survive
    d = rec["defect_control_stretch_360_to_368"]
    assert d["roundtrip_is_byte_identical"] is False
    assert d["content_rect_preserved_at_same_coordinates"] is False
    assert d["after_crop_back_vs_source"]["identical"] is False
    assert d["after_crop_back_vs_source"]["differing_pixels"] > 0
    assert round(d["vertical_mismatch_pct"], 4) == 2.2222

    # the same round-trip on the REAL control bytes
    real = json.loads(open(os.path.join(EV, "raw", "f07_real_inputs.json"),
                           encoding="utf-8").read())
    assert real["checks"]["source_padded_is_640x368"] is True
    assert real["checks"]["control_padded_is_640x368"] is True
    assert real["checks"]["cropped_back_is_640x360"] is True
    assert real["checks"]["real_control_frames_byte_identical_through_pad_crop"] is True
    assert real["frame_sha256_original"] == real["frame_sha256_roundtrip"]
    assert len(real["frame_sha256_original"]) == 121


# ------------------------------------------------------------------------- F09

def test_shutdown_missing_or_ambiguous_authority_is_unproven(shut, tmp_path):
    """Missing dumps / missing chain / a timeout probe must all be UNPROVEN, while a
    complete own-chain record still CONFIRMs, and the classifier must never stop a
    process."""
    # --- unit level: the authority gate
    empty = shut.authority_report(before_rows=[], after_rows=[], chain_pids=[],
                                  stop_log=[], port_closed=True)
    assert empty["authoritative"] is False
    assert "before_process_dump" in empty["missing_authority"]
    assert "after_process_dump" in empty["missing_authority"]
    assert "engine_process_chain" in empty["missing_authority"]
    assert "stop_log" in empty["missing_authority"]

    # a real engine chain is e.g. [{"pid": 4100, "cmdline": "serve_video14b.py"}]
    before = [{"pid": 4100}, {"pid": 4200}]
    after = [{"pid": 4200}]
    stop_log = [{"pid": 4100, "returncode": 0}]

    # missing engine chain (empty set must not "succeed")
    assert shut.authority_report(before_rows=before, after_rows=after, chain_pids=[],
                                 stop_log=stop_log, port_closed=True)["authoritative"] is False
    # missing stop log
    assert shut.authority_report(before_rows=before, after_rows=after, chain_pids=[4100],
                                 stop_log=[], port_closed=True)["authoritative"] is False
    # missing port evidence entirely
    assert shut.authority_report(before_rows=before, after_rows=after, chain_pids=[4100],
                                 stop_log=stop_log, port_closed=None)["authoritative"] is False
    # a TIMEOUT (10035 WSAEWOULDBLOCK) is not a closed port
    t = shut.authority_report(before_rows=before, after_rows=after, chain_pids=[4100],
                              stop_log=stop_log, port_closed=True, port_error_code=10035)
    assert t["authoritative"] is False
    assert "port_probe_timeout_10035" in t["missing_authority"]
    # the valid own-chain record IS authoritative (positive control)
    ok = shut.authority_report(before_rows=before, after_rows=after, chain_pids=[4100],
                               stop_log=stop_log, port_closed=True, port_error_code=10061)
    assert ok["authoritative"] is True
    assert ok["missing_authority"] == []

    # --- the classifier itself, on the reviewer's exact repro
    d = tmp_path / "no_authority"
    d.mkdir()
    (d / "wave2_shutdown_evidence.json").write_text('{"port_closed": true}',
                                                    encoding="utf-8")
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "w2_classify_shutdown.py"),
                        str(d).replace("\\", "/")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    payload = json.loads(r.stdout)
    assert payload["verdict"] == "SHUTDOWN_UNPROVEN"
    assert payload["verdict"].startswith("SHUTDOWN_CONFIRMED") is False
    assert r.returncode == 1
    assert "engine_process_chain" in payload["authority"]["missing_authority"]
    assert payload["self_audit_no_kill_path"]["kills_process"] is False

    # --- the recorded adversarial matrix
    cases = json.loads(open(os.path.join(EV, "raw", "f09_cases.json"),
                            encoding="utf-8").read())
    assert cases["all_match_expected"] is True
    by = {c["case"]: c for c in cases["cases"]}
    assert by["no_authority"]["verdict"] == "SHUTDOWN_UNPROVEN"
    assert by["missing_chain"]["verdict"] == "SHUTDOWN_UNPROVEN"
    assert by["timeout_probe"]["verdict"] == "SHUTDOWN_UNPROVEN"
    assert by["valid_own_chain"]["verdict"].startswith("SHUTDOWN_CONFIRMED")
    for c in cases["cases"]:
        assert c["self_audit_no_kill_path"]["kills_process"] is False
        assert c["self_audit_no_kill_path"]["kill_call_sites"] == []
    # the end-state re-check is read-only and separate from the stop action
    ro = by["no_authority"]["read_only_recheck"]
    assert ro is not None and ro["port_8210"]["listener_accepted"] is False


# ------------------------------------------------------------------------- F05

COMFY_PKG = ("C:/Users/Admin/Documents/Codex/work/mfv1/wt-comfy/"
             "experiments/mf_reskin_v1/comfy")
UI_VACE = os.path.join(WT, "workflows", "run", "mf_vace14b_book4s.json")
UI_ANIMATE = os.path.join(WT, "workflows", "run", "mf_animate2_book4s.json")
RUNNER = os.path.join(TOOLS, "w2_run_stage.py")
REVIEWER_INPUT_ONLY = ("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                       "mf-upgrade-review-20260922/root-probes/input-only-result.json")


@pytest.fixture(scope="module")
def runner():
    """The stage runner with the FROZEN COMFY adapter imported read-only.

    Importing it runs the module-level `sys.path` insert and the `mf_comfy`
    import (nothing else -- `main()` is guarded), so this exercises the REAL
    policy the wave-B GPU job runs under, not a copy of it.  Nothing is written
    inside `wt-comfy`.
    """
    return load(RUNNER, "mf_w2_run_stage")


def api_class_map(ui_path):
    """`node_id -> class_type` for the nodes a real run actually sends.

    The API prompt itself is the pinned frontend's job (`w2_convert_ui_to_api.py`
    needs a live server, which this CPU round must not start).
    `declared_terminal_outputs` reads exactly one field per node -- `class_type`
    -- and the frontend drops muted (mode 2) / bypassed (mode 4) nodes, so this
    reproduces the released run copy's node set faithfully for the field under
    test.
    """
    ui = json.loads(open(ui_path, encoding="utf-8").read())
    out = {}
    for n in ui.get("nodes") or []:
        if n.get("mode") in (2, 4):      # muted / bypassed: absent from the prompt
            continue
        out[str(n.get("id"))] = {"class_type": n.get("type")}
    return out


def test_runner_declares_terminal_outputs_and_rejects_input_only_history(runner, tmp_path):
    """F05: the runner declares the workflow's SAVE nodes, and an `input` preview
    can no longer be published as a product.

    Reviewer defect (the reference: `READ/root-probes/input-only-result.json`): a
    history whose only artifact was `{"filename": "source.png", "type": "input"}`
    came back `status: validated` under the runner that passed
    `allowed_types=("output", "input")` -- and a real VACE success was rejected
    because the adapter had picked the input-preview node instead.
    """
    from mf_comfy.adapter import PUBLISHABLE_SERVER_TYPES
    from mf_comfy.errors import ArtifactMissing

    # (1) the widening is gone from the source text AND from the module constant.
    #     The source-text check comes first so the preimage goes RED for the real
    #     reason ("the runner must not widen ...") instead of an AttributeError.
    src = open(RUNNER, encoding="utf-8").read()
    assert '("output", "input")' not in src, \
        "the runner must not widen the publishable server-types set"
    assert "allowed_types=ALLOWED_SERVER_TYPES" in src, \
        "the RunSpec must take the narrowed set from the one declaration"
    assert tuple(runner.ALLOWED_SERVER_TYPES) == tuple(PUBLISHABLE_SERVER_TYPES)
    assert runner.ALLOWED_SERVER_TYPES == ("output",)
    assert "input" not in PUBLISHABLE_SERVER_TYPES

    # (2) the REAL released VACE run copy: SaveVideo 114 is the declared terminal
    #     output, and the loader / preview / codec nodes are not declared at all
    declared = runner.declared_terminal_outputs(api_class_map(UI_VACE))
    assert declared == {"114": {"kind": "videos", "media_type": "video",
                                "server_types": ("output",)}}, declared
    for not_terminal in ("145", "146", "68"):   # LoadVideo / PreviewImage / CreateVideo
        assert not_terminal not in declared

    # (3) the released Wan-Animate-2 run copy: every declared node is a video
    #     product, and its LoadVideo (240) is never declared
    anim = runner.declared_terminal_outputs(api_class_map(UI_ANIMATE))
    assert sorted(anim) == ["246", "292"], anim
    assert all(c["kind"] == "videos" and c["media_type"] == "video"
               for c in anim.values()), anim
    assert "240" not in anim

    # (4) the declaration reaches the RunSpec the adapter actually receives
    sys.path.insert(0, os.path.join(COMFY_PKG, "tests"))
    assert COMFY_PKG in sys.path or os.path.join(COMFY_PKG, "tests") in sys.path
    from fake_transport import history_success, light_graph, make_rig
    spec = runner.build_run_spec(light_graph(), "wf_f05", {}, 5.0,
                                 attempt_id="att-f05", node_inventory_sha256="")
    assert spec.allowed_types == ("output",)
    assert spec.terminal_outputs == {"9": {"kind": "images", "media_type": "image",
                                           "server_types": ("output",)}}
    assert spec.attempt_id == "att-f05"
    assert spec.owner == "video14b"

    # (5) the reviewer's defect: an input-only history FAILS and stages nothing
    rig = make_rig(tmp_path / "input_only")
    rig.transport.history_map["pid-1"] = history_success("pid-1", "source.png",
                                                         server_type="input")
    with pytest.raises(ArtifactMissing):
        rig.adapter.run(spec)
    assert not list(rig.paths.root.rglob("*.png")), \
        "an input-only history must not produce a product"

    # ... and it still fails for a caller that widens allowed_types: the
    #     declaration may only NARROW the publishable set
    widened = runner.build_run_spec(light_graph(), "wf_f05", {}, 5.0,
                                    node_inventory_sha256="")
    widened.allowed_types = ("output", "input")
    rig2 = make_rig(tmp_path / "input_only_widened")
    rig2.transport.history_map["pid-1"] = history_success("pid-1", "source.png",
                                                          server_type="input")
    with pytest.raises(ArtifactMissing):
        rig2.adapter.run(widened)
    assert not list(rig2.paths.root.rglob("*.png"))

    # (6) positive control: the SAME declaration accepts the server's own output,
    #     so the failures above are not vacuous
    rig3 = make_rig(tmp_path / "real_output")
    rig3.transport.history_map["pid-1"] = history_success("pid-1", "product.png")
    out = rig3.adapter.run(spec)
    assert out.status == "validated"
    assert [a["filename"] for a in out.artifacts] == ["product.png"]
    assert [a["server_type"] for a in out.artifacts] == ["output"]

    # (7) the reviewer's recorded repro, replayed verbatim against this spec
    rec = json.loads(open(REVIEWER_INPUT_ONLY, encoding="utf-8").read())
    assert rec["status"] == "validated"          # the DEFECT, as recorded
    assert rec["history"]["outputs"]["9"]["images"][0]["type"] == "input"
    rig4 = make_rig(tmp_path / "replay")
    rig4.transport.history_map["pid-1"] = rec["history"]
    with pytest.raises(ArtifactMissing):
        rig4.adapter.run(spec)
    assert not list(rig4.paths.root.rglob("*.png")), \
        "the reviewer's input-only result must not be reproducible as a product"

    # (8) a graph with no save node is refused BEFORE any POST (fail closed)
    nosave = {"5": {"class_type": "EmptyLatentImage",
                    "inputs": {"width": 64, "height": 64, "batch_size": 1}}}
    assert runner.declared_terminal_outputs(nosave) == {}
    nosave_path = tmp_path / "nosave.api.json"
    nosave_path.write_text(json.dumps(nosave), encoding="utf-8")
    out_dir = tmp_path / "nosave_out"
    proc = subprocess.run(
        [sys.executable, RUNNER, str(nosave_path).replace("\\", "/"),
         "f05_guard", "wf_f05_nosave", str(out_dir).replace("\\", "/")],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 3, proc.stdout[-800:] + proc.stderr[-800:]
    payload = json.loads(proc.stdout)
    assert payload["status"] == "refused_no_terminal_output"
    assert not (out_dir / "run_record.json").exists(), \
        "a refused graph must not have submitted anything (no run record)"
