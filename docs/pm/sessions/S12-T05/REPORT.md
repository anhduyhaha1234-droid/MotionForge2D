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

## Contract compliance (T05 scope)

- Frontend-only: wiring full flow Export qua T03C API thật (preflight →
  job → status → result/evidence); không sửa production backend.
- Harness test-only mount router unmounted trên port riêng — production
  routing không đổi.
- Helper tiếng Việt dưới mọi button (text-gray-400+), testids đầy đủ cho E2E.
- Evidence chỉ render khi server `completed`; không suy diễn media URL.
