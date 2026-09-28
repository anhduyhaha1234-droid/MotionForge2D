"""MF-END-18 — Comfy adapter packaged as an app dependency: acceptance + negative controls.

Row map (binary):
* micro repro: the adapter module imports with ZERO engine dependency present, and
  reports a typed ``mf_end18_engine_unavailable`` in a clean environment;
* build/provenance: the build script extracts the pinned commit from the git
  OBJECT STORE, verifies the 11-file manifest live, refuses unpinned bytes and
  unresolved commits, and installs a RECORD-verified wheel; the runtime refuses
  any tampered/missing-provenance install with its own typed codes;
* roundtrip (fake HTTP transport at the process boundary — NO GPU, no real
  ComfyUI server): health → capability probe → run_shot submit/history/validate
  → ``ShotExecutionRecord(outcome="completed")`` composed through the FROZEN
  ``app.schemas.shot_reskin`` contract, artifacts hashed on disk;
* negative controls: capibility missing, workflow-pin hash mismatch, timeout
  after submit (ambiguous, never a second POST), foreign identity, lease-gated
  cancel, OOM → failed record, replay reuses the durable receipt, epoch missing;
* authority: one gate / one lease / one reservation ledger per managed root —
  two engines over the same root share exactly the same authority paths;
* static: no ``sys.path`` usage and no developer-worktree path in the adapter;
  the pyproject patch is bounded (dependency + entry point only, everything else
  byte-identical to the frozen base commit).
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.adapters.media_engine import comfy as engine_adapter
from app.schemas import shot_reskin as sr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_mf_comfy_dependency.py"
DEFAULT_SOURCE_REPO = "C:/Users/Admin/Documents/Codex/work/mfv1/wt-comfy"
SOURCE_REPO = Path(os.environ.get("MF_END18_SOURCE_REPO", DEFAULT_SOURCE_REPO))
BASE_COMMIT = "3602eb27302bd1f9665c5b2767814f201dd2257d"  # MF-END-18 wave base (immutable)
PIN = engine_adapter.MF_COMFY_SOURCE_COMMIT_PIN
CKPT = "model_a.safetensors"
TERMINAL_OUTPUTS = {"9": {"kind": "image", "media_type": "image"}}


def _load_build_module() -> Any:
    spec = importlib.util.spec_from_file_location("mf18_build_script", BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = _load_build_module()


def _run_python(code: str, *, path_entries: list[Path]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(p) for p in path_entries)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT_ROOT),
    )


# ── module-scoped dependency: build + verified install from the pin ──────────


@pytest.fixture(scope="module")
def dependency(tmp_path_factory: pytest.TempPathFactory) -> Any:
    if not SOURCE_REPO.is_dir():
        pytest.skip(f"pinned source repo {SOURCE_REPO} is absent on this machine")
    root = tmp_path_factory.mktemp("mf18_dependency")
    build_dir = root / "build"
    site = root / "site"
    proc = subprocess.run(
        [
            sys.executable, str(BUILD_SCRIPT),
            "--source-repo", str(SOURCE_REPO),
            "--out", str(build_dir),
            "--install-target", str(site),
            "--built-at", "2026-09-28T00:00:00Z",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"build refused: {proc.stderr}"
    summary = json.loads(proc.stdout)
    sys.path.insert(0, str(site))
    sys.modules.pop("mf_comfy", None)
    importlib.invalidate_caches()
    module = importlib.import_module("mf_comfy")
    yield SimpleNamespace(
        root=root, build_dir=build_dir, site=site, summary=summary,
        wheel=Path(summary["wheel"]), mf=module,
    )
    sys.modules.pop("mf_comfy", None)
    with contextlib.suppress(ValueError):
        sys.path.remove(str(site))


# ── fake ComfyUI server (the process boundary: HTTP transport surface) ───────


class FakeClock:
    def __init__(self, step: float = 0.5) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float | None = None) -> None:
        self.t += self.step if dt is None else float(dt)


def png_bytes(w: int = 8, h: int = 8, color: tuple[int, int, int] = (120, 80, 40)) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def minimal_object_info() -> dict[str, Any]:
    return {
        "CheckpointLoaderSimple": {
            "input": {"required": {"ckpt_name": [[CKPT]]}},
            "output": ["MODEL", "CLIP", "VAE"], "output_node": False,
            "python_module": "nodes",
        },
        "EmptyLatentImage": {
            "input": {"required": {"width": ["INT", {}], "height": ["INT", {}],
                                   "batch_size": ["INT", {}]}},
            "output": ["LATENT"], "output_node": False, "python_module": "nodes",
        },
        "CLIPTextEncode": {
            "input": {"required": {"text": ["STRING", {}], "clip": ["CLIP", {}]}},
            "output": ["CONDITIONING"], "output_node": False, "python_module": "nodes",
        },
        "KSampler": {
            "input": {"required": {
                "seed": ["INT", {}], "steps": ["INT", {}], "cfg": ["FLOAT", {}],
                "sampler_name": [["euler", "lcm"], {}], "scheduler": [["normal"], {}],
                "denoise": ["FLOAT", {}], "model": ["MODEL", {}],
                "positive": ["CONDITIONING", {}], "negative": ["CONDITIONING", {}],
                "latent_image": ["LATENT", {}]}},
            "output": ["LATENT"], "output_node": False, "python_module": "nodes",
        },
        "VAEDecode": {
            "input": {"required": {"samples": ["LATENT", {}], "vae": ["VAE", {}]}},
            "output": ["IMAGE"], "output_node": False, "python_module": "nodes",
        },
        "SaveImage": {
            "input": {"required": {"filename_prefix": ["STRING", {}], "images": ["IMAGE", {}]}},
            "output": ["IMAGE"], "output_node": True, "python_module": "nodes",
        },
    }


def light_graph(seed: int = 42, prefix: str = "mf18_out", ckpt: str = CKPT) -> dict[str, Any]:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 64, "height": 64, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "b", "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 6, "cfg": 1.0, "sampler_name": "lcm",
            "scheduler": "normal", "denoise": 1.0, "model": ["4", 0],
            "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix,
                                                    "images": ["8", 0]}},
    }


def history_success(prompt_id: str, filename: str = "mf18_out_00001_.png",
                    server_type: str = "output") -> dict[str, Any]:
    return {
        "prompt": [0, prompt_id, {}, {}, []],
        "outputs": {"9": {"images": [{"filename": filename, "subfolder": "",
                                      "type": server_type}]}},
        "status": {"status_str": "success", "completed": True, "messages": []},
    }


def history_error(prompt_id: str, text: str) -> dict[str, Any]:
    return {
        "prompt": [0, prompt_id, {}, {}, []],
        "outputs": {},
        "status": {
            "status_str": "error", "completed": False,
            "messages": [["execution_error", {
                "node_id": "3", "node_type": "KSampler", "exception_message": text}]],
        },
    }


def queue_item(prompt_id: str) -> list[Any]:
    return [0, prompt_id, {}, {}, []]


class FakeComfyServer:
    """Same surface as the package's HttpTransport; scenario knobs are explicit."""

    def __init__(self, oi: dict[str, Any] | None = None, clock: FakeClock | None = None) -> None:
        self.oi = oi if oi is not None else minimal_object_info()
        self.clock = clock
        self.submit_calls = 0
        self.submitted_graphs: list[dict] = []
        self.history_map: dict[str, dict] = {}
        self.queue_state: dict[str, list] = {"queue_running": [], "queue_pending": []}
        self.interrupt_calls: list[str] = []
        self.interrupt_history: dict | None = None
        self.view_payload = png_bytes()
        self.view_items: dict[tuple[str, str], bytes] = {}
        self.closed = False
        self.on_submit: Any | None = None

    # -- transport surface --
    def system_stats(self) -> dict[str, Any]:
        return {
            "system": {"comfyui_version": "fake-9.9", "python_version": "3.11", "os": "test"},
            "devices": [{"name": "fake-gpu", "vram_total": 12227 * 1024 * 1024}],
        }

    def object_info(self) -> dict[str, Any]:
        return self.oi

    def probe_capabilities(self, object_info: dict | None = None) -> dict[str, Any]:
        oi = object_info if object_info is not None else self.oi
        return {
            "base_url": "http://127.0.0.1:8199", "loopback_only": True,
            "comfyui_version": "fake-9.9", "device_name": "fake-gpu",
            "device_total_vram_mib": 12227, "node_class_count": len(oi or {}),
            "interrupt_payload": "json", "history_direct_endpoint": True,
        }

    def submit(self, graph: dict, client_id: str) -> Any:
        from mf_comfy.transport import SubmitResult

        self.submit_calls += 1
        self.submitted_graphs.append(graph)
        if self.on_submit is not None:
            self.on_submit(client_id)
        return SubmitResult(prompt_id=f"pid-{self.submit_calls}", number=self.submit_calls)

    def history(self, prompt_id: str = "") -> dict[str, Any]:
        if not prompt_id:
            return dict(self.history_map)
        entry = self.history_map.get(prompt_id)
        return {prompt_id: entry} if entry else {}

    def queue(self) -> dict[str, Any]:
        return self.queue_state

    def interrupt(self, prompt_id: str) -> dict[str, Any]:
        self.interrupt_calls.append(prompt_id)
        self.queue_state = {"queue_running": [], "queue_pending": []}
        if self.interrupt_history is not None:
            self.history_map[prompt_id] = self.interrupt_history
        return {"ok": True}

    def fetch_view(self, item: dict) -> bytes:
        key = (item.get("subfolder", ""), item.get("filename", ""))
        return self.view_items.get(key, self.view_payload)

    def drain_events(self, client_id: str, timeout_s: float) -> list[dict]:
        if self.clock is not None:
            self.clock.advance(timeout_s)
        return []

    def close(self) -> None:
        self.closed = True


