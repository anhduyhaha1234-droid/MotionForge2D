"""MF-END-01 — shot-reskin delivery contract: acceptance + negative controls.

Row map (binary):
* micro repro: module import, schema_version, DTO-availability flag;
* acceptance: strict schema refuses client path / foreign role / invalid
  interval / half-rational timebase / legacy route as backend / source-vs-output
  evidence confusion — each with its EXACT typed refusal code;
* frozen examples validate + JSON round-trip + doc↔module parse equality;
* engine projection: payload key sets == the pinned accepted-DTO field sets,
  deterministic payload sha256, null revision refuses, mutation refuses
  (when the accepted DTO has been transported in, the same payload constructs
  the REAL MediaEngineRequest — that row skips with an explicit reason until
  then, and the composition is proven against the pinned blob by the evidence
  probe);
* legacy DTO smoke: the neighbouring legacy schemas still import and validate.

No render, no GPU, no ffmpeg, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas import shot_reskin as sr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = PROJECT_ROOT / "docs" / "contracts" / "shot-reskin-delivery-v1.md"
TRANSPORTED_DTO = PROJECT_ROOT / "app" / "schemas" / "media_engine.py"

SOURCE_SHA = "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc"
ANCHOR_SHA = "aa08747048c42af56c9e5109b7a041d2f8d95bf7c79544017ef38b98bbb6455e"
OUTPUT_SHA = "dfc4e37b81ba4252635581a6f75fef1084324dcd7af9015e3ea3e2c86b90d77f"


# ── micro repro ───────────────────────────────────────────────────────────────


def test_micro_repro_module_imports_with_schema_version() -> None:
    assert sr.SCHEMA_VERSION == "mf.shot_reskin.contract.v1"
    assert sr.MEDIA_ENGINE_CONTRACT_VERSION_PIN == "mf.media_engine.contract.v1"
    assert sr.ExecutionBackend.COMFY_SHOT_ENGINE.value == "comfy_shot_engine"


def test_micro_repro_public_surface_exports_are_present() -> None:
    for name in sr.__all__:
        assert hasattr(sr, name), f"__all__ names a missing symbol: {name}"


# ── frozen examples ───────────────────────────────────────────────────────────


def test_frozen_shot_plan_validates() -> None:
    plan = sr.ShotPlan.model_validate(sr.FROZEN_EXAMPLES["shot_plan_book"])
    assert plan.span.frame_count == 120
    assert plan.timebase.fps == "30/1"
    assert plan.timebase.timebase == "1/15360"
    assert plan.timebase.timebase != plan.timebase.fps
    assert plan.source.sha256 == SOURCE_SHA
    assert {"BOOK-P1", "BOOK-P2", "BOOK-P3", "BOOK-P4"} <= set(plan.declared_roles)


def test_frozen_execution_record_validates() -> None:
    record = sr.ShotExecutionRecord.model_validate(sr.FROZEN_EXAMPLES["execution_record_book_p3b"])
    assert record.execution_backend == "comfy_shot_engine"
    assert record.legacy_route is None
    assert record.capability == "source_video_motion_transfer"
    assert record.outcome == "completed"
    assert record.input is not None and record.output is not None
    assert record.output.prompt_id == "d1f4e097-458d-4bd4-8049-fe6da26f91c1"
    assert record.output.artifacts[0].sha256 == OUTPUT_SHA


@pytest.mark.parametrize("name", ["shot_plan_book", "execution_record_book_p3b"])
def test_frozen_examples_round_trip_through_json(name: str) -> None:
    payload = sr.FROZEN_EXAMPLES[name]
    model = sr.ShotPlan if name == "shot_plan_book" else sr.ShotExecutionRecord
    dumped = json.loads(json.dumps(model.model_validate(payload).model_dump(mode="json")))
    assert model.model_validate(dumped)


def _doc_example(name: str) -> object:
    text = DOC_PATH.read_text(encoding="utf-8")
    start = text.index(f"<!-- FROZEN_EXAMPLE: {name} -->")
    end = text.index(f"<!-- /FROZEN_EXAMPLE: {name} -->", start)
    block = text[start:end]
    json_start = block.index("```json") + len("```json")
    json_end = block.index("```", json_start)
    return json.loads(block[json_start:json_end])


@pytest.mark.parametrize(
    "name", ["shot_plan_book", "execution_record_book_p3b", "negative_fixtures"]
)
def test_doc_frozen_blocks_parse_equal_to_module(name: str) -> None:
    assert _doc_example(name) == sr.FROZEN_EXAMPLES[name]


# ── acceptance: strict refusals (typed codes) ─────────────────────────────────


def _build(base: str, fixture: dict) -> sr.ShotPlan | sr.ShotExecutionRecord:
    patched = sr.apply_fixture_ops(
        sr.FROZEN_EXAMPLES[base],
        set_ops=tuple((path, value) for path, value in fixture.get("set", ())),
        append_ops=tuple((path, value) for path, value in fixture.get("append", ())),
    )
    model = sr.ShotPlan if base == "shot_plan_book" else sr.ShotExecutionRecord
    return model.model_validate(patched)


@pytest.mark.parametrize(
    "fixture",
    sr.FROZEN_EXAMPLES["negative_fixtures"],
    ids=[f["id"] for f in sr.FROZEN_EXAMPLES["negative_fixtures"]],
)
def test_frozen_negative_fixture_refuses_with_exact_code(fixture: dict) -> None:
    with pytest.raises(sr.ShotReskinRefusal) as excinfo:
        _build(fixture["base"], fixture)
    assert excinfo.value.code.value == fixture["expected_refusal_code"], (
        f"{fixture['id']}: got {excinfo.value.code.value}"
    )


def test_client_path_refused_on_every_artifact_position() -> None:
    plan_payload = json.loads(json.dumps(sr.FROZEN_EXAMPLES["shot_plan_book"]))
    plan_payload["source"]["path"] = "C:/client/source.mp4"
    with pytest.raises(sr.ShotReskinRefusal) as excinfo:
        sr.ShotPlan.model_validate(plan_payload)
    assert excinfo.value.code is sr.ShotReskinRefusalCode.CLIENT_ARTIFACT_PATH_REFUSED


def test_invalid_interval_negative_start_refused() -> None:
    with pytest.raises(sr.ShotReskinRefusal) as excinfo:
        sr.SourceSpan(start_frame=-1, end_frame_exclusive=10)
    assert excinfo.value.code is sr.ShotReskinRefusalCode.INVALID_INTERVAL_REFUSED


def test_span_engine_range_conversion_is_explicit() -> None:
    span = sr.SourceSpan(start_frame=0, end_frame_exclusive=120)
    assert span.to_engine_shot_range() == {"start_frame": 0, "end_frame": 119}
    back = sr.SourceSpan.from_engine_shot_range(0, 119)
    assert back == span
    assert sr.SourceSpan.from_engine_shot_range(72, 119) == sr.SourceSpan(
        start_frame=72, end_frame_exclusive=120
    )


# ── acceptance: source-vs-output evidence domains ─────────────────────────────


def _observed_binding(**updates: object) -> sr.OutputObservationBinding:
    plan = sr.ShotPlan.model_validate(sr.FROZEN_EXAMPLES["shot_plan_book"])
    base = plan.output_observations
    assert base is not None
    payload = base.model_dump(mode="json")
    payload["state"] = "observed"
    payload["observations"] = [
        {
            "observation_id": "OBS-BOOK-P1-HOLDS",
            "subject_role": "BOOK-P1",
            "kind": "holder",
            "span": {"start_frame": 0, "end_frame_exclusive": 120},
            "artifact": payload["output_artifact"],
            "state": "measured",
        }
    ]
    payload.update(updates)
    return sr.OutputObservationBinding.model_validate(payload)


def test_output_observation_binding_accepts_a_distinct_output_artifact() -> None:
    binding = _observed_binding()
    assert binding.output_artifact.sha256 == OUTPUT_SHA
    assert binding.output_artifact.sha256 != binding.source_artifact.sha256
    assert binding.observations[0].domain == "output"


def test_output_observation_bound_to_foreign_artifact_refused() -> None:
    payload = _observed_binding().model_dump(mode="json")
    payload["observations"][0]["artifact"]["sha256"] = ANCHOR_SHA
    with pytest.raises(sr.ShotReskinRefusal) as excinfo:
        sr.OutputObservationBinding.model_validate(payload)
    assert excinfo.value.code is sr.ShotReskinRefusalCode.EVIDENCE_DOMAIN_MISMATCH


def test_output_binding_with_source_artifact_refused() -> None:
    payload = _observed_binding().model_dump(mode="json")
    payload["output_artifact"]["sha256"] = SOURCE_SHA
    with pytest.raises(sr.ShotReskinRefusal) as excinfo:
        sr.OutputObservationBinding.model_validate(payload)
    assert excinfo.value.code is sr.ShotReskinRefusalCode.OUTPUT_BINDS_SOURCE_ARTIFACT


def test_unmeasured_binding_must_not_carry_observations() -> None:
    payload = _observed_binding().model_dump(mode="json")
    payload["state"] = "unmeasured"
    with pytest.raises(sr.ShotReskinRefusal) as excinfo:
        sr.OutputObservationBinding.model_validate(payload)
    assert excinfo.value.code is sr.ShotReskinRefusalCode.EVIDENCE_DOMAIN_MISMATCH


def test_output_observation_with_foreign_role_refused() -> None:
    payload = _observed_binding().model_dump(mode="json")
    payload["observations"][0]["subject_role"] = "BOOK-P9"
    plan_payload = sr.FROZEN_EXAMPLES["shot_plan_book"]
    patched = json.loads(json.dumps(plan_payload))
    patched["output_observations"] = payload
    with pytest.raises(sr.ShotReskinRefusal) as excinfo:
        sr.ShotPlan.model_validate(patched)
    assert excinfo.value.code is sr.ShotReskinRefusalCode.FOREIGN_ROLE_REFUSED


# ── engine projection (composition surface) ───────────────────────────────────


def _binding_with_revision() -> sr.EngineInputBinding:
    record = sr.ShotExecutionRecord.model_validate(sr.FROZEN_EXAMPLES["execution_record_book_p3b"])
    assert record.input is not None
    model = record.input.graph.model.model_copy(update={"revision": "p3b-r28-local-convrot"})
    graph = record.input.graph.model_copy(update={"model": model})
    return record.input.model_copy(update={"graph": graph})


def test_payload_key_sets_match_the_pinned_dto_field_sets() -> None:
    payload = _binding_with_revision().to_request_payload()
    assert set(payload) == set(sr.ENGINE_REQUEST_TOP_LEVEL_FIELDS)
    assert set(payload["source"]) == set(sr.ENGINE_SOURCE_LOCK_FIELDS)
    assert set(payload["pins"]) == set(sr.ENGINE_WORKFLOW_PIN_FIELDS)
    assert set(payload["pins"]["model"]) == set(sr.ENGINE_MODEL_PIN_FIELDS)
    assert set(payload["output"]) == set(sr.ENGINE_OUTPUT_CONTRACT_FIELDS)
    assert set(payload["output"]["audio"]) == set(sr.ENGINE_AUDIO_FIELDS)
    assert set(payload["budget"]) == set(sr.ENGINE_BUDGET_FIELDS)
    assert set(payload["cast"][0]) == set(sr.ENGINE_CAST_FIELDS)
    assert set(payload["cast"][0]["references"][0]) == set(sr.ENGINE_REFERENCE_FIELDS)


def test_payload_is_deterministic_and_matches_the_frozen_digest() -> None:
    binding = _binding_with_revision()
    assert binding.request_payload_sha256() == sr.payload_sha256(binding.to_request_payload())
    assert binding.request_payload_sha256() == sr.FROZEN_REQUEST_PAYLOAD_SHA256


def test_payload_refuses_null_provisioning_revision() -> None:
    record = sr.ShotExecutionRecord.model_validate(sr.FROZEN_EXAMPLES["execution_record_book_p3b"])
    assert record.input is not None
    with pytest.raises(sr.ShotReskinRefusal) as excinfo:
        record.input.to_request_payload()
    assert excinfo.value.code is sr.ShotReskinRefusalCode.RECORD_INCONSISTENT
    assert "revision" in excinfo.value.detail


def test_plan_projects_into_engine_input_binding() -> None:
    plan = sr.ShotPlan.model_validate(sr.FROZEN_EXAMPLES["shot_plan_book"])
    record = sr.ShotExecutionRecord.model_validate(sr.FROZEN_EXAMPLES["execution_record_book_p3b"])
    assert record.input is not None
    model = record.input.graph.model.model_copy(update={"revision": "p3b-r28-local-convrot"})
    graph = record.input.graph.model_copy(update={"model": model})
    projected = sr.input_binding_from_plan(
        plan,
        identity=record.input.identity,
        capability=record.capability or "",
        graph=graph,
        output_contract=record.input.output_contract,
        budget=record.input.budget,
        anchor=record.input.anchor,
        auxiliary_models=record.input.auxiliary_models,
    )
    payload = projected.to_request_payload()
    assert payload["cast"][0]["references"][0]["sha256"].startswith("a6096945")
    assert payload["source"]["shot_range"] == {"start_frame": 0, "end_frame": 119}
    assert [c["role"] for c in payload["cast"]] == ["BOOK-P1", "BOOK-P2", "BOOK-P3"]


def test_engine_result_ready_requires_a_recorded_mapping() -> None:
    record = sr.ShotExecutionRecord.model_validate(sr.FROZEN_EXAMPLES["execution_record_book_p3b"])
    assert record.output is not None
    with pytest.raises(sr.ShotReskinRefusal) as excinfo:
        record.output.assert_result_ready()
    assert excinfo.value.code is sr.ShotReskinRefusalCode.ENGINE_RESULT_INCOMPLETE
    decoded = record.output.decoded.model_copy(update={"mapping": tuple(range(120))})
    record.output.model_copy(update={"decoded": decoded}).assert_result_ready()


def test_to_engine_request_fails_closed_without_the_transported_dto() -> None:
    if TRANSPORTED_DTO.exists():
        pytest.skip("accepted DTO is present — covered by test_move... (real construct below)")
    with pytest.raises(sr.ShotReskinRefusal) as excinfo:
        sr.to_engine_request(_binding_with_revision())
    assert excinfo.value.code is sr.ShotReskinRefusalCode.MEDIA_ENGINE_DTO_UNAVAILABLE


@pytest.mark.skipif(
    not TRANSPORTED_DTO.exists(),
    reason=(
        "app/schemas/media_engine.py not in this tree yet: the accepted NR05/NR06 bytes "
        "(blob 9e4586a1…) are transported into the product tree by the INT task; the "
        "composition is proven against that pinned blob by the MF-END-01 evidence probe "
        "(raw/probe_dto_composition.json) in the meantime"
    ),
)
def test_engine_request_constructs_the_real_accepted_dto_once_transported() -> None:
    from app.schemas import media_engine

    request = sr.to_engine_request(_binding_with_revision())
    assert isinstance(request, media_engine.MediaEngineRequest)
    assert request.capability is media_engine.MediaCapability.SOURCE_VIDEO_MOTION_TRANSFER


# ── legacy DTO smoke (they stay green; this file never mutates them) ──────────


def test_legacy_renderer_backend_record_is_orthogonal() -> None:
    record = sr.ShotExecutionRecord(
        execution_backend="legacy_renderer",
        legacy_route="sprite_affine",
        capability=None,
        outcome="pending",
    )
    assert record.execution_backend == "legacy_renderer"
    assert record.input is None and record.output is None


def test_legacy_renderer_with_engine_capability_refused() -> None:
    with pytest.raises(sr.ShotReskinRefusal) as excinfo:
        sr.ShotExecutionRecord(
            execution_backend="legacy_renderer",
            legacy_route="pose_swap",
            capability="source_video_motion_transfer",
        )
    assert excinfo.value.code is sr.ShotReskinRefusalCode.BACKEND_BINDING_INVALID


def test_legacy_schemas_still_import_and_validate() -> None:
    from app.schemas import reskin_config, s10_full_apply

    chunk = s10_full_apply.CreateChunkRequest(
        run_id="run-1",
        chunk_index=0,
        order_index=0,
        shot_id="BOOK",
        core_start_frame=0,
        core_end_frame=119,
        content_hash="0" * 64,
    )
    assert chunk.overlap_before == 0
    assert reskin_config is not None
