# S13_P00_DELTA_MATRIX — old criterion → disposition → affected task → scope

**Task:** MF-TOOL-CONTRACT · **Status:** PROPOSAL (awaiting `C-CONTRACT` Codex review)

**Round D (this revision):** closes NR05 (contract) and NR06 (formal delta) from
`mf-review-20260924-f991e243`. Every row carries its exact C5 incoming edges, its exact
write-set, its migration owner + `down_revision` discovery and the tests that prove it (§2b,
§2c, §2d, §2e); §7 is a formal delta. S13-INT01, the 22 production tasks and P01A/P01B stay
`BLOCKED_DEPENDENCY` — C-CONTRACT remains `CHANGES_REQUESTED` until Codex says otherwise.
**Purpose:** for every criterion that already exists in the S13 plan and in the shipped
engine, state whether this contract **retains**, **replaces** or **defers** it — with the
affected S13 P00 task, the exact file/hunk/migration scope, the dependency that gates it and
the acceptance that closes it.

**Source of truth for the old criteria (both are read, neither is rewritten here):**

- `docs/pm/ROADMAP.md:264-277` — the sprint-level rows `S13-T01..S13-T08` ("old granularity").
- `output/s13-p00-readiness/20260823-0045-r1/synthesis/TASK_MAP_T01_T08_DRAFT.md` (revision
  C5) — the **22 active sub-task IDs**: T01A/B/C/D, T02A/B, T03A/B/C, T04A/B/C, T05A/B/C,
  T06A/B, T07A/B, T08A/B/C, each with write-set, forbidden paths and binary acceptance.
- `output/s13-p00-readiness/20260823-0045-r1/synthesis/ACCEPTANCE_GATES.md` and
  `DEPENDENCY_DAG.md` — gate vocabulary (waves W1–W11, `G5` write-set discipline,
  `FROZEN F-8/F-10/F-11/F-12`, `C13-GOLDEN-TRUTH-SIGNOFF`).

Legend — **disposition:** `RETAIN` (unchanged), `REPLACE` (superseded by a sharper rule in
this contract), `DEFER` (correct, but out of scope for P00; needs its own packet).

---

## 1. Sprint-level criteria (ROADMAP `S13-T01..T08`, old granularity)

| # | Old criterion (ROADMAP) | Disposition | Affected P00 task | Exact scope of the delta | Dependency | Acceptance |
|---|---|---|---|---|---|---|
| 1 | T01 — Character Profile + stable reference-code prompt contract | `RETAIN` | T01A (schema+repo+migration), T01C (prompt registry/version/hash) | **No file scope here.** Profile/reference binding stays exactly as P00 wrote it; the media engine only *consumes* `character_id`/`pack_version_id` through `CastBinding` | T01A approved | `CastBinding` fields match T01A's binding schema 1:1 (integration packet) |
| 2 | T02 — ComfyUI/provider adapter with capability + failure contracts | `REPLACE` (sharper) | T02A (protocol/config/4-state probe/resolver), T02B (transport/failure/security) | The adapter must express capability as the **four distinct values** of `MediaCapability`, with absence always carrying a reason code; a source-locked capability must not be servable by a degraded target | T01B + T01C approved | probe reports each of UNCONFIGURED/UNREACHABLE/DEGRADED/READY truthfully; resolver raises `PROVIDER_UNAVAILABLE` with **no fallback** |
| 3 | T03 — Pose-conditioned six-panel generation job | `REPLACE` (scope split) | T03A (single-slot durable job), T03B (six-slot orchestration/restart/cancel), T03C (generation HTTP contract) | Six-slot is the **legacy flat-2D** output shape for this capability; the engine contract does **not** universalise six slots. Replay/`InflightReservation` rule binds T03B | T02A approved + E01 infra; T03C after T01D+T02A+T03B+T04A | one six-slot round from a **confirmed** profile; client cannot choose provider (payload with `provider` → 422); restart/cancel map to a typed terminal state |
| 4 | T04 — Identity/style/pose validation + panel status | `RETAIN` (+typed states) | T04A (validation persistence/API), T04B (geometry), T04C (identity/style/cross-view) | Validation results must project onto the **distinct** contract states `generated/validated/reviewed/accepted/published` — no boolean collapse | T01B approved directly (candidate FK mandatory) | validation persists against the candidate FK; `validated` ≠ `accepted` is observable |
| 5 | T05 — Guided upload→profile→generate→review UI | `RETAIN` | T05A/B/C | No UI change in P00. The UI must render capability **absence with a reason**, not an empty panel | T01D + T03C + T04A approved | UI shows a stated reason for every unavailable capability |
| 6 | T06 — Regenerate one panel, preserve approved panels | `RETAIN` (+cache identity) | T06A (backend isolation), T06B (regenerate-one UI/E2E) | Regenerating one panel **must not** invalidate approved panels: this is exactly the shot-scoped invalidation rule (`invalidate_for_reference_change`) | T03B + T01B approved | one panel regenerates; other panels' artifacts byte-identical; a reference change invalidates only affected entries |
| 7 | T07 — Publish complete approved output as immutable Pack Version | `RETAIN` (fail-closed) | T07A (publish backend/snapshot/audit), T07B (confirm-publish UI/E2E) | Publication stays fail-closed; the engine adds an artifact-level pre-check that **narrows** what may publish and refuses an empty publish set | T05B + T06A approved | only `accepted` → `published`; publish snapshot + audit record; empty publish set refuses |
| 8 | T08 — Scenario J quality/performance benchmark report | `DEFER` | T08A/B/C | Benchmark truth stays Codex-signed; thresholds frozen **before** run 0. No engine constant may be tuned to make a benchmark pass | T04B+T04C; T08B behind the N≥3 blind-human roster | `THRESHOLDS_FROZEN.json` written before run 0; expected-verdict table complete pre-run |

## 2. Engine-level criteria already shipped (must not regress)

| # | Old criterion | Disposition | Affected P00 task | Exact scope | Dependency | Acceptance |
|---|---|---|---|---|---|---|
| 9 | Legacy six-slot completeness: `CORE_POSE_SLOTS` all present | `RETAIN` **unchanged** | T01A, T04A | `app/persistence/models.py:170`, `app/persistence/characters.py:569/746` — **no edit in P00** | — | a legacy pack still validates/publish exactly as today; `missing_slots` semantics unchanged |
| 10 | Immutable pack versions + CAS on publish/repin | `RETAIN` | T01B, T07A | `app/persistence/project_cast.py`, `app/schemas/{characters,project_cast}.py` — **no edit** | — | stale revision refuses (`stale_revision`); published version immutable |
| 11 | Cast pins an immutable `PackVersion` (never a mutable character) | `RETAIN` | T01B, T03C | media engine `CastBinding` is a **projection**, no second table | T01A | role → one `CharacterID` + one `PackVersion`, unique per request |
| 12 | Compatibility reasons are a closed typed set | `RETAIN` | T04A, P01A | `app/schemas/project_cast.py::CompatibilityReason` — extended later only per §6 | — | every refusal names one of the closed reason codes |
| 13 | Approval audit with conflict/integrity semantics | `RETAIN` | T07A | `app/services/s09_approval.py` — **no edit** | — | replaying an approval conflicts; audit row is immutable |
| 14 | Fail-closed publication (receipts, intent, lease) | `RETAIN` | T07A | `app/services/s12_export/publication.py`, `publication_lease_guard.py` — **no edit** | — | publication never silently overwrites; a lost race raises |
| 15 | Manual-library fallback when generation fails | `RETAIN` | T05A, T07B | `app/workflow/character_preset_importer.py`, `app/services/preset_manager.py` — **no edit** | — | with the provider unconfigured, the manual library path still works end-to-end |
| 16 | Single renderer route taxonomy (5 routes, one authority) | `RETAIN` | T02A | `app/persistence/models.py::RENDERER_ROUTES` — **never copied** | — | no second copy of the route list anywhere in S13 |
| 17 | One durable job store (E01) + one concurrency engine | `REPLACE` (made explicit) | T03A, T03B | media engine asserts it structurally (`assert_shared_stack`) | E01 | a second job store or competing engine is refused, not tolerated |
| 18 | Client cannot name the provider over HTTP | `RETAIN` (moved to T03C by C5-F1) | T03C | payload carrying `provider` (or equivalent) → 422 | T01D+T02A+T03B+T04A | 422 with an explicit error; zero jobs created |
| 19 | Validation thresholds frozen before benchmark run 0 | `RETAIN` | T08A | `THRESHOLDS_FROZEN.json` before run 0 | T04B+T04C | frozen file hash recorded before run 0 |
| 20 | Golden truth is Codex-signed, never self-signed | `RETAIN` | T08A/B | `C13-GOLDEN-TRUTH-SIGNOFF` (FROZEN F-12) | — | PM/Manager/worker never sign; only Codex opens the gate |

