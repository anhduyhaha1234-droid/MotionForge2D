"""Durable ReskinConfig persistence (S09-T01).

Pins a durable Reskin parameter contract to a (project, object_role) pair and
an immutable CharacterPackVersion, reusing the S07 Project Cast policy as the
single compatibility authority.

Design rules (mirroring S07 project_cast + frozen sprint decisions):
- Workspace/project/role/character/pack ownership validated fail-closed on
  every write; all FKs RESTRICT.
- Pack must be ``published`` and complete (CORE_POSE_SLOTS) — evaluated via
  ``evaluate_compatibility`` from app.persistence.project_cast (NEVER a second
  copy of the policy). Fallback pinning is NOT offered on this surface: a
  reskin contract is only ever created against a fully compatible pack.
- params JSON validated fail-closed BEFORE any write:
    anchor            {x,y} each in [0,1]
    scale             > 0
    fit_mode          contain | cover | stretch
    clip_mode         asset_alpha | original_mask | intersection
    offset            {x,y} finite floats
    rotation_offset_deg  finite float
    opacity           in [0,1]
- Idempotent replay: UNIQUE(workspace_id, idempotency_key) WHERE NOT NULL;
  equivalent replay returns the existing row, materially different payload →
  conflict (409 at the API boundary), zero mutation.
- Natural key UNIQUE(project_id, object_role_id): one contract per role.
- Revision CAS: UPDATE ... WHERE revision=:expected; zero rows → stale → 409,
  zero mutation.
- Version isolation: publishing a new PackVersion never mutates an existing
  row's pack_version_id (S07 behaviour preserved).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session

from app.persistence.models import (
    Character,
    CharacterPackVersion,
    ObjectRole,
    Project,
    ProjectCastMapping,
    ReskinConfig,
    Workspace,
    utc_now,
)
from app.persistence.project_cast import evaluate_compatibility

__all__ = [
    "CLIP_MODES",
    "FIT_MODES",
    "ReskinConfigConflictError",
    "ReskinConfigNotFoundError",
    "ReskinConfigOwnershipError",
    "ReskinConfigParamsError",
    "ReskinConfigRecord",
    "ReskinConfigRepository",
    "canonical_params_json",
    "parse_params",
    "validate_params",
]

FIT_MODES = ("contain", "cover", "stretch")
CLIP_MODES = ("asset_alpha", "original_mask", "intersection")


class ReskinConfigError(Exception):
    """Base error for ReskinConfig domain."""


class ReskinConfigNotFoundError(ReskinConfigError):
    """Config not found in workspace."""


class ReskinConfigConflictError(ReskinConfigError):
    """Idempotency conflict, natural-key conflict or CAS stale revision."""


class ReskinConfigOwnershipError(ReskinConfigError):
    """Cross-workspace or project/role ownership mismatch."""


class ReskinConfigParamsError(ValueError):
    """params payload outside its closed domain (fail-closed validation)."""


@dataclass(frozen=True)
class ReskinConfigRecord:
    id: str
    workspace_id: str
    project_id: str
    object_role_id: str
    cast_mapping_id: str | None
    character_id: str
    pack_version_id: str
    params: dict[str, Any]
    idempotency_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


def _require_number(params: dict[str, Any], key: str) -> float:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReskinConfigParamsError(
            f"params.{key} must be a finite number, got {value!r}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise ReskinConfigParamsError(f"params.{key} must be finite, got {value!r}")
    return number


def validate_params(params: Any) -> dict[str, Any]:
    """Validate the reskin parameter contract; fail-closed.

    Returns the canonicalized dict (floats normalized). Raises
    ReskinConfigParamsError on ANY violation — no defaults are invented for
    missing keys and unknown extra keys are rejected.
    """
    if not isinstance(params, dict):
        raise ReskinConfigParamsError("params must be a JSON object")

    allowed_keys = {
        "anchor",
        "scale",
        "fit_mode",
        "clip_mode",
        "offset",
        "rotation_offset_deg",
        "opacity",
    }
    unknown = set(params.keys()) - allowed_keys
    if unknown:
        raise ReskinConfigParamsError(f"params has unknown keys: {sorted(unknown)}")
    missing = allowed_keys - set(params.keys())
    if missing:
        raise ReskinConfigParamsError(f"params is missing keys: {sorted(missing)}")

    anchor = params["anchor"]
    if not isinstance(anchor, dict) or set(anchor.keys()) != {"x", "y"}:
        raise ReskinConfigParamsError("params.anchor must be an object with exactly x,y")
    anchor_x: float | int = anchor["x"]
    anchor_y: float | int = anchor["y"]
    if isinstance(anchor_x, bool) or not isinstance(anchor_x, (int, float)):
        raise ReskinConfigParamsError("params.anchor.x must be a number")
    if isinstance(anchor_y, bool) or not isinstance(anchor_y, (int, float)):
        raise ReskinConfigParamsError("params.anchor.y must be a number")
    if not math.isfinite(float(anchor_x)) or not math.isfinite(float(anchor_y)):
        raise ReskinConfigParamsError("params.anchor.x/y must be finite")
    if not (0.0 <= float(anchor_x) <= 1.0):
        raise ReskinConfigParamsError(
            f"params.anchor.x out of [0,1]: {anchor_x!r}"
        )
    if not (0.0 <= float(anchor_y) <= 1.0):
        raise ReskinConfigParamsError(
            f"params.anchor.y out of [0,1]: {anchor_y!r}"
        )

    scale = _require_number(params, "scale")
    if scale <= 0.0:
        raise ReskinConfigParamsError(f"params.scale must be > 0, got {scale!r}")

    fit_mode = params["fit_mode"]
    if fit_mode not in FIT_MODES:
        raise ReskinConfigParamsError(
            f"params.fit_mode must be one of {FIT_MODES}, got {fit_mode!r}"
        )

    clip_mode = params["clip_mode"]
    if clip_mode not in CLIP_MODES:
        raise ReskinConfigParamsError(
            f"params.clip_mode must be one of {CLIP_MODES}, got {clip_mode!r}"
        )

    offset = params["offset"]
    if not isinstance(offset, dict) or set(offset.keys()) != {"x", "y"}:
        raise ReskinConfigParamsError("params.offset must be an object with exactly x,y")
    offset_x = _require_number(offset, "x")
    offset_y = _require_number(offset, "y")
    del offset_x, offset_y  # finiteness already enforced by _require_number

    rotation = _require_number(params, "rotation_offset_deg")

    opacity = _require_number(params, "opacity")
    if not (0.0 <= opacity <= 1.0):
        raise ReskinConfigParamsError(f"params.opacity out of [0,1]: {opacity!r}")

    return {
        "anchor": {"x": float(anchor_x), "y": float(anchor_y)},
        "scale": scale,
        "fit_mode": fit_mode,
        "clip_mode": clip_mode,
        "offset": {"x": float(offset["x"]), "y": float(offset["y"])},
        "rotation_offset_deg": float(rotation),
        "opacity": opacity,
    }


def parse_params(raw: str) -> dict[str, Any]:
    """Parse stored params_json; corrupt rows fail loudly (never silently defaulted)."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as err:
        raise ReskinConfigParamsError(f"stored params_json is not valid JSON: {err}") from err
    return validate_params(value)


