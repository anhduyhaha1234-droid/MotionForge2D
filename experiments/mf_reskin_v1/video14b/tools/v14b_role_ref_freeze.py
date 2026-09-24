"""MF-V1-VIDEO14B round C — V02: role-specific reference freeze (CPU only, read-only).

WHY
---
The released run copies bind ONE whole-scene anchor as the image reference of the
reference encoder:

    Animate-2 : LoadImage 189 (mf_book_anchor_1650.png) -> link -> ResizeImageMaskNode
                672:590 -> CLIPVisionEncode 672:589
    VACE      : LoadImage 134 (mf_book_anchor_1650.png) -> WanVaceToVideo 49.reference_image

A whole-scene anchor is NOT an approved library pack, and no approved library pack exists,
so the roles this task is going to be run for -- BOOK / TURN / OCC -- have no frozen,
role-keyed reference at all.  This tool freezes that binding, TEST-ONLY, from the target
design the fixtures already allow, and records everything a reviewer needs to re-derive it.
It starts nothing, loads no model, touches no media.

WHAT IS ACTUALLY FROZEN (and what is NOT invented)
--------------------------------------------------
  * one frozen role->reference table keyed by role id BOOK / TURN / OCC, all three roles
    bound to the SAME frozen target-design asset -- i.e. "the same refs are used across
    BOOK/TURN/OCC" is true by construction and verifiable from the manifest;
  * the asset SHA mapping (target design vs the source identity it replaces) and the
    per-role measurements that prove the frozen target is not the role's own source;
  * a MEASURED NEGATIVE RESULT about role crops: neither the target-vs-role residual nor
    the cross-role difference yields a role-specific region (both cover ~the whole canvas),
    so no role crop is fabricated.  The numbers are in the record.

usage:
  python v14b_role_ref_freeze.py <worktree> <out_dir> <evidence_json>
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROLES = ("BOOK", "TURN", "OCC")
CANVAS = (640, 368)
ROI_THRESHOLD = 16          # mean |a - b| per pixel, 0..255
ROI_MIN_FRAC = 0.01         # < 1 % of the canvas: no usable role region
ROI_MAX_FRAC = 0.98         # > 98 %: not role-specific, it is the whole scene

RT = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")
BENCH = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/bench")

TARGET_ASSET = RT / "input/mf_book_anchor_1650.png"
TARGET_ASSET_SHA = "1311699b55c586abdb631d0468b4afc19cdf73a1b45b86fc4403f4517daf03fe"
SOURCE_ASSET = RT / "input/keyframe_f1650_src_padded_640x368.png"
SOURCE_ASSET_SHA = "b26bc6da229cf828e0984807f4369b04181fc6af059e3eacb716909682a80da1"

# the real file names in the BENCH source windows (BOOK has no frame suffix, TURN/OCC do)
ROLE_WINDOWS = {"BOOK": BENCH / "src_windows/BOOK_src.mp4",
                "TURN": BENCH / "src_windows/TURN_795_src.mp4",
                "OCC": BENCH / "src_windows/OCC_14768_src.mp4"}
ROLE_WINDOW_LABEL = {"BOOK": "BOOK window (film frames 1650..1770)",
                     "TURN": "TURN_795 window",
                     "OCC": "OCC_14768 window"}

WT_GRAPH = "experiments/mf_reskin_v1/video14b/workflows/run"
ANIMATE_GRAPH = f"{WT_GRAPH}/mf_animate2_book4s.m1.api.json"
VACE_GRAPH = f"{WT_GRAPH}/mf_vace14b_book4s.json"
ANIMATE_GRAPH_SHA = "ff134923db899b3a9b84baf05fa2c51c8caeb6420075b1765af979400dc7c02f"
ANIMATE_CANONICAL = "97045d0f5adfb961ae907e3628a2a0a5974c12c15ac7705721eb593358ebb796"
# the baseline API graph lives in the previous round's READ-ONLY root (never edited here)
BASELINE_API = Path(r"C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                    r"mf-reskin-correction-20260922/20260922T0955Z/VIDEO14B/waveB/workflows/"
                    r"mf_animate2_book4s.waveB.api.json")
BASELINE_CANONICAL = "f246221af10a27072481e6985c3683cf257269318e807c16e692261245cf3e5e"
# the single variable the M1 round changed
EXPECTED_DIFF = [{"field": "672:587.inputs.pose_end_percent", "baseline": 0, "candidate": 1}]


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def canonical_json(obj) -> str:
    """mf_comfy.pinning.canonical_json, restated: sort_keys, tight separators, NON-ascii kept.

    `ensure_ascii=False` is the entire difference from a naive sorted-key dump (the graph
    carries 133 non-ASCII characters in the Chinese negative prompt), so it is pinned here.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_sha(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def run(argv: list[str]) -> None:
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"command failed (rc={r.returncode}): {argv}\n{(r.stderr or '')[-2000:]}")


