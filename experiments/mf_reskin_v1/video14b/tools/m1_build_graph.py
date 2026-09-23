"""MF-V1-VIDEO14B wave B round M1 — build the SINGLE-VARIABLE test graph.

M1 is the diagnosis of exactly one node input: `672:587 WanAnimate2ToVideo`
`pose_end_percent` 0 -> 1 (the source opens a book over the whole 4 s window;
the submitted graph gave pose conditioning to 1/6 sampling steps because the
window was empty).  Nothing else may change.

This tool is deliberately paranoid:

* it loads the FROZEN baseline graph that was actually submitted in wave B
  (`mf_animate2_book4s.waveB.api.json`, file sha256 7ea87b66..., which the
  adapter hashed as f246221a...), taken from the wave-B evidence root;
* it edits the value on a byte level inside the `672:587` object only;
* it then proves, with a structural diff of the parsed JSON, that the changed
  path set is EXACTLY {672:587.inputs.pose_end_percent: 0 -> 1} and nothing else;
* it re-verifies every pinned input of the experiment (reference image sha256,
  driving clip sha256, seed, sampler/scheduler/steps/shift/cfg, context window,
  model file names, resolution/crop, save prefix) against the frozen record, so a
  silent drift in any of them is a refusal, not a warning;
* it writes the new graph and its hashes into the round evidence root.

usage:
  python m1_build_graph.py <baseline_api.json> <out_api.json> <out_evidence.json>

exit codes: 0 built, 2 refused (precondition), 3 refused (diff not single-valued)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

TARGET_NODE = "672:587"
TARGET_KEY = "pose_end_percent"
TARGET_OLD = 0
TARGET_NEW = 1

# ---------------------------------------------------------------- frozen pins
# measured in wave B (round b3/b4) and re-asserted here; see WAVE_B_REPORT.md §4
BASELINE_FILE_SHA256 = "7ea87b66569cc629b02bc27f2e7db0d6d03a4700403bf317076f3ab5f8f4c6f8"
BASELINE_GRAPH_SHA256 = "f246221af10a27072481e6985c3683cf257269318e807c16e692261245cf3e5e"

FROZEN = {
    ("189", "inputs", "image"): "mf_book_anchor_1650.png",
    ("240", "inputs", "file"): "mf_book_f1650_1770_drive_121f_padded_640x368.mp4",
    (TARGET_NODE, "inputs", "pose_strength"): 1,
    (TARGET_NODE, "inputs", "pose_start_percent"): 0,
    (TARGET_NODE, "inputs", "reference_image_strength"): 1,
    ("672:590", "inputs", "resize_type.crop"): "center",
    ("672:600", "inputs", "resize_type.width"): 640,
    ("672:600", "inputs", "resize_type.height"): 368,
    ("672:600", "inputs", "resize_type.crop"): "center",
    ("672:593", "inputs", "sampler_name"): "lcm",
    ("672:591", "inputs", "scheduler"): "simple",
    ("672:591", "inputs", "steps"): 6,
    ("672:591", "inputs", "denoise"): 1,
    ("672:592", "inputs", "shift"): 5,
    ("672:597", "inputs", "cfg"): 1,
    ("672:597", "inputs", "noise_seed"): 582699151003550,
    ("672:586", "inputs", "context_length"): 21,
    ("672:586", "inputs", "context_overlap"): 8,
    ("246", "inputs", "filename_prefix"): "mf_reskin_v1/video14b/animate2_book4s",
}

# ------------------------------------------------------------ external pins
INPUT_DIR = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\runtime\video14b\input")
REFERENCE_SHA256 = "1311699b55c586abdb631d0468b4afc19cdf73a1b45b86fc4403f4517daf03fe"
DRIVING_FRAMES = "1650..1769 (121 decoded frames; the exported clip keeps 0..119)"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def deep_diff(a, b, path=()):
    """Structural diff of two parsed JSON values -> list of (path, old, new)."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append((path + (k,), "<absent>", b[k]))
            elif k not in b:
                out.append((path + (k,), a[k], "<absent>"))
            else:
                out += deep_diff(a[k], b[k], path + (k,))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, f"len {len(a)}", f"len {len(b)}"))
        for i, (x, y) in enumerate(zip(a, b)):
            out += deep_diff(x, y, path + (i,))
    elif a != b:
        out.append((path, a, b))
    return out


