"""S11-T03B trajectory_drift + cut_drift detector acceptance tests (W6).

Contract under test (binding S11_T02_T06_PRODUCTION_PLAN REV7/C6, W6·T03B):

1. Both detectors register through the T03A registry (``register_detector``
   at import) with entry point ``<module>:detect``; the T03A bounded runner
   can execute them in a child process.
2. Thresholds are consumed READ-ONLY from the frozen policy
   (``thresholds.classify`` / ``get_threshold``) — boundaries are NEVER
   hard-coded in the detector: changing the boundary in a policy TEST-COPY
   changes the outcome (proven per detector).
3. trajectory_drift (visual): mean absolute horizontal deviation of the
   rendered (observed) path from the fixture's reference (ground-truth)
   path over the window; blocker/warning items carry
   reason_code=category=trajectory_drift and severity from the policy
   boundary (blocker >= 126.0 px, warning >= 31.5 px, else pass).
4. cut_drift (timecode): render cut points in MS are converted to frames
   THROUGH CanonicalTimebase exact Fraction arithmetic (``nearest_frame``)
   and compared to scene_detector ground-truth scene boundary frames
   (``cuts_to_scenes`` / ``scene_ms_range`` consumed); drift in frames is
   classified against the cut_drift policy (blocker >= 12 frames, warning
   >= 3 frames, else pass) — items are category=cut_drift.
5. Evidence is schema_version=1 and content-derived ONLY (artifact
   content hashes, window, measured values, policy id/boundaries): two
   runs over the same inputs produce byte-identical evidence JSON and the
   same natural-key window (repository create is idempotent — recheck
   reuses the same row).
6. Fail-closed: malformed inputs raise the detector's stable
   QC_*_INVALID_ARGS error; measurements outside the calibrated envelope
   raise QC_*_MEASUREMENT_INVALID (THRESHOLD_INVALID) — no item is ever
   fabricated.

Isolation: short Windows-native basetemp (invoked per run), -p
no:cacheprovider, env strips MOTIONFORGE_DATABASE_URL (the DB is a fresh
per-test temp SQLite built from ORM metadata).  Media fixture facts come
from the T06A1 committed manifest (two_scene_source — known cut boundary)
and trajectory fixtures from the T06A2 calibration generators — all
consumed read-only.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.persistence import create_engine_for_path
from app.persistence.models import Base
from app.persistence.qc_items import QCItemRecord
from app.services.qc_checks import (
    STATUS_BLOCKER,
    STATUS_PASS,
    STATUS_WARNING,
    classify,
    get_detector,
    registry,
    run_detector,
)
from app.services.qc_checks import thresholds as thresholds_mod
from app.services.qc_checks.thresholds import load_policy as _FROZEN_LOAD_POLICY
from app.services.qc_checks.cut_drift import (
    DetectorError as CutDriftDetectorError,
    create_qc_items as create_cut_drift_qc_items,
    detect as cut_drift_detect,
)
from app.services.qc_checks.trajectory_drift import (
    DetectorError as TrajectoryDriftDetectorError,
    create_qc_items as create_trajectory_drift_qc_items,
    detect as trajectory_drift_detect,
)
from app.services.scene_detector import cuts_to_scenes, scene_ms_range
from app.services.timebase import CanonicalTimebase
from s11_qc_calibration_builders import generate_trajectory_drift_input
from s11_qc_media_builders import load_manifest
from s11_qc_seed import seed_workspace_project_video

WS = "ws-s11-t03b"
P1 = "p-s11-t03b"
V1 = "v-s11-t03b"

#: Frozen policy boundaries (T03A, derived from T06A2 raw values) — the
#: tests reference them via the policy API, never as detector constants.
TRAJ_WARNING = 31.5
TRAJ_BLOCKER = 126.0
CUT_WARNING = 3
CUT_BLOCKER = 12


# ── helpers ─────────────────────────────────────────────────────────────────

def _fresh_engine(tmp_path: Path, name: str = "t03b.db") -> Any:
    engine = create_engine_for_path(tmp_path / name)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_workspace_project_video(
            session, workspace_id=WS, project_id=P1, video_item_id=V1
        )
        session.commit()
    return engine


def _base_args() -> dict[str, Any]:
    return {
        "workspace_id": WS,
        "project_id": P1,
        "video_item_id": V1,
        "layer_ref_type": "video_item",
        "layer_ref_id": V1,
    }


def _traj_args(amp: float, frames: int = 64, seed: int = 11001) -> dict[str, Any]:
    """Args built from the REAL T06A2 calibration generator (read-only
    consume) — same input family the calibrated boundaries came from."""
    inp = generate_trajectory_drift_input(seed=seed, drift_px_per_frame=amp, frames=frames)
    return {
        **_base_args(),
        "reference_x": [float(v) for v in inp["reference_x"]],
        "observed_x": [float(v) for v in inp["drifted_x"]],
        "frame_start": 0,
    }


def _expected_traj_value(amp: float, frames: int = 64) -> float:
    """Independent recompute of the mean absolute deviation (no detector
    code): sum(amp*t)/frames with t in [0, frames)."""
    return sum(amp * t for t in range(frames)) / frames


def _cut_args(
    *,
    render_cuts_ms: list[int],
    timebase: CanonicalTimebase | None = None,
    boundaries: list[dict[str, int]] | None = None,
) -> dict[str, Any]:
    tb = timebase or CanonicalTimebase.from_rational(30, 1, nb_frames=120)
    return {
        **_base_args(),
        "timebase": tb.to_json(),
        # Default ground truth: ONE cut boundary — scene 1 starts at frame
        # 60 (two_scene_source: 2.0 s @ 30 fps; scene 0 start is not a cut).
        "scene_boundaries": boundaries
        or [{"position": 1, "start_frame": 60}],
        "render_cuts_ms": render_cuts_ms,
    }


def _patched_policy(
    monkeypatch: pytest.MonkeyPatch, *, metric: str, **boundary_overrides: float
) -> None:
    """Test-copy technique: deep-copy the FROZEN policy (captured at test
    module import — never the already-patched attribute), change ONE
    boundary, and point the module's ``load_policy`` at the copy."""
    policy = json.loads(json.dumps(_FROZEN_LOAD_POLICY()))  # JSON round-trip deep copy
    policy["thresholds"][metric].update(boundary_overrides)
    monkeypatch.setattr(thresholds_mod, "load_policy", lambda: policy)


