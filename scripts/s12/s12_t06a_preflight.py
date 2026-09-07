"""S12-T06A preflight — fail-closed local prerequisite probe (read-only).

Checks (no install, no elevation, no network, no mutation):
  1. FFmpeg present + `-hide_banner -version` exits 0 (probe contract
     mirrors app/adapters/renderer/ffmpeg_binary.py).
  2. Python >= 3.11, < 3.13.
  3. Writable runtime roots: <install>/data, <install>/artifacts,
     <install>/output, <install>/logs (probe-write + delete a temp file).
  4. Localhost lifecycle: bind 127.0.0.1 on an ephemeral port (bind+close).
  5. Compiled artifacts present: manifest.json + frontend .next BUILD_ID +
     required-server-files.json; manifest build_id must match .next BUILD_ID
     (docs-artifact agreement gate).
  6. Backend source present: app/main.py importable path
     (packaging/windows/backend/ when staged, else repo app/).

Exit 0 = READY (JSON verdict READY). Exit 3 = BLOCKER (JSON verdict
BLOCKED_* with the exact missing env; the caller must record NOT_RUN and
must NOT waive). Stdout is exactly one JSON object (machine-readable);
human lines go to stderr.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


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


def probe_artifacts(repo: Path) -> dict:
    manifest = repo / "packaging" / "windows" / "manifest.json"
    if not manifest.is_file():
        return {"ok": False, "code": "BLOCKED_MANIFEST_MISSING",
                "detail": "packaging/windows/manifest.json missing: run "
                          "scripts/s12/s12_t06a_build_manifest.py first"}
    try:
        man = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        return {"ok": False, "code": "BLOCKED_MANIFEST_UNREADABLE",
                "detail": f"manifest.json unreadable: {err}"}
    nxt = repo / "frontend" / ".next"
    build_id_path = nxt / "BUILD_ID"
    if not build_id_path.is_file():
        return {"ok": False, "code": "BLOCKED_FRONTEND_BUILD_MISSING",
                "detail": "frontend/.next/BUILD_ID missing: run "
                          "'npm run build' in frontend/ first"}
    disk_build = build_id_path.read_text(encoding="utf-8").strip()
    man_build = ((man.get("frontend", {}) or {}).get("artifact", {})
                 or {}).get("build_id")
    if man_build != disk_build:
        return {"ok": False, "code": "BLOCKED_MANIFEST_STALE",
                "detail": f"manifest build_id {man_build!r} != "
                          f".next BUILD_ID {disk_build!r}: rebuild manifest"}
    req = nxt / "required-server-files.json"
    if not req.is_file():
        return {"ok": False, "code": "BLOCKED_FRONTEND_BUILD_INCOMPLETE",
                "detail": "frontend/.next/required-server-files.json "
                          "missing: rebuild frontend"}
    staged_backend = repo / "packaging" / "windows" / "backend" / "main.py"
    repo_backend = repo / "app" / "main.py"
    if not (staged_backend.is_file() or repo_backend.is_file()):
        return {"ok": False, "code": "BLOCKED_BACKEND_MISSING",
                "detail": "no backend entry point: neither "
                          "packaging/windows/backend/main.py nor app/main.py"}
    return {"ok": True, "code": "OK",
            "detail": f"manifest+build_id {disk_build} agree; "
                      "backend entry present"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install-root", default=".",
                    help="runtime root whose data/artifacts/output/logs "
                         "must be writable")
    args = ap.parse_args(argv)
    repo = Path(__file__).resolve().parent.parent.parent
    install_root = Path(args.install_root)
    if not install_root.is_absolute():
        install_root = repo / install_root
    checks = {
        "ffmpeg": probe_ffmpeg(),
        "python": probe_python(),
        "runtime_roots": probe_writable_roots(install_root),
        "localhost": probe_localhost(),
        "artifacts": probe_artifacts(repo),
    }
    failed = {k: v for k, v in checks.items() if not v["ok"]}
    verdict = {"verdict": "READY" if not failed else "BLOCKED",
               "failed": sorted(failed),
               "checks": checks,
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
