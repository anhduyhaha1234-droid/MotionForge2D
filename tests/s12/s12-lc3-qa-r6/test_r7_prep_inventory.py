"""S12-LC3-QA R7 prep checks — freeze inventory, R5 env config, Q01/Q02 records.

QA-owned (Manager B lane).  These tests bind the R7 preparation records to the
real repository state: the frozen R7 additions table in `R6_INVENTORY.md`, the
exact R5 audit environment values documented in `R7_PREP.md`, the delivered
T03A migration-compatibility node set, and the explicit Q01 corrections.
They execute no product chain and claim no product pass.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / "docs" / "pm" / "sessions" / "S12-LC3-QA"
T03A_MODULE = REPO_ROOT / "tests" / "s12" / "s12-t03a" / "test_s12_export_migration.py"

R7_IDS = (
    [f"A0{i}" for i in range(1, 7)]
    + [f"B0{i}" for i in range(1, 7)]
    + [f"Q0{i}" for i in range(1, 5)]
    + [f"P0{i}" for i in range(1, 4)]
)
NOT_YET_IMPLEMENTED = (
    [f"A0{i}" for i in range(1, 7)]
    + ["B01", "B02"]
)
DELIVERED_BRIDGE = ("B03", "B04", "B05", "B06")
R7_EXECUTED_LABELS = {
    "Q04": "EXECUTION INPUT @c3cf0955",
    "P01": "EXECUTED_BLOCKED_S12_READINESS @c3cf0955",
    "P02": "EXECUTED @c3cf0955",
    "P03": "PARTIAL @c3cf0955",
}
EXPECTED_T03A_NODES = (
    "test_single_head_is_current_head",
    "test_history_links_both_linear_edges",
    "test_history_walk_from_head_is_linear_to_parent",
    "test_fresh_upgrade_creates_tables",
    "test_upgrade_from_parent_retains_data_to_current_head",
    "test_upgrade_to_head_backfills_lineage_from_seeded_run",
    "test_downgrade_with_rows_refuses_at_current_head",
    "test_export_domain_guard_text_is_retained",
    "test_empty_downgrade_unwinds_lineage_then_tables",
)


def _inventory_text() -> str:
    return (DOCS / "R6_INVENTORY.md").read_text(encoding="utf-8")


def _prep_text() -> str:
    return (DOCS / "R7_PREP.md").read_text(encoding="utf-8")


def _report_text() -> str:
    return (DOCS / "R6_REPORT.md").read_text(encoding="utf-8")


def _r7_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        match = re.match(r"^\|\s*(A0[1-6]|B0[1-6]|Q0[1-4]|P0[1-3])\s*\|", line)
        if match:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            rows.append(cells)
    return rows


def _module_nodes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith(
            "test_"
        ):
            found.add(item.name)
    return found


def test_r7_additions_table_freezes_all_case_ids_with_owner_and_outcome() -> None:
    rows = _r7_rows(_inventory_text())
    assert [row[0] for row in rows] == R7_IDS
    by_id = {row[0]: row for row in rows}
    for case_id, row in by_id.items():
        assert len(row) == 6, (case_id, row)
        _case, owner, source, node, outcome, destination = row
        assert owner, case_id
        assert source, case_id
        assert node, case_id
        assert len(outcome) > 40, case_id
        assert "s12-r7-two-managers/20260916T0351Z" in destination, case_id
    for case_id in NOT_YET_IMPLEMENTED:
        assert "to be frozen by owner" in by_id[case_id][3], case_id
    for case_id, label in R7_EXECUTED_LABELS.items():
        assert label in by_id[case_id][3], (case_id, by_id[case_id][3][:80])
    for case_id in DELIVERED_BRIDGE:
        assert "DELIVERED VERBATIM @c49a578" in by_id[case_id][3], case_id
        assert "tests/s12/s12-public-authority-bridge/" in by_id[case_id][2], case_id
    assert "EXECUTED_THIS_TURN" in by_id["Q01"][3]
    assert "DELIVERED_THIS_TURN_VERIFIED" in by_id["Q02"][3]
    assert "EXECUTED_THIS_TURN_VERIFIED" in by_id["Q03"][3]


def test_r7_prep_doc_records_exact_r5_env_and_verification_procedure() -> None:
    text = _prep_text()
    assert "S12_R5_CANDIDATE_ROOT" in text
    assert "S12_R5_EXPECTED_CANDIDATE_SHA" in text
    assert "C:/Users/Admin/MotionForge2D-worktrees/s12-lc3-luna-integration" in text
    assert "35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86" in text
    assert "codex/s12-lc3-luna-integration" in text
    assert "rev-parse HEAD" in text
    assert "pytest tests/s12/s12-lc3-qa-r5/" in text


def test_r7_q02_delivered_nodes_exist_in_the_t03a_module() -> None:
    section = _prep_text().split("Delivered node IDs (full module, all executed):", 1)[1]
    section = section.split("\n\n", 1)[0]
    names = set(re.findall(r"test_[a-z0-9_]+", section))
    assert names == set(EXPECTED_T03A_NODES)
    module_nodes = _module_nodes(T03A_MODULE)
    for name in EXPECTED_T03A_NODES:
        assert name in module_nodes, name


def test_r7_corrections_are_explicit_and_old_claims_retired() -> None:
    report = _report_text()
    assert "NOT_REACHED / NOT_REEXECUTED" in report
    for marker in ("F01", "F03", "F04", "F05", "PRODUCER_PRESENT_WITH_OPEN_F03"):
        assert marker in report, marker
    inventory = _inventory_text()
    assert "no longer `BLOCKED_DEPENDENCY`" in inventory
    assert "PRODUCER_PRESENT_WITH_OPEN_F03" in inventory
    assert "EXECUTED_BLOCKED_S10_SHOTS_OVERLAP" in inventory


def test_r7_patch_kept_the_frozen_mv_b01_row_counts() -> None:
    text = _inventory_text()
    for pattern, expected in ((r"M\d{2}", 19), (r"V\d{2}", 15), (r"B01-[A-I]", 9)):
        count = sum(
            1 for line in text.splitlines() if re.match(rf"^\|\s*{pattern}\s*\|", line)
        )
        assert count == expected, (pattern, count)
    assert "## Reconciliation — delivered node IDs" in text
