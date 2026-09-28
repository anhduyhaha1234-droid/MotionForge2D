#!/usr/bin/env python
"""MF-END-18 — build/install the pinned ComfyUI stage adapter as an app dependency.

The app-side wrapper (``app/adapters/media_engine/comfy.py``) drives the
``mf_comfy`` package that the MF-V1-COMFY lane froze at commit
``70f718098f00f9dbdeb6cc9c5d7808b243eb0c57`` (R28 MATRIX: 13/13 rows, 269/269
checks; negative control PRE_FIX_BEHAVIOUR_CONFIRMED).  The package is NOT
imported from that developer worktree at runtime: this script builds a wheel
whose module bytes come out of the git OBJECT STORE at the pinned commit,
verifies every file against the manifest below, stamps an in-package provenance
record and installs it into an explicit target directory (or the active
environment with ``--pip-install``).

Subcommands are flags on one entry point::

    python scripts/build_mf_comfy_dependency.py --out <build-dir>
    python scripts/build_mf_comfy_dependency.py --out <build-dir> --install-target <site-dir>
    python scripts/build_mf_comfy_dependency.py --out <build-dir> --pip-install

Refusals are typed (``code`` on stderr, exit 2) and never build or install a
partial artifact:

* ``source_commit_unresolved``    — the requested commit is not an object in the repo
* ``source_file_set_mismatch``    — the pinned subpath holds different files than the manifest
* ``source_file_missing``         — a manifest file is absent at that commit
* ``source_content_mismatch``     — a file's bytes differ from the pinned sha256/size
* ``source_repo_missing``         — no usable git repository at ``--source-repo``
* ``install_record_mismatch``     — a wheel member does not match the wheel's own RECORD
* ``install_file_set_mismatch``   — wheel/install holds undeclared members
* ``install_content_mismatch``    — an installed module file does not match the pinned sha256/size
* ``install_target_conflict``     — target already holds a different mf_comfy install
* ``pip_install_failed``          — ``--pip-install`` ran pip, which returned non-zero

No GPU, no network, no sys.path mutation: the wheel is built with the stdlib
only, and the install is a verified RECORD-driven extraction.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

# ── the pinned source artifact ────────────────────────────────────────────────

DIST_NAME = "mf-comfy"
DIST_VERSION = "0.1.0"
MODULE_DIR = "mf_comfy"
SOURCE_SUBPATH = "experiments/mf_reskin_v1/comfy/mf_comfy"
PINNED_COMMIT = "70f718098f00f9dbdeb6cc9c5d7808b243eb0c57"
DEFAULT_SOURCE_REPO = "C:/Users/Admin/Documents/Codex/work/mfv1/wt-comfy"
PROVENANCE_NAME = "_mf_provenance.json"
PROVENANCE_SCHEMA = "mf.end18.comfy_dependency.provenance/1"
BUILDER = "scripts/build_mf_comfy_dependency.py"
WHEEL_TAG = "py3-none-any"

#: The frozen module file set — sha256 + size of the blob bytes at the pin.
#: Measured 2026-09-28 with ``git cat-file blob 70f7180:<subpath>/<name>``;
#: the identical manifest is hard-pinned in the runtime wrapper and in the
#: MF-END-18 tests, so build time and runtime verify the SAME bytes.
PINNED_FILES: dict[str, tuple[str, int]] = {
    "__init__.py": ("1ea9885bd140d01aa0f19d9e756bbe705b5a8066012687780a3c46c5b094b7dd", 1367),
    "adapter.py": ("945753341086c732f6701d543b5abeba991ced3559a5426737b96c6794f8b646", 100090),
    "contract.py": ("935a6db9fd6a85a4c4cbf7381392ac0af105e80ac5c32913a737d5b9f3624700", 5067),
    "errors.py": ("4bc873da04c0d4a309842dacd8266730eb04885837fd1d656345665c87f070b9", 8278),
    "gpugate.py": ("e2b7117ff0da735416595935a20549847c3e59ea34cb2f1da157e27ab382d792", 12063),
    "lease.py": ("3ee28fa3aad29d58de122f047e2288715c249e7f0b3510e129d8fa01d9c77371", 44969),
    "paths.py": ("0295ff75108e70bd4d9b0f1a5c9caa1b9b575eacce23d4d4e62ee038f5d13661", 3195),
    "pinning.py": ("0474ba45b2d65934d74aaab5f2407e0eb46b41803ba5e71d231ef8bd6d9e16b0", 3565),
    "reskin.py": ("efa535c1b8578c265a6cdd60609724214ff37705dcea651c9a6eb8f88aa00d4c", 35534),
    "resources.py": ("a6f264311a0c822ad9f99edd13957fe758774c3351302e119a743d40c0d17f6a", 3260),
    "transport.py": ("c9861e1b609a37d90a4bbd4b5f34e95fc1530a216e4c49dc9c31d098d9f07265", 13812),
}


class BuildRefusal(Exception):  # noqa: N818 — mirrors the contract refusal naming
    """Typed build/install refusal — printed as ``code: detail`` and exits 2."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _refuse(code: str, detail: str) -> None:
    raise BuildRefusal(code, detail)


