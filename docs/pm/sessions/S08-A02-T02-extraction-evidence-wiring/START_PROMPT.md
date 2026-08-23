You are the ONLY code writer for MotionForge2D task S08-A02-T02 (Extraction Evidence and Artifact Wiring).

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses). DO NOT call Meta directly.
- Model: ocg/muse-spark-1.2-contributor (verified on 9Router; meta/muse-spark-1.2-contributor returns 401 — do NOT use).
- Reasoning: max (agent.reasoning_overrides = {ocg/muse-spark-1.2-contributor: max} real YAML dict; agent.reasoning_effort = max).
- No fallback. If runtime reports a different model/provider or rejects, STOP with REPORT.md = BLOCKED_MODEL_ROUTE + exact error.
- Record actual Hermes session ID, displayed model, actual model ID, provider, reasoning, fallback in LOG.md and REPORT.md BEFORE any change.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration
HEAD: a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected: C:\Users\Admin\MotionForge2D (never modify). Intentional dirty — never reset/clean/stash/restore/checkout/commit/push/merge.
Alembic head: a0b1c2d3e4f5 (single). NO new migration unless a column/index is genuinely added.

TASK:
Read FULLY and execute ONLY: docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/TASK.md (normative)

ALSO READ (context; re-audit current code before trusting):
- output/s08-a02-t01-r1-c1/ro2-t02-planning.md (221-line authority plan)
- output/overnight-planning/S08-A02-T02-DRAFT.md
- docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md (T01 contract)
- app/persistence/structural_evidence.py (FULL — the repository T02 consumes)
- app/services/object_extraction.py (FULL ~2622 lines — the handler T02 wires)
- app/schemas/object_extraction.py, app/api/routes/object_extraction.py
- app/persistence/object_intelligence.py (READ-ONLY generation authority)
- Existing extraction tests + A02 structural-evidence tests

SCOPE (normative in TASK.md §5-§9):
- Produce OccurrenceSegment/SegmentMotion/SceneGraphOcclusion/SceneGraphContact rows inside _publish_effect's transaction (deterministic uuid5 ids, scene-scoped ranges, generation = job manifest, source_job_id, mask_artifact_id, canonical prompt/seg JSON, idempotency, provenance/confidence).
- Mask lifecycle: stage → publish ready; segment mask = published mask; ObjectRoleArtifact association same transaction; sha256 verified; fail-closed.
- Motion: camera-relative + object-relative rows; point_track_flow_ref is a REFERENCE (no dense flow); production emits confidence_source="derived" + reason (never confidence=1.0/model false evidence).
- Scene-graph: occlusion + contact edges (current-generation same video, range within endpoints); deterministic QA adapter emits >=1 occlusion + >=1 contact per scene.
- Read API: /{job_id} and /{job_id}/outputs expose structural graph for completed jobs only; read-only.
- Generation ownership: always via repository/manifest, never max+1/client. NO source_overlay. NO auto-supersede (new run = new generation).
- Boundary: T02 emits suggested evidence only; does NOT confirm groupings/apply corrections/trigger recompute (T03/T05).

ALLOWLIST (exact; verify at HEAD):
- Modify: app/services/object_extraction.py, app/schemas/object_extraction.py, app/api/routes/object_extraction.py, tests/test_object_extraction.py, tests/test_object_extraction_api.py, tests/test_object_extraction_production_wiring.py
- Thin helper ONLY if genuinely needed (e.g. batch scene-graph create) — justify, never weaken invariants: app/persistence/structural_evidence.py
- Evidence: docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/, output/s08-a02-t02/
FORBIDDEN without BLOCKED_SCOPE + one question: object_intelligence.py, models.py, other migrations, frontend, S07/S09, renderer/dense flow/video regeneration, MAIN, commit/push/merge, data/motionforge.db, deleting/weakening tests.

LOGGING:
- Append to docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/LOG.md (append-only, real timestamps local +07:00 and UTC=local-7h at write time).
- Fill docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/REPORT.md to SUBMITTED (never APPROVED).

DB/ENV: unset MOTIONFORGE_DATABASE_URL before any test; only fresh isolated SQLite under C:/Users/Admin/AppData/Local/Temp/ with -p no:cacheprovider and shallow unique --basetemp per run; never MAIN/user DB.

ACCEPTANCE (10 binary items, TASK §6): segment mapping + idempotent replay zero rows + deterministic byte-identical evidence + mask lifecycle sha256 + ownership fail-closed + fail-closed reads + no false evidence + scene graph edges + correction boundary keeps logical_id + single migration head.

VALIDATION (separate logs in NEW evidence dir output/s08-a02-t02/<ts>/): migration, domain, c1/c2/c3/c4, api, extraction wiring + api, phone, combined; ruff check app tests → 0; mypy app → Success; alembic single head; OpenAPI typed requestBody.  Existing tests must stay green (no weakening; correct coercion-dependent old tests only to stricter contract and document).

TEST INTEGRITY: new tests FAIL on pre-fix (RED) then PASS (GREEN); real SQLite/FK/Alembic/repo; no mocking of wiring behavior.

STOP CONDITIONS: do NOT open S07/S09 or a new sprint after A02; do NOT commit/push/merge; do NOT write MAIN; do NOT self-approve (SUBMITTED only). If blocked → REPORT.md = BLOCKED/BLOCKED_SCOPE/BLOCKED_MODEL_ROUTE with exact detail.  Tell user/manager immediately after SUBMITTED (manager verifies independently; final state MANAGER_VERIFIED_PENDING_CODEX_REVIEW).
