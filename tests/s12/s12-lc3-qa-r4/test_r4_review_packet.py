"""QA-owned R4 packet controls; these are evidence checks, not product passes."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs" / "pm" / "sessions" / "S12-LC3-QA"


def test_r4_matrix_has_exactly_62_rows_and_no_closure_claim() -> None:
    matrix = (DOCS / "R4_MATRIX.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (?:C|S|P|R)\d{2} \|", matrix, re.MULTILINE)
    assert len(rows) == 62
    assert "APPROVED" not in matrix
    assert "CLOSED" not in matrix


def test_r4_packet_names_all_required_artifacts() -> None:
    packet = (DOCS / "R4_PACKET_AUDIT.md").read_text(encoding="utf-8")
    for name in (
        "R4_MATRIX.md",
        "R4_COMMAND_LEDGER.md",
        "R4_SESSION_REGISTRY.md",
        "R4_RAW_EVIDENCE_INDEX.md",
        "R4_REPORT.md",
    ):
        assert name in packet


def test_r4_report_keeps_product_and_mechanism_separate() -> None:
    report = (DOCS / "R4_REPORT.md").read_text(encoding="utf-8")
    assert "BLOCKED_EXTERNAL_STRUCTURAL_LOCK_AUTHORITY" in report
    assert "FIXTURE_ONLY_ENGINEERING_MECHANISM" in report
    assert "NOT_DEMONSTRATED" in report
    assert "normal-product" in report
