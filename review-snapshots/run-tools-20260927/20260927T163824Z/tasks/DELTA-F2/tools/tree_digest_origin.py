"""DELTA-F2 — where does the pre-existing inventory staleness come from?

tree_digest() hashes WORKTREE BYTES of app/**; the committed inventory.json was
generated in the INTEGRATION worktree.  If the same commit is checked out with a
different EOL state in another worktree (core.autocrlf), the digests differ even
though every blob is identical (pitfall #46 family).

Read-only: imports the builder with bytecode writing disabled and prints digests
plus a per-file byte/CRLF comparison for app/**.  Writes nothing outside its own
temp output.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

WT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F2")
INTEG = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION")
EV = Path(
    r"C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    r"20260927T163824Z/tasks/DELTA-F2"
)
BUILDER_REL = "packaging/demo/build_demo_package_inventory.py"


def load_builder(repo: Path):
    spec = importlib.util.spec_from_file_location(f"builder_{repo.name}", repo / BUILDER_REL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    result: dict = {}
    for label, repo in (("delta_f2", WT), ("integration", INTEG)):
        module = load_builder(repo)
        app = repo / "app"
        result[label] = {
            "head": __import__("subprocess").run(
                ["git", "rev-parse", "HEAD"], cwd=str(repo),
                capture_output=True, text=True).stdout.strip(),
            "app_tree_sha256_live": module.tree_digest(app),
            "files": {},
        }
        for path in sorted(app.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            data = path.read_bytes()
            result[label]["files"][path.relative_to(app).as_posix()] = {
                "bytes": len(data), "crlf": data.count(b"\r\n"),
                "sha256": hashlib.sha256(data).hexdigest()[:16]}
    same = {rel: (a, result["integration"]["files"].get(rel))
            for rel, a in result["delta_f2"]["files"].items()
            if result["integration"]["files"].get(rel) != a}
    result["files_differing_bytes"] = sorted(same)
    result["differ_detail"] = {rel: {"delta_f2": v[0], "integration": v[1]}
                               for rel, v in same.items()}
    committed = json.loads((WT / "packaging/demo/inventory.json").read_text(encoding="utf-8"))
    result["committed_app_tree_sha256"] = committed["backend"]["app_tree_sha256"]
    (EV / "raw").mkdir(parents=True, exist_ok=True)
    (EV / "raw" / "tree_digest_origin.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
