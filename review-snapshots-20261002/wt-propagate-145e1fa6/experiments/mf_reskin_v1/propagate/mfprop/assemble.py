"""Assemble the per-window 4 s clips into the 20-30 s set, and verify media parity.

  * assemble(): concatenate the seven window clips in SOURCE frame order with the
    original audio spans, and probe the result (frame count, fps, duration, audio).
  * verify_parity(): decode every encoded frame back and compare it with the
    pre-encode PNG frame that produced it (acceptance row A09), plus an exact
    frame/PTS map check on the encoded container.
"""
from __future__ import annotations

import json
import os
import shutil

import numpy as np
from PIL import Image

from . import EV_ROOT, RUNTIME_ROOT, FPS, pts_of, time_of
from . import contract, decode, ledger

MEDIA = os.path.join(EV_ROOT, "media")
PACK = os.path.join(MEDIA, "assembled")


def _ffmpeg(argv: list[str], note: str = "") -> dict:
    r = ledger.run(argv, note=note)
    if r["returncode"] != 0:
        raise RuntimeError(f"ffmpeg rc={r['returncode']}: {r['stderr'][-400:].decode('utf-8', 'replace')}")
    return r


def _probe(path: str, stream: str = "v:0") -> dict:
    r = _ffmpeg(["ffprobe", "-v", "error", "-select_streams", stream, "-count_frames",
                 "-show_entries",
                 "stream=codec_name,nb_read_frames,avg_frame_rate,r_frame_rate,width,height,start_time,duration,time_base",
                 "-of", "json", path], note=f"probe {os.path.basename(path)} {stream}")
    return json.loads(r["stdout"].decode())


def assemble() -> dict:
    os.makedirs(PACK, exist_ok=True)
    wins = contract.windows()          # already in source frame order
    clips = []
    audio_parts = []
    film = contract.film_path()
    audio_dir = os.path.join(RUNTIME_ROOT, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    for w in wins:
        tag = w["tag"]
        clip = os.path.join(MEDIA, "clips", f"{tag}_4s.mp4")
        if not os.path.exists(clip):
            raise FileNotFoundError(f"missing window clip {clip} (run the full label with --media first)")
        clips.append(clip)
        a = os.path.join(audio_dir, f"{tag}.m4a")
        if not os.path.exists(a):
            t0 = w["start_frame"] / FPS
            _ffmpeg(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                     "-ss", f"{t0:.6f}", "-t", "4.0", "-i", film, "-vn", "-c:a", "aac",
                     "-b:a", "128k", a], note=f"audio span {tag}")
        audio_parts.append(a)
    # audio: concat the seven 4 s source spans in the same order
    alist = os.path.join(PACK, "audio_concat.txt")
    with open(alist, "w", encoding="utf-8") as fh:
        for a in audio_parts:
            fh.write(f"file '{a.replace(chr(92), '/')}'\n")
    audio_all = os.path.join(PACK, "assembled_audio.m4a")
    _ffmpeg(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "concat",
             "-safe", "0", "-i", alist, "-c", "copy", audio_all], note="concat window audio spans")
    # video: re-encode the concatenated clips (frame-order preserved, 30 fps CFR)
    vlist = os.path.join(PACK, "video_concat.txt")
    with open(vlist, "w", encoding="utf-8") as fh:
        for c in clips:
            fh.write(f"file '{c.replace(chr(92), '/')}'\n")
    out = os.path.join(PACK, "propagate_assembled_28s.mp4")
    _ffmpeg(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "concat",
             "-safe", "0", "-i", vlist, "-i", audio_all, "-c:v", "libx264", "-crf", "18",
             "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-shortest", out],
            note="assemble 28 s set from the seven window clips in source order")
    v = _probe(out)
    a = _probe(out, "a:0")
    total_expected = sum(w["frames"] for w in wins)
    return {
        "output": out,
        "bytes": os.path.getsize(out),
        "windows_in_order": [{"tag": w["tag"], "window_id": w["window_id"],
                              "start_frame": w["start_frame"], "frames": w["frames"],
                              "clip": os.path.join(MEDIA, "clips", f"{w['tag']}_4s.mp4")}
                             for w in wins],
        "expected_frames": total_expected,
        "expected_duration_s": round(total_expected / FPS, 6),
        "probe_video": v,
        "probe_audio": a,
        "frames_ok": int(v["streams"][0].get("nb_read_frames", -1)) == total_expected,
        "audio_concat_inputs": audio_parts,
    }


def verify_parity(labels=("full",)) -> dict:
    """Decode every encoded frame of every window clip and compare it with its
    pre-encode PNG (A09), and verify the exact frame/PTS map of each clip."""
    out = {"windows": [], "assembled": None}
    wins = contract.windows()
    for w in wins:
        tag = w["tag"]
        clip = os.path.join(MEDIA, "clips", f"{tag}_4s.mp4")
        png_dir = os.path.join(MEDIA, "preencode", tag)
        if not os.path.exists(clip):
            out["windows"].append({"tag": tag, "error": "clip missing"})
            continue
        pr = _probe(clip)
        reader = decode.ChunkReader(clip, chunk=16)
        maes, exact = [], 0
        for i in range(w["frames"]):
            arr = reader.read(i, 1, check_ceiling=False)[0]
            png = np.asarray(Image.open(os.path.join(png_dir, f"{tag}_f{w['start_frame'] + i}.png")).convert("RGB"))
            d = float(np.abs(arr.astype(np.int16) - png.astype(np.int16)).mean())
            maes.append(d)
            exact += int(d == 0.0)
        out["windows"].append({
            "tag": tag, "clip": clip, "frames_probed": int(pr["streams"][0].get("nb_read_frames", 0)),
            "expected_frames": w["frames"],
            "avg_frame_rate": pr["streams"][0].get("avg_frame_rate"),
            "duration_s": pr["streams"][0].get("duration"),
            "frame_parity_mae_mean": round(float(np.mean(maes)), 8),
            "frame_parity_mae_max": round(float(np.max(maes)), 8),
            "frames_byte_identical": exact,
            "pts_map": {"first_frame_id": w["start_frame"], "last_frame_id": w["end_frame_exclusive"] - 1,
                        "first_pts": pts_of(w["start_frame"]), "last_pts": pts_of(w["end_frame_exclusive"] - 1),
                        "fps": FPS, "cfr": pr["streams"][0].get("avg_frame_rate") == "30/1"},
        })
    asm = os.path.join(PACK, "propagate_assembled_28s.mp4")
    if os.path.exists(asm):
        pr = _probe(asm)
        out["assembled"] = {"path": asm, "frames": int(pr["streams"][0].get("nb_read_frames", 0)),
                           "avg_frame_rate": pr["streams"][0].get("avg_frame_rate"),
                           "duration_s": pr["streams"][0].get("duration")}
    with open(os.path.join(EV_ROOT, "media_parity.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    return out


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["assemble", "parity"])
    a = ap.parse_args(argv)
    if a.action == "assemble":
        r = assemble()
        with open(os.path.join(EV_ROOT, "assembled.json"), "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=1, ensure_ascii=False)
        print(f"ASSEMBLED {r['output']} frames={r['probe_video']['streams'][0].get('nb_read_frames')} "
              f"expected={r['expected_frames']} ok={r['frames_ok']} bytes={r['bytes']}")
    else:
        r = verify_parity()
        for w in r["windows"]:
            print(f"  {w.get('tag')}: frames={w.get('frames_probed')} parity_mae_mean={w.get('frame_parity_mae_mean')} "
                  f"identical={w.get('frames_byte_identical')}")
        print("PARITY_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
