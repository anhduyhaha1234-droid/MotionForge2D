"""MF-END-17 — controlled_shot_v1 + model_profiles patch: challenger decision (conditional).

Row map (binary):
* micro repro: the delivered artifacts exist, parse, and carry the declared sections;
* activation: the criteria are frozen from the packet, the Wan hard-gate rows are bound
  to the sealed predecessor registry, the measured-failure list is empty, the open items
  are routed (not adjudicated here), and the verdict is SKIPPED_NOT_NEEDED recorded as a
  skip — never as a test pass;
* contract: the G4 controlled-shot contract (correspondence masks + refs + source + frozen
  profile; same hard gates as G3; gate loosening forbidden; no multi-reference claim);
* probe: the SCAIL-2 family is BLOCKED_NO_WEIGHTS with the measured absence recorded, the
  correspondence mask semantics are captured from the installed node source, and 12 GB fit
  is NOT_PROVEN (no inference ever claimed);
* candidates: VACE 14B is measured and INELIGIBLE — real MP4 present, quality FAIL
  (watermark copy), VRAM PASS — with the exact receipt facts; SCAIL cannot run;
* eligibility rule: a candidate is eligible only with real local MP4 + passing quality +
  passing VRAM (three gates), applied verbatim;
* claims: no quality acceptance, no best/newest/fastest claim, no multi-reference claim,
  zero new GPU jobs, not deliverable;
* manifest: binds the artifact bytes, the measured evidence graph, the model hashes with
  hub provenance, the decision mirror, and the preserved failure taxonomy;
* profiles patch: additive only — 2 profiles stay, VACE stays INELIGIBLE with the
  watermark blocker, the End-17 note records the resolution;
* negatives: mutated docs (skip marked as a pass, multi-ref claim, VACE marked eligible,
  watermark gate flipped to pass, gate loosening allowed, empty criteria) are refused.

No GPU, no network, no render here.  Everything is offline validation of delivered bytes.
"""

from __future__ import annotations

import copy as _copy
import hashlib
import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = PROJECT_ROOT / "app" / "media_workflows" / "controlled_shot_v1.json"
MANIFEST_PATH = PROJECT_ROOT / "app" / "media_workflows" / "controlled_shot_v1.manifest.json"
PROFILES_PATH = PROJECT_ROOT / "app" / "media_workflows" / "model_profiles.json"

ARTIFACT_SCHEMA = "mf.controlled_shot.v1"
MANIFEST_SCHEMA = "mf.controlled_shot.manifest.v1"
GRAPH_ID = "controlled_shot_v1"

RUN_ROOT = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-17"
)
PROOF_ROOT = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof"
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")

#: measured facts this task binds (P4 challenger round + node probe)
P4_PROMPT_ID = "402d0c10-fb71-44ca-9250-94029cc3366c"
P4_GRAPH_SHA = "18d97cbabf3b7b473e9810b61ba90e1a07795a28d234bcb86eec66f88e54afeb"
P4_TEMPLATE_SHA = "b0a7e774459a7a5885d0882f89819f0b910273d823834248e8c3ff852ec65be6"
P4_WALL_S = 1174.24
P4_VRAM_MIB = 11680
P4_OUT_RAW_SHA = "691a8530e3f4bdbbf13fb99ffee9abc4e64b43b3617597736098c8d13a756611"
P4_OUT_TRIM_SHA = "32e0963bc39f758894c1dccadbefa1b5adb26b013e064d308cefb28d87ee0274"
VACE_UNET_SHA = "f202a5c59b8a91ada1862c46a038214f1f7f216c61ec8350d25f69b919da4307"
SCAIL_NODE_SHA = "7cd7f3588a7fbdb1d1379ad7fd0669364bbae3d921ba17cfbd9ee007251a980b"
HF_REVISION = "617a7633e636506f850e043bc4605f290a466a8e"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _artifact() -> dict:
    return _load(ARTIFACT_PATH)


def _manifest() -> dict:
    return _load(MANIFEST_PATH)


def _profiles() -> dict:
    return _load(PROFILES_PATH)


