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
    CharacterPackVersion,
    ReskinConfig,
    S09Correction,
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
    "ApprovalBlockedError",
    "ApprovalConflictError",
    "ApprovalNotFoundError",
    "ApprovalValidationError",
    "CheckpointIntegrity",
    "S09ApprovalIntegrityError",
    "S09ApprovalRecord",
    "S09ApprovalRepository",
]


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
