"""MF-V1-BENCH wave B (round 2) - CPU evaluation of the FROZEN M1 candidate.

Reads ONLY frozen subtrees:
  * manager/frozen/M1_book4s_animate2/M1_book4s_animate2/**   (this round's candidate)
  * manager/frozen/BOOK_animate2_waveB/**                     (old submitted candidate, prior freeze)
  * manager/frozen/BOOK_animate2_waveA_inputs/**              (source window, prior freeze)
  * the pinned source film (read-only)
No GPU, no engine, no model, no re-render, no network. Every measurement is a measurement,
never a quality score: there is no visual verdict on this route.

Writes (all inside the round's own evidence root, never a submitted packet):
  <NEW>/BENCH/raw/m1_preflight.json      input rehash + git + ledger-before hashes
  <NEW>/BENCH/raw/m1_eval_book.json      every row + numbers + positive controls
  <NEW>/BENCH/raw/cmd_transcript.jsonl   this round's ledger (append, per-run header)

The harness's own candidate step is executed as a child process with MF_BENCH_LEDGER named
explicitly, so run_dryrun.py cannot fall back onto a submitted packet's ledger (F10 c3).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

WT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/wt-bench")
BENCH_SRC = WT / "experiments" / "mf_reskin_v1" / "bench"
sys.path.insert(0, str(BENCH_SRC))
import common as C          # noqa: E402
import compare as CMP       # noqa: E402

NEW = Path("C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/"
           "mf-core-tool-delivery-20260923/20260923T1535Z")
CORR = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
            "mf-reskin-correction-20260922/20260922T0955Z")
WAVE12 = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
              "mf-reskin-model-upgrade-20260922/20260922T0345Z")

M1FREEZE = NEW / "manager" / "frozen" / "M1_book4s_animate2" / "M1_book4s_animate2"
M1 = M1FREEZE / "files" / "waveB_m1"
CAND = M1 / "clip" / "final_book4s_m1_decoded119_640x360.mp4"
SRC_FROZEN = M1 / "review" / "source_window_120f.mp4"
PAD368 = M1 / "review" / "source_conditioning_padded_121f_640x368.mp4"
OLD_FREEZE = CORR / "manager" / "frozen" / "BOOK_animate2_waveB"
OLDC = OLD_FREEZE / "files" / "final_book4s_decoded119_640x360.mp4"
SRC_ALT_FREEZE = CORR / "manager" / "frozen" / "BOOK_animate2_waveA_inputs"
SRC_ALT = SRC_ALT_FREEZE / "files" / "src_windows" / "BOOK_src.mp4"
FILM = C.REF_FILM

RAW = NEW / "BENCH" / "raw"
WORK = NEW / "BENCH" / "work" / "m1_scratch"
LEDGER = RAW / "cmd_transcript.jsonl"
C.set_ledger_path(LEDGER)

CAND_SHA = "5C2175AE73056EA6552B7B50432F618F7255A09F7CF9E5C695A870FE22286A6D"
OLDC_SHA = "55DAEF67162601A073A2F9DE0988B95008B08CBE16E4A36F5567981DBA776D04"
WSF = 1650                      # film frame the BOOK window starts on
NF = 120
# submitted evidence packets that may NOT grow (their ledgers are hashed before/after)
PROTECTED_LEDGERS = [CORR / "BENCH" / "raw" / "cmd_transcript.jsonl",
                     WAVE12 / "BENCH" / "raw" / "cmd_transcript.jsonl"]


def sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_p(p) -> str:
    return C.sha256_file(p)


def file_facts(p) -> dict:
    p = Path(p)
    return {"path": str(p), "exists": p.exists(),
            "bytes": p.stat().st_size if p.exists() else None,
            "sha256": sha_p(p) if p.exists() else None}


# --------------------------------------------------------------------------- #
# 0. preflight: rehash every frozen input, film pin, git state, ledger-before
# --------------------------------------------------------------------------- #

def rehash_freeze(freeze_dir) -> dict:
    """Re-hash a freeze against ITS OWN manifest, hashing the manifest's `frozen` field."""
    man = Path(freeze_dir) / "FREEZE_MANIFEST.json"
    d = json.loads(man.read_text(encoding="utf-8"))
    rows, mismatch, missing = [], [], []
    total = 0
    for f in d["files"]:
        p = Path(f["frozen"])
        want = str(f["sha256"]).strip().lower()
        if not p.exists():
            missing.append(f["rel"])
            rows.append({"rel": f["rel"], "state": "MISSING", "want": want, "got": None})
            continue
        got = sha_p(p)
        total += p.stat().st_size
        ok = got == want
        if not ok:
            mismatch.append(f["rel"])
        rows.append({"rel": f["rel"], "state": "OK" if ok else "HASH_MISMATCH",
                     "want": want, "got": got, "bytes": p.stat().st_size})
    return {"freeze": str(freeze_dir), "freeze_id": d.get("freeze_id"),
            "manifest_hash_mismatch_field": d.get("hash_mismatch"),
            "files": len(d["files"]), "bytes_total": total,
            "sha256_mismatch": len(mismatch), "missing": len(missing),
            "mismatch_rels": mismatch, "missing_rels": missing,
            "all_ok": not mismatch and not missing, "rows": rows}


