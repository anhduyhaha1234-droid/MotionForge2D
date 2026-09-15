"""S12-LC3-QA R6 finite inventory freeze — QA-owned packet checks only.

Freezes, per R6_ACCEPTANCE.md, the executable node IDs and parameter IDs for
M01-M19 (RETRY), V01-V15 (VAL) and B01-A..B01-I (producer + QA-owned B01-I),
with expected typed outcomes, all-row Run/Job counts and raw evidence paths.
Preserves the R04/R07/R08 retained gates as machine-checkable assertions,
hash-proves the corrected reviewer assertions it restates, and re-checks the
original 62-row authority ("no more, no fewer").

These are packet/static checks: no owner-lane or product test is executed,
and no row here is a pass. Collection is not execution.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / "docs" / "pm" / "sessions" / "S12-LC3-QA"
INVENTORY_PATH = DOCS / "R6_INVENTORY.md"
REPORT_PATH = DOCS / "R6_REPORT.md"
R5_MATRIX_PATH = DOCS / "R5_MATRIX.md"

REVIEW_ROOT = Path(
    os.environ.get(
        "S12_R6_REVIEW_ROOT",
        "C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs",
    )
)

AUTHORITY_IDS = (
    [f"C{number:02}" for number in range(1, 33)]
    + [f"S{number:02}" for number in range(1, 11)]
    + [f"P{number:02}" for number in range(1, 11)]
    + [f"R{number:02}" for number in range(1, 11)]
)

WAITING_BY_LANE = {
    "RETRY": "FROZEN_WAITING_FOR_RETRY",
    "VAL": "FROZEN_WAITING_FOR_VAL",
    "B01": "FROZEN_WAITING_FOR_B01",
}

PROVENANCE = {
    "s12-r4-independent-review-20260912/R3_MATRIX_AUTHORITY.md":
        "98C929FAB41A52BF5EF148A088230F0D87ADBFB28FD2BCE891C40DC9E6A4EC54",
    "s12-r5-independent-review-20260914/REVIEW.md":
        "B85ED4B6EC5E2740B2BE2C329D91B22D64D196E17F5AA87335C7B7F083826302",
    "s12-r5-independent-review-20260914/test_review_r5_identity.py":
        "155A2D2C32E31FEFC9F7CF6DC24C0D5FA1897FA53A4C4517F7556DD6E1146985",
    "s12-r5-independent-review-20260914/test_review_r5_publication.py":
        "5D5DB9C46EA20257EC9452038102385C9F5E4661572428B8D20CE67E844DB087",
    "s12-r5-independent-review-20260914/test_review_r5_publication.setup-v1.txt":
        "DBF1A83BEE14500CA65C0519748D3D6DF9446D76E3E9AB6858076C87B47D8ED4",
    "s12-r6-hermes-deepseek-review-20260915/R6_ACCEPTANCE.md":
        "3CDDE8605501D8A7BEA6A540800257BF6ACF7D33D27831FB0C7EB33F37D0434E",
    "s12-r6-hermes-deepseek-review-20260915/REVIEW.md":
        "AD5FFF3B97BF470FF007022C42FD94B6C947CA44858EE32F77D85905CE2ECEFB",
    "s12-r6-hermes-deepseek-review-20260915/NEXT_HERMES_PROMPT.md":
        "29E6D6C6D2DA0425453C486C21BD21C3BC9703F47E327C0986762A44FB42BFFD",
    "s12-r6-independent-review-20260914/REVIEW.md":
        "C61220A6DCB7659409D0F7236F98783545BCAB0858E2CC85612599AC51DA45D1",
}

IN_REPO_IMMUTABLE = {
    "docs/pm/sessions/S12-LC3-QA/R5_MATRIX.md":
        "D601E8FACA20E096D44E8F97A0FA783890432BB63D441269B2DCE88ABC90735C",
    "docs/pm/sessions/S12-LC3-QA/R5_REPORT.md":
        "5CCF38003CE077565F9733B74475084B48CA20EC1D2F3A31F9EDCDA7642EDEB2",
    "docs/pm/sessions/S12-LC3-QA/R5_COMMAND_LEDGER.md":
        "5F3E7AAD03AA6F303CECDA87E063FE11164013FECF55763907D5DA5E4BFAF794",
}


def _sha256_norm(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest().upper()


def _doc() -> str:
    assert INVENTORY_PATH.is_file(), INVENTORY_PATH
    return INVENTORY_PATH.read_text(encoding="utf-8")


def _case_rows(text: str, prefix: str) -> list[list[str]]:
    rows: list[list[str]] = []
    pattern = re.compile(rf"^\|\s*{prefix}\s*\|")
    for line in text.splitlines():
        if pattern.match(line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def _module_nodes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith(
            "test_"
        ):
            found.add(item.name)
        if isinstance(item, ast.ClassDef):
            for child in item.body:
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name.startswith("test_")
                ):
                    found.add(child.name)
    return found


def test_r6_finite_inventory_locks_mv_b01_case_sets() -> None:
    text = _doc()
    m_rows = _case_rows(text, r"M\d{2}")
    v_rows = _case_rows(text, r"V\d{2}")
    b_rows = _case_rows(text, r"B01-[A-I]")
    assert [row[0] for row in m_rows] == [f"M{number:02}" for number in range(1, 20)]
    assert [row[0] for row in v_rows] == [f"V{number:02}" for number in range(1, 16)]
    assert [row[0] for row in b_rows] == [f"B01-{letter}" for letter in "ABCDEFGHI"]
    all_ids = [row[0] for row in m_rows + v_rows + b_rows]
    assert len(all_ids) == 19 + 15 + 9
    assert len(set(all_ids)) == len(all_ids), all_ids


def test_r6_finite_inventory_rows_are_complete_and_stable() -> None:
    text = _doc()
    rows = (
        _case_rows(text, r"M\d{2}")
        + _case_rows(text, r"V\d{2}")
        + _case_rows(text, r"B01-[A-I]")
    )
    assert len(rows) == 43
    nodes: list[str] = []
    node_owner: dict[str, str] = {}
    for row in rows:
        assert len(row) == 9, row
        _case, lane, module, node, params, outcome, counts, evidence, status = row
        assert lane in {"RETRY", "VAL", "B01", "QA"}, row
        assert module.startswith("tests/"), row
        parts = [part.strip() for part in node.split(" + ")]
        assert parts and all(re.match(r"^test_[A-Za-z0-9_]+$", part) for part in parts), row
        assert params and outcome and counts and evidence and status, row
        assert "s12-r6-hermes/<uniqueUTC>" in evidence, row
        assert "{before,after}.raw.txt" in evidence, row
        assert len(set(parts)) == len(parts), ("duplicate node inside row", row[0])
        for part in parts:
            owner = node_owner.get(part)
            if owner is not None and {owner, row[0]} != {"B01-D", "B01-G"}:
                raise AssertionError((part, owner, row[0]))
            node_owner[part] = row[0]
        nodes.extend(parts)
    assert len(nodes) == 55
    by_case = {row[0]: row for row in rows}
    assert "field[" in by_case["M04"][4] and "site[" in by_case["M04"][4]
    assert "client_ids[" in by_case["M19"][4]
    assert "b_first" in by_case["V11"][4] and "a_first" in by_case["V11"][4]
    assert "basename155" in by_case["V14"][4]
    assert "1/1" in by_case["M01"][6]
    assert "2/2" in by_case["M02"][6]
    assert "3/3" in by_case["M03"][6]
    assert "2/2" in by_case["M08"][6] and "2/3" in by_case["M08"][6]
    assert "2/1" in by_case["M14"][6] and "2/2" in by_case["M14"][6]
    assert "1/1" in by_case["M17"][6]
    assert "2/2" in by_case["M19"][6]


def test_r6_matrix_has_exactly_the_original_62_unique_ids() -> None:
    matrix = R5_MATRIX_PATH.read_text(encoding="utf-8")
    main = matrix.split("## C01-C32", maxsplit=1)[1].split(
        "## Immutable probe inventory", maxsplit=1
    )[0]
    ids: list[str] = []
    for line in main.splitlines():
        if re.match(r"^\|\s*(?:C|S|P|R)\d{2}\s*\|", line):
            ids.append(line.strip().strip("|").split("|")[0].strip())
    assert len(ids) == 62
    assert len(set(ids)) == 62, ids
    assert ids == AUTHORITY_IDS
    text = _doc()
    restated = next(
        line for line in text.splitlines() if line.startswith("AUTHORITY-ID-LIST:")
    )
    assert restated.removeprefix("AUTHORITY-ID-LIST:").split() == AUTHORITY_IDS
    assert "No row is APPROVED or CLOSED" in text
    assert "carried verbatim" in text


def test_r6_preserved_gates_r04_r07_r08_are_machine_checkable() -> None:
    text = _doc()
    assert "R04 lost-ack/SHA prohibition" in text
    assert "successful commit / lost acknowledgement" in text
    assert "never adopt by matching SHA alone" in text
    assert "chunks bytes/mtime preserved" in text
    assert "R07 Windows companion paths" in text
    assert "interrupted temp" in text
    assert "basename155+" in text
    assert "export_master.mp4" in text
    assert "R08 exact collection" in text
    assert "complete applicable modules" in text
    assert "no new skips" in text
    assert "collection is not execution" in text
    for family in (
        "source identity/timing/provenance",
        "audio content/start-end",
        "audio deadline/error/cancel",
        "geometry",
        "migration/hash/Job binding",
        "stale/readiness/ownership",
    ):
        assert family in text, family
    rows = {row[0]: row for row in _case_rows(text, r"M\d{2}") + _case_rows(text, r"V\d{2}")}
    assert "lost acknowledgement" in rows["M16"][5].lower()
    assert "lost ack" in rows["V07"][5].lower()
    assert "sha" in rows["V07"][5].lower() and "forbid" in rows["V07"][5].lower()
    assert "basename155" in rows["V14"][4]
    assert "export_master.mp4" in rows["V14"][5]
    assert "interrupted_temp" in rows["V15"][3]


def test_r6_reviewer_assertion_provenance_hash_proven() -> None:
    text = _doc()
    for relative, digest in PROVENANCE.items():
        path = REVIEW_ROOT / relative
        assert path.is_file(), (relative, "reviewer artifact missing")
        assert _sha256_norm(path) == digest, relative
        assert digest in text, relative
        assert relative in text, relative
    for relative, digest in IN_REPO_IMMUTABLE.items():
        path = REPO_ROOT / relative
        assert path.is_file(), relative
        assert _sha256_norm(path) == digest, relative
        assert digest in text, relative
        assert relative in text, relative
    assert "test_review_r5_publication.setup-v1.txt" in text
    assert "s12_export_lease" in text
    assert "corrected reviewer harness" in text


def test_r6_owner_modules_are_frozen_waiting_or_present() -> None:
    text = _doc()
    rows = (
        _case_rows(text, r"M\d{2}")
        + _case_rows(text, r"V\d{2}")
        + _case_rows(text, r"B01-[A-H]")
    )
    for row in rows:
        case, lane, module, node, _params, _outcome, _counts, _evidence, status = row
        target = REPO_ROOT / module
        if target.is_file():
            module_nodes = _module_nodes(target)
            for part in (piece.strip() for piece in node.split(" + ")):
                assert part in module_nodes, (case, module, part)
        else:
            assert status == WAITING_BY_LANE[lane], (case, lane, status)
    b01i_rows = _case_rows(text, r"B01-I")
    assert len(b01i_rows) == 1
    assert b01i_rows[0][8] == "EXECUTED_BLOCKED_S10_SHOTS_OVERLAP"
    assert b01i_rows[0][3].startswith("test_b01i_")


def test_r6_report_declares_boundaries_and_waiting_lanes() -> None:
    report = REPORT_PATH.read_text(encoding="utf-8")
    assert "WAITING_FOR" in report
    for token in ("RETRY", "VAL", "B01", "INT"):
        assert token in report, token
    assert "PREPPED_NOT_EXECUTED" in report
    assert "EXECUTED_BLOCKED_S10_SHOTS_OVERLAP" in report
    assert "S12_REVIEW_OUT" in report
    assert "NOT_CLOSED" in report and "NOT_APPROVED" in report
    assert "20260915T131158Z" in report
