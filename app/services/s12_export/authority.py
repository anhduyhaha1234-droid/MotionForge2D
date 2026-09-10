"""S12-T01 server-owned export authority (C2, closes F02).

Read-only durable resolution of the CURRENT approved Full Apply authority
for one export preflight.  Every identity the export may render from is
resolved SERVER-SIDE here — never trusted from the client:

- workspace/project/video containment;
- frozen checkpoint pin (row present, same workspace+project, hash and
  revision equal — config/pack binding is verified through the checkpoint's
  reskin_config row);
- structural-lock manifest pin (row present, same video/project/generation,
  hash equal, status draft|active);
- immutable CURRENT completed Full Apply output: the newest completed
  publication of the newest completed ``S10FullApplyRun`` for the video;
  its artifact row must be ``ready``, carry a 64-hex sha256 and never be a
  ``.partial`` file.  Without it the export is refused — an original import
  is never exported "by accident";
- source/audio identity + origin: the approved output artifact IS the
  export source; ``native_4k`` is claimed ONLY when the video's own canvas
  is exactly 3840x2160 AND the approved output exists with measured
  rational timing (publication frame metadata fps_num/fps_den).  A bare
  3840x2160 import that never passed Full Apply, or a publication lacking
  measured timing, stays ``upscale_4k``/``unproven`` (fail-closed
  uncertainty: an artifact SHA plus dimensions is not native-origin proof).

Zero mutation: this module only reads.  No render decision is made here —
``preflight.evaluate_preflight`` turns the resolved facts into the frozen
verdict.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import (
    ApplyCheckpoint,
    Artifact,
    Project,
    ReskinConfig,
    StructuralLockManifest,
    S10FullApplyRun,
    S12ExportRun,
    VideoItem,
    Workspace,
)
from app.persistence.s10_full_apply import S10ApplyRepository

MASTER_WIDTH = 3840
MASTER_HEIGHT = 2160

__all__ = [
    "ExportAuthorityCheck",
    "ExportAuthority",
    "ExportContext",
    "resolve_export_context",
    "resolve_export_authority",
]


@dataclass(frozen=True)
class ExportAuthorityCheck:
    """One named authority bind result (mirrors preflight check shape)."""

    name: str
    passed: bool
    reason: str
    detail: str


@dataclass(frozen=True)
class ExportAuthority:
    """Server-resolved durable facts + per-bind verdicts (F02 authority).

    ``resolved`` is True ONLY when every bind passes AND the immutable
    current completed Full Apply output artifact was resolved.  Fields are
    the ACTUAL durable server identities consumers (T03A/B/C, T04A, T05)
    must pin into run/job/result records.
    """

    # ── containment ─────────────────────────────────────────────────
    workspace_id: str
    project_id: str
    video_item_id: str
    project_ok: bool = False
    video_ok: bool = False
    # ── pins ────────────────────────────────────────────────────────
    checkpoint_ok: bool = False
    checkpoint_id: str | None = None
    checkpoint_hash: str | None = None
    checkpoint_revision: int | None = None
    config_ok: bool = False  # reskin_config + pack_version binding
    lock_ok: bool = False
    lock_manifest_id: str | None = None
    lock_manifest_hash: str | None = None
    # ── immutable current completed Full Apply authority ────────────
    full_apply_ok: bool = False
    full_apply_run_id: str | None = None
    full_apply_publication_id: str | None = None
    source_artifact_id: str | None = None
    source_sha256: str | None = None
    source_relative_path: str | None = None
    source_state: str | None = None
    source_partial: bool = False
    source_frame_count: int | None = None
    source_fps_num: int | None = None
    source_fps_den: int | None = None
    # ── source canvas + origin (never previously-upscaled as native) ─
    source_width: int | None = None
    source_height: int | None = None
    source_origin: str = "unproven"  # proved-native | upscale | unproven
    # ── aggregate ───────────────────────────────────────────────────
    checks: tuple[ExportAuthorityCheck, ...] = field(default_factory=tuple)
    resolved: bool = False

    @property
    def failed_reasons(self) -> list[str]:
        return [c.reason for c in self.checks if not c.passed and c.reason != "S12_EXPORT_OK"]


@dataclass(frozen=True)
class ExportContext:
    """Server-owned context for the normal Export product entry point.

    The context is a read-only snapshot.  It exposes durable identities needed
    by the frozen preflight contract, but never exposes a source or output
    filesystem path.  ``context_revision`` lets submit/retry reject a stale
    browser snapshot after a new Full Apply or lock supersedes it.
    """

    workspace_id: str
    project_id: str
    video_item_id: str
    project_name: str | None = None
    video_title: str | None = None
    video_status: str | None = None
    video_width: int | None = None
    video_height: int | None = None
    video_duration_ms: int | None = None
    video_fps_num: int | None = None
    video_fps_den: int | None = None
    checkpoint_id: str | None = None
    checkpoint_hash: str | None = None
    checkpoint_revision: int | None = None
    manifest_id: str | None = None
    manifest_hash: str | None = None
    manifest_generation: str | None = None
    plan_id: str | None = None
    plan_hash: str | None = None
    frame_count: int | None = None
    fps_num: int | None = None
    fps_den: int | None = None
    chunk_config: dict[str, Any] = field(default_factory=dict)
    full_apply_run_id: str | None = None
    full_apply_status: str | None = None
    current_run_id: str | None = None
    current_run_status: str | None = None
    current_run_attempt: int | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def context_revision(self) -> str:
        material = {
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "video_item_id": self.video_item_id,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_hash": self.checkpoint_hash,
            "checkpoint_revision": self.checkpoint_revision,
            "manifest_id": self.manifest_id,
            "manifest_hash": self.manifest_hash,
            "manifest_generation": self.manifest_generation,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "frame_count": self.frame_count,
            "fps_num": self.fps_num,
            "fps_den": self.fps_den,
            "full_apply_run_id": self.full_apply_run_id,
        }
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


def _sha64(value: Any) -> str:
    return str(value or "").lower() if value else ""


def resolve_export_context(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
) -> ExportContext:
    """Resolve the current project/video export context without mutation.

    Full Apply is the source of the current checkpoint and render plan.  The
    current active/draft structural lock is resolved in the same scope.  A
    context with missing authorities is still returned so the UI can show the
    server-owned reason rather than asking a user to manufacture a pin.
    """
    project = session.get(Project, project_id)
    video = session.get(VideoItem, video_item_id) if project is not None else None
    if project is None or str(project.workspace_id) != workspace_id:
        return ExportContext(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            reasons=("S12_EXPORT_UNKNOWN_PROJECT",),
        )
    if video is None or str(video.project_id) != project_id:
        return ExportContext(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            project_name=str(project.name),
            reasons=("S12_EXPORT_UNKNOWN_VIDEO",),
        )

    reasons: list[str] = []
    full_apply = session.scalar(
        select(S10FullApplyRun)
        .where(
            S10FullApplyRun.workspace_id == workspace_id,
            S10FullApplyRun.project_id == project_id,
            S10FullApplyRun.video_item_id == video_item_id,
            S10FullApplyRun.status == "completed",
        )
        .order_by(S10FullApplyRun.created_at.desc(), S10FullApplyRun.id.desc())
    )
    checkpoint = session.get(ApplyCheckpoint, full_apply.apply_checkpoint_id) if full_apply else None
    if full_apply is None:
        reasons.append("S12_EXPORT_FULL_APPLY_MISSING")
    elif checkpoint is None:
        reasons.append("S12_EXPORT_STALE_CHECKPOINT")

    manifest = None
    if checkpoint is not None and checkpoint.structural_lock_manifest_id:
        manifest = session.get(StructuralLockManifest, checkpoint.structural_lock_manifest_id)
        if manifest is not None and (
            str(manifest.workspace_id) != workspace_id
            or str(manifest.project_id) != project_id
            or str(manifest.video_item_id) != video_item_id
            or manifest.status not in ("draft", "active")
        ):
            manifest = None
    if manifest is None:
        manifest = session.scalar(
            select(StructuralLockManifest)
            .where(
                StructuralLockManifest.workspace_id == workspace_id,
                StructuralLockManifest.project_id == project_id,
                StructuralLockManifest.video_item_id == video_item_id,
                StructuralLockManifest.status.in_(("draft", "active")),
            )
            .order_by(
                StructuralLockManifest.version.desc(),
                StructuralLockManifest.created_at.desc(),
                StructuralLockManifest.id.desc(),
            )
        )
    if manifest is None:
        reasons.append("S12_EXPORT_LOCK_MISSING")

    current_run = session.scalar(
        select(S12ExportRun)
        .where(
            S12ExportRun.workspace_id == workspace_id,
            S12ExportRun.project_id == project_id,
            S12ExportRun.video_item_id == video_item_id,
        )
        .order_by(S12ExportRun.created_at.desc(), S12ExportRun.id.desc())
    )
    chunk_config: dict[str, Any] = {}
    if full_apply is not None:
        try:
            parsed = json.loads(full_apply.chunk_config_json)
            if isinstance(parsed, dict):
                chunk_config = parsed
        except (TypeError, ValueError):
            reasons.append("S12_EXPORT_SOURCE_STALE")

    return ExportContext(
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        project_name=str(project.name),
        video_title=str(video.title),
        video_status=str(video.status),
        video_width=int(video.width) if video.width else None,
        video_height=int(video.height) if video.height else None,
        video_duration_ms=int(video.duration_ms) if video.duration_ms is not None else None,
        video_fps_num=int(video.fps_num) if video.fps_num else None,
        video_fps_den=int(video.fps_den) if video.fps_den else None,
        checkpoint_id=str(full_apply.apply_checkpoint_id) if full_apply else None,
        checkpoint_hash=_sha64(full_apply.apply_checkpoint_hash) if full_apply else None,
        checkpoint_revision=int(full_apply.apply_checkpoint_revision) if full_apply else None,
        manifest_id=str(manifest.id) if manifest else None,
        manifest_hash=_sha64(manifest.manifest_hash) if manifest else None,
        manifest_generation=str(manifest.source_generation) if manifest else None,
        plan_id=str(full_apply.plan_id) if full_apply else None,
        plan_hash=_sha64(full_apply.plan_hash) if full_apply else None,
        frame_count=int(full_apply.frame_count) if full_apply else None,
        fps_num=int(full_apply.fps_num) if full_apply and full_apply.fps_num else None,
        fps_den=int(full_apply.fps_den) if full_apply and full_apply.fps_den else None,
        chunk_config=chunk_config,
        full_apply_run_id=str(full_apply.id) if full_apply else None,
        full_apply_status=str(full_apply.status) if full_apply else None,
        current_run_id=str(current_run.id) if current_run else None,
        current_run_status=str(current_run.status) if current_run else None,
        current_run_attempt=int(current_run.attempt) if current_run else None,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def resolve_export_authority(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    checkpoint_id: str,
    checkpoint_hash: str,
    checkpoint_revision: int,
    manifest_id: str,
    manifest_hash: str,
    manifest_generation: str,
) -> ExportAuthority:
    """Resolve every server-owned authority bind (read-only, fail-closed).

    Never raises for a missing/stale bind: each failure is returned as a
    check with its frozen reason so callers can map HTTP/verdict
    consistently.  Raises only on unexpected infrastructure errors.
    """
    checks: list[ExportAuthorityCheck] = []
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        return ExportAuthority(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            checks=(ExportAuthorityCheck("workspace", False, "S12_EXPORT_UNKNOWN_PROJECT", "workspace missing"),),
        )

    project = session.get(Project, project_id)
    project_ok = project is not None and str(project.workspace_id) == workspace_id
    checks.append(
        ExportAuthorityCheck(
            "project",
            project_ok,
            "S12_EXPORT_OK" if project_ok else "S12_EXPORT_UNKNOWN_PROJECT",
            "project in workspace" if project_ok else "project missing or wrong workspace",
        )
    )
    video = session.get(VideoItem, video_item_id) if project_ok else None
    video_ok = video is not None and str(video.project_id) == project_id
    checks.append(
        ExportAuthorityCheck(
            "video",
            video_ok,
            "S12_EXPORT_OK" if video_ok else "S12_EXPORT_UNKNOWN_VIDEO",
            "video in project" if video_ok else "video missing or wrong project",
        )
    )
    if not (project_ok and video_ok):
        return ExportAuthority(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video_item_id,
            project_ok=project_ok,
            video_ok=video_ok,
            checks=tuple(checks),
        )

    # ── checkpoint pin (workspace + project + hash + revision) ──────
    ckpt = session.get(ApplyCheckpoint, checkpoint_id)
    ckpt_ok = False
    ckpt_row_hash: str | None = None
    ckpt_row_rev: int | None = None
    config_ok = False
    if ckpt is not None and str(ckpt.workspace_id) == workspace_id:
        if str(ckpt.project_id) == project_id:
            ckpt_row_hash = _sha64(ckpt.checkpoint_hash)
            ckpt_row_rev = int(ckpt.reskin_config_revision)
            ckpt_ok = (
                ckpt_row_hash == checkpoint_hash.lower()
                and ckpt_row_rev == int(checkpoint_revision)
            )
            if ckpt_ok:
                # config/pack binding: checkpoint's reskin_config must exist
                # and carry the same revision (params/config identity).
                rc = session.get(ReskinConfig, ckpt.reskin_config_id) if ckpt.reskin_config_id else None
                config_ok = (
                    rc is not None
                    and str(rc.workspace_id) == workspace_id
                    and int(rc.revision) == ckpt_row_rev
                    and bool(rc.pack_version_id)
                )
    checks.append(
        ExportAuthorityCheck(
            "checkpoint",
            ckpt_ok,
            "S12_EXPORT_OK" if ckpt_ok else "S12_EXPORT_STALE_CHECKPOINT",
            "frozen checkpoint pin matches"
            if ckpt_ok
            else "checkpoint missing, cross-project, or hash/revision drift",
        )
    )
    checks.append(
        ExportAuthorityCheck(
            "config_pack",
            config_ok,
            "S12_EXPORT_OK" if config_ok else "S12_EXPORT_CONFIG_MISSING",
            "checkpoint reskin_config + pack binding present"
            if config_ok
            else "checkpoint config/pack binding missing or revision drift",
        )
    )
    # cross-project checkpoint is a distinct hard reason (route 409 domain)
    ckpt_cross = ckpt is not None and str(ckpt.project_id) != project_id
    if ckpt_cross:
        checks.append(
            ExportAuthorityCheck(
                "checkpoint_cross_project",
                False,
                "S12_EXPORT_CROSS_PROJECT",
                "checkpoint belongs to another project",
            )
        )

    # ── structural-lock manifest pin ────────────────────────────────
    manifest = session.scalar(
        select(StructuralLockManifest).where(
            StructuralLockManifest.id == manifest_id,
            StructuralLockManifest.workspace_id == workspace_id,
        )
    )
    lock_ok = False
    lock_hash: str | None = None
    if manifest is not None:
        lock_hash = _sha64(manifest.manifest_hash)
        lock_ok = (
            str(manifest.video_item_id) == video_item_id
            and str(manifest.project_id) == project_id
            and str(manifest.source_generation) == manifest_generation
            and lock_hash == manifest_hash.lower()
            and manifest.status in ("draft", "active")
        )
    checks.append(
        ExportAuthorityCheck(
            "structural_lock",
            lock_ok,
            "S12_EXPORT_OK" if lock_ok else "S12_EXPORT_LOCK_MISSING",
            "structural lock pin matches current generation"
            if lock_ok
            else "structural lock missing, cross-scope, or stale identity",
        )
    )

    # ── immutable CURRENT completed Full Apply output ───────────────
    # Newest completed run for this video; newest completed publication of
    # that run; publication must pin the SAME checkpoint as the request.
    fa_ok = False
    run_id: str | None = None
    pub_id: str | None = None
    artifact_id: str | None = None
    artifact_sha: str | None = None
    artifact_rel: str | None = None
    artifact_state: str | None = None
    artifact_partial = False
    frame_count: int | None = None
    fps_num: int | None = None
    fps_den: int | None = None
    repo = S10ApplyRepository(session)
    try:
        runs = [r for r in repo.list_runs(workspace_id, project_id=project_id) if r.video_item_id == video_item_id and r.status == "completed"]
        if runs:
            newest_run = runs[0]  # list_runs orders created_at desc
            pubs = [
                p
                for p in repo.list_publications(workspace_id, newest_run.id)
                if p.state == "completed"
            ]
            if pubs:
                pub = pubs[0]  # list_publications orders created_at desc
                if (
                    pub.checkpoint_id == checkpoint_id
                    and _sha64(pub.checkpoint_hash) == checkpoint_hash.lower()
                    and int(pub.checkpoint_revision) == int(checkpoint_revision)
                ):
                    art = session.get(Artifact, pub.artifact_id)
                    if art is not None and str(art.workspace_id) == workspace_id:
                        artifact_id = str(art.id)
                        artifact_sha = _sha64(art.sha256)
                        artifact_rel = str(art.relative_path or "")
                        artifact_state = str(art.state or "")
                        artifact_partial = ".partial" in artifact_rel
                        fa_ok = (
                            artifact_state == "ready"
                            and len(artifact_sha) == 64
                            and not artifact_partial
                        )
                        run_id = str(newest_run.id)
                        pub_id = str(pub.id)
                        frame_count = int(pub.frame_count)
                        fps_num = int(newest_run.fps_num) if newest_run.fps_num else None
                        fps_den = int(newest_run.fps_den) if newest_run.fps_den else None
                        if fps_num is None or fps_den is None:
                            # fall back to publication frame metadata (measured)
                            fm = pub.frame_metadata or {}
                            fps_num = int(fm.get("fps_num") or 0) or None
                            fps_den = int(fm.get("fps_den") or 0) or None
    except Exception:
        fa_ok = False
    if fa_ok:
        checks.append(
            ExportAuthorityCheck(
                "full_apply_authority",
                True,
                "S12_EXPORT_OK",
                "immutable current completed Full Apply output resolved",
            )
        )
    else:
        if run_id is None or pub_id is None:
            checks.append(
                ExportAuthorityCheck(
                    "full_apply_authority",
                    False,
                    "S12_EXPORT_FULL_APPLY_MISSING",
                    "no completed Full Apply publication for this checkpoint/video — original import is never exported by accident",
                )
            )
        else:
            checks.append(
                ExportAuthorityCheck(
                    "full_apply_authority",
                    False,
                    "S12_EXPORT_SOURCE_STALE",
                    "completed Full Apply publication artifact missing/not-ready/.partial/sha-missing",
                )
            )

    # ── source canvas + origin (F02: never previously-upscaled as native)
    width = int(video.width) if video.width else None
    height = int(video.height) if video.height else None
    origin = "unproven"
    if fa_ok and width is not None and height is not None:
        if width == MASTER_WIDTH and height == MASTER_HEIGHT:
            if fps_num is not None and fps_den is not None:
                origin = "proved-native"
            else:
                origin = "unproven"  # approved output without measured timing
        else:
            origin = "upscale"
    checks.append(
        ExportAuthorityCheck(
            "source_origin",
            fa_ok,
            "S12_EXPORT_OK" if fa_ok else "S12_EXPORT_FULL_APPLY_MISSING",
            f"origin={origin} (canvas {width}x{height}, measured timing {'yes' if fps_num and fps_den else 'no'})",
        )
    )

    resolved = (
        project_ok
        and video_ok
        and ckpt_ok
        and config_ok
        and lock_ok
        and fa_ok
        and not ckpt_cross
    )
    return ExportAuthority(
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        project_ok=project_ok,
        video_ok=video_ok,
        checkpoint_ok=ckpt_ok,
        checkpoint_id=checkpoint_id,
        checkpoint_hash=checkpoint_hash.lower(),
        checkpoint_revision=int(checkpoint_revision),
        config_ok=config_ok,
        lock_ok=lock_ok,
        lock_manifest_id=manifest_id if lock_ok else None,
        lock_manifest_hash=manifest_hash.lower() if lock_ok else None,
        full_apply_ok=fa_ok,
        full_apply_run_id=run_id,
        full_apply_publication_id=pub_id,
        source_artifact_id=artifact_id,
        source_sha256=artifact_sha,
        source_relative_path=artifact_rel,
        source_state=artifact_state,
        source_partial=artifact_partial,
        source_frame_count=frame_count,
        source_fps_num=fps_num,
        source_fps_den=fps_den,
        source_width=width,
        source_height=height,
        source_origin=origin,
        checks=tuple(checks),
        resolved=resolved,
    )
