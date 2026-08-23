"""Durable StructuralLockManifest + SegmentRenderRoute persistence (S09-T00-I01).

Implements TARGET_PROFILE §4 P0-1 (versioned StructuralLockManifest per Video
Item), §4 P0-4 (contact anchors in normalized x/y per occurrence segment) and
§4 P0-7 (persisted renderer route + provenance per occurrence segment from the
EXACT enum {pose_swap, sprite_affine, mesh_warp, part_rig,
controlled_redraw}), plus the pin fields on ReskinConfig/ApplyCheckpoint.

Design rules (mirroring S09-T01 reskin_config + frozen sprint decisions):
- Workspace/project/video/segment ownership validated fail-closed on every
  write; every query is scoped by workspace_id (project optional filter);
  cross-workspace reads raise NotFound — isolation is binary.
- manifest JSON validated fail-closed BEFORE any write:
    frame_count        int >= 0
    timebase           {fps: number > 0, time_base: str, start_time_ms: int >= 0}
    shot_order         list[str] of unique non-empty shot ids
    fingerprints       {z_order: str(1..128), contacts: str(1..128)} (sha256 hex)
    segments           optional list of {occurrence_segment_id, route,
                       anchor {x,y} ∈ [0,1], start_frame >= 0, end_frame >=
                       start_frame, provenance: finite JSON object}
    policy_version     str(1..64)
    unknown keys rejected; NaN/Inf rejected everywhere (finite walk).
- Renderer route values come ONLY from models.RENDERER_ROUTES (single
  authority); provenance must be a JSON object when present.
- Idempotent replay: UNIQUE(workspace_id, idempotency_key) WHERE NOT NULL;
  equivalent replay returns the existing row, materially different payload →
  conflict.  Natural-key versioning: creating a manifest for a natural key
  whose latest row is draft/active supersedes it (status → superseded,
  superseded_by_id → successor, version increments).  Superseded history is
  never rewritten.
- Revision CAS: UPDATE ... WHERE revision=:expected; zero rows → stale →
  conflict, zero mutation.
- Pin operations: set_reskin_lock_pin (CAS-bumps reskin_config.revision) and
  set_checkpoint_lock_pin (apply_checkpoint rows are immutable — revision
  stays 1, only the two additive pin columns are written once).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.persistence.models import (
    RENDERER_ROUTES,
    ApplyCheckpoint,
    OccurrenceSegment,
    Project,
    ReskinConfig,
    StructuralLockManifest,
    VideoItem,
    Workspace,
    utc_now,
)

__all__ = [
    "LOCK_POLICY_PATTERN",
    "MANIFEST_HASH_LENGTH",
    "StructuralLockConflictError",
    "StructuralLockHashMismatchError",
    "StructuralLockNotFoundError",
    "StructuralLockOwnershipError",
    "StructuralLockParamsError",
    "StructuralLockRepository",
    "canonical_manifest_json",
    "manifest_hash",
    "parse_manifest",
    "validate_manifest",
]

MANIFEST_HASH_LENGTH = 64
_LOCK_POLICY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
#: Public pattern for bounded policy-version strings (mirrors migration CHECK).
LOCK_POLICY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StructuralLockError(Exception):
    """Base error for the structural-lock domain."""


class StructuralLockNotFoundError(StructuralLockError):
    """Manifest/route/pin target not found inside the given workspace."""


class StructuralLockConflictError(StructuralLockError):
    """Idempotency conflict, natural-key conflict or CAS stale revision."""


class StructuralLockOwnershipError(StructuralLockError):
    """Cross-workspace or project/video/segment ownership mismatch."""


class StructuralLockParamsError(ValueError):
    """Payload outside its closed domain (fail-closed validation)."""


class StructuralLockHashMismatchError(StructuralLockParamsError):
    """Caller-supplied manifest_hash does not match the canonical payload."""


# ── Fail-closed validation helpers ────────────────────────────────────────────


def _reject_non_finite(value: Any, path: str) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise StructuralLockParamsError(f"{path} must be finite, got {value!r}")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise StructuralLockParamsError(f"{path} keys must be strings")
            _reject_non_finite(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_non_finite(item, f"{path}[{index}]")


def _require_int(payload: dict[str, Any], key: str, minimum: int = 0) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StructuralLockParamsError(f"{key} must be an integer >= {minimum}")
    if value < minimum:
        raise StructuralLockParamsError(f"{key} must be >= {minimum}, got {value!r}")
    return value


def _validate_anchor_xy(anchor: Any, path: str) -> tuple[float, float]:
    if not isinstance(anchor, dict) or set(anchor.keys()) != {"x", "y"}:
        raise StructuralLockParamsError(
            f"{path} must be an object with exactly x,y"
        )
    coords: list[float] = []
    for axis in ("x", "y"):
        raw = anchor[axis]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise StructuralLockParamsError(f"{path}.{axis} must be a number")
        number = float(raw)
        if not math.isfinite(number):
            raise StructuralLockParamsError(f"{path}.{axis} must be finite")
        if not (0.0 <= number <= 1.0):
            raise StructuralLockParamsError(
                f"{path}.{axis} out of [0,1]: {raw!r}"
            )
        coords.append(number)
    return coords[0], coords[1]


def validate_manifest(manifest: Any) -> dict[str, Any]:
    """Validate the StructuralLockManifest payload; fail-closed.

    Returns the canonicalized dict (floats normalized, unknown keys rejected).
    Raises StructuralLockParamsError on ANY violation — no defaults are
    invented for missing required keys and NaN/Infinity are rejected
    everywhere (SQLite would bind them as NULL, silently corrupting CHECKs).
    """
    if not isinstance(manifest, dict):
        raise StructuralLockParamsError("manifest must be a JSON object")

    allowed_keys = {
        "frame_count",
        "timebase",
        "shot_order",
        "fingerprints",
        "segments",
        "policy_version",
    }
    unknown = set(manifest.keys()) - allowed_keys
    if unknown:
        raise StructuralLockParamsError(f"manifest has unknown keys: {sorted(unknown)}")
    missing = allowed_keys - set(manifest.keys())
    if missing:
        raise StructuralLockParamsError(f"manifest is missing keys: {sorted(missing)}")

    frame_count = _require_int(manifest, "frame_count")

    timebase = manifest["timebase"]
    if not isinstance(timebase, dict):
        raise StructuralLockParamsError("timebase must be a JSON object")
    tb_allowed = {"fps", "time_base", "start_time_ms"}
    tb_unknown = set(timebase.keys()) - tb_allowed
    if tb_unknown:
        raise StructuralLockParamsError(
            f"timebase has unknown keys: {sorted(tb_unknown)}"
        )
    tb_missing = tb_allowed - set(timebase.keys())
    if tb_missing:
        raise StructuralLockParamsError(
            f"timebase is missing keys: {sorted(tb_missing)}"
        )
    fps = timebase["fps"]
    if isinstance(fps, bool) or not isinstance(fps, (int, float)):
        raise StructuralLockParamsError("timebase.fps must be a number > 0")
    fps_number = float(fps)
    if not math.isfinite(fps_number) or fps_number <= 0.0:
        raise StructuralLockParamsError(f"timebase.fps must be > 0, got {fps!r}")
    time_base = timebase["time_base"]
    if not isinstance(time_base, str) or not time_base.strip():
        raise StructuralLockParamsError("timebase.time_base must be a non-empty string")
    if len(time_base) > 64:
        raise StructuralLockParamsError("timebase.time_base too long (max 64)")
    start_time_ms = _require_int(timebase, "start_time_ms")

    shot_order = manifest["shot_order"]
    if not isinstance(shot_order, list) or any(
        not isinstance(s, str) or not s.strip() for s in shot_order
    ):
        raise StructuralLockParamsError(
            "shot_order must be a list of non-empty strings"
        )
    if len(set(shot_order)) != len(shot_order):
        raise StructuralLockParamsError("shot_order must contain unique shot ids")

    fingerprints = manifest["fingerprints"]
    if not isinstance(fingerprints, dict):
        raise StructuralLockParamsError("fingerprints must be a JSON object")
    fp_allowed = {"z_order", "contacts"}
    if set(fingerprints.keys()) != fp_allowed:
        raise StructuralLockParamsError(
            f"fingerprints must have exactly keys {sorted(fp_allowed)}"
        )
    for name, value in fingerprints.items():
        if (
            not isinstance(value, str)
            or not _SHA256_RE.match(value)
        ):
            raise StructuralLockParamsError(
                f"fingerprints.{name} must be a lowercase sha256 hex string"
            )

    policy_version = manifest["policy_version"]
    if not isinstance(policy_version, str) or not _LOCK_POLICY_RE.match(policy_version):
        raise StructuralLockParamsError(
            "policy_version must match ^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
        )

    raw_segments = manifest["segments"]
    if raw_segments is None:
        segments: list[dict[str, Any]] = []
    else:
        if not isinstance(raw_segments, list):
            raise StructuralLockParamsError("segments must be a list or null")
        segments = []
        for index, seg in enumerate(raw_segments):
            path = f"segments[{index}]"
            if not isinstance(seg, dict):
                raise StructuralLockParamsError(f"{path} must be a JSON object")
            seg_allowed = {
                "occurrence_segment_id",
                "route",
                "anchor",
                "start_frame",
                "end_frame",
                "provenance",
            }
            seg_unknown = set(seg.keys()) - seg_allowed
            if seg_unknown:
                raise StructuralLockParamsError(
                    f"{path} has unknown keys: {sorted(seg_unknown)}"
                )
            seg_missing = seg_allowed - set(seg.keys())
            if seg_missing:
                raise StructuralLockParamsError(
                    f"{path} is missing keys: {sorted(seg_missing)}"
                )
            seg_id = seg["occurrence_segment_id"]
            if not isinstance(seg_id, str) or not seg_id.strip():
                raise StructuralLockParamsError(
                    f"{path}.occurrence_segment_id must be a non-empty string"
                )
            route = seg["route"]
            if route not in RENDERER_ROUTES:
                raise StructuralLockParamsError(
                    f"{path}.route must be one of {RENDERER_ROUTES}, got {route!r}"
                )
            anchor_x, anchor_y = _validate_anchor_xy(seg["anchor"], f"{path}.anchor")
            start_frame = _require_int(seg, "start_frame")
            end_frame = _require_int(seg, "end_frame")
            if end_frame < start_frame:
                raise StructuralLockParamsError(
                    f"{path}.end_frame must be >= start_frame"
                )
            provenance = seg["provenance"]
            if not isinstance(provenance, dict):
                raise StructuralLockParamsError(
                    f"{path}.provenance must be a JSON object"
                )
            _reject_non_finite(provenance, f"{path}.provenance")
            segments.append(
                {
                    "occurrence_segment_id": seg_id,
                    "route": route,
                    "anchor": {"x": anchor_x, "y": anchor_y},
                    "start_frame": start_frame,
                    "end_frame": end_frame,
                    "provenance": provenance,
                }
            )
        seg_ids = [s["occurrence_segment_id"] for s in segments]
        if len(set(seg_ids)) != len(seg_ids):
            raise StructuralLockParamsError(
                "segments must reference each occurrence segment at most once"
            )

    return {
        "frame_count": frame_count,
        "timebase": {
            "fps": fps_number,
            "time_base": time_base,
            "start_time_ms": start_time_ms,
        },
        "shot_order": list(shot_order),
        "fingerprints": dict(fingerprints),
        "segments": segments,
        "policy_version": policy_version,
    }


def parse_manifest(raw: str) -> dict[str, Any]:
    """Parse stored manifest_json; corrupt rows fail loudly."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as err:
        raise StructuralLockParamsError(
            f"stored manifest_json is not valid JSON: {err}"
        ) from err
    return validate_manifest(value)


