"""S12-T06A manifest builder — generate packaging/windows/manifest.json.

Reads REAL local state only (no network, no install, no elevation):
  - backend pins from pyproject.toml [project].dependencies
  - frontend pins from frontend/package.json + resolved versions in
    frontend/package-lock.json (when present)
  - compiled-frontend fingerprint: frontend/.next/BUILD_ID (sha256),
    frontend/.next/required-server-files.json (sha256), static file count
  - backend source fingerprint: sha256 of app/main.py + app/api/app.py
  - toolchain: python/node/npm/ffmpeg version probes (missing -> recorded
    as available:false, never fatal here; preflight.py enforces policy)

Usage (from repo root):
    python scripts/s12/s12_t06a_build_manifest.py [--out packaging/windows/manifest.json]

Exit 0 on success. Missing .next build -> exit 2 with NOT_RUN reason
(the frontend must be built first; the manifest must never be faked).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_probe(exe: str, args: list[str]) -> dict:
    found = shutil.which(exe)
    if found is None:
        return {"available": False, "path": None, "version": None,
                "error": f"{exe} not found on PATH"}
    try:
        out = subprocess.run([found, *args], capture_output=True, text=True,
                             timeout=30)
        first = (out.stdout or out.stderr or "").splitlines()
        return {"available": out.returncode == 0, "path": found,
                "version": first[0].strip() if first else None,
                "error": None if out.returncode == 0
                else f"{exe} exited {out.returncode}"}
    except (OSError, subprocess.TimeoutExpired) as err:
        return {"available": False, "path": found, "version": None,
                "error": str(err)}


def backend_pins(repo: Path) -> list[str]:
    with open(repo / "pyproject.toml", "rb") as fh:
        data = tomllib.load(fh)
    deps = data.get("project", {}).get("dependencies", [])
    return sorted(deps)


def frontend_pins(repo: Path) -> dict:
    fe = repo / "frontend"
    pkg = json.loads((fe / "package.json").read_text(encoding="utf-8"))
    lock_path = fe / "package-lock.json"
    locked: dict[str, str] = {}
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        for key, val in (lock.get("packages", {}) or {}).items():
            if key.startswith("node_modules/") and "/" not in key[len("node_modules/"):]:
                name = key[len("node_modules/"):]
                if isinstance(val, dict) and val.get("version"):
                    locked[name] = val["version"]
    out: dict[str, dict[str, str | None]] = {}
    for section in ("dependencies", "devDependencies"):
        for name, rang in (pkg.get(section, {}) or {}).items():
            out[name] = {"range": str(rang),
                         "locked": locked.get(name)}
    return out


def frontend_artifact(repo: Path) -> dict:
    fe = repo / "frontend"
    nxt = fe / ".next"
    if not (nxt / "BUILD_ID").is_file():
        return {"built": False,
                "error": "frontend/.next/BUILD_ID missing: run "
                         "'npm run build' in frontend/ first (NOT_RUN)"}
    build_id = (nxt / "BUILD_ID").read_text(encoding="utf-8").strip()
    req = nxt / "required-server-files.json"
    static_dir = nxt / "static"
    static_files: list[str] = []
    if static_dir.is_dir():
        static_files = sorted(
            str(p.relative_to(nxt)).replace("\\", "/")
            for p in static_dir.rglob("*") if p.is_file())
    return {"built": True, "build_id": build_id,
            "build_id_sha256": hashlib.sha256(build_id.encode()).hexdigest(),
            "required_server_files_sha256":
                sha256_file(req) if req.is_file() else None,
            "static_file_count": len(static_files)}


def backend_fingerprint(repo: Path) -> dict:
    files = ["app/main.py", "app/api/app.py", "app/config.py",
             "app/lifecycle.py", "alembic.ini"]
    out: dict[str, str | None] = {}
    for rel in files:
        p = repo / rel
        out[rel] = sha256_file(p) if p.is_file() else None
    return out


def git_head(repo: Path) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="packaging/windows/manifest.json")
    args = ap.parse_args(argv)
    repo = Path(__file__).resolve().parent.parent.parent
    art = frontend_artifact(repo)
    if not art.get("built"):
        print(f"NOT_RUN: {art.get('error')}", flush=True)
        return 2
    manifest = {
        "schema": "s12-t06a-manifest/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": git_head(repo),
        "backend": {"pins": backend_pins(repo),
                    "source_sha256": backend_fingerprint(repo),
                    "requires_python": ">=3.11,<3.13"},
        "frontend": {"pins": frontend_pins(repo), "artifact": art},
        "toolchain": {
            "python": run_probe(sys.executable, ["--version"]),
            "node": run_probe("node", ["--version"]),
            "npm": run_probe("npm", ["--version"]),
            "ffmpeg": run_probe("ffmpeg", ["-hide_banner", "-version"]),
        },
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = repo / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"manifest written: {out}", flush=True)
    print(f"  backend pins: {len(manifest['backend']['pins'])}", flush=True)
    print(f"  frontend deps: {len(manifest['frontend']['pins'])}", flush=True)
    print(f"  build_id: {art['build_id']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
