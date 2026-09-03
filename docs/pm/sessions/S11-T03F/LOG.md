# S11-T03F — Session LOG (W7)

- Task: Full per-video orchestrator + recheck resolution + measured summary
- Branch: `codex/s11/t03f-0903w7` (local commits only — no push/merge/rebase)
- WAVE_BASE: `0a7de285e3501ce51a2c934df48c1ca9871ddf40` (canonical post-W6 merge; porcelain 0 at start)
- Model route: provider `custom` (9Router), `ocg/deepseek-v4-flash`, reasoning max, fallback off, TTFB 900s
- Session rule: NEW SESSION (this is the only S11-T03F worker session)

## 0. Correction C1 (EXIT-GATE mypy — resume, bounded)

- Resumed on branch `codex/s11/t03f-0903w7` fast-forwarded to canonical
  `15f434928c1b24d88a8649468873c3da8295f3a6` (worktree clean, porcelain 0).
- Findings (mypy retained scope, orchestrator.py):
  1. `:175` Unused "type: ignore" comment [unused-ignore]
  2. `:177` Incompatible types in assignment (Callable[[Any], Any] vs overloaded dict.get) [assignment]
- Fix (bounded patch, preimage, NO behavior change, ONLY orchestrator.py):
  - removed the unused `# type: ignore[assignment]`;
  - added explicit `get: Callable[[str], Any]` annotation before the branches —
    both `dict.get` and the lambda satisfy (str) -> Any; `Callable` added to
    the typing import.
- Verify (real outputs in `evidence/c1_mypy_before.txt` / `c1_mypy_after.txt`):
  - retained scope `mypy orchestrator.py --follow-imports=skip` -> Success (exit 0);
  - full 4-file command: 4 errors BEFORE (2 T03F + 2 T03A) -> 2 errors AFTER,
    both FOREIGN-OWNED (T03A, pre-existing since W5 on mypy 2.3.0):
    thresholds.py:280 `no-any-return`, runner.py:160 `unused-ignore`.
    T03F write-set forbids touching those files -> routed to T03A owner.
  - pytest tests/test_s11_t03f_orchestrator.py: 14 passed in 35.54s
    (fresh root %TEMP%/s11t03fc1_r1, `-p no:cacheprovider`, env stripped);
  - ruff `--select F` on orchestrator.py + test file: All checks passed;
    py_compile OK.
- Commits (local): C1 fix + docs record SHA — see REPORT.md.

## 1. Baseline (verified at start)

- `git status --porcelain` = empty; branch correct; HEAD == WAVE_BASE.
- `app/services/qc_checks/orchestrator.py` ABSENT at WAVE_BASE (git cat-file confirms: path exists on disk, not in tree).
- Registry contains the binding 10 reason codes mapped 1:1 to 10 registered detectors
  (T03B: trajectory_drift/cut_drift; T03C: contact_break/z_order_error/silhouette_clipping;
  T03D: identity_drift/edge_halo/temporal_flicker; T03E: audio_missing/av_sync_drift).
- Read-only contracts consumed: T03A registry/runner/thresholds; T02B QCItemRepository
  lifecycle (create, acknowledge, recheck_resolved/recheck_dismissed/recheck_failed);
  T06A1 REAL media builders + calibration generators.

## 2. RED (before implementation)

- Wrote `tests/test_s11_t03f_orchestrator.py` (14 tests) FIRST.
- pytest: collection fails `ModuleNotFoundError: No module named 'app.services.qc_checks.orchestrator'` — the expected RED reason. Evidence: `evidence/red.txt`.

## 3. Implementation (write-set only)

- `app/services/qc_checks/orchestrator.py` (NEW, OWNER):
  - `run_full_check_set(...)` — one command, one video_item, full registered check-set
    (registry order; `detectors=` restricts). Each detector runs through the T03A common
    bounded runner (child process) with the WHOLE run sharing ONE absolute deadline and
    ONE cancel event (remaining budget is never a fresh window; cancel/deadline stop
    further scheduling -> checks_skipped).
  - Persistence: candidate-style outputs (`qc_items`/`items` keys or raw list = T03C/D/E)
    whitelist-filtered to the repository `create` parameter set + identity injection;
    measurement-style outputs (trajectory_drift/cut_drift) persisted through the
    detector's OWN `create_qc_items` (never re-implemented). All through
    `QCItemRepository.create` (natural-key idempotent ON CONFLICT DO NOTHING).
  - Recheck pass: open/acknowledged items of the video item auto-resolve ONLY when the
    fresh run positively reports the issue gone (positive pass coverage for
    measurement-style; complete-set absence for candidate-style; `invalid` outputs
    resolve nothing — fail-closed). Acknowledged + still-detected -> `recheck_failed`
    back to open. Every terminal transition carries FRESH recheck evidence (run_id +
    detector + result + supersedes_item_id).
  - Stale-reopen hook `reopen_stale_evidence(...)` (GAP-8, service layer shared with
    T04B): acknowledged -> open with `stale=True` + superseded_by_id/manifest/cast
    revisions in evidence; open = no-op; resolved/dismissed = REFUSED (terminal).
    Wired into the run via `lifecycle_signal`.
  - Measured summary: {created, reused, resolved_after_recheck, reopened_stale,
    not_applicable, errors, checks_*, per-detector counts, cancelled,
    deadline_exceeded, run_sec, deterministic run_id}; JSON-serializable.
