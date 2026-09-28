"""MF-END-09 rows — reference-asset generation job (graph G1 → managed library).

Row families:

* ``micro_*``      — pure functions: content key view-scoping, staged input
  managed+content-addressed, graph overrides pinned to the parameter table,
  manifest/plan validations (no engine, no DB).
* ``acceptance_*`` — the REAL path: API submit registers an intent (zero
  engine POSTs), the durable worker claims it, ONE engine submit produces the
  bytes, the MF-END-03 managed ingest saves them into the DRAFT pack, a
  terminal receipt makes a retry a 0-POST replay, and the frozen manifest
  then publishes (proving the generated asset satisfies validation).
* ``negative_*``   — published version immutability (route + handler), a
  missing/changed source reference, an in-doubt receipt (never a blind second
  POST), and provider unavailable with NO fixture fallback.

The ComfyUI process boundary is the HTTP transport: rows build the pinned
``mf_comfy`` wheel from source (MF-END-18 build script) and drive a fake
server at exactly that boundary — no GPU, no ComfyUI server.  These are CI
fixtures; they are never product-demo evidence.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.characters import CharacterRepository
from app.persistence.models import CharacterPackVersion
from app.workflow import reference_asset_jobs as raj
from app.workflow.durable_worker import build_worker_context

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_mf_comfy_dependency.py"
DEFAULT_SOURCE_REPO = "C:/Users/Admin/Documents/Codex/work/mfv1/wt-comfy"
SOURCE_REPO = Path(os.environ.get("MF_END09_SOURCE_REPO", DEFAULT_SOURCE_REPO))

SYMBOL = "reference_pack_v1"
FRONT = "front@character"
BACK = "back@character"
SIDE = "side@character"
CAPABILITY = "image_edit_multi_reference"
BACK_PROMPT = (
    "Render the BACK view of the same character: keep the outfit, colours, proportions and "
    "style exactly; no new objects and no watermark."
)
SIDE_PROMPT = (
    "Render the SIDE view of the same character: keep the outfit, colours, proportions and "
    "style exactly; no new objects and no watermark."
)


# ── harness helpers ──────────────────────────────────────────────────────────


def _session():
    service = deps._job_service
    assert service is not None
    return service.session_factory()


def _managed_root() -> Path:
    service = deps._job_service
    assert service is not None
    return Path(service.managed_root)


def _service():
    service = deps._job_service
    assert service is not None
    return service


def _png(mode: str = "RGBA", size: tuple[int, int] = (1024, 1024), color=(120, 60, 200, 200)):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return buf.getvalue()


def _requirement(key: str, alpha: bool) -> dict:
    return {"key": key, "alpha": alpha}


def _manifest(requirements, capabilities=(CAPABILITY,)) -> dict:
    return {
        "manifest_version": 1,
        "pack_contract": SYMBOL,
        "requirements": list(requirements),
        "capabilities": list(capabilities),
    }


def _declare(ver_id: str, manifest: dict) -> None:
    with _session() as session:
        repo = CharacterRepository(session)
        repo.declare_reference_manifest(ver_id, DEFAULT_WORKSPACE_ID, manifest)
        session.commit()


def _version_row(ver_id: str) -> dict[str, Any]:
    with _session() as session:
        row = session.get(CharacterPackVersion, ver_id)
        assert row is not None
        return {
            "id": row.id,
            "status": row.status,
            "revision": row.revision,
            "pack_contract_version": row.pack_contract_version,
        }


def _assets(ver_id: str) -> dict[str, dict[str, Any]]:
    from app.persistence.models import Artifact

    with _session() as session:
        row = session.get(CharacterPackVersion, ver_id)
        assert row is not None
        out: dict[str, dict[str, Any]] = {}
        for a in row.assets:
            artifact = session.get(Artifact, str(a.artifact_id))
            out[str(a.pose_slot)] = {
                "asset_id": str(a.id),
                "artifact_id": str(a.artifact_id),
                "sha256": str(getattr(artifact, "sha256", "") or ""),
                "size_bytes": int(getattr(artifact, "size_bytes", 0) or 0),
                "state": str(getattr(artifact, "state", "") or ""),
                "relative_path": str(getattr(artifact, "relative_path", "") or ""),
            }
        return out


def _create_character(client: TestClient, code: str) -> str:
    resp = client.post("/api/v2/characters", json={"name": f"Ref {code}", "code": code})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_version(client: TestClient, char_id: str) -> dict:
    resp = client.post(f"/api/v2/characters/{char_id}/versions")
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload(client: TestClient, ver_id: str, data: bytes, key: str = FRONT) -> dict:
    resp = client.post(
        f"/api/v2/characters/versions/{ver_id}/reference-artwork",
        data={"reference_key": key},
        files={"file": (f"{key.split('@')[0]}.png", data, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _submit(client: TestClient, ver_id: str, *, key: str, prompt: str, **extra: Any):
    payload = {"reference_key": key, "view_prompt": prompt, "seed": 2026092801}
    payload.update(extra)
    return client.post(f"/api/v2/characters/versions/{ver_id}/reference-asset-jobs", json=payload)


def _job_state(job_id: str) -> str:
    info = _service().get_job(job_id)
    assert info is not None
    return str(getattr(info.state, "value", info.state))


def _run_to_terminal(job_id: str, *, timeout: float = 60.0):
    """Start the durable worker and wait for *job_id* to reach a terminal state."""
    service = _service()
    service.start_worker()
    deadline = time.time() + timeout
    info = service.get_job(job_id)
    while time.time() < deadline:
        info = service.get_job(job_id)
        assert info is not None
        if str(getattr(info.state, "value", info.state)) in {
            "completed",
            "failed",
            "cancelled",
            "fenced",
        }:
            return info
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not reach a terminal state: {info}")


# ── mf_comfy dependency (the pinned wheel, built from source) ────────────────


@pytest.fixture(scope="module")
def dependency() -> Any:
    if not SOURCE_REPO.is_dir():
        pytest.skip(f"pinned source repo {SOURCE_REPO} is absent on this machine")
    root = Path(str(os.environ.get("TMP", "/tmp"))) / f"mf19_dep_{os.getpid()}"
    build_dir = root / "build"
    site = root / "site"
    proc = subprocess.run(
        [
            sys.executable,
            str(BUILD_SCRIPT),
            "--source-repo",
            str(SOURCE_REPO),
            "--out",
            str(build_dir),
            "--install-target",
            str(site),
            "--built-at",
            "2026-09-28T00:00:00Z",
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
    yield SimpleNamespace(root=root, build_dir=build_dir, site=site, summary=summary, mf=module)
    # Pop the WHOLE mf_comfy module tree: leaving ``mf_comfy.pinning`` behind
    # makes the NEXT module's fixture re-import a stale path (MF-END-18's rows
    # then resolve the wrong install target).
    for name in [n for n in list(sys.modules) if n == "mf_comfy" or n.startswith("mf_comfy.")]:
        sys.modules.pop(name, None)
    with contextlib.suppress(ValueError):
        sys.path.remove(str(site))
    importlib.invalidate_caches()


# ── fake ComfyUI server (process boundary: the HTTP transport surface) ───────


class FakeClock:
    def __init__(self, step: float = 0.25) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float | None = None) -> None:
        self.t += self.step if dt is None else float(dt)


def object_info_from_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Expose exactly the classes/inputs the frozen graph uses.

    String inputs are declared as plain ``STRING`` (no enum) so the fake server
    accepts the job's parameter overrides (prompt/filename/prefix) without
    pretending to be a model inventory — the real inventory check is exercised
    by MF-END-18's rows, not here.
    """
    by_class: dict[str, dict[str, Any]] = {}
    for node in graph.values():
        cls = node["class_type"]
        spec = by_class.setdefault(
            cls,
            {
                "input": {"required": {}},
                "output": [],
                "output_node": cls == "SaveImage",
                "python_module": "nodes",
            },
        )
        for name, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                continue
            if isinstance(value, bool):
                spec["input"]["required"][name] = ["BOOLEAN", {}]
            elif isinstance(value, int):
                spec["input"]["required"][name] = ["INT", {}]
            elif isinstance(value, float):
                spec["input"]["required"][name] = ["FLOAT", {}]
            else:
                spec["input"]["required"][name] = ["STRING", {}]
    return by_class


