"""MF-END-26 — Publication → tiếng gốc → S12 export: acceptance + negatives.

Row map (binary; every row runs REAL code over REAL temp databases, REAL
managed roots and REAL ffmpeg media — nothing is mocked at the code level):

* micro repro (26.0): the ONE export-gate consumption contract exists — the
  S12 preflight consumes ``mf-end-23/export-gate@1`` (schema pinned, never a
  second gate): every gate violation code maps onto the CLOSED preflight
  reason vocabulary, the gate's own code stays verbatim in the detail, and
  unknown schemas / missing videos / missing records fail CLOSED;
* 26.1: the server-owned authority consumes the gate ADDITIVELY: a
  gate-ready video passes the ``export_gate`` check with the gate identity
  attached, a gate-blocked video fails it with the mapped reason — and the
  authority's ``resolved`` verdict (the submit leg's 409 contract) is
  UNCHANGED by the gate (the gate adds, it does not redefine);
* 26.1/26.3: the export legs consume the gate: a BLOCKED gate refuses the
  submit with a typed message and ZERO rows written; ``not_run`` (owned by
  the readiness authority) and an unresolvable gate (environment guard) do
  NOT fabricate a refusal;
* 26.2: the original-audio probe is REAL (bounded ffprobe of the canonical
  first audio stream): AAC 44.1k stereo is measured (codec/sample-rate/
  channels/timebase/duration), a silent source is honestly ``present=False``,
  and a missing source fails closed with the engine's stable code;
* 26.2/26.1: the export's audio source is SERVER-OWNED: the submit leg
  resolves it from the same completed-publication artifact the export renders
  from (never a loose/client file) and records the measured provenance in the
  run manifest; a silent source stays honestly silent;
* 26.3 (ACCEPTANCE): the app's export path — submit → durable job → real
  runner/stitch → real source-locked publication — produces an MP4 that
  carries the ORIGINAL audio (AAC 44.1k stereo, re-encoded once by the
  assembly per C28-F01) with the full frame count, and the file REOPENS
  (full-file decode, zero errors);
* 26.4: an invalidation (blocked gate) refuses with zero mutation and never
  touches an already-published output (bytes unchanged); the 4K/1080p
  profile contract stays frozen and native-vs-upscale stays provenance-based.

Disclosures (no green-by-fabrication): the QC chain worlds are the REAL
MF-END-23 worlds (``test_mf_end_23`` harness: real rows, real sealed
observations, real gate computation) — re-used read-only.  The worker
harness (durable JobService + seeded S10 authority + lock/checkpoint rows)
is the REAL S12-T03C harness from ``tests/s12/s12-lc3-retry`` — re-used
read-only; the only substituted boundary is the frozen QC readiness
aggregate (Decision F) that the legacy harness itself substitutes.  The
4K-upscale REAL write on GPU is out of this bounded patch's scope and is
reported NOT_RUN, never a fake pass.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from app.persistence import readiness as rd
from app.services import original_audio_remux as remux
from app.services.s12_export import preflight as pf
from app.services.s12_export.authority import resolve_export_authority
from app.workflow import s12_export_jobs as jobs

WT = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: REAL MF-END-23 QC-world harness (read-only reuse, same delivery).
_T23 = _load_module(
    "mf26_t23_harness", WT / "tests" / "product_delivery" / "test_mf_end_23.py"
)
#: REAL S12-T03C worker harness (read-only reuse, S12-LC3 lane).
_RETRY = _load_module(
    "mf26_retry_harness",
    WT / "tests" / "s12" / "s12-lc3-retry" / "test_s12_t03c_c1_closure.py",
)

WS, PROJECT, VIDEO = _T23.WS, _T23.PROJECT, _T23.VIDEO
GATE = rd.EXPORT_GATE_SCHEMA


def _closed_reason_codes() -> set[str]:
    from app.schemas.s12_export import S12_EXPORT_REASON_CODES

    return set(S12_EXPORT_REASON_CODES)


@pytest.fixture(autouse=True)
def _managed_root(monkeypatch: Any, tmp_path: Path) -> Path:
    """One isolated managed root per test, published through the accessor."""
    root = tmp_path / "managed"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.api.deps.get_managed_root", lambda: root)
    _T23._MANAGED["root"] = root
    return root


def _seed_gate_world(tmp_path: Path, *, blocked: bool = False) -> dict[str, Any]:
    """REAL MF-END-23 world: gate ``ready`` by default, ``blocked`` on demand."""
    if blocked:
        # tampered observation bytes → EXPORT_BLOCKED_OUTPUT_EVIDENCE
        return _T23._seed_world(tmp_path / "blocked", observations_tampered=True)
    return _T23._seed_world(tmp_path)


def _full_run_world(tmp_path: Path, *, blocked: bool = False) -> dict[str, Any]:
    world = _seed_gate_world(tmp_path, blocked=blocked)
    seeded = _T23._seed_full_run(world["sf"])
    _T23._record_full_run(world["sf"], seeded)
    return world


def _authority(world: dict[str, Any]) -> Any:
    sf = world["sf"]
    with sf() as session:
        return resolve_export_authority(
            session,
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
            checkpoint_id="ck-mf26",
            checkpoint_hash="c" * 64,
            checkpoint_revision=1,
            manifest_id="lock-mf26",
            manifest_hash="d" * 64,
            manifest_generation="1",
        )


# ── 26.0 — micro repro: the ONE gate consumption contract ───────────────────


def test_mf26_0_gate_consumption_maps_every_code_into_closed_vocab() -> None:
    """Every gate violation code → CLOSED preflight reason; code kept verbatim."""
    vocab = _closed_reason_codes()
    codes = (
        rd.EXPORT_BLOCKED_READINESS,
        rd.EXPORT_BLOCKED_JOB_UNREADABLE,
        rd.EXPORT_BLOCKED_BAND_MISMATCH,
        rd.EXPORT_BLOCKED_DETECTOR_UNKNOWN,
        rd.EXPORT_BLOCKED_DETECTOR_REVISION,
        rd.EXPORT_BLOCKED_BINDING_MISSING,
        rd.EXPORT_BLOCKED_BINDING_TAMPER,
        rd.EXPORT_BLOCKED_STALE_SOURCE,
        rd.EXPORT_BLOCKED_STALE_RENDER,
        rd.EXPORT_BLOCKED_STALE_CAST,
        rd.EXPORT_BLOCKED_OUTPUT_EVIDENCE,
    )
    assert pf.EXPORT_GATE_SCHEMA == rd.EXPORT_GATE_SCHEMA == "mf-end-23/export-gate@1"
    for code in codes:
        record = rd.ExportGateRecord(
            schema=rd.EXPORT_GATE_SCHEMA,
            workspace_id=WS,
            project_id=PROJECT,
            status=rd.EXPORT_BLOCKED,
            videos=[
                rd.ExportGateVideoRecord(
                    video_item_id=VIDEO,
                    status=rd.EXPORT_BLOCKED,
                    readiness_status="ready",
                    run_state="completed",
                    check_state_detail="seeded",
                    latest_job_id="job-1",
                    binding_state="current",
                    output_state="invalid",
                    output_detail="seeded",
                    violations=(
                        rd.ExportGateViolation(
                            code=code,
                            video_item_id=VIDEO,
                            kind="seeded",
                            detail=f"seeded {code}",
                        ),
                    ),
                )
            ],
            blockers=[],
            visibility={},
            policy_version="seeded",
            content_hash="0" * 64,
            computed_at="2026-01-01T00:00:00+00:00",
        )
        verdict = pf.export_gate_consumption(record, VIDEO)
        assert verdict.passed is False, code
        assert verdict.reason in vocab, (code, verdict.reason)
        assert code in verdict.detail, (code, verdict.detail)
        assert verdict.schema_ok is True
    # ready → pass; not_run → the readiness authority owns the refusal
    ready = pf.export_gate_consumption(
        _record(rd.EXPORT_READY, status="ready"), VIDEO
    )
    assert ready.passed is True and ready.reason == "S12_EXPORT_OK"
    not_run = pf.export_gate_consumption(
        _record(rd.EXPORT_NOT_RUN, status="not_run"), VIDEO
    )
    assert not_run.passed is False
    assert not_run.reason == "S12_EXPORT_NOT_READY" in vocab


def _record(video_status: str, *, status: str) -> rd.ExportGateRecord:
    return rd.ExportGateRecord(
        schema=rd.EXPORT_GATE_SCHEMA,
        workspace_id=WS,
        project_id=PROJECT,
        status=status,
        videos=[
            rd.ExportGateVideoRecord(
                video_item_id=VIDEO,
                status=video_status,
                readiness_status="ready" if video_status == "ready" else "not_run",
                run_state="completed" if video_status == "ready" else "none",
                check_state_detail="seeded",
                latest_job_id="job-1",
                binding_state="current",
                output_state="valid",
                output_detail="seeded",
                violations=(),
            )
        ],
        blockers=[],
        visibility={},
        policy_version="seeded",
        content_hash="0" * 64,
        computed_at="2026-01-01T00:00:00+00:00",
    )


def test_mf26_0_gate_consumption_fails_closed_on_unknown_contract() -> None:
    """Unknown schema / absent video / missing record all REFUSE (fail closed)."""
    vocab = _closed_reason_codes()
    unknown = _record(rd.EXPORT_READY, status="ready")
    object.__setattr__(unknown, "schema", "mf-end-23/export-gate@999")
    verdict = pf.export_gate_consumption(unknown, VIDEO)
    assert verdict.passed is False and verdict.schema_ok is False
    assert verdict.reason in vocab and "999" in verdict.detail

    absent = pf.export_gate_consumption(
        _record(rd.EXPORT_READY, status="ready"), "v-other"
    )
    assert absent.passed is False and "v-other" in absent.detail
    assert absent.reason in vocab

    none = pf.export_gate_consumption(None, VIDEO)
    assert none.passed is False and none.reason in vocab


# ── 26.1 — authority consumes the gate, additively ──────────────────────────


def test_mf26_1_authority_consumes_gate_additively(tmp_path: Path) -> None:
    ready_world = _full_run_world(tmp_path / "ready")
    gate_ready = _T23._gate(ready_world["sf"])
    assert gate_ready.status == rd.EXPORT_READY, gate_ready.to_dict()
    auth_ready = _authority(ready_world)
    checks = {c.name: c for c in auth_ready.checks}
    assert "export_gate" in checks, [c.name for c in auth_ready.checks]
    assert checks["export_gate"].passed is True
    assert checks["export_gate"].reason == "S12_EXPORT_OK"
    assert auth_ready.export_gate_ok is True
    assert auth_ready.export_gate_schema == GATE
    assert auth_ready.export_gate_video_status == "ready"

    blocked_world = _full_run_world(tmp_path / "blocked", blocked=True)
    gate_blocked = _T23._gate(blocked_world["sf"])
    assert gate_blocked.status == rd.EXPORT_BLOCKED, gate_blocked.to_dict()
    auth_blocked = _authority(blocked_world)
    checks_b = {c.name: c for c in auth_blocked.checks}
    assert checks_b["export_gate"].passed is False
    assert checks_b["export_gate"].reason == "S12_EXPORT_NOT_READY"
    assert rd.EXPORT_BLOCKED_OUTPUT_EVIDENCE in checks_b["export_gate"].detail
    assert auth_blocked.export_gate_ok is False
    # ADDITIVE: the gate never enters ``resolved`` (the submit 409 contract) —
    # the verdict is identical across the ready and blocked worlds while the
    # gate check flips; only the preflight's own eligibility consumes it.
    assert auth_ready.resolved == auth_blocked.resolved is False
    assert auth_ready.export_gate_ok != auth_blocked.export_gate_ok


# ── 26.1/26.3 — the export legs consume the gate ────────────────────────────


def test_mf26_1_gate_refusal_blocked_only_and_zero_mutation(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """blocked → typed refusal; not_run/unresolvable → no fabricated refusal."""
    ready_world = _full_run_world(tmp_path / "ready")
    with ready_world["sf"]() as session:
        assert (
            jobs.export_gate_refusal(
                session,
                workspace_id=WS,
                project_id=PROJECT,
                video_item_id=VIDEO,
            )
            is None
        )

    blocked_world = _full_run_world(tmp_path / "blocked", blocked=True)
    with blocked_world["sf"]() as session:
        refusal = jobs.export_gate_refusal(
            session,
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
        )
    assert refusal is not None
    assert rd.EXPORT_BLOCKED_OUTPUT_EVIDENCE in refusal
    assert refusal.startswith("S12_EXPORT_NOT_READY")

    not_run_world = _seed_gate_world(tmp_path / "notrun")
    with not_run_world["sf"]() as session:
        assert (
            jobs.export_gate_refusal(
                session,
                workspace_id=WS,
                project_id=PROJECT,
                video_item_id=VIDEO,
            )
            is None
        )

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("seeded unresolvable gate")

    mp_boom = pytest.MonkeyPatch()
    mp_boom.setattr(rd, "compute_export_gate", _boom)
    try:
        with blocked_world["sf"]() as session:
            assert (
                jobs.export_gate_refusal(
                    session,
                    workspace_id=WS,
                    project_id=PROJECT,
                    video_item_id=VIDEO,
                )
                is None
            )
    finally:
        mp_boom.undo()

    # zero mutation: the refusal fires BEFORE any run/job row exists.
    blocked_world2 = _full_run_world(tmp_path / "blocked2", blocked=True)
    sf = blocked_world2["sf"]
    svc = _RETRY.JobService(sf, managed_root=tmp_path / "managed")
    with sf() as session:
        before = int(session.execute(text("SELECT COUNT(*) FROM s12_export_run")).scalar())
    with pytest.raises(jobs.S12ExportSubmitError) as exc:
        jobs.submit_export_job(
            svc,
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
            checkpoint_id="ck-mf26",
            checkpoint_hash="c" * 64,
            checkpoint_revision=1,
            manifest_id="lock-mf26",
            manifest_hash="d" * 64,
            manifest_generation="1",
            profile_id="master-4k-h264",
            plan_id="e" * 64,
            plan_hash="f" * 64,
            frame_count=8,
            chunk_config={"max_frames": 4, "overlap": 1},
            source_path=str(tmp_path / "managed" / "none.mp4"),
            fps=10.0,
            chunk_dir=str(tmp_path / "chunks"),
            scratch_dir=str(tmp_path / "scratch"),
            output_path=str(tmp_path / "out.mp4"),
        )
    assert "EXPORT_BLOCKED_OUTPUT_EVIDENCE" in str(exc.value)
    with sf() as session:
        after = int(session.execute(text("SELECT COUNT(*) FROM s12_export_run")).scalar())
        job_count = int(
            session.execute(
                text("SELECT COUNT(*) FROM job WHERE job_type=:t"),
                {"t": jobs.S12_EXPORT_JOB_TYPE},
            ).scalar()
        )
    assert (before, after) == (0, 0)
    assert job_count == 0


# ── 26.2 — the original-audio probe is real ─────────────────────────────────


def _ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not on PATH (real-media row needs the real binary)")
    return ffmpeg


def _make_source(path: Path, *, audio: bool, seconds: float = 0.8) -> Path:
    """Real CFR H.264 source; optional AAC 44.1k stereo (the proof shape)."""
    cmd = [
        _ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=320x180:rate={_RETRY.FPS}:duration={seconds}",
    ]
    if audio:
        cmd += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=44100:duration={seconds}",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-shortest",
        ]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    assert path.is_file() and path.stat().st_size > 0
    return path


def test_mf26_2_probe_original_audio_measures_real_aac_and_silent(
    tmp_path: Path,
) -> None:
    with_audio = _make_source(tmp_path / "src-audio.mp4", audio=True)
    probe = remux.probe_original_audio(with_audio)
    assert probe.present is True
    assert probe.codec == "aac"
    assert probe.sample_rate == 44100
    assert probe.channels == 2
    assert probe.time_base
    assert probe.duration is not None and float(probe.duration) >= 0.7
    assert probe.video_codec == "h264"
    assert probe.stream_index == 1  # video 0, audio 1

    silent = _make_source(tmp_path / "src-silent.mp4", audio=False)
    quiet = remux.probe_original_audio(silent)
    assert quiet.present is False and quiet.detail

    with pytest.raises(remux.OriginalAudioRemuxError) as exc:
        remux.probe_original_audio(tmp_path / "missing.mp4")
    assert exc.value.code == remux.CODE_SOURCE_NOT_FOUND


def test_mf26_2_resolve_audio_source_is_server_owned(tmp_path: Path) -> None:
    with_audio = _make_source(tmp_path / "src-audio.mp4", audio=True)
    path_value, provenance = jobs.resolve_original_audio_source(with_audio)
    assert path_value == str(with_audio)
    assert provenance["mode"] == "source_remux"
    assert provenance["source"] == "completed_publication_artifact"
    assert provenance["codec"] == "aac"
    assert provenance["sample_rate"] == 44100 and provenance["channels"] == 2
    assert provenance["time_base"]

    silent = _make_source(tmp_path / "src-silent.mp4", audio=False)
    path_none, prov_none = jobs.resolve_original_audio_source(silent)
    assert path_none is None and prov_none["mode"] == "absent"

    missing, prov_missing = jobs.resolve_original_audio_source(tmp_path / "nope.mp4")
    assert missing is None and prov_missing["mode"] == "absent"
    assert "probe failed closed" in prov_missing["reason"]


# ── 26.3 — ACCEPTANCE: the app's export carries the original audio ──────────


def _ffprobe_frames(path: Path) -> int:
    ffprobe = shutil.which("ffprobe")
    assert ffprobe, "ffprobe required"
    out = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    streams = json.loads(out.stdout)["streams"]
    return int(streams[0]["nb_read_frames"])


def test_mf26_3_export_end_to_end_carries_original_audio_and_reopens(
    tmp_path: Path,
) -> None:
    """ACCEPTANCE: submit → durable job → real runner/stitch → real publication."""
    _ffmpeg()
    fixture = getattr(_RETRY.env, "__wrapped__", _RETRY.env)
    retry_root = tmp_path / "retry"
    retry_root.mkdir(parents=True, exist_ok=True)
    factory, svc, manifest_id, auth, dirs, managed = next(fixture(retry_root))
    mp = pytest.MonkeyPatch()
    mp.setattr(_RETRY.route, "get_job_service", lambda: svc)
    mp.setattr(_RETRY.route, "get_managed_root", lambda: managed)
    mp.setattr("app.api.deps.get_managed_root", lambda: managed)
    # Decision F boundary (same substitution the legacy T03C lane makes): the
    # frozen QC readiness aggregate is a T03G/T04A-lane fixture — the export
    # path itself (runner/stitch/publication) stays REAL.  ``videos`` must be
    # addressable here so the REAL publication readiness gate is exercised.
    mp.setattr(
        "app.persistence.readiness.compute_project_readiness",
        lambda session, **kw: SimpleNamespace(
            status="ready",
            videos=[SimpleNamespace(video_item_id=f"v-{_RETRY.WS}")],
        ),
    )
    mp.setattr(
        "app.services.s12_export.publication._check_run_readiness",
        lambda session, **kw: "ready",
    )
    try:
        source = _make_source(managed / "apply" / "mf26src.mp4", audio=True)
        with factory() as session:
            session.execute(
                text("UPDATE artifact SET relative_path=:rel WHERE id=:aid"),
                {
                    "rel": str(source.relative_to(managed)).replace("\\", "/"),
                    "aid": auth["artifact_id"],
                },
            )
            session.commit()
        body = _RETRY._authority_body(factory, auth, manifest_id)
        with factory() as session:
            out = _RETRY.route.submit_export(
                _RETRY.route.S12ExportSubmitRequest(**body),
                session,
                workspace_id=_RETRY.WS,
            )
            session.commit()
        assert out["job_id"] and out["run_id"]

        from app.persistence.models import Job as JobRow

        with factory() as session:
            row = session.get(JobRow, out["job_id"])
            manifest = json.loads(row.input_manifest_json)
        # 26.1/26.2 — the manifest records the SERVER-OWNED audio identity.
        assert manifest["audio_source"] == str(source)
        assert manifest["audio_provenance"]["mode"] == "source_remux"
        assert manifest["audio_provenance"]["sample_rate"] == 44100
        assert manifest["audio_provenance"]["channels"] == 2

        ctx = SimpleNamespace(
            worker_id="worker-mf26",
            session_factory=factory,
            input_manifest=manifest,
        )
        result = _RETRY._s12_export_handler(ctx)
        assert result["status"] == "completed", result
        with factory() as session:
            run = _RETRY.S12ExportRepository(session).get_run(out["run_id"])
        assert run.status == "completed"

        final = Path(out["output_path"])
        assert final.is_file() and final.stat().st_size > 0
        probe = remux.probe_original_audio(final)
        assert probe.present is True, "exported MP4 must carry the original audio"
        assert probe.codec == "aac"
        assert probe.sample_rate == 44100 and probe.channels == 2
        assert _ffprobe_frames(final) == _RETRY.FRAMES
        dec = subprocess.run(
            [
                _ffmpeg(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(final),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert dec.returncode == 0, dec.stderr
        assert dec.stderr.strip() == "", dec.stderr
    finally:
        mp.undo()


# ── 26.4 — invalidation keeps outputs; profiles stay frozen ─────────────────


def test_mf26_4_invalidation_never_touches_published_output(tmp_path: Path) -> None:
    """A blocked-gate refusal writes zero rows and leaves outputs untouched."""
    world = _full_run_world(tmp_path, blocked=True)
    sf = world["sf"]
    published = world["managed"] / "published" / "final.mp4"
    published.parent.mkdir(parents=True, exist_ok=True)
    published.write_bytes(b"MF26-PUBLISHED-OUTPUT" + b"\x00" * 64)
    digest_before = __import__("hashlib").sha256(published.read_bytes()).hexdigest()
    svc = _RETRY.JobService(sf, managed_root=world["managed"])
    with pytest.raises(jobs.S12ExportSubmitError):
        jobs.submit_export_job(
            svc,
            workspace_id=WS,
            project_id=PROJECT,
            video_item_id=VIDEO,
            checkpoint_id="ck-mf26",
            checkpoint_hash="c" * 64,
            checkpoint_revision=1,
            manifest_id="lock-mf26",
            manifest_hash="d" * 64,
            manifest_generation="1",
            profile_id="master-4k-h264",
            plan_id="e" * 64,
            plan_hash="f" * 64,
            frame_count=8,
            chunk_config={"max_frames": 4, "overlap": 1},
            source_path=str(world["managed"] / "none.mp4"),
            fps=10.0,
            chunk_dir=str(tmp_path / "chunks"),
            scratch_dir=str(tmp_path / "scratch"),
            output_path=str(published),
        )
    assert published.is_file()
    import hashlib

    assert hashlib.sha256(published.read_bytes()).hexdigest() == digest_before
    with sf() as session:
        assert int(session.execute(text("SELECT COUNT(*) FROM s12_export_run")).scalar()) == 0


def test_mf26_4_profile_contract_and_upscale_provenance() -> None:
    """Frozen profiles + native-vs-upscale honesty (4K GPU write: NOT_RUN)."""
    assert pf.PREFLIGHT_PROFILES["master-4k-h264"]["width"] == 3840
    assert pf.PREFLIGHT_PROFILES["master-4k-h264"]["height"] == 2160
    assert pf.PREFLIGHT_PROFILES["preview-1080p-h264"]["width"] == 1920
    assert pf.PREFLIGHT_PROFILES["preview-1080p-h264"]["height"] == 1080
    assert pf.PROFILE_ENCODERS["master-4k-hevc"] == "libx265"

    ctx = pf.PreflightContext(
        project_id=PROJECT,
        video_item_id=VIDEO,
        source_found=True,
        source_ready=True,
        source_width=3840,
        source_height=2160,
        source_native_4k=False,  # dimensions alone NEVER imply native
        source_frame_count=8,
        profile_supported=True,
        profile_support_basis="seeded",
    )
    assert pf.classify_source_kind(ctx) == "upscale_4k"
    ctx_native = pf.PreflightContext(
        project_id=PROJECT,
        video_item_id=VIDEO,
        source_found=True,
        source_ready=True,
        source_width=3840,
        source_height=2160,
        source_native_4k=True,
        source_frame_count=8,
        profile_supported=True,
        profile_support_basis="seeded",
    )
    assert pf.classify_source_kind(ctx_native) == "native_4k"