def _list_all(session: Session) -> list[QCItemRecord]:
    from app.persistence.qc_items import QCItemRepository

    records, _total = QCItemRepository(session).list(workspace_id=WS)
    return records


# ── registry + runner entry (T03A contract) ─────────────────────────────────

class TestRegistryAndRunner:
    def test_both_detectors_registered_through_t03a_registry(self) -> None:
        spec_t = get_detector("trajectory_drift")
        assert spec_t.entry_point == "app.services.qc_checks.trajectory_drift:detect"
        assert spec_t.name in registry.names()
        spec_c = get_detector("cut_drift")
        assert spec_c.entry_point == "app.services.qc_checks.cut_drift:detect"
        assert spec_c.name in registry.names()
        # Both detectors never conflict with each other's names.
        assert registry.get("trajectory_drift").entry_point != registry.get("cut_drift").entry_point

    def test_trajectory_drift_runs_through_bounded_runner(self) -> None:
        run = run_detector(
            "trajectory_drift",
            args=_traj_args(amp=0.2, frames=8),  # value 0.7 px -> pass
            deadline_sec=30.0,
            capture_cap_bytes=64 * 1024,
        )
        assert run.status == "ok"
        assert run.output["metric"] == "trajectory_drift"
        assert run.output["measurements"][0]["status"] == STATUS_PASS

    def test_cut_drift_runs_through_bounded_runner(self) -> None:
        run = run_detector(
            "cut_drift",
            args=_cut_args(render_cuts_ms=[2000]),  # boundary 60 f -> 2000 ms -> drift 0
            deadline_sec=30.0,
            capture_cap_bytes=64 * 1024,
        )
        assert run.status == "ok"
        assert run.output["metric"] == "cut_drift"
        assert run.output["measurements"][0]["status"] == STATUS_PASS


