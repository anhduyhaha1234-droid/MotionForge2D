"""DELTA-F2 — terminal media shape vs the bucket a pinned ComfyUI actually writes.

Defect (measured on FROZEN CANDIDATE #4, MF-DEMO-E2E §F2): ComfyUI 0.37.0
publishes ``SaveVideo`` under the ``images`` bucket flagged ``animated``
(``comfy_api.latest._ui.PreviewVideo.as_dict()`` ->
``{"images": [...], "animated": (True,)}``) while the app declared the terminal
video as the ``videos`` bucket, so the pinned engine failed a render that had
ALREADY succeeded on the GPU with ``MF_COMFY_ARTIFACT_MISSING``
(actual_kind=images vs expected_kind=videos).

Rows (binary):
* F2.1 ``micro``: a video terminal declares the engine's server-decides form
  (empty bucket + ``media_type video``); image/audio keep their pinned buckets;
  the refusal taxonomy stays at 12 codes (no new code) and the engine pin is
  unchanged (no ``mf_comfy/**`` byte is touched).
* F2.1 ``provenance``: the embedded capture fixture equals the REAL
  ``MF-DEMO-E2E/raw/history_shot1.json`` on disk, and the real rendered clip the
  roundtrips replay matches its recorded sha256 (rows skip when the demo evidence
  is absent on this machine).
* F2.2 ``defect (RED)``: the pre-fix declaration on the REAL capture is refused
  by the pinned engine with ``MF_COMFY_ARTIFACT_MISSING``.
* F2.2 ``fix (GREEN)``: the app path on the same REAL capture completes, both
  ``images``+animated mp4 entries become app-kind ``video`` with the bytes
  re-hashed on disk, and the DURABLE contract proves the engine (not the app)
  decided the bucket.
* F2.2 ``replay``: the same identity reuses the receipt — no second POST — and
  keeps the video kind.
* F2.3 ``legacy``: a real ``videos`` bucket publish (other pins) is still
  accepted, with no shape proof needed.
* F2.4 ``negatives``: ``images`` WITHOUT an aligned, explicitly-true ``animated``
  flag is never the declared video (the entry keeps its bucket kind); an animated
  still (png) in the ``images`` bucket is refused by the engine (not a video
  container); a history read that cannot be made is a TYPED refusal, never a
  guess.

No GPU and no real ComfyUI server: the pinned engine (``mf_comfy`` @70f7180,
built from source by the MF-END-18 builder) runs against a fake HTTP transport
that replays the captured history and the REAL rendered mp4 bytes.

Measured: running this file against the BASE bytes of
``app/adapters/media_engine/comfy.py`` (git blob of the frozen candidate #4)
gives **10 failed, 2 passed** — the two passes are the fixture-provenance row and
the RED row that asserts the base failure itself; every row that verifies the fix
is red on base (``tools/red_on_base_probe.py`` restores the patched bytes in a
``finally`` and verifies sha256).
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import subprocess
import sys
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
SOURCE_REPO = Path(os.environ.get("DELTA_F2_SOURCE_REPO", DEFAULT_SOURCE_REPO))
DEFAULT_EVIDENCE = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z"
    "/tasks/MF-DEMO-E2E"
)
EVIDENCE = Path(os.environ.get("DELTA_F2_EVIDENCE", str(DEFAULT_EVIDENCE)))
CAPTURE_PATH = EVIDENCE / "raw" / "history_shot1.json"
CLIP_REL = "raw/renders/server_output/s10_full_apply/demo/sc-2102a9_00001_.mp4"
CLIP_PATH = EVIDENCE / CLIP_REL
REAL_DRIVE_NAME = "shotwin_ck_e9fbce1a8755a709_0_120.mp4"

# ── the REAL capture this task fixes (MF-DEMO-E2E/raw/history_shot1.json) ─────
REAL_PROMPT = "f8f000f9-1955-49e6-bb30-7d5cffdd3466"
CAPTURE_SHA256 = "2ee1c18afa6fa9e925bcc6196f73195e54e77f39d0fad15ffbbe99641ce53c7e"
REAL_CLIP_SHA256 = "2af9572812087685bdf9c09a7ca90263c1eb12fbc3d80e44db32fba29049875b"
REAL_CLIP_BYTES = 141545
#: node 246 = the terminal SaveVideo of the shot; 292 = the side-by-side aux
#: (undeclared here, exactly as the executor declares it); 240 = the driving
#: video it loaded (type ``input`` -> never publishable).
REAL_OUTPUTS: dict[str, Any] = {
    "240": {
        "images": [
            {"filename": "shotwin_ck_e9fbce1a8755a709_0_120.mp4", "subfolder": "",
             "type": "input"}
        ],
        "animated": [True],
    },
    "246": {
        "images": [
            {"filename": "sc-2102a9_00001_.mp4", "subfolder": "s10_full_apply\\demo",
             "type": "output"},
            {"filename": "sc-2102a9_00002_.mp4", "subfolder": "s10_full_apply\\demo",
             "type": "output"},
        ],
        "animated": [True, True],
    },
    "292": {
        "images": [
            {"filename": "sc-2102a9_00003_.mp4", "subfolder": "s10_full_apply\\demo",
             "type": "output"},
            {"filename": "sc-2102a9_00004_.mp4", "subfolder": "s10_full_apply\\demo",
             "type": "output"},
        ],
        "animated": [True, True],
    },
}

#: What the executor declares today (shot_reskin_executor.py:915-916): the app
#: kind, never the engine bucket.
APP_VIDEO_TERMINAL = {"246": {"kind": "video", "media_type": "video"}}
#: The engine declaration the PRE-FIX module produced for a video terminal — kept
#: only as the documented shape of the defect (the RED row loads the real base
#: module from git instead of re-typing it).
BASE_ENGINE_TERMINAL = {"246": {"kind": "videos", "media_type": "video",
                                "server_types": ("output",)}}
#: The engine's own declaration form for a video terminal after the fix.
FIXED_ENGINE_TERMINAL = {"246": {"kind": "", "media_type": "video",
                                 "server_types": ("output",)}}
#: FROZEN CANDIDATE #4 — the commit this task is required to go red on.
BASE_COMMIT = "951543664ed10e0dfaaff1f50f937b9624386074"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256(path.read_bytes())


def _load_build_module() -> Any:
    spec = importlib.util.spec_from_file_location("deltaf2_build_script", BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The MF-END-18 builder — the authority for the engine pins this fix must not touch.
BUILD = _load_build_module()


# ── module-scoped dependency: build the pinned engine from source ────────────


@pytest.fixture(scope="module")
def dependency(tmp_path_factory: pytest.TempPathFactory) -> Any:
    if not SOURCE_REPO.is_dir():
        pytest.skip(f"pinned source repo {SOURCE_REPO} is absent on this machine")
    root = tmp_path_factory.mktemp("deltaf2_dependency")
    build_dir = root / "build"
    site = root / "site"
    proc = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--source-repo", str(SOURCE_REPO),
         "--out", str(build_dir), "--install-target", str(site),
         "--built-at", "2026-09-29T00:00:00Z"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"build refused: {proc.stderr[-2000:]}"
    summary = json.loads(proc.stdout)
    sys.path.insert(0, str(site))
    for name in [m for m in list(sys.modules) if m == "mf_comfy" or m.startswith("mf_comfy.")]:
        sys.modules.pop(name, None)
    importlib.invalidate_caches()
    module = importlib.import_module("mf_comfy")
    yield SimpleNamespace(root=root, site=site, summary=summary, mf=module)
    for name in [m for m in list(sys.modules) if m == "mf_comfy" or m.startswith("mf_comfy.")]:
        sys.modules.pop(name, None)
    with contextlib.suppress(ValueError):
        sys.path.remove(str(site))


@pytest.fixture()
def real_bytes() -> bytes:
    if not CAPTURE_PATH.is_file():
        pytest.skip(f"real capture {CAPTURE_PATH} is absent on this machine")
    if CLIP_PATH.is_file():
        data = CLIP_PATH.read_bytes()
        assert _sha256(data) == REAL_CLIP_SHA256, (
            f"{CLIP_PATH} is not the captured render (sha256 {_sha256(data)[:16]}…)"
        )
        return data
    # The capture is the evidence that must be replayed; without the real clip the
    # roundtrips still exercise the REAL history shape with a deterministically
    # generated h264 mp4 so the engine's decode check stays meaningful.
    import numpy as np

    from app.services.renderer_routes.composite import write_frames_mp4

    frames = [np.full((48, 64, 3), value, dtype=np.uint8)
              for value in (30, 60, 90, 120)]
    out = Path(os.environ.get("TEMP", str(Path.home()))) / f"deltaf2_gen_{uuid.uuid4().hex}.mp4"
    write_frames_mp4(frames, out, fps=30.0)
    data = out.read_bytes()
    out.unlink(missing_ok=True)
    return data


# ── fake ComfyUI server: the engine's HTTP transport boundary ────────────────


class FakeClock:
    def __init__(self, step: float = 0.5) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float | None = None) -> None:
        self.t += self.step if dt is None else float(dt)


def minimal_object_info() -> dict[str, Any]:
    return {
        "SaveVideo": {
            "input": {"required": {"filename_prefix": ["STRING", {}]}},
            "output": ["VIDEO"], "output_node": True,
            "python_module": "comfy_extras.nodes_video",
        },
        "LoadVideo": {
            "input": {"required": {"file": [[REAL_DRIVE_NAME]]}},
            "output": ["VIDEO"], "output_node": False, "python_module": "nodes",
        },
    }


REAL_DRIVE_NAME = "shotwin_ck_e9fbce1a8755a709_0_120.mp4"


class ReplayTransport:
    """The transport surface the engine drives, replaying the captured history."""

    def __init__(self, outputs: dict[str, Any], payloads: dict[str, bytes],
                 clock: FakeClock) -> None:
        self.outputs = outputs
        self.payloads = payloads
        self.clock = clock
        self.submit_calls = 0
        self.submitted_graphs: list[dict[str, Any]] = []
        self.history_map: dict[str, dict[str, Any]] = {}
        self.history_calls = 0
        self.history_reads_with_id = 0
        self.fetch_calls: list[tuple[str, str]] = []
        #: witness knob: raise from the (fail_after_id_reads + 1)-th read that
        #: carries a prompt id (the app's own shape-proof read is the 2nd one).
        self.fail_after_id_reads: int | None = None

    # -- transport surface --
    def system_stats(self) -> dict[str, Any]:
        return {"system": {"comfyui_version": "0.37.0", "python_version": "3.11",
                           "os": "test"},
                "devices": [{"name": "RTX 5070", "vram_total": 12227 * 1024 * 1024}]}

    def object_info(self) -> dict[str, Any]:
        return minimal_object_info()

    def probe_capabilities(self, object_info: dict | None = None) -> dict[str, Any]:
        return {"base_url": "http://127.0.0.1:8199", "loopback_only": True,
                "comfyui_version": "0.37.0", "device_name": "RTX 5070",
                "device_total_vram_mib": 12227,
                "node_class_count": len(object_info or minimal_object_info()),
                "interrupt_payload": "json", "history_direct_endpoint": True}

    def submit(self, graph: dict, client_id: str) -> Any:
        from mf_comfy.transport import SubmitResult

        self.submit_calls += 1
        self.submitted_graphs.append(graph)
        prompt_id = f"prompt-{self.submit_calls}"
        self.history_map[prompt_id] = {
            "prompt": [0, prompt_id, {}, {}, []],
            "outputs": self.outputs,
            "status": {"status_str": "success", "completed": True, "messages": []},
        }
        return SubmitResult(prompt_id=prompt_id, number=self.submit_calls)

    def history(self, prompt_id: str = "") -> dict[str, Any]:
        self.history_calls += 1
        if not prompt_id:
            return dict(self.history_map)
        self.history_reads_with_id += 1
        if (self.fail_after_id_reads is not None
                and self.history_reads_with_id > self.fail_after_id_reads):
            from mf_comfy.errors import TransportError

            raise TransportError("history read refused by the DELTA-F2 witness fixture")
        entry = self.history_map.get(prompt_id)
        return {prompt_id: entry} if entry else {}

    def queue(self) -> dict[str, Any]:
        return {"queue_running": [], "queue_pending": []}

    def interrupt(self, prompt_id: str) -> dict[str, Any]:
        return {"ok": True}

    def fetch_view(self, item: dict) -> bytes:
        key = (item.get("subfolder", ""), item.get("filename", ""))
        self.fetch_calls.append(key)
        return self.payloads.get(key[1], next(iter(self.payloads.values())))

    def drain_events(self, client_id: str, timeout_s: float) -> list[dict]:
        self.clock.advance(timeout_s)
        return []

    def close(self) -> None:
        return None


# ── harness ─────────────────────────────────────────────────────────────────


GRAPH = {
    "246": {"class_type": "SaveVideo",
            "inputs": {"filename_prefix": "s10_full_apply/demo/sc-2102a9",
                       "video": ["240", 0]}},
    "240": {"class_type": "LoadVideo", "inputs": {"file": REAL_DRIVE_NAME}},
}


def stage_root(tmp_path: Path) -> Path:
    return tmp_path / "managed" / "media_engine" / "comfy_shot_engine"


def make_engine(tmp_path: Path, server: ReplayTransport, module: Any = None) -> Any:
    state = stage_root(tmp_path)
    state.mkdir(parents=True, exist_ok=True)
    (state / "instance_epoch.json").write_text(json.dumps({
        "instance_id": uuid.uuid4().hex, "launched_at": 0.0, "pid": os.getpid(),
        "host": "delta-f2-test", "base_url": "http://127.0.0.1:8199",
        "comfyui_version": "0.37.0"}), encoding="utf-8")
    engine_cls = (module or engine_adapter).ComfyShotEngine
    return engine_cls(
        managed_root=tmp_path / "managed", base_url="http://127.0.0.1:8199",
        owner="motionforge.comfy_shot_engine", transport=server, clock=server.clock,
        sleep=server.clock.advance, stage_timeout_s=2.0, poll_s=0.5,
    )


def load_base_module(tmp_path: Path) -> Any:
    """The PRE-FIX adapter module, straight out of git at the frozen base commit."""
    path = "app/adapters/media_engine/comfy.py"
    proc = subprocess.run(
        ["git", "show", f"{BASE_COMMIT}:{path}"], cwd=str(PROJECT_ROOT),
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0 or "class ComfyShotEngine" not in proc.stdout:
        pytest.skip(f"git cannot serve {BASE_COMMIT}:{path} here: {proc.stderr[-200:]}")
    target = tmp_path / "base_comfy_module.py"
    target.write_text(proc.stdout, encoding="utf-8", newline="")
    spec = importlib.util.spec_from_file_location("deltaf2_base_comfy", target)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_binding(attempt_id: str, workflow_hash: str) -> sr.EngineInputBinding:
    data = copy.deepcopy(sr.FROZEN_EXAMPLES["execution_record_book_p3b"]["input"])
    data["identity"]["attempt_id"] = attempt_id
    data["graph"]["workflow_id"] = "mf.comfy.deltaf2.savevideo"
    data["graph"]["workflow_version"] = "delta-f2-1"
    data["graph"]["workflow_hash"] = workflow_hash
    data["graph"]["nodes"] = []
    return sr.EngineInputBinding.model_validate(data)


def new_transport(clock: FakeClock, outputs: dict[str, Any], payload: bytes) -> ReplayTransport:
    payloads = {}
    for node_out in outputs.values():
        for bucket, items in (node_out or {}).items():
            if bucket == "animated" or not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("filename"):
                    payloads[str(item["filename"])] = payload
    return ReplayTransport(outputs, payloads, clock)


def run_shot(tmp_path: Path, *, attempt_id: str, declaration: dict[str, Any],
             outputs: dict[str, Any], payload: bytes, module: Any = None,
             ) -> tuple[Any, Any, ReplayTransport]:
    """Drive one attempt through the app adapter (optionally the BASE module)."""
    from mf_comfy.pinning import hash_workflow

    clock = FakeClock()
    server = new_transport(clock, outputs, payload)
    engine = make_engine(tmp_path, server, module=module)
    binding = make_binding(attempt_id, hash_workflow(GRAPH))
    record = engine.run_shot(binding, graph=GRAPH, terminal_outputs=declaration,
                             shot_id="sc-2102a9")
    return record, engine, server


def evidence_of(tmp_path: Path, attempt_id: str) -> dict[str, Any]:
    path = stage_root(tmp_path) / "evidence" / f"{attempt_id}.engine_evidence.json"
    assert path.is_file(), f"no engine evidence at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def closed_receipts(tmp_path: Path) -> list[dict[str, Any]]:
    closed = stage_root(tmp_path) / "reservations" / "closed"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(closed.glob("*.json"))]


# ── F2.1 micro ──────────────────────────────────────────────────────────────


def test_delta_f2_1_video_declares_the_engine_server_decides_form() -> None:
    """A video terminal must be a contract the pinned engine can validate."""
    normalized = engine_adapter._normalize_terminal_outputs(APP_VIDEO_TERMINAL)
    assert normalized == FIXED_ENGINE_TERMINAL
    # image/audio keep the buckets their measured pins publish into
    assert engine_adapter._normalize_terminal_outputs(
        {"9": {"kind": "image", "media_type": "image"}}
    ) == {"9": {"kind": "images", "media_type": "image", "server_types": ("output",)}}
    assert engine_adapter._normalize_terminal_outputs(
        {"7": {"kind": "audio", "media_type": "audio"}}
    ) == {"7": {"kind": "audio", "media_type": "audio", "server_types": ("output",)}}
    assert engine_adapter._normalize_terminal_outputs(None) == {}
    # the declaration still refuses what the engine would refuse
    with pytest.raises(ValueError):
        engine_adapter._normalize_terminal_outputs({"1": {"kind": "videos", "media_type": "video"}})
    with pytest.raises(ValueError):
        engine_adapter._normalize_terminal_outputs({"1": {"kind": "video", "media_type": "image"}})
    with pytest.raises(ValueError):
        engine_adapter._normalize_terminal_outputs({"1": {"kind": "audio", "media_type": "video"}})
    # no new refusal code, no engine file touched
    codes = [c.value for c in engine_adapter.ComfyEngineRefusalCode]
    assert len(codes) == len(set(codes)) == 12
    assert engine_adapter.MF_COMFY_SOURCE_COMMIT_PIN == BUILD.PINNED_COMMIT
    assert len(engine_adapter.MF_COMFY_MODULE_FILES) == 11


def test_delta_f2_1_fixture_equals_the_real_capture() -> None:
    """The embedded shape must BE the recorded 0.37 history entry, not a memory."""
    if not CAPTURE_PATH.is_file():
        pytest.skip(f"real capture {CAPTURE_PATH} is absent on this machine")
    raw = CAPTURE_PATH.read_bytes()
    assert _sha256(raw) == CAPTURE_SHA256, (
        f"{CAPTURE_PATH} changed since this test was written "
        f"(sha256 {_sha256(raw)}); re-derive the fixture from the new capture"
    )
    capture = json.loads(raw.decode("utf-8"))
    entry = capture[REAL_PROMPT]
    assert entry["outputs"] == REAL_OUTPUTS
    assert entry["status"]["status_str"] == "success"
    assert entry["status"]["completed"] is True
    # the terminal node's items are mp4 files the engine's VIDEO_SUFFIXES accepts,
    # and every one of them is flagged animated (the 0.37 SaveVideo shape)
    items = entry["outputs"]["246"]["images"]
    assert [item["filename"] for item in items] == [
        "sc-2102a9_00001_.mp4", "sc-2102a9_00002_.mp4"]
    assert [item["type"] for item in items] == ["output", "output"]
    assert entry["outputs"]["246"]["animated"] == [True, True]
    if CLIP_PATH.is_file():
        assert CLIP_PATH.stat().st_size == REAL_CLIP_BYTES
        assert _sha256_file(CLIP_PATH) == REAL_CLIP_SHA256


# ── F2.2 the defect, the fix, the replay ────────────────────────────────────


def test_delta_f2_2_pre_fix_declaration_is_refused_on_the_real_capture(
    dependency: Any, tmp_path: Path, real_bytes: bytes
) -> None:
    """RED: the BASE adapter (git, frozen candidate #4) fails a render that worked."""
    assert dependency.mf is not None
    base = load_base_module(tmp_path)
    # the base mapping IS the defect: video -> the ``videos`` bucket, while the
    # captured 0.37 server published the successful render into ``images``
    assert base._normalize_terminal_outputs(APP_VIDEO_TERMINAL) == BASE_ENGINE_TERMINAL
    record, _, server = run_shot(
        tmp_path, attempt_id="attempt-f2-red", declaration=APP_VIDEO_TERMINAL,
        outputs=REAL_OUTPUTS, payload=real_bytes, module=base,
    )
    assert server.submit_calls == 1, "the render prompt must actually have been sent"
    assert record.outcome == "failed"
    assert record.output is None
    assert record.error is not None and record.error.code == "MF_COMFY_ARTIFACT_MISSING"
    assert "different media kind" in str(record.error.message)
    written = evidence_of(tmp_path, "attempt-f2-red")
    failure = written["engine_failure"]
    assert failure["code"] == "MF_COMFY_ARTIFACT_MISSING"
    assert failure["details"]["actual_kind"] == "images"
    assert failure["details"]["expected_kind"] == "videos"
    assert failure["details"]["node_id"] == "246"


def test_delta_f2_2_fixed_adapter_accepts_the_real_capture(
    dependency: Any, tmp_path: Path, real_bytes: bytes
) -> None:
    """GREEN: same capture, app path -> completed, both clips are videos."""
    assert dependency.mf is not None
    record, engine, server = run_shot(
        tmp_path, attempt_id="attempt-f2-green", declaration=APP_VIDEO_TERMINAL,
        outputs=REAL_OUTPUTS, payload=real_bytes,
    )
    assert engine is not None
    assert record.outcome == "completed", record.error
    output = record.output
    assert output is not None
    artifacts = list(output.artifacts)
    assert [a.kind for a in artifacts] == ["video", "video"]
    assert [a.media_type for a in artifacts] == ["video/mp4", "video/mp4"]
    assert [a.publishable for a in artifacts] == [True, True]
    assert [a.server_output_type for a in artifacts] == ["output", "output"]
    # the bytes the record claims are the bytes on disk (and the real clip)
    for artifact in artifacts:
        on_disk = Path(engine.managed_root) / artifact.store_relative_path
        assert on_disk.is_file()
        assert _sha256_file(on_disk) == artifact.sha256 == _sha256(real_bytes)
        assert artifact.size_bytes == on_disk.stat().st_size == len(real_bytes)
    # the executor's own main-pick rule finds exactly one main clip
    candidates = [a for a in artifacts if a.kind == "video"]
    mains = [a for a in candidates if "_00001_" in Path(a.store_relative_path).name]
    assert len(mains) == 1 and mains[0].sha256 == REAL_CLIP_SHA256
    # ONE POST, and two history reads: the engine's validation + the app's proof
    assert server.submit_calls == 1
    assert server.history_reads_with_id == 2
    # the DURABLE contract shows the engine decided the bucket (kind "") while the
    # staged artifact kept the bucket the server really wrote ("images")
    receipts = closed_receipts(tmp_path)
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["outcome"] == "terminal_success"
    assert receipt["output_contract"]["nodes"]["246"] == {
        "kind": "", "media_type": "video", "server_types": ["output"]}
    staged = receipt["close_evidence"]["artifacts"]
    assert [item["kind"] for item in staged] == ["images", "images"]
    assert [item["server_type"] for item in staged] == ["output", "output"]
    # the app evidence records WHERE the shape proof came from and what it proved
    proof = evidence_of(tmp_path, "attempt-f2-green")["video_shape_proof"]
    assert proof["declared_video_nodes"] == ["246"]
    assert proof["source"] == "history"
    assert proof["proven_animated"] == [
        "images:sc-2102a9_00001_.mp4", "images:sc-2102a9_00002_.mp4"]
    assert proof["required_for"] == [
        {"node_id": "246", "bucket": "images", "filename": "sc-2102a9_00001_.mp4"},
        {"node_id": "246", "bucket": "images", "filename": "sc-2102a9_00002_.mp4"},
    ]


def test_delta_f2_2_replay_reuses_the_receipt_and_keeps_the_video_kind(
    dependency: Any, tmp_path: Path, real_bytes: bytes
) -> None:
    assert dependency.mf is not None
    from mf_comfy.pinning import hash_workflow

    clock = FakeClock()
    server = new_transport(clock, REAL_OUTPUTS, real_bytes)
    engine = make_engine(tmp_path, server)
    binding = make_binding("attempt-f2-replay", hash_workflow(GRAPH))
    first = engine.run_shot(binding, graph=GRAPH, terminal_outputs=APP_VIDEO_TERMINAL)
    replay_record, info = engine.replay(binding, graph=GRAPH,
                                        terminal_outputs=APP_VIDEO_TERMINAL)
    assert info["replayed"] is True
    assert server.submit_calls == 1, "a replay must never send a second POST"
    assert replay_record.outcome == "completed"
    assert [a.kind for a in replay_record.output.artifacts] == ["video", "video"]
    assert [a.kind for a in first.output.artifacts] == ["video", "video"]
    assert len(closed_receipts(tmp_path)) == 1


def test_delta_f2_3_legacy_videos_bucket_is_still_accepted(
    dependency: Any, tmp_path: Path, real_bytes: bytes
) -> None:
    """A pin that publishes a real ``videos`` bucket keeps working unchanged."""
    assert dependency.mf is not None
    outputs = {
        "246": {"videos": [
            {"filename": "sc-2102a9_00001_.mp4", "subfolder": "s10_full_apply\\demo",
             "type": "output"},
            {"filename": "sc-2102a9_00002_.mp4", "subfolder": "s10_full_apply\\demo",
             "type": "output"},
        ]}
    }
    record, _, server = run_shot(
        tmp_path, attempt_id="attempt-f2-legacy", declaration=APP_VIDEO_TERMINAL,
        outputs=outputs, payload=real_bytes,
    )
    assert record.outcome == "completed", record.error
    assert [a.kind for a in record.output.artifacts] == ["video", "video"]
    assert [a.media_type for a in record.output.artifacts] == ["video/mp4", "video/mp4"]
    # the videos bucket IS the video: no shape proof is needed (no extra read)
    proof = evidence_of(tmp_path, "attempt-f2-legacy")["video_shape_proof"]
    assert proof["source"] == "not-needed"
    assert proof["proven_animated"] == []
    assert server.history_reads_with_id == 1


# ── F2.4 negatives ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("animated", "expected_kinds"),
    [
        (None, ["image", "image"]),           # no animated key at all: no proof
        ([False], ["image", "image"]),        # short/absent flags: no proof
        ([True, False], ["video", "image"]),  # proof is per ENTRY, aligned by index
    ],
)
def test_delta_f2_4_images_without_animated_is_not_the_declared_video(
    dependency: Any, tmp_path: Path, real_bytes: bytes, animated: Any,
    expected_kinds: list[str],
) -> None:
    """``images`` + a video container is NOT a video without the per-entry proof."""
    assert dependency.mf is not None
    node_out: dict[str, Any] = {"images": [
        {"filename": "sc-2102a9_00001_.mp4", "subfolder": "s10_full_apply\\demo",
         "type": "output"},
        {"filename": "sc-2102a9_00002_.mp4", "subfolder": "s10_full_apply\\demo",
         "type": "output"},
    ]}
    if animated is not None:
        node_out["animated"] = animated
    outputs = {"246": node_out}
    record, _, server = run_shot(
        tmp_path, attempt_id="attempt-f2-neg", declaration=APP_VIDEO_TERMINAL,
        outputs=outputs, payload=real_bytes,
    )
    # the engine stages the bytes (a real video container on a declared node) ...
    assert record.outcome == "completed", record.error
    artifacts = list(record.output.artifacts)
    assert [a.kind for a in artifacts] == expected_kinds
    assert [a.media_type for a in artifacts] == [f"{kind}/mp4" for kind in expected_kinds]
    # ... and an entry the server did NOT flag animated is never the declared video
    unproven = [a for a in artifacts if a.kind != "video"]
    assert len(unproven) == sum(1 for kind in expected_kinds if kind != "video")
    proof = evidence_of(tmp_path, "attempt-f2-neg")["video_shape_proof"]
    assert proof["source"] == "history"
    assert proof["proven_animated"] == (
        [] if not animated or animated[0] is not True else ["images:sc-2102a9_00001_.mp4"]
    )
    assert len(proof["required_for"]) == 2
    assert server.submit_calls == 1