def git_facts() -> dict:
    def g(*args):
        rc, out, err = C.run(["git", *args], cwd=str(WT), label="git " + " ".join(args))
        return {"exit": rc, "out": out.strip(), "err": err.strip()[:200]}
    return {"head": g("rev-parse", "HEAD")["out"], "head_short": g("rev-parse", "--short", "HEAD")["out"],
            "head_parent": g("rev-parse", "HEAD^")["out"],
            "branch": g("rev-parse", "--abbrev-ref", "HEAD")["out"],
            "porcelain": g("status", "--porcelain")["out"],
            "remotes_containing_head": g("branch", "-r", "--contains", "HEAD")["out"]}


def ledger_snapshot(paths) -> dict:
    out = {}
    for p in paths:
        p = Path(p)
        if p.exists():
            b = p.read_bytes()
            out[str(p)] = {"exists": True, "bytes": len(b), "lines": b.count(b"\n"), "sha256": sha_b(b)}
        else:
            out[str(p)] = {"exists": False, "bytes": 0, "lines": 0, "sha256": None}
    return out


print("[m1] preflight: rehashing frozen inputs")
RAW.mkdir(parents=True, exist_ok=True)
pre = {"artifact": "m1_preflight.json", "task_id": "MF-V1-BENCH", "wave": "B (round 2, M1 candidate)",
       "run_id": C.RUN_ID, "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
       "freezes": {}, "inputs": {}, "film_pin": {}, "git": git_facts(),
       "ledger_before": ledger_snapshot(PROTECTED_LEDGERS),
       "own_ledger": str(LEDGER),
       "harness_source": str(BENCH_SRC)}

for name, d in (("M1_book4s_animate2", M1FREEZE), ("BOOK_animate2_waveB", OLD_FREEZE),
                ("BOOK_animate2_waveA_inputs", SRC_ALT_FREEZE)):
    r = rehash_freeze(d)
    r.pop("rows")
    pre["freezes"][name] = r
    print("[m1]   %-28s %3d files, mismatch=%d missing=%d" % (name, r["files"], r["sha256_mismatch"], r["missing"]))

pre["inputs"] = {"candidate_clip": file_facts(CAND), "source_window_frozen_m1": file_facts(SRC_FROZEN),
                 "source_window_frozen_waveA_inputs": file_facts(SRC_ALT),
                 "padding_render_640x368_121f": file_facts(PAD368), "old_candidate_clip": file_facts(OLDC)}
pre["inputs"]["candidate_clip"]["sha_matches_packet"] = pre["inputs"]["candidate_clip"]["sha256"] == CAND_SHA.lower()
pre["inputs"]["old_candidate_clip"]["sha_matches_packet"] = pre["inputs"]["old_candidate_clip"]["sha256"] == OLDC_SHA.lower()
film_sha = sha_p(FILM)
pre["film_pin"] = {"path": str(FILM), "bytes": FILM.stat().st_size, "sha256": film_sha,
                   "pinned_sha256": C.REF_FILM_SHA, "matches_pin": film_sha == C.REF_FILM_SHA}
print("[m1]   candidate sha ok=%s | old candidate sha ok=%s | film pin ok=%s"
      % (pre["inputs"]["candidate_clip"]["sha_matches_packet"],
         pre["inputs"]["old_candidate_clip"]["sha_matches_packet"], pre["film_pin"]["matches_pin"]))
