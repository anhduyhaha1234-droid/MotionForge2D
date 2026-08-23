You are the ONLY code writer for MotionForge2D correction task S08-A02-T01-C2 (Re-analysis Role Binding, Temporal Dependency, Lineage and Strict API Correction).

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses). DO NOT call any Meta provider directly; everything goes through local 9Router.
- Model: ocg/muse-spark-1.2-contributor  (verified present on 9Router and WORKING — probe 2026-08-20T14:16:46+07 returned banner ok, session 20260820_141647_ff6419. NOTE: `meta/muse-spark-1.2-contributor` returns HTTP 401 on 9Router — do NOT use it; the correct model ID is ocg/muse-spark-1.2-contributor as the user confirmed.)
- Reasoning: high (agent.reasoning_overrides = {ocg/muse-spark-1.2-contributor: high} — real YAML dict, verified effective via resolve_per_model_reasoning_effort; user set Muse contributor to high to save quota. DeepSeek keeps global max but you are NOT DeepSeek). Do not request max.
- No fallback (hermes fallback list empty — verified). Do not switch model/provider/fallback. If runtime reports a different model/provider or rejects this model, STOP with REPORT.md = BLOCKED_MODEL_ROUTE and paste the exact error.
- Record actual Hermes session ID, displayed model name, actual model ID, provider, reasoning level, and fallback status in LOG.md and REPORT.md BEFORE any code change.

