"""MF-END-17 — probe the controlled candidate's provenance on the Hub (read-only GET).

Verifies, per pinned revision: repo license, revision sha/date, and per-file size + LFS oid
so the manifest's `hf_lfs_oid_equals_measured_sha256` claim for the VACE row is backed by
saved raw bytes.  Writes raw/hf_provenance_probe.json.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "raw"

TARGETS = [
    ("Comfy-Org/Wan_2.1_ComfyUI_repackaged", "617a7633e636506f850e043bc4605f290a466a8e", [
        "split_files/diffusion_models/wan2.1_vace_14B_fp16.safetensors",
        "split_files/vae/wan_2.1_vae.safetensors",
        "split_files/text_encoders/umt5_xxl_fp16.safetensors",
    ]),
]


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main() -> int:
    measured = {}
    mf = RAW / "model_full_hashes.json"
    if mf.is_file():
        for f in json.loads(mf.read_text(encoding="utf-8")).get("files", []):
            measured[f["rel"].split("/")[-1]] = {"sha256": f.get("sha256"), "bytes": f.get("bytes")}

    out = {"artifact": "hf_provenance_probe.json", "repos": []}
    for repo, rev, files in TARGETS:
        info = get(f"https://huggingface.co/api/models/{repo}/revision/{rev}")
        tree = get(f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true&revision={rev}")
        by = {e["path"]: e for e in tree}
        row = {"repo": repo, "revision": info.get("sha"), "license": (info.get("cardData") or {}).get("license"),
               "lastModified": info.get("lastModified"), "files": []}
        for path in files:
            e = by.get(path)
            name = path.split("/")[-1]
            m = measured.get(name, {})
            oid = (e.get("lfs") or {}).get("oid") if e else None
            row["files"].append({
                "path": path,
                "exists": e is not None,
                "size": e.get("size") if e else None,
                "lfs_oid": oid,
                "measured_bytes": m.get("bytes"),
                "measured_sha256": m.get("sha256"),
                "size_matches_measured": bool(e and m.get("bytes") == e.get("size")),
                "lfs_oid_equals_measured_sha256": bool(oid and oid == m.get("sha256")),
            })
        out["repos"].append(row)
        print(f"{repo}@{rev[:12]} license={row['license']} files={len(row['files'])}")
    dest = RAW / "hf_provenance_probe.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    ok = all(f["exists"] and f["size_matches_measured"] and f["lfs_oid_equals_measured_sha256"]
             for r in out["repos"] for f in r["files"])
    print(json.dumps({"ok": ok, "dest": str(dest)}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