def canonical_manifest_json(manifest: dict[str, Any]) -> str:
    return json.dumps(validate_manifest(manifest), sort_keys=True, separators=(",", ":"))


def manifest_hash(canonical_json: str) -> str:
    """Deterministic sha256 over the CANONICAL manifest JSON."""
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    if not _SHA256_RE.match(digest):  # pragma: no cover - defensive
        raise StructuralLockParamsError("hash computation produced invalid digest")
    return digest


def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class LockManifestRecord:
    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    source_generation: str
    version: int
    status: str
    policy_version: str
    manifest_hash_hex: str
    manifest: dict[str, Any]
    idempotency_key: str | None
    superseded_by_id: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RenderRouteRecord:
    id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    occurrence_segment_id: str
    structural_lock_manifest_id: str | None
    route: str
    anchor_x: float
    anchor_y: float
    start_frame: int
    end_frame: int
    confidence: float
    confidence_source: str
    provenance: dict[str, Any] | None
    reasons: list[str]
    idempotency_key: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


def _map_manifest(row: StructuralLockManifest) -> LockManifestRecord:
    return LockManifestRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        source_generation=row.source_generation,
        version=row.version,
        status=row.status,
        policy_version=row.policy_version,
        manifest_hash_hex=row.manifest_hash,
        manifest=parse_manifest(row.manifest_json),
        idempotency_key=row.idempotency_key,
        superseded_by_id=row.superseded_by_id,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _parse_provenance(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as err:
        raise StructuralLockParamsError(
            f"stored provenance_json is not valid JSON: {err}"
        ) from err
    if not isinstance(value, dict):
        raise StructuralLockParamsError("stored provenance_json must be an object")
    _reject_non_finite(value, "provenance")
    return value


def _map_route(row: SegmentRenderRouteRow) -> RenderRouteRecord:
    reasons_raw = row.reasons_json or "[]"
    try:
        reasons = json.loads(reasons_raw)
    except json.JSONDecodeError as err:
        raise StructuralLockParamsError(
            f"stored reasons_json is not valid JSON: {err}"
        ) from err
    if not isinstance(reasons, list):
        raise StructuralLockParamsError("stored reasons_json must be a list")
    return RenderRouteRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        video_item_id=row.video_item_id,
        occurrence_segment_id=row.occurrence_segment_id,
        structural_lock_manifest_id=row.structural_lock_manifest_id,
        route=row.route,
        anchor_x=row.anchor_x,
        anchor_y=row.anchor_y,
        start_frame=row.start_frame,
        end_frame=row.end_frame,
        confidence=row.confidence,
        confidence_source=row.confidence_source,
        provenance=_parse_provenance(row.provenance_json),
        reasons=[str(r) for r in reasons],
        idempotency_key=row.idempotency_key,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class StructuralLockRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Manifest surface ────────────────────────────────────────────────

    @staticmethod
    def _assert_equivalent_manifest_request(
        existing: StructuralLockManifest,
        *,
        project_id: str,
        video_item_id: str,
        source_generation: str,
        policy_version: str,
        manifest_json: str,
    ) -> None:
        if (
            existing.project_id != project_id
            or existing.video_item_id != video_item_id
            or existing.source_generation != source_generation
            or existing.policy_version != policy_version
            or existing.manifest_json != manifest_json
        ):
            raise StructuralLockConflictError(
                f"idempotency key {existing.idempotency_key!r} is already bound "
                "to a different structural lock payload"
            )

    def create_manifest(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        source_generation: str,
        manifest: dict[str, Any],
        expected_hash: str | None = None,
        idempotency_key: str | None = None,
        activate: bool = True,
    ) -> tuple[LockManifestRecord, bool]:
        """Create the next manifest version for (video, generation).

        Equivalent idempotent replay returns ``(existing, False)``; a new
        natural-key row supersedes the previous draft/active version inside
        the SAME flush/transaction (history archived, never rewritten).
        """
        if not project_id.strip():
            raise ValueError("project_id must not be empty")
        if not video_item_id.strip():
            raise ValueError("video_item_id must not be empty")
        if (
            not isinstance(source_generation, str)
            or not (1 <= len(source_generation) <= 64)
        ):
            raise ValueError(
                "source_generation must be a 1..64 char string"
            )
        if idempotency_key is not None:
            if len(idempotency_key) > 255:
                raise ValueError("idempotency_key too long")
            if not idempotency_key.strip():
                raise ValueError("idempotency_key must not be empty if provided")

        canonical_json = canonical_manifest_json(manifest)
        computed_hash = manifest_hash(canonical_json)
        if expected_hash is not None:
            if (
                not isinstance(expected_hash, str)
                or not _SHA256_RE.match(expected_hash)
            ):
                raise StructuralLockParamsError(
                    "expected_hash must be a lowercase sha256 hex string"
                )
            if expected_hash != computed_hash:
                raise StructuralLockHashMismatchError(
                    "expected manifest_hash mismatch: caller hash does not "
                    "match canonical payload"
                )

        self._ensure_workspace(workspace_id)
        self._assert_ownership(workspace_id, project_id, video_item_id)

        if idempotency_key:
            existing = self._session.scalar(
                select(StructuralLockManifest).where(
                    StructuralLockManifest.workspace_id == workspace_id,
                    StructuralLockManifest.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                self._assert_equivalent_manifest_request(
                    existing,
                    project_id=project_id,
                    video_item_id=video_item_id,
                    source_generation=source_generation,
                    policy_version=manifest["policy_version"],
                    manifest_json=canonical_json,
                )
                return _map_manifest(existing), False

        predecessor = self._latest_row(workspace_id, project_id, video_item_id, source_generation)
        next_version = (predecessor.version + 1) if predecessor is not None else 1

        row = StructuralLockManifest(
            # Client-side id so the successor link can reference it before
            # any flush (the column default only fires at INSERT time; using
            # row.id pre-flush would otherwise assign NULL).
            id=_new_id(),
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            source_generation=source_generation,
            version=next_version,
            status="active" if activate else "draft",
            policy_version=manifest["policy_version"],
            manifest_hash=computed_hash,
            manifest_json=canonical_json,
            idempotency_key=idempotency_key,
            superseded_by_id=None,
        )
        try:
            with self._session.begin_nested():
                # FK-safe + partial-unique-safe ordering: (1) archive the
                # predecessor FIRST (status → superseded clears the partial
                # unique active-slot slot), flush; (2) INSERT the successor
                # (its id is client-side so the link can be assigned before
                # this flush); (3) point the archived predecessor at its
                # successor and flush.  A single combined flush would emit
                # UPDATE before INSERT (self-FK violation) and the INSERT
                # before the archive would trip the partial unique index.
                if predecessor is not None and predecessor.status in (
                    "draft",
                    "active",
                ):
                    predecessor.status = "superseded"
                    self._session.flush()
                self._session.add(row)
                self._session.flush()
                if predecessor is not None:
                    predecessor.superseded_by_id = row.id
                    self._session.flush()
        except IntegrityError as err:
            self._session.rollback()
            if idempotency_key:
                existing = self._session.scalar(
                    select(StructuralLockManifest).where(
                        StructuralLockManifest.workspace_id == workspace_id,
                        StructuralLockManifest.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    self._assert_equivalent_manifest_request(
                        existing,
                        project_id=project_id,
                        video_item_id=video_item_id,
                        source_generation=source_generation,
                        policy_version=manifest["policy_version"],
                        manifest_json=canonical_json,
                    )
                    return _map_manifest(existing), False
            raise StructuralLockConflictError(
                "structural lock manifest conflicts with an existing row "
                f"(natural key/version race): {err.orig}"
            ) from err
        return _map_manifest(row), True

    def get_manifest(self, manifest_id: str, workspace_id: str) -> LockManifestRecord:
        row = self._session.scalar(
            select(StructuralLockManifest).where(
                StructuralLockManifest.id == manifest_id,
                StructuralLockManifest.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise StructuralLockNotFoundError(
                f"StructuralLockManifest {manifest_id!r} not found in workspace"
            )
        return _map_manifest(row)

    def get_current_manifest(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        source_generation: str,
    ) -> LockManifestRecord:
        row = self._session.scalar(
            select(StructuralLockManifest)
            .where(
                StructuralLockManifest.workspace_id == workspace_id,
                StructuralLockManifest.project_id == project_id,
                StructuralLockManifest.video_item_id == video_item_id,
                StructuralLockManifest.source_generation == source_generation,
                StructuralLockManifest.status.in_(("draft", "active")),
            )
            .order_by(StructuralLockManifest.version.desc())
            .limit(1)
        )
        if row is None:
            raise StructuralLockNotFoundError(
                "no current structural lock manifest for the given "
                "video/generation in this workspace"
            )
        return _map_manifest(row)

    def list_manifests(
        self,
        workspace_id: str,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LockManifestRecord], int]:
        filters = [StructuralLockManifest.workspace_id == workspace_id]
        if project_id is not None:
            filters.append(StructuralLockManifest.project_id == project_id)
        total = int(
            self._session.scalar(
                select(func.count(StructuralLockManifest.id)).where(*filters)
            )
            or 0
        )
        rows = self._session.scalars(
            select(StructuralLockManifest)
            .where(*filters)
            .order_by(
                StructuralLockManifest.created_at.desc(),
                StructuralLockManifest.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return [_map_manifest(r) for r in rows], total

    def void_manifest(
        self,
        manifest_id: str,
        workspace_id: str,
        expected_revision: int,
    ) -> LockManifestRecord:
        """Void a DRAFT lock (no active/superseded row may ever be voided)."""
        if expected_revision < 1:
            raise ValueError("revision must be >= 1")
        stmt = (
            update(StructuralLockManifest)
            .where(
                StructuralLockManifest.id == manifest_id,
                StructuralLockManifest.workspace_id == workspace_id,
                StructuralLockManifest.revision == expected_revision,
                StructuralLockManifest.status == "draft",
            )
            .values(status="voided", updated_at=utc_now(), revision=expected_revision + 1)
            .returning(StructuralLockManifest)
        )
        try:
            row = self._session.execute(stmt).scalar_one()
        except Exception as err:  # NoResultFound covers both miss + stale CAS
            current = self._session.scalar(
                select(StructuralLockManifest).where(
                    StructuralLockManifest.id == manifest_id,
                    StructuralLockManifest.workspace_id == workspace_id,
                )
            )
            if current is None:
                raise StructuralLockNotFoundError(
                    f"StructuralLockManifest {manifest_id!r} not found"
                ) from err
            if current.status != "draft":
                raise StructuralLockConflictError(
                    f"only draft manifests can be voided; status={current.status!r}"
                ) from err
            raise StructuralLockConflictError(
                f"stale revision {expected_revision}; current is {current.revision}"
            ) from err
        return _map_manifest(row)

    # ── Renderer-route surface ──────────────────────────────────────────

    def record_render_route(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        occurrence_segment_id: str,
        route: str,
        anchor_x: float,
        anchor_y: float,
        start_frame: int,
        end_frame: int,
        provenance: dict[str, Any] | None = None,
        reasons: list[str] | None = None,
        algorithm: str | None = None,
        algorithm_version: str | None = None,
        confidence: float = 1.0,
        confidence_source: str = "model",
        structural_lock_manifest_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[RenderRouteRecord, bool]:
        """Persist one renderer-route decision (+ contact anchor) per segment.

        Route MUST be one of the exact five enum values; anchors are checked
        into [0,1]; ownership of segment/video/workspace is fail-closed.
        """
        if route not in RENDERER_ROUTES:
            raise StructuralLockParamsError(
                f"route must be one of {RENDERER_ROUTES}, got {route!r}"
            )
        for name, value in (("anchor_x", anchor_x), ("anchor_y", anchor_y)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise StructuralLockParamsError(f"{name} must be a number")
            number = float(value)
            if not math.isfinite(number):
                raise StructuralLockParamsError(f"{name} must be finite")
            if not (0.0 <= number <= 1.0):
                raise StructuralLockParamsError(f"{name} out of [0,1]: {value!r}")
        anchor_x_f, anchor_y_f = float(anchor_x), float(anchor_y)
        if isinstance(start_frame, bool) or not isinstance(start_frame, int) or start_frame < 0:
            raise StructuralLockParamsError("start_frame must be an integer >= 0")
        if isinstance(end_frame, bool) or not isinstance(end_frame, int) or end_frame < start_frame:
            raise StructuralLockParamsError("end_frame must be an integer >= start_frame")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise StructuralLockParamsError("confidence must be a number")
        confidence_f = float(confidence)
        if not math.isfinite(confidence_f) or not (0.0 <= confidence_f <= 1.0):
            raise StructuralLockParamsError("confidence must be within [0,1]")
        if confidence_source not in ("model", "detector", "user", "manual", "derived"):
            raise StructuralLockParamsError(
                f"invalid confidence_source {confidence_source!r}"
            )
        if provenance is not None:
            if not isinstance(provenance, dict):
                raise StructuralLockParamsError("provenance must be a JSON object")
            _reject_non_finite(provenance, "provenance")
        if reasons is not None and not isinstance(reasons, list):
            raise StructuralLockParamsError("reasons must be a list of strings")
        if idempotency_key is not None:
            if len(idempotency_key) > 255:
                raise ValueError("idempotency_key too long")
            if not idempotency_key.strip():
                raise ValueError("idempotency_key must not be empty if provided")

        self._ensure_workspace(workspace_id)
        self._assert_ownership(workspace_id, project_id, video_item_id)
        seg = self._session.get(OccurrenceSegment, occurrence_segment_id)
        if (
            seg is None
            or seg.workspace_id != workspace_id
            or seg.project_id != project_id
            or seg.video_item_id != video_item_id
        ):
            raise StructuralLockOwnershipError(
                "occurrence segment ownership mismatch"
            )
        if structural_lock_manifest_id is not None:
            self.get_manifest(structural_lock_manifest_id, workspace_id)

        provenance_json = (
            json.dumps(provenance, sort_keys=True, separators=(",", ":"))
            if provenance is not None
            else None
        )
        reasons_json = json.dumps(list(reasons or []), separators=(",", ":"))
        row = SegmentRenderRouteRow(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            occurrence_segment_id=occurrence_segment_id,
            structural_lock_manifest_id=structural_lock_manifest_id,
            route=route,
            anchor_x=anchor_x_f,
            anchor_y=anchor_y_f,
            start_frame=start_frame,
            end_frame=end_frame,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            confidence=confidence_f,
            confidence_source=confidence_source,
            provenance_json=provenance_json,
            reasons_json=reasons_json,
            idempotency_key=idempotency_key,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as err:
            self._session.rollback()
            if idempotency_key:
                existing = self._session.scalar(
                    select(SegmentRenderRouteRow).where(
                        SegmentRenderRouteRow.workspace_id == workspace_id,
                        SegmentRenderRouteRow.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    return _map_route(existing), False
            raise StructuralLockConflictError(
                "render route conflicts with an existing row "
                "(segment/route/start_frame already decided)"
            ) from err
        return _map_route(row), True

    def list_routes_for_video(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
    ) -> list[RenderRouteRecord]:
        rows = self._session.scalars(
            select(SegmentRenderRouteRow)
            .where(
                SegmentRenderRouteRow.workspace_id == workspace_id,
                SegmentRenderRouteRow.project_id == project_id,
                SegmentRenderRouteRow.video_item_id == video_item_id,
            )
            .order_by(
                SegmentRenderRouteRow.occurrence_segment_id,
                SegmentRenderRouteRow.start_frame,
                SegmentRenderRouteRow.id,
            )
        ).all()
        return [_map_route(r) for r in rows]

    # ── Pin surface (ReskinConfig / ApplyCheckpoint additive columns) ───

    def set_reskin_lock_pin(
        self,
        config_id: str,
        workspace_id: str,
        expected_revision: int,
        structural_lock_manifest_id: str | None,
        lock_policy_version: str | None,
    ) -> int:
        """Pin/unpin a ReskinConfig via CAS; returns the NEW revision."""
        if expected_revision < 1:
            raise ValueError("revision must be >= 1")
        if lock_policy_version is not None and not _LOCK_POLICY_RE.match(
            lock_policy_version
        ):
            raise StructuralLockParamsError(
                "lock_policy_version must match ^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
            )
        if structural_lock_manifest_id is not None:
            manifest_row = self._session.scalar(
                select(StructuralLockManifest).where(
                    StructuralLockManifest.id == structural_lock_manifest_id,
                    StructuralLockManifest.workspace_id == workspace_id,
                )
            )
            if manifest_row is None:
                raise StructuralLockOwnershipError(
                    "pinned manifest not found in this workspace "
                    "(cross-workspace pins refused)"
                )
        current = self._session.scalar(
            select(ReskinConfig).where(
                ReskinConfig.id == config_id,
                ReskinConfig.workspace_id == workspace_id,
            )
        )
        if current is None:
            raise StructuralLockNotFoundError(
                f"ReskinConfig {config_id!r} not found in workspace"
            )
        if current.revision != expected_revision:
            raise StructuralLockConflictError(
                f"stale revision {expected_revision}; current is {current.revision}"
            )
        stmt = (
            update(ReskinConfig)
            .where(
                ReskinConfig.id == config_id,
                ReskinConfig.workspace_id == workspace_id,
                ReskinConfig.revision == expected_revision,
            )
            .values(
                structural_lock_manifest_id=structural_lock_manifest_id,
                lock_policy_version=lock_policy_version,
                revision=expected_revision + 1,
                updated_at=utc_now(),
            )
            .returning(ReskinConfig.revision)
        )
        new_rev = self._session.execute(stmt).scalar_one()
        return int(new_rev)

    def set_checkpoint_lock_pin(
        self,
        checkpoint_id: str,
        workspace_id: str,
        structural_lock_manifest_id: str | None,
        lock_policy_version: str | None,
    ) -> None:
        """Freeze pins on an immutable ApplyCheckpoint (single write).

        The checkpoint's revision stays 1 forever; the pin pair may be
        written EXACTLY ONCE — a second call that tries to CHANGE either pin
        is refused with zero mutation.
        """
        if lock_policy_version is not None and not _LOCK_POLICY_RE.match(
            lock_policy_version
        ):
            raise StructuralLockParamsError(
                "lock_policy_version must match ^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
            )
        if structural_lock_manifest_id is not None:
            manifest_row = self._session.scalar(
                select(StructuralLockManifest).where(
                    StructuralLockManifest.id == structural_lock_manifest_id,
                    StructuralLockManifest.workspace_id == workspace_id,
                )
            )
            if manifest_row is None:
                raise StructuralLockOwnershipError(
                    "pinned manifest not found in this workspace "
                    "(cross-workspace pins refused)"
                )
        current = self._session.scalar(
            select(ApplyCheckpoint).where(
                ApplyCheckpoint.id == checkpoint_id,
                ApplyCheckpoint.workspace_id == workspace_id,
            )
        )
        if current is None:
            raise StructuralLockNotFoundError(
                f"ApplyCheckpoint {checkpoint_id!r} not found in workspace"
            )
        already_pinned = (
            current.structural_lock_manifest_id is not None
            or current.lock_policy_version is not None
        )
        if already_pinned and (
            current.structural_lock_manifest_id != structural_lock_manifest_id
            or current.lock_policy_version != lock_policy_version
        ):
            raise StructuralLockConflictError(
                "apply checkpoint pins are immutable once frozen"
            )
        if already_pinned:
            return
        current.structural_lock_manifest_id = structural_lock_manifest_id
        current.lock_policy_version = lock_policy_version
        current.updated_at = utc_now()
        self._session.flush()

    # ── internals ───────────────────────────────────────────────────────

    def _latest_row(
        self,
        workspace_id: str,
        project_id: str,
        video_item_id: str,
        source_generation: str,
    ) -> StructuralLockManifest | None:
        return self._session.scalar(
            select(StructuralLockManifest)
            .where(
                StructuralLockManifest.workspace_id == workspace_id,
                StructuralLockManifest.project_id == project_id,
                StructuralLockManifest.video_item_id == video_item_id,
                StructuralLockManifest.source_generation == source_generation,
            )
            .order_by(StructuralLockManifest.version.desc())
            .limit(1)
        )

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
        video_item_id: str,
    ) -> None:
        project = self._session.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            raise StructuralLockOwnershipError("project ownership mismatch")
        video = self._session.get(VideoItem, video_item_id)
        if video is None or video.project_id != project_id:
            raise StructuralLockOwnershipError("video item ownership mismatch")


from app.persistence.models import SegmentRenderRoute as SegmentRenderRouteRow  # noqa: E402
