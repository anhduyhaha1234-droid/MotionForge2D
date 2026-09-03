"""S11-T04B (W10) — stale-evidence reopen (GAP-8, service-level at recheck-run).

Binary gates (production plan REV7/C6, W10 block):

1. Stale-reopen works through EXACTLY the three anchors:
   - segment supersede   (OccurrenceSegment.superseded_by_id / lineage bump)
   - manifest lifecycle  (StructuralLockManifest no longer active +
                          superseded_by_id)
   - cast revision       (ProjectCastMapping.revision changed vs the item's
                          structured ``cast_revision`` evidence)
2. ReskinConfig is NEVER an anchor (lane-A phủ định): even a REAL CAS
   revision bump of the reskin config must NOT stale-flag the item, and the
   bridge source contains no ReskinConfig reference.
3. The reopen consumes the T03F-provided GAP-8 hook
   (``reopen_stale_evidence``): acknowledged item -> open WITH the stale
   flag in fresh recheck evidence; terminal items stay terminal
   (stable transition error, fail-closed).

All anchors are produced through REAL repository mutations (supersede_segment,
ProjectCastRepository.create_mapping/update_mapping, ReskinConfigRepository
create/update) on the temp Alembic-head DB.  The bridge module does NOT exist
at WAVE_BASE — importing it here is the RED gate.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.jobs import JobRepository, StepInput
from app.persistence.models import (
    Artifact,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    Job,
    ObjectRole,
    OccurrenceSegment,
    Project,
    Scene,
    StructuralLockManifest,
    VideoItem,
    Workspace,
)
from app.persistence.qc_items import (
    QCItemInvalidTransitionError,
    QCItemRepository,
)
from app.persistence.project_cast import ProjectCastRepository
from app.persistence.reskin_config import ReskinConfigRepository
from app.persistence.structural_evidence import (
    StructuralEvidenceRepository,
)
from app.services import qc_correction_bridge as bridge
from app.services.qc_checks.orchestrator import reopen_stale_evidence

WS = DEFAULT_WORKSPACE_ID
P1 = str(uuid.uuid4())
V1 = str(uuid.uuid4())

SOURCE_MEDIA_BYTES = b"motionforge-t04b-stale-source"
SOURCE_SHA = hashlib.sha256(SOURCE_MEDIA_BYTES).hexdigest()

REPO_ROOT = Path(__file__).resolve().parent.parent

CORE_POSE_SLOTS = ("front", "three_quarter", "side", "back", "sitting", "walking")

VALID_RESKIN_PARAMS = {
    "anchor": {"x": 0.5, "y": 0.5},
    "scale": 1.0,
    "fit_mode": "contain",
    "clip_mode": "asset_alpha",
    "offset": {"x": 0.0, "y": 0.0},
    "rotation_offset_deg": 0.0,
    "opacity": 1.0,
}


def _svc():
    service = deps.get_job_service()
    assert service is not None and service.session_factory is not None
    return service


def _session():
    return _svc().session_factory()


def _seed_video(session) -> dict[str, str]:
    """Workspace + project + video + source artifact + scene + COMPLETED
    DISCOVER job (generation "1" current — needed by every real anchor
    mutation below)."""
    if session.get(Workspace, WS) is None:
        session.add(Workspace(id=WS, name=WS))
        session.flush()
    project = Project(workspace_id=WS, name="T04B-stale")
    video = VideoItem(
        project=project, title="StaleVid", position=0, width=320, height=240,
        duration_ms=6000, fps_num=30, fps_den=1,
    )
    session.add(project)
    session.flush()
    session.add(video)
    session.flush()
    source = Artifact(
        workspace_id=WS,
        kind="video",
        relative_path=f"artifacts/{WS}/video/{video.id}/import/stale-source.mp4",
        state="ready",
        sha256=SOURCE_SHA,
        size_bytes=len(SOURCE_MEDIA_BYTES),
        mime_type="video/mp4",
    )
    session.add(source)
    session.flush()
    video.source_artifact_id = source.id
    scene = Scene(
        video_item=video, position=0, start_frame=0, end_frame=299,
        start_time_ms=0, end_time_ms=9999, status="pending",
    )
    session.add(scene)
    session.flush()
    job = JobRepository(session).create_job(
        workspace_id=WS,
        job_type="DISCOVER_OBJECTS",
        owner_type="video_item",
        owner_id=video.id,
        input_manifest={"schema_version": 1, "source_sha256": SOURCE_SHA},
        idempotency_key=f"t04b-stale-discover:{uuid.uuid4()}",
        input_generation="1",
        steps=[StepInput(step_code="extract", position=0, step_type="sync")],
        actor="system",
    )
    from sqlalchemy import update as sa_update

    session.execute(sa_update(Job).where(Job.id == job.id).values(state="completed"))
    session.commit()
    return {"project": project.id, "video": video.id, "scene": scene.id}


def _seed_role(session, ids: dict[str, str], name: str = "Hero") -> ObjectRole:
    role = ObjectRole(
        workspace_id=WS,
        project_id=ids["project"],
        video_item_id=ids["video"],
        source_generation="1",
        name=name,
        kind="character",
        status="confirmed",
    )
    session.add(role)
    session.flush()
    return role


def _seed_segment(
    session, ids: dict[str, str], role: ObjectRole
) -> OccurrenceSegment:
    seg = OccurrenceSegment(
        workspace_id=WS,
        project_id=ids["project"],
        video_item_id=ids["video"],
        logical_id=str(uuid.uuid4()),
        lineage_version=1,
        role_id=role.id,
        scene_id=ids["scene"],
        name="hero-segment",
        kind="character",
        start_frame=10,
        end_frame=100,
        start_time_ms=333,
        end_time_ms=3333,
        source_generation="1",
        confidence=0.9,
        confidence_source="model",
        reasons_json="[]",
        visibility="visible",
        z_order=0,
        revision=1,
    )
    session.add(seg)
    session.flush()
    return seg


def _create_qc_item(
    session,
    *,
    ids: dict[str, str],
    layer_ref_type: str,
    layer_ref_id: str,
    evidence: dict[str, Any],
    segment_row_id: str | None = None,
    segment_logical_id: str | None = None,
    status: str = "open",
) -> Any:
    repo = QCItemRepository(session)
    item = repo.create(
        workspace_id=WS,
        project_id=ids["project"],
        video_item_id=ids["video"],
        layer_ref_type=layer_ref_type,
        layer_ref_id=layer_ref_id,
        reason_code="trajectory_drift",
        evidence_window_key=f"t04b-stale-window-{uuid.uuid4()}",
        evidence={"schema_version": 1, **evidence},
        severity="warning",
        category="trajectory_drift",
        detector="trajectory_drift",
        detector_revision="1.0.0",
        confidence=0.85,
        confidence_source="derived",
        checkpoint_ref="t04b-stale-checkpoint",
        segment_row_id=segment_row_id,
        segment_logical_id=segment_logical_id,
    )
    if status == "acknowledged":
        item = repo.acknowledge(item.id, WS)
    session.commit()
    return item


# ── anchor 1: segment supersede ─────────────────────────────────────────────


def test_segment_supersede_anchor_reopens_with_stale_flag(
    client: TestClient,  # noqa: ARG002 - conftest env patch
) -> None:
    """The REAL ``supersede_segment`` (manual same-generation workflow)
    archives the predecessor; the service-level check at recheck-run flags
    the item stale and the GAP-8 hook reopens acknowledged -> open WITH the
    stale flag in fresh evidence."""
    with _session() as session:
        ids = _seed_video(session)
        role = _seed_role(session, ids)
        seg = _seed_segment(session, ids, role)
        item = _create_qc_item(
            session,
            ids=ids,
            layer_ref_type="segment",
            layer_ref_id=seg.id,
            segment_row_id=seg.id,
            segment_logical_id=seg.logical_id,
            evidence={"segment_id": seg.id, "lineage_version": 1},
            status="acknowledged",
        )
        assert bridge.check_stale_evidence(session, item, workspace_id=WS).stale is False

        # REAL audited supersede (workflow A: manual, same generation).
        prior, successor = StructuralEvidenceRepository(session).supersede_segment(
            WS,
            seg.id,
            seg.revision,
            source_generation="1",
            name="hero-segment-fixed",
            confidence_source="manual",
            provenance={"operator": "s11-t04b", "reason": "supersede test"},
        )
        session.commit()
        assert prior.superseded_by_id == successor.id
        assert successor.lineage_version == 2

        result = bridge.check_stale_evidence(
            session, item, workspace_id=WS
        )
        assert result.stale is True
        assert result.anchor == "segment_superseded"
        assert result.superseded_by_id == successor.id

        reopened = bridge.reopen_if_stale(session, item, workspace_id=WS)
        session.commit()
        assert reopened is not None
        assert reopened.status == "open"
        assert reopened.evidence["stale"] is True
        assert reopened.evidence["recheck"] == "stale_superseded"
        assert reopened.evidence["superseded_by_id"] == successor.id
        assert reopened.evidence["supersession_reason"] == result.reason


def test_segment_lineage_bump_alone_flags_stale(
    client: TestClient,  # noqa: ARG002 - conftest env patch
) -> None:
    """A lineage_version higher than the item's recorded evidence is itself
    a stale signal (supersession always bumps the lineage)."""
    with _session() as session:
        ids = _seed_video(session)
        role = _seed_role(session, ids)
        seg = _seed_segment(session, ids, role)
        item = _create_qc_item(
            session,
            ids=ids,
            layer_ref_type="segment",
            layer_ref_id=seg.id,
            segment_row_id=seg.id,
            segment_logical_id=seg.logical_id,
            evidence={"segment_id": seg.id, "lineage_version": 1},
            status="acknowledged",
        )
        # Simulate the supersession by moving the CURRENT row to a newer
        # lineage version (the durable record the check reads).
        seg.lineage_version = 3
        session.commit()
        result = bridge.check_stale_evidence(session, item, workspace_id=WS)
        assert result.stale is True
        assert result.anchor == "segment_superseded"


# ── anchor 2: manifest lifecycle ────────────────────────────────────────────


def _seed_manifest(
    session, ids: dict[str, str], *, version: int, status: str
) -> StructuralLockManifest:
    payload = {
        "frame_count": 300,
        "timebase": {"fps": 30, "time_base": "1/30", "start_time_ms": 0},
        "shot_order": ["shot-1"],
        "fingerprints": {"z_order": "a" * 64, "contacts": "b" * 64},
        "segments": [],
        "policy_version": "structural-thresholds-v1",
    }
    manifest = StructuralLockManifest(
        workspace_id=WS,
        project_id=ids["project"],
        video_item_id=ids["video"],
        source_generation="1",
        version=version,
        status=status,
        policy_version="structural-thresholds-v1",
        manifest_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        manifest_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        revision=1,
    )
    session.add(manifest)
    session.flush()
    return manifest


def test_manifest_lifecycle_anchor_reopens(
    client: TestClient,  # noqa: ARG002 - conftest env patch
) -> None:
    """The lock manifest the item's evidence referenced stops being active
    (superseded by a newer manifest) => stale at recheck-run; reopen carries
    the manifest revision in the stale evidence."""
    with _session() as session:
        ids = _seed_video(session)
        v1 = _seed_manifest(session, ids, version=1, status="active")
        item = _create_qc_item(
            session,
            ids=ids,
            layer_ref_type="render",
            layer_ref_id="render-ref",
            evidence={"lock_manifest_id": v1.id},
            status="acknowledged",
        )
        assert bridge.check_stale_evidence(session, item, workspace_id=WS).stale is False

        # lifecycle transition: v1 is archived (superseded) BEFORE v2 is
        # created (the partial unique active index forbids two draft/active
        # rows for one video+generation — exactly the real create_manifest
        # ordering).
        v1.status = "superseded"
        v1.revision = 2
        session.flush()
        v2 = _seed_manifest(session, ids, version=2, status="active")
        v1.superseded_by_id = v2.id
        session.commit()

        result = bridge.check_stale_evidence(session, item, workspace_id=WS)
        assert result.stale is True
        assert result.anchor == "manifest_lifecycle"
        assert result.superseded_by_id == v2.id
        assert result.manifest_revision == "2"

        reopened = bridge.reopen_if_stale(session, item, workspace_id=WS)
        session.commit()
        assert reopened.status == "open"
        assert reopened.evidence["stale"] is True
        assert reopened.evidence["manifest_revision"] == "2"


def test_voided_manifest_is_also_stale(
    client: TestClient,  # noqa: ARG002 - conftest env patch
) -> None:
    """A voided lock manifest (draft->voided) is equally a lifecycle change —
    the item's lock anchor no longer exists in force."""
    with _session() as session:
        ids = _seed_video(session)
        v1 = _seed_manifest(session, ids, version=1, status="draft")
        item = _create_qc_item(
            session,
            ids=ids,
            layer_ref_type="render",
            layer_ref_id="render-ref",
            evidence={"lock_manifest_id": v1.id},
            status="acknowledged",
        )
        v1.status = "voided"
        v1.revision = 2
        session.commit()
        result = bridge.check_stale_evidence(session, item, workspace_id=WS)
        assert result.stale is True
        assert result.anchor == "manifest_lifecycle"


