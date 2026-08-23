You are the ONLY code writer for MotionForge2D correction task S08-A02-T02-C2 (Idempotency Conflict Safety + Real Cross-Process Determinism) — LANE B.

MANDATORY MODEL CONFIGURATION:
- Provider: muse (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses).
- Model: ocg/muse-spark-1.2-contributor (verified; meta/... 401 — do NOT use).
- Reasoning: max. No fallback. Mismatch → STOP REPORT.md = BLOCKED_MODEL_ROUTE + exact error.
- Record Hermes session ID, model, provider, reasoning, fallback in LOG.md + REPORT.md BEFORE any change.

WORKTREE:
C:\Users\Admin\MotionForge2D-worktrees\s08-integration
Branch: codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204
MAIN protected. Intentional dirty (~208) — never reset/clean/stash/restore/checkout/commit/push/merge.
Alembic head: a0b1c2d3e4f5 (single). NO new migration.

TASK:
Read FULLY and execute ONLY: docs/pm/sessions/S08-A02-T02-C2-idempotency-real-determinism/TASK.md (normative)

ALSO READ: app/services/object_extraction.py (FULL, QA publication ~2360-2513; publish effect; confidence/bbox ~2230-2330), app/persistence/structural_evidence.py (READ-ONLY: create_motion/occlusion/contact return (record, created); conflict errors — do NOT modify), tests/test_object_extraction.py (FULL, test_c1_* ~2150+), docs/pm/sessions/S08-A02-T02-C1-truthful-deterministic-evidence/TASK.md + REPORT.md, docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/TASK.md.

EXACT SCOPE (Lane B allowlist ONLY — do NOT touch any Lane A/persistence file):
- app/services/object_extraction.py
- tests/test_object_extraction.py
- tests/test_object_extraction_api.py
- tests/test_object_extraction_production_wiring.py
- docs/pm/sessions/S08-A02-T02-C2-idempotency-real-determinism/ (LOG.md, REPORT.md)
- output/s08-a02-t02-c2/

FORBIDDEN: app/persistence/* (structural_evidence.py, object_intelligence.py, models.py), app/schemas (unless BLOCKED_SCOPE), tests/test_s08_a02_c3_corrections.py, migrations, frontend, S07/S09, MAIN, commit/push/merge, data/motionforge.db, deleting/weakening tests. If persistence change genuinely required → STOP BLOCKED_SCOPE (file, reason, AC).

BLOCKER 1 — WRONG CONFLICT SWALLOWING: service still wraps create_motion/create_occlusion/create_contact in try/except and swallows typed "already bound" on `isinstance(exc,...) and ("already bound" in str(exc))`.
Requirements: REMOVE ALL try/except around create_motion/create_occlusion/create_contact; call repository normally and receive (record, created); equivalent replay handled purely by created=False; EVERY conflict exception propagates + rolls back publication (atomic); do NOT classify domain error by substring message; DELETE tests that assert typed conflict is swallowed.

BLOCKER 2 — FAKE CROSS-PROCESS TEST: current test recomputes SHA in subprocess instead of actual application path.
Requirements: cross-process test MUST run ACTUAL application path (handler or worker, real StructuralEvidenceRepository, real publication, fresh isolated SQLite, deterministic QA provider + explicit QA mode); two processes with DIFFERENT PYTHONHASHSEED; query evidence from DB AFTER publication; normalize only env/job-specific identifiers the contract allows to differ; compare prompt/segmentation JSON, mask SHA256, camera/object transforms, motion refs, occlusion/contact kind+ranges, synthetic provenance, ordering; test must FAIL if implementation reverts to hash(seg_id); do NOT copy the implementation formula into the test.

ADDITIONAL TRUTHFULNESS: QA provenance uses ACTUAL provider (deterministic OR deterministic-identity); do NOT hardcode provider="deterministic" when running deterministic-identity; add tests for BOTH QA providers; production non-QA still: zero synthetic motion/contact/occlusion, no fake sparse-flow, actual algorithm, invalid confidence fail closed, no fabricated bbox.

MANDATORY TESTS (real, not monkeypatch-only): publish QA evidence; replay byte-identical payload → counts unchanged, completed; same idempotency key but mutate motion transform / motion ref / occlusion endpoint/range / contact kind/range — EACH raises correct conflict, rolls back, does NOT mutate existing row; exception TEXT changes must not affect logic.

VALIDATION (separate logs in NEW evidence dir output/s08-a02-t02-c2/<ts>/): new C2 tests; object_extraction suite; object_extraction API; production wiring; structural regression migration/domain/API/phone (read-only, no edits); real cross-process with TWO PYTHONHASHSEED; real conflicting-idempotency repro; combined focused ≥2 runs; ruff check app tests → 0; mypy app → Success; alembic single head; OpenAPI typed requestBody.

LOGGING: append to docs/pm/sessions/S08-A02-T02-C2-idempotency-real-determinism/LOG.md (append-only, real local +07:00 and UTC=local-7h at write time). Fill REPORT.md to SUBMITTED (never APPROVED).

STOP: do NOT open other tasks/sprints; do NOT commit/push/merge; do NOT write MAIN; SUBMITTED only. If blocked → REPORT.md = BLOCKED/BLOCKED_SCOPE/BLOCKED_MODEL_ROUTE. Exit cleanly with all evidence.