C.write_json(RAW / "m1_preflight.json", pre)


# --------------------------------------------------------------------------- #
# 1. harness candidate step (child process, ledger named explicitly)
# --------------------------------------------------------------------------- #

def run_harness() -> dict:
    env = dict(os.environ)
    env["MF_BENCH_LEDGER"] = str(LEDGER)          # explicit: never a default into a packet
    env["MF_BENCH_EV_OUT"] = str(NEW / "BENCH")
    env["MF_BENCH_WORK"] = str(WORK)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    argv = [sys.executable, "run_dryrun.py", "--steps", "candidate",
            "--candidate", str(CAND), "--source-clip", str(SRC_FROZEN),
            "--window-tag", "BOOK", "--expected-frames", str(NF)]
    t0 = time.time()
    proc = subprocess.run(argv, cwd=str(BENCH_SRC), env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout.decode("utf-8", "replace")
    (RAW / "m1_harness_candidate.stdout.txt").write_text(out, encoding="utf-8")
    return {"argv": argv, "cwd": str(BENCH_SRC), "exit_code": proc.returncode,
            "wall_s": round(time.time() - t0, 3),
            "env_forced": {"MF_BENCH_LEDGER": str(LEDGER), "MF_BENCH_EV_OUT": str(NEW / "BENCH"),
                           "MF_BENCH_WORK": str(WORK)},
            "stdout_path": str(RAW / "m1_harness_candidate.stdout.txt"),
            "stdout_tail": out.strip().splitlines()[-14:]}


print("[m1] harness: run_dryrun.py --steps candidate (child, explicit ledger)")
H = run_harness()
print("[m1]   exit=%s wall=%ss" % (H["exit_code"], H["wall_s"]))
HARNESS_JSON = RAW / "candidate_BOOK.json"
hj = json.loads(HARNESS_JSON.read_text(encoding="utf-8"))
ASSERT = {a["assertion"]: a for a in hj["assertions"]}
H["wrote"] = file_facts(HARNESS_JSON)
H["harness_technical_verdict"] = hj["technical_verdict"]
H["harness_visual_verdict"] = hj["visual_verdict"]


# --------------------------------------------------------------------------- #
# decode helpers (all external commands go through C.run/C.run_bytes -> ledger)
# --------------------------------------------------------------------------- #

def pcm_interleaved(path, ss=None, t=None):
    argv = ["ffmpeg", "-v", "error"]
    if ss is not None:
        argv += ["-ss", "%.6f" % ss]
    argv += ["-i", str(path)]
    if t is not None:
        argv += ["-t", "%.6f" % t]
    argv += ["-vn", "-acodec", "pcm_s16le", "-ac", "2", "-ar", "44100", "-f", "s16le", "-"]
    raw = C.run_bytes(argv, label="pcm %s ss=%s t=%s" % (Path(path).name, ss, t))
    a = np.frombuffer(raw, dtype="<i2")
    if a.size % 2:
        a = a[:-1]
    return raw, a.reshape(-1, 2)


def compare_pcm(c, f):
    n = min(len(c), len(f))
    d = np.abs(c[:n].astype(np.int32) - f[:n].astype(np.int32))
    return {"compared_samples_total": int(n * 2), "mae_int16_levels": round(float(d.mean()), 8),
            "max_abs_diff_int16": int(d.max()), "mismatch_count_samples": int((d != 0).sum()),
            "identical_fraction": round(float((d == 0).mean()), 8), "bit_exact": bool((d == 0).all())}


def stream_json(path, entries):
    rc, out, err = C.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)],
                         label="ffprobe " + Path(path).name)
    if rc != 0:
        raise SystemExit("ffprobe failed: %s" % err[-300:])
    return json.loads(out)


def gray_frame(path, w, h, select=None, n=None):
    argv = ["ffmpeg", "-v", "error", "-i", str(path)]
    vf = []
    if select:
        vf.append("select='%s'" % select)
    vf += ["scale=%d:%d" % (w, h), "format=gray"]
    argv += ["-vf", ",".join(vf)]
    if select:
        argv += ["-vsync", "0"]
    if n:
        argv += ["-frames:v", str(n)]
    argv += ["-f", "rawvideo", "-pix_fmt", "gray", "-"]
    buf = C.run_bytes(argv, label="gray %s w=%d h=%d sel=%s n=%s" % (Path(path).name, w, h, select, n))
    cnt = len(buf) // (w * h)
    return np.frombuffer(buf[:cnt * w * h], dtype=np.uint8).reshape(cnt, h, w)


