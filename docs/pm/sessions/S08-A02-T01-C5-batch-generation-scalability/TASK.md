# S08-A02-T01-C5 — Batch-Generation Scalability Correction (Codex CHANGES_REQUESTED)

Narrow correction responding to Codex CHANGES_REQUESTED on C4 scalability.  Fix the historical
query so it scales to >500 videos WITHOUT the `UNION ALL`/`literal_column` compound-SELECT limit and
WITHOUT unbounded single-statement IN-lists.

## 1. Mandatory model configuration (BLOCKED_MODEL on mismatch)
- Provider: `muse` (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses).
- Model: `ocg/muse-spark-1.2-contributor` (verified; meta/... 401 — do NOT use).
- Reasoning: `max` (config reasoning_overrides + agent.reasoning_effort).
- No fallback.  Mismatch → STOP REPORT.md = BLOCKED_MODEL_ROUTE.
- Record Hermes session ID / model / provider / reasoning / fallback in LOG.md + REPORT.md BEFORE any change.

## 2. Worktree guard
- ONLY `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`; branch `codex/s08-integration`; HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`.
- MAIN protected. Intentional dirty (~206). NEVER reset/clean/stash/restore/checkout/commit/push/merge.
- MOTIONFORGE_DATABASE_URL UNSET; temp isolated SQLite only; `-p no:cacheprovider`; shallow unique `--basetemp`.

## 3. Exact write allowlist (do NOT touch any Lane B file)
- `app/persistence/object_intelligence.py`
- `app/persistence/structural_evidence.py`
- `tests/test_s08_a02_c3_corrections.py`
- `docs/pm/sessions/S08-A02-T01-C5-batch-generation-scalability/`
- `output/s08-a02-t01-c5/`

FORBIDDEN: app/services/object_extraction.py, app/schemas/object_extraction.py,
app/api/routes/object_extraction.py, tests/test_object_extraction*.py, object_extraction DOMAIN
files, any other file, migrations, MAIN, commit/push/merge, data/motionforge.db, deleting/weakening
tests.  If genuinely needed outside → STOP BLOCKED_SCOPE (file, reason, AC).

## 4. Confirmed blocker (current code, pre-writer)
In `app/persistence/structural_evidence.py::list_historical_segments` (video_item_id=None branch):
- xây `literal_column(f"'{v}'")` UNION ALL cho TỪNG stale video (lines ~1762-1780) → SQLite giới hạn
  500 terms compound SELECT → `OperationalError: too many terms in compound SELECT` ở 501 videos.
- 4 unbounded single-statement IN-lists: `VideoItem.id.in_(distinct_vids)` (~1659),
  `Artifact.id.in_(artifact_ids)` (~1674), `Project.id.in_(project_ids)` (~1689),
  `Job.owner_id.in_(distinct_vids)` (~1700) — tăng không giới hạn theo workspace.
- replicate `_current_generation_for_source` locally (duplicate semantics, second source of truth).
- per-video fallback `except Exception → cur_gen=None` (unknown ownership không fail closed).

Also in `tests/test_s08_a02_c3_corrections.py::test_c4_multi_video_no_nplus1`:
- `contextlib.suppress(Exception)` quanh `_advance_generation` (~line 800) — broad-except.
- brittle statement counter đếm cả BEGIN/ROLLBACK.

## 5. Requirements (normative)
1. Xóa `literal_column` và UNION ALL per-video hoàn toàn.
2. KHÔNG nội suy ID trực tiếp vào SQL string (no string f-string of ids in SQL).
3. KHÔNG tạo một SQL statement có số parameters/compound terms tăng không giới hạn.
4. KHÔNG duplicate `_current_generation_for_source` trong structural_evidence — tạo authoritative
   batch-generation API trong `ObjectIntelligenceRepository` (hoặc tương đương có MỘT nguồn semantic
   duy nhất) và dùng nó.
5. Batch/chunk phải có kích thước CỐ ĐỊNH và parameterized (e.g. chunk IN-lists ≤ 900 params
   for SQLite default; use SQLAlchemy bindparams, never string interpolation).
6. `total`/filter/order/pagination phải giữ nguyên semantics: superseded OR stale generation;
   COUNT sau filter; offset/limit sau filter; deterministic ordering (start_frame,end_frame,z_order,id).
7. Unknown/corrupt ownership phải FAIL CLOSED — không `except Exception → current=None`.
8. KHÔNG load toàn bộ historical segment rows vào RAM.

Design hint: một batch current_generation API trong ObjectIntelligenceRepository trả dict
{video_id: gen} cho một SET video (đã có `_current_generation_map` nhưng là per-video dict-comprehension
N+1 — phải thay bằng batch SQL). Chunk tất cả `IN(...)` theo batch cố định; historical filter
`superseded OR video_item_id IN (stale-list-chunks)` với subquery/chunking parameterized.

## 6. Required tests (in tests/test_s08_a02_c3_corrections.py — NEW file allowed here)
- `test_c5_501_stale_videos_no_operational_error`: ≥501 stale videos, `list_historical_segments`
  without video_item_id → NO OperationalError, total == expected, page correct.
- `test_c5_1001_videos_chunking`: ≥1001 videos chứng minh chunking hoạt động (no compound-SELECT limit,
  no N+1, bounded statements).
- `test_c5_mixed_current_stale_superseded_total_page`: mixed current/stale/superseded videos,
  no video_item_id → total + page đúng + deterministic ordering.
- `test_c5_batch_generation_matches_scalar`: batch generation result == scalar `current_generation`
  cho: (a) current source SHA; (b) changed source SHA; (c) no completed job; (d) multiple completed
  generations; (e) wrong workspace (fail closed).
- SQL parameterized check: assert the generated SQL has no raw f-string-injected ids
  (e.g. assert no `literal_column` usage / no user-interpolated string in statements emitted).
- No N+1: bounded statement count (instrument SELECTs only — NOT BEGIN/ROLLBACK).
- Fix flaky: REMOVE `contextlib.suppress(Exception)` around `_advance_generation`; setup deterministic;
  if setup errors the test FAILS immediately; instrumentation counts only relevant SELECTs (or a stable
  assertion). Run the flaky test ≥20 times in a row and all must pass.

## 7. Required reading
- `app/persistence/structural_evidence.py` FULL (list_historical_segments ~1593-1900; create_extraction_segment ~1309)
- `app/persistence/object_intelligence.py` FULL (current_generation ~301-322, _current_generation_for_source ~324-358, _current_generation_map ~360-367)
- `tests/test_s08_a02_c3_corrections.py` FULL (c4 tests ~625-886)
- `docs/pm/sessions/S08-A02-T01-C4-hygiene-scalability/TASK.md` + `REPORT.md`
- `output/s08-a02-t01-r1-c1/ro2-t02-planning.md` (generation authority §8)

## 8. Validation (separate logs in NEW evidence dir output/s08-a02-t01-c5/<ts>/)
- C5 new tests; C4 tests; C3 tests; C2 tests; C1 tests; structural migration/domain/API/phone.
- Combined focused (A02 suites) at least twice.
- Flaky C4 test ×20 runs all pass.
- `python -m ruff check app tests` → 0; `python -m mypy app` → Success; `python -m alembic heads`
  → single a0b1c2d3e4f5; OpenAPI 9/9 typed requestBody intact.
- Cross-process determinism of batch vs scalar via two PYTHONHASHSEED runs (the batch API must be
  deterministic). No migration needed.

## 9. Stop conditions
- Do NOT open other tasks/sprints. Do NOT commit/push/merge. Do NOT write MAIN. SUBMITTED only.
- If blocked → REPORT.md = BLOCKED/BLOCKED_SCOPE/BLOCKED_MODEL_ROUTE.