# ── anchor 3: cast revision ─────────────────────────────────────────────────


def _seed_character_and_packs(
    session, *, pack_versions: tuple[int, ...] = (1, 2)
) -> tuple[str, dict[int, str]]:
    """Character + one published complete pack per requested version."""
    char = Character(workspace_id=WS, name="CastChar", code=f"cc_{uuid.uuid4().hex[:6]}")
    session.add(char)
    session.flush()
    packs: dict[int, str] = {}
    for version in pack_versions:
        pv = CharacterPackVersion(
            character_id=char.id, workspace_id=WS, version=version, status="published"
        )
        session.add(pv)
        session.flush()
        for slot in CORE_POSE_SLOTS:
            art = Artifact(
                workspace_id=WS,
                kind="image",
                state="ready",
                relative_path=f"artifacts/{WS}/image/{uuid.uuid4().hex}.png",
                mime_type="image/png",
                size_bytes=100,
                sha256="c" * 64,
            )
            session.add(art)
            session.flush()
            session.add(
                CharacterAsset(
                    pack_version_id=pv.id,
                    workspace_id=WS,
                    pose_slot=slot,
                    artifact_id=art.id,
                )
            )
        packs[version] = pv.id
    session.flush()
    return char.id, packs


def test_cast_revision_anchor_reopens(
    client: TestClient,  # noqa: ARG002 - conftest env patch
) -> None:
    """A REAL repin (``ProjectCastRepository.update_mapping`` CAS) changes the
    mapping revision; the item's structured ``cast_revision`` evidence is
    then stale and the service-level check reopens it."""
    with _session() as session:
        ids = _seed_video(session)
        role = _seed_role(session, ids)
        char_id, packs = _seed_character_and_packs(session)
        mapping, created = ProjectCastRepository(session).create_mapping(
            WS, ids["project"], role.id, char_id, packs[1],
            idempotency_key=f"t04b-cast:{uuid.uuid4()}",
        )
        assert created is True
        assert mapping.revision == 1
        item = _create_qc_item(
            session,
            ids=ids,
            layer_ref_type="object",
            layer_ref_id=f"obj-{role.id[:8]}",
            evidence={"object_role_id": role.id, "cast_revision": 1},
            status="acknowledged",
        )
        session.commit()
        assert bridge.check_stale_evidence(session, item, workspace_id=WS).stale is False

        # REAL CAS repin through the repository -> revision 2.
        updated = ProjectCastRepository(session).update_mapping(
            mapping.id, WS, expected_revision=1, pack_version_id=packs[2]
        )
        session.commit()
        assert updated.revision == 2

        result = bridge.check_stale_evidence(session, item, workspace_id=WS)
        assert result.stale is True
        assert result.anchor == "cast_revision"
        assert result.cast_revision == "2"

        reopened = bridge.reopen_if_stale(session, item, workspace_id=WS)
        session.commit()
        assert reopened.status == "open"
        assert reopened.evidence["stale"] is True
        assert reopened.evidence["cast_revision"] == "2"