# ── the contract predicate the delivered doc must pass (negatives mutate copies of it) ──


def controlled_contract_violations(doc: dict) -> list[str]:
    bad: list[str] = []
    act = doc.get("activation", {})
    verdict = act.get("verdict")
    if verdict not in ("SKIPPED_NOT_NEEDED", "ACTIVATED"):
        bad.append(f"unknown activation verdict: {verdict}")
    if verdict == "SKIPPED_NOT_NEEDED" and act.get("counts_as_test_pass") is not False:
        bad.append("a skip must never be counted as a test pass")
    if verdict == "SKIPPED_NOT_NEEDED" and act.get("wan_measured_hard_constraint_failures"):
        bad.append("skip declared while a measured hard-constraint failure exists")
    if not act.get("criteria"):
        bad.append("activation criteria missing")
    if not act.get("wan_measured_hard_gate_rows"):
        bad.append("activation without the measured gate rows")
    contract = doc.get("contract", {})
    if "FORBIDDEN" not in str(contract.get("gate_loosening", "")):
        bad.append("gate loosening not forbidden")
    if contract.get("multi_reference", {}).get("claimed_multi_ref") is not False:
        bad.append("multi-reference claim without evidence")
    for cand in doc.get("candidates", []):
        status = cand.get("status")
        gates = cand.get("eligibility_gates") or {}
        if status == "ELIGIBLE":
            verdicts = [gates.get(k, {}).get("verdict")
                        for k in ("real_local_mp4", "quality", "vram")]
            if verdicts != ["PASS", "PASS", "PASS"]:
                bad.append(f"{cand.get('id')}: eligible without all three gates passing")
        qual = gates.get("quality", {})
        defect = str(qual.get("defect", "")).lower()
        if "watermark" in defect and qual.get("verdict") == "PASS":
            bad.append(f"{cand.get('id')}: watermark defect recorded but quality marked PASS")
        if cand.get("semantics", {}).get("multi_ref_claim") is True:
            bad.append(f"{cand.get('id')}: multi-ref claim on a single-reference candidate")
    claims = doc.get("claims", {})
    if claims.get("deliverable") is True:
        bad.append("artifact claims deliverable while the path is unsupported")
    if verdict == "SKIPPED_NOT_NEEDED" and claims.get("skip_not_a_pass") is not True:
        bad.append("skip_not_a_pass missing")
    blob = json.dumps(doc).lower()
    for banned in ("best model", "newest model", "fastest model"):
        if banned in blob:
            bad.append(f"banned claim leaked: {banned}")
    return bad


# ── micro repro ───────────────────────────────────────────────────────────────


def test_micro_repro_files_exist_and_parse() -> None:
    for p in (ARTIFACT_PATH, MANIFEST_PATH, PROFILES_PATH):
        assert p.is_file(), f"missing {p}"
        _load(p)
    assert (PROJECT_ROOT / "tests" / "product_delivery" / "test_mf_end_17.py").is_file()


def test_micro_repro_declared_sections_present() -> None:
    a = _artifact()
    m = _manifest()
    assert a["schema_version"] == ARTIFACT_SCHEMA
    assert m["schema_version"] == MANIFEST_SCHEMA
    assert a["graph_id"] == GRAPH_ID == m["graph_id"]
    for key in ("purpose", "derived_from", "runtime_pin", "activation", "contract", "probe",
                "candidates", "path_status", "eligibility_policy", "model_area_policy",
                "claims", "evidence"):
        assert key in a, f"artifact section {key} missing"
    for key in ("workflow", "decision", "candidates", "models", "runtime", "measurement",
                "scail_probe", "failure_taxonomy_preserved", "evidence_root", "claims"):
        assert key in m, f"manifest section {key} missing"


# ── activation / decision ────────────────────────────────────────────────────


def test_activation_criteria_are_frozen_and_reference_the_packet() -> None:
    act = _artifact()["activation"]
    criteria = act["criteria"]
    assert len(criteria) >= 3
    joined = " ".join(criteria).lower()
    assert "input-ready" in joined
    assert "hard constraint" in joined or "hard constraints" in joined
    assert "test pass" in joined
    assert "MF-END-17" in act["criteria_source"]


