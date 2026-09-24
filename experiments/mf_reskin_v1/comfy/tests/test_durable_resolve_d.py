"""Round-D focused rows: one pytest test per frozen subcase (NR01 / NR02).

The engine (`durable_resolve_d_cases.py`) drives the adapter over the fake transport
and returns raw counters; this module turns each row into a pass/fail test. It is the
"focused" gate step — a green suite elsewhere never waives a failing row here.
"""
from __future__ import annotations

import pytest

import durable_resolve_d_cases as cases

ROW_CASES = [
    ("C04R-a", "c04r_a_valid_single_receipt"),
    ("C04R-b", "c04r_b_exact_receipt_plus_wrong_marker_order1"),
    ("C04R-c", "c04r_c_wrong_marker_plus_exact_receipt_order2"),
    ("C04R-d", "c04r_d_exact_receipt_plus_wrong_receipt"),
    ("C04R-e", "c04r_e_two_exact_receipts"),
    ("C04R-f", "c04r_f_foreign_workspace_or_alternate_path"),
    ("C04R-g", "c04r_g_cross_state_marker_receipt_quarantine"),
    ("C05R-a", "c05r_a_malformed_quarantine"),
    ("C05R-b", "c05r_b_empty_object_quarantine"),
    ("C05R-c", "c05r_c_quarantine_missing_authority"),
    ("C05R-d", "c05r_d_quarantine_read_error"),
    ("C05R-e", "c05r_e_quarantine_name_body_mismatch"),
    ("C05R-f", "c05r_f_same_attempt_changed_epoch"),
    ("C07R", "c07r_independent_new_work"),
]


@pytest.mark.parametrize("row_id,case", ROW_CASES, ids=[c for _r, c in ROW_CASES])
def test_round_d_row(row_id, case):
    cases.reset_scratch()
    row = cases.run_case(case)
    assert row["row"] == row_id
    bad = [c for c in row["checks"] if not c["ok"]]
    assert row["ok"], (
        f"{row_id} {case}: {len(bad)} failing check(s): "
        + "; ".join(f"{c['check']} expected={c['expected']!r} observed={c['observed']!r}"
                    for c in bad[:6]))


def test_round_d_matrix_covers_every_frozen_row():
    assert {rid for rid, _c in ROW_CASES} == set(cases.ROW_ORDER)
    assert set(cases.CASES) == {c for _r, c in ROW_CASES}
