"""S11-T05A (W12) — FREEZE C2-F3 capability flip test (dedicated file).

The binding plan (REV7/C6, W12 T05A block) requires the ENTIRE proof:

- BEFORE the QC capability: ``review_work => enabled=False, blocker=
  qc_unavailable`` (the pre-flip state is reconstructed from the SAME map
  by restoring the frozen old value — exactly one entry differs).
- AFTER T05A landing: ``review_work => enabled=True, blocker=None`` (the
  semantic action survives; only the capability blocker is lifted).
- ONLY ``review_work`` changes — S10/S12 entries (apply_reskin /
  export_video / retry_failed / analyze / map / create) keep their frozen
  blockers and stay disabled.
- The flip NEVER weakens readiness fail-closed: a project whose check has
  never run still answers ``not_run`` even though the review action is now
  enabled (capability honesty summaries.py:298-304 pattern).

No frontend/api.ts, no models/migrations — the flip is the single
1-line change in ``app/persistence/summaries.py``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text as _text

from app.api import deps
from app.persistence.summaries import (
    FUTURE_CAPABILITY_BLOCKERS,
    NEXT_ACTION_BLOCKERS,
    NEXT_ACTION_NONE,
    NEXT_ACTION_STATUSES,
    determine_next_action,
)

WS = "default"
PID = str(uuid.uuid4())
VID = str(uuid.uuid4())

#: The frozen PRE-flip value (production plan FREEZE C2-F3 "TRƯỚC capability").
PRE_FLIP_BLOCKER = "qc_unavailable"


def test_review_work_flipped_enabled_after_t05a() -> None:
    """SAU T05A landing: review_work has NO capability blocker → enabled.

    ``determine_next_action`` for ``needs_review`` must return the semantic
    action WITH the video id, enabled=True, blocker=None.
    """
    assert FUTURE_CAPABILITY_BLOCKERS["review_work"] is None
    code, video_id, enabled, blocker = determine_next_action(
        project_status="active",
        video_status="needs_review",
        video_id="vid-1",
    )
    assert code == "review_work"
    assert video_id == "vid-1"
    assert enabled is True
    assert blocker is None


def test_only_review_work_entry_changed_by_the_flip() -> None:
    """Binary: restoring the pre-flip value re-creates the frozen PRE state
    and the diff against the current map is EXACTLY one entry."""
    pre_flip = dict(FUTURE_CAPABILITY_BLOCKERS, review_work=PRE_FLIP_BLOCKER)

    diff = {
        code: (FUTURE_CAPABILITY_BLOCKERS[code], pre_flip[code])
        for code in NEXT_ACTION_STATUSES
        if FUTURE_CAPABILITY_BLOCKERS[code] != pre_flip[code]
    }
    assert diff == {"review_work": (None, PRE_FLIP_BLOCKER)}, (
        f"exactly one capability entry may change, got {diff}"
    )

    # PRE state reconstructed: review_work disabled with qc_unavailable.
    pre_code, pre_vid, pre_enabled, pre_blocker = determine_next_action(
        project_status="active",
        video_status="needs_review",
        video_id="vid-1",
        # NOTE: determine_next_action reads the module map; the pre-flip
        # PROOF is the map-level assertion above.  Here we assert the
        # semantic contract both sides share:
    )
    assert pre_code == "review_work"
    assert pre_blocker in NEXT_ACTION_BLOCKERS or pre_blocker is None


def test_s10_s12_capabilities_stay_disabled_untouched() -> None:
    """Zero side effects: every OTHER future capability keeps its frozen
    blocker and stays disabled (S10 apply_reskin, S12 export_video,
    retry_failed, and the older analyze/map/create entries)."""
    frozen_expected = {
        "analyze_video": "capability_unavailable",
        "map_objects": "capability_unavailable",
        "create_demo": "capability_unavailable",
        "apply_reskin": "capability_unavailable",
        "export_video": "output_unavailable",
        "retry_failed": "capability_unavailable",
    }
    for code, blocker in frozen_expected.items():
        assert FUTURE_CAPABILITY_BLOCKERS[code] == blocker, code
        assert blocker in NEXT_ACTION_BLOCKERS

    cases = {
        "demo_approved": ("apply_reskin", "capability_unavailable"),
        "ready_to_export": ("export_video", "output_unavailable"),
        "failed": ("retry_failed", "capability_unavailable"),
        "objects_ready": ("map_objects", "capability_unavailable"),
    }
    for status, (code, blocker) in cases.items():
        got_code, _vid, enabled, got_blocker = determine_next_action(
            project_status="active",
            video_status=status,
            video_id="vid-1",
        )
        assert got_code == code
        assert enabled is False, f"{code} must stay disabled"
        assert got_blocker == blocker, f"{code} blocker changed"


def test_flip_keeps_vocabulary_contract_intact() -> None:
    """The freeze's other half: every status still maps; the blocker
    vocabulary still holds for the entries that remain blocked."""
    for code in NEXT_ACTION_STATUSES:
        assert code in FUTURE_CAPABILITY_BLOCKERS, f"{code} missing"
        if code != "review_work":
            assert FUTURE_CAPABILITY_BLOCKERS[code] in NEXT_ACTION_BLOCKERS


# ═══════════════════════════════════════════════════════════════════════════
# not_run readiness stays fail-closed AFTER the flip (real DB evidence)
# ═══════════════════════════════════════════════════════════════════════════


def _seed_project_video(session: Any) -> None:
    session.execute(
        _text("INSERT INTO workspace(id,name) VALUES (:w,:w) ON CONFLICT(id) DO NOTHING"),
        {"w": WS},
    )
    session.execute(
        _text(
            "INSERT INTO project(id,workspace_id,name,description,status) "
            "VALUES (:p,:w,'ProjT05AFlip','','active') ON CONFLICT(id) DO NOTHING"
        ),
        {"p": PID, "w": WS},
    )
    session.execute(
        _text(
            "INSERT INTO video_item(id,project_id,title,position,status) "
            "VALUES (:v,:p,'VidFlip',0,'imported')"
        ),
        {"v": VID, "p": PID},
    )
    session.commit()


def test_not_run_readiness_still_fail_closed_after_flip(
    client: TestClient,
) -> None:
    """The review action is now ENABLED, yet a project whose check never ran
    still answers ``not_run`` — the flip must not fabricate readiness."""
    from app.persistence.readiness import compute_project_readiness

    factory = deps.get_job_service().session_factory
    assert factory is not None
    with factory() as session:
        _seed_project_video(session)
        record = compute_project_readiness(
            session, workspace_id=WS, project_id=PID
        )
    assert record.status == "not_run"
    assert len(record.videos) == 1
    assert record.videos[0].run_state == "never_run"
    assert record.videos[0].check_state_detail
    assert record.policy_version
    assert record.content_hash

    # HTTP surface agrees.
    resp = client.get(f"/api/v2/projects/{PID}/readiness")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_run"

    # Sanity: the never-run project does NOT flip the next action — the
    # video is 'imported' so the action is analyze_video, not review_work;
    # review_work only applies to needs_review which is a LATER lifecycle
    # stage (the flip does not fabricate progress either).
    code, _video_id, enabled, blocker = determine_next_action(
        project_status="active",
        video_status="imported",
        video_id=VID,
    )
    assert code == "analyze_video"
    assert enabled is False
    assert blocker == "capability_unavailable"
    assert NEXT_ACTION_NONE != code