def pairing_ext(a, b, radius=15):
    n = min(len(a), len(b))
    curve = {}
    for off in range(-radius, radius + 1):
        vals = [float(np.abs(a[i].astype(np.int16) - b[i + off].astype(np.int16)).mean())
                for i in range(n) if 0 <= i + off < len(b)]
        curve[off] = round(float(np.median(vals)), 6) if vals else None
    usable = {k: v for k, v in curve.items() if v is not None}
    best = min(usable, key=lambda k: usable[k])
    others = [v for k, v in usable.items() if k != best]
    return {"curve": curve, "argmin": best, "argmin_value": usable[best],
            "margin_over_runner_up": round(usable[best] - min(others), 6),
            "curve_min": min(usable.values()), "curve_max": max(usable.values()),
            "spread": round(max(usable.values()) - min(usable.values()), 6),
            "median_absdiff": usable.get(0),
            "advantage_of_offset0": round(min(others) - usable.get(0), 6) if usable.get(0) is not None else None}


def cuts(arr, thresh=40.0):
    if len(arr) < 2:
        return []
    d = CMP.per_frame_absdiff(arr[:-1], arr[1:])
    return [int(i + 1) for i in np.where(d > thresh)[0]]


# --------------------------------------------------------------------------- #
# 2. rows from the harness, re-read from the harness's own output
# --------------------------------------------------------------------------- #

PACKET_ROWS = ["video_codec_contract", "duration_contract", "frame_count_exact",
               "non_degenerate_frames", "not_frozen", "not_source_copy", "audio_contract",
               "cut_timeline", "frame_pairing"]
rows = {k: {"harness_verdict": ASSERT[k]["verdict"], "rule": ASSERT[k]["rule"],
            "measured": ASSERT[k]["measured"],
            "declared_negative_control": ASSERT[k].get("negative_control")} for k in PACKET_ROWS}
rows["pts_contract"] = {"harness_verdict": ASSERT["pts_contract"]["verdict"],
                        "rule": ASSERT["pts_contract"]["rule"],
                        "measured": ASSERT["pts_contract"]["measured"],
                        "declared_negative_control": ASSERT["pts_contract"].get("negative_control")}


# --------------------------------------------------------------------------- #
# 3. geometry / codec  (row: video_codec_contract, 640x360; the 368 defect must not return)
# --------------------------------------------------------------------------- #
print("[m1] geometry: clip vs the 640x368 padding render")
cv = stream_json(CAND, "stream=index,codec_type,codec_name,profile,width,height,pix_fmt,time_base,"
                       "r_frame_rate,avg_frame_rate,nb_frames,duration,start_pts,start_time,"
                       "sample_rate,channels,channel_layout,bit_rate")
vid = [s for s in cv["streams"] if s["codec_type"] == "video"][0]
aud = [s for s in cv["streams"] if s["codec_type"] == "audio"]
pv = stream_json(PAD368, "stream=codec_type,codec_name,width,height,nb_frames,duration")
pvid = [s for s in pv["streams"] if s["codec_type"] == "video"][0]

geom = {"clip": {k: vid.get(k) for k in ("codec_name", "profile", "width", "height", "pix_fmt",
                                         "time_base", "r_frame_rate", "avg_frame_rate",
                                         "nb_frames", "duration", "start_pts", "start_time")},
        "declared_contract_wh": [640, 360],
        "geometry_ok": [vid.get("width"), vid.get("height")] == [640, 360],
        "old_368_defect_present": vid.get("height") == 368,
        "old_368_defect_would_be": "640x368 (+8 rows, +2.2222% vertical)",
        "codec_ok": vid.get("codec_name") == "h264",
        "nb_frames_ok": str(vid.get("nb_frames")) == "120",
        "timebase_ok": vid.get("time_base") == "1/%d" % C.TIMEBASE_DEN,
        "rate_ok": vid.get("r_frame_rate") == "30/1" and vid.get("avg_frame_rate") == "30/1",
        "padding_render": {k: pvid.get(k) for k in ("codec_name", "width", "height", "nb_frames", "duration")},
        "cli_stream_count": len(cv["streams"]),
        "cli_streams": [{"index": s.get("index"), "codec_type": s.get("codec_type"),
                         "codec_name": s.get("codec_name")} for s in cv["streams"]]}
