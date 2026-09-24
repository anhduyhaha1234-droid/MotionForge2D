"""MF-P1-QC-EVIDENCE — persisted evidence readers (read-only, verified).

Every reader in this module answers ONE question: *what does the database and
the managed artifact root actually contain for this video item right now?*
Nothing is synthesized.  Rows are read through the owning public
repositories where the contract exists (structural evidence segments /
occlusions / contacts, render routes, full-apply publications) and re-checked
against the requesting scope so that cross-owner (foreign) evidence can never
be mixed in.

Byte-level integrity: an artifact read re-hashes the file on disk and
compares it with the ``artifact.sha256`` / ``artifact.size_bytes`` the
database recorded BEFORE the bytes are used as detector input.  A byte that
does not match is ``QC_EVIDENCE_TAMPERED`` — never a silent pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.artifacts import hash_file, is_within
from app.persistence.models import (
    Artifact,
    ArtifactOwner,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    ProjectCastMapping,
    Scene,
    VideoItem,
)
from app.persistence.s10_full_apply import S10ApplyRepository
from app.persistence.structural_evidence import (
    ContactRecord,
    OcclusionRecord,
    SegmentRecord,
    StructuralEvidenceRepository,
)
from app.persistence.structural_lock import (
    LockManifestRecord,
    RenderRouteRecord,
    StructuralLockRepository,
)
from app.services.qc_evidence.errors import (
    dependency,
    foreign,
    malformed,
    missing,
    stale,
    tampered,
)

#: Artifact row states that mean "the bytes are published and usable".
_READY = "ready"


@dataclass(frozen=True)
class VideoScope:
    """The requesting scope, verified against the video item's own row."""

    workspace_id: str
    project_id: str
    video_item_id: str
    source_generation: str
    width: int | None
    height: int | None
    fps_num: int | None
    fps_den: int | None
    duration_ms: int | None
    source_artifact_id: str | None
    title: str

    def canvas(self, detector: str = "qc_evidence") -> tuple[int, int]:
        if not self.width or not self.height:
            raise missing(
                detector,
                "video item has no persisted canvas dimensions "
                "(video_item.width/height are NULL) — the frame geometry the "
                "detector must judge against was never probed at import",
                video_item_id=self.video_item_id,
            )
        return int(self.width), int(self.height)


@dataclass(frozen=True)
class ArtifactEvidence:
    """A verified managed artifact: row identity + bytes re-hashed on read."""

    artifact_id: str
    kind: str
    relative_path: str
    sha256: str
    size_bytes: int
    data: bytes
    purposes: tuple[str, ...]

    def provenance(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "purposes": list(self.purposes),
            "bytes_reverified": True,
        }


# ── scope ────────────────────────────────────────────────────────────────────


def load_scope(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    generation: str = "1",
) -> VideoScope:
    """Resolve + ownership-check the video item (FOREIGN refusal otherwise)."""
    if not workspace_id or not project_id or not video_item_id:
        raise missing(
            "qc_evidence",
            "workspace_id, project_id and video_item_id are required to "
            "resolve persisted QC evidence",
        )
    item = session.get(VideoItem, video_item_id)
    if item is None:
        raise missing(
            "qc_evidence",
            f"video item {video_item_id!r} does not exist",
            video_item_id=video_item_id,
        )
    if str(item.project_id) != project_id:
        raise foreign(
            "qc_evidence",
            f"video item {video_item_id!r} belongs to project "
            f"{item.project_id!r}, not {project_id!r}",
            video_item_id=video_item_id,
            actual_project_id=str(item.project_id),
        )
    from app.persistence.models import Project

    project = session.get(Project, project_id)
    if project is None or str(project.workspace_id) != workspace_id:
        raise foreign(
            "qc_evidence",
            f"project {project_id!r} does not belong to workspace "
            f"{workspace_id!r}",
            project_id=project_id,
        )
    return VideoScope(
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        source_generation=str(generation or "1"),
        width=item.width,
        height=item.height,
        fps_num=item.fps_num,
        fps_den=item.fps_den,
        duration_ms=item.duration_ms,
        source_artifact_id=item.source_artifact_id,
        title=str(item.title),
    )


