"""MF-V1-VIDEO14B round D — registered checks for NR09 (shutdown classifier).

These pin the MEASURED properties of the round-D hardening, on the code AND on the
round's own raw evidence, so a later edit cannot quietly undo them.  Nothing here
starts an engine, loads a model, stops a pid or writes media.

Run:
  cd <worktree> && python -m pytest experiments/mf_reskin_v1/video14b/tests -q
"""
import hashlib
import importlib.util
import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(WT)))
TOOLS = os.path.join(WT, "tools")
EV = ("C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/"
      "mf-core-tool-delivery-20260924/20260924T1557Z/VIDEO14B")
ROUND_C_STATE = ("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/state/"
                 "roundC/v01_fixtures_post")
D_FIXTURES = ("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/state/"
              "roundD/f09_fixtures")
REAL_WAVE2 = ("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
              "mf-reskin-correction-20260922/20260922T0955Z/VIDEO14B/waveB/raw/shutdown")
R28_EVID = ("C:/Users/Admin/Documents/Codex/2026-09-27/c-v-th-c-hi-n/outputs/"
            "r28-cpu-execution-20260927/VIDEO14B")
R28_REPLAY = os.path.join(R28_EVID, "raw", "r28_roundd_replay.json")
# Immutable pins of the HISTORICAL round-D artifact.  d_f09_adversarial_cases.json records the
# classifier that produced it; both are frozen and neither may be compared with the live file.
HISTORICAL_CLASSIFIER_SHA256 = "80eac58f2fb795c5335df0b2291058591275dee4133e74a539aec2828bfc3f64"
HISTORICAL_D_F09_JSON_SHA256 = "1d9aef21cf704e4892ec5fea425d56179015eabcc64eef8607d97c02fc4e6ca4"
UNPROVEN = "SHUTDOWN_UNPROVEN"
CONFIRMED = "SHUTDOWN_CONFIRMED_WITH_DISCLOSED_OWN_CLIENT_EXIT"


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


def clf():
    return load(os.path.join(TOOLS, "w2_classify_shutdown.py"), "mf_d_clf")


# --------------------------------------------------------------------------- NR09

def test_nr09_verified_stop_action_is_pid_scoped_and_never_wide():
    """P2: rc=0 is not a stop; a verified stop names the exact pid and nothing wider."""
    m = clf()
    real_row = ["taskkill", "/PID", "4100", "/F"]
    assert m.verify_stop_argv(real_row, 4100)["verified"] is True
    assert m.verify_stop_argv(real_row, 4100)["widening_switches"] == []

    # a tree-wide or name-wide stop is refused, named, and never accepted
    for argv, why in (
        (["taskkill", "/PID", "4100", "/T", "/F"], "Tree"),
        (["taskkill", "/IM", "python.exe", "/F"], "image"),
        (["taskkill", "/PID", "4101", "/F"], "another pid"),
        (["python.exe", "probe_engine.py"], "not a stop verb"),
        ([], "missing argv"),
    ):
        v = m.verify_stop_argv(argv, 4100)
        assert v["verified"] is False, why
        assert v["problems"], why
    assert "/t" in m.WIDE_KILL_SWITCHES and "/im" in m.WIDE_KILL_SWITCHES

    # rc=0 on a non-stop command, and a stop of a pid outside the owned chain, are both
    # rejected with a reason - the reviewer's variant 3
    chain = [4100]
    before = [{"pid": 4100, "ppid": 1, "name": "python.exe", "ws_mb": "1",
               "cmdline": m.ENGINE_MARK + " --port 8310"}]
    audit = m.verified_stop_actions(
        [{"pid": 4100, "argv": ["python.exe", "probe_engine.py"], "returncode": 0}],
        chain, before)
    assert audit["verified_pids"] == [] and audit["verified"] is False
    assert audit["all_chain_pids_verified"] is False
    assert "not_a_stop_verb" in audit["rejected"][0]["reason"]
    audit2 = m.verified_stop_actions(
        [{"pid": 4200, "argv": ["taskkill", "/PID", "4200", "/F"], "returncode": 0}],
        chain, before)
    assert audit2["verified_pids"] == []
    assert "engine_chain" in audit2["rejected"][0]["reason"]

    # the REAL wave-B stop rows are accepted as verified, and are pid-scoped
    real = json.loads(open(os.path.join(REAL_WAVE2, "wave2_shutdown_evidence.json"),
                           encoding="utf-8").read())
    v = m.verified_stop_actions(real["stop_log"], real["engine_chain_leaf_to_root"],
                                m.dump_rows(__import__("pathlib").Path(REAL_WAVE2)
                                            / "wave2_pids_before_stop.txt"))
    assert set(v["verified_pids"]) == set(real["engine_chain_leaf_to_root"])
    for row in real["stop_log"]:
        low = [str(a).lower() for a in row["argv"]]
        assert low.count("/pid") == 1 and not [w for w in low if w in m.WIDE_KILL_SWITCHES]


