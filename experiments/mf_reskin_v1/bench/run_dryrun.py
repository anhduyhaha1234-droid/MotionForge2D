"""MF-V1-BENCH run_dryrun.py - dry-run the harness on FROZEN artifacts (read-only).

Reads (never writes): GOLDEN fixture/masks/annotations, COMFY calibration stills,
PROPAGATE clips+assembled. Writes only under the task's own write-set:
  <WT_BENCH>/experiments/mf_reskin_v1/bench/**        (code, docs)
  <RUNTIME>/bench/**                                  (temp extracts, broken controls)
  <BENCH_EV>/**                                       (evidence + review copies)

Usage:
  python run_dryrun.py --steps golden,extract,propagate,stills,negatives,sheets,report
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C          # noqa: E402
import probe as P           # noqa: E402
import compare as CMP       # noqa: E402
import assertions as A      # noqa: E402
import sheet as S           # noqa: E402

VENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
RAW = C.BENCH_EV / "raw"
SRC_EXTRACTS = C.RUNTIME / "src_windows"
BROKEN = C.RUNTIME / "broken"
REVIEW = C.BENCH_EV / "review"
SHEETS = C.BENCH_EV / "sheets"
CROPS = C.BENCH_EV / "crops"

SPEC_BASE = {"expected_frames": 120, "pts_duration": 4.0,
             "video": {"codec": "h264", "width": 640, "height": 360, "pix_fmt": "yuv420p"},
             "audio": {"codec": "aac", "sample_rate": 44100, "channels": 2},
             "audio_optional": True, "min_change_mae": 2.0, "max_identical_run": 2,
             "pairing_radius": 5, "pairing_min_fraction": 0.98, "pairing_margin_floor": 0.01,
             "window_start_frame": 0, "window_frame_count": 120}


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def win_map():
    fx = C.load_fixture()
    out = []
    for w in fx["windows"]:
        tag = w.get("annotation_tag")
        out.append({"window_id": w["window_id"], "tag": tag, "start_frame": w["start_frame"],
                    "end_frame_exclusive": w["end_frame_exclusive"], "frame_count": w.get("frame_count"),
                    "t0_s": round(w["start_frame"] / 30.0, 6),
                    "duration_s": round((w["end_frame_exclusive"] - w["start_frame"]) / 30.0, 6),
                    "classes": w.get("classes"), "holdout": w.get("holdout"),
                    "clip": C.PROP_CLIPS / ("%s_4s.mp4" % tag),
                    "extract": SRC_EXTRACTS / ("%s_src.mp4" % tag)})
    return fx, out


# --------------------------------------------------------------------------- #

def step_golden():
    log("golden: fixture freeze hash + source film + per-window PTS contract")
    fx, wins = win_map()
    rec = {"step": "golden_fixture_check", "raw_dir": "read-only",
           "findings_ignored_files": ["REVIEW_AND_DECISION.md F02/F03/F04 are the failure modes this harness must not reproduce"]}
    rec["fixture_path"] = str(C.GOLDEN_FIXTURE)
    rec["fixture_bytes"] = C.GOLDEN_FIXTURE.stat().st_size
    rec["fixture_sha256"] = C.sha256_file(C.GOLDEN_FIXTURE)
    rec["fixture_freeze_hash_recomputed"] = C.fixture_freeze_hash(fx)
    rec["fixture_freeze_hash_declared"] = C.FIXTURE_FREEZE_SHA
    rec["fixture_freeze_hash_match"] = rec["fixture_freeze_hash_recomputed"] == C.FIXTURE_FREEZE_SHA
    rec["fixture_declared_assertions"] = fx["assertions"]

    film = C.REF_FILM
    rec["source_film"] = {"path": str(film), "present": film.exists()}
    if film.exists():
        rec["source_film"]["size_bytes"] = film.stat().st_size
        rec["source_film"]["sha256"] = C.sha256_file(film)
        rec["source_film"]["sha256_matches_pin"] = rec["source_film"]["sha256"] == C.REF_FILM_SHA
        rec["source_film"]["bytes_match_pin"] = rec["source_film"]["size_bytes"] == C.REF_FILM_BYTES
        rec["source_film"]["probe"] = P.probe_full(film, count_frames=False)
    rec["windows"] = []
    for w in wins:
        pc = P.pts_contract(film, w["t0_s"], w["duration_s"],
                            window_start_frame=w["start_frame"], window_frame_count=w["frame_count"])
        rec["windows"].append({"window_id": w["window_id"], "tag": w["tag"], "start_frame": w["start_frame"],
                               "t0_s": w["t0_s"], "duration_s": w["duration_s"],
                               "pts_ok": pc["ok"], "sampled_frames": pc["sampled_frames"],
                               "seek_landed_on_frame": pc["seek_landed_on_frame"],
                               "window_frames_all_present": not pc["violations"]["R4_window_frames_present_and_contiguous"],
                               "first_pts": pc["first_pts"], "last_pts": pc["last_pts"],
                               "violations": {k: len(v) for k, v in pc["violations"].items()},
                               "violation_samples": {k: v[:3] for k, v in pc["violations"].items() if v}})
    rec["pts_contract_ok_all_windows"] = all(x["pts_ok"] for x in rec["windows"])
    rec["audio_facts_film"] = P.audio_facts(film)
    C.write_json(RAW / "golden_fixture_check.json", rec)
    return rec


def step_extract():
    log("extract: 7 source windows -> runtime/bench/src_windows (film stays read-only)")
    fx, wins = win_map()
    out = {"step": "source_window_extracts", "extracts": []}
    for w in wins:
        dst = Path(w["extract"])
        C.ensure(dst.parent)
        C.run(["ffmpeg", "-y", "-v", "error", "-ss", str(w["t0_s"]), "-i", str(C.REF_FILM),
               "-frames:v", str(w["frame_count"]), "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", str(dst)],
              label="extract source window %s" % w["tag"])
        f = P.probe_full(dst)
        # SELF-CHECK of the baseline: does extract frame 0 really equal film frame start_frame?
        # (if the extract were off by one frame, every before/after comparison would be shifted)
        anchor = {"start_frame": w["start_frame"], "candidates": {}}
        ex0 = CMP.frames_gray(dst, None, None, 1)
        best = None
        for off in (-1, 0, 1):
            fid = w["start_frame"] + off
            tmp = SRC_EXTRACTS / ("_anchor_%s_f%d.png" % (w["tag"], fid))
            C.run(["ffmpeg", "-y", "-v", "error", "-ss", "%.6f" % (fid / 30.0), "-i", str(C.REF_FILM),
                   "-frames:v", "1", str(tmp)], label="anchor frame %s f%d" % (w["tag"], fid))
            a = CMP.frames_gray(tmp, None, None, 1)
            if len(a) and len(ex0):
                v = round(float(abs(ex0[0].astype("int16") - a[0].astype("int16")).mean()), 4)
            else:
                v = None
            anchor["candidates"][str(off)] = v
            if v is not None and (best is None or v < best[1]):
                best = (off, v)
            try:
                tmp.unlink()
            except OSError:
                pass
        anchor["best_offset"] = best[0] if best else None
        anchor["best_mae"] = best[1] if best else None
        vals = [v for v in anchor["candidates"].values() if v is not None]
        spread = round(max(vals) - min(vals), 4) if vals else None
        anchor["spread"] = spread
        anchor["resolvable"] = bool(spread is not None and spread >= 0.01)
        anchor["extract_frame0_is_window_start"] = bool(anchor["resolvable"] and best and best[0] == 0) if anchor["resolvable"] else None
        out["extracts"].append({"window_id": w["window_id"], "tag": w["tag"], "path": str(dst),
                                "size_bytes": dst.stat().st_size if dst.exists() else None,
                                "decoded_frames": (f.get("decoded") or {}).get("nb_read_frames"),
                                "duration_s": (f.get("video") or {}).get("duration_s"),
                                "anchor_check": anchor,
                                "notes": "ffmpeg -ss before -i (frame-accurate decode-and-discard), re-encoded for comparison only; film bytes untouched"})
    C.write_json(RAW / "source_window_extracts.json", out)
    return out


def cut_offsets(extract):
    arr = CMP.frames_gray(extract, None, 4.0)
    return A._cuts(arr), arr


def step_propagate():
    log("propagate: probe + assertions + alignment facts on frozen clips (read-only)")
    fx, wins = win_map()
    out = {"step": "propagate_dryrun", "clips": [], "assembled": None}
    for w in wins:
        clip = Path(w["clip"])
        ex = Path(w["extract"])
        if not clip.exists():
            out["clips"].append({"window_id": w["window_id"], "tag": w["tag"], "clip": str(clip), "present": False,
                                 "error": "clip missing on disk"})
            continue
        spec = dict(SPEC_BASE)
        spec["source_clip"] = ex
        if w["start_frame"] is not None:
            spec["pts_t0"] = 0.0
        facts = P.probe_full(clip)
        ev = A.evaluate(clip, spec)
        align = CMP.align_report(clip, ex, None, 4.0)
        src_cuts, src_arr = cut_offsets(ex)
        rec = {"window_id": w["window_id"], "tag": w["tag"], "clip": str(clip),
               "clip_size_bytes": clip.stat().st_size, "facts": facts,
               "assertions": ev["assertions"], "technical_verdict": ev["derived"]["technical_verdict"],
               "alignment": align, "source_cut_offsets": src_cuts,
               "spec": {k: (str(v) if isinstance(v, Path) else v) for k, v in spec.items()}}
        out["clips"].append(rec)
        C.write_json(RAW / "propagate_dryrun.partial.json", out)
        log("  %s: %s" % (w["tag"], ev["derived"]["technical_verdict"]))
    if C.PROP_ASSEMBLED_MP4.exists():
        spec = dict(SPEC_BASE)
        spec.update({"expected_frames": 840, "pts_duration": 28.0, "min_change_mae": None,
                     "source_clip": None, "audio_optional": True,
                     "window_frame_count": 840})
        facts = P.probe_full(C.PROP_ASSEMBLED_MP4)
        ev = A.evaluate(C.PROP_ASSEMBLED_MP4, spec)
        out["assembled"] = {"path": str(C.PROP_ASSEMBLED_MP4), "size_bytes": C.PROP_ASSEMBLED_MP4.stat().st_size,
                            "facts": facts, "assertions": ev["assertions"],
                            "technical_verdict": ev["derived"]["technical_verdict"],
                            "sidecar_audio": str(C.PROP_ASSEMBLED / "assembled_audio.m4a"),
                            "sidecar_audio_present": (C.PROP_ASSEMBLED / "assembled_audio.m4a").exists()}
    C.write_json(RAW / "propagate_dryrun.json", out)
    partial = RAW / "propagate_dryrun.partial.json"   # incremental-evidence scratch file
    if partial.exists():
        partial.unlink()
    return out


def step_stills():
    log("stills: COMFY R4 calibration PNGs vs frozen GOLDEN keyframe (diagnostic only)")
    ref = C.GOLDEN / "keyframes/BOOK/keyframe_f1650.png"
    from PIL import Image
    out = {"step": "comfy_calibration_stills", "reference": str(ref), "stills": [],
           "note": "PSNR/entropy/LUT distance vs the source are DIAGNOSTICS (reconstruction), never a semantic-quality pass (GATE_VOCAB.md)"}

    def stats(p):
        im = Image.open(p)
        a = np.asarray(im.convert("RGB")).astype(np.float64)
        g = np.asarray(im.convert("L")).astype(np.float64)
        hist = np.bincount(g.astype(np.uint8).ravel(), minlength=256).astype(np.float64)
        pr = hist / hist.sum()
        ent = float(-(pr[pr > 0] * np.log2(pr[pr > 0])).sum())
        return {"size_bytes": Path(p).stat().st_size, "width": im.width, "height": im.height,
                "mode": im.mode, "per_channel_std": [round(float(a[:, :, i].std()), 4) for i in range(3)],
                "unique_colours": int(len(np.unique(a.reshape(-1, 3), axis=0))),
                "luma_entropy_bits": round(ent, 5),
                "luma_mean": round(float(g.mean()), 4), "luma_std": round(float(g.std()), 4)}, a

    ref_s, ref_a = stats(ref)
    out["reference_stats"] = ref_s
    for p in sorted(C.COMFY_CALIB_BOOK.glob("*.png")):
        s, a = stats(p)
        if a.shape == ref_a.shape:
            mse = float(((a - ref_a) ** 2).mean())
            psnr = None if mse == 0 else round(10 * np.log10((255.0 ** 2) / mse), 4)
        else:
            psnr = None
        out["stills"].append({"path": str(p), "name": p.name, **{k: v for k, v in s.items() if k != "a"},
                              "psnr_vs_source_keyframe_db": psnr,
                              "diagnostic_only": True})
    C.write_json(RAW / "comfy_calibration_stills.json", out)
    return out


def step_negatives():
    log("negatives: build broken inputs + prove each assertion FAILS on its control")
    fx, wins = win_map()
    tag2 = {w["tag"]: w for w in wins}
    ex = Path(tag2["BOOK"]["extract"])
    overrides = {"cut_timeline": Path(tag2["CUT_660"]["extract"]),
                 "frame_pairing": Path(tag2["TURN_795"]["extract"])}
    spec = dict(SPEC_BASE)
    spec["source_clip"] = ex
    res = A.run_negative_controls(ex, BROKEN, spec, overrides)
    out = {"step": "negative_controls", "default_base_input": str(ex),
           "control_on_broken_input_ok": "the control proves non-vacuity only when the assertion returns FAIL on the broken input",
           "base_overrides": {k: str(v) for k, v in overrides.items()},
           "results": res}
    C.write_json(RAW / "negative_controls.json", out)
    for r in res:
        log("  %-24s control=%-14s verdict_on_broken=%-12s proved=%s" % (r["assertion"], r["control"],
                                                                        r["assertion_verdict_on_broken_input"],
                                                                        r["control_proves_non_vacuity"]))
    return out


def step_sheets():
    log("sheets: contact sheets, crop strips, 1x/0.5x review copies")
    fx, wins = win_map()
    tag2 = {w["tag"]: w for w in wins}
    art = {"step": "review_artifacts", "items": [], "ready_for_human": []}

    def add(kind, p, note):
        p = Path(p)
        art["items"].append({"kind": kind, "path": str(p), "exists": p.exists(),
                             "size_bytes": p.stat().st_size if p.exists() else None, "note": note})

    for tag in ("BOOK", "CUT_660", "OCC_14768"):
        w = tag2[tag]
        cl, ex = Path(w["clip"]), Path(w["extract"])
        if ex.exists():
            add("sheet_before", S.contact_sheet(ex, SHEETS / ("%s_before_1fps_4x4.png" % tag), fps=4, tile="4x4"),
                "source window contact sheet (BEFORE)")
        if cl.exists():
            add("sheet_after", S.contact_sheet(cl, SHEETS / ("%s_after_1fps_4x4.png" % tag), fps=4, tile="4x4"),
                "frozen candidate contact sheet (AFTER)")
    # grip strip: centre crop over man+hands+book at the BOOK anchors
    wb = tag2["BOOK"]
    for side, src in (("before", Path(wb["extract"])), ("after", Path(wb["clip"]))):
        if src.exists():
            add("crop_grip_%s" % side,
                S.crop_strip(src, CROPS / ("BOOK_grip_%s_centre_320x180.png" % side),
                             "320:180:160:90", scale="320:180", t0=0, duration=4.0, fps=4, tile="4x4"),
                "centre crop (hands+book) at anchors 1650/1665/1680/1695/1710/1725/1740/1755 -> 2 fps pairs; VISUAL row")
    # cut strip around the measured cut offset in CUT_660
    wc = tag2["CUT_660"]
    if Path(wc["extract"]).exists():
        cuts, _ = cut_offsets(Path(wc["extract"]))
        if cuts:
            c0 = cuts[0]
            t0 = max(0.0, (c0 - 15) / 30.0)
            for side, src in (("before", Path(wc["extract"])), ("after", Path(wc["clip"]))):
                if src.exists():
                    add("crop_cut_%s" % side,
                        S.crop_strip(src, CROPS / ("CUT_660_cut_%s_centre_320x180.png" % side),
                                     "320:180:160:90", scale="320:180", t0=t0, duration=1.0, fps=10, tile="5x2"),
                        "cut boundary frame %d of the source window (+-15 frames), centre crop; VISUAL row 7" % c0)
            art["cut_measurement"] = {"window": "CUT_660", "source_cut_frame_offsets": cuts}
    # playback deliverables
    for tag in ("BOOK",):
        w = tag2[tag]
        for side, src in (("before", Path(w["extract"])), ("after", Path(w["clip"]))):
            if src.exists():
                for sp, label in ((1.0, "1x"), (0.5, "0p5x")):
                    add("review_%s" % label, S.review_copy(src, REVIEW / ("%s_%s_%s.mp4" % (tag, side, label)), speed=sp),
                        "full 4 s review copy at %s playback, audio retained" % label)
    if C.PROP_ASSEMBLED_MP4.exists():
        for sp, label in ((1.0, "1x"), (0.5, "0p5x")):
            add("review_28s_%s" % label, S.review_copy(C.PROP_ASSEMBLED_MP4,
                                                       REVIEW / ("PROPAGATE_assembled_28s_%s.mp4" % label), speed=sp),
                "full 28 s dry-run review copy at %s playback (PROPAGATE reconstruction baseline)" % label)
    # visual calibration inputs: deliberately broken candidates the REVIEWER must reject.
    # (machine verdicts for these live in section 4; these files are for the human's own eyes)
    vcal = C.ensure(C.BENCH_EV / "review" / "vcal")
    wb = tag2["BOOK"]
    if Path(wb["clip"]).exists():
        hands = vcal / "VCAL_hands_region_removed_BOOK_after.mp4"
        C.run(["ffmpeg", "-y", "-v", "error", "-i", str(wb["clip"]),
               "-vf", "drawbox=x=120:y=180:w=400:h=160:color=black:t=fill", *VENC, "-c:a", "copy", str(hands)],
              label="build vcal hands-removed")
        add("vcal", hands, "REVIEWER CALIBRATION: hand/book region blacked out - a reviewer who defends row 1/2 must call this FAIL")
    if C.RUNTIME.joinpath("broken", "broken_source_copy.mp4").exists():
        cp = vcal / "VCAL_source_copy_BOOK_after.mp4"
        shutil.copyfile(C.RUNTIME / "broken" / "broken_source_copy.mp4", cp)
        add("vcal", cp, "REVIEWER CALIBRATION: byte copy of the source window - a reviewer who defends row 5 must call this FAIL")
    cal = vcal / "README.txt"
    cal.write_text(
        "Visual calibration inputs for the human reviewer.\n"
        "These are deliberately broken and MUST be rejected:\n"
        "  VCAL_hands_region_removed_BOOK_after.mp4 -> rows 1 and 2 (character/hands present, hands attached) FAIL.\n"
        "  VCAL_source_copy_BOOK_after.mp4          -> row 5 (props/background changed) FAIL.\n"
        "If a reviewer passes either file, that reviewer's other PASS answers are not admissible.\n"
        "Row-by-row verdict forms: see CHECKLIST.md / GATE_VOCAB.md.\n", encoding="utf-8")
    art["ready_for_human"] = [i["path"] for i in art["items"] if i["exists"] and i["kind"].startswith(("sheet", "crop", "review", "vcal"))]
    C.write_json(RAW / "review_artifacts.json", art)
    return art


def step_report():
    log("report: assembling BENCH/REPORT.md from the measured raw artefacts")
    def rd(name, default=None):
        p = RAW / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    golden = rd("golden_fixture_check.json", {})
    prop = rd("propagate_dryrun.json", {"clips": []})
    neg = rd("negative_controls.json", {"results": []})
    stills = rd("comfy_calibration_stills.json", {"stills": []})
    art = rd("review_artifacts.json", {"items": []})
    ext = rd("source_window_extracts.json", {"extracts": []})

    L = []
    L.append("# MF-V1-BENCH - dry-run report on FROZEN artifacts (wave 1, CPU only)\n")
    L.append("Task MF-V1-BENCH. Harness: `experiments/mf_reskin_v1/bench/` (probe.py, compare.py, "
             "assertions.py, sheet.py, run_dryrun.py) + CHECKLIST.md / GATE_VOCAB.md / EVAL_PLAN.md.\n")
    L.append("No model, no GPU, no network, no render. Nothing under another task's evidence root was "
             "written, re-encoded or re-tuned. All verdict vocabulary: PASS / FAIL / UNKNOWN / "
             "NOT_REVIEWED / NOT_APPLICABLE (GATE_VOCAB.md).\n")

    # ---- section 0: what was measured, and which rows FAILED ----
    L.append("\n## 0. Dry-run in one screen\n")
    fail_rows, unm_rows = [], []
    for c in prop.get("clips", []):
        for r in c.get("assertions", []):
            if r["verdict"] == "FAIL":
                fail_rows.append((c.get("tag"), r))
            elif r["verdict"] == "UNMEASURED":
                unm_rows.append((c.get("tag"), r))
    L.append("Measured on FROZEN inputs: 7 clips x 120 frames (4.000 s @30fps) + the assembled 840-frame/28 s set. "
             "%d assertion verdicts are FAIL and %d are UNMEASURED; nothing was re-tuned to make them pass.\n"
             % (len(fail_rows), len(unm_rows)))
    L.append("| clip | failing assertion | measured |")
    L.append("|---|---|---|")
    for tag, r in fail_rows:
        L.append("| %s | %s | %s |" % (tag, r["assertion"], json.dumps(r["measured"], ensure_ascii=False)[:260]))
    if not fail_rows:
        L.append("| - | none | - |")
    L.append("\nUNMEASURED (kept, not laundered into PASS):")
    for tag, r in unm_rows:
        reason = (r["measured"] or {}).get("verdict_reason") if isinstance(r["measured"], dict) else None
        L.append("- %s / %s: %s" % (tag, r["assertion"], reason or (json.dumps(r["measured"], ensure_ascii=False)[:160] if r["measured"] else "no measurement produced")))
    L.append("\nRows 1-4 and 6 of CHECKLIST.md are **VISUAL_NOT_REVIEWED**: this route has no vision. "
             "The harness cannot and does not mark anything quality-accepted; it produces the crops/strips/review copies "
             "a human must watch (section 6).\n")

    L.append("\n## 1. What the dry-run actually measured\n")
    L.append("- Fixture `GOLDEN_FIXTURE.json`: %s bytes, sha256 `%s`" % (golden.get("fixture_bytes"), golden.get("fixture_sha256")))
    L.append("- Fixture freeze hash recomputed: `%s` vs declared `%s` -> **%s**" % (
        golden.get("fixture_freeze_hash_recomputed"), golden.get("fixture_freeze_hash_declared"),
        "MATCH" if golden.get("fixture_freeze_hash_match") else "MISMATCH"))
    sf = golden.get("source_film", {})
    L.append("- Source film (read-only): %s bytes, sha256 `%s`, pin match=%s" % (
        sf.get("size_bytes"), sf.get("sha256"), sf.get("sha256_matches_pin")))
    pw = golden.get("windows", [])
    L.append("- PTS contract on the frozen timeline, %d/7 windows checked (`pts = frame_id*512`, tb 1/15360, `t = frame_id/30`): "
             "**%s**" % (len(pw), "ALL 7 PASS" if golden.get("pts_contract_ok_all_windows") else "FAILURES PRESENT"))
    for w in pw:
        L.append("  - %s f%s..: sampled=%s first_pts=%s last_pts=%s violations=%s" % (
            w["window_id"], w["start_frame"], w["sampled_frames"], w["first_pts"], w["last_pts"],
            {k: v for k, v in w["violations"].items() if v} or "none"))
    af = golden.get("audio_facts_film", {})
    L.append("- Source audio: codec=%s %s Hz %s ch, bit_rate=%s, duration=%s s" % (
        af.get("codec"), af.get("sample_rate"), af.get("channels"), af.get("bit_rate"), af.get("duration_s")))

    L.append("\n## 2. Frozen candidate clips (PROPAGATE, read-only) - measured\n")
    L.append("| clip | decoded frames | duration s | avg/r fps | audio | technical verdict |")
    L.append("|---|---|---|---|---|---|")
    for c in prop.get("clips", []):
        v = (c.get("facts") or {}).get("video") or {}
        a = (c.get("facts") or {}).get("audio") or {}
        d = (c.get("facts") or {}).get("decoded") or {}
        L.append("| %s | %s | %s | %s / %s | %s | %s |" % (
            c.get("tag"), d.get("nb_read_frames"), v.get("duration_s"), v.get("avg_frame_rate"),
            v.get("r_frame_rate"),
            ("%s %sHz %sch" % (a.get("codec"), a.get("sample_rate"), a.get("channels"))) if a.get("present") else "absent",
            c.get("technical_verdict")))
    asm = prop.get("assembled")
    if asm:
        av = (asm.get("facts") or {}).get("video") or {}
        ad = (asm.get("facts") or {}).get("decoded") or {}
        L.append("\nAssembled 28 s dry-run set `%s`: decoded frames=%s duration_s=%s -> **%s**; sidecar audio `assembled_audio.m4a` present=%s" % (
            asm["path"], ad.get("nb_read_frames"), av.get("duration_s"), asm.get("technical_verdict"),
            asm.get("sidecar_audio_present")))

    L.append("\n## 2b. Baseline self-check: source-window extract frame 0 vs film frame\n")
    L.append("| window | start frame | |delta| to f(start-1) | f(start) | f(start+1) | best offset | extract aligned |")
    L.append("|---|---|---|---|---|---|---|---|")
    for e in ext.get("extracts", []):
        a = e.get("anchor_check", {})
        c = a.get("candidates", {})
        L.append("| %s | %s | %s | %s | %s | %s (spread %s, resolvable=%s) | %s |" % (
            e["tag"], a.get("start_frame"), c.get("-1"), c.get("0"), c.get("1"),
            a.get("best_offset"), a.get("spread"), a.get("resolvable"),
            a.get("extract_frame0_is_window_start")))

    L.append("\n## 3. Row-by-row verdicts (frozen artifacts)\n")
    L.append("| row | frozen candidate result | measured | disposition |")
    L.append("|---|---|---|---|")
    agg = {}
    for c in prop.get("clips", []):
        if "assertions" not in c:
            continue
        for r in c["assertions"]:
            agg.setdefault(r["assertion"], []).append(r["verdict"])
    for name, verdicts in sorted(agg.items()):
        row = A.TECHNICAL_ROWS.get(name, "-")
        L.append("| %s (harness row) | %s | %s | %s |" % (
            name, "/".join(verdicts),
            json.dumps(next((r["measured"] for c in prop.get("clips", []) if "assertions" in c
                             for r in c["assertions"] if r["assertion"] == name), {}), ensure_ascii=False)[:220],
            "TECHNICAL_PASS" if all(v in ("PASS", "NOT_APPLICABLE") for v in verdicts) else "TECHNICAL_FAIL"))
    L.append("\nRows 1-4 and 6 are `VISUAL_NOT_REVIEWED` by construction on this route (no vision): "
             "character/hands presence, hand attachment, grip timing, second-person occlusion, identity/style flip. "
             "Row 7 has measured proxies (`non_degenerate_frames`, `not_frozen`, `cut_timeline`) but the semantic "
             "blur/flicker/ghosting judgement stays `VISUAL_NOT_REVIEWED`. Row 8 is measured.\n")

    L.append("\n## 4. Negative controls (an assertion without a failing control is not evidence)\n")
    L.append("| assertion | control | base window | verdict of assertion on broken input | non-vacuous |")
    L.append("|---|---|---|---|---|")
    for r in neg.get("results", []):
        L.append("| %s | %s | %s | %s | %s |" % (r["assertion"], r["control"],
                                                  Path(r.get("base_input", "")).name,
                                                  r["assertion_verdict_on_broken_input"],
                                                  r["control_proves_non_vacuity"]))

    L.append("\n## 5. COMFY R4 calibration stills (diagnostic only)\n")
    L.append("| still | px | luma_std | unique colours | luma entropy (bits) | PSNR vs source keyframe |")
    L.append("|---|---|---|---|---|---|")
    for s in stills.get("stills", []):
        L.append("| %s | %sx%s | %s | %s | %s | %s dB |" % (s["name"], s["width"], s["height"], s["luma_std"],
                                                            s["unique_colours"], s["luma_entropy_bits"],
                                                            s["psnr_vs_source_keyframe_db"]))
    L.append("\nThese numbers are diagnostics (reconstruction distance / palette statistics). They are "
             "**not** a reskin verdict and cannot be used as one (GATE_VOCAB.md).\n")

    L.append("\n## 6. Review copies produced for a human\n")
    for i in art.get("items", []):
        if i.get("exists") and i["kind"].startswith(("sheet", "crop", "review", "vcal")):
            L.append("- `%s` (%s bytes) - %s" % (i["path"], i["size_bytes"], i["note"]))

    L.append("\n## 7. Reproduce the whole dry-run\n")
    L.append("```\ncd C:/Users/Admin/Documents/Codex/work/mfv1/wt-bench\n"
             "python experiments/mf_reskin_v1/bench/run_dryrun.py "
             "--steps golden,extract,propagate,stills,negatives,sheets,report\n```\n")
    L.append("Command transcript (argv/cwd/exit/duration) for every ffmpeg/ffprobe call: "
             "`raw/cmd_transcript.jsonl`. Command count in this run: %d, failures: %d.\n"
             % (len(C.LEDGER), sum(1 for x in C.LEDGER if not x["ok"])))

    L.append("\n## 8. What this harness deliberately does NOT do\n")
    L.append("- no image-scoring / vision / segmentation model, no metric platform, no benchmark suite;\n"
             "- no PROPAGATE metric reused as truth (its contact logic produced F02): every assertion here carries its\n"
             "  own negative control (section 4) and the frame-correspondence test is re-derived on the whole-clip\n"
             "  |delta|-vs-offset curve, whose discriminating power is measured and reported (a flat curve is UNMEASURED);\n"
             "- no per-thumbnail or per-export test farm: encoding/thumbnail helpers are built once (sheet.py);\n"
             "- no re-render, no re-encode, no re-freeze of any artifact under another task's evidence root;\n"
             "- no PASS on a row whose input is present but whose measurement is empty (F02 lesson, GATE_VOCAB.md).\n")
    L.append("\n## 9. Request to the human reviewer\n")
    L.append("Please watch the review copies in section 6 at 1x and 0.5x and answer rows 1-4, 6 and the semantic part of\n"
             "row 7 of CHECKLIST.md against the frozen PROPAGATE baseline (reconstruction, not a reskin):\n"
             "character + both hands present; hands attached to the body (no detached/duplicated hand); book grip held at\n"
             "the anchor frames; second person still present and not occluded; identity/style stable across the clip;\n"
             "no abnormal blur/flicker/ghosting at the measured cut frames. Until a viewer answers, those rows stay\n"
             "**NOT_REVIEWED** - no technical green here can substitute for them.\n")
    (C.BENCH_EV / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    log("wrote %s" % (C.BENCH_EV / "REPORT.md"))
    return {"report": str(C.BENCH_EV / "REPORT.md")}


CAND = {"path": None, "source": None, "window": None}


def step_candidate():
    """Evaluate ONE new candidate against its source window (wave-2 entry point).

    python run_dryrun.py --steps candidate --candidate <out.mp4> \
        --source-clip <src_window.mp4> [--window-tag BOOK] [--expected-frames 120]
    Writes raw/candidate_<tag>.json and prints the row table. Never touches frozen inputs.
    """
    log("candidate: %s" % CAND["path"])
    cand = Path(CAND["path"])
    src = Path(CAND["source"]) if CAND["source"] else None
    tag = CAND["window"] or cand.stem
    if not cand.exists():
        raise SystemExit("candidate not found: %s" % cand)
    if src is not None and not src.exists():
        raise SystemExit("source clip not found: %s" % src)
    n = CAND.get("expected_frames") or 120
    spec = dict(SPEC_BASE)
    spec.update({"expected_frames": n, "pts_duration": round(n / 30.0, 6), "window_frame_count": n,
                 "source_clip": src})
    facts = P.probe_full(cand)
    ev = A.evaluate(cand, spec)
    rec = {"step": "candidate", "candidate": str(cand), "source_clip": str(src) if src else None,
           "window_tag": tag, "facts": facts, "assertions": ev["assertions"],
           "technical_verdict": ev["derived"]["technical_verdict"],
           "visual_verdict": "VISUAL_NOT_REVIEWED",
           "note": "TECHNICAL_PASS is not a quality verdict: rows 1-4, 6 and the semantic part of row 7 need a viewer"}
    if src is not None:
        rec["alignment"] = CMP.align_report(cand, src, None, spec["pts_duration"])
    C.write_json(RAW / ("candidate_%s.json" % tag), rec)
    for a in ev["assertions"]:
        print("  %-24s %-13s %s" % (a["assertion"], a["verdict"],
                                    (a["measured"] or {}).get("verdict_reason", json.dumps(a["measured"], ensure_ascii=False)[:110])
                                    if isinstance(a["measured"], dict) else ""))
    print("  TECHNICAL=%s  VISUAL=VISUAL_NOT_REVIEWED" % ev["derived"]["technical_verdict"])
    return rec


STEPS = {"golden": step_golden, "extract": step_extract, "propagate": step_propagate,
         "candidate": step_candidate,
         "stills": step_stills, "negatives": step_negatives, "sheets": step_sheets, "report": step_report}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default="golden,extract,propagate,stills,negatives,sheets,report")
    ap.add_argument("--candidate", default=None, help="candidate mp4 for --steps candidate")
    ap.add_argument("--source-clip", default=None, help="source window extract for --steps candidate")
    ap.add_argument("--window-tag", default=None)
    ap.add_argument("--expected-frames", type=int, default=None)
    a = ap.parse_args(argv)
    CAND.update({"path": a.candidate, "source": a.source_clip, "window": a.window_tag,
                 "expected_frames": a.expected_frames})
    for d in (RAW, SRC_EXTRACTS, BROKEN, REVIEW, SHEETS, CROPS):
        C.ensure(d)
    t0 = time.time()
    for name in a.steps.split(","):
        name = name.strip()
        if not name:
            continue
        if name not in STEPS:
            print("unknown step", name)
            return 2
        STEPS[name]()
    C.flush_ledger()
    print("TOTAL %.1f s; commands=%d" % (time.time() - t0, len(C.LEDGER)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
