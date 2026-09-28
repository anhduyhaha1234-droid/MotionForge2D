"""S11-T05A (W12) — compute-on-the-fly project readiness aggregate (Decision F).

NO readiness table and NO migration: this module computes the aggregate
ON THE FLY from QCItem rows + durable check-run evidence every time it is
called.  The per-video verdicts come from the T03G read authority
``app.persistence.qc_check_runs.check_run_readiness`` (import-only) — the
distinction between never-run and completed-zero-item is loaded onto the
durable run evidence (C4-F2), never onto the emptiness of QCItem.

Aggregate rules (lane-C REVIEW_QUEUE_CONTRACT §4.2 + binding plan W12/T05A):

- ``blocked``  — every video has a completed CURRENT run and at least one
  unresolved blocker-severity item (open) exists in a current run;
- ``ready``    — every video has a completed CURRENT run and zero
  unresolved blockers; a completed zero-item run is clean/ready evidence;
- ``not_run``  — ANY video lacks a completed current run (never-run /
  queued / running / failed / stale) — not_run WINS (capability honesty,
  summaries.py:298-304 pattern); every per-video entry carries its
  check-state detail;
- ``blockers[]`` lists ONLY open blocker items from videos with a
  completed CURRENT run, each with WS-07 location/reason/action
  (navigation action from the T04A canonical resolver; unknown kinds
  resolve fail-closed to an ``explain`` action — never a dead link,
  never a crash);
- ``warning_count`` counts open warning items of current-run videos only
  (warnings never appear in ``blockers[]``, E2E-02);
- R4 (lane-A GAP_RISKS): a dismissed item can never clear a blocker —
  dismissed blocker rows are impossible by construction (repo guard +
  DB CHECK) and the predicate only ever counts ``status == open``.

Decision F identity: ``policy_version`` = the frozen T03A POLICY_ID
constant; ``content_hash`` = the frozen policy content hash — both equal
to the identity used by every durable check-run (``policy_bundle``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.persistence.jobs import JobRepository
from app.persistence.qc_check_runs import (
    READINESS_BLOCKED,
    READINESS_NOT_RUN,
    READINESS_READY,
    RUN_STATE_COMPLETED,
    check_run_readiness,
    full_coverage_detectors,
)
from app.persistence.qc_items import QCItemRecord, QCItemRepository
from app.persistence.videos import VideoItemRepository
from app.schemas.qc_items import QCItemData
from app.services.qc_checks.thresholds import POLICY_ID
from app.services.qc_navigation import (
    NavigationResolutionError,
    canonical_location,
    resolve_navigation,
)
from app.workflow.qc_checks_handler import (
    JOB_TYPE_RUN_QC_CHECKS,
    detector_revisions,
    evidence_fingerprint,
    output_evidence_binding,
    policy_bundle,
)

__all__ = [
    "ProjectReadinessRecord",
    "ReadinessBlockerRecord",
    "ReadinessVideoRecord",
    "compute_project_readiness",
    "ExportGateRecord",
    "ExportGateVideoRecord",
    "ExportGateViolation",
    "compute_export_gate",
]

#: Frozen Vietnamese presentation per reason code — WS-07 requires every
#: blocker to carry reason + action; the backend never invents prose for
#: unknown codes (stable generic fallback, never a crash).
REASON_PRESENTATION: dict[str, tuple[str, str]] = {
    "trajectory_drift": (
        "Quỹ đạo chuyển động của đối tượng bị lệch so với cảnh gốc.",
        "Chỉnh lại mask/keyframe quỹ đạo tại vị trí lỗi, sau đó chạy lại QC.",
    ),
    "cut_drift": (
        "Điểm cắt cảnh bị lệch so với cấu trúc gốc.",
        "Điều chỉnh lại thời điểm cắt tại vị trí lỗi, sau đó chạy lại QC.",
    ),
    "contact_break": (
        "Tiếp xúc giữa các đối tượng bị đứt trong cảnh.",
        "Sửa lại vùng tiếp xúc của đối tượng, sau đó chạy lại QC.",
    ),
    "z_order_error": (
        "Thứ tự lớp (z-order) của đối tượng bị sai.",
        "Sửa lại thứ tự lớp của đối tượng, sau đó chạy lại QC.",
    ),
    "silhouette_clipping": (
        "Silhouette của đối tượng bị cắt xén sai.",
        "Sửa lại mask silhouette tại vị trí lỗi, sau đó chạy lại QC.",
    ),
    "identity_drift": (
        "Nhận diện nhân vật bị trượt giữa các cảnh.",
        "Kiểm tra lại mapping nhân vật tại vị trí lỗi, sau đó chạy lại QC.",
    ),
    "edge_halo": (
        "Xuất hiện viền halo quanh đối tượng.",
        "Sửa lại vùng edge/feather của mask, sau đó chạy lại QC.",
    ),
    "temporal_flicker": (
        "Hình ảnh nhấp nháy theo thời gian tại phân đoạn lỗi.",
        "Sửa lại keyframe/mask tại phân đoạn lỗi, sau đó chạy lại QC.",
    ),
    "audio_missing": (
        "Thiếu audio trong video sau xử lý.",
        "Kiểm tra lại luồng audio/video gốc, sau đó chạy lại QC.",
    ),
    "av_sync_drift": (
        "Đồng bộ audio-video bị lệch.",
        "Chỉnh lại timebase/offset audio, sau đó chạy lại QC.",
    ),
}

#: Stable generic presentation for a reason code without frozen prose —
#: fails closed with the code itself, never an invented explanation.
_FALLBACK_PRESENTATION = (
    "Lỗi QC chưa có mô tả chuẩn cho mã này.",
    "Sửa nội dung tại vị trí lỗi, sau đó chạy lại QC.",
)


@dataclass(frozen=True)
class ReadinessVideoRecord:
    """Per-video fail-closed verdict (mirrors the T03G read authority)."""

    video_item_id: str
    status: str
    run_state: str
    check_state_detail: str
    zero_item_completion: bool | None = None
    latest_job_id: str | None = None
    blockers: int = 0


@dataclass(frozen=True)
class ReadinessBlockerRecord:
    """One unresolved blocker of a CURRENT run with WS-07 full detail."""

    qc_item_id: str
    code: str
    video_item_id: str
    layer_ref_type: str
    layer_ref_id: str
    location: dict[str, Any]
    reason_vi: str
    action_vi: str
    action: dict[str, Any]


@dataclass(frozen=True)
class ProjectReadinessRecord:
    """Compute-on-the-fly project readiness aggregate (Decision F)."""

    status: str
    blockers: list[ReadinessBlockerRecord]
    warning_count: int
    videos: list[ReadinessVideoRecord]
    policy_version: str
    content_hash: str
    computed_at: str


def _map_blocker(item: QCItemRecord) -> ReadinessBlockerRecord:
    """Map one open blocker row → WS-07 blocker entry (location/reason/action).

    Navigation resolution reuses the T04A canonical resolver; an unknown
    location kind fails closed to an ``explain`` action (Decision E — no
    dead link, no guessed target) without failing the whole aggregate.
    """
    data = QCItemData.from_record(item)
    try:
        nav = resolve_navigation(data)
        location = nav.canonical_location.model_dump()
        action = nav.action.model_dump()
    except NavigationResolutionError as err:
        location = canonical_location(data).model_dump()
        action = {
            "kind": "explain",
            "method": "GET",
            "target": None,
            "endpoint": None,
            "code": err.code,
            "reason": err.message,
        }
    reason_vi, action_vi = REASON_PRESENTATION.get(
        item.reason_code, _FALLBACK_PRESENTATION
    )
    return ReadinessBlockerRecord(
        qc_item_id=item.id,
        code=item.reason_code,
        video_item_id=item.video_item_id,
        layer_ref_type=item.layer_ref_type,
        layer_ref_id=item.layer_ref_id,
        location=location,
        reason_vi=reason_vi,
        action_vi=action_vi,
        action=action,
    )


def compute_project_readiness(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
) -> ProjectReadinessRecord:
    """Compute the readiness aggregate from CURRENT evidence (Decision F).

    - every active video of the project is classified by the T03G read
      authority against ITS CURRENT evidence fingerprint + policy hash;
    - any video without a completed current run ⇒ aggregate ``not_run``
      (fail-closed, not_run wins) with per-video check-state detail;
    - blockers[]/warning_count only ever reflect CURRENT-run evidence
      (open blocker / open warning, R4-safe).
    """
    videos = VideoItemRepository(session).list_videos(
        project_id, workspace_id, active_only=True
    )
    bundle = policy_bundle()

    verdicts = [
        check_run_readiness(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video.id,
            evidence_fingerprint=evidence_fingerprint(
                session, workspace_id=workspace_id, video_item_id=video.id
            ),
            policy_content_hash=bundle["policy_content_hash"],
        )
        for video in videos
    ]

    video_records = [
        ReadinessVideoRecord(
            video_item_id=v.video_item_id,
            status=v.status,
            run_state=v.run_state,
            check_state_detail=v.check_state_detail,
            zero_item_completion=v.zero_item_completion,
            latest_job_id=v.latest_job_id,
            blockers=v.blockers,
        )
        for v in verdicts
    ]

    current_ids = {
        v.video_item_id for v in verdicts if v.run_state == RUN_STATE_COMPLETED
    }

    blockers: list[ReadinessBlockerRecord] = []
    warning_count = 0
    if current_ids:
        item_rows, _total = QCItemRepository(session).list(
            workspace_id,
            project_id=project_id,
            severity="blocker",
            status="open",
            limit=1_000_000,
        )
        blockers = [
            _map_blocker(row)
            for row in item_rows
            if row.video_item_id in current_ids
        ]
        warn_rows, _warn_total = QCItemRepository(session).list(
            workspace_id,
            project_id=project_id,
            severity="warning",
            status="open",
            limit=1_000_000,
        )
        warning_count = sum(
            1 for row in warn_rows if row.video_item_id in current_ids
        )

    if any(v.status == READINESS_NOT_RUN for v in verdicts):
        status = READINESS_NOT_RUN
    elif blockers:
        status = READINESS_BLOCKED
    else:
        status = READINESS_READY

    return ProjectReadinessRecord(
        status=status,
        blockers=blockers,
        warning_count=warning_count,
        videos=video_records,
        policy_version=POLICY_ID,
        content_hash=bundle["policy_content_hash"],
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


# ══════════════════════════════════════════════════════════════════════════
# MF-END-23 — EXPORT GATE (additive contract ``mf-end-23/export-gate@1``)
#
# The gate answers ONE question: *may this project's video be exported?*  It
# never re-implements the readiness or policy authority — it CONSUMES
# ``check_run_readiness`` (full-scope, current evidence, current policy) and
# adds exactly the facts the old authority could not see:
#
# 1. the run really executed the REGISTERED band (the policy-mapped detector
#    set) at the CURRENT revisions — an unknown/missing detector is never a
#    pass;
# 2. the run's evidence binding (source + rendered OUTPUT + cast) is still the
#    CURRENT one — a render change or a cast change makes the run stale;
# 3. the output-observation evidence is INDEPENDENTLY re-validated from
#    persisted rows (bytes re-hashed): missing / foreign / tampered / stale
#    observations BLOCK the export, and an audio-only completion never
#    satisfies any of this (the authority already refuses it).
#
# ``compute_project_readiness`` is untouched: this is a NEW, versioned,
# additive contract (the END-01 pattern), not a silent redefinition.
# ══════════════════════════════════════════════════════════════════════════

#: Additive contract identity of the export gate report.
EXPORT_GATE_SCHEMA = "mf-end-23/export-gate@1"

EXPORT_READY = "ready"
EXPORT_BLOCKED = "blocked"
EXPORT_NOT_RUN = "not_run"

#: Stable violation codes (binary: any violation blocks the export).
EXPORT_BLOCKED_READINESS = "EXPORT_BLOCKED_READINESS"
EXPORT_BLOCKED_JOB_UNREADABLE = "EXPORT_BLOCKED_JOB_UNREADABLE"
EXPORT_BLOCKED_BAND_MISMATCH = "EXPORT_BLOCKED_BAND_MISMATCH"
EXPORT_BLOCKED_DETECTOR_UNKNOWN = "EXPORT_BLOCKED_DETECTOR_UNKNOWN"
EXPORT_BLOCKED_DETECTOR_REVISION = "EXPORT_BLOCKED_DETECTOR_REVISION"
EXPORT_BLOCKED_BINDING_MISSING = "EXPORT_BLOCKED_BINDING_MISSING"
EXPORT_BLOCKED_BINDING_TAMPER = "EXPORT_BLOCKED_BINDING_TAMPER"
EXPORT_BLOCKED_STALE_RENDER = "EXPORT_BLOCKED_STALE_RENDER"
EXPORT_BLOCKED_STALE_CAST = "EXPORT_BLOCKED_STALE_CAST"
EXPORT_BLOCKED_STALE_SOURCE = "EXPORT_BLOCKED_STALE_SOURCE"
EXPORT_BLOCKED_OUTPUT_EVIDENCE = "EXPORT_BLOCKED_OUTPUT_EVIDENCE"


@dataclass(frozen=True)
class ExportGateViolation:
    """One typed reason the export is blocked (never a percentage)."""

    code: str
    video_item_id: str
    kind: str
    detail: str


@dataclass(frozen=True)
class ExportGateVideoRecord:
    """Per-video export verdict with the full chain that produced it."""

    video_item_id: str
    status: str
    readiness_status: str
    run_state: str
    check_state_detail: str
    latest_job_id: str | None
    binding_state: str
    output_state: str
    output_detail: str
    violations: tuple[ExportGateViolation, ...]


@dataclass(frozen=True)
class ExportGateRecord:
    """The additive export-gate report (MF-END-23)."""

    schema: str
    workspace_id: str
    project_id: str
    status: str
    videos: list[ExportGateVideoRecord]
    blockers: list[ExportGateViolation]
    visibility: dict[str, Any]
    policy_version: str
    content_hash: str
    computed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "status": self.status,
            "videos": [
                {
                    "video_item_id": v.video_item_id,
                    "status": v.status,
                    "readiness_status": v.readiness_status,
                    "run_state": v.run_state,
                    "check_state_detail": v.check_state_detail,
                    "latest_job_id": v.latest_job_id,
                    "binding_state": v.binding_state,
                    "output_state": v.output_state,
                    "output_detail": v.output_detail,
                    "violations": [
                        {
                            "code": b.code,
                            "kind": b.kind,
                            "detail": b.detail,
                        }
                        for b in v.violations
                    ],
                }
                for v in self.videos
            ],
            "blockers": [
                {
                    "code": b.code,
                    "video_item_id": b.video_item_id,
                    "kind": b.kind,
                    "detail": b.detail,
                }
                for b in self.blockers
            ],
            "visibility": self.visibility,
            "policy_version": self.policy_version,
            "content_hash": self.content_hash,
            "computed_at": self.computed_at,
        }


def _managed_artifact_root() -> Any:
    """The public managed-artifact root (same accessor every component uses)."""
    from app.api.deps import get_managed_root  # noqa: PLC0415

    return get_managed_root()


def _binding_delta(
    recorded: Mapping[str, Any] | None, current: Mapping[str, Any]
) -> str:
    """Which component of the recorded binding no longer matches current."""
    if not isinstance(recorded, Mapping):
        return "missing"
    if not recorded:
        return "missing"
    if str(recorded.get("source", {}).get("sha256") or "") != str(
        current.get("source", {}).get("sha256") or ""
    ) or str(recorded.get("source", {}).get("artifact_id") or "") != str(
        current.get("source", {}).get("artifact_id") or ""
    ):
        return "source"
    recorded_render = recorded.get("render")
    current_render = current.get("render")
    if (recorded_render or {}).get("digest") != (current_render or {}).get("digest"):
        return "render"
    if str(recorded.get("cast", {}).get("digest") or "") != str(
        current.get("cast", {}).get("digest") or ""
    ):
        return "cast"
    if str(recorded.get("digest") or "") != str(current.get("digest") or ""):
        return "unresolved"
    return "current"


def _completion_of_run(repo: JobRepository, job_id: str) -> dict[str, Any] | None:
    """The run's completion block (latest successful attempt, schema-gated)."""
    for attempt in repo.list_attempts(job_id, limit=20):
        if attempt.error is not None:
            continue
        result = attempt.result
        if not isinstance(result, dict):
            continue
        if result.get("job_type") != JOB_TYPE_RUN_QC_CHECKS:
            continue
        if result.get("completed") is True:
            return result
    return None


