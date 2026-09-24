"""Contract surface of the product-P1 public chain — RUNNABLE NOW.

Every assertion here is about the PUBLIC surface the frozen-candidate run will
use: route existence/authority shape, registry integrity, and the two
anti-cheat guards for this suite (no seeded state, no hardcoded evidence
root).  No product state is created and no frozen pin is needed.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import public_chain_cases as R  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
PKG_DIR = _HERE
#: The anti-cheat guards below necessarily contain the very literals they
#: forbid, so they exclude themselves from the scan.
SELF = Path(__file__).name


def _production_ops() -> list[tuple[str, str, str]]:
    from app.api.app import app

    spec = app.openapi()
    rows: list[tuple[str, str, str]] = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method.lower() in {"get", "post", "put", "patch", "delete"}:
                rows.append((method.upper(), path.rstrip("/") or "/", op.get("operationId") or ""))
    return rows


def test_every_step_route_exists_in_production_openapi() -> None:
    ops = _production_ops()
    # The product registers <path> and <path>/ twins for browser tolerance;
    # both are the SAME public route, so existence is a set membership test.
    available = {(method, path) for method, path, _ in ops}
    missing: list[str] = []
    for entry in R.steps():
        for method, path in entry["routes"]:
            if (method, path.rstrip("/") or "/") not in available:
                missing.append(f"{entry['step']}: {method} {path}")
    assert missing == [], f"public chain routes missing from production OpenAPI: {missing}"

    operation_ids = [op_id for _, _, op_id in ops]
    assert all(operation_ids), "every operation must expose an operationId"
    dup_ops = [op_id for op_id, n in Counter(operation_ids).items() if n > 1]
    assert dup_ops == [], f"duplicate operationIds in the public surface: {sorted(dup_ops)}"


def test_registry_step_order_and_coverage() -> None:
    steps = R.steps()
    assert [s["order"] for s in steps] == list(range(1, len(steps) + 1))
    assert len(steps) == 13, f"public chain must be 13 steps, got {len(steps)}"
    expected_order = [
        "public_upload",
        "analyze",
        "library_roles",
        "producer",
        "approval",
        "s10_full_apply",
        "audio",
        "qc_full",
        "s12_api",
        "worker",
        "publisher",
        "download",
        "ui_reload",
    ]
    assert [s["step"] for s in steps] == expected_order
    for entry in steps:
        assert entry["routes"], f"{entry['step']} declares no public route"
        assert entry["pending_reason"].strip(), f"{entry['step']} declares no pending reason"


def test_case_nodes_resolve_to_real_functions() -> None:
    """No phantom coverage: every declared node must exist on disk."""
    unresolved: list[str] = []
    for case in R.cases():
        node = case["node"]
        rel, _, func = node.partition("::")
        target = REPO_ROOT / rel
        if not target.is_file():
            unresolved.append(f"{case['id']}: missing file {rel}")
            continue
        if func and not re.search(
            rf"^def {re.escape(func)}\(", target.read_text(encoding="utf-8"), re.M
        ):
            unresolved.append(f"{case['id']}: missing def {func} in {rel}")
    assert unresolved == [], f"registry declares coverage that does not exist: {unresolved}"


def test_pending_cases_declare_reason_and_freeze_dependency() -> None:
    pending = R.cases(R.PENDING_FROZEN_CANDIDATE)
    assert pending, "the suite must declare what waits for the freeze"
    for case in pending:
        assert case.get("await", "").strip(), f"{case['id']} has no declared freeze dependency"
    pending_steps = set(R.pending_steps())
    # The packet's dependency-honesty list: every step whose EXECUTED case
    # needs the frozen integrated candidate must be named here.
    expected_pending = {
        "public_upload",
        "analyze",
        "library_roles",
        "producer",
        "approval",
        "s10_full_apply",
        "audio",
        "qc_full",
        "s12_api",
        "worker",
        "publisher",
        "download",
        "ui_reload",
    }
    assert pending_steps == expected_pending, (
        f"pending-step declaration drift: missing {sorted(expected_pending - pending_steps)}, "
        f"unexpected {sorted(pending_steps - expected_pending)}"
    )


def test_new_suite_never_seeds_state() -> None:
    """The public chain must earn its own state: no seeding in THIS suite."""
    forbidden = (
        "session.add(",
        ".add_all(",
        "INSERT INTO",
        "insert into",
        "bulk_save_objects",
        "session.commit(",
    )
    offenders: list[str] = []
    for path in sorted(PKG_DIR.glob("*.py")):
        if path.name == SELF:
            continue  # this guard contains the literals it forbids
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.name}: {token}")
    assert offenders == [], f"this suite must not seed or mutate product state: {offenders}"


def test_new_suite_hardcodes_no_evidence_root() -> None:
    offenders: list[str] = []
    for path in sorted(PKG_DIR.glob("*.py")):
        if path.name == SELF:
            continue  # this guard contains the literals it forbids
        text = path.read_text(encoding="utf-8")
        for token in ("C:/Users/Admin/Documents", "C:\\Users\\Admin\\Documents", "Codex/outputs"):
            if token in text:
                offenders.append(f"{path.name}: {token}")
    assert offenders == [], (
        "evidence roots must come from the environment (S12QA_EVIDENCE_OUT), never hardcoded: "
        f"{offenders}"
    )


def test_ui_client_calls_only_public_routes() -> None:
    """UI reload contract pinned statically (the live UI run waits for the freeze)."""
    frontend = REPO_ROOT / "frontend"
    client = frontend / "src" / "lib" / "s12-export-api.ts"
    if not client.is_file():
        import pytest

        pytest.skip(f"PENDING_FROZEN_CANDIDATE: UI export client absent at {client}")
    blob = client.read_text(encoding="utf-8")

    # 1. the client must call the same PUBLIC routes the registry declares.
    for token in (
        "/export/preflight",
        "/export/context",
        "/s12-exports/submit",
        "/result",
        "/cancel",
        "/retry",
    ):
        assert token in blob, f"UI export client no longer calls public route token {token!r}"

    # 2. one exported function per public leg of the chain.
    for func in (
        "exportContext",
        "preflightExport",
        "submitExport",
        "exportStatus",
        "exportResult",
        "cancelExport",
        "retryExport",
    ):
        assert re.search(rf"export function {func}\(", blob), f"UI client lost {func}()"

    # 3. the client must not reach for product internals.
    for bad in ("app/services", "app/persistence", "../app"):
        assert bad not in blob, f"UI client references product internals: {bad}"
