"""Typed denials + zero mutation on the public chain — RUNNABLE NOW.

These are the cases that can be proven against THIS tree without a frozen
candidate and WITHOUT seeding any product state: every one of them asserts
that the public surface fails CLOSED and writes nothing when the chain has
not earned the state it needs.

QC discipline (packet §1): nothing here seeds QC eligibility or QC results.
The QC cases are exactly the "no state yet" denials, and the module ends by
proving the counts are still zero.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import public_chain_cases as R  # noqa: E402

CLIENT_ERRORS = {400, 404, 409, 422}
UNKNOWN = str(uuid.uuid4())


def _new_project(client: Any) -> str:
    response = client.post("/api/projects", json={"name": "S12-LC3-QA public chain"})
    assert response.status_code == 201, response.text
    project_id = response.json()["project_id"]
    assert isinstance(project_id, str) and project_id
    return project_id


def test_upload_step_unknown_project_typed_denial_zero_mutation(
    client: Any, state_counts: Any, tmp_path: Path
) -> None:
    before = state_counts()
    payload = tmp_path / "qa-fixture-upload.bin"
    payload.write_bytes(b"\x00" * 64)
    with payload.open("rb") as handle:
        response = client.post(
            f"/api/projects/{UNKNOWN}/video",
            files={"file": (payload.name, handle, "video/mp4")},
        )
    assert response.status_code in CLIENT_ERRORS, (
        f"upload against an unknown project must fail closed, got {response.status_code}: "
        f"{response.text[:300]}"
    )
    assert state_counts() == before, "a refused upload must not create rows"


def test_qc_step_implementation_picking_payload_denied_zero_mutation(
    client: Any, state_counts: Any
) -> None:
    """The QC submit body must not let a caller pick an implementation."""
    project_id = _new_project(client)
    before = state_counts()
    url = f"/api/v2/projects/{project_id}/qc-check-runs"
    for extra in (
        {"handler": "qc_checks_handler"},
        {"provider": "custom"},
        {"detector": "audio_missing"},
        {"detectors": ["audio_missing"]},
        {"model": "ocg/deepseek-v4.1-flash"},
    ):
        body = {"video_item_id": UNKNOWN, "scope": "audio", **extra}
        response = client.post(url, json=body)
        assert response.status_code == 422, (
            f"implementation-picking field {sorted(extra)[0]!r} must be denied with 422 "
            f"before the route body runs, got {response.status_code}: {response.text[:300]}"
        )
    assert state_counts() == before, "a denied QC submit must create zero Job/QC rows"


def test_qc_step_unknown_video_typed_denial_zero_mutation(
    client: Any, state_counts: Any
) -> None:
    project_id = _new_project(client)
    before = state_counts()
    response = client.post(
        f"/api/v2/projects/{project_id}/qc-check-runs",
        json={"video_item_id": UNKNOWN, "scope": "audio"},
    )
    assert response.status_code in CLIENT_ERRORS, response.text
    after = state_counts()
    assert after["jobs"] == before["jobs"], "a refused QC submit queued a job"
    assert after["qc_items"] == before["qc_items"], "a refused QC submit created a QC item"


def test_qc_read_surfaces_fail_closed_without_state(client: Any) -> None:
    """Reads on an empty chain answer deterministically; nothing is fabricated."""
    project_id = _new_project(client)
    items = client.get(f"/api/v2/projects/{project_id}/qc-items")
    assert items.status_code in (200, *CLIENT_ERRORS), items.text
    if items.status_code == 200:
        body = items.json()
        payload = body.get("items", body) if isinstance(body, dict) else body
        assert list(payload or []) == [], f"empty chain must expose no QC items: {body}"

    for path, code in (
        (f"/api/v2/qc-items/{UNKNOWN}", 404),
        (f"/api/v2/qc-navigation/{UNKNOWN}", 404),
    ):
        response = client.get(path)
        assert response.status_code == code, f"{path} -> {response.status_code}: {response.text[:200]}"

    readiness = client.get(f"/api/v2/projects/{project_id}/readiness")
    assert readiness.status_code in (200, 404, 422), readiness.text
    if readiness.status_code == 200:
        body = readiness.json()
        assert body.get("blockers") != [] or body.get("ready") is not True, (
            "a chain with no earned state must not report itself ready"
        )


def test_no_qc_state_was_seeded_or_earned(client: Any, state_counts: Any) -> None:
    """Post-condition of this module: QC state is still exactly zero."""
    _new_project(client)
    counts = state_counts()
    assert counts["qc_items"] == 0, f"QC state appeared without the chain earning it: {counts}"
    qc_jobs = 0
    from sqlalchemy import func, select

    from app.api import deps
    from app.persistence.models import Job

    with deps._job_service.session_factory() as session:
        qc_jobs = int(
            session.scalar(
                select(func.count()).select_from(Job).where(Job.job_type == "RUN_QC_CHECKS")
            )
            or 0
        )
    assert qc_jobs == 0, "a RUN_QC_CHECKS job exists although this module never seeded one"


def test_s12_unknown_run_reads_and_media_denied(client: Any, state_counts: Any) -> None:
    before = state_counts()
    for path in (
        f"/s12-exports/{UNKNOWN}",
        f"/s12-exports/{UNKNOWN}/result",
        f"/s12-exports/{UNKNOWN}/media",
    ):
        response = client.get(path)
        assert response.status_code == 404, f"{path} -> {response.status_code}: {response.text[:200]}"
    assert state_counts() == before


def test_s12_retry_and_cancel_unknown_run_denied(client: Any, state_counts: Any) -> None:
    before = state_counts()
    for path in (f"/s12-exports/{UNKNOWN}/retry", f"/s12-exports/{UNKNOWN}/cancel"):
        response = client.post(path, json={})
        assert response.status_code in (404, 405, 422), (
            f"{path} -> {response.status_code}: {response.text[:200]}"
        )
        assert response.status_code != 202, f"{path} accepted a retry/cancel for an unknown run"
    assert state_counts() == before, "refused retry/cancel must not create rows"


def test_registry_lists_these_denial_cases() -> None:
    """The registry must actually point at the denial cases run here."""
    runnable = {case["node"] for case in R.cases(R.RUNNABLE_NOW)}
    for expected in (
        f"{R.PKG}/test_public_chain_denials.py::test_qc_step_implementation_picking_payload_denied_zero_mutation",
        f"{R.PKG}/test_public_chain_denials.py::test_qc_step_unknown_video_typed_denial_zero_mutation",
        f"{R.PKG}/test_public_chain_denials.py::test_s12_unknown_run_reads_and_media_denied",
    ):
        assert expected in runnable, f"denial case not registered: {expected}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
