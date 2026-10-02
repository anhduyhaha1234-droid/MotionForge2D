"""Build docs/contracts/shot-reskin-delivery-v1.md from the contract module.

The three frozen JSON blocks (shot plan / execution record / negative fixtures)
are GENERATED from ``app/schemas/shot_reskin.py`` so the doc and the code cannot
drift: the test suite re-parses the marked blocks and asserts equality with
``FROZEN_EXAMPLES``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

WORKTREE = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-01")
sys.path.insert(0, str(WORKTREE))

from app.schemas import shot_reskin as sr  # noqa: E402

DOC_PATH = WORKTREE / "docs" / "contracts" / "shot-reskin-delivery-v1.md"


def block(name: str) -> str:
    payload = sr.FROZEN_EXAMPLES[name]
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"<!-- FROZEN_EXAMPLE: {name} -->\n```json\n{body}\n```\n<!-- /FROZEN_EXAMPLE: {name} -->"


PROSE_HEAD = """# Shot-reskin delivery contract v1 (MF-END-01)

Status: **contract + DTO + fixtures + tests only — no render was run** (packet
boundary).  `QUALITY_ACCEPTED=0`; not APPROVED/CLOSED.  Owner session
`20260928_111952_919c4e`; branch `codex/mf-end-01-0928`; base PRODUCT
`2c405f3e7643d42b387352643c89c8690976314`.  Implementation:
`app/schemas/shot_reskin.py`; tests: `tests/product_delivery/test_mf_end_01.py`;
evidence:
`mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-01/REPORT.md`.

This contract is the shot-level execution plan the app builds BEFORE an engine
call and records AFTER one, plus the evidence binding that keeps SOURCE facts
and OUTPUT observations apart.  It composes the accepted media-engine DTO
(`mf.media_engine.contract.v1`, MF-TOOL-CONTRACT NR05/NR06) by reuse — it never
redefines it, never modifies it and never stubs it.

## 1. What the contract owns

| Type | Owns |
|---|---|
| `ShotPlan` | source artifact + half-open span + timebase, declared elements (roles/props/background), interaction refs, reference manifest, source evidence, output observation binding |
| `ElementUnit` | role id, kind (person/prop/background/source_frame), source track, visible spans, occlusion, confidence |
| `InteractionRef` | subject role, relation, object role, one or more spans, evidence ids, measured/confirmed state |
| `ReferenceManifest` / `RoleReferenceSet` / `ReferenceItem` | per-role reference artifacts (managed ids + sha256 + key + view), style version, props, background |
| `SourceEvidenceFact` | a SOURCE fact (domain=source) measured on the locked source artifact |
| `OutputObservation` / `OutputObservationBinding` | OUTPUT facts (domain=output) measured on the rendered artifact; refuses when the output IS the source |
| `EngineInputBinding` | the engine-call input: capability, identity, source lock, cast+references, anchor, graph/model pins, output contract, budget — projected EXACTLY onto the accepted `MediaEngineRequest` field sets |
| `EngineOutputBinding` | what the engine returned: `prompt_id`, server graph hash, artifacts, decoded facts, audio handoff, wall time, VRAM peak |
| `ShotEngineError` | the error field: code, message, retryable, optional refusal-code link |
| `ShotExecutionRecord` | schema_version + execution backend (orthogonal axis) + capability + input/output/error + outcome |

## 2. Laws (binary; every refusal carries exactly one typed code)

| Law | Refusal code |
|---|---|
| intervals are half-open `[start, end)`; `end > start`, `start >= 0`; element visibility inside the shot span; interaction spans intersect it | `invalid_interval_refused` |
| frame rate and stream time_base are different quantities (pair-or-nothing); multi-frame span may not have a zero PTS span; declared time_base must hold `(frames-1)` frame intervals | `timebase_invalid` |
| a client path at any artifact position is refused (never resolved) | `client_artifact_path_refused` |
| roles declared by `elements`; interactions/manifest/evidence/observations may not name a role the shot does not declare | `foreign_role_refused` |
| element roles are unique in a shot | `duplicate_role_refused` |
| every interacting person carries references in the manifest (and the engine minima mirror `CAPABILITY_REFERENCE_REQUIREMENTS`) | `cast_reference_required` |
| source facts are measured on the locked source artifact; output observations on the rendered artifact; an output binding must name THIS shot's source | `evidence_domain_mismatch` |
| the output artifact may not be byte-identical to the source ("source returned as output") | `output_binds_source_artifact` |
| interaction evidence ids must exist in `source_evidence` | `unknown_evidence_refused` |
| a legacy renderer ROUTE is never an execution backend (`RENDERER_ROUTES` untouched) | `legacy_route_as_backend_refused` |
| backend vocabulary is closed; a comfy record carries no legacy route; a legacy record carries no capability/engine input/output | `backend_unknown_refused` / `backend_binding_invalid` |
| comfy backend requires a capability from the accepted vocabulary | `engine_capability_required` / `engine_capability_unknown` |
| a model pin handed to the engine needs the full-file sha256 (the DTO requires 64 hex) | `full_file_hash_required` |
| a `mask`/`graph`/`pose_sheet` artifact is never publishable; `publishable_types` may only narrow the server set | `artifact_not_publishable` |
| unknown contract version refuses | `schema_version_unsupported` |
| outcome/input/output/error consistency (completed ⇒ input+output, no error, …) | `record_inconsistent` |
| an engine RESULT needs a recorded decoded frame map — record it, do not invent it | `engine_result_incomplete` |
| the accepted DTO is not in this tree yet (INT transport pending) | `media_engine_dto_unavailable` |

