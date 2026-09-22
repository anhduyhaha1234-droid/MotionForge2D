"""MF-V1-VIDEO14B wave B closeout (b2) — C2: pick the delivery candidate MEASURABLY.

No vision exists on this route, so the pick is made against the rule recorded in
`pick_candidate_rule.json` (written BEFORE this tool runs) on axes already defined
in b1 by `waveB_pick_reference.py`:

  media_kind -> canvas_identity -> frame_count -> non_degeneracy ->
  restyle_strength (MAE vs source) -> composition (gradient correlation vs source)

Each candidate is decoded to PNG in PRESENTATION order (the same reader the F06
export uses) and every statistic is computed on decoded RGB frames.  Candidates
that are byte-identical collapse to ONE candidate: the pick is then trivial and
is recorded as such, not dressed up as a comparison.

The losing candidate is COPIED into <media_dir> and never deleted.

usage:
  python waveB_pick_video_candidate.py <source_window.mp4> <out_json> <media_dir> \
      --rule <pick_candidate_rule.json> <cand1.mp4> [<cand2.mp4> ...]
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

CANVAS = (640, 368)
N_FRAMES = 121
STD_MIN_FLOOR = 10.0
MAE_FLOOR = 2.0
GRAD_CORR_FLOOR = 0.0


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)
    if v is None:
        return {"has_video_stream": False}
    r2 = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                         "-show_frames", "-select_streams", "v:0", str(path)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    frames = json.loads(r2.stdout or "{}").get("frames", [])
    pts = [int(f["pts"]) for f in frames if "pts" in f]
    deltas = sorted({pts[i + 1] - pts[i] for i in range(len(pts) - 1)}) if len(pts) > 1 else []
    return {"has_video_stream": True, "codec_name": v.get("codec_name"),
            "container": path.suffix.lower().lstrip("."),
            "width": v.get("width"), "height": v.get("height"),
            "geometry": f"{v.get('width')}x{v.get('height')}",
            "r_frame_rate": v.get("r_frame_rate"), "time_base": v.get("time_base"),
            "nb_frames": v.get("nb_frames"), "duration": v.get("duration"),
            "has_audio_stream": a is not None,
            "presentation_pts_first": pts[0] if pts else None,
            "presentation_pts_last": pts[-1] if pts else None,
            "presentation_delta_set": deltas,
            "presentation_frame_count": len(pts)}


def decode_pngs(video: Path, work: Path) -> list[Path]:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video),
                        "-fps_mode", "passthrough", "-f", "image2",
                        "-start_number", "0", str(work / "f%03d.png")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"decode failed rc={r.returncode}: {video}\n{r.stderr[-800:]}")
    pngs = sorted(work.glob("f*.png"))
    if not pngs:
        raise SystemExit(f"ZERO-BYTE-DECODE-GUARD: no frame decoded from {video}")
    return pngs


def stats(path: Path, src: list[Path] | None) -> dict:
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.float64)
    gray = np.asarray(im.convert("L")).astype(np.float64)
    std_rgb = [round(float(a[:, :, i].std()), 4) for i in range(3)]
    m = {"size": list(im.size), "std_rgb": std_rgb, "std_min": round(min(std_rgb), 4),
         "mean_rgb": [round(float(a[:, :, i].mean()), 4) for i in range(3)],
         "frac_near_black": round(float((gray < 4).mean()), 6),
         "frac_near_white": round(float((gray > 251).mean()), 6)}
    q = (a // 4).astype(np.int32)
    m["distinct_colours_6bit"] = int(len(np.unique(q.reshape(-1, 3), axis=0)))
    if src is not None:
        s = np.asarray(Image.open(src).convert("L")).astype(np.float64)
        if s.shape == gray.shape:
            d = np.abs(gray - s)
            m["mae_vs_source"] = round(float(d.mean()), 4)
            m["frac_pixels_changed_gt2"] = round(float((d > 2).mean()), 6)
            gy, gx = np.gradient(gray)
            sy, sx = np.gradient(s)
            g = np.hypot(gx, gy).ravel()
            t = np.hypot(sx, sy).ravel()
            if g.std() > 0 and t.std() > 0:
                m["grad_corr_vs_source"] = round(float(np.corrcoef(g, t)[0, 1]), 6)
            else:
                m["grad_corr_vs_source"] = None
        else:
            m["not_comparable_to_source"] = (f"geometry {gray.shape[::-1]} != source "
                                             f"{s.shape[::-1]}")
    return m


def main() -> int:
    src_video = _p(sys.argv[1])
    out_json = _p(sys.argv[2])
    media_dir = _p(sys.argv[3])
    rule_value = sys.argv[sys.argv.index("--rule") + 1] if "--rule" in sys.argv else None
    rule_path = _p(rule_value) if rule_value else None
    cands: list[Path] = []
    skip_value = False
    for a in sys.argv[4:]:
        if skip_value:
            skip_value = False
            continue
        if a == "--rule":
            skip_value = True
            continue
        if a.startswith("--"):
            continue
        cands.append(_p(a))

    rule = json.loads(rule_path.read_text(encoding="utf-8")) if rule_path else {}
    work = Path(tempfile.mkdtemp(prefix="mfb_pick_"))
    src_pngs = decode_pngs(src_video, work / "src")
    src_probe = probe(src_video)
    # A source window at the wrong geometry silently degrades every comparison to
    # "not comparable" and then reads as a failure of the candidate.  Fail loudly
    # instead: the reference measurement is only meaningful on the padded canvas.
    if (src_probe.get("width"), src_probe.get("height")) != CANVAS:
        raise SystemExit(
            f"SOURCE_GEOMETRY_MISMATCH: source window is {src_probe.get('geometry')} but the "
            f"comparison canvas is {CANVAS[0]}x{CANVAS[1]} (pass the padded source window; a "
            f"stretch or a 640x360 unpadded source would make every axis unmeasurable)")

    rows: list[dict] = []
    for i, c in enumerate(cands, start=1):
        pr = probe(c)
        pngs = decode_pngs(c, work / f"cand{i}")
        per_frame = [stats(p, src_pngs[n] if n < len(src_pngs) else None)
                     for n, p in enumerate(pngs)]
        comparable = [f for f in per_frame if "mae_vs_source" in f]
        grads = [f["grad_corr_vs_source"] for f in comparable
                 if f.get("grad_corr_vs_source") is not None]
        agg = {
            "media_kind": "video" if pr.get("has_video_stream") else "not_a_video",
            "geometry": pr.get("geometry"),
            "canvas_identity": (pr.get("width"), pr.get("height")) == CANVAS,
            "frame_count": len(pngs),
            "std_min_over_frames": round(min(f["std_min"] for f in per_frame), 4),
            "mae_vs_source_mean": round(sum(f["mae_vs_source"] for f in comparable)
                                       / len(comparable), 4) if comparable else None,
            "grad_corr_vs_source_mean": round(sum(grads) / len(grads), 4) if grads else None,
            "frac_pixels_changed_gt2_mean": round(
                sum(f["frac_pixels_changed_gt2"] for f in comparable) / len(comparable), 6)
                if comparable else None,
            "distinct_colours_6bit_min": min(f["distinct_colours_6bit"] for f in per_frame),
            "frac_near_black_max": max(f["frac_near_black"] for f in per_frame),
            "frac_near_white_max": max(f["frac_near_white"] for f in per_frame),
        }
        fails = []
        if agg["media_kind"] != "video":
            fails.append("media_kind")
        if not agg["canvas_identity"]:
            fails.append("canvas_identity")
        if agg["frame_count"] != N_FRAMES:
            fails.append("frame_count")
        if agg["std_min_over_frames"] < STD_MIN_FLOOR:
            fails.append("non_degeneracy")
        if agg["mae_vs_source_mean"] is None or agg["mae_vs_source_mean"] <= MAE_FLOOR:
            fails.append("restyle_strength")
        if agg["grad_corr_vs_source_mean"] is None or \
                agg["grad_corr_vs_source_mean"] <= GRAD_CORR_FLOOR:
            fails.append("composition")
        rows.append({
            "candidate_index": i,
            "path": str(c).replace("\\", "/"),
            "sha256": sha256_file(c),
            "bytes": c.stat().st_size,
            "probe": pr,
            "measured": agg,
            "failed_axes": fails,
            "eligible": not fails,
            "per_frame_std_min": [f["std_min"] for f in per_frame],
        })

    # byte-identity collapse: identical sha256 => one candidate, not two
    by_sha: dict[str, list[int]] = {}
    for r in rows:
        by_sha.setdefault(r["sha256"], []).append(r["candidate_index"])
    identical_groups = [v for v in by_sha.values() if len(v) > 1]

    eligible = [r for r in rows if r["eligible"]]
    eligible.sort(key=lambda r: (-(r["measured"]["grad_corr_vs_source_mean"] or 0),
                                 -(r["measured"]["mae_vs_source_mean"] or 0),
                                 r["candidate_index"]))
    chosen = eligible[0] if eligible else None
    rejected = [r for r in rows if not chosen or r["candidate_index"] != chosen["candidate_index"]]

    media_dir.mkdir(parents=True, exist_ok=True)
    kept = []
    duplicates = []
    for r in rows:
        if chosen and r["candidate_index"] == chosen["candidate_index"]:
            continue
        same_bytes_as_chosen = bool(chosen) and r["sha256"] == chosen["sha256"]
        tag = "duplicate_of_chosen" if same_bytes_as_chosen else "rejected"
        dst = media_dir / f"{tag}_{Path(r['path']).name}"
        shutil.copy2(r["path"], dst)
        entry = {"of": r["path"], "copy": str(dst).replace("\\", "/"),
                 "sha256": sha256_file(dst), "bytes": dst.stat().st_size,
                 "same_bytes_as_chosen": same_bytes_as_chosen}
        (duplicates if same_bytes_as_chosen else kept).append(entry)
    chosen_copy = None
    if chosen:
        dst = media_dir / f"chosen_{Path(chosen['path']).name}"
        shutil.copy2(chosen["path"], dst)
        chosen_copy = {"of": chosen["path"], "copy": str(dst).replace("\\", "/"),
                       "sha256": sha256_file(dst), "bytes": dst.stat().st_size}

    report = {
        "artifact": "pick_candidate_measurement.json",
        "task_id": "MF-V1-VIDEO14B",
        "wave": "B",
        "round": "b2",
        "row": "F08 (GPU part)",
        "generated_at_local": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
        "rule_source": str(rule_path).replace("\\", "/") if rule_path else None,
        "rule_criteria_order": rule.get("criteria_order"),
        "quality_status": "NOT_VISUALLY_APPROVED",
        "no_visual_claim": True,
        "source_window": {"path": str(src_video).replace("\\", "/"),
                          "sha256": sha256_file(src_video),
                          "probe": src_probe, "decoded_frames": len(src_pngs)},
        "candidates": rows,
        "byte_identical_groups": identical_groups,
        "candidates_collapse_to": len(by_sha),
        "pick_is_trivial_byte_identity": bool(identical_groups) and len(by_sha) == 1,
        "chosen": {"candidate_index": chosen["candidate_index"], "path": chosen["path"],
                   "sha256": chosen["sha256"], "bytes": chosen["bytes"],
                   "measured": chosen["measured"], "copy": chosen_copy} if chosen else None,
        "rejected_kept": kept,
        "duplicates_of_chosen_kept": duplicates,
        "decision_note": None,
    }
    if report["pick_is_trivial_byte_identity"]:
        report["decision_note"] = (
            "all candidate files are byte-identical (one sha256 across every attempt): the "
            "render is deterministic for this graph/seed/input, so this is ONE candidate, not "
            "a ranked comparison. The pick is trivial and is recorded as such.")
    elif chosen is None:
        report["decision_note"] = "NO ELIGIBLE CANDIDATE — every candidate failed at least one axis."
    else:
        report["decision_note"] = ("picked on the recorded criteria order; ties broken by higher "
                                   "composition, then larger restyle MAE, then lower index.")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "chosen": report["chosen"] and {k: report["chosen"][k]
                                        for k in ("candidate_index", "path", "sha256", "bytes")},
        "candidates_collapse_to": report["candidates_collapse_to"],
        "pick_is_trivial_byte_identity": report["pick_is_trivial_byte_identity"],
        "rejected_kept": [k["copy"] for k in kept],
        "failed_axes": {r["candidate_index"]: r["failed_axes"] for r in rows},
        "eligible": {r["candidate_index"]: r["eligible"] for r in rows},
    }, indent=1, ensure_ascii=False))
    return 0 if chosen else 1


if __name__ == "__main__":
    raise SystemExit(main())
