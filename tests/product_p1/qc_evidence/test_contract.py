"""MF-P1-QC-EVIDENCE — the FROZEN detector → input → producer table.

Gate order step 1: the table is frozen before the implementation.  These
checks make the freeze machine-checkable — a producer, persistence path,
provenance proof, derivation or refusal set that drifts changes the digest.
"""

from __future__ import annotations

import pytest

from app.services.qc_evidence import (
    CONTRACTS,
    EVIDENCE_FAMILIES,
    EVIDENCE_REFUSAL_CODES,
    FULL_BAND,
    QC_EVIDENCE_DEPENDENCY,
    QC_EVIDENCE_FOREIGN,
    QC_EVIDENCE_MALFORMED,
    QC_EVIDENCE_MISSING,
    QC_EVIDENCE_STALE,
    QC_EVIDENCE_TAMPERED,
    VISUAL_DETECTORS,
    contract_for,
    render_markdown,
    table_digest,
    table_payload,
)

#: The digest of the table as RE-FROZEN in correction round C (finding R4/R5):
#: the observed side of cut_drift / contact_break / z_order_error /
#: silhouette_clipping is measured on the RENDER artifact bytes and the
#: identity target is the pinned LIBRARY reference of the selected CharacterID
#: + immutable PackVersion, so those rows were corrected.  The previous freeze
#: (db8fd80bb31b627e53d474c77e14baf1685f1d32cea824d7d35783b506a2c032) declared
#: the source-side observation this round removes — it is recorded here so the
#: drift between the two freezes is auditable, and any FURTHER drift still
#: fails this test.
FROZEN_TABLE_DIGEST = "76aebd7bb9a19f9602ab95279ad5aa527e82b0e22d5c6086ea2b26610135793f"

REQUIRED_CORE_REFUSALS = (
    QC_EVIDENCE_MISSING,
    QC_EVIDENCE_STALE,
    QC_EVIDENCE_FOREIGN,
    QC_EVIDENCE_MALFORMED,
    QC_EVIDENCE_TAMPERED,
)


def test_frozen_band_matches_the_ten_detectors() -> None:
    assert tuple(row.detector for row in CONTRACTS) == FULL_BAND
    assert len(CONTRACTS) == 10
    assert len(set(FULL_BAND)) == 10
    assert FULL_BAND[:8] == VISUAL_DETECTORS


def test_frozen_table_digest_is_unchanged() -> None:
    assert table_digest() == FROZEN_TABLE_DIGEST


def test_every_row_is_complete_and_refuses_the_full_taxonomy() -> None:
    for row in CONTRACTS:
        assert row.required_input.strip()
        assert row.producers, row.detector
        assert row.persistence, row.detector
        assert row.provenance.strip(), row.detector
        assert row.derivations.strip(), row.detector
        assert set(row.families) <= set(EVIDENCE_FAMILIES), row.detector
        assert set(REQUIRED_CORE_REFUSALS) <= set(row.refusals), row.detector
        assert set(row.refusals) <= set(EVIDENCE_REFUSAL_CODES), row.detector


def test_visual_rows_declare_the_no_producer_escape_hatch() -> None:
    """A fact with no producer must be reportable, never invented."""
    for detector in VISUAL_DETECTORS:
        row = contract_for(detector)
        assert QC_EVIDENCE_DEPENDENCY in row.refusals


def test_payload_is_machine_checkable_and_markdown_lists_every_row() -> None:
    payload = table_payload()
    assert payload["schema"] == "mf-p1-qc-evidence/input-provenance-table"
    assert [row["detector"] for row in payload["detectors"]] == list(FULL_BAND)
    markdown = render_markdown()
    body_rows = [line for line in markdown.splitlines() if line.startswith("| ")]
    # header + one row per detector
    assert len(body_rows) == len(CONTRACTS) + 1
    assert "||" not in markdown, "table integrity broken (doubled pipe)"
    for detector in FULL_BAND:
        assert detector in markdown
    assert f"table_digest = {FROZEN_TABLE_DIGEST}" in markdown


def test_unknown_detector_is_not_in_the_table() -> None:
    with pytest.raises(KeyError):
        contract_for("not_a_detector")