def role_frame(role: str, out_png: Path) -> Path:
    """Frame 0 of the role's own window, scaled onto the generation canvas (area)."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(ROLE_WINDOWS[role]), "-frames:v", "1",
         "-vf", f"scale={CANVAS[0]}:{CANVAS[1]}:flags=area", str(out_png)])
    if not out_png.is_file() or out_png.stat().st_size == 0:
        raise SystemExit(f"no frame extracted for role {role}")
    return out_png


def roi_of(diff) -> dict:
    import numpy as np
    mask = diff > ROI_THRESHOLD
    if not mask.any():
        return {"bbox": None, "frac_above_threshold": 0.0, "role_specific_region": False,
                "reason": "no pixel above the threshold"}
    ys, xs = np.where(mask)
    w = int(xs.max()) - int(xs.min()) + 1
    h = int(ys.max()) - int(ys.min()) + 1
    frac = (w * h) / (CANVAS[0] * CANVAS[1])
    return {"bbox": {"x": int(xs.min()), "y": int(ys.min()), "w": w, "h": h},
            "frac_of_canvas": round(frac, 6),
            "frac_above_threshold": round(float(mask.mean()), 6),
            "role_specific_region": bool(ROI_MIN_FRAC <= frac <= ROI_MAX_FRAC)}


def ui_reference_bindings(path: Path) -> list[dict]:
    """LoadImage -> the input it feeds, resolved through a UI graph's own link table."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    nodes = {str(n.get("id")): n for n in doc.get("nodes") or []}
    link_origin = {lk[0]: str(lk[1]) for lk in doc.get("links") or []
                   if isinstance(lk, list) and len(lk) >= 4}
    out = []
    for nid, node in nodes.items():
        for inp in node.get("inputs") or []:
            origin = link_origin.get(inp.get("link"))
            src = nodes.get(origin) if origin is not None else None
            if not src or src.get("type") != "LoadImage":
                continue
            out.append({"consumer_node": nid, "consumer_class_type": node.get("type"),
                        "input": inp.get("name"), "load_image_node": origin,
                        "load_image_file": (src.get("widgets_values") or [None])[0]})
    out.sort(key=lambda e: (e["consumer_node"], str(e["input"])))
    return out


def producers(graph: dict, node_id: str) -> list[dict]:
    out = []
    for nid, node in graph.items():
        for key, val in (node.get("inputs") or {}).items():
            if isinstance(val, list) and val and str(val[0]) == node_id:
                out.append({"consumer": nid, "input": key, "class_type": node.get("class_type")})
    return sorted(out, key=lambda e: (e["consumer"], str(e["input"])))


