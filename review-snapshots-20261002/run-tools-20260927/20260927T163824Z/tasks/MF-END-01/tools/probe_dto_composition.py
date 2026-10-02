"""Probe: COMPOSITION against the ACCEPTED media-engine DTO (real bytes).

Loads the accepted DTO from its pinned source (CONTRACT worktree copy of
``app/schemas/media_engine.py`` @ f0b918b, blob 9e4586a1…), verifies the blob id
with git, then:

1. cross-checks the pinned vocabulary in app/schemas/shot_reskin.py against the
   real DTO constants (capabilities / artifact kinds / publishable kinds /
   server output types / reference minima);
2. constructs ``MediaEngineRequest`` from the shot contract's engine payload for
   the frozen BOOK example (with the provisioning revision label — the frozen
   record keeps revision null; open item O1);
3. runs real DTO-side negatives: client path, empty cast references, shortened
   output timeline, capability substitution — each must refuse with the DTO's
   OWN typed code;
4. checks the request payload's key sets against the DTO's model fields, so a
   silent field-name drift cannot pass.

Exit 0 iff every row passes.  Read-only; prints compact JSON.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-01")
CONTRACT_TREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-tool-contract")
DTO_PATH = CONTRACT_TREE / "app" / "schemas" / "media_engine.py"
EXPECTED_BLOB = "9e4586a1b2cbc8aeb6d35a75c038327533b81b2a"

sys.path.insert(0, str(WORKTREE))

from app.schemas import shot_reskin as sr  # noqa: E402

rows: list[dict] = []


def row(name: str, ok: bool, detail: str) -> None:
    rows.append({"row": name, "pass": bool(ok), "detail": detail})


def load_dto():
    proc = subprocess.run(
        ["git", "-C", str(CONTRACT_TREE), "hash-object", "app/schemas/media_engine.py"],
        capture_output=True,
        text=True,
    )
    blob = proc.stdout.strip()
    row("dto.blob_matches_f0b918b", blob == EXPECTED_BLOB, blob)
    spec = importlib.util.spec_from_file_location("media_engine_probe", DTO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec: pydantic resolves forward references through the
    # module namespace in sys.modules, and a by-path load is not registered.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.MediaEngineRequest.model_rebuild()
    module.MediaEngineResult.model_rebuild()
    return module


def main() -> int:
    me = load_dto()
    row(
        "dto.contract_version",
        me.MEDIA_ENGINE_CONTRACT_VERSION == sr.MEDIA_ENGINE_CONTRACT_VERSION_PIN,
        me.MEDIA_ENGINE_CONTRACT_VERSION,
    )
    row(
        "vocab.capabilities",
        tuple(c.value for c in me.MediaCapability) == sr.ENGINE_CAPABILITY_PINS,
        ",".join(sorted(c.value for c in me.MediaCapability)),
    )
    row("vocab.artifact_kinds", me.ARTIFACT_KINDS == sr.ENGINE_ARTIFACT_KINDS, str(me.ARTIFACT_KINDS))
    row(
        "vocab.publishable_kinds",
        me.PUBLISHABLE_ARTIFACT_KINDS == sr.ENGINE_PUBLISHABLE_ARTIFACT_KINDS,
        str(me.PUBLISHABLE_ARTIFACT_KINDS),
    )
    row(
        "vocab.server_output_types",
        me.SERVER_OUTPUT_TYPES == sr.ENGINE_SERVER_OUTPUT_TYPES,
        str(me.SERVER_OUTPUT_TYPES),
    )
    row(
        "vocab.server_publishable",
        me.SERVER_PUBLISHABLE_TYPES == sr.ENGINE_SERVER_PUBLISHABLE_TYPES,
        str(me.SERVER_PUBLISHABLE_TYPES),
    )
    minima = {
        cap.value: (
            req.min_roles,
            req.min_references_per_role,
        )
        for cap, req in me.CAPABILITY_REFERENCE_REQUIREMENTS.items()
    }
    row("vocab.reference_minima", minima == sr.ENGINE_REFERENCE_MINIMA_PIN, json.dumps(minima))

    record = sr.ShotExecutionRecord.model_validate(sr.FROZEN_EXAMPLES["execution_record_book_p3b"])
    binding = record.input
    model_with_revision = binding.graph.model.model_copy(update={"revision": "p3b-r28-local-convrot"})
    binding = binding.model_copy(update={"graph": binding.graph.model_copy(update={"model": model_with_revision})})
    payload = binding.to_request_payload()

    # ``client_path`` / ``client_graph`` exist on the DTO ONLY so client-supplied
    # input can be REFUSED; they are deliberately never emitted by the projection.
    refusal_only = {"client_path", "client_graph"}
    row(
        "payload.refusal_only_fields_present_on_dto",
        refusal_only <= set(me.MediaEngineRequest.model_fields),
        str(sorted(refusal_only & set(me.MediaEngineRequest.model_fields))),
    )
    request_fields = set(me.MediaEngineRequest.model_fields) - refusal_only
    row(
        "payload.keys_exact_match",
        set(payload) == request_fields,
        f"missing={sorted(request_fields - set(payload))} extra={sorted(set(payload) - request_fields)}",
    )
    row(
        "payload.source_keys",
        set(payload["source"]) == set(me.SourceLock.model_fields),
        f"got={sorted(payload['source'])}",
    )
    row(
        "payload.pins_keys",
        set(payload["pins"]) == set(me.WorkflowPins.model_fields),
        f"got={sorted(payload['pins'])}",
    )
    row(
        "payload.model_pin_keys",
        set(payload["pins"]["model"]) == set(me.ModelPin.model_fields),
        f"got={sorted(payload['pins']['model'])}",
    )
    row(
        "payload.output_keys",
        set(payload["output"]) == set(me.OutputContract.model_fields),
        f"got={sorted(payload['output'])}",
    )
    row(
        "payload.budget_keys",
        set(payload["budget"]) == set(me.ResourceBudget.model_fields),
        f"got={sorted(payload['budget'])}",
    )
    if payload["cast"]:
        row(
            "payload.cast_keys",
            set(payload["cast"][0]) == set(me.CastBinding.model_fields),
            f"got={sorted(payload['cast'][0])}",
        )

    request = me.MediaEngineRequest(**payload)
    row(
        "compose.media_engine_request_built",
        request.source.source_sha256 == "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc",
        f"prompt-shaped request for {request.capability.value}",
    )
    row(
        "compose.effective_payload_sha_equals_frozen",
        sr.payload_sha256(payload) == sr.FROZEN_REQUEST_PAYLOAD_SHA256,
        sr.payload_sha256(payload),
    )
    row(
        "to_engine_request.refuses_without_transport",
        sr.MEDIA_ENGINE_DTO_PRESENT is False,
        "app.schemas.media_engine absent from the worktree (INT transport pending)",
    )

    neg = dict(payload)
    neg["client_path"] = "C:/tmp/stolen.mp4"
    try:
        me.MediaEngineRequest(**neg)
    except me.MediaEngineRefusal as refusal:
        row("dto_neg.client_path", refusal.code is me.MediaEngineRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED, refusal.code.value)
    else:
        row("dto_neg.client_path", False, "accepted a client path")

    neg = json.loads(json.dumps(payload))
    for entry in neg["cast"]:
        entry["references"] = []
    try:
        me.MediaEngineRequest(**neg)
    except me.MediaEngineRefusal as refusal:
        row("dto_neg.empty_cast_references", refusal.code is me.MediaEngineRefusalCode.REFERENCE_REQUIREMENT_UNMET, refusal.code.value)
    else:
        row("dto_neg.empty_cast_references", False, "accepted an empty cast")

    neg = json.loads(json.dumps(payload))
    neg["output"]["frame_count"] = 119
    try:
        me.MediaEngineRequest(**neg)
    except me.MediaEngineRefusal as refusal:
        row("dto_neg.shortened_output", refusal.code is me.MediaEngineRefusalCode.SOURCE_OUTPUT_TIMELINE_MISMATCH, refusal.code.value)
    else:
        row("dto_neg.shortened_output", False, "accepted a shortened output timeline")

    neg = json.loads(json.dumps(payload))
    neg["cast"][0]["references"] = [
        {"artifact_id": "a", "sha256": neg["cast"][0]["references"][0]["sha256"]},
        {"artifact_id": "b", "sha256": neg["cast"][0]["references"][0]["sha256"]},
    ]
    neg["capability"] = "image_edit_multi_reference"
    try:
        me.MediaEngineRequest(**neg)
    except me.MediaEngineRefusal as refusal:
        row("dto_neg.duplicate_reference_not_independent", refusal.code is me.MediaEngineRefusalCode.REFERENCE_REQUIREMENT_UNMET, refusal.code.value)
    else:
        row("dto_neg.duplicate_reference_not_independent", False, "duplicated pixels counted as two")

    failed = [r for r in rows if not r["pass"]]
    report = {
        "probe": "mf_end_01_dto_composition",
        "dto_source": str(DTO_PATH),
        "dto_blob": EXPECTED_BLOB,
        "rows_total": len(rows),
        "rows_passed": len(rows) - len(failed),
        "rows_failed": len(failed),
        "rows": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
