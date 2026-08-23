# S08-A02-T01 — LOG (append-only)

## Baseline (written by Hermes manager before writer launch — 2026-08-19T22:05+07:00)

### Restoration / preflight (manager, read-only)

- Worktree guard verified: `pwd`/toplevel = `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`; branch `codex/s08-integration`; HEAD `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`; `git status --short` = 187 entries at packet time (32 M + 155 ?? — intentional dirty baseline, never reset/clean/restore/checkout/stash/commit/push/merge); HEAD matches MAIN `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`.
- QA ports verified FREE before packet creation (no listeners on 3012/3013/8000/8025/8026/8027/8028/8014/8888/3000/5173/8002/3010).
- No writer process active before launch.
- S08-A01-C1: Codex `APPROVED_WITH_NON_BLOCKING_PROCESS_CORRECTION` — correction appended to `docs/pm/sessions/S08-A01-C1-taxonomy-safety-correction/REPORT.md` (session `20260819_172534_b0ad63`, ocg/deepseek-v4-flash, reasoning max, wall 3h50m33s, active 2h43m18s, 502→resume same session; manager_review_timestamp not recorded).
- Previous sessions `20260819_105751_c6c6a1` and `20260819_143912_9450e9` are CLOSED — NOT reusable.
- `output/MANAGER_STATE.md` updated to `S08-A01-C1 APPROVED / S08-A02-T01 NEXT` (single source of truth; active_task = S08-A02-T01).
- Migration head before T01: `f7a8b9c0d1e2` (10th revision in `migrations/versions/`; chain `a1b2c3d4e5f6 → 23b308b1fd0b → 1c9f2a4b7d8e → d5e6f7a8b9c0 → e7f8a9b0c1d2 → f2a3b4c5d6e7 → f3a4b5c6d7e8 → f4a5b6c7d8e9 → f5a6b7c8d9e0 → f6a7b8c9d0e1 → f7a8b9c0d1e2`).

### Protected baseline (manager, read-only)

- MAIN HEAD: `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`
- Worktree HEAD: `a43b20da742996bafcb2f9d1ac57b10d3f1a5204` (match)
- Existing allowlist-verified tables at HEAD: `workspace, channel, project, video_item, scene, artifact, artifact_owner, legacy_import, job, job_step, job_attempt, job_event, job_lease, character, character_pack_version, character_asset, object_role, object_occurrence, object_role_artifact, object_grouping_suggestion, object_role_operation, object_correction` (22 tables via `grep __tablename__` in `app/persistence/models.py`).
- Alembic env/target: `migrations/env.py` (`target_metadata = Base.metadata`, explicit `MOTIONFORGE_DATABASE_URL` / `-x db_url`, `PRAGMA foreign_keys=ON` via shared engine factory).

### Launch plan

- Task: S08-A02-T01 — SceneGraph & Structural Evidence Bridge: Domain, Persistence, Migration and API Contract.
- Session: NEW (filled in REPORT). Model `deepseek-v4-flash` via provider `custom:vietapi`, reasoning `max` — user override for all writers/workers, single writer only.
- Packet: `docs/pm/sessions/S08-A02-scene-structural-evidence-bridge/TASK.md` (full scope/allowlist/AC/migration invariants/validation order).

---

<!-- Writer appends all subsequent entries below this line. Append-only. -->

