# S08-A02-T02-C2 — Idempotency Conflict Safety + Real Cross-Process Determinism (Codex CHANGES_REQUESTED)

Narrow correction responding to Codex CHANGES_REQUESTED on T02/C1: (1) the writer still swallows
typed "already bound" conflicts, and (2) the "cross-process" test fakes it by recomputing SHA in a
subprocess instead of running the actual publication path.

## 1. Mandatory model configuration (BLOCKED_MODEL on mismatch)
- Provider: `muse` (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses).
- Model: `ocg/muse-spark-1.2-contributor` (verified; meta/... 401 — do NOT use).
- Reasoning: `max`. No fallback. Mismatch → STOP REPORT.md = BLOCKED_MODEL_ROUTE.
- Record Hermes session ID / model / provider / reasoning / fallback in LOG.md + REPORT.md BEFORE any change.

## 2. Worktree guard
- ONLY `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`; branch `codex/s08-integration`;
  HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`. MAIN protected. Intentional dirty (~208).
  NEVER reset/clean/stash/restore/checkout/commit/push/merge.
- MOTIONFORGE_DATABASE_URL UNSET; temp isolated SQLite; `-p no:cacheprovider`; shallow unique `--basetemp`.

## 3. Exact write allowlist (LANE B — do NOT touch any Lane A/persistence file)
- `app/services/object_extraction.py`
- `tests/test_object_extraction.py`
- `tests/test_object_extraction_api.py`
- `tests/test_object_extraction_production_wiring.py`
- `docs/pm/sessions/S08-A02-T02-C2-idempotency-real-determinism/`
- `output/s08-a02-t02-c2/`

FORBIDDEN: app/persistence/* (structural_evidence.py, object_intelligence.py, models.py), app/schemas/*
object_extraction? (schema untouched unless BLOCKED_SCOPE), tests/test_s08_a02_c3_corrections.py, any other
file, migrations, frontend, S07/S09, MAIN, commit/push/merge, data/motionforge.db, deleting/weakening tests.
If a persistence change is genuinely required → STOP BLOCKED_SCOPE.

## 4. BLOCKER 1 — WRONG CONFLICT SWALLOWING
Repository semantics (already implemented):
- equivalent idempotent replay → returns `(record, False)` (created=False);
- materially different payload with SAME idempotency key → raises
  MotionConflictError / OcclusionConflictError / ContactConflictError whose message contains "already bound".

The service MUST NOT swallow typed "already bound" exceptions (current code wraps create_motion/
create_occlusion/create_contact in try/except and `pass` on `isinstance(exc, ...) and ("already bound" in str(exc))`).

Requirements:
1. REMOVE ALL try/except around create_motion / create_occlusion / create_contact.
2. Call the repository normally and receive `(record, created)`.
3. Equivalent replay is handled purely by the repository's `created=False` return.
4. EVERY conflict exception must propagate and roll back the publication (atomic).
5. Do NOT classify domain errors by substring message matching.
6. DELETE the test that asserted a typed conflict is swallowed.

Mandatory REAL tests (not monkeypatch-only):
- Publish QA evidence; replay with byte-identical payload → counts unchanged, completed.
- Same idempotency key but mutated: motion transform; motion ref; occlusion endpoint/range;
  contact kind/range — EACH must raise the correct conflict, roll back, and NOT mutate the existing row.
- Exception TEXT changes must not affect logic (no substring matching).

## 5. BLOCKER 2 — FAKE CROSS-PROCESS TEST
Current `test_c1_cross_process_deterministic_qa_byte_identical` recomputes SHA in a subprocess instead of
running the actual application path.

Requirements:
1. Cross-process test MUST run the ACTUAL application path: handler or worker, real
   StructuralEvidenceRepository, real publication, fresh isolated SQLite, deterministic QA provider +
   explicit QA mode.
2. Two processes with DIFFERENT PYTHONHASHSEED.
3. Query evidence from the DB AFTER publication.
4. Normalize ONLY environment/job-specific identifiers the contract allows to differ.
5. Compare: prompt/segmentation JSON; mask SHA256; camera/object transforms; motion refs;
   occlusion/contact kind+ranges; synthetic provenance; ordering.
6. Test must FAIL if production implementation reverts to `hash(seg_id)`.
7. Do NOT copy the implementation formula into the test.

## 6. ADDITIONAL TRUTHFULNESS
- QA provenance must use the ACTUAL provider: `deterministic` OR `deterministic-identity`.
- Do NOT hardcode `provider="deterministic"` when running deterministic-identity.
- Add tests for BOTH QA providers.
- Production non-QA still: zero synthetic motion/contact/occlusion; no fake sparse-flow; actual algorithm;
  invalid confidence fail closed; no fabricated bbox.

## 7. Required reading
- `app/services/object_extraction.py` FULL (QA publication ~2360-2513; publish effect; confidence/bbox
  ~2230-2330; cross-process semantics) — specifically the try/except blocks to REMOVE.
- `app/persistence/structural_evidence.py` (read-only: create_motion/create_occlusion/create_contact
  return `(record, created)`; conflict errors). Do NOT modify.
- `tests/test_object_extraction.py` FULL (test_c1_* ~2150+).
- `docs/pm/sessions/S08-A02-T02-C1-truthful-deterministic-evidence/TASK.md` + `REPORT.md`
- `docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/TASK.md` (T02 original)

## 8. Validation (separate logs in NEW evidence dir output/s08-a02-t02-c2/<ts>/)
- New C2 tests (real conflict matrix, real cross-process); object_extraction suite; object_extraction API;
  production wiring; structural regression (read-only, no edits) migration/domain/API/phone.
- Real publication cross-process with TWO PYTHONHASHSEED.
- Real conflicting-idempotency payload repro (mutated transform/ref/endpoint/kind/range each raises).
- Combined focused (extraction + structural) ≥2 runs.
- `python -m ruff check app tests` → 0; `python -m mypy app` → Success; `python -m alembic heads`
  → single a0b1c2d3e4f5; OpenAPI typed requestBody intact.

## 9. Stop conditions
- Do NOT open other tasks/sprints. Do NOT commit/push/merge. Do NOT write MAIN. SUBMITTED only.
- If blocked → REPORT.md = BLOCKED/BLOCKED_SCOPE/BLOCKED_MODEL_ROUTE (file, reason, AC).