def test_cast_revision_untouched_means_not_stale(
    client: TestClient,  # noqa: ARG002 - conftest env patch
) -> None:
    """Negative control: with the mapping revision matching the item's
    evidence, NO anchor fires (the check is exact, not time-based)."""
    with _session() as session:
        ids = _seed_video(session)
        role = _seed_role(session, ids)
        char_id, packs = _seed_character_and_packs(session, pack_versions=(1,))
        mapping, _ = ProjectCastRepository(session).create_mapping(
            WS, ids["project"], role.id, char_id, packs[1],
            idempotency_key=f"t04b-cast2:{uuid.uuid4()}",
        )
        item = _create_qc_item(
            session,
            ids=ids,
            layer_ref_type="object",
            layer_ref_id=f"obj-{role.id[:8]}",
            evidence={"object_role_id": role.id, "cast_revision": mapping.revision},
            status="acknowledged",
        )
        session.commit()
        assert bridge.check_stale_evidence(session, item, workspace_id=WS).stale is False
        assert bridge.reopen_if_stale(session, item, workspace_id=WS) is None


# ── lane-A phủ định: ReskinConfig is NEVER an anchor ────────────────────────


def test_reskin_config_revision_change_is_never_an_anchor(
    client: TestClient,  # noqa: ARG002 - conftest env patch
) -> None:
    """Even a REAL CAS reskin-config revision bump must NOT stale-flag the
    item (lane-A phủ định): the only cast anchor is ProjectCastMapping."""
    with _session() as session:
        ids = _seed_video(session)
        role = _seed_role(session, ids)
        char_id, packs = _seed_character_and_packs(session, pack_versions=(1,))
        config, created = ReskinConfigRepository(session).create_config(
            WS,
            ids["project"],
            role.id,
            char_id,
            packs[1],
            dict(VALID_RESKIN_PARAMS),
            idempotency_key=f"t04b-reskin:{uuid.uuid4()}",
        )
        assert created is True
        item = _create_qc_item(
            session,
            ids=ids,
            layer_ref_type="object",
            layer_ref_id=f"obj-{role.id[:8]}",
            evidence={"object_role_id": role.id, "cast_revision": 1},
            status="acknowledged",
        )
        session.commit()
        assert bridge.check_stale_evidence(session, item, workspace_id=WS).stale is False

        # REAL CAS reskin update bumps config.revision (params-only repin).
        changed = dict(VALID_RESKIN_PARAMS)
        changed["opacity"] = 0.5
        updated = ReskinConfigRepository(session).update_config(
            config.id, WS, expected_revision=1, params=changed
        )
        session.commit()
        assert updated.revision == 2

        # The reskin bump must NOT fire any stale anchor.
        result = bridge.check_stale_evidence(session, item, workspace_id=WS)
        assert result.stale is False, "ReskinConfig must never be an anchor"
        assert bridge.reopen_if_stale(session, item, workspace_id=WS) is None