pc = ASSERT["pts_contract"]["measured"]
geom["pts"] = {"first_pts": pc["first_pts"], "last_pts": pc["last_pts"], "timebase_den": pc["timebase_den"],
               "ticks_per_frame": pc["ticks_per_frame"], "sampled_frames": pc["sampled_frames"],
               "expected_first": 0, "expected_last": (NF - 1) * C.TICKS_PER_FRAME,
               "violations": pc["violations"],
               "first_ok": pc["first_pts"] == 0, "last_ok": pc["last_pts"] == (NF - 1) * C.TICKS_PER_FRAME,
               "rule_ok": all(int(x) == 0 for x in pc["violations"].values()) and pc["sampled_frames"] > 0}
rows["video_codec_contract"]["independent"] = geom
rows["video_codec_contract"]["disposition"] = (
    "PASS" if all([geom["geometry_ok"], geom["codec_ok"], geom["nb_frames_ok"], geom["timebase_ok"],
                   geom["rate_ok"], geom["pts"]["first_ok"], geom["pts"]["last_ok"], geom["pts"]["rule_ok"]])
    else "FAIL")
rows["pts_contract"]["disposition"] = ASSERT["pts_contract"]["verdict"]

# ---- content rect of the padding render vs the clip (diagnostic, not a pass) ----
pad = (pvid["height"] - vid["height"]) // 2
clip_f0 = gray_frame(CAND, vid["width"], vid["height"], n=1)[0].astype(np.int16)
raw_f0 = gray_frame(PAD368, pvid["width"], pvid["height"], n=1)[0].astype(np.int16)
ycurve = {y: round(float(np.abs(clip_f0 - raw_f0[y:y + vid["height"]]).mean()), 6)
          for y in range(0, pvid["height"] - vid["height"] + 1)}
best_y = min(ycurve, key=lambda k: ycurve[k])
geom["content_rect"] = {"declared_pad_px_per_side": pad, "measured_offset_y": best_y,
                        "mae_at_measured": ycurve[best_y], "mae_at_zero": ycurve[0],
                        "mae_at_declared": ycurve[pad], "scan_y": ycurve,
                        "measured_equals_declared": best_y == pad,
                        "note": "diagnostic only: where the 640x360 frame sits inside the 640x368 render"}


# --------------------------------------------------------------------------- #
# 4. audio, decoded on both sides - THREE separate labels
# --------------------------------------------------------------------------- #
print("[m1] audio: decode candidate + film window")
cand_b4, cand4 = pcm_interleaved(CAND, t=4.0)
film_b4, film4 = pcm_interleaved(FILM, ss=55.0, t=4.0)
A_row = {"label": "A_first_4s_bit_exactness",
         "definition": "candidate decoded with -t 4.000000 (no seek) vs film [55.000, 59.000), 4.000000 s",
         "candidate": {"decode": "-t 4.000000", "samples_per_channel": int(len(cand4)),
                       "total_samples_2ch": int(cand4.size), "pcm_sha256": sha_b(cand_b4)},
         "film_window": {"decode": "-ss 55.000000 -t 4.000000", "samples_per_channel": int(len(film4)),
                         "total_samples_2ch": int(film4.size), "pcm_sha256": sha_b(film_b4)}}
A_row.update(compare_pcm(cand4, film4))
A_row["pcm_sha_equal"] = A_row["candidate"]["pcm_sha256"] == A_row["film_window"]["pcm_sha256"]

cand_full_b, cand_full = pcm_interleaved(CAND)
film_full_b, film_full = pcm_interleaved(FILM, ss=55.0, t=4.001995)
cmp_full = compare_pcm(cand_full, film_full)
B_row = {"label": "B_pre_aac_edge_sample_count",
         "definition": "the sample count the decoder emits for the candidate's whole audio stream "
                       "(the AAC stream edge), compared with the film decoded over the same 4.001995 s span",
         "candidate_samples_per_channel": int(len(cand_full)),
         "candidate_seconds": round(len(cand_full) / 44100.0, 6),
         "candidate_pcm_sha256": sha_b(cand_full_b),
         "content_samples_per_channel_from_A": int(len(cand4)),
         "edge_padding_samples_per_channel": int(len(cand_full) - len(cand4)),
         "film_same_span_samples_per_channel": int(len(film_full)),
         "decoded_delta_samples_per_channel": int(len(cand_full) - len(film_full)),
         "decoded_delta_ms": round((len(cand_full) - len(film_full)) / 44.1, 6),
         "compared_samples_total": cmp_full["compared_samples_total"],
         "bit_exact_over_compared": cmp_full["bit_exact"],
         "mismatch_count_samples": cmp_full["mismatch_count_samples"],
         "mae_int16_levels": cmp_full["mae_int16_levels"]}