# ── trajectory_drift (visual) ───────────────────────────────────────────────

class TestTrajectoryDrift:
    def test_blocker_item_created_above_blocker_boundary(self, tmp_path: Path) -> None:
        engine = _fresh_engine(tmp_path)
        args = _traj_args(amp=4.0)  # -> 126.0 px == blocker boundary
        with Session(engine) as session:
            records = create_trajectory_drift_qc_items(session, args)
            session.commit()
            assert len(records) == 1
            item = records[0]
            assert item.reason_code == "trajectory_drift"
            assert item.category == "trajectory_drift"
            assert item.severity == STATUS_BLOCKER
            assert item.detector == "trajectory_drift"
            assert item.layer_ref_type == "video_item"
            assert item.layer_ref_id == V1
            assert item.evidence["schema_version"] == 1
            assert item.evidence["metric"] == "trajectory_drift"
            assert item.evidence["value"] == 126.0
            assert item.evidence["warning_boundary_px"] == TRAJ_WARNING
            assert item.evidence["blocker_boundary_px"] == TRAJ_BLOCKER
            assert item.evidence["status"] == STATUS_BLOCKER
            assert item.evidence_window_key == "trajectory_drift:video_item:v-s11-t03b:w0-63"
            # content-derived confidence: min(value/blocker, 1.0)
            assert item.confidence == 1.0
            assert item.confidence_source == "detector"
            assert len(_list_all(session)) == 1

    def test_warning_item_in_warning_band(self, tmp_path: Path) -> None:
        engine = _fresh_engine(tmp_path)
        args = _traj_args(amp=1.0)  # -> 31.5 px == warning boundary
        with Session(engine) as session:
            records = create_trajectory_drift_qc_items(session, args)
            session.commit()
            assert len(records) == 1
            assert records[0].severity == STATUS_WARNING
            assert records[0].reason_code == "trajectory_drift"
            assert records[0].category == "trajectory_drift"

    def test_mid_band_value_stays_warning_not_blocker(self, tmp_path: Path) -> None:
        engine = _fresh_engine(tmp_path)
        args = _traj_args(amp=2.0)  # -> 63.0 px, inside warning band
        with Session(engine) as session:
            records = create_trajectory_drift_qc_items(session, args)
            session.commit()
            assert len(records) == 1
            assert records[0].severity == STATUS_WARNING

    def test_in_bounds_no_item_created(self, tmp_path: Path) -> None:
        engine = _fresh_engine(tmp_path)
        args = _traj_args(amp=0.2)  # -> 6.3 px < warning
        with Session(engine) as session:
            records = create_trajectory_drift_qc_items(session, args)
            session.commit()
            assert records == []
            assert _list_all(session) == []

    def test_measurement_matches_calibration_semantics(self) -> None:
        """The detector's mean-abs-deviation matches the independent
        recompute for every calibrated perturbation level."""
        for amp in (0.5, 1.0, 2.0, 4.0):
            result = trajectory_drift_detect(_traj_args(amp=amp))
            expected = _expected_traj_value(amp)
            assert result["measurements"][0]["value"] == pytest.approx(expected, abs=1e-9)

    def test_evidence_byte_identical_two_runs(self, tmp_path: Path) -> None:
        from app.persistence.qc_items import canonical_evidence_json

        engine_a = _fresh_engine(tmp_path, "a.db")
        engine_b = _fresh_engine(tmp_path, "b.db")
        args = _traj_args(amp=2.0)
        with Session(engine_a) as sa, Session(engine_b) as sb:
            ra = create_trajectory_drift_qc_items(sa, args)[0]
            rb = create_trajectory_drift_qc_items(sb, args)[0]
            # byte-identical evidence across two independent runs
            assert canonical_evidence_json(ra.evidence) == canonical_evidence_json(rb.evidence)
            assert ra.evidence_window_key == rb.evidence_window_key
        # detect() twice: evidence dicts byte-stable through serialization
        e1 = canonical_evidence_json(trajectory_drift_detect(args)["measurements"][0]["evidence"])
        e2 = canonical_evidence_json(trajectory_drift_detect(args)["measurements"][0]["evidence"])
        assert e1 == e2

    def test_natural_key_idempotent_recheck_reuses_row(self, tmp_path: Path) -> None:
        engine = _fresh_engine(tmp_path)
        args = _traj_args(amp=4.0)
        with Session(engine) as session:
            first = create_trajectory_drift_qc_items(session, args)
            second = create_trajectory_drift_qc_items(session, args)
            session.commit()
            assert first[0].id == second[0].id  # same row, no duplicate
            assert len(_list_all(session)) == 1

    def test_threshold_read_from_policy_test_copy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Boundary changed in the policy TEST-COPY changes the outcome —
        the detector cannot be hard-coding the boundaries."""
        args = _traj_args(amp=3.2)  # -> 100.8 px: frozen policy -> warning
        assert classify("trajectory_drift", _expected_traj_value(3.2))[0] == STATUS_WARNING

        # copy with a LOWER blocker -> the same 100.8 px becomes blocker
        _patched_policy(monkeypatch, metric="trajectory_drift", blocker_boundary=80.0)
        assert classify("trajectory_drift", 100.8)[0] == STATUS_BLOCKER
        engine = _fresh_engine(tmp_path)
        with Session(engine) as session:
            records = create_trajectory_drift_qc_items(session, args)
            session.commit()
            assert [r.severity for r in records] == [STATUS_BLOCKER]

        # copy with a HIGHER warning -> the same 100.8 px becomes pass
        # (setattr replaces the previous copy — no undo dance needed)
        _patched_policy(monkeypatch, metric="trajectory_drift", warning_boundary=200.0)
        assert classify("trajectory_drift", 100.8)[0] == STATUS_PASS
        engine2 = _fresh_engine(tmp_path, "c2.db")
        with Session(engine2) as session:
            records = create_trajectory_drift_qc_items(session, args)
            session.commit()
            assert records == []

    def test_mismatched_paths_fail_closed(self, tmp_path: Path) -> None:
        args = _traj_args(amp=1.0)
        args["observed_x"] = args["observed_x"][:-4]
        with pytest.raises(TrajectoryDriftDetectorError) as exc_info:
            trajectory_drift_detect(args)
        assert exc_info.value.code == "QC_TRAJECTORY_INVALID_ARGS"

    def test_out_of_envelope_measurement_fail_closed(self, tmp_path: Path) -> None:
        args = _traj_args(amp=5.0)  # -> 157.5 px > sanity max 126.0
        with pytest.raises(TrajectoryDriftDetectorError) as exc_info:
            trajectory_drift_detect(args)
        assert exc_info.value.code == "QC_TRAJECTORY_MEASUREMENT_INVALID"


# ── cut_drift (timecode) ────────────────────────────────────────────────────

class TestCutDrift:
    def test_blocker_item_created_above_blocker_boundary(self, tmp_path: Path) -> None:
        """Ground truth from the REAL T06A1 two_scene_source manifest (cut
        at 2.0 s @ 30 fps = frame 60) + scene_detector helpers."""
        manifest = load_manifest("two_scene_source")
        assert manifest["media"]["params"]["rate"] == 30
        assert manifest["media"]["params"]["duration_a"] == 2.0

        tb = CanonicalTimebase.from_rational(30, 1, nb_frames=120)
        scenes = cuts_to_scenes([60], nb_frames=120, min_scene_len_frames=30)
        assert scenes == [(0, 59), (60, 119)]
        boundary_ms = scene_ms_range(tb, 60, 119)[0]
        assert boundary_ms == 2000

        args = _cut_args(render_cuts_ms=[2400])  # 72 f vs boundary 60 -> drift 12
        engine = _fresh_engine(tmp_path)
        with Session(engine) as session:
            records = create_cut_drift_qc_items(session, args)
            session.commit()
            assert len(records) == 1
            item = records[0]
            assert item.reason_code == "cut_drift"
            assert item.category == "cut_drift"
            assert item.severity == STATUS_BLOCKER
            assert item.evidence["schema_version"] == 1
            assert item.evidence["metric"] == "cut_drift"
            assert item.evidence["scene_position"] == 1
            assert item.evidence["boundary_frame"] == 60
            assert item.evidence["boundary_time_ms"] == boundary_ms  # scene_detector GT ms
            assert item.evidence["render_cut_ms"] == 2400
            assert item.evidence["render_frame"] == 72
            assert item.evidence["drift_frames"] == 12
            assert item.evidence["status"] == STATUS_BLOCKER
            assert item.evidence["warning_boundary_frames"] == CUT_WARNING
            assert item.evidence["blocker_boundary_frames"] == CUT_BLOCKER
            assert item.confidence == 1.0  # min(12/12, 1.0)
            assert item.confidence_source == "detector"

    def test_warning_item_in_warning_band(self, tmp_path: Path) -> None:
        args = _cut_args(render_cuts_ms=[2100])  # 63 f vs 60 -> drift 3
        engine = _fresh_engine(tmp_path)
        with Session(engine) as session:
            records = create_cut_drift_qc_items(session, args)
            session.commit()
            assert len(records) == 1
            assert records[0].severity == STATUS_WARNING
            assert records[0].reason_code == "cut_drift"
            assert records[0].category == "cut_drift"
            assert records[0].confidence == pytest.approx(round(3 / 12, 6))

    def test_in_bounds_no_item_created(self, tmp_path: Path) -> None:
        args = _cut_args(render_cuts_ms=[2030])  # 61 f vs 60 -> drift 1 < 3
        engine = _fresh_engine(tmp_path)
        with Session(engine) as session:
            records = create_cut_drift_qc_items(session, args)
            session.commit()
            assert records == []
            assert _list_all(session) == []

    def test_frame_ms_conversion_exact_fraction_2997(self, tmp_path: Path) -> None:
        """29.97 fps (30000/1001) — ms<->frame conversion is exact ONLY
        through Fraction arithmetic (3.303 s = 98.991... frames)."""
        tb = CanonicalTimebase.from_rational(30000, 1001, nb_frames=180)
        # boundary frame 90 -> EXACTLY 3003 ms (Fraction, no float drift)
        assert tb.frame_to_time(90) * 1000 == Fraction(3003, 1)
        # exact round trip: 3003 ms -> frame 90
        assert tb.nearest_frame(Fraction(3003, 1000)) == 90
        # a render cut at 3303 ms -> frame 99 (98.991 -> half-up 99)
        assert tb.nearest_frame(Fraction(3303, 1000)) == 99

        args = _cut_args(
            render_cuts_ms=[3303],
            timebase=tb,
            boundaries=[{"position": 1, "start_frame": 90}],
        )
        engine = _fresh_engine(tmp_path)
        with Session(engine) as session:
            records = create_cut_drift_qc_items(session, args)
            session.commit()
            assert len(records) == 1
            item = records[0]
            assert item.severity == STATUS_WARNING  # drift 9 frames
            assert item.evidence["boundary_time_ms"] == 3003
            assert item.evidence["render_frame"] == 99
            assert item.evidence["drift_frames"] == 9
            # boundary_time_ms must equal the scene_detector canonical ms
            assert item.evidence["boundary_time_ms"] == scene_ms_range(tb, 90, 179)[0]

    def test_evidence_byte_identical_and_natural_key_idempotent(self, tmp_path: Path) -> None:
        from app.persistence.qc_items import canonical_evidence_json

        engine_a = _fresh_engine(tmp_path, "a.db")
        engine_b = _fresh_engine(tmp_path, "b.db")
        args = _cut_args(render_cuts_ms=[2400])
        with Session(engine_a) as sa, Session(engine_b) as sb:
            ra = create_cut_drift_qc_items(sa, args)[0]
            rb = create_cut_drift_qc_items(sb, args)[0]
            # byte-identical evidence across two independent runs
            assert canonical_evidence_json(ra.evidence) == canonical_evidence_json(rb.evidence)
            assert ra.evidence_window_key == rb.evidence_window_key
            sa.commit()  # persist before the idempotency recheck below
        # natural-key idempotency: recreate on the same DB reuses the row
        with Session(engine_a) as session:
            again = create_cut_drift_qc_items(session, args)
            session.commit()
            assert again[0].id == ra.id
            assert len(_list_all(session)) == 1

    def test_threshold_read_from_policy_test_copy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        args = _cut_args(render_cuts_ms=[2300])  # 69 f vs 60 -> drift 9: frozen -> warning
        assert classify("cut_drift", 9)[0] == STATUS_WARNING

        # copy with blocker=6 -> the same drift 9 becomes blocker
        _patched_policy(monkeypatch, metric="cut_drift", blocker_boundary=6.0)
        assert classify("cut_drift", 9)[0] == STATUS_BLOCKER
        engine = _fresh_engine(tmp_path)
        with Session(engine) as session:
            records = create_cut_drift_qc_items(session, args)
            session.commit()
            assert [r.severity for r in records] == [STATUS_BLOCKER]

        # copy with warning=99 -> the same drift 9 becomes pass
        # (setattr replaces the previous copy — no undo dance needed)
        _patched_policy(monkeypatch, metric="cut_drift", warning_boundary=99.0)
        assert classify("cut_drift", 9)[0] == STATUS_PASS
        engine2 = _fresh_engine(tmp_path, "c2.db")
        with Session(engine2) as session:
            records = create_cut_drift_qc_items(session, args)
            session.commit()
            assert records == []

    def test_scene_boundaries_and_render_cuts_mismatch_fail_closed(self) -> None:
        args = _cut_args(render_cuts_ms=[2000, 3000])  # 2 cuts vs 1 boundary
        with pytest.raises(CutDriftDetectorError) as exc_info:
            cut_drift_detect(args)
        assert exc_info.value.code == "QC_CUT_INVALID_ARGS"

    def test_out_of_envelope_drift_fail_closed(self, tmp_path: Path) -> None:
        args = _cut_args(render_cuts_ms=[4000])  # 120 f vs 60 -> drift 60 > sanity max 12
        with pytest.raises(CutDriftDetectorError) as exc_info:
            cut_drift_detect(args)
        assert exc_info.value.code == "QC_CUT_MEASUREMENT_INVALID"


# ── policy sanity (read-only reference for the evidence assertions) ─────────

class TestPolicySanity:
    def test_policy_boundaries_match_frozen_calibration(self) -> None:
        traj = thresholds_mod.get_threshold("trajectory_drift")
        assert traj["warning_boundary"] == TRAJ_WARNING
        assert traj["blocker_boundary"] == TRAJ_BLOCKER
        cut = thresholds_mod.get_threshold("cut_drift")
        assert cut["warning_boundary"] == CUT_WARNING
        assert cut["blocker_boundary"] == CUT_BLOCKER

    def test_calibration_derived_trajectory_inputs(self) -> None:
        """The test inputs reproduce the frozen calibration raw values —
        the fixture family is exactly the T06A2 calibration family."""
        for amp, expected in ((0.5, 15.75), (1.0, 31.5), (2.0, 63.0), (4.0, 126.0)):
            value = trajectory_drift_detect(_traj_args(amp=amp))["measurements"][0]["value"]
            assert value == pytest.approx(expected, abs=1e-9)