# ── artifacts ────────────────────────────────────────────────────────────────


def _artifact_purposes(session: Session, artifact_id: str) -> tuple[str, ...]:
    rows = session.scalars(
        select(ArtifactOwner.purpose).where(ArtifactOwner.artifact_id == artifact_id)
    ).all()
    return tuple(sorted(str(p) for p in rows))


def read_artifact(
    session: Session,
    managed_root: Path,
    scope: VideoScope,
    artifact_id: str,
    *,
    detector: str,
) -> ArtifactEvidence:
    """Read one managed artifact, re-verifying its bytes against the row."""
    if not artifact_id:
        raise missing(
            detector,
            "no artifact id recorded for the evidence this detector needs",
            video_item_id=scope.video_item_id,
        )
    row = session.get(Artifact, artifact_id)
    if row is None:
        raise missing(
            detector,
            f"artifact {artifact_id!r} does not exist",
            artifact_id=artifact_id,
        )
    if str(row.workspace_id) != scope.workspace_id:
        raise foreign(
            detector,
            f"artifact {artifact_id!r} belongs to workspace "
            f"{row.workspace_id!r}, not {scope.workspace_id!r}",
            artifact_id=artifact_id,
        )
    if str(row.state) != _READY:
        raise stale(
            detector,
            f"artifact {artifact_id!r} state is {row.state!r}; only a "
            "published (ready) artifact is admissible QC evidence",
            artifact_id=artifact_id,
            artifact_state=str(row.state),
        )
    relative = str(row.relative_path or "")
    if not relative or ".partial" in relative:
        raise malformed(
            detector,
            f"artifact {artifact_id!r} has an unusable relative path "
            f"{relative!r}",
            artifact_id=artifact_id,
        )
    absolute = Path(managed_root) / relative
    if not is_within(absolute, Path(managed_root)) or not absolute.is_file():
        raise missing(
            detector,
            f"artifact {artifact_id!r} file is absent under the managed root "
            f"({relative})",
            artifact_id=artifact_id,
            relative_path=relative,
        )
    declared_sha = str(row.sha256 or "").lower()
    declared_size = row.size_bytes
    if not declared_sha or declared_size is None:
        raise malformed(
            detector,
            f"artifact {artifact_id!r} row records no sha256/size — its bytes "
            "cannot be verified as evidence",
            artifact_id=artifact_id,
        )
    actual_size = int(absolute.stat().st_size)
    if actual_size != int(declared_size):
        raise tampered(
            detector,
            f"artifact {artifact_id!r} size on disk ({actual_size}) does not "
            f"match the recorded size ({declared_size})",
            artifact_id=artifact_id,
            declared_size_bytes=int(declared_size),
            actual_size_bytes=actual_size,
        )
    actual_sha = hash_file(absolute).lower()
    if actual_sha != declared_sha:
        raise tampered(
            detector,
            f"artifact {artifact_id!r} bytes hash to {actual_sha} but the row "
            f"records {declared_sha}",
            artifact_id=artifact_id,
            declared_sha256=declared_sha,
            actual_sha256=actual_sha,
        )
    return ArtifactEvidence(
        artifact_id=str(row.id),
        kind=str(row.kind),
        relative_path=relative,
        sha256=declared_sha,
        size_bytes=int(declared_size),
        data=absolute.read_bytes(),
        purposes=_artifact_purposes(session, str(row.id)),
    )


def source_artifact(
    session: Session, managed_root: Path, scope: VideoScope, *, detector: str
) -> ArtifactEvidence:
    """The video item's own imported source artifact (family: source)."""
    if not scope.source_artifact_id:
        raise missing(
            detector,
            "video item has no source artifact recorded "
            "(video_item.source_artifact_id is NULL)",
            video_item_id=scope.video_item_id,
        )
    return read_artifact(
        session, managed_root, scope, scope.source_artifact_id, detector=detector
    )


