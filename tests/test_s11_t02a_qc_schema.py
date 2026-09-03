"""S11-T02A QCItem schema tests (C4-F1 contract, lane-A QC_DOMAIN_CONTRACT).

Verifies the QCItem persistence contract on a FRESH temp SQLite database
built from ORM metadata (``Base.metadata.create_all``):

1. FK ``segment_row_id`` points at the exact immutable ``occurrence_segment``
   row (RESTRICT, never a name/lineage join).
2. Two lineage versions sharing one ``logical_id`` remain valid and a QCItem
   neos the exact ``segment_row_id`` it was created with.
3. A partial segment pair (one of ``segment_row_id`` / ``segment_logical_id``
   NULL while the other is set) is rejected by the DB-level pair-null CHECK.
4. Duplicate — sequential AND concurrent — natural key never creates two
   rows (UNIQUE on all 7 non-null natural-key columns).
5. PRAGMA foreign_key_check = 0 after a full seed + inserts.
6. SQLite NULL semantics cannot break uniqueness: every natural-key component
   is NOT NULL, and the unique index is non-partial.

Plus lane-A §1.3 rule 2: severity=blocker AND status=dismissed is rejected at
DB level; every enum CHECK literal is DERIVED from its single Python tuple
(CONTACT_KIND_CHECK_SQL pattern).

Runs only against per-test temp DB files under the pytest basetemp; never
touches MAIN data.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.persistence import create_engine_for_path
from app.persistence.models import (
    QC_ITEM_CATEGORIES,
    QC_ITEM_CATEGORY_CHECK_SQL,
    QC_ITEM_SEVERITIES,
    QC_ITEM_SEVERITY_CHECK_SQL,
    QC_ITEM_STATUSES,
    QC_ITEM_STATUS_CHECK_SQL,
    QCItem,
    QC_REASON_CODES,
    QC_REASON_CODE_CHECK_SQL,
)
from app.persistence.models import Base

WS = "ws-t02a-schema"
P1 = "p-t02a-schema"
V1 = "v-t02a-schema"
ROLE = "r-t02a-schema"
SCENE = "sc-t02a-schema"
SEG_A = "seg-t02a-lin1"
SEG_B = "seg-t02a-lin2"
LOGICAL = "lin-t02a-shared"

NATURAL_KEY_COLS = (
    "workspace_id",
    "project_id",
    "video_item_id",
    "layer_ref_type",
    "layer_ref_id",
    "reason_code",
    "evidence_window_key",
)

_QC_COLS = (
    "id, workspace_id, project_id, video_item_id, segment_row_id, "
    "segment_logical_id, layer_ref_type, layer_ref_id, reason_code, "
    "evidence_window_key, evidence_json, status, severity, category, detector, "
    "detector_revision, confidence, confidence_source, checkpoint_ref"
)

_SEG_SQL = text(
    "INSERT INTO occurrence_segment "
    "(id, workspace_id, project_id, video_item_id, role_id, scene_id, "
    "logical_id, lineage_version, name, kind, start_frame, end_frame, "
    "start_time_ms, end_time_ms, source_generation, confidence, "
    "confidence_source, reasons_json, visibility, z_order, superseded_by_id) "
    "VALUES (:seg_id, :w, :p, :v, :role, :scene, :logical, :lin, :name, "
    "'character', 0, 10, 0, 1000, '1', 0.9, 'model', '[]', 'visible', 0, :sup)"
)


def _seed(engine) -> None:
    """Seed workspace/project/video_item/scene/object_role + TWO occurrence
    segments that are two lineage VERSIONS of the SAME logical_id.

    NOTE: create_all builds the ORM DDL (Python-side defaults only), so every
    NOT NULL column is supplied explicitly in the raw INSERTs.
    """
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO workspace(id,name) VALUES (:w,:w)"), {"w": WS}
        )
        conn.execute(
            text(
                "INSERT INTO project(id,workspace_id,name,description,status) "
                "VALUES (:p,:w,'ProjT02A','','active')"
            ),
            {"p": P1, "w": WS},
        )
        conn.execute(
            text(
                "INSERT INTO video_item(id,project_id,title,position,status) "
                "VALUES (:v,:p,'VidT02A',0,'imported')"
            ),
            {"v": V1, "p": P1},
        )
        conn.execute(
            text(
                "INSERT INTO scene(id,video_item_id,position,start_frame,"
                "end_frame,start_time_ms,end_time_ms,status) "
                "VALUES (:s,:v,0,0,10,0,1000,'pending')"
            ),
            {"s": SCENE, "v": V1},
        )
        conn.execute(
            text(
                "INSERT INTO object_role(id,workspace_id,project_id,"
                "video_item_id,source_generation,name,kind,status) "
                "VALUES (:r,:w,:p,:v,'1','Hero','character','confirmed')"
            ),
            {"r": ROLE, "w": WS, "p": P1, "v": V1},
        )
        # lineage version 1 (root row) and version 2 (successor archives v1).
        conn.execute(
            _SEG_SQL,
            {
                "seg_id": SEG_A,
                "w": WS,
                "p": P1,
                "v": V1,
                "role": ROLE,
                "scene": SCENE,
                "logical": LOGICAL,
                "lin": 1,
                "name": "Hero-v1",
                "sup": None,
            },
        )
        conn.execute(
            _SEG_SQL,
            {
                "seg_id": SEG_B,
                "w": WS,
                "p": P1,
                "v": V1,
                "role": ROLE,
                "scene": SCENE,
                "logical": LOGICAL,
                "lin": 2,
                "name": "Hero-v2",
                "sup": SEG_A,
            },
        )


def _qc_params(qid: str, **over) -> dict:
    params = {
        "id": qid,
        "workspace_id": WS,
        "project_id": P1,
        "video_item_id": V1,
        "segment_row_id": SEG_B,
        "segment_logical_id": LOGICAL,
        "layer_ref_type": "video_item",
        "layer_ref_id": V1,
        "reason_code": "silhouette_clipping",
        "evidence_window_key": f"ewk-{qid}",
        "evidence_json": '{"schema_version": 1, "content": "x"}',
        "status": "open",
        "severity": "warning",
        "category": "silhouette_clipping",
        "detector": "qc-lane-a",
        "detector_revision": "1.0.0",
        "confidence": 0.87,
        "confidence_source": "model",
        "checkpoint_ref": "ckpt-t02a",
    }
    params.update(over)
    return params


def _insert_qc(engine, qid: str, **over) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO qc_item ({_QC_COLS}) VALUES ("
                ":id,:workspace_id,:project_id,:video_item_id,:segment_row_id,"
                ":segment_logical_id,:layer_ref_type,:layer_ref_id,:reason_code,"
                ":evidence_window_key,:evidence_json,:status,:severity,:category,"
                ":detector,:detector_revision,:confidence,:confidence_source,"
                ":checkpoint_ref)"
            ),
            _qc_params(qid, **over),
        )


def _fresh_engine(tmp_path: Path):
    engine = create_engine_for_path(tmp_path / "qc_schema.db")
    Base.metadata.create_all(engine)
    _seed(engine)
    return engine


# ── C4-F1 test 1: FK segment_row_id → immutable occurrence row ──────────────


def test_segment_fk_points_to_immutable_occurrence_row(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    _insert_qc(engine, "q-fk-ok")

    # True FK declared: segment_row_id -> occurrence_segment.id.
    with engine.connect() as conn:
        fks = [
            (r[3], r[2])
            for r in conn.execute(text("PRAGMA foreign_key_list('qc_item')"))
        ]
    assert ("segment_row_id", "occurrence_segment") in fks

    # FK is enforced: a dangling segment_row_id is rejected.
    with pytest.raises(IntegrityError):
        _insert_qc(
            engine,
            "q-fk-bad",
            segment_row_id="seg-does-not-exist",
            segment_logical_id="lin-does-not-exist",
        )

    # Immutable: deleting the referenced immutable occurrence row is refused
    # (RESTRICT), so a QCItem can never silently point at nothing.
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text("DELETE FROM occurrence_segment WHERE id=:sid"), {"sid": SEG_B}
        )


# ── C4-F1 test 2: two lineage versions, same logical_id, exact neoing ───────


def test_lineage_versions_share_logical_id_and_qcitem_neos_exact_row(
    tmp_path: Path,
) -> None:
    engine = _fresh_engine(tmp_path)

    with engine.connect() as conn:
        versions = conn.execute(
            text(
                "SELECT id, lineage_version FROM occurrence_segment "
                "WHERE logical_id=:l ORDER BY lineage_version"
            ),
            {"l": LOGICAL},
        ).all()
    assert [(r[0], r[1]) for r in versions] == [(SEG_A, 1), (SEG_B, 2)]

    # Both lineage versions are valid QCItem anchors; each QCItem neos the
    # EXACT row it was created with (immutable id, not the lineage logical_id).
    _insert_qc(engine, "q-lin-a", segment_row_id=SEG_A, evidence_window_key="ewk-a")
    _insert_qc(engine, "q-lin-b", segment_row_id=SEG_B, evidence_window_key="ewk-b")

    with engine.connect() as conn:
        rows = {
            r[0]: r[1]
            for r in conn.execute(
                text(
                    "SELECT id, segment_row_id FROM qc_item "
                    "WHERE id IN ('q-lin-a','q-lin-b') ORDER BY id"
                )
            )
        }
    assert rows == {"q-lin-a": SEG_A, "q-lin-b": SEG_B}


# ── C4-F1 test 3: partial segment pair rejected by CHECK ────────────────────


@pytest.mark.parametrize(
    "over",
    [
        {"segment_row_id": SEG_A, "segment_logical_id": None},
        {"segment_row_id": None, "segment_logical_id": LOGICAL},
    ],
    ids=["row-without-logical", "logical-without-row"],
)
def test_partial_segment_pair_rejected_by_check(
    tmp_path: Path, over: dict
) -> None:
    engine = _fresh_engine(tmp_path)
    with pytest.raises(IntegrityError):
        _insert_qc(engine, "q-partial", **over)

    # Both NULL (video-level issue, no segment anchor) stays valid.
    _insert_qc(
        engine,
        "q-video-level",
        segment_row_id=None,
        segment_logical_id=None,
    )


# ── C4-F1 test 4: duplicate + concurrent duplicate natural key ──────────────


def _natural_key() -> dict:
    return {
        "workspace_id": WS,
        "project_id": P1,
        "video_item_id": V1,
        "layer_ref_type": "video_item",
        "layer_ref_id": V1,
        "reason_code": "silhouette_clipping",
        "evidence_window_key": "ewk-same",
    }


def test_duplicate_natural_key_rejected(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    _insert_qc(engine, "q-dup-1", **_natural_key())
    with pytest.raises(IntegrityError):
        _insert_qc(engine, "q-dup-2", **_natural_key())

    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM qc_item "
                "WHERE evidence_window_key='ewk-same'"
            )
        ).scalar()
    assert count == 1


def test_concurrent_duplicate_natural_key_creates_one_row(tmp_path: Path) -> None:
    db = tmp_path / "qc_concurrent.db"
    engine = create_engine_for_path(db)
    Base.metadata.create_all(engine)
    _seed(engine)

    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, int]] = []

    def worker(tag: int) -> None:
        own = create_engine_for_path(db)
        try:
            with own.begin() as conn:
                barrier.wait(timeout=15)
                conn.execute(
                    text(
                        f"INSERT INTO qc_item ({_QC_COLS}) VALUES ("
                        ":id,:workspace_id,:project_id,:video_item_id,"
                        ":segment_row_id,:segment_logical_id,:layer_ref_type,"
                        ":layer_ref_id,:reason_code,:evidence_window_key,"
                        ":evidence_json,:status,:severity,:category,:detector,"
                        ":detector_revision,:confidence,:confidence_source,"
                        ":checkpoint_ref)"
                    ),
                    _qc_params(
                        f"q-conc-{tag}", evidence_window_key="ewk-same"
                    ),
                )
            outcomes.append(("ok", tag))
        except IntegrityError:
            outcomes.append(("dup", tag))

    t1 = threading.Thread(target=worker, args=(1,))
    t2 = threading.Thread(target=worker, args=(2,))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert not t1.is_alive() and not t2.is_alive(), "concurrent worker hung"
    assert sorted(tag for _, tag in outcomes) == [1, 2]
    assert sum(1 for outcome, _ in outcomes if outcome == "dup") == 1

    with create_engine_for_path(db).connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM qc_item "
                "WHERE evidence_window_key='ewk-same'"
            )
        ).scalar()
    assert count == 1, "concurrent duplicate created more than one row"


# ── C4-F1 test 5: PRAGMA foreign_key_check = 0 ──────────────────────────────


def test_foreign_key_check_zero_after_full_seed(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    _insert_qc(engine, "q-fk-a", segment_row_id=SEG_A)
    _insert_qc(engine, "q-fk-b", segment_row_id=SEG_B)
    _insert_qc(
        engine,
        "q-fk-c",
        segment_row_id=None,
        segment_logical_id=None,
        reason_code="identity_drift",
        category="identity_drift",
    )
    with engine.connect() as conn:
        violations = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        integrity = conn.execute(text("PRAGMA integrity_check")).fetchall()
    assert violations == []
    assert str(integrity[0][0]).strip().lower() == "ok"


# ── C4-F1 test 6: NULL semantics cannot break uniqueness ────────────────────


@pytest.mark.parametrize("col", NATURAL_KEY_COLS)
def test_null_in_any_natural_key_component_rejected(tmp_path: Path, col: str) -> None:
    engine = _fresh_engine(tmp_path)
    with pytest.raises(IntegrityError):
        _insert_qc(engine, "q-null", **{col: None})


def test_natural_key_unique_index_is_non_partial_full_7_columns(
    tmp_path: Path,
) -> None:
    engine = _fresh_engine(tmp_path)
    with engine.connect() as conn:
        # SQLite stores the table-level UNIQUE constraint as an auto
        # index (name sqlite_autoindex_qc_item_N, origin='u') whose
        # sqlite_master.sql is NULL; the partial flag is the authority
        # for "non-partial" (a partial index would let NULLs escape).
        indexes = conn.execute(text("PRAGMA index_list('qc_item')")).fetchall()
        unique_indexes = [r for r in indexes if r[3] == 'u']
        assert len(unique_indexes) == 1, f"expected one unique index, got {unique_indexes}"
        _, name, is_unique, origin, partial = unique_indexes[0]
        assert is_unique == 1
        assert partial == 0, "natural-key unique index must be non-partial"
        cols = [
            r[2]
            for r in conn.execute(text(f"PRAGMA index_info('{name}')"))
        ]
    assert tuple(cols) == NATURAL_KEY_COLS


# ── lane-A §1.3 rule 2: blocker + dismissed fail-closed at DB level ─────────


def test_blocker_dismissed_rejected_db_level(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    with pytest.raises(IntegrityError):
        _insert_qc(engine, "q-blocked-dismissed", severity="blocker", status="dismissed")

    # Adjacent valid combinations still work.
    _insert_qc(engine, "q-blocker-open", severity="blocker", status="open")
    _insert_qc(engine, "q-info-dismissed", severity="info", status="dismissed")
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM qc_item")).scalar()
    assert count == 2


# ── enum CHECKs: status / severity / category / reason_code / confidence ────


@pytest.mark.parametrize(
    "over",
    [
        {"status": "bogus"},
        {"severity": "fatal"},
        {"category": "not_a_category"},
        {"reason_code": "not_a_reason"},
        {"category": "clipping"},
        {"reason_code": "z_order"},
        {"reason_code": "audio_timecode"},
        {"confidence_source": "alien"},
        {"confidence": -0.1},
        {"confidence": 1.5},
    ],
    ids=[
        "status",
        "severity",
        "category",
        "reason_code",
        "category-old-removed",
        "reason_code-renamed",
        "reason_code-audio-timecode-removed",
        "confidence_source",
        "confidence-low",
        "confidence-high",
    ],
)
def test_enum_and_range_checks_reject_outside_values(
    tmp_path: Path, over: dict
) -> None:
    engine = _fresh_engine(tmp_path)
    with pytest.raises(IntegrityError):
        _insert_qc(engine, "q-bad-enum", **over)


# ── single-authority derivation (CONTACT_KIND_CHECK_SQL pattern) ────────────


def _derive_check_sql(column: str, values: tuple[str, ...]) -> str:
    return (
        column
        + " IN ("
        + ",".join("'" + v + "'" for v in values)
        + ")"
    )


def test_enum_check_sql_derived_from_single_python_tuple() -> None:
    assert QC_ITEM_STATUSES == ("open", "acknowledged", "resolved", "dismissed")
    assert QC_ITEM_SEVERITIES == ("blocker", "warning", "info")
    assert QC_ITEM_CATEGORIES == (
        "trajectory_drift",
        "cut_drift",
        "contact_break",
        "z_order_error",
        "silhouette_clipping",
        "identity_drift",
        "edge_halo",
        "temporal_flicker",
        "audio_missing",
        "av_sync_drift",
    )
    assert QC_REASON_CODES == QC_ITEM_CATEGORIES
    # Binding completeness (Decision B + D): all 10 codes present,
    # including edge_halo and the two T03E audio codes.
    for code in (
        "edge_halo",
        "audio_missing",
        "av_sync_drift",
        "z_order_error",
        "silhouette_clipping",
        "identity_drift",
        "temporal_flicker",
    ):
        assert code in QC_ITEM_CATEGORIES
        assert code in QC_REASON_CODES

    # Every SQL literal is DERIVED from its tuple — rebuilding from the tuple
    # must reproduce the constant byte-for-byte (single authority, no drift).
    assert QC_ITEM_STATUS_CHECK_SQL == _derive_check_sql("status", QC_ITEM_STATUSES)
    assert QC_ITEM_SEVERITY_CHECK_SQL == _derive_check_sql(
        "severity", QC_ITEM_SEVERITIES
    )
    assert QC_ITEM_CATEGORY_CHECK_SQL == _derive_check_sql(
        "category", QC_ITEM_CATEGORIES
    )
    assert QC_REASON_CODE_CHECK_SQL == _derive_check_sql("reason_code", QC_REASON_CODES)


# ── field-level contract (lane-A §1.1 / acceptance #4) ─────────────────────


def test_qcitem_column_contract(tmp_path: Path) -> None:
    engine = _fresh_engine(tmp_path)
    cols = {c["name"]: c for c in inspect(engine).get_columns("qc_item")}

    assert cols["segment_row_id"]["nullable"] is True
    assert cols["segment_logical_id"]["nullable"] is True
    for name in (
        "workspace_id",
        "project_id",
        "video_item_id",
        "layer_ref_type",
        "layer_ref_id",
        "reason_code",
        "evidence_window_key",
        "evidence_json",
        "status",
        "severity",
        "category",
        "detector",
        "detector_revision",
        "confidence",
        "confidence_source",
        "checkpoint_ref",
    ):
        assert cols[name]["nullable"] is False, f"{name} must be NOT NULL"

    # TimestampMixin reuse.
    for name in ("created_at", "updated_at", "revision"):
        assert name in cols, f"TimestampMixin column {name} missing"

    # segment_logical_id is a scoped lineage VALUE, not an FK.
    fk_targets = {
        r[3]: r[2]
        for r in engine.connect()
        .execute(text("PRAGMA foreign_key_list('qc_item')"))
        .fetchall()
    }
    assert fk_targets["segment_row_id"] == "occurrence_segment"
    assert "segment_logical_id" not in fk_targets

    # Model exposes the enum tuples as module constants (contract surface).
    assert QCItem.__tablename__ == "qc_item"