tail = film_full[len(cand_full):] if len(film_full) > len(cand_full) else None
B_row["film_tail_beyond_candidate"] = None if tail is None else {
    "samples_per_channel": int(len(tail)), "pcm_sha256": sha_b(tail.tobytes())}
C_row = {"label": "C_container_tail",
         "definition": "container-level stream durations (NOT decoded samples): the audio stream runs "
                       "past the 4.000000 s of video content by the AAC container padding",
         "container_audio_duration_s": float(aud[0]["duration"]) if aud else None,
         "container_video_duration_s": float(vid["duration"]),
         "container_delta_audio_minus_video_ms": round((float(aud[0]["duration"]) - float(vid["duration"])) * 1000.0, 6) if aud else None,
         "container_minus_requested_4s_ms": round((float(aud[0]["duration"]) - 4.0) * 1000.0, 6) if aud else None,
         "format_duration_s": stream_json(CAND, "format=duration")["format"]["duration"],
         "audio_nb_frames_packets": aud[0].get("nb_frames") if aud else None,
         "audio_sample_rate": aud[0].get("sample_rate") if aud else None,
         "audio_channels": aud[0].get("channels") if aud else None,
         "container_tail_samples_per_channel": round((float(aud[0]["duration"]) - 4.0) * 44100.0, 3) if aud else None,
         "note": "three different measurements: A = content samples, B = decoded samples at the AAC edge, "
                 "C = container duration. B and C differ by construction."}
audio = {"A": A_row, "B": B_row, "C": C_row,
         "harness_row": rows["audio_contract"]["measured"],
         "harness_verdict": rows["audio_contract"]["harness_verdict"]}
rows["audio_contract"]["independent"] = audio
rows["audio_contract"]["disposition"] = ASSERT["audio_contract"]["verdict"]


# --------------------------------------------------------------------------- #
# 5. motion / provenance rows measured against the source window
# --------------------------------------------------------------------------- #
print("[m1] source-window identity + pairing power")
src_alt_bytes, src_alt = pcm_interleaved(SRC_ALT)
src_frozen_bytes, src_frozen_pcm = pcm_interleaved(SRC_FROZEN)
n = min(len(src_alt), len(src_frozen_pcm))
if n == 0:
    src_pcm_ident = {"measured": False, "reason": "one side has no audio stream"}
else:
    d = np.abs(src_alt[:n].astype(np.int32) - src_frozen_pcm[:n].astype(np.int32))
    src_pcm_ident = {"measured": True, "compared_samples_total": int(n * 2),
                     "identical": bool((d == 0).all()), "mismatch_count_samples": int((d != 0).sum())}

cand_native = gray_frame(CAND, vid["width"], vid["height"], n=NF)
srcf_native = gray_frame(SRC_FROZEN, vid["width"], vid["height"], n=NF)
src_alt_native = gray_frame(SRC_ALT, vid["width"], vid["height"], n=NF)
old_native = gray_frame(OLDC, 640, 360, n=NF)
film_win = gray_frame(FILM, vid["width"], vid["height"], select="between(n\\,%d\\,%d)" % (WSF, WSF + NF - 1))
film_win_p5 = gray_frame(FILM, vid["width"], vid["height"], select="between(n\\,%d\\,%d)" % (WSF + 5, WSF + NF + 4))