def canonical_params_json(params: dict[str, Any]) -> str:
    return json.dumps(validate_params(params), sort_keys=True, separators=(",", ":"))


def _map_row(row: ReskinConfig) -> ReskinConfigRecord:
    return ReskinConfigRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        object_role_id=row.object_role_id,
        cast_mapping_id=row.cast_mapping_id,
        character_id=row.character_id,
        pack_version_id=row.pack_version_id,
        params=parse_params(row.params_json),
        idempotency_key=row.idempotency_key,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ReskinConfigRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _assert_equivalent_request(
        existing: ReskinConfig,
        *,
        project_id: str,
        object_role_id: str,
        character_id: str,
        pack_version_id: str,
        params_json: str,
    ) -> None:
        if (
            existing.project_id != project_id
            or existing.object_role_id != object_role_id
            or existing.character_id != character_id
            or existing.pack_version_id != pack_version_id
            or existing.params_json != params_json
        ):
            raise ReskinConfigConflictError(
                f"idempotency key {existing.idempotency_key!r} is already bound to "
                "a different reskin config payload"
            )

    def get_config(self, config_id: str, workspace_id: str) -> ReskinConfigRecord:
        row = self._session.scalar(
            select(ReskinConfig).where(
                ReskinConfig.id == config_id,
                ReskinConfig.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise ReskinNotFoundError(config_id)
        return _map_row(row)

    def list_configs(
        self,
        workspace_id: str,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ReskinConfigRecord], int]:
        from sqlalchemy import func

        filters = [ReskinConfig.workspace_id == workspace_id]
        if project_id is not None:
            proj = self._session.get(Project, project_id)
            if proj is None or proj.workspace_id != workspace_id:
                raise ReskinConfigNotFoundError(f"Project {project_id!r} not found")
            filters.append(ReskinConfig.project_id == project_id)
        total = int(
            self._session.scalar(select(func.count(ReskinConfig.id)).where(*filters)) or 0
        )
        rows = self._session.scalars(
            select(ReskinConfig)
            .where(*filters)
            .order_by(ReskinConfig.created_at.desc(), ReskinConfig.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return [_map_row(r) for r in rows], total

    def create_config(
        self,
        workspace_id: str,
        project_id: str,
        object_role_id: str,
        character_id: str,
        pack_version_id: str,
        params: dict[str, Any],
        idempotency_key: str | None = None,
        cast_mapping_id: str | None = None,
    ) -> tuple[ReskinConfigRecord, bool]:
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

        # Fail-closed param validation BEFORE any DB work (zero mutation on error).
        canonical_json = canonical_params_json(params)

        self._ensure_workspace(workspace_id)

        # Idempotent replay first (workspace-scoped).
        if idempotency_key:
            existing = self._session.scalar(
                select(ReskinConfig).where(
                    ReskinConfig.workspace_id == workspace_id,
                    ReskinConfig.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                self._assert_equivalent_request(
                    existing,
                    project_id=project_id,
                    object_role_id=object_role_id,
                    character_id=character_id,
                    pack_version_id=pack_version_id,
                    params_json=canonical_json,
                )
                return _map_row(existing), False

        # Natural key pre-check (workspace-scoped, no cross-workspace leak).
        natural_existing = self._session.scalar(
            select(ReskinConfig).where(
                ReskinConfig.workspace_id == workspace_id,
                ReskinConfig.project_id == project_id,
                ReskinConfig.object_role_id == object_role_id,
            )
        )
        if natural_existing is not None:
            if idempotency_key and natural_existing.idempotency_key == idempotency_key:
                self._assert_equivalent_request(
                    natural_existing,
                    project_id=project_id,
                    object_role_id=object_role_id,
                    character_id=character_id,
                    pack_version_id=pack_version_id,
                    params_json=canonical_json,
                )
                return _map_row(natural_existing), False
            raise ReskinConfigConflictError(
                f"reskin config for project {project_id!r} and role {object_role_id!r} "
                "already exists"
            )

        # Ownership (fail-closed 404 semantics, mirroring S07 _assert_ownership).
        self._assert_ownership(workspace_id, project_id, object_role_id, character_id, pack_version_id)  # noqa: E501

        if cast_mapping_id is not None:
            mapping = self._session.scalar(
                select(ProjectCastMapping).where(
                    ProjectCastMapping.id == cast_mapping_id,
                    ProjectCastMapping.workspace_id == workspace_id,
                )
            )
            if mapping is None:
                raise ReskinConfigOwnershipError("cast mapping ownership mismatch")
            if mapping.project_id != project_id or mapping.object_role_id != object_role_id:  # noqa: E501
                raise ReskinConfigOwnershipError("cast mapping does not match project/role")

        # Authoritative compatibility — REUSED S07 policy, never re-implemented.
        result = evaluate_compatibility(
            self._session,
            workspace_id,
            project_id,
            object_role_id,
            character_id,
            pack_version_id,
        )
        if not result.compatible:
            # S09 surface is STRICTER than S07 pinning: a reskin contract is
            # only ever created against a FULLY compatible pack — the S07
            # fallback matrix (incomplete_pack/generation_mismatch with
            # acknowledgement) must NOT let a degraded pin through here
            # (fail-closed, zero mutation).
            reason_str = ",".join(result.reasons) if result.reasons else "incompatible"
            if "workspace_mismatch" in result.reasons:
                raise ReskinConfigOwnershipError(f"compatibility blocked: {reason_str}")
            raise ReskinConfigConflictError(f"compatibility blocked: {reason_str}")

        row = ReskinConfig(
            workspace_id=workspace_id,
            project_id=project_id,
            object_role_id=object_role_id,
            cast_mapping_id=cast_mapping_id,
            character_id=character_id,
            pack_version_id=pack_version_id,
            params_json=canonical_json,
            idempotency_key=idempotency_key,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            if idempotency_key:
                existing = self._session.scalar(
                    select(ReskinConfig).where(
                        ReskinConfig.workspace_id == workspace_id,
                        ReskinConfig.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    self._assert_equivalent_request(
                        existing,
                        project_id=project_id,
                        object_role_id=object_role_id,
                        character_id=character_id,
                        pack_version_id=pack_version_id,
                        params_json=canonical_json,
                    )
                    return _map_row(existing), False
            natural = self._session.scalar(
                select(ReskinConfig).where(
                    ReskinConfig.workspace_id == workspace_id,
                    ReskinConfig.project_id == project_id,
                    ReskinConfig.object_role_id == object_role_id,
                )
            )
            if natural is not None:
                raise ReskinConfigConflictError(
                    f"reskin config for project {project_id!r} and role "
                    f"{object_role_id!r} already exists (concurrent)"
                ) from None
            raise
        return _map_row(row), True

    def update_config(
        self,
        config_id: str,
        workspace_id: str,
        expected_revision: int,
        params: dict[str, Any] | None = None,
        pack_version_id: str | None = None,
        character_id: str | None = None,
    ) -> ReskinConfigRecord:
        if expected_revision < 1:
            raise ValueError("revision must be >= 1")
        current = self._session.scalar(
            select(ReskinConfig).where(
                ReskinConfig.id == config_id,
                ReskinConfig.workspace_id == workspace_id,
            )
        )
        if current is None:
            raise ReskinConfigNotFoundError(f"ReskinConfig {config_id!r} not found")
        if current.revision != expected_revision:
            raise ReskinConfigConflictError(
                f"stale revision {expected_revision}; current revision is {current.revision}"  # noqa: E501
            )
        new_character_id = character_id if character_id is not None else current.character_id
        new_pack_version_id = (
            pack_version_id if pack_version_id is not None else current.pack_version_id
        )
        new_params_json = (
            canonical_params_json(params) if params is not None else current.params_json
        )
        if (
            new_character_id == current.character_id
            and new_pack_version_id == current.pack_version_id
            and new_params_json == current.params_json
        ):
            return _map_row(current)

        # Repin / reparametrize must still point at a compatible published pack
        # (same reused S07 authority as create; no fallback on this surface).
        result = evaluate_compatibility(
            self._session,
            workspace_id,
            current.project_id,
            current.object_role_id,
            new_character_id,
            new_pack_version_id,
            expected_revision=expected_revision,
            mapping_id=None,
        )
        if not result.compatible:
            # Same strictness as create: NO S07 fallback on this surface.
            reason_str = ",".join(result.reasons) if result.reasons else "incompatible"
            if "workspace_mismatch" in result.reasons:
                raise ReskinConfigOwnershipError(f"compatibility blocked: {reason_str}")
            raise ReskinConfigConflictError(f"compatibility blocked: {reason_str}")

        values: dict[str, object] = {
            "revision": expected_revision + 1,
            "updated_at": utc_now(),
            "character_id": new_character_id,
            "pack_version_id": new_pack_version_id,
            "params_json": new_params_json,
        }
        stmt = (
            update(ReskinConfig)
            .where(
                ReskinConfig.id == config_id,
                ReskinConfig.workspace_id == workspace_id,
                ReskinConfig.revision == expected_revision,
            )
            .values(**values)
            .returning(ReskinConfig)
        )
        try:
            row = self._session.execute(stmt).scalar_one()
        except NoResultFound:
            latest = self._session.scalar(
                select(ReskinConfig).where(
                    ReskinConfig.id == config_id,
                    ReskinConfig.workspace_id == workspace_id,
                )
            )
            cur_rev = latest.revision if latest is not None else None
            raise ReskinConfigConflictError(
                f"stale revision {expected_revision}; current revision is {cur_rev}"
            ) from None
        return _map_row(row)

    # ── internals ────────────────────────────────────────────────────────

    def _ensure_workspace(self, workspace_id: str) -> None:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        self._session.execute(
            sqlite_insert(Workspace)
            .values(id=workspace_id, name=workspace_id)
            .on_conflict_do_nothing(index_elements=[Workspace.id])
        )

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
            raise ReskinConfigOwnershipError("project ownership mismatch")
        role = self._session.get(ObjectRole, object_role_id)
        if role is None or role.workspace_id != workspace_id:
            raise ReskinConfigOwnershipError("object role ownership mismatch")
        if role.project_id != project_id:
            raise ReskinConfigOwnershipError("object role project mismatch")
        character = self._session.get(Character, character_id)
        if character is None or character.workspace_id != workspace_id:
            raise ReskinConfigOwnershipError("character ownership mismatch")
        pack = self._session.get(CharacterPackVersion, pack_version_id)
        if pack is None or pack.workspace_id != workspace_id:
            raise ReskinConfigOwnershipError("pack version ownership mismatch")
        if pack.character_id != character_id:
            raise ReskinConfigOwnershipError("pack version character mismatch")


# Backwards-compatible alias used by tests that reference the not-found error
# through the base module namespace.
ReskinNotFoundError = ReskinConfigNotFoundError
