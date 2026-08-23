# S08-P00 — Integrated S05 + S06 Base

**Status:** CLOSED (APPROVED by Codex PM review on 2026-08-05)  
**Owner:** Hermes implementation writer; Hermes manager verifies; Codex approves  
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`  
**Branch:** `codex/s08-integration`  
**Base:** `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`  
**Depends on:** S05 APPROVED/CLOSED and S06 APPROVED

## Outcome

Create one non-destructive integrated working tree containing the exact approved
S05 and corrected S06 product behavior, with semantic reconciliation of their
shared files and fresh integration evidence. Preserve all source worktrees and
MAIN unchanged. This preparation task does not implement S08 product behavior.

## Authoritative sources

- S05: `C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`
- S06: `C:\Users\Admin\MotionForge2D-worktrees\s06-t01-review`
- Protocol/handoff: `C:\Users\Admin\MotionForge2D\docs\pm\SESSION_PROTOCOL.md`
  and `C:\Users\Admin\MotionForge2D\docs\pm\CODEX_PM_HANDOFF.md`

MAIN is not a product-code source for this task. The old `s06-t01` worktree is
not authoritative.

## Required reading

1. MAIN `docs/pm/SESSION_PROTOCOL.md` and `docs/pm/CODEX_PM_HANDOFF.md`.
2. This TASK and START_PROMPT.
3. S05 C04 `TASK.md`, `REPORT.md`, `PM_REVIEW.md`.
4. S06 T05 corrected `TASK.md`, `REPORT.md`, `PM_REVIEW.md` and
   `INCIDENT_REPORT_WORKTREE_MAIN.md`.
5. Current versions of every shared file in base, S05 and S06 before resolving
   it: `app/api/app.py`, `app/api/deps.py`, `frontend/src/lib/api.ts`,
   `docs/pm/ROADMAP.md`.

## Allowed write scope

- The new integration worktree only.
- Approved S05 changed/untracked source, test, architecture and S05 session
  packet paths shown by the recorded S05 `git status --porcelain=v1` manifest.
- Approved corrected S06 changed/untracked source, migration, test, fixture,
  E2E/config and S06 session packet paths shown by the recorded S06 manifest.
- Semantic merge of the four shared files listed above.
- `docs/pm/sessions/S08-P00-integrated-base/LOG.md` and `REPORT.md`.
- New isolated integration evidence under
  `output/s08-p00-integration/<new-run-id>/`.

## Explicit exclusions

- `frontend/test-results/.last-run.json` from either source.
- Generated Playwright reports, `.next`, caches and old output/evidence trees.
- S06 quarantined corrupt test `tests/test_pack_publish_ux.py` and its obsolete
  nested API contract.
- Launcher/watch scripts and backup/quarantine contents.
- Any file from MAIN or old `s06-t01` as product source.

## Forbidden scope

- Any write to MAIN, S05, S06 or other worktrees.
- `channels.json`, production/user `data/`, databases, backups, old fixtures or
  old evidence in source trees.
- Commit, merge, push, deploy, rebase, cherry-pick, reset, checkout, restore,
  clean, stash, delete or branch/worktree operations.
- S08 product implementation or creation of S08-T01…T06 packets.

## Required integration semantics

1. Copy files individually from the two recorded authoritative manifests; do
   not recursively copy an entire repository or output directory.
2. For S05-only paths, integrated bytes must match S05.
3. For S06-only paths, integrated bytes must match S06.
4. Resolve shared files semantically:
   - `app/api/app.py`: preserve S05 explicit JobService/lifecycle/orchestrator
     ownership and S06 character router registration.
   - `app/api/deps.py`: preserve S05 authoritative public session-factory/root
     binding and every corrected S06 character dependency.
   - `frontend/src/lib/api.ts`: preserve S05 analyze/atomic-cancel APIs and S06
     `ApiError`, character read/validation and flat CAS publish APIs.
   - `docs/pm/ROADMAP.md`: preserve historical entries and truthfully mark
     S00–S06 complete; S08 remains unopened until P00 approval.
5. Do not reintroduce the obsolete S06 nested publish/image endpoints or corrupt
   `tests/test_pack_publish_ux.py`.
6. No competing DB factory, private lifecycle patch, mock production path or
   loss of API exports is permitted.

## Acceptance criteria

- [ ] Correct worktree/branch/base verified before the first write.
- [ ] Source and protected-state manifests recorded before integration.
- [ ] Every imported path is attributable to S05 or corrected S06.
- [ ] Source worktrees and MAIN remain byte/status unchanged.
- [ ] Three shared product files contain both approved behaviors with focused
      tests proving both sides.
- [ ] S05 final 41-test suite passes from the integrated tree.
- [ ] S06 corrected 90-test regression passes from the integrated tree.
- [ ] Import/analyze and character publish/read smoke paths both pass.
- [ ] Frontend typecheck, lint and build pass.
- [ ] Desktop and 390px smoke for both Import/Analyze and Character Library pass
      against a new isolated root/database/evidence directory.
- [ ] Fresh quality baseline passes 7/7 with a new Run ID.
- [ ] Protected MAIN hash/stat and all source-tree status snapshots are unchanged.
- [ ] REPORT/LOG are append-only and end at SUBMITTED; no approval is claimed.

## Stop conditions

- A required source path is ambiguous or absent from its authoritative manifest.
- A shared-file behavior cannot be preserved without product redesign.
- Any command would modify a source worktree, MAIN or protected data.
- Existing writer targets this integration worktree.
- Validation requires destructive cleanup or old evidence overwrite.