d_frozen_vs_alt = CMP.delta_facts(srcf_native, src_alt_native)
pair = {"metric": "whole-clip median per-frame |delta| vs frame offset, NATIVE %dx%d" % (vid["width"], vid["height"]),
        "harness_rule": rows["frame_pairing"]["rule"],
        "candidate_vs_source_window": pairing_ext(cand_native, srcf_native),
        "candidate_vs_source_window_alt_copy": pairing_ext(cand_native, src_alt_native),
        "old_candidate_vs_source_window": pairing_ext(old_native, srcf_native),
        "positive_control_known_0_shift_source_vs_film_window": pairing_ext(srcf_native, film_win),
        "positive_control_known_5_shift_film_plus5_vs_film_window": pairing_ext(film_win_p5, film_win),
        "source_window_frozen_vs_waveA_inputs_copy": d_frozen_vs_alt,
        "source_window_frozen_vs_waveA_inputs_pcm": src_pcm_ident,
        "film_window_frames_decoded": int(len(film_win)),
        "note": "a candidate deviation is only readable as a frame shift if the two positive controls show the "
                "curve CAN resolve 0 and +5 on this content; the controls are built from the film itself"}

# cut_timeline: does the BOOK window contain a hard cut at all?
clip_cuts, src_cuts = cuts(cand_native), cuts(srcf_native)
c660 = C.RUNTIME / "src_windows" / "CUT_660_src.mp4"
c660_native = gray_frame(c660, vid["width"], vid["height"], n=NF) if c660.exists() else np.zeros((0,), np.uint8)
c660_cuts = cuts(c660_native) if len(c660_native) else []
cut = {"candidate_cut_frame_offsets": clip_cuts, "source_cut_frame_offsets": src_cuts,
       "cut_threshold_mae": 40.0,
       "window_has_a_cut": bool(clip_cuts or src_cuts),
       "positive_control_window": str(c660),
       "positive_control_exists": c660.exists(),
       "positive_control_cut_frame_offsets": c660_cuts,
       "positive_control_frames": int(len(c660_native)),
       "note": "cut_timeline compares cut OFFSETS; with no cut in either side the comparison is empty and "
               "has no discriminating power (UNMEASURED, never PASS). The positive control is a window of the "
               "same film that DOES contain a hard cut - it proves the detector fires when a cut exists."}

# per-frame change, new vs old, and both vs source (measurements, not scores)
change = {"new_vs_old": CMP.delta_facts(cand_native, old_native),
          "new_vs_source": CMP.delta_facts(cand_native, srcf_native),
          "old_vs_source": CMP.delta_facts(old_native, srcf_native),
          "note": "diagnostic reconstruction deltas in grey levels; NOT quality scores"}

rows["frame_pairing"]["independent"] = pair
rows["cut_timeline"]["independent"] = cut
rows["not_source_copy"]["independent"] = change["new_vs_source"]

# dispositions for the two rows that can legitimately lack discriminating power
adv = pair["candidate_vs_source_window"]["advantage_of_offset0"]
floor = 0.01
c0_ok = pair["positive_control_known_0_shift_source_vs_film_window"]["argmin"] == 0
c5_ok = pair["positive_control_known_5_shift_film_plus5_vs_film_window"]["argmin"] == 5
if not (c0_ok and c5_ok):
    pairing_disp = "UNMEASURED"
    pairing_why = ("the positive controls do not resolve 0 and +5 on this content, so the row's own "
                   "measurement has no calibrated meaning")
elif adv is not None and adv >= floor:
    pairing_disp, pairing_why = "PASS", ("offset 0 is the strict minimum of the whole-clip curve "
                                         "(advantage %.6f >= floor %.2f)" % (adv, floor))
elif adv is not None and adv <= -floor:
    pairing_disp, pairing_why = "FAIL", ("curve minimised at offset %s; offset 0 is worse by %.6f"
                                         % (pair["candidate_vs_source_window"]["argmin"], -adv))
else:
    pairing_disp, pairing_why = "UNMEASURED", (
        "flat offset curve (advantage of offset 0 %.6f is inside +-floor %.2f; spread over offsets %s): a "
        "near-identical reconstruction cannot resolve an alignment on this window - never PASS"
        % (adv, floor, pair["candidate_vs_source_window"]["spread"]))
rows["frame_pairing"]["disposition"] = pairing_disp
rows["frame_pairing"]["disposition_reason"] = pairing_why
rows["cut_timeline"]["disposition"] = "UNMEASURED" if not cut["window_has_a_cut"] else ASSERT["cut_timeline"]["verdict"]
rows["cut_timeline"]["disposition_reason"] = (
    "no hard cut measured in the candidate (%s) or in the source window (%s): the offset comparison is empty, "
    "so this measurement has no discriminating power on this window"
    % (clip_cuts, src_cuts)) if not cut["window_has_a_cut"] else \
    "cut offsets measured on both sides: %s vs %s" % (clip_cuts, src_cuts)

