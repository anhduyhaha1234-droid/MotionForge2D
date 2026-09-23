"""R6/R7 control retention (S12-LC3-QA) — RUNNABLE NOW.

The R6/R7 controls this lane already owns must survive the product-P1
preparation round: decoded PTS + audio checks, partial/corrupt output, stale
lease, restart/retry/cancel.  This module PINS them by node id, proves the
nodes still exist in this tree, and proves the new public-chain registry and
this retention list agree (no silently dropped control).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = REPO_ROOT / "tests" / "product_p1" / "public_chain" / "public_chain_cases.py"

_CHAIN = ("tests/s12/s12-lc3-qa-r6/test_r6_b01i_public_chain.py",
          "test_b01i_public_product_chain_submit_worker_publisher_result_media_ui")

#: control id -> (owning file, function name) for the controls QA retains.
CONTROL_NODES: dict[str, tuple[str, str]] = {
    "decoded_pts": _CHAIN,
    "audio_checks": _CHAIN,
    "partial_or_corrupt_output": (
        "tests/s12/s12-lc3-retry/test_r4_retry_execution.py",
        "test_malformed_retry_lineage_claim_is_fail_closed",
    ),
    "stale_lease": (
        "tests/s12/s12-lc3-val/test_r7_lease_serialization.py",
        "test_a01_claim_first_stale_entry_denied_b_completes",
    ),
    "stale_lease_expired_reclaim": (
        "tests/s12/s12-lc3-val/test_r7_lease_serialization.py",
        "test_a02_expired_released_reclaimed_tokens",
    ),
    "restart_retry_cancel": _CHAIN,
    "r6_prep_dispatch_guard": (
        "tests/s12/s12-lc3-qa-r6/test_r6_b01i_prep.py",
        "test_b01i_dispatch_guard_blocks_until_dependencies_satisfied",
    ),
    "r6_prep_exclusive_output_policy": (
        "tests/s12/s12-lc3-qa-r6/test_r6_b01i_prep.py",
        "test_b01i_output_dir_is_exclusive_per_run",
    ),
    "r7_prep_inventory": (
        "tests/s12/s12-lc3-qa-r6/test_r7_prep_inventory.py",
        "test_r7_additions_table_freezes_all_case_ids_with_owner_and_outcome",
    ),
}


def _load_registry():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("s12qa_public_chain_registry", REGISTRY)
    assert spec and spec.loader, REGISTRY
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_r6_r7_control_nodes_pinned_and_present() -> None:
    problems: list[str] = []
    for control, (rel, func) in CONTROL_NODES.items():
        path = REPO_ROOT / rel
        if not path.is_file():
            problems.append(f"{control}: missing file {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        if not re.search(rf"^def {re.escape(func)}\(", text, re.M):
            problems.append(f"{control}: missing def {func} in {rel}")
    assert problems == [], f"retained R6/R7 controls are no longer present: {problems}"


def test_owned_controls_recorded_in_registry() -> None:
    registry = _load_registry()
    registered = {entry["control"] for entry in registry.RETAINED_CONTROLS}
    owned = set(CONTROL_NODES)
    # Every control the registry claims to retain must be pinned here, and
    # every control pinned here must be claimed — otherwise one side drifted.
    assert registered <= owned, (
        f"registry claims controls this retention test does not pin: {sorted(registered - owned)}"
    )
    assert owned <= registered, (
        f"retention test pins controls the registry does not claim: {sorted(owned - registered)}"
    )


def test_registry_control_files_exist() -> None:
    registry = _load_registry()
    missing = [
        entry["where"]
        for entry in registry.RETAINED_CONTROLS
        if not (REPO_ROOT / entry["where"]).exists()
        and not (REPO_ROOT / entry["where"]).is_dir()
    ]
    assert missing == [], f"retained-control references point nowhere: {missing}"