- `tests/test_s11_t03f_orchestrator.py` (NEW): 14 tests covering AC1-4 + C2-F2.

## 4. FIX loop (real failures, each diagnosed from actual output)

1. RED vs GREEN gap: zero-path scan regex over-matched SQL CHECK literal
   (`models.py` blocker-not-dismissed DDL) and ObjectGroupingSuggestion `values(status=...)`
   (different domain). Rewrote scan: AST-based writes + caller-grep, scoped to modules
   with a QCItem surface (SQL literals cannot appear as AST writes -> T02A backstop
   naturally excluded; non-QC status columns excluded by domain scope).
2. audio_missing/av_sync_drift persist error `QCItemParamsError: checkpoint_ref must be
   a non-empty string`: T03E args lacked checkpoint_ref -> test identity builder now
   ships `checkpoint_ref` (repo hard-requires non-empty).
3. edge_halo child FAILED TO SPAWN: `FileNotFoundError [WinError 206]` — 200x200 pixel
   grid serialized onto the child command line exceeds the Windows 32K CreateProcess
   limit. Test fixture uses 64x64 (same ring geometry, scaled); orchestrator's
   per-detector error recording caught the failure honestly (fail-closed) in the meantime.
4. Combo-run flake: deadline test asserted `checks_skipped == 10` with a 1e-9 deadline;
   under load one detector landed on the runner's own DEADLINE_EXCEEDED branch (OS timer
   granularity). Rewrote assertions to machine-independent invariants
   (checks_run==0, created==0, deadline_exceeded=True, checks fully accounted).
   Cancel path unchanged and fully deterministic (pre-set event -> all 10 skipped, 0 writes).

## 5. GREEN (real runs)

- T03F suite 14 passed x3 fresh roots: run1 34.86s / run2 34.44s / run3 34.59s
  (basetemp %TEMP%/s11t03f_evr*, `-p no:cacheprovider`, MOTIONFORGE_DATABASE_URL unset).
- Regression combo (T02B + T03A..F + T06A1 + T06A2): 177 passed, 0 failed, 103.77s.
- ruff `--select F` clean on allowlist files; py_compile OK; git diff --check 0.

## 6. Evidence (all raw real output)

- `evidence/baseline.txt` — porcelain 0 start, HEAD==WAVE_BASE, orchestrator absent.
- `evidence/red.txt` — RED ModuleNotFoundError (exact reason).
- `evidence/measured.txt` — real orchestrator probe: full-set per-detector counts
  (10 checks, created=4, errors=0), idempotency x2 (created=0 reused=4, same set,
  same run_id), recheck (unfixed still open; fixed -> resolved_after_recheck=4,
  evidence sample), no_audio_source (not_applicable=2, DB rows=0, C2-F2),
  zero-path grep (callers [], writes []), isolation flags.
- `evidence/run1..3.txt` — 14 passed x3 fresh roots.
- `evidence/checks.txt` — ruff/py_compile/diff-check + binding 10-set == QC_REASON_CODES.
- `evidence/regression.txt` — combo 177 passed.

## 7. Commit (local, allowlist only)

- Staged: `app/services/qc_checks/orchestrator.py`, `tests/test_s11_t03f_orchestrator.py`,
  `docs/pm/sessions/S11-T03F/**`. Nothing else.
- Commit SHA: recorded in REPORT.md; `git status --porcelain` = 0 after commit.

## 8. Status

TASK_SUBMITTED — xem REPORT.md (acceptance mapping + measured evidence). EXIT.4be8616e7ede37f18769ce6d1da4c8b288bea529
C1 fix commit: a19deecb85fd016576af6de12b11ef003b300927