## 3. Composition with the accepted media-engine contract v1

* Accepted bytes: `app/schemas/media_engine.py`, git blob
  `9e4586a1b2cbc8aeb6d35a75c038327533b81b2a` at `f0b918b` (CONTRACT branch of
  MF-TOOL-CONTRACT).  Blob id re-verified by `git hash-object` in the evidence
  probe; the file's sha256 is `5900c911aed68f586f0a17f8f1b5ae439aa0e8c540d3987b8d979095bc6e6bbe`.
* `EngineInputBinding.to_request_payload()` emits EXACTLY the
  `MediaEngineRequest` field sets (`workspace_id…budget`; nested models by their
  own field names).  The DTO's two refusal-only fields (`client_path`,
  `client_graph`) are deliberately NOT emitted — they exist so client input can
  be refused, and `ENGINE_REQUEST_TOP_LEVEL_FIELDS` therefore excludes them.
* `to_engine_request()` constructs the REAL DTO when it is importable;
  otherwise it refuses with `media_engine_dto_unavailable` (fail closed — no
  stub, no re-implementation, no silent degradation).  The transport itself is
  an INT job (EXECUTION_CONTRACT §3); MF-END-01 neither performs nor blocks it.
* Pinned vocabulary (cross-checked against the real DTO by the evidence probe):
  capabilities, artifact kinds, publishable kinds, server output types,
  `CAPABILITY_REFERENCE_REQUIREMENTS` minima.
* The `ShotRange` boundary is explicit: this contract's span is half-open
  `[start, end)`, the DTO's is INCLUSIVE — `to_engine_shot_range()` subtracts 1
  and `from_engine_shot_range()` adds 1 back; both are test rows.
* Model pin gap (open item O1): the P0 inventory recorded only 16-hex head-hashes
  (first 1 MiB).  MF-END-01 MEASURED the full-file sha256 of the five pinned
  Wan Animate 2 profile files (probe `probe_model_full_hashes.py`, 17.65 s,
  read-only) and re-derived every head-hash to prove provenance; the frozen
  example uses the full digests.  `revision` stays `null` because no
  provisioning revision was ever recorded — the projection refuses a null
  revision with a typed code (open item O1) instead of inventing one.

## 4. Frozen example — shot plan (BOOK unit, PROOF_GATE candidate)

Values come from the measured Phase-A evidence: `P1_UNIT_MANIFESTS.json`
(BOOK-UNIT-001 span/window/elements/interactions), `P3B_RECEIPT.json` (graph,
seed, outputs), and the MF-END-01 probes (PTS span `0..60928` = `119 × 512`
ticks at `30/1` fps and `1/15360` time_base, both on the source window and on
the rendered clip; packet storage order zigzags (B-frames) while the display
span is complete: 120 distinct PTS, all multiples of 512).  App-side identity
labels (project/series/artifact/cast/evidence ids) are placeholders by design —
the cast registry is created by MF-END-02+; every hash/byte/span is measured.

__BLOCK_SHOT_PLAN__

## 5. Frozen example — execution record (P3B BOOK, comfy backend)

