"""S12-T06A manifest builder — generate packaging/windows/manifest.json.

Reads REAL local state only (no network, no install, no elevation):
  - backend pins from pyproject.toml [project].dependencies (exact ==)
  - frontend pins from package.json ranges + REAL locked versions from
    package-lock.json (scoped packages included)
  - package artifact fingerprint: .next BUILD_ID + required-server-files
    sha256 + backend tree digest
  - endpoint (baked backend/frontend ports + API base URL)
  - toolchain VERSIONS only — never absolute user paths (F09: no Admin
    tool paths in the manifest)

Usage (from repo root):
    python scripts/s12/s12_t06a_build_manifest.py [--out <path>]
                                                  [--backend-port N]
                                                  [--frontend-port N]

Exit 0 on success. Missing .next build -> exit 2 with NOT_RUN reason.
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

REPO = Path(__file__).resolve().parent.parent.parent


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_probe_version(exe: str, args: list[str]) -> dict:
    """Version-only probe; never records absolute executable paths."""
    found = shutil.which(exe)
    if found is None:
        return {"available": False, "version": None,
                "error": f"{exe} not found on PATH"}
    try:
        out = subprocess.run([found, *args], capture_output=True, text=True,
                             timeout=30)
        first = (out.stdout or out.stderr or "").splitlines()
        return {"available": out.returncode == 0,
                "version": first[0].strip() if first else None,
                "error": None if out.returncode == 0
                else f"{exe} exited {out.returncode}"}
    except (OSError, subprocess.TimeoutExpired) as err:
        return {"available": False, "version": None, "error": str(err)}


def _git_head(repo: Path) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def backend_pins(repo: Path) -> list[str]:
    with open(repo / "pyproject.toml", "rb") as fh:
        data = tomllib.load(fh)
    deps = data.get("project", {}).get("dependencies", [])
    return sorted(deps)


def frontend_pins(repo: Path) -> dict[str, dict[str, str | None]]:
    """Ranges from package.json + REAL locked versions (scoped-aware).

    package-lock.json v3 uses keys like 'node_modules/@tanstack/react-query';
    the scoped name must keep its '/' (F09: no null dependency locks).
    """
    fe = repo / "frontend"
    pkg = json.loads((fe / "package.json").read_text(encoding="utf-8"))
    lock_path = fe / "package-lock.json"
    locked: dict[str, str] = {}
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        for key, val in (lock.get("packages", {}) or {}).items():
            if not key.startswith("node_modules/"):
                continue
            name = key[len("node_modules/"):]
            if isinstance(val, dict) and val.get("version"):
                locked[name] = val["version"]
    out: dict[str, dict[str, str | None]] = {}
    for section in ("dependencies", "devDependencies"):
        for name, rang in (pkg.get(section, {}) or {}).items():
            out[name] = {"range": str(rang), "locked": locked.get(name)}
    return out


def artifact_fingerprint(repo: Path) -> dict:
    fe = repo / "frontend"
    nxt = fe / ".next"
    if not (nxt / "BUILD_ID").is_file():
        return {"built": False,
                "error": "frontend/.next/BUILD_ID missing: run "
                         "'npm run build' in frontend/ first (NOT_RUN)"}
    build_id = (nxt / "BUILD_ID").read_text(encoding="utf-8").strip()
    req = nxt / "required-server-files.json"
    return {"built": True, "build_id": build_id,
            "build_id_sha256": hashlib.sha256(build_id.encode()).hexdigest(),
            "required_server_files_sha256":
                sha256_file(req) if req.is_file() else None,
            "backend_tree_sha256": _tree_digest(repo / "app")}


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    if not root.is_dir():
        return "MISSING"
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            rel = p.relative_to(root).as_posix()
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update(sha256_file(p).encode("ascii"))
    return h.hexdigest()


def build_manifest_dict(repo: Path, backend_port: int,
                        frontend_port: int) -> dict:
    art = artifact_fingerprint(repo)
    if not art.get("built"):
        raise SystemExit(f"NOT_RUN: {art.get('error')}")
    return {
        "schema": "s12-t06a-package/2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": _git_head(repo),
        "endpoint": {
            "backend_port": backend_port,
            "frontend_port": frontend_port,
            "api_base_url": f"http://127.0.0.1:{backend_port}",
        },
        "backend": {
            "pins": backend_pins(repo),
            "tree_sha256": art.get("backend_tree_sha256"),
            "requires_python": ">=3.11,<3.13",
        },
        "frontend": {
            "pins": frontend_pins(repo),
            "artifact": {
                "build_id": art.get("build_id"),
                "build_id_sha256": art.get("build_id_sha256"),
                "required_server_files_sha256": art.get(
                    "required_server_files_sha256"),
            },
        },
        "toolchain": {
            "python": run_probe_version(sys.executable, ["--version"]),
            "node": run_probe_version("node", ["--version"]),
            "ffmpeg": run_probe_version(
                "ffmpeg", ["-hide_banner", "-version"]),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default="packaging/windows/manifest.json")
    ap.add_argument("--backend-port", type=int, default=8421)
    ap.add_argument("--frontend-port", type=int, default=3121)
    args = ap.parse_args(argv)
    repo = REPO
    manifest = build_manifest_dict(repo, args.backend_port,
                                   args.frontend_port)
    out = Path(args.out)
    if not out.is_absolute():
        out = repo / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"manifest written: {out}", flush=True)
    print(f"  backend pins: {len(manifest['backend']['pins'])}", flush=True)
    print(f"  frontend deps: {len(manifest['frontend']['pins'])}",
          flush=True)
    print(f"  build_id: {manifest['frontend']['artifact']['build_id']}",
          flush=True)
    print(f"  endpoint: {manifest['endpoint']['api_base_url']}",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())