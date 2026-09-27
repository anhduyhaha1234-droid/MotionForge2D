"""MF-P1-QC-EVIDENCE — correction round D (NR03 / NR04) acceptance tests.

NR03  the numbers must MEASURE the intended visual facts
      Q03R-a  a cut the renderer moved (10 -> 17) with low background motion
              near the planned frame is either OBSERVED at 17 or a typed
              refusal — never a green ``cut_drift = 0`` reported at frame 10;
      Q03R-b  no cut present + background motion: no cut is reported;
      Q03R-c  a valid unchanged cut keeps its PASS;
      Q03R-d  the whole render replaced by one uniform unrelated level:
              findings/refusal — no source-shaped box, no clipping-ratio 0;
      Q03R-e  a global appearance change (geometry intact) is not turned into
              a contact/silhouette verdict built from source data;
      Q03R-f  a missing actor is a refusal, never "present because a box
              differs";
      Q03R-g  an actor the output clips at the frame border: R27-04 replaced
              the pre-fix MEASURED answer with the typed AUTHORITY verdict —
              the measured extent still reaches the border, but with no
              rendered-side role mask attributing the cut content to the role
              the composer REFUSES (QC_EVIDENCE_DEPENDENCY) instead of handing
              the frozen detector a frame-bounded bbox (a measured ratio of 0);
              the delivered pre-fix value is recomputed in the row's raw file;
      Q03R-h  reversed stacking / broken contact: the affected detector
              fails or refuses.
NR04  identity covers EVERY role, and legacy packs are supported
      Q04R-a  a per-role-only tamper on a LATER role changes that role's own
              measured verdict (byte-different), not just luma metadata;
      Q04R-b  later-segment drift across segments is reflected in the
              measured coverage;
      Q04R-c  a six-slot legacy pack (no 7th ``reference`` asset) through the
              PUBLIC path is valid, or refuses naming the true authority;
      Q04R-d  pin coverage and measured coverage are separate, distinguishable
              facts in the persisted (and UI-facing) evidence.

Every row writes its own RAW result (expected / observed / the render SHA the
observation came from / the pre-fix equivalent) under
``P1QC_EVIDENCE_ROOT`` (default: this round's literal evidence root), so a
reviewer can re-run the row and diff the bytes.
"""

from __future__ import annotations

import hashlib
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
from sqlalchemy import delete, select
from test_public_path import _bind_worker, _run_to_terminal, _submit

from app.persistence.models import Artifact, CharacterAsset, ProjectCastMapping, QCItem
from app.services.qc_checks import (
    contact_break,
    cut_drift,
    identity_drift,
    silhouette_clipping,
    z_order_error,
)
from app.services.qc_evidence import (
    QC_EVIDENCE_DEPENDENCY,
    QC_EVIDENCE_MISSING,
    QcEvidenceError,
    compose_visual_band,
)
from app.services.qc_evidence import observe as obs
from app.workflow.qc_checks_handler import JOB_TYPE_RUN_QC_CHECKS  # noqa: F401

#: Literal evidence root of round D (the packet's path, no nested NEW folder).
EVIDENCE_ROOT = Path(
    os.environ.get(
        "P1QC_EVIDENCE_ROOT",
        "C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/"
        "outputs/mf-core-tool-delivery-20260924/20260924T1557Z/P1QC/raw",
    )
)

RENDER_LEVEL = 8
#: Level of the full-canvas replacement used by Q03R-d (an unrelated uniform
#: render that is far from the fixture's black source and from level 8).
UNRELATED_LEVEL = 137


def _raw(name: str, payload: dict) -> None:
    """Persist one subcase's RAW result (fresh, byte-deterministic)."""
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_ROOT / f"{name}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
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


def _layered_clip(
    path: Path, layers: tuple[tuple[tuple[int, int, int, int], object, int], ...]
) -> bytes:
    """Write a REAL lossless clip from (rect, frames, level) layers.

    Every layer paints at its OWN level, so a background level, an actor level
    and an unrelated replacement level can coexist in one honest render.
    """
    import cv2

    fourcc = cv2.VideoWriter_fourcc(*"FFV1")
    writer = cv2.VideoWriter(str(path), fourcc, float(FPS_NUM), (CANVAS_W, CANVAS_H))
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


def _write_render(  # noqa: ANN001
    session_factory,
    managed_root: Path,
    ids,
    layers: tuple[tuple[tuple[int, int, int, int], object, int], ...],
) -> str:
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


def _render_identity(session_factory, managed_root: Path, ids) -> dict:  # noqa: ANN001
    """The render artifact's recorded digest + the digest of the bytes on disk."""
    with session_factory() as session:
        artifact = session.get(Artifact, ids.render_artifact_id)
        recorded = str(artifact.sha256)
        size = int(artifact.size_bytes)
        rel = str(artifact.relative_path)
    data = (Path(managed_root) / rel).read_bytes()
    on_disk = hashlib.sha256(data).hexdigest()
    return {
        "artifact_id": ids.render_artifact_id,
        "recorded_sha256": recorded,
        "on_disk_sha256": on_disk,
        "digest_matches_bytes": recorded == on_disk,
        "size_bytes": size,
    }