def make_engine(
    tmp_path: Path,
    server: FakeComfyServer,
    *,
    owner: str = "motionforge.comfy_shot_engine",
    stage_timeout_s: float = 2.0,
    poll_s: float = 0.5,
    write_epoch: bool = True,
    epoch_overrides: dict | None = None,
) -> tuple[Any, FakeClock]:
    managed_root = Path(tmp_path) / "managed"
    state = managed_root / "media_engine" / "comfy_shot_engine"
    state.mkdir(parents=True, exist_ok=True)
    clock = FakeClock(step=0.25)
    server.clock = clock
    if write_epoch:
        epoch_path = state / "instance_epoch.json"
        # One boot identity per managed root: a second engine over the same root
        # must share the recorded epoch (a rewrite would be a new server launch).
        if not epoch_path.exists() or epoch_overrides is not None:
            epoch = {
                "instance_id": uuid.uuid4().hex, "launched_at": 0.0, "pid": os.getpid(),
                "host": "test-host", "base_url": "http://127.0.0.1:8199",
                "comfyui_version": "fake-9.9",
            }
            if epoch_overrides:
                epoch.update(epoch_overrides)
            epoch_path.write_text(json.dumps(epoch), encoding="utf-8")
    engine = engine_adapter.ComfyShotEngine(
        managed_root=managed_root,
        base_url="http://127.0.0.1:8199",
        owner=owner,
        transport=server,
        clock=clock,
        sleep=clock.advance,
        stage_timeout_s=stage_timeout_s,
        poll_s=poll_s,
    )
    return engine, clock


