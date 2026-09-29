"""MF-V1-BENCH - INCREMENTAL verification (P5fix2/3 + assembly v1.2/v1.3), READ-ONLY on proof/**.

Sections:
  A hash audit      : candidate §7/§8/§9 claims + V12/V13 segment pins + P5FIX2/3 receipts +
                      FULL re-audit of PROOF_EVIDENCE_INDEX.md (every file under proof/)
  B decode audit    : seg clips (seg1 102f, seg2 18f, p5fix3 seg2 18f) + assembly v1.2/v1.3
  C span/pin check  : per-segment frames and spans; sum == 360 == 12.000 s
  D cut-scan audit  : MY OWN implementation of the declared rule
                      (changed_pixel_delta=32, changed_fraction>=0.50, mean_abs_diff>=12)
                      over the 3 source windows; compare with P5FIX2_CUT_SCAN.json
  E supersede       : v1/v1.1/v1.2/v1.3 assemblies + their own pin JSONs all on disk, hashes
                      match their cited values, no overwrite of an older pin
Writes bench/incremental_verify.json. Never writes into proof/**.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

RUN = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z")
PROOF = RUN / "proof"
EV = PROOF / "evidence"
BENCH = RUN / "bench"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

CANDIDATE_CLAIMS = [
    ("output/p7/assembly_v1_00001_.mp4",
     "5754baef491d84ddcbab32df73f1991008c0308608ba12bb97651cea5e61599a"),
    ("output/p7/assembly_v11_00001_.mp4",
     "50e8d42e312f28d23c047f22bdc9192cfacb080e8351de88c2cff4301261bbfa"),
    ("output/p7/assembly_v12_00001_.mp4",
     "fcc3c6f56b343d8e6d3342ac38822016917ef294b2fc25a9ba651b7d2127e36a"),
    ("output/p7/assembly_v13_00001_.mp4",
     "6878becc7e1db4c561253fb3ab79a85aacf0ecf685f7ea10dbac0e5b834a750e"),
    ("output/p5fix2_occ_seg1/animate2_occ_seg1_p5fix2_00001_.mp4",
     "b9b1cdb989f43ffbee7ea72f52005e86b44d0219d3a49719a6964f53f7f55cc4"),
    ("output/p5fix2_occ_seg2/animate2_occ_seg2_p5fix2_00001_.mp4",
     "31ac79f75b9fddeff9e490766111e3f4493552ec05265c5f6443da7cbabde926"),
    ("output/p5fix3_occ_seg2/animate2_occ_seg2_p5fix3_00001_.mp4",
     "7db4734bf73e267737ff9b17b4579792f9fd44d8140e0724cc364576a55098a7"),
]
NEW_EVIDENCE_REQUIRED = ["P5FIX2_CUT_SCAN.json", "P5FIX2_RUNS.json", "P7_ASSEMBLY_V12.json",
                         "P7_ASSEMBLY_V13.json", "P7_ASSEMBLY_V12_CHECK.json",
                         "P7_ASSEMBLY_V13_CHECK.json", "P5FIX3_GATE.json", "P5FIX3_RUN.json"]
# the packet named "P5FIX3_RECEIPT.json ... (nếu tên khác — tìm theo glob P5FIX3*)": the receipt that
# exists is P5FIX3_SEG2_RECEIPT.json (verified below); accept either spelling.
P5FIX3_RECEIPT_ANY = ["P5FIX3_RECEIPT.json", "P5FIX3_SEG2_RECEIPT.json"]
SOURCES = {"BOOK": "inputs/BOOK_src.mp4", "TURN": "inputs/TURN_795_src.mp4",
           "OCC": "inputs/OCC_14768_src.mp4"}
SEG_CLIPS = {"seg1": "output/p5fix2_occ_seg1/animate2_occ_seg1_p5fix2_00001_.mp4",
             "seg2_p5fix2": "output/p5fix2_occ_seg2/animate2_occ_seg2_p5fix2_00001_.mp4",
             "seg2_p5fix3": "output/p5fix3_occ_seg2/animate2_occ_seg2_p5fix3_00001_.mp4",
             "book_p3b": "output/p3b/animate2_book_p3b_00001_.mp4",
             "turn_p5fix": "output/p5fix_turn/animate2_turn_p5fix_00001_.mp4"}
UNIT_CLIP_KEY = {"BOOK": "book_p3b", "TURN": "turn_p5fix", "OCC_SEG1": "seg1",
                 "OCC_SEG2": "seg2_p5fix3"}
ASSEMBLIES = {"v1.2": "output/p7/assembly_v12_00001_.mp4",
              "v1.3": "output/p7/assembly_v13_00001_.mp4"}
RULE = {"changed_pixel_delta": 32, "min_changed_fraction": 0.50, "min_mean_abs_diff": 12.0}
UNREADABLE: list = []


def sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def dig(path: Path):
    if not path.is_file():
        return None, None
    try:
        h = hashlib.sha256()
        n = 0
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
                n += len(chunk)
        return h.hexdigest(), n
    except PermissionError:
        UNREADABLE.append(str(path))
        return None, None


def find_file(fr: str) -> Path:
    for base in (PROOF, PROOF / "output", RUN):
        p = (base / fr) if not Path(fr).is_absolute() else Path(fr)
        if p.is_file():
            return p
    return PROOF / fr


def run(argv, timeout=900):
    p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def ffprobe_json(path: Path) -> dict:
    rc, out, err = run([FFPROBE, "-v", "error", "-print_format", "json",
                        "-show_streams", "-show_format", str(path)])
    return json.loads(out.decode("utf-8", "replace")) if rc == 0 else {"_error": err[-200:]}


def decode_profile(path: Path) -> dict:
    d = ffprobe_json(path)
    if "_error" in d:
        return d
    vs = [s for s in d["streams"] if s["codec_type"] == "video"][0]
    aud = [s for s in d["streams"] if s["codec_type"] == "audio"]
    rc, out, err = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(path)])
    pts = [float(x) for x in out.decode().replace(",", " ").split()] if rc == 0 else None
    mono = all(b > a for a, b in zip(pts, pts[1:])) if pts else None
    return {"file": str(path.relative_to(RUN)).replace("\\", "/"),
            "width": vs.get("width"), "height": vs.get("height"),
            "nb_frames": vs.get("nb_frames"), "avg_frame_rate": vs.get("avg_frame_rate"),
            "duration_s": float(d["format"].get("duration", 0)),
            "size_bytes": int(d["format"].get("size", 0)),
            "pts_count": len(pts) if pts else None,
            "pts_first": pts[0] if pts else None, "pts_last": pts[-1] if pts else None,
            "pts_strictly_monotonic": mono,
            "audio": [{"codec": a.get("codec_name"), "sample_rate": a.get("sample_rate"),
                       "channels": a.get("channels"), "duration_s": a.get("duration")}
                      for a in aud]}


def frames_rgb(path: Path):
    import numpy as np
    rc, out, err = run([FFMPEG, "-v", "error", "-i", str(path), "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], timeout=900)
    if rc != 0:
        return None, err.decode("utf-8", "replace")[-200:]
    return np.frombuffer(out, dtype="uint8"), None


def cut_scan(path: Path) -> dict:
    """The declared rule, implemented independently: for every consecutive frame pair,
    mean_abs_diff over all channels and changed_fraction = share of pixels whose max-channel
    abs diff >= changed_pixel_delta. A pair is a CUT when both thresholds are met."""
    import numpy as np
    d = ffprobe_json(path)
    vs = [s for s in d.get("streams", []) if s["codec_type"] == "video"]
    if not vs:
        return {"_error": "no video"}
    h, w = int(vs[0]["height"]), int(vs[0]["width"])
    buf, err = frames_rgb(path)
    if buf is None:
        return {"_error": err}
    n = len(buf) // (h * w * 3)
    frames = buf[: n * h * w * 3].reshape(n, h, w, 3).astype("int16")
    rows = []
    for i in range(n - 1):
        diff = np.abs(frames[i + 1] - frames[i])
        mad = float(diff.mean())
        cf = float((diff.max(axis=2) >= RULE["changed_pixel_delta"]).mean())
        rows.append({"pair": "%d->%d" % (i, i + 1), "mean_abs_diff": round(mad, 4),
                     "changed_fraction": round(cf, 4)})
    mads = [r["mean_abs_diff"] for r in rows]
    med = float(np.median(mads)) if mads else None
    cuts = [r for r in rows if r["changed_fraction"] >= RULE["min_changed_fraction"]
            and r["mean_abs_diff"] >= RULE["min_mean_abs_diff"]]
    return {"file": str(path.relative_to(RUN)).replace("\\", "/"), "frames": n,
            "pairs": len(rows), "median_mean_abs_diff": round(med, 4) if med is not None else None,
            "max_mean_abs_diff": round(max(mads), 4) if mads else None,
            "cuts_my_run": cuts, "cut_pairs_my_run": [c["pair"] for c in cuts],
            "all_pairs": rows}


def main() -> int:
    BENCH.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    res = {"artifact": "incremental_verify.json", "task": "MF-V1-BENCH incremental P5fix2/3 + v1.3",
           "when": time.strftime("%Y-%m-%dT%H:%M:%S"), "read_only_root": str(PROOF)}

    # ---------- A. HASH ----------
    A = {"candidate_claims": [], "segment_pins": [], "receipt_output_files": [],
         "new_evidence_present": {}, "index": {"rows": 0, "match": 0, "mismatch": [], "missing": []}}
    for rel, want in CANDIDATE_CLAIMS:
        p = find_file(rel)
        got, n = dig(p)
        A["candidate_claims"].append({"file": rel, "found": p.is_file(), "claimed": want,
                                      "got": got, "bytes": n,
                                      "match": bool(got and got == want)})
    for pin_name, pin in (("P7_ASSEMBLY_V12.json", "v1.2"), ("P7_ASSEMBLY_V13.json", "v1.3")):
        d = json.loads((EV / pin_name).read_text(encoding="utf-8"))
        for s in d.get("segments", []):
            p = find_file(s.get("file", ""))
            got, n = dig(p)
            A["segment_pins"].append({"pin": pin_name, "unit": s.get("unit"), "file": s.get("file"),
                                      "claimed": s.get("sha256"), "frames_claim": s.get("frames"),
                                      "frames_got": None, "span": s.get("span"),
                                      "got": got, "bytes": n,
                                      "match": bool(got and got == str(s.get("sha256")).lower())})
        A["segment_pins"].append({"pin": pin_name, "_total_expected_frames": d.get("total_expected_frames"),
                                  "_order": d.get("order"), "_supersedes": d.get("supersedes")})
    for rf in ("P5FIX2_RUNS.json", "P5FIX2_SEG1_RECEIPT.json", "P5FIX2_SEG2_RECEIPT.json",
               "P5FIX2_ANCHOR_SEG2_RECEIPT.json", "P5FIX3_RUN.json", "P5FIX3_SEG2_RECEIPT.json",
               "P5FIX2_GATE.json", "P5FIX3_GATE.json"):
        p = EV / rf
        if not p.is_file():
            A["receipt_output_files"].append({"receipt": rf, "_missing": True})
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        ofs = d.get("output_files") or (d.get("runs") if isinstance(d.get("runs"), list) else [])
        count = 0
        for o in ofs if isinstance(ofs, list) else []:
            if not isinstance(o, dict):
                continue
            fr = o.get("file") or o.get("path")
            sh = o.get("sha256")
            if not fr or not sh:
                continue
            f = find_file(fr)
            got, n = dig(f)
            count += 1
            A["receipt_output_files"].append({"receipt": rf, "file": fr, "claimed": sh,
                                              "got": got, "bytes": n,
                                              "match": bool(got and got == str(sh).lower())})
        if count == 0:
            A["receipt_output_files"].append({"receipt": rf, "_no_output_files_key":
                                              sorted(d.keys())[:8]})
    for f in NEW_EVIDENCE_REQUIRED:
        A["new_evidence_present"][f] = (EV / f).is_file()
    p5f3_rec = next((r for r in P5FIX3_RECEIPT_ANY if (EV / r).is_file()), None)
    A["new_evidence_present"]["P5FIX3_RECEIPT.json (any spelling: %s)" % P5FIX3_RECEIPT_ANY] = \
        bool(p5f3_rec)
    A["p5fix3_receipt_resolved"] = p5f3_rec
    idx = (EV / "PROOF_EVIDENCE_INDEX.md").read_text(encoding="utf-8")
    for m in re.finditer(r"^\|\s*`([^`]+)`\s*\|\s*([\d,]+)\s*\|\s*`([0-9a-f]{64})`\s*\|\s*$", idx, re.M):
        rel = m.group(1).strip().replace("\\", "/")
        want_b, want_s = int(m.group(2).replace(",", "")), m.group(3)
        A["index"]["rows"] += 1
        p = PROOF / rel
        got, n = dig(p)
        if got is None:
            A["index"]["missing"].append(rel)
        elif got != want_s or n != want_b:
            A["index"]["mismatch"].append({"file": rel, "want": [want_b, want_s[:16]],
                                           "got": [n, (got or "")[:16]]})
        else:
            A["index"]["match"] += 1
    res["hash_audit"] = A

    # ---------- B. DECODE ----------
    dec = {}
    for k, rel in {**SEG_CLIPS, **ASSEMBLIES}.items():
        dec[k] = decode_profile(find_file(rel))
    res["decode_audit"] = dec

    # ---------- C. SPAN ----------
    v13 = json.loads((EV / "P7_ASSEMBLY_V13.json").read_text(encoding="utf-8"))
    spans = []
    total = 0
    for s in v13["segments"]:
        fr = int(s.get("frames") or 0)
        total += fr
        key = UNIT_CLIP_KEY.get(s.get("unit"), "")
        spans.append({"unit": s.get("unit"), "frames": fr,
                      "span": s.get("span") or s.get("span_frames") or s.get("source_span"),
                      "clip": key,
                      "clip_frames_measured": str(dec.get(key, {}).get("nb_frames") or ""),
                      "frames_match_clip": str(fr) == str(dec.get(key, {}).get("nb_frames"))})
    asm13 = dec.get("v1.3", {})
    span_ok = (total == int(v13.get("total_expected_frames") or -1) == int(asm13.get("nb_frames") or -2))
    res["span_check"] = {"v13_total_frames_from_pins": total,
                         "v13_total_expected_frames": v13.get("total_expected_frames"),
                         "assembly_v13_nb_frames": asm13.get("nb_frames"),
                         "assembly_v13_duration_s": asm13.get("duration_s"),
                         "segments": spans, "sum_and_assembly_match": span_ok}

    # ---------- D. CUT SCAN (own implementation) ----------
    their = json.loads((EV / "P5FIX2_CUT_SCAN.json").read_text(encoding="utf-8"))
    cutres = {"rule_mine": RULE, "windows": {}}
    for name, rel in SOURCES.items():
        mine = cut_scan(PROOF / rel)
        mine.pop("all_pairs", None)  # keep JSON small; per-pair of interest printed below
        th = their.get("windows", {}).get(name, {})
        cutres["windows"][name] = {
            "mine": {k: mine.get(k) for k in ("frames", "median_mean_abs_diff", "max_mean_abs_diff",
                                              "cuts_my_run", "cut_pairs_my_run", "_error") if k in mine},
            "theirs": {"cuts": th.get("cuts"), "cut_frames": th.get("cut_frames"),
                       "stats": th.get("stats"), "verdict": th.get("verdict")}}
    res["cut_scan_audit"] = cutres

    # ---------- E. SUPERSEDE ----------
    pins = {"v1": "P7_ASSEMBLY.json", "v1.1": "P7_ASSEMBLY_V11.json", "v1.2": "P7_ASSEMBLY_V12.json",
            "v1.3": "P7_ASSEMBLY_V13.json"}
    sup = {"assemblies_on_disk": {}, "pin_jsons": {}, "distinct_shas": None,
           "v13_supersedes_list": v13.get("supersedes")}
    asm_items = {"v1": "output/p7/assembly_v1_00001_.mp4",
                 "v1.1": "output/p7/assembly_v11_00001_.mp4"}
    asm_items.update(ASSEMBLIES)
    for label, rel in asm_items.items():
        p = find_file(rel)
        got, n = dig(p)
        sup["assemblies_on_disk"][label] = {"path": rel, "exists": p.is_file(), "sha256": got,
                                            "bytes": n,
                                            "mtime": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                                   time.localtime(p.stat().st_mtime))
                                            if p.is_file() else None}
    for label, fname in pins.items():
        p = EV / fname
        sup["pin_jsons"][label] = {"file": fname, "exists": p.is_file()}
    shas = [v["sha256"] for v in sup["assemblies_on_disk"].values() if v.get("sha256")]
    sup["distinct_shas"] = len(set(shas)) == len(shas)
    res["supersede"] = sup

    # ---------- writer watch ----------
    newest = sorted(((p.stat().st_mtime, str(p)) for p in PROOF.rglob("*") if p.is_file()),
                    reverse=True)[:1]
    res["writer_watch"] = {"newest_file_in_proof": newest[0][1] if newest else None,
                           "newest_mtime": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                         time.localtime(newest[0][0])) if newest else None,
                           "unreadable": sorted(set(UNREADABLE))}

    # ---------- verdict ----------
    ac = A["candidate_claims"]
    sp = [s for s in A["segment_pins"] if "unit" in s]
    ro = A["receipt_output_files"]
    mism = (sum(1 for r in ac if not r["match"]) + sum(1 for r in sp if r["match"] is False)
            + sum(1 for r in ro if r.get("match") is False)
            + len(A["index"]["mismatch"]) + len(A["index"]["missing"])
            + sum(1 for v in A["new_evidence_present"].values() if not v))
    cut_ok = all(not w["mine"].get("cuts_my_run") for k, w in cutres["windows"].items() if k != "OCC") \
        and [c["pair"] for c in cutres["windows"]["OCC"]["mine"].get("cuts_my_run", [])] == ["101->102"]
    res["hash_mismatch_total"] = mism
    res["cut_scan_confirms_occ_cut_at_102_and_no_book_cut"] = bool(cut_ok)
    span_frames_ok = all(s["frames_match_clip"] for s in res["span_check"]["segments"])
    res["span_frames_ok"] = span_frames_ok
    res["verdict"] = ("BENCH_PROOF_VERIFIED_INCREMENTAL" if (mism == 0 and cut_ok and span_ok
                                                             and span_frames_ok)
                      else "FINDINGS_INCREMENTAL") + "_CUTSCAN_%s" % ("OK" if cut_ok else "DIFF")
    res["wall_s"] = round(time.time() - t0, 2)
    (BENCH / "incremental_verify.json").write_text(json.dumps(res, indent=1), encoding="utf-8")

    print("HASH claims=%d/%d segpins=%d/%d receipts=%d/%d rows idx=%d/%d mism=%d"
          % (sum(1 for r in ac if r["match"]), len(ac),
             sum(1 for r in sp if r["match"]), len(sp),
             sum(1 for r in ro if r.get("match")), len(ro),
             A["index"]["match"], A["index"]["rows"], mism))
    for k, d in dec.items():
        print("DEC  %-12s %sx%s f=%s dur=%s aac=%s mono=%s"
              % (k, d.get("width"), d.get("height"), d.get("nb_frames"), d.get("duration_s"),
                 bool(d.get("audio")), d.get("pts_strictly_monotonic")))
    print("SPAN sum=%s expected=%s asm=%s ok=%s" % (total, v13.get("total_expected_frames"),
                                                    asm13.get("nb_frames"), span_ok))
    for k, w in cutres["windows"].items():
        print("CUT  %-4s mine cuts=%s med=%s max=%s | theirs=%s"
              % (k, w["mine"].get("cut_pairs_my_run"), w["mine"].get("median_mean_abs_diff"),
                 w["mine"].get("max_mean_abs_diff"),
                 [c.get("pair") for c in (w["theirs"].get("cuts") or [])]))
    print("SUP  distinct=%s pins=%s" % (sup["distinct_shas"],
                                        {k: v["exists"] for k, v in sup["pin_jsons"].items()}))
    print("VERDICT=%s wall=%ss" % (res["verdict"], res["wall_s"]))
    return 0 if (mism == 0 and cut_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
