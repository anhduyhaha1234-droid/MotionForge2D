"""MF-V1-BENCH — independent PROOF_GATE verification (READ-ONLY on proof/**, writes only bench/).

Answers, from disk bytes and my own measurements:
  1 hash audit      : every artifact the candidate/receipts/ledger/index claim -> recomputed sha256+bytes
  2 decode audit    : ffprobe dims/frames/fps/duration/PTS monotonic/audio on the main clips
  3 determinism     : MY OWN pixel diff p6_book_nocache vs p3b (+ overlap16 vs p3b), max abs diff
  4 cost audit      : wall_s / output duration from receipts, arithmetic shown
  5 gate checklist  : P0-P7 evidence present on disk? what fields exist? what is missing?
  6 negative spots  : assembly frame math, anchor placeholder test, watermark-region metric
Writes bench/bench_verify.json + crops for the vision check. Never writes into proof/**.

Run: cd <RUN>/bench && python -B verify_proof.py
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
OUT = PROOF / "output"
EV = PROOF / "evidence"
BENCH = RUN / "bench"
CROPS = BENCH / "crops"

FFPROBE = shutil.which("ffprobe") or "ffprobe"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

# candidate-cited (file, 16-hex sha256 prefix) pairs, transcribed from PROOF_GATE_CANDIDATE.md
CANDIDATE_CLAIMS = [
    ("evidence/P0_RUNTIME_MATRIX.json", "adb6bf7cffbce5b5"),
    ("evidence/P1_UNIT_MANIFESTS.json", "9763a1d14a3fef1c"),
    ("evidence/P2_ANCHOR_GATES.json", "d580db708c712652"),
    ("evidence/P3_RECEIPT.json", "8e6595922b02028a"),
    ("evidence/P3B_GEOMETRY_GATE.json", "f47ab0e456cc2634"),
    ("evidence/P4_GEOMETRY_GATE.json", "fffcca4d131c7dea"),
    ("evidence/P5_TURN_OCC_GATE.json", "08ac64854e66033c"),
    ("evidence/P5_OVERLAP_GATE.json", "f587038666512eb6"),
    ("evidence/P6_NOCACHE_GATE.json", "a5c0dd2a39e849b3"),
    ("evidence/P7_ASSEMBLY_CHECK.json", "dd5f3211f93d9e29"),
    ("output/p7/assembly_v1_00001_.mp4",
     "5754baef491d84ddcbab32df73f1991008c0308608ba12bb97651cea5e61599a"),
]
MAIN_CLIPS = {
    "p3b_main": "output/p3b/animate2_book_p3b_00001_.mp4",
    "p3_main": "output/p3/animate2_book_p3_00001_.mp4",
    "p4_vace_raw": "output/p4/animate2_vace_book_p4_00001_.mp4",
    "p5_turn": "output/p5_turn/animate2_turn_p5_00001_.mp4",
    "p5_occ": "output/p5_occ/animate2_occ_p5_00001_.mp4",
    "p6_nocache": "output/p6_book_nocache/animate2_book_nocache_00001_.mp4",
    "p5_ov16": "output/p5_book_overlap16/animate2_book_ov16_00001_.mp4",
    "p7_assembly": "output/p7/assembly_v1_00001_.mp4",
}


def sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


UNREADABLE: list = []


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
        # e.g. proof/user/comfyui.db.lock is held by a live process (or carries ACLs that deny
        # read): record it, never crash the whole audit on one locked file (pitfall #40 family).
        UNREADABLE.append(str(path))
        return None, None


def run(argv, timeout=600):
    p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def ffprobe_json(path: Path) -> dict:
    rc, out, err = run([FFPROBE, "-v", "error", "-print_format", "json",
                        "-show_streams", "-show_format", str(path)])
    if rc != 0:
        return {"_error": err.decode("utf-8", "replace")[-200:]}
    return json.loads(out.decode("utf-8", "replace"))


def pts_list(path: Path):
    rc, out, err = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(path)])
    if rc != 0:
        return None
    txt = out.decode("utf-8", "replace").replace(",", " ")
    vals = [float(x) for x in txt.split() if x.strip()]
    return vals


def decode_profile(path: Path, h: int, w: int) -> dict:
    rc, out, err = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams",
                        "-show_format", str(path)])
    d = json.loads(out.decode("utf-8", "replace"))
    vs = [s for s in d["streams"] if s["codec_type"] == "video"][0]
    aud = [s for s in d["streams"] if s["codec_type"] == "audio"]
    fmt = d["format"]
    pts = pts_list(path)
    mono = None
    if pts:
        mono = all(b > a for a, b in zip(pts, pts[1:]))
    return {"file": str(path.relative_to(RUN)).replace("\\", "/"),
            "width": vs.get("width"), "height": vs.get("height"),
            "nb_frames": vs.get("nb_frames"), "avg_frame_rate": vs.get("avg_frame_rate"),
            "duration_s": float(fmt.get("duration", 0)), "size_bytes": int(fmt.get("size", 0)),
            "pts_count": len(pts) if pts else None,
            "pts_first": pts[0] if pts else None, "pts_last": pts[-1] if pts else None,
            "pts_strictly_monotonic": mono,
            "audio": [{"codec": a.get("codec_name"), "sample_rate": a.get("sample_rate"),
                       "channels": a.get("channels"), "duration_s": a.get("duration")}
                      for a in aud]}


def raw_frames(path: Path):
    import numpy as np
    rc, out, err = run([FFMPEG, "-v", "error", "-i", str(path), "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], timeout=900)
    if rc != 0:
        return None, err.decode("utf-8", "replace")[-200:]
    return np.frombuffer(out, dtype="uint8"), None


def pixel_diff(a: Path, b: Path) -> dict:
    import numpy as np
    ba, ea = raw_frames(a)
    bb, eb = raw_frames(b)
    if ba is None or bb is None:
        return {"_error": {"a": ea, "b": eb}}
    n = min(len(ba), len(bb))
    fa, fb = ba[:n].astype("int16"), bb[:n].astype("int16")
    d = np.abs(fa - fb)
    tail = abs(len(ba) - len(bb))
    return {"a": str(a.relative_to(RUN)).replace("\\", "/"),
            "b": str(b.relative_to(RUN)).replace("\\", "/"),
            "bytes_a": len(ba), "bytes_b": len(bb), "bytes_missing_tail": tail,
            "max_abs_diff": int(d.max()), "pixels_differing": int((d > 0).sum()),
            "identical": bool(d.max() == 0 and tail == 0)}


def region_metric(png_or_clip: Path, x0, y0, x1, y1, frame=0) -> dict:
    """mean horizontal-gradient magnitude in a region of one frame (watermark = extra edges)."""
    import numpy as np
    rc, out, err = run([FFMPEG, "-v", "error", "-i", str(png_or_clip),
                        "-vf", "select=eq(n\\,%d)" % frame, "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], timeout=300)
    if rc != 0 or not out:
        return {"_error": (err.decode("utf-8", "replace") or "no output")[-200:]}
    h, w = None, None
    d = ffprobe_json(png_or_clip)
    vs = [s for s in d.get("streams", []) if s.get("codec_type") == "video"]
    if vs:
        h, w = int(vs[0]["height"]), int(vs[0]["width"])
    else:
        return {"_error": "no video stream"}
    arr = np.frombuffer(out, dtype="uint8")[: h * w * 3].reshape(h, w, 3)
    reg = arr[y0:y1, x0:x1].astype("int16")
    gx = np.abs(np.diff(reg, axis=1)).mean() if reg.shape[1] > 1 else 0.0
    uniq = len(np.unique(reg.reshape(-1, 3), axis=0))
    return {"region": [x0, y0, x1, y1], "frame": frame, "mean_abs_hgrad": round(float(gx), 3),
            "unique_colors": int(uniq), "mean_rgb": [round(float(v), 1) for v in reg.mean(axis=(0, 1))]}


def main() -> int:
    BENCH.mkdir(parents=True, exist_ok=True)
    CROPS.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    res = {"artifact": "bench_verify.json", "task": "MF-V1-BENCH PROOF_GATE verify",
           "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "session": "20260926_173425_c114cc_PLACEHOLDER", "read_only_root": str(PROOF)}

    # ---------- 1. HASH AUDIT ----------
    hash_audit = {"candidate_claims": [], "receipt_output_files": [], "ledger_rows": [],
                  "evidence_index": {"rows": 0, "checked": 0, "mismatch": [], "missing": []},
                  "counts": {}}
    for rel, want16 in CANDIDATE_CLAIMS:
        got, n = dig(PROOF / rel)
        hash_audit["candidate_claims"].append(
            {"file": rel, "claimed_sha256_16": want16, "got_sha256": got, "bytes": n,
             "match": bool(got and got.startswith(want16))})
    for rf in sorted(EV.glob("*RECEIPT*.json")) + sorted(EV.glob("P7_RUN.json")) + \
            sorted(EV.glob("P567_RUNS.json")):
        try:
            d = json.loads(rf.read_text(encoding="utf-8"))
        except Exception as exc:
            hash_audit["receipt_output_files"].append({"receipt": rf.name, "_error": str(exc)[:120]})
            continue
        for o in d.get("output_files", []):
            p = OUT / o.get("file", "")
            got, n = dig(p)
            hash_audit["receipt_output_files"].append(
                {"receipt": rf.name, "file": o.get("file"), "claimed_sha256": o.get("sha256"),
                 "claimed_bytes": o.get("bytes"), "got_sha256": got, "got_bytes": n,
                 "match": bool(got and got == str(o.get("sha256", "")).lower()
                               and n == o.get("bytes"))})
    for ln in (EV / "PROOF_LEDGER.jsonl").read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except Exception:
            hash_audit["ledger_rows"].append({"_unparsable": ln[:100], "checks": 0})
            continue
        checks = []

        def walk(node, trail=""):
            if isinstance(node, dict):
                f = node.get("file") or node.get("path")
                s = node.get("sha256") or node.get("sha")
                if isinstance(f, str) and isinstance(s, str) and re.fullmatch(r"[0-9a-f]{64}", s):
                    # ledger "file" fields are relative to proof/output/ (same convention as the
                    # receipts); some rows are absolute. Try both bases before declaring a miss.
                    if Path(f).is_absolute():
                        p = Path(f)
                    else:
                        p = PROOF / f
                        for base in (OUT, EV, PROOF):
                            if (base / f).is_file():
                                p = base / f
                                break
                    got, n = dig(p)
                    resolved_by = "direct"
                    if got is None:
                        # some ledger rows store a BARE basename (e.g. "animate2_book_p3_00001_.mp4"):
                        # resolve it by search across proof/**, but only accept an unambiguous hit
                        # or one whose bytes match the claim.
                        hits = [q for q in PROOF.rglob(Path(f).name) if q.is_file()]
                        sha_hits = [q for q in hits if dig(q)[0] == s.lower()]
                        if len(sha_hits) == 1 and len(hits) == 1:
                            p, resolved_by = sha_hits[0], "basename_search_unique"
                        elif len(sha_hits) == 1:
                            p, resolved_by = sha_hits[0], "basename_search_sha_match"
                        elif hits:
                            resolved_by = "basename_ambiguous(%d hits, 0 sha match)" % len(hits)
                        got, n = dig(p)
                    checks.append({"kind": "file+sha", "field": trail or "row",
                                   "file": f, "claimed": s, "got": got, "resolved_by": resolved_by,
                                   "resolved_path": (str(p.relative_to(PROOF)).replace("\\", "/")
                                                     if p.is_file() else None),
                                   "match": bool(got and got == s.lower())})
                    node = {k: v for k, v in node.items() if k not in ("sha256", "sha")}
                for k, v in node.items():
                    walk(v, (trail + "." + k).strip("."))
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, "%s[%d]" % (trail, i))
            elif isinstance(node, str) and re.fullmatch(r"[0-9a-f]{64}", node):
                checks.append({"kind": "sha_in_field", "field": trail, "claimed": node,
                               "resolved_file": None, "match": None})
        walk(d)
        # resolve standalone 64-hex values against the graphs dir, then output, then evidence
        for c in checks:
            if c["kind"] != "sha_in_field":
                continue
            found = None
            for sub in ("graphs", "output", "evidence"):
                for p in sorted((PROOF / sub).rglob("*")):
                    if p.is_file() and dig(p)[0] == c["claimed"]:
                        found = str(p.relative_to(PROOF)).replace("\\", "/")
                        break
                if found:
                    break
            c["resolved_file"] = found
            c["match"] = bool(found)
        hash_audit["ledger_rows"].append(
            {"phase": d.get("phase"), "checks": len(checks), "detail": checks})
    # evidence index (file,bytes,sha) rows vs disk — the index writes backticked WINDOWS paths and
    # comma-grouped byte counts (`evidence\X.json` | 2,703 | `sha`), neither of which the first
    # regex accepted: it matched 0/199 rows (a blanket miss = tool bug, not index corruption).
    idx = (EV / "PROOF_EVIDENCE_INDEX.md").read_text(encoding="utf-8")
    for m in re.finditer(r"^\|\s*`([^`]+)`\s*\|\s*([\d,]+)\s*\|\s*`([0-9a-f]{64})`\s*\|\s*$",
                         idx, re.M):
        rel = m.group(1).strip().replace("\\", "/")
        want_b, want_s = int(m.group(2).replace(",", "")), m.group(3)
        hash_audit["evidence_index"]["rows"] += 1
        p = PROOF / rel
        got, n = dig(p)
        if got is None:
            hash_audit["evidence_index"]["missing"].append(rel)
        elif got != want_s or n != want_b:
            hash_audit["evidence_index"]["mismatch"].append(
                {"file": rel, "want": [want_b, want_s[:16]], "got": [n, (got or "")[:16]]})
        else:
            hash_audit["evidence_index"]["checked"] += 1

    def tally(rows, claim_field, got_field="got_sha256"):
        ok = sum(1 for r in rows if r.get("match"))
        return {"rows": len(rows), "match": ok, "mismatch": len(rows) - ok,
                "mismatched": [r for r in rows if not r.get("match")][:8]}
    lrows = hash_audit["ledger_rows"]
    l_checks = [c for r in lrows for c in r.get("detail", [])]
    l_mism = [c for c in l_checks if c.get("match") is False]
    l_ok = [c for c in l_checks if c.get("match") is True]
    l_noclaim = [r for r in lrows if not r.get("detail")]
    hash_audit["counts"] = {
        "candidate_claims": tally(hash_audit["candidate_claims"], "claimed_sha256_16"),
        "receipt_output_files": tally(hash_audit["receipt_output_files"], "claimed_sha256"),
        "ledger_rows": {"rows": len(lrows), "checks": len(l_checks), "match": len(l_ok),
                        "mismatch": len(l_mism), "no_hash_claim_rows": len(l_noclaim),
                        "mismatched": l_mism[:8]},
        "evidence_index": {"rows": hash_audit["evidence_index"]["rows"],
                           "match": hash_audit["evidence_index"]["checked"],
                           "mismatch": len(hash_audit["evidence_index"]["mismatch"]),
                           "missing": len(hash_audit["evidence_index"]["missing"])},
    }
    res["hash_audit"] = hash_audit
    res["unreadable_files"] = sorted(set(UNREADABLE))

    # ---------- 2. DECODE AUDIT ----------
    decode = {}
    for name, rel in MAIN_CLIPS.items():
        p = PROOF / rel
        decode[name] = decode_profile(p, None, None) if p.is_file() else {"_missing": rel}
    res["decode_audit"] = decode

    # ---------- 3. DETERMINISM (my own pixel diff) ----------
    det = {}
    try:
        det["p6_nocache_vs_p3b"] = pixel_diff(PROOF / MAIN_CLIPS["p6_nocache"], PROOF / MAIN_CLIPS["p3b_main"])
    except Exception as exc:
        det["p6_nocache_vs_p3b"] = {"_error": str(exc)[:200]}
    try:
        det["ov16_vs_p3b"] = pixel_diff(PROOF / MAIN_CLIPS["p5_ov16"], PROOF / MAIN_CLIPS["p3b_main"])
    except Exception as exc:
        det["ov16_vs_p3b"] = {"_error": str(exc)[:200]}
    res["determinism"] = det

    # ---------- 4. COST AUDIT ----------
    def receipt_wall(fname):
        d = json.loads((EV / fname).read_text(encoding="utf-8"))
        for k in ("server_side_wall_s", "wall_s", "wall_seconds"):
            if isinstance(d.get(k), (int, float)):
                return d[k], k
        return None, None
    cost = {}
    p3w, k1 = receipt_wall("P3_RECEIPT.json")
    p3bw, k2 = receipt_wall("P3B_RECEIPT.json")
    p4w, k3 = receipt_wall("P4_RECEIPT.json")
    p6w, k4 = receipt_wall("P6_NOCACHE_RECEIPT.json")
    d4raw = decode.get("p4_vace_raw", {}).get("duration_s")
    cost["rows"] = [
        {"profile": "p3 cold (cache ON)", "wall_s": p3w, "key": k1, "out_s": 4.0,
         "s_per_out_s": round(p3w / 4.0, 2) if p3w else None, "candidate_claim": 596.95},
        {"profile": "p3b warm (cache ON)", "wall_s": p3bw, "key": k2, "out_s": 4.0,
         "s_per_out_s": round(p3bw / 4.0, 2) if p3bw else None, "candidate_claim": 38.67},
        {"profile": "p4 VACE (121f raw / trimmed 120f)", "wall_s": p4w, "key": k3,
         "out_s": d4raw, "s_per_out_s": round(p4w / d4raw, 2) if (p4w and d4raw) else None,
         "claim": 291.13, "note": "denominator = raw 121-frame duration %.4f s (4.0 s denom => %.2f)"
         % (d4raw or 0, (p4w / 4.0) if p4w else 0)},
        {"profile": "p6 nocache", "wall_s": p6w, "key": k4, "out_s": 4.0,
         "s_per_out_s": round(p6w / 4.0, 2) if p6w else None, "claim": "135.21/4 s"},
    ]
    cost["formula"] = "s_per_output_second = server_side_wall_s / output_duration_s"
    cost["accepted_seconds"] = 0
    cost["cost_per_accepted_second"] = "UNDEFINED (accepted_seconds = 0; no quality review yet)"
    res["cost_audit"] = cost

    # ---------- 5. GATE CHECKLIST ----------
    gates = {}
    for pid, files in {
        "P0": ["P0_RUNTIME_MATRIX.json", "P0_NODE_INTERFACES.json", "P0_object_info.json",
               "P0_MODEL_INVENTORY.json"],
        "P1": ["P1_UNIT_MANIFESTS.json"],
        "P2": ["P2_ANCHOR_GATES.json", "P2_ANCHOR_RECEIPTS.json"],
        "P3": ["P3_RECEIPT.json", "P3_DECODE_CHECK.json"],
        "P3b": ["P3B_GEOMETRY_GATE.json", "P3B_RECEIPT.json", "P3B_ARTIFACT_RECONCILIATION.json"],
        "P4": ["P4_GEOMETRY_GATE.json", "P4_RECEIPT.json"],
        "P5": ["P5_TURN_OCC_GATE.json", "P5_OVERLAP_GATE.json", "P5_TURN_RECEIPT.json",
               "P5_OCC_RECEIPT.json"],
        "P6": ["P6_NOCACHE_GATE.json", "P6_NOCACHE_RECEIPT.json"],
        "P7": ["P7_ASSEMBLY_CHECK.json", "P7_ASSEMBLY.json", "P7_RUN.json"],
    }.items():
        present = {f: (EV / f).is_file() for f in files}
        gates[pid] = {"files_present": present}
    # key-field probes (record what IS, not what should be)
    p1 = json.loads((EV / "P1_UNIT_MANIFESTS.json").read_text(encoding="utf-8"))
    blob = json.dumps(p1)
    gates["P1"].update({"has_role": '"role"' in blob, "has_timeline": '"timeline"' in blob,
                        "units": [k for k in (p1.get("units", {}) if isinstance(p1.get("units"), dict) else {})] or
                        list(p1.keys())[:6]})
    p4g = json.loads((EV / "P4_GEOMETRY_GATE.json").read_text(encoding="utf-8"))
    p4b = json.dumps(p4g).lower()
    gates["P4"].update({"mentions_hard_relationship": ("hard" in p4b and "relation" in p4b),
                        "ab_files_on_disk": [str(p.relative_to(PROOF)).replace("\\", "/")
                                             for p in sorted((EV / "previews").glob("p4_ab_*"))]})
    p5g = json.loads((EV / "P5_TURN_OCC_GATE.json").read_text(encoding="utf-8"))
    p5b = json.dumps(p5g).lower()
    gates["P5"].update({"mentions_chunk": "chunk" in p5b,
                        "mentions_continuation": "continuation" in p5b or "continu" in p5b})
    p6g = json.loads((EV / "P6_NOCACHE_GATE.json").read_text(encoding="utf-8"))
    gates["P6"].update({"_keys": sorted(p6g.keys())[:10]})
    p7g = json.loads((EV / "P7_ASSEMBLY_CHECK.json").read_text(encoding="utf-8"))
    gates["P7"].update({"_keys": sorted(p7g.keys())[:10],
                        "gates_true": sum(1 for v in p7g.get("gates", {}).values() if v is True)
                        if isinstance(p7g.get("gates"), dict) else None})
    gates["previews"] = sorted(p.name for p in (EV / "previews").glob("*"))
    res["gate_checklist"] = gates

    # ---------- 6. NEGATIVE CONTROLS ----------
    neg = {}
    asm = decode.get("p7_assembly", {})
    s_frames = 0
    per_clip = {}
    for k in ("p3b_main", "p5_turn", "p5_occ"):
        d = decode.get(k, {})
        per_clip[k] = d.get("nb_frames")
        try:
            s_frames += int(d.get("nb_frames") or 0)
        except Exception:
            pass
    neg["assembly_frame_math"] = {
        "sum_of_3_unit_clips": s_frames, "assembly_nb_frames": asm.get("nb_frames"),
        "assembly_duration_s": asm.get("duration_s"),
        "assembly_has_aac": any(a.get("codec") == "aac" for a in asm.get("audio", [])),
        "assembly_audio": asm.get("audio")}
    # anchor placeholder test (unique colours; a 2-colour placeholder would be tiny)
    anchors = {}
    try:
        from PIL import Image
        for p in sorted((OUT / "anchors").glob("*.png")):
            im = Image.open(p).convert("RGB")
            cols = im.getcolors(maxcolors=1 << 24) or []
            anchors[p.name] = {"size": im.size, "unique_colors": len(cols),
                               "top_color_share": round(max(c for c, _ in cols) / (im.size[0] * im.size[1]), 4)}
    except Exception as exc:
        anchors["_error"] = str(exc)[:160]
    neg["anchor_placeholder_test"] = anchors
    # watermark region: bottom-left 200x78 of frame 0 for p3b / p4 / p3
    wm = {}
    for k, rel in (("p3b", "p3b_main"), ("p4", "p4_vace_raw"), ("p3", "p3_main"),
                   ("p6", "p6_nocache")):
        try:
            wm[k] = region_metric(PROOF / MAIN_CLIPS[rel], 0, 290, 200, 368, frame=0)
        except Exception as exc:
            wm[k] = {"_error": str(exc)[:160]}
    neg["watermark_region_metric_bottom_left_200x78"] = wm
    # crops for the human/vision check
    crop_files = {}
    try:
        for k, rel in (("p3b", "p3b_main"), ("p4", "p4_vace_raw")):
            dst = CROPS / ("wm_%s_frame0.png" % k)
            rc, out, err = run([FFMPEG, "-y", "-v", "error", "-i", str(PROOF / MAIN_CLIPS[k]),
                                "-vf", "select=eq(n\\,0),crop=240:110:0:258", "-frames:v", "1",
                                str(dst)], timeout=300)
            crop_files[k] = {"path": str(dst), "rc": rc, "exists": dst.is_file(),
                             "bytes": dst.stat().st_size if dst.is_file() else 0,
                             "stderr_tail": err.decode("utf-8", "replace")[-120:]}
    except Exception as exc:
        crop_files["_error"] = str(exc)[:160]
    neg["crop_files"] = crop_files
    res["negative_controls"] = neg

    # ---------- verdict ----------
    hc = hash_audit["counts"]
    mism = (hc["candidate_claims"]["mismatch"] + hc["receipt_output_files"]["mismatch"]
            + hc["ledger_rows"]["mismatch"] + len(hash_audit["evidence_index"]["mismatch"])
            + len(hash_audit["evidence_index"]["missing"]))
    det_ok = all(d.get("identical") for d in det.values() if isinstance(d, dict) and "identical" in d)
    res["verdict"] = ("BENCH_PROOF_VERIFIED" if mism == 0 else "FINDINGS") + \
                     ("_PIXEL_DETERMINISM_CONFIRMED" if det_ok else "_PIXEL_DIFF_MISMATCH")
    res["hash_mismatch_total"] = mism
    res["wall_s"] = round(time.time() - t0, 2)
    (BENCH / "bench_verify.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("HASH  candidate=%s receipts=%s ledger=%s index=%s mismatches=%d"
          % (hc["candidate_claims"], hc["receipt_output_files"], hc["ledger_rows"],
             hc["evidence_index"], mism))
    for k, d in det.items():
        print("DET   %-22s max_abs=%s identical=%s" % (k, d.get("max_abs_diff"), d.get("identical")))
    for r in cost["rows"]:
        print("COST  %-40s wall=%s -> %s s/out-s (claim %s)"
              % (r["profile"][:40], r.get("wall_s"), r.get("s_per_out_s"), r.get("candidate_claim") or r.get("claim")))
    a = res["negative_controls"]["assembly_frame_math"]
    print("NEG   assembly frames=%s sum3=%s aac=%s dur=%s"
          % (a["assembly_nb_frames"], a["sum_of_3_unit_clips"], a["assembly_has_aac"], a["assembly_duration_s"]))
    print("VERDICT=%s wall=%ss" % (res["verdict"], res["wall_s"]))
    return 0 if mism == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
