"""S11-T06A1 self-test harness — deterministic media/QC seed infrastructure.

Self-test for the two fixture modules this task owns:

- ``tests/s11_qc_media_builders.py`` — deterministic ffmpeg-lavfi media
  builders (two_scene_source, multistream duration-variant, non-MP4/vp9/
  mpeg4 negatives, corrupt truncate, no_audio) that assert their own
  output with real ffprobe right after building (lane-B TEST_FIXTURE_PLAN
  §3.4) and expose a ONE-COMMAND dataset build (acceptance criterion 1).
- ``tests/s11_qc_seed.py`` — repository-fixture seeding (Decision A: no
  HTTP POST) of QCItems through ``QCItemRepository`` with a deterministic
  7-column natural key, idempotent re-runs, and minimal valid evidence
  (acceptance criterion 3).

The 7 media manifests under ``tests/fixtures/s11_qc/media_manifests/`` are
the committed description of each scenario: builder + params, cross-machine
stable probe expectations (codec names / stream counts / duration with
tolerance — NEVER hard byte hashes, lane-B §1.1) and the deterministic
seed plan for that scenario.  Negative scenarios (unsupported container/
codec, corrupt, no-audio) carry an EMPTY seed plan: the engine rejects the
media at import, so zero QCItems are seedable against them (production plan
W7 note: no_audio_source → zero QCItem created).

Isolation (lane-B TEST_FIXTURE_PLAN §4 + RESOURCE_PLAN §3, measured S11):
- every test builds/creates under the pytest basetemp only; this file is
  run with a SHORT Windows-native ``--basetemp`` (pid+seq unique) and
  ``-p no:cacheprovider`` (frozen command in LOG/REPORT);
- ``env -u MOTIONFORGE_DATABASE_URL`` at the command line + the conftest
  ``_patch_project_root`` fixture for every seed test (alembic upgrade
  head into a per-test temp SQLite, never ``data/motionforge.db``);
- a machine-wide msvcrt lock serializes concurrent acceptance harnesses
  (RESOURCE_PLAN §3.5 — same pattern as S11-T01D C2);
- process hygiene: ownership-scoped ffmpeg/ffprobe pid scan around the
  whole build (lane-B §4.4) — zero orphan survivors;
- best-effort cleanup of this module's own temp dirs (ignore_errors,
  Windows handle lag) so basetemp never orphans.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.models import QC_ITEM_SEVERITIES, QC_REASON_CODES
from app.persistence.qc_items import QCItemRecord

from s11_qc_media_builders import (
    MEDIA_SCENARIOS,
    build_all_media,
    ffmpeg_available,
    ffprobe,
    iter_manifests,
    load_manifest,
    probe_facts,
)
from s11_qc_seed import (
    count_qc_items,
    list_qc_items,
    seed_all_reason_codes,
    seed_qc_items_for_manifest,
    seed_workspace_project_video,
)

pytestmark = pytest.mark.skipif(
    not ffmpeg_available(), reason="ffmpeg/ffprobe not available"
)

if sys.platform == "win32":
    import msvcrt  # noqa: F401 - guarded machine-wide lock below

    try:
        import psutil  # noqa: F401
    except ImportError:  # pragma: no cover - non-Windows or slim env
        psutil = None  # type: ignore[assignment]
else:  # pragma: no cover - repo runs on Windows
    psutil = None  # type: ignore[assignment]

#: Machine-wide lock mirroring S11-T01D C2: serializes this acceptance
#: harness against any other concurrent acceptance harness on the machine.
_LOCK_PATH = Path(tempfile.gettempdir()) / "s11-t06a1-suite.lock"

#: Temp dirs this module creates beyond pytest-managed ones; best-effort
#: rmtree at session end (Windows handle lag → ignore_errors).
_MODULE_TEMP_DIRS: list[Path] = []


@pytest.fixture(scope="session", autouse=True)
def _suite_lock() -> Any:
    """Machine-wide msvcrt lock + best-effort module temp cleanup."""
    handle = None
    if sys.platform == "win32":
        handle = open(_LOCK_PATH, "a+")  # noqa: SIM115 - fd lifecycle below
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(0.25)
    try:
        yield
    finally:
        if handle is not None:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            handle.close()
        for d in _MODULE_TEMP_DIRS:
            shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def media_dir(tmp_path: Path) -> Path:
    """Per-test media output dir under the short pytest basetemp."""
    d = tmp_path / "media"
    d.mkdir(parents=True, exist_ok=True)
    _MODULE_TEMP_DIRS.append(d)
    return d


# ── manifest <-> media verification helpers ───────────────────────────────

def _assert_media_matches_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Assert REAL probe facts of a freshly built file against the commit-
    ed manifest's cross-machine-stable expectations (codecs/stream counts/
    duration-with-tolerance; never hard hashes)."""
    scenario = manifest["scenario"]
    expectation = manifest["probe_expectations"]
    facts = probe_facts(path, allow_error=True)
    assert facts["probe_ok"], (
        f"scenario {scenario}: expected probeable media at {path}, "
        f"probe failed: {facts.get('probe_error', '?')}"
    )
    assert facts["size_bytes"] > 0
    assert expectation["format_name_contains"] in facts["format_name"]
    duration = facts["duration_sec"]
    assert abs(duration - expectation["duration_sec"]) <= expectation[
        "duration_tolerance_sec"
    ], (
        f"scenario {scenario}: duration {duration} deviates from "
        f"{expectation['duration_sec']} ± {expectation['duration_tolerance_sec']}"
    )
    for wanted in expectation["streams"]:
        actual = [
            s
            for s in facts["streams"]
            if s["codec_type"] == wanted["codec_type"]
            and s["codec_name"] == wanted["codec_name"]
        ]
        assert len(actual) == wanted["count"], (
            f"scenario {scenario}: expected {wanted['count']} "
            f"{wanted['codec_type']}/{wanted['codec_name']} stream(s), "
            f"got {len(actual)}"
        )


