"""MF-V1-COMFY correction round C — C01–C08 frozen matrix rows (pytest nodes).

One node per frozen matrix row. The case bodies live in
`tests/durable_resolve_cases.py` so the SAME cases can be dumped to JSON by
`COMFY/raw/run_matrix_c.py` (round evidence) without duplicating logic.

    node id                                                        row
    tests/test_durable_resolve_c.py::test_c01_unchanged_unresolved_replay      C01
    tests/test_durable_resolve_c.py::test_c02_receipt_replay                   C02
    tests/test_durable_resolve_c.py::test_c03_body_only_mutations              C03
    tests/test_durable_resolve_c.py::test_c04_claimant_conflicts              C04
    tests/test_durable_resolve_c.py::test_c05_missing_or_corrupt              C05
    tests/test_durable_resolve_c.py::test_c06_legacy_rows_retained            C06
    tests/test_durable_resolve_c.py::test_c07_independent_new_work            C07
    tests/test_durable_resolve_c.py::test_c08_legacy_rows_replayed            C08
"""
from __future__ import annotations

from durable_resolve_cases import run_case, reset_scratch


def _assert_row(name: str) -> dict:
    reset_scratch()
    row = run_case(name)
    failed = [c for c in row["checks"] if not c["ok"]]
    detail = "\n".join(f"  - {c['check']}: expected {c['expected']!r}, got {c['observed']!r}"
                       for c in failed)
    assert row["ok"], (f"{row['row']} failed {len(failed)}/{row['total']} checks "
                       f"({row['passed']} passed)\n{detail}")
    return row


def test_c01_unchanged_unresolved_replay():
    """C01: unchanged unresolved replay -> same prompt/artifact, total POST = 1."""
    row = _assert_row("c01_unchanged_unresolved_replay")
    v = row["steps"] if isinstance(row["steps"], dict) else {}
    assert v["post_calls"] == 1


def test_c02_receipt_replay():
    """C02: a receipt for the same attempt never implies a new attempt."""
    _assert_row("c02_receipt_replay")


def test_c03_body_only_mutations():
    """C03: body-only mutation with the digest unchanged -> refusal before accept."""
    _assert_row("c03_body_only_mutations")


def test_c04_claimant_conflicts():
    """C04: any wrong or multiple claimant -> refuse, never the exact subset."""
    _assert_row("c04_claimant_conflicts")


def test_c05_missing_or_corrupt():
    """C05: unknown/corrupt durable state -> fail closed, evidence retained."""
    _assert_row("c05_missing_or_corrupt")


def test_c06_legacy_rows_retained():
    """C06: changed graph with an old pin / foreign owner completed -> retained."""
    _assert_row("c06_legacy_rows_retained")


def test_c07_independent_new_work():
    """C07: a genuinely independent new work item still runs (no over-lock)."""
    _assert_row("c07_independent_new_work")


def test_c08_legacy_rows_replayed(tmp_path):
    """C08: the earlier F01/F03/F04 rows are re-executed, not trusted from a prefix.

    The legacy rows are *called* here (not merely referenced) so a regression in
    any of them fails this row as well as its own.
    """
    from test_contract_regression import (  # noqa: PLC0415 - replayed on purpose
        test_corrupt_reservation_blocks_gate as row_malformed_json,
        test_epoch_change_with_success_history_is_rejected as row_f03_boot_change,
        test_f01_lost_ack_and_dead_opener_stay_blocking as row_f01_second_caller,
        test_inflight_submit_cannot_be_released_by_other_caller as row_f01_live_callers)
    from test_reservation import (  # noqa: PLC0415 - replayed on purpose
        test_f01_never_interrupts_a_foreign_prompt as row_shared_lease,
        test_f01_server_reboot_quarantines_and_never_adopts_foreign_output
        as row_reboot_quarantine,
        test_f01_terminal_success_releases_reservation_exactly_once as row_release_once,
        test_reservation_release_is_exactly_once_even_when_racing as row_racing_release)

    rows = [
        ("f01_two_live_callers_at_the_contested_post", row_f01_live_callers),
        ("f01_second_caller_and_dead_opener_stay_blocking", row_f01_second_caller),
        ("f03_boot_change_with_success_history", row_f03_boot_change),
        ("f04_malformed_marker_blocks_the_gate", row_malformed_json),
        ("f01_server_reboot_quarantine_never_foreign_output", row_reboot_quarantine),
        ("f01_terminal_success_released_exactly_once", row_release_once),
        ("shared_gpu_lease_never_interrupts_a_foreign_prompt", row_shared_lease),
        ("release_is_exactly_once_even_when_racing", row_racing_release),
    ]
    executed: list[str] = []
    for label, fn in rows:
        fn(tmp_path / label)
        executed.append(label)
    assert len(executed) == len(rows), "every legacy row must be executed, not a prefix"


if __name__ == "__main__":  # pragma: no cover - manual matrix dump
    for name in ("c01_unchanged_unresolved_replay", "c02_receipt_replay",
                 "c03_body_only_mutations", "c04_claimant_conflicts",
                 "c05_missing_or_corrupt", "c06_legacy_rows_retained",
                 "c07_independent_new_work"):
        row = run_case(name)
        print(f"{row['row']} {row['passed']}/{row['total']} ok={row['ok']}")
        for c in row["checks"]:
            if not c["ok"]:
                print(f"   FAIL {c['check']}: expected {c['expected']!r} got {c['observed']!r}")
