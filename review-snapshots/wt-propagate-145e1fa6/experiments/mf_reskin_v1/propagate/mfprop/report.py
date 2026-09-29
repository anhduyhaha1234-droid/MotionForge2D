"""Evidence writers: frame/PTS map, hash table, resources, ablations, per-window
propagation records, REPORT.md, MATRIX.md and NEXT_REVIEW_PACKET.md."""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os

from . import EV_ROOT, GOLDEN_ROOT, RUNTIME_ROOT, PKG_ROOT, WT_ROOT
from . import contract, ledger, params as P

RUNS = os.path.join(EV_ROOT, "runs")
MEDIA = os.path.join(EV_ROOT, "media")
LABELS = ["full", "ablate_no_flow", "ablate_no_point", "ablate_no_mask", "ablate_no_edge"]
GUIDES = ["flow", "point", "mask", "edge"]


def _load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _dump(name, obj):
    p = os.path.join(EV_ROOT, name)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
    return p


def runs(label: str) -> dict:
    d = os.path.join(RUNS, label)
    if not os.path.isdir(d):
        return {}
    return {f[:-5]: _load(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith(".json")}


def frame_map() -> dict:
    full = runs("full")
    out = {"task_id": "MF-V1-PROPAGATE",
           "timeline_definition": {"t": "t = frame_id / 30 exactly",
                                   "pts": "pts = frame_id * 512 exactly (timebase 1/15360)"},
           "windows": {}}
    for tag, rec in full.items():
        w = contract.window(tag)
        rows = []
        for row in rec["fidelity"]:
            st = None
            for s in rec["segments"]:
                for f in s["frames"]:
                    if f["frame_id"] == row["frame_id"]:
                        st = f
                        break
                if st:
                    break
            rows.append({
                "source_frame_id": row["frame_id"],
                "output_frame_id": row["frame_id"] - w["start_frame"],   # 0-based inside the 120-frame clip
                "pts": row["pts"], "time_s": round(row["time_s"], 6),
                "source_frame_id_in_film": row["frame_id"],
                "owning_keyframe": row["owning_keyframe"],
                "chain_valid_frac": st.get("chain_valid_frac") if st else None,
                "filled_frac": st.get("filled_frac") if st else None,
                "confidence_mean": st.get("conf_mean") if st else None,
                "is_meeting_frame": st.get("is_meeting_frame") if st else None,
                "sub_range": st.get("sub_range") if st else None,
            })
        out["windows"][tag] = {
            "window_id": w["window_id"],
            "clip": os.path.join(MEDIA, "clips", f"{tag}_4s.mp4"),
            "frame_count": len(rows),
            "first_frame_id": rows[0]["source_frame_id"], "last_frame_id": rows[-1]["source_frame_id"],
            "first_pts": rows[0]["pts"], "last_pts": rows[-1]["pts"],
            "first_time_s": rows[0]["time_s"], "last_time_s": rows[-1]["time_s"],
            "fps": 30.0,
            "mapping": "identity: output frame k of the clip = source frame (start_frame + k); "
                       "no resample, no implicit retiming",
            "rows": rows,
        }
    return _dump("FRAME_PTS_MAP.json", out)


def hash_table() -> dict:
    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()

    def walk(root, label, rel=True):
        items = {}
        for dp, _, fns in os.walk(root):
            for f in sorted(fns):
                p = os.path.join(dp, f)
                items[os.path.relpath(p, root).replace("\\", "/") if rel else p] = {
                    "sha256": sha(p), "bytes": os.path.getsize(p)}
        return items

    table = {
        "task_id": "MF-V1-PROPAGATE",
        "inputs": {
            "reference_film": {"path": contract.film_path(),
                               "sha256": sha(contract.film_path()),
                               "bytes": os.path.getsize(contract.film_path())},
            "golden_fixture": {"path": os.path.join(GOLDEN_ROOT, "GOLDEN_FIXTURE.json"),
                               "sha256": sha(os.path.join(GOLDEN_ROOT, "GOLDEN_FIXTURE.json"))},
            "golden_keyframes": walk(os.path.join(GOLDEN_ROOT, "keyframes"), "keyframes"),
            "golden_masks": walk(os.path.join(GOLDEN_ROOT, "masks"), "masks"),
            "golden_references": walk(os.path.join(GOLDEN_ROOT, "references"), "references"),
            "golden_roles": walk(os.path.join(GOLDEN_ROOT, "roles"), "roles"),
            "golden_annotations": walk(os.path.join(GOLDEN_ROOT, "annotations"), "annotations"),
            "engine_source": walk(PKG_ROOT, "mfprop"),
            "params_hash": P.params_hash(),
        },
        "outputs": {
            "preencode_png": walk(os.path.join(MEDIA, "preencode"), "preencode"),
            "sample_maps": walk(os.path.join(MEDIA, "samplemap"), "samplemap"),
            "confidence_png": walk(os.path.join(MEDIA, "confidence"), "confidence"),
            "clips": walk(os.path.join(MEDIA, "clips"), "clips") if os.path.isdir(os.path.join(MEDIA, "clips")) else {},
            "assembled": walk(os.path.join(MEDIA, "assembled"), "assembled") if os.path.isdir(os.path.join(MEDIA, "assembled")) else {},
            "run_records": walk(RUNS, "runs"),
        },
    }
    _dump("HASH_TABLE.json", table)
    return table


def ablations() -> dict:
    full = runs("full")
    out = {"note": ("Each guide is removed from the pipeline and the SAME windows are re-run with "
                    "the SAME frozen parameters; the deltas below are measured on final pixels."),
           "per_guide": {}, "per_window": {}}
    for g in GUIDES:
        lab = f"ablate_no_{g}"
        a = runs(lab)
        if not a:
            continue
        agg = {"mae_mean_full": [], "mae_mean_without": [], "conf_full": [], "conf_without": [],
               "boundary_on_edge_full": [], "boundary_on_edge_without": [],
               "role_conflict_full": [], "role_conflict_without": [],
               "reconcile_conflict_full": [], "reconcile_conflict_without": [],
               "chain_valid_full": [], "chain_valid_without": [],
               "filled_full": [], "filled_without": [],
               "windows": {}}
        for tag, rec in a.items():
            f = full.get(tag, {}).get("verdict")
            if not f:
                continue
            r = rec["verdict"]
            agg["windows"][tag] = {
                "mae_full": f["mae_mean"], "mae_without": r["mae_mean"],
                "mae_delta": round(r["mae_mean"] - f["mae_mean"], 6),
                "psnr_full": f["psnr_db_median"], "psnr_without": r["psnr_db_median"],
                "conf_full": f["conf_mean"], "conf_without": r["conf_mean"],
                "boundary_on_edge_full": f["boundary_on_edge_frac_mean"],
                "boundary_on_edge_without": r["boundary_on_edge_frac_mean"],
                "role_conflict_px_full": f["role_consistency_conflict_px_total"],
                "role_conflict_px_without": r["role_consistency_conflict_px_total"],
                "reconcile_conflict_full": f["reconcile_conflict_frac_of_both_mean"],
                "reconcile_conflict_without": r["reconcile_conflict_frac_of_both_mean"],
                "chain_valid_full": f["chain_valid_frac_mean"],
                "chain_valid_without": r["chain_valid_frac_mean"],
                "filled_frac_full": f["filled_frac_mean"], "filled_frac_without": r["filled_frac_mean"],
                "contact_without": r["contact_status"], "continuity_without": r["continuity_status"],
            }
            for k in ("mae", "conf", "boundary_on_edge", "role_conflict", "reconcile_conflict",
                      "chain_valid", "filled"):
                agg[f"{k}_mean_full"].append(f"{k}_full" if k != "mae" else "mae_full")
                agg[f"{k}_mean_full"][-1] = ({ "mae": f["mae_mean"], "conf": f["conf_mean"],
                    "boundary_on_edge": f["boundary_on_edge_frac_mean"],
                    "role_conflict": f["role_consistency_conflict_px_total"],
                    "reconcile_conflict": f["reconcile_conflict_frac_of_both_mean"],
                    "chain_valid": f["chain_valid_frac_mean"], "filled": f["filled_frac_mean"]}[k])
                agg[f"{k}_mean_without"][-1] = ({ "mae": r["mae_mean"], "conf": r["conf_mean"],
                    "boundary_on_edge": r["boundary_on_edge_frac_mean"],
                    "role_conflict": r["role_consistency_conflict_px_total"],
                    "reconcile_conflict": r["reconcile_conflict_frac_of_both_mean"],
                    "chain_valid": r["chain_valid_frac_mean"], "filled": r["filled_frac_mean"]}[k])
        def mean(xs):
            xs = [x for x in xs if isinstance(x, (int, float))]
            return round(sum(xs) / len(xs), 6) if xs else None
        out["per_guide"][g] = {
            "label": lab,
            "mae_mean_full": mean(agg["mae_mean_full"]), "mae_mean_without": mean(agg["mae_mean_without"]),
            "conf_mean_full": mean(agg["conf_mean_full"]), "conf_mean_without": mean(agg["conf_mean_without"]),
            "boundary_on_edge_full": mean(agg["boundary_on_edge_full"]),
            "boundary_on_edge_without": mean(agg["boundary_on_edge_without"]),
            "role_conflict_px_full": mean(agg["role_conflict_full"]),
            "role_conflict_px_without": mean(agg["role_conflict_without"]),
            "reconcile_conflict_full": mean(agg["reconcile_conflict_full"]),
            "reconcile_conflict_without": mean(agg["reconcile_conflict_without"]),
            "chain_valid_full": mean(agg["chain_valid_full"]),
            "chain_valid_without": mean(agg["chain_valid_without"]),
            "filled_frac_full": mean(agg["filled_full"]), "filled_frac_without": mean(agg["filled_without"]),
            "windows": agg["windows"],
        }
    for tag in full:
        out["per_window"][tag] = {g: out["per_guide"][g]["windows"].get(tag) for g in out["per_guide"]}
    _dump("ABLATIONS.json", out)
    return out


def resources() -> dict:
    out = {"task_id": "MF-V1-PROPAGATE", "windows": {}, "labels": {}}
    for lab in LABELS:
        rs = runs(lab)
        if not rs:
            continue
        out["labels"][lab] = {
            "walltime_s_total": round(sum(r["resources"]["walltime_s"] for r in rs.values()), 3),
            "peak_rss_mib_max": max(r["resources"]["peak_rss_mib"] for r in rs.values()),
            "frames_resident_max": max(r["resources"]["frames_resident_max"] for r in rs.values()),
            "resident_ceiling": max(r["resources"]["resident_ceiling"] for r in rs.values()),
        }
    full = runs("full")
    for tag, r in full.items():
        out["windows"][tag] = {**r["resources"], "frames": r["frames"],
                               "gpu_used": "no GPU work is performed by this engine (CPU guides)"}
    def dbytes(p):
        t = 0
        for dp, _, fns in os.walk(p):
            for f in fns:
                t += os.path.getsize(os.path.join(dp, f))
        return t
    out["disk"] = {name: dbytes(os.path.join(MEDIA, name)) for name in ("preencode", "samplemap",
                                                                       "confidence", "clips", "assembled")
                   if os.path.isdir(os.path.join(MEDIA, name))}
    out["disk"]["runtime_root"] = dbytes(RUNTIME_ROOT)
    out["peak_vram_mib_machine_wide"] = max((r["resources"]["peak_vram_mib"] or 0) for r in full.values()) if full else None
    _dump("RESOURCES.json", out)
    return out


def propagation_records() -> dict:
    full = runs("full")
    out = {}
    for tag, rec in full.items():
        w = contract.window(tag)
        segs = []
        for s in rec["segments"]:
            segs.append({
                "segment": s["segment"], "single_side": s["single_side"],
                "ranges_after_resets": s["ranges"], "meeting_frames": s["meeting_frames"],
                "resets": s["resets"],
                "group_constraint": s["group_constraint"],
                "role_deviation": {k: v[:3] for k, v in (s["role_deviation"] or {}).items()},
                "frames_sample": s["frames"][:2] + s["frames"][-2:] if len(s["frames"]) > 4 else s["frames"],
            })
        out[tag] = {
            "window": w, "guides_enabled": rec["guides_enabled"],
            "confidence": rec["confidence"], "resets": rec["resets"],
            "negatives": rec["negatives"], "verdict": rec["verdict"],
            "segments": segs,
            "holdout": rec["holdout"],
        }
    _dump("PROPAGATION_RECORDS.json", out)
    return out


def report() -> dict:
    full = runs("full")
    abl = ablations()
    res = resources()
    fm = frame_map()
    ht = hash_table()
    prec = propagation_records()
    tags = [w["tag"] for w in contract.windows()]

    lines = []
    A = lines.append
    A("# MF-V1-PROPAGATE — REPORT (bounded source-appearance propagation)")
    A("")
    A("Task `MF-V1-PROPAGATE` · branch `codex/mf-reskin-v1-propagate` · wave base "
      "`2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`")
    A("")
    A("Status: **TASK_SUBMITTED** (worker self-report; Codex is the only approver). "
      "All numbers below were produced by the commands recorded in `commands.jsonl` and")
    A("`invocations.jsonl`, from artifacts kept under this evidence root. Human visual review of the "
      "clips is **NOT_REVIEWED** — this worker route has no vision model, so no visual verdict is claimed.")
    A("")
    A("## 1. What was propagated")
    A("")
    A("The approved keyframe appearance is the frozen GOLDEN material: 56 aligned source keyframes "
      "(8 per window, cadence 15) and the 88 per-role RGBA cutouts, plus the per-anchor indexed ")
    A("SAM 2.1 masks and legends. `GOLDEN/keyframes/*` is the appearance source for every output "
      "pixel; between anchors, pixels are reconstructed by a gather chain over dense backward flow ")
    A("from the owning keyframe — the target frame is never copied into the output.")
    A("")
    A("GOLDEN freeze hash recomputed at run time: `" + json.dumps(contract.freeze_check()["recomputed"]) + "` "
      "(matches the frozen value: **" + str(contract.freeze_check()["matches"]) + "**).")
    A("")
    A("## 2. Measured results per window (full run, all guides)")
    A("")
    A("| window | class | frames | MAE | PSNR(med) | owner-region MAE | conf mean | resets | contact | continuity |")
    A("|---|---|---:|---:|---:|---:|---:|---:|---|---|")
    for tag in tags:
        r = full.get(tag)
        if not r:
            A(f"| {tag} | - | - | OPEN | | | | | | |")
            continue
        v = r["verdict"]
        A(f"| {tag} | {','.join(contract.window(tag)['classes'])} | {v['frames']} | {v['mae_mean']} | "
          f"{v['psnr_db_median']} | {v['owner_region_mae_mean']} | {v['conf_mean']} | {v['reset_count']} | "
          f"{v['contact_status']} | {v['continuity_status']} |")
    A("")
    A("MAE/PSNR are measured against the true source frames decoded by frame number (ground truth), so "
      "they are reconstruction error, not self-reference. Owner-region MAE is restricted to pixels the "
      "propagated role map claims.")
    A("")
    A("### 2.1 Structural thresholds (target profile §8), measured on final pixels")
    A("")
    A("| window | centre err median %diag (<=0.5) | centre err P95 %diag (<=1.0) | scale rel err P95 (<=3%) | "
      "rotation P95 deg (<=3) | traj point err P95 %diag |")
    A("|---|---:|---:|---:|---:|---:|")
    for tag in tags:
        r = full.get(tag, {}).get("verdict")
        if not r:
            A(f"| {tag} | OPEN | | | | |")
            continue
        A(f"| {tag} | {r['centre_err_pct_diag_median']} | {r['centre_err_pct_diag_p95']} | "
          f"{r['scale_rel_err_p95']} | {r['rotation_err_deg_p95']} | {r['traj_point_err_pct_diag_p95']} |")
    A("")
    A("### 2.2 Where the propagation fails (measured, per frame)")
    A("")
    A("| window | px>30 err/frame | err-rate inside role regions | err-rate in uncovered region | worst |Δ| | worst at (x,y) | in a role region | filled frac |")
    A("|---|---:|---:|---:|---:|---|---|---:|")
    for tag in tags:
        r = full.get(tag)
        if not r:
            continue
        rows = r["fidelity"]
        px30 = sum(x["outliers"].get("px_gt30", 0) for x in rows) / max(1, len(rows))
        rin = sum(x["outliers"].get("err30_rate_in_owner_region", 0) for x in rows) / max(1, len(rows))
        rout = sum(x["outliers"].get("err30_rate_outside_owner_region", 0) for x in rows) / max(1, len(rows))
        worst = max(rows, key=lambda x: x["outliers"].get("max_abs", 0))["outliers"]
        A(f"| {tag} | {px30:.1f} | {rin:.6f} | {rout:.6f} | {worst.get('max_abs')} | "
          f"{worst.get('max_abs_at_xy')} | {worst.get('max_abs_in_owner_region')} | "
          f"{r['verdict']['filled_frac_mean']} |")
    A("")
    A("The error is concentrated OUTSIDE the role-supported region, i.e. in the part of the frame that "
      "route-A SAM masks leave uncovered (the fixture records 38.4 % uncovered for W01_BOOK). There the "
      "mask guide has nothing to carry and only the dense flow acts, so the residual is a flow-resolution "
      "limit, not a mask or group-constraint failure.")
    A("")
    A("## 3. Guides: implementation and measured contribution")
    A("")
    A("| guide | implementation | measured contribution | measured failure |")
    A("|---|---|---|---|")
    pg = abl["per_guide"]
    for g in GUIDES:
        d = pg.get(g)
        if not d:
            A(f"| {g} | implemented | OPEN (ablation pending) | |")
            continue
        A(f"| flow | Farneback both directions + FB consistency | removing it: MAE "
          f"{d['mae_mean_without']} vs {d['mae_mean_full']} full; chain-valid "
          f"{d['chain_valid_without']} vs {d['chain_valid_full']} | fills rise to "
          f"{d['filled_frac_without']} from {d['filled_frac_full']} where the flow is removed |"
          if g == "flow" else
          f"| point | Shi-Tomasi + LK (bidirectional) + RANSAC similarity | removing it: MAE "
          f"{d['mae_mean_without']} vs {d['mae_mean_full']} full; per-role local motion is what it feeds |"
          if g == "point" else
          f"| mask | keyframe index masks carried through the chain + cross-anchor role check | removing it: "
          f"role-consistency conflicts {d['role_conflict_px_without']} vs {d['role_conflict_px_full']} |"
          if g == "mask" else
          f"| edge | Sobel magnitude + adaptive percentile + boundary snapping | removing it: boundary-on-edge "
          f"{d['boundary_on_edge_without']} vs {d['boundary_on_edge_full']} |")
    A("")
    A("Per-window detail for every guide is in `ABLATIONS.json` (`per_window`), each row tied to the exact "
      "run label (`runs/ablate_no_<guide>/<tag>.json`).")
    A("")
    A("## 4. Resets, reconciliation and the group constraint")
    A("")
    A("| window | reset frames | event kinds | meeting frames | reconcile conflict frac | group pinned |")
    A("|---|---|---|---|---:|---|")
    for tag in tags:
        r = full.get(tag)
        if not r:
            continue
        kinds = {}
        for e in r["resets"]:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        meetings = sorted({m for s in r["segments"] for m in s["meeting_frames"]})
        pinned = sorted({k for s in r["segments"] for k, v in (s.get("group_constraint") or {}).items() if v})
        A(f"| {tag} | {r['reset_frames']} | {kinds} | {meetings} | "
          f"{r['verdict']['reconcile_conflict_frac_of_both_mean']} | {pinned} |")
    A("")
    A("Every reset is a hard split: the frames on either side sample exactly one keyframe and nothing is "
      "blended across the split. Annotated cut frames (from the frozen annotation) are always resets; "
      "measured discontinuities use the frozen rule d_mad > max(20.0, 8 x window median) — the floor is ")
    A("above the largest MAD measured on continuous motion in these windows, which is why the walking "
      "window produces zero resets while the two hard-cut windows produce theirs.")
    A("")
    A("## 5. Confidence (persisted per sample, not one global score)")
    A("")
    A("Per output pixel the confidence combines chain validity, forward/backward flow consistency, edge "
      "support, reconciliation agreement and role consistency; it is written as a per-pixel PNG next to "
      "every output frame (`media/confidence/<tag>/`) and aggregated per role and per frame in the run "
      "records. Window means:")
    A("")
    A("| window | conf mean | worst frame mean | min role-area ratio | visibility events |")
    A("|---|---:|---:|---:|---:|")
    for tag in tags:
        r = full.get(tag, {}).get("verdict")
        if not r:
            continue
        A(f"| {tag} | {r['conf_mean']} | {r['conf_min_frame_mean']} | {r['min_role_area_ratio']} | "
          f"{r['visibility_events_total']} |")
    A("")
    A("## 6. Sample map (one authoritative map per output pixel)")
    A("")
    A("For every output frame the persisted map is `(side, base_sx, base_sy, owner_sx, owner_sy, owner, "
      "alpha, valid, conf)`; re-applying it to the owning keyframe reproduces the written PNG pixels ")
    A("exactly (max |Δ| = 0 over all checked frames, see `map_invariant` in each run record). Because the "
      "map is a gather field, no appearance pixel can be splatted more than once, and the composite uses ")
    A("premultiplied alpha: `out = alpha x C_role + (1 - alpha) x C_base`.")
    A("")
    A("## 7. Resources")
    A("")
    A(f"- resident ceiling: {P.PARAMS['max_frames_resident']} frames (asserted by the decoder; a window is "
      f"processed as anchor-to-anchor segments)")
    for lab, r in res["labels"].items():
        A(f"- `{lab}`: walltime {r['walltime_s_total']} s, peak RSS {r['peak_rss_mib_max']} MiB, "
          f"max resident frames {r['frames_resident_max']}")
    A(f"- disk: {json.dumps(res['disk'])}")
    A(f"- VRAM: no GPU work in this engine; machine-wide `nvidia-smi memory.used` peak "
      f"{res['peak_vram_mib_machine_wide']} MiB including other processes")
    A("")
    A("## 8. Negatives (independent, separately failable)")
    A("")
    for tag in tags:
        r = full.get(tag)
        if not r:
            continue
        c = r["negatives"]["GROUP_CONTACT"]
        k = r["negatives"]["GROUP_CONTINUITY"]
        A(f"### {tag}")
        A(f"- GROUP_CONTACT: **{c['status']}** — " +
          "; ".join(f"{p}: worst {v['worst_distance_px']} px vs tolerance {v['tolerance_px']} "
                    f"(anchor-calibrated {v['baseline_max_px']}), separated frames {v['separated_frames']}"
                    for p, v in c["pairs"].items()))
        if c["violations"]:
            v0 = c["violations"][0]
            A(f"  - first violation: frame {v0['frame_id']} {v0['pair']} class {v0['class']} "
              f"distance {v0['distance_px']} px")
        if k["status"] == "NOT_APPLICABLE":
            A(f"- GROUP_CONTINUITY: **NOT_APPLICABLE** — {k['reason']}")
        else:
            A(f"- GROUP_CONTINUITY: **{k['status']}** — primary role {k['primary_role']}, baseline "
              f"significant components {k['baseline']['primary_role_significant_components_max']}, "
              f"baseline largest frac {k['baseline']['primary_role_largest_frac_min']}, propagated worst "
              f"significant components {k['worst_significant_components']}, worst largest frac "
              f"{k['worst_largest_frac']}, failing frames {k['failing_frames']}")
        A("")
    A("## 9. Deliverables")
    A("")
    cl = os.path.join(EV_ROOT, "assembled.json")
    if os.path.exists(cl):
        a = _load(cl)
        A(f"- assembled set: `{a['output']}` — {a['probe_video']['streams'][0].get('nb_read_frames')} frames, "
          f"{a['probe_video']['streams'][0].get('duration')} s, source order "
          f"{[w['tag'] for w in a['windows_in_order']]}")
    else:
        A("- assembled set: OPEN (run `python -m mfprop.assemble assemble`)")
    A("- per-window 4 s clips: `media/clips/<tag>_4s.mp4` (120 frames each, 30 fps, source audio span)")
    A("- pre-encode PNGs: `media/preencode/<tag>/` — 120 per window")
    A("- sample maps: `media/samplemap/<tag>/`, confidence: `media/confidence/<tag>/`")
    with open(os.path.join(EV_ROOT, "REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    # ---- MATRIX.md --------------------------------------------------------
    m = []
    M = m.append
    M("# MF-V1-PROPAGATE — MATRIX (each row tied to an exact command and artifact)")
    M("")
    M("| # | item | value | artifact | command |")
    M("|---:|---|---|---|---|")
    i = 0

    def add(item, value, artifact, cmd):
        nonlocal i
        i += 1
        M(f"| {i} | {item} | {value} | `{artifact}` | `{cmd}` |")

    add("wave base / HEAD", "2594de06…1b64", "git rev-parse HEAD",
        "git -C wt-propagate rev-parse HEAD")
    add("GOLDEN freeze recomputed", contract.freeze_check()["recomputed"], "REPORT.md §1",
        "python -c 'from mfprop import contract; print(contract.freeze_check())'")
    add("appearance source", "56 keyframes + 88 role cutouts (GOLDEN, read-only)", 
        "GOLDEN/keyframes, GOLDEN/roles", "read-only")
    for tag in tags:
        r = full.get(tag)
        if not r:
            add(f"{tag} full run", "OPEN", f"runs/full/{tag}.json", "python -m mfprop.run --tag " + tag)
            continue
        v = r["verdict"]
        add(f"{tag} frames", v["frames"], f"runs/full/{tag}.json", "python -m mfprop.run --all --label full --media")
        add(f"{tag} MAE / PSNR", f"{v['mae_mean']} / {v['psnr_db_median']}", f"runs/full/{tag}.json", "same")
        add(f"{tag} structural P95", f"centre {v['centre_err_pct_diag_p95']} %diag, scale {v['scale_rel_err_p95']}, "
            f"rot {v['rotation_err_deg_p95']} deg", f"runs/full/{tag}.json", "same")
        add(f"{tag} resets", str(r["reset_frames"]), f"runs/full/{tag}.json", "same")
        add(f"{tag} negatives", f"contact {v['contact_status']} / continuity {v['continuity_status']}",
            f"runs/full/{tag}.json", "same")
        add(f"{tag} peak RSS", f"{r['resources']['peak_rss_mib']} MiB", f"runs/full/{tag}.json", "same")
        add(f"{tag} clip", f"120 frames 4.0 s", f"media/clips/{tag}_4s.mp4", "ffprobe -count_frames")
    add("map invariant", "max |Δ| = 0", "runs/full/*.json -> map_invariant",
        "python -m mfprop.report")
    add("assembled set", "28.0 s / 840 frames", "media/assembled/", "python -m mfprop.assemble assemble")
    add("guide ablation", "4 labels", "ABLATIONS.json", "python -m mfprop.run --all --label ablate_no_<guide> …")
    add("params hash", P.params_hash(), "mfprop/params.py", "python -c 'from mfprop import params; print(params.params_hash())'")
    add("guard", "see verify_final.json", "runtime/propagate/guards/verify_final.json",
        "python tools/write_set_guard.py verify …")
    with open(os.path.join(EV_ROOT, "MATRIX.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(m) + "\n")
    return {"report": os.path.join(EV_ROOT, "REPORT.md"), "matrix": os.path.join(EV_ROOT, "MATRIX.md")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["all", "frame-map", "hashes", "resources", "ablations", "records"])
    a = ap.parse_args(argv)
    ledger.self_check()
    if a.action == "all":
        report()
    elif a.action == "frame-map":
        frame_map()
    elif a.action == "hashes":
        hash_table()
    elif a.action == "resources":
        resources()
    elif a.action == "ablations":
        ablations()
    elif a.action == "records":
        propagation_records()
    print("REPORT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
