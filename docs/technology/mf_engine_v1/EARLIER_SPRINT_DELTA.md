# EARLIER_SPRINT_DELTA — reuse / change / retain against the existing engine

**Task:** MF-TOOL-CONTRACT · **Status:** PROPOSAL (awaiting `C-CONTRACT` Codex review)
**Rule of this document:** for every existing entrypoint the generator alpha (S13) will need,
state whether it is **reused as-is**, **changed** (with the exact file scope), or **retained
untouched** — and name what does *not* change now.

**Scope boundary that governs everything below.** The live engine routing of S09/S10
(`app/services/renderer_router.py` + `app/services/renderer_routes/**` +
`app/services/s10_*.py` + `app/persistence/models.py::RENDERER_ROUTES`) is **retained
untouched by this task**. Rewiring the live render path is a *later, exact integration
packet* with its own write-set and its own Codex review — it is **not** an authorized
production rewrite now, and this contract does not grant one. Nothing in this document is a
licence to edit a live pipeline file. The machine-checkable half of the contract
(`app/schemas/media_engine.py`) is deliberately pure: no DB, no queue, no route, no worker.

---

## 1. Source facts (import, probe, timebase, source lock)

| Entrypoint | Path | Decision |
|---|---|---|
| Video import / managed artifact intake | `app/services/video_import.py`, `app/workflow/ingest_service.py` | **REUSE as-is** |
| Container/stream probe | `app/services/video_probe.py` | **REUSE as-is** |
| Canonical timebase + PTS normalisation | `app/services/timebase.py` | **REUSE as-is** — the sole authority for `fps_num/fps_den`, `first_pts`, frame indexing |
| Proxy generation | `app/services/video_proxy.py` | **REUSE as-is** |
| Source-locked timeline / source timing | `app/services/source_locked_timeline.py`, `app/services/structural_lock_source_timing.py` | **REUSE as-is** |
| Contracts | `docs/architecture/CANONICAL_TIMEBASE_PROXY_CONTRACT.md`, `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md`, `docs/architecture/MANAGED_ARTIFACT_CONTRACT.md` | **RETAIN** — the media-engine `SourceLock` mirrors them rather than redefining them |

**Delta.** The media engine adds `SourceLock` (`source_artifact_id`, `source_sha256`,
inclusive `ShotRange` in the clip's own index space, `pts_start_ticks`/`pts_end_ticks`,
rational fps) as the *request-level* way to name a source. It **adds no new probe or
timebase implementation**: the integers it carries are the ones `app/services/timebase.py`
already produces. This is the part of the contract that must be reconciled first at
integration time, because the BENCH/VIDEO14B rounds measured PTS semantics on exactly these
fields (`first_pts`/`last_pts`/`1/15360` timebase).

## 2. Library and cast (characters, packs, project cast)

| Entrypoint | Path | Decision |
|---|---|---|
| Character library domain + pack versions | `app/persistence/characters.py`, `app/persistence/models.py` (`CORE_POSE_SLOTS`, `PackVersion`, `Asset`) | **REUSE as-is** |
| Character / pack schemas | `app/schemas/characters.py` (`PackVersionData`, `PackVersionValidationData`, `PublishVersionRequest`, `SetDefaultVersionRequest`) | **REUSE as-is** |
| Character routes | `app/api/routes/durable_characters.py` | **RETAIN untouched** |
| Project cast mapping + CAS | `app/persistence/project_cast.py`, `app/schemas/project_cast.py` (`ProjectCastCreateRequest`, `ProjectCastUpdateRequest` with `revision` CAS + `idempotency_key`, `ProjectCastData`) | **REUSE as-is** — the engine's `CastBinding` is a *request projection* of an existing cast pin, not a second table |
| Compatibility evaluation | `app/schemas/project_cast.py` (`CompatibilityReason`, `CompatibilityEvaluate*`), `app/api/routes/project_cast.py` | **REUSE as-is** — S13 P01 must consume this, not replace it |
| Character validation | `app/workflow/character_validator.py` | **REUSE as-is** |
| Preset import / library fallback | `app/workflow/character_preset_importer.py`, `app/services/preset_manager.py`, `app/workflow/preset_layout_manifest.py` | **REUSE as-is** — this is the manual-library fallback that must keep working when generation fails |

