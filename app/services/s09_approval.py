"""Immutable approval/checkpoint repository (S09-T06A).

Writes the foundation ``apply_checkpoint`` table through a fail-closed
approval surface.  The checkpoint is the IMMUTABLE approval record for one
reskin contract state; every later source/pack/route change must never
mutate it.

Immutability semantics (binary, enforced):

- ``revision = 1`` CHECK in the DB; rows are NEVER updated or deleted by
  this repository after INSERT.
- The stored snapshot freezes: pinned pack version ids, the resolved
  CompatibilityPolicy evidence/version, per-segment renderer routes,
  StructuralLockManifest ref, accepted warnings/overrides and demo
  artifact / correction-history refs.  All of it is INSIDE
  ``snapshot_json`` + the pin columns — nothing is read back live from
  mutable tables when serving a checkpoint.
- ``checkpoint_hash`` = sha256 over the canonical approval payload
  (config id/revision, pins, pack versions, loop hashes, timebase,
  snapshot).  Serving re-computes the hash from the STORED row only;
  mismatch → :class:`S09ApprovalIntegrityError` (fail closed).
- Later changes to reskin_config / packs / routes do NOT touch the row:
  the approval keeps its frozen ``reskin_config_revision`` and snapshot.

Blockers fail closed:

- Unresolved demo blockers → submission refused with ZERO durable
  mutation (:class:`ApprovalBlockedError`).  A blocker exists when any
  referenced correction is still ``pending`` or was ``cancelled`` (only
  ``applied`` corrections resolve), or when an override lacks explicit
  user provenance.
- Warnings/overrides are EXPLICIT opt-in: they are part of the request,
  hashed into the checkpoint; there is no implicit accept anywhere.

Idempotency/CAS:

- UNIQUE(workspace_id, idempotency_key) WHERE NOT NULL; equivalent replay
  returns ``(existing, created=False)``; materially different payload
  under the same key → :class:`ApprovalConflictError` (zero mutation).
- Natural key: content sha256 of the canonical request — duplicate
  submissions converge on ONE row regardless of client keys.
- Conflict probe direction B: a DIFFERENT payload under an existing
  natural key raises conflict with ZERO durable mutation.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import (
    RENDERER_ROUTES,
    ApplyCheckpoint,
    Artifact,
    CharacterAsset,
    CharacterPackVersion,
    ObjectRole,
    OccurrenceSegment,
    ReskinConfig,
    S09Correction,
    VideoItem,
)
from app.persistence.reskin_config import (
    ReskinConfigParamsError,
    parse_params,
)
from app.persistence.structural_lock import (
    StructuralLockNotFoundError,
    StructuralLockParamsError,
    StructuralLockRepository,
    canonical_manifest_json,
)
from app.persistence.structural_lock import (
    manifest_hash as structural_manifest_hash,
)

__all__ = [
    "APPROVAL_V2_SCHEMA",
    "FULL_APPLY_AUTHORITY_VERSION",
    "FULL_APPLY_EXECUTABLE_ROUTES",
    "ApprovalBlockedError",
    "ApprovalConflictError",
    "ApprovalNotFoundError",
    "ApprovalValidationError",
    "CheckpointIntegrity",
    "S09ApprovalIntegrityError",
    "S09ApprovalRecord",
    "S09ApprovalRepository",
]

#: Immutable snapshot schema tag for the v2 approval surface (C6A).  v1
#: checkpoints keep ``s09.approval/v1`` forever — v2 is ADDITIVE and a v2
#: row always carries the nested ``full_apply_authority``.
APPROVAL_V2_SCHEMA = "s09.approval/v2"

#: Version tag of the frozen Full Apply authority block inside v2 snapshots.
FULL_APPLY_AUTHORITY_VERSION = "s09.full-apply-authority/v1"

#: Routes the licensed production adapters can execute for Full Apply.
#: Mirrors ``app/workflow/s10_full_apply_jobs.py:_EXECUTABLE_ROUTES`` (the
#: S10-owned single authority).  S09 must NOT import S10 (dependency
#: direction: S10 consumes S09 authority), so the capability set is mirrored
#: here and FREEZED into every v2 snapshot at approval time — a later
#: capability change never mutates a stored checkpoint, and an unsupported
#: route is recorded as non-executable (never downgraded).
FULL_APPLY_EXECUTABLE_ROUTES = frozenset(
    {"sprite_affine", "pose_swap", "controlled_redraw"}
)


class ApprovalConflictError(Exception):
    """CAS/idempotency conflict — zero durable mutation."""


class ApprovalNotFoundError(Exception):
    """No checkpoint for the requested id inside this workspace."""


class ApprovalBlockedError(Exception):
    """Unresolved demo blockers — submission refused, zero mutation."""


class ApprovalValidationError(ValueError):
    """Payload outside its closed domain (fail-closed validation)."""


class S09ApprovalIntegrityError(Exception):
    """Stored checkpoint hash no longer matches its own content."""


def _new_id() -> str:
    return str(__import__("uuid").uuid4())


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _reject_non_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ApprovalValidationError(f"non-finite number at {path}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_non_finite(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_non_finite(item, f"{path}[{index}]")
        return
    return


def _require_str_list(
    values: list[str] | None, field: str, *, max_len: int = 255
) -> list[str]:
    if values is None:
        return []
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ApprovalValidationError(f"{field} entries must be non-empty strings")
        if len(value) > max_len:
            raise ApprovalValidationError(f"{field} entry too long (max {max_len})")
        cleaned.append(value)
    if len(set(cleaned)) != len(cleaned):
        raise ApprovalValidationError(f"{field} entries must be unique")
    return cleaned


@dataclass(frozen=True)
class S09ApprovalRecord:
    id: str
    workspace_id: str
    project_id: str
    reskin_config_id: str
    reskin_config_revision: int
    structural_lock_manifest_id: str | None
    lock_policy_version: str | None
    pack_version_ids: list[str]
    loop_hashes: list[dict[str, Any]]
    timebase_fingerprint: str
    snapshot: dict[str, Any]
    checkpoint_hash: str
    note: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CheckpointIntegrity:
    checkpoint_id: str
    verified: bool
    reason: str


def _map_row(row: ApplyCheckpoint) -> S09ApprovalRecord:
    return S09ApprovalRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        reskin_config_id=row.reskin_config_id,
        reskin_config_revision=row.reskin_config_revision,
        structural_lock_manifest_id=row.structural_lock_manifest_id,
        lock_policy_version=row.lock_policy_version,
        pack_version_ids=list(json.loads(row.pack_version_ids_json)),
        loop_hashes=list(json.loads(row.loop_hashes_json)),
        timebase_fingerprint=row.timebase_fingerprint,
        snapshot=dict(json.loads(row.snapshot_json)),
        checkpoint_hash=row.checkpoint_hash,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class S09ApprovalRepository:
    """Fail-closed immutable approval surface over ``apply_checkpoint``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── reads ────────────────────────────────────────────────────────────

    def get_checkpoint(self, checkpoint_id: str, workspace_id: str) -> S09ApprovalRecord:
        current = self._session.scalar(
            select(ApplyCheckpoint).where(
                ApplyCheckpoint.id == checkpoint_id,
                ApplyCheckpoint.workspace_id == workspace_id,
            )
        )
        if current is None:
            raise ApprovalNotFoundError(
                f"ApplyCheckpoint {checkpoint_id!r} not found in workspace"
            )
        return self._verified_record(current)

    def list_checkpoints(
        self,
        workspace_id: str,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[S09ApprovalRecord]:
        stmt = (
            select(ApplyCheckpoint)
            .where(ApplyCheckpoint.workspace_id == workspace_id)
            .order_by(ApplyCheckpoint.created_at.desc(), ApplyCheckpoint.id)
            .limit(limit)
        )
        if project_id is not None:
            stmt = stmt.where(ApplyCheckpoint.project_id == project_id)
        rows = self._session.scalars(stmt).all()
        return [self._verified_record(row) for row in rows]

    def verify_checkpoint(self, checkpoint_id: str, workspace_id: str) -> CheckpointIntegrity:
        """Recompute the hash over the STORED row only (no live joins)."""
        row = self._session.scalar(
            select(ApplyCheckpoint).where(
                ApplyCheckpoint.id == checkpoint_id,
                ApplyCheckpoint.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise ApprovalNotFoundError(
                f"ApplyCheckpoint {checkpoint_id!r} not found in workspace"
            )
        expected = _checkpoint_content_hash(
            reskin_config_id=row.reskin_config_id,
            reskin_config_revision=row.reskin_config_revision,
            structural_lock_manifest_id=row.structural_lock_manifest_id,
            lock_policy_version=row.lock_policy_version,
            pack_version_ids=json.loads(row.pack_version_ids_json),
            loop_hashes=json.loads(row.loop_hashes_json),
            timebase_fingerprint=row.timebase_fingerprint,
            snapshot=json.loads(row.snapshot_json),
        )
        if expected != row.checkpoint_hash:
            return CheckpointIntegrity(
                checkpoint_id=row.id,
                verified=False,
                reason="stored checkpoint_hash does not match recomputed content hash",
            )
        return CheckpointIntegrity(checkpoint_id=row.id, verified=True, reason="ok")

    # ── write path ───────────────────────────────────────────────────────

    def submit_checkpoint(
        self,
        workspace_id: str,
        reskin_config_id: str,
        expected_reskin_revision: int,
        pack_version_ids: list[str],
        *,
        demo_artifact_ids: list[str] | None = None,
        correction_ids: list[str] | None = None,
        accepted_warnings: list[str] | None = None,
        overrides: list[str] | None = None,
        note: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[S09ApprovalRecord, bool]:
        """Create the ONE immutable checkpoint; equivalent replay replays.

        ``project_id`` is DERIVED server-side from the reskin config row
        (client never supplies ownership identity).
        """
        warnings_clean = _require_str_list(accepted_warnings, "accepted_warnings")
        overrides_clean = _require_str_list(overrides, "overrides")
        packs_clean = _require_str_list(pack_version_ids, "pack_version_ids")
        demos_clean = _require_str_list(demo_artifact_ids, "demo_artifact_ids", max_len=36 * 4)
        corrections_clean = _require_str_list(correction_ids, "correction_ids")

        # ── 1. Resolve + validate EVERYTHING before any write ────────────
        config = self._session.scalar(
            select(ReskinConfig).where(
                ReskinConfig.id == reskin_config_id,
                ReskinConfig.workspace_id == workspace_id,
            )
        )
        if config is None:
            raise ApprovalNotFoundError(
                f"ReskinConfig {reskin_config_id!r} not found in workspace"
            )
        project_id = config.project_id

        # CAS guard: the approval freezes exactly the revision the approver
        # saw.  Stale expectation → conflict BEFORE any durable mutation.
        if config.revision != expected_reskin_revision:
            raise ApprovalConflictError(
                f"stale reskin_config revision {expected_reskin_revision}; "
                f"current revision is {config.revision}"
            )

        # ── 1b. Pinned pack versions must exist in THIS workspace ────────
        seen_packs: set[str] = set()
        for pack_id in packs_clean:
            if pack_id in seen_packs:
                continue
            seen_packs.add(pack_id)
            pack = self._session.scalar(
                select(CharacterPackVersion).where(
                    CharacterPackVersion.id == pack_id,
                    CharacterPackVersion.workspace_id == workspace_id,
                )
            )
            if pack is None:
                raise ApprovalNotFoundError(
                    f"CharacterPackVersion {pack_id!r} not found in workspace"
                )

        # Demo artifact refs must exist in THIS workspace (ownership).
        for artifact_id in demos_clean:
            artifact = self._session.scalar(
                select(Artifact).where(
                    Artifact.id == artifact_id,
                    Artifact.workspace_id == workspace_id,
                )
            )
            if artifact is None:
                raise ApprovalNotFoundError(
                    f"demo artifact {artifact_id!r} not found in workspace"
                )

        # Correction history refs must exist in THIS workspace AND every
        # unresolved one BLOCKS the approval (fail closed, zero mutation).
        for correction_id in corrections_clean:
            correction = self._session.scalar(
                select(S09Correction).where(
                    S09Correction.id == correction_id,
                    S09Correction.workspace_id == workspace_id,
                )
            )
            if correction is None:
                raise ApprovalNotFoundError(
                    f"correction {correction_id!r} not found in workspace"
                )
            if correction.status != "applied":
                raise ApprovalBlockedError(
                    f"correction {correction_id!r} is {correction.status!r}; "
                    "only applied corrections can be approved over"
                )

        # Overrides are explicit-only: each needs a matching applied
        # correction ref (the recorded human decision), never implicit.
        for override in overrides_clean:
            matched = False
            for correction_id in corrections_clean:
                correction = self._session.get(S09Correction, correction_id)
                assert correction is not None  # validated above
                request_payload = json.loads(correction.request_json)
                reasons: list[str] = list(request_payload.get("reasons", []))
                provenance = request_payload.get("provenance") or {}
                if isinstance(provenance, dict):
                    reasons.extend(provenance.get("reasons", []) or [])
                    # RouteOverrideProvenance.evidence mirrors override_reason
                    # inside the provenance object — match it explicitly too
                    # (F3 P1: mirrors FE ApprovalPanel.reasonsOf).
                    evidence = provenance.get("evidence")
                    if isinstance(evidence, str) and evidence:
                        reasons.append(evidence)
                # Route-override audit evidence lives at the TOP LEVEL of the
                # request payload (RouteOverrideCorrectionRequest.
                # override_reason) — a legitimate override must match it too.
                override_reason = request_payload.get("override_reason")
                if isinstance(override_reason, str) and override_reason:
                    reasons.append(override_reason)
                if override in reasons:
                    matched = True
                    break
            if not matched:
                raise ApprovalBlockedError(
                    f"override {override!r} has no explicit applied-correction "
                    "evidence; overrides cannot be implicit"
                )

        # ── 2. Lock-pin resolution (hash-verified, fail-closed) ──────────
        lock_repo = StructuralLockRepository(self._session)
        manifest_id = config.structural_lock_manifest_id
        policy_version = config.lock_policy_version
        route_evidence: list[dict[str, Any]] = []
        if manifest_id is not None:
            try:
                manifest = lock_repo.get_manifest(manifest_id, workspace_id)
            except StructuralLockNotFoundError as err:
                raise ApprovalValidationError(
                    f"pinned structural lock manifest not found: {err}"
                ) from err
            except StructuralLockParamsError as err:
                raise ApprovalConflictError(
                    f"pinned manifest payload invalid: {err}"
                ) from err
            if manifest.status == "voided":
                raise ApprovalConflictError(
                    f"structural lock manifest {manifest_id!r} is voided"
                )
            try:
                canonical = canonical_manifest_json(manifest.manifest)
            except StructuralLockParamsError as err:
                raise ApprovalConflictError(
                    f"pinned manifest payload invalid: {err}"
                ) from err
            if structural_manifest_hash(canonical) != manifest.manifest_hash_hex:
                raise ApprovalConflictError(
                    "pinned manifest hash mismatch: refusing to approve over "
                    "a tampered manifest"
                )
            for seg in manifest.manifest.get("segments", []):
                if seg["route"] not in RENDERER_ROUTES:
                    raise ApprovalConflictError(
                        f"manifest segment route {seg['route']!r} outside enum"
                    )
            policy_version = manifest.policy_version

            routes = lock_repo.list_routes_for_video(
                workspace_id, config.project_id, manifest.video_item_id
            )
            for r in routes:
                if r.route not in RENDERER_ROUTES:
                    raise ApprovalConflictError(
                        f"persisted render route {r.route!r} outside enum"
                    )
                route_evidence.append(
                    {
                        "occurrence_segment_id": r.occurrence_segment_id,
                        "route": r.route,
                        "anchor_x": r.anchor_x,
                        "anchor_y": r.anchor_y,
                        "start_frame": r.start_frame,
                        "end_frame": r.end_frame,
                        "confidence": r.confidence,
                        "confidence_source": r.confidence_source,
                        "reasons": list(r.reasons),
                        "provenance": r.provenance,
                        "structural_lock_manifest_id": r.structural_lock_manifest_id,
                    }
                )

        # ── 3. Freeze the immutable snapshot ─────────────────────────────
        snapshot: dict[str, Any] = {
            "schema": "s09.approval/v1",
            "note": note,
            "compatibility_policy": {
                "policy_version": policy_version,
                "structural_lock_manifest_id": manifest_id,
                "renderer_routes_per_segment": route_evidence,
            },
            "warnings_accepted": list(warnings_clean),
            "overrides": list(overrides_clean),
            "demo_artifact_refs": list(demos_clean),
            "correction_history_refs": list(corrections_clean),
        }
        _reject_non_finite(snapshot)

        loop_hashes = [
            {
                "loop_index": index,
                "pack_version_id": pack_id,
                "content_hash": hashlib.sha256(
                    f"{reskin_config_id}:{pack_id}".encode()
                ).hexdigest(),
            }
            for index, pack_id in enumerate(packs_clean)
        ]
        timebase_payload = _canonical_json(
            {
                "reskin_config_id": reskin_config_id,
                "revision": expected_reskin_revision,
                "packs": packs_clean,
                "policy": policy_version,
            }
        )
        timebase_fingerprint = hashlib.sha256(timebase_payload.encode()).hexdigest()

        content_hash = _checkpoint_content_hash(
            reskin_config_id=reskin_config_id,
            reskin_config_revision=expected_reskin_revision,
            structural_lock_manifest_id=manifest_id,
            lock_policy_version=policy_version,
            pack_version_ids=packs_clean,
            loop_hashes=loop_hashes,
            timebase_fingerprint=timebase_fingerprint,
            snapshot=snapshot,
        )
        natural_key = content_hash[:64]

        # Idempotent replay FIRST (workspace-scoped idempotency key).
        if idempotency_key:
            existing = self._session.scalar(
                select(ApplyCheckpoint).where(
                    ApplyCheckpoint.workspace_id == workspace_id,
                    ApplyCheckpoint.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                self._assert_equivalent_request(existing, natural_key=natural_key)
                return _map_row(existing), False

        # Natural-key replay: identical content converges on ONE row.
        existing_natural = self._session.execute(
            select(ApplyCheckpoint).where(
                ApplyCheckpoint.workspace_id == workspace_id,
                ApplyCheckpoint.checkpoint_hash == natural_key,
            )
        ).scalar_one_or_none()
        if existing_natural is not None:
            return _map_row(existing_natural), False

        # CONFLICT PROBE (direction B): same natural key with DIFFERENT
        # content is impossible (hash IS the key), so conflicts arrive via
        # the idempotency-key branch above.  The reverse direction — an
        # existing row whose content hash differs while a caller insists on
        # the same key — is covered by _assert_equivalent_request.
        row = ApplyCheckpoint(
            id=_new_id(),
            workspace_id=workspace_id,
            project_id=project_id,
            reskin_config_id=reskin_config_id,
            reskin_config_revision=expected_reskin_revision,
            pack_version_ids_json=_canonical_json(packs_clean),
            loop_hashes_json=_canonical_json(loop_hashes),
            timebase_fingerprint=timebase_fingerprint,
            snapshot_json=_canonical_json(snapshot),
            checkpoint_hash=content_hash,
            note=note,
            idempotency_key=idempotency_key,
            # Pin columns written ONCE here; set_checkpoint_lock_pin would
            # refuse any later change (immutable-once semantics).
            structural_lock_manifest_id=manifest_id,
            lock_policy_version=policy_version,
        )
        self._session.add(row)
        try:
            self._session.flush()
        except Exception as err:  # pragma: no cover - defensive
            self._session.rollback()
            raise ApprovalConflictError(f"checkpoint insert failed: {err}") from err
        return _map_row(row), True

    def replay_probe(
        self, workspace_id: str, idempotency_key: str
    ) -> S09ApprovalRecord:
        """Explicit replay lookup — NotFound when the key is unknown."""
        existing = self._session.scalar(
            select(ApplyCheckpoint).where(
                ApplyCheckpoint.workspace_id == workspace_id,
                ApplyCheckpoint.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise ApprovalNotFoundError(
                f"no checkpoint bound to idempotency key {idempotency_key!r}"
            )
        return self._verified_record(existing)

    def conflict_probe(
        self,
        workspace_id: str,
        idempotency_key: str,
        reskin_config_id: str,
        expected_reskin_revision: int,
        pack_version_ids: list[str],
        *,
        demo_artifact_ids: list[str] | None = None,
        correction_ids: list[str] | None = None,
        accepted_warnings: list[str] | None = None,
        overrides: list[str] | None = None,
    ) -> None:
        """Direction-B probe: MUST raise; success means zero-mutation held."""
        existing = self._session.scalar(
            select(ApplyCheckpoint).where(
                ApplyCheckpoint.workspace_id == workspace_id,
                ApplyCheckpoint.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise ApprovalNotFoundError(
                f"no checkpoint bound to idempotency key {idempotency_key!r}"
            )
        snapshot = dict(json.loads(existing.snapshot_json))
        differing_payload = (
            existing.reskin_config_id != reskin_config_id
            or existing.reskin_config_revision != expected_reskin_revision
            or json.loads(existing.pack_version_ids_json) != list(pack_version_ids)
            or snapshot.get("warnings_accepted") != list(accepted_warnings or [])
            or snapshot.get("overrides") != list(overrides or [])
            or snapshot.get("demo_artifact_refs") != list(demo_artifact_ids or [])
            or snapshot.get("correction_history_refs") != list(correction_ids or [])
        )
        if not differing_payload:
            raise ApprovalValidationError(
                "payload equals the stored one; use submit/replay instead"
            )
        raise ApprovalConflictError(
            "idempotency key already bound to a materially different approval"
        )

    # ── v2 authority surface (S10-C6A — immutable approval v2) ───────────

    def submit_checkpoint_v2(
        self,
        workspace_id: str,
        reskin_config_id: str,
        expected_reskin_revision: int,
        pack_version_ids: list[str],
        *,
        demo_artifact_ids: list[str] | None = None,
        correction_ids: list[str] | None = None,
        accepted_warnings: list[str] | None = None,
        overrides: list[str] | None = None,
        note: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[S09ApprovalRecord, bool]:
        """Deterministic reapproval — creates a NEW ``s09.approval/v2`` row.

        v1 rows are NEVER mutated/backfilled: this path only inserts v2 rows
        (or replays an equivalent v2).  The nested ``full_apply_authority``
        is built EXCLUSIVELY from persisted/canonical rows (structural lock
        manifest + segments + roles + reskin configs + pack assets + source
        artifact); the client payload is never render truth.  The whole
        snapshot — including every authority field — sits inside the
        checkpoint content hash (``checkpoint_hash`` = sha256 over the
        canonical v2 payload), so a later live mutation can never silently
        change the stored authority.
        """
        warnings_clean = _require_str_list(accepted_warnings, "accepted_warnings")
        overrides_clean = _require_str_list(overrides, "overrides")
        packs_clean = _require_str_list(pack_version_ids, "pack_version_ids")
        demos_clean = _require_str_list(
            demo_artifact_ids, "demo_artifact_ids", max_len=36 * 4
        )
        corrections_clean = _require_str_list(correction_ids, "correction_ids")

        # ── 1. Resolve + validate EVERYTHING before any write ────────────
        config = self._session.scalar(
            select(ReskinConfig).where(
                ReskinConfig.id == reskin_config_id,
                ReskinConfig.workspace_id == workspace_id,
            )
        )
        if config is None:
            raise ApprovalNotFoundError(
                f"ReskinConfig {reskin_config_id!r} not found in workspace"
            )
        project_id = config.project_id
        if config.revision != expected_reskin_revision:
            raise ApprovalConflictError(
                f"stale reskin_config revision {expected_reskin_revision}; "
                f"current revision is {config.revision}"
            )

        # Pinned pack versions must exist in THIS workspace and carry the
        # approved published/ready status the Full Apply binding requires.
        for pack_id in packs_clean:
            pack = self._session.scalar(
                select(CharacterPackVersion).where(
                    CharacterPackVersion.id == pack_id,
                    CharacterPackVersion.workspace_id == workspace_id,
                )
            )
            if pack is None:
                raise ApprovalNotFoundError(
                    f"CharacterPackVersion {pack_id!r} not found in workspace"
                )

        for artifact_id in demos_clean:
            artifact = self._session.scalar(
                select(Artifact).where(
                    Artifact.id == artifact_id,
                    Artifact.workspace_id == workspace_id,
                )
            )
            if artifact is None:
                raise ApprovalNotFoundError(
                    f"demo artifact {artifact_id!r} not found in workspace"
                )

        for correction_id in corrections_clean:
            correction = self._session.scalar(
                select(S09Correction).where(
                    S09Correction.id == correction_id,
                    S09Correction.workspace_id == workspace_id,
                )
            )
            if correction is None:
                raise ApprovalNotFoundError(
                    f"correction {correction_id!r} not found in workspace"
                )
            if correction.status != "applied":
                raise ApprovalBlockedError(
                    f"correction {correction_id!r} is {correction.status!r}; "
                    "only applied corrections can be approved over"
                )

        # Overrides are explicit-only (identical to the v1 path — C3
        # reasonsOf mirror preserved).
        for override in overrides_clean:
            matched = False
            for correction_id in corrections_clean:
                correction = self._session.get(S09Correction, correction_id)
                assert correction is not None  # validated above
                request_payload = json.loads(correction.request_json)
                reasons: list[str] = list(request_payload.get("reasons", []))
                provenance = request_payload.get("provenance") or {}
                if isinstance(provenance, dict):
                    reasons.extend(provenance.get("reasons", []) or [])
                    evidence = provenance.get("evidence")
                    if isinstance(evidence, str) and evidence:
                        reasons.append(evidence)
                override_reason = request_payload.get("override_reason")
                if isinstance(override_reason, str) and override_reason:
                    reasons.append(override_reason)
                if override in reasons:
                    matched = True
                    break
            if not matched:
                raise ApprovalBlockedError(
                    f"override {override!r} has no explicit applied-correction "
                    "evidence; overrides cannot be implicit"
                )

        # ── 2. Lock-pin resolution (hash-verified, fail-closed) + authority ──
        lock_repo = StructuralLockRepository(self._session)
        manifest_id = config.structural_lock_manifest_id
        policy_version = config.lock_policy_version
        route_evidence: list[dict[str, Any]] = []

        if manifest_id is None:
            # Demo approval may still exist without a manifest, but Full
            # Apply is NOT executable: no deterministic structural authority.
            structural_lock: dict[str, Any] = {
                "structural_lock_manifest_id": None,
                "policy_version": None,
                "manifest_hash": None,
                "canonical_manifest": None,
            }
            shot_order: list[str] = []
            segments_authority: list[dict[str, Any]] = []
            role_mappings: list[dict[str, Any]] = []
            source_authority: dict[str, Any] | None = None
            authority_reasons: list[str] = [
                "no structural lock manifest pinned; full apply requires "
                "manifest authority (reapproval after pinning)"
            ]
            unsupported_routes: list[str] = []
        else:
            try:
                manifest = lock_repo.get_manifest(manifest_id, workspace_id)
            except StructuralLockNotFoundError as err:
                raise ApprovalValidationError(
                    f"pinned structural lock manifest not found: {err}"
                ) from err
            except StructuralLockParamsError as err:
                raise ApprovalConflictError(
                    f"pinned manifest payload invalid: {err}"
                ) from err
            if manifest.status == "voided":
                raise ApprovalConflictError(
                    f"structural lock manifest {manifest_id!r} is voided"
                )
            try:
                canonical = canonical_manifest_json(manifest.manifest)
            except StructuralLockParamsError as err:
                raise ApprovalConflictError(
                    f"pinned manifest payload invalid: {err}"
                ) from err
            if structural_manifest_hash(canonical) != manifest.manifest_hash_hex:
                raise ApprovalConflictError(
                    "pinned manifest hash mismatch: refusing to approve over "
                    "a tampered manifest"
                )
            for seg in manifest.manifest.get("segments", []):
                if seg["route"] not in RENDERER_ROUTES:
                    raise ApprovalConflictError(
                        f"manifest segment route {seg['route']!r} outside enum"
                    )
            policy_version = manifest.policy_version

            routes = lock_repo.list_routes_for_video(
                workspace_id, config.project_id, manifest.video_item_id
            )
            for r in routes:
                if r.route not in RENDERER_ROUTES:
                    raise ApprovalConflictError(
                        f"persisted render route {r.route!r} outside enum"
                    )
                route_evidence.append(
                    {
                        "occurrence_segment_id": r.occurrence_segment_id,
                        "route": r.route,
                        "anchor_x": r.anchor_x,
                        "anchor_y": r.anchor_y,
                        "start_frame": r.start_frame,
                        "end_frame": r.end_frame,
                        "confidence": r.confidence,
                        "confidence_source": r.confidence_source,
                        "reasons": list(r.reasons),
                        "provenance": r.provenance,
                        "structural_lock_manifest_id": r.structural_lock_manifest_id,
                    }
                )

            structural_lock = {
                "structural_lock_manifest_id": manifest.id,
                "policy_version": manifest.policy_version,
                "manifest_hash": manifest.manifest_hash_hex,
                "canonical_manifest": manifest.manifest,
            }
            shot_order = list(manifest.manifest.get("shot_order", []))

            # Source managed artifact authority (persisted rows only).
            # VideoItem carries no workspace column — its workspace is the
            # owning Project's (config.project_id is already workspace-bound
            # above), so project binding is the cross-scope check.
            video_item = self._session.get(VideoItem, manifest.video_item_id)
            if video_item is None or video_item.project_id != project_id:
                raise ApprovalValidationError(
                    f"cross-scope video_item {manifest.video_item_id!r} "
                    "referenced by pinned manifest"
                )
            source_authority = None
            if video_item.source_artifact_id is not None:
                source_artifact = self._session.get(
                    Artifact, video_item.source_artifact_id
                )
                if (
                    source_artifact is not None
                    and source_artifact.workspace_id == workspace_id
                ):
                    source_authority = {
                        "source_generation": manifest.source_generation,
                        "source_artifact_id": source_artifact.id,
                        "relative_path": source_artifact.relative_path,
                        "sha256": source_artifact.sha256,
                        "size_bytes": source_artifact.size_bytes,
                        "frame_count": manifest.manifest.get("frame_count"),
                        "fps": manifest.manifest["timebase"]["fps"],
                        "time_base": manifest.manifest["timebase"]["time_base"],
                        "start_time_ms": manifest.manifest["timebase"][
                            "start_time_ms"
                        ],
                    }
            if source_authority is None:
                authority_reasons = [
                    "source artifact missing/incomplete for full apply"
                ]
            else:
                authority_reasons = []
            unsupported_routes = []

            # EXACT manifest-selected segments (never route alternatives).
            segments_authority = []
            role_mapping_by_role: dict[str, dict[str, Any]] = {}
            for seg in manifest.manifest.get("segments", []):
                seg_entry, seg_reasons, seg_unsupported = (
                    self._build_segment_authority(
                        workspace_id,
                        project_id,
                        manifest.source_generation,
                        seg,
                        role_mapping_by_role,
                    )
                )
                segments_authority.append(seg_entry)
                authority_reasons.extend(seg_reasons)
                unsupported_routes.extend(seg_unsupported)
            role_mappings = list(role_mapping_by_role.values())

        # Pack eligibility (approved published/ready — mirrors the S10
        # checkpoint binding check; never a silent downgrade).
        for pack_id in packs_clean:
            pack = self._session.get(CharacterPackVersion, pack_id)
            assert pack is not None  # validated above
            if pack.status not in ("published", "ready"):
                authority_reasons.append(
                    f"pack_version {pack_id} status {pack.status!r} "
                    "not published/ready for full apply"
                )

        eligibility = {
            "full_apply_executable": not authority_reasons,
            "reasons": sorted(set(authority_reasons)),
            "unsupported_routes": sorted(set(unsupported_routes)),
        }

        video_item_id: str | None = (
            manifest.video_item_id if manifest_id is not None else None
        )
        source_generation: str | None = (
            manifest.source_generation if manifest_id is not None else None
        )

        # ── 3. Freeze the immutable v2 snapshot (authority hash-covered) ──
        snapshot: dict[str, Any] = {
            "schema": APPROVAL_V2_SCHEMA,
            "note": note,
            "compatibility_policy": {
                "policy_version": policy_version,
                "structural_lock_manifest_id": manifest_id,
                "renderer_routes_per_segment": route_evidence,
            },
            "warnings_accepted": list(warnings_clean),
            "overrides": list(overrides_clean),
            "demo_artifact_refs": list(demos_clean),
            "correction_history_refs": list(corrections_clean),
            "full_apply_authority": {
                "authority_version": FULL_APPLY_AUTHORITY_VERSION,
                "identity": {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "video_item_id": video_item_id,
                    "reskin_config_id": reskin_config_id,
                    "reskin_config_revision": expected_reskin_revision,
                    "source_generation": source_generation,
                },
                "source": source_authority,
                "structural_lock": structural_lock,
                "shot_order": shot_order,
                "segments": segments_authority,
                "role_mappings": role_mappings,
                "eligibility": eligibility,
            },
        }
        _reject_non_finite(snapshot)

        loop_hashes = [
            {
                "loop_index": index,
                "pack_version_id": pack_id,
                "content_hash": hashlib.sha256(
                    f"{reskin_config_id}:{pack_id}".encode()
                ).hexdigest(),
            }
            for index, pack_id in enumerate(packs_clean)
        ]
        timebase_payload = _canonical_json(
            {
                "reskin_config_id": reskin_config_id,
                "revision": expected_reskin_revision,
                "packs": packs_clean,
                "policy": policy_version,
            }
        )
        timebase_fingerprint = hashlib.sha256(timebase_payload.encode()).hexdigest()

        content_hash = _checkpoint_content_hash(
            reskin_config_id=reskin_config_id,
            reskin_config_revision=expected_reskin_revision,
            structural_lock_manifest_id=manifest_id,
            lock_policy_version=policy_version,
            pack_version_ids=packs_clean,
            loop_hashes=loop_hashes,
            timebase_fingerprint=timebase_fingerprint,
            snapshot=snapshot,
        )
        natural_key = content_hash[:64]

        # Idempotent replay FIRST (workspace-scoped idempotency key).
        if idempotency_key:
            existing = self._session.scalar(
                select(ApplyCheckpoint).where(
                    ApplyCheckpoint.workspace_id == workspace_id,
                    ApplyCheckpoint.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                self._assert_equivalent_request(existing, natural_key=natural_key)
                return _map_row(existing), False

        # Natural-key replay: identical v2 content converges on ONE row.
        existing_natural = self._session.execute(
            select(ApplyCheckpoint).where(
                ApplyCheckpoint.workspace_id == workspace_id,
                ApplyCheckpoint.checkpoint_hash == natural_key,
            )
        ).scalar_one_or_none()
        if existing_natural is not None:
            return _map_row(existing_natural), False

        row = ApplyCheckpoint(
            id=_new_id(),
            workspace_id=workspace_id,
            project_id=project_id,
            reskin_config_id=reskin_config_id,
            reskin_config_revision=expected_reskin_revision,
            pack_version_ids_json=_canonical_json(packs_clean),
            loop_hashes_json=_canonical_json(loop_hashes),
            timebase_fingerprint=timebase_fingerprint,
            snapshot_json=_canonical_json(snapshot),
            checkpoint_hash=content_hash,
            note=note,
            idempotency_key=idempotency_key,
            structural_lock_manifest_id=manifest_id,
            lock_policy_version=policy_version,
        )
        self._session.add(row)
        try:
            self._session.flush()
        except Exception as err:  # pragma: no cover - defensive
            self._session.rollback()
            raise ApprovalConflictError(f"checkpoint insert failed: {err}") from err
        return _map_row(row), True

    def full_apply_authority(
        self, checkpoint_id: str, workspace_id: str
    ) -> dict[str, Any]:
        """Return the frozen Full Apply authority for a v2 checkpoint.

        Read-only.  A v1 checkpoint fails closed with ``REAPPROVAL_REQUIRED``
        (zero mutation); a tampered v2 row raises
        :class:`S09ApprovalIntegrityError`; a v2 row whose snapshot lost the
        authority block is treated as corrupted storage.
        """
        row = self._session.scalar(
            select(ApplyCheckpoint).where(
                ApplyCheckpoint.id == checkpoint_id,
                ApplyCheckpoint.workspace_id == workspace_id,
            )
        )
        if row is None:
            raise ApprovalNotFoundError(
                f"ApplyCheckpoint {checkpoint_id!r} not found in workspace"
            )
        integrity = self.verify_checkpoint(row.id, row.workspace_id)
        if not integrity.verified:
            raise S09ApprovalIntegrityError(integrity.reason)
        snapshot = json.loads(row.snapshot_json)
        schema = snapshot.get("schema")
        if schema != APPROVAL_V2_SCHEMA:
            raise ApprovalValidationError(
                f"REAPPROVAL_REQUIRED: checkpoint {checkpoint_id!r} is "
                f"{schema!r}; full apply requires a s09.approval/v2 "
                "checkpoint (deterministic reapproval)"
            )
        authority = snapshot.get("full_apply_authority")
        if not isinstance(authority, dict):
            raise S09ApprovalIntegrityError(
                f"checkpoint {checkpoint_id!r} v2 snapshot is missing "
                "full_apply_authority"
            )
        return authority

    # ── internals ────────────────────────────────────────────────────────

    def _assert_equivalent_request(
        self, existing: ApplyCheckpoint, *, natural_key: str
    ) -> None:
        if existing.checkpoint_hash != natural_key:
            raise ApprovalConflictError(
                "idempotency key is already bound to a materially different "
                "approval payload"
            )

    def _verified_record(self, row: ApplyCheckpoint) -> S09ApprovalRecord:
        integrity = self.verify_checkpoint(row.id, row.workspace_id)
        if not integrity.verified:
            raise S09ApprovalIntegrityError(integrity.reason)
        return _map_row(row)

    # ── v2 authority builders (persisted rows only — never client truth) ──

    def _build_segment_authority(
        self,
        workspace_id: str,
        project_id: str,
        manifest_generation: str,
        manifest_seg: dict[str, Any],
        role_mapping_by_role: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        """Freeze ONE exact manifest-selected segment (route/range/identity).

        Cross-scope segment/generation references fail closed
        (:class:`ApprovalValidationError`) BEFORE any write.  Eligibility is
        computed per segment: unsupported route (never downgraded), missing
        geometry and missing role mapping are each recorded with a precise
        immutable reason.
        """
        seg_id = manifest_seg["occurrence_segment_id"]
        seg_row = self._session.get(OccurrenceSegment, seg_id)
        if (
            seg_row is None
            or seg_row.workspace_id != workspace_id
            or seg_row.project_id != project_id
        ):
            raise ApprovalValidationError(
                f"cross-scope occurrence segment {seg_id!r} referenced by "
                "pinned manifest"
            )
        if seg_row.source_generation != manifest_generation:
            raise ApprovalValidationError(
                f"segment {seg_id} generation {seg_row.source_generation!r} "
                f"!= manifest generation {manifest_generation!r}"
            )

        reasons: list[str] = []
        unsupported: list[str] = []

        route = manifest_seg["route"]
        route_executable = route in FULL_APPLY_EXECUTABLE_ROUTES
        if not route_executable:
            unsupported.append(route)
            reasons.append(
                f"segment {seg_id}: route {route!r} not executable by "
                "licensed production adapters — no downgrade"
            )

        geometry = self._segment_geometry(seg_row)
        if not geometry["has_geometry"]:
            reasons.append(
                f"segment {seg_id}: missing/ambiguous affected geometry "
                "(segmentation/prompt evidence)"
            )

        role_entry: dict[str, Any] | None = None
        role = self._session.get(ObjectRole, seg_row.role_id) if seg_row.role_id else None
        if role is None or role.workspace_id != workspace_id or role.project_id != project_id:
            reasons.append(
                f"segment {seg_id}: role mapping missing/ambiguous "
                "(no persisted object role in scope)"
            )
        else:
            role_entry = {
                "object_role_id": role.id,
                "role_name": role.name,
                "kind": role.kind,
            }
            if role.id not in role_mapping_by_role:
                mapping = self._build_role_mapping(
                    workspace_id, project_id, role
                )
                if mapping is None:
                    reasons.append(
                        f"segment {seg_id}: role {role.id} has no approved "
                        "reskin config mapping"
                    )
                else:
                    role_mapping_by_role[role.id] = mapping

        mask_entry: dict[str, Any] | None = None
        if seg_row.mask_artifact_id is not None:
            mask = self._session.get(Artifact, seg_row.mask_artifact_id)
            if mask is None or mask.workspace_id != workspace_id:
                raise ApprovalValidationError(
                    f"cross-scope mask artifact {seg_row.mask_artifact_id!r} "
                    "referenced by segment"
                )
            mask_entry = {
                "artifact_id": mask.id,
                "relative_path": mask.relative_path,
                "sha256": mask.sha256,
                "size_bytes": mask.size_bytes,
            }

        segment_executable = (
            route_executable
            and geometry["has_geometry"]
            and role_entry is not None
            and role is not None
            and role.id in role_mapping_by_role
        )
        return (
            {
                "occurrence_segment_id": seg_id,
                "logical_id": seg_row.logical_id,
                "lineage_version": seg_row.lineage_version,
                "route": route,
                "anchor": {
                    "x": manifest_seg["anchor"]["x"],
                    "y": manifest_seg["anchor"]["y"],
                },
                "start_frame": manifest_seg["start_frame"],
                "end_frame": manifest_seg["end_frame"],
                "provenance": manifest_seg.get("provenance"),
                "geometry": geometry,
                "mask_artifact": mask_entry,
                "role": role_entry,
                "eligibility": {
                    "executable": segment_executable,
                    "reason": "; ".join(
                        r for r in reasons if r.startswith(f"segment {seg_id}")
                    ),
                },
            },
            reasons,
            unsupported,
        )

    def _build_role_mapping(
        self,
        workspace_id: str,
        project_id: str,
        role: ObjectRole,
    ) -> dict[str, Any] | None:
        """Freeze the approved published pack/mapping/config authority for a role.

        Returns ``None`` when no reskin config exists for the role inside
        this project (authority incomplete → fail closed).  Every numeric
        fact (pack version/status, asset SHA/size, params) is read from the
        persisted rows at approval time and frozen into the snapshot.
        """
        config = self._session.scalar(
            select(ReskinConfig).where(
                ReskinConfig.workspace_id == workspace_id,
                ReskinConfig.project_id == project_id,
                ReskinConfig.object_role_id == role.id,
            )
        )
        if config is None:
            return None
        pack = self._session.get(CharacterPackVersion, config.pack_version_id)
        if pack is None or pack.workspace_id != workspace_id:
            return None

        assets: list[dict[str, Any]] = []
        asset_rows = self._session.scalars(
            select(CharacterAsset)
            .where(
                CharacterAsset.pack_version_id == pack.id,
                CharacterAsset.workspace_id == workspace_id,
            )
            .order_by(CharacterAsset.pose_slot)
        ).all()
        for asset in asset_rows:
            art = self._session.get(Artifact, asset.artifact_id)
            if art is None or art.workspace_id != workspace_id:
                raise ApprovalValidationError(
                    f"cross-scope pack asset artifact {asset.artifact_id!r}"
                )
            assets.append(
                {
                    "pose_slot": asset.pose_slot,
                    "artifact_id": asset.artifact_id,
                    "relative_path": art.relative_path,
                    "sha256": art.sha256,
                    "size_bytes": art.size_bytes,
                }
            )

        try:
            params = parse_params(config.params_json)
        except ReskinConfigParamsError as err:
            raise ApprovalValidationError(
                f"stored reskin params invalid: {err}"
            ) from err
        params_hash = hashlib.sha256(_canonical_json(params).encode()).hexdigest()

        return {
            "object_role_id": role.id,
            "role_name": role.name,
            "kind": role.kind,
            "character_id": config.character_id,
            "pack_version_id": pack.id,
            "pack_version": pack.version,
            "pack_status": pack.status,
            "pack_assets": assets,
            "config_params": params,
            "cast_mapping_id": config.cast_mapping_id,
            "dependency_hashes": {
                "params": params_hash,
                "pack_assets": [a["sha256"] for a in assets],
            },
        }

    def _segment_geometry(self, seg_row: OccurrenceSegment) -> dict[str, Any]:
        """Derive the real affected geometry from persisted evidence.

        The segmentation/prompt JSON rows are the ONLY geometry authority;
        missing/empty evidence yields ``has_geometry=False`` (fail closed —
        the authority is never guessed or hard-coded).
        """
        segmentation = _parse_geometry_json(seg_row.segmentation_json)
        prompt = _parse_geometry_json(seg_row.prompt_json)
        has_geometry = bool(
            (segmentation is not None and (segmentation["points"] or segmentation["boxes"]))
            or (prompt is not None and (prompt["points"] or prompt["boxes"]))
        )
        return {
            "segmentation": segmentation,
            "prompt": prompt,
            "has_geometry": has_geometry,
        }


def _parse_geometry_json(raw: str | None) -> dict[str, Any] | None:
    """Parse persisted segment geometry evidence (points/boxes shape).

    Returns ``None`` for missing/blank evidence; corrupt stored JSON fails
    closed with :class:`ApprovalValidationError` (never silently defaulted).
    Only the canonical ``points``/``boxes`` keys are read — anything else in
    the stored evidence is left out of the frozen geometry (no guessing).
    """
    if raw is None or not str(raw).strip():
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as err:
        raise ApprovalValidationError(
            f"stored segment geometry is not valid JSON: {err}"
        ) from err
    if not isinstance(value, dict):
        raise ApprovalValidationError("stored segment geometry must be an object")
    _reject_non_finite(value)
    return {
        "points": list(value.get("points", []) or []),
        "boxes": list(value.get("boxes", []) or []),
    }


def _checkpoint_content_hash(
    *,
    reskin_config_id: str,
    reskin_config_revision: int,
    structural_lock_manifest_id: str | None,
    lock_policy_version: str | None,
    pack_version_ids: list[str],
    loop_hashes: list[dict[str, Any]],
    timebase_fingerprint: str,
    snapshot: dict[str, Any],
) -> str:
    payload = _canonical_json(
        {
            "reskin_config_id": reskin_config_id,
            "reskin_config_revision": reskin_config_revision,
            "structural_lock_manifest_id": structural_lock_manifest_id,
            "lock_policy_version": lock_policy_version,
            "pack_version_ids": list(pack_version_ids),
            "loop_hashes": loop_hashes,
            "timebase_fingerprint": timebase_fingerprint,
            "snapshot": snapshot,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