# ── git access (object store, never the working tree) ─────────────────────────


def _git(repo: Path, *args: str, code: str = "source_repo_missing") -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip()
        _refuse(code, f"git {' '.join(args)} failed in {repo}: {msg}")
    return proc.stdout


def resolve_commit(repo: Path, commit: str) -> str:
    """Resolve a commit-ish to its full 40-hex id, refusing on a bad object.

    ``git rev-parse`` ECHOES an unresolvable 40-hex argument, so the check
    must be ``--verify <c>^{commit}`` (never a bare rev-parse).
    """
    if not (repo / ".git").exists():
        _refuse("source_repo_missing", f"{repo} is not a git repository")
    out = _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}",
               code="source_commit_unresolved").decode().strip()
    if len(out) != 40:
        _refuse("source_commit_unresolved", f"{commit!r} did not resolve to one commit")
    return out


def read_source_files(repo: Path, commit: str) -> dict[str, bytes]:
    """Extract the pinned module at ``commit`` from the object store.

    The file SET is checked first (an extra or missing file is a refusal, never
    a silent omission), then every file's sha256 + size against the manifest.
    """
    resolved = resolve_commit(repo, commit)
    listing = _git(repo, "ls-tree", "-r", "--name-only", resolved, "--", SOURCE_SUBPATH,
                   code="source_file_set_mismatch")
    names = sorted(
        Path(line.strip()).name for line in listing.decode().splitlines() if line.strip()
    )
    expected = sorted(PINNED_FILES)
    if names != expected:
        extra = sorted(set(names) - set(expected))
        missing = sorted(set(expected) - set(names))
        _refuse(
            "source_file_set_mismatch",
            f"at {resolved[:12]}:{SOURCE_SUBPATH} expected exactly {len(expected)} files; "
            f"extra={extra} missing={missing}",
        )
    files: dict[str, bytes] = {}
    for name in expected:
        blob = _git(repo, "cat-file", "blob", f"{resolved}:{SOURCE_SUBPATH}/{name}",
                    code="source_file_missing")
        want_sha, want_size = PINNED_FILES[name]
        got_sha = hashlib.sha256(blob).hexdigest()
        if len(blob) != want_size or got_sha != want_sha:
            _refuse(
                "source_content_mismatch",
                f"{name} at {resolved[:12]} is {len(blob)} B/{got_sha[:16]}…; the manifest "
                f"pins {want_size} B/{want_sha[:16]}… — refusing to build from unpinned bytes",
            )
        files[name] = blob
    return files


# ── wheel build (stdlib only) ─────────────────────────────────────────────────