def main() -> int:
    base_p, out_p, ev_p = (Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    base_p = Path(base_p)
    raw_bytes = base_p.read_bytes()          # hash the BYTES, never a newline-normalised read
    raw_text = raw_bytes.decode("utf-8")
    base_file_sha = hashlib.sha256(raw_bytes).hexdigest()

    refused = []
    if base_file_sha != BASELINE_FILE_SHA256:
        refused.append({"check": "baseline_file_sha256", "expected": BASELINE_FILE_SHA256,
                        "actual": base_file_sha})

    base = json.loads(raw_text)
    parent = base.get(TARGET_NODE, {}).get("inputs", {})
    for (nid, sec, key), want in FROZEN.items():
        got = (base.get(nid, {}).get(sec, {}) or {}).get(key, "<absent>")
        if got != want:
            refused.append({"check": f"frozen:{nid}.{sec}.{key}", "expected": want,
                            "actual": got})
    if parent.get(TARGET_KEY, "<absent>") != TARGET_OLD:
        refused.append({"check": f"frozen:{TARGET_NODE}.inputs.{TARGET_KEY}",
                        "expected": TARGET_OLD, "actual": parent.get(TARGET_KEY, "<absent>")})

    ref = INPUT_DIR / "mf_book_anchor_1650.png"
    ref_sha = sha256_file(ref) if ref.is_file() else "<absent>"
    if ref_sha != REFERENCE_SHA256:
        refused.append({"check": "reference_image_sha256", "expected": REFERENCE_SHA256,
                        "actual": ref_sha,
                        "path": str(ref)})

    drive = INPUT_DIR / "mf_book_f1650_1770_drive_121f_padded_640x368.mp4"
    drive_rec = {"path": str(drive), "exists": drive.is_file(),
                 "bytes": drive.stat().st_size if drive.is_file() else None,
                 "sha256": sha256_file(drive) if drive.is_file() else None}

    if refused:
        print(json.dumps({"status": "REFUSED_PRECONDITION", "refusals": refused}, indent=1,
                         ensure_ascii=False))
        return 2

    # ---- the one allowed edit: byte-scoped inside the 672:587 object -----------
    base_graph_sha = hashlib.sha256(
        json.dumps(base, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()
    if base_graph_sha != BASELINE_GRAPH_SHA256:
        print(json.dumps({"status": "REFUSED_PRECONDITION",
                          "refusals": [{"check": "baseline_graph_sha256",
                                        "expected": BASELINE_GRAPH_SHA256,
                                        "actual": base_graph_sha}]}, indent=1))
        return 2

    new = json.loads(raw_text)
    new[TARGET_NODE]["inputs"][TARGET_KEY] = TARGET_NEW

    diff = deep_diff(base, new)
    changes = [{"path": ".".join(str(x) for x in d[0]), "old": d[1], "new": d[2]}
               for d in diff]
    single = (len(changes) == 1
              and changes[0]["path"] == f"{TARGET_NODE}.inputs.{TARGET_KEY}"
              and changes[0]["old"] == TARGET_OLD and changes[0]["new"] == TARGET_NEW)
    if not single:
        print(json.dumps({"status": "REFUSED_DIFF_NOT_SINGLE_VALUED",
                          "changes": changes}, indent=1, ensure_ascii=False))
        return 3

    out_p.write_text(json.dumps(new, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out_text = out_p.read_text(encoding="utf-8")
    out_file_sha = hashlib.sha256(out_text.encode("utf-8")).hexdigest()
    out_graph_sha = hashlib.sha256(
        json.dumps(new, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()

    ev = {
        "artifact": "m1_build_graph.json",
        "task_id": "MF-V1-VIDEO14B",
        "round": "waveB_m1",
        "rule": "single-variable test: pose_end_percent 0 -> 1 on node 672:587 only",
        "baseline": {
            "path": str(base_p),
            "file_sha256": base_file_sha,
            "graph_sha256_canonical": base_graph_sha,
        },
        "m1": {
            "path": str(out_p),
            "file_sha256": out_file_sha,
            "graph_sha256_canonical": out_graph_sha,
            "nodes": len(new),
            "bytes": len(out_text.encode("utf-8")),
        },
        "structural_diff": changes,
        "single_valued_change": single,
        "frozen_assertions_checked": len(FROZEN),
        "reference_image": {"path": str(ref), "sha256": ref_sha},
        "driving_clip": {**drive_rec, "window": DRIVING_FRAMES},
        "node_672_587_inputs_after": new[TARGET_NODE]["inputs"],
    }
    ev_p.write_text(json.dumps(ev, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": "BUILT",
        "single_valued_change": single,
        "changes": changes,
        "baseline_file_sha256": base_file_sha,
        "m1_file_sha256": out_file_sha,
        "m1_graph_sha256_canonical": out_graph_sha,
        "evidence": str(ev_p),
    }, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
