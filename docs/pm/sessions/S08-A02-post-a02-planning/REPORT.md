# S08-A02 Post-A02 Planning — Report (LANE C, READ-ONLY)

**Status:** SUBMITTED (writer sets SUBMITTED; manager/Codex own approval)  
**End state:** BLOCKED_NEXT_SPRINT_AUTHORITY  
**Hermes session:** `20260820_230742_0cd5e3`  
**Model:** `ocg/muse-spark-1.2-contributor` via provider `muse` (Meta Muse via 9Router — `http://127.0.0.1:20128/v1`, `api_mode codex_responses`), reasoning `max`, fallback `none (no fallback)`  
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` — branch `codex/s08-integration`, HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`, MAIN `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` MATCH, `git status --porcelain | wc -l` ~211 intentional dirty, `MOTIONFORGE_DATABASE_URL` UNSET, migration head `a0b1c2d3e4f5` single  
**Run ID:** `20260820_231237` (UTC `2026-08-20T16:12:37Z`, local `2026-08-20T23:12:37+07:00`)  
**Started / Finished:** 2026-08-20T23:07+07:00 → 2026-08-20T23:15+07:00 (wall ~8m)  
**Evidence written (ONLY — no app/tests/migrations):**
- `output/post-a02-planning/20260820_231237/AUTHORITY.md`
- `output/post-a02-planning/20260820_231237/DEPENDENCY_DAG.md`
- `output/post-a02-planning/20260820_231237/PARALLELIZATION.md`
- `output/post-a02-planning/20260820_231237/NEXT_SPRINT_DRAFT.md`
- `docs/pm/sessions/S08-A02-post-a02-planning/LOG.md` (append-only, this lane)
- `docs/pm/sessions/S08-A02-post-a02-planning/REPORT.md` (this file)

---

## Model / provenance (verified BEFORE any write — BLOCKED_MODEL on mismatch)