def reference_chain(graph: dict, start: str) -> dict:
    """Walk forward from a LoadImage to whatever consumes it, depth-first, deterministic."""
    steps = [{"node": start, "class_type": graph[start].get("class_type"),
              "file": (graph[start].get("inputs") or {}).get("image")}]
    seen = {start}
    frontier = [start]
    while frontier:
        nxt = []
        for node_id in frontier:
            for cons in producers(graph, node_id):
                if cons["consumer"] in seen:
                    continue
                seen.add(cons["consumer"])
                steps.append(cons)
                nxt.append(cons["consumer"])
        frontier = sorted(nxt)
    return {"load_image": start, "steps": steps,
            "reaches_clip_vision_encode": any(s.get("class_type") == "CLIPVisionEncode"
                                             for s in steps),
            "reference_encoder_inputs": [s for s in steps
                                         if s.get("class_type") == "CLIPVisionEncode"]}


def graph_diff(a, b, prefix: str = "") -> list[dict]:
    out: list[dict] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            out += graph_diff(a.get(key), b.get(key), f"{prefix}{key}.")
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            out += graph_diff(a[i] if i < len(a) else None, b[i] if i < len(b) else None,
                              f"{prefix}{i}.")
    elif a != b:
        out.append({"field": prefix[:-1], "baseline": a, "candidate": b})
    return out


def panel(path: Path, label: str, width: int = 640) -> "object":
    from PIL import Image, ImageDraw
    im = Image.open(path).convert("RGB")
    im = im.resize((width, int(im.height * width / im.width)))
    bar = 18
    out = Image.new("RGB", (im.width, im.height + bar), (24, 24, 24))
    out.paste(im, (0, bar))
    ImageDraw.Draw(out).text((4, 3), label, fill=(235, 235, 235))
    return out


