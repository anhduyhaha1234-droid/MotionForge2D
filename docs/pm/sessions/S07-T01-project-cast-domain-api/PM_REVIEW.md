# S07-T01 — PM REVIEW (manager-only, filled after writer SUBMITTED)

## Manager state
- status: PENDING (filled after writer SUBMITTED + independent review)
- reviewer: HERMES MANAGER (ocg/muse-spark-1.2-contributor @ muse, reasoning max)

## Findings
- (manager review — code quality, test strength, allowlist, migration, gates)

## Verdict
- MANAGER_VERIFIED or CORRECTION_REQUIRED (manager only)

## MANAGER REVIEW — S07-T01 (independent, not trusting writer REPORT)
reviewed_at: 2026-08-21T04:58:00+07:00 / 2026-08-20T21:58:00Z
reviewer: HERMES MANAGER (ocg/muse-spark-1.2-contributor @ muse, reasoning max)

### Code review (read actual code)
- project_cast.py: ownership guards (project/role/character/pack all same workspace; role.project match;
  pack.character match), idempotent replay via UNIQUE(workspace,idempotency_key) + equivalent-payload check
  (different payload → stable conflict), natural-unique (project,role) conflict, CAS update/delete
  (UPDATE/DELETE WHERE revision=:expected, NoResultFound → 409), IntegrityError race → conflict, FK RESTRICT.
- migration b2c3d4e5f6a7b: down_revision=a0b1c2d3e4f5 single head; 1 table; FK RESTRICT x5; partial UNIQUE
  idempotency; UNIQUE(project,role); fail-closed downgrade (refuses if rows exist); PRAGMA integrity+FK check.
- schemas: _StrictModel extra=forbid strict=True; no client workspace_id in requests (server-owned default).
- routes: POST 201/200 idempotent; GET list/detail 404 no-leak; PATCH 409 stale; DELETE 204/409; typed $ref
  requestBody (ProjectCastCreateRequest / ProjectCastUpdateRequest).

### Manager live re-runs (temp SQLite, UNSET DB env)
- T01 suites 35 passed; head-sensitive S08 test 1 passed (after 7-file head fix); 7-file+S06+S08 regression
  291 passed; migration round-trip 7 passed; gates ruff 0 / mypy 0 / alembic single b2c3d4e5f6a7b /
  git diff --check 0; OpenAPI $ref typed.

### Scope check
- Allowlist respected; 7 head-hardcoded test files updated per manager BLOCKED_SCOPE decision (head constant
  only, no test-logic change); S08 core untouched; MAIN untouched; no commit/push/merge.

### Verdict
S07-T01 = MANAGER_VERIFIED.

## MANAGER REVIEW — CODEX CORRECTION CYCLE (F1-F6)
reviewed_at: 2026-08-21T11:20:00+07:00 / 2026-08-21T04:20:00Z

### Code review (read actual code)
- Authoritative policy single-source: app/persistence/project_cast.py `evaluate_compatibility()` module function;
  route evaluate + create_mapping + update_mapping/repin ALL call it (via `_check_compatibility_or_raise`).
  No duplicate policy across UI/route/repo.
- Generation authority: ObjectIntelligenceRepository.current_generation(workspace_id, role.video_item_id);
  generation_mismatch iff role.source_generation != current_generation. NO str(pack.version) comparison (grep 0).
- fail-closed reasons: source_overlay_refusal, unpublished_pack, incomplete_pack (+missing_required_pose),
  object_kind_mismatch, missing_required_capability, generation_mismatch, workspace_mismatch, stale_revision.
- fallback_allowed always False this correction (advisory only; no durable fallback-acceptance snapshot).
- mapping_id congruence (workspace+project+role) enforced in evaluate (mismatch → workspace_mismatch no-leak).
- DELETE requires revision: None → 422; stale → 409 zero mutation; missing mapping → 404.
- Idempotent replay returns (record, False) BEFORE compatibility (equivalent already-accepted) ✓; conflict/rejected
  writes zero mutation; typed ProjectCastConflictError/ProjectCastOwnershipError.

### Manager live re-runs (temp SQLite, UNSET DB env)
- T01 suites + compatibility: 56 passed. Focused 20-test markers: 23 passed.
- No source_generation↔pack.version comparison; DELETE revision required.
- S06+S08 broach regression: 142 passed. Gates ruff 0, mypy 0, alembic single b2c3d4e5f6a7b, git diff 0.

### Note
- `except Exception: current_gen=None` remains broad (follow-up: prefer catching ObjectIntelligence errors; gen
  check then skipped only when video/role lacking authority — role workspace_mismatch covers cross-ws). Non-blocking.

### Verdict
S07-T01 = MANAGER_VERIFIED.
