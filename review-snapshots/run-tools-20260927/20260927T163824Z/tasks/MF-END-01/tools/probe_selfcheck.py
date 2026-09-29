"""Probe: MF-END-01 contract self-check (micro repro + acceptance controls).

Runs AGAINST THE WORKTREE MODULE (read-only):
1. import + SCHEMA_VERSION micro repro;
2. both frozen examples validate;
3. every frozen negative fixture (N01..N23) refuses with its EXACT code;
4. engine-request payload builds, is deterministic, and its sha256 is printed
   (used to freeze FROZEN_REQUEST_PAYLOAD_SHA256);
5. to_engine_request() fails closed with media_engine_dto_unavailable while the
   accepted DTO has not been transported into this tree.

Exit code 0 iff every row passes.  Prints a compact JSON report.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORKTREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-01")
sys.path.insert(0, str(WORKTREE))

from app.schemas import shot_reskin as sr  # noqa: E402

rows: list[dict] = []


def row(name: str, ok: bool, detail: str) -> None:
    rows.append({"row": name, "pass": bool(ok), "detail": detail})


def main() -> int:
    row("micro.import", sr.SCHEMA_VERSION == "mf.shot_reskin.contract.v1", sr.SCHEMA_VERSION)
    row(
        "micro.dto_present_flag",
        sr.MEDIA_ENGINE_DTO_PRESENT is False,
        f"MEDIA_ENGINE_DTO_PRESENT={sr.MEDIA_ENGINE_DTO_PRESENT}",
    )

    plan = sr.ShotPlan.model_validate(sr.FROZEN_EXAMPLES["shot_plan_book"])
    row("frozen.shot_plan_validates", True, f"shot {plan.shot_id} roles={sorted(plan.declared_roles)}")
    record = sr.ShotExecutionRecord.model_validate(sr.FROZEN_EXAMPLES["execution_record_book_p3b"])
    row("frozen.execution_record_validates", True, f"backend={record.execution_backend}")

    for fixture in sr.FROZEN_EXAMPLES["negative_fixtures"]:
        base = sr.FROZEN_EXAMPLES[fixture["base"]]
        patched = sr.apply_fixture_ops(
            base,
            set_ops=tuple((p, v) for p, v in fixture.get("set", ())),
            append_ops=tuple((p, v) for p, v in fixture.get("append", ())),
        )
        model = sr.ShotPlan if fixture["base"] == "shot_plan_book" else sr.ShotExecutionRecord
        try:
            model.model_validate(patched)
        except sr.ShotReskinRefusal as refusal:
            ok = refusal.code.value == fixture["expected_refusal_code"]
            row(f"fixture.{fixture['id']}", ok, f"got={refusal.code.value} want={fixture['expected_refusal_code']}")
        except Exception as exc:  # noqa: BLE001
            row(f"fixture.{fixture['id']}", False, f"wrong exception {type(exc).__name__}: {exc}")
        else:
            row(f"fixture.{fixture['id']}", False, "VALIDATED but must refuse")

    binding = record.input
    assert binding is not None
    try:
        binding.to_request_payload()
    except sr.ShotReskinRefusal as refusal:
        row(
            "payload.refuses_null_revision",
            refusal.code is sr.ShotReskinRefusalCode.RECORD_INCONSISTENT,
            refusal.code.value,
        )
    else:
        row("payload.refuses_null_revision", False, "built a payload with a null revision")

    model_with_revision = binding.graph.model.model_copy(update={"revision": "p3b-r28-local-convrot"})
    graph_with_revision = binding.graph.model_copy(update={"model": model_with_revision})
    binding_with_revision = binding.model_copy(update={"graph": graph_with_revision})
    payload = binding_with_revision.to_request_payload()
    sha_a = sr.payload_sha256(payload)
    sha_b = binding_with_revision.request_payload_sha256()
    row("payload.deterministic", sha_a == sha_b, sha_a[:16])
    row("payload.serialisable", bool(json.dumps(payload)), f"keys={sorted(payload)}")

    try:
        sr.to_engine_request(binding_with_revision)
    except sr.ShotReskinRefusal as refusal:
        row(
            "composition.fails_closed_without_dto",
            refusal.code is sr.ShotReskinRefusalCode.MEDIA_ENGINE_DTO_UNAVAILABLE,
            refusal.code.value,
        )
    else:
        row("composition.fails_closed_without_dto", False, "constructed an engine request without the DTO??")

    failed = [r for r in rows if not r["pass"]]
    report = {
        "probe": "mf_end_01_selfcheck",
        "rows_total": len(rows),
        "rows_passed": len(rows) - len(failed),
        "rows_failed": len(failed),
        "payload_sha256_with_revision_label": sha_a,
        "rows": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