def make_binding(
    *,
    attempt_id: str = "attempt-mf18-1",
    workflow_hash: str,
    identity_over: dict | None = None,
) -> sr.EngineInputBinding:
    data = copy.deepcopy(sr.FROZEN_EXAMPLES["execution_record_book_p3b"]["input"])
    data["identity"]["attempt_id"] = attempt_id
    if identity_over:
        data["identity"].update(identity_over)
    data["graph"]["workflow_id"] = "mf.comfy.fake.saveimage"
    data["graph"]["workflow_version"] = "mf18-test-1"
    data["graph"]["workflow_hash"] = workflow_hash
    data["graph"]["nodes"] = []
    return sr.EngineInputBinding.model_validate(data)


def graph_pin_hash(graph: dict) -> str:
    from mf_comfy.pinning import hash_workflow

    return hash_workflow(graph)


def state_of(tmp_path: Path) -> Path:
    return Path(tmp_path) / "managed" / "media_engine" / "comfy_shot_engine"


def read_receipts(tmp_path: Path) -> list[dict]:
    closed = state_of(tmp_path) / "reservations" / "closed"
    if not closed.is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(closed.glob("*.json"))]


# ── micro repro ──────────────────────────────────────────────────────────────


def test_mf18_1_module_imports_with_pins_and_refusal_taxonomy() -> None:
    codes = list(engine_adapter.ComfyEngineRefusalCode)
    assert len({c.value for c in codes}) == len(codes) == 12
    assert PIN == "70f718098f00f9dbdeb6cc9c5d7808b243eb0c57"
    assert len(engine_adapter.MF_COMFY_MODULE_FILES) == 11
    assert engine_adapter.MF_COMFY_PROVENANCE_SCHEMA == BUILD.PROVENANCE_SCHEMA
    assert engine_adapter.MF_COMFY_PROVENANCE_FILENAME == BUILD.PROVENANCE_NAME


def test_mf18_1_clean_env_import_reports_typed_unavailable() -> None:
    """A clean environment WITHOUT the dependency: import works, status is typed."""
    code = (
        "import json, sys; "
        "from app.adapters.media_engine import comfy as c; "
        "st = c.engine_status(); "
        "print(json.dumps({'available': st['available'], 'code': st.get('code')})); "
        "print('CLEAN_IMPORT_OK')"
    )
    proc = _run_python(code, path_entries=[PROJECT_ROOT])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.splitlines()[0])
    if payload["available"]:
        pytest.skip("mf_comfy is importable in the ambient environment; the clean-env " \
                    "control cannot isolate absence here")
    assert payload["code"] == "mf_end18_engine_unavailable"
    assert "CLEAN_IMPORT_OK" in proc.stdout


# ── build / provenance ───────────────────────────────────────────────────────


def test_mf18_2_dependency_builds_and_installs_from_pinned_source(dependency: Any) -> None:
    summary = dependency.summary
    assert summary["ok"] is True
    assert summary["source_commit"] == PIN
    assert summary["commit_matches_pin"] is True
    assert summary["source_files_verified"] == 11
    assert summary["install"]["module_files_verified"] == 11
    assert dependency.wheel.is_file()
    assert len(summary["wheel_sha256"]) == 64
    installed = dependency.site / "mf_comfy"
    assert (installed / "_mf_provenance.json").is_file()
    assert (installed / "adapter.py").stat().st_size == BUILD.PINNED_FILES["adapter.py"][1]


