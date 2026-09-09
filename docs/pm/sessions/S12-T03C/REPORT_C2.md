# S12-T03C C2 REPORT — normal API/worker/recovery/publication

Status: **TASK_SUBMITTED** | Branch `codex/s12/s12-t03c-0907a` @ (see commit SHA)
Baseline `da7108b` | No push/merge | Model `ocg/deepseek-v4-flash` fallback OFF.

## Evidence (real numbers)

- T03C suite: **30 passed** (~37–40s, isolated `%TEMP%` basetemp, fresh migrated DBs; includes real ffmpeg render).
- Regression T03A + T03B: **92 passed** (~117s, real media) — frozen lanes untouched.
- `ruff check --select F` (4 prod + 2 wiring + tests): All checks passed.
- `git diff --check`: clean (exit 0).
- Porcelain: allowlist only — 4 prod (jobs/route/publication/lifecycle) + 2 prior wiring kept + 3 test files updated + 1 new closure file + 2 docs.

## Row status (T03C C2 scope)

| Row | Status | Basis |
|---|---|---|
| C01 | PASS | mounted API + registered handler; 1 valid submit → 1 run + 1 Job, non-null IDs, server-owned paths |
| C04-part | PASS | real authority stale → 409 zero rows; real readiness not_run → 409 zero rows |
| C05 | PASS | non-media/partial/traversal/spoof → 0 mutation (helper + real route) |
| C07-part | PASS | union replay converges 1 run/1 job; same-key material drift → conflict, 0 extra rows |
| C09 (consumer) | PASS | publish re-checks live fence; expired-lease reconcile zero-mutation; stale token cannot publish |
| C14-part | PASS | expired lease → resumable report; fresh claim wins new fence (consumer side) |
| C15 | PASS | cancel winner + 409; retry converges ≤1 run; job/run states agree |
| C16 | PASS (bounded) | real worker render + real publication + real validator: no TypeError, no double assembly, coherent `failed` on NOT_MEASURED; positive PASS depends on T04A digest authority (reported) |
| C17/C18 (consumer) | PASS (bounded) | fence re-check mid-publication + atomic rename + sidecar bytes + partials never public + tampered replay fails |

## Key artifacts

`app/workflow/s12_export_jobs.py` handler→publish real caller + failure coherence; `publication.py` candidate boundary + byte sidecar + single-winner CAS; `routes/s12_export.py` F02 authority-gated submit + real job_id + server paths; `lifecycle.py` startup reconcile caller. Evidence: `<C2-root>/s12-t03c/{pytest_t03c.txt,ruff_F.txt,diff_check.txt,porcelain.txt}`.