**Delta.** `CastBinding(role, character_id, pack_version_id, references[], style_version)`
gives the engine a frozen, per-request view of a cast pin: the `pack_version_id` is the
immutable version, never a mutable character pointer. `character_id` + `pack_version_id` must
be consistent (same rule `app/persistence/project_cast.py` already enforces). **No second
cast table, no second pack table, no migration** — see `PACK_CAPABILITY_CONTRACT.md` §3.
`style_version` is carried per role because a style is bound to a role's reference set; the
engine never invents a workspace-wide style.

## 3. Render, apply, jobs

| Entrypoint | Path | Decision |
|---|---|---|
| E01 durable job repository (leases, idempotency keys, attempts, retry/cancel races) | `app/persistence/jobs.py`, `docs/architecture/DURABLE_JOB_CONTRACT.md` (V1.1) | **REUSE as-is — single authority** |
| Durable worker | `app/workflow/durable_worker.py` | **REUSE as-is** |
| Job service / reconciler | `app/workflow/job_service.py`, `app/workflow/job_reconciler.py`, `docs/architecture/JOB_RECONCILIATION.md` | **REUSE as-is** |
| Job API | `app/api/routes/jobs.py`, `docs/architecture/DURABLE_JOB_API_CUTOVER.md` | **RETAIN untouched** |
| Renderer contract + router (S09) | `app/services/renderer_contract.py`, `app/services/renderer_router.py` | **RETAIN untouched by this task** — integration is a later exact packet |
| Renderer routes (S09) | `app/services/renderer_routes/{adaptive_pose_swap,composite,benchmark_results}.py` | **RETAIN untouched** |
| Route taxonomy | `app/persistence/models.py::RENDERER_ROUTES` (5 routes: `pose_swap`, `sprite_affine`, `mesh_warp`, `part_rig`, `controlled_redraw`) | **RETAIN untouched — single authority, never copied** |
| Render service | `app/services/render.py` | **RETAIN untouched** |
| S10 apply / chunk / recompute | `app/services/s10_chunk_plan.py`, `s10_full_apply.py`, `s10_multi_role_apply.py`, `s10_recompute.py`, `s10_structural_compare.py`, `app/workflow/s10_full_apply_jobs.py` | **RETAIN untouched** |

**Delta.** The media engine defines a request/result envelope and a **replay rule** that run
*on top of* E01, not beside it: the `InflightReservation` (with
`outstanding/inflight/acked/ambiguous`) is the durable record written before an upstream
POST, and `resolve_replay` is the only way an unresolved replay is settled. The contract
explicitly forbids a second job database or a competing concurrency engine
(`assert_shared_stack`), and its GPU lease is a **view** over E01's lease. `ResourceBudget`
maps onto E01's existing `resource_class` vocabulary
(`cpu_light`, `cpu_heavy`, `gpu`, `io`).

## 4. QC and audio

| Entrypoint | Path | Decision |
|---|---|---|
| QC checks suite | `app/services/qc_checks/**` (orchestrator, registry, runner, thresholds, 13 checks) | **REUSE as-is** |
| QC A/V recheck | `app/services/qc_av_recheck.py` | **REUSE as-is** |
| QC correction bridge / navigation | `app/services/qc_correction_bridge.py`, `app/services/qc_navigation.py` | **RETAIN untouched** |
| QC API | `app/api/routes/qc_check_runs.py`, `qc_items.py`, `qc_navigation.py` | **RETAIN untouched** |
| Original-audio remux | `app/services/original_audio_remux.py`, `app/workflow/original_audio_handler.py`, `docs/architecture/ORIGINAL_AUDIO_REMUX_CONTRACT.md` | **REUSE as-is** |
| Audio dubbing | `app/workflow/audio_dubbing_service.py` | **RETAIN untouched** |

**Delta.** `AudioHandoff` makes the audio decision *typed at the contract level*
(`source_remux` | `generated` | `silent`), with `source_artifact_id` mandatory for remux —
so a generated clip can never silently lose or silently fake the original audio. The
implementation it calls is the existing remux service; the contract only refuses to leave
audio implicit. QC stays authoritative: `MediaEngineState.validated/reviewed/accepted` are
contract states that a later integration must project onto the existing QC/approval records,
not a replacement for them.

## 5. Export and publication