class FakeComfyServer:
    """Same surface as the package's HttpTransport (MF-END-18 rows)."""

    def __init__(self, object_info: dict[str, Any]) -> None:
        self.oi = object_info
        self.submit_calls = 0
        self.submitted_graphs: list[dict] = []
        self.history_map: dict[str, dict] = {}
        self.interrupt_calls: list[str] = []
        self.view_payload = _png("RGB", (1024, 1024), (90, 60, 30))
        self.closed = False
        self.on_submit: Any | None = None

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
            "base_url": "http://127.0.0.1:8199",
            "loopback_only": True,
            "comfyui_version": "fake-9.9",
            "device_name": "fake-gpu",
            "device_total_vram_mib": 12227,
            "node_class_count": len(oi or {}),
            "interrupt_payload": "json",
            "history_direct_endpoint": True,
        }

    def submit(self, graph: dict, client_id: str) -> Any:
        from mf_comfy.transport import SubmitResult

        self.submit_calls += 1
        self.submitted_graphs.append(graph)
        prompt_id = f"pid-{self.submit_calls}"
        prefix = str(graph.get("SAVE", {}).get("inputs", {}).get("filename_prefix") or "out")
        filename = f"{prefix.split('/')[-1]}_00001_.png"
        self.history_map[prompt_id] = {
            "prompt": [0, prompt_id, {}, {}, []],
            "outputs": {"SAVE": {"images": [{"filename": filename, "subfolder": "",
                                             "type": "output"}]}},
            "status": {"status_str": "success", "completed": True, "messages": []},
        }
        if self.on_submit is not None:
            self.on_submit(client_id)
        return SubmitResult(prompt_id=prompt_id, number=self.submit_calls)

    def history(self, prompt_id: str = "") -> dict[str, Any]:
        if not prompt_id:
            return dict(self.history_map)
        entry = self.history_map.get(prompt_id)
        return {prompt_id: entry} if entry else {}

    def queue(self) -> dict[str, Any]:
        return {"queue_running": [], "queue_pending": []}

    def interrupt(self, prompt_id: str) -> dict[str, Any]:
        self.interrupt_calls.append(prompt_id)
        return {"ok": True}

    def fetch_view(self, item: dict) -> bytes:
        return self.view_payload

    def drain_events(self, client_id: str, timeout_s: float) -> list[dict]:
        return []

    def close(self) -> None:
        self.closed = True