def test_wan_gate_rows_bind_the_sealed_profile() -> None:
    act = _artifact()["activation"]
    wan = {p["id"]: p for p in _profiles()["profiles"]}["wan_animate2_int8_pad640x368_cacheoff"]
    assert act["wan_measured_hard_gate_rows"] == wan["eligibility"]["hard_gate_rows"]
    verdicts = {r["gate"]: r["verdict"] for r in act["wan_measured_hard_gate_rows"]}
    assert any("OPEN" in v for v in verdicts.values()), "the open rows must stay visible"
    assert all(v != "FAIL" for v in verdicts.values())


def test_no_measured_hard_constraint_failures_and_open_items_routed() -> None:
    act = _artifact()["activation"]
    assert act["wan_measured_hard_constraint_failures"] == []
    ids = {o["id"] for o in act["open_items_routed"]}
    assert {"F5_BOOK_STATE", "F6_RAM_INSTRUMENT"} <= ids
    for item in act["open_items_routed"]:
        assert item["routed_to"], f"{item['id']} lost its routing"


def test_activation_verdict_is_a_skip_not_a_pass() -> None:
    act = _artifact()["activation"]
    assert act["verdict"] == "SKIPPED_NOT_NEEDED"
    assert act["counts_as_test_pass"] is False
    assert _artifact()["claims"]["skip_not_a_pass"] is True
    rationale = act["rationale"].lower()
    assert "trigger is not met" in rationale
    assert "without cause" in rationale or "not run" in rationale


def test_contract_is_the_g4_contract_and_forbids_loosening() -> None:
    contract = _artifact()["contract"]
    assert "G4" in contract["family"]
    assert any("correspondence" in i for i in contract["inputs"])
    assert "same hard gates" in contract["gates"].lower()
    assert contract["gate_loosening"].startswith("FORBIDDEN")
    assert contract["multi_reference"]["claimed_multi_ref"] is False
    assert contract["one_candidate_at_a_time"] is True


# ── probe / candidates ───────────────────────────────────────────────────────


def test_probe_is_blocked_with_measured_absence() -> None:
    probe = _artifact()["probe"]
    assert probe["status"] == "BLOCKED_NO_WEIGHTS"
    assert probe["inference_tested"] == "NOT_RUN"
    assert probe["weights"]["present"] is False
    assert all(v == 0 for v in probe["weights"]["scan_hits"].values())
    assert probe["weights"]["sam3_weights_present"] is False
    assert set(probe["node_ids"]) == {"WanSCAILToVideo", "SCAIL2ColoredMask"}
    assert HEX64.match(probe["node_source"]["sha256"])
    sem = probe["correspondence_graph_semantics"]
    assert sem["palette"]["count"] == 6
    assert "same order" in sem["identity_rule"] or "SAME order" in sem["identity_rule"]


def test_win12gb_is_not_proven_and_not_claimed() -> None:
    win = _artifact()["probe"]["win12gb"]
    assert win["status"] == "NOT_PROVEN_ON_THIS_GPU"
    assert "no SCAIL-2 weights" in win["why"]
    assert win["closest_measured_reference"]["note"].startswith("measured for VACE")


def test_candidate_scail_cannot_run() -> None:
    cand = {c["id"]: c for c in _artifact()["candidates"]}["scail2_wan_scail"]
    assert cand["status"] == "BLOCKED_NO_WEIGHTS"
    assert cand["eligibility"]["verdict"] == "NOT_ELIGIBLE"
    assert "NONE" in cand["eligibility"]["real_local_mp4"]
    assert cand["inference_tested"] == "NOT_RUN"


