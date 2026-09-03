"""S11-T02B QCItem repository + internal idempotent lifecycle tests.

Verifies the repository layer (app.persistence.qc_items) on FRESH temp
SQLite databases built from ORM metadata (``Base.metadata.create_all``):

1. Creation is idempotent on the 7-column natural key: a duplicate — sequential
   AND concurrent — reuses the existing row (DB-level atomic upsert, NEVER a
   check-then-insert race) (C4-F1).
2. Repository returns FROZEN dataclass DTOs only; ORM rows never escape
   (lane-A §2 #4).
3. Terminal transitions (``resolved``/``dismissed``) REQUIRE fresh recheck
   evidence in the payload; an evidence-less attempt is rejected
   (lane-A §1.3 rule 1 / AC3). ``acknowledged`` is non-terminal.
4. A recheck that still finds the issue returns the item to ``open`` (with
   recheck evidence); terminal states are terminal (no reversal).
5. A ``blocker`` cannot be dismissed (lane-A §1.3 rule 2, fail-closed in the
   repository BEFORE the DB CHECK).
6. Ownership is fail-closed: reads from another workspace are
   indistinguishable from not-found (zero leak).
7. List filters (status/severity/category/video_item_id) return exactly the
   matching subset within the workspace, with deterministic paging.

Runs only against per-test temp DB files under the pytest basetemp; never
touches MAIN data.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.persistence import create_engine_for_path
from app.persistence.models import Base
from app.persistence.qc_items import (
    QCItemBlockedDismissalError,
    QCItemEvidenceRequiredError,
    QCItemInvalidTransitionError,
    QCItemNotFoundError,
    QCItemParamsError,
    QCItemRecord,
    QCItemRepository,
)

WS = "ws-t02b-repo"
WS2 = "ws-t02b-other"
P1 = "p-t02b-repo"
P2 = "p-t02b-other-project"
V1 = "v-t02b-repo"
V2 = "v-t02b-other-video"

NATURAL_KEY = dict(
    workspace_id=WS,
    project_id=P1,
    video_item_id=V1,
    layer_ref_type="video_item",
    layer_ref_id=V1,
    reason_code="silhouette_clipping",
    evidence_window_key="ewk-t02b-1",
)


def _seed_ws_project_video(engine, *, ws: str, pid: str, vid: str) -> None:
    """Seed the FK chain the repository requires (raw SQL, ORM DDL)."""
    with engine.begin() as conn:
        conn.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO workspace(id,name) VALUES (:w,:w)"
            ),
            {"w": ws},
        )
        conn.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO project(id,workspace_id,name,description,status) "
                "VALUES (:p,:w,'ProjT02B','','active')"
            ),
            {"p": pid, "w": ws},
        )
        conn.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO video_item(id,project_id,title,position,status) "
                "VALUES (:v,:p,'VidT02B',0,'imported')"
            ),
            {"v": vid, "p": pid},
        )


def _fresh_engine(tmp_path: Path, name: str = "qc_repo.db") -> Any:
    engine = create_engine_for_path(tmp_path / name)
    Base.metadata.create_all(engine)
    _seed_ws_project_video(engine, ws=WS, pid=P1, vid=V1)
    _seed_ws_project_video(engine, ws=WS2, pid=P2, vid=V2)
    return engine


def _evidence(**over: Any) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "content": "detector-derived bytes",
        "metric_value": 0.0,
    }
    payload.update(over)
    return payload


def _create(
    repo: QCItemRepository, *, ewk: str = "ewk-t02b-1", **over: Any
) -> QCItemRecord:
    params: dict[str, Any] = {
        "workspace_id": WS,
        "project_id": P1,
        "video_item_id": V1,
        "layer_ref_type": "video_item",
        "layer_ref_id": V1,
        "reason_code": "silhouette_clipping",
        "evidence_window_key": ewk,
        "evidence": _evidence(),
        "severity": "warning",
        "category": "silhouette_clipping",
        "detector": "qc-t02b-detector",
        "detector_revision": "1.0.0",
        "confidence": 0.87,
        "confidence_source": "model",
        "checkpoint_ref": "ckpt-t02b",
    }
    params.update(over)
    return repo.create(**params)


# ── idempotent creation ──────────────────────────────────────────────────────


def test_create_returns_frozen_dto_and_persists(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _create(repo)

        import dataclasses

        assert dataclasses.is_dataclass(record)
        assert isinstance(record, QCItemRecord)
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.status = "hacked"  # type: ignore[misc]
        # DTO is a plain frozen dataclass — not an ORM row leaking out.
        assert not isinstance(record, Base.__class__)

        assert record.workspace_id == WS
        assert record.status == "open"
        assert record.revision == 1
        assert record.evidence == _evidence()
        assert record.segment_row_id is None
        assert record.segment_logical_id is None

        session.commit()
    with engine.connect() as conn:
        count = conn.execute(
            __import__("sqlalchemy").text("SELECT COUNT(*) FROM qc_item")
        ).scalar()
    assert count == 1


def test_create_same_natural_key_reuses_existing_row(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        first = _create(repo)
        # Same 7-column natural key, different evidence CONTENT: still reuse.
        second = _create(repo, evidence={"schema_version": 1, "content": "other"})
        assert second.id == first.id
        # Reuse does not silently overwrite the stored evidence.
        assert second.evidence == _evidence()
        session.commit()
    with engine.connect() as conn:
        count = conn.execute(
            __import__("sqlalchemy").text("SELECT COUNT(*) FROM qc_item")
        ).scalar()
    assert count == 1


def test_different_evidence_window_key_creates_distinct_item(
    tmp_path: Path,
) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        first = _create(repo, ewk="ewk-t02b-1")
        second = _create(repo, ewk="ewk-t02b-2")
        assert second.id != first.id
        session.commit()
    with engine.connect() as conn:
        count = conn.execute(
            __import__("sqlalchemy").text("SELECT COUNT(*) FROM qc_item")
        ).scalar()
    assert count == 2


def test_concurrent_create_same_natural_key_deterministic_reuse(
    tmp_path: Path,
) -> None:
    """C4-F1: a true uniqueness race must converge on ONE row.

    Both writers attempt the same natural key simultaneously (barrier before
    the atomic upsert). The repository uses a DB-level atomic
    INSERT..ON CONFLICT DO NOTHING followed by a consistent read — NEVER a
    check-then-insert window.
    """
    db = tmp_path / "qc_concurrent.db"
    engine = create_engine_for_path(db)
    Base.metadata.create_all(engine)
    _seed_ws_project_video(engine, ws=WS, pid=P1, vid=V1)

    barrier = threading.Barrier(2)
    results: list[tuple[int, str]] = []
    errors: list[Exception] = []

    def worker(tag: int) -> None:
        own = create_engine_for_path(db)
        try:
            with Session(own) as session:
                repo = QCItemRepository(session)
                barrier.wait(timeout=15)
                record = _create(repo, ewk="ewk-t02b-race")
                session.commit()
                results.append((tag, record.id))
        except Exception as err:  # pragma: no cover - failure evidence
            errors.append(err)

    threads = [threading.Thread(target=worker, args=(t,)) for t in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "concurrent worker hung"
    assert errors == [], f"concurrent create raised: {errors}"
    assert len(results) == 2

    ids = {item_id for _, item_id in results}
    assert len(ids) == 1, f"two rows for one natural key: {results}"

    with create_engine_for_path(db).connect() as conn:
        count = conn.execute(
            __import__("sqlalchemy").text(
                "SELECT COUNT(*) FROM qc_item WHERE evidence_window_key='ewk-t02b-race'"
            )
        ).scalar()
        ids2 = conn.execute(
            __import__("sqlalchemy").text(
                "SELECT id FROM qc_item WHERE evidence_window_key='ewk-t02b-race'"
            )
        ).scalars().all()
    assert count == 1
    assert set(ids2) == ids


# ── lifecycle: terminal transitions require fresh recheck evidence ───────────


def test_acknowledge_is_non_terminal_and_needs_no_evidence(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _create(repo)
        acknowledged = repo.acknowledge(record.id, WS)
        assert acknowledged.status == "acknowledged"
        assert acknowledged.revision == 2
        session.commit()


def test_terminal_transitions_reject_missing_evidence(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _create(repo)
        repo.acknowledge(record.id, WS)

        for transition in (
            lambda: repo.recheck_resolved(record.id, WS, evidence=None),
            lambda: repo.recheck_dismissed(record.id, WS, evidence=None),
            lambda: repo.recheck_resolved(record.id, WS, evidence={}),
        ):
            with pytest.raises(QCItemEvidenceRequiredError):
                transition()
        # Zero mutation on rejected attempts.
        fresh = repo.get(record.id, WS)
        assert fresh.status == "acknowledged"
        session.commit()


def test_resolve_with_fresh_recheck_evidence_reaches_terminal(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _create(repo)
        repo.acknowledge(record.id, WS)
        fresh_evidence = _evidence(content="recheck-pass-bytes", metric_value=1.0)
        resolved = repo.recheck_resolved(record.id, WS, evidence=fresh_evidence)
        assert resolved.status == "resolved"
        assert resolved.evidence == fresh_evidence
        assert resolved.revision == 3
        session.commit()


def test_dismiss_with_fresh_recheck_evidence(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _create(repo, severity="info", reason_code="av_sync_drift", category="av_sync_drift")
        dismissed = repo.recheck_dismissed(
            record.id, WS, evidence=_evidence(content="accepted-risk")
        )
        assert dismissed.status == "dismissed"
        session.commit()


def test_recheck_still_present_returns_to_open(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _create(repo)
        repo.acknowledge(record.id, WS)
        reopened = repo.recheck_failed(
            record.id, WS, evidence=_evidence(content="still-present")
        )
        assert reopened.status == "open"
        assert reopened.evidence == _evidence(content="still-present")
        session.commit()


def test_recheck_to_open_requires_evidence(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _create(repo)
        repo.acknowledge(record.id, WS)
        with pytest.raises(QCItemEvidenceRequiredError):
            repo.recheck_failed(record.id, WS, evidence=None)
        session.commit()


def test_terminal_states_are_terminal(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _create(repo)
        repo.acknowledge(record.id, WS)
        repo.recheck_resolved(record.id, WS, evidence=_evidence())

        for transition in (
            lambda: repo.acknowledge(record.id, WS),
            lambda: repo.recheck_resolved(record.id, WS, evidence=_evidence()),
            lambda: repo.recheck_dismissed(record.id, WS, evidence=_evidence()),
            lambda: repo.recheck_failed(record.id, WS, evidence=_evidence()),
        ):
            with pytest.raises(QCItemInvalidTransitionError):
                transition()

        dismissed = _create(repo, ewk="ewk-t02b-dismissed")
        repo.recheck_dismissed(dismissed.id, WS, evidence=_evidence())
        with pytest.raises(QCItemInvalidTransitionError):
            repo.recheck_failed(dismissed.id, WS, evidence=_evidence())
        session.commit()


def test_noop_transitions_rejected(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _create(repo)
        # open -> acknowledged is the legitimate first acknowledge.
        acknowledged = repo.acknowledge(record.id, WS)
        assert acknowledged.status == "acknowledged"
        # acknowledged -> acknowledged is a no-op and refused.
        with pytest.raises(QCItemInvalidTransitionError):
            repo.acknowledge(record.id, WS)
        session.commit()


def test_blocker_cannot_be_dismissed(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _create(repo, severity="blocker")
        with pytest.raises(QCItemBlockedDismissalError):
            repo.recheck_dismissed(record.id, WS, evidence=_evidence())
        # Zero mutation: still open.
        assert repo.get(record.id, WS).status == "open"
        session.commit()


# ── reads: get / ownership / list filters ────────────────────────────────────


def test_get_unknown_or_foreign_workspace_is_not_found(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _create(repo)
        with pytest.raises(QCItemNotFoundError):
            repo.get(record.id, "ws-does-not-exist")
        with pytest.raises(QCItemNotFoundError):
            repo.get("no-such-id", WS)
        # An item that lives in WS2 is not visible from WS (fail-closed).
        foreign = _create(
            repo, workspace_id=WS2, project_id=P2, video_item_id=V2,
            layer_ref_id=V2, ewk="ewk-t02b-foreign",
        )
        with pytest.raises(QCItemNotFoundError):
            repo.get(foreign.id, WS)
        assert repo.get(foreign.id, WS2).id == foreign.id
        session.commit()


def test_list_filters_and_workspace_scope(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        # 6 local items spanning status/severity/category/video_item_id.
        a = _create(repo, ewk="ewk-a", severity="blocker")  # open/blocker/clipping
        b = _create(repo, ewk="ewk-b", category="silhouette_clipping")  # open/warning/silhouette_clipping
        repo.acknowledge(b.id, WS)  # acknowledged
        c = _create(repo, ewk="ewk-c", category="identity_drift", reason_code="identity_drift")
        repo.acknowledge(c.id, WS)
        repo.recheck_resolved(c.id, WS, evidence=_evidence(content="pass"))  # resolved
        d = _create(repo, ewk="ewk-d", category="identity_drift", reason_code="identity_drift",
                    severity="info")
        repo.recheck_dismissed(d.id, WS, evidence=_evidence(content="accepted"))  # dismissed
        e = _create(repo, ewk="ewk-e", category="trajectory_drift",
                    reason_code="trajectory_drift")  # open/warning
        f = _create(repo, ewk="ewk-f", category="temporal_flicker", reason_code="temporal_flicker",
                    severity="blocker")  # open/blocker
        # Foreign item (different workspace AND project) must never appear.
        foreign = _create(repo, workspace_id=WS2, project_id=P2, video_item_id=V2,
                          layer_ref_id=V2, ewk="ewk-foreign")

        all_items, total = repo.list(WS, limit=100)
        assert total == 6
        local_ids = {r.id for r in all_items}
        assert foreign.id not in local_ids

        filtered, total = repo.list(WS, status="open")
        assert total == 3
        assert {r.id for r in filtered} == {a.id, e.id, f.id}

        filtered, total = repo.list(WS, severity="blocker")
        assert total == 2
        assert {r.id for r in filtered} == {a.id, f.id}

        filtered, total = repo.list(WS, category="silhouette_clipping")
        assert total == 2
        assert {r.id for r in filtered} == {a.id, b.id}

        filtered, total = repo.list(WS, video_item_id=V1)
        assert total == 6  # all local items share V1

        filtered, total = repo.list(WS, video_item_id="v-none")
        assert total == 0

        filtered, total = repo.list(WS, status="open", severity="blocker")
        assert total == 2
        assert {r.id for r in filtered} == {a.id, f.id}

        combined, total = repo.list(
            WS, project_id=P1, status="open", severity="blocker", category="silhouette_clipping"
        )
        assert total == 1
        assert combined[0].id == a.id

        # The foreign workspace has exactly its own item.
        empty, total = repo.list(WS2)
        assert total == 1
        assert [r.id for r in empty] == [foreign.id]
        session.commit()


def test_list_pagination_deterministic(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        for idx in range(5):
            _create(repo, ewk=f"ewk-page-{idx}")
        page1, total = repo.list(WS, limit=2, offset=0)
        page2, total2 = repo.list(WS, limit=2, offset=2)
        page3, total3 = repo.list(WS, limit=2, offset=4)
        assert total == total2 == total3 == 5
        assert len(page1) == 2 and len(page2) == 2 and len(page3) == 1
        # Deterministic ordering: created_at DESC, id DESC → disjoint pages.
        seen = {r.id for r in page1} | {r.id for r in page2} | {r.id for r in page3}
        assert len(seen) == 5
        session.commit()


def test_list_invalid_filter_value_rejected(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        _create(repo)
        with pytest.raises(QCItemParamsError):
            repo.list(WS, status="not-a-status")
        with pytest.raises(QCItemParamsError):
            repo.list(WS, severity="fatal")
        with pytest.raises(QCItemParamsError):
            repo.list(WS, category="not-a-category")
        session.commit()


# ── creation validation (fail-closed before DB) ──────────────────────────────


@pytest.mark.parametrize(
    "over",
    [
        {"severity": "fatal"},
        {"category": "not_a_category"},
        {"reason_code": "not_a_reason"},
        {"confidence": -0.1},
        {"confidence": 1.5},
        {"confidence_source": "alien"},
        {"segment_row_id": "seg-only", "segment_logical_id": None},
        {"segment_row_id": None, "segment_logical_id": "lin-only"},
    ],
    ids=[
        "severity",
        "category",
        "reason_code",
        "confidence_low",
        "confidence_high",
        "confidence_source",
        "partial_pair_left",
        "partial_pair_right",
    ],
)
def test_create_rejects_invalid_payload(tmp_path: Path, over: dict[str, Any]) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        with pytest.raises(QCItemParamsError):
            _create(repo, **over)
        session.commit()
    with engine.connect() as conn:
        count = conn.execute(
            __import__("sqlalchemy").text("SELECT COUNT(*) FROM qc_item")
        ).scalar()
    assert count == 0


def test_create_rejects_missing_evidence(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        repo = QCItemRepository(session)
        with pytest.raises(QCItemParamsError):
            _create(repo, evidence=None)
        session.commit()