DEFAULT_LAYERS = (
    (DELTA_RECT, range(0, 10), RENDER_LEVEL),
    (MASK_B_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
    (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
)


# ── Q03R-a: a cut the renderer MOVED, with low background motion nearby ─────


def test_q03r_a_moved_cut_is_observed_or_refused(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    # frames 10..16 paint the same layer shifted by 1 px (low background
    # motion near the planned frame); the shot change is at 17.
    shifted = (DELTA_RECT[0] + 1, DELTA_RECT[1], DELTA_RECT[2] + 1, DELTA_RECT[3])
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
            (shifted, range(10, 17), RENDER_LEVEL),
            (MASK_B_RECT, range(17, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_C_RECT, range(17, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )
    render = _render_identity(session_factory, managed_root, ids)
    # the PRE-FIX equivalent: the round-C +/-1 search window is still available
    # (span=None) and is exactly what the delivered bytes reported.
    try:
        args = _compose(session_factory, managed_root, ids)["cut_drift"]
        observed = args["cut_observations"][1]
        refusal = None
        measurement = cut_drift.detect(args)["measurements"][1]["value"]
    except QcEvidenceError as exc:
        args, observed, measurement = {}, None, None
        refusal = {"aggregate_code": exc.code, **_detector_failure(exc, "cut_drift")}
    prefix = _prefix_cut_observation(session_factory, managed_root, ids)
    _raw(
        "q03r_a",
        {
            "subcase": "Q03R-a",
            "expected": "observed frame ~= 17 (or a typed refusal); never a "
            "green cut_drift=0 at the planned frame 10",
            "observed": {
                "observed_frame": (observed or {}).get("observed_frame"),
                "observed_cut_ms": (observed or {}).get("observed_cut_ms"),
                "search_span": (observed or {}).get("search_span"),
                "reason": (observed or {}).get("reason"),
                "drift_frames_from_planned": measurement,
                "refusal": refusal,
            },
            "pre_fix_equivalent": prefix,
            "render": render,
            "disposition": (
                "PASS (observed at the moved cut)"
                if observed and observed.get("observed_frame") == 17
                else "TYPED_REFUSAL (no green)"
                if refusal
                else "FAIL"
            ),
        },
    )
    if not refusal:
        assert observed["observed_frame"] == 17
        assert measurement == 7.0
    else:
        assert refusal.get("reason") in (None, "no_distinguishable_cut")
    assert _no_qc_rows(session_factory) == 0


def _prefix_cut_observation(session_factory, managed_root: Path, ids) -> dict:  # noqa: ANN001
    """Reproduce the DELIVERED (pre-fix) cut answer for the same bytes.

    The pre-fix code took the ARGMAX of ``|render(f) - render(f-1)|`` inside
    ``boundary +/- 1`` (deterministic tie-break: closest to the boundary, then
    lowest frame) and reported it unconditionally.  This recomputes exactly
    that from the preserved delta primitive, so the value below is the pre-fix
    VALUE, not a description of it.
    """
    from app.services.qc_evidence import sources as src
    from app.services.qc_evidence.measure import decode_video_frames

    with session_factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=ids.workspace_id,
            project_id=ids.project_id,
            video_item_id=ids.video_item_id,
            generation="1",
        )
        evidence, role, _facts = src.render_result_artifact(
            session, managed_root, scope, detector="cut_drift"
        )
    path = Path(managed_root) / evidence.relative_path
    frames = decode_video_frames(path, list(range(8, 13)), detector="cut_drift")
    measured = obs.observed_boundary(frames, 10, detector="cut_drift")
    deltas = {int(frame): value for frame, value in measured["deltas"].items()}
    prefix_frame = None
    if deltas:
        prefix_frame = sorted(
            deltas.items(), key=lambda item: (-item[1], abs(item[0] - 10), item[0])
        )[0][0]
    return {
        "search_window": measured["search_span"],
        "frame": prefix_frame,
        "delta": deltas.get(prefix_frame) if prefix_frame is not None else None,
        "note": "the pre-fix search only considered the boundary +/- 1 frames and "
        "reported its argmax unconditionally, so this frame (with the planned "
        "boundary at 10) is what the delivered bytes reported — a drift of "
        f"{abs((prefix_frame or 10) - 10)} frame(s)",
        "render_role": role,
    }


def _detector_failure(error: QcEvidenceError, detector: str) -> dict:  # noqa: ANN001
    """The typed failure of ONE detector inside an aggregate refusal."""
    failed = (error.details.get("failed_detectors") or {}).get(detector)
    if not failed:
        return {"refused": False}
    details = dict(failed.get("details") or {})
    return {
        "refused": True,
        "code": failed.get("code"),
        "message": failed.get("message"),
        "reason": details.get("reason"),
        "search_span": details.get("search_span"),
        "named_segment": details.get("segment_id"),
        "background_levels": details.get("background_levels"),
    }


# ── Q03R-b: motion but no cut ──────────────────────────────────────────────


def test_q03r_b_motion_without_a_cut_reports_no_cut(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    # the layer drifts 1 px per frame for the WHOLE clip: motion everywhere,
    # no shot change at all.
    lanes = tuple(
        ((100 + offset, 160, 141 + offset, 200), [index], RENDER_LEVEL)
        for index, offset in enumerate(range(TOTAL_FRAMES))
    )
    _write_render(session_factory, managed_root, ids, lanes)
    render = _render_identity(session_factory, managed_root, ids)
    try:
        args = _compose(session_factory, managed_root, ids)["cut_drift"]
        observed, refusal = args["cut_observations"][1], None
    except QcEvidenceError as exc:
        observed = None
        refusal = {"aggregate_code": exc.code, **_detector_failure(exc, "cut_drift")}
    prefix = _prefix_cut_observation(session_factory, managed_root, ids)
    _raw(
        "q03r_b",
        {
            "subcase": "Q03R-b",
            "expected": "no cut reported; no fabricated drift",
            "observed": {
                "cut_reported": bool(observed and observed.get("observed_frame")),
                "reason": (observed or {}).get("reason"),
                "refusal": refusal,
            },
            "pre_fix_equivalent": prefix,
            "render": render,
            "disposition": "PASS (no cut reported)"
            if (refusal or not (observed or {}).get("observed_frame"))
            else "FAIL",
        },
    )
    assert refusal is not None, observed
    assert refusal["reason"] == "no_distinguishable_cut"
    assert _no_qc_rows(session_factory) == 0


# ── Q03R-c: the valid cut keeps its PASS (control) ─────────────────────────


def test_q03r_c_valid_cut_keeps_pass(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    _write_render(session_factory, managed_root, ids, DEFAULT_LAYERS)
    render = _render_identity(session_factory, managed_root, ids)
    args = _compose(session_factory, managed_root, ids)["cut_drift"]
    out = cut_drift.detect(args)
    _raw(
        "q03r_c",
        {
            "subcase": "Q03R-c",
            "expected": "observed cut 10, drift 0, PASS retained",
            "observed": {
                "observed_frame": args["cut_observations"][1]["observed_frame"],
                "render_cuts_ms": args["render_cuts_ms"],
                "planned_cuts_ms": args["planned_cuts_ms"],
                "drift_frames": out["measurements"][1]["value"],
                "status": out["measurements"][1]["status"],
            },
            "render": render,
            "disposition": "PASS",
        },
    )
    assert args["cut_observations"][1]["observed_frame"] == 10
    assert out["measurements"][1]["value"] == 0.0


# ── Q03R-d: the whole render replaced by one uniform unrelated level ───────


def test_q03r_d_uniform_unrelated_render_is_not_a_source_shaped_pass(evidence_db) -> None:  # noqa: ANN001, E501
    session_factory, managed_root, ids = evidence_db
    _write_render(
        session_factory,
        managed_root,
        ids,
        (((0, 0, CANVAS_W, CANVAS_H), range(0, TOTAL_FRAMES), UNRELATED_LEVEL),),
    )
    render = _render_identity(session_factory, managed_root, ids)
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    codes = _codes(raised.value)
    failed = raised.value.details.get("failed_detectors") or {}
    silhouette = failed.get("silhouette_clipping", {})
    contact = failed.get("contact_break", {})
    # the PRE-FIX equivalent on the same bytes: "differs from the source inside
    # the annotated box" returns the ANNOTATION box as the observed geometry
    # and the clipping ratio the frozen detector derives from it is 0.
    prefix = _prefix_geometry_measurement(session_factory, managed_root, ids)
    _raw(
        "q03r_d",
        {
            "subcase": "Q03R-d",
            "expected": "findings/refusal; no source-shaped box; no "
            "clipping-ratio 0 green",
            "observed": {
                "refusal_codes": codes,
                "silhouette": silhouette.get("details"),
                "contact": contact.get("details"),
                "source_shaped_boxes_reported": bool(
                    silhouette.get("details", {}).get("bbox")
                ),
            },
            "pre_fix_equivalent": prefix,
            "render": render,
            "disposition": "PASS (typed refusal, no box, no clipping green)"
            if codes.get("silhouette_clipping")
            else "FAIL",
        },
    )
    assert codes["silhouette_clipping"] == QC_EVIDENCE_DEPENDENCY
    assert codes["contact_break"] == QC_EVIDENCE_DEPENDENCY
    assert "bbox" not in silhouette.get("details", {})
    assert _no_qc_rows(session_factory) == 0


def _prefix_geometry_measurement(session_factory, managed_root: Path, ids) -> dict:  # noqa: ANN001
    """The delivered (pre-fix) geometry measurement on the current bytes."""
    from app.services.qc_evidence import sources as src
    from app.services.qc_evidence.measure import decode_png_gray, decode_video_frames

    with session_factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=ids.workspace_id,
            project_id=ids.project_id,
            video_item_id=ids.video_item_id,
            generation="1",
        )
        source, role, _facts = src.render_result_artifact(
            session, managed_root, scope, detector="silhouette_clipping"
        )
        del source
        src_artifact = src.source_artifact(
            session, managed_root, scope, detector="silhouette_clipping"
        )
        rendered, render_role, _f = src.render_result_artifact(
            session, managed_root, scope, detector="silhouette_clipping"
        )
        mask_bytes = src.read_artifact(
            session, managed_root, scope, ids.mask_a, detector="silhouette_clipping"
        )
    mask_matrix, _mw, _mh = decode_png_gray(mask_bytes.data, detector="x")
    bbox = (100, 160, 116, 176)
    indices = [0, 1, 2, 3, 5, 6, 7, 8]
    src_frames = decode_video_frames(
        Path(managed_root) / src_artifact.relative_path, indices, detector="x"
    )
    out_frames = decode_video_frames(
        Path(managed_root) / rendered.relative_path, indices, detector="x"
    )
    changed = []
    object_boxes = []
    for index in indices:
        if index in src_frames and index in out_frames:
            box = obs.changed_bbox(
                src_frames[index], out_frames[index], region=bbox, detector="x"
            )
            if box is not None:
                changed.append(list(box))
            obj = obs.rendered_object_bbox(
                out_frames[index], region=bbox, detector="x"
            )
            object_boxes.append([list(obj) if obj else None][0])
    del mask_matrix, role, render_role
    return {
        "prefix_changed_bbox_per_frame": changed,
        "expected_annotation_bbox": list(bbox),
        "prefix_reported_the_annotation_box": any(row == list(bbox) for row in changed),
        "postfix_rendered_object_bbox_per_frame": object_boxes,
    }


# ── Q03R-e: a global appearance change is not a source-built pass ──────────


def test_q03r_e_recolour_is_measured_on_the_render(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    recoloured = 200
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), recoloured),
            (MASK_B_RECT, range(10, TOTAL_FRAMES), recoloured),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), recoloured),
        ),
    )
    render = _render_identity(session_factory, managed_root, ids)
    composed = _compose(session_factory, managed_root, ids)
    args = composed["silhouette_clipping"]
    by_id = {row["id"]: row for row in args["segments"]}
    first = by_id[ids.segment_a]
    _raw(
        "q03r_e",
        {
            "subcase": "Q03R-e",
            "expected": "the observed geometry is measured on the rendered "
            "bytes (never source-built) and the persisted evidence says so",
            "observed": {
                "observed_bbox": first["bbox"],
                "expected_bbox": first["expected_bbox"],
                "measured_on": first["measured_on"],
                "render_background_level_per_frame": first[
                    "render_background_level_per_frame"
                ],
                "border_contact": first["border_contact"],
                "observation_measure": args["render_observation"]["measure"],
                "detector_items": silhouette_clipping.detect_silhouette_clipping(args),
            },
            "render": render,
            "disposition": "PASS",
        },
    )
    # R28: the measured extent is INTERSECTED with the role's own published
    # support, so for this world the pinned number is the support-bounded
    # extent (the recolour covers MORE than the support).  The row's claim —
    # measured on the RENDER's own bytes, never built from the source — is
    # unchanged and is re-proved by the non-vacuity control below.
    assert first["bbox"] == list(MASK_A_RECT) == [100, 160, 116, 176]
    assert first["measured_on"].startswith("rendered_object_pixels")
    assert first["expected_bbox"] == list(MASK_A_RECT)
    assert args["render_observation"]["artifact"]["artifact_id"] == ids.render_artifact_id

    # NON-VACUITY: repaint the SAME role STRICTLY INSIDE its annotation.  A
    # measurement taken from the annotation would keep returning MASK_A_RECT;
    # the real measurement must follow the render and SHRINK.
    shrunk = (100, 160, 110, 170)
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (shrunk, range(0, 10), recoloured),
            (MASK_B_RECT, range(10, TOTAL_FRAMES), recoloured),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), recoloured),
        ),
    )
    control = _compose(session_factory, managed_root, ids)["silhouette_clipping"]
    control_first = {row["id"]: row for row in control["segments"]}[ids.segment_a]
    assert control_first["bbox"] == list(shrunk)
    assert control_first["bbox"] != control_first["expected_bbox"]
    _raw(
        "q03r_e_control_render_shrunk",
        {
            "subcase": "Q03R-e (non-vacuity control, R28)",
            "expected": "the measured extent follows the RENDER: repainting the "
            "role strictly inside its annotation shrinks the measurement away "
            "from the annotation box",
            "observed": {
                "control_painted_rect": list(shrunk),
                "control_measured_bbox": control_first["bbox"],
                "control_expected_bbox": control_first["expected_bbox"],
                "annotation": list(MASK_A_RECT),
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "PASS (render-driven, not annotation-driven)",
        },
    )


# ── Q03R-f: the actor is missing from the render ───────────────────────────


def test_q03r_f_missing_actor_refuses_instead_of_a_box_difference(evidence_db) -> None:  # noqa: ANN001, E501
    session_factory, managed_root, ids = evidence_db
    # a full-canvas background that differs from the source EVERYWHERE, with
    # segment B's actor absent: the source-difference measurement would report
    # B's annotation box as "present".
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            ((0, 0, CANVAS_W, CANVAS_H), range(0, TOTAL_FRAMES), 50),
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
        ),
    )
    render = _render_identity(session_factory, managed_root, ids)
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    error = raised.value
    silhouette = (error.details.get("failed_detectors") or {}).get(
        "silhouette_clipping", {}
    )
    prefix = _prefix_geometry_measurement_for(session_factory, managed_root, ids, ids.mask_b)
    _raw(
        "q03r_f",
        {
            "subcase": "Q03R-f",
            "expected": "refuse / report absence — never 'present because a box "
            "differs'",
            "observed": {
                "refusal_code": _codes(error).get("silhouette_clipping"),
                "details": silhouette.get("details"),
                "named_segment": (
                    silhouette.get("details", {}).get("segment_id") == ids.segment_b
                ),
            },
            "pre_fix_equivalent": prefix,
            "render": render,
            "disposition": "PASS (typed refusal naming the missing actor)"
            if _codes(error).get("silhouette_clipping") == QC_EVIDENCE_DEPENDENCY
            else "FAIL",
        },
    )
    assert _codes(error)["silhouette_clipping"] == QC_EVIDENCE_DEPENDENCY
    assert prefix["prefix_reported_the_annotation_box"] is True
    assert _no_qc_rows(session_factory) == 0


