# S11-T03F — REPORT (W7)

Task: **W7 · T03F — Full per-video orchestrator + recheck resolution + measured summary**
Branch: `codex/s11/t03f-0903w7` | Parent (WAVE_BASE): `0a7de285e3501ce51a2c934df48c1ca9871ddf40`
Model: `ocg/deepseek-v4-flash` (custom 9Router, reasoning max, fallback off, TTFB 900s)

## Write-set (allowlist — nothing else touched)

| Path | Kind |
|---|---|
| `app/services/qc_checks/orchestrator.py` | NEW — T03F OWNER (run_full_check_set + reopen_stale_evidence + measured summary) |
| `tests/test_s11_t03f_orchestrator.py` | NEW — 14 tests |
| `docs/pm/sessions/S11-T03F/**` | evidence (LOG/REPORT/evidence raw) |

Forbidden surfaces untouched: runner/registry/thresholds, all 10 detector modules,
qc_items repo/routes (import read-only), models.py, migrations/**, frontend/**, MAIN.

## Acceptance criteria (binary) — evidence mapping

### AC1 — One command, full registered set, per-detector results
`test_full_set_one_command_measured_per_detector` + `test_registered_set_is_the_binding_10_reason_codes` PASS.
- 1 orchestrator command on 1 video_item ran **10/10 registered checks** (8 visual/timecode reasons + audio_missing + av_sync_drift); `checks_requested=10, checks_run=10, checks_skipped=0, errors=0`.
- Per-detector measured counts (evidence/measured.txt §1): trajectory_drift 1 (blocker), cut_drift 1 (blocker), audio_missing 1 (blocker), av_sync_drift 1 (warning), 6 detectors pass 0 — **exactly the fixture-manifest expectation computed dynamically** (each detector's own in-process run); DB rows == expected == 4, all open.
- Summary is measured runtime data, JSON-serializable; assert động theo fixture manifest.

### AC2 — Recheck flow + zero path (C2-F2)
`test_recheck_flow_fix_resolves_not_fixed_stays_open`, `test_terminal_resolve_without_evidence_rejected`,
`test_acknowledged_item_still_detected_returns_open`, `test_zero_terminal_status_paths_outside_recheck_lifecycle` PASS.
- Unfixed rerun: `created=0, resolved_after_recheck=0`, items stay `open`.
- Fixed rerun: `resolved_after_recheck=4` (== previously open items), all `resolved`, every resolution carries evidence `{recheck: resolved, recheck_result: pass, run_id, supersedes_item_id, detector}` (raw sample in measured.txt §3); 4th rerun touches nothing.
- Evidence-less terminal attempt (`recheck_resolved(evidence=None)`) → `QCItemEvidenceRequiredError`, item untouched.
- Acknowledged + still-detected → `recheck_failed` → open with `recheck_result: still_detected`.
- **Zero-path scan** (AST + grep over app/): terminal-status WRITES outside {qc_items.py, orchestrator.py} → `[]`; `recheck_resolved/recheck_dismissed` CALLERS outside {owner, orchestrator} → `[]`; every orchestrator recheck call passes `evidence=` (AST-verified). Zero exceptions.

### AC3 — Idempotency ×2
`test_idempotency_x2_zero_duplicates` PASS (measured.txt §2): run2 `created=0, reused=4`; same row set (`same set: True`); distinct natural keys == rows; identical run_id for identical input.

### AC4 — Measured summary, no hard-coded counts
All summary assertions are computed against the fixture manifest (per-detector in-process detect() on the same args) and against the runtime DB state; report counts above are the actual measured values.

### C2-F2 — no_audio_source → not_applicable, ZERO QCItem
`test_no_audio_source_not_applicable_zero_items` PASS (measured.txt §4): REAL T06A1 `build_no_audio_source` media → audio_missing + av_sync_drift `applicability=not_applicable, items_found=0`; summary `not_applicable=2, created=0, errors=0`; **DB rows = 0** (zero QCItem created on the whole run).

### Bounded run — cancel/deadline whole-run
`test_cancel_event_bounds_whole_run_zero_writes`, `test_deadline_bounds_whole_run_invalid_bounds_rejected` PASS:
pre-set cancel → all 10 skipped, 0 runs, 0 rows; `deadline_sec<=0` → `QC_RUNNER_INVALID_ARGS` before any spawn/write; exhausted deadline → checks_run=0, created=0, deadline_exceeded=True, every requested check accounted (machine-independent invariant — see LOG §4 flake).

### GAP-8 — stale-reopen hook (service layer, shared with T04B)
`test_stale_reopen_hook_acknowledged_to_open_stale_flag`, `test_stale_reopen_terminal_item_refused`, `test_run_level_stale_reopen_wiring` PASS:
acknowledged + superseded_by_id/manifest_revision/cast_revision → open with `stale=True` evidence; terminal item refused (`QCItemInvalidTransitionError`, still resolved); run-level `lifecycle_signal` wiring reopens the named item during the run (`reopened_stale=1`, evidence shows `superseded_by_id`).

### Fail-closed extras
Missing args for a registered detector → `QC_ORCHESTRATOR_MISSING_ARGS`, never runs silently; unknown requested detector → error before any spawn; per-detector persist/child failure recorded as error, remaining checks still run (honest summary).

## Test + static gate results (raw)

- T03F suite: **14 passed × 3 fresh roots** (run1 34.86s / run2 34.44s / run3 34.59s; basetemp `%TEMP%/s11t03f_evr*`, `-p no:cacheprovider`, MOTIONFORGE_DATABASE_URL unset).
- Regression combo (T02B repo/API + T03A policy/runner + T03B/C/D/E detectors + T03F + T06A1/A2): **177 passed, 0 failed** (103.77s).
- `ruff check --select F` allowlist files: All checks passed. `py_compile`: OK. `git diff --check`: 0.
- Binding registry set == `QC_REASON_CODES` (10/10, exact names; T03C register() wired at startup layer, orchestrator never mutates registry).

## Isolation

Per-test temp SQLite DB (`create_engine_for_path` + ORM `Base.metadata.create_all`, FK chain via s11_qc_seed); REAL T06A1 media (two_scene_source / multistream_duration_variant / no_audio_source, ffprobe-asserted by builders); env stripped; cache provider off; short unique Windows-native basetemp.

## Commit

- SHA: `4be8616e7ede37f18769ce6d1da4c8b288bea529` (docs record commit: see LOG.md)
- Files: orchestrator.py, test file, docs/pm/sessions/S11-T03F/** — allowlist only.
- No push/merge/rebase; porcelain 0 after commit.

## Verification commands (post-commit, Step 5 gate)

- [x] artifact exists: orchestrator.py + test file
- [x] all checklist items pass on clean re-run (run1..3 + regression)
- [x] no stray files (porcelain == 0)
- [x] TASK_SUBMITTED — evidence: LOG.md + REPORT.md + evidence/*.txt raw