"""Durable targeted correction workflow + RECOMPUTE_OBJECTS job (S08-T05).

Implements the recompute side of the S08-T05 dependency/invalidation graph
(packet DESIGN.md — normative) on top of the approved DURABLE_JOB_CONTRACT
V1.1:

- **Impact** (:func:`compute_correction_impact`) is the read-only
  pre-confirmation scope report (exact affected sets, no writes).

- **The RECOMPUTE_OBJECTS durable Job** (:func:`recompute_objects_handler`)
  regenerates ONLY the invalidated derived state of one correction:
  grouping suggestions for pairs containing an affected role (only when the
  correction superseded real pending rows) and the derived thumbnail/mask
  artifacts of the affected DISCOVER candidate roles — derived
  deterministically from the CURRENT occurrence geometry
  (``_crop_thumbnail`` / ``_mask_png``, the same real algorithm as the
  T02 deterministic extractor).  Unaffected rows/files are never touched.

- **Durable contracts**: per-phase checkpoints (input fingerprint ->
  recompute -> staged -> published) with replay-safe publication
  (job-scoped deterministic artifact ids), cancel observed at every phase
  (drain leaves zero rows/files), staging GC of own + predecessor
  ``*.staging`` partials, one publication transaction, and an
  ``output_validator`` that re-verifies every declared row/file before the
  worker's completion gate — ``completed`` is impossible with a partial or
  orphaned output set.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update

from app.persistence.artifacts import ArtifactWriteError, ManagedPathError, ManagedRoot, hash_file
from app.persistence.models import (
    REMOVAL_ONLY_KINDS,
    Artifact,
    ArtifactOwner,
    ObjectOccurrence,
    ObjectRole,
    ObjectRoleArtifact,
    VideoItem,
)
from app.persistence.object_correction import (
    JOB_TYPE_RECOMPUTE_OBJECTS,
    CorrectionImpact,
    ObjectCorrectionRepository,
)
from app.persistence.object_grouping import ObjectGroupingRepository
from app.services.object_extraction import (
    ARTIFACT_PURPOSE_CANDIDATE_MASK,
    ARTIFACT_PURPOSE_CANDIDATE_THUMBNAIL,
    ARTIFACT_PURPOSE_RESULT_MANIFEST,
    CODE_CANCELLED,
    CODE_PATH_CONTAINMENT,
    CODE_PUBLICATION_FAILED,
    CODE_VIDEO_ITEM_NOT_FOUND,
    ExtractionError,
    _crop_thumbnail,
    _mask_png,
    _sha256_hex,
)
from app.services.object_grouping import (
    DEFAULT_GROUPING_ALGORITHM,
    DEFAULT_GROUPING_ALGORITHM_VERSION,
    OccurrenceEvidence,
    RoleEvidence,
    generate_pair_suggestions,
)
from app.workflow.durable_worker import WorkerContext

__all__ = [
    "CODE_CORRECTION_NOT_FOUND",
    "CODE_ROLE_CHANGED",
    "CODE_ROLE_NOT_FOUND",
    "CorrectionJobError",
    "RECOMPUTE_SCHEMA_VERSION",
    "compute_correction_impact",
    "recompute_objects_handler",
    "register_recompute_objects_handler",
]

#: Schema version of the recompute checkpoint/result manifest.
RECOMPUTE_SCHEMA_VERSION = 1

#: Test synchronization seam (None in production — zero overhead): when set,
#: the handler calls it between phases so tests can block the REAL handler
#: at a deterministic point to exercise the durable cancel/restart timing
#: (the same pattern as the T02 blocking-provider hook; never a mock).
PHASE_HOOK: Callable[[str], None] | None = None


def _phase_hook(phase: str) -> None:
    if PHASE_HOOK is not None:
        PHASE_HOOK(phase)

CODE_CORRECTION_NOT_FOUND = "CORRECTION_NOT_FOUND"
CODE_ROLE_NOT_FOUND = "ROLE_NOT_FOUND"
CODE_ROLE_CHANGED = "ROLE_CHANGED"

_CORRECTION_ACTIONS: dict[str, str] = {
    CODE_CORRECTION_NOT_FOUND: (
        "Không tìm thấy bản ghi chỉnh sửa tương ứng. Hãy tạo lại chỉnh sửa "
        "rồi thử lại."
    ),
    CODE_ROLE_NOT_FOUND: (
        "Một vai trò trong phạm vi chỉnh sửa không còn tồn tại. Hãy kiểm tra "
        "lại thư viện đối tượng rồi thử lại."
    ),
    CODE_ROLE_CHANGED: (
        "Vai trò đã thay đổi sau khi công việc tính toán lại được tạo (có "
        "chỉnh sửa mới hơn). Hãy tạo chỉnh sửa mới cho trạng thái hiện tại."
    ),
}


class CorrectionJobError(ExtractionError):
    """Stable correction-job failure (adds correction-specific actions)."""

    def action(self) -> str:
        return _CORRECTION_ACTIONS.get(self.code, super().action())


def compute_correction_impact(
    session: Any,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    correction_type: str,
    request: dict[str, Any],
) -> CorrectionImpact:
    """Read-only impacted-scope computation (no durable writes)."""
    return ObjectCorrectionRepository(session).compute_impact(
        workspace_id, project_id, video_item_id, correction_type, request
    )


# ── handler plumbing (mirrors the approved T02 patterns) ────────────────────


def _managed_for(ctx: WorkerContext) -> ManagedRoot:
    return ManagedRoot(Path(str(ctx.input_manifest.get("managed_root") or "artifacts")))


def _raise_if_cancelled(ctx: WorkerContext, phase: str) -> None:
    if ctx.is_cancelled():
        raise CorrectionJobError(
            CODE_CANCELLED,
            f"object recompute cancelled before {phase} phase",
            location=f"phase:{phase}",
        )


def _remove_file(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _wrap_managed_errors(exc: ManagedPathError) -> CorrectionJobError:
    return CorrectionJobError(
        CODE_PATH_CONTAINMENT,
        f"managed path rejected: {exc}",
        location="managed path",
        details={"reason": str(exc)},
    )


def _predecessor_job_id(ctx: WorkerContext) -> str | None:
    if ctx.session_factory is None:
        return None
    try:
        from app.persistence.jobs import JobRepository

        with ctx.session_factory() as session:
            return JobRepository(session).get_job(ctx.job_id).predecessor_job_id
    except Exception:  # noqa: BLE001 - cleanup is best-effort
        return None


def _cleanup_staging_partials(ctx: WorkerContext, managed: ManagedRoot) -> None:
    root = managed.root
    dirs = [root / "staging" / ctx.job_id / ctx.step_code]
    predecessor = _predecessor_job_id(ctx)
    if predecessor is not None:
        dirs.append(root / "staging" / predecessor / ctx.step_code)
    for staging_dir in dirs:
        if not staging_dir.is_dir():
            continue
        for partial in staging_dir.glob("*.staging"):
            with contextlib.suppress(OSError):
                partial.unlink(missing_ok=True)


def _staging_relative_path(ctx: WorkerContext, name: str) -> str:
    return f"staging/{ctx.job_id}/{ctx.step_code}/{name}"


def _final_relative_path(ctx: WorkerContext, name: str) -> str:
    workspace_id = str(ctx.input_manifest.get("workspace_id") or "default")
    return f"artifacts/{workspace_id}/image/{ctx.job_id}/{ctx.step_code}/{name}"


def _association_id(ctx: WorkerContext, role_id: str, name: str) -> str:
    """Deterministic association id for a recompute media link (replay-safe)."""
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_OID,
            f"recompute:{ctx.job_id}:role:{role_id}:artifact:{name}",
        )
    )


def _artifact_id(ctx: WorkerContext, final_rel: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"recompute-objects:{ctx.job_id}:{final_rel}"))


def _fingerprint(roles: list[dict[str, Any]]) -> str:
    payload: list[Any] = []
    for role in sorted(roles, key=lambda item: str(item["role_id"])):
        payload.append(
            [
                role["role_id"],
                role["revision"],
                [
                    [
                        occ["scene_id"],
                        occ["frame_index"],
                        occ["bbox_x"],
                        occ["bbox_y"],
                        occ["bbox_w"],
                        occ["bbox_h"],
                        occ["confidence"],
                    ]
                    for occ in sorted(
                        role["occurrences"],
                        key=lambda item: (str(item["scene_id"]), int(item["frame_index"])),
                    )
                ],
            ]
        )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# ── handler ─────────────────────────────────────────────────────────────────


def recompute_objects_handler(ctx: WorkerContext) -> dict[str, Any]:
    """Execute one RECOMPUTE_OBJECTS run: input -> recompute -> stage -> publish.

    Restart/resume semantics: the input phase re-resolves the affected roles
    from the live database and computes their geometry fingerprint; a
    committed publication is replayed (verified row-by-row) only when the
    fingerprint is unchanged (a newer correction otherwise fails this stale
    job with ``ROLE_CHANGED``); cancel is observed at every phase.
    """
    managed = _managed_for(ctx)
    cp = ctx.checkpoint
    if not isinstance(cp, dict):
        cp = {"schema_version": RECOMPUTE_SCHEMA_VERSION}

    input_ev = _input_phase(ctx, cp)
    cp = {**cp, "input": input_ev, "phase": "input"}
    ctx.progress(15, "input resolved")

    published = cp.get("published")
    if isinstance(published, dict) and published.get("manifest_artifact_id"):
        if published.get("fingerprint") != input_ev["fingerprint"]:
            raise CorrectionJobError(
                CODE_ROLE_CHANGED,
                "affected roles changed after publication — a newer "
                "correction owns the current state",
                location="replay",
            )
        _verify_committed(ctx, managed, published)
        ctx.progress(100, "published (replayed)")
        return {"input": input_ev, "published": published}

    _raise_if_cancelled(ctx, "recompute")
    plan = _recompute_phase(ctx, input_ev)
    # The checkpoint carries ONLY the metadata payload (no binary bytes);
    # the full plan stays in memory for staging/publishing.
    cp = {**cp, "plan": _plan_meta(plan), "phase": "plan"}
    ctx.progress(45, "recompute plan derived")
    _phase_hook("recompute")

    staged = _stage_phase(ctx, managed, plan)
    cp = {**cp, "staged": staged, "phase": "staged"}
    ctx.write_checkpoint(cp)
    ctx.progress(75, "artifacts staged")

    published_out = _publish_phase(ctx, managed, input_ev, plan, staged, cp)
    ctx.progress(100, "recompute published")
    return {"input": input_ev, "published": published_out}


def _input_phase(ctx: WorkerContext, cp: dict[str, Any]) -> dict[str, Any]:
    """Resolve the affected roles + geometry fingerprint from the live DB.

    Every affected role must still be ACTIVE on the manifest's video item +
    generation — a role superseded by a newer correction fails this stale
    job with ``ROLE_CHANGED``.
    """
    _raise_if_cancelled(ctx, "input")
    if ctx.session_factory is None:
        raise CorrectionJobError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot resolve input",
            location="input phase",
        )
    manifest = ctx.input_manifest
    workspace_id = str(manifest["workspace_id"])
    project_id = str(manifest["project_id"])
    video_item_id = str(manifest["video_item_id"])
    generation = str(manifest["generation"])
    correction_id = str(manifest["correction_id"])
    affected_role_ids = [str(rid) for rid in manifest.get("affected_role_ids") or []]
    with ctx.session_factory() as session:
        from app.persistence.models import ObjectCorrection

        correction = session.get(ObjectCorrection, correction_id)
        if correction is None or correction.workspace_id != workspace_id:
            raise CorrectionJobError(
                CODE_CORRECTION_NOT_FOUND,
                f"correction {correction_id!r} not found in workspace",
                location="correction",
            )
        if correction.status != "applied":
            raise CorrectionJobError(
                CODE_CORRECTION_NOT_FOUND,
                f"correction {correction_id!r} is {correction.status}; recompute "
                "requires an applied correction",
                location="correction",
            )
        video = session.get(VideoItem, video_item_id)
        if video is None or video.project_id != project_id:
            raise CorrectionJobError(
                CODE_VIDEO_ITEM_NOT_FOUND,
                f"video item {video_item_id!r} not found under project {project_id!r}",
                location="video_item",
            )
        if video.width is None or video.height is None:
            raise CorrectionJobError(
                CODE_PUBLICATION_FAILED,
                "video item has no canonical dimensions; recompute cannot "
                "derive artifacts",
                location="video_item",
            )
        roles: list[dict[str, Any]] = []
        for role_id in affected_role_ids:
            role = session.get(ObjectRole, role_id)
            if (
                role is None
                or role.workspace_id != workspace_id
                or role.video_item_id != video_item_id
                or role.source_generation != generation
                or role.status not in ("suggested", "confirmed")
            ):
                raise CorrectionJobError(
                    CODE_ROLE_CHANGED,
                    f"affected role {role_id!r} is no longer active on this "
                    "video item + generation (superseded by a newer "
                    "correction or removed)",
                    location="object_role",
                    details={"role_id": role_id},
                )
            occurrences = session.scalars(
                select(ObjectOccurrence)
                .where(ObjectOccurrence.role_id == role_id)
                .order_by(ObjectOccurrence.scene_id, ObjectOccurrence.frame_index)
            ).all()
            roles.append(
                {
                    "role_id": role.id,
                    "name": role.name,
                    "revision": role.revision,
                    "source_job_id": role.source_job_id,
                    "occurrences": [
                        {
                            "scene_id": occ.scene_id,
                            "frame_index": occ.frame_index,
                            "bbox_x": occ.bbox_x,
                            "bbox_y": occ.bbox_y,
                            "bbox_w": occ.bbox_w,
                            "bbox_h": occ.bbox_h,
                            "confidence": occ.confidence,
                        }
                        for occ in occurrences
                    ],
                }
            )
    return {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "video_item_id": video_item_id,
        "generation": generation,
        "correction_id": correction_id,
        "video_width": video.width,
        "video_height": video.height,
        "roles": roles,
        "fingerprint": _fingerprint(roles),
        "resolved": True,
    }


def _plan_meta(plan: dict[str, Any]) -> dict[str, Any]:
    """Checkpoint-safe metadata copy of the recompute plan (NO binary bytes).

    The full plan (including the artifact bytes) stays in memory for
    staging/publishing; the checkpoint carries only the metadata payload —
    the same boundary the T02 handler enforces.
    """
    return {
        "suggestions": plan.get("suggestions") or [],
        "artifacts": [
            {
                key: value
                for key, value in artifact.items()
                if key != "bytes"
            }
            for artifact in plan.get("artifacts") or []
        ],
    }


def _union_bbox(occurrences: list[dict[str, Any]]) -> dict[str, int] | None:
    if not occurrences:
        return None
    xs = [int(occ["bbox_x"]) for occ in occurrences]
    ys = [int(occ["bbox_y"]) for occ in occurrences]
    rights = [int(occ["bbox_x"]) + max(0, int(occ["bbox_w"])) for occ in occurrences]
    bottoms = [int(occ["bbox_y"]) + max(0, int(occ["bbox_h"])) for occ in occurrences]
    return {
        "x": min(xs),
        "y": min(ys),
        "width": max(0, max(rights) - min(xs)),
        "height": max(0, max(bottoms) - min(ys)),
    }


def _recompute_phase(ctx: WorkerContext, input_ev: dict[str, Any]) -> dict[str, Any]:
    """Derive the exact recompute plan: suggestion pairs + artifact bytes.

    Suggestions: ONLY pairs where at least one role is affected (the pairs
    the invalidation removed) — regenerated from the CURRENT active roles
    via the same deterministic T03 algorithm.
    Artifacts: ONLY affected roles produced by a DISCOVER run
    (``source_job_id`` set) — derived from the CURRENT occurrence geometry
    via the same deterministic helpers as the T02 extractor.
    """
    manifest = ctx.input_manifest
    affected = {str(rid) for rid in manifest.get("affected_role_ids") or []}
    artifact_role_ids = [str(rid) for rid in manifest.get("artifact_role_ids") or []]

    if ctx.session_factory is None:
        raise CorrectionJobError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot derive recompute plan",
            location="recompute phase",
        )
    suggestion_plan: list[dict[str, Any]] = []
    if bool(manifest.get("regenerate_suggestions")):
        with ctx.session_factory() as session:
            active_roles = ObjectGroupingRepository(session).list_active_roles(
                str(input_ev["workspace_id"]),
                str(input_ev["project_id"]),
                str(input_ev["video_item_id"]),
                str(input_ev["generation"]),
            )
            evidence = [
                RoleEvidence(
                    role_id=record.id,
                    name=record.name,
                    kind=record.kind,
                    source_generation=record.source_generation,
                    occurrences=tuple(
                        OccurrenceEvidence(
                            scene_id=occ.scene_id,
                            frame_index=occ.frame_index,
                            time_ms=occ.time_ms,
                            bbox_x=occ.bbox_x,
                            bbox_y=occ.bbox_y,
                            bbox_w=occ.bbox_w,
                            bbox_h=occ.bbox_h,
                        )
                        for occ in (record.occurrences or [])
                    ),
                )
                for record in active_roles
            ]
        for pair in generate_pair_suggestions(
            evidence,
            removal_only_kinds=REMOVAL_ONLY_KINDS,
            algorithm=DEFAULT_GROUPING_ALGORITHM,
            algorithm_version=DEFAULT_GROUPING_ALGORITHM_VERSION,
        ):
            if affected.intersection(pair.role_ids):
                suggestion_plan.append(
                    {
                        "role_ids": list(pair.role_ids),
                        "confidence": pair.confidence,
                        "reasons": list(pair.reasons),
                        "algorithm": pair.algorithm,
                        "algorithm_version": pair.algorithm_version,
                    }
                )

    artifact_plan: list[dict[str, Any]] = []
    roles_by_id = {str(role["role_id"]): role for role in input_ev["roles"]}
    for role_id in artifact_role_ids:
        role = roles_by_id.get(role_id)
        if role is None or role.get("source_job_id") is None:
            continue
        bbox = _union_bbox(role["occurrences"])
        if bbox is None:
            continue
        width = max(1, int(input_ev["video_width"]))
        height = max(1, int(input_ev["video_height"]))
        thumb, tw, th = _crop_thumbnail(width, height, bbox)
        mask, mw, mh = _mask_png(width, height, bbox)
        safe = re.sub(r"[^A-Za-z0-9_-]", "", role_id)[:12] or "role"
        artifact_plan.append(
            {
                "role_id": role_id,
                "name": f"{safe}_thumbnail.png",
                "purpose": ARTIFACT_PURPOSE_CANDIDATE_THUMBNAIL,
                "bytes": thumb,
                "width": tw,
                "height": th,
            }
        )
        artifact_plan.append(
            {
                "role_id": role_id,
                "name": f"{safe}_mask.png",
                "purpose": ARTIFACT_PURPOSE_CANDIDATE_MASK,
                "bytes": mask,
                "width": mw,
                "height": mh,
            }
        )
    return {"suggestions": suggestion_plan, "artifacts": artifact_plan}


def _stage_phase(
    ctx: WorkerContext, managed: ManagedRoot, plan: dict[str, Any]
) -> list[dict[str, Any]]:
    """Write every recompute artifact via managed atomic writes."""
    staged: list[dict[str, Any]] = []
    _cleanup_staging_partials(ctx, managed)
    for artifact in plan["artifacts"]:
        if ctx.is_cancelled():
            for entry in staged:
                with contextlib.suppress(ManagedPathError, OSError):
                    _remove_file(managed.resolve(str(entry["staged_rel"])))
            raise CorrectionJobError(
                CODE_CANCELLED,
                "object recompute cancelled during staging; staged files removed",
                location="phase:staging",
            )
        name = str(artifact["name"])
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise CorrectionJobError(
                CODE_PATH_CONTAINMENT,
                f"artifact name {name!r} contains unsafe characters",
                location="artifact name",
            )
        raw = bytes(artifact["bytes"])
        sha256 = _sha256_hex(raw)
        size = len(raw)
        staged_rel = _staging_relative_path(ctx, name)
        try:
            written_sha, written_size = managed.atomic_write_bytes(
                staged_rel, raw, expected_sha256=sha256
            )
        except ManagedPathError as exc:
            raise _wrap_managed_errors(exc) from exc
        except ArtifactWriteError as exc:
            raise CorrectionJobError(
                CODE_PUBLICATION_FAILED,
                f"staging artifact {name!r} failed: {exc}",
                location="artifact (staging)",
            ) from exc
        if written_sha != sha256 or written_size != size:
            raise CorrectionJobError(
                CODE_PUBLICATION_FAILED,
                f"staged artifact {name!r} evidence mismatch",
                location="artifact (staging)",
                details={"sha256": written_sha, "size_bytes": written_size},
            )
        staged.append(
            {
                "name": name,
                "purpose": str(artifact["purpose"]),
                "role_id": str(artifact["role_id"]),
                "staged_rel": staged_rel,
                "sha256": sha256,
                "size_bytes": size,
                "width": int(artifact["width"]),
                "height": int(artifact["height"]),
            }
        )
    return staged


def _publish_phase(
    ctx: WorkerContext,
    managed: ManagedRoot,
    input_ev: dict[str, Any],
    plan: dict[str, Any],
    staged: list[dict[str, Any]],
    cp: dict[str, Any],
) -> dict[str, Any]:
    """Publish: atomic move + ONE transaction (artifacts + suggestions +
    manifest); replay-safe and cancel-free (no partial output).
    """
    if ctx.session_factory is None:
        raise CorrectionJobError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot publish",
            location="publish phase",
        )
    _raise_if_cancelled(ctx, "publish")

    published_files: list[dict[str, Any]] = []
    created_files: list[Path] = []
    try:
        for entry in staged:
            final_rel = _final_relative_path(ctx, str(entry["name"]))
            try:
                staged_path = managed.resolve(str(entry["staged_rel"]))
                final_path = managed.resolve(final_rel)
            except ManagedPathError as exc:
                raise _wrap_managed_errors(exc) from exc
            created = _publish_file(managed, staged_path, final_path, str(entry["sha256"]))
            if created:
                created_files.append(final_path)
            published_files.append({**entry, "final_rel": final_rel})
    except CorrectionJobError:
        for entry in staged:
            with contextlib.suppress(ManagedPathError, OSError):
                _remove_file(managed.resolve(str(entry["staged_rel"])))
        raise

    try:
        manifest_artifact_id, suggestion_ids = _publish_effect(
            ctx, managed, input_ev, plan, published_files
        )
    except Exception as exc:  # noqa: BLE001 - publication failures are permanent
        for entry in staged:
            with contextlib.suppress(ManagedPathError, OSError):
                _remove_file(managed.resolve(str(entry["staged_rel"])))
        for final_path in created_files:
            _remove_file(final_path)
        if isinstance(exc, CorrectionJobError):
            raise
        raise CorrectionJobError(
            CODE_PUBLICATION_FAILED,
            f"publication transaction failed: {exc}",
            location="artifact (publish step)",
            details={"error_type": type(exc).__name__},
        ) from exc

    for entry in staged:
        with contextlib.suppress(ManagedPathError, OSError):
            _remove_file(managed.resolve(str(entry["staged_rel"])))

    published = {
        "manifest_artifact_id": manifest_artifact_id,
        "manifest_rel": _final_relative_path(ctx, "result.json"),
        "fingerprint": input_ev["fingerprint"],
        "files": published_files,
        "suggestion_ids": suggestion_ids,
    }
    ctx.write_checkpoint({**cp, "published": published, "phase": "published"})
    return published


def _publish_file(managed: ManagedRoot, staged_path: Path, final_path: Path, sha256: str) -> bool:
    """Atomically move a staged file into its final managed path (T02 pattern)."""
    if final_path.exists():
        if hash_file(final_path) != sha256:
            raise CorrectionJobError(
                CODE_PUBLICATION_FAILED,
                "final file exists but does not match the recorded sha256",
                location="artifact (publish step)",
                details={"expected_sha256": sha256},
            )
        _remove_file(staged_path)
        return False
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staged_path, final_path)
    except OSError as exc:
        raise CorrectionJobError(
            CODE_PUBLICATION_FAILED,
            f"atomic rename into final path failed: {exc}",
            location="artifact (publish step)",
        ) from exc
    return True


def _publish_effect(
    ctx: WorkerContext,
    managed: ManagedRoot,
    input_ev: dict[str, Any],
    plan: dict[str, Any],
    published_files: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """Persist artifact rows + owners + suggestion rows + manifest in ONE txn."""
    if ctx.session_factory is None:
        raise CorrectionJobError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot persist publication",
            location="publish phase",
        )
    workspace_id = str(input_ev["workspace_id"])
    project_id = str(input_ev["project_id"])
    video_item_id = str(input_ev["video_item_id"])
    generation = str(input_ev["generation"])
    suggestion_ids: list[str] = []
    with ctx.session_factory() as session:
        for entry in published_files:
            artifact_id = _artifact_id(ctx, str(entry["final_rel"]))
            artifact = session.get(Artifact, artifact_id)
            if artifact is None:
                session.add(
                    Artifact(
                        id=artifact_id,
                        workspace_id=workspace_id,
                        kind="image",
                        relative_path=str(entry["final_rel"]),
                        state="ready",
                        sha256=str(entry["sha256"]),
                        size_bytes=int(entry["size_bytes"]),
                        mime_type="image/png",
                        width=int(entry["width"]),
                        height=int(entry["height"]),
                    )
                )
            else:
                if (
                    artifact.sha256 != str(entry["sha256"])
                    or artifact.size_bytes != int(entry["size_bytes"])
                ):
                    raise CorrectionJobError(
                        CODE_PUBLICATION_FAILED,
                        f"existing artifact row conflicts with the staged "
                        f"evidence ({entry['name']!r})",
                        location="artifact (publish step)",
                        details={"artifact_id": artifact_id},
                    )
                if artifact.state != "ready":
                    artifact.state = "ready"
            owner = session.get(
                ArtifactOwner,
                (artifact_id, "video_item", video_item_id, str(entry["purpose"])),
            )
            if owner is None:
                session.add(
                    ArtifactOwner(
                        artifact_id=artifact_id,
                        owner_type="video_item",
                        owner_id=video_item_id,
                        purpose=str(entry["purpose"]),
                    )
                )

        # S08-T05-C1 (finding D1): REPLACE the affected roles' media links.
        # Each published thumbnail/mask of an affected role gets a NEW
        # ObjectRoleArtifact row (deterministic id, recompute job as source);
        # every previously ACTIVE association of the same (role, purpose) is
        # superseded via the self-FK — old rows stay auditable, resolution
        # ("newest valid") is superseded_by_id IS NULL.
        associations: list[dict[str, Any]] = []
        for entry in published_files:
            role_id = str(entry.get("role_id") or "")
            purpose = str(entry.get("purpose") or "")
            if not role_id or purpose not in (
                ARTIFACT_PURPOSE_CANDIDATE_THUMBNAIL,
                ARTIFACT_PURPOSE_CANDIDATE_MASK,
            ):
                continue
            artifact_id = _artifact_id(ctx, str(entry["final_rel"]))
            association_id = _association_id(ctx, role_id, str(entry["name"]))
            existing_assoc = session.get(ObjectRoleArtifact, association_id)
            if existing_assoc is None:
                session.add(
                    ObjectRoleArtifact(
                        id=association_id,
                        workspace_id=workspace_id,
                        role_id=role_id,
                        artifact_id=artifact_id,
                        purpose=purpose,
                        source_generation=generation,
                        source_job_id=ctx.job_id,
                    )
                )
            else:
                if (
                    existing_assoc.role_id != role_id
                    or existing_assoc.artifact_id != artifact_id
                    or existing_assoc.purpose != purpose
                    or existing_assoc.source_generation != generation
                    or existing_assoc.source_job_id != ctx.job_id
                ):
                    raise CorrectionJobError(
                        CODE_PUBLICATION_FAILED,
                        f"existing association {association_id!r} conflicts with "
                        "this recompute's evidence",
                        location="object_role_artifact (publish step)",
                        details={"association_id": association_id},
                    )
            # Supersede every other ACTIVE association of the same
            # (role, purpose) — replay-safe: already-superseded rows are
            # excluded by the IS NULL guard and keep their original target.
            session.execute(
                update(ObjectRoleArtifact)
                .where(
                    ObjectRoleArtifact.role_id == role_id,
                    ObjectRoleArtifact.purpose == purpose,
                    ObjectRoleArtifact.superseded_by_id.is_(None),
                    ObjectRoleArtifact.id != association_id,
                )
                .values(superseded_by_id=association_id)
            )
            # Deterministic on replay: list exactly the rows superseded BY
            # THIS association (re-run re-selects the same set — the manifest
            # bytes stay identical).
            superseded = session.execute(
                select(ObjectRoleArtifact.id).where(
                    ObjectRoleArtifact.superseded_by_id == association_id,
                )
            ).scalars().all()
            associations.append(
                {
                    "association_id": association_id,
                    "role_id": role_id,
                    "artifact_id": artifact_id,
                    "purpose": purpose,
                    "source_generation": generation,
                    "source_job_id": ctx.job_id,
                    "superseded_association_ids": [str(rid) for rid in superseded],
                }
            )

        grouping_repo = ObjectGroupingRepository(session)
        suggestion_rows: list[dict[str, Any]] = []
        for pair in plan["suggestions"]:
            record, created = grouping_repo.create_suggestion(
                workspace_id,
                project_id,
                video_item_id,
                generation,
                list(pair["role_ids"]),
                float(pair["confidence"]),
                list(pair["reasons"]),
                str(pair["algorithm"]),
                str(pair["algorithm_version"]),
            )
            suggestion_ids.append(record.id)
            suggestion_rows.append(
                {
                    "suggestion_id": record.id,
                    "role_ids": list(record.role_ids),
                    "confidence": record.confidence,
                    "reasons": list(record.reasons),
                    "created": created,
                }
            )

        manifest_bytes = json.dumps(
            {
                "schema_version": RECOMPUTE_SCHEMA_VERSION,
                "job_id": ctx.job_id,
                "correction_id": input_ev["correction_id"],
                "video_item_id": video_item_id,
                "source_generation": generation,
                "fingerprint": input_ev["fingerprint"],
                "roles": [
                    {
                        "role_id": role["role_id"],
                        "name": role["name"],
                        "artifacts": [
                            {
                                "name": entry["name"],
                                "purpose": entry["purpose"],
                                "sha256": entry["sha256"],
                                "size_bytes": entry["size_bytes"],
                                "width": entry["width"],
                                "height": entry["height"],
                            }
                            for entry in published_files
                            if entry.get("role_id") == role["role_id"]
                        ],
                    }
                    for role in input_ev["roles"]
                ],
                "suggestions": suggestion_rows,
                "associations": associations,
            },
            sort_keys=True,
        ).encode("utf-8")
        manifest_rel = _final_relative_path(ctx, "result.json")
        manifest_sha = _sha256_hex(manifest_bytes)
        manifest_size = len(manifest_bytes)
        try:
            managed.atomic_write_bytes(
                manifest_rel, manifest_bytes, expected_sha256=manifest_sha
            )
        except ManagedPathError as exc:
            raise _wrap_managed_errors(exc) from exc
        except ArtifactWriteError as exc:
            raise CorrectionJobError(
                CODE_PUBLICATION_FAILED,
                f"writing the result manifest failed: {exc}",
                location="artifact (manifest)",
            ) from exc
        manifest_artifact_id = _artifact_id(ctx, manifest_rel)
        manifest_row = session.get(Artifact, manifest_artifact_id)
        if manifest_row is None:
            session.add(
                Artifact(
                    id=manifest_artifact_id,
                    workspace_id=workspace_id,
                    kind="document",
                    relative_path=manifest_rel,
                    state="ready",
                    sha256=manifest_sha,
                    size_bytes=manifest_size,
                    mime_type="application/json",
                )
            )
        else:
            if manifest_row.sha256 != manifest_sha or manifest_row.size_bytes != manifest_size:
                raise CorrectionJobError(
                    CODE_PUBLICATION_FAILED,
                    "existing manifest artifact row conflicts with the staged evidence",
                    location="artifact (manifest)",
                )
            if manifest_row.state != "ready":
                manifest_row.state = "ready"
        owner = session.get(
            ArtifactOwner,
            (manifest_artifact_id, "video_item", video_item_id, ARTIFACT_PURPOSE_RESULT_MANIFEST),
        )
        if owner is None:
            session.add(
                ArtifactOwner(
                    artifact_id=manifest_artifact_id,
                    owner_type="video_item",
                    owner_id=video_item_id,
                    purpose=ARTIFACT_PURPOSE_RESULT_MANIFEST,
                )
            )
        session.commit()
    return manifest_artifact_id, suggestion_ids


def _verify_committed(
    ctx: WorkerContext, managed: ManagedRoot, published: dict[str, Any]
) -> None:
    """Re-verify a committed publication row-by-row (replay gate)."""
    if ctx.session_factory is None:
        raise CorrectionJobError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot verify publication",
            location="replay",
        )
    manifest_artifact_id = str(published["manifest_artifact_id"])
    with ctx.session_factory() as session:
        manifest_row = session.get(Artifact, manifest_artifact_id)
        if manifest_row is None or manifest_row.state != "ready":
            raise CorrectionJobError(
                CODE_PUBLICATION_FAILED,
                "manifest artifact row missing or not ready on replay",
                location="replay",
                details={"artifact_id": manifest_artifact_id},
            )
        target = managed.resolve(str(published["manifest_rel"]))
        if not target.is_file() or hash_file(target) != manifest_row.sha256:
            raise CorrectionJobError(
                CODE_PUBLICATION_FAILED,
                "manifest file missing or corrupt on replay",
                location="replay",
            )
        for entry in published.get("files") or []:
            row = session.get(Artifact, _artifact_id(ctx, str(entry["final_rel"])))
            if row is None or row.state != "ready" or row.sha256 != str(entry["sha256"]):
                raise CorrectionJobError(
                    CODE_PUBLICATION_FAILED,
                    f"published artifact row {entry['name']!r} missing or "
                    "inconsistent on replay",
                    location="replay",
                    details={"artifact_id": _artifact_id(ctx, str(entry["final_rel"]))},
                )
            final = managed.resolve(str(entry["final_rel"]))
            if not final.is_file() or hash_file(final) != row.sha256:
                raise CorrectionJobError(
                    CODE_PUBLICATION_FAILED,
                    f"published artifact file {entry['name']!r} missing or "
                    "corrupt on replay",
                    location="replay",
                )
        for suggestion_id in published.get("suggestion_ids") or []:
            from app.persistence.models import ObjectGroupingSuggestion

            if session.get(ObjectGroupingSuggestion, suggestion_id) is None:
                raise CorrectionJobError(
                    CODE_PUBLICATION_FAILED,
                    f"published suggestion row {suggestion_id!r} missing on replay",
                    location="replay",
                )
        # S08-T05-C1: every declared media link must exist and be the ONLY
        # ACTIVE association of its (role, purpose) — the superseded set must
        # point back at the new association (auditable lineage, no orphans).
        for assoc_meta in published.get("associations") or []:
            association_id = str(assoc_meta["association_id"])
            assoc = session.get(ObjectRoleArtifact, association_id)
            if assoc is None or assoc.source_job_id != ctx.job_id:
                raise CorrectionJobError(
                    CODE_PUBLICATION_FAILED,
                    f"published association {association_id!r} missing on replay",
                    location="replay",
                    details={"association_id": association_id},
                )
            if assoc.superseded_by_id is not None:
                raise CorrectionJobError(
                    CODE_PUBLICATION_FAILED,
                    f"published association {association_id!r} is itself "
                    "superseded on replay",
                    location="replay",
                    details={"association_id": association_id},
                )
            active = session.scalar(
                select(func.count(ObjectRoleArtifact.id)).where(
                    ObjectRoleArtifact.role_id == assoc.role_id,
                    ObjectRoleArtifact.purpose == assoc.purpose,
                    ObjectRoleArtifact.superseded_by_id.is_(None),
                )
            )
            if active != 1:
                raise CorrectionJobError(
                    CODE_PUBLICATION_FAILED,
                    f"role {assoc.role_id!r} purpose {assoc.purpose!r} has "
                    f"{active} active associations (expected exactly 1)",
                    location="replay",
                    details={"association_id": association_id},
                )
            for old_id in assoc_meta.get("superseded_association_ids") or []:
                old_assoc = session.get(ObjectRoleArtifact, str(old_id))
                if (
                    old_assoc is None
                    or old_assoc.superseded_by_id != association_id
                ):
                    raise CorrectionJobError(
                        CODE_PUBLICATION_FAILED,
                        f"superseded association {old_id!r} missing or not "
                        "pointing at the replacement on replay",
                        location="replay",
                        details={"association_id": association_id, "old_id": old_id},
                    )


def _validate_recompute_outputs(
    ctx: WorkerContext, result: dict[str, Any], staging_dir: Path
) -> dict[str, Any]:
    """Completion gate: verify every declared row/file; no orphan files.

    A missing/corrupt row or file raises => the Job fails — ``completed``
    is impossible until all declared outputs are committed and validated,
    and every managed file under the job's final path must equal an
    artifact row (no-orphan invariant).  The gate reads the handler's
    RESULT (the committed publication payload), never the pre-run
    checkpoint.
    """
    managed = _managed_for(ctx)
    workspace_id = str(ctx.input_manifest.get("workspace_id") or "default")
    final_dir = managed.resolve(
        f"artifacts/{workspace_id}/image/{ctx.job_id}/{ctx.step_code}"
    )
    published = result.get("published") if isinstance(result, dict) else None
    if not isinstance(published, dict) or not published.get("manifest_artifact_id"):
        raise CorrectionJobError(
            CODE_PUBLICATION_FAILED,
            "no committed publication recorded for the completion gate",
            location="output validator",
        )
    if ctx.session_factory is None:
        raise CorrectionJobError(
            CODE_PUBLICATION_FAILED,
            "worker context has no session factory; cannot validate outputs",
            location="output validator",
        )
    with ctx.session_factory() as session:
        manifest_row = session.get(
            Artifact, str(published["manifest_artifact_id"])
        )
        if manifest_row is None or manifest_row.state != "ready":
            raise CorrectionJobError(
                CODE_PUBLICATION_FAILED,
                "manifest artifact row missing at completion",
                location="output validator",
            )
        declared: dict[str, str] = {}
        if published.get("manifest_rel"):
            declared[str(published["manifest_rel"])] = manifest_row.sha256 or ""
        for entry in published.get("files") or []:
            row = session.get(Artifact, _artifact_id(ctx, str(entry["final_rel"])))
            if row is None or row.state != "ready" or row.sha256 != str(entry["sha256"]):
                raise CorrectionJobError(
                    CODE_PUBLICATION_FAILED,
                    f"artifact row {entry['name']!r} missing/inconsistent at completion",
                    location="output validator",
                )
            declared[str(entry["final_rel"])] = row.sha256 or ""
        # No-orphan invariant: every managed file under the final path is a
        # declared row; declared rows must exist on disk with matching hash.
        if final_dir.is_dir():
            for file_path in final_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                rel = managed.relative_path_of(file_path)
                if rel not in declared:
                    raise CorrectionJobError(
                        CODE_PUBLICATION_FAILED,
                        f"orphan managed file {rel} has no artifact row",
                        location="output validator",
                    )
        for rel, sha in declared.items():
            target = managed.resolve(rel)
            if not target.is_file() or hash_file(target) != sha:
                raise CorrectionJobError(
                    CODE_PUBLICATION_FAILED,
                    f"declared artifact file {rel} missing/corrupt at completion",
                    location="output validator",
                )
        for suggestion_id in published.get("suggestion_ids") or []:
            from app.persistence.models import ObjectGroupingSuggestion

            if session.get(ObjectGroupingSuggestion, suggestion_id) is None:
                raise CorrectionJobError(
                    CODE_PUBLICATION_FAILED,
                    f"declared suggestion row {suggestion_id!r} missing at completion",
                    location="output validator",
                )
        # Staging must be drained (no leftover partials of this job).
        for leftover in staging_dir.rglob("*"):
            if leftover.is_file():
                raise CorrectionJobError(
                    CODE_PUBLICATION_FAILED,
                    f"staging not drained at completion: {leftover.name}",
                    location="output validator",
                )
    return {}


def register_recompute_objects_handler(worker: Any) -> None:
    """Register the RECOMPUTE_OBJECTS handler + strict output gate."""
    worker.register_handler(
        JOB_TYPE_RECOMPUTE_OBJECTS,
        recompute_objects_handler,
        output_validator=_validate_recompute_outputs,
        resource_class="cpu_light",
    )
