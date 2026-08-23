# S08-A02-T01 — SceneGraph & Structural Evidence Bridge: Implementation Report

**Status:** PLANNED (writer will set to SUBMITTED; manager/Codex review owns approval — never self-approve)
**Hermes session:** NEW — `S08-A02-T01` (s08-integration writer session; never reused `20260819_172534_b0ad63` or any H02/C1 session)
**Model:** deepseek-v4-flash via provider custom:vietapi, reasoning max
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration` @ `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`)
**Task:** S08-A02-T01 — SceneGraph & Structural Evidence Bridge: Domain, Persistence, Migration and API Contract
**writer_started_at_local:** (filled by writer)
**writer_started_at_utc:** (filled by writer)
**writer_finished_at_local:** (filled by writer)
**writer_finished_at_utc:** (filled by writer)
**writer_elapsed_seconds:** (filled by writer)
**manager_review_started / finished:** (filled by manager)
**total_wall_clock_seconds:** (filled by manager)

---

## Hard worktree guard (verified before any write)

- `pwd` / `git rev-parse --show-toplevel` = `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`.
- `git branch --show-current` = `codex/s08-integration`; `git rev-parse HEAD` = `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`.
- `git status --short` count at first writer check: (filled by writer — intentional dirty baseline; NEVER reset/checkout/restore/clean/stash/commit/push/merge).
- Env: `MOTIONFORGE_DATABASE_URL` UNSET and verified at start and finish; no bare `TestClient(app)` (conftest `client` fixture only).
- Migration head at start: `f7a8b9c0d1e2`.

---

## Scope

Per `TASK.md` §5 allowlist (single authorized layout — structural_evidence.*). No file outside the allowlist without a BLOCKED question.

## Findings / implementation

(Writer fills per-AC findings with file:line pointers and run timestamps.)

## Files changed (this round — inside allowlist only)

(Writer lists every modified/created file — backend, schemas, routes, tests, evidence.)

## Validation (verbatim commands + real results; fresh isolated roots; -p no:cacheprovider; shallow basetemps; MOTIONFORGE_DATABASE_URL unset)

(Writer pastes all 12 steps from TASK.md §7/§12 in order, with real integers and Run IDs.)

## Protected-data comparison

(Writer compares HEAD + MAIN hashes at finish — byte-identical.)

## Deviations / limitations

(Writer lists any deviation from TASK.md or known limitation that Codex should know.)

## Session lineage

S08-A01-C1 writer session `20260819_172534_b0ad63` is CLOSED and was NOT reused. This report is from the NEW S08-A02-T01 writer session.

**Status: PLANNED.** No self-approval, no TASK.md/PM_REVIEW.md/commit/push/merge/reset/clean/stash. S07/S09/S08-A02-T02 NOT started. Manager verification owns the next step.

---

## Incident — ABORTED_UNTRUSTED_PARTIAL_OUTPUT

- appended_at_local / utc: 2026-08-19T23:35+07:00 / 2026-08-19T16:35Z (approx)
- appended_by: HERMES MANAGER RECOVERY (recovery handoff, manager-level bookkeeping)

### What happened

- The A02-T01 writer round left the task at **PLANNED** — it never set `SUBMITTED`, never filled
  writer timestamps, never recorded a Hermes session ID, never appended a validation log, and
  produced no `MODEL_QUALITY_DOSSIER`.
- The user confirmed the previous writer/model attempt did NOT meet the required standard, so this
  output is being treated as an **untrusted partial draft**, not a submitted artifact.

### Provenance status

- `REPORT.md` still records model `deepseek-v4-flash` (provider `custom:vietapi`, reasoning `max`),
  but **model provenance cannot be independently verified from the artifacts**: no Hermes session
  ID, no writer timestamps, no validation log, no MODEL_QUALITY_DOSSIER exist for this round.
- Per the user's instruction, this output is **NOT attributed to the DeepSeek baseline**. It must
  not be quoted as DeepSeek evidence anywhere.

### File state (kept as draft for recovery — NOT approved)

- `app/persistence/models.py` — SHA `F633718E0E7C88231641DE165A036B6F6953F22CE18AB2AD6278C54A9758727A`
- `app/persistence/structural_evidence.py` — SHA `D6E1CBCE0C5103AEBF14A6EDB28A062EA4F5970250870A741BD279481F555E5C`
- `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py` — SHA `4A027FC7CC6644901D69675B724922097EEE991EAA2F848B32AA6F1AD6976766`

These files are retained as **recovery drafts** only. They are not approved, not attributed to the
DeepSeek baseline, and are NOT the source of truth for the S08-A02 contract. R1 recovery
(`S08-A02-T01-R1-deepseek-core-recovery`) owns the corrected contract.

### History preservation

This incident is APPENDED, not inserted. All prior A02 REPORT/LOG entries are untouched. No history
was silently rewritten or deleted.