def test_delta_f2_4_animated_still_in_images_bucket_is_refused_by_the_engine(
    dependency: Any, tmp_path: Path
) -> None:
    """An ``animated`` still (png) is not a video container: the engine refuses it."""
    assert dependency.mf is not None
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
    outputs = {"246": {"images": [
        {"filename": "still_00001_.png", "subfolder": "s10_full_apply\\demo",
         "type": "output"},
    ], "animated": [True]}}
    record, _, server = run_shot(
        tmp_path, attempt_id="attempt-f2-neg-png", declaration=APP_VIDEO_TERMINAL,
        outputs=outputs, payload=buf.getvalue(),
    )
    assert record.outcome == "failed"
    assert record.output is None
    assert record.error is not None and record.error.code == "MF_COMFY_ARTIFACT_MISSING"
    assert "non-video artifact" in str(record.error.message)
    assert server.submit_calls == 1


def test_delta_f2_4_unreadable_history_is_a_typed_refusal(
    dependency: Any, tmp_path: Path, real_bytes: bytes
) -> None:
    """No proof available -> refuse typed; never classify on a guess."""
    assert dependency.mf is not None
    from mf_comfy.pinning import hash_workflow

    clock = FakeClock()
    server = new_transport(clock, REAL_OUTPUTS, real_bytes)
    # the engine's own validation read (1st) works; the app's proof read (2nd) fails
    server.fail_after_id_reads = 1
    engine = make_engine(tmp_path, server)
    binding = make_binding("attempt-f2-witness", hash_workflow(GRAPH))
    with pytest.raises(engine_adapter.ComfyEngineRefusal) as caught:
        engine.run_shot(binding, graph=GRAPH, terminal_outputs=APP_VIDEO_TERMINAL)
    refusal = caught.value
    assert refusal.code is engine_adapter.ComfyEngineRefusalCode.ENGINE_REFUSED
    assert refusal.engine_code == "MF_COMFY_TRANSPORT_ERROR"
    assert "animation bucket" in refusal.detail
    assert server.submit_calls == 1, "the refusal must never trigger a second POST"
    assert server.history_reads_with_id == 2, "the app's proof read must have been made"
    written = evidence_of(tmp_path, "attempt-f2-witness")
    assert written["status"] == "refused"
    assert written["refusal"]["engine_code"] == "MF_COMFY_TRANSPORT_ERROR"
    # nothing was composed, and the durable terminal receipt is still the engine's
    assert closed_receipts(tmp_path)[0]["outcome"] == "terminal_success"


def test_delta_f2_5_engine_dependency_is_untouched() -> None:
    """The fix is app-side only: the pinned engine files/summary are unchanged."""
    summary_pin = BUILD.PINNED_COMMIT
    assert summary_pin == engine_adapter.MF_COMFY_SOURCE_COMMIT_PIN
    assert len(BUILD.PINNED_FILES) == 11
    assert set(BUILD.PINNED_FILES) == set(engine_adapter.MF_COMFY_MODULE_FILES)
    for name, (sha, size) in sorted(BUILD.PINNED_FILES.items()):
        assert engine_adapter.MF_COMFY_MODULE_FILES[name] == sha, name
        assert isinstance(size, int) and size > 0
    assert engine_adapter._ANIMATION_BUCKETS == ("images", "gifs")
    assert engine_adapter._TERMINAL_KIND_MAP["video"] == ("", "video")
