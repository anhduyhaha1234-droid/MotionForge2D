# S07 — SPRINT CONTRACT — Project Cast Reuse

- sprint: S07
- epic: E04 — Character Library and Cast Mapping (docs/pm/ROADMAP.md:132-158)
- started_via: user-provided HERMES MANAGER authority (2026-08-21) after Codex APPROVED S08-A02 bundle (C5/C6/T02-C1/C2; independent targeted 90 passed; ObjectRole/E05 contract eligible)
- worktree: C:\Users\Admin\MotionForge2D-worktrees\s08-integration (branch codex/s08-integration, base HEAD a43b20da742996bafcb2f9d1ac57b10d3f1a5204)
- MAIN protected: C:\Users\Admin\MotionForge2D (never modify; no test may write into MAIN)
- model: EVERY writer/reviewer → provider muse, model ocg/muse-spark-1.2-contributor, reasoning max, fallback disabled
- created_local/utc: 2026-08-21T01:12:00+07:00 / 2026-08-20T18:12:00Z

## 1. Outcome
User maps a Project Object Role to an immutable Character Pack Version. Later Character Library
edits or publishing a new Pack Version must NOT silently change an existing Project Cast Mapping.

Provides: durable Project Cast Mapping; immutable Pack Version pinning; workspace isolation;
deterministic compatibility policy; explicit compatibility warnings; idempotency; optimistic
revision/CAS; cross-project reuse; version isolation; Scenario I acceptance evidence.

## 2. Out of scope
reskin transform/compositing; demo loop; full apply; QC; audio; 4K; character generation; renderer/
dense flow; S09+; changing S08 extraction/grouping/correction core.

## 3. Dependency DAG (strict — do not break)
```
S07-T01 → S07-T02 → S07-T03 → S07 SPRINT REVIEW GATE → STOP FOR CODEX REVIEW
```
One production writer active at a time. No parallel T01/T02/T03.

Parallel read-only (allowed while a production writer runs, max 2 review lanes + 1 BA lane):
- S07-RO1 — domain/persistence review
- S07-RO2 — API/UI/test-strength review
- S11-T01-BA-PREFLIGHT (read-only; verdict SAFE_TO_PARALLELIZE_WITH_EVIDENCE or MUST_WAIT_WITH_EVIDENCE; NO S11 code)

## 4. Tasks
| Task | Session outcome | Depends |
|---|---|---|
| S07-T01 | Project Cast Mapping domain/API pins Object Role → immutable Pack Version | S06 exit + E05 contract (both acquired) |
| S07-T02 | In-context library picker + compatibility warnings | S07-T01 MANAGER_VERIFIED |
| S07-T03 | Cross-project reuse + version isolation integration/acceptance (Scenario I) | S07-T02 MANAGER_VERIFIED |

## 5. Session / correction rules
- One Task ID = one owning writer session. Each task its own session.
- Correction of the SAME task: resume the owning session (same model Muse max). No new correction session.
- T03 discovering a production defect: T03 never edits production; Manager sends repro to owning T01/T02 session; after fix, resume T03 to re-verify.
- Recovery session ONLY if old dead/unresumable/corrupt with evidence; log recovery reason + last confirmed state; never two writers owning a task.

## 6. Terminal state
Tasks: writer SUBMITTED → manager MANAGER_VERIFIED (only after independent review/gates).
Sprint: SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW. NEVER APPROVED/CLOSED/CODEX_APPROVED by Hermes.
Stop all S07 lanes; verify clean ports/processes/session lineage; hand off to Codex.

After S07 terminal: do NOT create S09/S11 contracts/packets/dispatch. Codex decides next sprint/task.

## 7. Quality gates (per task + final)
ruff app tests 0; mypy app 0; one Alembic head; git diff --check 0; frontend (T02/T03) typecheck,
eslint, build; Playwright desktop + 390px; PRAGMA foreign_key_check 0; protected data/hashes unchanged
(channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555, motionforge.db 311296 B
unless intentional migration — then backup-verified); fresh quality baseline 7/7; NO_LISTENERS/process cleanup.
