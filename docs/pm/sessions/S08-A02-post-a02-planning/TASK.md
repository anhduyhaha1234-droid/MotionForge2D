# S08-A02 Post-A02 Planning — READ-ONLY (LANE C)

Read-only planning lane to prepare the post-A02 work.  Does NOT modify production or test code.
Does NOT create an official sprint/task packet.  Does NOT dispatch implementation.

## 1. Mandatory model configuration (BLOCKED_MODEL on mismatch)
- Provider: `muse` (Meta Muse via 9Router — base_url http://127.0.0.1:20128/v1, api_mode codex_responses).
- Model: `ocg/muse-spark-1.2-contributor` (verified; meta/... 401 — do NOT use).
- Reasoning: `max`. No fallback. Mismatch → STOP REPORT.md = BLOCKED_MODEL_ROUTE.
- Record Hermes session ID / model / provider / reasoning / fallback in LOG.md + REPORT.md.

## 2. Worktree guard
- ONLY `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`; branch `codex/s08-integration`;
  HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`. MAIN protected. Intentional dirty (~208).
- MOTIONFORGE_DATABASE_URL UNSET. NO tests run, NO code edited, NO migrations.

## 3. Write scope (EXACT — the ONLY files this lane may create)
- `output/post-a02-planning/<run-id>/AUTHORITY.md`
- `output/post-a02-planning/<run-id>/DEPENDENCY_DAG.md`
- `output/post-a02-planning/<run-id>/PARALLELIZATION.md`
- `output/post-a02-planning/<run-id>/NEXT_SPRINT_DRAFT.md`
- `docs/pm/sessions/S08-A02-post-a02-planning/LOG.md` + `REPORT.md` (lane evidence)

## 4. Read authority (do not roam beyond these + their direct references)
- `docs/pm/ROADMAP.md`
- `docs/pm/sprints/S08-SPRINT_CONTRACT.md`, `S08-SPRINT_REPORT.md`
- All S08-A02 packets/reports:
  - `docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/`
  - `docs/pm/sessions/S08-A02-T01-C1/... C2/... C3/... C4/... C5/... C6/`
  - `docs/pm/sessions/S08-A02-T02-extraction-evidence-wiring/`
  - `docs/pm/sessions/S08-A02-T02-C1-truthful-deterministic-evidence/`
- `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md`
- `output/MANAGER_STATE.md`, `output/OVERNIGHT_HANDOFF.md` (directly-referenced planning)
- Any doc the above reference DIRECTLY (e.g., RO-2 plan, source-locked target profile).

## 5. Objectives
1. **A02 closeout gates**: list what Codex must approve to close A02 (C5, C6, T02-C1, T02-C2 verdicts;
   manager verify; one migration head; combined suites; protected hashes).
2. **Next sprint/task authority**: does the roadmap/contract give authority for the next task/sprint?
   Search ROADMAP for S09 (Demo-first reskin) / S07 (Project cast reuse) / any post-A02 item.
3. **If authority exists**, define for each: outcome; task decomposition; dependency DAG; exact file
   ownership; migration owner; integration gate; which tasks may run in parallel.
4. **Propose a safe max concurrency level** given the worktree/ownership constraints.
5. Do NOT create official sprint/task packet. Do NOT dispatch.
6. **If authority is missing**, list exactly the user decisions needed (one decision per item), and end
   `BLOCKED_NEXT_SPRINT_AUTHORITY`.

## 6. Output contract
- `AUTHORITY.md`: what is authorized today vs. what is gated on Codex/user decisions (cite file:line).
- `DEPENDENCY_DAG.md`: tasks + edges (depends-on / blocks), serial vs parallel, migration owner.
- `PARALLELIZATION.md`: proposed lanes with exact non-overlapping file ownership + max concurrency.
- `NEXT_SPRINT_DRAFT.md`: a READY-TO-REVIEW draft (NOT an official packet) of the next sprint contract,
  anchored to authoritative sources.
- End state: `POST_A02_PLAN_DRAFT_READY` or `BLOCKED_NEXT_SPRINT_AUTHORITY` (in REPORT.md).

## 7. Mandatory reading discipline
- Do not write to any file under `app/`, `tests/`, `migrations/`, `docs/pm/sessions/*/TASK.md` etc.
- Only the four output docs + lane LOG/REPORT may be written.
- No commit/push/merge. No MAIN writes.

## 8. Stop
- End with REPORT.md = SUBMITTED (manager/Codex own approval). Mark end state as
  `POST_A02_PLAN_DRAFT_READY` or `BLOCKED_NEXT_SPRINT_AUTHORITY` with the exact missing decisions.