def make_engine_factory(server: FakeComfyServer, clock: FakeClock):
    """Factory injected at ``raj._ENGINE_FACTORY`` (the documented test seam)."""

    def factory(managed_root: Path) -> Any:
        from app.adapters.media_engine.comfy import ComfyShotEngine

        state = Path(managed_root) / "media_engine" / "comfy_shot_engine"
        state.mkdir(parents=True, exist_ok=True)
        epoch_path = state / "instance_epoch.json"
        if not epoch_path.exists():
            epoch_path.write_text(
                json.dumps(
                    {
                        "instance_id": "end09testepoch",
                        "launched_at": 0.0,
                        "pid": os.getpid(),
                        "host": "test-host",
                        "base_url": "http://127.0.0.1:8199",
                        "comfyui_version": "fake-9.9",
                    }
                ),
                encoding="utf-8",
            )
        return ComfyShotEngine(
            managed_root=managed_root,
            base_url="http://127.0.0.1:8199",
            owner="motionforge.reference_asset_jobs",
            transport=server,
            clock=clock,
            sleep=clock.advance,
            stage_timeout_s=2.0,
            poll_s=0.5,
        )

    return factory


def _frozen_graph() -> dict[str, Any]:
    document, _manifest = raj.load_graph_documents()
    return document["graph"]


@pytest.fixture()
def engine_bound(monkeypatch: pytest.MonkeyPatch) -> FakeComfyServer:
    """A fake Comfy server wired into the job engine seam (same process)."""
    server = FakeComfyServer(object_info_from_graph(_frozen_graph()))
    clock = FakeClock()
    monkeypatch.setattr(raj, "_ENGINE_FACTORY", make_engine_factory(server, clock))
    return server


def _setup_pack(client: TestClient, *, code: str = "end09") -> tuple[str, str, dict]:
    """Character + draft reference version (front+side authored, back missing).

    Two INDEPENDENT authored references are required by the pinned capability
    minima (``image_edit_multi_reference`` -> >=2 distinct shas), so the pack is
    built the way a real reference pack starts.
    """
    char_id = _create_character(client, code)
    version = _create_version(client, char_id)
    ver_id = version["id"]
    _declare(
        ver_id,
        _manifest(
            [
                _requirement(FRONT, True),
                _requirement(SIDE, True),
                _requirement(BACK, False),
            ]
        ),
    )
    uploaded = _upload(client, ver_id, _png("RGBA", (1024, 1024), (120, 60, 200, 200)))
    _upload(client, ver_id, _png("RGBA", (1024, 1024), (30, 200, 60, 200)), key=SIDE)
    return char_id, ver_id, uploaded


