# S08-R01 — REPORT

**Status:** SUBMITTED (never APPROVED — manager/Codex review owns approval)
**Task:** S08-R01 — Runtime Lifecycle Safety (new Task ID, fresh session)
**Session:** 20260816_225849_3788f0
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`
**Branch / base:** `codex/s08-integration` @ `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`

## Outcome

The GENERIC durable-job lifecycle is fixed (not S08-handler-specific):

1. A cancel arriving while a Job is still `queued` now reaches terminal
   `cancelled` deterministically with zero handler effects — no pending
   forever-state. Three independent engine paths guarantee it:
   - the durable WORKER's claim scan falls back to unleased
     `cancelling` Jobs and drains them (zero effects, lease released);
   - the RECONCILER resolves unleased `cancelling` Jobs directly to
     terminal `cancelled` (no worker needs to be alive, no lease is
     ever created);
   - RESTART: the lifecycle's startup reconcile resolves any pre-cancel
     Job before the fresh worker polls, and the fresh worker drains any
     remainder.
2. Preserved: idempotent second cancel (`cancelling` → True, terminal →
   False), running-cancel drain (existing S05 paths untouched),
   completion/cancel race (first committed writer wins; `cancel_job`
   now re-reads over a bounded window instead of surfacing a spurious
   conflict), fencing, retry, restart and immutable terminal history
   (all terminal rows still never transition; the fix only adds new
   active→terminal drains).
3. Explicit regression added: create queued Job → cancel before worker
   claim → worker / reconciler / restart → `cancelled`, zero effects, no
   orphan lease.
4. DISCOVER_OBJECTS and RECOMPUTE_OBJECTS are covered by the same
   generic fix (tests prove the real registered handlers never run and
   zero object/occurrence/artifact rows exist).
5. The default managed artifact root resolves from the CONFIGURED
   absolute project root (`<project root>/artifacts`) — never the
   process CWD. Worker, reconciler, chain orchestrator, APIs and job
   manifests all use the same public `JobService.managed_root` /
   session factory (S05-C04 binding preserved).
6. QA/test fail-closed: in QA mode (`MOTIONFORGE_QA_MODE=1`) or under
   pytest, the effective roots must be explicit, absolute and isolated —
   the protected MAIN root and CWD-relative roots are rejected with a
   stable error before any file/DB side effect.
7. QA launchers no longer rely on `cd` for storage correctness (env
   inline roots place DB + artifacts under the run root regardless of
   CWD — proven by test).
8. Pristine `app.main:app` lifecycle and S05-C03/C04 wiring preserved
   (fresh-process generations pass; binding tests pass).

## Changed files

| File | Change |
|---|---|
| `app/config.py` | `PROTECTED_MAIN_ROOT`, QA-mode flag, pytest detection, `validate_runtime_roots()` fail-closed guard |
| `app/workflow/job_service.py` | default managed root from config root; fail-closed validation; `cancel_job` bounded re-read/retry |
| `app/workflow/durable_worker.py` | queued-cancel drain claim (`cancel_drain` marker, zero effects, atomic lease release + post-heartbeat re-release); drain decided from live claim-time state |
| `app/workflow/job_reconciler.py` | unleased `cancelling` → terminal `cancelled` resolution; drain-marker recognition on fence (cancel wins over requeue) |
| `app/api/deps.py` | `get_managed_root()` fallback from configured root (validated) |
| `tests/test_s05_orchestrator_binding.py` | S05-C04-R3 updated to the new absolute default-root contract (wiring assertions unchanged) |
| `tests/test_s08_r01_queued_cancel_lifecycle.py` | NEW — 7 regression tests (AC1–AC4) |
| `tests/test_s08_r01_root_resolution.py` | NEW — 11 root/fail-closed/launcher tests (AC5–AC7) |
| `docs/pm/sessions/S08-R01-runtime-lifecycle-safety/LOG.md`, `REPORT.md` | this packet evidence |

No changes outside the allowed write scope. No commit/push/deploy/
reset/checkout/restore/clean/stash/delete.

## Acceptance evidence (per AC, real commands — see LOG.md §5)

- **AC1 (queued-cancel deterministic terminal, zero effects, no orphan
  lease):** `test_queued_cancel_worker_claim_drains_zero_effects_no_orphan_lease`,
  `test_queued_cancel_reconciler_resolves_zero_effects_no_lease`,
  `test_queued_cancel_restart_fresh_worker_drains` — job `cancelled`,
  handler runs = 0, staging files = [], attempt rows = [], lease
  released/absent. PASS.
- **AC2 (idempotent second cancel, running-cancel drain, races,
  fencing, retry, restart, terminal immutability):**
  `test_second_cancel_idempotent_then_terminal_cancel_rejected`,
  `test_cancel_racing_worker_claim_cancel_wins` + the full existing S02
  durable suites (`test_durable_worker` 32, `test_job_reconciliation`
  24, `test_durable_job_api` 15, `test_durable_job_persistence` 48) and
  S05 suites (`test_s05_atomic_cancel` 4, `test_s05_chain_progression`
  6, lifecycle/orchestration/golden 24, production wiring 1, services
  111). PASS.
- **AC3 (explicit regression):** the three legs above (worker claim /
  reconciler pass / restart with fresh engine+factory+worker). PASS.
- **AC4 (DISCOVER_OBJECTS + RECOMPUTE_OBJECTS via the generic fix):**
  `test_discover_objects_queued_cancel_zero_effects`,
  `test_recompute_objects_queued_cancel_zero_effects` — real registered
  handlers, zero durable effects (object_role/occurrence/artifact
  counts unchanged), no staging files. PASS.
- **AC5 (single public root):**
  `test_default_managed_root_from_configured_project_root_not_cwd`,
  `test_deps_get_managed_root_fallback_uses_configured_root`,
  `test_worker_orchestrator_manifest_share_public_service_root` +
  updated S05-C04-R3 binding test. PASS.
- **AC6 (QA/test fail-closed):**
  `test_test_mode_rejects_default_main_config`,
  `test_test_mode_rejects_relative_managed_root`,
  `test_test_mode_accepts_explicit_isolated_roots`,
  `test_qa_mode_rejects_protected_main_root`,
  `test_qa_mode_rejects_relative_project_root`,
  `test_qa_mode_requires_explicit_env_root`. PASS.
- **AC7 (launcher without cd):**
  `test_qa_launcher_without_cd_resolves_isolated_root` — QA mode + env
  roots, CWD elsewhere: DB at `<run root>/data/motionforge.db`,
  artifacts under `<run root>/artifacts`, nothing under CWD. PASS.
- **AC8 (pristine app.main:app + S05-C03/C04):** `test_s05_production_wiring`
  (4 fresh-process generations, 1 test) + `test_s05_orchestrator_binding`
  (2) + S05 lifecycle/orchestration/golden (24). PASS.

## Tests and commands (final battery, cache disabled, shallow basetemps)

```
python -m pytest tests/test_persistence_bootstrap.py tests/test_api.py
  tests/test_durable_job_persistence.py tests/test_durable_job_api.py
  tests/test_durable_worker.py tests/test_job_reconciliation.py
  tests/test_s05_orchestrator_binding.py
  tests/test_s08_r01_queued_cancel_lifecycle.py
  tests/test_s08_r01_root_resolution.py -q -p no:cacheprovider
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08r01-final-core
  -> 204 passed in 136.05s

