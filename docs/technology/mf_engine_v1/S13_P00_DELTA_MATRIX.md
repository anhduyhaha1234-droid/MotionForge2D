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

## 3. Per-pack-type behaviour (required by the delta)

| Behaviour | `legacy_six_slot_2d` | `reference_pack_v1` (proposed) |
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

## 5. Migration scope

**This task adds no migration.** The only migration-adjacent item is
`pack_contract_version` for `reference_pack_v1` (`PACK_CAPABILITY_CONTRACT.md` §6.1), which is
**DEFER**red: it is a T01A/T01B-adjacent schema change and must arrive as its own packet with
its own single-head preflight (`alembic heads` → exactly one live head whose chain already
contains the predecessor migration) — the same discipline `T04A` already carries.

Existing migration chain untouched: `T01A → T01B → T04A` remains the plan of record.

## 6. Hard rule — changes outside P00 paths need an explicit Codex-approved delta first

Any change to a path that is not part of the S13 P00 write-sets — specifically
`app/api/app.py`, `app/config.py`, `app/persistence/models.py`, `app/persistence/jobs.py`,
any migration, any UI/frontend file, `app/services/renderer_router.py`,
`app/services/renderer_routes/**`, `app/services/s10_*.py`, the S12 export package, or the
runtime/media/database state — **requires an explicit Codex-approved delta before it is
written**. This contract proposes; it does not authorize. A worker that finds a change like
that necessary must stop and return the request, not implement it.

## 7. Open questions this proposal puts to Codex

1. Should items 2, 3 and 17 above be recorded as formal `REPLACE` amendments to the C5 task
   map, or as clarifications that leave the 22 IDs and the W1–W11 baseline intact? This
   contract prefers **clarifications** — the 22 active IDs and the wave baseline stay
   unchanged, as C4/C5 already require.
2. Does `reference_pack_v1` need its own gate row in `ACCEPTANCE_GATES.md` before T01A
   activation, or is it sufficient that it is a proposal until an approved packet adopts it?
3. `GpuLeaseView` shares E01's lease; confirm that no S13 task may add a second lease table
   even for the provider (the contract says refuse — `competing_concurrency_engine_refused`).