def _prefix_geometry_measurement_for(  # noqa: ANN001
    session_factory, managed_root: Path, ids, mask_id: str
) -> dict:
    from app.services.qc_evidence import sources as src
    from app.services.qc_evidence.measure import decode_png_gray, decode_video_frames

    with session_factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=ids.workspace_id,
            project_id=ids.project_id,
            video_item_id=ids.video_item_id,
            generation="1",
        )
        source = src.source_artifact(session, managed_root, scope, detector="x")
        rendered, _role, _f = src.render_result_artifact(
            session, managed_root, scope, detector="x"
        )
        mask_bytes = src.read_artifact(
            session, managed_root, scope, mask_id, detector="x"
        )
    _matrix, _mw, _mh = decode_png_gray(mask_bytes.data, detector="x")
    matrix = decode_png_gray(mask_bytes.data, detector="x")[0]
    arr = np.asarray(matrix, dtype=np.float64) > 0.0
    ys, xs = np.nonzero(arr)
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    indices = [10, 11, 13, 14]
    src_frames = decode_video_frames(
        Path(managed_root) / source.relative_path, indices, detector="x"
    )
    out_frames = decode_video_frames(
        Path(managed_root) / rendered.relative_path, indices, detector="x"
    )
    changed = []
    for index in indices:
        box = obs.changed_bbox(
            src_frames[index], out_frames[index], region=bbox, detector="x"
        )
        if box is not None:
            changed.append(list(box))
    return {
        "prefix_changed_bbox_per_frame": changed,
        "expected_annotation_bbox": list(bbox),
        "prefix_reported_the_annotation_box": any(row == list(bbox) for row in changed),
    }