def _receipt(ver_id: str, key: str = BACK, prompt: str = BACK_PROMPT) -> tuple[dict, str]:
    """Recompute the plan/receipt path for a (version, key) pair."""
    assets = _assets(ver_id)
    source = assets[raj.DEFAULT_SOURCE_REFERENCE_KEY]
    graph_manifest = raj.load_graph_documents()[1]
    manifest = raj._build_manifest(
        workspace_id=DEFAULT_WORKSPACE_ID,
        character_id=_char_of(ver_id),
        version_id=ver_id,
        reference_key=key,
        view_prompt=prompt,
        source_reference_key=raj.DEFAULT_SOURCE_REFERENCE_KEY,
        source_artifact_id=source["asset_id"],
        source_sha256=source["sha256"],
        source_size_bytes=source["size_bytes"],
        style_version=None,
        seed=2026092801,
        graph_file_sha256=str(graph_manifest["workflow"]["graph_file_sha256"]),
    )
    plan = raj.reference_asset_plan(manifest)
    manifest["content_key"] = plan.content_key
    return manifest, plan.content_key


def _char_of(ver_id: str) -> str:
    with _session() as session:
        row = session.get(CharacterPackVersion, ver_id)
        assert row is not None
        return str(row.character_id)


def _worker_ctx(manifest: dict[str, Any]):
    manifest = dict(manifest)
    manifest["managed_root"] = str(_managed_root())
    return build_worker_context(
        job_id="direct-end09",
        job_type=raj.JOB_TYPE_REFERENCE_ASSET,
        step_code="reference_asset",
        step_id="direct-end09-step",
        workspace_id=DEFAULT_WORKSPACE_ID,
        owner_type="character",
        owner_id=str(manifest["character_id"]),
        input_manifest=manifest,
        attempt=1,
        checkpoint={"schema_version": 1},
        worker_id="end09-direct",
        fence_token="direct",
        ttl_seconds=60,
        progress=lambda *args, **kwargs: None,
        write_checkpoint=lambda *args, **kwargs: None,
        is_cancelled=lambda: False,
        staging_dir=lambda: _managed_root(),
        session_factory=_service().session_factory,
    )


# ── micro rows ───────────────────────────────────────────────────────────────


def test_micro_content_key_is_view_scoped_and_deterministic() -> None:
    base = {
        "schema": raj.RECEIPT_SCHEMA,
        "workspace_id": "ws",
        "character_id": "c",
        "version_id": "v",
        "reference_key": BACK,
        "source_reference_key": FRONT,
        "source_sha256": "a" * 64,
        "style_version": None,
        "graph_file_sha256": "b" * 64,
        "graph_config_hash": "c",
        "view_prompt_sha256": "d" * 64,
    }
    key = raj.reference_asset_content_key(base)
    assert raj.reference_asset_content_key(dict(base)) == key
    changed_view = dict(base, reference_key=SIDE)
    changed_seed = dict(base, graph_config_hash="e")
    changed_source = dict(base, source_sha256="f" * 64)
    assert len({key, raj.reference_asset_content_key(changed_view),
                raj.reference_asset_content_key(changed_seed),
                raj.reference_asset_content_key(changed_source)}) == 4


def test_micro_staged_input_is_managed_and_content_addressed(tmp_path: Path) -> None:
    document, _manifest = raj.load_graph_documents()
    manifest = {
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "character_id": "c",
        "version_id": "v",
        "reference_key": BACK,
        "source_reference_key": FRONT,
        "source_artifact_id": "art-1",
        "source_sha256": "0" * 64,
        "source_size_bytes": 1,
        "view_prompt": BACK_PROMPT,
        "seed": 7,
    }
    plan = raj.reference_asset_plan(manifest)
    data = b"payload"
    plan = type(plan)(
        **{
            **plan.__dict__,
            "source_sha256": raj._sha256_bytes(data),
            "source_size_bytes": len(data),
        }
    )
    first = raj.stage_reference_input(tmp_path, plan, data)
    second = raj.stage_reference_input(tmp_path, plan, data)
    assert first == second
    assert first.read_bytes() == data
    assert first.parent == raj.runtime_input_dir(tmp_path)
    assert raj._sha256_bytes(data)[:16] in first.name
    with pytest.raises(raj.ReferenceAssetJobError) as excinfo:
        raj.stage_reference_input(tmp_path, plan, b"other")
    assert excinfo.value.code is raj.ReferenceAssetRefusalCode.SOURCE_HASH_MISMATCH
    assert document["graph"]["REF_LOAD"]["inputs"]["image"] != first.name


