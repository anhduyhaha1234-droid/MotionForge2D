"""MF-V1-VIDEO14B round I1 -- assemble the evidence bundle + BENCH's 6-item freeze package.

Copies every I1 artifact into the evidence root with a hash manifest (enumerated at the ROOT
and in each subtree -- a manifest that recurses one directory misses the deliverables), runs an
INDEPENDENT ffprobe/PIL geometry check on each delivered artifact, builds the 6-item identity
package BENCH asked for, and writes the FROZEN marker LAST.

usage: python i1_evidence.py <evidence_root> <frozen_at_iso>
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

RT = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")
REPO = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/wt-video14b/experiments/mf_reskin_v1/video14b")
STATE = RT / "state" / "roundI1"
OUT = RT / "output" / "mf_reskin_v1" / "video14b" / "roundI1"
BENCH = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/bench/src_windows")
SHOT_WINDOW = {"BOOK": "BOOK_src.mp4", "TURN": "TURN_795_src.mp4", "OCC": "OCC_14768_src.mp4"}
SOURCE_START_FRAME = {"BOOK": 1650, "TURN": 795, "OCC": 14768}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def ffprobe(p: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=index,codec_type,codec_name,width,height,nb_frames,r_frame_rate",
                        "-of", "json", str(p)], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)["streams"]
    except Exception:  # noqa: BLE001
        return [{"probe_failed": r.stderr[-200:]}]


def copy(src: Path, dst: Path, rows: list) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_file() and src.resolve() != dst.resolve():
        shutil.copyfile(src, dst)
    row = {"evidence_path": str(dst).replace("\\", "/"), "source_path": str(src).replace("\\", "/"),
           "present": dst.is_file()}
    if row["present"]:
        row.update({"sha256": sha256_file(dst), "bytes": dst.stat().st_size})
    rows.append(row)
    return row


def main() -> int:
    ev = Path(sys.argv[1].replace("\\", "/"))
    frozen_at = sys.argv[2]
    raw = ev / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    files: list = []

    for name in ("i1_TARGET.md", "i1_native_frames.json", "i1_ref_manifest.json",
                 "i1_prompt_ledger.jsonl", "i1_collect.json", "i1_model_hashes.json",
                 "i1_visual_observation.json"):
        src = next((c for c in (ev / name, ev / "raw" / name, STATE / name) if c.is_file()), ev / name)
        copy(src, raw / name, files)
    for name in ("i1_correction.json",):
        copy(REPO / "workflows" / "run" / "roundI1" / name, raw / name, files)
    for name in ("roundI1_spec.json", "anchor_book.i1.api.json", "anchor_turn.i1.api.json",
                 "anchor_occ.i1.api.json", "anchor_book.i1c1.api.json"):
        copy(REPO / "workflows" / "run" / "roundI1" / name, raw / "graphs" / name, files)
    copy(RT / "instance_epoch.json", raw / "instance_epoch_at_collect.json", files)
    copy(RT / "logs" / "server_gpu_i1.log", raw / "server_gpu_i1.log", files)
    for lg in sorted(STATE.glob("logslice_*.log")):
        copy(lg, raw / "logslices" / lg.name, files)
    for hj in sorted(STATE.glob("history_*.json")):
        copy(hj, raw / "history" / hj.name, files)
    for sh in sorted((STATE / "sheets").glob("*.png")):
        copy(sh, raw / "sheets" / sh.name, files)
    copy(STATE / "object_info_live_8310_post_stage.json", raw / "object_info_live_8310_post_stage.json", files)

    collect = json.loads((STATE / "i1_collect.json").read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- independent geometry
    geometry = {}
    for shot in ("BOOK", "TURN", "OCC"):
        for tag, key in (("canvas", "canvas"), ("delivery", "delivery_640x360")):
            if shot not in collect["shots"]:
                continue
            p = Path(collect["shots"][shot][key]["path"])
            geometry[f"{shot}_{tag}"] = {"path": str(p).replace("\\", "/"),
                                         "sha256_recomputed": sha256_file(p),
                                         "bytes": p.stat().st_size, "ffprobe_streams": ffprobe(p)}
        if "corrected_attempt" in collect["shots"].get(shot, {}):
            p = Path(collect["shots"][shot]["corrected_attempt"]["path"])
            geometry[f"{shot}_correction_canvas"] = {"path": str(p).replace("\\", "/"),
                                                     "sha256_recomputed": sha256_file(p),
                                                     "bytes": p.stat().st_size, "ffprobe_streams": ffprobe(p)}
            p = Path(collect["corrections"][shot]["delivery_640x360"]["path"])
            geometry[f"{shot}_correction_delivery"] = {"path": str(p).replace("\\", "/"),
                                                       "sha256_recomputed": sha256_file(p),
                                                       "bytes": p.stat().st_size, "ffprobe_streams": ffprobe(p)}
    rec_sha = {}
    for shot, c in collect["shots"].items():
        rec_sha[Path(c["canvas"]["path"]).as_posix()] = c["canvas"]["sha256"]
        rec_sha[Path(c["delivery_640x360"]["path"]).as_posix()] = c["delivery_640x360"]["sha256"]
    for shot, c in (collect.get("corrections") or {}).items():
        rec_sha[Path(c["canvas"]["path"]).as_posix()] = c["canvas"]["sha256"]
        rec_sha[Path(c["delivery_640x360"]["path"]).as_posix()] = c["delivery_640x360"]["sha256"]
    hashes_ok = all(v["sha256_recomputed"] == rec_sha.get(Path(v["path"]).as_posix())
                    for v in geometry.values())
    audio_measured = {k: [s.get("codec_type") for s in v["ffprobe_streams"]] for k, v in geometry.items()}

    # ------------------------------------------------------- BENCH's 6-item identity package
    rows = []
    for shot in ("BOOK", "TURN", "OCC"):
        if shot not in collect["shots"]:
            continue
        c = collect["shots"][shot]
        win = BENCH / SHOT_WINDOW[shot]
        rows.append({
            "shot": shot,
            "1_clip_or_artifact_identity": {
                "canvas_path": c["canvas"]["path"], "canvas_sha256": c["canvas"]["sha256"],
                "canvas_bytes": c["canvas"]["bytes"], "canvas_size": c["canvas"]["size"],
                "delivery_path": c["delivery_640x360"]["path"],
                "delivery_sha256": c["delivery_640x360"]["sha256"],
                "delivery_bytes": c["delivery_640x360"]["bytes"],
                "delivery_size": c["delivery_640x360"]["size"],
                "media_type": "still PNG (RGB), NOT a clip: no fps, no frame count, no window"},
            "2_source_window": {
                "path": str(win).replace("\\", "/"), "sha256": sha256_file(win),
                "bytes": win.stat().st_size,
                "start_frame_in_the_pinned_film": SOURCE_START_FRAME[shot],
                "reproducible_extract": f"ffmpeg -i <window> -vf \"select='eq(n,<idx>)'\" -frames:v 1 "
                                       f"out.png  (idx in 0,40,80,119), then pad 4/4 by translation",
                "film_pin": "5a175454...9fa2 (BENCH's pin; NOT re-hashed by this lane - the film file "
                            "is not present in this tree, only the per-shot windows are)"},
            "3_mapping_and_padding": {
                "window_id": f"{shot}_f000",
                "source_start_frame": SOURCE_START_FRAME[shot],
                "frame_count_of_window": 120, "output_frame_count": "n/a (still)",
                "padding": "top 4 + bottom 4 blank lines, 640x360 -> 640x368, TRANSLATION ONLY "
                           "(tools/v14b_geometry.py); delivery = the inverse crop",
                "index_mapping": "the anchor corresponds to frame index 0 of the window = source "
                                 "frame SOURCE_START_FRAME + 0",
                "note": "round D's own frame extraction RESAMPLED 640x360 -> 640x368 (scale=640:368); "
                        "I1 re-decoded the frames natively and padded by translation instead "
                        "(raw/i1_native_frames.json)"},
            "4_audio_decision": {"decision": "NOT_APPLICABLE__THE_ANCHOR_IS_A_STILL_PNG",
                                 "measured_streams": audio_measured.get(f"{shot}_canvas"),
                                 "nothing_invented": True},
            "5_engine_facts": {
                "engine": "ComfyUI 0.37.0", "comfyui_commit": "73c9bad4d21e7addbe1d13bc92eee0f1431b017d",
                "base_url": collect["engine_epoch_at_collect"]["base_url"],
                "instance_id": collect["engine_epoch_at_collect"]["instance_id"],
                "pid": collect["engine_epoch_at_collect"]["pid"],
                "port": collect["engine_epoch_at_collect"]["port"],
                "gpu": "NVIDIA GeForce RTX 5070, 12227 MiB",
                "weights_sha256": collect["model_hashes"],
                "sampler": "KSamplerSelect euler + Flux2Scheduler + SamplerCustomAdvanced + CFGGuider cfg=1",
                "steps": 4, "seed": c["seed"], "canvas": c["canvas"]["size"],
                "timings": {k: v for k, v in collect["timings"].items() if k.startswith(shot)},
                "graph": c["graph"], "graph_sha256": c["graph_sha256"],
                "references_read_by_the_encoder": [
                    {"index": r["index"], "role": r["role"], "loadimage_value": r["loadimage_value"],
                     "staged_path": r["staged_path"], "staged_sha256": r["staged_sha256"],
                     "staged_bytes": r["staged_bytes"], "frozen_path": r["frozen_path"],
                     "frozen_sha256": r["frozen_sha256"],
                     "byte_identical_to_the_frozen_file": r["byte_identical"]}
                    for r in c["references"]],
            },
            "6_freeze_state": {"frozen_at": frozen_at,
                               "owning_lane": "MF-V1-VIDEO14B (this lane)",
                               "lane_stopped_writing": "declared in i1_FROZEN.marker after this manifest",
                               "bytes_immutable_from_drop_time": True},
        })
    frozen = {"artifact": "i1_freeze_package.json", "task_id": "MF-V1-VIDEO14B", "round": "I1",
              "for": "MF-V1-BENCH first media evaluation (its 6-item identity list)",
              "frozen_at": frozen_at, "shots": rows,
              "generation_budget": {"posts_total": len([r for r in
                                                        (STATE / "i1_prompt_ledger.jsonl").read_text(encoding="utf-8").splitlines()
                                                        if r.strip() and json.loads(r).get("event") == "post"]),
                                    "cap": 4, "anchors": 3, "diagnosed_corrections": 1, "seed_sweeps": 0},
              "blockers": {"BOOK": (json.loads((ev / "raw" / "i1_visual_observation.json").read_text(encoding="utf-8"))
                                    ["shots"]["BOOK"]["verdict_code"]
                           if (ev / "raw" / "i1_visual_observation.json").is_file() else None),
                           "I2_READY": False,
                           "I2_blocker": "I2 animates the BOOK shot; its first-frame reference is the BOOK "
                                         "anchor, whose diagnosed defects (open-book two-hand contact and "
                                         "BOOK-P3 placement) persist after the one allowed correction. "
                                         "TURN and OCC are prop/detail anchors and do not gate I2."}}
    (raw / "i1_freeze_package.json").write_text(json.dumps(frozen, indent=1, ensure_ascii=False), encoding="utf-8")

    facts = {"artifact": "i1_engine_facts.json", "task_id": "MF-V1-VIDEO14B", "round": "I1",
             "geometry_independent_check": geometry,
             "geometry_hashes_agree_with_the_collector": hashes_ok,
             "audio_streams_measured": audio_measured,
             "engine_epoch_at_collect": collect["engine_epoch_at_collect"],
             "model_hashes": collect["model_hashes"],
             "object_info_live_sha256": sha256_file(STATE / "object_info_live_8310_post_stage.json"),
             "timings": collect["timings"],
             "corrections": collect.get("corrections", {}),
             "server_log_sha256": sha256_file(RT / "logs" / "server_gpu_i1.log")}
    (raw / "i1_engine_facts.json").write_text(json.dumps(facts, indent=1, ensure_ascii=False), encoding="utf-8")

    # ---------------------------------------------------------------- manifest (ROOT + subtrees)
    for extra in ("i1_freeze_package.json", "i1_engine_facts.json"):
        files.append({"evidence_path": str(raw / extra).replace("\\", "/"), "present": True,
                      "sha256": sha256_file(raw / extra), "bytes": (raw / extra).stat().st_size})
    # a fixed deliverable list can silently miss a file the round wrote later (round D shipped a
    # manifest that recursed one subtree and omitted its own top-level report), so ALSO enumerate
    # the evidence root recursively and add anything the fixed list did not already cover.
    known = {f["evidence_path"] for f in files}
    for p in sorted(raw.glob("**/*")):
        if p.is_file():
            ep = str(p).replace("\\", "/")
            if ep not in known:
                files.append({"evidence_path": ep, "source_path": "added by the recursive evidence-root scan",
                              "present": True, "sha256": sha256_file(p), "bytes": p.stat().st_size})
                known.add(ep)
    manifest = {"artifact": "i1_evidence_manifest.json", "task_id": "MF-V1-VIDEO14B", "round": "I1",
                "evidence_root": str(ev).replace("\\", "/"), "frozen_at": frozen_at,
                "enumerated_from": "the fixed deliverable list PLUS a recursive scan of the evidence root "
                                   "(raw/**), deduplicated; this file and i1_FROZEN.marker are written last "
                                   "and are therefore intentionally not inside their own enumeration",
                "files": files, "file_count": len(files),
                "all_present": all(f["present"] for f in files),
                "geometry_hashes_agree": hashes_ok}
    (raw / "i1_evidence_manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    marker = {"artifact": "i1_FROZEN.marker", "task_id": "MF-V1-VIDEO14B", "round": "I1",
              "frozen_at": frozen_at,
              "owning_lane_stopped_writing": True,
              "statement": "The MF-V1-VIDEO14B I1 lane has stopped writing into this root. Every file "
                           "listed in raw/i1_evidence_manifest.json is byte-immutable from this moment; "
                           "verify with the sha256 values in that manifest.",
              "manifest": str(raw / "i1_evidence_manifest.json").replace("\\", "/")}
    (raw / "i1_FROZEN.marker").write_text(json.dumps(marker, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"files": len(files), "all_present": manifest["all_present"],
                      "geometry_hashes_agree": hashes_ok,
                      "posts_total": frozen["generation_budget"]["posts_total"],
                      "frozen_marker": str(raw / "i1_FROZEN.marker")}, indent=1))
    return 0 if manifest["all_present"] and hashes_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