def test_bridge_source_never_references_reskin() -> None:
    """Binary lane-A: the bridge's stale-check CODE contains zero ReskinConfig
    references (no import, no repository use, no ORM read — the phủ định
    binds on behavior, not docstring prose)."""
    source = (REPO_ROOT / "app/services/qc_correction_bridge.py").read_text(
        encoding="utf-8"
    )
    for token in ("reskin_config", "ReskinConfig(", "ReskinConfigRepository", "ReskinConfigRecord"):
        assert token not in source, f"bridge must not reference {token!r}"
    assert "reskin" not in source.lower().replace(
        "reskinconfig", "RCSK-ONLY-PROSE"
    ), "bridge code must not reference reskin in any code form"


# ── terminal items stay terminal ────────────────────────────────────────────


def test_terminal_item_is_refused_by_stale_reopen(
    client: TestClient,  # noqa: ARG002 - conftest env patch
) -> None:
    """resolved/dismissed are terminal (T02B): the GAP-8 hook refuses a stale
    supersession with the repository's stable transition error — the bridge
    must not silently reopen terminal items."""
    with _session() as session:
        ids = _seed_video(session)
        role = _seed_role(session, ids)
        seg = _seed_segment(session, ids, role)
        item = _create_qc_item(
            session,
            ids=ids,
            layer_ref_type="segment",
            layer_ref_id=seg.id,
            segment_row_id=seg.id,
            segment_logical_id=seg.logical_id,
            evidence={"segment_id": seg.id, "lineage_version": 1},
            status="open",
        )
        repo = QCItemRepository(session)
        repo.recheck_resolved(
            item.id,
            WS,
            evidence={
                "schema_version": 1,
                "recheck": "resolved",
                # fresh recheck evidence keeps its location anchors (the same
                # way real detector evidence references its segment window)
                "segment_id": seg.id,
                "lineage_version": 1,
            },
        )
        resolved = repo.get(item.id, WS)
        session.commit()
        assert resolved.status == "resolved"

        with pytest.raises(QCItemInvalidTransitionError):
            reopen_stale_evidence(
                repo,
                resolved,
                workspace_id=WS,
                superseded_by_id="succ-1",
                supersession_reason="segment superseded",
            )
        # The bridge's own reopen wrapper refuses through the same hook —
        # with a REAL stale signal (segment lineage bumped) present.
        seg.lineage_version = 2
        seg.revision = 2
        session.commit()
        with pytest.raises(QCItemInvalidTransitionError):
            bridge.reopen_if_stale(session, resolved, workspace_id=WS)