def test_micro_graph_overrides_follow_the_pinned_parameter_table() -> None:
    template = _frozen_graph()
    graph = raj.build_reference_asset_graph(
        template,
        ref_filename="end09_ref_abc.png",
        prompt=BACK_PROMPT,
        seed=11,
        filename_prefix="mf_reference_asset_v1/back_character",
    )
    assert graph["REF_LOAD"]["inputs"]["image"] == "end09_ref_abc.png"
    assert graph["PROMPT"]["inputs"]["text"] == BACK_PROMPT
    assert graph["NOISE"]["inputs"]["noise_seed"] == 11
    assert graph["LATENT"]["inputs"]["width"] == raj.CANVAS_WIDTH
    assert graph["SAVE"]["inputs"]["filename_prefix"] == "mf_reference_asset_v1/back_character"
    assert graph["REF_BG"]["inputs"]["color"] == raj.NEUTRAL_RGB_INT
    assert graph["REF_RESIZE"]["inputs"]["resize_type.longer_size"] == raj.REF_LONGER_SIDE
    assert graph["GUIDER"]["inputs"]["cfg"] == raj.CFG
    assert graph["SIGMAS"]["inputs"]["steps"] == raj.STEPS
    # the frozen template itself is untouched (deep copy)
    assert template["REF_LOAD"]["inputs"]["image"] == "ra_v1_ref_dan_choi.png"
    with pytest.raises(raj.ReferenceAssetJobError) as bad_canvas:
        raj.build_reference_asset_graph(
            template,
            ref_filename="x.png",
            prompt=BACK_PROMPT,
            seed=1,
            filename_prefix="p",
            canvas_width=1000,
        )
    assert bad_canvas.value.code is raj.ReferenceAssetRefusalCode.REQUEST_INVALID
    with pytest.raises(raj.ReferenceAssetJobError) as bad_name:
        raj.build_reference_asset_graph(
            template, ref_filename="../x.png", prompt=BACK_PROMPT, seed=1, filename_prefix="p"
        )
    assert bad_name.value.code is raj.ReferenceAssetRefusalCode.REQUEST_INVALID


def test_micro_plan_refusals_are_typed() -> None:
    document, manifest_doc = raj.load_graph_documents()
    base = {
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "character_id": "c",
        "version_id": "v",
        "reference_key": BACK,
        "source_reference_key": FRONT,
        "source_artifact_id": "art-1",
        "source_sha256": "a" * 64,
        "source_size_bytes": 10,
        "view_prompt": BACK_PROMPT,
        "seed": 5,
    }
    plan = raj.reference_asset_plan(base)
    assert plan.content_key.startswith("sha256:")
    assert plan.view == "back" and plan.role == "character"
    with pytest.raises(raj.ReferenceAssetJobError) as missing:
        raj.reference_asset_plan({k: v for k, v in base.items() if k != "source_sha256"})
    assert missing.value.code is raj.ReferenceAssetRefusalCode.REQUEST_INVALID
    with pytest.raises(raj.ReferenceAssetJobError) as no_view:
        raj.reference_asset_plan(dict(base, view_prompt="Render the character nicely, please."))
    assert no_view.value.code is raj.ReferenceAssetRefusalCode.VIEW_PROMPT_REFUSED
    with pytest.raises(raj.ReferenceAssetJobError) as wrong_key:
        raj.reference_asset_plan(dict(base, content_key="sha256:" + "0" * 64))
    assert wrong_key.value.code is raj.ReferenceAssetRefusalCode.CONTENT_KEY_MISMATCH
    with pytest.raises(raj.ReferenceAssetJobError) as same:
        raj.reference_asset_plan(dict(base, source_reference_key=BACK))
    assert same.value.code is raj.ReferenceAssetRefusalCode.REQUEST_INVALID
    assert manifest_doc["workflow"]["graph_file_sha256"]


# ── acceptance rows ──────────────────────────────────────────────────────────


