"""MF-V1-VIDEO14B round R27 -- frozen rows for the input/event/epoch corrections (CPU only).

Thirteen frozen rows (Manager MATRIX gates on these names):

  R27-01 right INPUT   : alpha is composited ONCE onto a flat neutral background and the
                         graph points at that derived, opaque file whose sha256 is pinned;
                         the immutable original RGBA stays byte-identical; the resize keeps
                         the aspect with no crop and no stretch; a declared pose the file's
                         own pixels contradict is a typed refusal.
  R27-02 right EVENT   : a prompt asserting an event state the FIRST frame does not show is
                         a typed refusal (the BOOK prompt used to demand an open two-page
                         book with both hands on it: index 0 shows an upright closed cover);
                         the partial/edge person is declared instead of silently dropped.
  R27-06 right EPOCH   : the verdict is bound to the immutable INSTANCE identity + matching
                         process lifetime, not to a reusable port; a record with no instance
                         id, or another instance's id on the same port, cannot confirm, and a
                         NEWER live epoch is never attached to old evidence.

Nothing here starts an engine, loads a model, stops a pid, or writes media.

Run:
  cd <worktree> && python -m pytest experiments/mf_reskin_v1/video14b/tools -q
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(WT, "tools")
EVID = ("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
        "mf-cpu-input-correction-20260927/20260927T051440Z/VIDEO14B")
INPUT_ROOT = "C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/input"
CLASSIFIER = os.path.join(TOOLS, "w2_classify_shutdown.py")
ANCHOR_BUILDER = os.path.join(TOOLS, "i1_make_anchor_graphs.py")
RETAINED_HELPERS = os.path.join(TOOLS, "v14b_f09_cases.py")
CONFIRMED = "SHUTDOWN_CONFIRMED_WITH_DISCLOSED_OWN_CLIENT_EXIT"
NEUTRAL_BG = (128, 128, 128)
DAN_CHOI_DERIVED = "i1d_cast_dan_choi_standing_on_neutral_bg.png"
REF_DIR = "roundD_refs"

# Measured 2026-09-27 on the frozen round-D references; these are the IMMUTABLE originals.
ORIGINAL_REF_SHA256 = {
    "cast_boy_hacker_sitting.png":
        "a60969452f904e5e7249db1ff43d7b552f8d7105fa6bff84c6bc32b9273d02c4",
    "cast_dan_choi_standing.png":
        "271f1c5789ee8fb9022ab402d834c8f2d4e862f972a105060e457b68b0282496",
    "cast_gau_nau_back.png":
        "9658aa3a947ffbf3c062757380438c36eb05bd2959444dddc659afbc60bffd11",
}
DERIVED_SHA256 = {
    DAN_CHOI_DERIVED:
        "2ffc245346340b4cc95ffa4c5ac9f3ad3e4485927a655e6a47ab960e5c848969",
    "i1d_cast_boy_hacker_sitting_on_neutral_bg.png":
        "a2ad4db98ac733c969260d052f35e737c37eef664b1b36d5a6fd9a7254006821",
    "i1d_cast_gau_nau_back_on_neutral_bg.png":
        "49e99094d802495dd92e1dbab87125806efcb077f0be37125738b7218a63096f",
}
DAN_CHOI_H_OVER_W = 1.364548
FROZEN_SNAPSHOT_INSTANCE = "frozen-run-instance-aaaa2904"
FOREIGN_INSTANCE = "foreign-instance-bbbb7712"
RESTARTED_INSTANCE = "restarted-instance-cccc5521"
GOLDEN_PAGE_STATES = [
    {"state": "cover_upright", "frames": [0, 71], "time_s": [0.0, 2.3667]},
    {"state": "open_two_pages", "frames": [72, 119], "time_s": [2.4, 3.9667]},
]

_MODS: dict = {}


def load(path: str, name: str):
    if name not in _MODS:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        _MODS[name] = mod
    return _MODS[name]


def anchor():
    return load(ANCHOR_BUILDER, "mf_r27_anchor")


def clf():
    return load(CLASSIFIER, "mf_r27_clf")


def retained():
    return load(RETAINED_HELPERS, "mf_r27_retained_helpers")


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def proposal_spec() -> dict:
    return json.loads((Path(EVID) / "graph_proposals" / "roundI1_spec.json")
                      .read_text(encoding="utf-8"))


def proposal_graph(shot: str) -> dict:
    return json.loads((Path(EVID) / "graph_proposals" / f"anchor_{shot.lower()}.i1.api.json")
                      .read_text(encoding="utf-8"))


def book_instruction() -> str:
    return proposal_spec()["graphs"]["BOOK"]["instruction"]


def ref_row(shot: str, needle: str) -> dict:
    rows = [r for r in proposal_spec()["graphs"][shot]["refs"] if needle in r["file"]]
    assert rows, f"no {shot} reference matching {needle!r}"
    return rows[0]


def _record(test: str, row: dict) -> dict:
    """File this row's measured values under <EVID>/raw/r27_frozen_rows.json."""
    p = Path(EVID) / "raw" / "r27_frozen_rows.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    data.setdefault("artifact", "r27_frozen_rows.json")
    data.setdefault("task_id", "MF-V1-VIDEO14B")
    data.setdefault("round", "R27")
    data.setdefault("engine_started", False)
    data.setdefault("model_loaded", False)
    data.setdefault("pid_stopped_by_this_tool", False)
    data["test_module"] = os.path.basename(__file__)
    data["test_module_sha256"] = sha256_file(__file__)
    data.setdefault("rows", {})[test] = row
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return row