def test_nr09_stop_order_is_derived_leaf_to_root_not_declared():
    """A real shutdown walks the verified chain leaf -> root, derived from ppid."""
    m = clf()
    rows = [{"pid": 9588, "ppid": 18304, "cmdline": "launcher"},
            {"pid": 20756, "ppid": 9588, "cmdline": "engine"},
            {"pid": 31000, "ppid": 20756, "cmdline": "worker"}]
    order = m.owner_chain_stop_order([31000, 20756, 9588], rows)
    assert order["derived_leaf_to_root"] == [31000, 20756, 9588]
    assert order["matches_declared"] is True
    # the REAL record's list is root-first; the derivation exposes that instead of
    # trusting the label
    real = m.owner_chain_stop_order([9588, 20756], rows)
    assert real["derived_leaf_to_root"] == [20756, 9588]
    assert real["matches_declared"] is False


def test_nr09_epoch_binding_and_contradiction_detection():
    """P3 + contradictions: only evidence that is PRESENT and disagrees is a conflict."""
    m = clf()
    ok = m.epoch_binding({"instance_epoch": {"port": 8310}}, resolved_port=8310)
    assert ok["bound"] is True and ok["mismatch"] is False
    wrong = m.epoch_binding({"instance_epoch": {"port": 8210}, "port": 8210},
                            resolved_port=8310)
    assert wrong["bound"] is False and wrong["mismatch"] is True
    absent = m.epoch_binding({}, resolved_port=8310)
    assert absent["bound"] is False and absent["mismatch"] is False, \
        "an empty record is missing evidence, never a contradiction"

    c = m.contradiction_report(port_closed=True, connect_ex_after=0, listening_after=[],
                               engine_absent_after=True, epoch_mismatch=False)
    assert c["contradictory"] is True and "connect_ex_after_0" in c["contradictions"][0]
    c2 = m.contradiction_report(port_closed=True, connect_ex_after=10061,
                                listening_after=[], engine_absent_after=False,
                                epoch_mismatch=True)
    assert c2["contradictory"] is True and len(c2["contradictions"]) == 2
    c3 = m.contradiction_report(port_closed=True, connect_ex_after=10035,
                                listening_after=[], engine_absent_after=True,
                                epoch_mismatch=False)
    assert c3["contradictory"] is False


