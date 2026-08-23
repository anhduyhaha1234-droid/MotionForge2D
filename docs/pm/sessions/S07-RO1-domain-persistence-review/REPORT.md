# S07-RO1 — Domain & Persistence Review: Report

**Status:** SUBMITTED (read-only review; never APPROVED — manager/Codex consume findings)  
**Reviewer:** S07-RO1 — Domain & Persistence (READ-ONLY)  
**Run ID:** `20260821_020000`  
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` — branch `codex/s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204`  
**Base HEAD:** `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` (dirty S08 base ~211, not tidied)  
**Model:** provider `muse`, model `ocg/muse-spark-1.2-contributor`, reasoning `max`, fallback `disabled` — **VERIFIED PASS** (no BLOCKED_MODEL_ROUTE; this session runs as `ocg/muse-spark-1.2-contributor`)  
**Started local / UTC:** `2026-08-21T01:58:00+07:00 / 2026-08-20T18:58:00Z`  
**Ended local / UTC:** `2026-08-21T02:01:00+07:00 / 2026-08-20T19:01:00Z`  

## Scope

Read FULLY: `docs/pm/sessions/S07-RO1-domain-persistence-review/TASK.md` + `docs/pm/sessions/S07-T01-project-cast-domain-api/TASK.md` (§5 required behaviors 1–17, §7 design guidance, §6 write allowlist). Reviewed Project Cast Mapping domain/persistence **as it lands + final state at `a43b20d`** — schema/FK/migration, workspace isolation, idempotency, revision/CAS, immutable version pin, cross-workspace enforcement, atomic rollback, deterministic serialization — while S07-T01 writer runs (PID 23588, `output/s07-t01/20260821_011600_writer-muse.log` showed only preflight at poll time).

## Method (read-only)

No production/tests/migrations/frontend modified; no commit/push/merge/reset/clean/stash/restore/checkout; no MAIN writes; no task scope change. Inspected `app/persistence/models.py` (2065 lines, 26 tables), `app/api/app.py` (8 routers), `migrations/versions/` (12 revisions, head `a0b1c2d3e4f5`), `Base.metadata` introspection (`python -c ...`), `app/persistence/characters.py` + `object_intelligence.py` + `migrations/versions/a0b1c2d3e4f5_s08_a02_structural_evidence.py` as reference authority for idempotency/CAS/cross-workspace/determinism patterns, `docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md`, `docs/pm/sprints/S07-SPRINT_CONTRACT.md`, `output/overnight-planning/S07-COMPATIBILITY-DRAFT.md`.

## Findings pointer

Full findings: `output/s07-readonly-review/20260821_020000/FINDINGS_RO1.md` + `LOG` in same dir.

**Summary: 10 BLOCKING, 2 FOLLOW-UP.**

| ID | Area | Priority | Verdict |
|---|---|---|---|
| RO1-F01 | Schema/model — `project_cast_mapping` table missing | BLOCKING | FAIL |
| RO1-F02 | Migration — ONE migration with down_revision=a0b1c2d3e4f5 missing | BLOCKING | FAIL |
| RO1-F03 | FK correctness + PRAGMA foreign_key_check | BLOCKING | FAIL (not provable) |
| RO1-F04 | Workspace isolation (B cannot read/mutate A) | BLOCKING | FAIL |
| RO1-F05 | Idempotency — equivalent replay no dup; different payload stable conflict zero mutation | BLOCKING | FAIL |
| RO1-F06 | Revision/CAS — stale 409, concurrent one winner | BLOCKING | FAIL |
| RO1-F07 | Immutable version pin (FK to pack_version.id, new publish no mutate) | BLOCKING | FAIL |
| RO1-F08 | Cross-workspace enforcement (project/role/character/pack same workspace, no leak) | BLOCKING | FAIL |
| RO1-F09 | Atomic rollback on failure | BLOCKING | FAIL |
| RO1-F10 | Deterministic serialization | BLOCKING | FAIL |
| RO1-F11 | S08 core untouched guard (merge risk) | FOLLOW-UP | PASS (watch) |
| RO1-F12 | Migration test harness (parity/heads/downgrade/protected data) | FOLLOW-UP | FAIL (covered by F02) |

At this base, S07 persistence contract is **0% satisfied** — every allowlisted artifact is absent. `alembic heads` is still `a0b1c2d3e4f5`; `Base.metadata` has 26 tables, none `project_cast_mapping`; `grep -c project_cast` = 0.

## Verdict

**SUBMITTED — BLOCKING gaps pre-landing.** Writer session (same task, same model `ocg/muse-spark-1.2-contributor` max, same allowlist, ONE migration `down_revision=a0b1c2d3e4f5`) must close RO1-F01…F10 before S07 can reach `MANAGER_VERIFIED`. Each finding lists reproduction / expected / actual / impact / missing test — verifier can paste the reproduction bundle in `FINDINGS_RO1.md` to confirm.

## Re-verify after S07-T01 lands

- `ruff check app tests → 0`, `mypy app → Success`, `git diff --check → 0`, `alembic heads → exactly one (new)`, `upgrade→downgrade→upgrade` temp DB + `PRAGMA foreign_key_check → 0` + `integrity_check → ok`, protected `channels.json` sha256 `dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555` + `motionforge.db 311296 B` unless intentional temp-only migration, `MOTIONFORGE_DATABASE_URL` UNSET / `-p no:cacheprovider` / `--basetemp`, OpenAPI typed `$ref`/`properties` for project_cast endpoints, plus per-finding tests: workspace isolation, idempotent replay, conflict matrix (role/pack/character/mapping_data variations → 409 zero mutation), stale 409 + concurrent CAS one winner loser rollback, immutable pin byte-identical after publish, cross-workspace 404 no-leak (4 dimensions), transaction rollback zero rows, deterministic JSON `sort_keys`.

## Evidence

- `output/s07-readonly-review/20260821_020000/FINDINGS_RO1.md` — normative findings (priority/file/reproduction/expected/actual/impact/missing test/verdict).
- `output/s07-readonly-review/20260821_020000/LOG.md` — review timeline + tool invocations.
- `output/s07-t01/20260821_011600_writer-muse.log` — writer preflight proof (as-lands timing).
- `app/persistence/models.py`, `migrations/versions/`, `app/api/app.py`, `Base.metadata` introspection — read-only source proof in FINDINGS appendix.

*Read-only review — no production/tests/migrations/frontend modified; worktree left as found.*