- **Hermes session ID:** `20260820_230742_0cd5e3` (env `HERMES_SESSION_ID` verified via `env | grep HERMES` before dispatch; this writer's session header).
- **Displayed model:** `ocg/muse-spark-1.2-contributor`
- **Actual model ID:** `ocg/muse-spark-1.2-contributor` (verified; `meta/muse-spark-1.2-contributor` returns HTTP 401 on 9Router — never used).
- **Provider:** `muse` (Meta Muse via 9Router, `base_url http://127.0.0.1:20128/v1`, `api_mode codex_responses`) — verified via `C:\Users\Admin\AppData\Local\hermes\config.yaml` and 9Router probe at dispatch.
- **Reasoning:** `max` — `agent.reasoning_effort: max` + `agent.reasoning_overrides: {ocg/muse-spark-1.2-contributor: max}` as a **real YAML dict** (not JSON string) in `config.yaml`; `isinstance(dict)` verified.
- **Fallback:** `none` — no fallback model/provider configured; mismatch would have been `BLOCKED_MODEL_ROUTE` per `TASK.md:9` (did not occur).
- **Worktree guard:** `pwd` / `git rev-parse --show-toplevel` = `C:/Users/Admin/MotionForge2D-worktrees/s08-integration`, branch `codex/s08-integration`, HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`, `git status --porcelain | wc -l` = 211 at write time, MAIN protected `C:\Users\Admin\MotionForge2D` untouched, `MOTIONFORGE_DATABASE_URL` UNSET.

---

## Write scope (ONLY — enforced)

Per `docs/pm/sessions/S08-A02-post-a02-planning/TASK.md:17-23` + `57-59`:

- Allowed: `output/post-a02-planning/<run-id>/AUTHORITY.md`, `DEPENDENCY_DAG.md`, `PARALLELIZATION.md`, `NEXT_SPRINT_DRAFT.md`, and `docs/pm/sessions/S08-A02-post-a02-planning/LOG.md`+`REPORT.md`.
- Forbidden and NOT touched: `app/`, `tests/`, `migrations/`, any `docs/pm/sessions/*/TASK.md`, any `docs/pm/sprints/*` official packet, any `app/api/app.py` beyond the DRAFT ownership matrix, `frontend/`, `data/motionforge.db`, `channels.json`. No test was run, no code edited, no migration created, no commit/push/merge.

---

## A02 closeout gates (what Codex must approve — normative, with file:line)

S08 is `SPRINT_SUBMITTED` (`docs/pm/sprints/S08-SPRINT_REPORT.md:2-3`); Hermes never writes APPROVED/CLOSED (`docs/pm/sprints/S08-SPRINT_CONTRACT.md:46-48`). The bundle gated on **one Codex sprint-exit review** (`output/MANAGER_STATE.md:5,75-84` — `MANAGER_VERIFIED_PENDING_CODEX_REVIEW — awaiting Codex. Do NOT open sprint/task beyond A02`) is:

1. **A02-T01 C5 Batch-Generation Scalability** — `docs/pm/sessions/S08-A02-T01-C5-batch-generation-scalability/REPORT.md:1-3` (SUBMITTED). Must approve: no `literal_column`/`union_all` (`structural_evidence.py` 0), chunked IN ≤900 with bindparams, authoritative `batch_current_generation` in `ObjectIntelligenceRepository` (single source; `structural_evidence.py` delegates to it), fail-closed unknown ownership (`RoleNotFoundError`, no `except Exception→None`), `list_historical_segments` COUNT after filter + offset/limit after filter + deterministic ordering, no full-history RAM load, flaky fix (no `contextlib.suppress`, deterministic position + hashlib sha, SELECT-only instrumentation). Manager re-run: C3 14 + C2 24 + C1 51 + migration 10 + domain 30 + struct API 50 + phone 1 → combined 180×2, plus 501/1001-video bounded SELECTs ≤15, ruff 0, mypy 91 files 0 (`output/MANAGER_STATE.md:18-32`).

2. **A02-T01 C6 Final Query Scalability** — `docs/pm/sessions/S08-A02-T01-C6-final-query-scalability/TASK.md:27-58` + `REPORT.md:3-8` (SUBMITTED, writer `20260820_230743_c36303` running). Must approve on top of C5: every SQL statement has a FIXED declared bind-parameter budget (no unbounded `or_(IN(chunk)…)` in final COUNT/page SELECT), no UNION ALL per video, no ID string interpolation, no full-history RAM load, COUNT after filter, OFFSET/LIMIT after filter with global deterministic ordering, authoritative `batch_current_generation`, no duplicated generation semantics, no N+1. Preferred SQLite-native `json_each(:stale_json)` JSON-array bind (single JSON text param + `WHERE video_item_id IN (SELECT value FROM json_each(:stale_json))`) or equivalent fixed-budget technique — never raw `literal_column` interpolation.

3. **A02-T02-C1 Truthful Evidence + Determinism** — `docs/pm/sessions/S08-A02-T02-C1-truthful-deterministic-evidence/REPORT.md:1-15` (SUBMITTED). Must approve: `hash(seg_id)` → `hashlib.sha256` stable digest, synthetic motion/contact/occlusion gated by `_is_qa_synthetic` (qa_mode ∧ provider in deterministic/deterministic-identity), production truthful (no inferred edges/flow, no deterministic-layout fallback where missing), missing bbox → omit prompt (never 10/10/50/50), confidence missing/NaN/Inf/out-of-range → `ExtractionError` fail-closed (no clamp/default 0.7), typed idempotency `isinstance(... ) and ("already bound" in str(...))` with explicit parentheses, atomic+idempotent publication. Manager re-run: object_extraction 58 (12 new) + API 20 + prod wiring 1 + C2/C3/C1 89 + mig 10 + domain 30 + struct API 50 + phone 1 → combined 259×2, cross-process PYTHONHASHSEED 1 vs 999 byte-identical (`output/MANAGER_STATE.md:34-51`).

4. **A02-T02-C2 Idempotency + Real Cross-Process Determinism** — `docs/pm/sessions/S08-A02-T02-C2-idempotency-real-determinism/TASK.md:27-54` + `REPORT.md:3-15` (SUBMITTED placeholder, not yet manager-verified). Must approve: remove ALL try/except around `create_motion/create_occlusion/create_contact`; replay uses `(record, created)` (`created=False` for equivalent payload) and every conflict exception propagates and rolls back atomically; no substring message classification (`"already bound"` matching deleted); real handler/worker cross-process determinism test (not SHA recomputation); QA provenance (`deterministic` + `deterministic-identity`), production truthfulness preserved.

5. **S08-T01..T06 underlying evidence** — `docs/pm/sprints/S08-SPRINT_REPORT.md:19-28,104-135` + `docs/pm/ROADMAP.md:170-175` (S08-T01..T06 `SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW` after C1+C2 golden vertical). Codex already approved the final golden vertical Run `20260818-s08t06-c2` (frozen SHA `f008c027…`, thresholds pre-tuned) and baseline `20260819-004409` 7/7, but the whole exit gate must be re-verified after C6+T02-C2 close.

6. **Manager independent verification** — `output/MANAGER_STATE.md:28-32,46-50,57-63` (combined 259 pass ×2, ruff 0, mypy 91 files 0, alembic single head `a0b1c2d3e4f5`, OpenAPI 9/9, cross-process identical). The same integration gate must be repeated after C6+T02-C2 finish.

7. **One migration head** — single Alembic head `a0b1c2d3e4f5` (`down_revision f7a8b9c0d1e2`), `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md:198-212` — any new column/index after A02 must be one new revision with fail-closed downgrade; never two heads, never auto-applied on import/request.

8. **Combined suites + protected hashes** — `docs/pm/sprints/S08-SPRINT_CONTRACT.md:39-43` (focused S08, S01/S02/S03/S05/S06 regressions, migrations, restart/retry/cancel/concurrency, ruff/mypy/diff-check, frontend tsc/eslint/build, Playwright desktop+390px, golden metrics, fresh 7/7 baseline, protected-data comparison, complete lineage). Protected MAIN: `channels.json dd7aae26…555`, `motionforge.db 311296 B` unchanged (`OUTPUT/MANAGER_STATE.md:11-12`); SAM2.1 checkpoint read-only `898083611 B` SHA `2647878d…` if applicable.

---

## Next sprint/task authority (search of ROADMAP for S07/S09/post-A02)

**Finding: NO AUTHORITY today for any post-A02 sprint/task.**

- `S07-T01 Project Cast Mapping … S06 exit,E05 contract → PLANNED` (`docs/pm/ROADMAP.md:153`)
- `S09-T01 Reskin Mapping … E04,E05 → PLANNED` (`docs/pm/ROADMAP.md:199`)
- Activation rule: `Task chỉ chuyển PLANNED -> READY khi mọi dependency đã APPROVED và PM đã tạo session packet` (`docs/pm/ROADMAP.md:284`); parallel only when PM allows non-overlapping scopes (`ROADMAP.md:283`); sprint closes only after exit gate (`ROADMAP.md:285`).
- S08 contract: `Hermes stops every writer and submits docs/pm/sprints/S08-SPRINT_REPORT.md as SPRINT_SUBMITTED. Hermes never writes Codex approval and does not start S07.` (`docs/pm/sprints/S08-SPRINT_CONTRACT.md:46-48`).
- Because E05 = S08 (`docs/pm/ROADMAP.md:166-188`) and S08 is `SPRINT_SUBMITTED` / `MANAGER_VERIFIED_PENDING_CODEX_REVIEW` (`output/MANAGER_STATE.md:3-6` + `docs/pm/sprints/S08-SPRINT_REPORT.md:2-3`), the required `APPROVED` dependency for both S07-T01 (`E05 contract`) and S09-T01 (`E04,E05`) is **not met**. All downstream S07-T02/T03 and S09-T02..T06 + S10..S13 are transitively blocked (`ROADMAP.md:153-155,199-214`).
- `S07-T01 vẫn chờ contract` (`ROADMAP.md:286`) — confirms S07 uniquely waits on the E05 structural-evidence contract that A02 delivers; S09 additionally waits on E04 (which requires S07).

Therefore **every ROADMAP entry beyond A02 is `PLANNED` and dependency-gated on Codex approval of S08+A02**; there is no `READY` task to dispatch, and no implicit authority to create a packet by this lane (`TASK.md:57-59`).

---

## Decomposition / DAG / parallelization / max concurrency (DRAFT summary — cite the four docs)

- **DAG:** `DEPENDENCY_DAG.md §2-6` — nodes A02-C5/C6 + A02-T02-C1/C2 (parallel lanes today) → `S08-CLOSE` (Codex serial gate) → `S07-T01 → T02 → T03` (serial) → `S09-T01 → T02 → T03 → T04 → T05 → T06` (serial) → `S10..S13`. `S07-T01` blocks `S09-T01` via `E04` (`ROADMAP.md:199,286`). Migration owner: A02 keeps single head `a0b1c2d3e4f5`; S07-T01 owns next S07 migration; S09-T01 owns next S09 migration (each exactly ONE new revision, `down_revision = <head_at_dispatch>`, fail-closed downgrade per `PERSISTENCE_DOMAIN_CONTRACT.md:198-212`). Integration gate: focused + S01/S02/S03/S05/S06 + restart/retry/cancel/concurrency + ruff/mypy/diff-check + frontend tsc/eslint/build + Playwright desktop+390px + golden + fresh 7/7 + protected hashes + lineage (same as `S08-SPRINT_CONTRACT.md:39-43`).

- **Parallelization:** `PARALLELIZATION.md §1-5` — A02: **2 lanes in parallel** (Lane A = `structural_evidence.py`+`object_intelligence.py`+`test_s08_a02_c3_corrections.py`; Lane B = `object_extraction.py`+`test_object_extraction*.py`; zero file overlap, manager verified combined 259×2). Post-A02: **max 1 concurrent writer** — linear chains + single worktree/HEAD + single migration head + intentional dirty ~211 + single `MANAGER_STATE` owner. S07 vs S09 not parallel until S07-T01 completes. Detailed per-task ownership matrix in `PARALLELIZATION.md §2.2` + `NEXT_SPRINT_DRAFT.md §6`.

- **Max concurrency recommendation:** **2 for the narrow A02 closeout window (already running), then 1 for all post-A02 work** — do not raise above 1 without an explicit new worktree + disjoint `--basetemp` + disjoint Alembic heads + port offsets, which would complicate the protected-data comparison and is never worth it while S07→S09 is serial by dependency.

---

## User decisions needed (if authority missing — one decision per item)

Because the finding is **BLOCKED_NEXT_SPRINT_AUTHORITY**, the PM must obtain explicit user (and Codex where noted) decisions before promoting `NEXT_SPRINT_DRAFT.md` to any official packet or dispatching any writer. Each item is one independent decision:

**D1. Ordering: S07 before S09, or S09 before S07?**  
Options: (a) S07-T01..T03 first (recommended — satisfies `ROADMAP.md:199` `E04,E05` for S09-T01 and `ROADMAP.md:286`). (b) S09-T01..T06 first (requires relaxing S09-T01's `E04` dependency and accepting that S07 will later add `ProjectCastMapping` FKs that S09 mappings must already tolerate as nullable/deferred). One choice only — determines the first post-A02 migration owner (S07-T01 vs S09-T01). No dispatch until chosen.

**D2. Cast-reuse scope for S07-T01:**  
Is S07-T01 Pinned Object Role → Pack Version mapping per **project** (ROADMAP text `Project Cast Mapping domain/API pins Object Role to Pack Version` `ROADMAP.md:153` + overnight `S07-COMPATIBILITY-DRAFT.md`) or per **video_item**? Per-project is the overnight default; per-video would require a different FK (`video_item_id` instead of `project_id`) and changes the version-isolation tests. No schema work until pinned.

**D3. Reskin preconditions for S09-T01:**  
Does S09-T01 need `ReskinMapping` to reference the future `ProjectCastMapping` FK (nullable) from the start, or may it pin directly to `PackVersion` and add the cast FK in S09-T02? The choice affects the first S09 migration's FK set and the S07↔S09 overlap risk flagged in `NEXT_SPRINT_DRAFT.md §8`.

**D4. Migration sequencing guard:**  
Confirm that the next sprint's first task (whether S07-T01 or S09-T01) is the **sole migration owner** and will create **exactly ONE** new Alembic revision `down_revision = <head_at_dispatch>` (today `a0b1c2d3e4f5`) with a `downgrade()` that fails closed on data loss (`PERSISTENCE_DOMAIN_CONTRACT.md:224-227`), and that no other post-A02 task may create a migration without a `BLOCKED_SCOPE` stop. This is the user/Codex alignment that prevents two heads.

**D5. Demo-loop source-of-truth for S09-T03:**  
For `Select 3-5 representative demo loops and create proxy jobs` (`ROADMAP.md:201` `S09-T03`), does the proxy-job contract reuse the existing `Job`/`Artifact` managed-root pattern (`PERSISTENCE_DOMAIN_CONTRACT.md:38-42,191-193`) and the overnight `S09-T00-BENCHMARK-DRAFT.md` dataset, or introduce a new loop-artifact kind? The choice determines `S09-T03`'s file ownership (loop service vs artifact lifecycle) and the golden benchmark scope for `S09-T06`'s immutable apply checkpoint (`ROADMAP.md:204`).

Until D1..D5 are answered and `S08-CLOSE` is Codex-APPROVED, this DRAFT must remain a **read-only planning artifact** under `output/post-a02-planning/20260820_231237/` and must not be copied to `docs/pm/sprints/` or `docs/pm/sessions/`.

---

## Warnings / limitations

- **Dirty worktree risk:** `git status --porcelain | wc -l` = 211 at this lane's finish (baseline 208→211). All counts above are manager-reported; any writer that begins without a fresh preflight hash will mis-attribute which files it owns. The manager preflight hash discipline in `docs/pm/sessions/S08-A02-T01-C5/REPORT.md:9-15` etc. must be repeated for every future writer.
- **Single-head fragility:** Two concurrent writers each creating a migration would produce two Alembic heads — automatic rejection per `PERSISTENCE_DOMAIN_CONTRACT.md:201-203`. The ownership table in `DEPENDENCY_DAG.md §4` and `PARALLELIZATION.md §2.2` is the enforcement mechanism; enforce it before any parallel dispatch.
- **No runtime evidence from this lane:** Per `TASK.md:15` — `NO tests run, NO code edited, NO migrations` — all gates above are cited from authoritative markdown/ reports, not from a fresh pytest/ruff/mypy run in this lane. The manager must still re-run the integration gate after C6+T02-C2 close before `S08-CLOSE` can be approved.
- **Blocked state is intentional:** `BLOCKED_NEXT_SPRINT_AUTHORITY` is not an error — it is the normative consequence of `ROADMAP.md:284` given S08's `SPRINT_SUBMITTED` status. Promoting the DRAFT without the five decisions would create an orphan sprint with missing FK owners and a second migration head.

---

## End state

**BLOCKED_NEXT_SPRINT_AUTHORITY** — conditional DRAFT produced at `output/post-a02-planning/20260820_231237/` (AUTHORITY + DAG + PARALLELIZATION + NEXT_SPRINT_DRAFT), ready for PM review but **gated** on (a) Codex approval of the A02 bundle (C5/C6 + T02-C1/T02-C2) and `S08-CLOSE`, and (b) user decisions D1..D5. No official sprint/task packet was created; no implementation was dispatched; no `app/`/`tests/`/`migrations/`/`MAIN` was modified; no commit/push/merge was performed.

**SUBMITTED** — Hermes stops here; manager/Codex own approval. Never self-approve.

