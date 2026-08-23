# S08-A02-T01-C5 — LOG (append-only, local +07:00 / UTC=local-7h)

## 2026-08-20T20:22:00+07:00 / 2026-08-20T13:22:00Z — MANAGER PREFLIGHT (LANE A)
- updater: HERMES MANAGER (ocg/muse-spark-1.2-contributor @ muse, reasoning max, no fallback)
- Worktree: C:\Users\Admin\MotionForge2D-worktrees\s08-integration; branch codex/s08-integration;
  HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204; status ~206; DB UNSET; alembic single a0b1c2d3e4f5;
  MAIN a43b20da (master) protected; no QA listeners.
- Context: Codex CHANGES_REQUESTED for C4 scalability + T02 truthfulness. This is LANE A (C5).
- Baseline hashes (pre-writer):
  - app/persistence/object_intelligence.py = 78c5a5edbf58cba66c0c46960924ecc9b2a2cb4c029a6548609562207786f89b
  - app/persistence/structural_evidence.py = d151d0b91563baa024523cdd6fea6bd173bcc9e7fa14e72a6fd57a82fbd9a991
  - tests/test_s08_a02_c3_corrections.py = 5a145b951cc7705ecdbf3b2d8c7046276ab92f50801c444b4c882c0f6ae6718c
- Confirmed in code: literal_column/union_all per stale video (~1762-1780); 4 unbounded IN-lists (~1659-1700);
  duplicate _current_generation_for_source; suppress(Exception) in test (~800).
- Model route: ocg/muse-spark-1.2-contributor via muse/9Router probe OK.
- Evidence: output/s08-a02-t01-c5/20260820_202100_manager_preflight/

[next: dispatch LANE A writer Muse]

## 2026-08-20T20:31:24.861616+07:00 / 2026-08-20T13:31:24.861616Z — WRITER PROVENANCE (BEFORE ANY CODE CHANGE)
- Hermes session: 20260820_202903_c611af
- Displayed model: ocg/muse-spark-1.2-contributor
- Actual model ID: ocg/muse-spark-1.2-contributor
- Provider: muse (Meta Muse via 9Router http://127.0.0.1:20128/v1 api_mode codex_responses)
- Reasoning: max (agent.reasoning_effort=max + reasoning_overrides={ocg/muse-spark-1.2-contributor: max} real YAML dict verified)
- Fallback: none (no fallback)
- Probe: 9Router 127.0.0.1:20128 probe OK 2026-08-20T20:31+07; model via `muse` provider verified from C:/Users/Admin/AppData/Local/hermes/config.yaml; reasoning_overrides is real YAML dict, fallback empty
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration; branch codex/s08-integration; HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204; status 208 dirty (INTENTIONAL never reset); MOTIONFORGE_DATABASE_URL UNSET; alembic single a0b1c2d3e4f5
- Baseline hashes (pre-C5 writer):
  - app/persistence/object_intelligence.py = 78c5a5edbf58cba66c0c46960924ecc9b2a2cb4c029a6548609562207786f89b
  - app/persistence/structural_evidence.py = d151d0b91563baa024523cdd6fea6bd173bcc9e7fa14e72a6fd57a82fbd9a991
  - tests/test_s08_a02_c3_corrections.py = 5a145b951cc7705ecdbf3b2d8c7046276ab92f50801c444b4c882c0f6ae6718c
- Targets (C5 normative):
  1. Remove literal_column + UNION ALL per-video entirely
  2. No ID string-interpolation into SQL
  3. No unbounded single-statement param/compound count (chunk <=900)
  4. Authoritative batch generation API in ObjectIntelligenceRepository (single source)
  5. Fixed-size parameterized chunking via SQLAlchemy bindparams
  6. Preserve semantics: superseded OR stale-gen; COUNT after filter; offset/limit after filter; deterministic ordering
  7. Unknown/corrupt ownership FAILS CLOSED (no except Exception->None)
  8. No full-history RAM load
- Target checks (prove fail before fix): literal_column present -> FAIL expected; IN(distinct_vids) unbounded present -> FAIL expected; duplicate _current_generation_for_source present -> FAIL expected; except Exception->None present -> FAIL expected

## 2026-08-20T21:15:14.480316+07:00 / 2026-08-20T14:15:14.480316Z — WRITER SUBMITTED (LANE A C5 COMPLETE)
- Evidence dir: output/s08-a02-t01-c5/20260820_205210/ (18 logs, NEW)
- Validation: 01_c5 6 passed, 02_c4 2 passed, 03_c3_all 14 passed, 04_c2 24 passed, 05_c1 51 passed, 06_migration 10 passed, 07_domain 30 passed, 08_api 50 passed, 09_phone 1 passed, 10_combined_1 180 passed, 11_combined_2 180 passed, 12_flaky_x20 20/20 passed, 13_ruff 0, 14_mypy Success, 15_alembic single a0b1c2d3e4f5, 16_openapi 9/9, 17-18 determinism both DET PASS
- Fixes: literal_column/UNION ALL removed, 4 unbounded INs chunked to 900, authoritative batch API (single source _resolve_generation_from_jobs), fail-closed, no RAM load
- Hashes post: oi=6de46d31ff6a..., se=879c9a739e15..., test=b5ee8c7d469e...
- Status: SUBMITTED (never APPROVED) — do NOT commit/push/merge, do NOT write MAIN, blocked_scope none, model route verified

---

## 2026-08-20T22:00:00+07:00 / 2026-08-20T15:00:00Z — MANAGER INTEGRATION GATE (LANE A) — ALL PASS
- writer session 20260820_202903_c611af SUBMITTED; manager re-ran independently (not trusting REPORT alone)
- Manager re-run: C3 (C4+C5) 14 | C2 24 | C1 51 | Mig+Dom+Phone 41 | Struct API 50; Combined 259 (×2)
- Flaky ×20 → 20/20; 501/1001-video repro PASS; batch==scalar matrix + determinism seeds PASS
- ruff 0 | mypy 0 | alembic single | OpenAPI 9/9 | MAIN protected (channels.json hash match, no MAIN src change)
- File ownership: Lane A only touched object_intelligence.py / structural_evidence.py / test_s08_a02_c3_corrections.py
- State: MANAGER_VERIFIED_PENDING_CODEX_REVIEW