def test_acceptance_submit_intent_then_worker_generates_and_saves(
    client: TestClient, engine_bound: FakeComfyServer, dependency: Any
) -> None:
    assert dependency.mf is not None
    _char_id, ver_id, uploaded = _setup_pack(client)
    assert engine_bound.submit_calls == 0

    resp = _submit(client, ver_id, key=BACK, prompt=BACK_PROMPT)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["duplicate"] is False
    assert body["view"] == "back" and body["role"] == "character"
    content_key = body["content_key"]
    job_id = body["job"]["job_id"]
    # the submit only registered an intent: no engine POST, no library write
    assert engine_bound.submit_calls == 0
    assert _job_state(job_id) in {"pending", "queued"}
    assert BACK not in _assets(ver_id)

    # a duplicate submit of the same identity returns the SAME durable job
    again = _submit(client, ver_id, key=BACK, prompt=BACK_PROMPT)
    assert again.status_code == 202, again.text
    assert again.json()["duplicate"] is True
    assert again.json()["job"]["job_id"] == job_id
    assert engine_bound.submit_calls == 0

    info = _run_to_terminal(job_id)
    assert str(info.state.value) == "completed", info
    assert engine_bound.submit_calls == 1

    graph = engine_bound.submitted_graphs[0]
    staged_name = graph["REF_LOAD"]["inputs"]["image"]
    staged = raj.runtime_input_dir(_managed_root()) / staged_name
    assert staged.is_file()
    assert raj._sha256_bytes(staged.read_bytes()) == raj._sha256_bytes(uploaded_png(uploaded))

    assets = _assets(ver_id)
    assert BACK in assets and FRONT in assets
    assert assets[FRONT]["asset_id"] == uploaded["asset_id"]
    assert assets[FRONT]["sha256"] == uploaded["sha256"]
    assert assets[BACK]["state"] == "ready"
    assert assets[BACK]["sha256"] == raj._sha256_bytes(engine_bound.view_payload)
    assert assets[BACK]["asset_id"] != assets[FRONT]["asset_id"]

    with _session() as session:
        repo = CharacterRepository(session, storage_root=_managed_root())
        _asset, path, _mime = repo.resolve_asset_content(
            character_id=_char_id,
            version_id=ver_id,
            asset_id=assets[BACK]["asset_id"],
            workspace_id=DEFAULT_WORKSPACE_ID,
        )
        assert Path(path).read_bytes() == engine_bound.view_payload

    receipt = raj.read_receipt(_managed_root(), content_key)
    assert receipt is not None
    assert receipt["status"] == raj.RECEIPT_COMPLETED
    assert receipt["engine"]["prompt_id"] == "pid-1"
    assert receipt["asset"]["asset_id"] == assets[BACK]["asset_id"]
    assert receipt["graph_config_hash"]
    assert receipt["graph_file_sha256"] == raj.load_graph_documents()[1]["workflow"][
        "graph_file_sha256"
    ]
    # the pack is still a draft: nothing was published by the job
    assert _version_row(ver_id)["status"] == "draft"


def uploaded_png(uploaded: dict) -> bytes:
    """The staged identity bytes == the uploaded authored artwork bytes."""
    with _session() as session:
        row = session.get(CharacterPackVersion, uploaded["version_id"])
        assert row is not None
        asset = next(a for a in row.assets if str(a.id) == uploaded["asset_id"])
        from app.persistence.models import Artifact

        artifact = session.get(Artifact, str(asset.artifact_id))
        assert artifact is not None
        return (_managed_root() / str(artifact.relative_path)).read_bytes()


def test_acceptance_missing_view_only_generates_that_view(
    client: TestClient, engine_bound: FakeComfyServer, dependency: Any
) -> None:
    assert dependency.mf is not None
    _char_id, ver_id, uploaded = _setup_pack(client, code="end09b")
    assert _submit(client, ver_id, key=BACK, prompt=BACK_PROMPT).status_code == 202
    back_job = _submit(client, ver_id, key=BACK, prompt=BACK_PROMPT).json()["job"]["job_id"]
    _run_to_terminal(back_job)
    assert engine_bound.submit_calls == 1
    before = _assets(ver_id)
    assert BACK in before and FRONT in before

    # a submitted view that already exists is refused (no second generation)
    present = _submit(client, ver_id, key=BACK, prompt=BACK_PROMPT)
    assert present.status_code == 409, present.text
    assert present.json()["detail"]["code"] == "mf_end09_target_key_present"
    assert engine_bound.submit_calls == 1

    # exactly ONE asset was added, exactly one POST, and nobody else was touched
    after = _assets(ver_id)
    assert set(after) == {FRONT, SIDE, BACK}
    assert after[FRONT] == before[FRONT]
    assert after[SIDE] == before[SIDE]
    assert after[BACK]["sha256"] == raj._sha256_bytes(engine_bound.view_payload)
    assert engine_bound.submitted_graphs[0]["PROMPT"]["inputs"]["text"] == BACK_PROMPT
    assert engine_bound.submitted_graphs[0]["REF_LOAD"]["inputs"]["image"].startswith(
        "end09_ref_"
    )


