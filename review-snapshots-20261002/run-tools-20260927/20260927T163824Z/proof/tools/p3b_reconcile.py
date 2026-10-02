"""P3b artifact reconciliation.

The first P3b submission (prompt d1f4e097) ran with the SaveVideo prefix INHERITED from the p3
graph (`p3/animate2_book_p3`), so it wrote 00005..00008 into output/p3/.  Two things to establish,
both measured here:

  1. the P3 evidence was NOT overwritten - ComfyUI continued the numbering; every recorded P3
     sha256 still matches on disk.  Verify before touching anything.
  2. the new files ARE the geometry-fixed clips - check dims/frames, then MOVE them (hash-preserving,
     same bytes) into output/p3b/ under a p3b name, recording the mapping.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
P3 = PROOF / "output" / "p3"
P3B = PROOF / "output" / "p3b"


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def probe(p: pathlib.Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate,duration",
                        "-of", "json", str(p)], capture_output=True, text=True)
    return json.loads(r.stdout)["streams"][0] if r.returncode == 0 else {}


rec3 = json.loads((PROOF / "evidence" / "P3_RECEIPT.json").read_text(encoding="utf-8"))
integrity = {}
for m in rec3["output_files"]:
    name = m["file"].split("/")[-1]
    f = P3 / name
    integrity[name] = {"recorded_sha256": m["sha256"], "present": f.is_file(),
                       "sha256_now": sha(f) if f.is_file() else None}
    integrity[name]["unchanged"] = integrity[name]["present"] and \
        integrity[name]["sha256_now"] == integrity[name]["recorded_sha256"]

new = sorted(p for p in P3.glob("animate2_book_p3_0*.mp4")
             if p.name not in {m["file"].split("/")[-1] for m in rec3["output_files"]})
P3B.mkdir(parents=True, exist_ok=True)
moved = []
for i, src in enumerate(new, start=1):
    dst = P3B / f"animate2_book_p3b_{i:05d}_.mp4"
    before = sha(src)
    shutil.move(str(src), str(dst))
    moved.append({"from": f"p3/{src.name}", "to": f"p3b/{dst.name}",
                  "sha256_before": before, "sha256_after": sha(dst),
                  "byte_identical": before == sha(dst), "bytes": dst.stat().st_size,
                  "ffprobe": probe(dst)})
out = {"artifact": "P3B_ARTIFACT_RECONCILIATION.json",
       "prompt_id": "d1f4e097-458d-4bd4-8049-fe6da26f91c1",
       "incident": "the P3b graph inherited the SaveVideo prefix p3/animate2_book_p3 (the prefix "
                   "was not part of the geometry delta), so the first P3b run wrote 00005..00008 "
                   "into output/p3/",
       "p3_evidence_integrity": integrity,
       "p3_evidence_intact": all(v["unchanged"] for v in integrity.values()),
       "relocated": moved, "relocated_count": len(moved),
       "why_no_rerun": "the SaveVideo prefix does not enter the computation - same graph, same "
                       "seed, same inputs produce the same pixels - so re-running for a filename "
                       "would burn a GPU job; the outputs are relocated instead and the graph file "
                       "kept byte-identical to the one that ran (sha recorded in P3B_GRAPH.json)",
       "footgun_for_next_round": "re-point SaveVideo 246/292 to p3b/... before the next submission"}
(PROOF / "evidence" / "P3B_ARTIFACT_RECONCILIATION.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"p3_intact": out["p3_evidence_intact"],
                  "moved": [{k: m[k] for k in ("from", "to", "byte_identical")} for m in moved],
                  "new_dims": {m["to"]: [m["ffprobe"].get("width"), m["ffprobe"].get("height"),
                                         m["ffprobe"].get("nb_read_frames"),
                                         m["ffprobe"].get("r_frame_rate")] for m in moved}},
                 indent=1))