def test_candidate_vace_is_measured_and_ineligible() -> None:
    cand = {c["id"]: c for c in _artifact()["candidates"]}["vace_14b_fp16_book"]
    assert cand["status"] == "MEASURED_INELIGIBLE"
    assert cand["measured"]["prompt_id"] == P4_PROMPT_ID
    assert cand["measured"]["graph_sha256"] == P4_GRAPH_SHA
    assert cand["measured"]["server_side_wall_s"] == P4_WALL_S
    assert cand["measured"]["vram_peak_mib"] == P4_VRAM_MIB
    outs = {o["sha256"] for o in cand["measured"]["outputs"]}
    assert outs == {P4_OUT_RAW_SHA}
    assert cand["measured"]["comparison_artifact"]["sha256"] == P4_OUT_TRIM_SHA
    assert cand["unsupported_recorded"] is True
    gates = cand["eligibility_gates"]
    assert gates["real_local_mp4"]["verdict"] == "PASS"
    assert gates["quality"]["verdict"] == "FAIL"
    assert "watermark" in gates["quality"]["defect"].lower()
    assert gates["vram"]["verdict"] == "PASS"
    assert gates["verdict"] == "INELIGIBLE"
    assert cand["cases_run"].startswith("1 of 4")
    assert cand["semantics"]["multi_ref_claim"] is False


def test_eligibility_policy_applied_verbatim() -> None:
    pol = _artifact()["eligibility_policy"]
    assert "real local MP4" in pol["rule"]
    assert "quality" in pol["rule"] and "VRAM" in pol["rule"]
    assert pol["no_gate_loosening"] is True
    assert pol["no_multi_ref_claim"] is True
    status = _artifact()["path_status"]["status"]
    assert status == "UNSUPPORTED_ON_THIS_RUNTIME"


def test_no_multi_ref_or_recency_claims_anywhere() -> None:
    blob = json.dumps(_artifact(), ensure_ascii=False).lower()
    banned_phrases = ("supports multi-reference", "supports multiple references",
                      "multi-ref workflow")
    for banned in banned_phrases:
        assert banned not in blob, f"forbidden claim: {banned}"
    for banned in ("best model", "newest model", "fastest model"):
        assert banned not in blob
        assert banned not in json.dumps(_manifest()).lower()
        assert banned not in json.dumps(_profiles()).lower()


def test_zero_gpu_jobs_and_not_deliverable() -> None:
    claims = _artifact()["claims"]
    assert claims["new_gpu_jobs_this_task"] == 0
    assert claims["deliverable"] is False
    assert claims["quality_accepted"] is False
    assert _artifact()["model_area_policy"]["downloads_performed_this_task"] == 0


# ── manifest ─────────────────────────────────────────────────────────────────


def test_manifest_binds_the_artifact_bytes() -> None:
    m = _manifest()["workflow"]
    assert m["graph_file"] == "app/media_workflows/controlled_shot_v1.json"
    assert m["graph_file_sha256"] == _sha256_file(ARTIFACT_PATH)
    assert m["graph_file_bytes"] == ARTIFACT_PATH.stat().st_size
    assert m["shipped_runnable_graph"] is False
    assert "misrepresent" in m["why_no_graph"]


def test_manifest_binds_the_measured_evidence_graph() -> None:
    ev = _manifest()["workflow"]["measured_evidence_graph"]
    assert ev["sha256"] == P4_GRAPH_SHA
    assert ev["node_count"] == 15
    assert ev["node_classes"]["49"] == "WanVaceToVideo"
    assert ev["template_sha256"] == P4_TEMPLATE_SHA
    assert ev["validation_offline"]["p0_object_info"]["ok"] is True
    assert ev["validation_offline"]["p3_object_info_gpu"]["ok"] is True


def test_manifest_models_bind_measured_hashes_and_provenance() -> None:
    models = {row["role"]: row for row in _manifest()["models"]}
    assert set(models) == {"unet", "vae", "text_encoder"}
    for row in models.values():
        assert HEX64.match(row["sha256"]), row
        assert row["bytes"] > 0
        assert row["license"] == "apache-2.0"
        assert row["revision"] == HF_REVISION
        assert row["lfs_oid_equals_measured_sha256"] is True
    assert models["unet"]["sha256"] == VACE_UNET_SHA


