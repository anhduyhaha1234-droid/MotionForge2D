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

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.persistence.qc_check_runs import (
    READINESS_BLOCKED,
    READINESS_NOT_RUN,
    READINESS_READY,
    RUN_STATE_COMPLETED,
    check_run_readiness,
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
from app.workflow.qc_checks_handler import evidence_fingerprint, policy_bundle

__all__ = [
    "ProjectReadinessRecord",
    "ReadinessBlockerRecord",
    "ReadinessVideoRecord",
    "compute_project_readiness",
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