def test_acceptance_retry_replays_zero_post_and_manifest_publishes(
    client: TestClient, engine_bound: FakeComfyServer, dependency: Any
) -> None:
    assert dependency.mf is not None
    _char_id, ver_id, uploaded = _setup_pack(client, code="end09c")
    first = _submit(client, ver_id, key=BACK, prompt=BACK_PROMPT)
    assert first.status_code == 202
    content_key = first.json()["content_key"]
    job_id = first.json()["job"]["job_id"]
    info = _run_to_terminal(job_id)
    assert str(info.state.value) == "completed"
    assert engine_bound.submit_calls == 1
    assets_before = _assets(ver_id)

    retry = client.post(
        f"/api/v2/characters/reference-asset-jobs/{job_id}/retry",
        json={"input_generation": "retry-1"},
    )
    assert retry.status_code == 202, retry.text
    retry_job = retry.json()["job"]["job_id"]
    assert retry_job != job_id
    assert retry.json()["content_key"] == content_key
    info = _run_to_terminal(retry_job)
    assert str(info.state.value) == "completed", info
    # the terminal receipt was replayed: ZERO extra engine submits, same asset
    assert engine_bound.submit_calls == 1
    assets_after = _assets(ver_id)
    assert assets_after[BACK] == assets_before[BACK]
    assert assets_after[FRONT] == assets_before[FRONT]
    receipt = raj.read_receipt(_managed_root(), content_key)
    assert receipt is not None
    assert int(receipt["replay"]["count"]) == 1
    assert receipt["engine"]["artifact_sha256"] == assets_after[BACK]["sha256"]

    # the generated asset satisfies the FROZEN manifest: the pack now publishes
    revision = _version_row(ver_id)["revision"]
    published = client.post(
        f"/api/v2/characters/versions/{ver_id}/publish", json={"revision": revision}
    )
    assert published.status_code == 200, published.json()
    assert published.json()["status"] == "published"
    snapshot = json.loads(published.json()["validation_json"])
    assert snapshot["required_keys"] == [FRONT, SIDE, BACK]
    assert snapshot["pack_contract_version"] == SYMBOL


# ── negative rows ────────────────────────────────────────────────────────────


def test_negative_published_version_is_immutable(
    client: TestClient, engine_bound: FakeComfyServer, dependency: Any
) -> None:
    assert dependency.mf is not None
    _char_id, ver_id, _uploaded = _setup_pack(client, code="end09d")
    intent = _submit(client, ver_id, key=BACK, prompt=BACK_PROMPT)
    assert intent.status_code == 202
    _run_to_terminal(intent.json()["job"]["job_id"])
    assert engine_bound.submit_calls == 1
    revision = _version_row(ver_id)["revision"]
    publish_resp = client.post(
        f"/api/v2/characters/versions/{ver_id}/publish", json={"revision": revision}
    )
    assert publish_resp.status_code == 200, publish_resp.json()
    assert _version_row(ver_id)["status"] == "published"
    calls_before = engine_bound.submit_calls

    refused = _submit(client, ver_id, key=BACK, prompt=BACK_PROMPT)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "mf_end09_version_not_draft"

    # a stale draft intent (registered before publication) refuses typed too
    manifest, content_key = _receipt(
        ver_id,
        key="walking@character",
        prompt="Render the WALKING view of the same character: keep the outfit, colours, "
        "proportions and style exactly.",
    )
    with pytest.raises(raj.ReferenceAssetJobError) as excinfo:
        raj.run_reference_asset_job(_worker_ctx(manifest))
    assert excinfo.value.code is raj.ReferenceAssetRefusalCode.VERSION_NOT_DRAFT
    assert engine_bound.submit_calls == calls_before
    assert set(_assets(ver_id)) == {FRONT, SIDE, BACK}
    assert raj.read_receipt(_managed_root(), content_key) is None


