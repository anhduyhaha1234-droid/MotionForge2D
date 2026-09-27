"""MF-P1-QC-EVIDENCE — correction round R27-04 acceptance tests (geometry authority).

What this round changes (the defect it closes)
---------------------------------------------

The frozen ``silhouette_clipping`` metric is bbox area OUTSIDE the frame, and a
bbox measured from decoded pixels is frame-bounded by construction — so the
ratio can NEVER carry a cut the frame itself bounds.  Before this round a
rendered object the OUTPUT clipped at the frame border therefore composed to a
measured ``clipped_ratio = 0`` and the frozen detector emitted no item: a cut
object read as zero risk.

R27-04 gives the observation an explicit AUTHORITY layer:

* a rendered object is attributed to a role only through that role's OWN
  published support (its segmentation mask): ``rendered_object_bbox`` is only
  reachable through ``supported_object_bbox``, whose ``region`` must BE the
  support's own measured extent;
* a measured extent that reaches a frame side carries a VERDICT — a side the
  ROLE'S OWN published extent already reaches is source-intended partial
  visibility (NOT new truncation), a side only the RENDER reaches is newly
  introduced truncation and is FLAGGED, and when nothing attributes the cut
  content to the role (no rendered-side role mask) the composer REFUSES with a
  typed ``QC_EVIDENCE_DEPENDENCY`` instead of reporting a 0 PASS;
* the role/segment/frame binding is checked: a segment measured with another
  current segment's published mask is refused.

The ten frozen rows below (names are the contract)
--------------------------------------------------

1.  ``test_r27_valid_supported_in_frame_measured`` — a supported role fully
    inside the frame is MEASURED from the render and cleared;
2.  ``test_r27_missing_role_mask_is_unmeasurable_not_pass`` — the role's
    published support bytes are gone: typed refusal, never a 0 PASS;
3.  ``test_r27_empty_uniform_has_no_measurement`` — an empty/uniform support or
    an all-one-level render yields NO measurement;
4.  ``test_r27_unrelated_checkerboard_geometry_refused`` — geometry unrelated
    to the role is refused, never measured as its silhouette;
5.  ``test_r27_known_truncated_role_is_measured_and_flagged`` — a role the
    output truncates is NEVER an empty success (R28: the row's final
    assertion changed — the outcome must be a typed refusal or a real
    finding, never `[]`);
6.  ``test_r27_source_intended_edge_contact_not_clipping`` — a contact the
    ROLE'S OWN extent already reaches is NOT new clipping;
7.  ``test_r27_foreign_role_segment_frame_refused`` — a segment bound to
    another segment's published mask is refused;
8.  ``test_r27_missing_expected_support_unmeasurable`` — no pinned support was
    ever published for the role: typed refusal;
9.  ``test_r27_bounded_payload_retained`` — the argv-transported argument set
    stays inside the measured child-process budget while the per-role data is
    retained;
10. ``test_r27_per_role_controls_retained`` — every role keeps its own mask
    binding, its own measured row and the frozen detector's per-role contract.

The six R28 rows (added by the correction round that closed the two measured
false passes; names are the contract)
---------------------------------------------------------------------------

11. ``test_r28_full_canvas_checker_refused`` (Q-1) — a support that fills the
    whole frame never becomes a role's extent, for an in-frame OR a clipped
    render;
12. ``test_r28_uniform_support_refused`` (Q-2) — a uniform support (full-canvas
    white, all-zero blank) is refused in both shapes;
13. ``test_r28_hollow_support_does_not_authorize_interior`` (Q-3) — an object
    painted only where the support has NO pixels is not attributable to the role;
14. ``test_r28_foreign_same_geometry_support_refused`` (Q-4) — a candidate whose
    geometry collides with ANOTHER current segment's extent is refused by
    identity;
15. ``test_r28_wrong_frame_rendered_support_refused`` (Q-5) — a rendered-side
    support on a different canvas is refused;
16. ``test_r28_multiple_overlapping_supports_refused`` (Q-6) — several
    overlapping candidates are ambiguous and refuse with EVERY candidate named,
    never resolved by overlap or recency.

Every row drives the REAL composition (``compose_visual_band`` — the server-side
gate that either produces the detector args or refuses the whole band) and, for
every measurable world, the REAL frozen detector
(``silhouette_clipping.detect_silhouette_clipping``).  Row 10 also carries the
non-vacuity control: the same frozen detector MUST still emit one blocker item
per role when a role's geometry is genuinely outside the frame, so the ``[]``
results elsewhere are not green-by-construction.

Every row writes its own RAW result (expected / observed / the render SHA the
observation came from / the disposition) under ``P1QC_EVIDENCE_ROOT`` (default:
this round's literal evidence root), so a reviewer can re-run the row and diff
the bytes.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np
import pytest
from conftest import (
    CANVAS_H,
    CANVAS_W,
    DELTA_RECT,
    FPS_NUM,
    MASK_A_RECT,
    MASK_B_RECT,
    MASK_C_RECT,
    TOTAL_FRAMES,
)

import conftest as _conftest
from alembic import command
from sqlalchemy import select, update

from app.persistence import create_engine_for_path, create_session_factory
from app.persistence.artifacts import ManagedRoot
from app.persistence.models import Artifact, OccurrenceSegment, QCItem
from app.services.qc_checks import silhouette_clipping
from app.services.qc_evidence import (
    QC_EVIDENCE_DEPENDENCY,
    QC_EVIDENCE_MALFORMED,
    QC_EVIDENCE_MISSING,
    QcEvidenceError,
    compose_visual_band,
)
from app.services.qc_evidence import compose as composer
from app.services.qc_evidence import observe as obs

#: Literal evidence root of this round (the packet's path, no nested NEW folder).
EVIDENCE_ROOT = Path(
    os.environ.get(
        "P1QC_EVIDENCE_ROOT",
        "C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
        "mf-cpu-input-correction-20260927/20260927T051440Z/P1QC/raw",
    )
)

RENDER_LEVEL = 8
#: Type codes that mean "unmeasurable / not attributable" — the ONLY acceptable
#: answers when the observation has no authority (never a measured 0 PASS).
TYPED_REFUSALS = (
    QC_EVIDENCE_MISSING,
    QC_EVIDENCE_MALFORMED,
    QC_EVIDENCE_DEPENDENCY,
)


# ── evidence + composition helpers ──────────────────────────────────────────


def _raw(name: str, payload: dict) -> None:
    """Persist one row's RAW result (fresh, byte-deterministic)."""
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_ROOT / f"{name}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _compose(session_factory, managed_root: Path, ids):  # noqa: ANN001
    with session_factory() as session:
        return compose_visual_band(
            session,
            managed_root=managed_root,
            workspace_id=ids.workspace_id,
            project_id=ids.project_id,
            video_item_id=ids.video_item_id,
        )