`prompt_id`, output file names/bytes/sha256, wall time `154.67 s` and
VRAM peak `10973 MiB` are the P3B receipt values; the graph hash is the
submitted graph; `config_hash` is sha256 of the canonical `declared_params`
JSON from the receipt (recomputed in `raw/probe_dto_composition.json` payload
evidence).  `server_output_type` is `unclassified` on every artifact because
the receipts record no server classification — and an unclassified node output
is never publishable (NR05.4); the contract mirrors that instead of claiming
`output`.  Budget numbers are the demo POLICY caps: wall 900 s (cold BOOK run
measured 596.95 s), VRAM cap = the device total 12,227 MiB, output cap 512 MiB.
The engine-request payload built from this record (with the provisioning
revision label supplied) has canonical sha256
`__PAYLOAD_SHA__`.

__BLOCK_RECORD__

## 6. Negative fixtures (machine-readable, used by the tests)

Each fixture patches one of the frozen examples (`set` = dotted path → value,
`append` = append to the list at the path) and MUST refuse with the listed code.
The test file parametrizes over this array, so the doc block, the module
constant and the test rows are one source.  Every `set` on `sha256` uses a REAL
hash from the proof evidence as the "foreign" value — no invented digests.

__BLOCK_FIXTURES__

## 7. Source vs output evidence (U08 / U21)

* A `SourceEvidenceFact` (domain `source`) must be measured on the locked source
  artifact; a foreign artifact refuses (`evidence_domain_mismatch`).
* An `OutputObservation` (domain `output`) must be measured on the rendered
  artifact the binding names; anything else refuses.
* `OutputObservationBinding` refuses an output whose sha equals the source
  (`output_binds_source_artifact`) — the "source returned as output" case the
  MF-END-19 acceptance names.
* `state=unmeasured` must carry no observations: absence of data is visible as
  UNKNOWN, never as an empty list that reads like a pass.
* The frozen output binding is `unmeasured` on purpose: role-level output
  observations are produced by MF-END-21; the binding freezes the artifact
  identity today so those observations are domain-pinned the moment they exist.

## 8. Legacy route orthogonality

`app/persistence/models.py::RENDERER_ROUTES` = (`pose_swap`, `sprite_affine`,
`mesh_warp`, `part_rig`, `controlled_redraw`) is untouched; the values are
PINNED in this module (`LEGACY_RENDERER_ROUTES_PIN`) so a legacy route used as
an `execution_backend` refuses with `legacy_route_as_backend_refused`, a comfy
record carrying a `legacy_route` refuses, and a legacy record carrying engine
capability/input/output refuses.  Comfy is a backend, not a route alias.

## 9. Open items (recorded, not fixed here)

* **O1** — the P0 model inventory records no provisioning `revision`; engine
  pin projection refuses a null revision (typed).  Owner: MF-END-16 (model
  profiles) / provisioning.
* **O2** — the partial person `BOOK-P4` (right-edge sliver, visible all 120
  frames) has NO reference artwork yet; the plan freezes its element and the
  demo coverage finding F2 (DEMO_PROOF_REVIEW) tracks it.  Owner: MF-END-12/14.
* **O3** — book-state policy (Wan keeps the book closed while the source opens
  it at frame 72) is a product decision; the contract can express the change
  (two interaction spans) but does not decide it.  Owner: Codex (F3).
* **O4** — the receipts record no per-node pins and no decoded frame map;
  `nodes: []` and `mapping: null` in the examples are the measured truth, and
  `assert_result_ready()` refuses a result without a map.  Owner: MF-END-18/19.
* **O5** — server output classification (`server_output_type`) is absent from
  the receipts; every frozen artifact is `unclassified` (never publishable).

## 10. Verification

* Frozen examples validate; 23/23 negative fixtures refuse with their exact
  codes; payload key sets equal the accepted DTO field sets; payload digest is
  frozen (`__PAYLOAD_SHA__`); `to_engine_request` fails closed without the
  transported DTO; the composition probe builds a REAL `MediaEngineRequest`
  from the pinned blob (22 rows) including four DTO-side negatives.
* Raw evidence: `MF-END-01/raw/probe_selfcheck.json`,
  `MF-END-01/raw/probe_dto_composition.json`, `MF-END-01/commands.jsonl`,
  `MF-END-01/REPORT.md`.
"""


def main() -> int:
    text = (
        PROSE_HEAD.replace("__BLOCK_SHOT_PLAN__", block("shot_plan_book"))
        .replace("__BLOCK_RECORD__", block("execution_record_book_p3b"))
        .replace("__BLOCK_FIXTURES__", block("negative_fixtures"))
        .replace("__PAYLOAD_SHA__", sr.FROZEN_REQUEST_PAYLOAD_SHA256)
    )
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(text, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(DOC_PATH.read_bytes()).hexdigest()
    print(f"wrote {DOC_PATH} bytes={DOC_PATH.stat().st_size} sha256={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