def test_manifest_decision_mirrors_the_artifact() -> None:
    d = _manifest()["decision"]
    a = _artifact()["activation"]
    assert d["verdict"] == a["verdict"] == "SKIPPED_NOT_NEEDED"
    assert d["counts_as_test_pass"] is False
    assert d["wan_measured_hard_constraint_failures"] == []
    assert d["rationale"] == a["rationale"]
    assert {o["id"] for o in d["open_items_routed"]} == {o["id"] for o in a["open_items_routed"]}


def test_manifest_failure_taxonomy_preserved() -> None:
    rows = {f["id"]: f for f in _manifest()["failure_taxonomy_preserved"]}
    for fid in ("F1_GEOMETRY_CROP", "F2_PROMPT_CARRYOVER", "F3_SEGMENT_AT_CUT",
                "F4_WATERMARK_COPY", "F5_BOOK_STATE", "F6_RAM_INSTRUMENT",
                "F7_SEAM_FLAG_BOOK", "F8_TURN_TRANSIENT_GLYPH"):
        assert fid in rows, f"missing {fid}"
    assert rows["F4_WATERMARK_COPY"]["status"] == "OPEN_PRODUCT_BLOCKER"
    assert rows["F5_BOOK_STATE"]["status"] == "OPEN_PRODUCT_DECISION"
    assert rows["F6_RAM_INSTRUMENT"]["status"] == "OPEN_INSTRUMENT"


def test_evidence_rows_are_sha_bearing() -> None:
    for row in _artifact()["evidence"]:
        assert row["path"].startswith("proof/")
        assert HEX64.match(row["sha256"]), row["path"]
        assert row["bytes"] > 0


# ── profiles patch ───────────────────────────────────────────────────────────


def test_profiles_patch_is_additive_and_consistent() -> None:
    prof = _profiles()
    assert len(prof["profiles"]) == 2
    ids = {p["id"]: p for p in prof["profiles"]}
    vace = ids["vace_14b_fp16_book"]
    assert vace["eligibility"]["status"] == "INELIGIBLE"
    assert any("watermark" in b.lower() for b in vace["eligibility"]["blockers"])
    ctrl = vace["controlled_artifact"]
    assert ctrl["graph_file"] == "app/media_workflows/controlled_shot_v1.json"
    assert ctrl["controlled_path_status"] == "UNSUPPORTED_ON_THIS_RUNTIME"
    block = prof["controlled_shot"]
    assert block["artifact"] == "app/media_workflows/controlled_shot_v1.json"
    assert block["activation"] == _artifact()["activation"]["verdict"]
    assert block["counts_as_test_pass"] is False
    assert "SKIPPED_NOT_NEEDED" in prof["selection"]["end17_note"]


# ── evidence cross-checks (skipped when the run/proof roots are absent) ──────


def test_reverify_evidence_all_match() -> None:
    raw = RUN_ROOT / "raw" / "evidence_reverify.json"
    if not raw.is_file():
        pytest.skip("reverify raw not present")
    d = _load(raw)
    assert d["verdict"] == "PASS"
    assert d["mismatches"] == 0
    assert len(d["rows"]) >= 20
    assert all(row["verdict"] == "MATCH" for row in d["rows"])
    assert d["cross_links"]["all_equal"] is True
    assert d["graph_validation"]["p0_object_info"]["ok"]
    assert d["graph_validation"]["p3_object_info_gpu"]["ok"]
    assert all(v == "refused" for v in d["ports"].values())


def test_proof_files_still_match_the_bound_hashes() -> None:
    if not PROOF_ROOT.is_dir():
        pytest.skip("proof root not present")
    for rel, expectation in (
        ("graphs/animate2_vace_book.p4.api.json", P4_GRAPH_SHA),
        ("output/p4/animate2_vace_book_p4_00001_.mp4", P4_OUT_RAW_SHA),
        ("output/p4/animate2_vace_book_p4_00001__trim120.mp4", P4_OUT_TRIM_SHA),
    ):
        path = PROOF_ROOT / rel
        assert path.is_file(), f"missing {rel}"
        assert _sha256_file(path) == expectation, rel


