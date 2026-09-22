"""MF-V1-BENCH wave-2 review bundle - playback deliverables for the human reviewer.

CPU only, deterministic ffmpeg filters, READ-ONLY on every frozen input.
Writes only into <BENCH_EV>/review/wave2, <BENCH_EV>/sheets/wave2_book and
<BENCH_EV>/crops/wave2_book (new directories - the wave-1 sheets/crops are not touched).

The candidate is 640x368 and the source window is 640x360. Every side-by-side and every
paired strip therefore states the transform used, because the 8-row difference is a
measured FAIL of the geometry row and must be visible to the reviewer, not smoothed away:
  - "scale_to_source" : scale=640:360 (the same aspect-squashing transform the harness uses)
  - "native"          : the candidate untouched at 640x368
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

VENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
AENC = ["-c:a", "aac", "-b:a", "160k"]
ANCHORS = [1650, 1665, 1680, 1695, 1710, 1725, 1740, 1755]   # BOOK anchors per CHECKLIST.md row 1
START = 1650
# The candidate and the source clip are both 120-frame windows whose frame i is film
# frame 1650 + i, so the tile selectors must use INDICES (0,15,...), not film frame
# numbers - selecting eq(n,1650) on a 120-frame clip matches nothing and ffmpeg exits
# 0 having written no file.
IDX = [a - START for a in ANCHORS]
SEL = "select='" + "+".join("eq(n\\,%d)" % i for i in IDX) + "'"


def run(argv, label, cwd=None):
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    if r.returncode != 0:
        raise SystemExit("FAILED %s\n  cmd: %s\n  err: %s" % (label, " ".join(argv), r.stderr.strip()[-600:]))
    return r


def size(p):
    p = Path(p)
    return p.stat().st_size if p.exists() else 0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--bench", required=True)
    ap.add_argument("--out-manifest", required=True)
    a = ap.parse_args(argv)

    C = Path(a.candidate)
    S = Path(a.source)
    B = Path(a.bench)
    R = B / "review" / "wave2"
    SH = B / "sheets" / "wave2_book"
    CR = B / "crops" / "wave2_book"
    for d in (R, SH, CR):
        d.mkdir(parents=True, exist_ok=True)

    side = "[0:v]scale=640:360,pad=640:360:0:0[v0];[1:v]scale=640:360[v1];[v0][v1]hstack=inputs=2"

    made = []

    def add(path, label):
        n = size(path)
        if n == 0:
            raise SystemExit("ZERO-BYTE/ABSENT artifact: %s (%s) - ffmpeg can exit 0 having written nothing" % (path, label))
        made.append({"path": str(path), "bytes": n, "label": label})

    # 1/2 - review copies of the candidate (1x and 0.5x), native geometry
    p = R / "BOOK_r4_candidate_1x.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(C), "-c", "copy", str(p)], "candidate 1x copy")
    add(p, "candidate, 1x playback, stream copy, native 640x368, audio kept")
    p = R / "BOOK_r4_candidate_0p5x.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(C), "-vf", "setpts=2.0*PTS", "-af", "atempo=0.5",
         *VENC, *AENC, str(p)], "candidate 0.5x")
    add(p, "candidate, 0.5x playback (slow), native 640x368")

    # 3/4 - review copies of the source window (A/B baseline)
    p = R / "BOOK_r4_source_1x.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(S), "-c", "copy", str(p)], "source 1x copy")
    add(p, "source window [1650,1770), 1x playback, stream copy, 640x360")
    p = R / "BOOK_r4_source_0p5x.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(S), "-vf", "setpts=2.0*PTS", "-af", "atempo=0.5",
         *VENC, *AENC, str(p)], "source 0.5x")
    add(p, "source window [1650,1770), 0.5x playback")

    # 5/6 - side-by-side (source left, candidate right), candidate scaled to 640x360
    p = R / "BOOK_r4_sidebyside_sourceL_candidateR_1x.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(S), "-i", str(C), "-filter_complex", side,
         "-map", "0:a", "-c:a", "aac", "-b:a", "160k", *VENC, str(p)], "sidebyside 1x")
    add(p, "A/B side-by-side L=source 640x360 / R=candidate scale_to_source 640x360, 1x, source audio")
    p = R / "BOOK_r4_sidebyside_sourceL_candidateR_0p5x.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(S), "-i", str(C), "-filter_complex",
         side + "[s];[s]setpts=2.0*PTS[out]",
         "-map", "[out]", "-map", "0:a", "-af", "atempo=0.5",
         *VENC, *AENC, str(p)], "sidebyside 0.5x")
    add(p, "A/B side-by-side, 0.5x playback")

    # 7/8/9 - contact sheets, 16 frames (4 fps over 4 s), 4x4
    for src, name, label in ((S, "BOOK_r4_source_1fps_4x4.png", "source window contact sheet 4x4, 640x360"),
                             (C, "BOOK_r4_candidate_1fps_4x4.png", "candidate contact sheet 4x4, native 640x368")):
        p = SH / name
        run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
             "-vf", "fps=4,scale=320:-2,tile=4x4", "-frames:v", "1", str(p)], "sheet %s" % name)
        add(p, label)
    p = SH / "BOOK_r4_sidebyside_sourceL_candidateR_1fps_4x4.png"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(S), "-i", str(C), "-filter_complex",
         side + "[v];[v]fps=4,scale=320:-2,tile=4x4[out]", "-map", "[out]", "-frames:v", "1", str(p)],
        "sheet sidebyside")
    add(p, "A/B side-by-side contact sheet 4x4 (16 frames = 4 fps over the 4 s window)")

    # 10/11/12 - grip strips at the 8 BOOK anchor frames (f1650,1665,...), centre 320x180
    pc = CR / "BOOK_r4_grip_candidate_centre_320x180_8anchors.png"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(C),
         "-vf", "%s,crop=320:180:160:94,tile=4x2" % SEL, "-vsync", "0", "-frames:v", "1", str(pc)],
        "grip crops candidate")
    add(pc, "candidate grip strip: centre 320x180 crop at anchors f1650/1665/1680/1695/1710/1725/1740/1755 (t=0..3.5 s), tile 4x2, native 640x368 -> crop y=94")
    ps = CR / "BOOK_r4_grip_source_centre_320x180_8anchors.png"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(S),
         "-vf", "%s,crop=320:180:160:90,tile=4x2" % SEL, "-vsync", "0", "-frames:v", "1", str(ps)],
        "grip crops source")
    add(ps, "source grip strip: centre 320x180 crop at the same anchors, tile 4x2, 640x360 -> crop y=90")
    p = CR / "BOOK_r4_grip_sidebyside_320x180x2_8anchors.png"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(C), "-i", str(S), "-filter_complex",
         "[0:v]%s,crop=320:180:160:94[c];[1:v]%s,crop=320:180:160:90[s];[c][s]hstack=inputs=2,tile=4x2[out]" % (SEL, SEL),
         "-map", "[out]", "-vsync", "0", "-frames:v", "1", str(p)], "grip sidebyside")
    add(p, "grip A/B strip per anchor: L=candidate(native crop y=94) R=source(crop y=90), 8 anchors, tile 4x2")

    # 13 - 2x zoom on the grip region (hands+book), anchors only
    p = CR / "BOOK_r4_grip_candidate_zoom2x_8anchors.png"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(C),
         "-vf", "%s,crop=320:184:160:92,scale=640:368,tile=4x2" % SEL, "-vsync", "0", "-frames:v", "1", str(p)],
        "grip zoom")
    add(p, "candidate grip region at 2x (centre 320x184 -> 640x368) for hands/book judgement, 8 anchors")

    # 14 - geometry: the 8-row mismatch made visible (top/bottom edge rows)
    p = CR / "BOOK_r4_geometry_edge_rows_vstack.png"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(C), "-i", str(S), "-filter_complex",
         "[0:v]select='eq(n\\,0)',crop=640:8:0:0,scale=640:24[cT];"
         "[1:v]select='eq(n\\,0)',crop=640:8:0:0,scale=640:24[sT];"
         "[0:v]select='eq(n\\,0)',crop=640:8:0:360,scale=640:24[cB];"
         "[1:v]select='eq(n\\,0)',crop=640:8:0:352,scale=640:24[sB];"
         "[cT][sT][cB][sB]vstack=inputs=4[out]",
         "-map", "[out]", "-vsync", "0", "-frames:v", "1", str(p)], "geometry rows")
    add(p, "geometry evidence, frame i=0, top->bottom bands: candidate top 8 rows, source top 8 rows, candidate bottom 8 rows, source bottom 8 rows (each 640x8 stretched to 640x24)")

    man = {"artifact": "wave2_review_manifest.json", "task_id": "MF-V1-BENCH",
           "candidate": str(C), "source": str(S),
           "candidate_native_geometry": "640x368", "source_geometry": "640x360",
           "anchors_film_frames": ANCHORS, "transform_note": "side-by-side/strips scale the candidate via scale=640:360 unless labelled native",
           "artifacts": made, "total_bytes": sum(m["bytes"] for m in made)}
    Path(a.out_manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_manifest).write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    for m in made:
        print("%9d  %s" % (m["bytes"], m["path"]))
    print("TOTAL %d bytes in %d artifacts" % (man["total_bytes"], len(made)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
