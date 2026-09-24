# S13_P00_DELTA_MATRIX — old criterion → disposition → affected task → scope

**Task:** MF-TOOL-CONTRACT · **Status:** PROPOSAL (awaiting `C-CONTRACT` Codex review)
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

### 2b.1 T01–T04 (12 IDs)

| # | TaskID | Disposition | Reason | Old symbol / hunk (authority) | New / changed path | Migration owner | Dependency | Tests (planned, later packet) |
|---|---|---|---|---|---|---|---|---|
| 1 | T01A | `RETAIN` + `ADD` | character/profile binding is unchanged; the reference-pack contract is ONE additive column + a frozen manifest on the existing immutable version | `app/persistence/models.py::CharacterPackVersion` (`character_pack_version`; `ck_pack_version_status`, `uq_pack_version_character_version`), `app/persistence/characters.py::CORE_POSE_SLOTS` use at `:569`/`:746` | `character_pack_version.pack_contract_version` + `requirement_manifest_json` + `requirement_manifest_sha256` (migration #1 — §5) | **T01A** (migration 1 of 3) | — | `tests/test_s13_t01a_pack_contract.py` — legacy rows read `legacy_six_slot_2d`, reference rows carry a manifest; completeness unchanged for legacy |
| 2 | T01B | `RETAIN` + `ADD` | immutable pack versions + CAS on publish/repin stay the authority; the manifest is FROZEN at publish, never re-derived | `app/persistence/project_cast.py` (pack must be published+complete), `app/schemas/characters.py::PublishVersionRequest`/`SetDefaultVersionRequest` | `app/persistence/characters.py` publish path writes the manifest hash once; no second table | **T01B** (migration 2 of 3) | T01A | `tests/test_s13_t01b_manifest_freeze.py` — a published version's manifest hash never changes; repin is CAS-only |
| 3 | T01C | `RETAIN` | prompt registry/version/hash semantics are untouched by this contract | C5 prompt-registry entries; `reference_code` prompt contract | unchanged | — | — | C5's own T01C tests (not restated here) |
| 4 | T01D | `RETAIN` | the single `app/api/app.py` router include discipline is unchanged (one hunk per task, serialized) | `app/api/app.py` (one include) | unchanged | — | T01A/T01B approved | C5's T01D tests (one-include diff assertion) |
| 5 | T02A | `REPLACE` (sharper) | capability must be the four distinct `MediaCapability` values with explicit absence; the probe is fail-closed | `app/services/renderer_contract.py::CapabilityDescriptor`, `RendererContractCode`; `app/persistence/models.py::RENDERER_ROUTES` | `app/services/generation/**` (NEW, later packet) consuming `app/schemas/media_engine.py::MediaCapability` | — | T01B + T01C | `tests/test_s13_t02a_capability_probe.py` — 4-state probe truthfully reported; no fallback |
| 6 | T02B | `RETAIN` | transport containment/failure/security scope is unchanged; it inherits the typed refusal vocabulary | C5 T02B transport surface | unchanged | — | T02A | C5's T02B tests |
| 7 | T03A | `RETAIN` + `ADD` | one durable job per slot still goes through E01; the contract adds the durable `InflightReservation` identity (epoch/workspace/output contract) | `app/persistence/jobs.py` (leases, idempotency keys, attempts) | `app/schemas/media_engine.py::InflightReservation`, `reservation_identity_for` (pure, this task) | — (E01 owns schema; no migration here) | E01 infra | `tests/technology/test_media_engine_contract.py` — reservation identity is epoch-bound (`test_reservation_identity_is_epoch_bound_but_the_cache_is_not`) |
| 8 | T03B | `REPLACE` (made explicit) | six-slot orchestration is a legacy *output shape*; the replay rule is now settled against a backend identity proof, ownership first | `resolve_replay` (this task) + E01 replay-safe window (`docs/architecture/DURABLE_JOB_CONTRACT.md` §8) | `app/schemas/media_engine.py::BackendIdentityProof`, `resolve_replay(proof=...)` | — | T02A + E01 | `test_replay_owner_is_proven_before_the_acked_reattach`, `test_unresolved_replay_never_duplicates_the_post` (18 cases) |
| 9 | T03C | `RETAIN` + `ADD` | the client still cannot name a provider (422); the request carries the capability-aware reference requirement | C5 T03C HTTP surface; `app/schemas/media_engine.py::MediaEngineRequest` | `CAPABILITY_REFERENCE_REQUIREMENTS` enforcement at request construction (this task) | — | T01D+T02A+T03B+T04A | `test_source_motion_requires_reference_pixels`, `test_controlled_edit_is_not_forced_to_carry_character_references` |
| 10 | T04A | `RETAIN` + `ADD` | validation persistence/API unchanged; results must still project onto the five distinct states | `app/schemas/characters.py::PackVersionValidationData`, `app/services/s09_approval.py` | validation must ALSO read the pack's declared contract branch (§5) | — | T01B approved (candidate FK mandatory) | `tests/test_s13_t04a_validation_branch.py` — legacy validator unchanged; reference branch reads the manifest |
| 11 | T04B | `RETAIN` | geometry validation is unchanged; it is not the place a pack's contract branch is decided | C5 T04B geometry checks | unchanged | — | — | C5's T04B tests |
| 12 | T04C | `RETAIN` (+capability-aware) | identity/style/cross-view validation stays; it must consult the capability's requirement profile instead of a universal slot list | C5 T04C validators | requirement profile from `CAPABILITY_REFERENCE_REQUIREMENTS` (this task, pure) | — | T04B | `test_every_capability_declares_a_normative_reference_requirement` |



### 2b.2 T05–T08 (10 IDs) + P01A/P01B — 22 + 2

| # | TaskID | Disposition | Reason | Old symbol / hunk (authority) | New / changed path | Migration owner | Dependency | Tests (planned, later packet) |
|---|---|---|---|---|---|---|---|---|
| 13 | T05A | `RETAIN` | guided upload→profile→generate flow unchanged; the manual-library fallback keeps working when generation fails | `app/workflow/character_preset_importer.py`, `app/services/preset_manager.py` | unchanged | — | T01D+T03C+T04A | C5's T05A tests + the fallback epic-exit test |
| 14 | T05B | `RETAIN` | review UI unchanged in P00 | C5 T05B surface | unchanged | — | T03C | C5's T05B tests |
| 15 | T05C | `RETAIN` (+capability-aware) | the UI must render capability ABSENCE with a stated reason and must show **only the requirement of the pack type the pack actually declares** — never "missing pose" for a pack that never declared flat-2D slots | C5 T05C UI; `asset_content_url` per-slot preview | copy/render rules read `pack_contract_version` (later packet) | — | T05A/T05B | UI test: a `reference_pack_v1` pack renders its declared requirements, no six-slot wording |
| 16 | T06A | `RETAIN` + `ADD` | backend isolation of a single-panel regenerate is unchanged; the contract supplies the cache identity + the epoch distinction | `invalidate_for_reference_change`, `cache_identity_for` (this task) | `settings_digest` gains the source stream time_base; the epoch stays OUT of the cache (this task) | — | T03B + T01B | `test_every_cache_identity_component_changes_the_digest` (12 controls), `test_cache_distinguishes_capability_and_stream_timebase_but_not_the_epoch` |
| 17 | T06B | `RETAIN` | regenerate-one UI/E2E unchanged | C5 T06B E2E | unchanged | — | T06A | C5's T06B E2E |
| 18 | T07A | `RETAIN` + `REPLACE` (fail-closed, sharper) | publish backend/snapshot/audit unchanged; the publication gate now takes the SERVER's node-output classification as the authority and refuses an EMPTY allow-list | `app/services/s12_export/publication.py`, `publication_lease_guard.py`; `assert_publishable_set` (this task) | publish snapshot records `pack_contract_version` + `requirement_manifest_sha256` at **T07A**; artifact gate refuses `temp`/`input`/`intermediate`/`preview` and an empty allow-list | — (snapshot field is T07A's own write-set) | T05B + T06A | `test_empty_publish_allowlist_refuses`, `test_non_output_server_classifications_refuse_publication` |
| 19 | T07B | `RETAIN` | confirm-publish UI/E2E unchanged; it inherits the empty-allow-list refusal | C5 T07B E2E | unchanged | — | T07A | C5's T07B E2E |
| 20 | T08A | `DEFER` | Scenario J benchmark truth stays Codex-signed; thresholds frozen BEFORE run 0; no engine constant may be tuned to make a benchmark pass | C5 T08A; `THRESHOLDS_FROZEN.json` | unchanged | — | T04B+T04C | `THRESHOLDS_FROZEN.json` hash recorded before run 0 |
| 21 | T08B | `DEFER` | blind-human roster is an external act | C5 T08B; `C13-GOLDEN-TRUTH-SIGNOFF` (FROZEN F-12) | unchanged | — | T08A + N≥3 human roster | signed roster before the verdict table is read |
| 22 | T08C | `DEFER` | benchmark reporting artefacts are a later packet; the registry rows it reads are this contract's (§7 rows 24–26) | C5 T08C; `ModelRegistryEntry.release_date` vs `repo_modified_date` | unchanged | — | T08B | `test_release_date_and_repo_modification_date_are_different_facts`, `test_no_automatic_download_from_a_ui_click` |
| P01A | P01A | `RETAIN` — advisory, **zero writes** | the fit recommender is contracted, never implemented here; hard gates precede any AI score, and a run creates no cast row, no pack version, no publication | `S13_P01_TASK_CONTRACTS.md` §1 (`app/services/generation/character_fit.py`, `app/schemas/character_fit.py`, `tests/test_character_fit.py` — all NEW, later packet) | unchanged by this contract | — | T01A+T01C+T02A approved | advisory run with `git status` showing only the three allowlisted files |
| P01B | P01B | `RETAIN` — **user-confirmed only** | browsing/fit endpoints are read-only; persistence goes through the existing project-cast CAS APIs after explicit human confirmation; the confirmed choice survives 2 videos + a reopen | `S13_P01_TASK_CONTRACTS.md` §2 (`app/api/routes/character_fit.py`, `tests/test_character_fit_api.py`, `frontend/src/app/(app)/characters/generation/fit/**`, `frontend/e2e/s13-p01-fit.spec.ts` — NEW; `app/api/app.py` one include hunk) | unchanged by this contract | — | P01A+T03C+T05B, serialized after T07B | stale revision refuses; missing evidence refuses; 2-video/reopen persistence E2E |

**Count: 22 P00 IDs (12 above + 10 here) + P01A + P01B = 22 + 2 = 24 rows.**

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

## 7. Decision record (this round — no open questions left)

1. Items 2, 3 and 17 are recorded as **clarifications**: the 22 active IDs and the W1–W11
   baseline are unchanged (§2b, §8).
2. `reference_pack_v1` needs **no new gate row in `ACCEPTANCE_GATES.md`**: it is adopted by an
   approved packet, and §5 is its concrete storage plan.
3. `GpuLeaseView` keeps sharing E01's lease: **no S13 task may add a second lease table**, even
   for the provider (`competing_concurrency_engine_refused`).
4. The reference-pack persistence decision is **TAKEN** (§5): an additive
   `pack_contract_version` column plus a frozen requirement/reference manifest bound to the
   existing immutable pack version — one existing pack/version authority, two versioned branches,
   no second pack table, no second cast table. Only its *implementation* is a later packet.

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

**No silent reduction.** Nothing here withdraws a criterion: a requirement that changed is stated
as *changed* (with the old symbol and the new path), never re-labelled as a "clarification with no
file change".