def _assert_corrupt_matches_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Corrupt media expectation: ffprobe MUST reject the file (measured
    on this machine: middle-truncate → 'moov atom not found', probe rc=1)."""
    scenario = manifest["scenario"]
    expectation = manifest["probe_expectations"]
    assert expectation.get("probe_must_fail") is True, scenario
    assert path.exists() and path.stat().st_size > 0
    facts = probe_facts(path, allow_error=True)
    assert facts["probe_ok"] is False, (
        f"scenario {scenario}: corrupt file must NOT probe cleanly"
    )
    assert "moov atom not found" in facts["probe_error"].lower() or "invalid data" in (
        facts["probe_error"].lower()
    ), f"scenario {scenario}: unexpected probe error: {facts['probe_error']}"


def _build_dataset(dest: Path) -> dict[str, Path]:
    """Acceptance criterion 1: ONE command builds the whole media dataset."""
    files = build_all_media(dest)
    assert set(files) == set(MEDIA_SCENARIOS)
    return files


# ── media builders ─────────────────────────────────────────────────────────

def test_manifests_load_and_schema() -> None:
    """All 7 manifests exist, parse, and carry the frozen schema."""
    loaded = list(iter_manifests())
    assert [m["scenario"] for m in loaded] == list(MEDIA_SCENARIOS)
    for manifest in loaded:
        scenario = manifest["scenario"]
        assert manifest["manifest_version"] == 1
        assert manifest["manifest_type"] == "s11_qc_media_manifest"
        media = manifest["media"]
        assert callable(getattr(__import__("s11_qc_media_builders"), media["builder"])), (
            f"{scenario}: builder {media['builder']} must resolve"
        )
        assert media["relative_path"].startswith("media/")
        assert isinstance(media["relative_path"], str)
        pe = manifest["probe_expectations"]
        if pe.get("probe_must_fail"):
            assert "format_name_contains" not in pe
        else:
            assert isinstance(pe.get("format_name_contains"), str)
        assert isinstance(pe.get("duration_sec", 0.0), (int, float))
        plan = manifest["seed_plan"]
        codes = plan["reason_codes"]
        assert isinstance(codes, list)
        assert set(codes) <= set(QC_REASON_CODES)
        assert plan["severity"] in QC_ITEM_SEVERITIES
        assert json.dumps(manifest, sort_keys=True)  # serializable


def test_build_all_media_dataset_matches_manifests(media_dir: Path) -> None:
    """One-command dataset build; every file re-probed and matched against
    its manifest's probe expectations (builders already assert internally;
    this is the independent harness re-check)."""
    files = _build_dataset(media_dir)
    for scenario, path in files.items():
        manifest = load_manifest(scenario)
        if manifest["probe_expectations"].get("probe_must_fail"):
            _assert_corrupt_matches_manifest(path, manifest)
        else:
            _assert_media_matches_manifest(path, manifest)


def test_determinism_two_runs_identical_probe_facts(tmp_path: Path) -> None:
    """Determinism ×2: build the whole dataset twice into fresh dirs; both
    runs must yield IDENTICAL probe facts (codec/duration/streams) and
    identical file sizes.  No hard cross-machine hash is asserted — the
    comparison is within this machine, this ffmpeg build (lane-B §1.1)."""
    run1 = _build_dataset(tmp_path / "run1")
    run2 = _build_dataset(tmp_path / "run2")
    _MODULE_TEMP_DIRS.append(run1[next(iter(run1))].parent)
    _MODULE_TEMP_DIRS.append(run2[next(iter(run2))].parent)
    for scenario in MEDIA_SCENARIOS:
        facts1 = probe_facts(run1[scenario], allow_error=True)
        facts2 = probe_facts(run2[scenario], allow_error=True)
        assert facts1 == facts2, (
            f"scenario {scenario}: probe facts differ between two "
            f"deterministic builds: {facts1} != {facts2}"
        )
    # dirty-buffer determinism: second run must not reuse ANY byte.
    # Exception: the Matroska muxer injects a RANDOM SegmentUID per
    # muxing, so byte-identity is structurally impossible for the mkv
    # scenario — its determinism contract is probe facts + size equality
    # (asserted above).  All six MP4 scenarios must be byte-identical.
    for scenario in MEDIA_SCENARIOS:
        if scenario == "unsupported_non_mp4":
            continue
        assert run1[scenario].read_bytes() == run2[scenario].read_bytes(), (
            f"scenario {scenario}: byte content differs across runs"
        )


def test_corrupt_truncate_decode_rejected(media_dir: Path) -> None:
    """Corrupt media is not decodable — fail-closed at the engine boundary.
    (ffprobe error is asserted in the manifest check; this proves ffmpeg
    itself rejects the truncated file, the engine's import precondition.)"""
    corrupt = build_all_media(media_dir)["corrupt_truncate"]
    result = subprocess.run(
        [ffprobe(), "-v", "error", "-show_format", str(corrupt)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0, (
        f"corrupt file must not probe cleanly; stderr: {result.stderr[:300]}"
    )


# ── seed infrastructure (repository-fixture, Decision A) ───────────────────

def _fresh_seed_engine(_patch_project_root: Path) -> Any:
    """Engine bound to the conftest-patched temp SQLite (alembic head)."""
    return create_engine_for_path(_patch_project_root / "data" / "test.db")


WS = "ws-t06a1-seed"
PID = "p-t06a1-seed"
VID = "v-t06a1-seed"


def test_seed_every_reason_code_via_repository(_patch_project_root: Path) -> None:
    """Acceptance criterion 3: one seed call creates a QCItem for EVERY
    reason_code through the QCItemRepository (never HTTP POST), with
    minimal valid evidence, on a fresh temp SQLite."""
    engine = _fresh_seed_engine(_patch_project_root)
    factory = create_session_factory(engine)
    with factory() as session:
        seed_workspace_project_video(
            session, workspace_id=WS, project_id=PID, video_item_id=VID
        )
        records = seed_all_reason_codes(
            session,
            workspace_id=WS,
            project_id=PID,
            video_item_id=VID,
        )
        assert len(records) == len(QC_REASON_CODES)
        assert {r.reason_code for r in records} == set(QC_REASON_CODES)
        for record in records:
            assert isinstance(record, QCItemRecord)
            assert record.status == "open"
            assert record.workspace_id == WS
            assert record.layer_ref_type == "video_item"
            assert record.layer_ref_id == VID
            assert isinstance(record.evidence, dict) and len(record.evidence) > 0
            assert record.evidence["schema_version"] == 1
            assert record.evidence["seed_source"] == "s11_qc_seed"
        session.commit()
        assert count_qc_items(session) == len(QC_REASON_CODES)


def test_seed_idempotent_natural_key_reuse(_patch_project_root: Path) -> None:
    """Repeated seeding reuses the same rows via the 7-column natural key:
    identical ids, stable count, first evidence preserved (C4-F1)."""
    engine = _fresh_seed_engine(_patch_project_root)
    factory = create_session_factory(engine)
    with factory() as session:
        seed_workspace_project_video(
            session, workspace_id=WS, project_id=PID, video_item_id=VID
        )
        first = seed_all_reason_codes(
            session, workspace_id=WS, project_id=PID, video_item_id=VID
        )
        session.commit()
        first_ids = {r.id for r in first}
        first_evidence = {r.reason_code: r.evidence for r in first}

        second = seed_all_reason_codes(
            session, workspace_id=WS, project_id=PID, video_item_id=VID
        )
        session.commit()
        assert {r.id for r in second} == first_ids
        assert count_qc_items(session) == len(QC_REASON_CODES)
        for record in second:
            assert record.evidence == first_evidence[record.reason_code]


def test_seed_from_manifest_plans_negative_scenarios_empty(
    _patch_project_root: Path,
) -> None:
    """Each manifest's seed plan seeds exactly its reason codes (idempotent);
    negative scenarios (container/codec unsupported, corrupt, no-audio) seed
    ZERO items — engine rejects the media at import (W7: no_audio_source →
    zero QCItem created)."""
    engine = _fresh_seed_engine(_patch_project_root)
    factory = create_session_factory(engine)
    with factory() as session:
        seed_workspace_project_video(
            session, workspace_id=WS, project_id=PID, video_item_id=VID
        )
        cumulative = 0
        for manifest in iter_manifests():
            scenario = manifest["scenario"]
            expected = len(manifest["seed_plan"]["reason_codes"])
            records = seed_qc_items_for_manifest(
                session,
                manifest,
                workspace_id=WS,
                project_id=PID,
                video_item_id=VID,
            )
            assert len(records) == expected, scenario
            session.commit()
            cumulative += expected
            assert count_qc_items(session) == cumulative, scenario
            # idempotent re-seed: same plan, same natural keys → stable
            again = seed_qc_items_for_manifest(
                session,
                manifest,
                workspace_id=WS,
                project_id=PID,
                video_item_id=VID,
            )
            session.commit()
            assert {r.id for r in again} == {r.id for r in records}
            assert count_qc_items(session) == cumulative
        listed = list_qc_items(session, workspace_id=WS)
        assert len(listed) == cumulative


@pytest.mark.skipif(psutil is None, reason="psutil not available")
def test_no_orphan_ffmpeg_processes(media_dir: Path) -> None:
    """Ownership-scoped process hygiene (RESOURCE_PLAN §4): building the
    whole dataset must not leave ANY ffmpeg/ffprobe survivor behind."""
    def _ffmpeg_pids() -> set[int]:
        return {
            p.pid
            for p in psutil.process_iter(["name"])  # type: ignore[union-attr]
            if (p.info.get("name") or "").lower().startswith(("ffmpeg", "ffprobe"))
        }

    baseline = _ffmpeg_pids()
    _build_dataset(media_dir)
    time.sleep(1.0)  # allow any straggler to exit
    survivors = _ffmpeg_pids() - baseline
    assert survivors == set(), f"orphan ffmpeg/ffprobe processes: {survivors}"