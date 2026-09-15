"""B01-I public product-chain runner plan — PREPPED, NOT EXECUTED.

QA owns B01-I: one bounded public chain on the frozen integrated candidate
(S10 -> S12 -> durable worker -> publisher -> result/media, then UI
submit/reload) after RETRY/VAL/B01 are terminal and S12-LC3-INT has
integrated. This module freezes the exact node ID, command, env contract and
the exclusive evidence-output policy. It executes nothing: the dispatch guard
refuses while any dependency is unsatisfied, and every run gets a NEW output
directory created exclusively (S12_REVIEW_OUT style) so older evidence is
never reused or overwritten.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

_T = TypeVar("_T")

B01I_STATUS = "PREPPED_NOT_EXECUTED"

PYTHON311 = "C:/Users/Admin/AppData/Local/Programs/Python/Python311/python.exe"
QA_R6_DIR = "tests/s12/s12-lc3-qa-r6"
B01I_MODULE = f"{QA_R6_DIR}/test_r6_b01i_public_chain.py"
B01I_NODE = (
    f"{B01I_MODULE}::test_b01i_public_product_chain_submit_worker_publisher_result_media_ui"
)
B01I_COMMAND = [PYTHON311, "-B", "-m", "pytest", B01I_NODE, "-q", "-p", "no:cacheprovider"]

B01I_REQUIRED_ENV = ("S12_REVIEW_OUT", "S12_R6_CANDIDATE_ROOT", "S12_R6_EXPECTED_CANDIDATE_SHA")
B01I_EVIDENCE_ROOT_TEMPLATE = (
    "C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r6-hermes/<uniqueUTC>/QA/B01-I"
)

B01I_REQUIRED_DEPENDENCIES = (
    "S12-LC3-RETRY terminal: M01-M19 frozen cases executed and recorded",
    "S12-LC3-VAL terminal: V01-V15 frozen cases executed and recorded",
    "S09-LOCK-PRODUCER-B01 terminal: B01-A..B01-H green (public producer + reapproval)",
    "S12-LC3-INT serial transport integrated; candidate SHA frozen for QA",
)

_RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")


def new_run_output_dir(base: Path | str, run_id: str) -> Path:
    """Create a NEW exclusive run directory; refuse reuse so old evidence is never overwritten."""
    if not _RUN_ID_RE.match(run_id):
        raise ValueError(f"run_id must be a UTC stamp YYYYMMDDTHHMMSSZ, got {run_id!r}")
    target = Path(base) / run_id
    target.mkdir(parents=True, exist_ok=False)
    return target


def guarded_dispatch(runner: Callable[[], _T], *, dependencies_satisfied: bool) -> _T:
    """Run the B01-I chain only when every dependency is recorded as satisfied."""
    if not dependencies_satisfied:
        raise RuntimeError(
            "B01-I dispatch is gated: RETRY/VAL/B01 terminal + INT frozen candidate required"
        )
    return runner()
