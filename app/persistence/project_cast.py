"""Durable Project Cast Mapping persistence (S07-T01 + C1/C2).

Pins a Project Object Role to an immutable Character Pack Version.

Design rules (mirroring S08 object_intelligence + S06 character_library +
frozen C1/C2 policy):
- Workspace + project ownership validated fail-closed on every write.
- Valid ObjectRole: must exist, same workspace, same project, current generation.
- Pin exactly one immutable PackVersion: FK to character_pack_version.id;
  character_id is denormalized guard FK to character.id, must match pack_version.character_id.
- Pack must be published and complete (CORE_POSE_SLOTS).
- source_overlay never reused; kind mismatch; capability mismatch → rejected.
- Generation authority: ObjectIntelligenceRepository.current_generation.
- Idempotent replay: UNIQUE(workspace_id, idempotency_key) WHERE IS NOT NULL;
  equivalent compatible replay returns existing, incompatible → 409 zero mutation.
- Revision/CAS: UPDATE ... WHERE revision=:expected; zero rows → 409.
- FK RESTRICT fail closed; PRAGMA foreign_key_check clean.
- Authoritative compatibility in this module only (single source).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session, joinedload

from app.persistence.models import (
    CORE_POSE_SLOTS,
    PACK_CONTRACT_VERSION_LEGACY,
    PACK_CONTRACT_VERSION_REFERENCE,
    Character,
    CharacterPackVersion,
    ObjectRole,
    Project,
    ProjectCastMapping,
    SeriesCastSnapshot,
    SeriesCastSnapshotEntry,
    VideoItem,
    utc_now,
)

if TYPE_CHECKING:
    from app.persistence.characters import PackVersionRecord

CompatibilityReason = Literal[
    "workspace_mismatch",
    "source_overlay_refusal",
    "object_kind_mismatch",
    "incomplete_pack",
    "unpublished_pack",
    "missing_required_pose",
    "missing_required_capability",
    "generation_mismatch",
    "stale_revision",
]

class ProjectCastError(Exception):
    """Base error for Project Cast Mapping."""


class ProjectCastNotFoundError(ProjectCastError):
    """Mapping not found in workspace."""


class ProjectCastConflictError(ProjectCastError):
    """Idempotency conflict or CAS stale revision or compatibility blocked."""


class ProjectCastOwnershipError(ProjectCastError):
    """Cross-workspace or project/role ownership mismatch."""


@dataclass(frozen=True)
class ProjectCastRecord:
    id: str
    workspace_id: str
    project_id: str
    object_role_id: str
    character_id: str
    pack_version_id: str
    idempotency_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CompatibilityResult:
    compatible: bool
    reasons: list[CompatibilityReason]
    fallback_allowed: bool
    fallback_description: str | None
    blocked: bool
    pinned_version_id: str | None
    current_revision: int | None
    workspace_id: str


def _map_row(row: ProjectCastMapping) -> ProjectCastRecord:
    return ProjectCastRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        object_role_id=row.object_role_id,
        character_id=row.character_id,
        pack_version_id=row.pack_version_id,
        idempotency_key=row.idempotency_key,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _ensure_workspace(session: Session, workspace_id: str) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.persistence.models import Workspace

    session.execute(
        sqlite_insert(Workspace)
        .values(id=workspace_id, name=workspace_id)
        .on_conflict_do_nothing(index_elements=[Workspace.id])
    )


def _reference_branch_missing_keys(pack: CharacterPackVersion) -> list[str]:
    """Missing declared reference keys of a reference_pack_v1 row.

    Returns a non-empty list when the pack is incomplete OR its frozen
    requirement manifest fails integrity — i.e. exactly when the pack must
    not be treated as a complete reference set (mirrors
    ``reference_pack_completeness`` from the MF-END-04 validator).
    """
    from app.workflow.character_validator import (
        PackContractBranch,
        parse_reference_manifest,
    )

    manifest = parse_reference_manifest(
        PackContractBranch(
            pack_contract_version=pack.pack_contract_version,
            requirement_manifest_json=pack.requirement_manifest_json,
            requirement_manifest_sha256=pack.requirement_manifest_sha256,
        )
    )
    if manifest.errors:
        return ["<invalid reference manifest>"]
    attached = {asset.pose_slot for asset in (pack.assets or [])}
    return [req.key for req in manifest.requirements if req.key not in attached]


def _kind_compatible(role_kind: str, character_type: str) -> bool:
    if role_kind == character_type:
        return True
    if role_kind in ("background", "foreground", "graphic") and character_type in ("prop", "other"):
        return True
    return role_kind == "other" and character_type in ("character", "prop", "other")


def _evaluate_compatibility_pure(
    workspace_id: str,
    role: ObjectRole | None,
    pack: CharacterPackVersion | None,
    character: Character | None,
    project: Project | None,
    mapping: ProjectCastMapping | None,
    expected_revision: int | None,
    current_generation: str | None,
) -> tuple[bool, list[CompatibilityReason], bool, str | None]:
    reasons: list[CompatibilityReason] = []

    if role is None or pack is None or character is None or project is None:  # noqa: SIM102
        if "workspace_mismatch" not in reasons:  # noqa: SIM102
            reasons.append("workspace_mismatch")
        return False, reasons, False, None

    if (  # noqa: SIM102, E501
        role.workspace_id != workspace_id
        or pack.workspace_id != workspace_id  # noqa: E501
        or character.workspace_id != workspace_id  # noqa: E501
        or project.workspace_id != workspace_id  # noqa: E501
    ):
        if "workspace_mismatch" not in reasons:  # noqa: SIM102
            reasons.append("workspace_mismatch")

    if project.workspace_id != workspace_id:  # noqa: SIM102
        if "workspace_mismatch" not in reasons:  # noqa: SIM102
            reasons.append("workspace_mismatch")

    if role.kind == "source_overlay":  # noqa: SIM102
        if "source_overlay_refusal" not in reasons:  # noqa: SIM102
            reasons.append("source_overlay_refusal")

    if pack.status != "published":  # noqa: SIM102
        if "unpublished_pack" not in reasons:  # noqa: SIM102
            reasons.append("unpublished_pack")

    # Completeness dispatches on the pack contract branch (MF-END-05):
    # a legacy row keeps the CORE_POSE_SLOTS demand EXACTLY as before, while
    # a reference_pack_v1 row is complete when its frozen requirement
    # manifest passed integrity and every declared reference key is attached
    # (same rule as reference_pack_completeness in the MF-END-04 validator).
    if pack.pack_contract_version == PACK_CONTRACT_VERSION_REFERENCE:
        if _reference_branch_missing_keys(pack):  # noqa: SIM102
            if "incomplete_pack" not in reasons:  # noqa: SIM102
                reasons.append("incomplete_pack")
    else:
        present_slots = {a.pose_slot for a in (pack.assets or [])}
        missing = [s for s in CORE_POSE_SLOTS if s not in present_slots]
        if missing:  # noqa: SIM102
            if "incomplete_pack" not in reasons:  # noqa: SIM102
                reasons.append("incomplete_pack")
            if "missing_required_pose" not in reasons:  # noqa: SIM102
                reasons.append("missing_required_pose")

    if role.kind in ("character", "prop") and character.character_type == "other":  # noqa: SIM102
        if "missing_required_capability" not in reasons:  # noqa: SIM102
            reasons.append("missing_required_capability")

    if not _kind_compatible(role.kind, character.character_type):  # noqa: SIM102
        if "object_kind_mismatch" not in reasons:  # noqa: SIM102
            reasons.append("object_kind_mismatch")

    if current_generation is not None and role.source_generation != current_generation:  # noqa: SIM102
        if "generation_mismatch" not in reasons:  # noqa: SIM102
            reasons.append("generation_mismatch")

    if expected_revision is not None and mapping is not None and mapping.revision != expected_revision:  # noqa: E501, SIM102
        if "stale_revision" not in reasons:  # noqa: SIM102
            reasons.append("stale_revision")

    compatible = len(reasons) == 0
    # P1-A: deterministic fallback matrix — only generation_mismatch and
    # incomplete_pack (including its companion missing_required_pose) are
    # fallback-supported. All other reasons remain fail-closed.
    fallback_allowed = False
    fallback_desc: str | None = None
    if not compatible:
        # Supported fallback reasons (deterministic, no silent nearest-match)
        supported_fallback = {"generation_mismatch", "incomplete_pack"}
        # incomplete_pack always co-occurs with missing_required_pose in current
        # impl; treat that companion as part of the same fallback bucket.
        supported_with_companion = {"generation_mismatch", "incomplete_pack", "missing_required_pose"}  # noqa: E501
        reason_set = set(reasons)
        if reason_set.issubset(supported_with_companion) and reason_set.intersection(supported_fallback):  # noqa: E501
            fallback_allowed = True
            if "generation_mismatch" in reason_set:
                fallback_desc = "Có thể ghim với cảnh báo: thế hệ nguồn khác với hiện tại (generation mismatch) — cần xác nhận có chủ đích."  # noqa: E501
            elif "incomplete_pack" in reason_set:
                fallback_desc = "Có thể ghim với cảnh báo: pack thiếu pose bắt buộc — sẽ dùng fallback có chủ đích."  # noqa: E501
            else:
                fallback_desc = "Có thể ghim với cảnh báo có chủ đích."
    return compatible, reasons, fallback_allowed, fallback_desc


def evaluate_compatibility(
    session: Session,
    workspace_id: str,
    project_id: str,
    object_role_id: str,
    character_id: str,
    pack_version_id: str,
    expected_revision: int | None = None,
    mapping_id: str | None = None,
) -> CompatibilityResult:
    project = session.get(Project, project_id)
    role = session.get(ObjectRole, object_role_id)
    pack = session.scalars(
        select(CharacterPackVersion).options(joinedload(CharacterPackVersion.assets)).where(CharacterPackVersion.id == pack_version_id)  # noqa: E501
    ).first()
    # Fallback if not found via joinedload (for test where pack may not have assets)
    if pack is None:
        pack = session.get(CharacterPackVersion, pack_version_id)
        if pack is not None:
            # Ensure assets loaded
            session.refresh(pack, attribute_names=["assets"])
    character = session.get(Character, character_id)
    mapping: ProjectCastMapping | None = None
    pinned_version_id: str | None = None
    current_rev: int | None = None
    if mapping_id is not None:
        mapping = session.scalar(
            select(ProjectCastMapping).where(
                ProjectCastMapping.id == mapping_id, ProjectCastMapping.workspace_id == workspace_id
            )
        )
        if mapping is not None:
            pinned_version_id = mapping.pack_version_id
            current_rev = mapping.revision
            if mapping.project_id != project_id or mapping.object_role_id != object_role_id:
                # Fail closed: mapping_id mismatch
                return CompatibilityResult(
                    compatible=False,
                    reasons=["workspace_mismatch"],
                    fallback_allowed=False,
                    fallback_description=None,
                    blocked=True,
                    pinned_version_id=pinned_version_id,
                    current_revision=current_rev,
                    workspace_id=workspace_id,
                )
            if expected_revision is not None and mapping.revision != expected_revision:
                # Will be handled as stale_revision in pure eval
                pass
        else:
            # mapping_id provided but not found in workspace -> workspace_mismatch (no leak)
            return CompatibilityResult(
                compatible=False,
                reasons=["workspace_mismatch"],
                fallback_allowed=False,
                fallback_description=None,
                blocked=True,
                pinned_version_id=None,
                current_revision=None,
                workspace_id=workspace_id,
            )
    else:
        # Try to find existing mapping for this project+role for pinned display
        existing = session.scalar(
            select(ProjectCastMapping).where(
                ProjectCastMapping.project_id == project_id,
                ProjectCastMapping.object_role_id == object_role_id,
                ProjectCastMapping.workspace_id == workspace_id,
            )
        )
        if existing is not None:
            pinned_version_id = existing.pack_version_id
            current_rev = existing.revision
            mapping = existing

    # Determine current generation via backend authority
    current_gen: str | None = None
    if role is not None:
        from app.persistence.object_intelligence import (
            ObjectIntelligenceRepository,
            RoleNotFoundError,
        )

        repo = ObjectIntelligenceRepository(session)
        try:
            current_gen = repo.current_generation(workspace_id, role.video_item_id)
        except RoleNotFoundError:
            # P2 (C2): the video item itself does not exist in THIS workspace —
            # fail closed as workspace_mismatch instead of skipping the
            # generation check (which would let a cross-workspace role pass).
            return CompatibilityResult(
                compatible=False,
                reasons=["workspace_mismatch"],
                fallback_allowed=False,
                fallback_description=None,
                blocked=True,
                pinned_version_id=pinned_version_id,
                current_revision=current_rev,
                workspace_id=workspace_id,
            )
        # C3-P1: no broad ``except Exception`` here. The generation authority
        # is the single source of truth for staleness; swallowing arbitrary
        # backend errors (OperationalError/SQLAlchemy/RuntimeError) would turn
        # an authority outage into current_gen=None and silently skip the
        # generation check (fail-open). Every other exception MUST propagate
        # so create/repin/evaluate fail closed with a 5xx — never a 2xx built
        # on unknown authority state.

    compatible, reasons, fallback_allowed, fallback_desc = _evaluate_compatibility_pure(
        workspace_id=workspace_id,
        role=role,
        pack=pack,
        character=character,
        project=project,
        mapping=mapping,
        expected_revision=expected_revision,
        current_generation=current_gen,
    )

    # Additional checks for missing entities that should be workspace_mismatch
    if project is None or project.workspace_id != workspace_id:  # noqa: SIM102
        if "workspace_mismatch" not in reasons:  # noqa: SIM102
            reasons.append("workspace_mismatch")
        compatible = False
    if role is None or role.workspace_id != workspace_id or role.project_id != project_id:  # noqa: SIM102
        if "workspace_mismatch" not in reasons:  # noqa: SIM102
            # If role exists but project mismatch, it's already workspace_mismatch via pure, but ensure  # noqa: E501
            if role is not None and role.project_id != project_id:
                pass
            else:
                reasons.append("workspace_mismatch")
        compatible = False
    if character is None or character.workspace_id != workspace_id:  # noqa: SIM102
        if "workspace_mismatch" not in reasons:  # noqa: SIM102
            reasons.append("workspace_mismatch")
        compatible = False
    if pack is None or pack.workspace_id != workspace_id or pack.character_id != character_id:  # noqa: SIM102
        if "workspace_mismatch" not in reasons:  # noqa: SIM102
            # Check if pack exists but character mismatch is already handled elsewhere, but keep
            reasons.append("workspace_mismatch")
        compatible = False

    # Re-evaluate fallback after additional workspace checks (deterministic)
    if not compatible:
        supported_fallback = {"generation_mismatch", "incomplete_pack"}
        supported_with_companion = {"generation_mismatch", "incomplete_pack", "missing_required_pose"}  # noqa: E501
        reason_set = set(reasons)
        if reason_set.issubset(supported_with_companion) and reason_set.intersection(supported_fallback):  # noqa: E501
            fallback_allowed = True
            if fallback_desc is None:
                if "generation_mismatch" in reason_set:
                    fallback_desc = "Có thể ghim với cảnh báo: thế hệ nguồn khác với hiện tại (generation mismatch) — cần xác nhận có chủ đích."  # noqa: E501
                elif "incomplete_pack" in reason_set:
                    fallback_desc = "Có thể ghim với cảnh báo: pack thiếu pose bắt buộc — sẽ dùng fallback có chủ đích."  # noqa: E501
        else:
            # Any unsupported reason → no fallback
            fallback_allowed = False
            fallback_desc = None

    blocked = not compatible and not fallback_allowed
    return CompatibilityResult(
        compatible=compatible,
        reasons=reasons,
        fallback_allowed=fallback_allowed,
        fallback_description=fallback_desc,
        blocked=blocked,
        pinned_version_id=pinned_version_id,
        current_revision=current_rev,
        workspace_id=workspace_id,
    )


def _check_compatibility_or_raise(
    session: Session,
    workspace_id: str,
    project_id: str,
    object_role_id: str,
    character_id: str,
    pack_version_id: str,
    expected_revision: int | None = None,
    mapping_id: str | None = None,
    fallback_acknowledged: bool = False,
) -> None:
    result = evaluate_compatibility(
        session,
        workspace_id,
        project_id,
        object_role_id,
        character_id,
        pack_version_id,
        expected_revision=expected_revision,
        mapping_id=mapping_id,
    )
    if not result.compatible:
        # Fallback-supported with explicit client acknowledgement is allowed end-to-end
        if result.fallback_allowed and fallback_acknowledged:
            return
        reason_str = ",".join(result.reasons) if result.reasons else "incompatible"
        if "workspace_mismatch" in result.reasons:
            raise ProjectCastOwnershipError(f"compatibility blocked: {reason_str}")
        raise ProjectCastConflictError(f"compatibility blocked: {reason_str}")


class ProjectCastRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _assert_ownership(
        self,
        workspace_id: str,
        project_id: str,
        object_role_id: str,
        character_id: str,
        pack_version_id: str,
    ) -> None:
        project = self._session.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            raise ProjectCastOwnershipError("project ownership mismatch")
        role = self._session.get(ObjectRole, object_role_id)
        if role is None or role.workspace_id != workspace_id:
            raise ProjectCastOwnershipError("object role ownership mismatch")
        if role.project_id != project_id:
            raise ProjectCastOwnershipError("object role project mismatch")
        character = self._session.get(Character, character_id)
        if character is None or character.workspace_id != workspace_id:
            raise ProjectCastOwnershipError("character ownership mismatch")
        pack = self._session.get(CharacterPackVersion, pack_version_id)
        if pack is None or pack.workspace_id != workspace_id:
            raise ProjectCastOwnershipError("pack version ownership mismatch")
        if pack.character_id != character_id:
            raise ProjectCastOwnershipError("pack version character mismatch")

    @staticmethod
    def _assert_equivalent_request(
        existing: ProjectCastMapping,
        project_id: str,
        object_role_id: str,
        character_id: str,
        pack_version_id: str,
    ) -> None:
        if (
            existing.project_id != project_id
            or existing.object_role_id != object_role_id
            or existing.character_id != character_id
            or existing.pack_version_id != pack_version_id
        ):
            raise ProjectCastConflictError(
                f"idempotency key {existing.idempotency_key!r} is already bound to a different cast mapping payload"  # noqa: E501
            )

    def create_mapping(
        self,
        workspace_id: str,
        project_id: str,
        object_role_id: str,
        character_id: str,
        pack_version_id: str,
        idempotency_key: str | None = None,
        fallback_acknowledged: bool = False,
    ) -> tuple[ProjectCastRecord, bool]:
        if not project_id.strip():
            raise ValueError("project_id must not be empty")
        if not object_role_id.strip():
            raise ValueError("object_role_id must not be empty")
        if not character_id.strip():
            raise ValueError("character_id must not be empty")
        if not pack_version_id.strip():
            raise ValueError("pack_version_id must not be empty")
        if idempotency_key is not None and len(idempotency_key) > 255:
            raise ValueError("idempotency_key too long")
        if idempotency_key is not None and not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty if provided")
        _ensure_workspace(self._session, workspace_id)
        # Idempotency check first: if key exists and payload equivalent, return idempotent without compatibility re-check  # noqa: E501
        # But we must also ensure that equivalent replay is only for compatible payloads that were previously accepted  # noqa: E501
        # If existing mapping exists with same key and equivalent payload, return it (idempotent)
        if idempotency_key:
            existing = self._session.scalar(
                select(ProjectCastMapping).where(
                    ProjectCastMapping.workspace_id == workspace_id,
                    ProjectCastMapping.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                self._assert_equivalent_request(
                    existing, project_id, object_role_id, character_id, pack_version_id
                )
                return _map_row(existing), False
        # C4-P1b: natural unique pre-check MUST be workspace-scoped. A pair
        # occupied in ANOTHER workspace is not "already exists" for this one -
        # leaking that via 409 before the fail-closed compatibility check
        # reveals cross-workspace occupancy state. Scope it like the
        # idempotency lookup above.
        natural_existing = self._session.scalar(
            select(ProjectCastMapping).where(
                ProjectCastMapping.workspace_id == workspace_id,
                ProjectCastMapping.project_id == project_id,
                ProjectCastMapping.object_role_id == object_role_id,
            )
        )
        if natural_existing is not None:
            if idempotency_key and natural_existing.idempotency_key == idempotency_key:
                self._assert_equivalent_request(
                    natural_existing, project_id, object_role_id, character_id, pack_version_id
                )
                return _map_row(natural_existing), False
            raise ProjectCastConflictError(
                f"mapping for project {project_id!r} and role {object_role_id!r} already exists"
            )
        # Authoritative compatibility check (fail closed, zero mutation) - must be before ownership to ensure correct generation check  # noqa: E501
        # But we still need ownership for missing entity cases; evaluate_compatibility handles workspace checks  # noqa: E501
        _check_compatibility_or_raise(
            self._session, workspace_id, project_id, object_role_id, character_id, pack_version_id,
            fallback_acknowledged=fallback_acknowledged,
        )
        # Also assert ownership for missing entity 404 mapping (kept for backward)
        self._assert_ownership(workspace_id, project_id, object_role_id, character_id, pack_version_id)  # noqa: E501
        row = ProjectCastMapping(
            workspace_id=workspace_id,
            project_id=project_id,
            object_role_id=object_role_id,
            character_id=character_id,
            pack_version_id=pack_version_id,
            idempotency_key=idempotency_key,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            if idempotency_key:
                existing = self._session.scalar(
                    select(ProjectCastMapping).where(
                        ProjectCastMapping.workspace_id == workspace_id,
                        ProjectCastMapping.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    self._assert_equivalent_request(
                        existing, project_id, object_role_id, character_id, pack_version_id
                    )
                    return _map_row(existing), False
            natural = self._session.scalar(
                select(ProjectCastMapping).where(
                    ProjectCastMapping.workspace_id == workspace_id,
                    ProjectCastMapping.project_id == project_id,
                    ProjectCastMapping.object_role_id == object_role_id,
                )
            )
            if natural is not None:
                if idempotency_key and natural.idempotency_key == idempotency_key:
                    self._assert_equivalent_request(
                        natural, project_id, object_role_id, character_id, pack_version_id
                    )
                    return _map_row(natural), False
                raise ProjectCastConflictError(
                    f"mapping for project {project_id!r} and role {object_role_id!r} already exists (concurrent)"  # noqa: E501
                ) from None
            raise
        return _map_row(row), True

    def get_mapping(self, mapping_id: str, workspace_id: str) -> ProjectCastRecord:
        row = self._session.scalar(
            select(ProjectCastMapping).where(
                ProjectCastMapping.id == mapping_id, ProjectCastMapping.workspace_id == workspace_id
            )
        )
        if row is None:
            raise ProjectCastNotFoundError(f"Mapping {mapping_id!r} not found")
        return _map_row(row)

    def list_mappings(
        self,
        workspace_id: str,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ProjectCastRecord], int]:
        from sqlalchemy import func

        filters = [ProjectCastMapping.workspace_id == workspace_id]
        if project_id is not None:
            proj = self._session.get(Project, project_id)
            if proj is None or proj.workspace_id != workspace_id:
                raise ProjectCastNotFoundError(f"Project {project_id!r} not found")
            filters.append(ProjectCastMapping.project_id == project_id)
        total = int(self._session.scalar(select(func.count(ProjectCastMapping.id)).where(*filters)) or 0)  # noqa: E501
        rows = self._session.scalars(
            select(ProjectCastMapping).where(*filters).order_by(ProjectCastMapping.created_at.desc(), ProjectCastMapping.id).offset(offset).limit(limit)  # noqa: E501
        ).all()
        return [_map_row(r) for r in rows], total

    def update_mapping(
        self,
        mapping_id: str,
        workspace_id: str,
        expected_revision: int,
        pack_version_id: str | None = None,
        character_id: str | None = None,
        fallback_acknowledged: bool = False,
    ) -> ProjectCastRecord:
        if expected_revision < 1:
            raise ValueError("revision must be >= 1")
        current = self._session.scalar(
            select(ProjectCastMapping).where(
                ProjectCastMapping.id == mapping_id, ProjectCastMapping.workspace_id == workspace_id
            )
        )
        if current is None:
            raise ProjectCastNotFoundError(f"Mapping {mapping_id!r} not found")
        if current.revision != expected_revision:
            raise ProjectCastConflictError(f"stale revision {expected_revision}; current revision is {current.revision}")  # noqa: E501
        new_character_id = character_id if character_id is not None else current.character_id
        new_pack_version_id = pack_version_id if pack_version_id is not None else current.pack_version_id  # noqa: E501
        if new_character_id == current.character_id and new_pack_version_id == current.pack_version_id:  # noqa: E501
            return _map_row(current)
        # Authoritative compatibility for repin (fail closed)
        _check_compatibility_or_raise(
            self._session,
            workspace_id,
            current.project_id,
            current.object_role_id,
            new_character_id,
            new_pack_version_id,
            expected_revision=expected_revision,
            mapping_id=mapping_id,
            fallback_acknowledged=fallback_acknowledged,
        )
        self._assert_ownership(
            workspace_id, current.project_id, current.object_role_id, new_character_id, new_pack_version_id  # noqa: E501
        )
        values: dict[str, object] = {
            "revision": expected_revision + 1,
            "updated_at": utc_now(),
            "character_id": new_character_id,
            "pack_version_id": new_pack_version_id,
        }
        stmt = (
            update(ProjectCastMapping)
            .where(
                ProjectCastMapping.id == mapping_id,
                ProjectCastMapping.workspace_id == workspace_id,
                ProjectCastMapping.revision == expected_revision,
            )
            .values(**values)
            .returning(ProjectCastMapping)
        )
        try:
            row = self._session.execute(stmt).scalar_one()
        except NoResultFound:
            latest = self._session.scalar(
                select(ProjectCastMapping).where(
                    ProjectCastMapping.id == mapping_id, ProjectCastMapping.workspace_id == workspace_id  # noqa: E501
                )
            )
            cur_rev = latest.revision if latest is not None else None
            raise ProjectCastConflictError(f"stale revision {expected_revision}; current revision is {cur_rev}") from None  # noqa: E501
        return _map_row(row)

    def delete_mapping(
        self,
        mapping_id: str,
        workspace_id: str,
        expected_revision: int | None = None,
    ) -> None:
        row = self._session.scalar(
            select(ProjectCastMapping).where(
                ProjectCastMapping.id == mapping_id, ProjectCastMapping.workspace_id == workspace_id
            )
        )
        if row is None:
            raise ProjectCastNotFoundError(f"Mapping {mapping_id!r} not found")
        if expected_revision is None:
            raise ValueError("revision is required for delete")
        if row.revision != expected_revision:
            raise ProjectCastConflictError(f"stale revision {expected_revision}; current revision is {row.revision}")  # noqa: E501
        from sqlalchemy import delete

        del_stmt = (
            delete(ProjectCastMapping).where(
                ProjectCastMapping.id == mapping_id,
                ProjectCastMapping.workspace_id == workspace_id,
                ProjectCastMapping.revision == expected_revision,
            )
        )
        result = self._session.execute(del_stmt)
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise ProjectCastConflictError(f"stale revision {expected_revision}; current revision is {row.revision}")  # noqa: E501
        self._session.flush()


# ── MF-END-05: series cast snapshot ("series pin") ─────────────────────────────
#
# A series is the production container (``project``) that owns its video
# items.  A snapshot freezes the reusable cast set of the series WITHOUT
# cloning the library: every entry references the immutable ``character`` /
# ``character_pack_version`` rows by FK and stores only frozen digests.  The
# per-video pin itself stays in ``project_cast_mapping`` (the single cast
# authority, S07-T01); ``apply_snapshot_to_video`` copies a frozen snapshot
# onto a new video of the series through the EXISTING ``create_mapping``
# service, so this module never becomes a second cast store.

ROLE_KEY_MAX_LENGTH = 64
STYLE_VERSION_MAX_LENGTH = 64
_ROLE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


class SeriesCastError(ProjectCastError):
    """Base error for the series cast snapshot."""


class SeriesCastNotFoundError(ProjectCastNotFoundError):
    """Snapshot (or its target) not found in this workspace."""


class SeriesCastConflictError(ProjectCastConflictError):
    """Freeze/apply refused: branch, completeness, coverage or digest conflict."""


class SeriesCastOwnershipError(ProjectCastOwnershipError):
    """Cross-workspace / cross-series ownership mismatch."""


class SeriesCastStaleError(SeriesCastConflictError):
    """A frozen entry no longer matches the live library.

    Deliberate re-pin creates a NEW snapshot; an existing frozen snapshot is
    never rewritten, and no stale entry is applied silently.
    """


@dataclass(frozen=True)
class SeriesCastEntryInput:
    """Requested ``role_key -> character / pack version / style`` entry."""

    role_key: str
    character_id: str
    pack_version_id: str
    style_version: str | None = None


@dataclass(frozen=True)
class SeriesCastReference:
    """One frozen per-key asset reference (``pose_slot``/``artifact_id``/sha)."""

    pose_slot: str
    artifact_id: str
    sha256: str | None


@dataclass(frozen=True)
class SeriesCastEntryRecord:
    role_key: str
    character_id: str
    pack_version_id: str
    pack_contract_version: str
    manifest_sha256: str | None
    style_version: str | None
    references: tuple[SeriesCastReference, ...]


@dataclass(frozen=True)
class SeriesCastSnapshotRecord:
    id: str
    workspace_id: str
    project_id: str
    snapshot_index: int
    entries_sha256: str
    entries: tuple[SeriesCastEntryRecord, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SeriesCastApplyEntry:
    role_key: str
    object_role_id: str
    mapping_id: str
    character_id: str
    pack_version_id: str
    manifest_sha256: str | None
    created: bool


@dataclass(frozen=True)
class SeriesCastApplyResult:
    snapshot_id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    entries_sha256: str
    entries: tuple[SeriesCastApplyEntry, ...]


def _validate_role_key(role_key: str) -> str:
    if not isinstance(role_key, str) or not _ROLE_KEY_PATTERN.match(role_key):
        raise ValueError(f"role_key {role_key!r} must match {_ROLE_KEY_PATTERN.pattern!r}")
    return role_key


def _validate_style_version(style_version: str | None) -> str | None:
    if style_version is None:
        return None
    if not style_version.strip() or len(style_version) > STYLE_VERSION_MAX_LENGTH:
        raise ValueError(
            f"style_version must be 1..{STYLE_VERSION_MAX_LENGTH} characters when provided"
        )
    return style_version


def _references_from_record(record: PackVersionRecord) -> tuple[SeriesCastReference, ...]:
    references = [
        SeriesCastReference(
            pose_slot=asset.pose_slot,
            artifact_id=asset.artifact_id,
            sha256=asset.artifact_sha256,
        )
        for asset in record.assets
    ]
    return tuple(sorted(references, key=lambda ref: ref.pose_slot))


def _references_bytes(references: Sequence[SeriesCastReference]) -> bytes:
    payload = [
        {"pose_slot": ref.pose_slot, "artifact_id": ref.artifact_id, "sha256": ref.sha256}
        for ref in sorted(references, key=lambda ref: ref.pose_slot)
    ]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _entries_bytes(entries: Sequence[SeriesCastEntryRecord]) -> bytes:
    payload = [
        {
            "role_key": entry.role_key,
            "character_id": entry.character_id,
            "pack_version_id": entry.pack_version_id,
            "pack_contract_version": entry.pack_contract_version,
            "manifest_sha256": entry.manifest_sha256,
            "style_version": entry.style_version,
            "references": json.loads(_references_bytes(entry.references).decode("utf-8")),
        }
        for entry in sorted(entries, key=lambda item: item.role_key)
    ]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _map_series_entry(row: SeriesCastSnapshotEntry) -> SeriesCastEntryRecord:
    references = tuple(
        SeriesCastReference(
            pose_slot=ref["pose_slot"],
            artifact_id=ref["artifact_id"],
            sha256=ref.get("sha256"),
        )
        for ref in json.loads(row.references_json)
    )
    return SeriesCastEntryRecord(
        role_key=row.role_key,
        character_id=row.character_id,
        pack_version_id=row.pack_version_id,
        pack_contract_version=row.pack_contract_version,
        manifest_sha256=row.manifest_sha256,
        style_version=row.style_version,
        references=references,
    )


class SeriesCastRepository:
    """Durable series cast snapshot over the EXISTING per-video cast authority."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- reads -----------------------------------------------------------------

    def get_snapshot(self, snapshot_id: str, workspace_id: str) -> SeriesCastSnapshotRecord:
        return self._load_snapshot_record(snapshot_id, workspace_id)

    def latest_snapshot(
        self, workspace_id: str, project_id: str
    ) -> SeriesCastSnapshotRecord | None:
        header = self._session.scalar(
            select(SeriesCastSnapshot)
            .where(
                SeriesCastSnapshot.workspace_id == workspace_id,
                SeriesCastSnapshot.project_id == project_id,
            )
            .order_by(SeriesCastSnapshot.snapshot_index.desc())
            .limit(1)
        )
        if header is None:
            return None
        return self._load_snapshot_record(header.id, workspace_id)

    def list_snapshots(
        self,
        workspace_id: str,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SeriesCastSnapshotRecord], int]:
        from sqlalchemy import func

        filters = [SeriesCastSnapshot.workspace_id == workspace_id]
        if project_id is not None:
            project = self._session.get(Project, project_id)
            if project is None or project.workspace_id != workspace_id:
                raise SeriesCastNotFoundError(f"Project {project_id!r} not found")
            filters.append(SeriesCastSnapshot.project_id == project_id)
        total = int(
            self._session.scalar(select(func.count(SeriesCastSnapshot.id)).where(*filters))
            or 0
        )
        rows = self._session.scalars(
            select(SeriesCastSnapshot)
            .where(*filters)
            .order_by(
                SeriesCastSnapshot.project_id,
                SeriesCastSnapshot.snapshot_index.desc(),
                SeriesCastSnapshot.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return [self._load_snapshot_record(row.id, workspace_id) for row in rows], total

    # -- freeze ----------------------------------------------------------------

    def freeze_snapshot(
        self,
        workspace_id: str,
        project_id: str,
        entries: Sequence[SeriesCastEntryInput],
    ) -> tuple[SeriesCastSnapshotRecord, bool]:
        """Freeze *entries* as the next series snapshot (INSERT-only).

        Returns ``(record, created)``.  A freeze whose canonical entry digest
        equals the latest snapshot's is an idempotent replay: the existing
        latest snapshot is returned with ``created=False`` and no row is
        written.  A digest difference creates ``snapshot_index + 1``; the old
        snapshot is never modified.
        """
        if not project_id.strip():
            raise ValueError("project_id must not be empty")
        if not entries:
            raise ValueError("entries must not be empty")
        _ensure_workspace(self._session, workspace_id)
        project = self._session.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            raise SeriesCastOwnershipError("project ownership mismatch")
        seen: set[str] = set()
        normalized: list[SeriesCastEntryInput] = []
        for entry in entries:
            role_key = _validate_role_key(entry.role_key)
            if role_key in seen:
                raise ValueError(f"duplicate role_key {role_key!r} in freeze request")
            seen.add(role_key)
            normalized.append(
                SeriesCastEntryInput(
                    role_key=role_key,
                    character_id=entry.character_id,
                    pack_version_id=entry.pack_version_id,
                    style_version=_validate_style_version(entry.style_version),
                )
            )
        resolved = [
            self._resolve_frozen_entry(workspace_id, entry) for entry in normalized
        ]
        digest = hashlib.sha256(_entries_bytes(resolved)).hexdigest()

        latest_header = self._session.scalar(
            select(SeriesCastSnapshot)
            .where(
                SeriesCastSnapshot.workspace_id == workspace_id,
                SeriesCastSnapshot.project_id == project_id,
            )
            .order_by(SeriesCastSnapshot.snapshot_index.desc())
            .limit(1)
        )
        if latest_header is not None and latest_header.entries_sha256 == digest:
            return self._load_snapshot_record(latest_header.id, workspace_id), False

        next_index = 1 if latest_header is None else latest_header.snapshot_index + 1
        header = SeriesCastSnapshot(
            workspace_id=workspace_id,
            project_id=project_id,
            snapshot_index=next_index,
            entries_sha256=digest,
        )
        self._session.add(header)
        self._session.flush()
        for entry in resolved:
            self._session.add(
                SeriesCastSnapshotEntry(
                    snapshot_id=header.id,
                    workspace_id=workspace_id,
                    role_key=entry.role_key,
                    character_id=entry.character_id,
                    pack_version_id=entry.pack_version_id,
                    pack_contract_version=entry.pack_contract_version,
                    manifest_sha256=entry.manifest_sha256,
                    style_version=entry.style_version,
                    references_json=_references_bytes(entry.references).decode("utf-8"),
                )
            )
        self._session.flush()
        return self._load_snapshot_record(header.id, workspace_id), True

    # -- apply -----------------------------------------------------------------

    def apply_snapshot_to_video(
        self,
        snapshot_id: str,
        workspace_id: str,
        video_item_id: str,
        resolutions: Sequence[tuple[str, str]],
    ) -> SeriesCastApplyResult:
        """Copy a frozen snapshot onto a new video of the same series.

        ``resolutions`` maps every snapshot ``role_key`` to the target video's
        ``object_role_id`` — the WHOLE set is required (no partial pin), so a
        shared series cast is never half-applied silently.  Every frozen entry
        is re-verified against the live library (published, same branch, same
        manifest sha, same canonical asset references) before ANY mapping is
        written; a mismatch refuses the whole call (zero mutation).  The pins
        are written through the EXISTING ``ProjectCastRepository.create_mapping``
        service with a deterministic ``series-snapshot:<id>:<role>`` idempotency
        key, so replaying the same copy is idempotent.
        """
        if not video_item_id.strip():
            raise ValueError("video_item_id must not be empty")
        snapshot = self._load_snapshot_record(snapshot_id, workspace_id)
        video = self._session.get(VideoItem, video_item_id)
        if video is None:
            raise SeriesCastNotFoundError(f"Video item {video_item_id!r} not found")
        project = self._session.get(Project, video.project_id)
        if project is None or project.workspace_id != workspace_id:
            raise SeriesCastOwnershipError("video item ownership mismatch")
        if video.project_id != snapshot.project_id:
            raise SeriesCastOwnershipError(
                "snapshot and target video do not belong to the same series (project mismatch)"
            )
        by_key = {entry.role_key: entry for entry in snapshot.entries}
        provided: dict[str, str] = {}
        for role_key, object_role_id in resolutions:
            key = _validate_role_key(role_key)
            if key in provided:
                raise ValueError(f"duplicate role_key {key!r} in apply request")
            if key not in by_key:
                raise SeriesCastConflictError(
                    f"role_key {key!r} is not part of snapshot {snapshot_id!r}"
                )
            provided[key] = object_role_id
        missing = sorted(key for key in by_key if key not in provided)
        if missing:
            raise SeriesCastConflictError(
                "series pin copies the WHOLE set: missing resolutions for "
                + ", ".join(missing)
            )
        for key in sorted(provided):
            role = self._session.get(ObjectRole, provided[key])
            if role is None or role.workspace_id != workspace_id:
                raise SeriesCastOwnershipError(
                    f"role {key!r}: object role ownership mismatch"
                )
            if role.project_id != snapshot.project_id or role.video_item_id != video_item_id:
                raise SeriesCastOwnershipError(
                    f"role {key!r}: object role does not belong to the target video "
                    "of this series"
                )
            self._assert_frozen_entry_live(workspace_id, by_key[key])

        repo = ProjectCastRepository(self._session)
        applied: list[SeriesCastApplyEntry] = []
        for key in sorted(provided):
            entry = by_key[key]
            record, created = repo.create_mapping(
                workspace_id=workspace_id,
                project_id=snapshot.project_id,
                object_role_id=provided[key],
                character_id=entry.character_id,
                pack_version_id=entry.pack_version_id,
                idempotency_key=f"series-snapshot:{snapshot.id}:{video_item_id}:{key}",
            )
            applied.append(
                SeriesCastApplyEntry(
                    role_key=key,
                    object_role_id=provided[key],
                    mapping_id=record.id,
                    character_id=record.character_id,
                    pack_version_id=record.pack_version_id,
                    manifest_sha256=entry.manifest_sha256,
                    created=created,
                )
            )
        return SeriesCastApplyResult(
            snapshot_id=snapshot.id,
            workspace_id=workspace_id,
            project_id=snapshot.project_id,
            video_item_id=video_item_id,
            entries_sha256=snapshot.entries_sha256,
            entries=tuple(applied),
        )

    # -- internals -------------------------------------------------------------

    def _load_snapshot_record(
        self, snapshot_id: str, workspace_id: str
    ) -> SeriesCastSnapshotRecord:
        header = self._session.scalar(
            select(SeriesCastSnapshot).where(
                SeriesCastSnapshot.id == snapshot_id,
                SeriesCastSnapshot.workspace_id == workspace_id,
            )
        )
        if header is None:
            raise SeriesCastNotFoundError(f"Snapshot {snapshot_id!r} not found")
        rows = self._session.scalars(
            select(SeriesCastSnapshotEntry)
            .where(SeriesCastSnapshotEntry.snapshot_id == header.id)
            .order_by(SeriesCastSnapshotEntry.role_key)
        ).all()
        entries = tuple(_map_series_entry(row) for row in rows)
        digest = hashlib.sha256(_entries_bytes(entries)).hexdigest()
        if digest != header.entries_sha256:
            raise SeriesCastConflictError(
                f"snapshot {snapshot_id!r} is corrupt: recomputed entries digest {digest} "
                f"does not match frozen {header.entries_sha256}"
            )
        return SeriesCastSnapshotRecord(
            id=header.id,
            workspace_id=header.workspace_id,
            project_id=header.project_id,
            snapshot_index=header.snapshot_index,
            entries_sha256=header.entries_sha256,
            entries=entries,
            created_at=header.created_at,
            updated_at=header.updated_at,
        )

    def _resolve_frozen_entry(
        self, workspace_id: str, entry: SeriesCastEntryInput
    ) -> SeriesCastEntryRecord:
        from app.persistence.characters import (
            CharacterRepository,
            PackVersionNotFoundError,
        )

        character = self._session.get(Character, entry.character_id)
        if character is None or character.workspace_id != workspace_id:
            raise SeriesCastOwnershipError(
                f"role {entry.role_key!r}: character ownership mismatch"
            )
        try:
            record = CharacterRepository(self._session).get_pack_version(
                entry.pack_version_id, workspace_id
            )
        except PackVersionNotFoundError:
            raise SeriesCastOwnershipError(
                f"role {entry.role_key!r}: pack version ownership mismatch"
            ) from None
        if record.character_id != entry.character_id:
            raise SeriesCastOwnershipError(
                f"role {entry.role_key!r}: pack version character mismatch"
            )
        row = self._session.get(CharacterPackVersion, entry.pack_version_id)
        if row is None:  # pragma: no cover - defensive: record implies row
            raise SeriesCastNotFoundError(
                f"role {entry.role_key!r}: pack version disappeared mid-freeze"
            )
        if row.status != "published":
            raise SeriesCastConflictError(
                f"role {entry.role_key!r}: unpublished_pack (status {row.status!r} is not "
                "publishable for a series pin)"
            )
        self._assert_branch_complete(entry.role_key, row, record)
        return SeriesCastEntryRecord(
            role_key=entry.role_key,
            character_id=entry.character_id,
            pack_version_id=entry.pack_version_id,
            pack_contract_version=row.pack_contract_version,
            manifest_sha256=row.requirement_manifest_sha256,
            style_version=entry.style_version,
            references=_references_from_record(record),
        )

    def _assert_branch_complete(
        self,
        role_key: str,
        row: CharacterPackVersion,
        record: PackVersionRecord,
    ) -> None:
        from app.workflow.character_validator import (
            PackContractBranch,
            parse_reference_manifest,
            reference_pack_completeness,
        )

        branch = row.pack_contract_version
        if branch == PACK_CONTRACT_VERSION_LEGACY:
            attached = {asset.pose_slot for asset in record.assets}
            missing = [slot for slot in CORE_POSE_SLOTS if slot not in attached]
            if missing:
                raise SeriesCastConflictError(
                    f"role {role_key!r}: incomplete_pack (missing required pose "
                    f"slots: {', '.join(missing)})"
                )
            return
        if branch != PACK_CONTRACT_VERSION_REFERENCE:
            raise SeriesCastConflictError(
                f"role {role_key!r}: unknown pack contract branch {branch!r}"
            )
        manifest = parse_reference_manifest(
            PackContractBranch(
                pack_contract_version=branch,
                requirement_manifest_json=row.requirement_manifest_json,
                requirement_manifest_sha256=row.requirement_manifest_sha256,
            )
        )
        if manifest.errors:
            raise SeriesCastConflictError(
                f"role {role_key!r}: invalid requirement manifest: "
                + "; ".join(manifest.errors)
            )
        complete, missing_keys = reference_pack_completeness(record, manifest)
        if not complete:
            raise SeriesCastConflictError(
                f"role {role_key!r}: incomplete_pack (missing required reference "
                f"keys: {', '.join(missing_keys)})"
            )

    def _assert_frozen_entry_live(
        self, workspace_id: str, entry: SeriesCastEntryRecord
    ) -> None:
        from app.persistence.characters import (
            CharacterRepository,
            PackVersionNotFoundError,
        )

        try:
            record = CharacterRepository(self._session).get_pack_version(
                entry.pack_version_id, workspace_id
            )
        except PackVersionNotFoundError:
            raise SeriesCastStaleError(
                f"role {entry.role_key!r}: frozen pack version "
                f"{entry.pack_version_id!r} no longer exists in this workspace"
            ) from None
        row = self._session.get(CharacterPackVersion, entry.pack_version_id)
        if row is None:  # pragma: no cover - defensive: record implies row
            raise SeriesCastNotFoundError(
                f"role {entry.role_key!r}: pack version disappeared mid-apply"
            )
        if row.status != "published":
            raise SeriesCastStaleError(
                f"role {entry.role_key!r}: frozen pack version is no longer published "
                f"(status {row.status!r}); re-freeze a new snapshot instead"
            )
        if row.pack_contract_version != entry.pack_contract_version:
            raise SeriesCastStaleError(
                f"role {entry.role_key!r}: frozen contract "
                f"{entry.pack_contract_version!r} no longer matches the live pack "
                f"({row.pack_contract_version!r})"
            )
        if row.requirement_manifest_sha256 != entry.manifest_sha256:
            raise SeriesCastStaleError(
                f"role {entry.role_key!r}: frozen manifest sha256 "
                f"{entry.manifest_sha256!r} no longer matches the live pack "
                f"({row.requirement_manifest_sha256!r})"
            )
        if _references_bytes(_references_from_record(record)) != _references_bytes(
            entry.references
        ):
            raise SeriesCastStaleError(
                f"role {entry.role_key!r}: frozen asset references no longer match the "
                "live pack (library changed since freeze); re-freeze a new snapshot"
            )