def compute_export_gate(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
) -> ExportGateRecord:
    """Decide whether the project may export (MF-END-23, additive).

    Consumes the existing readiness/policy authority and adds: the registered
    band + current revisions, the output-bound evidence identity, and the
    INDEPENDENT re-validation of the published output-observation evidence.
    Any violation blocks; a video without a completed CURRENT full-scope run
    is ``not_run`` (never a pass).
    """
    from app.services.qc_evidence.compose import output_evidence_status  # noqa: PLC0415

    videos = VideoItemRepository(session).list_videos(
        project_id, workspace_id, active_only=True
    )
    bundle = policy_bundle()
    registered_band = list(full_coverage_detectors())
    registered_band_set = set(registered_band)
    current_revisions = detector_revisions(registered_band)
    managed_root = _managed_artifact_root()
    repo = JobRepository(session)

    video_records: list[ExportGateVideoRecord] = []
    all_blockers: list[ExportGateViolation] = []
    visibility_videos: dict[str, Any] = {}

    for video in videos:
        violations: list[ExportGateViolation] = []

        def _block(
            code: str,
            kind: str,
            detail: str,
            _violations: list[ExportGateViolation] = violations,
            _video_item_id: str = video.id,
        ) -> None:
            _violations.append(
                ExportGateViolation(
                    code=code,
                    video_item_id=_video_item_id,
                    kind=kind,
                    detail=detail,
                )
            )

        readiness = check_run_readiness(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=video.id,
            evidence_fingerprint=evidence_fingerprint(
                session,
                workspace_id=workspace_id,
                video_item_id=video.id,
                project_id=project_id,
            ),
            policy_content_hash=bundle["policy_content_hash"],
        )
        binding_state = "unresolved"
        output_state = "unresolved"
        output_detail = "readiness not_run — the output evidence was not reached"
        if readiness.status == READINESS_NOT_RUN:
            _block(
                EXPORT_BLOCKED_READINESS,
                "readiness",
                "no completed CURRENT full-scope check-run: "
                f"{readiness.check_state_detail}",
            )
        else:
            job_id = readiness.latest_job_id
            manifest: dict[str, Any] = {}
            completion: dict[str, Any] | None = None
            try:
                job = repo.get_job(str(job_id)) if job_id else None
                manifest = (
                    dict(job.input_manifest)
                    if job is not None and isinstance(job.input_manifest, dict)
                    else {}
                )
                completion = (
                    _completion_of_run(repo, str(job_id)) if job_id else None
                )
            except Exception as exc:  # noqa: BLE001 - typed, never a crash
                job = None
                _block(
                    EXPORT_BLOCKED_JOB_UNREADABLE,
                    "run",
                    f"check-run job {job_id!r} could not be read: "
                    f"{type(exc).__name__}: {exc}",
                )
            completion_detectors = (
                list(completion.get("detectors") or [])
                if isinstance(completion, dict)
                else []
            )
            if completion is None:
                _block(
                    EXPORT_BLOCKED_BAND_MISMATCH,
                    "band",
                    "the completed run carries no readable completion block; "
                    "its detector coverage is unknowable",
                )
            else:
                unknown = [
                    name
                    for name in completion_detectors
                    if name not in registered_band_set
                ]
                if unknown:
                    _block(
                        EXPORT_BLOCKED_DETECTOR_UNKNOWN,
                        "band",
                        "the completed run executed detector(s) that are not "
                        f"part of the registered band: {sorted(unknown)}",
                    )
                if sorted(completion_detectors) != sorted(registered_band):
                    _block(
                        EXPORT_BLOCKED_BAND_MISMATCH,
                        "band",
                        "the completed run's detector set is not the registered "
                        f"band (run={sorted(completion_detectors)} vs "
                        f"registered={registered_band})",
                    )
                revisions = completion.get("detector_revisions")
                revisions = revisions if isinstance(revisions, dict) else {}
                for name in registered_band:
                    if name not in revisions:
                        _block(
                            EXPORT_BLOCKED_DETECTOR_REVISION,
                            "band",
                            f"detector {name!r} has no recorded revision in the "
                            "completed run — its coverage cannot be verified",
                        )
                    elif str(revisions[name]) != str(current_revisions[name]):
                        _block(
                            EXPORT_BLOCKED_DETECTOR_REVISION,
                            "band",
                            f"detector {name!r} ran at revision "
                            f"{revisions[name]!r} but the registered revision is "
                            f"{current_revisions[name]!r}",
                        )
            current_binding = output_evidence_binding(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=video.id,
            )
            recorded_binding = (
                manifest.get("evidence_binding")
                if isinstance(manifest.get("evidence_binding"), dict)
                else None
            )
            completion_binding = (
                completion.get("evidence_binding")
                if isinstance(completion, dict)
                and isinstance(completion.get("evidence_binding"), dict)
                else None
            )
            if recorded_binding is None:
                binding_state = "missing"
                _block(
                    EXPORT_BLOCKED_BINDING_MISSING,
                    "binding",
                    "the run manifest carries no output-bound evidence binding; "
                    "the run cannot be shown to describe the current output",
                )
            else:
                delta = _binding_delta(recorded_binding, current_binding)
                binding_state = delta
                if delta == "source":
                    _block(
                        EXPORT_BLOCKED_STALE_SOURCE,
                        "binding",
                        "the video's source evidence changed after the run "
                        "(stale run — a NEW run must be submitted)",
                    )
                elif delta == "render":
                    _block(
                        EXPORT_BLOCKED_STALE_RENDER,
                        "binding",
                        "the rendered output changed after the run (stale "
                        "checkpoint — a NEW run must be submitted)",
                    )
                elif delta == "cast":
                    _block(
                        EXPORT_BLOCKED_STALE_CAST,
                        "binding",
                        "the project cast binding changed after the run (stale "
                        "run — a NEW run must be submitted)",
                    )
                elif delta != "current":
                    _block(
                        EXPORT_BLOCKED_BINDING_MISSING,
                        "binding",
                        f"the recorded evidence binding does not match the "
                        f"current one ({delta})",
                    )
                if (
                    completion_binding is not None
                    and str(completion_binding.get("digest") or "")
                    != str(recorded_binding.get("digest") or "")
                ):
                    _block(
                        EXPORT_BLOCKED_BINDING_TAMPER,
                        "binding",
                        "the completion's evidence binding does not match the "
                        "manifest's (tampered/replayed envelope)",
                    )
            status_block = output_evidence_status(
                session,
                managed_root=managed_root,
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=video.id,
            )
            output_state = str(status_block.get("state") or "unresolved")
            output_detail = str(status_block.get("detail") or "")
            if output_state != "valid":
                _block(
                    EXPORT_BLOCKED_OUTPUT_EVIDENCE,
                    "output_evidence",
                    f"{status_block.get('code') or 'OUTPUT_EVIDENCE'}: "
                    f"{output_detail}",
                )
            visibility_videos[video.id] = {
                "render": (status_block.get("checked") or {}).get("render"),
                "observations_artifact": (status_block.get("checked") or {}).get(
                    "observations_artifact"
                ),
                "sealed": (status_block.get("checked") or {}).get("sealed"),
                "output_state": output_state,
                "output_code": status_block.get("code") or "",
                "binding_state": binding_state,
                "cast_digest": str(
                    (current_binding.get("cast") or {}).get("digest") or ""
                ),
                "registered_band": registered_band,
                "detector_revisions": current_revisions,
            }

        video_status = (
            EXPORT_NOT_RUN
            if readiness.status == READINESS_NOT_RUN
            else (EXPORT_BLOCKED if violations else EXPORT_READY)
        )
        all_blockers.extend(violations)
        video_records.append(
            ExportGateVideoRecord(
                video_item_id=video.id,
                status=video_status,
                readiness_status=readiness.status,
                run_state=readiness.run_state,
                check_state_detail=readiness.check_state_detail,
                latest_job_id=readiness.latest_job_id,
                binding_state=binding_state,
                output_state=output_state,
                output_detail=output_detail,
                violations=tuple(violations),
            )
        )

    if any(v.status == EXPORT_NOT_RUN for v in video_records):
        status = EXPORT_NOT_RUN
    elif all_blockers:
        status = EXPORT_BLOCKED
    else:
        status = EXPORT_READY

    return ExportGateRecord(
        schema=EXPORT_GATE_SCHEMA,
        workspace_id=workspace_id,
        project_id=project_id,
        status=status,
        videos=video_records,
        blockers=all_blockers,
        visibility={
            "videos": visibility_videos,
            "registered_band": registered_band,
            "policy": {
                "policy_id": bundle["policy_id"],
                "content_hash": bundle["policy_content_hash"],
            },
            "dependencies": {
                "render": "MF-END-19/20 rendered output (publication or owned "
                "render-side artifact) resolved from persisted rows",
                "observations": "MF-END-21 published rendered-observations "
                "artifact, bytes re-hashed on read",
                "comparison_policy": "MF-END-22 frozen comparison policy "
                "(calibrated rows, digest-pinned)",
                "band": "T03A policy-mapped registered detector band at "
                "current revisions",
            },
        },
        policy_version=POLICY_ID,
        content_hash=bundle["policy_content_hash"],
        computed_at=datetime.now(UTC).isoformat(),
    )