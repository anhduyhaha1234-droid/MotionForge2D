"""MF-V1-PROPAGATE engine tests.

Synthetic tests do not need the film (they build frames in memory and drive the real
`propagate_segment`, `guides` and `measure` code paths).  Real-data tests verify the
frozen contract and frame-exact decoding against the GOLDEN keyframes.

Run:  python tests/test_mfprop.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mfprop import HEIGHT, WIDTH, contract, decode, guides, measure, params as P, propagate  # noqa: E402

FAILS: list[str] = []
COUNT = 0


def check(name: str, cond: bool, detail: str = ""):
    global COUNT
    COUNT += 1
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(f"{name} {detail}")


def approx(a, b, tol=1e-3):
    return abs(float(a) - float(b)) <= tol


# --------------------------------------------------------------------- synthetic
def synth_sequence(n=16, shift=1.0, cut_at=None):
    """A textured frame moving by `shift` px per frame; optional hard cut."""
    base = np.zeros((HEIGHT, WIDTH, 3), np.float32)
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
    base[..., 0] = (xx * 0.5 + yy * 0.25) % 255
    base[..., 1] = ((xx // 8) * 16 + (yy // 8) * 8) % 255
    base[..., 2] = 128
    base[40:120, 60:180, :] = 240          # a moving block of constant colour
    frames = []
    for i in range(n):
        s = i * shift
        M = np.float32([[1, 0, s], [0, 1, s * 0.5]])
        f = np.clip(np.dstack([np.roll(base[..., c], int(round(s)), axis=1) for c in range(3)]), 0, 255)
        if cut_at is not None and i >= cut_at:
            f = np.full((HEIGHT, WIDTH, 3), 30, np.uint8)
            f[100:200, 300:500] = 200
        frames.append(f.astype(np.uint8))
    return np.stack(frames)


def synth_bundle(frames, idx_map_left=None, idx_map_right=None):
    idx_map_left = np.zeros((HEIGHT, WIDTH), np.uint8) if idx_map_left is None else idx_map_left
    idx_map_right = np.zeros((HEIGHT, WIDTH), np.uint8) if idx_map_right is None else idx_map_right
    return {
        "frames": frames,
        "left": {"frame_id": 1650, "rgb": frames[0], "index_map": idx_map_left},
        "right": {"frame_id": 1650 + len(frames) - 1, "rgb": frames[-1], "index_map": idx_map_right},
        "depth": {"role_1": 0},
    }


def win_stub(n_roles=1, group=()):
    return {"tag": "BOOK", "role_ids": [f"role_{i}" for i in range(1, n_roles + 1)],
            "group_members": list(group), "anchors": [1650, 1650 + 15],
            "start_frame": 1650, "end_frame_exclusive": 1770, "frames": 120,
            "window_id": "W01_BOOK", "holdout": False, "classes": ["holdout"], "duration_s": 4.0,
            "start_pts": 844800, "end_pts_exclusive": 906240, "anchor_cadence": 15}


def test_params():
    print("[params]")
    check("params hash is stable", P.params_hash() == P.params_hash())
    check("params hash is 64 hex", len(P.params_hash()) == 64)
    check("mad floor above continuous-motion noise", P.PARAMS["reset"]["mad_floor"] >= 12.0,
          str(P.PARAMS["reset"]["mad_floor"]))


def test_contract():
    print("[frozen contract]")
    fz = contract.freeze_check()
    check("freeze recomputes to the frozen value", fz["matches"], fz["recomputed"])
    check("freeze matches the packet constant", fz["matches_packet_constant"])
    ws = contract.windows()
    check("7 windows", len(ws) == 7, str(len(ws)))
    check("windows are in source frame order",
          [w["start_frame"] for w in ws] == sorted(w["start_frame"] for w in ws))
    check("tags are the artifact tags", [w["tag"] for w in ws]
          == ["CUT_660", "TURN_795", "BOOK", "CAM_4212", "WALK_7927", "OCC_14768", "HOLDOUT_16231"])
    check("each window is 120 frames / 4.0 s",
          all(w["frames"] == 120 and approx(w["duration_s"], 4.0) for w in ws))
    check("pts formula exact", all(w["start_pts"] == w["start_frame"] * 512 for w in ws))
    check("anchors every 15 frames, 8 per window",
          all(len(w["anchors"]) == 8 and w["anchor_cadence"] == 15 for w in ws))
    check("holdout window flagged", [w["tag"] for w in ws if w["holdout"]] == ["HOLDOUT_16231"])
    g = contract.interaction_group("BOOK")
    check("group members read from the fixture", g["members"] == ["role_2", "role_3", "role_6", "role_7"],
          str(g["members"]))
    check("role reference counts sum to 88",
          sum(len(contract.role_ids(w["tag"])) for w in ws) == 88,
          str(sum(len(contract.role_ids(w["tag"])) for w in ws)))


def test_sampling():
    print("[sampling]")
    img = np.zeros((HEIGHT, WIDTH, 3), np.float32)
    img[10, 20] = [255, 128, 0]
    grid = guides.identity_coords((HEIGHT, WIDTH))
    out, w = guides.bilinear(img, grid)
    check("bilinear at identity returns the image", np.array_equal(out, img))
    check("bilinear weight is 1 inside", float(w.min()) == 1.0)
    check("bilinear reproduces the last row/column (no faked border)",
          np.array_equal(out[-1], img[-1]) and np.array_equal(out[:, -1], img[:, -1]))
    out2, w2 = guides.bilinear(img, grid - 10000.0)
    check("bilinear outside the frame has zero weight", float(w2.max()) == 0.0)
    n, wi = guides.sample_nearest(img, grid)
    check("nearest at identity returns the image", np.array_equal(n, img))
    check("nearest weight is 1 inside", float(wi.min()) == 1.0)
    half = np.stack([grid[..., 0] + 0.5, grid[..., 1]], -1)
    o3, _ = guides.bilinear(img, half)
    n3, _ = guides.sample_nearest(img, half)
    check("bilinear averages across a half-pixel shift", not np.array_equal(o3, n3))


def test_flow_and_edges():
    print("[flow / edge guides]")
    frames = synth_sequence(2, shift=2.0)
    g0, g1 = guides.to_gray(frames[0]), guides.to_gray(frames[1])
    f01, f10, fb = guides.flow_pair(g0, g1, P.PARAMS["farneback"])
    check("flow field shape", f01.shape == (HEIGHT, WIDTH, 2))
    med = float(np.median(f01[..., 0]))
    check("flow recovers a 2 px shift within 1 px", abs(med - 2.0) <= 1.0, f"median dx={med}")
    check("forward/backward consistency is small on a rigid shift",
          float(np.median(fb)) < 1.5, f"median fb={float(np.median(fb))}")
    mag = guides.edge_magnitude(g0, P.PARAMS["edge"])
    check("edge magnitude normalised", float(mag.max()) <= 1.0 and float(mag.max()) > 0.0)
    eb, thr = guides.edge_mask(mag, P.PARAMS["edge"])
    check("edge mask is binary", set(np.unique(eb)) <= {0, 1})
    snapped = guides.snap_mask_to_edges(eb, eb, 2)
    check("snapping only moves boundary pixels", float(np.abs(snapped.astype(int) - eb.astype(int)).mean()) < 0.5)
    pts = guides.corner_points(g0, P.PARAMS["points"])
    check("corner detection finds points", len(pts) >= 8, str(len(pts)))
    tracks = guides.track_chain([g0, g1], 0, P.PARAMS["points"])
    check("point tracking returns per-step positions", 0 in tracks["points"] and 1 in tracks["points"])
    fit = guides.fit_partial_affine(tracks["points"][0], tracks["points"][1], 2.0)
    check("similarity fit on a rigid shift is translation-only",
          fit["ok"] and approx(fit["translation"][0], 2.0, 1.0), str(fit.get("translation")))
    inv = guides.invert_similarity(fit["matrix"])
    back = guides.apply_similarity(inv, guides.apply_similarity(fit["matrix"], tracks["points"][0]))
    check("inverse similarity round-trips", float(np.abs(back - tracks["points"][0]).max()) < 1e-3)


def test_chain():
    print("[chain]")
    frames = synth_sequence(8, shift=1.0)
    grays = [guides.to_gray(f) for f in frames]
    ids = list(range(1650, 1658))
    fwd, bwd = {}, {}
    for i in range(len(ids) - 1):
        f01, f10, _ = guides.flow_pair(grays[i], grays[i + 1], P.PARAMS["farneback"])
        fwd[ids[i]] = f01
        bwd[ids[i + 1]] = f10
    zero = np.zeros((HEIGHT, WIDTH, 2), np.float32)
    L = propagate.chain_from_left({f: bwd.get(f, zero) for f in ids}, ids, ids[0])
    check("chain identity at the anchor", np.array_equal(L["coords"][ids[0]], guides.identity_coords((HEIGHT, WIDTH))))
    check("chain validity at the anchor is 1", int(L["valid"][ids[0]].min()) == 1)
    R = propagate.chain_from_right({f: fwd.get(f, zero) for f in ids}, ids, ids[-1])
    check("right chain identity at the right anchor", int(R["valid"][ids[-1]].min()) == 1)
    d = np.linalg.norm(L["coords"][ids[4]] - L["coords"][ids[3]], axis=-1)
    check("chain accumulates the 1 px per-frame displacement",
          approx(float(np.median(d)), 1.0, 0.6), f"median step={float(np.median(d)):.3f}")


def test_static_chain_is_exact():
    print("[static chain is lossless]")
    frames = np.stack([np.full((HEIGHT, WIDTH, 3), 90, np.uint8) for _ in range(6)])
    frames[:, 50:150, 100:200] = 200
    outs, seg = propagate.propagate_segment("BOOK", win_stub(), 1650, 1655,
                                            synth_bundle(frames), P.params(),
                                            {"flow", "point", "mask", "edge"})
    mae = [float(np.abs(o.out_rgb.astype(np.int16) - frames[i].astype(np.int16)).mean())
           for i, o in enumerate(outs)]
    check("constant sequence reconstructs exactly", max(mae) == 0.0, str(mae))


def test_map_invariant_and_single_map():
    print("[sample map invariant]")
    frames = synth_sequence(16, shift=1.0)
    lm = np.zeros((HEIGHT, WIDTH), np.uint8)
    lm[40:120, 60:180] = 1
    rm = np.zeros((HEIGHT, WIDTH), np.uint8)
    rm[44:124, 64:184] = 1
    outs, seg = propagate.propagate_segment("BOOK", win_stub(), 1650, 1665,
                                            synth_bundle(frames, lm, rm), P.params(),
                                            {"flow", "point", "mask", "edge"})
    check("one output per frame", len(outs) == 16, str(len(outs)))
    bad_sides, bad_recon, maes = 0, 0, []
    for o in outs:
        if not set(np.unique(o.anchor_side).tolist()) <= {0, 1}:
            bad_sides += 1
        anchor = frames[0].astype(np.float32) if int(o.anchor_side.mean() < 0.5) else frames[-1].astype(np.float32)
        c_o, _ = guides.bilinear(anchor, np.stack([o.owner_sx, o.owner_sy], -1))
        c_b, _ = guides.bilinear(anchor, np.stack([o.sx, o.sy], -1))
        rec = np.clip(o.alpha[..., None] * c_o + (1 - o.alpha[..., None]) * c_b, 0, 255).astype(np.uint8)
        if not np.array_equal(rec, o.out_rgb):
            bad_recon += 1
        maes.append(float(np.abs(o.out_rgb.astype(np.int16) - frames[o.frame_id - 1650].astype(np.int16)).mean()))
    check("every pixel belongs to exactly one keyframe side", bad_sides == 0)
    check("the persisted map alone reproduces the written pixels", bad_recon == 0, f"{bad_recon} frames differ")
    check("anchor frames reconstruct exactly (identity map)", approx(np.mean(maes[:1]), 0.0))
    check("interior frames reconstruct with sub-pixel error", max(maes) < 12.0, f"max MAE={max(maes):.3f}")
    check("confidence is a per-pixel uint8 map", outs[5].conf.dtype == np.uint8 and outs[5].conf.shape == (HEIGHT, WIDTH))
    check("alpha is premultiplied coverage in [0,1]",
          float(outs[5].alpha.min()) >= 0.0 and float(outs[5].alpha.max()) <= 1.0)
    check("meeting frames reported", len(seg["meeting_frames"]) >= 1, str(seg["meeting_frames"]))
    check("reconciliation statistics persisted per frame",
          all("reconcile_conflict_px" in f for f in seg["frames"]))


def test_group_constraint_pins_members():
    print("[group constraint]")
    frames = synth_sequence(16, shift=1.0)
    lm = np.zeros((HEIGHT, WIDTH), np.uint8)
    lm[40:120, 60:180] = 1
    lm[130:170, 200:260] = 2
    outs, seg = propagate.propagate_segment("BOOK", win_stub(2, group=("role_1",)),
                                           1650, 1665, synth_bundle(frames, lm, lm),
                                           P.params(), {"flow", "point", "mask", "edge"})
    pinned = [k for s in [seg] for k, v in (s["group_constraint"] or {}).items() if v]
    check("group members are pinned to the group solve", "role_1" in pinned, str(pinned))
    gc = (seg["group_constraint"] or {}).get("role_1", [{}])[0]
    check("independent-solve deviation is measured for the pinned member",
          "independent_solve_would_deviate_px_p95" in gc, str(gc)[:200])
    check("applied deviation for a pinned member is zero", gc.get("applied_deviation_px_max") == 0.0, str(gc))


def test_reset_detection():
    print("[resets]")
    smooth = synth_sequence(16, shift=1.0)
    grays = [guides.to_gray(f) for f in smooth]
    ids = list(range(1650, 1666))
    ev = propagate.detect_resets(grays, ids, [], P.params())
    check("no reset on continuous motion", not [e for e in ev if e["kind"] == "measured_discontinuity"],
          str([e for e in ev if e["kind"] == "measured_discontinuity"]))
    cut = synth_sequence(16, shift=1.0, cut_at=8)
    ev2 = propagate.detect_resets([guides.to_gray(f) for f in cut], ids, [], P.params())
    meas = [e for e in ev2 if e["kind"] == "measured_discontinuity"]
    check("a hard cut is detected", len(meas) >= 1, str(ev2))
    if meas:
        check("the detected cut frame is the cut frame", meas[0]["frame_id"] == 1658,
              str(meas[0]["frame_id"]))
        check("the reset records its measured MAD and the frozen threshold",
              meas[0]["mad_measured"] > meas[0]["mad_threshold"], str(meas[0]))
    ev3 = propagate.detect_resets(grays, ids, [{"frame_id": 1660, "scene_score": 1.0}], P.params())
    ann = [e for e in ev3 if e["kind"] == "annotated_cut"]
    check("an annotated cut is always a reset", len(ann) == 1 and ann[0]["frame_id"] == 1660, str(ev3))


def test_single_side_tail_and_unpropagated():
    print("[tail / explicit failure]")
    frames = synth_sequence(16, shift=1.0, cut_at=6)
    outs, seg = propagate.propagate_segment("BOOK", win_stub(), 1650, 1665,
                                            synth_bundle(frames), P.params(),
                                            {"flow", "point", "mask", "edge"}, single_side=True)
    statuses = [o.stats.get("status") for o in outs]
    check("frames beyond a reset with no keyframe are explicitly UNPROPAGATED",
          any(s == "UNPROPAGATED_NO_KEYFRAME_BEYOND_RESET" for s in statuses), str(statuses))
    up = [o for o in outs if o.stats.get("status") == "UNPROPAGATED_NO_KEYFRAME_BEYOND_RESET"]
    if up:
        check("unpropagated frames carry zero confidence", int(up[0].conf.max()) == 0)
        check("unpropagated frames carry no owning keyframe", up[0].stats.get("owning_keyframe") is None)
    check("single-side run reports no reconciliation meeting", seg["single_side"] is True)


def test_negatives_and_outliers():
    print("[negatives / outlier measurement]")
    a = np.zeros((HEIGHT, WIDTH), bool)
    b = np.zeros((HEIGHT, WIDTH), bool)
    a[10:20, 10:20] = True
    b[10:20, 10:20] = True
    d = measure._support_distance(a, b)
    check("overlapping supports are TRUE_ZERO with the reason", d["class"] == "TRUE_ZERO" and d["distance_px"] == 0.0)
    b2 = np.zeros((HEIGHT, WIDTH), bool)
    b2[10:20, 21:31] = True
    d2 = measure._support_distance(a, b2)
    check("adjacent supports report the measured 1.0 px", d2["class"] == "MEASURED" and approx(d2["distance_px"], 1.0),
          str(d2))
    d3 = measure._support_distance(a, np.zeros((HEIGHT, WIDTH), bool))
    check("an empty support is OCCLUDED, not 0.0", d3["class"] == "OCCLUDED" and d3["distance_px"] is None)
    out = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    truth = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    truth[0:10, 0:10] = 200
    owner = np.zeros((HEIGHT, WIDTH), np.uint8)
    owner[100:200, 100:200] = 1
    rep = measure.outlier_report(out, truth, owner)
    check("outlier report counts high-error pixels", rep["px_gt30"] == 100, str(rep["px_gt30"]))
    check("outlier report splits by owner region", rep["px_gt30_outside_owner_region"] == 100
          and rep["px_gt30_in_owner_region"] == 0)
    check("outlier report carries per-region error rates",
          rep["err30_rate_in_owner_region"] == 0.0 and rep["err30_rate_outside_owner_region"] > 0)


def test_real_decode_is_frame_exact():
    print("[real decode]")
    if not os.path.exists(contract.film_path()):
        check("reference film present", False, contract.film_path())
        return
    rep = decode.alignment_report("BOOK")
    check("every BOOK anchor decodes byte-exact to the GOLDEN keyframe",
          rep["frame_map_verified"], f"exact {rep['anchors_exact']}/{rep['anchors_total']}, worst MAE {rep['worst_mae']}")
    check("decode commands stay inside the resident ceiling",
          all(c["count"] <= P.PARAMS["max_frames_resident"] for c in rep["decode_commands"]))


def test_continuity_gate_not_applicable():
    print("[continuity gate applicability]")
    fake = [type("F", (), {"frame_id": 1, "role_owner": np.zeros((HEIGHT, WIDTH), np.uint8)})()]
    r = measure.continuity_negative(fake, "WALK_7927")
    check("a window with no character role is NOT_APPLICABLE, never PASS",
          r["status"] == "NOT_APPLICABLE", r["status"])


def main() -> int:
    for fn in (test_params, test_contract, test_sampling, test_flow_and_edges, test_chain,
               test_static_chain_is_exact, test_map_invariant_and_single_map,
               test_group_constraint_pins_members, test_reset_detection,
               test_single_side_tail_and_unpropagated, test_negatives_and_outliers,
               test_continuity_gate_not_applicable, test_real_decode_is_frame_exact):
        fn()
    print(f"\nTESTS {COUNT - len(FAILS)}/{COUNT} passed")
    if FAILS:
        print("FAILURES:")
        for f in FAILS:
            print(" -", f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