## 2b. Per-TaskID mapping — all 22 P00 IDs + P01A/P01B (C5 revision)

Codex R7 required the matrix to map **every** active sub-task ID from the C5 map
(`TASK_MAP_T01_T08_DRAFT.md`, revision C5) with an exact disposition, the old symbol or hunk it
touches, the new/changed path, the migration owner, the dependency that gates it and the tests
that close it. The 22 IDs are `T01A/B/C/D`, `T02A/B`, `T03A/B/C`, `T04A/B/C`, `T05A/B/C`,
`T06A/B`, `T07A/B`, `T08A/B/C` — **22 = 4+2+3+3+3+2+2+3**, and they stay exactly 22 (see §8).
`ADD` means "this contract contributes one additive, named change"; it is never a silent
replacement of the task's own acceptance.

**Round D correction (NR06):** the previous revision of this table dropped eleven P00
DAG edges while the document claimed the graph was unchanged, and the changes it did
make were labelled *clarifications*. Both are corrected here: the `C5 depends-on`
column below now carries the **exact** incoming edge set of every row (§2c is the
authoritative edge list, transcribed from `P00/DEPENDENCY_DAG.md` §2), and every change
to a requirement is stated as a **formal delta** in §7 (old criterion/symbol -> new
path/symbol, owning TaskID, migration owner, `down_revision` discovery, proving tests).
Restored edges: `T01A -> T01C`, `T01A -> T01D`, `T02A -> T03A`, `T03A -> T03B`,
`T04A -> T04B`, `T04A -> T04C` (T04C previously substituted T04B), `T05A -> T05B` +
`T04A -> T05B`, `T05B -> T06B`, `T06A + T04B + T04C -> T07A`, `T07B + T06B -> T08B`,
and the T08C gate is restored to `frozen T03C + B13-PROVIDER-MEASURED-EVIDENCE`
(T08B was substituted). T08A preparation carries **no** human-roster blocker; the
roster gates T08B only.

### 2b.1 T01–T04 (12 IDs)