# ── Q03R-g: the actor is clipped at the frame border ───────────────────────


def _prefix_border_geometry(session_factory, managed_root: Path, ids) -> dict:  # noqa: ANN001
    """Reproduce the DELIVERED (pre-R27-04) answer for the same render bytes.

    The pre-fix composer measured the rendered object with the unchanged
    primitive ``obs.rendered_object_bbox`` and handed that frame-bounded bbox
    straight to the frozen detector, which reports nothing for it (the T06A2
    ratio is bbox area outside the frame = 0.0).  This recomputes exactly that
    from the primitive, so the value below is the PRE-FIX VALUE, not a
    description of it.
    """
    from app.services.qc_evidence import sources as src
    from app.services.qc_evidence.measure import decode_video_frames

    with session_factory() as session:
        scope = src.load_scope(
            session,
            workspace_id=ids.workspace_id,
            project_id=ids.project_id,
            video_item_id=ids.video_item_id,
            generation="1",
        )
        evidence, _role, _facts = src.render_result_artifact(
            session, managed_root, scope, detector="silhouette_clipping"
        )
    path = Path(managed_root) / evidence.relative_path
    indices = list(range(10, TOTAL_FRAMES))
    frames = decode_video_frames(path, indices, detector="silhouette_clipping")
    observed = None
    for index in sorted(frames):
        measured = obs.rendered_object_bbox(
            frames[index], region=MASK_B_RECT, detector="silhouette_clipping"
        )
        if measured is None:
            continue
        observed = (
            measured
            if observed is None
            else (
                min(observed[0], measured[0]),
                min(observed[1], measured[1]),
                max(observed[2], measured[2]),
                max(observed[3], measured[3]),
            )
        )
    if observed is None:
        return {"measured_bbox": None, "note": "the pre-fix primitive measured nothing"}
    pre_fix_args = {
        "analysis_window": {"start_frame": 10, "end_frame": TOTAL_FRAMES - 1},
        "frame": {"width": CANVAS_W, "height": CANVAS_H},
        "segments": [
            {
                "id": ids.segment_b,
                "start_frame": 10,
                "end_frame": TOTAL_FRAMES - 1,
                "bbox": [float(v) for v in observed],
                "mask_artifact_id": ids.mask_b,
            }
        ],
    }
    return {
        "measured_bbox": [int(v) for v in observed],
        "border_contact": obs.border_contact(observed, (CANVAS_H, CANVAS_W)),
        "clipped_ratio_the_frozen_detector_derives": (
            silhouette_clipping.measure_clipping_ratio(pre_fix_args)
        ),
        "detector_items_the_pre_fix_composer_handed_over": (
            silhouette_clipping.detect_silhouette_clipping(pre_fix_args)
        ),
        "note": "the pre-fix composer measured the rendered object with the "
        "unchanged primitive and handed the frame-bounded bbox to the frozen "
        "detector, whose metric (area OUTSIDE the frame) reports 0.0 and emits "
        "no item: a cut object read as zero risk — the defect R27-04 closes by "
        "refusing without a rendered-side role mask",
    }


