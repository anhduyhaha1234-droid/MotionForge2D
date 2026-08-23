# S08-A02-T02 — Extraction Evidence and Artifact Wiring

Normative task packet for MotionForge2D mini-sprint S08-A02, task T02.  Builds on the
A02-T01 structural-evidence contract (approved per user-provided Codex verdict).  Each
requirement below cites its authority file:line.

## 0. Authority map (file:line provenance)

| Requirement | Authority |
|---|---|
| T02 exists as the consumer of the T01 durable contract | `docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md:25` (outcome: "contract ... that S08-A02-T02 will use as its single durable truth"); `:11` (mini-sprint, T01 then T02) |
| Overall T02 outcome / scope / out-of-scope | `output/s08-a02-t01-r1-c1/ro2-t02-planning.md` (221-line READ-ONLY plan) + `output/overnight-planning/S08-A02-T02-DRAFT.md` |
| Extraction output → segment mapping contract | RO-2 §1 (`ro2-t02-planning.md:25-47`) |
| Prompt / mask artifact lifecycle | RO-2 §2 (`:49-58`), §3 (`:60-67`) |
| Point/track/flow evidence references | RO-2 §4 (`:69-76`) |
| Camera-relative transform ingestion | RO-2 §5 (`:78-85`) |
| Object-relative motion | RO-2 §6 (`:87-94`) |
| Contact / occlusion / visibility ingestion | RO-2 §7 (`:96-105`) |
| Generation ownership (authority = repository, never max+1 / client) | RO-2 §8 (`:107-115`); `app/persistence/structural_evidence.py:586-592`; `app/persistence/object_intelligence.py:301-358` |
| Deterministic QA adapters (CI w/o GPU) | RO-2 §9 (`:117-129`); `app/services/object_extraction.py:175,857,876` |
| Production fail-closed behavior | RO-2 §10 (`:131-141`); `app/services/object_extraction.py:1514,1617,1736,2177,2277,2385,2424` |
| Correction / recompute boundary (T02 vs T05) | RO-2 §11 (`:142-151`) |
| File overlap map / exact allowlist | RO-2 §12 (`:153-169`); DRAFT §3 (`S08-A02-T02-DRAFT.md:41-52`) |
| Binary acceptance criteria (10 items) | RO-2 §13 (`:171-182`); DRAFT §6 (`:74-85`) |
| Required tests | RO-2 §14 (`:184-203`); DRAFT §7 (`:87-92`) |
| Migration policy | RO-2 §15 (`:205-214`); DRAFT §8 (`:94-103`) |

## 1. Mandatory model configuration (BLOCKED_MODEL on mismatch)

- Provider: `muse` (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses).
- Model: `ocg/muse-spark-1.2-contributor` (verified on 9Router; meta/... returns 401 — do NOT use).
- Reasoning: `max` (config reasoning_overrides = {ocg/muse-spark-1.2-contributor: max}; agent.reasoning_effort max).
- No fallback.  Mismatch/reject → STOP REPORT.md = BLOCKED_MODEL_ROUTE with exact error.
- Record actual Hermes session ID, model, provider, reasoning, fallback in LOG.md + REPORT.md BEFORE any code change.

## 2. Worktree guard