| # | TaskID | Disposition | Reason | C5 depends-on (edges restored) | Old symbol / hunk (authority) | Exact new / changed path + symbol | Migration owner / `down_revision` discovery | Tests that prove it |
|---|---|---|---|---|---|---|---|---|
| 1 | T01A | `RETAIN` + `ADD` | character/profile binding is unchanged; the reference-pack contract is ONE additive column + a frozen manifest on the existing immutable version | E04 (library spine) — no P00 predecessor | `app/persistence/models.py::CharacterPackVersion` (`character_pack_version`; `ck_pack_version_status`, `uq_pack_version_character_version`), `app/persistence/characters.py::CORE_POSE_SLOTS` use at `:569`/`:746` | `character_pack_version.pack_contract_version` + `requirement_manifest_json` + `requirement_manifest_sha256` (migration 1 of 3, §5.3); branch vocabulary `legacy_six_slot_2d` / `reference_pack_v1`; **no second pack/library/cast/asset table** | **MIGRATION OWNER 1 of 3** — `migrations/versions/<live-head-child>_s13_t01a_identity_profile.py`; `down_revision` = LIVE single head at activation (C5 G1: never hard-coded, abort on multiple heads); measured this round: single head `d4e5f6a7b8c9` (21 files / 21 revisions / 0 missing parents) | `tests/test_s13_t01a_pack_contract.py` — legacy rows read `legacy_six_slot_2d`, reference rows carry a manifest; legacy completeness unchanged; both CHECK constraints refuse a half-bound branch |
| 2 | T01B | `RETAIN` + `ADD` | immutable pack versions + CAS on publish/repin stay the authority; the manifest is FROZEN at publish, never re-derived | T01A | `app/persistence/project_cast.py` (pack must be published+complete), `app/schemas/characters.py::PublishVersionRequest`/`SetDefaultVersionRequest` | publish path in `app/persistence/characters.py` writes `requirement_manifest_sha256` ONCE at publish — the manifest is frozen against the existing immutable `CharacterPackVersion`, never re-derived; repin stays CAS-only | **MIGRATION OWNER 2 of 3** — `migrations/versions/<live-head-child>_s13_t01b_slot_candidate.py`; `down_revision` = the live head at ITS activation (normally T01A's migration); one file, chained, never concurrent | `tests/test_s13_t01b_manifest_freeze.py` — a published version's manifest hash never changes; repin is CAS-only; a `reference_pack_v1` row without a manifest is unpersistable |
| 3 | T01C | `RETAIN` | prompt registry/version/hash semantics are untouched by this contract | T01A | C5 prompt-registry entries; `reference_code` prompt contract | **no file change** — the delta is the restored dependency edge `T01A -> T01C` (template content-hash pins the profile/reference hash tuple T01A stores). Previously the row omitted `T01A`, which would have let T01C open in W2 against an unfrozen T01A schema | no migration (C5 F-2: versioned code module) — this is what keeps W2 provably disjoint | C5's own T01C tests (prompt template content-hash pinning) + a wave-disjointness check proving the `T01A` edge is consumed before W2 opens |
| 4 | T01D | `RETAIN` | the single `app/api/app.py` router include discipline is unchanged (one hunk per task, serialized) | T01A | `app/api/app.py` (one include) | **no file change** — the delta is the restored dependency edge `T01A -> T01D`; T01D's `app/api/app.py` include stays ONE hunk, serialized before T03C's include (one owner per shared file per wave) | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | C5's T01D tests (one-include diff assertion) + the W2 disjoint-write-set proof across T01B/T01C/T01D |
| 5 | T02A | `REPLACE` (sharper) | capability must be the four distinct `MediaCapability` values with explicit absence; the probe is fail-closed | T01B + T01C | `app/services/renderer_contract.py::CapabilityDescriptor`, `RendererContractCode`; `app/persistence/models.py::RENDERER_ROUTES` | NEW `app/services/generation/provider.py` (protocol/DTOs) + `resolver.py` (fail-closed four-state capability probe: UNCONFIGURED/UNREACHABLE/DEGRADED/READY, absence always carrying `unavailable_reason_code`) + `__init__.py`; consumes `MediaCapability` from `app/schemas/media_engine.py`; reads `app/services/renderer_contract.py::CapabilityDescriptor`/`RendererContractCode` and `app/persistence/models.py::RENDERER_ROUTES` READ-ONLY. The former `app/services/generation/**` wildcard is replaced by these three exact paths. A source-locked capability may not be served by a degraded target (`FORBIDDEN_DEGRADATION_TARGETS`) | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | `tests/test_s13_t02a_capability_probe.py` — four-state probe reported truthfully, absence always with a reason code, no fallback, degradation of a source-locked capability refused |
| 6 | T02B | `RETAIN` | transport containment/failure/security scope is unchanged; it inherits the typed refusal vocabulary | T02A | C5 T02B transport surface | **no behaviour change** — transport containment/failure/security inherit the typed refusal vocabulary of `app/schemas/media_engine.py::MediaEngineRefusalCode` (no edit); the changed requirement in this row is the DEPENDENCY (`T02A` protocol frozen) plus the additive `pack_contract_version` context for the error envelope's model pin | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | C5's T02B tests (fake transports only) + a typed-code assertion on the refusal envelope |
| 7 | T03A | `RETAIN` + `ADD` | one durable job per slot still goes through E01; the contract adds the durable `InflightReservation` identity (epoch/workspace/output contract) | T02A + E01 | `app/persistence/jobs.py` (leases, idempotency keys, attempts) | durable single-slot job unchanged; the contract adds the pure `InflightReservation` + `reservation_identity_for` used by the handler, and the row now carries its real edge `T02A + E01` (it previously named only E01) | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | `tests/technology/test_media_engine_contract.py::test_reservation_identity_is_epoch_bound_but_the_cache_is_not` + C5's single-slot job tests |
| 8 | T03B | `REPLACE` (made explicit) | six-slot orchestration is a legacy *output shape*; the replay rule is now settled against a backend identity proof, ownership first | T03A + E01 | `resolve_replay` (this task) + E01 replay-safe window (`docs/architecture/DURABLE_JOB_CONTRACT.md` §8) | six-slot orchestration unchanged as an *output shape*; the contract adds `BackendIdentityProof`, `resolve_replay` and the ownership-before-reattach rule; the row now carries `T03A` (it previously named `T02A + E01` only, i.e. it could have opened before the single-slot handler it composes existed) | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | `test_replay_owner_is_proven_before_the_acked_reattach`, `test_unresolved_replay_never_duplicates_the_post` (18 cases) + C5's orchestration tests |
| 9 | T03C | `RETAIN` + `ADD` | the client still cannot name a provider (422); the request carries the capability-aware reference requirement | T01D + T02A + T03B + T04A | C5 T03C HTTP surface; `app/schemas/media_engine.py::MediaEngineRequest` | `CAPABILITY_REFERENCE_REQUIREMENTS` enforcement at request construction + `SourceLock`/`OutputContract` cross-field invariants (NR05) applied to incoming payloads; client `provider` -> 422 unchanged | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | `test_source_motion_requires_reference_pixels`, `test_controlled_edit_is_not_forced_to_carry_character_references` + `test_source_locked_output_must_reproduce_the_source_timeline` + the 422 provider-payload test |
| 10 | T04A | `RETAIN` + `ADD` | validation persistence/API unchanged; results must still project onto the five distinct states | T01B | `app/schemas/characters.py::PackVersionValidationData`, `app/services/s09_approval.py` | validation persistence unchanged; the validator must ALSO read the pack's declared branch (`pack_contract_version`) — migration 3 of 3 reads the column, never writes it; compatibility evaluator stays ONE implementation with TWO branches at `app/schemas/project_cast.py::CompatibilityEvaluateRequest`/`CompatibilityEvaluateResponse` (+ the `CompatibilityReason` literal at `:105`) | **MIGRATION OWNER 3 of 3** — `migrations/versions/f13a04a20268_s13_t04a_candidate_validation.py` (C5 D3 name; the revision id is discovered at activation); `down_revision` = live single head at activation, abort on multiple heads; this row READS `pack_contract_version`, never writes it | `tests/test_s13_t04a_validation_branch.py` — legacy validator unchanged, reference branch reads the manifest; tri-state FK/CHECK present in the DB after upgrade; the compatibility evaluator stays ONE implementation with TWO branches |
| 11 | T04B | `RETAIN` | geometry validation is unchanged; it is not the place a pack's contract branch is decided | T04A | C5 T04B geometry checks | **no behaviour change in the checks themselves** — the row's old `—` dependency was the defect: geometry checks register into the T04A tri-state pipeline (`T04A -> T04B`). Values `PASS / REVIEW_REQUIRED / FAIL` come from `app/persistence/character_validation_results.py` (T04A), so T04B cannot open before T04A | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | C5's T04B geometry tests + the registration test proving the checks feed the T04A tri-state pipeline (the restored `T04A -> T04B` edge) |
| 12 | T04C | `RETAIN` (+capability-aware) | identity/style/cross-view validation stays; it must consult the capability's requirement profile instead of a universal slot list | T04A | C5 T04C validators | **substituted dependency corrected**: identity/style/cross-view checks depend on `T04A` (the tri-state registration pipeline), NOT on T04B. The capability-aware requirement profile is read from `CAPABILITY_REFERENCE_REQUIREMENTS` (`app/schemas/media_engine.py`), so no universal slot list is required of a `reference_pack_v1` pack | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | `test_every_capability_declares_a_normative_reference_requirement` + C5's T04C cross-view tests registering through T04A |



### 2b.2 T05–T08 (10 IDs) + P01A/P01B — 22 + 2

| # | TaskID | Disposition | Reason | C5 depends-on (edges restored) | Old symbol / hunk (authority) | Exact new / changed path + symbol | Migration owner / `down_revision` discovery | Tests that prove it |
|---|---|---|---|---|---|---|---|---|
| 13 | T05A | `RETAIN` | guided upload→profile→generate flow unchanged; the manual-library fallback keeps working when generation fails | T01D + T03C + T04A | `app/workflow/character_preset_importer.py`, `app/services/preset_manager.py` | shell UI unchanged; inherits capability absence WITH a reason and the reference requirement profile; dependency unchanged (`T01D + T03C + T04A`) | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | C5's T05A tests + the fallback epic-exit test (manual library still works with the provider unconfigured) |
| 14 | T05B | `RETAIN` | review UI unchanged in P00 | T05A + T04A | C5 T05B surface | review grid unchanged as UI; the restored edges are `T05A -> T05B` and `T04A -> T05B` — the row previously named only `T03C`, which would have opened the review grid before the shell and before the states it renders existed | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | C5's T05B tests + a grid test that renders capability absence with a stated reason (the restored `T04A -> T05B` states) |
| 15 | T05C | `RETAIN` (+capability-aware) | the UI must render capability ABSENCE with a stated reason and must show **only the requirement of the pack type the pack actually declares** — never "missing pose" for a pack that never declared flat-2D slots | T05B | C5 T05C UI; `asset_content_url` per-slot preview | UI must show ONLY the requirement of the pack type the pack actually declares (never 'missing pose' for `reference_pack_v1`); dependency `T05B` unchanged | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | UI test: a `reference_pack_v1` pack renders its DECLARED requirements and emits no six-slot wording |
| 16 | T06A | `RETAIN` + `ADD` | backend isolation of a single-panel regenerate is unchanged; the contract supplies the cache identity + the epoch distinction | T03B + T01B | `invalidate_for_reference_change`, `cache_identity_for` (this task) | backend isolation unchanged; the contract supplies `cache_identity_for` + the epoch distinction, and the reference-pack branch means a reference change invalidates only the affected shot entries. Dependency unchanged (`T03B + T01B`) | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | `test_every_cache_identity_component_changes_the_digest` (12 controls), `test_cache_distinguishes_capability_and_stream_timebase_but_not_the_epoch` |
| 17 | T06B | `RETAIN` | regenerate-one UI/E2E unchanged | T05B + T06A | C5 T06B E2E | regenerate-one UI/E2E unchanged; restored edge `T05B -> T06B` (the row previously named only `T06A`) — the UX cannot be built before the panel it acts on | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | C5's T06B E2E + a single-request network-log assertion (restored `T05B -> T06B`) |
| 18 | T07A | `RETAIN` + `REPLACE` (fail-closed, sharper) | publish backend/snapshot/audit unchanged; the publication gate now takes the SERVER's node-output classification as the authority and refuses an EMPTY allow-list | T06A + T04B + T04C | `app/services/s12_export/publication.py`, `publication_lease_guard.py`; `assert_publishable_set` (this task) | publication gate takes the SERVER node-output classification as authority (an omitted classification is `unclassified` and refuses; empty allow-list refuses) and the snapshot pins the APPROVED reference-pack manifest: `app/persistence/characters.py` publish tx records `pack_contract_version` + `requirement_manifest_sha256` beside the existing immutable version / `published_at` / `validation_json` / per-slot assets, reusing the existing receipt writer `app/services/s12_export/publication.py::_write_publication_receipt` (no edit there). Restored edges `T06A + T04B + T04C -> T07A` (the row previously named `T05B + T06A`, which would have published unvalidated geometry/identity results) | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | `test_empty_publish_allowlist_refuses`, `test_non_output_server_classifications_refuse_publication`, `test_absent_server_classification_is_recorded_and_refuses_publication` + a snapshot assertion that `pack_contract_version` + `requirement_manifest_sha256` are pinned at publish (restored `T04B`/`T04C` edges) |
| 19 | T07B | `RETAIN` | confirm-publish UI/E2E unchanged; it inherits the empty-allow-list refusal | T07A + T05B (+ T05C) | C5 T07B E2E | confirm-publish UI/E2E unchanged; dependency `T07A + T05B (+T05C)` unchanged; inherits the empty-allow-list / unclassified refusals | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | C5's T07B E2E + the near-threshold block/approve path (SJ-04/SJ-05) |
| 20 | T08A | `DEFER` | Scenario J benchmark truth stays Codex-signed; thresholds frozen BEFORE run 0; no engine constant may be tuned to make a benchmark pass | T04B + T04C — **no human-roster blocker** | C5 T08A; `THRESHOLDS_FROZEN.json` | preparation has **NO human-roster blocker**: the golden cohort `12 + 10 + 8 = 30`, `THRESHOLDS_FROZEN.json` and `EXPECTED_VERDICTS.json` are produced from `T04B + T04C` alone, freeze-BEFORE-run-0. Its completion ENABLES the Codex-only gate `C13-GOLDEN-TRUTH-SIGNOFF`, which is an OUTGOING edge to T08B — never an incoming gate on T08A | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | `output/s13-t08-benchmark/THRESHOLDS_FROZEN.json` hash recorded BEFORE run 0; golden cohort assertion `12 + 10 + 8 = 30`; **no roster artifact is read by any T08A test** |
| 21 | T08B | `DEFER` | blind-human roster is an external act | T07B + T06B + T08A + C13-GOLDEN-TRUTH-SIGNOFF + real N>=3 roster | C5 T08B; `C13-GOLDEN-TRUTH-SIGNOFF` (FROZEN F-12) | real gates only: `T07B + T06B + T08A` + `C13-GOLDEN-TRUTH-SIGNOFF` + a REAL N>=3 blind-human roster confirmed pre-dispatch (missing roster => `BLOCKED_DEPENDENCY`, never a mock run). The roster gates ONLY this row | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | signed roster (`N >= 3`) present before the verdict table is read; blinded FAR/repeatability artifacts under `output/s13-t08-benchmark/results/**` |
| 22 | T08C | `DEFER` | benchmark reporting artefacts are a later packet; the registry rows it reads are this contract's (§7 rows 24–26) | frozen T03C + B13-PROVIDER-MEASURED-EVIDENCE — **not T08B** | C5 T08C; `ModelRegistryEntry.release_date` vs `repo_modified_date` | gate corrected: `frozen T03C + B13-PROVIDER-MEASURED-EVIDENCE` — **not T08B**. Aggregation validates EXTERNAL provider evidence only; any missing required field => `BLOCKED_DEPENDENCY`, never fabricated | no migration in this task; it does not touch `migrations/**` (any change there needs its own Codex-approved delta — §6) | `test_release_date_and_repo_modification_date_are_different_facts`, `test_no_automatic_download_from_a_ui_click` + the REQUIRED-field contract test on external evidence; missing field -> `BLOCKED_DEPENDENCY` |
| P01A | P01A | `RETAIN` — advisory, **zero writes** | the fit recommender is contracted, never implemented here; hard gates precede any AI score, and a run creates no cast row, no pack version, no publication | T01A + T01C + T02A (approved) | `S13_P01_TASK_CONTRACTS.md` §1 (`app/services/generation/character_fit.py`, `app/schemas/character_fit.py`, `tests/test_character_fit.py` — all NEW, later packet) | advisory, **zero writes** beyond its three allowlisted files: hard blockers evaluated BEFORE any AI score, Top-K with per-dimension explanation, no cast/pack/publication mutation | no migration — advisory, zero writes | `tests/test_character_fit.py` — hard blockers precede any AI score; Top-K explains every dimension; a run creates no cast row, no pack version, no publication (`git status` shows only the three allowlisted files) |
| P01B | P01B | `RETAIN` — **user-confirmed only** | browsing/fit endpoints are read-only; persistence goes through the existing project-cast CAS APIs after explicit human confirmation; the confirmed choice survives 2 videos + a reopen | P01A + T03C + T05B, serialized after T07B | `S13_P01_TASK_CONTRACTS.md` §2 (`app/api/routes/character_fit.py`, `tests/test_character_fit_api.py`, `frontend/src/app/(app)/characters/generation/fit/**`, `frontend/e2e/s13-p01-fit.spec.ts` — NEW; `app/api/app.py` one include hunk) | **user-confirmed only**: browsing/fit endpoints read-only, persistence through existing project-cast CAS APIs after explicit human confirmation; the confirmed choice survives two videos + a reopen | no migration — reuses existing project-cast CAS APIs | `tests/test_character_fit_api.py` + `frontend/e2e/s13-p01-fit.spec.ts` — stale revision refuses, missing evidence refuses, the confirmed choice survives 2 videos + a reopen |

**Count: 22 P00 IDs (12 above + 10 here) + P01A + P01B = 22 + 2 = 24 rows.**

## 2c. Exact DAG edges (C5 authority) — restored

Transcribed from `P00/DEPENDENCY_DAG.md` §2 (revision C5). `RESTORED` marks an edge the
previous revision of §2b omitted or substituted; nothing else is changed. A row may never
open without every incoming edge APPROVED (DAG GATE-rule A).

| # | Edge | Justification (C5) | Consumed by | §2b status |
|---|---|---|---|---|
| 1 | `P00 -> W1` | S13-P00 APPROVED by Codex is the activation gate; no production task opens from TASK_MANAGER_VERIFIED | all 22 | RETAINED (§8) |
| 2 | `E04 -> T01A` | identity binding extends the Character domain; reference authority = `Artifact.sha256` | T01A | RETAINED |
| 3 | `T01A -> T01B` | candidate rows FK identity/profile artifacts and reuse the hash-binding columns | T01B | RETAINED |
| 4 | `T01A -> T01C` | template content-hash pins the reference/profile hash tuple semantics | T01C | **RESTORED** |
| 5 | `T01A -> T01D` | the HTTP contract binds reference Artifacts into the profile T01A stores | T01D | **RESTORED** |
| 6 | `T01B + T01C -> T02A` | the request DTO needs `identity_profile_hash` + `prompt_template_id/version` | T02A | RETAINED |
| 7 | `T01B -> T04A` | validation persists against candidate rows; the tri-state store carries a MANDATORY candidate FK | T04A | RETAINED (C5-F1) |
| 8 | `T02A -> T02B` | transport implements the frozen `GenerationProvider` protocol | T02B | RETAINED |
| 9 | `T01D + T02A + T03B + T04A -> T03C` | the route surface requires all four; serialized after all four | T03C | RETAINED |
| 10 | `T02A -> T03A` | the handler drives submit/poll through the protocol; the capability gate pattern is reused | T03A | **RESTORED** |
| 11 | `E01 -> T03A, T03B` | lease/fence/checkpoint/idempotency machinery is shared | T03A, T03B | RETAINED |
| 12 | `T03A -> T03B` | six-slot orchestration composes N single-slot jobs + restart/cancel semantics | T03B | **RESTORED** |
| 13 | `T03B -> T03C` | the HTTP contract invokes T03B orchestration; T03B never self-creates a route | T03C | RETAINED |
| 14 | `T04A -> T04B` | check functions register into the T04A tri-state result pipeline | T04B | **RESTORED** |
| 15 | `T04A -> T04C` | same registration pipeline; T04C does NOT depend on T04B | T04C | **RESTORED (T04B was substituted)** |
| 16 | `T01D + T03C + T04A -> T05A` | the guided shell wires the real upload/confirm/submit HTTP contracts | T05A | RETAINED |
| 17 | `T04A -> T05A, T05B` | the UI renders states/reasons that exist only once persistence/API land | T05A, T05B | **RESTORED for T05B** |
| 18 | `T05A -> T05B` | the review grid builds on the shell routing/state | T05B | **RESTORED** |
| 19 | `T05B -> T05C` | comparison modes attach to the existing review panel | T05C | RETAINED |
| 20 | `T03B + T01B -> T06A` | single-panel isolation = create-before-supersede + exactly one job dispatch | T06A | RETAINED |
| 21 | `T05B + T06A -> T06B` | the regenerate UX needs the panel (T05B) and the backend isolation (T06A) | T06B | **RESTORED** |
| 22 | `T06A + T04B + T04C -> T07A` | the publish gate consumes the full extended registry + supersede-stable candidates | T07A | **RESTORED** |
| 23 | `T07A + T05B (+ T05C) -> T07B` | the confirm dialog lists candidates + provenance over the real review UI | T07B | RETAINED |
| 24 | `T04B + T04C -> T08A` | threshold bands come from the implemented check designs; freeze BEFORE run 0 | T08A | RETAINED — **no roster blocker** |
| 25 | `T08A -> C13-GOLDEN-TRUTH-SIGNOFF -> T08B` | EXPECTED_VERDICTS review is Codex-only; PM cannot self-sign | T08B | RETAINED |
| 26 | `T07B + T06B + T08A -> T08B` | run 1 uses the real review/publish UI; regeneration rate reads candidate history | T08B | **RESTORED (T07B + T06B)** |
| 27 | `frozen T03C + B13-PROVIDER-MEASURED-EVIDENCE -> T08C` | the external measured bundle must satisfy the REQUIRED-field contract before aggregation opens | T08C | **RESTORED (T08B was substituted)** |

P01 rows (from `docs/technology/mf_engine_v1/S13_P01_TASK_CONTRACTS.md`, not part of the 22):

| # | Edge | Justification | Consumed by |
|---|---|---|---|
| 28 | `T01A + T01C + T02A approved -> P01A` | the fit recommender reads the frozen profile/prompt/capability contracts | P01A |
| 29 | `P01A -> P01B` | the API exposes the recommender that P01A builds | P01B |
| 30 | `T03C + T05B (+ T07B) -> P01B` | read-only fit endpoints over the real generation/review surfaces; serialized after T07B | P01B |

## 2d. DAG <-> write-set mapping — 22 P00 tasks + P01A/P01B

Exclusive write paths are transcribed from `P00/WRITESET_MATRIX.md` §1 (D3, revision C5);
the wave column is `P00/DEPENDENCY_DAG.md` §3 (D2). This table is the mapping the delta was
asked for: exact task -> exact wave -> exact paths -> migration ownership.

| TaskID | Wave | Exclusive write paths (C5 D3) | Migration |
|---|---|---|---|
| T01A | W1 | NEW `migrations/versions/<live-head-child>_s13_t01a_identity_profile.py` · NEW `app/persistence/character_identity.py` · NEW `app/schemas/character_identity.py` · NEW `tests/test_character_identity_profile.py` · EXT `app/persistence/models.py` (register only) | 1 of 3 (`<live-head-child>_s13_t01a_identity_profile.py`) |
| T01B | W2 | NEW `migrations/versions/<live-head-child>_s13_t01b_slot_candidate.py` · NEW `app/persistence/character_candidates.py` · NEW `tests/test_character_candidates.py` · EXT `app/persistence/models.py` (register only) | 2 of 3 (`<live-head-child>_s13_t01b_slot_candidate.py`) |
| T01C | W2 | NEW `app/workflow/prompt_templates.py` · NEW `tests/test_prompt_templates.py` · NO migration | none |
| T01D | W2 | EXT `app/schemas/character_identity.py` · NEW `app/api/routes/character_identity.py` · EXT `app/api/app.py` (EXACTLY ONE include) · NEW `tests/test_character_identity_api.py` | none |
| T02A | W3 | NEW `app/services/generation/__init__.py` · NEW `app/services/generation/provider.py` · NEW `app/services/generation/resolver.py` · EXT `app/config.py` (MOTIONFORGE_COMFY_* envs) · NEW `tests/test_generation_provider_protocol.py` | none |
| T02B | W4 | NEW `app/services/generation/comfy_transport.py` (+ failure-code mapping) · NEW `tests/test_comfy_transport_fakes.py` (fake transports ONLY under tests/**) | none |
| T03A | W4 | NEW `app/workflow/job_handlers_generation.py` · EXT `app/workflow/job_handlers.py` (ONE import+register line) · NEW `tests/test_generation_job_single_slot.py` | none |
| T03B | W5 | NEW `app/services/generation/orchestration.py` · NEW `tests/test_generation_orchestration.py` | none |
| T03C | W6 | NEW `app/schemas/character_generation.py` · NEW `app/api/routes/character_generation.py` · EXT `app/api/app.py` (EXACTLY ONE include, strictly AFTER T01D's hunk) · NEW `tests/test_character_generation_api.py` | none |
| T04A | W3 | NEW `migrations/versions/f13a04a20268_s13_t04a_candidate_validation.py` (revision id discovered at activation) · EXT `app/persistence/models.py` · EXT `app/persistence/character_candidates.py` · NEW `app/persistence/character_validation_results.py` · NEW `app/schemas/character_validation.py` · EXT `app/api/routes/durable_characters.py` · NEW `tests/test_character_validation_migration.py` · NEW `tests/test_character_validation_repository.py` · NEW `tests/test_character_validation_api.py` | 3 of 3 (`f13a04a20268_s13_t04a_candidate_validation.py`) |
| T04B | W5 | NEW `app/workflow/character_checks_geometry.py` · NEW `tests/test_character_checks_geometry.py` | none |
| T04C | W5 | NEW `app/workflow/character_checks_identity.py` · NEW `tests/test_character_checks_identity.py` | none |
| T05A | W7 | EXT `frontend/src/app/(app)/characters/page.tsx` · NEW `frontend/src/app/(app)/characters/generation/**` (shell) · EXT `frontend/src/lib/api.ts` · NEW `frontend/e2e/s13-t05a-shell.spec.ts` | none |
| T05B | W8 | EXT the same two frontend files (candidate-aware six-tile grid, slot review panel, reasons list, history strip) · NEW `frontend/e2e/s13-t05b-review-grid.spec.ts` | none |
| T05C | W9 | NEW `frontend/src/app/(app)/characters/generation/compare/**` · EXT review-panel wiring · NEW `frontend/e2e/s13-t05c-compare.spec.ts` | none |
| T06A | W8 | NEW `app/services/generation/regenerate.py` · EXT `app/api/routes/durable_characters.py` (slot-scoped regenerate) · NEW `tests/test_regenerate_isolation.py` | none |
| T06B | W10 | EXT frontend regenerate action + history interactions · NEW `frontend/e2e/s13-t06-regenerate.spec.ts` | none |
| T07A | W9 | EXT `app/persistence/characters.py` (publish transaction + snapshot) · EXT `app/api/routes/durable_characters.py` (publish route guard) · NEW `tests/test_s13_publish_gate.py` | none |
| T07B | W11 | EXT `page.tsx` confirm-dialog region · NEW `frontend/e2e/s13-t07-publish.spec.ts` | none |
| T08A | W10 | NEW `scripts/benchmark/build_s13_golden.py` · NEW `scripts/benchmark/run_s13_validation_benchmark.py` · NEW `tests/fixtures/golden/**` · NEW `output/s13-t08-benchmark/{THRESHOLDS_FROZEN,DATASET_MANIFEST,EXPECTED_VERDICTS}.json` | none |
| T08B | post-W11 gated window | SINGLE namespace `output/s13-t08-benchmark/results/**` ONLY (raw Run0/Run1/Run2 JSON, blind-human logs, traces, FAR report) | none |
| T08C | post-W11 gated window | NEW `scripts/benchmark/validate_provider_evidence.py` · NEW `tests/test_s13_provider_evidence_contract.py` · NEW `output/s13-t08-benchmark/provider-evidence/normalized_metrics.json` · NEW `output/s13-t08-benchmark/PROVIDER_PERFORMANCE_REPORT.md` · READ-ONLY `output/s13-t08-benchmark/provider-evidence/raw/**` | none |
| P01A | independent CR work (advisory, zero writes) | NEW `app/services/generation/character_fit.py` · NEW `app/schemas/character_fit.py` · NEW `tests/test_character_fit.py` (three files; zero writes elsewhere) | none |
| P01B | serialized after T07B | NEW `app/api/routes/character_fit.py` · NEW `tests/test_character_fit_api.py` · NEW `frontend/src/app/(app)/characters/generation/fit/**` · NEW `frontend/e2e/s13-p01-fit.spec.ts` · EXT `app/api/app.py` (ONE include) · EXT `frontend/src/app/(app)/characters/page.tsx` · EXT `frontend/src/lib/api.ts` | none |

**Shared-file ownership (one writer per file per wave):**

- `app/persistence/models.py` — T01A, T01B, T04A (registration/schema-field hunks), each in
  its own wave, serialized;
- `migrations/versions/` — T01A -> T01B -> T04A only, one live head at a time;
- `app/api/app.py` — T01D (first include) then T03C (second include), nothing else;
- `app/persistence/characters.py` — T07A (publish tx / snapshot); no other S13 task edits it;
- `app/schemas/project_cast.py` — ONE compatibility evaluator with TWO branches (§5.5), owned
  by the P00 task that already owns the file; this contract adds no second evaluator;
- `frontend/src/app/(app)/characters/page.tsx` + `frontend/src/lib/api.ts` — T05A/T05B/T05C
  sequential in W7-W9, then T07B alone in W11 (GATE-rule B).

## 2e. `down_revision` discovery — measured, never remembered

C5 D3 G1: each migration-bearing task resolves `down_revision` from the **live single head**
at activation and ABORTS if multiple heads exist; a revision id is never hard-coded.

| Fact | Measured value (this round) |
|---|---|
| Discovery command | python: parse migrations/versions/*.py; head set = revision set minus all down_revision values (C5 D3 G1 rule) |
| Migration files / revisions | 21 / 21 |
| Head set | `d4e5f6a7b8c9` — exactly one |
| Missing parents | 0 |
| Root revision | `a1b2c3d4e5f6` |
| `branch_labels` | none declared — the chain is linear |

Raw: `raw/d14_migration_head.json`. T01A's migration therefore takes
`down_revision = "d4e5f6a7b8c9"` **or** whatever single head exists at its own dispatch time
if a later packet landed first.

## 3. Per-pack-type behaviour (required by the delta)

| Behaviour | `legacy_six_slot_2d` | `reference_pack_v1` (frozen by this round) |
|---|---|---|
| **Profile refusal** | Refuses only when the legacy gate fails: incomplete (`missing_slots` non-empty) or unpublished → `incomplete_pack` / `unpublished_pack`; a capability beyond a flat 2D six-pose pack → `missing_required_capability` | Refuses per capability: the pack declares its required views/references/roles; a capability with no satisfying declaration is refused with an explicit reason (`missing_required_pose` / `missing_required_capability`) — never silently skipped |
| **Orchestration** | Existing six-slot round (one job per slot, ordered, restartable); a failed slot does not silently re-run as a different route | Round shape follows the declared reference set; per-shot/per-panel granularity so one panel's regeneration never invalidates approved panels |
| **Validators** | The existing completeness/geometry validator (`PackVersionValidationData`), unchanged; six-slot completeness is authoritative for this type | Validator consumes the pack's declared requirement profile; legacy `CORE_POSE_SLOTS` is **not** required. Partial completeness per capability is representable |
| **Publish snapshot** | Immutable version + `published_at` + `validation_json` + assets per slot, unchanged | Immutable version + declared contract version + per-capability completeness record + references used. Snapshot records which capability the pack was accepted **for** |
| **UI behaviour** | Unchanged: six pose slots, per-slot preview via the server-produced content URL (`asset_content_url`), draft validation before publish | Renders the pack's **declared** requirements and, for each unsatisfied capability, the stated reason. No "missing pose" wording for a pack that never declared flat-2D slots |

## 4. Media-engine criteria added by this task (no old criterion superseded)

These are additions, not replacements — they exist because S13 has no equivalent today:

| # | New criterion | Affected P00 task | Scope | Acceptance |
|---|---|---|---|---|
| 21 | Capabilities distinct; source-locked route may not degrade to T2V/I2V | T02A, T03C | `app/schemas/media_engine.py` (NEW, pure) | refusal even **with** operator approval; proven by negative control N1 |
| 22 | Client paths and client graphs refused with typed codes | T01D, T03C | same module | `client_artifact_path_refused`, `client_graph_refused`; proven by N2 |
| 23 | Cache identity derived from frozen facts; reference change invalidates affected shots only | T06A | same module | 12-component mutation test; only affected entries invalidate; proven by N4 |
| 24 | Unresolved replay re-attaches or refuses — never a second POST | T03B | same module + E01 replay-safe window (§8 of the job contract) | `issues_post` is a constant `False`; proven by N3 |
| 25 | Result carries durable prompt id / server epoch / ownership; states are distinct | T03A, T03B, T04A | same module | `generated/validated/reviewed/accepted/published`; only `accepted` → `published` |
| 26 | Model registry: measured hardware profile; release date ≠ repo modification date; no UI-triggered download | T02A, T08C | same module | `auto_download_refused` for a UI origin; unmeasured `measured_live` claim rejected |
| 27 | One shared GPU lease for image, video and E01 jobs | T03A, T03B | view over E01 lease | second store/engine refused; one holder, no bypass |

## 5. Reference-pack storage plan — FROZEN, owned by T01A/T01B (docs only here)

**This task executes no migration** (which is why nothing under `migrations/**` is touched).
The decision Codex R7 asked for is now **made**, not deferred: the plan below is concrete and
belongs to **T01A (schema) → T01B (freeze/read) → T04A (validator branch)**.

### 5.1 Discovery, measured (raw: `raw/d06_migration_chain.json`)

| Fact | Measured value |
|---|---|
| Migration files / revisions | 21 / 21 |
| Single head | `d4e5f6a7b8c9` (`s12_retry_lineage`) |
| Root revision | `a1b2c3d4e5f6` |
| `down_revision` pointing at a non-existent revision | none |
| Duplicate revision ids | none |
| `branch_labels` declared | none — the chain is linear |
| Character-library migration | `d5e6f7a8b9c0_character_library_schema.py` |

Head discovery is a command, not a memory: parse `migrations/versions/*.py`, subtract every
`down_revision` from the set of `revision` values — what remains is the head set, and there must
be exactly one. The reference-pack migration MUST take `down_revision = "d4e5f6a7b8c9"`, or the
single head measured at its own dispatch time if a later packet landed first.

### 5.2 Affected schema, measured from `app/persistence/models.py`

| Table | Lines | Columns | FK | Constraints |
|---|---|---|---|---|
| `character_pack_version` (`CharacterPackVersion`) | 1017–1057 | `id`, `character_id`, `workspace_id`, `version`, `status`, `validation_json`, `published_at`, `revision` | `character.id`, `workspace.id` | `ck_pack_version_positive`, `ck_pack_version_status`, `ck_pack_version_revision_positive`, `uq_pack_version_character_version` |
| `character_asset` (`CharacterAsset`) | 1058–1086 | `id`, `pack_version_id`, `workspace_id`, `pose_slot`, `artifact_id` | `character_pack_version.id`, `workspace.id`, `artifact.id` | `ck_character_asset_pose_slot_nonempty`, `ck_character_asset_pose_slot_len`, `uq_character_asset_version_pose_slot` |

`artifact.id` is the EXISTING managed-artifact authority: reference assets are addressed by
artifact id + hash, never by a path, and never through a new table.

### 5.3 The additive change (T01A migration #1)

```
ALTER TABLE character_pack_version
  ADD COLUMN pack_contract_version      VARCHAR(32)   NOT NULL DEFAULT 'legacy_six_slot_2d',
  ADD COLUMN requirement_manifest_json  TEXT          NULL,
  ADD COLUMN requirement_manifest_sha256 VARCHAR(64)  NULL;
ALTER TABLE character_pack_version
  ADD CONSTRAINT ck_pack_version_contract_branch CHECK (
    pack_contract_version IN ('legacy_six_slot_2d','reference_pack_v1')),
  ADD CONSTRAINT ck_pack_version_manifest_binding CHECK (
    (pack_contract_version = 'legacy_six_slot_2d' AND requirement_manifest_json IS NULL)
    OR (pack_contract_version = 'reference_pack_v1'
        AND requirement_manifest_json  IS NOT NULL
        AND requirement_manifest_sha256 IS NOT NULL));
```

- **upgrade:** three `add_column` calls with the `server_default` above, then two
  `create_check_constraint` calls. Every pre-existing row becomes `legacy_six_slot_2d` with a
  NULL manifest, so **no legacy pack changes behaviour** — no data migration, no backfill loop.
- **downgrade:** two `drop_constraint` calls then three `drop_column` calls; the pre-image is
  exactly the schema in §5.2.
- **FK:** **no new FK is added.** A manifest is JSON, so the artifact ids it names cannot carry a
  database FK; instead each manifest entry must resolve to an `Artifact` row in the same
  workspace, which the capability-aware validator enforces. Reference PIXELS keep living in the
  existing `character_asset` rows — `pose_slot` carries a namespaced reference key (e.g.
  `front@character`) for `reference_pack_v1` and the six legacy slot names for
  `legacy_six_slot_2d`. **No second pack table, no second cast table, no second asset table.**
- **CHECK:** the two constraints above are the whole new invariant set;
  `ck_pack_version_status` and `uq_pack_version_character_version` stay untouched.
- **Serialization:** T01A → T01B → T04A, one live head at a time. T04A's validator branch only
  *reads* the column.

### 5.4 Publish snapshot at T07A

At publish, T07A's snapshot records `pack_contract_version` + `requirement_manifest_sha256`
alongside the existing immutable version / `published_at` / `validation_json` / per-slot assets,
so a published reference pack is provably the manifest that was reviewed. A `reference_pack_v1`
pack with no manifest is not publishable: the CHECK forbids the row at the schema level and the
validator refuses it at the API level.

### 5.5 One compatibility evaluator, two branches

`app/schemas/project_cast.py::CompatibilityEvaluate*` keeps its single implementation and its
`CompatibilityReason` vocabulary, and gains ONE branch point on the pack's declared
`pack_contract_version`:

- `legacy_six_slot_2d` → today's rules, `CORE_POSE_SLOTS` completeness included;
- `reference_pack_v1` → the pack's declared/manifest requirements, per capability.
  **`CORE_POSE_SLOTS` is never required of this branch**, and `incomplete_pack` is never emitted
  for a flat-2D pose the pack never declared.

A pack declaration (manifest) may only **select or add** requirements from the capability
profile; it may never lower a normative minimum — `CAPABILITY_REFERENCE_REQUIREMENTS` in the pure
module is that floor, and lowering a minimum to pass is the one thing the evaluator must refuse.

## 6. Hard rule — changes outside P00 paths need an explicit Codex-approved delta first

Any change to a path that is not part of the S13 P00 write-sets — specifically
`app/api/app.py`, `app/config.py`, `app/persistence/models.py`, `app/persistence/jobs.py`,
any migration, any UI/frontend file, `app/services/renderer_router.py`,
`app/services/renderer_routes/**`, `app/services/s10_*.py`, the S12 export package, or the
runtime/media/database state — **requires an explicit Codex-approved delta before it is
written**. This contract proposes; it does not authorize. A worker that finds a change like
that necessary must stop and return the request, not implement it.

## 7. Formal delta (round D) — changed requirements are CHANGED

The previous revision recorded items 2/3/17 as *clarifications* and left changed rows
reading `unchanged`. This is the formal delta the prompt requires: OLD criterion -> NEW
criterion, with the class of change, the affected TaskIDs, the exact symbol/path and the
acceptance that closes it. Classes: `RETAIN` (unchanged in substance), `REPLACE` (superseded
by a sharper rule), `CHANGE` (the graph or the gate itself moves), `ADD` (new authority).

| # | Old requirement (as previously written) | New requirement (formal) | Class | Affected TaskIDs | Exact symbol / path | Acceptance |
|---|---|---|---|---|---|---|
| D-1 | "The adapter must express capability as the four distinct values" — filed as a *clarification* of ROADMAP row 2 | Binding on T02A's fail-closed resolver: capability absence is always stated with a reason code, and a source-locked capability may never be served by a degraded target | `REPLACE` (sharper) | T02A, T03C | NEW `app/services/generation/resolver.py`, `app/services/generation/provider.py`; `app/schemas/media_engine.py::{MediaCapability, CapabilityOffer, CapabilitySet, FORBIDDEN_DEGRADATION_TARGETS, CAPABILITY_REFERENCE_REQUIREMENTS}` | 4-state probe (`UNCONFIGURED/UNREACHABLE/DEGRADED/READY`) + `tests/technology/test_media_engine_contract.py::test_every_capability_declares_a_normative_reference_requirement` |
| D-2 | "T03 — pose-conditioned six-panel generation job" as one RT — filed as a *clarification* | Scope split T03A/T03B/T03C with the exact C5 write-sets; six slots are the LEGACY output shape only — the engine never universalises six poses and a `reference_pack_v1` pack is never forced into them | `REPLACE` (scope split) | T03A, T03B, T03C | `app/workflow/job_handlers_generation.py` (T03A), `app/services/generation/orchestration.py` (T03B), `app/api/routes/character_generation.py` (T03C), `app/schemas/media_engine.py::{InflightReservation, reservation_identity_for, BackendIdentityProof, resolve_replay}` | `test_reservation_identity_is_epoch_bound_but_the_cache_is_not`; orchestration tests; 422 provider-payload test |
| D-3 | "One durable job store (E01) + one concurrency engine" — filed as a *clarification* | Structural and enforced: a second job store, a second concurrency engine or a second GPU lease table is REFUSED, not tolerated | `REPLACE` (made explicit) | T03A, T03B | `app/schemas/media_engine.py::{assert_shared_stack, GpuLeaseView, E01_JOB_STORE, SECOND_JOB_DATABASE_ALLOWED, COMPETING_CONCURRENCY_ENGINE_ALLOWED}` | `test_second_job_store_and_competing_engine_are_refused`, `test_one_shared_gpu_lease_serializes_image_and_video_jobs` |
| D-4 | The 24-row table omitted or substituted **eleven** DAG edges while §8 claimed "the C5 dependency DAG and its wave ordering stay the plan of record" | Every row now carries its exact incoming edge set (§2b `C5 depends-on` column) and §2c is the authoritative list: `T01A -> T01C`, `T01A -> T01D`, `T02A -> T03A`, `T03A -> T03B`, `T04A -> T04B`, `T04A -> T04C` (T04C had substituted T04B), `T05A -> T05B` + `T04A -> T05B`, `T05B -> T06B`, `T06A + T04B + T04C -> T07A`, `T07B + T06B -> T08B` | `CHANGE` (graph) | T01C, T01D, T03A, T03B, T04B, T04C, T05B, T06B, T07A, T08B | §2b `C5 depends-on` column + §2c | doc-integrity probe re-deriving every row's edge set from the C5 list (`raw/d16_nr06_doc_check.json`) |
| D-5 | T08C depended on T08B; T08A's row sat inside roster language | T08A preparation is UNCONDITIONAL and has **no** human-roster blocker (its completion ENABLES the Codex gate `C13-GOLDEN-TRUTH-SIGNOFF`, an outgoing edge); T08B carries `T07B + T06B + T08A + C13 + N>=3 real roster`; T08C carries `frozen T03C + B13-PROVIDER-MEASURED-EVIDENCE` | `REPLACE` (gate correction) | T08A, T08B, T08C | `output/s13-t08-benchmark/{THRESHOLDS_FROZEN,DATASET_MANIFEST,EXPECTED_VERDICTS}.json` (T08A), `output/s13-t08-benchmark/results/**` (T08B), `scripts/benchmark/validate_provider_evidence.py` (T08C) | missing roster => `BLOCKED_DEPENDENCY` for T08B only; missing external field => `BLOCKED_DEPENDENCY` for T08C only |
| D-6 | `app/services/generation/**` wildcard; several cells read `unchanged` | Exact paths and exact symbols everywhere: T02A is `app/services/generation/{__init__,provider,resolver}.py`; a row with no file change says so explicitly AND names what does change (the edge, or the symbol it reads) | `REPLACE` (precision) | all 24 rows | §2d write-set table (transcribed from C5 D3, no wildcards) | doc probe: no table cell equals `unchanged`; every row's path names >= 1 concrete path or symbol |
| D-7 | "Reference-pack persistence decision needed" (OPEN_PRODUCT_DECISIONS) | TAKEN (§5): ONE pack/version authority, two versioned branches `legacy_six_slot_2d` / `reference_pack_v1`, additive `pack_contract_version` + frozen requirement/reference manifest bound to the existing immutable version; `CORE_POSE_SLOTS` never required of the reference branch; ONE compatibility evaluator with two branches; T07A pins the approved manifest in the publish snapshot | `ADD` (adopted) | T01A, T01B, T04A, T05C, T07A | `character_pack_version.{pack_contract_version, requirement_manifest_json, requirement_manifest_sha256}`; `app/schemas/project_cast.py::{CompatibilityEvaluateRequest, CompatibilityEvaluateResponse}` + `CompatibilityReason` (`:105`); `app/persistence/characters.py` publish tx | §5 constraints + migration serialization `T01A -> T01B -> T04A` + `tests/test_s13_t01a_pack_contract.py`, `tests/test_s13_t01b_manifest_freeze.py`, `tests/test_s13_t04a_validation_branch.py` |
| D-8 | `down_revision` candidates named as fixed ids | Discover the LIVE single head at activation, abort on multiple heads, never hard-code (C5 G1); measured this round: 21 files / 21 revisions / single head `d4e5f6a7b8c9` / 0 missing parents | `ADD` (procedure) | T01A, T01B, T04A | `migrations/versions/**` | `raw/d14_migration_head.json`; activation preflight aborts on multiple heads |

No open questions remain: the four previous decision-record items are folded into D-1..D-8
above (D-1/D-2/D-3 are the former items 2/3/17 — now `REPLACE`, not "clarification"; the
former item 2's `reference_pack_v1` gate question is D-7; item 3's lease rule is D-3).

## 8. Retained sprint baseline (D07 — no silent reduction)

| Retained | Statement |
|---|---|
| 22-task P00 | the 22 active sub-task IDs (§2b) stay 22; `ADD` / `REPLACE` are clarifications, never removals |
| Waves W1–W11 | the C5 dependency DAG and its wave ordering stay the plan of record |
| 30-character golden cohort | 12 + 10 + 8 = 30 characters, unchanged |
| Human review | N ≥ 3 blind human reviewers for the T08B verdict |
| External benchmark | the external 30 six-panel benchmark, unchanged |
| Migration serialization | T01A → T01B → T04A, one live head at a time (§5.1) |
| UI scope | the UI shows only the requirement of the pack type the pack actually declares (§2b.2 T05C) |
| P01A / P01B | P01A advisory with **zero writes**; P01B **user-confirmed only**; confirmed selection survives 2 videos + a reopen (§2b.2) |
| Single authorities | one E01 durable store + one shared lease; one renderer route taxonomy; one compatibility evaluator (§5.5); no second provider evaluator; no duplicate job/GPU lease |
| DAG edges | all C5 edges are restored verbatim (§2c); no row may omit or substitute an incoming edge, and the wave plan (W1-W11) stays the plan of record |
| Roster scope | the real N>=3 blind-human roster gates **T08B only**; T08A preparation carries no human-roster blocker |
| Formal delta | a requirement that changed is stated as CHANGED with its old symbol and new path (§7); "clarification" is no longer used for a behaviour change |
| Exact paths | no wildcard and no bare `unchanged` cell survives; every row names its exact path/symbol or states explicitly why no file changes |

**No silent reduction.** Nothing here withdraws a criterion: a requirement that changed is stated
as *changed* (with the old symbol and the new path), never re-labelled as a "clarification with no
file change".
