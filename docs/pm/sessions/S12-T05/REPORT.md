# S12-T05 REPORT — Export UI (preflight → submit → status → cancel/retry → evidence)

Status: **TASK_SUBMITTED** | Date: 2026-09-07 | Worker: S12-T05 owner
Branch: `codex/s12/s12-t05-0907a` (worktree `s12-s12-t05-0907a`)
Baseline: `16598ea` | Prod commit: `030553b` | No merge/fetch/push.

## Acceptance evidence (real numbers)

- Playwright `s12-export.spec.ts` (real backend :8415 + Next :3015, 0 route
  mocks): **15 passed + 1 skipped** (~21-31s, desktop + mobile 390x844):
  preflight eligible + blocked fail-closed (`S12_EXPORT_NOT_READY`),
  submit 202 → poll `pending/running` + panel/progress hiện, cancel →
  `cancelled`, retry 202 + predecessor linkage, completed seed → evidence +
  run-id + tiếng Việt, nav desktop → `/export`, empty khi thiếu params.
  1 skip chủ đích: nav link trên mobile (AppNav `hidden md:flex`).
- Backend regression T03C (T05 không sửa backend): **15 passed** (21.5s,
  `tests/s12/s12-t03c/`, 9 job/API + 6 publication).
- `tsc --noEmit` full: **exit 0, 0 `error TS`** (scope T05 sạch).
- `py_compile` seed/harness/boot: OK.
- Backend guards SHA-256 nguyên: `s12_export.py` `8e795642…`,
  `s12_export_jobs.py` `068442ed…`, `publication.py` `d0b540c8…`.
- Porcelain sau commit: sạch. Allowlist: 11 files frontend (+2158/-1),
  0 backend, + LOG + REPORT (commit docs riêng).

## C1 correction (rows C20/C21/C22) — all green

- Playwright `s12-export.spec.ts`: **23 passed + 1 skipped** (~28-32s,
  desktop + mobile 390x844, real API :8415/:3015, 0 route mocks).
  - C20 project-export GREEN: 8 base tests giữ nguyên (no case removal).
  - C21 durable-refresh GREEN: reload giữ cùng active run; xóa localStorage
    → reopen cùng URL vẫn resolve cùng server run (no local authority).
  - C22 result-access GREEN: completed → 0 `a[href]/video/audio` suy diễn;
    pending → progress only, evidence hidden; stale id → role=alert,
    evidence hidden.
  - 1 skip chủ đích giữ nguyên: mobile nav-link (AppNav `hidden md:flex`).
- Backend T03C regression tại tree: **15 passed** (~19.5s). 4 repro tests
  của W4 (`test_c1_repro_typeerrors.py`) thuộc T03C-owned, không copy vào
  branch T05 — T05 chỉ consume interface qua API thật.
- `tsc --noEmit`: exit 0, 0 errors. `ruff check --select F` touched scope:
  All checks passed. `git diff --check`: 0.
- Harness mount test-only GIỮ NGUYÊN (W4 `9a91e18` không thuộc history
  branch — verified `merge-base --is-ancestor` = false, không merge/rebase).
- Evidence: `<C1-root>/s12-t05/` (SUMMARY + pytest + tsc + ruff + porcelain
  + diff_check) + raw `<C1-root>/matrix/C20|C21|C22/raw.txt`.

## Contract compliance (T05 scope)

- Frontend-only: wiring full flow Export qua T03C API thật (preflight →
  job → status → result/evidence); không sửa production backend.
- Harness test-only mount router unmounted trên port riêng — production
  routing không đổi.
- Helper tiếng Việt dưới mọi button (text-gray-400+), testids đầy đủ cho E2E.
- Evidence chỉ render khi server `completed`; không suy diễn media URL.
