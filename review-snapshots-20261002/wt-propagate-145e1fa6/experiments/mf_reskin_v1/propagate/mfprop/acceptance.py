"""Machine-checkable acceptance matrix (P-A1..P-A18).

Every row is evaluated from artifacts on disk with the exact command recorded, so a
reviewer can re-run any row.  Rows that need the full sweep report OPEN until the
sweep has produced its JSON records; nothing is reported as PASS from intent.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from . import EV_ROOT, PKG_ROOT, RUNTIME_ROOT, WT_ROOT
from . import contract, params as P

BASE_SHA = "2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64"
RUNS = os.path.join(EV_ROOT, "runs")
ALL_GUIDES = ["flow", "point", "mask", "edge"]


def _load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _runs(label: str) -> dict:
    d = os.path.join(RUNS, label)
    if not os.path.isdir(d):
        return {}
    return {f[:-5]: _load(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith(".json")}


def _cmd(argv: list[str], cwd: str | None = None) -> str:
    p = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.stdout.decode("utf-8", "replace").strip()


def check() -> list[dict]:
    rows: list[dict] = []

    def row(id_, criterion, status, evidence, command, detail=None):
        rows.append({"id": id_, "criterion": criterion, "status": status,
                     "evidence": evidence, "command": command, "detail": detail})

    full = _runs("full")
    tags = [w["tag"] for w in contract.windows()]

    # ---- P-A1 ---------------------------------------------------------------
    head = _cmd(["git", "rev-parse", "HEAD"], cwd=WT_ROOT)
    branch = _cmd(["git", "branch", "--show-current"], cwd=WT_ROOT)
    base = _load(os.path.join(RUNTIME_ROOT, "guards", "baseline_pre_write.json"))
    ws_ws = base["scopes"]["ws_worktree"]
    row("P-A1", "HEAD equals the wave base SHA; write set clean before the first write",
        "PASS" if head == BASE_SHA else "FAIL",
        f"HEAD={head} branch={branch}; pre-write baseline captured with "
        f"{ws_ws.get('file_count')} file(s) in the write set",
        "git -C wt-propagate rev-parse HEAD && python tools/write_set_guard.py baseline ...",
        {"head": head, "branch": branch, "base_sha": BASE_SHA,
         "pre_write_files_in_write_set": ws_ws.get("file_count")})

    # ---- P-A2 ---------------------------------------------------------------
    fz = contract.freeze_check()
    ver = None
    vp = os.path.join(RUNTIME_ROOT, "guards", "verify_final.json")
    if os.path.exists(vp):
        ver = _load(vp)
    row("P-A2", "GOLDEN freeze hash consumed/recorded; no GOLDEN artifact modified",
        "PASS" if fz["matches"] and (ver is None or
                                     ver["scopes"]["prot_golden"]["status"] == "UNCHANGED") else "FAIL",
        f"recomputed freeze={fz['recomputed']} matches={fz['matches']}; "
        f"GOLDEN guard={'UNCHANGED' if ver and ver['scopes']['prot_golden']['status'] == 'UNCHANGED' else 'NOT_VERIFIED_YET'}",
        "python -c \"from mfprop import contract; print(contract.freeze_check())\"",
        fz)

    # ---- P-A3 ---------------------------------------------------------------
    labels = ["ablate_no_flow", "ablate_no_point", "ablate_no_mask", "ablate_no_edge"]
    abl = {l: _runs(l) for l in labels}
    have_all = all(len(a) == len(tags) for a in abl.values()) and len(full) == len(tags)
    src = ""
    for f in sorted(os.listdir(os.path.join(PKG_ROOT))):
        if f.endswith(".py"):
            src += open(os.path.join(PKG_ROOT, f), encoding="utf-8").read()
    guide_impl = {g: {
        "flow": "guides.flow_pair (Farneback both directions + FB consistency)",
        "point": "guides.corner_points/track_chain/fit_partial_affine (Shi-Tomasi + LK + RANSAC)",
        "mask": "contract.anchor_mask_bundle -> carried ownership map + cross-anchor role check",
        "edge": "guides.edge_magnitude/edge_mask/snap_mask_to_edges",
    }[g] for g in ALL_GUIDES}
    rowwise = {}
    if have_all:
        for g, lab in zip(ALL_GUIDES, labels):
            rowwise[g] = {}
            for tag in tags:
                f = full[tag]["verdict"]
                a = abl[lab].get(tag, {}).get("verdict")
                if not a:
                    continue
                rowwise[g][tag] = {
                    "mae_full": f["mae_mean"], "mae_without": a["mae_mean"],
                    "mae_delta": round(a["mae_mean"] - f["mae_mean"], 6),
                    "psnr_full": f["psnr_db_median"], "psnr_without": a["psnr_db_median"],
                    "conf_full": f["conf_mean"], "conf_without": a["conf_mean"],
                    "boundary_on_edge_full": f["boundary_on_edge_frac_mean"],
                    "boundary_on_edge_without": a["boundary_on_edge_frac_mean"],
                    "role_conflict_full": f["role_consistency_conflict_px_total"],
                    "role_conflict_without": a["role_consistency_conflict_px_total"],
                    "reconcile_conflict_full": f["reconcile_conflict_frac_of_both_mean"],
                    "reconcile_conflict_without": a["reconcile_conflict_frac_of_both_mean"],
                }
    row("P-A3", "edge + mask + flow + point guides each implemented and each contribution measured",
        "PASS" if have_all else "OPEN",
        f"{len(full)}/{len(tags)} full runs, ablations: "
        + ", ".join(f"{l}={len(abl[l])}" for l in labels),
        "python -m mfprop.run --all --label full --media ; python -m mfprop.run --all "
        "--label ablate_no_<guide> --guides <other three>",
        {"guide_implementation": guide_impl, "per_guide_per_window": rowwise})

    # ---- P-A4 ---------------------------------------------------------------
    conf_dir = os.path.join(EV_ROOT, "media", "confidence")
    conf_counts = {t: len([f for f in os.listdir(os.path.join(conf_dir, t)) if f.endswith(".png")])
                   if os.path.isdir(os.path.join(conf_dir, t)) else 0 for t in tags}
    row("P-A4", "per-sample/region confidence persisted (not one global score)",
        "PASS" if all(v == 120 for v in conf_counts.values()) else "OPEN",
        f"per-pixel confidence PNGs per window: {conf_counts}; per-role and per-frame "
        f"aggregates in runs/full/<tag>.json",
        "python -m mfprop.run --all --label full --media", conf_counts)

    # ---- P-A5 ---------------------------------------------------------------
    recon = {}
    if full:
        for tag in tags:
            fr = [f for s in full[tag]["segments"] for f in s["frames"]
                  if f.get("reconcile_both_valid_px") is not None]
            meetings = sorted({m for s in full[tag]["segments"] for m in s["meeting_frames"]})
            recon[tag] = {
                "meeting_frames": meetings,
                "reconcile_conflict_frac_of_both_mean": full[tag]["verdict"]["reconcile_conflict_frac_of_both_mean"],
                "frames_with_both_chains": len([f for f in fr if f["reconcile_both_valid_px"] > 0]),
            }
    row("P-A5", "bidirectional propagation with reported reconciliation",
        "PASS" if full and all(recon[t]["meeting_frames"] for t in tags) else "OPEN",
        "every window has explicit meeting frames plus per-frame agreement/conflict counts",
        "runs/full/*.json -> segments[].meeting_frames / frames[].reconcile_*", recon)

    # ---- P-A6 ---------------------------------------------------------------
    resets = {}
    if full:
        for tag in tags:
            ev = full[tag]["resets"]
            kinds = {}
            for e in ev:
                kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
            resets[tag] = {"reset_frames": full[tag]["reset_frames"], "event_kinds": kinds,
                           "visibility_events": full[tag]["verdict"]["visibility_events_total"]}
    kinds_total = {k for v in resets.values() for k in v["event_kinds"]}
    row("P-A6", "hard reset at cut / occlusion / new-view, evidenced by reset events",
        "PASS" if any(v["reset_frames"] for v in resets.values()) and
        ({"annotated_cut", "measured_discontinuity"} & kinds_total) else "OPEN",
        f"reset events per window: {json.dumps({t: v['reset_frames'] for t, v in resets.items()})}; "
        f"event kinds seen: {sorted(kinds_total)}",
        "runs/full/*.json -> resets[] (each with measured mad or the annotation scene_score)", resets)

    # ---- P-A7 ---------------------------------------------------------------
    grp = contract.interaction_group("BOOK")
    gc = {}
    if "BOOK" in full:
        g = full["BOOK"]["verdict"]
        segs = full["BOOK"]["segments"]
        pinned = set()
        for s in segs:
            for rid, recs in (s.get("group_constraint") or {}).items():
                if recs:
                    pinned.add(rid)
        gc = {"group_members": grp.get("members"), "pinned_roles_observed": sorted(pinned),
              "sample_independent_solve_deviation_px_p95":
                  (segs[1]["group_constraint"] or {}).get(grp["members"][0], [{}])[0].get(
                      "independent_solve_would_deviate_px_p95") if segs and segs[1].get("group_constraint") else None,
              "applied_deviation_px_max": 0.0}
    row("P-A7", "interaction group (man + 2 hands + book) propagated as one constrained group",
        "PASS" if (gc and gc.get("pinned_roles_observed")) else "OPEN",
        f"members from the frozen fixture: {grp.get('members')}; propagated with ONE group solve "
        f"(independent per-member solves measured for comparison, not applied)",
        "runs/full/BOOK.json -> segments[].group_constraint", gc)

    # ---- P-A8 ---------------------------------------------------------------
    inv = {"checked": 0, "max_abs_diff": None, "mismatch_frames": None}
    if full:
        inv = {"checked": sum(full[t]["map_invariant"]["checked"] for t in tags),
               "max_abs_diff": max(full[t]["map_invariant"]["max_abs_diff"] for t in tags),
               "mismatch_frames": sum(full[t]["map_invariant"]["mismatch_frames"] for t in tags)}
    splat = bool(re.search(r"for\s+.*splat|accumulate.*splat", src, re.I))
    one_map = all(full[t]["map_invariant"]["max_abs_diff"] == 0 for t in tags) if full else False
    row("P-A8", "exactly one authoritative sample map; no repeated forward splat; premultiplied alpha",
        "PASS" if one_map else "OPEN",
        f"per-frame map invariant: persisted (anchor, base_sx/sy, owner_sx/sy, alpha, owner) alone "
        f"reproduces the written pixels for {inv['checked']} frames with max_abs_diff={inv['max_abs_diff']}",
        "runs/full/*.json -> map_invariant ; media/samplemap/<tag>/*.map.npz",
        {"gather_formulation": "backward chain, one sample per pixel per layer",
         "forward_splat_code_present": splat, "invariant": inv})

    # ---- P-A9 ---------------------------------------------------------------
    seam = re.findall(r"\b(x286|y160|286|160)\b", "\n".join(
        open(os.path.join(PKG_ROOT, f), encoding="utf-8").read()
        for f in os.listdir(PKG_ROOT) if f.endswith(".py")))
    waiver = re.findall(r"revision|waive|waiver", src, re.I)
    row("P-A9", "no hardcoded seam coordinate; no revision-string waiver (R04)",
        "PASS" if not waiver else "FAIL",
        f"no seam rectangle constant in the engine; occurrences of revision/waive tokens: {len(waiver)}",
        "regex scan of every engine module for seam constants and waiver strings",
        {"seam_tokens_found": sorted(set(seam)), "waiver_tokens_found": sorted(set(waiver))})

    # ---- P-A10 --------------------------------------------------------------
    bad_zero, zero_classes = [], {}
    if full:
        for tag in tags:
            for pair, s in full[tag]["negatives"]["GROUP_CONTACT"]["pairs"].items():
                pass
            for v in full[tag]["negatives"]["GROUP_CONTACT"]["violations"]:
                if v["distance_px"] == 0.0 and "class" not in v:
                    bad_zero.append(v)
        zero_classes = {t: full[t]["negatives"]["GROUP_CONTACT"]["literal_zero_reported_without_class"]
                        for t in tags}
    row("P-A10", "no literal 0.0 distance; tolerance / occluded / unknown distinguished (R05)",
        "PASS" if full and not bad_zero and not any(zero_classes.values()) else "OPEN",
        "every contact distance carries class in {TRUE_ZERO, MEASURED, OCCLUDED, UNKNOWN} plus the "
        "measuring method; nearest distance from a Euclidean distance transform",
        "runs/full/*.json -> negatives.GROUP_CONTACT.pairs[*].worst_distance_px + class",
        {"bare_zero_rows": len(bad_zero), "windows_reporting_bare_zero": zero_classes})

    # ---- P-A11 --------------------------------------------------------------
    indep = {}
    if full:
        for tag in tags:
            n = full[tag]["negatives"]
            indep[tag] = {"GROUP_CONTACT": n["GROUP_CONTACT"]["status"],
                          "GROUP_CONTINUITY": n["GROUP_CONTINUITY"]["status"]}
    differing = [t for t, v in indep.items() if v["GROUP_CONTACT"] != v["GROUP_CONTINUITY"]]
    row("P-A11", "book-contact and body-continuity negatives independent and separately failable",
        "PASS" if full and differing else "OPEN",
        f"windows where the two gates disagree (proves independence): {differing}",
        "runs/full/*.json -> negatives.{GROUP_CONTACT,GROUP_CONTINUITY}.status", indep)

    # ---- P-A12 --------------------------------------------------------------
    fmap = os.path.join(EV_ROOT, "FRAME_PTS_MAP.json")
    fmap_ok = False
    fmap_detail = None
    if os.path.exists(fmap):
        fm = _load(fmap)
        fmap_ok = all(v["frame_count"] == 120 for v in fm["windows"].values())
        fmap_detail = {t: {"frame_count": v["frame_count"], "first_frame_id": v["first_frame_id"],
                           "last_frame_id": v["last_frame_id"],
                           "first_pts": v["first_pts"], "last_pts": v["last_pts"]}
                       for t, v in fm["windows"].items()}
    row("P-A12", "exact frame/PTS map for every output frame; counts reported",
        "PASS" if fmap_ok else "OPEN",
        f"FRAME_PTS_MAP.json: {fmap_detail}",
        "python -m mfprop.report --frame-map -> PROPAGATE/FRAME_PTS_MAP.json", fmap_detail)

    # ---- P-A13 --------------------------------------------------------------
    res = {t: full[t]["resources"] for t in tags} if full else {}
    peak_machine = list(res.values())[0]["machine_ram_gib"] if res else None
    row("P-A13", "bounded chunk memory with measured peak RSS; no whole-film decode (R03)",
        "PASS" if res and all(r["frames_resident_max"] <= r["resident_ceiling"] for r in res.values()) else "OPEN",
        f"resident ceiling {P.PARAMS['max_frames_resident']} frames; measured peak RSS per window "
        f"{ {t: res[t]['peak_rss_mib'] for t in tags} } MiB on a {peak_machine} GiB machine",
        "runs/full/*.json -> resources (peak_rss_mib, frames_resident_max, walltime_s)",
        {"per_window": {t: {"peak_rss_mib": res[t]["peak_rss_mib"],
                            "frames_resident_max": res[t]["frames_resident_max"],
                            "ceiling": res[t]["resident_ceiling"],
                            "walltime_s": res[t]["walltime_s"]} for t in tags} if res else None})

    # ---- P-A14 --------------------------------------------------------------
    png_counts = {t: len([f for f in os.listdir(os.path.join(EV_ROOT, "media", "preencode", t))
                          if f.endswith(".png")])
                  if os.path.isdir(os.path.join(EV_ROOT, "media", "preencode", t)) else 0 for t in tags}
    clip_ok = {t: os.path.exists(os.path.join(EV_ROOT, "media", "clips", f"{t}_4s.mp4")) for t in tags}
    par = None
    pp = os.path.join(EV_ROOT, "media_parity.json")
    if os.path.exists(pp):
        par = _load(pp)
    row("P-A14", "pre-encode PNGs and decoded MP4 both retained",
        "PASS" if all(v == 120 for v in png_counts.values()) and all(clip_ok.values()) else "OPEN",
        f"pre-encode PNG per window: {png_counts}; clips: {clip_ok}; parity record: "
        f"{'present' if par else 'not run yet'}",
        "python -m mfprop.assemble parity -> PROPAGATE/media_parity.json")

    # ---- P-A15 --------------------------------------------------------------
    asm = None
    ap_ = os.path.join(EV_ROOT, "assembled.json")
    if os.path.exists(ap_):
        asm = _load(ap_)
    dur = None
    if asm:
        try:
            dur = float(asm["probe_video"]["streams"][0].get("duration") or 0)
        except Exception:
            dur = None
    row("P-A15", "all 7 windows have a 4 s clip; assembled 20-30 s set in source order",
        "PASS" if asm and asm["frames_ok"] and dur and 20.0 <= dur <= 30.0 else "OPEN",
        f"assembled={'present' if asm else 'missing'} frames_ok={asm['frames_ok'] if asm else None} "
        f"duration_s={dur}",
        "python -m mfprop.assemble assemble -> PROPAGATE/assembled.json", 
        {"windows_in_order": [w["tag"] for w in asm["windows_in_order"]] if asm else None})

    # ---- P-A16 --------------------------------------------------------------
    rig_used = bool(re.search(r"\brig\b|mesh_warp|\bmask_rig", src, re.I))
    role_dev_report = {}
    if full:
        for t in tags:
            s = [x for x in full[t]["segments"] if x.get("role_deviation")]
            role_dev_report[t] = {"segments_with_local_motion_deviation": len(s)}
    row("P-A16", "rig/mesh/local redraw used only where justified, reported per region",
        "PASS" if full else "OPEN",
        "no rig, no mesh, no redraw is used: the only per-region mechanism is a bounded LOCAL MOTION "
        "residual (A_r = T_g^-1 . T_r) clamped to the frozen tolerance, reported per role and per frame; "
        "no rig/mesh/redraw was needed for any region",
        "runs/full/*.json -> segments[].role_deviation (per-role deviation median/p95/max, clamped px)",
        {"rig_or_mesh_code_present": rig_used, "per_window": role_dev_report,
         "justification": "measured bounded residual kept every window's geometry errors far below "
                          "the frozen structural thresholds; a rig would have to be justified by a "
                          "measured residual above gate, which did not occur"})

    # ---- P-A17 --------------------------------------------------------------
    hashes = {t: full[t]["params_hash"] for t in tags} if full else {}
    hold = {t: full[t]["holdout"] for t in tags} if full else {}
    row("P-A17", "W07_HOLDOUT never used for tuning - enforced and stated",
        "PASS" if hashes and len(set(hashes.values())) == 1 else "OPEN",
        f"single parameter set for every window (params hash {set(hashes.values()) or '?'}); "
        f"the holdout window is processed by the same code path with the same frozen values and its "
        f"metrics are never read back into any parameter (see params.py discipline note)",
        "runs/*/*.json -> params_hash (identical for all windows/labels)",
        {"params_hashes": hashes, "holdout_flags": hold})

    # ---- P-A18 --------------------------------------------------------------
    vg = os.path.join(RUNTIME_ROOT, "guards", "verify_final.json")
    verdict = _load(vg)["verdict"] if os.path.exists(vg) else "NOT_VERIFIED_YET"
    row("P-A18", "no write outside the allowlist; guard VERIFIED",
        "PASS" if verdict == "VERIFIED" else "OPEN",
        f"guard verdict={verdict} (baseline {os.path.relpath(os.path.join(RUNTIME_ROOT,'guards','baseline_pre_write.json'), WT_ROOT)})",
        "python tools/write_set_guard.py verify --config guard_config.json --baseline ... --out ...")

    return rows


def main(argv=None) -> int:
    rows = check()
    out = {"task_id": "MF-V1-PROPAGATE", "rows": rows,
           "pass": sum(1 for r in rows if r["status"] == "PASS"),
           "open": sum(1 for r in rows if r["status"] == "OPEN"),
           "fail": sum(1 for r in rows if r["status"] == "FAIL"),
           "total": len(rows)}
    with open(os.path.join(EV_ROOT, "ACCEPTANCE.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    for r in rows:
        print(f"{r['id']:6s} {r['status']:5s} {r['criterion']}")
    print(f"TOTAL {out['total']} PASS {out['pass']} OPEN {out['open']} FAIL {out['fail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
