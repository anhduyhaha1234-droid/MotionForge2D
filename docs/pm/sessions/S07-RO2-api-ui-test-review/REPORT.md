# S07-RO2 — Read-Only Review: API, UI & Test Strength — REPORT

**Status:** SUBMITTED (read-only reviewer never sets APPROVED; manager consumes findings)

**Hermes session:** 20260821_011356_f99a1a  
**Role:** S07-RO2 — API, UI & Test-Strength review  
**Provider:** muse (Meta Muse via 9Router http://127.0.0.1:20128/v1, api_mode codex_responses)  
**Model:** ocg/muse-spark-1.2-contributor (verified; meta/... returns 401 — not used)  
**Reasoning:** max  
**Fallback:** disabled  
**Start:** local 2026-08-21T01:13:56+07:00 / UTC 2026-08-20T18:13:56Z  
**End:** local 2026-08-21T01:24:00+07:00 / UTC 2026-08-20T18:24:00Z  
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration @ a43b20da742996bafcb2f9d1ac57b10d3f1a5204 (codex/s08-integration)  
**Alembic head:** a0b1c2d3e4f5 (single, no S07 migration yet)  
**MOTIONFORGE_DATABASE_URL:** UNSET (verified)

## Worktree guard

- Branch: codex/s08-integration, HEAD a43b20d, MAIN protected (C:\Users\Admin\MotionForge2D — not modified)
- `git status` (~211 dirty at dispatch, S08 work) — reviewer did NOT reset/clean/stash/restore/checkout/commit/push/merge, did NOT tidy dirty worktree, did NOT write MAIN
- Read-only: no writes to `app/`, `tests/`, `migrations/`, `frontend/` — only `output/s07-readonly-review/<run-id>/` + this packet REPORT.md/LOG.md

## Review scope

Read FULLY `docs/pm/sessions/S07-RO2-api-ui-test-review/TASK.md` (normative) + `docs/pm/sessions/S07-T01-project-cast-domain-api/TASK.md` + ROADMAP E04 S07 + PERSISTENCE_DOMAIN_CONTRACT + S08-SPRINT_CONTRACT + S07-COMPATIBILITY-DRAFT + existing `app/api/routes`, `app/schemas`, `app/persistence/models`, frontend conventions, `output/s07-t01` dispatch log.

Review S07 as it lands (T01 first, T02 later):
- T01: strict schemas/OpenAPI typed/error mapping/workspace authority/idempotency contract
- T02: picker compatibility warnings + no-fabrication + states + Vietnamese helper text + desktop/390px + keyboard
- Test strength: real repo/API, exact assertions, no mock-away, Scenario I coverage

## Findings summary

At snapshot a43b20d, **S07-T01 and S07-T02 have NOT landed** (writer dispatched PID 23588 but production files not yet present):

- `app/persistence/project_cast.py` — NOT FOUND
- `app/schemas/project_cast.py` — NOT FOUND
- `app/api/routes/project_cast.py` — NOT FOUND
- `app/persistence/models.py` — no `ProjectCastMapping` block
- `migrations/versions/<s07>` — none (head still a0b1c2d3e4f5)
- `tests/test_s07_*` — NOT FOUND
- `docs/pm/sessions/S07-T02*` + frontend picker — NOT FOUND (only DRAFT `output/overnight-planning/S07-COMPATIBILITY-DRAFT.md`)

Full findings with priority/file/reproduction/expected/actual/impact/missing test/verdict are in packet output (see below). No gate can PASS until writer lands.

**Output packet:** `output/s07-readonly-review/20260821_012400_ro2_review/FINDINGS_RO2.md` (14 findings F-RO2-01..14) + `LOG.md`

| ID | Priority | Verdict | Dimension |
|---|---|---|---|
| F-RO2-01 | HIGH | NOT LANDED — BLOCKED | Strict schemas (T01) |
| F-RO2-02 | MEDIUM | RISK (inheritance) | Strict schemas — characters.py thiếu strict=True |
| F-RO2-03 | HIGH | NOT LANDED — BLOCKED | OpenAPI typed |
| F-RO2-04 | HIGH | NOT LANDED — BLOCKED | Error mapping |
| F-RO2-05 | INFO | PASS (existing) | Error mapping — existing pattern đúng |
| F-RO2-06 | HIGH | NOT LANDED + RISK | Workspace authority — query param client-fabricated |
| F-RO2-07 | HIGH | NOT LANDED — BLOCKED | Idempotency/conflict |
| F-RO2-08 | INFO | PASS (existing) | Idempotency — existing pattern đúng |
| F-RO2-09 | HIGH | NOT LANDED (expected) | Compatibility warnings (T02) |
| F-RO2-10 | HIGH | NOT LANDED (expected) | No silent nearest-match |
| F-RO2-11 | MEDIUM-HIGH | NOT LANDED + FAIL (inheritance) | States/helper text — text-gray-500/10px violation |
| F-RO2-12 | MEDIUM | NOT LANDED (expected) | Desktop/390px/keyboard |
| F-RO2-13 | HIGH | NOT LANDED — BLOCKED | Test strength |
| F-RO2-14 | INFO | PASS (existing) | Test strength — existing real repo/API |

**Inheritance risks cần writer tránh khi land:**
- Dùng `app/schemas/structural_evidence.py:_StrictModel (extra="forbid", strict=True)` làm mẫu, không dùng `characters.py` (`strict` thiếu → coercion).
- Workspace phải server-derived (đừng expose `workspace_id` làm query param như các routes hiện tại).
- Helper text phải `text-gray-400` sáng hơn + `text-[11px]` min, không `text-gray-500`/`text-[10px]` (ChannelDashboard/ScenePreview đang violation).

## Evidence

- Ground-truth commands and outputs logged in `output/s07-readonly-review/20260821_012400_ro2_review/LOG.md`
- Each finding includes reproduction shell command + expected vs actual
- No mock/stub data used

## Limitations

- Snapshot review — writer chưa land nên không thể verify runtime behavior (HTTP 422/409/404, OpenAPI, idempotency replay, picker rendering). Cần re-review sau khi writer push files.
