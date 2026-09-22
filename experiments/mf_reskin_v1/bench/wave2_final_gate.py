"""MF-V1-BENCH wave-2 FINAL GATE - verifies the delivered state on disk. Exit 0 only if every row passes."""
import json
import subprocess
import sys
from pathlib import Path

EV = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/mf-reskin-model-upgrade-20260922/20260922T0345Z")
B = EV / "BENCH"
CAND = EV / "VIDEO14B/wave2/media/final_vace14b_book4s_4s.mp4"
CAND_SHA = "ca42806b6ec5647f2ac1bf8a555c25fce819a44a27fbb30058a56b39a5471a88"

rows = []


def chk(name, ok, detail=""):
    rows.append((name, bool(ok), detail))


def sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# 1. the evaluation report exists and carries the required content
rep = B / "EVAL_BOOK_R4.md"
txt = rep.read_text(encoding="utf-8") if rep.exists() else ""
chk("EVAL_BOOK_R4.md exists", rep.exists(), "%d bytes" % (rep.stat().st_size if rep.exists() else 0))
for token, what in [("ca42806b6ec5647f2ac1bf8a555c25fce819a44a27fbb30058a56b39a5471a88", "candidate sha in report"),
                    ("640×368", "candidate geometry"), ("640×360", "source geometry"),
                    ("+8 rows", "geometry delta"), ("2.2222", "vertical %"),
                    ("71.6794", "not_source_copy mae_median"),
                    ("352,968", "audio sample count"),
                    ("MAE 0.0", "audio MAE"),
                    ("0 mismatches", "audio mismatches"),
                    ("1.995 ms", "audio delta ms"),
                    ("60928", "last pts"), ("UNMEASURED", "unmeasured verdict"),
                    ("NOT_REVIEWED", "not reviewed verdict"),
                    ("NEXT_REVIEW_PACKET", "review packet section")]:
    chk("report contains %s" % what, token in txt)
norm = " ".join(txt.split())   # the report wraps lines, so match on normalised whitespace
chk("report only mentions QUALITY_ACCEPTED as a negation",
    "did **not** write `QUALITY_ACCEPTED`" in norm
    and not any(p in norm for p in ["= QUALITY_ACCEPTED", "STATUS: QUALITY_ACCEPTED",
                                    "verdict QUALITY_ACCEPTED", "is QUALITY_ACCEPTED"]))
chk("report does not self-approve", not any(w in txt for w in ["\nAPPROVED\n", "\nCLOSED\n", "STATUS: APPROVED"]))

# 2. the reviewer request exists with all 7 semantic rows
rr = B / "review/wave2/REVIEWER_REQUEST.md"
rt = rr.read_text(encoding="utf-8") if rr.exists() else ""
chk("REVIEWER_REQUEST.md exists", rr.exists(), "%d bytes" % (rr.stat().st_size if rr.exists() else 0))
chk("reviewer request lists S1..S7", all(("S%d" % i) in rt for i in range(1, 8)))

# 3. the 14 review artifacts exist, non-empty, PNG dims as declared
man = json.loads((B / "raw/wave2_review_manifest.json").read_text(encoding="utf-8"))
arts = man["artifacts"]
chk("manifest lists 14 artifacts", len(arts) == 14, "n=%d" % len(arts))
chk("every artifact non-empty on disk", all(Path(a["path"]).exists() and Path(a["path"]).stat().st_size > 0 for a in arts))
chk("manifest total bytes matches disk",
    sum(Path(a["path"]).stat().st_size for a in arts) == man["total_bytes"], "%d" % man["total_bytes"])
expect = {"BOOK_r4_grip_candidate_centre_320x180_8anchors.png": (1280, 360),
          "BOOK_r4_grip_source_centre_320x180_8anchors.png": (1280, 360),
          "BOOK_r4_grip_sidebyside_320x180x2_8anchors.png": (2560, 360),
          "BOOK_r4_grip_candidate_zoom2x_8anchors.png": (2560, 736),
          "BOOK_r4_geometry_edge_rows_vstack.png": (640, 96),
          "BOOK_r4_candidate_1fps_4x4.png": (1280, 736),
          "BOOK_r4_source_1fps_4x4.png": (1280, 720),
          "BOOK_r4_sidebyside_sourceL_candidateR_1fps_4x4.png": (1280, 360)}
bad = []
for name, (w, h) in expect.items():
    for a in arts:
        if Path(a["path"]).name == name:
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height", "-of", "csv=p=0", a["path"]],
                               capture_output=True, text=True)
            got = tuple(int(x) for x in r.stdout.strip().split(","))
            if got != (w, h):
                bad.append("%s got %s want %s" % (name, got, (w, h)))
chk("PNG dimensions as declared", not bad, "; ".join(bad))