def test_scail_probe_raw_matches_the_artifact() -> None:
    raw = RUN_ROOT / "raw" / "scail_probe.json"
    if not raw.is_file():
        pytest.skip("scail probe raw not present")
    probe = _load(raw)
    art = _artifact()["probe"]
    assert probe["source_sha256"] == art["node_source"]["sha256"] == SCAIL_NODE_SHA
    assert probe["node_ids"] == art["node_ids"]
    assert probe["weights"]["weights_present"] is False


def test_model_hashes_raw_confirm_the_manifest() -> None:
    raw = RUN_ROOT / "raw" / "model_full_hashes.json"
    if not raw.is_file():
        pytest.skip("model hash raw not present")
    d = _load(raw)
    assert d["ok"] is True
    by = {f["rel"].split("/")[-1]: f["sha256"] for f in d["files"]}
    models = {row["role"]: row for row in _manifest()["models"]}
    assert by["wan2.1_vace_14B_fp16.safetensors"] == models["unet"]["sha256"]
    assert by["wan_2.1_vae.safetensors"] == models["vae"]["sha256"]
    assert by["umt5_xxl_fp16.safetensors"] == models["text_encoder"]["sha256"]


# ── negatives ────────────────────────────────────────────────────────────────


def test_controlled_doc_passes_its_own_predicate() -> None:
    assert controlled_contract_violations(_artifact()) == []


@pytest.mark.parametrize("name,mutate", [
    ("skip_marked_as_test_pass", lambda d: d["activation"].update({"counts_as_test_pass": True})),
    ("skip_flag_removed", lambda d: d["claims"].update({"skip_not_a_pass": False})),
    ("multi_ref_claimed",
     lambda d: d["contract"]["multi_reference"].update({"claimed_multi_ref": True})),
    ("candidate_multi_ref_claimed",
     lambda d: d["candidates"][1]["semantics"].update({"multi_ref_claim": True})),
    ("vace_marked_eligible", lambda d: d["candidates"][1].update({"status": "ELIGIBLE"})),
    ("vace_eligible_with_flipped_gates",
     lambda d: (d["candidates"][1].update({"status": "ELIGIBLE"}),
                d["candidates"][1]["eligibility_gates"]["quality"].update({"verdict": "PASS"}))),
    ("watermark_gate_flipped_to_pass",
     lambda d: d["candidates"][1]["eligibility_gates"]["quality"].update({"verdict": "PASS"})),
    ("gate_loosening_allowed",
     lambda d: d["contract"].update({"gate_loosening": "allowed for challengers"})),
    ("criteria_emptied", lambda d: d["activation"].update({"criteria": []})),
    ("gate_rows_emptied", lambda d: d["activation"].update({"wan_measured_hard_gate_rows": []})),
    ("skip_despite_measured_failure",
     lambda d: d["activation"].update({"wan_measured_hard_constraint_failures": ["dims FAIL"]})),
    ("deliverable_claim", lambda d: d["claims"].update({"deliverable": True})),
    ("best_model_claim", lambda d: d.update({"purpose": d["purpose"] + " this is the best model"})),
])
def test_negative_control_contract_refusals(name: str, mutate) -> None:
    doc = _copy.deepcopy(_artifact())
    mutate(doc)
    violations = controlled_contract_violations(doc)
    assert violations, f"mutation {name} was not refused"


def test_negative_control_eligibility_predicate_is_exact() -> None:
    def eligible(gates: dict) -> bool:
        checked = ("real_local_mp4", "quality", "vram")
        return [gates[k]["verdict"] for k in checked] == ["PASS", "PASS", "PASS"]

    base = {
        "real_local_mp4": {"verdict": "PASS"},
        "quality": {"verdict": "PASS"},
        "vram": {"verdict": "PASS"},
    }
    assert eligible(base)
    for key in ("real_local_mp4", "quality", "vram"):
        bad = _copy.deepcopy(base)
        bad[key]["verdict"] = "FAIL"
        assert not eligible(bad), key
