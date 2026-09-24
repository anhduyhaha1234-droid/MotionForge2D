"""MF-P1-QC-EVIDENCE — correction round C (Codex R4/R5) acceptance tests.

Target identity comes from the LIBRARY, observation comes from the RENDER.

Q01  identity target = selected CharacterID + immutable PackVersion + the
     library REFERENCE artifact bytes/SHA, with the role / revision /
     workspace / generation provenance, and PER-ROLE coverage for a
     multi-role video (a first-segment-only coverage is never reported as the
     entire cast).
Q02  missing / stale / foreign / tampered / incompatible pin, and an evaluator
     that errors or times out, each refuse with a typed code and ZERO green QC
     publication; ``compatible=True`` is forbidden whenever the evaluator
     fails.
Q03  source facts and rendered observations have SEPARATE authority: every
     output-side detector carries the resolved render artifact SHA + frame
     range/PTS + producer, and a source annotation is never reported as
     observed.
Q04  paired negatives: keeping the source facts, the rendered bytes are
     changed (and the artifact hash updated honestly) — the affected detector
     must then measure the change, refuse, or report the deviation; deleting
     the output or its producer refuses.

Both halves are exercised against the REAL detectors: a composed argument set
is worthless unless the frozen detector consumes it and its measurement moves.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from conftest import (
    DELTA_RECT,
    MASK_B_RECT,
    MASK_C_RECT,
    RENDER_LEVEL,
    TOTAL_FRAMES,
    _video_bytes,
)
from sqlalchemy import delete, select, update

from app.persistence.models import (
    Artifact,
    ArtifactOwner,
    CharacterAsset,
    CharacterPackVersion,
    ProjectCastMapping,
    QCItem,
    SceneGraphOcclusion,
    Workspace,
)
from app.services.qc_checks import (
    contact_break,
    cut_drift,
    identity_drift,
    silhouette_clipping,
    trajectory_drift,
    z_order_error,
)
from app.services.qc_evidence import (
    QC_EVIDENCE_DEPENDENCY,
    QC_EVIDENCE_FOREIGN,
    QC_EVIDENCE_MALFORMED,
    QC_EVIDENCE_MISSING,
    QC_EVIDENCE_STALE,
    QC_EVIDENCE_TAMPERED,
    QcEvidenceError,
    compose_visual_band,
)


def _compose(session_factory, managed_root: Path, ids, **overrides):  # noqa: ANN001
    payload = {
        "workspace_id": ids.workspace_id,
        "project_id": ids.project_id,
        "video_item_id": ids.video_item_id,
    }
    payload.update(overrides)
    with session_factory() as session:
        return compose_visual_band(session, managed_root=managed_root, **payload)


def _codes(error: QcEvidenceError) -> dict[str, str]:
    return dict(error.details.get("refusals") or {})


def _no_qc_rows(session_factory) -> int:  # noqa: ANN001
    with session_factory() as session:
        return len(session.scalars(select(QCItem)).all())


def _rewrite_render(  # noqa: ANN001
    session_factory,
    managed_root: Path,
    ids,
    *,
    square_rect,
    lit_frames,
    extra_layers=(),
) -> bytes:
    """Rewrite the RENDERED artifact bytes and update its recorded hash honestly.

    This is the Q04 mechanism: the source facts are untouched, only the output
    bytes change, and the artifact row is updated to the TRUE sha256/size of
    the new bytes (never a fabricated hash).
    """
    with session_factory() as session:
        artifact = session.get(Artifact, ids.render_artifact_id)
        target = Path(managed_root) / str(artifact.relative_path)
        data = _video_bytes(
            target,
            square_rect=square_rect,
            lit_frames=lit_frames,
            level=RENDER_LEVEL,
            extra_layers=extra_layers,
        )
        artifact.sha256 = hashlib.sha256(data).hexdigest()
        artifact.size_bytes = len(data)
        session.commit()
    return data


# ── Q01: the target identity comes from the library ────────────────────────


def test_identity_target_is_the_pinned_library_reference_not_the_source(evidence_db) -> None:  # noqa: ANN001, E501
    session_factory, managed_root, ids = evidence_db
    args = _compose(session_factory, managed_root, ids)["identity_drift"]
    reference_id = ids.reference_artifact_ids["Character"]
    pinned = args["pinned_reference"]
    assert pinned["artifact_id"] == reference_id
    assert pinned["artifact_id"] != ids.source_artifact_id
    assert pinned["artifact_id"] != ids.render_artifact_id
    with session_factory() as session:
        row = session.get(Artifact, reference_id)
        asset = session.scalar(
            select(CharacterAsset).where(
                CharacterAsset.pose_slot == "reference",
                CharacterAsset.pack_version_id == ids.pack_version_ids["Character"],
            )
        )
    assert str(row.sha256) == pinned["artifact_sha256"]
    assert str(asset.artifact_id) == reference_id
    identity = pinned["identity"]
    assert identity["character_id"] == ids.character_ids["Character"]
    assert identity["pack_version_id"] == ids.pack_version_ids["Character"]
    assert identity["workspace_id"] == ids.workspace_id
    assert identity["source_generation"]
    assert identity["pack_version_revision"] == 1
    assert identity["pose_slot"] == "reference"
    # the observation side is the RENDER, in the same window
    assert {frame["artifact_id"] for frame in args["frames"]} == {ids.render_artifact_id}
    assert args["render_observation"]["artifact"]["artifact_id"] == ids.render_artifact_id
    assert args["render_observation"]["pts_ms"]["timebase"] == {"fps_num": 30, "fps_den": 1}


def test_identity_coverage_enumerates_every_rendered_role(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    args = _compose(session_factory, managed_root, ids)["identity_drift"]
    cast_pin = args["cast_pin"]
    coverage = cast_pin["cast_coverage"]
    assert cast_pin["roles_total"] == len(ids.role_ids) == 3
    assert cast_pin["roles_covered"] == cast_pin["roles_total"]
    assert cast_pin["uncovered_role_ids"] == []
    assert {row["object_role_id"] for row in coverage} == set(ids.role_ids.values())
    for row in coverage:
        assert row["character_id"] in ids.character_ids.values()
        assert row["pack_version_id"] in ids.pack_version_ids.values()
        assert row["reference_artifact"]["sha256"]
        assert len(row["reference_artifact"]["sha256"]) == 64
        assert row["segment_row_ids"]
    # the measurement scope is declared explicitly — never "the entire cast"
    assert cast_pin["coverage_scope"] == "single_role"
    assert cast_pin["measured_role_id"] == ids.role_ids["Character"]
    assert {row["object_role_id"] for row in cast_pin["role_observations"]} == set(
        ids.role_ids.values()
    )
    assert all(row["rendered_frames"] for row in cast_pin["role_observations"])


def test_identity_refuses_when_one_role_of_the_cast_has_no_pin(evidence_db) -> None:  # noqa: ANN001
    """A first-segment-only coverage may never be published as the cast."""
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        session.execute(
            delete(ProjectCastMapping).where(
                ProjectCastMapping.id == ids.cast_mapping_ids["Prop"]
            )
        )
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    assert _codes(raised.value)["identity_drift"] == QC_EVIDENCE_MISSING
    assert _no_qc_rows(session_factory) == 0


# ── Q02: typed refusals, never a fail-open verdict ─────────────────────────


def test_compatibility_evaluator_error_is_a_typed_refusal_never_compatible_true(  # noqa: ANN001, E501
    evidence_db, monkeypatch
) -> None:
    import app.persistence.project_cast as cast_module

    session_factory, managed_root, ids = evidence_db

    def _explode(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("probe compatibility query failure")

    monkeypatch.setattr(cast_module, "evaluate_compatibility", _explode)
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    error = raised.value
    assert _codes(error)["identity_drift"] == QC_EVIDENCE_DEPENDENCY
    details = error.details["failed_detectors"]["identity_drift"]["details"]
    assert details["evaluator_error_type"] == "RuntimeError"
    assert "probe compatibility query failure" in details["evaluator_error"]
    assert "evaluate_compatibility" in details["dependency"]["missing_producer"]
    # no green publication anywhere: nothing composed, nothing persisted
    assert "refusals" in error.details
    assert _no_qc_rows(session_factory) == 0


def test_incompatible_pin_refuses_instead_of_measuring_identity(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        session.execute(
            update(CharacterPackVersion)
            .where(CharacterPackVersion.id == ids.pack_version_ids["Character"])
            .values(status="draft")
        )
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    error = raised.value
    assert _codes(error)["identity_drift"] == QC_EVIDENCE_STALE
    details = error.details["failed_detectors"]["identity_drift"]["details"]
    assert "unpublished_pack" in details["reasons"]
    assert details["compatibility"]["compatible"] is False
    assert _no_qc_rows(session_factory) == 0


def test_missing_reference_asset_is_a_dependency_not_a_source_substitution(evidence_db) -> None:  # noqa: ANN001, E501
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        session.execute(
            delete(CharacterAsset).where(
                CharacterAsset.pose_slot == "reference",
                CharacterAsset.pack_version_id == ids.pack_version_ids["Character"],
            )
        )
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    error = raised.value
    assert _codes(error)["identity_drift"] == QC_EVIDENCE_DEPENDENCY
    report = error.details["failed_detectors"]["identity_drift"]["details"]["dependency"]
    assert "reference" in report["missing_producer"]


def test_tampered_reference_bytes_refuse(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        artifact = session.get(Artifact, ids.reference_artifact_ids["Character"])
        target = Path(managed_root) / str(artifact.relative_path)
    original = target.read_bytes()
    tampered = bytearray(original)
    tampered[-1] = tampered[-1] ^ 0xFF
    try:
        target.write_bytes(bytes(tampered))
        with pytest.raises(QcEvidenceError) as raised:
            _compose(session_factory, managed_root, ids)
        assert _codes(raised.value)["identity_drift"] == QC_EVIDENCE_TAMPERED
    finally:
        target.write_bytes(original)


def test_foreign_pinned_target_is_refused(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        session.add(Workspace(id="ws-p1qc-foreign", name="ws-p1qc-foreign"))
        session.flush()
        session.execute(
            update(CharacterPackVersion)
            .where(CharacterPackVersion.id == ids.pack_version_ids["Character"])
            .values(workspace_id="ws-p1qc-foreign")
        )
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    assert _codes(raised.value)["identity_drift"] == QC_EVIDENCE_FOREIGN


# ── Q03: separate authority for source facts vs rendered observation ──────

_RENDER_OBSERVED_DETECTORS = (
    "trajectory_drift",
    "cut_drift",
    "contact_break",
    "z_order_error",
    "silhouette_clipping",
    "identity_drift",
    "temporal_flicker",
)


def test_every_output_side_detector_carries_the_render_sha_range_pts_and_producer(evidence_db) -> None:  # noqa: ANN001, E501
    session_factory, managed_root, ids = evidence_db
    composed = _compose(session_factory, managed_root, ids)
    with session_factory() as session:
        render_sha = str(session.get(Artifact, ids.render_artifact_id).sha256)
    for detector in _RENDER_OBSERVED_DETECTORS:
        observation = composed[detector]["render_observation"]
        assert observation["artifact"]["artifact_id"] == ids.render_artifact_id, detector
        assert observation["artifact"]["sha256"] == render_sha, detector
        assert observation["artifact"]["bytes_reverified"] is True, detector
        assert observation["producer"], detector
        assert observation["producer_persistence"], detector
        assert observation["window"]["end_frame"] >= observation["window"]["start_frame"]
        assert observation["pts_ms"]["timebase"] == {"fps_num": 30, "fps_den": 1}
        assert observation["pts_ms"]["end_ms"] >= observation["pts_ms"]["start_ms"]
        assert observation["measure"], detector
    # edge_halo observes the RENDERED-side published mask, not the video render
    halo = composed["edge_halo"]["rendered_observation"]
    assert halo["artifact"]["artifact_id"] == ids.mask_rendered
    assert halo["artifact"]["bytes_reverified"] is True
    assert "mask" in halo["producer"]
    assert halo["pts_ms"]["timebase"] == {"fps_num": 30, "fps_den": 1}
    # a source annotation is never carried as an observed value
    assert composed["silhouette_clipping"]["segments"][0]["bbox"]
    assert composed["silhouette_clipping"]["segments"][0]["expected_bbox"]
    assert composed["cut_drift"]["render_cuts_ms"]
    assert composed["cut_drift"]["planned_cuts_ms"]
    assert composed["z_order_error"]["render_order"]
    assert "lock_manifest" not in composed["z_order_error"]


def test_source_side_values_and_observed_values_are_different_keys(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    composed = _compose(session_factory, managed_root, ids)
    # cut_drift: the planned (source) cut timecodes are recorded separately
    # from the observed ones and the two are never conflated.
    assert composed["cut_drift"]["render_cuts_ms"] == [0, 333]
    assert composed["cut_drift"]["planned_cuts_ms"] == [0, 333]
    assert composed["cut_drift"]["cut_observations"][1]["delta"] > 0.0
    # z_order: the persisted scene-graph z_order is only an annotation; the
    # order the detector judges is the MEASURED one.
    stacking = composed["z_order_error"]["render_stacking"][0]
    assert stacking["measured_on_top"] == stacking["occluder_segment_id"]
    assert stacking["agrees_with_annotation"] is True
    assert stacking["overlap_px"] > 0


# ── Q04: paired negatives on the OUTPUT bytes ─────────────────────────────


def test_deleting_the_render_file_refuses_every_output_side_detector(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        artifact = session.get(Artifact, ids.render_artifact_id)
        target = Path(managed_root) / str(artifact.relative_path)
    original = target.read_bytes()
    target.unlink()
    try:
        with pytest.raises(QcEvidenceError) as raised:
            _compose(session_factory, managed_root, ids)
        codes = _codes(raised.value)
        for detector in (
            "cut_drift",
            "contact_break",
            "z_order_error",
            "silhouette_clipping",
        ):
            assert codes[detector] == QC_EVIDENCE_MISSING, (detector, codes)
        for detector in _RENDER_OBSERVED_DETECTORS:
            assert codes[detector] in (QC_EVIDENCE_MISSING, QC_EVIDENCE_DEPENDENCY), (
                detector,
                codes,
            )
        # the source-side-only detector is unaffected by the output deletion
        assert "edge_halo" not in codes
        assert _no_qc_rows(session_factory) == 0
    finally:
        target.write_bytes(original)


def test_removing_the_render_producer_refuses_instead_of_substituting_the_source(evidence_db) -> None:  # noqa: ANN001, E501
    """No render-side artifact at all: the composer must NOT measure the
    imported source against itself."""
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        session.execute(
            delete(ArtifactOwner).where(ArtifactOwner.artifact_id == ids.render_artifact_id)
        )
        session.execute(delete(Artifact).where(Artifact.id == ids.render_artifact_id))
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    codes = _codes(raised.value)
    for detector in _RENDER_OBSERVED_DETECTORS:
        assert codes[detector] == QC_EVIDENCE_DEPENDENCY, (detector, codes)
    dependency = (
        raised.value.details["failed_detectors"]["cut_drift"]["details"]["dependency"]
    )
    assert dependency["missing_producer"]
    assert _no_qc_rows(session_factory) == 0


def test_shifting_the_rendered_cut_changes_the_observed_cut(evidence_db) -> None:  # noqa: ANN001
    """Keep the source facts, move the cut in the OUTPUT: the observed value
    must follow the render (the planned value never moves)."""
    session_factory, managed_root, ids = evidence_db
    _rewrite_render(
        session_factory,
        managed_root,
        ids,
        square_rect=DELTA_RECT,
        lit_frames=range(0, 9),
        extra_layers=(
            (MASK_B_RECT, range(9, TOTAL_FRAMES)),
            (MASK_C_RECT, range(9, TOTAL_FRAMES)),
        ),
    )
    args = _compose(session_factory, managed_root, ids)["cut_drift"]
    assert args["render_cuts_ms"] == [0, 300]
    assert args["planned_cuts_ms"] == [0, 333]
    assert args["cut_observations"][1]["observed_frame"] == 9
    out = cut_drift.detect(args)
    assert out["measurements"][1]["value"] == 1.0


def test_removing_the_rendered_cut_refuses_cut_drift(evidence_db) -> None:  # noqa: ANN001
    """The output carries one continuous layer across the boundary the scene
    ground truth calls a cut: the check refuses instead of reporting the
    planned timecode as if it had been observed."""
    session_factory, managed_root, ids = evidence_db
    _rewrite_render(
        session_factory,
        managed_root,
        ids,
        square_rect=DELTA_RECT,
        lit_frames=range(0, TOTAL_FRAMES),
    )
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    assert _codes(raised.value)["cut_drift"] == QC_EVIDENCE_MISSING
    assert _no_qc_rows(session_factory) == 0


def test_flipping_the_rendered_stacking_flips_the_measured_order(evidence_db) -> None:  # noqa: ANN001
    """Paint the occludee's layer over the overlap in the OUTPUT: the measured
    order must flip (the annotation is unchanged)."""
    session_factory, managed_root, ids = evidence_db
    # frames 5..9: the painted layer covers C's mask region but NOT A's
    # exclusive area, so the overlap appearance matches the occludee's
    # exclusive appearance -> the measured top flips to the occludee.
    overlay = (MASK_C_RECT[0], DELTA_RECT[1], DELTA_RECT[2], DELTA_RECT[3])
    _rewrite_render(
        session_factory,
        managed_root,
        ids,
        square_rect=DELTA_RECT,
        lit_frames=range(0, 5),
        extra_layers=(
            (overlay, range(5, 10)),
            (MASK_B_RECT, range(10, TOTAL_FRAMES)),
            (MASK_C_RECT, range(10, TOTAL_FRAMES)),
        ),
    )
    args = _compose(session_factory, managed_root, ids)["z_order_error"]
    stacking = args["render_stacking"][0]
    assert stacking["occluder_segment_id"] == ids.segment_a
    assert stacking["measured_on_top"] == ids.segment_c
    assert stacking["agrees_with_annotation"] is False
    # the real detector now counts the edge as a violation (1 < the frozen
    # warning boundary of 4, so it is a measured change, not an item)
    assert z_order_error.measure_z_order_violations(args) == 1
    # the control render (the shipped one) measures the occluder on top
    _rewrite_render(
        session_factory,
        managed_root,
        ids,
        square_rect=DELTA_RECT,
        lit_frames=range(0, 10),
        extra_layers=(
            (MASK_B_RECT, range(10, TOTAL_FRAMES)),
            (MASK_C_RECT, range(10, TOTAL_FRAMES)),
        ),
    )
    flipped = _compose(session_factory, managed_root, ids)["z_order_error"]
    measured = flipped["render_stacking"][0]
    assert measured["measured_on_top"] == measured["occluder_segment_id"]
    assert measured["agrees_with_annotation"] is True
    assert flipped["render_order"] != args["render_order"]
    assert z_order_error.measure_z_order_violations(flipped) == 0


def test_shrinking_a_rendered_layer_shrinks_the_observed_bbox(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    shrunk = (310, 170, 330, 190)
    _rewrite_render(
        session_factory,
        managed_root,
        ids,
        square_rect=DELTA_RECT,
        lit_frames=range(0, 10),
        extra_layers=(
            (shrunk, range(10, TOTAL_FRAMES)),
            (MASK_C_RECT, range(10, TOTAL_FRAMES)),
        ),
    )
    args = _compose(session_factory, managed_root, ids)["silhouette_clipping"]
    by_id = {row["id"]: row for row in args["segments"]}
    observed = by_id[ids.segment_b]["bbox"]
    assert observed == list(shrunk)
    assert by_id[ids.segment_b]["expected_bbox"] == list(MASK_B_RECT)
    assert silhouette_clipping.detect_silhouette_clipping(args) == []


def test_removing_a_rendered_layer_refuses_silhouette(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    _rewrite_render(
        session_factory,
        managed_root,
        ids,
        square_rect=DELTA_RECT,
        lit_frames=range(0, 10),
        extra_layers=((MASK_C_RECT, range(10, TOTAL_FRAMES)),),
    )
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    assert _codes(raised.value)["silhouette_clipping"] == QC_EVIDENCE_DEPENDENCY
    assert _no_qc_rows(session_factory) == 0


def test_contact_observation_is_measured_on_the_render(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    shrunk = (105, 165, 111, 171)
    _rewrite_render(
        session_factory,
        managed_root,
        ids,
        square_rect=shrunk,
        lit_frames=range(0, 10),
        extra_layers=(
            (MASK_B_RECT, range(10, TOTAL_FRAMES)),
            (MASK_C_RECT, range(10, TOTAL_FRAMES)),
        ),
    )
    args = _compose(session_factory, managed_root, ids)["contact_break"]
    by_id = {row["id"]: row for row in args["segments"]}
    segment_a = by_id[ids.segment_a]
    assert segment_a["expected_bbox_per_frame"][0] == list(
        (100, 160, 116, 176)
    )
    observed = [row for row in segment_a["bbox_per_frame"] if row is not None]
    assert observed
    assert observed[0] == list(shrunk)
    assert contact_break.detect_contact_break(args) == []


def test_trajectory_observation_is_measured_on_the_render(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    moved = (200, 160, 241, 200)
    # frames 0..4 paint the layer 100 px to the right of the persisted anchor;
    # frames 5..9 keep the shipped placement so the occlusion/contact windows
    # stay observable and only the trajectory observation moves.
    _rewrite_render(
        session_factory,
        managed_root,
        ids,
        square_rect=DELTA_RECT,
        lit_frames=range(5, 10),
        extra_layers=(
            (moved, range(0, 5)),
            (MASK_B_RECT, range(10, TOTAL_FRAMES)),
            (MASK_C_RECT, range(10, TOTAL_FRAMES)),
        ),
    )
    args = _compose(session_factory, managed_root, ids)["trajectory_drift"]
    assert args["observed_x"][:5] == [220.0] * 5
    assert args["observed_x"][5:] == [120.0] * 5
    assert args["reference_x"][0] == 120.0
    out = trajectory_drift.detect(args)
    values = [m["value"] for m in out["measurements"]]
    # the metric is the MEAN absolute deviation over the window
    assert values == [50.0]
    statuses = [m["status"] for m in out["measurements"]]
    assert "warning" in statuses


# ── disposition matrix: every detector has a positive and a refusal row ───


def _mutate_render_file_missing(session_factory, managed_root, ids):  # noqa: ANN001
    with session_factory() as session:
        artifact = session.get(Artifact, ids.render_artifact_id)
        (Path(managed_root) / str(artifact.relative_path)).unlink()


def _mutate_render_row_stale(session_factory, managed_root, ids):  # noqa: ANN001
    with session_factory() as session:
        session.execute(
            update(Artifact)
            .where(Artifact.id == ids.render_artifact_id)
            .values(state="staging")
        )
        session.commit()


def _mutate_render_producer_missing(session_factory, managed_root, ids):  # noqa: ANN001
    with session_factory() as session:
        session.execute(
            delete(ArtifactOwner).where(ArtifactOwner.artifact_id == ids.render_artifact_id)
        )
        session.execute(delete(Artifact).where(Artifact.id == ids.render_artifact_id))
        session.commit()


def _mutate_render_bytes_tampered(session_factory, managed_root, ids):  # noqa: ANN001
    with session_factory() as session:
        artifact = session.get(Artifact, ids.render_artifact_id)
        target = Path(managed_root) / str(artifact.relative_path)
        original = target.read_bytes()
        data = bytearray(original)
        data[-1] = data[-1] ^ 0xFF
        target.write_bytes(bytes(data))


def _mutate_mask_row_malformed(session_factory, managed_root, ids):  # noqa: ANN001
    with session_factory() as session:
        session.execute(update(Artifact).where(Artifact.id == ids.mask_a).values(sha256=None))
        session.commit()


def _mutate_segments_missing(session_factory, managed_root, ids):  # noqa: ANN001
    from app.persistence.models import (
        OccurrenceSegment,
        S09Correction,
        SceneGraphContact,
        SceneGraphOcclusion,
        SegmentMotion,
        SegmentRenderRoute,
    )

    with session_factory() as session:
        for model in (
            QCItem,
            S09Correction,
            SegmentRenderRoute,
            SceneGraphContact,
            SceneGraphOcclusion,
            SegmentMotion,
        ):
            session.execute(delete(model))
        session.execute(delete(OccurrenceSegment))
        session.commit()


def _mutate_contacts_missing(session_factory, managed_root, ids):  # noqa: ANN001
    from app.persistence.models import SceneGraphContact

    with session_factory() as session:
        session.execute(delete(SceneGraphContact))
        session.commit()


def _mutate_occlusions_missing(session_factory, managed_root, ids):  # noqa: ANN001
    with session_factory() as session:
        session.execute(delete(SceneGraphOcclusion))
        session.commit()


def _mutate_scenes_missing(session_factory, managed_root, ids):  # noqa: ANN001
    from app.persistence.models import Scene

    _mutate_segments_missing(session_factory, managed_root, ids)
    with session_factory() as session:
        session.execute(delete(Scene))
        session.commit()


def _mutate_cast_pin_missing(session_factory, managed_root, ids):  # noqa: ANN001
    with session_factory() as session:
        session.execute(delete(ProjectCastMapping))
        session.commit()


def _mutate_rendered_mask_owners_missing(session_factory, managed_root, ids):  # noqa: ANN001
    with session_factory() as session:
        session.execute(
            delete(ArtifactOwner).where(
                ArtifactOwner.artifact_id.in_(
                    [ids.mask_rendered, ids.mask_b, ids.mask_c]
                )
            )
        )
        session.commit()


DISPOSITIONS: tuple[tuple[str, str, str, object], ...] = (
    ("render_file_missing", "cut_drift", QC_EVIDENCE_MISSING, _mutate_render_file_missing),
    ("render_file_missing", "contact_break", QC_EVIDENCE_MISSING, _mutate_render_file_missing),
    ("render_file_missing", "z_order_error", QC_EVIDENCE_MISSING, _mutate_render_file_missing),
    (
        "render_file_missing",
        "silhouette_clipping",
        QC_EVIDENCE_MISSING,
        _mutate_render_file_missing,
    ),
    ("render_file_missing", "identity_drift", QC_EVIDENCE_MISSING, _mutate_render_file_missing),
    ("render_file_missing", "trajectory_drift", QC_EVIDENCE_MISSING, _mutate_render_file_missing),
    ("render_row_stale", "cut_drift", QC_EVIDENCE_STALE, _mutate_render_row_stale),
    ("render_row_stale", "temporal_flicker", QC_EVIDENCE_STALE, _mutate_render_row_stale),
    (
        "render_producer_missing",
        "cut_drift",
        QC_EVIDENCE_DEPENDENCY,
        _mutate_render_producer_missing,
    ),
    (
        "render_producer_missing",
        "silhouette_clipping",
        QC_EVIDENCE_DEPENDENCY,
        _mutate_render_producer_missing,
    ),
    ("render_bytes_tampered", "z_order_error", QC_EVIDENCE_TAMPERED, _mutate_render_bytes_tampered),
    (
        "mask_row_malformed",
        "silhouette_clipping",
        QC_EVIDENCE_MALFORMED,
        _mutate_mask_row_malformed,
    ),
    ("segments_missing", "contact_break", QC_EVIDENCE_MISSING, _mutate_segments_missing),
    ("segments_missing", "identity_drift", QC_EVIDENCE_MISSING, _mutate_segments_missing),
    ("contacts_missing", "contact_break", QC_EVIDENCE_MISSING, _mutate_contacts_missing),
    ("occlusions_missing", "z_order_error", QC_EVIDENCE_MISSING, _mutate_occlusions_missing),
    ("scenes_missing", "cut_drift", QC_EVIDENCE_MISSING, _mutate_scenes_missing),
    ("cast_pin_missing", "identity_drift", QC_EVIDENCE_MISSING, _mutate_cast_pin_missing),
    (
        "rendered_mask_owners_missing",
        "edge_halo",
        QC_EVIDENCE_DEPENDENCY,
        _mutate_rendered_mask_owners_missing,
    ),
)


@pytest.mark.parametrize(
    "case,detector,expected_code,mutate",
    DISPOSITIONS,
    ids=[f"{row[0]}::{row[1]}" for row in DISPOSITIONS],
)
def test_refusal_matrix_row(  # noqa: ANN001
    evidence_db, case: str, detector: str, expected_code: str, mutate
) -> None:
    session_factory, managed_root, ids = evidence_db
    mutate(session_factory, managed_root, ids)
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    codes = _codes(raised.value)
    assert codes.get(detector) == expected_code, (case, detector, codes)


def test_every_visual_detector_is_composable_in_the_default_world(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    composed = _compose(session_factory, managed_root, ids)
    assert sorted(composed) == [
        "contact_break",
        "cut_drift",
        "edge_halo",
        "identity_drift",
        "silhouette_clipping",
        "temporal_flicker",
        "trajectory_drift",
        "z_order_error",
    ]
    # every composed detector's OWN real entry point consumes its args
    assert trajectory_drift.detect(composed["trajectory_drift"])["measurements"][0]["status"]
    assert cut_drift.detect(composed["cut_drift"])["measurements"]
    assert contact_break.detect_contact_break(composed["contact_break"]) == []
    assert z_order_error.detect_z_order_error(composed["z_order_error"]) == []
    assert silhouette_clipping.detect_silhouette_clipping(composed["silhouette_clipping"]) == []
    assert identity_drift.detect(composed["identity_drift"])["measured_distance"] > 0.0
    assert _no_qc_rows(session_factory) == 0