def test_mf18_2_wheel_members_are_the_pinned_bytes(dependency: Any) -> None:
    import zipfile

    with zipfile.ZipFile(dependency.wheel) as zf:
        names = sorted(zf.namelist())
    expected = sorted(
        [f"mf_comfy/{name}" for name in BUILD.PINNED_FILES]
        + ["mf_comfy/_mf_provenance.json",
           "mf_comfy-0.1.0.dist-info/METADATA",
           "mf_comfy-0.1.0.dist-info/WHEEL",
           "mf_comfy-0.1.0.dist-info/RECORD"]
    )
    assert names == expected
    provenance = json.loads(
        (dependency.site / "mf_comfy" / "_mf_provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["schema"] == BUILD.PROVENANCE_SCHEMA
    assert provenance["source_commit"] == PIN
    assert provenance["commit_matches_pin"] is True
    assert set(provenance["files"]) == set(BUILD.PINNED_FILES)
    for name, (sha, size) in BUILD.PINNED_FILES.items():
        assert provenance["files"][name] == {"sha256": sha, "size_bytes": size}
        on_disk = (dependency.site / "mf_comfy" / name).read_bytes()
        assert hashlib.sha256(on_disk).hexdigest() == sha
        assert len(on_disk) == size


def test_mf18_2_manifest_agrees_three_ways_with_live_git(dependency: Any) -> None:
    """script manifest == wrapper manifest == live bytes at the pin (git object store)."""
    manifest_sha_only = {name: sha for name, (sha, _size) in BUILD.PINNED_FILES.items()}
    assert manifest_sha_only == engine_adapter.MF_COMFY_MODULE_FILES
    proc = subprocess.run(
        ["git", "-C", str(SOURCE_REPO), "rev-parse", "--verify", f"{PIN}^{{commit}}"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == PIN
    for name, (sha, size) in sorted(BUILD.PINNED_FILES.items()):
        blob = subprocess.run(
            ["git", "-C", str(SOURCE_REPO), "cat-file", "blob",
             f"{PIN}:{BUILD.SOURCE_SUBPATH}/{name}"],
            capture_output=True,
        )
        assert blob.returncode == 0, name
        assert hashlib.sha256(blob.stdout).hexdigest() == sha, name
        assert len(blob.stdout) == size, name


def test_mf18_2_build_refuses_unresolved_commit(tmp_path: Path) -> None:
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--source-repo", str(SOURCE_REPO),
         "--commit", "f" * 39, "--out", str(out)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "source_commit_unresolved" in proc.stderr
    assert not list(out.glob("*.whl"))


def _make_local_repo(tmp_path: Path, *, tamper: str, extra: bool, source_files: Path) -> Path:
    repo = tmp_path / "tampered_repo"
    module_dir = repo / "experiments" / "mf_reskin_v1" / "comfy" / "mf_comfy"
    module_dir.mkdir(parents=True)
    for name in BUILD.PINNED_FILES:
        (module_dir / name).write_bytes((source_files / name).read_bytes())
    if tamper:
        path = module_dir / tamper
        path.write_bytes(path.read_bytes() + b"# tampered\n")
    if extra:
        (module_dir / "extra_module.py").write_bytes(b"# not part of the pin\n")
    for cmd in (["init", "-q"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "x"],
        check=True, capture_output=True,
    )
    return repo


def test_mf18_2_build_refuses_unpinned_bytes(tmp_path: Path, dependency: Any) -> None:
    source_files = dependency.site / "mf_comfy"
    # (a) one byte changed in a module file
    repo_a = _make_local_repo(tmp_path / "a", tamper="adapter.py", extra=False,
                              source_files=source_files)
    out_a = tmp_path / "out_a"
    proc = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--source-repo", str(repo_a),
         "--commit", "HEAD", "--out", str(out_a)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "source_content_mismatch" in proc.stderr
    assert not list(out_a.glob("*.whl"))
    # (b) an extra file at the pinned subpath
    repo_b = _make_local_repo(tmp_path / "b", tamper="", extra=True,
                              source_files=source_files)
    out_b = tmp_path / "out_b"
    proc = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--source-repo", str(repo_b),
         "--commit", "HEAD", "--out", str(out_b)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "source_file_set_mismatch" in proc.stderr
    assert not list(out_b.glob("*.whl"))


def test_mf18_2_install_refuses_wheel_record_mismatch(tmp_path: Path, dependency: Any) -> None:
    import zipfile

    tampered = tmp_path / "tampered.whl"
    with zipfile.ZipFile(dependency.wheel) as src, zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "mf_comfy/adapter.py":
                data = data + b"# tampered\n"
            dst.writestr(info, data)
    with pytest.raises(BUILD.BuildRefusal) as excinfo:
        BUILD.install_wheel(tampered, tmp_path / "site_tampered")
    assert excinfo.value.code == "install_record_mismatch"


def test_mf18_2_install_refuses_drifted_target_and_is_idempotent(
    tmp_path: Path, dependency: Any
) -> None:
    target = tmp_path / "site_drifted"
    BUILD.install_wheel(dependency.wheel, target)  # clean install
    again = BUILD.install_wheel(dependency.wheel, target)  # same pinned bytes: idempotent
    assert again["module_files_verified"] == 11
    (target / "mf_comfy" / "adapter.py").write_bytes(b"# drifted\n")
    with pytest.raises(BUILD.BuildRefusal) as excinfo:
        BUILD.install_wheel(dependency.wheel, target)
    assert excinfo.value.code == "install_target_conflict"
    assert (target / "mf_comfy" / "adapter.py").read_bytes() == b"# drifted\n"


def test_mf18_2_clean_env_imports_adapter_with_dependency(dependency: Any) -> None:
    """Acceptance: in a clean interpreter, the app adapter imports and is READY."""
    code = (
        "import json; "
        "from app.adapters.media_engine import comfy as c; "
        "st = c.engine_status(); "
        "e = c.ComfyShotEngine(managed_root='C:/nonexistent/mf18'); "
        "print(json.dumps({'available': st['available'], 'commit': st.get('source_commit'), "
        "'files': st.get('files_verified'), 'pkg': st.get('package_dir'), "
        "'authority_keys': sorted(e.authority())}))"
    )
    proc = _run_python(code, path_entries=[PROJECT_ROOT, dependency.site])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["available"] is True
    assert payload["commit"] == PIN
    assert payload["files"] == 11
    assert str(dependency.site) in payload["pkg"]
    assert payload["authority_keys"] == [
        "epoch", "gpu_stage_lock", "leases", "reservations", "stage_root"]


def test_mf18_2_runtime_refuses_tampered_and_unprovenanced_installs(
    tmp_path: Path, dependency: Any
) -> None:
    variants: list[tuple[str, Path, str]] = []
    # (a) one module byte changed on disk
    site_a = tmp_path / "site_tampered_byte"
    shutil.copytree(dependency.site, site_a)
    adapter_py = site_a / "mf_comfy" / "adapter.py"
    adapter_py.write_bytes(adapter_py.read_bytes() + b"# x\n")
    variants.append(("tampered_byte", site_a, "mf_end18_provenance_mismatch"))
    # (b) provenance record removed
    site_b = tmp_path / "site_no_provenance"
    shutil.copytree(dependency.site, site_b)
    (site_b / "mf_comfy" / "_mf_provenance.json").unlink()
    variants.append(("no_provenance", site_b, "mf_end18_provenance_missing"))
    # (c) an extra module file appears
    site_c = tmp_path / "site_extra_module"
    shutil.copytree(dependency.site, site_c)
    (site_c / "mf_comfy" / "extra.py").write_text("# extra\n", encoding="utf-8")
    variants.append(("extra_module", site_c, "mf_end18_provenance_mismatch"))

    code = (
        "import json; "
        "from app.adapters.media_engine import comfy as c; "
        "st = c.engine_status(); "
        "print(json.dumps({'available': st['available'], 'code': st.get('code')}))"
    )
    for label, site, want_code in variants:
        proc = _run_python(code, path_entries=[PROJECT_ROOT, site])
        assert proc.returncode == 0, f"{label}: {proc.stderr}"
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        assert payload["available"] is False, label
        assert payload["code"] == want_code, label


def test_mf18_2_runtime_status_verifies_in_process(dependency: Any) -> None:
    status = engine_adapter.engine_status()
    assert status["available"] is True
    assert status["source_commit"] == PIN
    assert status["files_verified"] == 11
    assert str(dependency.site) in status["package_dir"]


# ── authority + probes ───────────────────────────────────────────────────────


def test_mf18_3_one_authority_per_managed_root(dependency: Any, tmp_path: Path) -> None:
    server = FakeComfyServer()
    engine_a, _ = make_engine(tmp_path, server)
    engine_b, _ = make_engine(tmp_path, server, owner="second-caller")
    assert engine_a.authority() == engine_b.authority()
    assert engine_a.authority()["reservations"] == str(state_of(tmp_path) / "reservations")
    assert engine_a.authority()["gpu_stage_lock"] == str(state_of(tmp_path) / "gpu_stage.lock")


def test_mf18_3_health_and_capability_probe(dependency: Any, tmp_path: Path) -> None:
    server = FakeComfyServer()
    engine, _ = make_engine(tmp_path, server)
    health = engine.health()
    assert health["ok"] is True
    assert health["comfyui_version"] == "fake-9.9"
    assert health["device_name"] == "fake-gpu"
    assert health["loopback_only"] is True
    probe = engine.capability_probe(
        required_node_classes=("SaveImage", "KSampler"),
        required_models={"CheckpointLoaderSimple": {"ckpt_name": CKPT}},
    )
    assert probe["missing_classes"] == []
    assert probe["missing_models"] == []
    assert len(probe["node_inventory_sha256"]) == 64
    assert probe["node_class_count"] == len(server.oi)


def test_mf18_3_capability_probe_refuses_missing_capability(
    dependency: Any, tmp_path: Path
) -> None:
    server = FakeComfyServer()
    engine, _ = make_engine(tmp_path, server)
    with pytest.raises(engine_adapter.ComfyEngineRefusal) as excinfo:
        engine.capability_probe(required_node_classes=("WanAnimateToVideo",))
    assert excinfo.value.code == engine_adapter.ComfyEngineRefusalCode.CAPABILITY_MISSING
    assert "WanAnimateToVideo" in excinfo.value.detail
    with pytest.raises(engine_adapter.ComfyEngineRefusal) as excinfo:
        engine.capability_probe(
            required_models={"CheckpointLoaderSimple": {"ckpt_name": "absent.safetensors"}}
        )
    assert excinfo.value.code == engine_adapter.ComfyEngineRefusalCode.CAPABILITY_MISSING
    assert "absent.safetensors" in excinfo.value.detail


def test_mf18_3_epoch_missing_refuses_to_submit(dependency: Any, tmp_path: Path) -> None:
    server = FakeComfyServer()
    engine, _ = make_engine(tmp_path, server, write_epoch=False)
    with pytest.raises(engine_adapter.ComfyEngineRefusal) as excinfo:
        engine.health()
    assert excinfo.value.code == engine_adapter.ComfyEngineRefusalCode.EPOCH_MISSING
    assert server.submit_calls == 0


# ── the roundtrip ────────────────────────────────────────────────────────────


def test_mf18_3_run_shot_roundtrip_completes_and_records(
    dependency: Any, tmp_path: Path
) -> None:
    graph = light_graph()
    server = FakeComfyServer()
    server.history_map["pid-1"] = history_success("pid-1")
    engine, _ = make_engine(tmp_path, server)
    binding = make_binding(workflow_hash=graph_pin_hash(graph))

    record = engine.run_shot(
        binding, graph=graph, terminal_outputs=TERMINAL_OUTPUTS, shot_id="BOOK",
    )

    assert isinstance(record, sr.ShotExecutionRecord)
    assert record.execution_backend == "comfy_shot_engine"
    assert record.legacy_route is None
    assert record.capability == "source_video_motion_transfer"
    assert record.outcome == "completed"
    assert record.error is None
    assert record.input is binding
    assert record.output is not None
    out = record.output
    assert out.prompt_id == "pid-1"
    assert out.graph_sha256_server == binding.graph.workflow_hash
    assert out.decoded.decoded_frames == binding.output_contract.frame_count
    assert out.decoded.timebase == "1/15360"
    assert out.audio.mode == "source_remux"
    assert out.server_side_wall_s > 0
    assert len(out.artifacts) == 1
    artifact = out.artifacts[0]
    assert artifact.kind == "image"
    assert artifact.media_type == "image/png"
    assert artifact.publishable is True
    assert artifact.server_output_type == "output"
    assert artifact.sha256 == hashlib.sha256(server.view_payload).hexdigest()
    staged = engine_adapter.Path(engine.managed_root) / artifact.store_relative_path
    assert staged.is_file()
    assert hashlib.sha256(staged.read_bytes()).hexdigest() == artifact.sha256
    assert not Path(artifact.store_relative_path).is_absolute()
    # round-trip through the FROZEN contract
    reparsed = sr.ShotExecutionRecord.model_validate(record.model_dump(mode="json"))
    assert reparsed == record
    # exactly ONE POST, reservation durably closed as terminal_success
    assert server.submit_calls == 1
    receipts = read_receipts(tmp_path)
    assert len(receipts) == 1
    assert receipts[0]["outcome"] == "terminal_success"
    assert receipts[0]["prompt_id"] == "pid-1"
    assert receipts[0]["submit_count"] == 1
    # the gate and the lease were released; evidence was written
    assert engine._gate.held is False
    assert engine._lease.read() is None
    evidence = list((state_of(tmp_path) / "evidence").glob("*.engine_evidence.json"))
    assert len(evidence) == 1
    payload = json.loads(evidence[0].read_text(encoding="utf-8"))
    assert payload["status"] == "validated"
    assert payload["counters"]["submit_count"] == 1


def test_mf18_3_replay_reuses_durable_receipt_without_second_post(
    dependency: Any, tmp_path: Path
) -> None:
    graph = light_graph()
    server = FakeComfyServer()
    server.history_map["pid-1"] = history_success("pid-1")
    engine, _ = make_engine(tmp_path, server)
    binding = make_binding(workflow_hash=graph_pin_hash(graph))

    first = engine.run_shot(binding, graph=graph, terminal_outputs=TERMINAL_OUTPUTS)
    record, info = engine.replay(binding, graph=graph, terminal_outputs=TERMINAL_OUTPUTS)

    assert info["replayed"] is True
    assert info["submit_count"] == 0
    assert record.outcome == "completed"
    assert record.output is not None and first.output is not None
    assert record.output.prompt_id == first.output.prompt_id == "pid-1"
    assert record.output.artifacts[0].sha256 == first.output.artifacts[0].sha256
    assert server.submit_calls == 1, "replay must never POST a second prompt"
    assert len(read_receipts(tmp_path)) == 1


def test_mf18_4_run_shot_refuses_hash_mismatch_with_zero_posts(
    dependency: Any, tmp_path: Path
) -> None:
    graph = light_graph()
    server = FakeComfyServer()
    server.history_map["pid-1"] = history_success("pid-1")
    engine, _ = make_engine(tmp_path, server)
    binding = make_binding(workflow_hash="0" * 64)  # pin names a different graph

    with pytest.raises(engine_adapter.ComfyEngineRefusal) as excinfo:
        engine.run_shot(binding, graph=graph, terminal_outputs=TERMINAL_OUTPUTS)
    assert excinfo.value.code == engine_adapter.ComfyEngineRefusalCode.PIN_MISMATCH
    assert excinfo.value.engine_code == "MF_COMFY_WORKFLOW_HASH_MISMATCH"
    assert server.submit_calls == 0
    assert read_receipts(tmp_path) == []


def test_mf18_4_timeout_is_ambiguous_and_never_resubmits(
    dependency: Any, tmp_path: Path
) -> None:
    graph = light_graph()
    server = FakeComfyServer()
    server.queue_state["queue_running"] = [queue_item("pid-1")]  # stays queued
    engine, _ = make_engine(tmp_path, server, stage_timeout_s=1.0)
    binding = make_binding(workflow_hash=graph_pin_hash(graph))

    with pytest.raises(engine_adapter.ComfyEngineRefusal) as excinfo:
        engine.run_shot(binding, graph=graph, terminal_outputs=TERMINAL_OUTPUTS)
    assert excinfo.value.code == engine_adapter.ComfyEngineRefusalCode.AMBIGUOUS_AFTER_SUBMIT
    assert server.submit_calls == 1
    # the durable reservation is kept, the gate and lease stay held
    markers = list((state_of(tmp_path) / "reservations").glob("*.reservation.json"))
    assert len(markers) == 1
    assert read_receipts(tmp_path) == []
    assert engine._gate.held is True
    assert engine._lease.read() is not None
    # a second call with the SAME identity re-adopts and still never re-POSTs
    with pytest.raises(engine_adapter.ComfyEngineRefusal):
        engine.run_shot(binding, graph=graph, terminal_outputs=TERMINAL_OUTPUTS)
    assert server.submit_calls == 1, "an unresolved attempt may never become a second POST"
    assert len(list((state_of(tmp_path) / "reservations").glob("*.reservation.json"))) == 1


def test_mf18_4_foreign_owner_is_refused(dependency: Any, tmp_path: Path) -> None:
    graph = light_graph()
    server = FakeComfyServer()
    server.queue_state["queue_running"] = [queue_item("pid-1")]
    engine, _ = make_engine(tmp_path, server, stage_timeout_s=1.0)
    binding = make_binding(workflow_hash=graph_pin_hash(graph))
    with pytest.raises(engine_adapter.ComfyEngineRefusal):
        engine.run_shot(binding, graph=graph, terminal_outputs=TERMINAL_OUTPUTS)
    assert server.submit_calls == 1

    intruder_binding = make_binding(workflow_hash=graph_pin_hash(graph))
    engine_intruder, _ = make_engine(tmp_path, server, owner="intruder")
    with pytest.raises(engine_adapter.ComfyEngineRefusal) as excinfo:
        engine_intruder.run_shot(
            intruder_binding, graph=graph, terminal_outputs=TERMINAL_OUTPUTS
        )
    assert excinfo.value.code == engine_adapter.ComfyEngineRefusalCode.FOREIGN_IDENTITY_REFUSED
    assert server.submit_calls == 1, "a foreign identity may never inherit a live prompt"


def test_mf18_4_independent_attempts_post_once_each(dependency: Any, tmp_path: Path) -> None:
    """CONTROL (mirrors R27-8): two genuinely different attempts still POST twice."""
    graph = light_graph()
    server = FakeComfyServer()
    first_png = png_bytes(color=(200, 10, 10))
    second_png = png_bytes(color=(10, 200, 10))
    server.view_items[("", "first.png")] = first_png
    server.view_items[("", "second.png")] = second_png
    server.history_map["pid-1"] = history_success("pid-1", "first.png")
    server.history_map["pid-2"] = history_success("pid-2", "second.png")
    engine, _ = make_engine(tmp_path, server)
    pin = graph_pin_hash(graph)

    record_a = engine.run_shot(
        make_binding(attempt_id="att-1", workflow_hash=pin),
        graph=graph, terminal_outputs=TERMINAL_OUTPUTS,
    )
    record_b = engine.run_shot(
        make_binding(attempt_id="att-2", workflow_hash=pin),
        graph=graph, terminal_outputs=TERMINAL_OUTPUTS,
    )

    assert server.submit_calls == 2, "independent attempts must not be over-locked"
    assert record_a.output is not None and record_b.output is not None
    assert record_a.output.prompt_id == "pid-1"
    assert record_b.output.prompt_id == "pid-2"
    assert record_a.output.artifacts[0].sha256 == hashlib.sha256(first_png).hexdigest()
    assert record_b.output.artifacts[0].sha256 == hashlib.sha256(second_png).hexdigest()
    receipts = read_receipts(tmp_path)
    assert sorted(r["attempt_id"] for r in receipts) == ["att-1", "att-2"]
    assert all(r["outcome"] == "terminal_success" for r in receipts)


def test_mf18_4_cancel_is_lease_gated(dependency: Any, tmp_path: Path) -> None:
    server = FakeComfyServer()
    engine, _ = make_engine(tmp_path, server)
    with pytest.raises(engine_adapter.ComfyEngineRefusal) as excinfo:
        engine.cancel("pid-404")
    assert excinfo.value.engine_code == "MF_COMFY_LEASE_NOT_HELD"
    assert excinfo.value.code == engine_adapter.ComfyEngineRefusalCode.ENGINE_REFUSED
    assert server.interrupt_calls == [], "no HTTP call without the lease"


def test_mf18_4_cancel_releases_a_queued_attempt(dependency: Any, tmp_path: Path) -> None:
    graph = light_graph()
    server = FakeComfyServer()
    server.queue_state["queue_running"] = [queue_item("pid-1")]
    server.interrupt_history = history_error("pid-1", "execution_interrupted")
    engine, _ = make_engine(tmp_path, server, stage_timeout_s=1.0)
    binding = make_binding(workflow_hash=graph_pin_hash(graph))
    with pytest.raises(engine_adapter.ComfyEngineRefusal) as excinfo:
        engine.run_shot(binding, graph=graph, terminal_outputs=TERMINAL_OUTPUTS)
    assert excinfo.value.code == engine_adapter.ComfyEngineRefusalCode.AMBIGUOUS_AFTER_SUBMIT

    result = engine.cancel("pid-1")
    assert server.interrupt_calls == ["pid-1"]
    assert result["terminal_proven"] is True
    assert result["reservation_released"] is True
    receipts = read_receipts(tmp_path)
    assert len(receipts) == 1
    assert receipts[0]["outcome"] == "cancelled"
    assert engine._gate.held is False


def test_mf18_4_oom_is_a_failed_record_with_durable_terminal_error(
    dependency: Any, tmp_path: Path
) -> None:
    graph = light_graph()
    server = FakeComfyServer()
    server.history_map["pid-1"] = history_error(
        "pid-1", "CUDA out of memory. Tried to allocate 2.00 GiB"
    )
    engine, _ = make_engine(tmp_path, server)
    binding = make_binding(workflow_hash=graph_pin_hash(graph))

    record = engine.run_shot(binding, graph=graph, terminal_outputs=TERMINAL_OUTPUTS)
    assert record.outcome == "failed"
    assert record.output is None
    assert record.error is not None
    assert record.error.code == "MF_COMFY_OOM"
    assert record.error.retryable is False
    assert server.submit_calls == 1
    receipts = read_receipts(tmp_path)
    assert len(receipts) == 1
    assert receipts[0]["outcome"] == "terminal_error"
    assert engine._gate.held is False


# ── static / packaging ───────────────────────────────────────────────────────


def test_mf18_2_adapter_source_has_no_worktree_paths_or_sys_path() -> None:
    text = (PROJECT_ROOT / "app" / "adapters" / "media_engine" / "comfy.py").read_text(
        encoding="utf-8"
    )
    # Skip the module docstring: it NAMES the things the code never does.
    body = text.split('"""', 2)[2] if text.startswith('"""') else text
    assert "sys.path" not in body
    assert "wt-comfy" not in body
    assert "mfv1" not in body
    assert PIN in text


def test_mf18_3_runtime_did_not_mutate_sys_path(dependency: Any, tmp_path: Path) -> None:
    polluted = [p for p in sys.path if "wt-comfy" in p or "experiments" in p]
    assert polluted == []
    assert dependency.mf.__file__ is not None
    assert str(dependency.site) in str(Path(dependency.mf.__file__).resolve())


def test_mf18_2_pyproject_patch_is_bounded() -> None:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["optional-dependencies"]["comfy"] == ["mf-comfy==0.1.0"]
    assert data["project"]["entry-points"]["motionforge.media_engine"] == {
        "comfy_shot_engine": "app.adapters.media_engine.comfy:ComfyShotEngine",
    }
    base = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "show", f"{BASE_COMMIT}:pyproject.toml"],
        capture_output=True, text=True,
    )
    assert base.returncode == 0, base.stderr
    base_data = tomllib.loads(base.stdout)
    # bounded: nothing else in the file changed vs the frozen wave base
    assert data["build-system"] == base_data["build-system"]
    assert data["project"]["version"] == base_data["project"]["version"]
    assert data["project"]["dependencies"] == base_data["project"]["dependencies"]
    assert data["project"]["name"] == base_data["project"]["name"]
    assert data["project"]["requires-python"] == base_data["project"]["requires-python"]
    base_extras = base_data["project"]["optional-dependencies"]
    assert set(base_extras) | {"comfy"} == set(data["project"]["optional-dependencies"])
    for name, value in base_extras.items():
        assert data["project"]["optional-dependencies"][name] == value, name
    assert base_data["project"].get("entry-points", {}) == {}
    assert data["tool"]["ruff"] == base_data["tool"]["ruff"]
    assert data["tool"]["pytest"]["ini_options"] == base_data["tool"]["pytest"]["ini_options"]
