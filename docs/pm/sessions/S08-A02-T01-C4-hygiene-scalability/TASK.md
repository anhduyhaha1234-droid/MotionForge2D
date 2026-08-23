# S08-A02-T01-C4 — Hygiene & Scalability Correction (post-Codex non-blocking notes)

Narrow hygiene correction in response to Codex's three non-blocking notes on
S08-A02-T01 (verdict APPROVED_WITH_NON_BLOCKING_NOTES, 30 passed).  NARROW scope —
do NOT refactor beyond the three notes.

## 1. Mandatory model configuration (BLOCKED_MODEL on mismatch)

- Provider: `muse` (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses).
- Model: `ocg/muse-spark-1.2-contributor` (verified on 9Router; meta/... returns 401 — do NOT use).
- Reasoning: `max` (config reasoning_overrides = {ocg/muse-spark-1.2-contributor: max}; agent.reasoning_effort max).
- No fallback.  If runtime reports a different model/provider or rejects, STOP
  REPORT.md = BLOCKED_MODEL_ROUTE with exact error.
- Record actual Hermes session ID, model, provider, reasoning, fallback in LOG.md + REPORT.md
  BEFORE any code change.

## 2. Worktree guard

- ONLY worktree: `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`
- Branch `codex/s08-integration`; HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
- MAIN `C:\Users\Admin\MotionForge2D` protected — never modify.
- Intentional dirty (~204 entries).  Never reset/clean/stash/restore/checkout/commit/push/merge.
- `MOTIONFORGE_DATABASE_URL` UNSET; tests use fresh isolated SQLite under C:/Users/Admin/AppData/Local/Temp/,
  `-p no:cacheprovider`, shallow unique `--basetemp`.  Never data/motionforge.db or user DB.

## 3. Baseline hashes (verified by manager preflight 2026-08-20T17:40+07)

- app/persistence/structural_evidence.py = fa9ef29d360ad93d6880d29047bc0be9690990bb8dd582ed17741ddcc3a6207e
- tests/test_s08_a02_c2_integrity.py = 4760bfd54f407cffa06ee2df38265cb139be7a331d6b52e45098e5278ec4976d
- tests/test_s08_a02_c3_corrections.py = dd3001e6f02f8300b41369e5c1a6d8379dc914634f05a2847c3cf46d65a71700

## 4. Required reading (read FULLY first)

- `docs/pm/sessions/S08-A02-T01-C3-project-role-historical/TASK.md` + `REPORT.md`
- `app/persistence/structural_evidence.py` — `list_historical_segments` (~1407-1494), helpers `current_generation` (~586-592)
- `app/persistence/object_intelligence.py` — READ-ONLY authority: `current_generation` (~301-322),
  `_current_generation_for_source` (~324-358), `_current_generation_map` (~360-367).  DO NOT MODIFY — C4
  may only use them read-only or replicate the batch resolution inside structural_evidence.py.
- `tests/test_s08_a02_c2_integrity.py` — `test_c2f6_strict_rejects_bool_for_int` (~883-901) and siblings.
- `tests/test_s08_a02_c3_corrections.py` — file header noqa + all 41 long lines.

## 5. C4 objectives (one per Codex note)

### C4-1 — strict boolean test: replace broad except
- In `tests/test_s08_a02_c2_integrity.py::test_c2f6_strict_rejects_bool_for_int`,
  replace the `try:/except Exception:` block with a tight `with pytest.raises(ValidationError):`
  around `SegmentCreateRequest.model_validate({... start_frame: True ...})`.
- Assert the validation error location is `start_frame` (introspect the ValidationError
  payload: `e.errors()[0]["loc"]` contains `start_frame`, and the error type is the int-strict
  rejection) — without over-coupling to internal message wording.
- Keep the payload valid in every other respect (bool only in start_frame).  Test must FAIL
  if model_validate did NOT reject the bool.
- Do NOT broaden the except.  Do NOT weaken the test.

### C4-2 — remove file-level ruff suppression in C3 tests
- Delete the file header `# ruff: noqa: E501, B011, F841` from `tests/test_s08_a02_c3_corrections.py`.
- Fix all E501 long lines (41 lines >88 cols) by line-wrapping; remove unused imports/variables
  (F841) and fix B011 (assertions without message where flagged) properly.
- Use inline `# noqa: <code>` ONLY where wrapping is genuinely impractical and document why;
  prefer real wrapping so coverage stays exact.
- Do NOT weaken assertions or change expected values.
- Result must be `python -m ruff check tests/test_s08_a02_c3_corrections.py tests/test_s08_a02_c2_integrity.py` → 0
  WITH the file-level suppression removed (verify by grep that no file-level `# ruff: noqa:` remains in these files).

