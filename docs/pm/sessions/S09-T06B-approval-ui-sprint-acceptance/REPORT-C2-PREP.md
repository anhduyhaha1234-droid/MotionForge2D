# REPORT — S09-T06B-C2-PREP (spec only-affected-regenerates, PREP phase)

- Task: S09-T06B-C2-PREP · Owner session: 20260824_131423_423e42 · Worktree: s08-integration @ codex/s08-integration @ ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- Phase: PREP — dry-run acceptance ×2 trên production stack hiện tại. Final measured run CHỈ làm sau I05-C2 verified và T03/T04 writers exit (Manager resume lại owner này).

## Files changed (exclusive write-set)
- output/s09/20260823_sprint_full/t06b-c2/: PLAN.md, run-prod-backend.sh, run-prod-seed.py, build-c2prep-evidence.py + evidence/benchmark_results_c2prep_synthetic.json, run-prod-seed logs, gate-c2-* logs, prod-backend.log/prod-frontend.log
- frontend/e2e/s09-t06bc2-global-setup.ts, frontend/e2e/s09-t06bc2-only-affected-regenerates.spec.ts, frontend/playwright.s09t06bc2.config.ts
- LOG.md append-only (mục 2026-08-25 C2-PREP)

## Verification evidence (real runs)
- Seed sau fix: run1 SEEDED_RESET demo_jobs_deleted=4; run2 SEEDED_RESET demo_jobs_deleted=0 (idempotent) — seed-postfix-run1/2.log
- Playwright Chromium ×2 PASS: 1 passed (15.8s) / 1 passed (15.4s) — gate-c2-playwright-run1.log / run2.log, production stack :8199/:3114 thật (app.api.app + next start), env explicit NEXT_PUBLIC_API_URL + NEXT_PUBLIC_S09_BENCHMARK_RESULTS lúc build
- TSC repo-wide errors=0; ESLint --max-warnings 0 CLEAN cho 3 file write-set
- pytest baseline T06A: 34 passed, 65 warnings in 34.88s

## Acceptance coverage trong spec (binary asserts)
1. Snapshot artifact IDs/hashes trước correction (job #1 qua UI submit thật)
2. Route_override correction qua UI → stale-revision confirm 409 không tạo gì; confirm hợp lệ → applied
3. Job #2 với pinned_routes từ correction: affected loop d2_mouth_phone có pin honored trong plan.routes_by_risk_class + route_notes; MỌI unaffected loop giữ nguyên artifact_id/sha/size/frame_count; đúng 4 distinct artifacts trên cả 2 jobs, 8 rows, không duplicate/không mất row
4. Approval fail closed khi pending (nút disable), sau confirm approve được với checkpoint hash 64-hex + verify PASS
5. Browser reload + backend process restart THẬT (kill PID + spawn lại run-prod-backend.sh) giữ nguyên checkpoint/hash/publications

## Findings (thuộc T05B owner 093602_af7c26 — KHÔNG sửa trong scope này)
1. CorrectionPanel không gửi affected_loop_ids → archived impact.affected_loop_ids=[]; spec assert segment-scope thay thế.
2. ApprovalPanel reasonsOf() chỉ đọc request.reasons / request.provenance.reasons; payload route_override không mang field nào trong hai cái đó → approval override evidence-match bất khả thi cho route_override bằng thiết kế hiện tại.

## Blockers / risks
- Không còn blocker kỹ thuật cho PREP.
- Final measured run phụ thuộc ngoài: I05-C2 verified + T03/T04 exit; khi đó assert "affected loop có sha MỚI" sẽ bật lên trên cùng harness snapshot hiện có.

STATUS: TASK_SUBMITTED (PREP phase — WAITING_JOIN cho final run sau I05-C2 + T03/T04 exit)
