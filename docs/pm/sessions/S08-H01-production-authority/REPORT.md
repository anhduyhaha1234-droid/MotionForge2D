# S08-H01 — Frontend Production Authority: Implementation Report

**Status:** SUBMITTED  _(never APPROVED — manager/Codex sprint-exit review owns approval; PM_REVIEW.md untouched)_
**Correction round:** Codex CHANGES_REQUESTED finding F (PRODUCTION AUTHORITY), sprint S08 exit.
**Hermes session:** 20260817_182805_a3c8a4 (NEW session for Task ID S08-H01, model `ocg/deepseek-v4-flash`)
**Worktree:** `C:\Users\Admin\MotionForge2D-worktrees\s08-integration` (branch `codex/s08-integration`)

---

## CORRECTION ROUND — finding F status

| Finding F item | Status | Evidence |
|---|---|---|
| 1. Remove all fabricated fallback project/video data | DONE | `projects/[id]/page.tsx` and `Dashboard.tsx` rewritten; grep over `frontend/src` for `Dự án 2D`, `v-001`, `itemsData.items`, `setProjects([])`, `Fallback demo projects`, `Fallback mock detail` → 0 hits. |
| 2. API failure → honest error/retry/not-found UI (never silent-empty) | DONE | Detail page: durable→legacy resolve → 404 NOT-FOUND card + link back; network/server failure → "Không thể tải dự án" + "Thử lại". Dashboard: TanStack error + "Thử lại". Verified by E2E test 05/m04 (real backend kill → error → restart → retry recovers). |
| 3. Project/video identity from durable backend + URL; no localStorage/Zustand sole truth | DONE | Detail resolves `GET /api/v2/projects/{id}` → `GET /api/projects/{id}` → NOT-FOUND; videos from the real contract (`videos` payload / analyze-chain `video_item_id`). Rehydration still re-validates via backend. E2E 03/m03: URL `?video=` preserves selection across F5. |
| 4. LegacyWorkspace must not fabricate; hydrate + validate durable IDs from backend | DONE | `resumeProject` validates via `getProject`+`getSceneDetails` BEFORE writing the store; failures render honest banner + "🔄 Thử lại" + "Danh sách dự án" (no `console.error` swallow). E2E 06/m05. |
| 5. Detail → processing → gallery preserves selection EXPLICITLY | DONE | `Tiếp tục xử lý` → `/import-analyze?project=<id>`; per-video `Xem chi tiết →` → `/object-gallery?project=<id>&video=<video_item_id>`; ImportAnalyzePanel success → `Xem thư viện đối tượng` → same explicit URL. E2E 04. |
| 6. Desktop + 390px tests: API failure, retry, refresh, multi-video navigation | DONE | `playwright.s08h01.config.ts` — 11 tests (6 desktop + 5 mobile-390px), **11 passed (1.4m)**. Real error paths (no mocks): not-found on 404, connection-refused kill/restart + retry, F5 refresh, multi-video URL switch. |
| 7. No S06 redesign; no object-gallery contract changes | DONE | Character Library untouched; no backend file modified by H01 (backend regression 161 passed before/after, mypy/ruff clean). |

## Changes (frontend-only)

- `frontend/src/lib/api.ts` — typed `DurableProjectData`/`DurableProjectListResponse` + `api.getDurableProject`/`api.listDurableProjects`; completed `ProjectData` with backend-serialized `task_status`/`channel_id`/`created_at`/`updated_at`.
- `frontend/src/app/(app)/projects/[id]/page.tsx` — honest rewrite (resolve durable→legacy→not-found; error+retry; real video rows; explicit URL navigation; no dead "+ Thêm Video Item" button).
- `frontend/src/components/Dashboard.tsx` — honest rewrite (real durable contract, error+retry, no fabricated jobs call; jobs card shows explicit no-API note).
- `frontend/src/components/LegacyWorkspace.tsx` — backend-validated hydrate with honest error banner + retry; no silent failures.
- `frontend/src/components/ImportAnalyzePanel.tsx` — completed-chain → "Xem thư viện đối tượng" explicit gallery link (minimal nav wiring).
- `frontend/e2e/s08-h01-helpers.ts`, `s08-h01-production-authority.spec.ts`, `s08-h01-production-authority-mobile.spec.ts`, `frontend/playwright.s08h01.config.ts` — new.
- `frontend/e2e/s08-t04-helpers.ts` — API base env-overridable (`QA_API_BASE`, default 8025 unchanged).
- `output/s08-sprint/20260817-s08h01-r1/` — fresh QA run root (backend-root, run-qa-backend.sh port 8026, screenshots, logs).

## Validation (all ran; exact commands + verbatim results in LOG.md)

- `npx tsc --noEmit` → `TSC_EXIT=0`
- `npx eslint .` → 0 errors, 10 warnings (pre-existing `@next/next/no-img-element`)
- `npm run build` → exit 0 (all routes; `/projects/[id]` dynamic)
- Backend regression (T01–T05 combined, `-p no:cacheprovider`): baseline `161 passed in 85.58s` ≡ exit `161 passed in 86.35s` — **backend suites unchanged**
- `ruff check` changed `.py` → `RUFF_EXIT=0`; `python -m mypy app` → `Success: no issues found in 86 source files`
- `git diff --check` → exit 0
- Explicit fabricated-fallback grep over `frontend/src` → 0 hits
- Playwright `--list` → 11 tests (6 desktop + 5 mobile-390px), no cross-selection
- Playwright full run → **11 passed (1.4m)**; 15 fresh screenshots under the H01 run root (desktop + mobile, error/retry/not-found/gallery/navigation)
- Protected data (MAIN) unchanged: `channels.json` SHA-256 `dd7aae26…55eb555`, `data/motionforge.db` 311296 bytes, SAM2.1 checkpoint 898083611 bytes mtime 2026-07-29

## Out-of-scope / notes

- Dashboard component is currently unreferenced by any page (S04-T02 dead code) but was cleaned anyway per finding F; note left for the manager.
- The durable v2 video list (`/api/v2/projects/{id}/videos`) is the authority for durable projects; legacy projects expose their current video via the analyze chain (the only backend authority for them) — no hybrid cross-write added.
- 3 harness incidents occurred during QA (Next `.next` cache corruption; spec not starting its own backend; one wrong test assertion about candidate naming) — all fixed, documented in LOG.md; none affected frontend contracts.

**Files changed (mine, in worktree only):** see `git status --short` grep in LOG.md (frontend + this packet). No commit/push performed; no PM_REVIEW.md touched.

**Status:** SUBMITTED — awaiting manager/Codex verification. Do not self-approve.