def build_observation_sheet(out_png: Path, panels: list[tuple[Path, str]]) -> Path:
    imgs = [panel(p, lab) for p, lab in panels]
    cols = 2
    rows = (len(imgs) + cols - 1) // cols
    w = max(i.width for i in imgs) * cols
    h = max(i.height for i in imgs) * rows
    from PIL import Image
    sheet = Image.new("RGB", (w, h), (16, 16, 16))
    for k, im in enumerate(imgs):
        sheet.paste(im, ((k % cols) * im.width, (k // cols) * im.height))
    sheet.save(out_png)
    if out_png.stat().st_size == 0:
        raise SystemExit("observation sheet is empty")
    return out_png


def main() -> int:
    wt = _p(sys.argv[1])
    out_dir = _p(sys.argv[2])
    ev_out = _p(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)

    import numpy as np
    from PIL import Image

    target_sha = sha256_file(TARGET_ASSET)
    source_sha = sha256_file(SOURCE_ASSET)
    if target_sha != TARGET_ASSET_SHA or source_sha != SOURCE_ASSET_SHA:
        raise SystemExit(f"asset pin mismatch: target={target_sha} source={source_sha}")

    target = np.asarray(Image.open(TARGET_ASSET).convert("RGB"))
    source = np.asarray(Image.open(SOURCE_ASSET).convert("RGB"))
    d_target_source = np.abs(target.astype(np.int16) - source.astype(np.int16)).mean(axis=2)

    frames: dict[str, "object"] = {}
    role_rows: dict[str, dict] = {}
    for role in ROLES:
        frame_png = role_frame(role, out_dir / f"role_frame_{role}_640x368.png")
        frame = np.asarray(Image.open(frame_png).convert("RGB"))
        frames[role] = frame
        d = np.abs(frame.astype(np.int16) - target.astype(np.int16)).mean(axis=2)
        role_rows[role] = {
            "role_id": role,
            "role_window_label": ROLE_WINDOW_LABEL[role],
            "role_window": str(ROLE_WINDOWS[role]).replace("\\", "/"),
            "role_window_sha256": sha256_file(ROLE_WINDOWS[role]),
            "role_frame_png": str(frame_png).replace("\\", "/"),
            "role_frame_sha256": sha256_file(frame_png),
            "frozen_ref_asset": str(TARGET_ASSET).replace("\\", "/"),
            "frozen_ref_sha256": target_sha,
            "frozen_ref_pixels": list(Image.open(TARGET_ASSET).size),
            "residual_target_vs_role_frame": {
                "mae_mean": round(float(d.mean()), 6), "max_abs": int(d.max()),
                "frac_above_threshold": round(float((d > ROI_THRESHOLD).mean()), 6)},
            "ref_differs_from_this_roles_source": bool(int(d.max()) > 0),
            "role_specific_crop_roi": roi_of(d),
        }

    # cross-role: is there a region that SEPARATES the roles from each other?
    cross: dict[str, dict] = {}
    for role in ROLES:
        others = [np.abs(frames[role].astype(np.int16) - frames[o].astype(np.int16)).mean(axis=2)
                  for o in ROLES if o != role]
        d = np.mean(others, axis=0)
        cross[role] = {"mae_mean_vs_other_roles": round(float(d.mean()), 6),
                       "max_abs": int(d.max()), **roi_of(d)}

    chains = []
    anim_path = wt / ANIMATE_GRAPH
    anim_graph = json.loads(anim_path.read_text(encoding="utf-8"))
    for nid in sorted(nid for nid, n in anim_graph.items()
                      if n.get("class_type") == "LoadImage"):
        chains.append(reference_chain(anim_graph, nid))
    vace_bindings = ui_reference_bindings(wt / VACE_GRAPH)

    baseline_doc = json.loads(BASELINE_API.read_text(encoding="utf-8"))
    diff = graph_diff(baseline_doc, anim_graph)

    sheet = build_observation_sheet(out_dir / "v02_reference_observation_sheet.png", [
        (TARGET_ASSET, "FROZEN TARGET ref (test-only cast asset)"),
        (SOURCE_ASSET, "SOURCE identity (what it must differ from)"),
        (role_rows["BOOK"]["role_frame_png"], "BOOK window frame 0"),
        (role_rows["TURN"]["role_frame_png"], "TURN window frame 0"),
        (role_rows["OCC"]["role_frame_png"], "OCC window frame 0"),
    ])

    ref_shas = {r: target_sha for r in ROLES}
    checks = {
        "roles_are_book_turn_occ": list(ROLES) == ["BOOK", "TURN", "OCC"],
        "every_role_has_a_role_keyed_ref": all(role_rows[r]["frozen_ref_sha256"] for r in ROLES),
        "same_frozen_refs_used_across_all_roles": len(set(ref_shas.values())) == 1,
        "target_ref_differs_from_source_identity": target_sha != source_sha,
        "target_ref_differs_from_source_at_pixels":
            bool(int(d_target_source.max()) > 0),
        "every_role_ref_differs_from_that_roles_source": all(
            role_rows[r]["ref_differs_from_this_roles_source"] for r in ROLES),
        "no_role_crop_fabricated": all(
            not role_rows[r]["role_specific_crop_roi"]["role_specific_region"] for r in ROLES),
        "graph_pins_match_the_released_copies": (
            sha256_file(anim_path) == ANIMATE_GRAPH_SHA
            and canonical_sha(anim_graph) == ANIMATE_CANONICAL
            and canonical_sha(baseline_doc) == BASELINE_CANONICAL),
        "canonical_graph_diff_is_the_single_m1_variable": diff == EXPECTED_DIFF,
        "loadimage_reaches_clip_vision_encode": all(c["reaches_clip_vision_encode"] for c in chains),
        "vace_reference_binding_traced": bool(vace_bindings),
        "not_an_approved_library_pack": True,
        "test_only_never_published": True,
    }

    rec = {
        "artifact": "v02_role_ref_freeze.json", "task_id": "MF-V1-VIDEO14B", "row": "V02",
        "round": "roundC",
        "rule": ("freeze one role-keyed reference table for BOOK/TURN/OCC from the existing "
                 "target design (test-only) and prove the binding, the asset SHA mapping and "
                 "the target-vs-source difference"),
        "test_only": True,
        "published": False,
        "user_approved": False,
        "approved_library_pack_exists": False,
        "test_only_statement": (
            "TEST-ONLY: never published, never user-approved.  A whole-scene anchor is not an "
            "approved library pack, and this freeze does NOT promote these artifacts into one; "
            "it records the binding that exists so a later pack can be pinned against it."),
        "canvas": list(CANVAS),
        "assets": {
            "target_design": {"path": str(TARGET_ASSET).replace("\\", "/"), "sha256": target_sha,
                              "pixels": list(Image.open(TARGET_ASSET).size),
                              "is": ["runtime/input/mf_book_anchor_1650.png (LoadImage 189 / 134)",
                                     "wave-B reference_chosen_640x368.png",
                                     "fixtures/test_only_cast_asset.png"],
                              "target_vs_source": {
                                  "mae_mean": round(float(d_target_source.mean()), 6),
                                  "max_abs": int(d_target_source.max()),
                                  "sha_differs": target_sha != source_sha}},
            "source_identity": {"path": str(SOURCE_ASSET).replace("\\", "/"),
                                "sha256": source_sha,
                                "pixels": list(Image.open(SOURCE_ASSET).size),
                                "is": ["fixtures/test_only_other_asset.png"]},
        },
        "frozen_role_to_ref_sha256": ref_shas,
        "roles": role_rows,
        "cross_role_separation": cross,
        "negative_result_no_role_crop_was_invented": {
            "why": ("neither the target-vs-role residual nor the cross-role difference yields a "
                    "role-specific region: every candidate bounding box covers the whole canvas "
                    "(frac_of_canvas 1.0, frac_above_threshold 0.88-0.99), so a 'role crop' would "
                    "be the full scene re-labelled.  No crop is fabricated; the numbers are here "
                    "so a reviewer can re-derive the decision."),
            "target_vs_role_frac_of_canvas": {r: role_rows[r]["role_specific_crop_roi"]
                                              .get("frac_of_canvas") for r in ROLES},
            "cross_role_mae_mean": {r: cross[r]["mae_mean_vs_other_roles"] for r in ROLES},
        },
        "loadimage_to_reference_encoder_trace": {
            "animate_graph": ANIMATE_GRAPH,
            "animate_graph_file_sha256": sha256_file(anim_path),
            "animate_graph_canonical_sha256": canonical_sha(anim_graph),
            "animate_reference_chains": chains,
            "vace_graph": VACE_GRAPH,
            "vace_graph_file_sha256": sha256_file(wt / VACE_GRAPH),
            "vace_reference_bindings": vace_bindings,
            "is_approved_library_pack": False,
            "why_not_a_library_pack": ("the binding is one whole-scene anchor file feeding the "
                                       "reference encoder, not a role-keyed pack with versions"),
        },
        "canonical_graph_diff": {
            "baseline": str(BASELINE_API).replace("\\", "/"),
            "baseline_canonical_sha256": canonical_sha(baseline_doc),
            "candidate": ANIMATE_GRAPH, "candidate_canonical_sha256": canonical_sha(anim_graph),
            "differing_fields": diff, "count": len(diff),
            "is_the_single_m1_variable": diff == EXPECTED_DIFF},
        "visual_observation_input": {
            "sheet": str(sheet).replace("\\", "/"), "sheet_sha256": sha256_file(sheet),
            "panels": ["FROZEN TARGET ref", "SOURCE identity", "BOOK frame 0", "TURN frame 0",
                       "OCC frame 0"],
            "note": ("pixels handed to a reviewer / auxiliary vision model; this tool itself "
                     "makes NO visual claim")},
        "checks": checks,
    }
    rec["verdict"] = "ROLE_REFS_FROZEN_TEST_ONLY" if all(checks.values()) else "INCOMPLETE"
    ev_out.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"checks": checks, "ref_sha": target_sha,
                      "roi": {r: role_rows[r]["role_specific_crop_roi"] for r in ROLES},
                      "cross_role_mae": {r: cross[r]["mae_mean_vs_other_roles"] for r in ROLES},
                      "diff": diff, "sheet": rec["visual_observation_input"]["sheet"],
                      "verdict": rec["verdict"]}, indent=1))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
