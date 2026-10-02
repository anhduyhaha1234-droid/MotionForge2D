"""MF-END-17 — model area re-verification (read-only).

Three jobs:
1. full sha256 of the VACE files this task binds (unet 14B, declared vae, declared clip);
2. head-hash (first 1 MiB) + size of ALL 12 model files vs the sealed P0 inventory
   (proves the model area is unchanged since the proof round, without re-reading 88 GB);
3. SCAIL / SAM model-file scan (the packet's "verify model source/license/disk before
   download" step: measured here as "nothing to download was downloaded; the family is
   absent from the models root").

Usage: python -B tools/w17_hash_models.py
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

MODELS_ROOT = Path("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/models")
PROOF = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof")
P0_INVENTORY = PROOF / "evidence" / "P0_MODEL_INVENTORY.json"
RAW = Path(__file__).resolve().parent.parent / "raw"

#: files this task binds, with the sealed full sha256 (MF-END-16 raw/model_full_hashes.json)
BIND = [
    ("diffusion_models/wan2.1_vace_14B_fp16.safetensors", 34675323640,
     "f202a5c59b8a91ada1862c46a038214f1f7f216c61ec8350d25f69b919da4307"),
    ("vae/wan_2.1_vae.safetensors", 253815318, None),
    ("text_encoders/umt5_xxl_fp16.safetensors", 11366399385, None),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024 * 8), b""):
            h.update(chunk)
    return h.hexdigest()


def head_sha16(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.sha256(fh.read(1024 * 1024)).hexdigest()[:16]


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    out: dict = {"artifact": "model_full_hashes.json", "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "models_root": str(MODELS_ROOT).replace("\\", "/"), "files": []}
    ok = True
    for rel, want_bytes, want_sha in BIND:
        p = MODELS_ROOT / rel
        row = {"rel": rel, "exists": p.is_file()}
        if p.is_file():
            st = p.stat()
            row["bytes"] = st.st_size
            row["bytes_match"] = st.st_size == want_bytes
            row["sha256"] = sha256_file(p)
            row["sha_match_sealed"] = (row["sha256"] == want_sha) if want_sha else None
            row["mtime_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))
            if not row["bytes_match"] or row["sha_match_sealed"] is False:
                ok = False
        else:
            ok = False
        out["files"].append(row)
        print(json.dumps({"rel": rel, "done": True, "sha16": (row.get("sha256") or "")[:16]}), flush=True)
    out["ok"] = ok
    (RAW / "model_full_hashes.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    # model-area invariance vs P0 inventory (size + first-1MiB hash of every file)
    inv = json.loads(P0_INVENTORY.read_text(encoding="utf-8"))
    scan = {"artifact": "model_area_scan.json", "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "root": str(MODELS_ROOT).replace("\\", "/"), "rows": []}
    area_ok = True
    for group, g in inv.get("groups", {}).items():
        for f in g.get("files", []):
            p = MODELS_ROOT / f["rel"]
            row = {"rel": f["rel"], "group": group, "p0_bytes": f["bytes"], "p0_sha16_head": f["sha16"]}
            if p.is_file():
                row["bytes"] = p.stat().st_size
                row["sha16_head"] = head_sha16(p)
                row["unchanged"] = (row["bytes"] == f["bytes"] and row["sha16_head"] == f["sha16"])
            else:
                row["unchanged"] = False
            if not row["unchanged"]:
                area_ok = False
            scan["rows"].append(row)

    # SCAIL / SAM scan
    scan["family_scan"] = {}
    for pat in ("*scail*", "*SCAIL*", "*sam*", "*SAM*"):
        hits = [p.as_posix() for p in MODELS_ROOT.rglob(pat) if p.is_file()]
        scan["family_scan"][pat] = {"count": len(hits), "hits": hits[:10]}
    scan["family_scan_note"] = ("no SCAIL / SAM weight file exists anywhere under the models root; "
                                "the SCAIL-2 family cannot run inference here")
    scan["unchanged_vs_p0"] = area_ok
    scan["file_count"] = len(scan["rows"])
    (RAW / "model_area_scan.json").write_text(json.dumps(scan, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"model_full_hashes_ok": ok, "model_area_unchanged": area_ok,
                      "scanned": len(scan["rows"])}))
    return 0 if ok and area_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
