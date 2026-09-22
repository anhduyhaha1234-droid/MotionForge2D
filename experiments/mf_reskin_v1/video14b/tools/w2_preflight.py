"""Wave-2 preflight helpers for MF-V1-VIDEO14B (S0e and input checks).

Subcommands:
  inventory  <object_info.json> <out.json>            node inventory sha256 + class count
  classes    <object_info.json> <api_or_ui.json> ...  every class_type present?
  film       <film.mp4> <expected_sha256>             freeze check
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PKG = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\wt-comfy\experiments\mf_reskin_v1\comfy")
sys.path.insert(0, str(PKG))
from mf_comfy.pinning import hash_node_inventory, sha256_file  # noqa: E402


def _p(s: str) -> Path:
    """Normalise an MSYS path (/c/Users/...) to a Windows native path.

    A Windows python.exe silently treats '/c/...' as a RELATIVE path (\\c\\...),
    so a reviewer copying a command verbatim would hit a false 'missing file'.
    """
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def collect_class_types(obj) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        if "class_type" in obj and isinstance(obj["class_type"], str):
            found.add(obj["class_type"])
        if "type" in obj and isinstance(obj["type"], str) and "inputs" in obj:
            found.add(obj["type"])  # UI-format node
        for v in obj.values():
            found |= collect_class_types(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= collect_class_types(v)
    return found


def main() -> int:
    cmd = sys.argv[1]
    if cmd == "inventory":
        oi = json.loads(_p(sys.argv[2]).read_text(encoding="utf-8"))
        rec = {
            "object_info_path": str(_p(sys.argv[2])),
            "node_inventory_sha256": hash_node_inventory(oi),
            "class_count": len(oi),
        }
        _p(sys.argv[3]).write_text(json.dumps(rec, indent=1), encoding="utf-8")
        print(json.dumps(rec, indent=1))
        return 0
    if cmd == "classes":
        oi = json.loads(_p(sys.argv[2]).read_text(encoding="utf-8"))
        rep = {"object_info": str(_p(sys.argv[2])), "graphs": []}
        bad = 0
        for g in sys.argv[3:]:
            want = collect_class_types(json.loads(_p(g).read_text(encoding="utf-8")))
            missing = sorted(c for c in want if c not in oi)
            rep["graphs"].append({"graph": str(_p(g)), "classes": len(want), "missing": missing})
            bad += len(missing)
        rep["missing_total"] = bad
        print(json.dumps(rep, indent=1))
        return 1 if bad else 0
    if cmd == "film":
        got = sha256_file(_p(sys.argv[2])).upper()
        want = sys.argv[3].upper()
        print(json.dumps({"film": str(_p(sys.argv[2])), "sha256": got, "expected": want,
                          "match": got == want,
                          "size_bytes": _p(sys.argv[2]).stat().st_size}, indent=1))
        return 0 if got == want else 1
    print("unknown subcommand")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
