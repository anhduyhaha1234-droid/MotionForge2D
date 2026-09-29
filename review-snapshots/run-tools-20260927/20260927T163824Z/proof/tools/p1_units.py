"""P1 — scene-unit manifests for BOOK / TURN / OCC (RUN/proof only).

Every value comes from a measured artifact named next to it; nothing is inferred from a prompt or
a summary:
  * BOOK window / event table / roles / occlusions -> SOURCE_EVENT_AND_REFERENCE_MAP.md (R27),
    re-checked against the clip's own bytes and the roundI1 spec
  * reference roles + hashes -> graph_proposals/roundI1_spec.json (R27 evidence, read-only)
  * TURN/OCC source frames -> runtime/video14b/input/roundI1_src/** (read-only)
  * input copies -> PROOF/inputs/** (source files are never modified or moved)

`execution_profile` is a PLACEHOLDER in this pass: the profile numbers that ARE known from the
research restatement in the packet are recorded with `source: "packet-restated constraint"` and
`measured_here: false`, so nobody can mistake them for measurements taken in this pass.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
R27 = pathlib.Path(r"C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                   r"mf-cpu-input-correction-20260927/20260927T051440Z/VIDEO14B")
INPUT = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/input")
BENCH = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/bench/src_windows")
WT = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/wt-video14b")
BOOK_SRC = BENCH / "BOOK_src.mp4"
BOOK_SHA = "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc"


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def copy_in(p: pathlib.Path) -> dict:
    dst = PROOF / "inputs" / p.name
    shutil.copy2(p, dst)
    return {"src": str(p).replace("\\", "/"), "copy": f"inputs/{p.name}",
            "bytes": dst.stat().st_size, "sha256": sha(dst),
            "copy_is_byte_identical": sha(dst) == sha(p)}


def main() -> int:
    (PROOF / "inputs").mkdir(parents=True, exist_ok=True)
    spec = json.loads((R27 / "graph_proposals" / "roundI1_spec.json").read_text(encoding="utf-8"))
    book = spec["graphs"]["BOOK"]
    events = book["first_frame_event_visibility"]
    people = book["first_frame_people"]

    # any roundI1 extraction manifest that records the TURN/OCC windows (read-only)
    manif = {}
    for pat in ("workflows/run/roundI1/*.json", "runtime/video14b/state/roundI1/*.json",
                "runtime/video14b/state/roundI1/**/*.json"):
        for p in sorted(WT.parent.parent.glob(pat)) if "workflows" in pat else \
                sorted(pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mfv1").glob(pat)):
            if p.is_file():
                try:
                    manif[str(p).replace("\\", "/")] = json.loads(p.read_text(encoding="utf-8"))
                except Exception as e:  # noqa: BLE001
                    manif[str(p).replace("\\", "/")] = {"read_error": repr(e)}

    # ---- inputs: copy the pinned source clip + every source frame + the derived references
    inputs = {"source_clip": copy_in(BOOK_SRC),
              "source_clip_sha_matches_packet": sha(BOOK_SRC) == BOOK_SHA,
              "source_frames": {}, "derived_references": {}}
    for f in sorted((INPUT / "roundI1_src").glob("*.png")):
        inputs["source_frames"][f.name] = copy_in(f)
    for f in sorted((R27 / "derived_inference_input").glob("i1d_*.png")):
        inputs["derived_references"][f.name] = copy_in(f)

    book_refs = book["refs"]
    units = []

    def unit(uid, shot, span_frames, span_s, elements, interactions, assets, acceptance, profile):
        return {"unit_id": uid, "shot": shot,
                "source": {"span_frames": span_frames, "span_seconds": span_s,
                           "span_convention": "[start, end) on the decoded index space",
                           "fps_rational": span_s["fps_rational"],
                           "fps_source": span_s["fps_source"],
                           "geometry": span_s.get("geometry")},
                "elements": elements, "interactions": interactions, "assets": assets,
                "execution_profile": profile, "acceptance": acceptance,
                "quality_accepted": False}

    # BOOK: 120 frames @ 30/1 (measured on the pinned clip)
    el = []
    for role_row in book_refs:
        el.append({"role": role_row["role"], "kind": "reference_source_frame"
                   if role_row["role"] == "source_frame" else "character",
                   "bbox": role_row.get("measured_pixels", {}).get("opaque_bbox_wh"),
                   "visibility": role_row.get("why"),
                   "authored_artwork": role_row.get("authored_artwork"),
                   "asset": role_row.get("loadimage_value"),
                   "sha256": role_row.get("frozen_sha256"),
                   "derived_sha256": role_row.get("derived_sha256"),
                   "pose_declared": role_row.get("pose_declared")})
    el.append({"role": "BOOK-P4", "kind": "partial_person_at_frame_edge",
               "bbox": [628, 254, 639, 306], "visibility":
                   people.get("partial_edge_person_measured"),
               "authored_artwork": "NO_FROZEN_REFERENCE",
               "note": "declared, never completed and never removed"})
    units.append(unit(
        "BOOK-UNIT-001", "BOOK", [0, 120],
        {"fps_rational": "30/1", "fps_source": "SOURCE_EVENT_AND_REFERENCE_MAP.md §0 (ffmpeg "
                                               "geometry read on the pinned clip)",
         "geometry": "640x360 yuv420p", "duration_s": 4.0},
        el,
        [{"subject": "BOOK-P1", "object": "blue book (closed cover, upright)",
          "verb": "holds against the chest", "frames": [0, 72]},
         {"subject": "BOOK-P1", "object": "blue book (two pages, V spread)", "verb": "holds open",
          "frames": [72, 120]},
         {"subject": "BOOK-P1", "object": "yellow part", "verb": "holds beside the cover",
          "frames": [[0, 72], [105, 120]]},
         {"subject": "BOOK-P3", "object": "table", "verb": "sits behind it, back to camera",
          "frames": [0, 120]}],
        {"source_window": inputs["source_clip"], "references": inputs["derived_references"],
         "reference_roles": {r["role"]: r.get("loadimage_value") for r in book_refs}},
        {"hard_events": [{"event": "book_state_open_two_pages", "first_frame": 72,
                          "first_time_s": 2.4,
                          "must_not_be_shown_at": 0},
                         {"event": "partial_person_visible", "frames": [0, 120],
                          "must_not_be_completed": True}],
         "first_frame_state": events[0]["state"]},
        {"placeholder": True,
         "why": "execution profile is fixed with the graph in P2+; nothing was inferred here",
         "known_constraints": [
             {"name": "wan_continuation_frames", "value": 1,
              "source": "packet-restated constraint", "measured_here": False},
             {"name": "scail_continuation_frames", "value": 5,
              "source": "packet-restated constraint", "measured_here": False},
             {"name": "wan_reference_image", "value": "reference_image[:1] only",
              "source": "packet-restated constraint", "measured_here": False},
             {"name": "scail_palette_sorting", "value": "auto by position -> needs explicit "
                                                       "role->track->palette mapping and "
                                                       "sort_by=none once mapped",
              "source": "packet-restated constraint", "measured_here": False},
             {"name": "sam3_max_objects_default", "value": 4,
              "source": "packet-restated constraint", "measured_here": False}]}))

    # TURN / OCC: prop shots; their source frames are the two decoded indexes copied above
    for uid, shot, frames, roles in (
            ("TURN-UNIT-001", "TURN", [0, 80],
             ["source_frame", "source_frame_late"]),
            ("OCC-UNIT-001", "OCC", [0, 40],
             ["source_frame", "source_frame_late"])):
        rows = spec["graphs"][shot]["refs"]
        assets = {r["role"]: inputs["source_frames"].get(pathlib.Path(r["file"]).name)
                  for r in rows}
        units.append(unit(
            uid, shot, [frames[0], frames[1] + 1],
            {"fps_rational": "30/1",
             "fps_source": "same encoder window family as the pinned BOOK clip; the TURN/OCC "
                           "window spans are recorded from the decoded frame INDEXES present "
                           "in runtime/video14b/input/roundI1_src (f000/f080, f000/f040)",
             "geometry": "640x368 (native 640x360 + translation pad)",
             "frames_present": [frames[0], frames[1]]},
            [{"role": r["role"], "kind": "prop_detail_source_frame",
              "visibility": r.get("why"), "asset": r["file"],
              "sha256": r.get("frozen_sha256")} for r in rows],
            [{"subject": "none", "object": "prop (printed form / document)",
              "verb": "no person is visible in this shot",
              "frames": [frames[0], frames[1] + 1]}],
            {"source_frames": assets,
             "note": "both indexes were decoded natively and padded by TRANSLATION; no resample"},
            {"hard_events": [{"event": "no_person_in_frame", "frames": [frames[0], frames[1] + 1],
                              "must_not_add_person": True}]},
            {"placeholder": True,
             "why": "execution profile is fixed with the graph in P2+; nothing was inferred here",
             "known_constraints": []}))

    art = {"artifact": "P1_UNIT_MANIFESTS.json", "round": "R28-PROOF-P1",
           "task_id": "MF-V1-VIDEO14B", "cpu_only": True, "gpu_used": False,
           "engine_started": False, "model_loaded": False, "media_generated": False,
           "source_modified": False,
           "basis": {"event_map": str(R27 / "SOURCE_EVENT_AND_REFERENCE_MAP.md").replace(
                         "\\", "/"),
                     "event_map_sha256": sha(R27 / "SOURCE_EVENT_AND_REFERENCE_MAP.md"),
                     "roundI1_spec": str(R27 / "graph_proposals" / "roundI1_spec.json")
                     .replace("\\", "/"),
                     "roundI1_spec_sha256": sha(R27 / "graph_proposals" / "roundI1_spec.json"),
                     "roundI1_manifests_found": sorted(manif),
                     "research_doc": "COMFY_UNITS_RESEARCH.md NOT FOUND on this host (searched "
                                     "C:/Users/Admin and the run root); the constraints the packet "
                                     "restates are recorded with measured_here=false"},
           "units": units, "unit_count": len(units)}
    (PROOF / "evidence" / "P1_UNIT_MANIFESTS.json").write_text(
        json.dumps(art, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"units": [u["unit_id"] for u in units],
                      "book_elements": len(units[0]["elements"]),
                      "inputs_copied": len(inputs["source_frames"]) +
                      len(inputs["derived_references"]) + 1,
                      "source_clip_sha_ok": inputs["source_clip_sha_matches_packet"],
                      "manifests_found": sorted(manif),
                      "bytes": (PROOF / "evidence" / "P1_UNIT_MANIFESTS.json").stat().st_size},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
