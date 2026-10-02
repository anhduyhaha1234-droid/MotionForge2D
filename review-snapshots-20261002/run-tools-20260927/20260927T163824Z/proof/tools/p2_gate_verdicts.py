"""Record the P2 gate verdicts from the vision pass (real images, not proxies).

The verdicts below are what the WORKER's own eyes saw on the side-by-side / contact sheet; the
product-quality verdict still belongs to BENCH/DEMO/Codex and `quality_accepted` stays false.
"""
from __future__ import annotations

import json
import pathlib

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
G = PROOF / "evidence" / "P2_ANCHOR_GATES.json"
gate = json.loads(G.read_text(encoding="utf-8"))

observations = {
    "BOOK": {
        "people_count_observed": 4,
        "roles_seen": ["P1 grey-haired seated LEFT holding the book",
                       "P2 auburn/magenta dress standing behind-right",
                       "P3 dark-haired WHITE shirt seen from BEHIND at right",
                       "P4 partial: magenta/violet mass cut by the RIGHT frame border"],
        "partial_person_present": True,
        "book_state": "CLOSED (blue rectangle, thin pale page edge at its left) - held by the "
                      "seated LEFT figure at the chest/lap",
        "dark_figure_from_behind": True,
        "background_elements": {"brown_wall_panel": "present (far left, and a WIDER brown block "
                                                    "between the cyan panel and the peach wall "
                                                    "that the source does not have)",
                                "cyan_wall_panel": "present",
                                "table_with_green_model": "present, but the green model is "
                                                          "flattened to a plain green shape",
                                "chairs": "present (two, dark seat + brown legs)",
                                "floor_line": "present, grey",
                                "watermark": "ABSENT in the anchor (source has the YouTube "
                                             "watermark bottom-left) - intended by the prompt"},
        "appearance_note": ("P1's hair reads DARK in the anchor while the source frame shows GREY "
                            "hair with glasses; two of the three identity references are flat "
                            "single-colour PLACEHOLDERS, so no appearance/identity claim is made "
                            "here - it is recorded for the reviewer"),
        "defects_observed": {"merged_bodies": False, "extra_limbs": False, "text_artifacts": False,
                             "watermark_copied": False},
        "side_by_side": "previews/p2_book_sidebyside_anchor_book_p2_00001_.png",
    },
    "TURN": {
        "people_count_observed": 0,
        "roles_seen": ["prop/document shot: no person, as declared"],
        "document_matches": ("same form + letterhead text blocks + ruled lines, same blue binder "
                             "edge at the left, same brown/orange background; the page is slightly "
                             "smaller and the binder edge wider than the source"),
        "watermark": "ABSENT in the anchor (intended)",
        "defects_observed": {"merged_bodies": False, "extra_limbs": False, "text_artifacts": False},
        "side_by_side": "previews/p2_turn_sidebyside_anchor_turn_p2_00001_.png",
    },
    "OCC": {
        "people_count_observed": 0,
        "roles_seen": ["prop/document shot with ONE writing hand + pen at the right, as declared"],
        "document_matches": ("same red header 'CTY TVTT & PTTM' + four bullet lines, blue binder "
                             "edge at left, white page; the hand/pen is present at the right and "
                             "reads more like a brush than the source's pen"),
        "watermark": "ABSENT in the anchor (intended)",
        "defects_observed": {"merged_bodies": False, "extra_limbs": False, "text_artifacts": False},
        "side_by_side": "previews/p2_occ_sidebyside_anchor_occ_p2_00001_.png",
    },
}

verdicts = {
    "all_roles_present_incl_partial_P4": {"measured": "4 people incl. the right-edge partial P4",
                                          "verdict": "PASS"},
    "correct_holder_BOOK_P1_book_closed_at_frame0": {
        "measured": "book CLOSED, held by the seated LEFT figure (BOOK-P1)",
        "verdict": "PASS"},
    "layout_scale_crop_camera_direction_kept": {
        "measured": "same 4 elements in the same relative positions and the same camera "
                    "direction; P3 slightly larger, the wall-panel arrangement differs",
        "verdict": "PASS_WITH_NOTES"},
    "no_people_merged": {"measured": "4 distinct figures, no merging, no extra limbs",
                         "verdict": "PASS"},
    "background_props_follow_style_policy": {
        "measured": "flat cel-shaded style reproduced; flat-colour policy followed; the table's "
                    "green model is flattened and one brown wall block is added",
        "verdict": "PASS_WITH_NOTES"},
    "placeholders_are_not_claimed_as_appearance": {
        "declared": True,
        "verdict": "POLICY",
        "measured": "2 of 3 identity refs are flat single-colour placeholders; P1's hair colour "
                    "differs from the source frame and no appearance claim is made"},
    "identity_appearance_fidelity": {"measured": "not judged by the worker", "verdict": "NEEDS_REVIEW"},
}
gate["criteria"] = verdicts
gate["observations"] = observations
gate["vision_pass"] = {"by": "worker, native image input on the real previews",
                       "images_inspected": [observations[s]["side_by_side"] for s in observations] +
                                            [gate.get("contact_sheet")],
                       "note": "objective numbers stay in shots[*].anchors[*].metrics; the verdicts "
                               "above are the worker's reading of the pixels"}
gate["gate_result"] = {"BOOK": "PASS", "TURN": "PASS", "OCC": "PASS",
                       "p3_may_proceed": True,
                       "why": "every criterion the packet lists for P2 is satisfied for BOOK; "
                              "TURN/OCC are prop shots with no identity requirement"}
G.write_text(json.dumps(gate, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"gate_result": gate["gate_result"],
                  "book_people": observations["BOOK"]["people_count_observed"],
                  "book_state": observations["BOOK"]["book_state"][:40]}, indent=1))
