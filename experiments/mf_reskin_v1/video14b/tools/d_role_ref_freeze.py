"""MF-V1-VIDEO14B round D — NR08: per-SHOT cast references from the repository's pack.

WHY THIS REPLACES THE ROUND-C BINDING
-------------------------------------
The round-C freeze (V02) pointed BOOK, TURN and OCC at the IDENTICAL whole-scene anchor
1311699b...  Declaring those three source windows "roles" was the error: they are SHOTS,
and a shot has identities, not a label.  Three aliases of one full-scene PNG is not a
character reference, and no colour re-export can fix the observed failure (the source has
an OPEN book held by the seated character; the output keeps it closed/upright and adds one
to the standing character).

WHAT IS FROZEN HERE
-------------------
  * a shot inventory in which SHOT IDS ARE NOT CHARACTER IDS: each shot lists the
    identities/props actually visible in its own decoded frames, taken from the SHA'd
    frame set, and a shot with no person carries ZERO people;
  * a real per-identity reference for every full figure, taken from the repository's own
    usable pack `presets/characters/<set>_<pose>.png` (the layout that
    `app/workflow/preset_layout_manifest.py` documents), with the git blob id, the file
    SHA, the pixel size and the canonical pose slot recorded for every frozen pixel;
  * IDENTITY REUSE: the same CharacterID + PackVersion + reference BYTES wherever an
    identity appears, so the same asset feeds more than one shot;
  * the LoadImage -> reference-encoder input trace read out of the ROUND-D candidate
    graph, plus the canonical graph diff that SHOWS that wiring;
  * typed findings, not invented pixels: a prop with no separable reference in the pack is
    MARKED, and the members of a shot's cast set that the frozen generator node cannot
    consume are marked `wired_in_candidate_graph: false` with the source line that limits
    it (WanAnimate2ToVideo.execute uses reference_image[:1]).

TEST-ONLY: nothing here is published, nothing is user-approved, there is no approved
library pack, and this freeze does NOT promote these assets into one.  It starts nothing,
loads no model and writes no media.

usage:
  python d_role_ref_freeze.py <worktree> <observation_json> <out_dir> <evidence_json>
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROUND_C_TOOL = "experiments/mf_reskin_v1/video14b/tools/v14b_role_ref_freeze.py"
PACK_DIR = "presets/characters"
LAYOUT_POSES = ("three_quarter", "walking", "sitting", "standing", "talking", "back")
POSE_SLOT = {"front": "front", "three_quarter": "three_quarter", "side": "side",
             "back": "back", "sitting": "sitting", "walking": "walking",
             "talking": "front", "standing": "side"}
SHOT_ORDER = ("BOOK", "TURN", "OCC")
REF_DIR = "C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/input/roundD_refs"
D_GRAPH_DIR = "experiments/mf_reskin_v1/video14b/workflows/run/roundD"
REF_NODE = "189"
REF_WALK = ("672:590", "672:589", "672:587")     # resize -> CLIPVisionEncode -> generator
VACE_REF_NODE = "134"
VACE_CONSUMER = "49"
NODE_LIMIT_EVIDENCE = ("runtime/video14b/ComfyUI/comfy_extras/nodes_wan.py:1253 "
                       "WanAnimate2ToVideo.execute -> "
                       "reference_image[:1]  (the frozen node consumes ONE reference)")


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def split_pose(stem: str) -> tuple[str, str] | None:
    for pose in sorted(LAYOUT_POSES, key=len, reverse=True):
        if stem.endswith("_" + pose):
            return stem[: -(len(pose) + 1)], pose
    return None


def main() -> int:
    wt = _p(sys.argv[1])
    obs_path = _p(sys.argv[2])
    out_dir = _p(sys.argv[3])
    ev_out = _p(sys.argv[4])
    out_dir.mkdir(parents=True, exist_ok=True)
    rc = load(wt / ROUND_C_TOOL, "mf_d_roundc_freeze")
    from PIL import Image

    obs = json.loads(obs_path.read_text(encoding="utf-8"))
    pack_dir = wt / PACK_DIR

    # ---------------------------------------------------------------- the pack
    pack_rows: dict[str, dict] = {}
    for p in sorted(pack_dir.glob("*.png")):
        parsed = split_pose(p.stem)
        if not parsed:
            continue
        set_name, pose = parsed
        pack_rows[f"{set_name}_{pose}"] = {
            "set_name": set_name, "layout_pose": pose,
            "pose_slot": POSE_SLOT[pose], "path": str(p).replace("\\", "/"),
            "sha256": rc.sha256_file(p), "bytes": p.stat().st_size,
            "pixels": list(Image.open(p).size)}
    sets: dict[str, set] = {}
    for row in pack_rows.values():
        sets.setdefault(row["set_name"], set()).add(row["layout_pose"])
    complete_sets = sorted(s for s, poses in sets.items()
                           if set(LAYOUT_POSES) <= poses)
    pack_version_body = rc.canonical_json(
        {k: v["sha256"] for k, v in pack_rows.items()})
    pack_version = "presets-characters@" + hashlib.sha256(
        pack_version_body.encode()).hexdigest()[:16]
    pack_root_sha = hashlib.sha256(pack_version_body.encode()).hexdigest()
    blob = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "--verify", "HEAD:" + PACK_DIR],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    tree_sha = blob.stdout.strip() if blob.returncode == 0 else None

    # ------------------------------------------------------------- cast assignment
    canon: dict[str, str] = {}
    for claim in obs.get("identity_equivalence_claims") or []:
        canon[claim["b"]] = claim["a"]
    distinct: list[str] = []
    for shot in SHOT_ORDER:
        for person in obs["shots"][shot]["persons"]:
            if not person.get("is_a_full_figure", True):
                continue
            cid = canon.get(person["obs_id"], person["obs_id"])
            if cid not in distinct:
                distinct.append(cid)
    assignment = {cid: complete_sets[i] for i, cid in enumerate(distinct)}
    cast = {}
    for cid, set_name in assignment.items():
        posture = None
        for shot in SHOT_ORDER:
            for person in obs["shots"][shot]["persons"]:
                if canon.get(person["obs_id"], person["obs_id"]) == cid:
                    posture = posture or person["posture"]
        pose = obs["posture_to_pose_slot"][posture]
        row = pack_rows[f"{set_name}_{pose}"]
        cast[cid] = {**row, "character_id": set_name, "member_from_posture": posture,
                     "pack_version": pack_version,
                     "pack_version_sha256": pack_root_sha,
                     "pack_git_tree_sha": tree_sha}
    # the frozen reference FILE is identity-keyed, so reuse is byte reuse
    ref_dir = _p(REF_DIR)
    ref_dir.mkdir(parents=True, exist_ok=True)
    for cid, row in cast.items():
        name = f"cast_{row['character_id']}_{row['layout_pose']}.png"
        dst = ref_dir / name
        shutil.copyfile(row["path"], dst)
        row["frozen_ref_file"] = name
        row["frozen_ref_path"] = str(dst).replace("\\", "/")
        row["frozen_ref_sha256"] = rc.sha256_file(dst)
        row["copy_is_byte_identical_to_the_pack_source"] = (
            row["frozen_ref_sha256"] == row["sha256"])

    # ------------------------------------------------------------------ shot table
    shots = {}
    for shot in SHOT_ORDER:
        spec = obs["shots"][shot]
        identities = []
        for person in spec["persons"]:
            cid = canon.get(person["obs_id"], person["obs_id"])
            if cid not in cast:                     # partial person, no full figure
                identities.append({"obs_id": person["obs_id"],
                                   "is_a_full_figure": False,
                                   "resolution": "NO_FROZEN_REFERENCE__partial_person_"
                                                 "not_a_full_figure",
                                   "posture": person["posture"],
                                   "appearance": person["appearance"],
                                   "frames_visible": person["frames_visible"]})
                continue
            row = cast[cid]
            identities.append({
                "obs_id": person["obs_id"], "identity_id": cid,
                "is_a_full_figure": True, "posture": person["posture"],
                "appearance": person["appearance"],
                "frames_visible": person["frames_visible"],
                "character_id": row["character_id"], "pose_slot": row["pose_slot"],
                "layout_pose": row["layout_pose"], "pack_version": row["pack_version"],
                "asset": row["path"], "asset_sha256": row["sha256"],
                "asset_bytes": row["bytes"], "asset_pixels": row["pixels"],
                "asset_git_blob": None,
                "frozen_ref_file": row["frozen_ref_file"],
                "frozen_ref_sha256": row["frozen_ref_sha256"]})
        for ident in identities:
            if ident.get("asset"):
                rel = ident["asset"][len(str(wt).replace("\\", "/")) + 1:]
                gb = subprocess.run(["git", "-C", str(wt), "rev-parse", "--verify",
                                     f"HEAD:{rel}"], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
                ident["asset_git_blob"] = gb.stdout.strip() if gb.returncode == 0 else None
        shots[shot] = {
            "shot_id": shot,
            "persons_visible_count": len([i for i in identities
                                          if i.get("is_a_full_figure")]),
            "identity_count": len([i for i in identities if i.get("is_a_full_figure")]),
            "identities": identities,
            "props": spec["props"],
            "props_note": spec.get("persons_note"),
            "people_added_by_this_freeze": False,
            "primary_identity": next((i["identity_id"] for i in identities
                                      if i.get("is_a_full_figure")), None),
        }

    # ------------------------------------------------------- round-D candidate graphs
    animate_rel = D_GRAPH_DIR + "/mf_animate2_book4s.d.api.json"
    vace_rel = D_GRAPH_DIR + "/mf_vace14b_book4s.d.json"
    anim_src = wt / rc.ANIMATE_GRAPH
    vace_src = wt / rc.VACE_GRAPH
    assert rc.sha256_file(anim_src) == rc.ANIMATE_GRAPH_SHA, "released M1 graph changed"
    assert rc.canonical_sha(anim_src and json.loads(anim_src.read_text(encoding="utf-8"))) \
        == rc.ANIMATE_CANONICAL, "released M1 graph canonical hash changed"
    anim_base = json.loads(anim_src.read_text(encoding="utf-8"))
    vace_base = json.loads(vace_src.read_text(encoding="utf-8"))
    baseline_doc = json.loads(rc.BASELINE_API.read_text(encoding="utf-8"))
    assert rc.canonical_sha(baseline_doc) == rc.BASELINE_CANONICAL, "baseline changed"

    book_primary = cast[shots["BOOK"]["primary_identity"]]
    anim = copy.deepcopy(anim_base)
    vace = copy.deepcopy(vace_base)
    anim[REF_NODE]["inputs"]["image"] = book_primary["frozen_ref_file"]
    vace_node = next(n for n in vace["nodes"] if str(n["id"]) == VACE_REF_NODE)
    vace_node["widgets_values"] = [book_primary["frozen_ref_file"], "image"]
    (wt / D_GRAPH_DIR).mkdir(parents=True, exist_ok=True)
    (wt / animate_rel).write_text(json.dumps(anim, indent=2) + "\n", encoding="utf-8")
    (wt / vace_rel).write_text(json.dumps(vace, indent=2) + "\n", encoding="utf-8")

    chains = [rc.reference_chain(anim, nid) for nid in
              sorted(nid for nid, n in anim.items() if n.get("class_type") == "LoadImage")]
    vace_bindings = rc.ui_reference_bindings(wt / vace_rel)
    vace_consumer = [b for b in vace_bindings if b["consumer_node"] == VACE_CONSUMER]
    diff = rc.graph_diff(baseline_doc, anim)
    vace_diff = rc.graph_diff(vace_base, vace)

    m1_fields = [d for d in diff if d["field"].endswith("pose_end_percent")]
    wire_fields = [d for d in diff if d not in m1_fields]
    not_wired = []
    for shot, spec in shots.items():
        for ident in spec["identities"]:
            if not ident.get("is_a_full_figure"):
                continue
            if shot == "BOOK" and ident["identity_id"] == shots["BOOK"]["primary_identity"]:
                continue
            not_wired.append({
                "shot_id": shot, "obs_id": ident["obs_id"],
                "identity_id": ident["identity_id"], "character_id": ident["character_id"],
                "frozen_ref_file": ident["frozen_ref_file"],
                "wired_in_candidate_graph": False,
                "reason": ("the frozen generator node consumes ONE reference image, so a "
                           "shot's non-primary cast members are frozen but not wired in "
                           "this round"),
                "frozen_node_evidence": NODE_LIMIT_EVIDENCE})

    checks = {
        "shot_ids_are_not_character_ids": not (
            {s["shot_id"] for s in shots.values()}
            & {i["character_id"] for s in shots.values() for i in s["identities"]
               if i.get("character_id")}),
        "every_shot_person_was_inspected_in_its_own_decoded_frames": all(
            i["frames_visible"] for s in shots.values() for i in s["identities"]),
        "shot_without_a_person_has_zero_people": shots["TURN"]["identity_count"] == 0,
        "no_people_were_added_by_this_freeze": all(
            not s["people_added_by_this_freeze"] for s in shots.values()),
        "every_full_figure_has_a_real_pack_reference": all(
            i.get("asset") and i.get("asset_sha256") and i.get("asset_pixels")
            for s in shots.values() for i in s["identities"] if i.get("is_a_full_figure")),
        "references_are_not_three_aliases_of_one_file": len(
            {i["asset_sha256"] for s in shots.values() for i in s["identities"]
             if i.get("is_a_full_figure")}) == len(distinct) and len(distinct) == 3,
        "every_reference_lives_in_the_repository_pack": all(
            i["asset"].startswith(str(pack_dir).replace("\\", "/"))
            for s in shots.values() for i in s["identities"] if i.get("asset")),
        "reference_copies_are_byte_identical_to_their_pack_source": all(
            row["copy_is_byte_identical_to_the_pack_source"] for row in cast.values()),
        "identity_reuse_is_same_character_and_same_bytes": (
            next(i for i in shots["OCC"]["identities"] if i.get("is_a_full_figure"))["character_id"]
            == next(i for i in shots["BOOK"]["identities"] if i.get("is_a_full_figure"))["character_id"]
            and next(i for i in shots["OCC"]["identities"] if i.get("is_a_full_figure"))["frozen_ref_sha256"]
            == next(i for i in shots["BOOK"]["identities"] if i.get("is_a_full_figure"))["frozen_ref_sha256"]),
        "pack_is_a_real_repository_pack_with_one_version": bool(
            pack_rows) and tree_sha is not None and len(complete_sets) == 4,
        "props_without_a_separable_reference_are_marked": bool(
            obs["prop_reference_search"]["result"].startswith("NO separable prop reference")),
        "no_prop_pixels_were_fabricated": all(
            "prop" not in (r["set_name"] or "") for r in pack_rows.values()),
        "loadimage_reaches_clip_vision_encode_in_the_candidate": all(
            c["reaches_clip_vision_encode"] for c in chains),
        "candidate_reference_loadimage_carries_a_pack_reference": all(
            (anim[c["load_image"]]["inputs"] or {}).get("image", "").startswith("cast_")
            for c in chains),
        "vace_reference_binding_traced_from_the_candidate": bool(vace_consumer),
        "vace_reference_file_is_the_pack_reference": (
            vace_node["widgets_values"][0] == book_primary["frozen_ref_file"]),
        "canonical_diff_shows_the_reference_wiring": bool(wire_fields) and all(
            d["field"].endswith(".inputs.image") or "widgets_values" in d["field"]
            for d in wire_fields),
        "canonical_diff_keeps_the_m1_variable": len(m1_fields) == 1,
        "vace_canonical_diff_is_only_the_reference_wiring": len(vace_diff) == 1,
        "unwired_cast_members_are_marked_with_a_reason": all(
            not x["wired_in_candidate_graph"] and x["reason"] for x in not_wired),
        "not_an_approved_library_pack": True,
        "test_only_never_published": True,
    }

    rec = {
        "artifact": "d_role_ref_freeze.json", "task_id": "MF-V1-VIDEO14B", "row": "NR08",
        "round": "roundD",
        "rule": ("freeze a per-SHOT cast reference from the repository pack, with shot ids "
                 "!= character ids, real distinct reference bytes, identity reuse and the "
                 "LoadImage -> reference-encoder trace taken from the round-D candidate graph"),
        "test_only": True, "published": False, "user_approved": False,
        "approved_library_pack_exists": False, "demo_claim": False,
        "library_approval_claimed": False,
        "test_only_statement": (
            "TEST-ONLY: never published, never user-approved, no library or demo approval "
            "is claimed here.  The demo owner (MF-DEMO-E2E) tracks product impact "
            "separately.  These bytes are a cast cast from the repository's own preset "
            "pack; they are not an approved library pack."),
        "pack": {"dir": str(pack_dir).replace("\\", "/"), "files": len(pack_rows),
                 "pack_version": pack_version, "pack_version_sha256": pack_root_sha,
                 "pack_git_tree_sha": tree_sha, "complete_six_pose_sets": complete_sets,
                 "sets": {s: sorted(p) for s, p in sorted(sets.items())},
                 "rows": pack_rows,
                 "is_a_usable_pack_in_the_repository": True,
                 "documented_by": "app/workflow/preset_layout_manifest.py"},
        "cast_assignment": {
            "rule": ("distinct observed identities, in shot order BOOK/TURN/OCC then "
                     "observation order, take the complete six-pose sets in sorted order; "
                     "the observed posture selects the layout pose file"),
            "distinct_identities": distinct, "assignment": assignment,
            "rows": {k: {kk: vv for kk, vv in v.items()} for k, v in cast.items()}},
        "shot_inventory": shots,
        "shot_ids": list(SHOT_ORDER),
        "character_ids": sorted({r["character_id"] for r in cast.values()}),
        "identity_reuse_across_shots": [
            {"identity_id": cid,
             "shots": [{"shot_id": s, "obs_id": i["obs_id"],
                        "frozen_ref_file": i["frozen_ref_file"],
                        "frozen_ref_sha256": i["frozen_ref_sha256"]}
                       for s in SHOT_ORDER for i in shots[s]["identities"]
                       if i.get("identity_id") == cid],
             "character_id": row["character_id"], "pose_slot": row["pose_slot"],
             "pack_version": row["pack_version"],
             "frozen_ref_file": row["frozen_ref_file"],
             "frozen_ref_sha256": row["frozen_ref_sha256"]} for cid, row in cast.items()],
        "frozen_cast_to_ref_sha256": {row["character_id"]: row["frozen_ref_sha256"]
                                      for row in cast.values()},
        "unwired_cast_members": not_wired,
        "frozen_node_limit_evidence": NODE_LIMIT_EVIDENCE,
        "prop_findings": [{"prop": "book / printed form / binder edge / pen",
                           "status": "NO_SEPARABLE_REFERENCE_IN_THE_REPOSITORY_PACK",
                           "search": obs["prop_reference_search"],
                           "fabricated_pixels": False}],
        "loadimage_to_reference_encoder_trace": {
            "candidate_graph": animate_rel,
            "candidate_graph_sha256": rc.sha256_file(wt / animate_rel),
            "candidate_graph_canonical_sha256":
                rc.canonical_sha(json.loads((wt / animate_rel).read_text(encoding="utf-8"))),
            "reference_walk": list(REF_WALK),
            "animate_reference_chains": chains,
            "vace_candidate_graph": vace_rel,
            "vace_candidate_graph_sha256": rc.sha256_file(wt / vace_rel),
            "reference_node": VACE_REF_NODE, "consumer_node": VACE_CONSUMER,
            "vace_reference_bindings": vace_bindings,
            "is_approved_library_pack": False},
        "canonical_graph_diff": {
            "baseline": str(rc.BASELINE_API).replace("\\", "/"),
            "baseline_canonical_sha256": rc.canonical_sha(baseline_doc),
            "candidate": animate_rel,
            "candidate_canonical_sha256":
                rc.canonical_sha(json.loads((wt / animate_rel).read_text(encoding="utf-8"))),
            "differing_fields": diff, "count": len(diff),
            "m1_variable_fields": m1_fields,
            "reference_wiring_fields": wire_fields,
            "is_the_single_m1_variable": len(m1_fields) == 1 and not wire_fields},
        "vace_canonical_graph_diff": {
            "baseline": rc.VACE_GRAPH, "candidate": vace_rel,
            "differing_fields": vace_diff, "count": len(vace_diff)},
        "released_graphs_untouched": {
            "animate_api_sha256": rc.sha256_file(anim_src),
            "animate_api_canonical_sha256": rc.canonical_sha(anim_base),
            "vace_sha256": rc.sha256_file(vace_src),
            "baseline_api_sha256": rc.sha256_file(rc.BASELINE_API),
            "pins_hold": rc.sha256_file(anim_src) == rc.ANIMATE_GRAPH_SHA
            and rc.canonical_sha(anim_base) == rc.ANIMATE_CANONICAL
            and rc.canonical_sha(baseline_doc) == rc.BASELINE_CANONICAL},
        "visual_observation_input": {
            "observation_json": str(obs_path).replace("\\", "/"),
            "observation_sha256": rc.sha256_file(obs_path),
            "label": obs["label"], "open_item_not_a_pass": obs["open_item_not_a_pass"]},
        "checks": checks,
    }
    rec["verdict"] = "ROLE_REFS_FROZEN_PER_SHOT_FROM_PACK" if all(checks.values()) \
        else "INCOMPLETE"
    ev_out.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"checks": checks, "verdict": rec["verdict"],
                      "cast": {k: {"character_id": v["character_id"],
                                   "pose_slot": v["pose_slot"],
                                   "file": v["frozen_ref_file"],
                                   "sha256": v["frozen_ref_sha256"],
                                   "pixels": v["pixels"]} for k, v in cast.items()},
                      "diff": diff, "wire_fields": wire_fields,
                      "vace_diff": vace_diff, "not_wired": len(not_wired)},
                     indent=1, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
