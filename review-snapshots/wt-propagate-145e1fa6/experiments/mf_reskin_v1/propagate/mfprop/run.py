"""Per-window driver: bounded decode -> guides -> bidirectional propagation ->
measured metrics -> media (pre-encode PNG frames, sample maps, confidence maps, MP4).

Resource discipline (finding R03): frames are resident only for one anchor-to-anchor
segment (<= 16), the resident ceiling is asserted by the decoder, and peak RSS is
sampled by a monitor thread for the whole run and reported.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import numpy as np
import psutil
from PIL import Image

if __package__ in (None, ""):  # allow `python run.py`
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from mfprop import EV_ROOT, RUNTIME_ROOT, HEIGHT, WIDTH, FPS, pts_of, time_of
    from mfprop import contract, decode, guides, ledger, measure, params as P, propagate
else:
    from . import EV_ROOT, RUNTIME_ROOT, HEIGHT, WIDTH, FPS, pts_of, time_of
    from . import contract, decode, guides, ledger, measure, params as P, propagate

RUNS_DIR = os.path.join(EV_ROOT, "runs")
MEDIA_DIR = os.path.join(EV_ROOT, "media")
ALL_GUIDES = ("flow", "point", "mask", "edge")


# ------------------------------------------------------------------ resources
class ResourceSampler(threading.Thread):
    def __init__(self, interval: float = 0.02):
        super().__init__(daemon=True)
        self.interval = interval
        self.peak = 0
        self.peak_vram = None
        self._halt = threading.Event()
        self.proc = psutil.Process(os.getpid())

    def _vram(self):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                                  "--format=csv,noheader,nounits"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
            return int(out.stdout.decode().strip().splitlines()[0])
        except Exception:
            return None

    def run(self):
        v0 = self._vram()
        self.peak_vram = v0
        while not self._halt.is_set():
            try:
                rss = self.proc.memory_info().rss
                self.peak = max(self.peak, rss)
            except Exception:
                break
            v = self._vram()
            if v is not None:
                self.peak_vram = max(self.peak_vram or 0, v)
            self._halt.wait(self.interval)

    def stop(self) -> dict:
        self._halt.set()
        self.join(timeout=3)
        import psutil as _ps
        gb = round(_ps.virtual_memory().total / (1024 ** 3), 2)
        return {"peak_rss_mib": round(self.peak / (1024 ** 2), 2),
                "machine_ram_gib": gb,
                "peak_rss_pct_of_machine": round(100.0 * self.peak / _ps.virtual_memory().total, 3),
                "peak_vram_mib": self.peak_vram,
                "vram_note": "nvidia-smi memory.used, machine-wide; this run uses the CPU "
                             "guides only, so any rise is not attributable to this task"}


def dir_bytes(p: str) -> int:
    tot = 0
    for dp, _, fns in os.walk(p):
        for f in fns:
            try:
                tot += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return tot


# -------------------------------------------------------------------- plumbing
def build_jobs(win: dict) -> list[dict]:
    a = win["anchors"]
    jobs = []
    for i in range(len(a) - 1):
        jobs.append({"start": a[i], "end": a[i + 1], "single_side": False,
                     "keep": (a[i], a[i + 1] - 1)})
    jobs.append({"start": a[-1], "end": win["end_frame_exclusive"] - 1, "single_side": True,
                 "keep": (a[-1], win["end_frame_exclusive"] - 1)})
    return jobs


def run_window(tag: str, cfg: dict, guides_on: set[str], label: str, media: bool,
               reader: decode.ChunkReader | None = None) -> dict:
    t_start = time.time()
    win = contract.window(tag)
    win = dict(win)
    win["role_ids"] = contract.role_ids(tag)
    win["group_members"] = contract.interaction_group(tag).get("members", [])
    depth = contract.containment_depth(tag)["depth"]

    reader = reader or decode.window_reader()
    res = ResourceSampler()
    res.start()

    frames_out: list[propagate.FrameOut] = []
    seg_records: list[dict] = []
    decode_cmds: list[dict] = []
    fidelity_rows: list[dict] = []
    map_invariant = {"checked": 0, "max_abs_diff": 0, "mismatch_frames": 0}
    max_resident = 0

    png_dir = os.path.join(MEDIA_DIR, "preencode", tag)
    map_dir = os.path.join(MEDIA_DIR, "samplemap", tag)
    conf_dir = os.path.join(MEDIA_DIR, "confidence", tag)
    if media:
        for d in (png_dir, map_dir, conf_dir):
            os.makedirs(d, exist_ok=True)

    for job in build_jobs(win):
        start, end = job["start"], job["end"]
        n = end - start + 1
        max_resident = max(max_resident, n)
        truth = reader.read(start, n)
        decode_cmds.extend(reader.commands[-1:])
        L = {"frame_id": start, "rgb": contract.load_keyframe(tag, start),
             "index_map": contract.load_index_mask(tag, start)}
        R = {"frame_id": end, "rgb": contract.load_keyframe(tag, end),
             "index_map": contract.load_index_mask(tag, end)} if not job["single_side"] else L
        for side in (L, R):
            counts = np.bincount(side["index_map"].ravel(), minlength=len(win["role_ids"]) + 1)
            side["active_idx"] = [i for i in range(1, len(win["role_ids"]) + 1)
                                  if counts[i] >= cfg["mask"]["min_role_area_px"]]
        bundles = {"frames": truth, "left": L, "right": R, "depth": depth}
        outs, seg = propagate.propagate_segment(tag, win, start, end, bundles, cfg, guides_on,
                                                single_side=job["single_side"])
        seg["guide_set"] = sorted(guides_on)
        seg_records.append(seg)
        print(f"    [{label}] {tag} segment {start}..{end} done "
              f"({len(outs)} frames, {time.time() - t_start:.1f}s elapsed)", flush=True)
        k0, k1 = job["keep"]
        for fo in outs:
            if not (k0 <= fo.frame_id <= k1):
                continue
            idx = fo.frame_id - start
            t_rgb = truth[idx]
            fid_row = {
                "frame_id": fo.frame_id,
                "pts": pts_of(fo.frame_id),
                "time_s": fo.frame_id / FPS,
                "owning_keyframe": fo.stats.get("owning_keyframe"),
                "all_fidelity": measure.fidelity(fo.out_rgb, t_rgb),
                "owner_region_fidelity": measure.fidelity(fo.out_rgb, t_rgb, fo.role_owner > 0)
                if (fo.role_owner > 0).any() else None,
                "outliers": measure.outlier_report(fo.out_rgb, t_rgb, fo.role_owner),
            }
            roles = {}
            for idx_r in sorted(set(fo.role_owner.ravel().tolist()) - {0}):
                m = fo.role_owner == idx_r
                roles[str(idx_r)] = {"role_id": win["role_ids"][idx_r - 1],
                                     "px": int(m.sum()),
                                     **measure.fidelity(fo.out_rgb, t_rgb, m)}
            fid_row["per_role_fidelity"] = roles
            if (fo.role_owner > 0).any():
                fid_row["structural"] = measure.structural(fo.out_rgb, t_rgb, L["rgb"], cfg)
            fidelity_rows.append(fid_row)

            if media:
                Image.fromarray(fo.out_rgb).save(
                    os.path.join(png_dir, f"{tag}_f{fo.frame_id}.png"), compress_level=1)
                Image.fromarray(fo.conf).save(
                    os.path.join(conf_dir, f"{tag}_f{fo.frame_id}.conf.png"), compress_level=1)
                np.savez_compressed(
                    os.path.join(map_dir, f"{tag}_f{fo.frame_id}.map.npz"),
                    side=fo.anchor_side, base_sx=fo.sx, base_sy=fo.sy,
                    owner_sx=fo.owner_sx, owner_sy=fo.owner_sy, owner=fo.role_owner,
                    alpha=fo.alpha, valid=fo.valid, conf=fo.conf,
                    frame_id=np.int32(fo.frame_id), owning_keyframe=np.int32(fo.stats["owning_keyframe"] or -1))
                # invariant: the persisted map alone reproduces the written pixels
                anchor = (L if fo.stats["owning_keyframe"] == L["frame_id"] else R)["rgb"].astype(np.float32)
                c_o, _ = guides.bilinear(anchor, np.stack([fo.owner_sx, fo.owner_sy], -1))
                c_b, _ = guides.bilinear(anchor, np.stack([fo.sx, fo.sy], -1))
                rec = np.clip(fo.alpha[..., None] * c_o + (1.0 - fo.alpha[..., None]) * c_b,
                              0, 255).astype(np.uint8)
                d = int(np.abs(rec.astype(np.int16) - fo.out_rgb.astype(np.int16)).max())
                map_invariant["checked"] += 1
                map_invariant["max_abs_diff"] = max(map_invariant["max_abs_diff"], d)
                map_invariant["mismatch_frames"] += int(d > 0)
            frames_out.append(fo)

    frames_out.sort(key=lambda f: f.frame_id)

    # ---- negatives measured on final pixels ---------------------------------
    contact = measure.contact_negatives(frames_out, tag)
    continuity = measure.continuity_negative(frames_out, tag)

    # ---- media: MP4 + audio + parity ---------------------------------------
    media_rec = {}
    if media:
        media_rec = pack_window_video(tag, win, frames_out, png_dir)

    resource = res.stop()
    wall = time.time() - t_start

    conf_means = [f.stats.get("conf_mean") for f in frames_out if f.stats.get("conf_mean") is not None]
    resets = [e for s in seg_records for e in s["resets"]]
    rec = {
        "tag": tag, "window_id": win["window_id"], "label": label,
        "guides_enabled": sorted(guides_on),
        "frames": len(frames_out),
        "frame_ids": [int(frames_out[0].frame_id), int(frames_out[-1].frame_id)],
        "expected_frames": win["frames"],
        "params_hash": P.params_hash(),
        "holdout": contract.holdout_guard(tag),
        "resources": {**resource, "walltime_s": round(wall, 3),
                      "frames_resident_max": max_resident,
                      "resident_ceiling": cfg["max_frames_resident"],
                      "media_bytes": dir_bytes(png_dir) + dir_bytes(map_dir) + dir_bytes(conf_dir)
                      if media else 0},
        "decode_commands": len(decode_cmds),
        "resets": resets,
        "reset_frames": sorted({e["frame_id"] for e in resets
                                if e["kind"] in ("annotated_cut", "measured_discontinuity")}),
        "segments": seg_records,
        "confidence": {
            "mean": round(float(np.mean(conf_means)), 6) if conf_means else None,
            "p05_of_frame_means": round(float(np.percentile(conf_means, 5)), 6) if conf_means else None,
            "min": round(float(min(conf_means)), 6) if conf_means else None,
            "persisted_per_sample": bool(media),
        },
        "fidelity": fidelity_rows,
        "negatives": {"GROUP_CONTACT": contact, "GROUP_CONTINUITY": continuity},
        "map_invariant": map_invariant,
        "media": media_rec,
        "verdict": None,
    }
    agg = aggregate(rec)
    rec["verdict"] = agg
    return rec


def aggregate(rec: dict) -> dict:
    fid = rec["fidelity"]
    all_mae = [r["all_fidelity"]["mae"] for r in fid]
    psnr = [r["all_fidelity"]["psnr_db"] for r in fid if r["all_fidelity"]["psnr_db"]]
    owner_mae = [r["owner_region_fidelity"]["mae"] for r in fid if r["owner_region_fidelity"]]
    struct = [r["structural"] for r in fid if r.get("structural", {}).get("ok")]
    frame_stats = [f for s in rec["segments"] for f in s["frames"]]
    owning = sorted({f.get("owning_keyframe") for f in frame_stats if f.get("owning_keyframe")})
    res = {
        "frames": len(fid),
        "mae_mean": round(float(np.mean(all_mae)), 6),
        "mae_p95": round(float(np.percentile(all_mae, 95)), 6),
        "mae_max": round(float(np.max(all_mae)), 6),
        "psnr_db_median": round(float(np.median(psnr)), 4) if psnr else None,
        "owner_region_mae_mean": round(float(np.mean(owner_mae)), 6) if owner_mae else None,
        "structural_frames": len(struct),
        "centre_err_pct_diag_median": round(float(np.median([s["centre_error_pct_diag"] for s in struct])), 6) if struct else None,
        "centre_err_pct_diag_p95": round(float(np.percentile([s["centre_error_pct_diag"] for s in struct], 95)), 6) if struct else None,
        "scale_rel_err_p95": round(float(np.percentile([s["scale_rel_error"] for s in struct], 95)), 6) if struct else None,
        "rotation_err_deg_p95": round(float(np.percentile([s["rotation_error_deg"] for s in struct], 95)), 6) if struct else None,
        "traj_point_err_pct_diag_p95": round(float(np.percentile(
            [s["traj_point_err_pct_diag_p95"] for s in struct], 95)), 6) if struct else None,
        "contact_status": rec["negatives"]["GROUP_CONTACT"]["status"],
        "continuity_status": rec["negatives"]["GROUP_CONTINUITY"]["status"],
        "conf_mean": rec["confidence"]["mean"],
        "conf_min_frame_mean": rec["confidence"]["min"],
        "reset_count": len(rec["reset_frames"]),
        "filled_frac_mean": round(float(np.mean([f["filled_frac"] for f in frame_stats])), 6),
        "chain_valid_frac_mean": round(float(np.mean([f["chain_valid_frac"] for f in frame_stats])), 6),
        "boundary_on_edge_frac_mean": round(float(np.mean(
            [f["boundary_on_edge_frac"] for f in frame_stats if f.get("boundary_on_edge_frac") is not None])), 6)
        if any(f.get("boundary_on_edge_frac") is not None for f in frame_stats) else None,
        "role_consistency_conflict_px_total": int(sum(f.get("role_consistency_conflict_px", 0) for f in frame_stats)),
        "edge_snapped_px_total": int(sum(f.get("edge_snapped_px", 0) for f in frame_stats)),
        "reconcile_conflict_frac_of_both_mean": round(float(np.mean(
            [f["reconcile_conflict_frac_of_both"] for f in frame_stats
             if f.get("reconcile_conflict_frac_of_both") is not None])), 6)
        if any(f.get("reconcile_conflict_frac_of_both") is not None for f in frame_stats) else None,
        "owning_keyframes_used": owning,
        "visibility_events_total": int(sum(len(f.get("visibility_events") or []) for f in frame_stats)),
        "visibility_event_examples": [e for f in frame_stats for e in (f.get("visibility_events") or [])][:10],
        "min_role_area_ratio": min([f["min_role_area_ratio"] for f in frame_stats
                                    if f.get("min_role_area_ratio") is not None], default=None),
        "unpropagated_frames": [f["frame_id"] for f in frame_stats
                                if f.get("status") == "UNPROPAGATED_NO_KEYFRAME_BEYOND_RESET"],
    }
    res["target_centre_median_ok"] = (res["centre_err_pct_diag_median"] is not None
                                      and res["centre_err_pct_diag_median"] <= 0.5)
    res["target_centre_p95_ok"] = (res["centre_err_pct_diag_p95"] is not None
                                   and res["centre_err_pct_diag_p95"] <= 1.0)
    res["target_scale_p95_ok"] = (res["scale_rel_err_p95"] is not None
                                  and res["scale_rel_err_p95"] <= 0.03)
    res["target_rotation_p95_ok"] = (res["rotation_err_deg_p95"] is not None
                                     and res["rotation_err_deg_p95"] <= 3.0)
    return res


# ------------------------------------------------------------------- packaging
def _ffmpeg(argv: list[str], cwd: str | None = None, note: str = "") -> dict:
    r = ledger.run(argv, cwd=cwd or os.getcwd(), note=note)
    if r["returncode"] != 0:
        raise RuntimeError(f"ffmpeg failed: {argv}\n{r['stderr'][-500:].decode('utf-8','replace')}")
    return r


def pack_window_video(tag: str, win: dict, frames: list, png_dir: str) -> dict:
    """Encode the pre-encode PNGs with source audio and measure parity + A/V drift."""
    out_dir = os.path.join(MEDIA_DIR, "clips")
    os.makedirs(out_dir, exist_ok=True)
    seq_dir = os.path.join(RUNTIME_ROOT, "seq", tag)
    if os.path.isdir(seq_dir):
        shutil.rmtree(seq_dir)
    os.makedirs(seq_dir, exist_ok=True)
    for i, fo in enumerate(sorted(frames, key=lambda f: f.frame_id)):
        src = os.path.join(png_dir, f"{tag}_f{fo.frame_id}.png")
        dst = os.path.join(seq_dir, f"f{i:05d}.png")
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
    film = contract.film_path()
    t0 = win["start_frame"] / FPS
    audio_dir = os.path.join(RUNTIME_ROOT, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    audio = os.path.join(audio_dir, f"{tag}.m4a")
    _ffmpeg(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-ss", f"{t0:.6f}", "-t", "4.0", "-i", film, "-vn", "-c:a", "aac", "-b:a", "128k", audio],
            note=f"source audio for {tag} (4.0 s from t={t0:.6f})")
    clip = os.path.join(out_dir, f"{tag}_4s.mp4")
    _ffmpeg(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-framerate", "30",
             "-i", os.path.join(seq_dir, "f%05d.png"), "-i", audio, "-c:v", "libx264", "-crf", "18",
             "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-shortest", clip],
            note=f"encode {tag} 4 s clip (120 frames + source audio)")
    probe = _ffmpeg(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                     "-show_entries", "stream=nb_read_frames,avg_frame_rate,width,height,start_time",
                     "-of", "json", clip], note=f"probe {tag} clip")
    probe_a = _ffmpeg(["ffprobe", "-v", "error", "-select_streams", "a:0",
                       "-show_entries", "stream=codec_name,sample_rate,channels,start_time,duration",
                       "-of", "json", clip], note=f"probe {tag} clip audio")
    # decoded parity: MP4 -> frames vs pre-encode PNG
    dec = decode.ChunkReader(clip, chunk=16)
    parity = []
    for fo in sorted(frames, key=lambda f: f.frame_id):
        arr = dec.read(0, 1, check_ceiling=False)
        png = np.asarray(Image.open(os.path.join(png_dir, f"{tag}_f{fo.frame_id}.png")).convert("RGB"))
        parity.append(float(np.abs(arr[0].astype(np.int16) - png.astype(np.int16)).mean()))
        break  # first frame only here; the full sweep is done by the parity tool
    return {
        "clip": clip,
        "clip_bytes": os.path.getsize(clip),
        "audio_m4a": audio,
        "probe_video": json.loads(probe["stdout"].decode()),
        "probe_audio": json.loads(probe_a["stdout"].decode()),
        "source_start_s": t0,
        "first_frame_parity_mae_decoded_vs_preencode": parity[0] if parity else None,
        "encode_dir": seq_dir,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--label", default="full")
    ap.add_argument("--guides", default=",".join(ALL_GUIDES))
    ap.add_argument("--media", action="store_true")
    a = ap.parse_args(argv)
    ledger.self_check()
    cfg = P.params()
    guides_on = {g.strip() for g in a.guides.split(",") if g.strip()}
    tags = [w["tag"] for w in contract.windows()] if a.all else a.tag
    out_dir = os.path.join(RUNS_DIR, a.label)
    os.makedirs(out_dir, exist_ok=True)
    reader = decode.window_reader()
    for tag in tags:
        rec = run_window(tag, cfg, guides_on, a.label, a.media, reader)
        with open(os.path.join(out_dir, f"{tag}.json"), "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=1, ensure_ascii=False)
        v = rec["verdict"]
        print(f"[{a.label}] {tag}: frames={rec['frames']} mae_mean={v['mae_mean']} "
              f"psnr_med={v['psnr_db_median']} conf={v['conf_mean']} resets={v['reset_count']} "
              f"contact={v['contact_status']} continuity={v['continuity_status']} "
              f"peak_rss={rec['resources']['peak_rss_mib']}MiB wall={rec['resources']['walltime_s']}s",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