def test_nr09_five_variants_and_controls_are_not_confirmed():
    """The reviewer's five variants plus the unknown/timeout/missing-authority controls."""
    cases = ev("d_f09_adversarial_cases.json")
    assert cases["fixture_is_synthetic"] is True
    assert cases["all_cases_match_expected"] is True
    assert cases["all_match_expected"] is True
    assert cases["all_five_variants_not_confirmed"] is True
    assert len(cases["adversarial_variants"]) == 5
    assert len(cases["controls"]) == 2
    assert len(cases["retained_fixtures"]) == 4
    # V-8 provenance: the round-D JSON is an IMMUTABLE artifact.  It pins the classifier that
    # WROTE it (80eac58f...) and its own bytes are pinned here too.  The live file has moved on
    # twice since (R27 hardening, R28 lifetime authority), so comparing the historical pin with
    # the current source is a false failure - measured 2026-09-27: that comparison asserted
    # 80eac58f == 7ee82ed0.  The historical pin is asserted against the historical artifact and
    # the CURRENT behaviour is asserted from the versioned R28 replay below.
    assert cases["classifier_tool_sha256"] == HISTORICAL_CLASSIFIER_SHA256
    assert sha256(os.path.join(EV, "raw", "d_f09_adversarial_cases.json")) == \
        HISTORICAL_D_F09_JSON_SHA256
    current_classifier_sha = sha256(os.path.join(TOOLS, "w2_classify_shutdown.py"))
    assert current_classifier_sha != HISTORICAL_CLASSIFIER_SHA256, \
        "the current classifier is a later revision: the historical pin cannot be the live file"
    replay = json.loads(open(R28_REPLAY, encoding="utf-8").read())
    assert replay["historical"]["classifier_tool_sha256_pinned_by_round_d"] == \
        HISTORICAL_CLASSIFIER_SHA256
    assert replay["historical"]["round_d_json_sha256"] == HISTORICAL_D_F09_JSON_SHA256
    assert replay["current"]["classifier_tool_sha256"] == current_classifier_sha

    by = {c["case"]: c for c in cases["cases"]}
    expected = {
        "adv_absent_self_exit_receipt": "SHUTDOWN_UNPROVEN",
        "adv_engine_still_present": "SHUTDOWN_UNPROVEN_CONTRADICTION",
        "adv_non_stop_command_rc0": "SHUTDOWN_UNPROVEN",
        "adv_connect_succeeded_but_closed_flag": "SHUTDOWN_UNPROVEN_CONTRADICTION",
        "adv_wrong_epoch_port": "SHUTDOWN_UNPROVEN_CONTRADICTION",
        "ctl_unknown_port_state": "SHUTDOWN_UNPROVEN",
        "ctl_missing_stop_authority": "SHUTDOWN_UNPROVEN",
    }
    for name, want in expected.items():
        assert by[name]["verdict"] == want, (name, by[name]["verdict"])
        assert by[name]["is_confirmed"] is False
        assert by[name]["returncode"] == 1
        assert by[name]["unproven_reason"], name
        assert by[name]["matches_expected"] is True
    assert "own_client_exit_without_self_exit_receipt" in \
        by["adv_absent_self_exit_receipt"]["unproven_reason"]
    assert "engine_pid_still_present_after" in by["adv_engine_still_present"]["unproven_reason"]
    assert "verified_pid_scoped_stop" in by["adv_non_stop_command_rc0"]["unproven_reason"]
    assert "port_closure_not_proven_by_refusal" in \
        by["adv_connect_succeeded_but_closed_flag"]["unproven_reason"]
    assert any("port_closed_true_but_connect_ex_after_0" in x for x in
               by["adv_connect_succeeded_but_closed_flag"]["contradictions"]["contradictions"])
    assert "epoch_port_binding" in by["adv_wrong_epoch_port"]["unproven_reason"]
    assert by["adv_wrong_epoch_port"]["epoch_binding"]["mismatch"] is True
    assert "port_probe_timeout_10035" in by["timeout_probe"]["unproven_reason"]

    # the retained four, including the repaired positive
    assert by["valid_own_chain"]["verdict"] == CONFIRMED
    assert by["valid_own_chain"]["returncode"] == 0
    assert by["valid_own_chain"]["is_confirmed"] is True
    assert by["valid_own_chain"]["collateral_removed"] == []
    assert all(by["valid_own_chain"]["verdict_basis"]["pillars"].values())
    assert by["valid_own_chain"]["self_exit_evidence"]
    for name in ("no_authority", "missing_chain", "timeout_probe"):
        assert by[name]["verdict"] == "SHUTDOWN_UNPROVEN"
        assert by[name]["returncode"] == 1
    assert cases["positive_case_full_provenance"] is True

    # the classifier never kills, and the audit is not vacuous
    for c in cases["cases"]:
        a = c["self_audit_no_kill_path"]
        assert a["kills_process"] is False
        assert a["kill_call_sites"] == []
        assert a["subprocess_call_nodes_inspected"] > 0
        assert a["audit_is_non_vacuous"] is True
        assert a["stop_verbs_are_data_only"] is True
    assert cases["no_case_has_a_kill_path"] is True


