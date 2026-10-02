"""MF-V1-VIDEO14B round I1 -- collect the produced anchors: delivery crop, sheets, timings.

  deliver : crop the 640x368 generation canvas back to 640x360 with the pad-inverse
            (`v14b_geometry.crop_image`, translation only) and hash both forms.
  timings : RECOMPUTE the per-anchor timings from the saved history JSONs.  The first
            version of `i1_run_anchor.py` subtracted epoch SECONDS from engine
            MILLISECOND timestamps, so the queue/exec fields it wrote into the ledger
            rows were wrong; the numbers here are derived from the engine's own
            execution_start / execution_success values divided by 1000, and the ledger's
            bad values are recorded next to the corrected ones instead of being edited
            away.
  sheets  : one labelled contact sheet per anchor (source frame | every reference the
            encoder read | the produced anchor, at the same canvas) plus a combined
            review sheet of all three rows.

usage: python i1_collect.py [--shots BOOK TURN OCC]
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v14b_geometry import PAD_BOTTOM, PAD_TOP, crop_image  # noqa: E402
from i1_contact_sheet import build  # noqa: E402

RT = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b")
REPO = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/wt-video14b/experiments/mf_reskin_v1/video14b")
STATE = RT / "state" / "roundI1"
OUT = RT / "output" / "mf_reskin_v1" / "video14b" / "roundI1"
SPEC = REPO / "workflows" / "run" / "roundI1" / "roundI1_spec.json"
LEDGER = STATE / "i1_prompt_ledger.jsonl"
SHOTS = ("BOOK", "TURN", "OCC")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def info(p: Path) -> dict:
    from PIL import Image
    im = Image.open(p)
    return {"path": str(p).replace("\\", "/"), "bytes": p.stat().st_size,
            "sha256": sha256_file(p), "size": list(im.size), "mode": im.mode}


def ledger_rows() -> list[dict]:
    if not LEDGER.is_file():
        return []
    return [json.loads(ln) for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]


def main() -> int:
    shots = SHOTS
    if "--shots" in sys.argv:
        i = sys.argv.index("--shots")
        shots = tuple(sys.argv[i + 1:])
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    native = json.loads((STATE / "i1_native_frames.json").read_text(encoding="utf-8"))
    refman = json.loads((STATE / "i1_ref_manifest.json").read_text(encoding="utf-8"))
    epoch = json.loads((RT / "instance_epoch.json").read_text(encoding="utf-8"))
    hashes = json.loads((STATE / "i1_model_hashes.json").read_text(encoding="utf-8"))
    rows = ledger_rows()
    rec: dict = {"artifact": "i1_collect.json", "task_id": "MF-V1-VIDEO14B", "round": "I1",
                 "engine_epoch_at_collect": epoch, "model_hashes": hashes,
                 "pad": {"top": PAD_TOP, "bottom": PAD_BOTTOM,
                         "rule": "delivery 640x360 = pad-inverse of the 640x368 canvas, translation only"},
                 "shots": {}, "timings": {}, "sheets": {}, "errors": []}

    delivery_dir = STATE / "deliver_640x360"
    delivery_dir.mkdir(parents=True, exist_ok=True)
    sheet_dir = STATE / "sheets"
    sheet_dir.mkdir(parents=True, exist_ok=True)

    for shot in shots:
        g = OUT / f"anchor_{shot.lower()}_i1_00001_.png"
        if not g.is_file():
            rec["errors"].append(f"{shot}: generated anchor absent: {g}")
            continue
        from PIL import Image
        canvas = info(g)
        if canvas["size"] != [640, 368]:
            rec["errors"].append(f"{shot}: anchor canvas is {canvas['size']}, expected [640, 368]")
        dv = delivery_dir / f"anchor_{shot.lower()}_i1_640x360.png"
        crop_image(Image.open(g)).save(dv)
        delivery = info(dv)
        if delivery["size"] != [640, 360]:
            rec["errors"].append(f"{shot}: delivery crop is {delivery['size']}, expected [640, 360]")
        # independent check: crop(pad(native frame)) must equal the native frame bit for bit
        nat = [f for f in native["frames"][shot]["frames"] if f["index"] == 0][0]
        np_ = Path(nat["native"]["path"])
        roundtrip = bool((Image.open(np_).convert("RGB").tobytes()
                          == crop_image(Image.open(nat["padded_640x368"]["path"])).convert("RGB").tobytes()))
        rec["shots"][shot] = {
            "kind": spec["graphs"][shot]["kind"],
            "graph": spec["graphs"][shot]["graph"],
            "graph_sha256": spec["graphs"][shot]["graph_sha256"],
            "seed": spec["graphs"][shot]["seeds"][0]["noise_seed"],
            "instruction": spec["graphs"][shot]["instruction"],
            "canvas": canvas, "delivery_640x360": delivery,
            "delivery_is_pad_inverse_of_the_generated_canvas": True,
            "independent_crop_of_the_padded_native_frame_is_bit_exact": roundtrip,
            "references": [r for r in refman["rows"] if r["shot"] == shot],
            "source_frames": native["frames"][shot],
        }

        # ---------------------------------------------------------------- contact sheets
        cells = [{"path": spec["graphs"][shot]["refs"][0]["staged_path"],
                  "label": f"ref1 source frame {shot} f000 (native+pad)"}]
        for r in spec["graphs"][shot]["refs"][1:]:
            cells.append({"path": r["staged_path"], "label": f"ref{r['index']} {r['role']}"})
        cells.append({"path": str(g).replace("\\", "/"), "label": f"{shot} ANCHOR (640x368)"})
        cells.append({"path": str(dv).replace("\\", "/"), "label": f"{shot} delivery (640x360)"})
        sp = sheet_dir / f"sheet_{shot.lower()}.spec.json"
        sp.write_text(json.dumps({"title": f"MF-V1-VIDEO14B I1 {shot}: references the encoder read -> produced anchor",
                                  "cell_w": 512, "cell_h": 296, "pad": 8, "label_px": 16,
                                  "rows": [{"label": f"{shot}: sources + references + anchor + delivery",
                                            "cells": cells}]}, indent=1, ensure_ascii=False), encoding="utf-8")
        sheet = sheet_dir / f"sheet_{shot.lower()}.png"
        rep = build(json.loads(sp.read_text(encoding="utf-8")), sheet)
        rep["sha256"] = sha256_file(sheet)
        rep["bytes"] = sheet.stat().st_size
        rec["sheets"][shot] = rep

    # ---------------------------------------------------------------- corrected timings
    for shot in shots:
        for row in [r for r in rows if r.get("event") == "post" and r.get("shot") == shot
                    and r.get("result") == "DONE"]:
            mt = row["summary"]["message_times"]
            start, end = mt.get("execution_start"), mt.get("execution_success")
            post_ts = row["ts"]
            rec["timings"][f"{shot}:{row['attempt_tag']}"] = {
                "shot": shot, "prompt_id": row["prompt_id"], "attempt_tag": row["attempt_tag"],
                "reason_recorded_before_the_post": row.get("reason"),
                "engine_execution_start_ms": start, "engine_execution_success_ms": end,
                "engine_clock_is_epoch_milliseconds": True,
                "exec_s": round((end - start) / 1000.0, 3) if start and end else None,
                "queue_wait_s": round(start / 1000.0 - post_ts, 3) if start else None,
                "engine_wall_s_from_the_runner": row.get("engine_wall_s"),
                "vram_before_mib": row["vram_before"]["nvidia"]["used_mib"],
                "vram_after_mib": row["vram_after"]["nvidia"]["used_mib"],
                "vram_peak_sampled_mib": row.get("vram_sample_peak_mib"),
                "unload_before_vram": {"before_mib": row["pre_unload"]["before"]["nvidia"]["used_mib"],
                                       "after_mib": row["pre_unload"]["after"]["nvidia"]["used_mib"]}
                                      if row.get("pre_unload") else None,
                "ledger_as_written_was_wrong_for_queue_wait_s_and_exec_s":
                    {"ledger_queue_wait_s": row.get("queue_wait_s"), "ledger_exec_s": row.get("exec_s"),
                     "why": "i1_run_anchor.py subtracted epoch seconds from engine millisecond "
                            "timestamps; corrected here from the same engine values / 1000"},
                "model_load_lines": row["log"]["load_lines"],
                "model_prepare_lines": row["log"]["prepare_lines"],
                "log_slice": row["log"]["path"], "history_json": row["history_json"],
            }

    # ------------------------------------------------------- the one diagnosed correction
    corr_path = REPO / "workflows" / "run" / "roundI1" / "i1_correction.json"
    if corr_path.is_file():
        corr = json.loads(corr_path.read_text(encoding="utf-8"))
        shot = corr["shot"]
        cg = OUT / "anchor_book_i1c1_00001_.png"
        if cg.is_file():
            canvas = info(cg)
            dvc = delivery_dir / "anchor_book_i1c1_640x360.png"
            crop_image(Image.open(cg)).save(dvc)
            delivery = info(dvc)
            cells = [{"path": spec["graphs"][shot]["refs"][0]["staged_path"],
                      "label": f"ref1 source frame {shot} f000 (native+pad)"}]
            for r in spec["graphs"][shot]["refs"][1:]:
                cells.append({"path": r["staged_path"], "label": f"ref{r['index']} {r['role']}"})
            cells.append({"path": rec["shots"][shot]["canvas"]["path"], "label": f"{shot} attempt a1 (first)"})
            cells.append({"path": str(cg).replace("\\", "/"), "label": f"{shot} attempt c1 (the one correction)"})
            cells.append({"path": spec["graphs"][shot]["refs"][0]["staged_path"],
                          "label": "source frame at the same index"})
            sp = sheet_dir / "sheet_book_correction.spec.json"
            sp.write_text(json.dumps({"title": f"MF-V1-VIDEO14B I1 {shot}: references | attempt a1 | corrected c1 | source",
                                      "cell_w": 512, "cell_h": 296, "pad": 8, "label_px": 16,
                                      "rows": [{"label": f"{shot}: is the corrected attempt closer to the reference?",
                                                "cells": cells}]}, indent=1, ensure_ascii=False), encoding="utf-8")
            sheet = sheet_dir / "sheet_book_correction.png"
            rep = build(json.loads(sp.read_text(encoding="utf-8")), sheet)
            rep["sha256"] = sha256_file(sheet)
            rep["bytes"] = sheet.stat().st_size
            rec["corrections"] = {shot: {
                "diagnosis_recorded_before_the_post": corr["diagnosis"],
                "seed_before": corr["seed_before"], "seed_after": corr["seed_after"],
                "instruction_sha256_before": corr["instruction_sha256_before"],
                "instruction_sha256_after": corr["instruction_sha256_after"],
                "instruction_chars_before": corr["instruction_chars_before"],
                "instruction_chars_after": corr["instruction_chars_after"],
                "graph_before": corr["src"], "graph_after": corr["dst"],
                "graph_before_sha256": corr["graph_before_sha256"], "graph_after_sha256": corr["graph_sha256"],
                "changed_node_ids": corr["changed_node_ids"],
                "wiring_and_references_unchanged": corr["wiring_and_references_unchanged"],
                "canvas": canvas, "delivery_640x360": delivery, "sheet": rep,
                "first_attempt_untouched": rec["shots"][shot]["canvas"],
            }}
            if shot in rec["shots"]:
                rec["shots"][shot]["corrected_attempt"] = rec["corrections"][shot]["canvas"]
        else:
            rec["errors"].append(f"correction graph recorded but its output is absent: {cg}")

    # ---------------------------------------------------------------- combined review sheet
    crells = []
    for shot in shots:
        if shot not in rec["shots"]:
            continue
        crells.append({"path": rec["shots"][shot]["canvas"]["path"], "label": f"{shot} ANCHOR"})
        crells.append({"path": rec["shots"][shot]["source_frames"]["frames"][0]["native"]["path"],
                       "label": f"{shot} source f000 native 640x360 (actual decode)"})
    cs = sheet_dir / "sheet_combined.spec.json"
    cs.write_text(json.dumps({"title": "MF-V1-VIDEO14B I1 combined review: each produced anchor beside its native source frame",
                              "cell_w": 512, "cell_h": 296, "pad": 8, "label_px": 16,
                              "rows": [{"label": f"{shots[i]} anchor | {shots[i]} native source",
                                        "cells": crells[2 * i:2 * i + 2]}
                                       for i in range(len(shots))]}, indent=1, ensure_ascii=False), encoding="utf-8")
    csheet = sheet_dir / "sheet_combined.png"
    crep = build(json.loads(cs.read_text(encoding="utf-8")), csheet)
    crep["sha256"] = sha256_file(csheet)
    crep["bytes"] = csheet.stat().st_size
    rec["sheets"]["combined_review"] = crep
    out = STATE / "i1_collect.json"
    out.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"shots": {s: {"canvas": v["canvas"]["sha256"][:12],
                                    "delivery": v["delivery_640x360"]["sha256"][:12],
                                    "bytes": v["canvas"]["bytes"]} for s, v in rec["shots"].items()},
                      "timings": {s: {"exec_s": v["exec_s"], "queue_wait_s": v["queue_wait_s"],
                                      "peak_mib": v["vram_peak_sampled_mib"]} for s, v in rec["timings"].items()},
                      "sheets": {k: v["sha256"][:12] for k, v in rec["sheets"].items()},
                      "errors": rec["errors"], "json": str(out)}, indent=1))
    return 1 if rec["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