def publication_artifact(
    session: Session, managed_root: Path, scope: VideoScope, *, detector: str
) -> tuple[ArtifactEvidence, dict[str, Any]] | None:
    """Newest completed full-apply publication artifact (family: result).

    Returns ``None`` when no full-apply run exists at all.  Raises
    ``QC_EVIDENCE_STALE`` when a completed run exists but carries no usable
    completed publication — evidence that exists yet is not current is never
    silently skipped.
    """
    repo = S10ApplyRepository(session)
    runs = [
        run
        for run in repo.list_runs(scope.workspace_id, project_id=scope.project_id)
        if str(run.video_item_id) == scope.video_item_id
    ]
    if not runs:
        return None
    completed = [run for run in runs if str(run.status) == "completed"]
    if not completed:
        raise stale(
            detector,
            "the video has full-apply runs but none completed; the rendered "
            "result is not current",
            runs=[str(run.id) for run in runs][:5],
        )
    newest = completed[0]
    publications = [
        pub
        for pub in repo.list_publications(scope.workspace_id, newest.id)
        if str(pub.state) == "completed"
    ]
    if not publications:
        raise stale(
            detector,
            f"full-apply run {newest.id!r} completed without a completed "
            "publication — there is no published render to measure",
            run_id=str(newest.id),
        )
    pub = publications[0]
    if str(pub.workspace_id) != scope.workspace_id:
        raise foreign(
            detector,
            f"publication {pub.id!r} belongs to workspace {pub.workspace_id!r}",
            publication_id=str(pub.id),
        )
    artifact = read_artifact(
        session, managed_root, scope, str(pub.artifact_id), detector=detector
    )
    return artifact, {
        "publication_id": str(pub.id),
        "run_id": str(newest.id),
        "content_hash": str(pub.content_hash),
        "checkpoint_id": str(pub.checkpoint_id),
        "checkpoint_hash": str(pub.checkpoint_hash),
        "frame_count": int(pub.frame_count),
        "frame_metadata": dict(pub.frame_metadata or {}),
    }


def render_result_artifact(
    session: Session, managed_root: Path, scope: VideoScope, *, detector: str
) -> tuple[ArtifactEvidence, str, dict[str, Any]]:
    """Resolve the video's current rendered result by disclosed precedence.

    1. the newest completed full-apply publication artifact (the strongest
       result evidence: it carries the run + checkpoint identity);
    2. otherwise the newest PUBLISHED render-side artifact owned by the video
       (owner purpose ``result`` — what the object-correction / publication
       producers stage as the video's rendered output);
    3. otherwise the imported source artifact — for a video that was never
       rendered the current result IS its source, and the returned role says
       so explicitly so a reviewer can see exactly which artifact was used.
    """
    published = publication_artifact(session, managed_root, scope, detector=detector)
    if published is not None:
        artifact, meta = published
        return artifact, "publication", meta
    owned = rendered_result_artifacts(session, scope, exclude=scope.source_artifact_id)
    for artifact_id in owned:
        artifact = read_artifact(
            session, managed_root, scope, artifact_id, detector=detector
        )
        return artifact, "owned_result_artifact", {
            "reason": "no completed full-apply publication exists; the newest "
            "published render-side artifact owned by this video is used",
            "owner_purposes": list(artifact.purposes),
        }
    artifact = source_artifact(session, managed_root, scope, detector=detector)
    return artifact, "source_fallback_no_render", {
        "reason": "no completed full-apply publication and no owned render-side "
        "artifact exist for this video; the imported source artifact is the "
        "current render"
    }


def rendered_result_artifacts(
    session: Session, scope: VideoScope, *, exclude: str | None
) -> tuple[str, ...]:
    """Ids of the video's render-side artifacts, newest first.

    Deliberately NOT filtered by artifact state: a newer render-side artifact
    that is not published yet must be READ and refused as ``QC_EVIDENCE_STALE``
    by :func:`read_artifact`, never silently skipped in favour of an older,
    still-ready artifact — that would judge the video against a superseded
    render and read as green.
    """
    rows = session.execute(
        select(Artifact.id)
        .join(ArtifactOwner, ArtifactOwner.artifact_id == Artifact.id)
        .where(
            Artifact.workspace_id == scope.workspace_id,
            Artifact.kind.in_(("video", "image")),
            ArtifactOwner.owner_type == "video_item",
            ArtifactOwner.owner_id == scope.video_item_id,
            ArtifactOwner.purpose.in_(("result", "publication", "render")),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id)
    ).all()
    return tuple(str(row[0]) for row in rows if str(row[0]) != str(exclude or ""))