def test_nr09_real_endstate_is_separate_and_still_consistent():
    """The real end state is filed apart from the synthetic fixtures, and stays CONFIRMED."""
    cases = ev("d_f09_adversarial_cases.json")
    real = cases["real_endstate"]
    assert real["synthetic"] is False
    assert real["separate_from_synthetic_fixtures"] is True
    assert real["written_by_this_tool"] is False
    assert real["engine_started"] is False and real["pid_stopped_by_this_tool"] is False
    assert real["verdict"] == CONFIRMED and real["matches_expected"] is True
    assert real["epoch_binding"]["bound"] is True
    assert real["verified_stop_audit"]["all_chain_pids_verified"] is True
    assert real["contradictions"]["contradictory"] is False
    assert real["collateral_removed"] == []
    assert real["self_audit_no_kill_path"]["kills_process"] is False
    # the derivation, not the label: the record's own list is root-first
    assert real["stop_order_leaf_to_root"]["declared"] == [9588, 20756]
    assert real["stop_order_leaf_to_root"]["derived_leaf_to_root"] == [20756, 9588]
    assert real["stop_order_leaf_to_root"]["matches_declared"] is False
    assert os.path.isfile(os.path.join(D_FIXTURES, "real_endstate_stdout.json"))

    # the retained round-C fixture directories still answer the same way
    live = {}
    live_reason = {}
    for name in ("no_authority", "missing_chain", "timeout_probe", "valid_own_chain"):
        d = os.path.join(ROUND_C_STATE, name)
        assert os.path.isdir(d), d
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "w2_classify_shutdown.py"),
                            d.replace("\\", "/")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        payload = json.loads(r.stdout)
        live[name] = payload["verdict"]
        live_reason[name] = payload["unproven_reason"]
    assert live["no_authority"] == live["missing_chain"] == live["timeout_probe"] \
        == UNPROVEN
    # V-8: the round-C `valid_own_chain` fixture carries NO frozen epoch snapshot and no declared
    # launch time, so under the R28 authority rules it is UNPROVEN with a named reason.  It is
    # NOT relabelled a positive to keep a count: the CONFIRMED verdict above stays in the
    # HISTORICAL record, and the positive control is the replay's synthetic exact positive, which
    # carries a full independent lifetime authority.
    assert live["valid_own_chain"] == UNPROVEN, live["valid_own_chain"]
    assert "no_validated_independent_epoch_authority" in live_reason["valid_own_chain"]
    replay = json.loads(open(R28_REPLAY, encoding="utf-8").read())
    positive = replay["rows"]["r28_synthetic_exact_positive"]
    assert positive["verdict"] == CONFIRMED and positive["returncode"] == 0
    assert positive["instance_identity_binding"]["lifetime_matches_the_authority"] is True
    assert all(positive["verdict_basis"]["pillars"].values())


def test_nr09_classifier_module_never_executes_a_stop():
    """kill_audit proves the module has no executed stop path; the verbs are data only."""
    m = clf()
    a = m.kill_audit()
    assert a["kills_process"] is False
    assert a["kill_call_sites"] == []
    assert a["subprocess_call_nodes_inspected"] > 0
    assert a["stop_verbs_are_data_only"] is True
    assert a["stop_verbs_are_used_only_to_verify"] == ["verify_stop_argv",
                                                      "verified_stop_actions"]
    src = open(os.path.join(TOOLS, "w2_classify_shutdown.py"), encoding="utf-8").read()
    body = src.split("def main()")[1]
    # main() must not build or run a stop command: no stop verb used as a command string,
    # no reference to the widening-switch list, and no pid-scoped argv literal
    assert '"taskkill"' not in body
    assert "WIDE_KILL_SWITCHES" not in body
    assert '"/pid"' not in body and '"/PID"' not in body


# --------------------------------------------------------------------------- NR08