def test_negative_source_reference_missing_or_changed_refuses_before_post(
    client: TestClient, engine_bound: FakeComfyServer, dependency: Any
) -> None:
    assert dependency.mf is not None
    _char_id, ver_id, _uploaded = _setup_pack(client, code="end09e")
    absent = _submit(
        client, ver_id, key=BACK, prompt=BACK_PROMPT, source_reference_key="top@character"
    )
    assert absent.status_code == 422, absent.text
    assert absent.json()["detail"]["code"] == "mf_end09_source_reference_missing"
    assert engine_bound.submit_calls == 0

    manifest, _content_key = _receipt(ver_id, key=BACK, prompt=BACK_PROMPT)
    manifest["source_sha256"] = "0" * 64  # stale identity bytes
    with pytest.raises(raj.ReferenceAssetJobError) as excinfo:
        raj.run_reference_asset_job(_worker_ctx(manifest))
    assert excinfo.value.code is raj.ReferenceAssetRefusalCode.CONTENT_KEY_MISMATCH
    assert engine_bound.submit_calls == 0


def test_negative_receipt_recovery_never_duplicates_generation(
    client: TestClient, engine_bound: FakeComfyServer, dependency: Any
) -> None:
    """A crash-recovered receipt never yields a duplicate generation.

    Phase 1 — the receipt says ``submitted`` but the engine's durable ledger has
    no record for the recorded identity: exactly ONE first POST happens (a
    duplicate of nothing).  Phase 2 — the receipt is crashed back to
    non-terminal AFTER the engine attempt went terminal: the replay reuses the
    durable evidence with ZERO new POSTs and the same asset.
    """
    assert dependency.mf is not None
    _char_id, ver_id, _uploaded = _setup_pack(client, code="end09f")
    manifest, content_key = _receipt(ver_id, key=BACK, prompt=BACK_PROMPT)
    plan = raj.reference_asset_plan(manifest)
    receipt_file = raj.receipt_path(_managed_root(), content_key)
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    receipt_file.write_text(
        json.dumps(
            {
                "schema": raj.RECEIPT_SCHEMA,
                "content_key": content_key,
                "status": raj.RECEIPT_SUBMITTED,
                "attempt_id": "end09-crash-1",
                "job_id": "crash-job",
                "attempt": 1,
                "version_id": ver_id,
                "character_id": manifest["character_id"],
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "reference_key": BACK,
                "graph_config_hash": plan.graph_config_hash,
                "engine": {},
                "asset": {},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    first = raj.run_reference_asset_job(_worker_ctx(manifest))
    assert engine_bound.submit_calls == 1
    assert first["asset_id"] == _assets(ver_id)[BACK]["asset_id"]
    receipt = raj.read_receipt(_managed_root(), content_key)
    assert receipt is not None and receipt["status"] == raj.RECEIPT_COMPLETED

    crashed = dict(receipt)
    crashed["status"] = raj.RECEIPT_SUBMITTED
    receipt_file.write_text(json.dumps(crashed, sort_keys=True) + "\n", encoding="utf-8")
    replay = raj.run_reference_asset_job(_worker_ctx(manifest))
    assert engine_bound.submit_calls == 1  # the attempt is terminal on disk: no second POST
    assert replay["asset_id"] == first["asset_id"]
    assert _assets(ver_id)[BACK]["sha256"] == first["sha256"]


def test_negative_engine_unavailable_has_no_fixture_fallback(
    client: TestClient, dependency: Any
) -> None:
    assert dependency.mf is not None
    _char_id, ver_id, _uploaded = _setup_pack(client, code="end09g")
    resp = _submit(client, ver_id, key=BACK, prompt=BACK_PROMPT)
    assert resp.status_code == 202, resp.text
    content_key = resp.json()["content_key"]
    job_id = resp.json()["job"]["job_id"]

    site = Path(str(dependency.site))
    saved_path = list(sys.path)
    popped = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "mf_comfy" or name.startswith("mf_comfy.")
    }
    try:
        sys.path[:] = [p for p in sys.path if p != str(site)]
        importlib.invalidate_caches()
        if importlib.util.find_spec("mf_comfy") is not None:  # pragma: no cover
            pytest.skip("mf_comfy is importable outside the built site dir")
        info = _run_to_terminal(job_id)
    finally:
        sys.path[:] = saved_path
        sys.modules.update(popped)
        importlib.invalidate_caches()

    assert str(info.state.value) == "failed", info
    blob = f"{info.error or ''} {info.message or ''}"
    assert "engine_unavailable" in blob or "mf_end09_engine_refused" in blob, blob
    assert BACK not in _assets(ver_id)
    # no fixture fallback exists: the receipt is left non-terminal for a retry
    receipt = raj.read_receipt(_managed_root(), content_key)
    assert receipt is not None and receipt["status"] == raj.RECEIPT_SUBMITTED