def rendered_minus_expected_masks(
    session: Session, scope: VideoScope, *, expected_id: str
) -> tuple[str, ...]:
    """Candidate ids for the RENDERED-side mask of ``expected_id``.

    The rendered side must be a DIFFERENT persisted artifact (different id
    and, checked by the caller, a different sha256) covering the SAME region
    as the expected mask — comparing a mask with itself, or with a mask that
    bounds a different region, is refused by the composer.
    """
    rows = session.execute(
        select(Artifact.id, Artifact.created_at)
        .join(ArtifactOwner, ArtifactOwner.artifact_id == Artifact.id)
        .where(
            Artifact.workspace_id == scope.workspace_id,
            Artifact.kind == "image",
            Artifact.state == _READY,
            ArtifactOwner.owner_type == "video_item",
            ArtifactOwner.owner_id == scope.video_item_id,
            ArtifactOwner.purpose == "mask",
            Artifact.id != expected_id,
        )
        .order_by(Artifact.created_at.desc(), Artifact.id)
    ).all()
    return tuple(str(row[0]) for row in rows)


# ── structural evidence ──────────────────────────────────────────────────────


def current_segments(session: Session, scope: VideoScope) -> list[SegmentRecord]:
    """Current-generation segments of the video (family: result)."""
    rows, _total = StructuralEvidenceRepository(session).list_segments(
        scope.workspace_id,
        video_item_id=scope.video_item_id,
        only_current=True,
        limit=500,
    )
    out: list[SegmentRecord] = []
    for row in rows:
        if str(row.project_id) != scope.project_id or str(row.video_item_id) != scope.video_item_id:
            raise foreign(
                "qc_evidence",
                f"segment {row.id!r} is owned by "
                f"{row.project_id!r}/{row.video_item_id!r}, outside the "
                "requested scope",
                segment_id=str(row.id),
            )
        out.append(row)
    return out


def render_routes(session: Session, scope: VideoScope) -> list[RenderRouteRecord]:
    """Persisted renderer-route decisions for the video (family: annotation)."""
    return StructuralLockRepository(session).list_routes_for_video(
        scope.workspace_id, scope.project_id, scope.video_item_id
    )


def occlusion_edges(session: Session, scope: VideoScope) -> list[OcclusionRecord]:
    """Scene-graph occlusion annotations for the video."""
    rows = StructuralEvidenceRepository(session).list_occlusions(scope.workspace_id)
    return [
        row
        for row in rows
        if str(row.video_item_id) == scope.video_item_id
        and str(row.project_id) == scope.project_id
    ]


def contact_edges(session: Session, scope: VideoScope) -> list[ContactRecord]:
    """Scene-graph contact annotations for the video."""
    rows = StructuralEvidenceRepository(session).list_contacts(scope.workspace_id)
    return [
        row
        for row in rows
        if str(row.video_item_id) == scope.video_item_id
        and str(row.project_id) == scope.project_id
    ]


def scene_rows(session: Session, scope: VideoScope) -> list[Scene]:
    """Scene-detector boundaries (family: annotation, ground truth)."""
    return list(
        session.scalars(
            select(Scene)
            .where(
                Scene.video_item_id == scope.video_item_id,
            )
            .order_by(Scene.position, Scene.id)
        ).all()
    )


def current_lock_manifest(
    session: Session, scope: VideoScope
) -> LockManifestRecord | None:
    """The current active/draft S09 manifest, or ``None`` when none exists."""
    try:
        return StructuralLockRepository(session).get_current_manifest(
            scope.workspace_id,
            scope.project_id,
            scope.video_item_id,
            scope.source_generation,
        )
    except Exception:
        return None


#: The pose slot that carries the character library's REFERENCE pixels.  The
#: identity authority of a reskin is the pinned CharacterID + PackVersion and
#: the bytes of this slot — never a crop of the video's own source frames.
REFERENCE_POSE_SLOT = "reference"