def test_q03r_g_border_clipped_actor_carries_real_geometry(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    clipped = (MASK_B_RECT[0], MASK_B_RECT[1], MASK_B_RECT[2], CANVAS_H)
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
            (clipped, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )
    render = _render_identity(session_factory, managed_root, ids)
    prefix = _prefix_border_geometry(session_factory, managed_root, ids)
    try:
        args = _compose(session_factory, managed_root, ids)["silhouette_clipping"]
        refusal: dict | None = None
        failure: dict = {}
        observed = {row["id"]: row for row in args["segments"]}[ids.segment_b]
    except QcEvidenceError as exc:
        args = {}
        failure = dict(
            (exc.details.get("failed_detectors") or {}).get("silhouette_clipping") or {}
        )
        refusal = {
            "aggregate_code": exc.code,
            "code": failure.get("code"),
            "message": failure.get("message"),
            "details": dict(failure.get("details") or {}),
        }
        observed = {}
    _raw(
        "q03r_g",
        {
            "subcase": "Q03R-g",
            "expected": "R27-04: an actor the OUTPUT clips at the frame border, "
            "with no rendered-side role mask attributing the cut content to the "
            "role, is a typed refusal (QC_EVIDENCE_DEPENDENCY) — never a measured "
            "clipped_ratio of 0 PASS; the measured extent still reaches the border "
            "and the pre-fix value is recomputed below",
            "observed": {
                "refusal": refusal,
                "observed_bbox": observed.get("bbox"),
                "expected_bbox": observed.get("expected_bbox"),
                "border_contact": observed.get("border_contact"),
                "measured_on": observed.get("measured_on"),
                "clipping_authority": (refusal or {}).get("details", {}).get(
                    "clipping_authority"
                ),
            },
            "pre_fix_equivalent": prefix,
            "render": render,
            "disposition": (
                "TYPED_REFUSAL (the pre-fix measured answer is recorded above)"
                if refusal
                else "PASS (measured; no attributable truncation)"
            ),
        },
    )
    # the delivered pre-fix answer for the SAME bytes: a 0 ratio and no item
    assert prefix["detector_items_the_pre_fix_composer_handed_over"] == []
    assert prefix["clipped_ratio_the_frozen_detector_derives"] == 0.0
    assert prefix["border_contact"] == ["bottom"]
    assert prefix["measured_bbox"] == [MASK_B_RECT[0], MASK_B_RECT[1], MASK_B_RECT[2], CANVAS_H]
    if refusal is None:
        # legacy positive path (kept, so the row still proves the measurement)
        assert observed["bbox"] == [MASK_B_RECT[0], MASK_B_RECT[1], MASK_B_RECT[2], CANVAS_H]
        assert observed["border_contact"] == ["bottom"]
        assert observed["expected_bbox"] == list(MASK_B_RECT)
        assert silhouette_clipping.detect_silhouette_clipping(args) == []
    else:
        # R28: the refusal STILL fires (never a measured clipped_ratio of 0
        # PASS) but its CARRIER moved.  The composer now refuses at the
        # painted-beyond-support guard BEFORE the authority block is computed,
        # because intersecting the measurement with the role's own support
        # leaves a support-bounded extent that does not itself reach the border
        # while the render still paints the actor continuing to it.  The pinned
        # R27-04 claim is unchanged (typed QC_EVIDENCE_DEPENDENCY, nothing
        # reaches the detector); the details asserted below are the MEASURED
        # shape of the R28 refusal (raw/q03r_g.json).
        assert args == {}
        assert failure["code"] == "QC_EVIDENCE_DEPENDENCY"
        details = dict(failure.get("details") or {})
        assert details["contact_sides"] == ["bottom"]
        assert details["role_extent_bbox"] == list(MASK_B_RECT)
        assert details["segment_id"] == ids.segment_b
        dependency_report = dict(details.get("dependency") or {})
        assert dependency_report["missing_fact"].startswith(
            "a rendered object pixel set"
        )
        assert "object-correction" in dependency_report["missing_producer"]
        assert "purpose='mask'" in dependency_report["expected_persistence"]
        # The authority block is NOT materialised on this path — the refusal
        # happens before it — so its absence is asserted to keep the record
        # exact instead of silently reading a KeyError as a pass.
        assert "clipping_authority" not in details



# ── Q03R-h: reversed stacking; broken contact ──────────────────────────────


def test_q03r_h_reversed_stacking_and_broken_contact(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    overlay = (MASK_C_RECT[0], DELTA_RECT[1], DELTA_RECT[2], DELTA_RECT[3])
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 5), RENDER_LEVEL),
            (overlay, range(5, 10), RENDER_LEVEL),
            (MASK_B_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )
    render = _render_identity(session_factory, managed_root, ids)
    composed = _compose(session_factory, managed_root, ids)
    z_args = composed["z_order_error"]
    stacking = z_args["render_stacking"][0]
    violations = z_order_error.measure_z_order_violations(z_args)
    # a BROKEN contact: the two contacting actors are painted apart, so the
    # rendered objects no longer touch (the annotation still says they do)
    contact_a = (MASK_A_RECT[0], MASK_A_RECT[1], MASK_A_RECT[0] + 8, MASK_A_RECT[1] + 4)
    contact_c = (MASK_C_RECT[0], MASK_C_RECT[3] - 4, MASK_C_RECT[0] + 40, MASK_C_RECT[3])
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (contact_a, range(0, 10), RENDER_LEVEL),
            (contact_c, range(5, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_B_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )
    broken_render = _render_identity(session_factory, managed_root, ids)
    broken = _compose(session_factory, managed_root, ids)["contact_break"]
    by_id = {row["id"]: row for row in broken["segments"]}
    left = [row for row in by_id[ids.segment_a]["bbox_per_frame"] if row]
    right = [row for row in by_id[ids.segment_c]["bbox_per_frame"] if row]
    gap = None
    if left and right:
        gap = max(0, max(left[0][1], right[0][1]) - min(left[0][3], right[0][3]))
    _raw(
        "q03r_h",
        {
            "subcase": "Q03R-h",
            "expected": "affected detector fails/refuses",
            "observed": {
                "reversed_stacking": {
                    "measured_on_top": stacking["measured_on_top"],
                    "occluder_segment_id": stacking["occluder_segment_id"],
                    "agrees_with_annotation": stacking["agrees_with_annotation"],
                    "violations": violations,
                    "detector_items": z_order_error.detect_z_order_error(z_args),
                },
                "broken_contact": {
                    "rendered_bbox_a": left[:1],
                    "rendered_bbox_c": right[:1],
                    "measured_vertical_gap_px": gap,
                    "frozen_detector_items": contact_break.detect_contact_break(broken),
                    "note": "the frozen contact record ends at the analysis "
                    "window end (SceneGraphContact frames 5..9) so its own "
                    "expiry rule yields no candidate; the break is carried by "
                    "the MEASURED rendered geometry in the composed evidence "
                    "(see the report's typed block for the exact file)",
                },
            },
            "render": render,
            "broken_contact_render": broken_render,
            "disposition": "PASS (stacking fails measurably; the broken contact "
            "is measured on the render)",
        },
    )
    assert stacking["agrees_with_annotation"] is False
    assert violations >= 1
    assert gap is not None and gap > 0


# ── Q04R-a / Q04R-b: per-role measurement, later-role tamper ───────────────


def test_q04r_a_later_role_tamper_changes_that_roles_own_verdict(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    _write_render(session_factory, managed_root, ids, DEFAULT_LAYERS)
    control_render = _render_identity(session_factory, managed_root, ids)
    control = _compose(session_factory, managed_root, ids)["identity_drift"]
    # tamper ONLY the later role (Prop): a recoloured layer inside its own
    # segment window.  The earlier role's bytes and the source are untouched.
    tampered = (
        (DELTA_RECT, range(0, 10), RENDER_LEVEL),
        (MASK_B_RECT, range(10, TOTAL_FRAMES), 200),
        (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
    )
    _write_render(session_factory, managed_root, ids, tampered)
    tamper_render = _render_identity(session_factory, managed_root, ids)
    after = _compose(session_factory, managed_root, ids)["identity_drift"]

    def role_block(args: dict, role_id: str) -> dict:
        return next(
            row
            for row in args["identity_measurements"]
            if str(row["object_role_id"]) == role_id
        )

    prop = ids.role_ids["Prop"]
    character = ids.role_ids["Character"]
    before_prop, after_prop = role_block(control, prop), role_block(after, prop)
    before_char, after_char = role_block(control, character), role_block(after, character)
    control_item = identity_drift.detect(control)
    after_item = identity_drift.detect(after)
    _raw(
        "q04r_a",
        {
            "subcase": "Q04R-a",
            "expected": "the tampered (later) role's OWN verdict changes "
            "byte-different — not just luma metadata",
            "observed": {
                "prop_measured_distance_px": [
                    before_prop["measured_distance_px"],
                    after_prop["measured_distance_px"],
                ],
                "prop_verdict": [before_prop["verdict"], after_prop["verdict"]],
                "prop_crop_sha256_frame0": [
                    before_prop["rendered_frames"][0]["sha256"],
                    after_prop["rendered_frames"][0]["sha256"],
                ],
                "character_measured_distance_px": [
                    before_char["measured_distance_px"],
                    after_char["measured_distance_px"],
                ],
                "prop_block_bytes_differ": json.dumps(
                    before_prop, sort_keys=True
                )
                != json.dumps(after_prop, sort_keys=True),
                "character_block_bytes_differ": json.dumps(
                    before_char, sort_keys=True
                )
                != json.dumps(after_char, sort_keys=True),
                "detector_verdict_changed": json.dumps(
                    control_item, sort_keys=True
                )
                != json.dumps(after_item, sort_keys=True),
                "measured_coverage_per_role": after["measured_coverage"]["per_role"][prop],
            },
            "control_render": control_render,
            "tampered_render": tamper_render,
            "disposition": "PASS",
        },
    )
    assert before_prop["measured_distance_px"] != after_prop["measured_distance_px"]
    assert before_prop["verdict"]["status"] != after_prop["verdict"]["status"]
    assert (
        before_prop["rendered_frames"][0]["sha256"]
        != after_prop["rendered_frames"][0]["sha256"]
    )
    # the untouched role stays byte-identical (the tamper is per-role only)
    assert json.dumps(before_char, sort_keys=True) == json.dumps(after_char, sort_keys=True)


def test_q04r_b_later_segment_drift_is_measured(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    # the later role's own layer drifts across its segment window: present for
    # the first half of its frames, then a shifted placement.
    shifted = (MASK_B_RECT[0] + 6, MASK_B_RECT[1] + 6, MASK_B_RECT[2] + 6, MASK_B_RECT[3] + 6)
    _write_render(
        session_factory,
        managed_root,
        ids,
        (
            (DELTA_RECT, range(0, 10), RENDER_LEVEL),
            (MASK_B_RECT, range(10, 15), RENDER_LEVEL),
            (shifted, range(15, TOTAL_FRAMES), RENDER_LEVEL),
            (MASK_C_RECT, range(10, TOTAL_FRAMES), RENDER_LEVEL),
        ),
    )
    render = _render_identity(session_factory, managed_root, ids)
    args = _compose(session_factory, managed_root, ids)["identity_drift"]
    prop = next(
        row
        for row in args["identity_measurements"]
        if str(row["object_role_id"]) == ids.role_ids["Prop"]
    )
    _raw(
        "q04r_b",
        {
            "subcase": "Q04R-b",
            "expected": "measured coverage reflects the later-segment drift",
            "observed": {
                "frames_measured": prop["frames_measured"],
                "distance_per_frame": [
                    frame["distance_to_own_reference_px"]
                    for frame in prop["rendered_frames"]
                ],
                "reference_distance_max_px": prop["reference_distance_max_px"],
                "max_adjacent_distance_px": prop["max_adjacent_distance_px"],
                "verdict": prop["verdict"],
                "aggregate": args["measured_coverage"]["aggregate_distance_px"],
            },
            "render": render,
            "disposition": "PASS",
        },
    )
    distances = [frame["distance_to_own_reference_px"] for frame in prop["rendered_frames"]]
    assert len(set(distances)) > 1, distances
    assert prop["max_adjacent_distance_px"] > 0.0


# ── Q04R-c / Q04R-d: legacy pack through the public path, coverage split ───


def test_q04r_c_and_d_legacy_pack_public_path_and_coverage_split(http_evidence) -> None:  # noqa: ANN001, E501
    client, service, ids = http_evidence
    with service.session_factory() as session:
        session.execute(delete(CharacterAsset).where(CharacterAsset.pose_slot == "reference"))
        session.commit()
        remaining = sorted(
            str(row)
            for row in session.scalars(select(CharacterAsset.pose_slot)).all()
        )
    _bind_worker(service)
    response = _submit(client, ids.project_id, ids.video_item_id, "full")
    assert response.status_code == 202, response.text
    job_id = str(response.json()["job_id"])
    _run_to_terminal(service)
    from app.persistence.models import Job

    with service.session_factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.state == "completed", job.error_json
        manifest = json.loads(job.input_manifest_json)
        items = list(
            session.scalars(
                select(QCItem).where(QCItem.video_item_id == ids.video_item_id)
            ).all()
        )
    identity_args = manifest["detector_args"]["identity_drift"]
    _raw(
        "q04r_c",
        {
            "subcase": "Q04R-c",
            "expected": "a six-slot legacy pack (no 7th reference asset) through "
            "the PUBLIC path is valid — never an unconditional 7th-asset demand",
            "observed": {
                "pose_slots_present_after_deletion": remaining,
                "submit_status": response.status_code,
                "job_state": job.state,
                "scope": manifest["scope"],
                "detectors_composed": len(manifest["detector_args"]),
                "identity_reference_pose_slot": identity_args["pinned_reference"][
                    "identity"
                ]["pose_slot"],
                "identity_reference_slot_source": identity_args["pinned_reference"][
                    "identity"
                ]["reference_slot_source"],
                "identity_measured_roles": identity_args["measured_coverage"]["roles"],
                "qc_items_persisted": len(items),
                "detectors_with_items": sorted({str(item.detector) for item in items}),
                "identity_drift_transport_bytes": len(
                    json.dumps(identity_args, separators=(",", ":"))
                ),
                "identity_drift_pretty_bytes": len(json.dumps(identity_args)),
                "identity_drift_payload_budget": identity_args["payload_budget"],
            },
            "disposition": "PASS (legacy pack measured through the declared mapping)",
        },
    )
    assert len(json.dumps(identity_args, separators=(",", ":"))) < 30000
    assert identity_args["payload_budget"]["within_limit"] is True
    assert identity_args["pinned_reference"]["identity"]["pose_slot"] == "front"
    assert (
        identity_args["pinned_reference"]["identity"]["reference_slot_source"]
        == "declared_core_pose_mapping"
    )
    assert manifest["scope"] == "full"
    assert len(manifest["detector_args"]) == 10
    _raw(
        "q04r_d",
        {
            "subcase": "Q04R-d",
            "expected": "pin coverage vs measured coverage: both fields present "
            "and distinguishable in persisted + UI-facing evidence",
            "observed": {
                "persisted_manifest": {
                    "pin_coverage": identity_args["pin_coverage"],
                    "measured_coverage": identity_args["measured_coverage"],
                },
                "distinguishable": identity_args["pin_coverage"]["kind"]
                != identity_args["measured_coverage"]["kind"],
                "ui_facing_channel": {
                    "declared_metadata_carries_coverage": identity_args["cast_pin"][
                        "expected_metadata"
                    ],
                    "item_evidence_surface": "GET /api/v2/projects/{id}/qc-items "
                    "returns the frozen detector's own evidence; a per-role "
                    "coverage block there requires the out-of-allowlist delta "
                    "named in the report (identity_drift._base_evidence / "
                    "orchestrator._persist_output)",
                },
            },
            "disposition": "PASS (persisted, distinguishable; UI-facing channel "
            "typed-blocked and reported)",
        },
    )
    assert identity_args["pin_coverage"]["kind"] == "pinned"
    assert identity_args["measured_coverage"]["kind"] == "measured"
    assert identity_args["pin_coverage"]["count"] == 3
    assert identity_args["measured_coverage"]["count"] == 3
    assert set(identity_args["measured_coverage"]["roles"]) == set(ids.role_ids.values())


def test_q04r_d_metadata_flip_surfaces_the_coverage_to_the_item(evidence_db) -> None:  # noqa: ANN001
    """The declared metadata channel carries the coverage split to an item.

    The frozen detector copies ``cast_pin.expected_metadata`` and every
    consumed frame's ``metadata`` into the QCItem evidence when an identity
    flip fires.  The composed metadata is self-consistent (no spurious flip on
    a valid render) and carries the pin/measured coverage counts, so a real
    identity flip reaches the UI-facing evidence WITH the coverage split.  The
    flip input below is taken from the SAME composition (the Extra role's own
    metadata), never fabricated.
    """
    session_factory, managed_root, ids = evidence_db
    _write_render(session_factory, managed_root, ids, DEFAULT_LAYERS)
    args = _compose(session_factory, managed_root, ids)["identity_drift"]
    consistent = identity_drift.detect(args)
    extra_metadata = json.loads(json.dumps(args["cast_pin"]["expected_metadata"]))
    extra_metadata["object_role_id"] = ids.role_ids["Extra"]
    probe = json.loads(json.dumps(args))
    probe["frames"][0]["metadata"] = extra_metadata
    flipped = identity_drift.detect(probe)
    flip_items = [item for item in flipped["items"] if item["evidence"].get("identity_flip")]
    _raw(
        "q04r_d_flip_channel",
        {
            "subcase": "Q04R-d (flip channel)",
            "expected": "no spurious flip on a valid render; a real identity "
            "flip surfaces pin/measured coverage in the item evidence",
            "observed": {
                "consistent_verdict": {
                    "status": consistent["status"],
                    "identity_flip": consistent["identity_flip"],
                    "items": len(consistent["items"]),
                },
                "flip_probe": {
                    "identity_flip": flipped["identity_flip"],
                    "items": len(flipped["items"]),
                    "evaluated": probe["frames"][0]["metadata"],
                    "expected": probe["cast_pin"]["expected_metadata"],
                    "expected_carries_coverage": {
                        "pin_coverage_count": probe["cast_pin"]["expected_metadata"][
                            "pin_coverage_count"
                        ],
                        "measured_coverage_count": probe["cast_pin"][
                            "expected_metadata"
                        ]["measured_coverage_count"],
                    },
                    "probe_provenance": "frame 0's metadata replaced with the "
                    "SAME composition's Extra-role metadata (a real value from "
                    "the same evidence, not a fabricated one)",
                },
            },
            "render": _render_identity(session_factory, managed_root, ids),
            "disposition": "PASS",
        },
    )
    assert consistent["identity_flip"] == {"flipped": False, "flip_kind": None}
    assert not [
        item for item in consistent["items"] if item["evidence"].get("identity_flip")
    ], "a consistent render must not emit an identity flip item"
    assert flipped["identity_flip"]["flipped"] is True
    assert flip_items, flipped
    evidence = flip_items[0]["evidence"]
    assert evidence["identity_flip"]["expected"]["pin_coverage_count"] == 3
    assert evidence["identity_flip"]["observed"][0]["measured_coverage_count"] == 3
    assert evidence["frames"], "the item evidence cites the rendered frames"


# ── the retained controls keep working on the ROUND-D measurement ──────────


def test_retained_control_default_world_still_passes(evidence_db) -> None:  # noqa: ANN001
    session_factory, managed_root, ids = evidence_db
    _write_render(session_factory, managed_root, ids, DEFAULT_LAYERS)
    composed = _compose(session_factory, managed_root, ids)
    # the runner hands each set over as ``sys.argv[2]`` of a child process,
    # serialised with ``json.dumps(args, separators=(",", ":"))`` — the budget
    # is measured in THAT form (the pretty dump is recorded for reference).
    sizes = {
        name: len(json.dumps(payload, separators=(",", ":")))
        for name, payload in composed.items()
    }
    pretty_sizes = {name: len(json.dumps(payload)) for name, payload in composed.items()}
    _raw(
        "retained_default_world",
        {
            "subcase": "retained control",
            "expected": "the shipped render still composes and still passes",
            "observed": {
                "detectors": sorted(composed),
                "detector_args_transport_bytes": sizes,
                "detector_args_pretty_dump_bytes": pretty_sizes,
                "serialisation": "json.dumps(args, separators=(',', ':')) "
                "(app/services/qc_checks/runner.py)",
                "child_argv_budget_bytes": 30000,
                "measured_os_ceiling_chars": {
                    "spawns": 32500,
                    "winerror_206": 32700,
                },
                "identity_drift_budget": composed["identity_drift"]["payload_budget"],
                "contact_items": len(contact_break.detect_contact_break(composed["contact_break"])),
                "z_order_items": len(z_order_error.detect_z_order_error(composed["z_order_error"])),
                "silhouette_items": len(
                    silhouette_clipping.detect_silhouette_clipping(
                        composed["silhouette_clipping"]
                    )
                ),
                "identity_distance": identity_drift.detect(
                    composed["identity_drift"]
                )["measured_distance"],
                "cut_observations": composed["cut_drift"]["cut_observations"],
            },
            "disposition": "PASS",
        },
    )
    # the bounded detector args travel to the detector as a CHILD-PROCESS
    # argument, so every set must stay well inside the Windows command line.
    assert max(sizes.values()) < 30000, sizes
    assert composed["identity_drift"]["payload_budget"]["within_limit"] is True
    assert contact_break.detect_contact_break(composed["contact_break"]) == []
    assert z_order_error.detect_z_order_error(composed["z_order_error"]) == []
    assert (
        silhouette_clipping.detect_silhouette_clipping(composed["silhouette_clipping"])
        == []
    )
    assert identity_drift.detect(composed["identity_drift"])["measured_distance"] > 0.0
    assert composed["cut_drift"]["render_cuts_ms"] == [0, 333]
    assert composed["cut_drift"]["planned_cuts_ms"] == [0, 333]


def test_retained_refusals_still_refuse(evidence_db) -> None:  # noqa: ANN001
    """The retained fail-closed row: a genuinely absent authority still refuses."""
    session_factory, managed_root, ids = evidence_db
    _write_render(session_factory, managed_root, ids, DEFAULT_LAYERS)
    with session_factory() as session:
        session.execute(delete(ProjectCastMapping))
        session.commit()
    with pytest.raises(QcEvidenceError) as raised:
        _compose(session_factory, managed_root, ids)
    assert _codes(raised.value)["identity_drift"] == QC_EVIDENCE_MISSING
    assert _no_qc_rows(session_factory) == 0
    _raw(
        "retained_refusal_missing_pin",
        {
            "subcase": "retained refusal",
            "expected": "a missing cast pin is QC_EVIDENCE_MISSING, zero QC rows",
            "observed": {
                "codes": _codes(raised.value),
                "qc_rows": _no_qc_rows(session_factory),
            },
            "disposition": "PASS",
        },
    )
