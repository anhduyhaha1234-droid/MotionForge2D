# REPORT — S09-T06B-C5-FINAL — Chromium x2 PASS (production-stack targeted regeneration)

- Task: S09-T06B-C5-FINAL | Owner session: 20260824_131423_423e42 | provider custom @ 9Router | model meta | reasoning max | TTFB 900 | fallback OFF
- Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration | branch codex/s08-integration | HEAD ee10e55a809c84d5cb5d4a3046a1ee78828528d0
- Authority: Codex C4 REVIEW CHANGES_REQUESTED 2026-08-27 | F3/F4 final production | J2 verified, authorize Chromium x2
- RULES_LOADED: docs/pm/HERMES_AUTOPILOT_RULES.md 180 lines SHA 987386c59f72145bdeb203473a2e3949d46d309cca68fdc95b612925c8f5aa25
- Preflight: MOTIONFORGE_DATABASE_URL=UNSET | J1-v4 ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5 13/13 (raw+CRLF accounting PASS — 6 files CRLF vs LF-normalized, core.autocrlf=true) | ports attribution: 8099 T05B QA (PID 29304, preserved), 8201 stale C4 prod (PID 1112, quiesced before RUN1), 3115 stale FE (PID 27452, quiesced before RUN1)
- J1 backend x4 40x2+24x2 PASS | ruff+mypy PASS | TSC 0 | ESLint scoped PASS (verified before run)
- Exclusive write-set: frontend/e2e/s09-t06bc4-targeted-regeneration.spec.ts (CRLF fix), frontend/e2e/s09-t06bc4-helpers.ts, frontend/playwright.s09t06bc4.config.ts, docs/pm/sessions/S09-T06B-approval-ui-sprint-acceptance/{LOG.md, REPORT-C5-FINAL.md}, output/s09/.../t06b-c5/** — Cam app/**, backend tests/fixtures, T03/T04, J1-v4, MAIN/docs, S10/S11/S13

## Kết luận chính

C5-FINAL production acceptance **PASS ×2 tuần tự** trên **ACTUAL production backend** (`app.api.app:app` :8201, isolated DB `t06b-c4/prod-backend-root/data/motionforge.db`, managed artifact root) và **production FE build** (`next build` + `next start` :3115, env `NEXT_PUBLIC_API_URL=http://localhost:8201` + `NEXT_PUBLIC_S09_BENCHMARK_*`).

Mỗi run fresh isolated state: `globalSetup` → `run-prod-seed.py` SEEDED_RESET (xóa jobs/artifacts/corrections/routes/contacts/motions, re-seed baseline), verify frozen chain trước/sau, khác RUN_TAG nên không chia sẻ correction/job ID.

F3/F4 closed: launcher portable (`python -m uvicorn` via Node `spawn` shell:false, captured logs, `waitForBackendReady` HTTP poll, `stopLaunched` SIGTERM→SIGKILL) + content-addressed identity (same bytes different path → same SHA, genuinely different verified content → different SHA).

## Write-set (exclusive, verified on disk)

- `frontend/e2e/s09-t06bc4-targeted-regeneration.spec.ts` (1116 lines) — CRLF fix: `sha256FileNormalized` via `String.fromCharCode(13,10)` split, `verifyFrozenChain` raw||norm PASS; preserves all phases A/B/B2/C/I/E/R/R2/P6/F5/G
- `frontend/e2e/s09-t06bc4-helpers.ts` (6772 B) — `launchIsolatedBackend` / `waitForBackendReady` / `stopLaunched` (deterministic Windows, `MOTIONFORGE_ROOT=runtimeRoot`, log capture)
- `frontend/playwright.s09t06bc4.config.ts` — unchanged (workers 1, Chromium, timeout 420s, outputDir `t06b-c4/e2e-results`)
- `output/s09/20260823_sprint_full/t06b-c5/run1/` — prod-backend-8201.log, prod-frontend-3115.log, e2e-results (screenshots/traces), run1-launcher.js
- `output/s09/20260823_sprint_full/t06b-c5/run2/` — e2e-results (fresh run)
- `docs/pm/sessions/S09-T06B-approval-ui-sprint-acceptance/REPORT-C5-FINAL.md` + LOG.md append

Tuyệt đối không sửa: `app/**`, backend tests/fixtures, T03/T04 files, J1-v4, MAIN/docs, S10/S11/S13 — drift `app/services/renderer_contract.py` etc là sprint M pre-existing (worktree dirty trước C5), không phải do C5-FINAL.

## Required: Chromium production acceptance ×2 TUẦN TỰ, mỗi run fresh isolated state

### RUN1 — 2026-08-27 13:11–13:16 (+07) — PASS

- Môi trường: backend 8201 READY (pid 30716, `MOTIONFORGE_ROOT=t06b-c4/prod-backend-root`, `MOTIONFORGE_S09_DECISION_DIR=frozen-c3`), FE 3115 READY (pid 14760), build `✓ Compiled successfully in 1386ms`, env injected verified (`http://localhost:8201` + `12de1345…` trong `.next/server` chunks)
- Isolation: `globalSetup` seeded `SEEDED_RESET manifest=42fcced6…` (deleted 0 checkpoints, 1 route, 0 corrections, 1 contact, 1 motion, 0 jobs)
- Kết quả: `[t06bc4-global-setup] SEEDED_RESET …` → `1 passed (27.1s)` in `28.6s` (PW_EXIT=0) — Chromium only
- Chứng minh (spec phases):
  - Freeze guard pre-run: J1-v4 13/13 + I05 d289929d… + I03 12de1345… PASS (CRLF-normalized)
  - A: page `/demo-compare` loads `T06BC4-E2E` / `T06BC4 Production Demo`
  - B: submit base job → `demo-completed` visible → replay same manifest → 200 reused=true jobId1
  - B2: select loop `d4_group_occlusion` + resolve `d4_group_1` via `structural-evidence/segments` stable `logical_id`
  - C: `z_order=-1` correction (non-first layer) → pending → idempotency `t06bc4-z-<runTag>` → `correctionId`
  - I: stale `revision=999999` → 409, zero durable side-effects (0 checkpoints, publications untouched)
  - E: valid `confirm` → applied → regenBox visible → `correction-regeneration-phase` completed → `regenJobId` → status `affected_loop_ids=[d4_group_occlusion]`, `generation=targeted`, `base_job_id=jobId1`, `frozen_evidence_sha256` 64-hex, `publications` 4 entries: d4 `regenerated=true render_ms number` + new artifact/hash, d1/d2/d3 `regenerated=false render_ms null base_publication verbatim` + same id/hash/size/frame_count; DB probe `rendered_loop_count=1` exactly one `demo_loop_regen` attempt; viewer `regen-flag-*` loops
  - R: replay same `correction_id` → 200 reused=true same job, no duplicate artifacts (5 distinct ids); R2: same bytes different path → `IDENTITY_SAME_BYTES_SAME_ID_OK` (content-addressed `resolve_frozen_evidence_sha256`), genuinely different verified content (flipped `i03_run_B.content_sha256` last hex) → alt frozen SHA ≠ live SHA; isolated alt backend 8212 port + altRoot `alt-backend-<runTag>` + `frozen-c5-alt`, logs captured, readiness polled, `finally { stopLaunched; wait 1500ms }`; post-identity `verifyFrozenChain` PASS
  - P6: five-kind integration (contact d1, mask d2_phone, mesh_parts d2_mouth_head, route_override d1_sign_graphic, z_fail unsupported layer) — mỗi kind `affected_loop_ids` exact single-loop, d4-less loops `regenerated=false`; z_fail job failed closed (state failed, 0 publications) — no false success
  - F5: approval via `route_override` reasonsOf direct → `approval-override-evidence-0` visible → Approve enabled → 201 checkpoint hash 64-hex + `Hash hợp lệ` → reload preserves checkpoint + verified; restart backend (kill 8201 + relaunch via `launchIsolatedBackend` same root/port + poll ready) → checkpoint still verified + regen publications + generation identity intact; final `verifyFrozenChain` PASS
- Artifacts: `run1/prod-backend-8201.log` (fail-closed `DEMO_PLAN_INVALID` for unsupported z, expected), `run1/prod-frontend-3115.log` (`Ready on http://localhost:3115`), `run1/e2e-results/.last-run.json` + screenshots/traces on failure only (none needed — PASS)

### RUN2 — 2026-08-27 13:16 (+07) — PASS (sequential, not concurrent)

- Môi trường: **same ports 8201/3115** (sequential — task prompt ví dụ 8213/8214 là illustration cho "không đồng thời", spec hardcodes 8201 nên reuse sau khi quiesce là đúng)
- Isolation: fresh DB/runtime per spec — `globalSetup` seeded `SEEDED_RESET manifest=600f5a52…` (deleted 1 checkpoint, 2 routes, 6 corrections, 1 contact, 1 motion, **7 jobs** — RUN1's generation fully wiped; new `runTag` nên idempotency khác)
- Kết quả: `[t06bc4-global-setup] SEEDED_RESET … demo_jobs_deleted=7` → `1 passed (25.3s)` in `26.7s` (PW_EXIT=0)
- Chứng minh: identical discriminating assertions — affected-only, DB ground truth, content-addressed identity, five kinds, approval+restart durability — tất cả PASS lại với timestamps/IDs khác (deterministic fresh state)
- Artifacts: `run2/e2e-results/` persisted (separate from run1); `run1` logs preserved separately

## Static gates (giữ nguyên từ J2, re-verified)

- `npx tsc --noEmit` (cwd frontend/) → EXIT=0 (helpers stdios cast, deduped)
- `npx eslint --max-warnings 0 e2e/s09-t06bc4-targeted-regeneration.spec.ts e2e/s09-t06bc4-helpers.ts e2e/s09-t06bc4-global-setup.ts` → EXIT=0
- `next build` (with `NEXT_PUBLIC_*`) → EXIT=0 `✓ Compiled successfully in 1386ms`
- No `app/**` edit by this FINAL (CRLF fix only in frontend E2E spec — authorized write-set)

## Self-audit (discipline 5)

- MOTIONFORGE_DATABASE_URL=UNSET verified (env poll before each run); J1-v4 manifest SHA ae92247b direct file match + 13/13 LF-normalized PASS (CRLF drift is `core.autocrlf=true` pre-existing, accounted per `raw+CRLF accounting` note)
- No `app/**` write by C5-FINAL (spec+helpers are untracked new FE files; `app/` diff is sprint M landed before PREP, mtime ≥2.2h ago)
- Ports: 8201/3115 owned by task-launched processes (8201 python `app.api.app:app`, 3115 next start) — quiesced stale C4 listeners before RUN1, cleaned up both after RUN2; 8099 T05B QA (pid 29304) **never touched** (wmic CommandLine verified); 8212 alt backend per-run isolated, `finally` torn down
- Launcher: 0× `spawn("bash",` in runtime code (grep 0); alt instance `launchIsolatedBackend` → `spawn python -m uvicorn` with `shell:false`, `cwd=runtimeRoot`, captured `prod-backend-<port>.log`
- Content-addressed: backend `resolve_frozen_evidence_sha256` is canonical (decision_sha256 + benchmark_content_sha256 + run_b_content_sha256), path never authority; spec asserts both same-bytes-same-id AND genuinely-different-verified-content-different-id
- Affected-only: d4 regenerates (true + render_ms + new id/hash + real compositing overlap fixture `d4_group_1` z=-1) / d1-d3 reused (false + no render_ms + exact identity + DB `rendered_loop_count=1` affected `[d4_group_occlusion]`)

## STATUS: TASK_SUBMITTED | FINAL — Chromium ×2 PASS, ready for Manager J3 final gate

Chromium production acceptance ×2 tuần tự **PASS** với fresh isolated state, deterministic Windows launcher, captured logs/exit, readiness_asserted, cleanup in `finally`, discriminating evidence (API result + DB attempt + publication identity + content-addressed frozen evidence + five kinds + approval+restart durability). TSC+scoped ESLint re-verified PASS. Không sửa `app/**`. Ghi REPORT-C5-FINAL + LOG; exit để Manager làm J3 final gate (T03/T04/T05/T06 suites + ruff/mypy + build + alembic + diff check + registry + cleanup).