for k in ("frame_count_exact", "non_degenerate_frames", "not_frozen", "not_source_copy",
          "duration_contract", "video_codec_contract", "audio_contract", "pts_contract"):
    rows[k].setdefault("disposition", ASSERT[k]["verdict"])


# --------------------------------------------------------------------------- #
# 6. ledger isolation: hash every protected packet ledger again after the run
# --------------------------------------------------------------------------- #
ledger_after = ledger_snapshot(PROTECTED_LEDGERS)
iso = {"protected_ledgers": {k: {"before": pre["ledger_before"][k], "after": ledger_after[k],
                                 "bytes_appended": ledger_after[k]["bytes"] - pre["ledger_before"][k]["bytes"],
                                 "sha_unchanged": ledger_after[k]["sha256"] == pre["ledger_before"][k]["sha256"]}
                             for k in ledger_after},
       "own_ledger": {"path": str(LEDGER), "exists": LEDGER.exists(),
                      "bytes": LEDGER.stat().st_size if LEDGER.exists() else 0},
       "zero_appended_to_submitted_packets": all(
           v["bytes_appended"] == 0 and v["sha_unchanged"] for v in
           [{"bytes_appended": ledger_after[k]["bytes"] - pre["ledger_before"][k]["bytes"],
             "sha_unchanged": ledger_after[k]["sha256"] == pre["ledger_before"][k]["sha256"]} for k in ledger_after])}

rec = {"artifact": "m1_eval_book.json", "task_id": "MF-V1-BENCH",
       "wave": "B (round 2) - CPU evaluation of the frozen M1 candidate",
       "kind": "measurement_not_quality_score", "run_id": C.RUN_ID,
       "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
       "no_visual_verdict": {"route": "no vision on this route", "reference": "NOT_VISUALLY_APPROVED",
                             "semantic_rows": "NOT_REVIEWED", "quality_accepted": 0,
                             "accepted_seconds": 0,
                             "cost_per_accepted_second": "undefined (accepted seconds = 0)"},
       "frozen_inputs": {"candidate_clip": file_facts(CAND), "source_window": file_facts(SRC_FROZEN),
                         "source_window_alt": file_facts(SRC_ALT), "old_candidate": file_facts(OLDC),
                         "padding_render": file_facts(PAD368), "film": file_facts(FILM)},
       "harness": H, "harness_verdicts": {k: ASSERT[k]["verdict"] for k in ASSERT},
       "rows": rows, "E2_audio": audio, "E3_geometry": geom, "E4_pairing": pair, "E5_cut": cut,
       "E6_change": change, "ledger_isolation": iso}
C.write_json(RAW / "m1_eval_book.json", rec)
C.flush_ledger()

print("[m1] rows:")
for k in ["video_codec_contract", "duration_contract", "frame_count_exact", "non_degenerate_frames",
          "not_frozen", "not_source_copy", "audio_contract", "cut_timeline", "frame_pairing", "pts_contract"]:
    r = rows[k]
    print("  %-24s harness=%-11s disposition=%-11s" % (k, r["harness_verdict"], r.get("disposition")))
print("[m1] audio A bit_exact=%s (%d samples/ch) | B cand=%d film=%d delta=%+d | C container delta=%s ms"
      % (A_row["bit_exact"], A_row["candidate"]["samples_per_channel"], B_row["candidate_samples_per_channel"],
         B_row["film_same_span_samples_per_channel"], B_row["decoded_delta_samples_per_channel"],
         C_row["container_delta_audio_minus_video_ms"]))
print("[m1] geometry=%sx%s old368=%s | pts first=%s last=%s | not_source_copy mae_median=%s"
      % (vid["width"], vid["height"], geom["old_368_defect_present"], geom["pts"]["first_pts"],
         geom["pts"]["last_pts"], rows["not_source_copy"]["measured"].get("mae_median")))
print("[m1] pairing advantage=%s reason=%s" % (adv, pairing_why))
print("[m1] ledger isolation: %s" % json.dumps({k: v["bytes_appended"] for k, v in iso["protected_ledgers"].items()}))
print("[m1] wrote", RAW / "m1_eval_book.json", "commands=%d" % C.command_count())
