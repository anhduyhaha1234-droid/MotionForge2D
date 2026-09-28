"""MF-END-28 — demo package inventory + external-models manifest builder.

Writes TWO committed artifacts under ``packaging/demo/``:

* ``inventory.json`` — schema ``mf2d-demo-inventory/1``: what the demo
  delivery package is made of, measured from the real tree (no guesses):
    - ``backend``   : exact `==` pins from pyproject.toml + app tree digest
    - ``frontend``  : package.json ranges + REAL locked versions + lockfile sha
    - ``toolchain`` : python / node / ffmpeg VERSIONS only (never paths)
    - ``comfy``     : engine identity from the frozen media registry +
                      the mf-comfy dependency pin (commit + module-file manifest)
    - ``models``    : EXTERNAL roots only (never bundled, never copied)
    - ``frozen_packaging`` : inventory of the EXISTING S12-T06A packaging
                      files (path/bytes/sha256) — read-only record
    - ``guardrails``: measured scans (secrets, absolute user paths) over the
                      new MF-END-28 artifacts

* ``models.json`` — schema ``mf2d-demo-models/1``: every model the demo
  graphs load, taken from the in-tree registries
  (``app/media_workflows/model_profiles.json`` and
  ``app/media_workflows/reference_asset_v1.manifest.json``), each with
  rel path / sha256 / bytes / license / source.  Files stay in an external
  read-only root (``MF2D_MODELS_ROOT``); ``bundled`` is always false.

No network, no GPU, no install; stdlib only.  Deterministic for a pinned
``--generated-at`` value: re-running with the same timestamp yields
byte-identical files (used by the MF-END-28 test).

Usage:
    python packaging/demo/build_demo_package_inventory.py
    python packaging/demo/build_demo_package_inventory.py \
        --generated-at 2026-09-28T00:00:00+00:00 --out-dir <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DEMO_DIR = REPO / "packaging" / "demo"
INVENTORY_NAME = "inventory.json"
MODELS_NAME = "models.json"

MODEL_PROFILES = REPO / "app" / "media_workflows" / "model_profiles.json"
REFERENCE_MANIFEST = (
    REPO / "app" / "media_workflows" / "reference_asset_v1.manifest.json"
)
COMFY_BUILDER = REPO / "scripts" / "build_mf_comfy_dependency.py"

#: Frozen S12-T06A packaging artifacts recorded read-only in the inventory.
FROZEN_PACKAGING_GLOBS = (
    "packaging/windows/*",
    "scripts/s12/*.py",
)

#: Files authored by MF-END-28 that the guardrail scans cover.  Two files
#: are EXCLUDED by name: this builder and inventory.json itself — their
#: marker lists deliberately contain the very literals being searched for,
#: so scanning them would flag the honest detector (measured 2026-09-28:
#: 10 secret + 2 path hits, all inside the scan record).  See the MF-END-28
#: REPORT for the disclosure; this is a documented exclusion, not a finding.
MF_END_28_FILES = (
    "packaging/demo/models.json",
    "packaging/demo/README.md",
    "scripts/mf_delivery_launcher.ps1",
    "THIRD_PARTY.md",
)
SCANNER_EXCLUDED = (
    ("packaging/demo/build_demo_package_inventory.py",
     "contains the marker lists themselves"),
    ("packaging/demo/inventory.json",
     "is the scan record; stores the marker lists by design"),
)

SECRET_MARKERS = (
    "sk-",
    "ghp_",
    "AKIA",
    "-----BEGIN",
    "password=",
    "password:",
    "secret=",
    "token=",
    "api_key=",
    "apikey=",
)

ABSOLUTE_USER_MARKERS = ("C:\\Users\\", "C:/Users/", "/c/Users/")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_head(repo: Path) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def probe_version(exe: str, args: list[str]) -> dict:
    found = shutil.which(exe)
    if found is None:
        return {"available": False, "version": None}
    try:
        out = subprocess.run([found, *args], capture_output=True, text=True,
                             timeout=30)
        first = (out.stdout or out.stderr or "").splitlines()
        version = first[0].strip() if first else None
        return {"available": out.returncode == 0, "version": version}
    except (OSError, subprocess.TimeoutExpired) as err:
        return {"available": False, "version": None, "error": str(err)}


def backend_pins(repo: Path) -> list[str]:
    with open(repo / "pyproject.toml", "rb") as fh:
        data = tomllib.load(fh)
    deps = data.get("project", {}).get("dependencies", [])
    return sorted(deps)


def frontend_pins(repo: Path) -> tuple[dict, str | None]:
    fe = repo / "frontend"
    pkg = json.loads((fe / "package.json").read_text(encoding="utf-8"))
    lock_path = fe / "package-lock.json"
    locked: dict[str, str] = {}
    lock_sha = None
    if lock_path.is_file():
        lock_sha = sha256_file(lock_path)
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
    return out, lock_sha


def tree_digest(root: Path) -> str:
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


def comfy_section() -> dict:
    registry = json.loads(MODEL_PROFILES.read_text(encoding="utf-8"))
    engine = registry.get("engine", {})
    builder_text = COMFY_BUILDER.read_text(encoding="utf-8")

    def const(name: str) -> str | None:
        for line in builder_text.splitlines():
            if line.startswith(f"{name} = "):
                return line.split("=", 1)[1].strip().strip('"')
        return None

    pinned_files: dict[str, tuple[str, int]] = {}
    ns: dict = {}
    code = compile(builder_text, str(COMFY_BUILDER), "exec")
    exec(code, ns)  # noqa: S102 — in-repo builder, stdlib-only constants
    pinned_files = ns.get("PINNED_FILES", {})
    pins_digest = sha256_bytes("\n".join(
        f"{name}:{sha}:{size}" for name, (sha, size)
        in sorted(pinned_files.items())).encode("utf-8"))
    return {
        "engine": {
            "name": engine.get("name"),
            "version": engine.get("version"),
            "head": engine.get("head"),
            "license": engine.get("license"),
            "registry": "app/media_workflows/model_profiles.json",
        },
        "dependency": {
            "dist_name": const("DIST_NAME"),
            "dist_version": const("DIST_VERSION"),
            "module_dir": const("MODULE_DIR"),
            "source_commit": const("PINNED_COMMIT"),
            "source_subpath": const("SOURCE_SUBPATH"),
            "module_file_count": len(pinned_files) if pinned_files else None,
            "module_files_digest": pins_digest if pinned_files else None,
            "builder": "scripts/build_mf_comfy_dependency.py",
            "install_policy": (
                "built from the git object store at the pinned commit and "
                "installed to an explicit target dir; never imported from a "
                "developer worktree at runtime"),
        },
    }


def models_section() -> dict:
    registry = json.loads(MODEL_PROFILES.read_text(encoding="utf-8"))
    profiles = {p["id"]: p for p in registry.get("profiles", [])}
    chosen_id = (registry.get("selection", {}) or {}).get("chosen")
    chosen = profiles.get(chosen_id) if chosen_id else None
    models: list[dict] = []
    if chosen:
        for m in chosen.get("models", []):
            models.append({
                "id": f"{chosen.get('graph_id')}:{m.get('role')}",
                "profile": chosen_id,
                "graph_id": chosen.get("graph_id"),
                "rel": m.get("rel"),
                "sha256": m.get("sha256"),
                "bytes": m.get("bytes"),
                "license": m.get("license"),
                "source": m.get("source"),
                "revision": m.get("revision"),
            })
    ref = json.loads(REFERENCE_MANIFEST.read_text(encoding="utf-8"))
    for m in ref.get("models", []):
        models.append({
            "id": f"{ref.get('graph_id')}:{m.get('role')}",
            "profile": "reference_asset_v1",
            "graph_id": ref.get("graph_id"),
            "rel": m.get("rel"),
            "sha256": m.get("sha256"),
            "bytes": m.get("bytes"),
            "license": m.get("license"),
            "source": m.get("source"),
            "revision": None,
        })
    return {
        "schema": "mf2d-demo-models/1",
        "source_registries": [
            "app/media_workflows/model_profiles.json",
            "app/media_workflows/reference_asset_v1.manifest.json",
        ],
        "bundled": False,
        "copy_policy": ("external read-only root; never copied into the "
                        "package, the checkout, or git"),
        "root_env": "MF2D_MODELS_ROOT",
        "default_profile": chosen_id,
        "models": models,
    }


def frozen_packaging_inventory(repo: Path) -> list[dict]:
    rows: list[dict] = []
    for pattern in FROZEN_PACKAGING_GLOBS:
        for p in sorted(repo.glob(pattern)):
            if p.is_file():
                rows.append({
                    "path": p.relative_to(repo).as_posix(),
                    "bytes": p.stat().st_size,
                    "sha256": sha256_file(p),
                })
    doc = repo / "docs" / "packaging" / "s12-windows.md"
    if doc.is_file():
        rows.append({
            "path": "docs/packaging/s12-windows.md",
            "bytes": doc.stat().st_size,
            "sha256": sha256_file(doc),
        })
    return rows


def guardrails(repo: Path) -> dict:
    secret_hits: list[dict] = []
    path_hits: list[dict] = []
    scanned: list[str] = []
    for rel in MF_END_28_FILES:
        p = repo / rel
        if not p.is_file():
            continue
        scanned.append(rel)
        text = p.read_text(encoding="utf-8", errors="replace")
        low = text.lower()
        for marker in SECRET_MARKERS:
            if marker.lower() in low:
                secret_hits.append({"file": rel, "marker": marker})
        for marker in ABSOLUTE_USER_MARKERS:
            if marker in text:
                path_hits.append({"file": rel, "marker": marker})
    return {
        "scanned_files": scanned,
        "scanner_excluded": SCANNER_EXCLUDED,
        "secret_markers": list(SECRET_MARKERS),
        "secret_hits": secret_hits,
        "absolute_user_path_markers": list(ABSOLUTE_USER_MARKERS),
        "absolute_user_path_hits": path_hits,
        "user_db_policy": ("no user DB is bundled: the runtime root owns "
                           "data/motionforge.db and is created outside the "
                           "package tree"),
        "global_config_policy": ("no global Hermes config is read or "
                                 "modified by these artifacts"),
    }


def build_inventory(repo: Path, generated_at: str) -> dict:
    return {
        "schema": "mf2d-demo-inventory/1",
        "generated_at_utc": generated_at,
        "source_head": git_head(repo),
        "backend": {
            "pins": backend_pins(repo),
            "requires_python": ">=3.11,<3.13",
            "app_tree_sha256": tree_digest(repo / "app"),
        },
        "frontend": {
            "pins": frontend_pins(repo)[0],
            "lockfile_sha256": frontend_pins(repo)[1],
        },
        "toolchain": {
            "python": probe_version(sys.executable, ["--version"]),
            "node": probe_version("node", ["--version"]),
            "ffmpeg": probe_version("ffmpeg", ["-hide_banner", "-version"]),
        },
        "comfy": comfy_section(),
        "models": models_section(),
        "frozen_packaging": frozen_packaging_inventory(repo),
        "guardrails": guardrails(repo),
    }


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="build_demo_package_inventory.py")
    ap.add_argument("--out-dir", default=str(DEMO_DIR))
    ap.add_argument("--generated-at", default=None)
    args = ap.parse_args(argv)
    generated_at = args.generated_at or datetime.now(
        UTC).isoformat(timespec="seconds")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    repo = REPO

    models = models_section()
    write_json(out_dir / MODELS_NAME, models)
    inventory = build_inventory(repo, generated_at)
    write_json(out_dir / INVENTORY_NAME, inventory)

    print(f"models.json    : {len(models['models'])} external models "
          f"(bundled={models['bundled']})")
    print(f"inventory.json : backend pins "
          f"{len(inventory['backend']['pins'])}, frontend pins "
          f"{len(inventory['frontend']['pins'])}, frozen packaging rows "
          f"{len(inventory['frozen_packaging'])}")
    print(f"guardrail hits : secrets={len(inventory['guardrails']['secret_hits'])}"
          f" absolute_paths="
          f"{len(inventory['guardrails']['absolute_user_path_hits'])}")
    print(f"wrote to       : {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
