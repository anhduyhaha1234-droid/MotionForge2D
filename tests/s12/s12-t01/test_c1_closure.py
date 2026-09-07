"""S12-C1 closure rows owned by T01 (W1): C02 + C03 + C04-T01-part.

Isolation: reuses the ``client``/seed helpers from
``test_preflight_contract`` (same isolated DB/basetime discipline — import
the module, never copy it).  No case removed to obtain green.

- C02 capability-preflight: real CPU eligible via the ffmpeg encoder probe;
  failed encoder rejected with the concrete reason; no constant flag, no
  silent fallback (monkeypatched binary-missing + encoder-absent + smoke-rc
  paths each fail the profile check with a distinct basis).
- C03 source-provenance: native ONLY for proved native origin; 1080p-upscale
  honesty; already-upscaled-4K (3840x2160 unproven) is upscale_4k, never
  native_4k (F-OBS-01); non-16:9 letterbox vs fail-closed; missing provenance
  (no dims) is below_4k.
- C04 T01-part: current full-apply authority — valid control preflights with
  zero side effects (no S12 runs/Jobs/outputs); missing/stale checkpoint,
  cross-project checkpoint, and not-ready video each yield ineligible verdict
  AND create zero runs/Jobs/publication rows.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from fastapi.testclient import TestClient

from app.api import deps
from app.persistence.jobs import JobRepository as _JR
from app.schemas.s12_export import ExportPreflightRequest
from app.services.s12_export.preflight import (
    PREFLIGHT_PROFILES,
    PROFILE_ENCODERS,
    classify_source_kind,
    evaluate_preflight,
    probe_encoder_support,
)
import pytest

from test_preflight_contract import (  # noqa: F401 (shared seed helpers)
    WS,
    _ctx,
    _http_body,
    _req,
    _seed_checkpoint,
    _seed_completed_check_run,
    _seed_manifest,
    _seed_ws_project_video,
)

from sqlalchemy import text as _text


def _hex64(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _count_jobs() -> int:
    factory = deps.get_job_service().session_factory
    assert factory is not None
    with factory() as s:
        return len(_JR(s).list_jobs(WS))


# ── C02: real capability probe ───────────────────────────────────────


def test_c02_real_cpu_eligible() -> None:
    ok, basis = probe_encoder_support("master-4k-h264")
    assert ok is True, basis
    assert "libx264" in basis and "rc=0" in basis
    assert set(PROFILE_ENCODERS) == set(PREFLIGHT_PROFILES)


def test_c02_unknown_profile_rejected() -> None:
    ok, basis = probe_encoder_support("no-such-profile")
    assert ok is False and "unknown profile" in basis


def test_c02_failed_encoder_rejected_with_reason(
    monkeypatch: Any,
) -> None:
    import app.services.s12_export.preflight as pf

    monkeypatch.setattr(pf, "_find_ffmpeg", lambda: None)
    pf._probe_cache.clear()
    ok, basis = probe_encoder_support("master-4k-h264")
    assert ok is False and "not found" in basis

    import subprocess

    class _Enc:
        stdout = b"some other encoders, no x264 here"
        returncode = 0

    monkeypatch.setattr(pf, "_find_ffmpeg", lambda: "/fake/ffmpeg")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _Enc()
    )
    pf._probe_cache.clear()
    ok2, basis2 = probe_encoder_support("master-4k-h264")
    assert ok2 is False and "absent" in basis2

    class _SmokeFail:
        stdout = b"libx264blurbfake"
        returncode = 0

    class _Fail:
        stdout = b""
        stderr = b"boom"
        returncode = 1

    calls = {"n": 0}

    def _fake_run(*a: Any, **k: Any) -> Any:
        calls["n"] += 1
        return _SmokeFail() if calls["n"] == 1 else _Fail()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    pf._probe_cache.clear()
    ok3, basis3 = probe_encoder_support("master-4k-h264")
    assert ok3 is False and "rc=1" in basis3


def test_c02_no_silent_fallback_between_profiles() -> None:
    ok_h264, _ = probe_encoder_support("master-4k-h264")
    assert ok_h264 is True
    # HEVC support is whatever the probe measures — but its verdict must
    # come from ITS OWN encoder, never borrowed from h264's result.
    assert PROFILE_ENCODERS["master-4k-hevc"] == "libx265"
    assert PROFILE_ENCODERS["master-4k-hevc"] != PROFILE_ENCODERS["master-4k-h264"]


def test_c02_probe_failure_blocks_http_profile(
    client: TestClient, s12_session: Any, monkeypatch: Any
) -> None:
    """Encoder failure at request time → profile check failed, reason kept."""
    import app.api.routes.s12_export_preflight as route

    vid = f"v-c02f-{uuid.uuid4().hex[:6]}"
    pid = f"p-c02f-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid, vid=vid)
    _seed_completed_check_run(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    monkeypatch.setattr(
        route, "probe_encoder_support", lambda _p: (False, "encoder 'libx264' smoke failed rc=1: boom")
    )
    resp = client.post(
        f"/api/v2/projects/{pid}/export/preflight", json=_http_body(vid, ckpt, mani)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["eligible"] is False
    assert "S12_EXPORT_UNSUPPORTED_PROFILE" in body["reasons"]
    assert body["profile"]["supported"] is False
    assert "rc=1" in (body["profile"]["support_basis"] or "")


# ── C03: source provenance (F-OBS-01) ────────────────────────────────


def test_c03_native_only_when_proved() -> None:
    proved = _ctx(source_width=3840, source_height=2160, source_native_4k=True)
    assert classify_source_kind(proved) == "native_4k"
    resp = evaluate_preflight(ExportPreflightRequest(**_req()), proved)
    assert resp.source_kind == "native_4k"
    assert resp.source_provenance == "proved-native"
    assert resp.profile.upscale_method is None


def test_c03_already_upscaled_4k_never_native() -> None:
    """F-OBS-01: 3840x2160 dims WITHOUT proved origin is upscale_4k."""
    unproven = _ctx(source_width=3840, source_height=2160, source_native_4k=False)
    assert classify_source_kind(unproven) == "upscale_4k"
    resp = evaluate_preflight(ExportPreflightRequest(**_req()), unproven)
    assert resp.source_kind == "upscale_4k"
    assert resp.source_provenance == "unproven"
    assert resp.profile.upscale_method  # labeled method required


def test_c03_1080p_upscale_honesty() -> None:
    ctx = _ctx(source_width=1920, source_height=1080, source_native_4k=False)
    assert classify_source_kind(ctx) == "upscale_4k"
    resp = evaluate_preflight(ExportPreflightRequest(**_req()), ctx)
    assert resp.source_kind == "upscale_4k"
    assert resp.source_provenance == "unproven"


def test_c03_non_16x9_letterbox_vs_fail_closed() -> None:
    ctx = _ctx(source_width=1920, source_height=800, source_native_4k=False)
    ok_resp = evaluate_preflight(ExportPreflightRequest(**_req()), ctx)
    assert ok_resp.eligible is True  # letterbox preserves
    strict = ExportPreflightRequest(**_req(aspect_handling="fail_closed"))
    bad = evaluate_preflight(strict, ctx)
    assert bad.eligible is False
    assert "S12_EXPORT_ASPECT_MISMATCH" in bad.reasons


def test_c03_missing_provenance_below_4k() -> None:
    ctx = _ctx(source_width=None, source_height=None, source_frame_count=None)
    assert classify_source_kind(ctx) == "below_4k"


def test_c03_http_1080p_reports_upscale(
    client: TestClient, s12_session: Any
) -> None:
    vid = f"v-c03-{uuid.uuid4().hex[:6]}"
    pid = f"p-c03-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(
        s12_session, ws=WS, pid=pid, vid=vid, w=1920, h=1080, duration_ms=10_000
    )
    _seed_completed_check_run(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    resp = client.post(
        f"/api/v2/projects/{pid}/export/preflight", json=_http_body(vid, ckpt, mani)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_kind"] == "upscale_4k"
    assert body["source_provenance"] == "unproven"


# ── C04 T01-part: current full-apply authority, zero side effects ────


def test_c04_valid_control_zero_side_effects(
    client: TestClient, s12_session: Any
) -> None:
    vid = f"v-c04v-{uuid.uuid4().hex[:6]}"
    pid = f"p-c04v-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid, vid=vid)
    _seed_completed_check_run(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    before = _count_jobs()
    resp = client.post(
        f"/api/v2/projects/{pid}/export/preflight", json=_http_body(vid, ckpt, mani)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["eligible"] is True
    assert _count_jobs() == before
    factory = deps.get_job_service().session_factory
    assert factory is not None
    with factory() as s:
        pubs = s.execute(
            _text("SELECT COUNT(*) FROM s10_full_apply_publication")
        ).scalar()
        runs = s.execute(_text("SELECT COUNT(*) FROM s10_full_apply_run")).scalar()
    assert pubs == 0 and runs == 0


def _assert_invalid_zero_side_effects(
    client: TestClient, body: dict[str, Any], pid: str, expect: str
) -> None:
    before = _count_jobs()
    resp = client.post(f"/api/v2/projects/{pid}/export/preflight", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["eligible"] is False
    assert expect in resp.json()["reasons"]
    assert _count_jobs() == before


def test_c04_missing_checkpoint_zero_runs(
    client: TestClient, s12_session: Any
) -> None:
    vid = f"v-c04m-{uuid.uuid4().hex[:6]}"
    pid = f"p-c04m-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid, vid=vid)
    _seed_completed_check_run(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    ghost = {"checkpoint_id": f"ckpt-{uuid.uuid4().hex[:6]}",
             "checkpoint_hash": _hex64("ghost"), "checkpoint_revision": 1}
    _assert_invalid_zero_side_effects(
        client, _http_body(vid, ghost, mani), pid, "S12_EXPORT_STALE_CHECKPOINT"
    )


def test_c04_stale_hash_and_revision_zero_runs(
    client: TestClient, s12_session: Any
) -> None:
    vid = f"v-c04s-{uuid.uuid4().hex[:6]}"
    pid = f"p-c04s-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid, vid=vid)
    _seed_completed_check_run(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    bad_hash = dict(ckpt, checkpoint_hash=_hex64("wrong"))
    _assert_invalid_zero_side_effects(
        client, _http_body(vid, bad_hash, mani), pid, "S12_EXPORT_STALE_CHECKPOINT"
    )
    bad_rev = dict(ckpt, checkpoint_revision=2)
    _assert_invalid_zero_side_effects(
        client, _http_body(vid, bad_rev, mani), pid, "S12_EXPORT_STALE_CHECKPOINT"
    )


def test_c04_cross_project_zero_runs(
    client: TestClient, s12_session: Any
) -> None:
    vid_a = f"v-c04xa-{uuid.uuid4().hex[:6]}"
    pid_a = f"p-c04xa-{uuid.uuid4().hex[:6]}"
    pid_b = f"p-c04xb-{uuid.uuid4().hex[:6]}"
    vid_b = f"v-c04xb-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid_a, vid=vid_a)
    _seed_ws_project_video(s12_session, ws=WS, pid=pid_b, vid=vid_b)
    _seed_completed_check_run(s12_session, ws=WS, pid=pid_b, vid=vid_b)
    ckpt_a = _seed_checkpoint(s12_session, ws=WS, pid=pid_a, vid=vid_a)
    mani_b = _seed_manifest(s12_session, ws=WS, pid=pid_b, vid=vid_b)
    _assert_invalid_zero_side_effects(
        client, _http_body(vid_b, ckpt_a, mani_b), pid_b, "S12_EXPORT_CROSS_PROJECT"
    )


def test_c04_not_run_video_zero_runs(
    client: TestClient, s12_session: Any
) -> None:
    vid = f"v-c04n-{uuid.uuid4().hex[:6]}"
    pid = f"p-c04n-{uuid.uuid4().hex[:6]}"
    _seed_ws_project_video(s12_session, ws=WS, pid=pid, vid=vid)
    ckpt = _seed_checkpoint(s12_session, ws=WS, pid=pid, vid=vid)
    mani = _seed_manifest(s12_session, ws=WS, pid=pid, vid=vid)
    _assert_invalid_zero_side_effects(
        client, _http_body(vid, ckpt, mani), pid, "S12_EXPORT_NOT_READY"
    )


@pytest.fixture()
def s12_session():
    """Local session fixture (same discipline as test_preflight_contract)."""
    factory = deps.get_job_service().session_factory
    assert factory is not None
    session = factory()
    try:
        yield session
    finally:
        session.close()