python -m pytest tests/test_s05_atomic_cancel.py tests/test_s05_chain_progression.py
  tests/test_s05_lifecycle.py tests/test_s05_orchestration.py
  tests/test_s05_golden_integration.py tests/test_s05_production_wiring.py
  tests/test_video_import.py tests/test_timebase.py
  tests/test_scene_detection.py tests/test_video_proxy.py
  -q -p no:cacheprovider --basetemp=C:/Users/Admin/AppData/Local/Temp/s08r01-final-s05
  -> 150 passed in 164.28s

python -m pytest tests/test_object_intelligence_domain.py
  tests/test_object_extraction.py tests/test_object_extraction_api.py
  tests/test_object_extraction_production_wiring.py tests/test_object_grouping.py
  tests/test_object_correction.py tests/test_object_correction_api.py
  tests/test_s08_golden_object_intelligence.py -q -p no:cacheprovider
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08r01-final-s08
  -> 137 passed in 105.13s

python -m pytest tests/test_character_domain.py tests/test_character_preset_importer.py
  tests/test_character_read_api.py tests/test_character_validator.py
  tests/test_publish_rejection.py -q -p no:cacheprovider
  --basetemp=C:/Users/Admin/AppData/Local/Temp/s08r01-s06
  -> 90 passed in 56.33s

python -m ruff check app tests      -> All checks passed!
python -m mypy app                  -> Success: no issues found in 86 source files
git diff --check                    -> exit 0 (pre-existing CRLF advisories only)
```

## Protected-data comparison

- MAIN `channels.json` SHA-256:
  `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555`
  — identical to the baseline. UNCHANGED.
- MAIN `data/motionforge.db`: 311296 bytes — identical to the baseline.
  UNCHANGED.

## Deviations / notes for the manager and Codex

1. Contract-actor note (documented, engine-level): for a never-claimed
   `cancelling` Job the drain is performed by the worker (contract actor
   "worker") or by the reconciler as an authority actor (same actor the
   existing `fenced → cancelled` CANCEL_REQUESTED path already uses).
   Both pass through a `running` transition marked with a durable
   `cancel_drain` event detail — required because the schema CHECK
   `ck_job_finished_requires_started` forbids a terminal write without
   `started_at`, and `running` is the only transition that sets it. The
   reconciler's marked-running → cancelled pair commits in ONE
   transaction (never observable separately); the worker's is a real
   claim (observable as a brief `running` during the drain).
2. `_cancel_drain` release behavior: the NEW drain-claim path releases
   its lease atomically with the terminal transition (plus a defensive
   re-release after the heartbeat thread is joined). Existing
   running-cancel drains keep their previous lease behavior — no S05
   assertion was altered.
3. `tests/test_s05_orchestrator_binding.py` S05-C04-R3 was updated
   because it pinned the OLD CWD-relative default (`Path("artifacts")`)
   that AC5 explicitly replaces; the wiring/fail-closed/isolation
   assertions were preserved and extended (CWD now provably irrelevant).
4. Reconciliation of a drained Job leaves its never-run steps `pending`
   (the reconciler never mutates step state outside fence-rollback —
   identical to the existing CANCEL_REQUESTED fence path). The worker
   drain marks every step `cancelled` along the §4.4 chain.

## End state

SUBMITTED — Hermes stops here. No commit/push/deploy/reset/checkout/
restore/clean/stash was performed; manager verification (then Codex
sprint review) owns the next gate.

SUBMITTED
