"""MF-P1-QC-EVIDENCE — per-detector composition + the refusal taxonomy.

Positive side: the composed arguments feed the REAL detector entry points and
the measurements come out of the persisted bytes (reference == observed for
the pinned route anchor; a zero cut drift; a constant-luminance window), while
detectors whose persisted render genuinely differs report their measurement
instead of a papered pass.

Refusal side: missing / stale / foreign / malformed / tampered evidence and a
fact with no producer each refuse with their TYPED code — never a silent pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import delete, update

from app.persistence.models import Artifact, ArtifactOwner, Scene
from app.services.qc_checks import (
    contact_break,
    cut_drift,
    edge_halo,
    identity_drift,
    silhouette_clipping,
    temporal_flicker,
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

ANCHOR_X = 120.0 / 640.0


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


# ── positive: the real detectors consume the persisted evidence ─────────────


def test_compose_supplies_all_eight_visual_detectors(evidence_db) -> None:  # noqa: ANN001
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
    # the audio pair keeps the handler-owned envelope path (not composed here)
    assert "audio_missing" not in composed and "av_sync_drift" not in composed


def test_every_composed_argument_set_carries_verified_provenance(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    composed = _compose(session_factory, managed_root, ids)
    for detector, args in composed.items():
        provenance = args["evidence_provenance"]
        assert provenance["detector"] == detector
        assert provenance["composer"] == "mf-p1-qc-evidence"
        assert provenance["input_digest"]
        assert provenance["composed_digest"]
        assert provenance["families"]
        assert provenance["derivations"]
        assert args["checkpoint_ref"] == "s11-qc-evidence"
        # every artifact cited in the provenance was byte-reverified on read
        for family in provenance["families"].values():
            for value in _iter_artifact_evidence(family):
                assert value["bytes_reverified"] is True
                assert len(value["sha256"]) == 64


def _iter_artifact_evidence(node):  # noqa: ANN001, ANN202
    if isinstance(node, dict):
        if "artifact_id" in node and "bytes_reverified" in node:
            yield node
            return
        for value in node.values():
            yield from _iter_artifact_evidence(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_artifact_evidence(value)


def test_trajectory_drift_reference_equals_measured_placement(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    args = _compose(session_factory, managed_root, ids)["trajectory_drift"]
    assert args["evidence_provenance"]["families"]["annotation"]["anchor_x"] == ANCHOR_X
    assert args["reference_x"] == [120.0] * len(args["reference_x"])
    assert args["observed_x"] == args["reference_x"]
    assert args["evidence_provenance"]["families"]["artifact"]["render"]["artifact_id"] == (
        ids.render_artifact_id
    )
    out = trajectory_drift.detect(args)
    assert out["measurements"][0]["status"] == "pass"
    assert out["measurements"][0]["value"] == 0.0


def test_cut_drift_uses_the_persisted_render_timecodes(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    args = _compose(session_factory, managed_root, ids)["cut_drift"]
    assert [row["start_frame"] for row in args["scene_boundaries"]] == [0, 10]
    assert args["render_cuts_ms"] == [0, 333]
    out = cut_drift.detect(args)
    assert [m["status"] for m in out["measurements"]] == ["pass", "pass"]
    assert all(m["value"] == 0.0 for m in out["measurements"])


def test_geometry_detectors_read_the_persisted_masks(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    composed = _compose(session_factory, managed_root, ids)

    silhouette = composed["silhouette_clipping"]
    assert silhouette["frame"] == {"width": 640, "height": 360}
    assert {row["mask_artifact_id"] for row in silhouette["segments"]} >= {ids.mask_a}
    assert silhouette_clipping.detect_silhouette_clipping(silhouette) == []

    z_order = composed["z_order_error"]
    assert z_order_error.detect_z_order_error(z_order) == []

    contact = composed["contact_break"]
    assert contact["analysis_window"]["start_frame"] == 5
    assert contact_break.detect_contact_break(contact) == []

    halo = composed["edge_halo"]
    assert halo["expected"]["artifact_id"] == ids.mask_a
    assert halo["rendered"]["artifact_id"] != ids.mask_a
    halo_out = edge_halo.detect(halo)
    assert halo_out["halo_width_px"] > 0.0
    assert len(halo_out["items"]) == 1

    flicker = composed["temporal_flicker"]
    flicker_out = temporal_flicker.detect(flicker)
    assert flicker_out["mean_interframe_luminance_delta"] == 0.0
    assert flicker_out["items"] == []


def test_identity_reference_is_the_pinned_library_target_and_frames_the_render(evidence_db) -> None:  # noqa: ANN001, E501
    """Correction round C / R4: target identity from the LIBRARY, observation
    from the RENDER — the source video is the motion authority, never the
    identity reference."""
    session_factory, managed_root, ids = evidence_db
    composed = _compose(session_factory, managed_root, ids)
    args = composed["identity_drift"]
    reference_id = ids.reference_artifact_ids["Character"]
    assert args["pinned_reference"]["artifact_id"] == reference_id
    assert args["pinned_reference"]["artifact_id"] != ids.source_artifact_id
    assert args["pinned_reference"]["artifact_sha256"]
    assert args["pinned_reference"]["identity"]["character_id"] == (
        ids.character_ids["Character"]
    )
    assert args["pinned_reference"]["identity"]["pack_version_id"] == (
        ids.pack_version_ids["Character"]
    )
    assert args["cast_pin"]["coverage_scope"] == "single_role"
    assert args["cast_pin"]["roles_total"] == 3
    assert {row["object_role_id"] for row in args["cast_pin"]["cast_coverage"]} == set(
        ids.role_ids.values()
    )
    assert {frame["artifact_id"] for frame in args["frames"]} == {ids.render_artifact_id}
    out = identity_drift.detect(args)
    # a REAL measured difference between the source and the rendered artifact
    # (synthetic fixture render) — reported, not papered green.
    assert out["measured_distance"] > 0.0
    assert len(out["items"]) >= 1


def test_composition_is_deterministic(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    first = _compose(session_factory, managed_root, ids)
    second = _compose(session_factory, managed_root, ids)
    assert {
        name: args["evidence_provenance"]["input_digest"] for name, args in first.items()
    } == {
        name: args["evidence_provenance"]["input_digest"] for name, args in second.items()
    }


# ── refusals ────────────────────────────────────────────────────────────────


def test_foreign_scope_is_refused(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids, project_id="p-someone-else")
    assert raised.value.code == QC_EVIDENCE_FOREIGN
    assert raised.value.details["evidence_code"] == QC_EVIDENCE_FOREIGN


def _delete_all_segments(session) -> None:  # noqa: ANN001
    """Remove every occurrence segment in FK (RESTRICT) dependency order.

    `occurrence_segment` is referenced with ON DELETE RESTRICT by the motion,
    scene-graph occlusion/contact, render-route, S09-correction and QCItem
    rows, so a bare `DELETE FROM occurrence_segment` is refused by the
    database.  Deleting the dependents first is what the test actually means
    by "the structural evidence producer published nothing".
    """
    from app.persistence.models import (
        OccurrenceSegment,
        QCItem,
        S09Correction,
        SceneGraphContact,
        SceneGraphOcclusion,
        SegmentMotion,
        SegmentRenderRoute,
    )

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


def test_missing_segments_refuse_for_every_segment_detector(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        _delete_all_segments(session)
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    codes = _codes(raised.value)
    for detector in (
        "contact_break",
        "z_order_error",
        "silhouette_clipping",
        "identity_drift",
        "edge_halo",
    ):
        assert codes[detector] == QC_EVIDENCE_MISSING, detector


def test_missing_scene_rows_refuse_cut_drift(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        # occurrence_segment.scene_id is ON DELETE RESTRICT, so the segments
        # (and their dependents) go first; cut_drift resolves the scene rows
        # before the segments, so the refusal it reports is still the missing
        # scene ground truth.
        _delete_all_segments(session)
        session.execute(delete(Scene))
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    assert _codes(raised.value)["cut_drift"] == QC_EVIDENCE_MISSING


def test_stale_render_artifact_refuses_the_render_backed_detectors(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        session.execute(
            update(Artifact).where(Artifact.id == ids.render_artifact_id).values(state="staging")
        )
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    codes = _codes(raised.value)
    for detector in ("identity_drift", "temporal_flicker"):
        assert codes[detector] == QC_EVIDENCE_STALE, detector


def test_malformed_artifact_row_refuses(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        session.execute(
            update(Artifact).where(Artifact.id == ids.mask_a).values(sha256=None)
        )
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    codes = _codes(raised.value)
    assert codes["silhouette_clipping"] == QC_EVIDENCE_MALFORMED
    assert codes["edge_halo"] == QC_EVIDENCE_MALFORMED


def test_tampered_mask_bytes_refuse(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        artifact = session.get(Artifact, ids.mask_a)
        target = Path(managed_root) / artifact.relative_path
    original = target.read_bytes()
    try:
        target.write_bytes(bytes([1]) * (len(original) + 7))
        with pytest.raises(QcEvidenceError) as raised:
            _compose(session_factory, managed_root, ids)
        codes = _codes(raised.value)
        assert codes["silhouette_clipping"] == QC_EVIDENCE_TAMPERED
    finally:
        target.write_bytes(original)


def test_same_size_tamper_is_still_refused(evidence_db) -> None:  # noqa: ANN001
    """Byte-level integrity: same size, different bytes ⇒ TAMPERED."""
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        artifact = session.get(Artifact, ids.mask_a)
        target = Path(managed_root) / artifact.relative_path
    original = target.read_bytes()
    tampered = bytearray(original)
    tampered[-1] = tampered[-1] ^ 0xFF
    try:
        target.write_bytes(bytes(tampered))
        with pytest.raises(QcEvidenceError) as raised:
            _compose(session_factory, managed_root, ids)
        assert _codes(raised.value)["edge_halo"] == QC_EVIDENCE_TAMPERED
    finally:
        target.write_bytes(original)


def test_missing_route_producer_is_an_exact_dependency_report(evidence_db) -> None:  # noqa: ANN001
    from app.persistence.models import SegmentRenderRoute

    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        session.execute(delete(SegmentRenderRoute))
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    error = raised.value
    assert _codes(error)["trajectory_drift"] == QC_EVIDENCE_DEPENDENCY
    report = error.details["failed_detectors"]["trajectory_drift"]["details"]["dependency"]
    assert "anchor_x" in report["expected_persistence"]
    assert report["missing_producer"]


def test_missing_rendered_side_mask_is_a_dependency_not_a_self_comparison(evidence_db) -> None:  # noqa: ANN001, E501
    """Correction round C: the render side of edge_halo is the RENDERED-side
    published mask.  With every rendered-side mask candidate gone the check
    refuses with an exact dependency report — it never falls back to comparing
    the expected annotation with itself."""
    session_factory, managed_root, ids = evidence_db
    with session_factory() as session:
        session.execute(
            delete(ArtifactOwner).where(
                ArtifactOwner.artifact_id.in_(
                    [ids.mask_rendered, ids.mask_b, ids.mask_c]
                )
            )
        )
        session.execute(delete(Artifact).where(Artifact.id == ids.mask_rendered))
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    assert _codes(raised.value)["edge_halo"] == QC_EVIDENCE_DEPENDENCY