def test_nr08_per_shot_references_are_real_distinct_pack_bytes():
    """The reviewer's complaint: BOOK/TURN/OCC were three aliases of ONE full-scene PNG."""
    ref = ev("d_role_ref_freeze.json")
    assert ref["test_only"] is True and ref["published"] is False
    assert ref["user_approved"] is False and ref["approved_library_pack_exists"] is False
    assert ref["library_approval_claimed"] is False and ref["demo_claim"] is False
    assert not ref["checks"] or all(ref["checks"].values()), \
        {k: v for k, v in ref["checks"].items() if not v}
    assert all(ref["checks"].values())
    assert ref["verdict"] == "ROLE_REFS_FROZEN_PER_SHOT_FROM_PACK"
    # real, distinct reference bytes instead of three copies of one anchor
    assert len(ref["frozen_cast_to_ref_sha256"]) == 3
    assert len(set(ref["frozen_cast_to_ref_sha256"].values())) == 3
    assert len(ref["identity_reuse_across_shots"]) == 3
    for row in ref["cast_assignment"]["rows"].values():
        assert row["path"].startswith(ref["pack"]["dir"]), row["path"]
        assert os.path.isfile(row["path"])
        assert sha256(row["path"]) == row["sha256"]
        assert os.path.isfile(row["frozen_ref_path"])
        assert sha256(row["frozen_ref_path"]) == row["frozen_ref_sha256"]
        assert row["frozen_ref_sha256"] == row["sha256"]
        assert row["pixels"][0] > 0 and row["pixels"][1] > 0
        assert row["copy_is_byte_identical_to_the_pack_source"] is True
        assert row["pack_git_tree_sha"]
    for shot in ref["shot_inventory"].values():
        for ident in shot["identities"]:
            if ident.get("is_a_full_figure"):
                assert ident["asset_git_blob"], "every frozen pixel needs its git blob"
    pack = ref["pack"]
    assert pack["is_a_usable_pack_in_the_repository"] is True
    assert pack["pack_version"].startswith("presets-characters@")
    assert pack["pack_version_sha256"]
    assert len(pack["complete_six_pose_sets"]) == 4


def test_nr08_shot_inventory_keeps_shot_ids_and_character_ids_apart():
    ref = ev("d_role_ref_freeze.json")
    shots = ref["shot_inventory"]
    assert list(ref["shot_ids"]) == ["BOOK", "TURN", "OCC"]
    assert not (set(ref["shot_ids"]) & set(ref["character_ids"])), \
        "a shot id must never be used as a character id"
    assert shots["TURN"]["identity_count"] == 0
    assert shots["TURN"]["persons_visible_count"] == 0
    assert all(not s["people_added_by_this_freeze"] for s in shots.values())
    for shot, spec in shots.items():
        for ident in spec["identities"]:
            assert ident["frames_visible"], (shot, ident["obs_id"])
            if ident.get("is_a_full_figure"):
                assert ident["identity_id"] and ident["character_id"]
                assert ident["pose_slot"] in ("front", "three_quarter", "side", "back",
                                              "sitting", "walking")
            else:
                assert "NO_FROZEN_REFERENCE" in ident["resolution"]
    partial = [i for s in shots.values() for i in s["identities"]
               if not i.get("is_a_full_figure")]
    assert partial, "the hand-only observation must be recorded and given no reference"


def test_nr08_identity_reuse_is_the_same_bytes_across_shots():
    ref = ev("d_role_ref_freeze.json")
    book = [i for i in ref["shot_inventory"]["BOOK"]["identities"]
            if i.get("identity_id")][0]
    occ = [i for i in ref["shot_inventory"]["OCC"]["identities"] if i.get("identity_id")]
    assert occ, "the OCC seated figure must resolve to the same tracked identity"
    assert occ[0]["identity_id"] == book["identity_id"]
    assert occ[0]["character_id"] == book["character_id"]
    assert occ[0]["pose_slot"] == book["pose_slot"]
    assert occ[0]["asset"] == book["asset"]
    assert occ[0]["frozen_ref_file"] == book["frozen_ref_file"]
    assert occ[0]["frozen_ref_sha256"] == book["frozen_ref_sha256"]
    reuse = [r for r in ref["identity_reuse_across_shots"]
             if r["identity_id"] == book["identity_id"]][0]
    assert [s["shot_id"] for s in reuse["shots"]] == ["BOOK", "OCC"]
    assert len({s["frozen_ref_sha256"] for s in reuse["shots"]}) == 1