| Entrypoint | Path | Decision |
|---|---|---|
| S12 export package | `app/services/s12_export/{authority,capabilities,chunks,preflight,profiles,publication,publication_lease_guard,runner,stitch,validation}.py` | **REUSE as-is** |
| Publication fail-closed core | `app/services/s12_export/publication.py` (receipts, intent files, `_PublicationGuard`, `PublicationRaceLost`) | **REUSE as-is — the publication authority** |
| Export jobs / routes | `app/workflow/s12_export_jobs.py`, `app/api/routes/s12_export.py`, `app/api/routes/s12_export_preflight.py` | **RETAIN untouched** |
| Contract | `docs/contracts/s12-export.md` | **RETAIN** |
| Approval audit | `app/services/s09_approval.py` (`S09ApprovalIntegrityError`, `ApprovalConflictError`, `ApprovalBlockedError`) | **REUSE as-is** |

**Delta.** The media engine's publication gate (`assert_publishable_set`) is an
*artifact-level* pre-check that narrows what may be published and refuses an empty publish
set. It does **not** reimplement receipts, intent files or the publication lease — the S12
authority keeps that. Only `accepted` may project to `published`, mirroring the existing
"publish only after review/approval" rule and the fail-closed publication requirement.

## 6. Generator (S13 greenfield)

**Measured finding:** there is **no generator module today** — `app/services/` contains no
`generation`, `comfy` or diffusion module, and no route exposes one
(`ls app/services` / `grep -rl comfy app/` return nothing). S13's generator is greenfield;
the reuse surface is E01 (jobs/leases) plus the renderer contract's failure vocabulary.

| Artefact | Status |
|---|---|
| Provider/protocol layer (S13-T02A), transport containment (T02B) | **NEW** — later packet, not this task |
| Durable generation jobs (S13-T03A/B), generation HTTP surface (T03C) | **NEW** — later packet |
| Validation + review + regenerate + publish (T04x/T06x/T07x) | **NEW** — later packet |
| Golden dataset / benchmark (T08A/B/C) | **NEW** — later packet, Codex-signed truth |
| Provider choice by the client | **FORBIDDEN** — the client must not be able to name a provider (T03C acceptance: a payload carrying `provider` → 422) |

**Delta.** The generator inherits, by contract: distinct capabilities with no silent
degradation (§2), typed refusal codes instead of generic errors, pins that make a render
reproducible (workflow/model/node/config/seed), a cache identity that is derived not
supplied, a replay rule that cannot double-POST, a registry with measured hardware profiles
and no UI-triggered download, and one shared GPU lease.

---

## 7. What this task changes on disk

**Only additions.** Files created by MF-TOOL-CONTRACT:

- `app/schemas/media_engine.py` (NEW)
- `tests/technology/test_media_engine_contract.py` (NEW)
- `docs/technology/mf_engine_v1/**` (NEW: this file, `MEDIA_ENGINE_CONTRACT.md`,
  `PACK_CAPABILITY_CONTRACT.md`, `S13_P00_DELTA_MATRIX.md`, `S13_P01_TASK_CONTRACTS.md`)
- `docs/pm/sessions/MF-TOOL-CONTRACT/**` (NEW: session LOG/REPORT)

**No existing file is modified.** Specifically untouched: `app/api/app.py`,
`app/config.py`, `app/persistence/models.py`, `app/persistence/jobs.py`, every migration,
every UI/frontend file, `app/services/renderer_router.py`, `app/services/renderer_routes/**`,
`app/services/s10_*.py`, and the S12 export package. Any change to those requires a new
Codex-approved delta *before* writing (see `S13_P00_DELTA_MATRIX.md` §6).

## 8. Integration checkpoint (owner: a later packet)

Before any S13 production task activates, one exact integration packet must reconcile:

1. `SourceLock` ↔ `app/services/timebase.py` output fields (PTS/timebase identity).
2. `CastBinding` ↔ `app/persistence/project_cast.py` CAS + compatibility reasons.
3. `InflightReservation`/`resolve_replay` ↔ E01's existing idempotency-key and replay-safe
   window semantics (`DURABLE_JOB_CONTRACT.md` §8).
4. `AudioHandoff` ↔ `app/services/original_audio_remux.py`.
5. `assert_publishable_set` ↔ `app/services/s12_export/publication.py` receipts.
6. The single `app/api/app.py` router include the S13 HTTP tasks (T01D/T03C) will need —
   one hunk per task, serialized, never bundled.