- ONLY worktree: `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`; branch `codex/s08-integration`;
  HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`.
- MAIN `C:\Users\Admin\MotionForge2D` protected — never modify.
- Intentional dirty.  Never reset/clean/stash/restore/checkout/commit/push/merge.
- `MOTIONFORGE_DATABASE_URL` UNSET; tests only fresh isolated SQLite under C:/Users/Admin/AppData/Local/Temp/,
  `-p no:cacheprovider`, shallow unique `--basetemp`.  Never data/motionforge.db or user DB.

## 3. Outcome

Wire real `DISCOVER_OBJECTS` extraction output into the structural-evidence contract:
produce `OccurrenceSegment` / `SegmentMotion` / `SceneGraphOcclusion` / `SceneGraphContact` rows in the
same publication transaction that already creates roles/occurrences/artifacts, and extend the
deterministic QA adapter to emit motion/occlusion/contact evidence so CI exercises the full graph
without a GPU.  (DRAFT §1; RO-2 §0/§16.)

## 4. Required reading (read FULLY before editing)

- RO-2 plan (full): `output/s08-a02-t01-r1-c1/ro2-t02-planning.md`
- DRAFT: `output/overnight-planning/S08-A02-T02-DRAFT.md`
- `docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md` (T01 contract)
- `app/persistence/structural_evidence.py` (FULL) — repository T02 consumes
- `app/services/object_extraction.py` (FULL, ~2622 lines) — handler being wired
- `app/schemas/object_extraction.py`, `app/api/routes/object_extraction.py`
- `app/persistence/object_intelligence.py` (read-only authority for generation)
- Existing extraction tests + A02 structural-evidence tests

## 5. Scope

### 5.1 IN (this task)
- **Segment mapping** (§1): every extraction candidate → ONE `OccurrenceSegment` per (role, scene);
  scene-scoped frame/time range; `source_generation` = job manifest generation; `source_job_id` =
  DISCOVER_OBJECTS job; `mask_artifact_id` = published mask; deterministic `uuid5` logical_id + record id;
  idempotency_key; canonical prompt/segmentation JSON; provenance/confidence.  Publication INSIDE
  `_publish_effect` (object_extraction.py:1857) transaction with roles/occurrences/artifacts.
- **Mask lifecycle** (§2): stage→publish ready; segment.mask_artifact_id = published mask;
  ObjectRoleArtifact association (purpose mask) same transaction; sha256 verified; fail-closed.
- **Motion ingestion** (§5/§6): camera-relative AND object-relative rows; `point_track_flow_ref` is a
  REFERENCE (no dense-flow engine); production emits `confidence_source="derived"` + reason when no real
  estimator (NEVER `confidence=1.0/model` false evidence).
- **Scene-graph edges** (§7): occlusion + contact, both current-generation same video, range within
  endpoints; deterministic QA adapter emits ≥1 occlusion + ≥1 contact per scene.
- **Deterministic QA adapters** (§9): extend to emit edges/motions; only when
  `MOTIONFORGE_EXTRACTION_PROVIDER=deterministic` + QA mode; production never falls back.
- **Read API** (§12): `GET /{job_id}`, `GET /{job_id}/outputs` return structural graph for completed jobs
  only; read-only.
- **Generation ownership** (§8): always via repository/manifest; never max+1/client.

### 5.2 OUT (must NOT be implemented)
- Dense optical flow engine, renderer/compositor/canvas preview, video regeneration/render job.
- S07 (project cast reuse), S09 (demo-first reskin), frontend UI feature.
- T05 correction apply / RECOMPUTE / group-confirm (boundary: see §5.3).
- `source_overlay` segment production (explicit guard).
- New migration unless a column/index is genuinely added (schema already exists).

### 5.3 Correction / recompute boundary (RO-2 §11)
- T02 produces suggested evidence only; does NOT confirm groupings, apply corrections, trigger recompute,
  or auto-supersede.  New extraction run = NEW generation (old segments stale/historical read-only),
  NOT an auto-supersede.  Corrections (T05) use `supersede_segment` — same logical_id successor.

## 6. Binary acceptance criteria (RO-2 §13, 10 items; DRAFT §6)

1. After a completed DISCOVER_OBJECTS job: segment count == candidates × scenes; every segment
   `source_generation` == job generation; `source_job_id` == job id; `mask_artifact_id` non-null &
   points at a ready image artifact owned by the video item; `logical_id` stable on replay.
2. Idempotent replay → `reused=True`, same job id; fresh subprocess re-run → ZERO new segment/motion/
   edge/role/occurrence/artifact rows (counts before/after).
3. Deterministic evidence byte-identical across two independent runs (ids, transforms, edges, mask bytes, sha256).
4. Mask lifecycle: reachable via content endpoint, sha256 verified, contained under job prefix; tampered/
   missing mask → job fails before completion.
5. Ownership chain fails closed: cross-workspace/video/generation role/scene/artifact/job → zero rows before commit.
6. Fail-closed reads: /outputs 409 while active; empty for queued/running/cancelled/failed; graph only when completed.
7. No false evidence: production with no real estimator emits motion with `confidence_source="derived"` +
   explicit reason — never `confidence=1.0, confidence_source="model"`.
8. Scene graph: deterministic adapter emits ≥1 occlusion + ≥1 contact per scene; read API returns them;
   PRAGMA foreign_key_check empty; integrity_check ok after full extraction + read-back.
9. Correction boundary: `supersede_segment` on extraction segment keeps logical_id, archives predecessor,
   both queryable; stale-generation segment read-only (zero mutation on update).
10. Migration safety: `a0b1c2d3e4f5` single head; NO new migration unless a column/index is added → then
    new migration with T01 fail-closed downgrade discipline.

## 7. Allowlist (exact; RO-2 §12 + DRAFT §3 — verify names at HEAD)

Modify:
- `app/services/object_extraction.py`
- `app/schemas/object_extraction.py`
- `app/api/routes/object_extraction.py`
- `tests/test_object_extraction.py`
- `tests/test_object_extraction_api.py`
- `tests/test_object_extraction_production_wiring.py`

Thin helper ONLY (if genuinely needed, e.g. a batch scene-graph create) — justify, never weaken invariants:
- `app/persistence/structural_evidence.py`

NO change (do NOT touch): `app/persistence/models.py`, `migrations/versions/a0b1c2d3e4f5_*`,
`app/api/app.py`, `app/workflow/job_service.py`, `app/persistence/object_intelligence.py`,
`app/persistence/object_correction.py`, any other file.

Evidence:
- `docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/` (TASK/START_PROMPT/LOG/REPORT)
- `output/s08-a02-t02/`

FORBIDDEN without BLOCKED_SCOPE + one question: object_intelligence.py, models.py, other migrations,
frontend, S07/S09, renderer/dense-flow/video regeneration, MAIN, commit/push/merge,
data/motionforge.db for tests, deleting/weakening tests.  If a genuinely required change is outside the
allowlist → STOP REPORT.md = BLOCKED_SCOPE (file, reason, acceptance criterion) — never widen scope yourself.

## 8. Migration policy
- Schema already exists (A02-T01).  NO new migration expected.  `python -m alembic heads` must stay single
  `a0b1c2d3e4f5`.  If a column/index is added → NEW migration with T01 fail-closed downgrade
  (`_assert_no_structural_evidence_rows` before DDL, PRAGMA checks on every path); never writable_schema retrofit.

## 9. Test plan (RO-2 §14; DRAFT §7)

In `tests/test_object_extraction.py`:
1. `test_segments_committed_per_candidate_scene` (counts, gen, job, mask linkage)
2. `test_segment_logical_id_stable_on_replay` (same ids, zero new rows)
3. `test_deterministic_segment_and_motion_evidence` (two runs byte-identical)
4. `test_mask_artifact_lifecycle_and_content_endpoint` (stage→publish→read→sha256; tampered fails)
5. `test_segment_ownership_chain_fails_closed`
6. `test_stale_generation_segments_are_historical_and_read_only`
7. `test_occlusion_and_contact_edges_emitted`
8. `test_no_false_motion_evidence`
9. `test_correction_supersede_keeps_logical_id`

In `tests/test_object_extraction_api.py`:
10. `test_graph_readback_only_when_completed` (409 active; graph completed; empty failed/cancelled)
11. `test_outputs_endpoint_exposes_only_committed_artifacts`

In `tests/test_object_extraction_production_wiring.py`:
12. Extend pristine-subprocess recipe: assert segment/motion/edge counts + PRAGMA foreign_key_check empty
    after full lifecycle.

Regression: full S08 A02 related suites + extraction existing tests stay green; ruff/mypy/git diff --check
stay green.  No mocked repo/DB for wiring tests.

## 10. Required validation (each separate log; NEW evidence dir output/s08-a02-t02/<ts>/)

- Migration: `python -m pytest tests/test_s08_a02_structural_evidence_migration.py -p no:cacheprovider -q`
- Domain: `python -m pytest tests/test_s08_a02_structural_evidence_domain.py -p no:cacheprovider -q`
- C1/C2/C3/C4: `tests/test_s08_a02_c2_integrity.py tests/test_s08_a02_c3_corrections.py
  tests/test_s08_a02_r1_c1_semantic_safety.py`
- API: `tests/test_s08_a02_structural_evidence_api.py` + `tests/test_object_extraction_api.py`
- Extraction wiring: `tests/test_object_extraction.py tests/test_object_extraction_production_wiring.py`
- Phone: `tests/test_s08_a02_phone_interaction_scenario.py`
- Combined focused suite (all above in one run, if within budget).
- Quality gates: `python -m ruff check app tests` → 0; `python -m mypy app` → Success;
  `python -m alembic heads` → single a0b1c2d3e4f5; OpenAPI typed requestBody intact.

## 11. Test integrity
- New tests FAIL on pre-fix code (RED) then PASS (GREEN). Real SQLite/FK/Alembic/repo — no mocks for
  wiring behavior.  Do NOT weaken/delete existing tests; correct coercion-dependent old tests only to the
  stricter contract and document.

## 12. Stop conditions / finish
- Do NOT open S07/S09 or a sprint after A02.  Do NOT commit/push/merge.  Do NOT write MAIN.
- Do NOT self-approve: REPORT.md = SUBMITTED only; manager verifies independently → MANAGER_VERIFIED_PENDING_CODEX_REVIEW.
- If blocked → REPORT.md = BLOCKED / BLOCKED_SCOPE / BLOCKED_MODEL_ROUTE with exact detail.
- Follow the RULES of thumb: generation via repository/manifest; no naive max+1; no source_overlay
  segments; no false evidence; publication stays atomic; layering services→persistence only.
