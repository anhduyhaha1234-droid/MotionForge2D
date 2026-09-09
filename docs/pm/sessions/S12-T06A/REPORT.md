# S12-T06A REPORT — C2 (F09 closure: staged package + process-identity safety)

Status: **TASK_SUBMITTED** | Date: 2026-09-09 | Worker: T06A owner
Branch: `codex/s12/s12-t06a-0907a` | Baseline: `6fc6aef` | No merge/push.

## F09 closed (review finding, owner T06A)

- Launcher no longer runs from REPO: staged package root derived from
  `__file__`, backend cwd = `<pkg>/backend`, frontend via staged
  node_modules `next start` (no npx, no dev checkout).
- Manifest no longer records Admin tool paths (toolchain = versions
  only) and has REAL locked dependency versions (scoped-aware, no null).
- Process metadata binds PID + creation time + executable + command +
  ownership token; stop refuses reused/wrong PIDs (evidence retained +
  nonzero), failed stop keeps evidence and returns nonzero.
- Default uninstall keeps user data; data removal requires explicit
  `--confirm-remove-data`.
- Endpoint baked at real build boundary (NEXT_PUBLIC_API_URL rebuild);
  wrong endpoint fails closed. Manifest describes external runtimes
  honestly; the package is a STAGED build, never labelled portable.

## Row statuses

- C23 staged package outside checkout + real lifecycle: **GREEN (local)**;
  clean-VM counterpart **NOT_RUN** (no clean VM; exact missing env
  recorded, never waived).
- C24 packaged build/runtime/dependency hashes + pins verified;
  tamper/missing runtime/wrong endpoint FAIL; no secrets/Admin paths:
  **GREEN** (build_id ilMFXRHX0rRYMrBt7RD0E, 17 backend exact pins,
  17 frontend real locks; live negatives: BLOCKED_MANIFEST_STALE,
  BLOCKED_WRONG_ENDPOINT, BLOCKED_NODE_MISSING/FFMPEG_MISSING; grep
  Admin paths 0).
- C25-part process identity + qa-root guard + data retention:
  **GREEN** (T06A half; T05 half owned by T05 — root-deletion guard in
  F10 fix belongs to T05's boot.py).

## Live evidence (real numbers)

- Stage: STAGE_EXIT 0, build ilMFXRHX0rRYMrBt7RD0E, ports 8426/3126.
- Lifecycle from staged root: setup 0; serve 0 (backend 11748 /health
  200, frontend 14832 / + /export 200, identity creation times
  captured); diagnose READY 6/6 (identity verified both); stop 0 (both
  ports down, pids cleared); uninstall 0 (data preserved); no-keep
  without confirm -> exit 3, data preserved.
- Tests: tests/s12/s12-t06a/ 17 passed (isolated temp roots).
- Gates: ruff --select F scripts/s12/ tests/s12/s12-t06a/ All checks
  passed; git diff --check 0; py_compile OK; porcelain allowlist only.

## For Manager / Codex (substance)

- 5 pre-existing collection errors in tests/s12 (duplicate
  test_c1_closure.py under s12-t02/t03b/t03c/t04a) remain; NOT owned by
  T06A. T06A dir collects + passes independently.
- Clean-machine external acceptance stays NOT_RUN (missing clean Windows
  VM; no waiver) — beta/release remains blocked on it and C29.
- Evidence: `<C2-root>/s12-t06a/` (evidence_index.md + stage/runtime
  logs) and `<C2-root>/matrix/C23-C24-C25.md`.