def _compose_or_refusal(session_factory, managed_root: Path, ids):  # noqa: ANN001
    """The real gate: either the composed band, or the typed band refusal."""
    try:
        return _compose(session_factory, managed_root, ids), None
    except QcEvidenceError as exc:
        return None, exc


def _detector_failure(error: QcEvidenceError, detector: str) -> dict:
    """The typed failure of ONE detector inside the aggregate band refusal."""
    failed = (error.details.get("failed_detectors") or {}).get(detector)
    assert failed is not None, f"{detector} missing from failed_detectors"
    return dict(failed)


def _assert_unmeasurable(error: QcEvidenceError, detector: str, expected_code: str) -> dict:
    """The refusal is TYPED and no argument set reached the detector at all."""
    failure = _detector_failure(error, detector)
    assert failure["code"] == expected_code, failure
    assert failure["code"] in TYPED_REFUSALS
    assert (error.details.get("refusals") or {}).get(detector) == expected_code
    return failure


def _rows(args: dict) -> dict[str, dict]:
    return {row["id"]: row for row in args["segments"]}


def _authority(args: dict, segment_id: str) -> dict:
    return _rows(args)[segment_id]["clipping_authority"]


def _items(args: dict) -> list[dict]:
    """Run the REAL frozen detector on the composed argument set."""
    return silhouette_clipping.detect_silhouette_clipping(args)


def _transported(args: dict) -> int:
    """Size of the SAME serialization ``runner.py`` hands over as argv[2]."""
    return len(json.dumps(args, separators=(",", ":")))


def _render_identity(session_factory, managed_root: Path, ids) -> dict:  # noqa: ANN001
    with session_factory() as session:
        artifact = session.get(Artifact, ids.render_artifact_id)
        recorded = str(artifact.sha256)
        size = int(artifact.size_bytes)
        rel = str(artifact.relative_path)
    data = (Path(managed_root) / rel).read_bytes()
    return {
        "artifact_id": ids.render_artifact_id,
        "recorded_sha256": recorded,
        "on_disk_sha256": hashlib.sha256(data).hexdigest(),
        "digest_matches_bytes": recorded == hashlib.sha256(data).hexdigest(),
        "size_bytes": size,
    }


def _no_qc_rows(session_factory) -> int:  # noqa: ANN001
    with session_factory() as session:
        return len(session.scalars(select(QCItem)).all())


# ── world mutations (persisted rows + real bytes, never QC tables) ──────────


def _publish_mask(session_factory, managed_root: Path, ids, rect, *, rel: str) -> str:  # noqa: ANN001
    """Publish a REAL 640x360 grayscale mask artifact for the video item."""
    root = ManagedRoot(Path(managed_root))
    with session_factory() as session:
        row = _conftest._publish(  # noqa: SLF001 - the fixture owns this helper
            session,
            root,
            rel=rel,
            data=_conftest._png_bytes(rect),  # noqa: SLF001
            kind="image",
            mime_type="image/png",
            purposes=(("video_item", ids.video_item_id, "mask"),),
        )
        session.commit()
        return str(row.id)


def _publish_png_bytes(session_factory, managed_root: Path, ids, data: bytes, *, rel: str) -> str:  # noqa: ANN001
    root = ManagedRoot(Path(managed_root))
    with session_factory() as session:
        row = _conftest._publish(  # noqa: SLF001
            session,
            root,
            rel=rel,
            data=data,
            kind="image",
            mime_type="image/png",
            purposes=(("video_item", ids.video_item_id, "mask"),),
        )
        session.commit()
        return str(row.id)


def _repoint_support(session_factory, segment_id: str, artifact_id: str | None) -> None:  # noqa: ANN001
    """Re-bind a segment's persisted support (the pinned expected geometry)."""
    with session_factory() as session:
        session.execute(
            update(OccurrenceSegment)
            .where(OccurrenceSegment.id == segment_id)
            .values(mask_artifact_id=artifact_id)
        )
        session.commit()


def _layered_clip(path: Path, layers) -> bytes:
    """Write a REAL lossless clip from (rect, frames, level) layers."""
    import cv2

    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"FFV1"), float(FPS_NUM), (CANVAS_W, CANVAS_H)
    )
    assert writer.isOpened(), "FFV1 video writer unavailable on this host"
    for index in range(TOTAL_FRAMES):
        frame = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)
        for rect, frames, level in layers:
            if index in frames:
                x0, y0, x1, y1 = rect
                frame[y0:y1, x0:x1] = int(level)
        writer.write(frame)
    writer.release()
    data = path.read_bytes()
    assert len(data) > 0, "lossless clip came back empty (fail closed)"
    return data


def _write_render(session_factory, managed_root: Path, ids, layers) -> str:  # noqa: ANN001
    """Rewrite the RENDERED artifact honestly (true sha256/size recorded)."""
    with session_factory() as session:
        artifact = session.get(Artifact, ids.render_artifact_id)
        target = Path(managed_root) / str(artifact.relative_path)
        data = _layered_clip(target, layers)
        digest = hashlib.sha256(data).hexdigest()
        artifact.sha256 = digest
        artifact.size_bytes = len(data)
        session.commit()
    return digest


