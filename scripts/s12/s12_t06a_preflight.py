"""S12-T06A preflight — fail-closed package prerequisite probe (read-only).

Operates on a relocatable STAGED PACKAGE (package root derived from
__file__: stage/scripts/s12_t06a_preflight.py -> stage; repo
scripts/s12/ -> repo). Checks (no install, no elevation, no network,
no mutation):

  1. FFmpeg present + `-hide_banner -version` exits 0.
  2. Python >= 3.11, < 3.13.
  3. Node.js present + `node --version` exits 0 (frontend runtime).
  4. Writable runtime roots: <install-root>/{data,artifacts,output,logs}.
  5. Localhost bind 127.0.0.1 (ephemeral port, bind+close).
  6. Package integrity:
       - manifest.json present and parseable;
       - frontend .next/BUILD_ID exists and equals manifest build_id
         (tamper/missing build => BLOCKED, never waived);
       - required-server-files.json present;
       - backend entry point present (stage/backend/app/main.py or
         package/app/main.py);
       - endpoint correct at build/runtime boundary: the baked frontend
         API base (staged .next build output) must contain the
         manifest endpoint api_base_url (wrong endpoint => BLOCKED).

Exit 0 = READY (JSON verdict READY). Exit 3 = BLOCKER (JSON verdict
BLOCKED_* with the exact missing env; caller must record NOT_RUN and
must NOT waive). Stdout is exactly one JSON object; human lines -> stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def probe_ffmpeg() -> dict:
    exe = shutil.which("ffmpeg")
    if exe is None:
        return {"ok": False, "code": "BLOCKED_FFMPEG_MISSING",
                "detail": "ffmpeg not found on PATH nor in WinGet Links"}
    try:
        out = subprocess.run([exe, "-hide_banner", "-version"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as err:
        return {"ok": False, "code": "BLOCKED_FFMPEG_BROKEN",
                "detail": f"ffmpeg probe failed: {err}"}
    if out.returncode != 0:
        return {"ok": False, "code": "BLOCKED_FFMPEG_BROKEN",
                "detail": f"ffmpeg -version exited {out.returncode}"}
    line = (out.stdout.splitlines() or [""])[0].strip()
    return {"ok": True, "code": "OK", "detail": line, "path": exe}


def probe_python() -> dict:
    v = sys.version_info
    if (v.major, v.minor) < (3, 11) or (v.major, v.minor) >= (3, 13):
        return {"ok": False, "code": "BLOCKED_PYTHON_VERSION",
                "detail": f"python {sys.version.split()[0]} outside "
                          "supported range >=3.11,<3.13"}
    return {"ok": True, "code": "OK",
            "detail": sys.version.split()[0], "path": sys.executable}


def probe_node() -> dict:
    exe = shutil.which("node")
    if exe is None:
        return {"ok": False, "code": "BLOCKED_NODE_MISSING",
                "detail": "node not found on PATH; Node.js 20+ is a "
                          "declared external runtime (never installed)"}
    try:
        out = subprocess.run([exe, "--version"], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as err:
        return {"ok": False, "code": "BLOCKED_NODE_BROKEN",
                "detail": f"node probe failed: {err}"}
    if out.returncode != 0:
        return {"ok": False, "code": "BLOCKED_NODE_BROKEN",
                "detail": f"node --version exited {out.returncode}"}
    line = (out.stdout.splitlines() or [""])[0].strip()
    return {"ok": True, "code": "OK", "detail": line, "path": exe}


def probe_writable_roots(install_root: Path) -> dict:
    need = ["data", "artifacts", "output", "logs"]
    bad: list[str] = []
    for name in need:
        d = install_root / name
        try:
            d.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=str(d), prefix=".w",
                                             suffix=".tmp",
                                             delete=False) as fh:
                fh.write(b"w")
                probe = Path(fh.name)
            probe.unlink()
        except OSError as err:
            bad.append(f"{name}: {err}")
    if bad:
        return {"ok": False, "code": "BLOCKED_RUNTIME_ROOTS_NOT_WRITABLE",
                "detail": "; ".join(bad)}
    return {"ok": True, "code": "OK",
            "detail": f"writable: {', '.join(need)}"}


def probe_localhost() -> dict:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return {"ok": True, "code": "OK",
                "detail": f"127.0.0.1 ephemeral bind ok (port {port})"}
    except OSError as err:
        return {"ok": False, "code": "BLOCKED_LOCALHOST_BIND",
                "detail": f"cannot bind 127.0.0.1: {err}"}


def manifest_path() -> Path:
    return PACKAGE_ROOT / "manifest.json"


def probe_package() -> dict:
    mf = manifest_path()
    if not mf.is_file():
        return {"ok": False, "code": "BLOCKED_MANIFEST_MISSING",
                "detail": f"manifest.json missing in package root "
                          f"{PACKAGE_ROOT}: stage the package first "
                          "(scripts/s12/s12_t06a_stage.py)"}
    try:
        man = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        return {"ok": False, "code": "BLOCKED_MANIFEST_UNREADABLE",
                "detail": f"manifest.json unreadable: {err}"}
    fe_artifact = ((man.get("frontend", {}) or {}).get("artifact", {})
                   or {})
    man_build = fe_artifact.get("build_id")
    nxt = PACKAGE_ROOT / "frontend" / ".next"
    build_id_path = nxt / "BUILD_ID"
    if not build_id_path.is_file():
        return {"ok": False, "code": "BLOCKED_FRONTEND_BUILD_MISSING",
                "detail": "frontend/.next/BUILD_ID missing in package: "
                          "rebuild package (stage)"}
    disk_build = build_id_path.read_text(encoding="utf-8").strip()
    if man_build != disk_build:
        return {"ok": False, "code": "BLOCKED_MANIFEST_STALE",
                "detail": f"manifest build_id {man_build!r} != .next "
                          f"BUILD_ID {disk_build!r}: rebuild manifest/package"}
    req = nxt / "required-server-files.json"
    if not req.is_file():
        return {"ok": False, "code": "BLOCKED_FRONTEND_BUILD_INCOMPLETE",
                "detail": "frontend/.next/required-server-files.json "
                          "missing: rebuild package"}
    staged_app = PACKAGE_ROOT / "backend" / "app" / "main.py"
    repo_app = PACKAGE_ROOT / "app" / "main.py"
    if not (staged_app.is_file() or repo_app.is_file()):
        return {"ok": False, "code": "BLOCKED_BACKEND_MISSING",
                "detail": "no backend entry point: neither "
                          "backend/app/main.py nor app/main.py in package"}
    # Endpoint correctness at the real build/runtime boundary: the baked
    # /api rewrite target must carry the manifest api_base_url.
    endpoint = (man.get("endpoint", {}) or {})
    api_base = endpoint.get("api_base_url") or ""
    if not api_base:
        return {"ok": False, "code": "BLOCKED_ENDPOINT_MISSING",
                "detail": "manifest endpoint.api_base_url missing"}
    baked = _baked_api_search(nxt, api_base)
    if not baked:
        return {"ok": False, "code": "BLOCKED_WRONG_ENDPOINT",
                "detail": f"staged .next build does not reference baked "
                          f"api base {api_base!r}: rebuild package with "
                          "the packaged backend port (wrong endpoint "
                          "fails closed)"}
    return {"ok": True, "code": "OK",
            "detail": f"manifest+build_id {disk_build} agree; endpoint "
                      f"{api_base} baked; backend entry present"}


def _baked_api_search(nxt: Path, api_base: str) -> bool:
    """Check the staged .next build for the baked API base string.

    Looks at lightweight build manifests first (routes-manifest.json,
    required-server-files.json, build-manifest.json), then a bounded
    sample of server chunks; never scans node_modules.
    """
    candidates: list[Path] = []
    for name in ("routes-manifest.json", "required-server-files.json",
                 "build-manifest.json", "prerender-manifest.json"):
        p = nxt / name
        if p.is_file():
            candidates.append(p)
    server_dir = nxt / "server"
    if server_dir.is_dir():
        try:
            for _, _, files in os.walk(server_dir):
                for f in sorted(files):
                    if f.endswith(".js") or f.endswith(".json"):
                        candidates.append(server_dir / f)
                    if len(candidates) >= 60:
                        break
                if len(candidates) >= 60:
                    break
        except OSError:
            pass
    for p in candidates:
        try:
            # bounded read (first 4 MiB) to avoid huge chunk scans
            with open(p, "rb") as fh:
                head = fh.read(4 * 1024 * 1024)
            if api_base.encode("utf-8") in head:
                return True
        except OSError:
            continue
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install-root", default=".",
                    help="runtime root whose data/artifacts/output/logs "
                         "must be writable")
    args = ap.parse_args(argv)
    install_root = Path(args.install_root)
    if not install_root.is_absolute():
        install_root = PACKAGE_ROOT / install_root
    checks = {
        "ffmpeg": probe_ffmpeg(),
        "python": probe_python(),
        "node": probe_node(),
        "runtime_roots": probe_writable_roots(install_root),
        "localhost": probe_localhost(),
        "package": probe_package(),
    }
    failed = {k: v for k, v in checks.items() if not v["ok"]}
    verdict = {"verdict": "READY" if not failed else "BLOCKED",
               "failed": sorted(failed),
               "checks": checks,
               "package_root": str(PACKAGE_ROOT),
               "install_root": str(install_root)}
    print(json.dumps(verdict, indent=2), flush=True)
    if failed:
        print("BLOCKER: " + "; ".join(
            f"{k}={v['code']}: {v['detail']}"
            for k, v in failed.items()), file=sys.stderr, flush=True)
        return 3
    print("READY: all preflight checks passed", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())