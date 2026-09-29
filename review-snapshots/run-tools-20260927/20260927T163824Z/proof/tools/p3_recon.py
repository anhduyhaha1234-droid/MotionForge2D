"""P3 recon: which loader enum values the LIVE server accepts, how the three wave-B graph
variants differ, and where the template's own input files live.
"""
from __future__ import annotations

import json
import pathlib

PROOF = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
                     r"20260927T163824Z/proof")
WB = pathlib.Path(r"C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                  r"mf-reskin-correction-20260922/20260922T0955Z/VIDEO14B/waveB/workflows")
INPUT = pathlib.Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/input")

oi = json.loads((PROOF / "evidence" / "P0_object_info.json").read_text(encoding="utf-8"))
for ct, key in (("UNETLoader", "unet_name"), ("VAELoader", "vae_name"), ("CLIPLoader", "clip_name"),
                ("CLIPVisionLoader", "clip_name"), ("LoraLoaderModelOnly", "lora_name")):
    decl = oi.get(ct, {}).get("input", {}).get("required", {}).get(key)
    print(f"{ct}.{key} = {json.dumps(decl)[:300]}")

print("=== template files present in the runtime input dir? ===")
for n in ("mf_book_anchor_1650.png", "mf_book_f1650_1770_drive_120f.mp4",
          "mf_book_f1650_1770_drive_121f.mp4", "mf_book_f1650_1770_drive_121f_padded_640x368.mp4"):
    p = INPUT / n
    print(f"  {n}: {p.is_file()} {p.stat().st_size if p.is_file() else ''}")

print("=== variant deltas ===")
gs = {n: json.loads((WB / f"mf_animate2_book4s.{n}.api.json").read_text(encoding="utf-8"))
      for n in ("api", "fixed", "shim")}
base = gs["api"]
for name, g in gs.items():
    if name == "api":
        continue
    diffs = []
    for nid in sorted(set(base) | set(g)):
        a, b = base.get(nid), g.get(nid)
        if a != b:
            diffs.append(nid)
    print(f"  api vs {name}: {len(diffs)} nodes differ -> {diffs[:12]}")
print("=== key params of fixed ===")
f = gs["fixed"]
for nid in ("189", "240", "246", "292", "672:578", "672:579", "672:580", "672:583", "672:584",
            "672:587", "672:591", "672:592", "672:593", "672:594", "672:597", "672:600",
            "672:635", "672:586"):
    node = f.get(nid)
    if node:
        inp = {k: v for k, v in node["inputs"].items() if not (isinstance(v, list) and len(v) == 2
                                                               and isinstance(v[0], str))}
        print(f"  {nid} {node['class_type']}: {json.dumps(inp)[:200]}")