def _record_hash(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def build_wheel(
    files: dict[str, bytes],
    *,
    out_dir: Path,
    source_repo: str,
    source_commit: str,
    commit_matches_pin: bool,
    built_at_utc: str,
) -> tuple[Path, str, dict]:
    """Assemble the wheel + provenance.  Returns (wheel_path, wheel_sha, provenance)."""
    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "dist_name": DIST_NAME,
        "version": DIST_VERSION,
        "module_dir": MODULE_DIR,
        "source_repo": source_repo,
        "source_subpath": SOURCE_SUBPATH,
        "source_commit": source_commit,
        "source_commit_pin": PINNED_COMMIT,
        "commit_matches_pin": commit_matches_pin,
        "builder": BUILDER,
        "built_at_utc": built_at_utc,
        "files": {
            name: {"sha256": PINNED_FILES[name][0], "size_bytes": PINNED_FILES[name][1]}
            for name in sorted(files)
        },
    }
    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {DIST_NAME}\n"
        f"Version: {DIST_VERSION}\n"
        "Summary: MotionForge ComfyUI stage adapter (pinned external dependency)\n"
        "License: MIT\n"
        "Requires-Python: >=3.11\n"
        "\n"
        "Built by scripts/build_mf_comfy_dependency.py from the frozen source commit.\n"
        "Install target: explicit site directory or the active environment.\n"
    ).encode()
    wheel_meta = (
        "Wheel-Version: 1.0\n"
        "Generator: mf-end18-build-mf-comfy-dependency\n"
        "Root-Is-Purelib: true\n"
        f"Tag: {WHEEL_TAG}\n"
    ).encode()
    dist_info = f"{MODULE_DIR}-{DIST_VERSION}.dist-info"
    members: dict[str, bytes] = {}
    for name in sorted(files):
        members[f"{MODULE_DIR}/{name}"] = files[name]
    members[f"{MODULE_DIR}/{PROVENANCE_NAME}"] = (
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    ).encode()
    members[f"{dist_info}/METADATA"] = metadata
    members[f"{dist_info}/WHEEL"] = wheel_meta
    record_lines = [
        f"{path},sha256={_record_hash(data)},{len(data)}"
        for path, data in sorted(members.items())
    ]
    record_lines.append(f"{dist_info}/RECORD,,")
    members[f"{dist_info}/RECORD"] = ("\n".join(record_lines) + "\n").encode()

    out_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = out_dir / f"{MODULE_DIR}-{DIST_VERSION}-{WHEEL_TAG}.whl"
    if wheel_path.exists():
        wheel_path.unlink()
    fixed_date = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, data in sorted(members.items()):
            info = zipfile.ZipInfo(path, date_time=fixed_date)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    wheel_sha = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    full = dict(provenance)
    full["wheel"] = {"filename": wheel_path.name, "sha256": wheel_sha}
    (out_dir / "mf_comfy_dependency_provenance.json").write_text(
        json.dumps(full, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return wheel_path, wheel_sha, full


# ── verified install ──────────────────────────────────────────────────────────


def install_wheel(wheel: Path, target: Path) -> dict:
    """RECORD-verified extraction of the wheel into ``target``.

    Every member is hashed against the wheel's own RECORD before it is written;
    undeclared members and digest mismatches refuse without installing.  A target
    that already holds a DIFFERENT mf_comfy install is refused (never silently
    overwritten); re-installing the same pinned bytes is idempotent.
    """
    target.mkdir(parents=True, exist_ok=True)
    existing = target / MODULE_DIR
    if existing.is_dir():
        drifted = []
        for path in sorted(existing.glob("*.py")):
            want = PINNED_FILES.get(path.name)
            data = path.read_bytes()
            if (want is None or want[1] != len(data)
                    or hashlib.sha256(data).hexdigest() != want[0]):
                drifted.append(path.name)
        if drifted:
            _refuse(
                "install_target_conflict",
                f"{target} already holds a different mf_comfy install (drifted: {drifted}); "
                "point --install-target at a clean directory or remove the old install",
            )
    with zipfile.ZipFile(wheel) as zf:
        names = sorted(zf.namelist())
        dist_info = next(
            (n.split("/", 1)[0] for n in names if n.endswith(".dist-info/RECORD")), ""
        )
        if not dist_info:
            _refuse("install_record_mismatch", f"{wheel.name} holds no RECORD")
        record_name = f"{dist_info}/RECORD"
        declared: dict[str, tuple[str, str]] = {}
        for line in zf.read(record_name).decode("utf-8").splitlines():
            if not line.strip():
                continue
            parts = line.rsplit(",", 2)
            if len(parts) != 3:
                _refuse("install_record_mismatch", f"malformed RECORD line: {line!r}")
            declared[parts[0]] = (parts[1], parts[2])
        extra = sorted(set(names) - set(declared))
        if extra:
            _refuse(
                "install_file_set_mismatch",
                f"{wheel.name} holds members the RECORD does not declare: {extra}",
            )
        for name in names:
            want_hash, want_size = declared[name]
            data = zf.read(name)
            if name.endswith("/RECORD"):
                continue
            if f"sha256={_record_hash(data)}" != want_hash or str(len(data)) != want_size:
                _refuse(
                    "install_record_mismatch",
                    f"{name} does not match its RECORD entry ({len(data)} B)",
                )
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    # The module bytes must additionally equal the pinned source manifest — the
    # RECORD only proves the wheel is internally consistent, not what it pins.
    module_dir = target / MODULE_DIR
    for name, (want_sha, want_size) in sorted(PINNED_FILES.items()):
        path = module_dir / name
        if not path.is_file():
            _refuse("install_file_set_mismatch", f"installed module is missing {name}")
        data = path.read_bytes()
        if len(data) != want_size or hashlib.sha256(data).hexdigest() != want_sha:
            _refuse("install_content_mismatch", f"installed {name} does not match the pin")
    installed = sorted(p.name for p in module_dir.glob("*.py"))
    if installed != sorted(PINNED_FILES):
        _refuse(
            "install_file_set_mismatch",
            f"installed module file set is {installed}; the pin is {sorted(PINNED_FILES)}",
        )
    return {
        "target": str(target),
        "members": len(names),
        "module_files_verified": len(PINNED_FILES),
        "provenance": str(module_dir / PROVENANCE_NAME),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-repo", default=DEFAULT_SOURCE_REPO,
                        help="git repository holding the pinned source commit")
    parser.add_argument("--commit", default=PINNED_COMMIT,
                        help="source commit (defaults to the pin; content stays "
                             "manifest-checked)")
    parser.add_argument("--out", required=True, help="build output directory (wheel + provenance)")
    parser.add_argument("--install-target",
                        help="verified install of the wheel into this explicit site directory")
    parser.add_argument("--pip-install", action="store_true",
                        help="install the wheel into the ACTIVE environment with pip "
                             "(offline: --no-index --no-deps)")
    parser.add_argument("--built-at", default=None,
                        help="override the UTC build timestamp (deterministic rebuilds)")
    parser.add_argument("--report", default=None, help="write the JSON summary here as well")
    args = parser.parse_args(argv)

    try:
        repo = Path(args.source_repo)
        if not repo.is_dir():
            _refuse("source_repo_missing", f"{repo} does not exist")
        resolved = resolve_commit(repo, args.commit)
        files = read_source_files(repo, args.commit)
        built_at = args.built_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        out_dir = Path(args.out)
        wheel, wheel_sha, provenance = build_wheel(
            files,
            out_dir=out_dir,
            source_repo=str(repo),
            source_commit=resolved,
            commit_matches_pin=(resolved == PINNED_COMMIT),
            built_at_utc=built_at,
        )
        summary: dict = {
            "ok": True,
            "dist": f"{DIST_NAME}=={DIST_VERSION}",
            "source_commit": resolved,
            "source_commit_pin": PINNED_COMMIT,
            "commit_matches_pin": provenance["commit_matches_pin"],
            "source_files_verified": len(files),
            "wheel": str(wheel),
            "wheel_sha256": wheel_sha,
            "provenance": str(out_dir / "mf_comfy_dependency_provenance.json"),
        }
        if args.install_target:
            summary["install"] = install_wheel(wheel, Path(args.install_target))
        if args.pip_install:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                 "--force-reinstall", str(wheel)],
                capture_output=True,
                check=False,
            )
            if proc.returncode != 0:
                _refuse(
                    "pip_install_failed",
                    proc.stderr.decode("utf-8", "replace").strip()[-400:],
                )
            summary["pip_install"] = {"returncode": 0, "wheel": str(wheel)}
    except BuildRefusal as exc:
        print(f"REFUSED {exc.code}: {exc.detail}", file=sys.stderr)
        if args.report:
            Path(args.report).write_text(
                json.dumps({"ok": False, "code": exc.code, "detail": exc.detail}, indent=2)
                + "\n",
                encoding="utf-8",
            )
        return 2
    text = json.dumps(summary, indent=2, sort_keys=True)
    print(text)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
