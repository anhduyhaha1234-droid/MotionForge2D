"""DELTA-F6 — two P1 seams of the QC composer, measured on the REAL R4 data.

The evidence is ``tasks/MF-DEMO-E2E-R4`` (FROZEN #7 ``dfdad734``): the QC submit
of the 640x360x360f publication refused ``QC_RUN_EVIDENCE_UNAVAILABLE`` with two
P1 blockers, both reproduced here on the REAL publication bytes copied from that
run (sha256 ``075133f3…`` — the identity recorded in
``raw/final_evidence.json`` and ``raw/final_gate.json`` of the R4 evidence).

* **F-R4-1 (cut_drift starvation)** — ``compose._cut_drift`` truncated the frame
  window with ``sorted(wanted)[:MAX_WINDOW_FRAMES]`` (24) on the UNION of the
  per-boundary search spans, and ``measure.decode_video_frames`` truncated AGAIN
  with ``[:MAX_WINDOW_FRAMES]``.  For a 3-scene 360f render the union is 75
  indices, so the decode kept ``-1..22`` and the boundary at frame 120 had ZERO
  measurable pairs: ``no_measurable_frame_pair`` even though the render carries a
  REAL cut at 120 (MAD 80.82) and at 240 (MAD 119.51).  Each boundary's span is
  already bounded to the composition window; the decode is now the union of those
  windows (``limit=None`` — the caller's windows are the bound).
* **F-R4-2 (identity argv transport)** — the composed ``identity_drift`` set
  measured 63,327 B on that video and the detector child could not be spawned at
  all (``FileNotFoundError [WinError 206]``).  The composer now transports the
  set under a MEASURED, disclosed ladder: the frozen detector's consumable core
  (pixel payloads in their exact integral form, per-frame metadata, the cast
  identity block, the row identities) is never reduced; the composer-side
  evidence is hoisted/digested/summarised only as far as the measured spawn
  ceiling requires, the FULL pre-transport set is persisted under the managed
  root and digested into the argument set, and a set that fits nowhere refuses
  with the typed ``QC_EVIDENCE_MALFORMED``.

Rows (binary; RED on the pre-fix tree, GREEN after the fix) — the world is the
real publication with the R4 timeline (boundaries 0 / 120 / 240, 30 fps):

* 6.0 the committed fixture IS the real run's publication: it hashes to the R4
  identity and decodes to 640x360x360f.
* 6.1 cut_drift observes the REAL cuts (frames 120 and 240 == the planned
  timecodes 4000 ms / 8000 ms) and the frozen detector measures drift 0.
* 6.2 negative: a boundary whose window has no decodable frame pair still
  refuses ``no_measurable_frame_pair`` — nothing is fabricated.
* 6.3 identity_drift composes inside the MEASURED spawn budget: the transport
  ladder discloses its level, the full-evidence file is persisted and
  digest-matches, and the REAL child process (``run_detector``) spawns and
  reproduces the composer's own per-role measurement.
* 6.4 negative: a genuinely absent authority (deleted cast pin) still refuses
  ``QC_EVIDENCE_MISSING`` with zero QC rows.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from alembic import command
from sqlalchemy import select, text, update

from app.persistence import create_engine_for_path, create_session_factory
from app.services.qc_checks import identity_drift as identity_detector
from app.services.qc_checks import runner as qc_runner
from app.services.qc_evidence import QcEvidenceError
from app.services.qc_evidence import compose as qc_compose
from app.services.qc_evidence import sources as qc_sources

WT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "delta_f6"
PUBLICATION = FIXTURES / "r4_publication_640x360_360f.mp4"

#: The real R4 publication identity (tasks/MF-DEMO-E2E-R4/raw/final_evidence.json).
R4_PUBLICATION_SHA = (
    "075133f3d2d6918d7cff3a036d7234ce64e154b06b09fe8dbc4b1b04ff9fa269"
)
R4_PUBLICATION_BYTES = 3_840_735
R4_PUBLICATION_FRAMES = 360
R4_PUBLICATION_DIMS = (360, 640)
#: The planned timeline of that publication: 3 scenes at 30 fps.
R4_SCENES: tuple[tuple[int, int, int], ...] = ((0, 119, 0), (120, 239, 4000), (240, 359, 8000))
#: The real delta the render carries at each boundary (raw/probe_qc_compose_r4.json).
R4_CUT_MAD: dict[int, float] = {120: 80.8241, 240: 119.5122}
#: The boundary the R4 run reported as starved (raw/qc_receipt.json).
R4_STARVED_SPAN = [108, 131]

#: The frozen QC-evidence conftest owns the canonical persisted QC world (roles,
#: masks, cast pins, publication).  DELTA-F6 reuses its REAL seeding helper and
#: adopts the real publication + the real R4 timeline on top of it — the same
#: way DELTA-F5 copied the real run's media into its own fixture tree.
_CONFTEST = (
    Path(__file__).resolve().parents[1] / "product_p1" / "qc_evidence" / "conftest.py"
)
_spec = importlib.util.spec_from_file_location("delta_f6_frozen_qc_conftest", _CONFTEST)
assert _spec is not None and _spec.loader is not None
_frozen = importlib.util.module_from_spec(_spec)
# the module must be registered before execution: its frozen dataclasses resolve
# their own module through sys.modules at decoration time
import sys as _sys  # noqa: E402

_sys.modules[_spec.name] = _frozen
_spec.loader.exec_module(_frozen)


def _argv_transport_bytes(value: Any) -> int:
    """The MEASURED command-line cost of one argv item (runner.py's form)."""
    return len(
        subprocess.list2cmdline([json.dumps(value, separators=(",", ":"))])
    )


def _mask_png_bytes(rect: tuple[int, int, int, int]) -> bytes:
    """A real 640x360 grayscale PNG with one white rectangle (mask bytes)."""
    from PIL import Image

    array = np.zeros((_frozen.CANVAS_H, _frozen.CANVAS_W), dtype=np.uint8)
    x0, y0, x1, y1 = rect
    array[y0:y1, x0:x1] = 255
    buffer = io.BytesIO()
    Image.fromarray(array, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def r4_world(tmp_path: Path):  # noqa: ANN201
    """The frozen QC world adopted to the REAL R4 publication + timeline."""
    database_path = tmp_path / "delta_f6.db"
    command.upgrade(_frozen._alembic_config(database_path), "head")  # noqa: SLF001
    session_factory = create_session_factory(create_engine_for_path(database_path))
    managed_root = tmp_path / "managed"
    managed_root.mkdir(parents=True, exist_ok=True)
    ids = _frozen.seed_qc_evidence(session_factory, managed_root)
    publication_bytes = PUBLICATION.read_bytes()
    assert hashlib.sha256(publication_bytes).hexdigest() == R4_PUBLICATION_SHA
    assert len(publication_bytes) == R4_PUBLICATION_BYTES
    with session_factory() as session:
        # 1) the video's current result IS the real R4 publication (every
        #    render-side artifact the resolver may pick is adopted)
        targets = session.execute(
            text(
                "SELECT id, relative_path FROM artifact WHERE id IN ("
                "SELECT artifact_id FROM artifact_owner WHERE owner_type='video_item'"
                " AND owner_id=:vid AND purpose IN ('result','render','publication'))"
                " OR id=:render_id"
            ),
            {"vid": ids.video_item_id, "render_id": ids.render_artifact_id},
        ).all()
        assert targets, "the frozen world publishes no render-side artifact"
        for artifact_id, relative_path in targets:
            (managed_root / relative_path).write_bytes(publication_bytes)
            session.execute(
                text(
                    "UPDATE artifact SET sha256=:sha, size_bytes=:size WHERE id=:id"
                ),
                {"sha": R4_PUBLICATION_SHA, "size": R4_PUBLICATION_BYTES,
                 "id": artifact_id},
            )
        session.execute(
            update(_frozen.VideoItem)
            .where(_frozen.VideoItem.id == ids.video_item_id)
            .values(duration_ms=12_000)
        )
        # 2) the REAL three-scene timeline (boundaries 0 / 120 / 240)
        scene_rows = list(
            session.scalars(
                select(_frozen.Scene).where(
                    _frozen.Scene.video_item_id == ids.video_item_id
                )
            ).all()
        )
        assert len(scene_rows) == 2, scene_rows
        for row, (start, end, start_ms) in zip(scene_rows, R4_SCENES[:2], strict=True):
            row.start_frame = start
            row.end_frame = end
            row.start_time_ms = start_ms
            row.end_time_ms = start_ms + int((end - start + 1) * 1000 / _frozen.FPS_NUM)
        tail_start, tail_end, tail_ms = R4_SCENES[2]
        session.add(
            _frozen.Scene(
                video_item_id=ids.video_item_id,
                position=2,
                start_frame=tail_start,
                end_frame=tail_end,
                start_time_ms=tail_ms,
                end_time_ms=tail_ms
                + int((tail_end - tail_start + 1) * 1000 / _frozen.FPS_NUM),
                status="approved",
            )
        )
        # 3) the segments follow the scenes (one segment per boundary frame)
        for artifact_id, (start, end, start_ms) in zip(
            (ids.segment_a, ids.segment_b, ids.segment_c), R4_SCENES, strict=True
        ):
            session.execute(
                text(
                    "UPDATE occurrence_segment SET start_frame=:sf, end_frame=:ef, "
                    "start_time_ms=:st, end_time_ms=:et WHERE id=:id"
                ),
                {
                    "sf": start,
                    "ef": end,
                    "st": start_ms,
                    "et": start_ms + int((end - start + 1) * 1000 / _frozen.FPS_NUM),
                    "id": artifact_id,
                },
            )
        # 4) the FIRST (primary) role's mask is a real 32x32 window — the
        #    geometry the R4 measurement had (its identity payload is what blew
        #    the child-process command line)
        mask_row = session.execute(
            text("SELECT id, relative_path FROM artifact WHERE id=:id"),
            {"id": ids.mask_a},
        ).one()
        mask_bytes = _mask_png_bytes((100, 160, 132, 192))
        (managed_root / mask_row.relative_path).write_bytes(mask_bytes)
        session.execute(
            text("UPDATE artifact SET sha256=:sha, size_bytes=:size WHERE id=:id"),
            {
                "sha": hashlib.sha256(mask_bytes).hexdigest(),
                "size": len(mask_bytes),
                "id": mask_row.id,
            },
        )
        session.commit()
    return session_factory, managed_root, ids


def _cut_args(session_factory: Any, managed_root: Path, ids: Any) -> dict[str, Any]:
    with session_factory() as session:
        scope = qc_sources.load_scope(
            session,
            workspace_id=ids.workspace_id,
            project_id=ids.project_id,
            video_item_id=ids.video_item_id,
            generation="1",
        )
        ctx = qc_compose._Context(  # noqa: SLF001 - the composer's own seam
            session=session, managed_root=managed_root, scope=scope
        )
        return qc_compose._cut_drift(ctx)  # noqa: SLF001


def _identity_args(session_factory: Any, managed_root: Path, ids: Any) -> dict[str, Any]:
    with session_factory() as session:
        scope = qc_sources.load_scope(
            session,
            workspace_id=ids.workspace_id,
            project_id=ids.project_id,
            video_item_id=ids.video_item_id,
            generation="1",
        )
        ctx = qc_compose._Context(  # noqa: SLF001 - the composer's own seam
            session=session, managed_root=managed_root, scope=scope
        )
        return qc_compose._identity_drift(ctx)  # noqa: SLF001


def test_6_0_the_fixture_is_the_real_r4_publication() -> None:
    data = PUBLICATION.read_bytes()
    assert hashlib.sha256(data).hexdigest() == R4_PUBLICATION_SHA
    assert len(data) == R4_PUBLICATION_BYTES
    from app.services.qc_evidence.measure import decode_video_frames

    frames = decode_video_frames(
        PUBLICATION, [0, 119, 120, 239, 240, 359], detector="cut_drift", limit=None
    )
    assert sorted(frames) == [0, 119, 120, 239, 240, 359]
    assert np.asarray(frames[0]).shape == R4_PUBLICATION_DIMS


def test_6_1_cut_drift_observes_the_real_cuts_of_the_publication(r4_world) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = r4_world
    args = _cut_args(session_factory, managed_root, ids)
    observations = args["cut_observations"]
    assert [row["boundary_frame"] for row in observations] == [0, 120, 240]
    # the REAL cut of each boundary is the frame the render's own delta reports
    assert [row["observed_frame"] for row in observations] == [0, 120, 240]
    for row in observations[1:]:
        assert row["reason"] is None, row
        assert row["delta"] > 40.0, row  # the measured step, not motion
        assert row["neighbour_max_delta"] < row["delta"] / 2.0, row
    assert args["render_cuts_ms"] == [0, 4000, 8000]
    assert args["planned_cuts_ms"] == [0, 4000, 8000]
    # the pre-fix refusal: the boundary's span was never decoded at all
    assert observations[1]["search_span"] == R4_STARVED_SPAN
    # the frozen detector's own measurement on the composed set: drift 0
    from app.services.qc_checks import cut_drift as cut_detector

    out = cut_detector.detect(args)
    assert [row["value"] for row in out["measurements"]] == [0.0, 0.0, 0.0]
    assert [row["status"] for row in out["measurements"]] == ["pass", "pass", "pass"]


def test_6_2_unmeasurable_boundary_still_refuses(r4_world) -> None:  # noqa: ANN001
    """Negative: no decodable frame pair -> the typed refusal, never a green."""
    session_factory, managed_root, ids = r4_world
    with session_factory() as session:
        session.execute(
            text(
                "UPDATE occurrence_segment SET start_frame=1200, end_frame=1500, "
                "start_time_ms=40000, end_time_ms=50000 WHERE id=:id"
            ),
            {"id": ids.segment_c},
        )
        session.execute(
            text(
                "UPDATE scene SET start_frame=1200, end_frame=1500 "
                "WHERE video_item_id=:vid AND position=2"
            ),
            {"vid": ids.video_item_id},
        )
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _cut_args(session_factory, managed_root, ids)
    details = raised.value.details
    assert raised.value.code == "QC_EVIDENCE_MISSING"
    assert details.get("reason") == "no_measurable_frame_pair"
    assert details.get("search_span") == [1188, 1211]
    assert details.get("measured", {}).get("measured_frames") == []


def test_6_3_identity_transport_spawns_and_reproduces_the_measurement(r4_world) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = r4_world
    args = _identity_args(session_factory, managed_root, ids)
    budget = args["payload_budget"]
    # the transport ladder reported itself, with the ceiling it was measured on
    assert budget["transport_level"] in {"L1", "L2", "L3", "L4", "L5", "L6"}
    assert budget["reductions"], budget
    measured = _argv_transport_bytes(args)
    assert measured == budget["measured_escaped_bytes"] or measured <= budget[
        "hard_cap_bytes"
    ]
    # the ladder's OWN disclosed rule: the set it stopped at (before the
    # payload_budget disclosure block, which lives inside the reserved budget)
    # spawns with the runner's command-line overhead and the output-binding
    # reserve still free
    assert (
        budget["measured_escaped_bytes"]
        + qc_compose.ARGV_RUNNER_COMMANDLINE_OVERHEAD_BYTES
        + qc_compose.ARGV_OUTPUT_BINDING_RESERVE_BYTES
        <= qc_compose.ARGV_CEILING_SPAWN_OK_BYTES
    )
    assert budget["within_limit"] is True
    # the FULL pre-transport set is persisted and digest-bound
    record = budget["full_evidence_file"]
    assert record and record["schema"] == qc_compose.IDENTITY_TRANSPORT_SCHEMA
    path = managed_root / record["relative_path"]
    data = path.read_bytes()
    assert len(data) == record["size_bytes"]
    assert hashlib.sha256(data).hexdigest() == record["sha256"]
    full = json.loads(data)
    assert full["frames"] and full["identity_measurements"]
    assert len(full["identity_measurements"]) >= 3
    # the frozen detector's OWN integrity gate accepts the transported crops
    assert identity_detector._crop_sha256(  # noqa: SLF001 - the frozen check
        args["pinned_reference"]["crop"]
    ) == args["pinned_reference"]["sha256"]
    for frame in args["frames"]:
        assert identity_detector._crop_sha256(frame["crop"]) == frame["sha256"]  # noqa: SLF001
    in_process = identity_detector.detect(args)
    assert in_process["identity_flip"] == {"flipped": False, "flip_kind": None}
    # the REAL child process receives the transported payload and reproduces it
    run = qc_runner.run_detector(
        "identity_drift",
        args=args,
        deadline_sec=120.0,
        capture_cap_bytes=4_000_000,
    )
    assert run.status == "ok"
    assert run.code == qc_runner.QC_RUNNER_OK
    primary_role = str(args["identity_measurements"][0]["object_role_id"])
    composer_value = float(
        next(
            row["measured_distance_px"]
            for row in args["identity_measurements"]
            if str(row["object_role_id"]) == primary_role
        )
    )
    assert run.output["measured_distance"] == in_process["measured_distance"]
    assert abs(float(run.output["measured_distance"]) - composer_value) < 1e-6


def test_6_4_absent_authority_still_refuses(r4_world) -> None:  # noqa: ANN001
    """Negative: a deleted cast pin is a typed refusal with zero QC rows."""
    session_factory, managed_root, ids = r4_world
    with session_factory() as session:
        session.execute(
            text("DELETE FROM project_cast_mapping WHERE id=:id"),
            {"id": ids.cast_mapping_ids["Prop"]},
        )
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _identity_args(session_factory, managed_root, ids)
    assert raised.value.code == "QC_EVIDENCE_MISSING"
    with session_factory() as session:
        assert (
            session.execute(text("SELECT COUNT(*) FROM qc_item")).scalar_one() == 0
        )