def test_nr08_trace_and_canonical_diff_show_the_real_wiring():
    ref = ev("d_role_ref_freeze.json")
    trace = ref["loadimage_to_reference_encoder_trace"]
    # the released graphs are untouched: the pins still hold
    assert ref["released_graphs_untouched"]["pins_hold"] is True
    cand = os.path.join(REPO, trace["candidate_graph"])
    assert os.path.isfile(cand)
    assert sha256(cand) == trace["candidate_graph_sha256"]
    chains = [c for c in trace["animate_reference_chains"] if c["load_image"] == "189"]
    assert chains and chains[0]["reaches_clip_vision_encode"] is True
    nodes = {(s.get("node") or s.get("consumer")): s for s in chains[0]["steps"]}
    assert "672:590" in nodes and "672:589" in nodes
    assert nodes["672:589"]["class_type"] == "CLIPVisionEncode"
    assert nodes["672:590"]["class_type"] == "ResizeImageMaskNode"
    vace = [b for b in trace["vace_reference_bindings"] if b["consumer_node"] == "49"]
    assert vace and vace[0]["input"] == "reference_image"
    assert vace[0]["load_image_file"] == trace["vace_reference_bindings"][0][
        "load_image_file"]
    assert trace["is_approved_library_pack"] is False
    # the diff must SHOW the wiring, not assert it in prose
    diff = ref["canonical_graph_diff"]
    wire = diff["reference_wiring_fields"]
    assert any(d["field"] == "189.inputs.image" for d in wire)
    assert diff["is_the_single_m1_variable"] is False
    assert len(diff["m1_variable_fields"]) == 1
    assert ref["vace_canonical_graph_diff"]["count"] == 1
    # unwired members are marked, and a prop with no reference is marked, never invented
    assert ref["unwired_cast_members"]
    assert all(not m["wired_in_candidate_graph"] and m["reason"]
               for m in ref["unwired_cast_members"])
    assert ref["prop_findings"][0]["fabricated_pixels"] is False
    assert "NO_SEPARABLE_REFERENCE" in ref["prop_findings"][0]["status"]

    # the observation is a separate artifact and is NOT a quality verdict
    obs = ev("d_visual_observation.json")
    assert obs["label"] == "VISUAL_OBSERVATION_ONLY__NOT_A_QUALITY_VERDICT"
    assert obs["open_item_not_a_pass"] is True
    assert ref["visual_observation_input"]["observation_sha256"] == \
        sha256(os.path.join(EV, "raw", "d_visual_observation.json"))
    assert obs["frame_evidence"]["sheet_sha256"] == \
        sha256(obs["frame_evidence"]["sheet"])