def _compatibility_verdict(
    session: Session, scope: VideoScope, row: ProjectCastMapping, detector: str
) -> dict[str, Any]:
    """The pinned cast mapping's compatibility verdict, or a typed refusal.

    There is deliberately NO fail-open branch: when the evaluator raises (a
    query failure, a timeout, an authority outage) the pin has NO verdict, and
    reporting ``compatible=True`` would fabricate the one fact the identity
    check is built on.  The refusal names the evaluator as the missing
    producer and carries the evaluator error verbatim.
    """
    from app.persistence.project_cast import evaluate_compatibility

    try:
        result = evaluate_compatibility(
            session,
            scope.workspace_id,
            scope.project_id,
            str(row.object_role_id),
            str(row.character_id),
            str(row.pack_version_id),
            int(row.revision),
            str(row.id),
        )
    except Exception as exc:
        raise dependency(
            detector,
            "the cast compatibility evaluator raised for the pinned target "
            "identity, so no compatibility verdict exists for it; a "
            "fail-open 'compatible' would be a fabricated verdict",
            fact="the compatibility verdict of the project cast pin",
            producer="app.persistence.project_cast.evaluate_compatibility",
            persistence="project_cast_mapping revision + "
            "character_pack_version.status/revision + character_asset pose slots",
            mapping_id=str(row.id),
            object_role_id=str(row.object_role_id),
            evaluator_error_type=type(exc).__name__,
            evaluator_error=str(exc)[:500],
        ) from exc
    return {
        "compatible": bool(result.compatible),
        "reasons": [str(reason) for reason in (result.reasons or [])],
        "blocked": bool(getattr(result, "blocked", False)),
        "fallback_allowed": bool(getattr(result, "fallback_allowed", False)),
        "pinned_version_id": (
            str(result.pinned_version_id)
            if getattr(result, "pinned_version_id", None) is not None
            else None
        ),
        "current_revision": getattr(result, "current_revision", None),
        "evaluator": "app.persistence.project_cast.evaluate_compatibility",
    }


