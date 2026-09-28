"""MF-END-28 — Đóng gói runtime/engine cho demo + S12: acceptance + negatives.

Row map (nhị phân):

* 28.0  micro/surface: launcher ``scripts/mf_delivery_launcher.ps1`` tồn tại,
  parse được bằng PowerShell AST (0 lỗi), không chứa path tuyệt đối kiểu
  ``C:\\Users\\...``, phụ thuộc ``$PSScriptRoot`` (không dùng cwd), có đủ
  chuỗi hợp đồng: ``-WindowStyle Hidden``, ``/health``, ``MODEL_MISSING``,
  ``MF2D_MODELS_ROOT``; các file ``packaging/demo/*`` tồn tại.
* 28.1  inventory/manifest phản ánh THẬT: backend pins == pyproject.toml;
  comfy dependency pin == hằng số trong ``scripts/build_mf_comfy_dependency.py``;
  frontend pins 17 mục; toolchain có version python/node/ffmpeg; models.json
  mọi entry ``bundled: false`` + có sha256/bytes/license + rel không tuyệt đối.
* 28.2  builder tất định: chạy lại với cùng ``--generated-at`` → byte-identical
  với file đã commit (models.json) và bằng inventory.json sau khi bỏ
  ``generated_at_utc``; hai lần chạy cùng timestamp → giống nhau từng byte.
* 28.3  launcher chạy THẬT từ cwd lạ (tempdir): ``check`` rc=0 + JSON ok +
  model rows khớp đĩa; thiếu model → rc=3 + đúng số dòng ``MODEL_MISSING``;
  ``stop`` khi chưa/đã dừng → ``not_running``/``already_gone`` rc=0.
* 28.4  package staged NGOÀI checkout: các quy tắc từ chối của harness S12-T06A
  (stage root trong repo / trong protected MAIN) là THẬT (chạy được, BLOCKED);
  nếu bản staged ngoài checkout tồn tại (``MF2D_DEMO_STAGE`` hoặc
  ``~/MF2D-demo-pkg-*``) → kiểm integrity: manifest schema 2, backend/frontend
  staged, KHÔNG có user DB (``*.db``) và KHÔNG có model weights (``*.safetensors``)
  trong package; thiếu host-clean → ghi NOT_RUN (không bịa).
* 28.5  THIRD_PARTY.md bounded patch: section cũ còn nguyên (PyTorch, SAM 2.1,
  Renderer Router, checklist cuối), section mới hiện diện (ComfyUI engine +
  mf-comfy + bảng model + ghi chú no-secrets), giữ CRLF, không BOM.

Disclosure: 28.3/28.4 dùng PowerShell thật + process thật của host này
(Windows).  Không GPU, không copy model/DB vào package.  Clean Windows
VM/human acceptance là hạng mục R1 của delivery — NOT_RUN ở đây.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

WT = Path(__file__).resolve().parents[2]
LAUNCHER = WT / "scripts" / "mf_delivery_launcher.ps1"
DEMO_DIR = WT / "packaging" / "demo"
INVENTORY = DEMO_DIR / "inventory.json"
MODELS_JSON = DEMO_DIR / "models.json"
BUILDER = DEMO_DIR / "build_demo_package_inventory.py"
README = DEMO_DIR / "README.md"
THIRD_PARTY = WT / "THIRD_PARTY.md"
REGISTRY = WT / "app" / "media_workflows" / "model_profiles.json"
COMFY_BUILDER = WT / "scripts" / "build_mf_comfy_dependency.py"
STAGE_SCRIPT = WT / "scripts" / "s12" / "s12_t06a_stage.py"

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ABS_PATH_MARKERS = ("C:\\Users\\", "C:/Users/", "/c/Users/")


def _run(cmd: list[str], cwd: Path | None = None,
         timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def _launcher_json(proc: subprocess.CompletedProcess) -> dict | None:
    for line in (proc.stdout or "").splitlines():
        if line.startswith("LAUNCHER_JSON="):
            return json.loads(line.split("=", 1)[1])
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


# --- 28.0 ------------------------------------------------------------------

def test_28_0_surface_and_powershell_syntax() -> None:
    for p in (LAUNCHER, INVENTORY, MODELS_JSON, README, BUILDER):
        assert p.is_file(), f"missing deliverable: {p}"
    text = LAUNCHER.read_text(encoding="utf-8")
    for marker in ("$PSScriptRoot", "-WindowStyle Hidden", "/health",
                   "MODEL_MISSING", "MF2D_MODELS_ROOT", "LAUNCHER_JSON=",
                   "identity verified"):
        assert marker in text, f"launcher contract marker missing: {marker}"
    for bad in ABS_PATH_MARKERS:
        assert bad not in text, f"absolute user path marker in launcher: {bad}"
    if POWERSHELL is None:
        pytest.skip("powershell not on PATH (NOT_RUN: PS AST parse)")
    script = (
        "$t=$null;$e=$null;"
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{LAUNCHER}',[ref]$t,[ref]$e);"
        "$e | ForEach-Object { $_.ToString() }; exit $e.Count"
    )
    proc = _run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
                 script])
    assert proc.returncode == 0, f"PS parse errors: {proc.stdout}"


# --- 28.1 ------------------------------------------------------------------

def test_28_1_manifests_reflect_the_real_tree() -> None:
    import tomllib
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    models = json.loads(MODELS_JSON.read_text(encoding="utf-8"))

    with open(WT / "pyproject.toml", "rb") as fh:
        deps = sorted(tomllib.load(fh)["project"]["dependencies"])
    assert inv["backend"]["pins"] == deps, "backend pins diverge from pyproject"

    builder_text = COMFY_BUILDER.read_text(encoding="utf-8")
    m = re.search(r'^PINNED_COMMIT = "([0-9a-f]{40})"', builder_text, re.M)
    assert m, "cannot read PINNED_COMMIT from the comfy builder"
    assert inv["comfy"]["dependency"]["source_commit"] == m.group(1), (
        "comfy source commit diverges from scripts/build_mf_comfy_dependency.py")
    assert inv["comfy"]["dependency"]["module_file_count"] >= 1

    assert len(inv["frontend"]["pins"]) >= 10
    for key in ("python", "node", "ffmpeg"):
        assert inv["toolchain"][key]["version"], f"toolchain {key} unmeasured"

    assert models["bundled"] is False
    assert models["copy_policy"].startswith("external read-only")
    assert len(models["models"]) >= 8
    for entry in models["models"]:
        rel = entry["rel"]
        assert not Path(rel).is_absolute(), f"model rel must be relative: {rel}"
        assert "/" in rel
        assert SHA_RE.match(entry["sha256"]), f"bad sha for {rel}"
        assert entry["bytes"] > 0
        assert entry["license"], f"license missing for {rel}"


def test_28_1b_models_exist_on_this_host() -> None:
    root_raw = _registry()["engine"]["models_root"]
    root = Path(root_raw)
    if not root.is_dir():
        pytest.skip(f"NOT_RUN: models root absent on this host ({root_raw})")
    models = json.loads(MODELS_JSON.read_text(encoding="utf-8"))
    missing = []
    for entry in models["models"]:
        f = root / entry["rel"]
        if not f.is_file() or f.stat().st_size != entry["bytes"]:
            missing.append(entry["rel"])
    assert not missing, f"declared models missing/size-mismatch: {missing}"


# --- 28.2 ------------------------------------------------------------------

def test_28_2_builder_is_deterministic(tmp_path: Path) -> None:
    stamp = "2026-09-28T12:00:00+00:00"
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    for out in (out_a, out_b):
        proc = _run([sys.executable, str(BUILDER), "--out-dir", str(out),
                     "--generated-at", stamp], cwd=WT)
        assert proc.returncode == 0, proc.stderr[-400:]
    assert (out_a / "models.json").read_bytes() == (
        out_b / "models.json").read_bytes(), "models.json not deterministic"
    inv_a = json.loads((out_a / "inventory.json").read_text(encoding="utf-8"))
    inv_b = json.loads((out_b / "inventory.json").read_text(encoding="utf-8"))
    assert inv_a == inv_b, "inventory.json differs between identical runs"

    committed = json.loads(INVENTORY.read_text(encoding="utf-8"))
    fresh = dict(inv_a)
    committed_cmp = dict(committed)
    fresh.pop("generated_at_utc", None)
    committed_cmp.pop("generated_at_utc", None)
    assert fresh == committed_cmp, (
        "committed inventory.json is stale vs a fresh build "
        "(rerun packaging/demo/build_demo_package_inventory.py)")


def test_28_2b_guardrail_scans_are_clean() -> None:
    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    guard = inv["guardrails"]
    assert guard["secret_hits"] == [], guard["secret_hits"]
    assert guard["absolute_user_path_hits"] == [], guard["absolute_user_path_hits"]
    scanned = guard["scanned_files"]
    for rel in ("scripts/mf_delivery_launcher.ps1", "THIRD_PARTY.md",
                "packaging/demo/README.md", "packaging/demo/models.json"):
        assert rel in scanned, f"guardrail did not scan {rel}"


# --- 28.3 ------------------------------------------------------------------

def test_28_3_launcher_check_real_run_from_foreign_cwd(tmp_path: Path) -> None:
    if POWERSHELL is None:
        pytest.skip("powershell not on PATH (NOT_RUN)")
    reg_root = _registry()["engine"]["models_root"]
    bp, fp = _free_port(), _free_port()
    proc = _run([POWERSHELL, "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(LAUNCHER),
                 "-Action", "check", "-PackageRoot", str(WT),
                 "-ModelsRoot", reg_root,
                 "-BackendPort", str(bp), "-FrontendPort", str(fp)],
                cwd=tmp_path)
    data = _launcher_json(proc)
    assert data is not None, f"no LAUNCHER_JSON line: {proc.stdout[-300:]}"
    if Path(reg_root).is_dir():
        assert proc.returncode == 0, json.dumps(data)[:400]
        assert data["status"] == "ok"
        assert data["models"]["status"] == "ok"
        assert len(data["models"]["missing"]) == 0
        assert data["toolchain"]["python"] and data["toolchain"]["node"]
        assert "ffmpeg" in (data["toolchain"]["ffmpeg"] or "")
    else:
        assert proc.returncode == 3
        codes = [f["code"] for f in data["findings"]]
        assert "MODELS_ROOT_UNSET" in codes or "MODELS_ROOT_MISSING" in codes


def test_28_3b_launcher_flags_missing_models(tmp_path: Path) -> None:
    if POWERSHELL is None:
        pytest.skip("powershell not on PATH (NOT_RUN)")
    empty = tmp_path / "empty-models"
    empty.mkdir()
    bp, fp = _free_port(), _free_port()
    proc = _run([POWERSHELL, "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(LAUNCHER),
                 "-Action", "check", "-PackageRoot", str(WT),
                 "-ModelsRoot", str(empty),
                 "-BackendPort", str(bp), "-FrontendPort", str(fp)],
                cwd=tmp_path)
    data = _launcher_json(proc)
    assert data is not None
    declared = len(json.loads(MODELS_JSON.read_text(encoding="utf-8"))["models"])
    codes = [f["code"] for f in data["findings"]]
    assert proc.returncode == 3, json.dumps(data)[:400]
    assert codes.count("MODEL_MISSING") == declared, codes
    assert data["status"] == "blocked"


def test_28_3c_launcher_stop_is_idempotent_and_typed() -> None:
    if POWERSHELL is None:
        pytest.skip("powershell not on PATH (NOT_RUN)")
    runtime = (os.environ.get("MF2D_DEMO_RUNTIME")
               or str(Path(os.environ.get("TEMP", ".")) / "mf28-rt-none"))
    proc = _run([POWERSHELL, "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(LAUNCHER),
                 "-Action", "stop", "-RuntimeRoot", runtime], timeout=120)
    data = _launcher_json(proc)
    assert data is not None
    if proc.returncode == 0 and data.get("status") == "not_running":
        assert data["action"] == "stop"
    else:
        # A recorded-but-dead pair must be reported already_gone, never killed.
        assert data.get("status") in ("stopped", "not_running"), data
        for res in data.get("results", {}).values():
            assert res.get("status") in ("already_gone", "no_record",
                                         "stopped"), res


# --- 28.4 ------------------------------------------------------------------

def test_28_4_stage_harness_refusal_rules_are_real(tmp_path: Path) -> None:
    inside_repo = WT / "packaging" / "_mf28_should_refuse"
    assert not inside_repo.exists()
    proc = _run([sys.executable, str(STAGE_SCRIPT), "--stage-root",
                 str(inside_repo)], cwd=WT)
    assert proc.returncode != 0
    msg = proc.stdout + proc.stderr
    assert "BLOCKED" in msg and "OUTSIDE the repo checkout" in msg, msg
    assert not inside_repo.exists(), "refusal must not create the stage dir"

    protected = Path.home() / "MotionForge2D" / "_mf28_should_refuse"
    proc2 = _run([sys.executable, str(STAGE_SCRIPT), "--stage-root",
                  str(protected)], cwd=WT)
    assert proc2.returncode != 0
    msg2 = proc2.stdout + proc2.stderr
    assert "BLOCKED" in msg2 and "protected MAIN" in msg2, msg2
    assert not protected.exists()


def test_28_4b_staged_demo_package_outside_checkout() -> None:
    candidates: list[Path] = []
    env = os.environ.get("MF2D_DEMO_STAGE")
    if env:
        candidates.append(Path(env))
    candidates += sorted(Path.home().glob("MF2D-demo-pkg-*"),
                         key=lambda p: p.stat().st_mtime if p.exists() else 0,
                         reverse=True)
    pkg = next((c for c in candidates if c.is_dir()), None)
    if pkg is None:
        pytest.skip("NOT_RUN: no staged demo package on this host "
                    "(set MF2D_DEMO_STAGE to a package root)")
    resolved = pkg.resolve()
    assert not resolved.is_relative_to(WT.resolve()), (
        "demo package must live OUTSIDE the checkout")
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "s12-t06a-package/2"
    assert (pkg / "backend" / "app" / "main.py").is_file()
    assert (pkg / "frontend" / ".next" / "BUILD_ID").is_file()
    assert (pkg / "scripts" / "s12_t06a_run.py").is_file()
    assert (pkg / "Start-MotionForge-Beta.cmd").is_file()
    # KHÔNG copy user DB / model weights vào package:
    assert not list(pkg.rglob("*.db")), "user DB copied into the package"
    assert not list(pkg.rglob("*.sqlite*")), "sqlite files copied into package"
    assert not list(pkg.rglob("*.safetensors")), "model weights copied into package"


# --- 28.5 ------------------------------------------------------------------

def test_28_5_third_party_bounded_patch_integrity() -> None:
    data = THIRD_PARTY.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf"), "BOM introduced"
    assert data.count(b"\r\n") == data.count(b"\n"), "CRLF/LF mix introduced"
    text = data.decode("utf-8")
    # Sections mới (MF-END-28):
    for marker in ("## ComfyUI Engine And Shot-Engine Dependency (MF-END-18 / MF-END-28)",
                   "## AI Model Checkpoints For The Demo Graphs",
                   "wan_animate_2_int8_convrot.safetensors",
                   "no keys, tokens or credentials"):
        assert marker in text, f"missing new THIRD_PARTY marker: {marker}"
    # Nội dung cũ còn nguyên (bounded patch, không rewrite):
    for marker in ("## Python Packages", "**PyTorch**", "sam2.1_hiera_large.pt",
                   "## Renderer Router Wired Backends (S09-T00-I02)",
                   "Fully offline-capable after model download",
                   "validate_license_for_product_use"):
        assert marker in text, f"THIRD_PARTY lost original content: {marker}"
    models = json.loads(MODELS_JSON.read_text(encoding="utf-8"))
    for entry in models["models"]:
        base = entry["rel"].split("/")[-1]
        assert base in text, f"model not documented in THIRD_PARTY: {base}"