def test_r28_versioned_replay_binds_current_behaviour_to_current_bytes():
    """V-8: historical pins stay historical; current behaviour binds to the versioned R28 replay.

    The replay is generated in the R28 evidence root by running the CURRENT classifier over
    versioned copies of the retained fixtures, a synthetic exact positive carrying a full
    independent lifetime authority, and the real wave-B end state read-only.  It records the
    current source shas next to the historical ones, so a reviewer can tell which artefact each
    assertion is about.
    """
    replay = json.loads(open(R28_REPLAY, encoding="utf-8").read())
    assert replay["replay_version"] == "R28" and replay["generated_by_round"] == "R28"
    assert replay["cpu_only"] is True and replay["engine_started"] is False
    assert replay["model_loaded"] is False and replay["pid_stopped_by_this_tool"] is False
    assert replay["runtime_input_written_to"] is False
    assert replay["old_evidence_written_to"] is False
    # --- current bytes, bound by hash
    assert replay["current"]["classifier_tool_sha256"] == \
        sha256(os.path.join(TOOLS, "w2_classify_shutdown.py"))
    assert replay["current"]["anchor_tool_sha256"] == \
        sha256(os.path.join(TOOLS, "i1_make_anchor_graphs.py"))
    assert replay["current"]["classifier_sha_moved"] is True
    # --- historical bytes: immutable, and NOT overwritten by this round
    assert replay["historical"]["classifier_tool_sha256_pinned_by_round_d"] == \
        HISTORICAL_CLASSIFIER_SHA256
    assert replay["historical"]["round_d_json_sha256"] == HISTORICAL_D_F09_JSON_SHA256
    assert sha256(os.path.join(EV, "raw", "d_f09_adversarial_cases.json")) == \
        HISTORICAL_D_F09_JSON_SHA256, "the historical round-D JSON must not be rewritten"
    assert replay["historical"]["immutable"] is True
    # --- the versioned fixtures were copied, and the copies carry the source hashes
    assert replay["fixtures"]["copied"], "no versioned fixture was copied into the root"
    for entry in replay["fixtures"]["copied"]:
        assert entry["file_count"] > 0
        assert os.path.isdir(entry["copied_dir"]), entry["copied_dir"]
    # --- current behaviour, row by row
    rows = replay["rows"]
    assert len(rows) == replay["row_count"] == 17
    for key in ("roundD_f09_fixtures/adv_absent_self_exit_receipt",
                "roundD_f09_fixtures/adv_connect_succeeded_but_closed_flag",
                "roundD_f09_fixtures/adv_engine_still_present",
                "roundD_f09_fixtures/adv_non_stop_command_rc0",
                "roundD_f09_fixtures/adv_wrong_epoch_port",
                "roundD_f09_fixtures/ctl_missing_stop_authority",
                "roundD_f09_fixtures/ctl_unknown_port_state"):
        assert rows[key]["verdict"].startswith(UNPROVEN), (key, rows[key]["verdict"])
        assert rows[key]["is_confirmed"] is False and rows[key]["returncode"] == 1
    for key in ("roundC_v01_fixtures_post/no_authority",
                "roundC_v01_fixtures_post/missing_chain",
                "roundC_v01_fixtures_post/timeout_probe",
                "roundC_v01_fixtures_post/valid_own_chain"):
        assert rows[key]["verdict"] == UNPROVEN, (key, rows[key]["verdict"])
        assert "no_validated_independent_epoch_authority" in rows[key]["unproven_reason"]
    # the reviewer's five variants, judged by the CURRENT classifier: none is confirmed
    for name in ("adv_absent_self_exit_receipt", "adv_engine_still_present",
                 "adv_non_stop_command_rc0", "adv_connect_succeeded_but_closed_flag",
                 "adv_wrong_epoch_port"):
        row = rows["roundD_f09_fixtures/" + name]
        assert row["is_confirmed"] is False, name
        assert row["unproven_reason"], name
    # NOTE (behaviour change, disclosed): `adv_wrong_epoch_port` used to be
    # SHUTDOWN_UNPROVEN_CONTRADICTION because the classifier compared the record against the LIVE
    # runtime port.  With the R28 rule the live file is not an authority, so nothing DISAGREES
    # and the honest verdict is UNPROVEN - which still cannot confirm.  The historical JSON keeps
    # its own, older expectation; this replay records the current one.
    assert rows["roundD_f09_fixtures/adv_wrong_epoch_port"]["verdict"] == UNPROVEN
    assert "epoch_authority:absent" in rows["roundD_f09_fixtures/adv_wrong_epoch_port"][
        "unproven_reason"]
    # --- the synthetic positive needs a FULL independent lifetime authority
    positive = rows["r28_synthetic_exact_positive"]
    snap = positive["frozen_epoch_snapshot"]
    assert positive["verdict"] == CONFIRMED and positive["returncode"] == 0
    assert set(snap) >= {"instance_id", "port", "pid", "launched_at"}
    ident = positive["instance_identity_binding"]
    assert ident["authority_source"] == "evidence_frozen_snapshot"
    assert ident["authority_valid"] is True
    assert ident["lifetime_matches_the_authority"] is True
    assert ident["instance_id_matches_the_authority"] is True
    assert positive["port_decision"]["independently_authoritative"] is True
    assert all(positive["verdict_basis"]["pillars"].values())
    # --- the real end state: no authority in the old record -> current UNPROVEN, historical kept
    real = rows["real_waveB_endstate"]
    assert real["verdict"] == UNPROVEN and real["returncode"] == 1
    assert real["historical_verdict"] == CONFIRMED
    assert real["historical_matches_expected"] is True
    assert real["historical_had_no_authority_fields"] is True
    assert real["frozen_epoch_snapshot_files"] == []
    assert "no_validated_independent_epoch_authority" in real["unproven_reason"]
    assert real["epoch_authority"]["record_declared_epoch"]["complete"] is True, \
        "the real record declares a complete epoch and is still not an authority"
    assert real["epoch_authority"]["record_self_declaration_used_as_authority"] is False