def cast_pin_for_role(
    session: Session,
    managed_root: Path,
    scope: VideoScope,
    role_id: str,
    *,
    detector: str,
) -> dict[str, Any]:
    """The TARGET IDENTITY of one object role (finding R4).

    For a reskin the video's source is the MOTION authority; the identity
    authority is the SELECTED library pin — the project cast mapping's
    ``character_id`` + immutable ``pack_version_id`` plus that pack version's
    REFERENCE artifact, whose bytes are re-hashed on read.  Every fact carries
    its provenance (role, mapping revision, character/pack version + revision,
    workspace, source generation, artifact sha256/size).

    Fail-closed: a missing pin (``QC_EVIDENCE_MISSING``), a foreign pin
    (``QC_EVIDENCE_FOREIGN``), an unpublished/mismatched reference asset
    (``QC_EVIDENCE_DEPENDENCY`` with the exact producer), tampered reference
    bytes (``QC_EVIDENCE_TAMPERED``, raised by :func:`read_artifact`) and an
    evaluator that cannot produce a verdict (``QC_EVIDENCE_DEPENDENCY``) each
    refuse.  The verdict is NEVER coerced to ``compatible=True``.
    """
    row = session.scalar(
        select(ProjectCastMapping).where(
            ProjectCastMapping.workspace_id == scope.workspace_id,
            ProjectCastMapping.project_id == scope.project_id,
            ProjectCastMapping.object_role_id == role_id,
        )
    )
    if row is None:
        raise missing(
            detector,
            f"the project holds no cast pin for object role {role_id!r}: the "
            "reskin target identity (CharacterID + PackVersion) was never "
            "selected, so no library target exists to judge the rendered "
            "identity against",
            role_id=role_id,
            project_id=scope.project_id,
        )
    if str(row.workspace_id) != scope.workspace_id or str(row.project_id) != scope.project_id:
        raise foreign(
            detector,
            f"cast pin {row.id!r} belongs to "
            f"{row.workspace_id!r}/{row.project_id!r}, outside the requested "
            "scope",
            mapping_id=str(row.id),
            role_id=role_id,
        )
    character = session.get(Character, str(row.character_id))
    pack = session.get(CharacterPackVersion, str(row.pack_version_id))
    if character is None or pack is None:
        raise missing(
            detector,
            "the pinned target identity is dangling: the cast pin references "
            "a character / pack version row that does not exist",
            mapping_id=str(row.id),
            character_id=str(row.character_id),
            pack_version_id=str(row.pack_version_id),
        )
    if (
        str(pack.character_id) != str(row.character_id)
        or str(pack.workspace_id) != scope.workspace_id
    ):
        raise foreign(
            detector,
            f"pinned pack version {row.pack_version_id!r} does not belong to "
            f"character {row.character_id!r} in workspace "
            f"{scope.workspace_id!r}; the pin is not admissible for this video",
            mapping_id=str(row.id),
        )
    if str(character.workspace_id) != scope.workspace_id:
        raise foreign(
            detector,
            f"pinned character {row.character_id!r} belongs to workspace "
            f"{character.workspace_id!r}, outside the requested scope",
            mapping_id=str(row.id),
        )
    asset = session.scalars(
        select(CharacterAsset)
        .where(
            CharacterAsset.pack_version_id == str(row.pack_version_id),
            CharacterAsset.pose_slot == REFERENCE_POSE_SLOT,
        )
        .order_by(CharacterAsset.id)
    ).first()
    if asset is None:
        raise dependency(
            detector,
            f"pinned pack version {row.pack_version_id!r} carries no "
            f"{REFERENCE_POSE_SLOT!r} pose asset: the character library never "
            "published the reference pixels of this target, and the video's "
            "own source frames are not the identity authority",
            fact="the pinned REFERENCE artifact of the selected PackVersion",
            producer="character pack publication (CharacterAsset pose_slot="
            f"{REFERENCE_POSE_SLOT!r})",
            persistence="character_asset.artifact_id",
        )
    reference = read_artifact(
        session, managed_root, scope, str(asset.artifact_id), detector=detector
    )
    verdict = _compatibility_verdict(session, scope, row, detector)
    return {
        "mapping_id": str(row.id),
        "mapping_revision": int(row.revision),
        "object_role_id": str(row.object_role_id),
        "character_id": str(row.character_id),
        "character_revision": int(character.revision),
        "character_status": str(character.status),
        "pack_version_id": str(row.pack_version_id),
        "pack_version": int(pack.version),
        "pack_version_revision": int(pack.revision),
        "pack_version_status": str(pack.status),
        "workspace_id": scope.workspace_id,
        "project_id": scope.project_id,
        "source_generation": scope.source_generation,
        "pose_slot": str(asset.pose_slot),
        "reference_asset_id": str(asset.id),
        "reference_artifact": reference.provenance(),
        "compatible": bool(verdict.get("compatible")),
        "reasons": list(verdict.get("reasons") or []),
        "compatibility": verdict,
        # internal (JSON-unsafe) handle for the reference bytes; never
        # serialized — compose reads it through ``pin_identity``/``pin_reference``
        "reference_evidence": reference,
    }


def pin_identity(pin: Mapping[str, Any]) -> dict[str, Any]:
    """JSON-safe identity view of a cast pin (drops the byte-level handle)."""
    return {key: value for key, value in pin.items() if key != "reference_evidence"}


def pin_reference(pin: Mapping[str, Any]) -> ArtifactEvidence:
    """The pinned library reference bytes of a cast pin (re-verified on read)."""
    evidence = pin.get("reference_evidence")
    if not isinstance(evidence, ArtifactEvidence):  # pragma: no cover - defensive
        raise malformed(
            "qc_evidence",
            "cast pin carries no verified reference artifact handle",
        )
    return evidence



def manifest_segments(manifest: LockManifestRecord) -> list[dict[str, Any]]:
    """The validated manifest's segment list (public S09 payload)."""
    segments = manifest.manifest.get("segments")
    if not isinstance(segments, list):
        raise malformed(
            "z_order_error",
            f"structural lock manifest {manifest.id!r} carries no segment list",
            manifest_id=str(manifest.id),
        )
    return [dict(seg) for seg in segments if isinstance(seg, dict)]