DEFAULT_LAYERS = (
    (DELTA_RECT, range(0, 10), RENDER_LEVEL),
    (MASK_B_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
    (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
)
#: Segment B's own extent extended to the bottom frame side (a role that IS at
#: the frame edge in the source: legitimately partially visible).
BOTTOM_B = (MASK_B_RECT[0], MASK_B_RECT[1], MASK_B_RECT[2], CANVAS_H)


def _checker_png(rect, tile: int = 4) -> bytes:
    """A real checkerboard PNG confined to ``rect`` (unrelated texture)."""
    from PIL import Image

    array = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    x0, y0, x1, y1 = rect
    sub = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    ys, xs = np.indices(sub.shape)
    sub[((ys // tile) + (xs // tile)) % 2 == 1] = 255
    array[y0:y1, x0:x1] = sub
    buffer = io.BytesIO()
    Image.fromarray(array, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()


def _blank_png() -> bytes:
    """A real 640x360 grayscale PNG carrying NO pixels (uniform/empty)."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8), mode="L").save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


def _second_world(base: Path):
    """A second isolated production-schema world (same migrations, same seed).

    The ``evidence_db`` fixture yields ONE world per row; a row that has to
    mutate the persisted world twice (or compare two worlds) builds its own
    here.  Identical construction: alembic ``head`` + ``seed_qc_evidence``.
    """
    root = Path(base) / "second"
    root.mkdir(parents=True, exist_ok=True)
    database_path = root / "p1qc.db"
    command.upgrade(_conftest._alembic_config(database_path), "head")  # noqa: SLF001
    session_factory = create_session_factory(create_engine_for_path(database_path))
    managed_root = root / "managed"
    managed_root.mkdir(parents=True, exist_ok=True)
    ids = _conftest.seed_qc_evidence(session_factory, managed_root)  # noqa: SLF001
    return session_factory, managed_root, ids


# ── row 1: a supported role fully inside the frame is MEASURED ──────────────


def test_r27_valid_supported_in_frame_measured(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
    assert refusal is None, refusal
    args = composed["silhouette_clipping"]
    rows = _rows(args)
    assert set(rows) == {ids.segment_a, ids.segment_b, ids.segment_c}

    observed: dict[str, dict] = {}
    for segment_id, row in rows.items():
        auth = row["clipping_authority"]
        assert auth["verdict"] == obs.GEOMETRY_IN_FRAME
        assert auth["contact_sides"] == []
        assert auth["detector_clearance"] is True
        assert auth["newly_introduced_truncation"] is False
        assert auth["attributed_to_role"] is True
        assert auth["measure_revision"] == obs.OBSERVATION_REVISION == "1.3.0"
        # the extent is the ROLE'S OWN published geometry
        assert auth["role_extent_bbox"] == row["expected_bbox"]
        observed[str(segment_id)[:8]] = {
            "bbox": row["bbox"],
            "expected_bbox": row["expected_bbox"],
            "verdict": auth["verdict"],
        }

    # R28: the measured extent is the painted object INTERSECTED with the
    # role's own published support, so it can never exceed the support.  In
    # this fixture every rendered layer covers its role's whole support, so the
    # measurement CLAMPS to the support (pre-R28 it stretched over the whole
    # painted rectangle, which attributed pixels the role did not cover).
    by_id = rows
    for segment_id in (ids.segment_a, ids.segment_b, ids.segment_c):
        assert by_id[segment_id]["bbox"] == by_id[segment_id]["expected_bbox"], (
            "the measured extent must be bounded by the role's own support"
        )
    assert by_id[ids.segment_a]["bbox"] == list(MASK_A_RECT)
    assert by_id[ids.segment_a]["expected_bbox"] == list(MASK_A_RECT)
    assert by_id[ids.segment_c]["expected_bbox"] == list(MASK_C_RECT)
    assert by_id[ids.segment_b]["bbox"] == by_id[ids.segment_b]["expected_bbox"] == list(MASK_B_RECT)

    # the band-level authority summary covers every role, and nothing is flagged
    summary = args["clipping_authority"]
    assert [row["segment_id"] for row in summary["per_segment"]] == [
        row["id"] for row in args["segments"]
    ]
    assert summary["newly_introduced_truncation"] == []
    assert all(row["detector_clearance"] for row in summary["per_segment"])
    assert summary["observation_revision"] == obs.OBSERVATION_REVISION

    # GATE: the frozen detector is the final consumer and reports nothing
    assert _items(args) == []

    _raw(
        "r27_valid_supported_in_frame_measured",
        {
            "row": "R27-01",
            "expected": "each supported role measured inside the frame; verdict "
            "in_frame_measured; the frozen detector reports no clipping item",
            "observed": observed,
            "authority_summary": summary,
            "detector_items": _items(args),
            "transported_chars": _transported(args),
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "PASS",
        },
    )
    assert _no_qc_rows(session_factory) == 0


# ── row 2: the role's published support bytes are gone ──────────────────────


def test_r27_missing_role_mask_is_unmeasurable_not_pass(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        artifact = session.get(Artifact, ids.mask_b)
        relative = str(artifact.relative_path)
        (Path(managed_root) / relative).unlink()

    composed, error = _compose_or_refusal(session_factory, managed_root, ids)
    assert composed is None, "a missing support must never compose a measurement"
    assert error is not None
    failure = _assert_unmeasurable(error, "silhouette_clipping", QC_EVIDENCE_MISSING)
    assert "is absent under the managed root" in failure["message"]
    assert ids.mask_b in failure["message"]
    # nothing was produced for the detector, so no clipped_ratio=0 PASS exists
    assert "silhouette_clipping" not in (composed or {})
    assert _no_qc_rows(session_factory) == 0

    _raw(
        "r27_missing_role_mask_is_unmeasurable_not_pass",
        {
            "row": "R27-02",
            "expected": "typed QC_EVIDENCE_MISSING for the role whose published "
            "support bytes are absent; the band produces NO argument set, so no "
            "measured clipped_ratio=0 PASS can exist",
            "observed": {
                "aggregate_code": error.code,
                "detector_code": failure["code"],
                "message": failure["message"],
                "artifact_id": ids.mask_b,
                "relative_path": relative,
                "composed_detectors": sorted((composed or {}).keys()),
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "TYPED_REFUSAL (nothing measured)",
        },
    )


# ── row 3: empty / uniform geometry has NO measurement ──────────────────────


def test_r27_empty_uniform_has_no_measurement(evidence_db, tmp_path: Path) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    empty_id = _publish_png_bytes(
        session_factory, managed_root, ids, _blank_png(), rel="media/mask_b_blank.png"
    )
    _repoint_support(session_factory, ids.segment_b, empty_id)

    composed, error = _compose_or_refusal(session_factory, managed_root, ids)
    assert composed is None, "an empty support must never compose a measurement"
    assert error is not None
    empty_failure = _assert_unmeasurable(error, "silhouette_clipping", QC_EVIDENCE_MALFORMED)
    assert "no non-zero pixels" in empty_failure["message"]

    # the observation primitive refuses the same empty support on its own
    with pytest.raises(QcEvidenceError) as primitive:
        obs.support_mask(np.zeros((CANVAS_H, CANVAS_W), dtype=np.float32))
    assert primitive.value.code == QC_EVIDENCE_MISSING

    # a render that paints NOTHING (one uniform level) is equally unmeasurable
    factory2, managed2, ids2 = _second_world(tmp_path)
    _write_render(
        factory2,
        managed2,
        ids2,
        (((0, 0, CANVAS_W, CANVAS_H), range(0, TOTAL_FRAMES), 0),),
    )
    uniform_frame = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    assert obs.rendered_object_bbox(uniform_frame, region=MASK_B_RECT, detector="r27") is None
    composed2, error2 = _compose_or_refusal(factory2, managed2, ids2)
    assert composed2 is None, "a render with no painted object must never compose"
    assert error2 is not None
    uniform_failure = _assert_unmeasurable(
        error2, "silhouette_clipping", QC_EVIDENCE_DEPENDENCY
    )
    assert "paints NO object inside segment" in uniform_failure["message"]

    _raw(
        "r27_empty_uniform_has_no_measurement",
        {
            "row": "R27-03",
            "expected": "an empty/uniform support and an all-one-level render "
            "both yield NO measurement: typed refusal, never a 0 PASS",
            "observed": {
                "empty_support": {
                    "code": empty_failure["code"],
                    "message": empty_failure["message"],
                    "artifact_id": empty_id,
                },
                "uniform_render": {
                    "code": uniform_failure["code"],
                    "message": uniform_failure["message"],
                },
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "TYPED_REFUSAL (nothing measured)",
        },
    )


# ── row 4: geometry unrelated to the role is refused ────────────────────────


def test_r27_unrelated_checkerboard_geometry_refused(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    unrelated = (420, 60, 540, 140)
    checker_id = _publish_png_bytes(
        session_factory,
        managed_root,
        ids,
        _checker_png(unrelated),
        rel="media/mask_b_unrelated.png",
    )
    _repoint_support(session_factory, ids.segment_b, checker_id)

    composed, error = _compose_or_refusal(session_factory, managed_root, ids)
    assert composed is None, "unrelated geometry must never compose a measurement"
    assert error is not None
    failure = _assert_unmeasurable(error, "silhouette_clipping", QC_EVIDENCE_DEPENDENCY)
    assert "paints NO object inside segment" in failure["message"]

    # the observation level: the render paints NOTHING in that unrelated region,
    # so there is no object there to measure — and a region that is not the
    # role's own published extent is refused outright.
    frame = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    frame[160:200, 300:340] = RENDER_LEVEL
    support = np.zeros((CANVAS_H, CANVAS_W), dtype=np.float32)
    support[60:140, 420:540] = 1.0
    assert obs.rendered_object_bbox(frame, region=unrelated, detector="r27") is None
    with pytest.raises(QcEvidenceError) as region_refusal:
        obs.supported_object_bbox(frame, support=support, region=MASK_B_RECT, detector="r27")
    assert region_refusal.value.code == QC_EVIDENCE_MALFORMED
    assert "is not the role's own published extent" in region_refusal.value.message

    _raw(
        "r27_unrelated_checkerboard_geometry_refused",
        {
            "row": "R27-04",
            "expected": "geometry unrelated to the role (a checkerboard region the "
            "render never paints) is refused: no object there to measure, and a "
            "region that is not the role's published extent is refused",
            "observed": {
                "code": failure["code"],
                "message": failure["message"],
                "artifact_id": checker_id,
                "checker_region": list(unrelated),
                "rendered_object_bbox": None,
                "region_refusal": {
                    "code": region_refusal.value.code,
                    "message": region_refusal.value.message,
                },
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "TYPED_REFUSAL (nothing measured)",
        },
    )


# ── row 5: a truncated role whose authority is REJECTED never reads [] ──────


def test_r27_known_truncated_role_is_measured_and_flagged(evidence_db) -> None:  # noqa: ANN001
    """Q-r0 (R28): a KNOWN truncation must NOT end in an empty success.

    Before R28 this row asserted `_items(args) == []` for a role the output
    clips at the frame border — a cut object read as zero risk, because the
    frozen metric (bbox area OUTSIDE the frame) can never carry a
    frame-bounded cut and the composer's authority metadata had no consumer.

    R28 keeps the row and CHANGES ITS FINAL ASSERTION: the scripted world below
    gives the role a rendered-side mask candidate that is INDISTINGUISHABLE
    from another current segment's own published extent (same geometry), which
    the composer must refuse.  The final outcome is therefore a typed refusal
    (or, if the band ever composes, a real finding) — NEVER `[]`.
    """
    session_factory, managed_root, ids = evidence_db
    # Segment B's OWN support does NOT reach the bottom frame side (its pinned
    # mask is MASK_B_RECT), while the RENDER paints BOTTOM_B — so the cut is
    # NOT source-intended and must be attributed or refused, never passed.
    # A rendered-side candidate published at the SAME geometry as segment C's
    # own mask: nothing identifies it as B's rendered-side mask, so it is
    # AMBIGUOUS between roles and must be refused (the R28 identity rule).
    _publish_mask(
        session_factory,
        managed_root,
        ids,
        MASK_C_RECT,
        rel="media/mask_ambiguous_rendered_side.png",
    )
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
            (BOTTOM_B, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )

    composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
    if refusal is not None:
        # The band refused — assert it refused for the RIGHT reason and that a
        # typed code travelled (never a silent pass).
        failure = _detector_failure(refusal, "silhouette_clipping")
        assert failure["code"] in TYPED_REFUSALS, failure
        observed = {
            "disposition": "TYPED_REFUSAL",
            "code": failure["code"],
            "segment_id": ids.segment_b,
        }
    else:
        # If the band composed, the FINAL consumer must report a REAL finding
        # for the truncated role — an empty list is the exact defect R28 closes.
        args = composed["silhouette_clipping"]
        row = _rows(args)[ids.segment_b]
        auth = row["clipping_authority"]
        items = _items(args)
        assert items, (
            "a known truncated role composed to an EMPTY detector result; the "
            f"authority was {auth['verdict']!r} with clearance "
            f"{auth['detector_clearance']!r} — a cut object read as zero risk "
            "(the R28 defect)"
        )
        assert any(item["layer_ref_id"] == ids.segment_b for item in items), items
        observed = {
            "disposition": "REAL_FINDING",
            "verdict": auth["verdict"],
            "detector_clearance": auth["detector_clearance"],
            "bbox": row["bbox"],
            "detector_items": len(items),
        }
        assert auth["verdict"] in (
            obs.GEOMETRY_NEW_TRUNCATION,
            obs.GEOMETRY_UNATTRIBUTABLE,
        ), auth["verdict"]
        assert auth["detector_clearance"] is False

    # NON-VACUITY: a genuinely measurable world still composes, so the
    # non-pass above is not green-by-construction.
    _raw(
        "r27_known_truncated_role_is_measured_and_flagged",
        {
            "row": "Q-r0",
            "expected": "a known truncation NEVER ends in an empty success: the "
            "final outcome is a typed refusal or a real finding, never []",
            "observed": observed,
            "frozen_metric_limit": "the metric is bbox area OUTSIDE the frame "
            "and a decoded-pixel bbox is frame-bounded, so a frame-bounded cut "
            "can never appear as a positive clipped_ratio",
        },
    )
    assert _no_qc_rows(session_factory) == 0


# ── row 6: a source-intended edge contact is NOT new clipping ───────────────


def test_r27_source_intended_edge_contact_not_clipping(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    bottom_mask = _publish_mask(
        session_factory, managed_root, ids, BOTTOM_B, rel="media/mask_b_bottom.png"
    )
    _repoint_support(session_factory, ids.segment_b, bottom_mask)
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
            (BOTTOM_B, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )

    composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
    assert refusal is None, refusal
    args = composed["silhouette_clipping"]
    row = _rows(args)[ids.segment_b]
    auth = row["clipping_authority"]

    assert row["bbox"] == row["expected_bbox"] == list(BOTTOM_B)
    assert row["border_contact"] == ["bottom"]
    assert auth["verdict"] == obs.GEOMETRY_SOURCE_INTENDED_EDGE
    assert auth["detector_clearance"] is True
    assert auth["newly_introduced_truncation"] is False
    assert auth["role_extent_reaches_sides"] == ["bottom"]
    assert auth["sides_intended_by_source"] == ["bottom"]
    assert auth["sides_not_reached_by_role_extent"] == []

    # NOT clipping: nothing is flagged at the band level and the frozen detector
    # reports no item for any role.
    assert args["clipping_authority"]["newly_introduced_truncation"] == []
    assert _items(args) == []

    _raw(
        "r27_source_intended_edge_contact_not_clipping",
        {
            "row": "R27-06",
            "expected": "a frame side the ROLE'S OWN published extent already "
            "reaches is source-intended partial visibility: measured, cleared, "
            "NOT reported as clipping",
            "observed": {
                "segment_id": ids.segment_b,
                "bbox": row["bbox"],
                "expected_bbox": row["expected_bbox"],
                "border_contact": row["border_contact"],
                "verdict": auth["verdict"],
                "detector_clearance": auth["detector_clearance"],
                "sides_intended_by_source": auth["sides_intended_by_source"],
                "flagged_segment_ids": args["clipping_authority"][
                    "newly_introduced_truncation"
                ],
                "detector_items": _items(args),
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "PASS (measured, not clipping)",
        },
    )


# ── row 7: a segment bound to another segment's published mask ──────────────


def test_r27_foreign_role_segment_frame_refused(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    _repoint_support(session_factory, ids.segment_b, ids.mask_a)

    composed, error = _compose_or_refusal(session_factory, managed_root, ids)
    assert composed is None, "a foreign role binding must never compose a measurement"
    assert error is not None
    failure = _assert_unmeasurable(error, "silhouette_clipping", QC_EVIDENCE_MALFORMED)
    message = failure["message"]
    assert ids.segment_b in message
    assert ids.mask_a in message
    assert ids.segment_a in message
    assert "binding is inconsistent" in message

    _raw(
        "r27_foreign_role_segment_frame_refused",
        {
            "row": "R27-07",
            "expected": "segment B bound to segment A's published mask is refused: "
            "the measurement region is not this role's geometry",
            "observed": {
                "code": failure["code"],
                "message": message,
                "segment_id": ids.segment_b,
                "foreign_artifact_id": ids.mask_a,
                "conflicting_segment_id": ids.segment_a,
                "composed_detectors": sorted((composed or {}).keys()),
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "TYPED_REFUSAL (nothing measured)",
        },
    )


# ── row 8: no pinned support was ever published for the role ────────────────


def test_r27_missing_expected_support_unmeasurable(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    _repoint_support(session_factory, ids.segment_b, None)

    composed, error = _compose_or_refusal(session_factory, managed_root, ids)
    assert composed is None, "a role with no pinned support must never compose"
    assert error is not None
    failure = _assert_unmeasurable(error, "silhouette_clipping", QC_EVIDENCE_MISSING)
    assert "records no mask artifact id" in failure["message"]

    _raw(
        "r27_missing_expected_support_unmeasurable",
        {
            "row": "R27-08",
            "expected": "a role whose pinned expected support was never published "
            "is unmeasurable: typed QC_EVIDENCE_MISSING, no argument set produced",
            "observed": {
                "code": failure["code"],
                "message": failure["message"],
                "segment_id": ids.segment_b,
                "binding": None,
                "composed_detectors": sorted((composed or {}).keys()),
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "TYPED_REFUSAL (nothing measured)",
        },
    )


# ── row 9: the argv-transported payload stays bounded AND retained ──────────


def test_r27_bounded_payload_retained(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    # a world where the authority block carries a real contact (worst case for
    # the transported size: every role row plus the band-level summary)
    edge_mask = _publish_mask(
        session_factory, managed_root, ids, BOTTOM_B, rel="media/mask_b_bound.png"
    )
    _repoint_support(session_factory, ids.segment_b, edge_mask)
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
            (BOTTOM_B, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )
    composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
    assert refusal is None, refusal

    measured: dict[str, int] = {}
    for name, args in composed.items():
        transported = _transported(args)
        measured[name] = transported
        # the SAME transport runner.py uses (sys.argv[2] of the child process)
        assert transported <= composer.ARGV_DETECTOR_ARGS_BUDGET_BYTES, (name, transported)
        assert transported < composer.ARGV_CEILING_SPAWN_OK_BYTES, (name, transported)

    # RETAINED: every per-role control is still shipped in the bounded set
    args = composed["silhouette_clipping"]
    row_keys = {frozenset(row.keys()) for row in args["segments"]}
    assert len(row_keys) == 1
    assert row_keys.pop() == frozenset(
        {
            "id",
            "logical_id",
            "start_frame",
            "end_frame",
            "mask_artifact_id",
            "bbox",
            "expected_bbox",
            "observed_frames",
            "render_background_level_per_frame",
            "border_contact",
            "clipping_authority",
            "measured_on",
        }
    )
    assert len(args["segments"]) == 3
    assert len(args["clipping_authority"]["per_segment"]) == 3
    masks = args["evidence_provenance"]["families"]["artifact"]["masks"]
    assert len(masks) == 3
    # one provenance row per role, each the artifact that role is BOUND to
    assert {row["artifact_id"] for row in masks} == {
        row["mask_artifact_id"] for row in args["segments"]
    }
    # the bounded set is still a REAL contract set: the detector consumes it
    assert _items(args) == []

    _raw(
        "r27_bounded_payload_retained",
        {
            "row": "R27-09",
            "expected": "every composed detector's argv-transported argument set "
            "stays inside the project budget and below the measured spawn "
            "ceiling, while every per-role control is retained",
            "observed": {
                "transport": "sys.argv[2] (json.dumps(args, separators=(',', ':')))",
                "budget_bytes": composer.ARGV_DETECTOR_ARGS_BUDGET_BYTES,
                "spawn_ok_ceiling_bytes": composer.ARGV_CEILING_SPAWN_OK_BYTES,
                "measured_transported_bytes": measured,
                "segment_rows": len(args["segments"]),
                "authority_rows": len(args["clipping_authority"]["per_segment"]),
                "mask_provenance_rows": len(masks),
                "detector_items": _items(args),
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "PASS (bounded + retained)",
        },
    )


# ── row 10: per-role controls retained (with a NON-VACUITY control) ─────────


def test_r27_per_role_controls_retained(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
    assert refusal is None, refusal
    args = composed["silhouette_clipping"]
    rows = _rows(args)

    # every role keeps its OWN binding and its OWN persisted geometry
    binding = {
        ids.segment_a: ids.mask_a,
        ids.segment_b: ids.mask_b,
        ids.segment_c: ids.mask_c,
    }
    expected_bbox = {
        ids.segment_a: list(MASK_A_RECT),
        ids.segment_b: list(MASK_B_RECT),
        ids.segment_c: list(MASK_C_RECT),
    }
    for segment_id, artifact_id in binding.items():
        assert rows[segment_id]["mask_artifact_id"] == artifact_id
        assert rows[segment_id]["expected_bbox"] == expected_bbox[segment_id]
        assert rows[segment_id]["clipping_authority"]["role_extent_bbox"] == expected_bbox[segment_id]
        assert rows[segment_id]["observed_frames"], "no frame was measured for this role"
        assert rows[segment_id]["render_background_level_per_frame"]

    summary = args["clipping_authority"]
    assert [row["segment_id"] for row in summary["per_segment"]] == [
        row["id"] for row in args["segments"]
    ]
    assert len(summary["per_segment"]) == len(binding)

    # NON-VACUITY: the frozen detector still emits ONE blocker per role when a
    # role's geometry genuinely lies outside the frame.  Without this control
    # every `_items(args) == []` above would be green by construction.
    control = copy.deepcopy(args)
    for row in control["segments"]:
        row["bbox"] = [0.0, 0.0, float(CANVAS_W), float(2 * CANVAS_H)]
    items = _items(control)
    assert len(items) == len(binding)
    assert {item["layer_ref_id"] for item in items} == set(binding)
    assert {item["severity"] for item in items} == {"blocker"}
    assert {item["evidence"]["clipped_ratio"] for item in items} == {0.5}

    _raw(
        "r27_per_role_controls_retained",
        {
            "row": "R27-10",
            "expected": "every role keeps its own support binding, its own measured "
            "row and the band-level summary covers every role; the frozen detector "
            "still emits one blocker per role for frame-external geometry",
            "observed": {
                "roles": sorted(str(key)[:8] for key in binding),
                "segment_rows": len(args["segments"]),
                "authority_rows": len(summary["per_segment"]),
                "per_role_binding_retained": True,
                "control_items": len(items),
                "control_item_roles": sorted(str(item["layer_ref_id"])[:8] for item in items),
                "control_severities": sorted({item["severity"] for item in items}),
                "control_clipped_ratio": sorted(
                    {item["evidence"]["clipped_ratio"] for item in items}
                ),
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "PASS (per-role controls retained, non-vacuous)",
        },
    )


# ── R28 rows: the authority must be IDENTITY-bound, UNIQUE and CLEARING ─────


def _mask_png(size: tuple[int, int], rect: tuple[int, int, int, int]) -> bytes:
    """A real grayscale PNG of ARBITRARY canvas size with one lit rectangle."""
    from PIL import Image

    width, height = int(size[0]), int(size[1])
    array = np.zeros((height, width), dtype=np.uint8)
    x0, y0, x1, y1 = rect
    array[y0:y1, x0:x1] = 255
    buffer = io.BytesIO()
    Image.fromarray(array, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()


def _ring_png(rect: tuple[int, int, int, int], hole: tuple[int, int, int, int]) -> bytes:
    """A real 640x360 mask lit on ``rect`` with ``hole`` punched out of it."""
    from PIL import Image

    array = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    x0, y0, x1, y1 = rect
    array[y0:y1, x0:x1] = 255
    hx0, hy0, hx1, hy1 = hole
    array[hy0:hy1, hx0:hx1] = 0
    buffer = io.BytesIO()
    Image.fromarray(array, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()


def test_r28_full_canvas_checker_refused(evidence_db) -> None:  # noqa: ANN001
    """Q-1: a full-canvas checker support cannot establish a role's extent.

    The artifact is byte-distinct, canvas-matching and "bounds" the role, i.e.
    every condition the old first-overlap lookup tested — yet a mask that fills
    the whole frame says nothing about WHERE the role is and would make every
    frame side look source-intended.  Both an in-frame render and a clipped
    render must refuse, and the mask must never become an identity role.
    """
    session_factory, managed_root, ids = evidence_db
    checker = _checker_png((0, 0, CANVAS_W, CANVAS_H))
    artifact = _publish_png_bytes(
        session_factory, managed_root, ids, checker,
        rel="media/r28_mask_b_full_canvas_checker.png",
    )
    _repoint_support(session_factory, ids.segment_b, artifact)

    observed: dict[str, dict] = {}
    for label, layers in (
        (
            "render_in_frame",
            (
                (DELTA_RECT, range(0, 10), RENDER_LEVEL),
                (MASK_B_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
                (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            ),
        ),
        (
            "render_clipped",
            (
                (DELTA_RECT, range(0, 10), RENDER_LEVEL),
                (BOTTOM_B, range(10, TOTAL_FRAMES), RENDER_LEVEL),
                (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            ),
        ),
    ):
        _write_render(session_factory, managed_root, ids, layers)
        composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
        assert composed is None, f"{label}: a full-canvas support must never compose"
        assert refusal is not None, label
        failure = _assert_unmeasurable(
            refusal, "silhouette_clipping", QC_EVIDENCE_MALFORMED
        )
        assert "WHOLE frame" in failure["message"], failure["message"]
        assert "cannot establish where this role is" in failure["message"]
        observed[label] = {
            "code": failure["code"],
            "message_head": failure["message"][:200],
        }

    _raw(
        "r28_full_canvas_checker_refused",
        {
            "row": "Q-1",
            "expected": "a mask that spans the whole frame is refused as an "
            "authority for BOTH an in-frame and a clipped render; it never "
            "becomes an identity role for the geometry",
            "observed": observed,
            "support_artifact_id": artifact,
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "TYPED_REFUSAL (nothing measured)",
        },
    )
    assert _no_qc_rows(session_factory) == 0


def test_r28_uniform_support_refused(evidence_db) -> None:  # noqa: ANN001
    """Q-2: a uniform support carries no geometry and must refuse.

    Two shapes are measured: a full-canvas WHITE mask (bounds every pixel) and
    an all-zero BLANK mask (bounds nothing).  Neither may be read as a role's
    extent, and neither may clear a clipping question.
    """
    session_factory, managed_root, ids = evidence_db
    observed: dict[str, dict] = {}

    white = _conftest._png_bytes((0, 0, CANVAS_W, CANVAS_H))  # noqa: SLF001
    white_id = _publish_png_bytes(
        session_factory, managed_root, ids, white, rel="media/r28_mask_b_white.png"
    )
    _repoint_support(session_factory, ids.segment_b, white_id)
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
            (BOTTOM_B, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )
    composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
    assert composed is None, "a full-canvas uniform support must never compose"
    assert refusal is not None
    failure = _assert_unmeasurable(refusal, "silhouette_clipping", QC_EVIDENCE_MALFORMED)
    assert "WHOLE frame" in failure["message"], failure["message"]
    observed["white_full_canvas"] = {
        "artifact_id": white_id,
        "code": failure["code"],
        "message_head": failure["message"][:200],
    }

    blank = _blank_png()
    blank_id = _publish_png_bytes(
        session_factory, managed_root, ids, blank, rel="media/r28_mask_b_blank.png"
    )
    _repoint_support(session_factory, ids.segment_b, blank_id)
    composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
    assert composed is None, "an all-zero support must never compose"
    assert refusal is not None
    # MEASURED: an all-zero mask is refused at the decode boundary as MALFORMED
    # ("contains no non-zero pixels") rather than reaching the later empty-bounds
    # check — both are typed refusals; the assertion follows the real behaviour.
    failure = _assert_unmeasurable(refusal, "silhouette_clipping", QC_EVIDENCE_MALFORMED)
    assert "no non-zero pixels" in failure["message"], failure["message"]
    observed["uniform_blank"] = {
        "artifact_id": blank_id,
        "code": failure["code"],
        "message_head": failure["message"][:200],
    }

    _raw(
        "r28_uniform_support_refused",
        {
            "row": "Q-2",
            "expected": "a uniform support (all-white full canvas, all-zero "
            "blank) is refused in both shapes; it can never clear a role",
            "observed": observed,
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "TYPED_REFUSAL (nothing measured)",
        },
    )
    assert _no_qc_rows(session_factory) == 0


def test_r28_hollow_support_does_not_authorize_interior(evidence_db) -> None:  # noqa: ANN001
    """Q-3: the support's PIXELS decide attribution, not its bounding box.

    The role's published support is a ring whose interior it does NOT cover.
    The output paints an object ONLY inside that hollow interior, so nothing
    attributes it to this role and the band must refuse — the old code read the
    ring's bbox and measured the interior as the role's silhouette.
    """
    session_factory, managed_root, ids = evidence_db
    hole = (312, 172, 328, 188)
    ring = _ring_png(MASK_B_RECT, hole)
    ring_id = _publish_png_bytes(
        session_factory, managed_root, ids, ring, rel="media/r28_mask_b_hollow.png"
    )
    _repoint_support(session_factory, ids.segment_b, ring_id)
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
            (hole, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )
    composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
    assert composed is None, "an interior-only object is NOT this role's silhouette"
    assert refusal is not None
    failure = _assert_unmeasurable(
        refusal, "silhouette_clipping", QC_EVIDENCE_DEPENDENCY
    )
    assert "paints NO object inside segment" in failure["message"], failure["message"]
    _raw(
        "r28_hollow_support_does_not_authorize_interior",
        {
            "row": "Q-3",
            "expected": "an object painted only where the role's support has NO "
            "pixels is not attributable to the role: typed refusal, never a "
            "measurement of the ring's bounding box",
            "observed": {
                "code": failure["code"],
                "message_head": failure["message"][:220],
                "support_artifact_id": ring_id,
                "hole": list(hole),
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "TYPED_REFUSAL (nothing measured)",
        },
    )
    assert _no_qc_rows(session_factory) == 0


def test_r28_foreign_same_geometry_support_refused(evidence_db) -> None:  # noqa: ANN001
    """Q-4: a candidate whose geometry is ANOTHER role's is refused.

    The role reaches the right frame side, so the rendered-side lookup runs.  A
    byte-distinct candidate overlaps the role AND the extent of a DIFFERENT
    current segment, so nothing attributes it to this role rather than that one:
    the band must refuse and name the segment it collided with, never adopt the
    mask because the boxes touch (the pre-R28 first-overlap behaviour).
    """
    session_factory, managed_root, ids = evidence_db
    b_edge = (560, 100, 640, 200)    # reaches the RIGHT frame side
    c_beside = (440, 100, 520, 200)  # overlaps the candidate, NOT the role
    candidate_rect = (500, 100, 640, 200)  # overlaps BOTH the role and C

    b_mask = _publish_mask(
        session_factory, managed_root, ids, b_edge, rel="media/r28_mask_b_right_edge.png"
    )
    _repoint_support(session_factory, ids.segment_b, b_mask)
    c_mask = _publish_mask(
        session_factory, managed_root, ids, c_beside, rel="media/r28_mask_c_beside.png"
    )
    _repoint_support(session_factory, ids.segment_c, c_mask)
    foreign = _publish_mask(
        session_factory,
        managed_root,
        ids,
        candidate_rect,
        rel="media/r28_mask_foreign_rendered_side.png",
    )
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
            (b_edge, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            (c_beside, range(5, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )

    composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
    assert composed is None, (
        "a candidate that is indistinguishable from another role's extent must "
        "never become this role's rendered-side authority"
    )
    assert refusal is not None
    failure = _assert_unmeasurable(
        refusal, "silhouette_clipping", QC_EVIDENCE_DEPENDENCY
    )
    assert "overlaps ANOTHER current segment" in failure["message"], failure["message"]
    assert foreign in failure["message"], "the refused candidate must be named"
    assert str(list(c_beside)) in failure["message"], (
        "the segment it collided with must be named"
    )
    _raw(
        "r28_foreign_same_geometry_support_refused",
        {
            "row": "Q-4",
            "expected": "a byte-distinct rendered-side candidate whose geometry "
            "collides with ANOTHER current segment's published extent is "
            "refused by identity; nothing is adopted because the boxes overlap",
            "observed": {
                "code": failure["code"],
                "message_head": failure["message"][:260],
                "candidate_artifact_id": foreign,
                "candidate_rect": list(candidate_rect),
                "collided_with_segment_id": ids.segment_c,
                "collided_with_bbox": list(c_beside),
                "role_edge_bbox": list(b_edge),
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "TYPED_REFUSAL (nothing measured)",
        },
    )
    assert _no_qc_rows(session_factory) == 0


def test_r28_wrong_frame_rendered_support_refused(evidence_db) -> None:  # noqa: ANN001
    """Q-5: a rendered-side support on a DIFFERENT canvas is refused.

    The candidate is byte-distinct and ready, but its own decoded geometry is
    half the video canvas: whatever it bounds cannot be this video's rendered
    geometry, so the band refuses instead of measuring a foreign frame.
    """
    session_factory, managed_root, ids = evidence_db
    edge = _publish_mask(
        session_factory, managed_root, ids, BOTTOM_B, rel="media/r28_mask_b_bound.png"
    )
    _repoint_support(session_factory, ids.segment_b, edge)
    wrong_frame = _publish_png_bytes(
        session_factory,
        managed_root,
        ids,
        _mask_png((CANVAS_W // 2, CANVAS_H // 2), (10, 10, 100, 100)),
        rel="media/r28_mask_wrong_frame.png",
    )
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
            (BOTTOM_B, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )
    composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
    assert composed is None, "a wrong-canvas candidate must never be measured"
    assert refusal is not None
    failure = _assert_unmeasurable(
        refusal, "silhouette_clipping", QC_EVIDENCE_MALFORMED
    )
    assert "but the video canvas is" in failure["message"], failure["message"]
    assert f"{CANVAS_W // 2}x{CANVAS_H // 2}" in failure["message"]
    assert wrong_frame in failure["message"], "the offending artifact must be named"
    _raw(
        "r28_wrong_frame_rendered_support_refused",
        {
            "row": "Q-5",
            "expected": "a rendered-side mask artifact published at a different "
            "canvas geometry is refused (fail closed), never decoded as this "
            "video's rendered extent",
            "observed": {
                "code": failure["code"],
                "message_head": failure["message"][:240],
                "candidate_artifact_id": wrong_frame,
                "candidate_canvas": [CANVAS_W // 2, CANVAS_H // 2],
                "video_canvas": [CANVAS_W, CANVAS_H],
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "TYPED_REFUSAL (nothing measured)",
        },
    )
    assert _no_qc_rows(session_factory) == 0


def test_r28_multiple_overlapping_supports_refused(evidence_db) -> None:  # noqa: ANN001
    """Q-6: several overlapping candidates are ambiguous — refuse, never take one.

    Two byte-distinct masks both overlap the role's published extent, so
    nothing identifies WHICH one is this role's rendered-side mask.  The refusal
    must name every candidate, which is the proof that no first-overlap pick
    happened.
    """
    session_factory, managed_root, ids = evidence_db
    edge = _publish_mask(
        session_factory, managed_root, ids, BOTTOM_B, rel="media/r28_mask_b_bound.png"
    )
    _repoint_support(session_factory, ids.segment_b, edge)
    extra = _publish_mask(
        session_factory,
        managed_root,
        ids,
        (320, 160, 360, 360),
        rel="media/r28_mask_overlap_extra.png",
    )
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
            (BOTTOM_B, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )
    composed, refusal = _compose_or_refusal(session_factory, managed_root, ids)
    assert composed is None, "overlapping candidates must refuse, not pick the first"
    assert refusal is not None
    failure = _assert_unmeasurable(
        refusal, "silhouette_clipping", QC_EVIDENCE_DEPENDENCY
    )
    assert "byte-distinct rendered-side masks" in failure["message"], failure["message"]
    assert "nothing identifies WHICH one is THIS role's" in failure["message"]
    named = [aid for aid in (ids.mask_b, extra) if aid in failure["message"]]
    assert len(named) == 2, (
        "every ambiguous candidate must be named so the reviewer can see that no "
        f"candidate was silently chosen; named={named}"
    )
    _raw(
        "r28_multiple_overlapping_supports_refused",
        {
            "row": "Q-6",
            "expected": "two byte-distinct candidates overlapping the role's "
            "extent are ambiguous: refused with every candidate named, never "
            "resolved by overlap or recency",
            "observed": {
                "code": failure["code"],
                "message_head": failure["message"][:280],
                "candidates_named": named,
                "role_extent_bbox": list(BOTTOM_B),
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "TYPED_REFUSAL (nothing measured)",
        },
    )
    assert _no_qc_rows(session_factory) == 0