### C4-3 — historical query: remove N+1 / unbounded IN-list when no video_item_id
- In `app/persistence/structural_evidence.py::list_historical_segments`, the
  `video_item_id is None` branch currently:
    - selects DISTINCT video_item_id;
    - loops per video calling `current_generation()` (N+1);
    - materializes an unbounded `stale_vids` list and builds `video_item_id.in_(stale_vids)`.
- Replace with a batch/scalable approach, keeping EXACT semantics:
  - business filter stays: superseded OR stale generation (stale = video's current generation != source_generation);
  - `total` = COUNT after filter; `offset/limit` applied after filter; deterministic ordering
    (start_frame, end_frame, z_order, id);
  - must NOT load the full segment history into Python memory;
  - must NOT run one current_generation query per distinct video;
  - must NOT build an unbounded IN-list by number of videos.
- Preferred: one bulk current-generation resolution inside structural_evidence.py (query the
  DISCOVER_OBJECTS completed jobs for the distinct videos once, replicate the
  `_current_generation_for_source` max-gen / latest-for-SHA rule against that one job set),
  then apply stale detection either as a SQL subquery/join over that resolution or a
  bounded set of stale-generation videos; if a genuine need to keep the stale-video set in
  Python, bound it and justify, but the N+1 loop over current_generation MUST go.
- object_intelligence.py is NOT in the allowlist — do not modify it; replicate resolve logic locally in
  structural_evidence.py as needed, or reuse `_current_generation_map` only if it actually removes the
  N+1 (verify: it does NOT — it is a dict-comprehension of per-video calls, so do not use it as the answer).

### C4-4 — focused multi-video test proving no N+1
- Add tests (in `tests/test_s08_a02_c3_corrections.py`) with MULTIPLE videos, mixing
  current/stale/superseded rows, querying `list_historical_segments` WITHOUT video_item_id:
  - assert `total` and the returned page are correct for the mix;
  - prove absence of N+1 by checking the number of SQL statements executed
    (e.g. SQLAlchemy `event.listens_for(Engine, "before_cursor_execute")` counter, or equivalent
    real instrumentation) — the per-video current-generation resolution must not grow linearly
    with the video count;
  - do NOT mock repository behavior. Real SQLite + FK + Alembic.
- Make the test FAIL on the current (pre-fix) code: either statement-count assertion trips, or
  an explicit assertion that current-generation is resolved in a bounded number of queries.

## 6. Allowlist (exact)

- app/persistence/structural_evidence.py
- tests/test_s08_a02_c2_integrity.py
- tests/test_s08_a02_c3_corrections.py
- docs/pm/sessions/S08-A02-T01-C4-hygiene-scalability/ (LOG/REPORT)
- output/s08-a02-t01-c4/

FORBIDDEN without BLOCKED_SCOPE: app/persistence/object_intelligence.py, any other production
file, any other migration, frontend, A02-T02, S07/S09, MAIN, commit/push/merge,
data/motionforge.db, deleting/weakening tests.

If the batch optimization genuinely requires modifying a file OUTSIDE the allowlist
(e.g. object_intelligence.py), STOP: set REPORT.md = BLOCKED_SCOPE, name the file, reason, and
acceptance criterion.  Do NOT widen scope yourself.

## 7. Validation (each separate log + combined; evidence dir NEW output/s08-a02-t01-c4/<ts>/)

- `python -m pytest tests/test_s08_a02_c2_integrity.py -p no:cacheprovider -q`
- `python -m pytest tests/test_s08_a02_c3_corrections.py -p no:cacheprovider -q`
- `python -m pytest tests/test_s08_a02_r1_c1_semantic_safety.py -p no:cacheprovider -q`
- `python -m pytest tests/test_s08_a02_structural_evidence_api.py -p no:cacheprovider -q`
- `python -m pytest tests/test_s08_a02_structural_evidence_migration.py -p no:cacheprovider -q`
- `python -m pytest tests/test_s08_a02_structural_evidence_domain.py -p no:cacheprovider -q`
- `python -m pytest tests/test_s08_a02_phone_interaction_scenario.py -p no:cacheprovider -q`
- Combined: that suite minus c2/c3 duplicated (run c2+c3 first, then the other five, then a
  combined run if within time budget).
- Quality gates: `python -m ruff check app tests` → 0 (and no file-level noqa in the two test files);
  `python -m mypy app` → Success; `python -m alembic heads` → single a0b1c2d3e4f5;
  OpenAPI 9/9 mutating ops typed requestBody.

## 8. Test integrity
- New C4 tests must FAIL on pre-fix code (RED) then PASS (GREEN). Real SQLite/FK/Alembic/repo.
- No mock repository.  No weakening.  Document any corrected old test.

## 9. Do NOT claim PASS if:
- any `except Exception` remains where a tight `pytest.raises` is required;
- any file-level `# ruff: noqa:` remains in the two test files;
- the historical query still does per-video current_generation calls or unbounded IN-list;
- the no-N+1 multi-video test is absent or passes for an unrelated reason;
- evidence empty / counts don't match logs; any focused regression fails.
