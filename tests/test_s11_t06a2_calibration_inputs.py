"""S11-T06A2 self-test — raw QC calibration fixtures and measurements.

Self-test for the calibration module and committed fixtures this task owns:

- ``tests/s11_qc_calibration_builders.py`` — deterministic calibration
  input generators + raw measurement functions (one function per metric),
  a one-command fixture builder (``build_all_calibration``) that MEASURES
  real raw values (synthetic seeded inputs + REAL ffprobe facts for the
  NO_AUDIO source fact, consuming T06A1 builders read-only) and writes the
  four committed calibration JSON files.
- ``tests/fixtures/s11_qc/calibration/*.json`` — four committed raw
  calibration files covering the 8 overlay reason codes
  (trajectory_drift, cut_drift | contact_break, z_order_error,
  silhouette_clipping | identity_drift, edge_halo, temporal_flicker)
  plus A/V sync drift and the NO_AUDIO source fact.

Boundary (lane-A GAP-4/R2/R6, later-wave owners T03A/T06B): this task
produces RAW input + RAW measurement ONLY.  It never derives policy — the
prohibited vocabulary is checked by the binary scan below as
runtime-assembled patterns, so no calibration file ever contains those
tokens as raw text.

Determinism convention (lane-B §1.1, measured S11): within one machine +
one ffmpeg build the outputs repeat byte-for-byte (asserted ×2 by hash);
no hard cross-machine hash is ever asserted.

Isolation (lane-B §4 + RESOURCE_PLAN §3, measured S11):
- every test builds/measures under the pytest basetemp only; run with a
  SHORT Windows-native ``--basetemp`` + ``-p no:cacheprovider``;
- ``env -u MOTIONFORGE_DATABASE_URL`` at the command line;
- no committed media binary — the NO_AUDIO media is rebuilt at runtime
  via the T06A1 builder into the caller's temp dir;
- a machine-wide msvcrt lock serializes this acceptance harness against
  concurrent suites (RESOURCE_PLAN §3.5, same pattern as S11-T01D C2);
- best-effort cleanup of this module's own temp dirs.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

if sys.platform == "win32":
    import msvcrt  # noqa: F401 - guarded machine-wide lock below

    try:
        import psutil  # noqa: F401
    except ImportError:  # pragma: no cover - non-Windows or slim env
        psutil = None  # type: ignore[assignment]
else:  # pragma: no cover - repo runs on Windows
    psutil = None  # type: ignore[assignment]

from s11_qc_calibration_builders import (
    CALIBRATION_FIXTURES,
    CALIBRATION_REVISION,
    build_all_calibration,
    iter_calibration_fixtures,
    load_calibration_fixture,
    resolve_measurement,
    resolve_source,
)
from s11_qc_media_builders import (
    build_no_audio_source,
    ffmpeg_available,
    probe_facts,
)

pytestmark = pytest.mark.skipif(
    not ffmpeg_available(), reason="ffmpeg/ffprobe not available"
)

#: Machine-wide lock mirroring S11-T01D C2 / T06A1 harness.
_LOCK_PATH = Path(tempfile.gettempdir()) / "s11-t06a2-suite.lock"

#: Temp dirs this module creates beyond pytest-managed ones.
_MODULE_TEMP_DIRS: list[Path] = []

#: Policy vocabulary prohibited in ALL calibration files.  Tokens are
#: assembled at runtime ONLY from per-character string literals, so
#: neither this file nor the scanned files ever contain the raw tokens
#: (or any suspicious sub-token) in their source text.
_BANNED_TOKENS = (
    "t" "h" "r" "e" "s" "h" "o" "l" "d",
    "w" "a" "r" "n" "i" "n" "g",
    "b" "l" "o" "c" "k" "e" "r",
    "s" "e" "v" "e" "r" "i" "t" "y",
    "v" "e" "r" "d" "i" "c" "t",
    "g" "o" "l" "d" "e" "n",
    "e" "x" "p" "e" "c" "t" "e" "d",
    "o" "u" "t" "c" "o" "m" "e",
)
_BANNED_PATTERNS = [
    re.compile(tok, re.IGNORECASE) for tok in _BANNED_TOKENS
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
def fixture_dir(tmp_path: Path) -> Path:
    """Per-test output dir for built calibration fixtures."""
    d = tmp_path / "calibration"
    d.mkdir(parents=True, exist_ok=True)
    _MODULE_TEMP_DIRS.append(d)
    return d


# ── AC1/AC2: coverage of the 8 overlay reason codes + A/V sync / NO_AUDIO ──

def test_calibration_covers_all_eight_overlay_reason_codes(
    fixture_dir: Path,
) -> None:
    """AC1: deterministic raw input + measured raw value for every one of
    the 8 overlay reason codes, partitioned exactly T03B=2 / T03C=3 /
    T03D=3 (production plan C6-F1)."""
    fixtures = list(iter_calibration_fixtures())
    metrics: dict[str, dict[str, Any]] = {}
    for fixture in fixtures:
        for record in metrics_of(fixture):
            name = record["metric"]
            assert name not in metrics, f"duplicate metric {name}"
            metrics[name] = record

    overlay_codes = (
        "trajectory_drift", "cut_drift",
        "contact_break", "z_order_error", "silhouette_clipping",
        "identity_drift", "edge_halo", "temporal_flicker",
    )
    assert set(overlay_codes) <= set(metrics), (
        "missing overlay metric(s): "
        f"{set(overlay_codes) - set(metrics)}"
    )
    # T03B fixture carries exactly its 2 codes; T03C its 3; T03D its 3.
    by_fixture = {
        f["fixture_id"]: {r["metric"] for r in metrics_of(f)}
        for f in fixtures
    }
    assert by_fixture["trajectory_cut"] == {"trajectory_drift", "cut_drift"}
    assert by_fixture["contact_zorder_clipping"] == {
        "contact_break", "z_order_error", "silhouette_clipping",
    }
    assert by_fixture["identity_halo_flicker"] == {
        "identity_drift", "edge_halo", "temporal_flicker",
    }
    for record in metrics.values():
        assert len(record["perturbation_levels"]) >= 3, record["metric"]


def metrics_of(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """Records of one committed fixture."""
    return fixture["metrics"]


def test_calibration_av_sync_and_no_audio_source_fact(
    fixture_dir: Path,
) -> None:
    """AC2: raw boundary measurements for A/V sync and the NO_AUDIO source
    fact (av_sync.json).  The NO_AUDIO fact is MEASURED from real ffprobe
    facts of freshly built T06A1 no-audio media (never invented)."""
    fixture = load_calibration_fixture("av_sync")
    metrics = {r["metric"]: r for r in metrics_of(fixture)}
    av = metrics["av_sync_drift"]
    assert av["unit"] == "s"
    offsets = [lvl["raw_value"] for lvl in av["perturbation_levels"]]
    assert offsets == sorted(offsets) and len(set(offsets)) == len(offsets)

    noa = metrics["no_audio_source_fact"]
    assert noa["unit"] == "count"
    durations: list[float] = []
    for lvl in noa["perturbation_levels"]:
        assert lvl["raw_value"] == 0, (
            "NO_AUDIO source fact must measure zero audio streams"
        )
        durations.append(lvl["measured_duration_sec"])
    assert durations == sorted(durations) and len(set(durations)) == len(
        durations
    ), "NO_AUDIO fact levels must grow with built media duration"
    # Real media measurement: rebuild the T06A1 no-audio media at the
    # first level's duration and re-probe — committed fact must match.
    first = noa["perturbation_levels"][0]
    media_path = build_no_audio_source(
        fixture_dir / "media" / "no_audio_source.mp4",
        duration=first["perturbation"]["duration_sec"],
    )
    facts = probe_facts(media_path)
    audio_streams = [
        s for s in facts["streams"] if s["codec_type"] == "audio"
    ]
    assert len(audio_streams) == 0
    dur = facts["duration_sec"]
    assert dur is not None
    assert abs(dur - first["measured_duration_sec"]) <= 0.35


# ── AC3: every metric record carries the full required field set ──────────

_REQUIRED_RECORD_FIELDS = (
    "metric", "unit", "deterministic_seed",
    "source_reference", "result_reference",
    "measurement_function_revision",
)
_REQUIRED_LEVEL_FIELDS = ("level", "perturbation", "raw_value")


def test_every_metric_record_has_full_required_fields() -> None:
    """AC3: unit / deterministic seed / source+result reference /
    measurement-function revision / raw value — missing ANY one fails."""
    for fixture in iter_calibration_fixtures():
        for record in metrics_of(fixture):
            for field in _REQUIRED_RECORD_FIELDS:
                assert field in record, (
                    f"{fixture['fixture_id']}/{record['metric']}: "
                    f"missing required field {field!r}"
                )
            assert (
                record["measurement_function_revision"] == CALIBRATION_REVISION
            ), record["metric"]
            assert isinstance(record["deterministic_seed"], int)
            assert isinstance(record["unit"], str) and record["unit"]
            levels = record["perturbation_levels"]
            assert isinstance(levels, list) and len(levels) >= 3
            for lvl in levels:
                for field in _REQUIRED_LEVEL_FIELDS:
                    assert field in lvl, (
                        f"{fixture['fixture_id']}/{record['metric']} "
                        f"level {lvl.get('level')}: missing {field!r}"
                    )
                assert isinstance(lvl["raw_value"], (int, float)), (
                    f"{record['metric']} level {lvl['level']}: raw_value "
                    "must be numeric (raw measurement only)"
                )
            # measurement function + source generator must resolve to the
            # real module symbols cited by the record.
            measure = resolve_measurement(record["result_reference"])
            source = resolve_source(record["source_reference"])
            assert callable(measure), record["result_reference"]
            assert callable(source), record["source_reference"]


# ── AC4: zero policy vocabulary in every calibration file (binary scan) ───

_CALIBRATION_FILES_TO_SCAN = (
    Path(__file__).resolve().parent / "s11_qc_calibration_builders.py",
) + tuple(
    sorted(
        (Path(__file__).resolve().parent / "fixtures" / "s11_qc"
         / "calibration").glob("*.json")
    )
) + (Path(__file__).resolve(),)


def test_zero_policy_vocabulary_scan() -> None:
    """AC4: ZERO policy tokens in builders + committed calibration JSON +
    this self-test.  Binary scan of the raw file bytes (not just JSON
    keys); tokens are checked as runtime-assembled patterns."""
    for path in _CALIBRATION_FILES_TO_SCAN:
        assert path.exists(), f"calibration file missing: {path}"
        text = path.read_text(encoding="utf-8")
        for pattern in _BANNED_PATTERNS:
            match = pattern.search(text)
            assert match is None, (
                f"{path.name}: banned policy token {match.group(0)!r} "
                f"at byte {match.start()}"
            )


# ── AC5: >= 3 perturbation levels + deterministic / monotonic self-test ───

def test_perturbation_levels_monotonic_and_deterministic(
    fixture_dir: Path,
) -> None:
    """AC5: every metric has >= 3 perturbation levels, raw values move
    monotonically (strictly in the declared direction, or constant for a
    source fact), and the raw value is REPRODUCED by re-running the real
    measurement on the deterministic seeded input (same input -> same raw
    value)."""
    for fixture in iter_calibration_fixtures():
        for record in metrics_of(fixture):
            name = record["metric"]
            levels = record["perturbation_levels"]
            assert len(levels) >= 3, name
            direction = record.get("monotonic")
            assert direction in ("increasing", "decreasing", "constant"), name
            raw = [lvl["raw_value"] for lvl in levels]
            if direction == "increasing":
                assert all(b > a for a, b in zip(raw, raw[1:])), (
                    f"{name}: raw values not strictly increasing: {raw}"
                )
            elif direction == "decreasing":
                assert all(b < a for a, b in zip(raw, raw[1:])), (
                    f"{name}: raw values not strictly decreasing: {raw}"
                )
            else:
                assert all(b == a for a, b in zip(raw, raw[1:])), (
                    f"{name}: constant raw values drifted: {raw}"
                )
            # deterministic re-measurement: replay each level's perturbation
            # through the cited source generator + measurement function.
            for lvl in levels:
                source = resolve_source(record["source_reference"])
                measure = resolve_measurement(record["result_reference"])
                replay = measure(
                    source(
                        seed=record["deterministic_seed"],
                        **lvl["perturbation"],
                    )
                )
                assert abs(float(replay) - float(lvl["raw_value"])) < 1e-9, (
                    f"{name} level {lvl['level']}: replay raw {replay} "
                    f"!= committed raw {lvl['raw_value']}"
                )


# ── AC6: two builds -> identical output (hash) ────────────────────────────

def test_two_builds_identical_hashes(fixture_dir: Path) -> None:
    """AC6: build the complete calibration dataset twice into fresh dirs;
    every file's sha256 must be identical across the two runs AND equal to
    the committed fixture bytes (determinism ×2, byte-exact)."""
    run1 = build_all_calibration(fixture_dir / "run1")
    run2 = build_all_calibration(fixture_dir / "run2")
    _MODULE_TEMP_DIRS.append(run1[list(run1)[0]].parent)
    _MODULE_TEMP_DIRS.append(run2[list(run2)[0]].parent)
    assert set(run1) == set(run2) == set(CALIBRATION_FIXTURES)
    for fixture_id in CALIBRATION_FIXTURES:
        h1 = _sha256(run1[fixture_id])
        h2 = _sha256(run2[fixture_id])
        assert h1 == h2, (
            f"{fixture_id}: build hashes differ "
            f"(run1 {h1[:16]} != run2 {h2[:16]})"
        )
        # committed fixture must be byte-identical to the rebuilt one
        committed = (
            Path(__file__).resolve().parent / "fixtures" / "s11_qc"
            / "calibration" / f"{fixture_id}.json"
        )
        assert _sha256(committed) == h1, (
            f"{fixture_id}: committed fixture drifted from deterministic "
            "builder output"
        )


# ── schema / hygiene ──────────────────────────────────────────────────────

def test_calibration_fixture_schema_and_json_parse() -> None:
    """Committed fixtures parse, carry the frozen schema, and stay fully
    deterministic (sorted serialization, no float noise)."""
    for fixture_id in CALIBRATION_FIXTURES:
        doc = load_calibration_fixture(fixture_id)
        assert doc["fixture_type"] == "s11_qc_calibration"
        assert doc["schema_version"] == 1
        assert isinstance(doc["metrics"], list) and doc["metrics"]
        for record in metrics_of(doc):
            assert record["unit"] in {
                "px", "frame", "count", "ratio", "s", "level",
            }, record
            for lvl in record["perturbation_levels"]:
                json.dumps(lvl["raw_value"])  # serializable
        # round-trip stability: parse -> dump sorted -> parse again equal
        serialized = json.dumps(doc, sort_keys=True, indent=2,
                                ensure_ascii=False)
        assert json.loads(serialized) == doc


@pytest.mark.skipif(psutil is None, reason="psutil not available")
def test_no_orphan_ffmpeg_processes(fixture_dir: Path) -> None:
    """Process hygiene (RESOURCE_PLAN §4): building + measuring the whole
    calibration dataset (incl. the real T06A1 no-audio media build) leaves
    zero ffmpeg/ffprobe survivors."""
    def _ffmpeg_pids() -> set[int]:
        return {
            p.pid
            for p in psutil.process_iter(["name"])  # type: ignore[union-attr]
            if (p.info.get("name") or "").lower().startswith(
                ("ffmpeg", "ffprobe")
            )
        }

    baseline = _ffmpeg_pids()
    build_all_calibration(fixture_dir / "hygiene")
    time.sleep(1.0)
    survivors = _ffmpeg_pids() - baseline
    assert survivors == set(), f"orphan ffmpeg/ffprobe processes: {survivors}"