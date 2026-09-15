"""B01-I prep checks — plan shape, exclusive output dir, dispatch guard only.

The B01-I public product chain is NOT executed by this module
(PREPPED_NOT_EXECUTED); it only proves the frozen plan is complete, the
per-run output policy cannot overwrite older evidence, and dispatch stays
gated until RETRY/VAL/B01 are terminal and INT has integrated.
"""

from __future__ import annotations

import sys
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from r6_b01i_plan import (  # noqa: E402
    B01I_COMMAND,
    B01I_EVIDENCE_ROOT_TEMPLATE,
    B01I_MODULE,
    B01I_NODE,
    B01I_REQUIRED_DEPENDENCIES,
    B01I_REQUIRED_ENV,
    B01I_STATUS,
    PYTHON311,
    guarded_dispatch,
    new_run_output_dir,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / "docs" / "pm" / "sessions" / "S12-LC3-QA"


def test_b01i_plan_freezes_exact_node_and_command() -> None:
    assert B01I_STATUS == "PREPPED_NOT_EXECUTED"
    assert B01I_MODULE.startswith("tests/s12/s12-lc3-qa-r6/")
    assert B01I_MODULE.endswith("test_r6_b01i_public_chain.py")
    expected_node = (
        f"{B01I_MODULE}::test_b01i_public_product_chain_submit_worker_publisher_result_media_ui"
    )
    assert expected_node == B01I_NODE
    assert B01I_COMMAND[0] == PYTHON311
    assert B01I_COMMAND[1:] == ["-B", "-m", "pytest", B01I_NODE, "-q", "-p", "no:cacheprovider"]
    for key in ("S12_REVIEW_OUT", "S12_R6_CANDIDATE_ROOT", "S12_R6_EXPECTED_CANDIDATE_SHA"):
        assert key in B01I_REQUIRED_ENV
    assert "<uniqueUTC>" in B01I_EVIDENCE_ROOT_TEMPLATE
    assert "s12-r6-hermes" in B01I_EVIDENCE_ROOT_TEMPLATE
    deps = " ".join(B01I_REQUIRED_DEPENDENCIES)
    for token in ("S12-LC3-RETRY", "S12-LC3-VAL", "S09-LOCK-PRODUCER-B01", "S12-LC3-INT"):
        assert token in deps


def test_b01i_prep_is_recorded_in_owned_docs() -> None:
    inventory = (DOCS / "R6_INVENTORY.md").read_text(encoding="utf-8")
    report = (DOCS / "R6_REPORT.md").read_text(encoding="utf-8")
    for text in (inventory, report):
        assert "PREPPED_NOT_EXECUTED" in text
        assert B01I_NODE in text
        assert "S12_REVIEW_OUT" in text


def test_b01i_output_dir_is_exclusive_per_run(tmp_path: Path) -> None:
    first = new_run_output_dir(tmp_path, "20260915T131158Z")
    assert first.is_dir()
    marker = first / "result.json"
    marker.write_text("owned run evidence", encoding="utf-8")
    try:
        new_run_output_dir(tmp_path, "20260915T131158Z")
        raise AssertionError("re-using an existing run id must be refused")
    except FileExistsError:
        pass
    assert marker.read_text(encoding="utf-8") == "owned run evidence"
    second = new_run_output_dir(tmp_path, "20260915T131159Z")
    assert second.is_dir() and second != first
    for bad in ("20260915", "131158Z", "2026-09-15T13:11:58Z"):
        try:
            new_run_output_dir(tmp_path, bad)
            raise AssertionError(f"run id {bad!r} must be rejected")
        except ValueError:
            pass


def test_b01i_dispatch_guard_blocks_until_dependencies_satisfied() -> None:
    calls: list[str] = []

    def runner() -> str:
        calls.append("ran")
        return "b01i-run"

    try:
        guarded_dispatch(runner, dependencies_satisfied=False)
        raise AssertionError("dispatch must stay gated while dependencies are open")
    except RuntimeError:
        pass
    assert calls == []
    assert guarded_dispatch(runner, dependencies_satisfied=True) == "b01i-run"
    assert calls == ["ran"]