def _rgba(arr):
    from PIL import Image
    import numpy as np
    return Image.fromarray(np.asarray(arr, dtype="uint8"), "RGBA")


def _workdir() -> Path:
    """A SHORT native temp root (MAX_PATH guard) for the synthetic epoch fixtures."""
    return Path(tempfile.mkdtemp(prefix="mf_r27_"))


def _run_classifier(fixture_dir) -> tuple:
    r = subprocess.run([sys.executable, CLASSIFIER, str(fixture_dir).replace("\\", "/")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    payload = json.loads(r.stdout)
    return r.returncode, payload


def _frozen_snapshot(port: int) -> dict:
    return {"instance_id": FROZEN_SNAPSHOT_INSTANCE, "port": port, "pid": 4100,
            "launched_at": 1790420879.1671743, "owner": "video14b",
            "base_url": f"http://127.0.0.1:{port}", "host": "DESKTOP-B5TR9HD"}


# --------------------------------------------------------------- R27-01 right INPUT
def test_r27_alpha_opaque_render_input():
    """An opaque cutout is composited on the neutral bg; its own RGB is untouched."""
    import numpy as np
    m = anchor()
    arr = np.zeros((4, 4, 4), dtype="uint8")
    arr[:, :, 0], arr[:, :, 1], arr[:, :, 2] = 17, 34, 51
    arr[:, :, 3] = 255
    out = m.render_encoder_input(_rgba(arr))
    a = np.asarray(out)
    assert out.mode == "RGB", out.mode
    assert tuple(a[0, 0]) == (17, 34, 51)
    assert (a[:, :, 0] == 17).all() and (a[:, :, 2] == 51).all()
    assert a.shape == (4, 4, 3), "the encoder input must have NO alpha channel"
    buf = io.BytesIO()
    out.save(buf, "PNG")
    row = _record("test_r27_alpha_opaque_render_input", {
        "case": "opaque_cutout", "input_mode": "RGBA alpha=255",
        "encoder_input_mode": out.mode,
        "encoder_input_png_bytes": len(buf.getvalue()),
        "encoder_input_png_sha256": hashlib.sha256(buf.getvalue()).hexdigest(),
        "encoder_input_array_sha256": hashlib.sha256(a.tobytes()).hexdigest(),
        "pixels_equal_the_source_rgb": True, "neutral_bg_rgb": list(NEUTRAL_BG)})
    assert len(row["encoder_input_png_sha256"]) == 64 and row["encoder_input_png_bytes"] > 0


def test_r27_alpha_full_transparent_render_input():
    """Fully transparent pixels contribute NO RGB: they are exactly the neutral bg."""
    import numpy as np
    m = anchor()
    darks = np.zeros((3, 3, 4), dtype="uint8")
    darks[:, :, 3] = 0                       # dark RGB, fully transparent
    brights = np.zeros((3, 3, 4), dtype="uint8")
    brights[:, :, :3] = 255
    brights[:, :, 3] = 0                     # white RGB, fully transparent
    a = np.asarray(m.render_encoder_input(_rgba(darks)))
    b = np.asarray(m.render_encoder_input(_rgba(brights)))
    assert (a == np.array(NEUTRAL_BG, dtype="uint8")).all(), a[0, 0]
    assert (b == a).all(), "transparent RGB must not bleed through the background"
    row = _record("test_r27_alpha_full_transparent_render_input", {
        "case": "fully_transparent", "dark_rgb_result": [int(v) for v in a[0, 0]],
        "white_rgb_result": [int(v) for v in b[0, 0]],
        "output_is_exactly_the_neutral_bg": True,
        "transparent_rgb_contributed": False})
    assert row["output_is_exactly_the_neutral_bg"] is True


def test_r27_alpha_partial_render_input():
    """Partial alpha is composited correctly and blended ONCE (no double blend)."""
    import numpy as np
    m = anchor()
    arr = np.zeros((2, 2, 4), dtype="uint8")
    arr[:, :, 0] = 255
    arr[:, :, 3] = 128
    img = _rgba(arr)
    once = np.asarray(m.render_encoder_input(img))
    a = 128 / 255.0
    expected = np.rint(np.array([255.0, 0.0, 0.0]) * a
                       + np.array(NEUTRAL_BG, dtype="float64") * (1 - a))
    assert (once[0, 0] == expected.astype("uint8")).all(), (once[0, 0], expected)
    assert once[0, 0, 0] == 192, once[0, 0, 0]          # measured single-blend value
    # feeding the composite back through the same blend MUST change it: that is what a
    # double blend looks like, and it must not be what this function did.
    twice = np.asarray(m.render_encoder_input(
        _rgba(np.dstack([once, np.full((2, 2, 1), 128, dtype="uint8")]))))
    assert (twice[0, 0] != once[0, 0]).any(), "composite was applied twice"
    row = _record("test_r27_alpha_partial_render_input", {
        "case": "partial_alpha", "alpha": 128, "rgb": [255, 0, 0],
        "single_blend_value": [int(v) for v in once[0, 0]],
        "documented_formula": "round(rgb*a + bg*(1-a)), a=alpha/255",
        "second_blend_value": [int(v) for v in twice[0, 0]],
        "blend_count": 1, "double_blend_detected": False})
    assert row["blend_count"] == 1


def test_r27_inference_input_hash_pinned_in_graph():
    """The graph LoadImage points at the DERIVED input and the derived sha is pinned."""
    spec = proposal_spec()
    graph = proposal_graph("BOOK")
    row = ref_row("BOOK", "dan_choi")
    assert row["alpha_was_composited"] is True
    assert row["loadimage_value"] == DAN_CHOI_DERIVED, row["loadimage_value"]
    loads = {k: v["inputs"]["image"] for k, v in graph.items()
             if v["class_type"] == "LoadImage"}
    assert DAN_CHOI_DERIVED in loads.values(), loads
    derived = Path(EVID) / "derived_inference_input" / DAN_CHOI_DERIVED
    live = sha256_file(derived)
    assert live == row["derived_sha256"] == DERIVED_SHA256[DAN_CHOI_DERIVED]
    assert row["derived_sha256"] != row["frozen_sha256"], "the raw RGBA must not be re-pointed"
    assert row["source_representation"] == "alpha_composited_on_neutral_bg"
    assert spec["neutral_bg_rgb"] == list(NEUTRAL_BG)
    assert row["measured_pixels"]["near_black_rgb_fraction"] > 0.98, \
        "the measurement that motivates the fix"
    _record("test_r27_inference_input_hash_pinned_in_graph", {
        "loadimage_value": row["loadimage_value"], "derived_sha256": row["derived_sha256"],
        "derived_bytes": row["derived_bytes"], "frozen_sha256": row["frozen_sha256"],
        "derived_exists_on_disk": derived.is_file(),
        "derived_is_opaque": not row["measured_pixels"]["has_alpha"]
        or row["source_representation"] == "alpha_composited_on_neutral_bg",
        "raw_near_black_fraction": row["measured_pixels"]["near_black_rgb_fraction"],
        "staging_plan": row.get("staging_plan"),
        "all_composited_refs_pinned": all(
            r["derived_sha256"] == DERIVED_SHA256[r["loadimage_value"]]
            for r in spec["graphs"]["BOOK"]["refs"] if r.get("alpha_was_composited"))})


def test_r27_source_png_unmodified():
    """The original RGBA files are byte-identical after the whole run, and not written to."""
    for name, want in ORIGINAL_REF_SHA256.items():
        p = Path(INPUT_ROOT) / REF_DIR / name
        assert p.is_file(), p
        assert sha256_file(p) == want, f"{name} changed on disk"
    spec = proposal_spec()
    for shot in ("BOOK", "TURN", "OCC"):
        for r in spec["graphs"][shot]["refs"]:
            assert r["frozen_sha256"] == sha256_file(r["frozen_path"]), r["frozen_path"]
            if r.get("alpha_was_composited"):
                assert r["staging_plan"]["staging_state"] == \
                    "NOT_PERFORMED_THIS_ROUND_RUNTIME_INPUT_IS_READ_ONLY"
                assert not (Path(INPUT_ROOT) / r["loadimage_value"]).exists(), \
                    "this CPU round must not write into the runtime input dir"
    row = _record("test_r27_source_png_unmodified", {
        "originals": {n: sha256_file(Path(INPUT_ROOT) / REF_DIR / n)
                      for n in ORIGINAL_REF_SHA256},
        "match_pinned": True,
        "runtime_input_dir_written_to": False,
        "staged_derived_files_present_in_input_dir": 0})
    assert row["match_pinned"] is True


def test_r27_no_stretch_no_crop_aspect_preserved():
    """The resize scales the longer side with ONE factor: aspect kept, no crop, no stretch."""
    m = anchor()
    plans = {}
    for w, h in ((1024, 1024), (768, 512), (640, 640), (1024, 768), (513, 291)):
        plan = m.resize_plan(w, h)
        plans[f"{w}x{h}"] = plan
        assert plan["resize_type"] == "scale longer dimension"
        assert max(plan["resized_wh"]) == m.REF_LONGER_SIDE
        assert plan["aspect_preserved"] is True, (w, h, plan["aspect_in"], plan["aspect_out"])
        assert plan["crop_applied"] is False and plan["crop"] is None
        assert plan["stretch_applied"] is False and plan["covers_whole_source"] is True
    graph = proposal_graph("BOOK")
    resizers = [n for n in graph.values() if n["class_type"] == "ResizeImageMaskNode"]
    assert resizers, "no resize node in the proposal"
    for n in resizers:
        assert n["inputs"]["resize_type"] == "scale longer dimension"
        assert n["inputs"]["resize_type.longer_size"] == m.REF_LONGER_SIDE
        assert not [k for k in n["inputs"] if "crop" in k.lower()]
    spec = proposal_spec()
    for r in spec["graphs"]["BOOK"]["refs"]:
        if r["resize_kind"] == "longer_side":
            assert r["resize_plan"]["aspect_preserved"] is True
            assert r["resize_plan"]["crop_applied"] is False
    _record("test_r27_no_stretch_no_crop_aspect_preserved", {
        "plans": {k: {"resized_wh": v["resized_wh"], "aspect_in": v["aspect_in"],
                      "aspect_out": v["aspect_out"], "crop_applied": v["crop_applied"],
                      "stretch_applied": v["stretch_applied"],
                      "aspect_preserved": v["aspect_preserved"]}
                  for k, v in plans.items()},
        "resize_nodes_checked": len(resizers),
        "graph_resize_type": "scale longer dimension",
        "primary_resize_node": spec["graphs"]["BOOK"]["refs"][0]["resize_plan"]["resize_node"],
        "primary_resize_is_identity": spec["graphs"]["BOOK"]["refs"][0]["resize_plan"][
            "identity_for_this_input"]})
    assert len(plans) == 5


def test_r27_reference_metadata_mismatch_refused():
    """A declared role/pose the file's own pixels contradict is refused with a type."""
    m = anchor()
    measured = m.measure_reference(Path(INPUT_ROOT) / REF_DIR / "cast_dan_choi_standing.png")
    assert abs(measured["opaque_bbox_height_over_width"] - DAN_CHOI_H_OVER_W) < 1e-5
    assert measured["opaque_bbox_wh"] == [598, 816]
    true_claim = m.check_reference_pose("cast_dan_choi_seated_cross_legged",
                                        "seated_cross_legged", measured)
    assert true_claim is None, "the measured wide low silhouette IS seated cross-legged"
    refusal = m.check_reference_pose("cast_dan_choi_standing", "standing_upright", measured)
    assert refusal is not None, "a standing claim over a wide low silhouette must refuse"
    assert refusal.code == "REFERENCE_POSE_METADATA_MISMATCH"
    assert refusal.code in m.TYPED_REFUSAL_CODES
    rec = refusal.to_dict()
    assert rec["refused"] is True
    assert rec["detail"]["measured_height_over_width"] == measured["opaque_bbox_height_over_width"]
    row = ref_row("BOOK", "dan_choi")
    assert "standing" not in row["role"], row["role"]
    assert row["pose_declared"] == "seated_cross_legged"
    assert "standing" in row["filename_claim_vs_measured"], \
        "the file's own (wrong) name claim is recorded, the file is NOT renamed"
    _record("test_r27_reference_metadata_mismatch_refused", {
        "measured_height_over_width": measured["opaque_bbox_height_over_width"],
        "measured_bbox_wh": measured["opaque_bbox_wh"],
        "measured_size": measured["size"],
        "true_pose": "seated_cross_legged", "true_pose_refused": False,
        "false_pose": "standing_upright", "false_pose_refused": True,
        "refusal_code": refusal.code, "refusal_detail": rec["detail"],
        "declared_role_in_proposal": row["role"],
        "file_renamed": False})
    assert row["pose_declared"] == "seated_cross_legged"


def test_r27_first_frame_event_mismatch_refused():
    """A prompt asserting an event state index 0 does not show is refused with a type."""
    m = anchor()
    facts = m.SOURCE_FIRST_FRAME_FACTS["BOOK"]
    assert facts["facts_status"] == "MEASURED"
    assert facts["book_state_first_frame"] == "cover_upright"
    assert facts["open_book_event_is_in_the_first_frame"] is False
    assert facts["open_book_event_first_index"] == 72
    assert facts["book_state_events"] == GOLDEN_PAGE_STATES
    old = ("Reference image 1 shows three people in one room. The pale/grey-haired figure "
           "seated on the left in the black chair, both hands on an open blue book, takes the "
           "character design of reference image 2. The open blue book, the table with the "
           "green tray, and the chairs are redrawn in the same flat style.")
    refusals = m.check_prompt_event_state("BOOK", old)
    codes = sorted({r.code for r in refusals})
    # the old prompt is wrong twice: it asserts a page-spread state index 0 does not show AND
    # it never declares the partial/edge person that the frame does show.
    assert codes == ["PROMPT_EVENT_STATE_NOT_IN_FIRST_FRAME", "PROMPT_PEOPLE_COUNT_MISMATCH"], codes
    assert len(refusals) >= 2, "both the page-spread claim and the both-hands claim must fire"
    assert [r.code for r in refusals].count("PROMPT_EVENT_STATE_NOT_IN_FIRST_FRAME") >= 2
    assert all(r.to_dict()["refused"] is True for r in refusals)
    shipped = book_instruction()
    assert m.check_prompt_event_state("BOOK", shipped) == [], "the shipped proposal must pass"
    for p in m.FORBIDDEN_PROMPT_CLAIMS["BOOK"]:
        assert not re.search(p["pattern"], shipped.lower()), p["pattern"]
    assert "two pages" not in shipped.lower() and "both hands" not in shipped.lower()
    _record("test_r27_first_frame_event_mismatch_refused", {
        "old_prompt_refused": True, "old_prompt_refusal_codes": codes,
        "old_prompt_refusal_count": len(refusals),
        "first_frame_state": facts["book_state_first_frame"],
        "open_book_event_first_index": facts["open_book_event_first_index"],
        "open_book_event_time_s": facts["open_book_event_time_s"],
        "book_state_events": facts["book_state_events"],
        "shipped_prompt_refusals": 0,
        "patterns_checked": [p["pattern"] for p in m.FORBIDDEN_PROMPT_CLAIMS["BOOK"]]})
    assert len(refusals) >= 2


def test_r27_full_and_partial_roles_declared():
    """The partial/edge person is declared, not dropped; roles cover every reference."""
    spec = proposal_spec()
    book = spec["graphs"]["BOOK"]
    people = book["first_frame_people"]
    assert people["fully_visible"] == 3
    assert people["partial_at_edge"] == 1
    measured = people["partial_edge_person_measured"]
    assert "628,254,639,306" in measured and "touches x=639" in measured
    shipped = book_instruction().lower()
    assert "partial" in shipped and "right edge" in shipped
    roles = [r["role"] for r in book["refs"]]
    assert len(roles) == 4 and len(set(roles)) == 4, roles
    missing = [r["role"] for r in book["refs"] if r["authored_artwork"] == "MISSING"]
    assert len(missing) == 2, f"authored artwork must be declared MISSING: {missing}"
    assert all(r["measured_pixels"]["unique_rgb_colors"] <= 2
               for r in book["refs"] if r["authored_artwork"] == "MISSING")
    _record("test_r27_full_and_partial_roles_declared", {
        "people_fully_visible": people["fully_visible"],
        "people_partial_at_edge": people["partial_at_edge"],
        "partial_edge_person_measured": measured,
        "roles": roles,
        "authored_artwork_missing_roles": missing,
        "placeder_roles_unique_colors": [
            r["measured_pixels"]["unique_rgb_colors"] for r in book["refs"]
            if r["authored_artwork"] == "MISSING"],
        "prompt_declares_partial": True, "new_images_generated": False})
    assert len(missing) == 2


# --------------------------------------------------------------- R27-06 right EPOCH
def test_r27_epoch_missing_instance_id_refused():
    """A record that declares no instance id cannot confirm this instance's shutdown."""
    r = retained()
    harden = clf()
    port = int(harden.PORT)
    work = _workdir()
    try:
        base = r.full_ev(port)
        ev = dict(base)
        ev["instance_epoch"] = {"port": port, "pid": 4100}       # no instance_id
        assert "instance_id" not in ev["instance_epoch"]
        c = r.case(work, "missing_instance_id", dumps=True, ev=ev, port=port, receipts=True)
        rc, p = _run_classifier(c["dir"])
        ident = p["instance_identity_binding"]
        assert p["verdict"] != CONFIRMED, p["verdict"]
        assert p["verdict"].startswith("SHUTDOWN_UNPROVEN")
        assert ident["bound"] is False
        assert "instance_epoch_has_no_instance_id" in ident["problems"]
        assert ident["mismatch"] is False, "absence is missing authority, not a contradiction"
        assert "instance_identity_binding" in (p["unproven_reason"] or "")
        assert rc == 1
        _record("test_r27_epoch_missing_instance_id_refused", {
            "verdict": p["verdict"], "returncode": rc,
            "instance_identity_bound": ident["bound"], "mismatch": ident["mismatch"],
            "problems": ident["problems"], "unproven_reason": p["unproven_reason"],
            "authority_source": ident["authority_source"]})
        assert ident["bound"] is False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_r27_epoch_foreign_instance_same_port_refused():
    """A FOREIGN instance id on the SAME port cannot confirm this instance's shutdown."""
    r = retained()
    harden = clf()
    port = int(harden.PORT)
    work = _workdir()
    try:
        base = r.full_ev(port)
        ev = dict(base)
        ev["instance_epoch"] = {"port": port, "pid": 4100, "instance_id": FOREIGN_INSTANCE}
        c = r.case(work, "foreign_instance_same_port", dumps=True, ev=ev, port=port,
                   receipts=True)
        snap = Path(c["dir"]) / "instance_epoch.json"
        snap.write_text(json.dumps(_frozen_snapshot(port), indent=1), encoding="utf-8")
        rc, p = _run_classifier(c["dir"])
        ident = p["instance_identity_binding"]
        assert p["verdict"] != CONFIRMED, p["verdict"]
        assert p["verdict"] == "SHUTDOWN_UNPROVEN_CONTRADICTION", p["verdict"]
        assert ident["bound"] is False and ident["mismatch"] is True
        assert ident["authority_source"] == "evidence_frozen_snapshot"
        assert ident["authority_instance_id"] == FROZEN_SNAPSHOT_INSTANCE
        assert ident["declared_instance_id"] == FOREIGN_INSTANCE
        assert ident["instance_id_matches_the_authority"] is False
        assert any("another_instance_id" in c for c in p["contradictions"]["contradictions"])
        _record("test_r27_epoch_foreign_instance_same_port_refused", {
            "verdict": p["verdict"], "returncode": rc,
            "authority_source": ident["authority_source"],
            "authority_instance_id": ident["authority_instance_id"],
            "declared_instance_id": ident["declared_instance_id"],
            "identity_matches": ident["instance_id_matches_the_authority"],
            "mismatch": ident["mismatch"], "port": port,
            "same_port_different_instance": True,
            "contradictions": p["contradictions"]["contradictions"]})
        assert ident["mismatch"] is True
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_r27_epoch_valid_exact_confirmed():
    """An EXACT frozen epoch + matching process lifetime still confirms."""
    r = retained()
    harden = clf()
    port = int(harden.PORT)
    work = _workdir()
    try:
        snap = _frozen_snapshot(port)
        base = r.full_ev(port)
        ev = dict(base)
        ev["instance_epoch"] = dict(snap)
        c = r.case(work, "valid_exact_epoch", dumps=True, ev=ev, port=port, receipts=True)
        (Path(c["dir"]) / "instance_epoch.json").write_text(json.dumps(snap, indent=1),
                                                            encoding="utf-8")
        rc, p = _run_classifier(c["dir"])
        ident = p["instance_identity_binding"]
        assert p["verdict"] == CONFIRMED, (p["verdict"], p["unproven_reason"])
        assert rc == 0
        assert ident["bound"] is True and ident["mismatch"] is False
        assert ident["authority_source"] == "evidence_frozen_snapshot"
        assert ident["instance_id_matches_the_authority"] is True
        assert ident["declared_pid_is_an_engine_chain_pid"] is True
        assert all(p["verdict_basis"]["pillars"].values())
        assert p["verdict_basis"]["instance_identity_bound"] is True
        _record("test_r27_epoch_valid_exact_confirmed", {
            "verdict": p["verdict"], "returncode": rc,
            "instance_id": ident["declared_instance_id"],
            "authority_source": ident["authority_source"],
            "declared_pid": ident["declared_epoch_pid"],
            "declared_pid_is_an_engine_chain_pid": ident["declared_pid_is_an_engine_chain_pid"],
            "instance_identity_bound": ident["bound"],
            "all_pillars_held": bool(all(p["verdict_basis"]["pillars"].values())),
            "pillars": p["verdict_basis"]["pillars"]})
        assert p["verdict"] == CONFIRMED
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_r27_epoch_old_after_dump_contradictory_port_refused():
    """A STALE epoch after a restart is never attached to old evidence."""
    r = retained()
    harden = clf()
    port = int(harden.PORT)
    work = _workdir()
    try:
        snap = _frozen_snapshot(port)
        stale = dict(snap)
        stale.update({"instance_id": RESTARTED_INSTANCE, "port": port + 1, "pid": 5480,
                      "launched_at": 1790999999.5})
        base = r.full_ev(port)
        ev = dict(base)
        ev["instance_epoch"] = stale                 # the NEWEST epoch, attached to old dump
        ev["port"] = port + 1
        c = r.case(work, "stale_epoch_after_dump", dumps=True, ev=ev, port=port, receipts=True)
        (Path(c["dir"]) / "instance_epoch.json").write_text(json.dumps(snap, indent=1),
                                                            encoding="utf-8")
        rc, p = _run_classifier(c["dir"])
        ident = p["instance_identity_binding"]
        live = p["live_instance_epoch_read_once"]
        assert p["verdict"] != CONFIRMED, p["verdict"]
        assert p["verdict"] == "SHUTDOWN_UNPROVEN_CONTRADICTION", p["verdict"]
        assert ident["bound"] is False and ident["mismatch"] is True
        # the FROZEN snapshot is the authority; the freshly-read live epoch is NOT adopted
        assert ident["authority_source"] == "evidence_frozen_snapshot"
        assert ident["authority_instance_id"] == FROZEN_SNAPSHOT_INSTANCE
        assert ident["authority_port"] == port
        assert ident["declared_instance_id"] == RESTARTED_INSTANCE
        assert ident["authority_instance_id"] != ident["declared_instance_id"]
        assert ident["live_epoch_used_as_authority"] is False
        assert live["used_as_identity_authority"] is False and live["read_once"] is True
        assert live["epoch"] is None or \
            live["epoch"].get("instance_id") != ident["authority_instance_id"], \
            "the live epoch must not have been substituted for the frozen authority"
        assert p["verdict_basis"]["live_epoch_used_as_authority"] is False
        assert any("another_epoch_port" in c for c in p["contradictions"]["contradictions"])
        _record("test_r27_epoch_old_after_dump_contradictory_port_refused", {
            "verdict": p["verdict"], "returncode": rc,
            "authority_source": ident["authority_source"],
            "authority_instance_id": ident["authority_instance_id"],
            "authority_port": ident["authority_port"],
            "declared_instance_id": ident["declared_instance_id"],
            "declared_epoch_port": ident["declared_epoch_port"],
            "declared_epoch_pid": ident["declared_epoch_pid"],
            "mismatch": ident["mismatch"],
            "live_epoch_used_as_authority": False,
            "live_epoch_instance_id": (live.get("epoch") or {}).get("instance_id"),
            "live_epoch_path": live["path"],
            "contradictions": p["contradictions"]["contradictions"],
            "note": ("the live/newest epoch is reported but never adopted: attaching it to old "
                     "evidence is the R27-06 defect")})
        assert ident["mismatch"] is True
    finally:
        shutil.rmtree(work, ignore_errors=True)
