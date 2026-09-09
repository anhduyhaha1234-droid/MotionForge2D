"""S12-T06A stage builder — create a relocatable staged beta package.

Produces a self-contained stage directory (owned path, OUTSIDE the repo
checkout and OUTSIDE the protected MAIN tree) containing:

  - backend artifact:  app/ package + alembic.ini + migrations/ (byte-compiled
                       tree, no dev files)
  - frontend artifact: REBUILT .next output with the backend endpoint baked
                       at build time (next.config rewrites), plus package.json
                       / package-lock.json and the installed node_modules
                       runtime tree
  - manifest.json:     dependency pins (backend exact ``==`` from
                       pyproject.toml; frontend ranges + real locked versions
                       from package-lock.json), artifact hashes (BUILD_ID,
                       required-server-files.json sha256, backend tree digest),
                       baked endpoint (backend/frontend ports + API base URL),
                       toolchain versions ONLY (never absolute user paths)
  - scripts/:          s12_t06a_run.py + s12_t06a_preflight.py copies
  - launchers:         Start/Stop/Uninstall/Install .cmd + README-BETA.txt

The stage is NOT fully self-contained: it declares the external runtimes
Python 3.11, Node.js 20+ and FFmpeg and probes them at runtime. It never
installs, downloads, elevates, or edits PATH/registry/firewall/ACL.

Usage:
    python scripts/s12/s12_t06a_stage.py --stage-root <ABS> \
        --backend-port 8425 --frontend-port 3125

Refuses: stage root inside the repo checkout, inside protected MAIN
(Path.home()/MotionForge2D), or a relative path. Missing frontend build
deps (npm/node) -> exact BLOCKER, exit 3 (never waived, never installed).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from s12_t06a_build_manifest import (  # noqa: E402
    build_manifest_dict,
)


def log(msg: str) -> None:
    print(f"[s12-t06a-stage] {msg}", flush=True)


def validate_stage_root(root: Path) -> None:
    if not root.is_absolute():
        raise SystemExit("BLOCKED: --stage-root must be absolute")
    repo_resolved = REPO.resolve()
    if root.resolve() == repo_resolved or root.resolve().is_relative_to(
            repo_resolved):
        raise SystemExit(
            "BLOCKED: stage root must be OUTSIDE the repo checkout")
    main = (Path.home() / "MotionForge2D").resolve()
    try:
        if root.resolve() == main or root.resolve().is_relative_to(main):
            raise SystemExit(
                "BLOCKED: stage root must be outside protected MAIN "
                "tree")
    except OSError:
        pass


def copy_backend(repo: Path, stage: Path) -> None:
    src = repo / "app"
    dst = stage / "backend" / "app"
    log(f"copying backend app/ -> {dst}")
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "*.pyo"))
    for rel in ("alembic.ini", "migrations"):
        s = repo / rel
        if s.is_file():
            shutil.copy2(s, stage / "backend" / rel)
        elif s.is_dir():
            shutil.copytree(s, stage / "backend" / rel,
                            ignore=shutil.ignore_patterns(
                                "__pycache__", "*.pyc", "*.pyo"))
    log("backend staged")


def rebuild_frontend(repo: Path, backend_port: int) -> str:
    """Rebuild the frontend with the backend endpoint baked at BUILD time.

    The real build/runtime boundary: next.config.ts reads NEXT_PUBLIC_API_URL
    at build time for /api rewrites, so the staged .next output must be built
    with the packaged backend port, never the dev default.
    """
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node is None or npm is None:
        raise SystemExit(
            "BLOCKED: BLOCKED_NODE_MISSING: node/npm not on PATH; "
            "Node.js 20+ is a declared external runtime (never installed "
            "by this package)")
    api = f"http://127.0.0.1:{backend_port}"
    env = os.environ.copy()
    env["NEXT_PUBLIC_API_URL"] = api
    log(f"npm run build with NEXT_PUBLIC_API_URL={api} "
        f"(baked at build boundary)")
    proc = subprocess.run([npm, "run", "build"], cwd=str(repo / "frontend"),
                          env=env, capture_output=True, text=True,
                          timeout=600)
    if proc.returncode != 0:
        raise SystemExit(
            "BLOCKED: frontend build failed: "
            + (proc.stdout[-800:] or "") + (proc.stderr[-800:] or ""))
    build_id = (repo / "frontend" / ".next" / "BUILD_ID").read_text(
        encoding="utf-8").strip()
    log(f"frontend built: BUILD_ID={build_id}")
    return build_id


def copy_frontend(repo: Path, stage: Path) -> None:
    src = repo / "frontend"
    dst = stage / "frontend"
    log("copying frontend/.next + package files + node_modules (runtime)")
    shutil.copytree(src / ".next", dst / ".next",
                    ignore=shutil.ignore_patterns("cache"))
    for rel in ("package.json", "package-lock.json"):
        shutil.copy2(src / rel, dst / rel)
    shutil.copytree(src / "node_modules", dst / "node_modules",
                    ignore=shutil.ignore_patterns(
                        ".cache", ".bin", "@playwright", "playwright",
                        "playwright-core", "@tailwindcss", "eslint",
                        "tailwindcss", "@eslint", "eslint-config-next",
                        "@types"))
    log("frontend staged")


def copy_scripts_and_launchers(repo: Path, stage: Path) -> None:
    scripts = stage / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in ("s12_t06a_run.py", "s12_t06a_preflight.py"):
        shutil.copy2(repo / "scripts" / "s12" / name, scripts / name)
    pkg = repo / "packaging" / "windows"
    for name in ("Start-MotionForge-Beta.cmd", "Stop-MotionForge-Beta.cmd",
                 "Uninstall-MotionForge-Beta.cmd",
                 "Install-MotionForge-Beta.cmd", "README-BETA.txt"):
        src = pkg / name
        if src.is_file():
            shutil.copy2(src, stage / name)
    log("scripts + launchers staged")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="s12_t06a_stage.py")
    ap.add_argument("--stage-root", required=True)
    ap.add_argument("--backend-port", type=int, default=8421)
    ap.add_argument("--frontend-port", type=int, default=3121)
    args = ap.parse_args(argv)

    stage = Path(args.stage_root).expanduser()
    validate_stage_root(stage)
    if stage.exists():
        log(f"BLOCKED: stage root already exists: {stage} "
            "(refusing overwrite; use a fresh owned path)")
        return 3
    stage.mkdir(parents=True)

    build_id = rebuild_frontend(REPO, args.backend_port)
    copy_backend(REPO, stage)
    copy_frontend(REPO, stage)
    copy_scripts_and_launchers(REPO, stage)
    manifest = build_manifest_dict(REPO, args.backend_port,
                                   args.frontend_port)
    (stage / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log(f"STAGE READY: {stage}")
    log(f"  build_id={build_id} backend=127.0.0.1:{args.backend_port} "
        f"frontend=127.0.0.1:{args.frontend_port}")
    log("  external declared runtimes required: Python 3.11, Node.js 20+, "
        "FFmpeg (probed, never installed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())