# 4. raw evidence files
for p in ["raw/wave2_eval_book_r4.json", "raw/wave2_argmin_control_src_vs_film.json",
          "raw/wave2_review_manifest.json", "raw/negative_controls.json", "raw/candidate_BOOK.json",
          "raw/wave1_snapshots/candidate_BOOK.wave1.json", "raw/wave1_snapshots/negative_controls.wave1.json",
          "raw/wave2_snapshots/cmd_transcript.before_append_fix.jsonl"]:
    chk("evidence %s" % p, (B / p).exists(), "%d bytes" % (B / p).stat().st_size if (B / p).exists() else "MISSING")

# 5. measured facts re-read from the JSON (not from the prose)
ev = json.loads((B / "raw/wave2_eval_book_r4.json").read_text(encoding="utf-8"))
chk("candidate pts == frame_id*512 (presentation)", ev["A_pts_audit"]["candidate"]["contract_pts_equals_frame_id_x512_presentation_order"])
chk("r3 export is NOT frame_id*512", not ev["A_pts_audit"]["superseded_r3_export"]["contract_pts_equals_frame_id_x512_presentation_order"])
b = ev["B_audio_pcm"]["candidate_full_vs_film_55p000_plus_4p001995"]
chk("audio bit-identical, 352,968 samples, 0 mismatches",
    b["bit_identical"] and b["compared_samples_total"] == 352968 and b["mismatch_count_samples"] == 0 and b["mae_int16_levels"] == 0.0)
g = ev["D_geometry"]
chk("geometry 640x368 vs 640x360, +8 px, 1.022222",
    g["height_delta_px"] == 8 and g["vertical_ratio_candidate_over_source"] == 1.022222)

# 6. harness rows
c = json.loads((B / "raw/candidate_BOOK.json").read_text(encoding="utf-8"))
vd = {a["assertion"]: a["verdict"] for a in c["assertions"]}
chk("video_codec_contract FAIL (geometry)", vd.get("video_codec_contract") == "FAIL")
chk("not_source_copy PASS", vd.get("not_source_copy") == "PASS")
chk("frame_pairing UNMEASURED", vd.get("frame_pairing") == "UNMEASURED")
chk("cut_timeline UNMEASURED", vd.get("cut_timeline") == "UNMEASURED")
chk("row split 7 PASS / 1 FAIL / 2 UNMEASURED",
    sum(1 for v in vd.values() if v == "PASS") == 7
    and sum(1 for v in vd.values() if v == "FAIL") == 1
    and sum(1 for v in vd.values() if v == "UNMEASURED") == 2,
    "PASS=%d FAIL=%d UNMEASURED=%d" % (sum(1 for v in vd.values() if v == "PASS"),
                                       sum(1 for v in vd.values() if v == "FAIL"),
                                       sum(1 for v in vd.values() if v == "UNMEASURED")))
chk("technical verdict TECHNICAL_FAIL", c["technical_verdict"] == "TECHNICAL_FAIL")
nc = json.loads((B / "raw/negative_controls.json").read_text(encoding="utf-8"))
chk("10 negative controls all non-vacuous", len(nc["results"]) == 10 and all(r["control_proves_non_vacuity"] for r in nc["results"]))

# 7. the frozen candidate is untouched
chk("candidate sha256 unchanged", sha(CAND) == CAND_SHA, sha(CAND)[:16])
chk("candidate size 163391", CAND.stat().st_size == 163391)

# 8. worktree state and commit scope
def git(*a):
    r = subprocess.run(["git"] + list(a), cwd="C:/Users/Admin/Documents/Codex/work/mfv1/wt-bench",
                       capture_output=True, text=True)
    return r.stdout.strip(), r.returncode


out, _ = git("status", "--porcelain")
chk("worktree clean", out == "", out[:120])
out, rc = git("merge-base", "--is-ancestor", "36c912e", "HEAD")
chk("HEAD descends from the pinned wave base 36c912e", rc == 0, out[:80])
out, _ = git("diff", "--name-only", "36c912e..HEAD")
files = [f for f in out.splitlines() if f.strip()]
chk("every commit since 36c912e touches ONLY the bench allowlist",
    bool(files) and all(f.startswith("experiments/mf_reskin_v1/bench/") for f in files),
    "%d files" % len(files))
out, rc = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
chk("branch has no upstream (nothing pushed)", rc != 0, out[:60])

# 9. no stray temp files in the CPU temp area
tmp = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/bench")
stray = [p.name for p in tmp.iterdir() if p.name.startswith("_")]
chk("no stray temp files in runtime/bench", not stray, "; ".join(stray))

print("%-58s %s" % ("CHECK", "RESULT"))
ok = True
for n, o, d in rows:
    ok = ok and o
    print("%-58s %-4s %s" % (n[:58], "PASS" if o else "FAIL", d[:70]))
print("\nFINAL GATE: %d/%d PASS -> %s" % (sum(1 for _, o, _ in rows if o), len(rows), "GATE_PASS" if ok else "GATE_FAIL"))
sys.exit(0 if ok else 1)