CONTINUATION MODE (IMPORTANT — READ):
A previous C2 writer session 20260820_134635_e3dda6 (same Muse model, reasoning max) was KILLED mid-edit by the user. Its partial work REMAINS in the worktree — do NOT discard, do NOT reset/restore/checkout, do NOT revert. You continue FROM that working state. Current mid-edit hashes (start point, all DIFFER from the recovered clean baseline on purpose):
- app/persistence/models.py: 4C77368452CB4712725A2B55C102C2F711280DB61F842CF0BEDCACF803E7C138
- app/persistence/structural_evidence.py: BBA087585222C3FB9681E2A52630E053967FBED78ECE1A6479D34BCC7E1E1A38
- migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py: 3529914454ABF5C579A496EBD5D1EA2CD3029DF1F7773DF0C4E5FE500101D072
- app/schemas/structural_evidence.py: 9A97855E482E649939E2D763A27C9F7A8B6C49730EF69C7EE6F1FDCB9244DE87
- app/api/routes/structural_evidence.py: 0422B51ABB34F9D035DC0AF693BE56DBE3F8EB4C97171939E161EE069C9136D5
- tests/test_s08_a02_c2_integrity.py EXISTS (created by killed writer, partially fixed) — continue working on it, do not delete.
- scratch files _fix_c2.py, _fix_c2_mig.py, _fix_c2_routes.py exist at worktree root (created by killed writer) — treat as your own scratch; you may inspect/update/delete them, but NEVER leave them as deliverables.
AUDIT the current code state on disk first (read the actual files; the killed writer's LOG/reasoning claims are secondary). Then drive C2-F1..F6 to full completion.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration
HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected: C:\Users\Admin\MotionForge2D (do NOT modify, ever)
Alembic head: a0b1c2d3e4f5 (single head, down_revision f7a8b9c0d1e2) — unreleased, may rewrite within same revision for C2-F4 DB constraints. NO second head.

TASK:
Read FULLY and execute ONLY:
docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/TASK.md (normative C2-F1..F6)

Also read (context only — do NOT modify, do NOT trust at face value; re-audit current code):
- output/s08-a02-t01-c2/CODEX_INDEPENDENT_REVIEW.md (CHANGES_REQUESTED, 32 patches reverted)
- docs/pm/sessions/S08-A02-T01-R1-C1-semantic-safety/TASK.md + REPORT.md + LOG.md
- docs/pm/sessions/S08-A02-T01-R2-structural-evidence-api/TASK.md + REPORT.md + LOG.md
- docs/pm/sessions/S08-A02-T01-R1-deepseek-core-recovery/TASK.md
- docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md
- docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md

READ PRODUCTION CODE FULLY (current on-disk state, not only REPORTs):
- app/persistence/models.py — complete A02 block + constants/exports
- app/persistence/structural_evidence.py — FULL file: create_segment, update_segment, supersede_segment, _assert_role_compatible, segment_lineage, motion/occlusion/contact paths
- app/persistence/object_intelligence.py — create_role/update_role/current_generation/_current_generation_for_source (ONLY authority, do NOT modify without BLOCKED_SCOPE)
- migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py
- app/schemas/structural_evidence.py
- app/api/routes/structural_evidence.py (9 mutating ops: POST segments, PATCH current segment, POST supersede, POST motion, PATCH motion, POST occlusion, PATCH occlusion, POST contact, PATCH contact)
- app/api/app.py (only if router registration genuinely requires it)

READ ALL FIVE EXISTING A02 TESTS:
- tests/test_s08_a02_r1_c1_semantic_safety.py
- tests/test_s08_a02_structural_evidence_api.py
- tests/test_s08_a02_structural_evidence_domain.py
- tests/test_s08_a02_structural_evidence_migration.py
- tests/test_s08_a02_phone_interaction_scenario.py
Plus the in-progress tests/test_s08_a02_c2_integrity.py.

LOGGING:
- Append to docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/LOG.md (append-only, real timestamps local +07:00 Asia/Bangkok and UTC=local-7h at write time)
- Fill docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/REPORT.md to SUBMITTED (never APPROVED)

C2 BLOCKING FINDINGS — ALL SIX MUST BE CLOSED WITH CODE + FAILING-THEN-PASSING TESTS:

C2-F1 — RE-ANALYSIS TARGET ROLE BINDING:
- Workflow B must accept/bind target_role_id from new current generation. Validate workspace, project, video, generation, kind. Target generation == ObjectIntelligenceRepository.current_generation(). Require matching completed DISCOVER_OBJECTS job and source SHA. Predecessor retains old role (never mutated — no role.source_generation assignment), successor uses new role. Workflow A manual same-gen keeps prior role and rejects arbitrary target_role_id. Replace every helper that assigns role.source_generation directly. Tests must create new role via ObjectIntelligenceRepository.create_role (never mutate ObjectRole.source_generation directly).

C2-F2 — SEGMENT RANGE MUST PROTECT CHILD EVIDENCE:
- Before CAS update_segment commits, compute proposed frame/time range and validate ALL attached SegmentMotion, SceneGraphOcclusion (either endpoint), SceneGraphContact (either endpoint). Every child range inside proposed parent in BOTH frames and milliseconds. Violation -> stable SegmentConflictError (API 409), parent revision unchanged, all rows unchanged, transaction rolled back. Tests: start/end shrink, frame-only/time-only, motion/both occlusion/both contact endpoints, allowed expansion, stale CAS.

C2-F3 — MANUAL CORRECTION REQUIRES EXPLICIT HUMAN PROVENANCE:
- Workflow A: require confidence_source in {user, manual} AND caller-supplied non-empty manual provenance/audit data. Never inherit prior machine provenance when missing/null/empty. Old source_job_id is extraction history, not human provenance. Missing/null/empty -> stable zero-mutation rejection at repo AND API.

C2-F4 — DATABASE-ENFORCED LINEAGE:
- Real SQLite constraints with ORM/migration parity inside existing unreleased revision a0b1c2d3e4f5 (no second head). DB enforces: no self-link, successor cannot have two predecessors, one active row per (workspace_id, logical_id), unique (workspace_id, logical_id, lineage_version), concurrent supersede single winner, no orphan placeholder. Wallet-driven detection insufficient. Replace transient self-link lifecycle if it conflicts (the killed writer already changed placeholder_superseded_by_id to a random _new_id() — audit that decision against C2-F4). Raw-SQL tests: second predecessor same successor rejected by SQLite, duplicate active rejected, self-link rejected, PRAGMA integrity_check ok, PRAGMA foreign_key_check empty, rollback no orphans.

C2-F5 — HISTORICAL API MUST NOT MIX CURRENT:
- /segments/historical returns ONLY historical (superseded OR stale-generation active), never active successor of current generation. Mixed current+history belongs only to lineage endpoint. Filtering before total/offset/limit/pagination. Querying current source_generation returns superseded predecessors but excludes active successor. Current list remains current-gen + active-only.

C2-F6 — STRICT DTO AND TYPED OPENAPI:
- Request schemas strict typing (ConfigDict strict=True): reject numeric strings, reject booleans for int/float, keep rejecting unknown fields, stable 422 for NaN/Infinity at any depth, zero mutation on validation failure. Every public POST/PATCH exposes concrete Pydantic request model in OpenAPI requestBody (concrete schema/$ref, not {type: object, additionalProperties: true}). All nine mutating ops. Response schemas concrete. DELETE absent.

ALLOWLIST (exact):
Production: app/persistence/models.py (A02 block only), app/persistence/structural_evidence.py, migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py, app/schemas/structural_evidence.py, app/api/routes/structural_evidence.py, app/api/app.py only if registration genuinely requires it.
Tests: tests/test_s08_a02_r1_c1_semantic_safety.py, tests/test_s08_a02_structural_evidence_api.py, tests/test_s08_a02_structural_evidence_domain.py, tests/test_s08_a02_structural_evidence_migration.py, tests/test_s08_a02_phone_interaction_scenario.py, tests/test_s08_a02_c2_integrity.py (new).
Evidence: docs/pm/sessions/S08-A02-T01-C2-semantic-api-integrity/, output/s08-a02-t01-c2/.
FORBIDDEN without BLOCKED_SCOPE+one question: app/persistence/object_intelligence.py, other migrations, frontend, A02-T02, S07/S09, renderer/dense flow/video regeneration, eight old head-bump tests, MAIN, any file outside allowlist, commit/push/merge, using data/motionforge.db for tests, deleting/weakening tests, cleaning unrelated dirty files.

TEST INTEGRITY:
- Do not delete/weaken tests. Do not change expected values to obtain pass. Correct coercion-dependent old test only to stricter contract and document it.
- Use real SQLite, foreign keys, Alembic, repo, router. No mocked repo/DB.
- Every new C2 test must fail on recovered pre-C2 code (the killed writer already converted several; re-audit).
- Green suite is evidence, not approval.

VALIDATION ORDER (MOTIONFORGE_DATABASE_URL UNSET, -p no:cacheprovider, fresh shallow basetemps C:/Users/Admin/AppData/Local/Temp/):
1 C2 dedicated tests (test_s08_a02_c2_integrity.py)  2 C1 focused  3 Migration  4 Domain  5 API  6 Phone  7 Combined A02  8 Object-intelligence/grouping/correction regressions  9 Persistence bootstrap+durable jobs  10 Full relevant S08  11 Ruff  12 Mypy  13 git diff --check  14 OpenAPI typed requestBody inspection  15 Alembic heads/integrity/FK/upgrade/downgrade refusal  16 One fresh quality baseline 7/7  17 Protected MAIN/hash comparison  18 NO_LISTENERS and final status/process audit
Record verbatim command, real pass/fail count, elapsed, unique Run ID, raw log path for every run. Do not rerun baseline to hide flaky failures.

FINISH:
Writer finishes only as SUBMITTED with exact files changed, per-finding code+test evidence, all runs, protected hash comparison, actual session/model/provider/reasoning, deviations/limitations. Manager verifies independently. Neither may write APPROVED. Final manager state = MANAGER_VERIFIED_PENDING_CODEX_REVIEW. A02-T01 remains NOT APPROVED until CODEX. Do not open A02-T02. Do not commit/push/merge. Stop after manager verification.

TIMESTAMPS: Take at write time, local +07:00 (Asia/Bangkok) and UTC = local-7h. Never future/estimated. Verification must use real outputs, not REPORT claims alone.
