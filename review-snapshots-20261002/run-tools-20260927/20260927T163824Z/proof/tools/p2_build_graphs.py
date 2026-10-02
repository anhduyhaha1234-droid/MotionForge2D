"""P2 step 1: stage the pinned inputs into PROOF/inputs and build the three anchor graphs.

The graphs are the R27-I1 graphs that ACTUALLY RAN (anchor_{book,turn,occ}.i1.api.json), with a
MEASURED delta: SaveImage.filename_prefix -> the proof output dir.  Every other node/input is
copied byte-for-byte, and the script prints the diff so the delta is provable, not asserted.

Also: stage the LoadImage-visible filenames into PROOF/inputs (copies; sources untouched) and
validate every class/required input against P0_object_info.json before anything is submitted.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
R27 = pathlib.Path(r"C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                   r"mf-cpu-input-correction-20260927/20260927T051440Z/VIDEO14B")
RUNTIME_INPUT = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/input")
SHOTS = ("BOOK", "TURN", "OCC")


def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def gen_sha(blob: str) -> str:
    return hashlib.sha256(blob.encode()).hexdigest()


oi = json.loads((PROOF / "evidence" / "P0_object_info.json").read_text(encoding="utf-8"))
spec = json.loads((R27 / "graph_proposals" / "roundI1_spec.json").read_text(encoding="utf-8"))
(PROOF / "graphs").mkdir(parents=True, exist_ok=True)
(PROOF / "inputs").mkdir(parents=True, exist_ok=True)

# ---- 1. stage the LoadImage-visible names (i1_* staged files + i1d_* derived refs) --------
staged = {}
for name in ("i1_BOOK_f000_640x368.png", "i1_TURN_f000_640x368.png", "i1_TURN_f080_640x368.png",
             "i1_OCC_f000_640x368.png", "i1_OCC_f040_640x368.png",
             "i1_cast_boy_hacker_sitting.png", "i1_cast_dan_choi_standing.png",
             "i1_cast_gau_nau_back.png"):
    src = RUNTIME_INPUT / name
    if not src.is_file():
        staged[name] = {"staged": False, "why": "not in the runtime input dir"}
        continue
    dst = PROOF / "inputs" / name
    if not dst.exists() or sha(dst) != sha(src):
        shutil.copy2(src, dst)
    staged[name] = {"staged": True, "src": str(src).replace("\\", "/"),
                    "bytes": dst.stat().st_size, "sha256": sha(dst),
                    "byte_identical_to_runtime": sha(dst) == sha(src)}
for name in ("i1d_cast_boy_hacker_sitting_on_neutral_bg.png",
             "i1d_cast_dan_choi_standing_on_neutral_bg.png",
             "i1d_cast_gau_nau_back_on_neutral_bg.png"):
    dst = PROOF / "inputs" / name
    staged[name] = {"staged": dst.is_file(), "from": "R27 derived_inference_input (copied in P1)",
                    "bytes": dst.stat().st_size if dst.is_file() else 0,
                    "sha256": sha(dst) if dst.is_file() else None}

# ---- 2. build the graphs with a MEASURED delta -------------------------------------------
report = {"artifact": "P2_GRAPHS.json", "built_by": "proof/tools/p2_build_graphs.py",
          "template": "R27-I1 graphs that ran for real (anchor_{shot}.i1.api.json)",
          "staged_inputs": staged, "graphs": {}, "validation": {}}
written = []
for shot in SHOTS:
    src = R27 / "graph_proposals" / f"anchor_{shot.lower()}.i1.api.json"
    g = json.loads(src.read_text(encoding="utf-8"))
    prefix_old = g["9"]["inputs"]["filename_prefix"]
    prefix_new = f"anchors/anchor_{shot.lower()}_p2"
    g["9"]["inputs"]["filename_prefix"] = prefix_new
    out = PROOF / "graphs" / f"anchor_{shot.lower()}.p2.api.json"
    out.write_text(json.dumps(g, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    # measured diff vs the template
    diffs = []
    tpl = json.loads(src.read_text(encoding="utf-8"))
    for nid in sorted(set(tpl) | set(g)):
        a, b = tpl.get(nid), g.get(nid)
        if a == b:
            continue
        for k in set(((a or {}).get("inputs") or {})) | set(((b or {}).get("inputs") or {})):
            av = ((a or {}).get("inputs") or {}).get(k)
            bv = ((b or {}).get("inputs") or {}).get(k)
            if av != bv:
                diffs.append({"node": nid, "class_type": (b or a).get("class_type"),
                              "input": k, "template": av, "built": bv})
    roles = {}
    for nid, node in g.items():
        if node["class_type"] == "LoadImage":
            roles[nid] = node["inputs"]["image"]
    report["graphs"][shot] = {
        "path": f"graphs/anchor_{shot.lower()}.p2.api.json", "sha256": sha(out),
        "nodes": len(g), "seed": g["75:73"]["inputs"]["noise_seed"],
        "steps": g["75:62"]["inputs"]["steps"], "cfg": g["75:63"]["inputs"]["cfg"],
        "sampler": g["75:61"]["inputs"]["sampler_name"],
        "models": {"unet": g["75:70"]["inputs"]["unet_name"],
                   "clip": [g["75:71"]["inputs"]["clip_name"], g["75:71"]["inputs"]["type"]],
                   "vae": g["75:72"]["inputs"]["vae_name"]},
        "size": [g["75:66"]["inputs"]["width"], g["75:66"]["inputs"]["height"]],
        "megapixels": g["75:80"]["inputs"]["megapixels"],
        "loadimage_roles": roles,
        "prompt_chars": len(g["75:74"]["inputs"]["text"]),
        "prompt_sha256": gen_sha(g["75:74"]["inputs"]["text"]),
        "template_sha256": sha(src),
        "delta_vs_template": diffs,
        "delta_is_prefix_only": all(d["node"] == "9" and d["input"] == "filename_prefix"
                                    for d in diffs),
        "filename_prefix": prefix_new}
    # ---- 3. validate against the LIVE object_info ----------------------------------------
    errs, warns = [], []
    for nid, node in g.items():
        ct = node["class_type"]
        if ct not in oi:
            errs.append(f"node {nid}: class_type {ct!r} not registered")
            continue
        req = oi[ct]["input"].get("required", {}) or {}
        opt = oi[ct]["input"].get("optional", {}) or {}
        for k in req:
            if k not in node["inputs"]:
                errs.append(f"node {nid} ({ct}): missing required input {k!r}")
        for k in node["inputs"]:
            base = k.split(".", 1)[0]
            if base not in req and base not in opt:
                warns.append(f"node {nid} ({ct}): input {k!r} not declared by the engine")
    report["validation"][shot] = {"errors": errs, "warnings": warns,
                                  "ok": not errs, "nodes_checked": len(g)}
    written.append(str(out).replace("\\", "/"))
    print(f"{shot}: {len(g)} nodes, seed {report['graphs'][shot]['seed']}, prefix "
          f"{prefix_new}, delta {diffs}, errors {len(errs)}")

report["all_graphs_valid"] = all(v["ok"] for v in report["validation"].values())
report["written"] = written
(PROOF / "evidence" / "P2_GRAPHS.json").write_text(
    json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"all_valid": report["all_graphs_valid"],
                  "staged": sum(1 for v in staged.values() if v.get("staged")),
                  "written": written}, indent=1, ensure_ascii=False))
