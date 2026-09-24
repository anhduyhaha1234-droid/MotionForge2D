"""QA3 — engine cases stay TYPED: the engineering case and the typed real-case
block are two separate things and are never merged into "product complete".

RUNNABLE NOW.  Nothing here executes the engine and nothing creates product
state: the product-side reads are the registry and (only when the QA evidence
root is exported) the recorded engine-probe artifact.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import public_chain_cases as R  # noqa: E402

PROBE_ARTIFACT_KEY = "raw/qa3_engine_probe.json"


def test_engine_cases_separate_engineering_case_from_typed_real_case() -> None:
    """The two QA3 blocks must both exist and must be disjoint."""
    engineering = R.engine_cases("engineering_case")
    typed = R.engine_cases("typed_real_case")
    assert engineering, "QA3 requires an engineering case when the real engine is unavailable"
    assert typed, "QA3 requires a typed real-case block for the engine-dependent legs"
    eng_ids = {row["id"] for row in engineering}
    real_ids = {row["id"] for row in typed}
    assert eng_ids and real_ids, (eng_ids, real_ids)
    assert not (eng_ids & real_ids), f"an id may not be both kinds: {sorted(eng_ids & real_ids)}"
    for row in R.engine_cases():
        assert row["kind"] in {"engineering_case", "typed_real_case"}, row
        assert row["title"].strip(), row


def test_engineering_case_claims_no_product_result() -> None:
    """An engineering case is a QA/host row: it may never carry a product claim."""
    engineering = R.engine_cases("engineering_case")
    assert engineering, "no engineering case declared"
    for row in engineering:
        assert row["claimed_product_result"] is None, row
        assert row["why"].strip(), row
        assert row["cannot_claim"].strip(), row
        assert row["probe_artifact"] == PROBE_ARTIFACT_KEY, row["probe_artifact"]
        assert row["probe_env"] == "S12QA_EVIDENCE_OUT", row["probe_env"]
        assert row["probe_command"].strip(), row
        assert "step" not in row, "an engineering case is not a product row"
        assert "disposition" not in row, "an engineering case declares no product disposition"


def test_typed_real_cases_cover_exactly_the_engine_dependent_legs() -> None:
    """The typed block is exactly the engine-dependent legs, each typed non-pass."""
    typed = R.engine_cases("typed_real_case")
    typed_steps = {row["step"] for row in typed}
    expected = set(R.ENGINE_PRODUCT_LEGS)
    assert typed_steps == expected, (
        f"typed real-case block drift: missing {sorted(expected - typed_steps)}, "
        f"unexpected {sorted(typed_steps - expected)}"
    )
    declared_steps = {entry["step"] for entry in R.steps()}
    for row in typed:
        assert row["step"] in declared_steps, f"{row['id']} names an unknown chain step"
        assert row["disposition"] in R.TYPED_ENGINE_DISPOSITIONS, row
        assert "PASS" not in row["disposition"], row
        assert row["why"].strip(), row
        assert row["must_not_claim"].strip(), row


def test_no_engine_row_is_reported_as_product_complete() -> None:
    """Nothing in either block may READ as a product-complete claim.

    The scan covers the fields that CARRY a claim (id/kind/title/step/
    disposition/why).  ``cannot_claim`` and ``must_not_claim`` are DENIAL
    lists -- naming a forbidden claim there is the opposite of claiming it --
    so they are excluded from the scan and asserted separately below.
    """
    forbidden = ("product complete", "product_complete", "quality_accepted")
    denial_keys = {"cannot_claim", "must_not_claim"}
    for row in R.engine_cases():
        claim_fields = {key: value for key, value in row.items() if key not in denial_keys}
        blob = json.dumps(claim_fields).lower()
        for token in forbidden:
            assert token not in blob, (
                f"{row['id']} carries the claim {token!r} in {sorted(claim_fields)}"
            )
        assert (row["cannot_claim"] if row["kind"] == "engineering_case" else row["must_not_claim"]).strip(), row


def test_engine_denials_name_the_forbidden_product_claims() -> None:
    """The denials must be explicit: the engineering case names what it cannot claim."""
    engineering = R.engine_cases("engineering_case")
    assert engineering, "no engineering case declared"
    for row in engineering:
        denial = row["cannot_claim"].lower()
        for token in ("product complete", "chain green"):
            assert token in denial, (
                f"{row['id']} must explicitly deny {token!r}: {row['cannot_claim']!r}"
            )


def test_registry_document_exposes_both_engine_blocks_separately() -> None:
    doc = R.document()
    assert doc["engine_cases"] == [dict(row) for row in R.ENGINE_CASES]
    assert doc["totals"]["engine_engineering_cases"] == len(R.engine_cases("engineering_case"))
    assert doc["totals"]["engine_typed_real_cases"] == len(R.engine_cases("typed_real_case"))
    assert doc["totals"]["engine_engineering_cases"] >= 1
    assert doc["totals"]["engine_typed_real_cases"] >= 1
    assert doc["engine_legend"]["engineering_case"].strip()
    assert doc["engine_legend"]["typed_real_case"].strip()


def test_engine_probe_artifact_agrees_with_the_declaration() -> None:
    """When the QA evidence root is exported, the measured probe is checked."""
    root = os.environ.get("S12QA_EVIDENCE_OUT")
    if not root:
        pytest.skip(
            "S12QA_EVIDENCE_OUT not exported: the recorded engine probe is verified in the "
            "QA evidence root by the evidence driver, not from here"
        )
    artifact = Path(root) / PROBE_ARTIFACT_KEY
    assert artifact.is_file(), f"engine probe artifact missing: {artifact}"
    probe = json.loads(artifact.read_text(encoding="utf-8"))
    assert "real_render_engine_available" in probe, sorted(probe)
    assert probe["binaries"], "the probe must record the engine binaries it looked for"
    encoding = probe["binaries"].get("ffmpeg", {}).get("path")
    if probe["real_render_engine_available"]:
        assert R.engine_cases("engineering_case"), "an available engine still needs the typing"
    else:
        # The engine was measured unavailable: the engineering case is the honest
        # record, and the product legs stay typed non-pass.
        assert R.engine_cases("engineering_case"), "unavailable engine without an engineering case"
        for row in R.engine_cases("typed_real_case"):
            assert row["disposition"] == "NOT_EXECUTED_ENGINE_UNAVAILABLE", row
    assert encoding or not probe["real_render_engine_available"], probe["binaries"]
