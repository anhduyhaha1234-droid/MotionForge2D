# S07 — SPRINT REPORT (append-only)

Sprint S07 — Project Cast Reuse.

## Header
- created_local/utc: 2026-08-21T01:12:00+07:00 / 2026-08-20T18:12:00Z
- manager model: ocg/muse-spark-1.2-contributor @ muse, reasoning max, no fallback
- base HEAD (worktree): a43b20da742996bafcb2f9d1ac57b10d3f1a5204; MAIN a43b20da (protected)
- git status count at start: 211 (intentional dirty)

## Session lineage
| Task | Session role | Session ID | Model | Provider | Reasoning | Start local/utc | State |
|---|---|---|---|---|---|---|---|
| S07-T01 | writer | (pending) | ocg/muse-spark-1.2-contributor | muse | max | (pending) | PREPARING |
| S07-RO1 | read-only reviewer | (pending) | ocg/muse-spark-1.2-contributor | muse | max | (pending) | PREPARING |
| S07-RO2 | read-only reviewer | (pending) | ocg/muse-spark-1.2-contributor | muse | max | (pending) | PREPARING |
| S11-T01-BA-PREFLIGHT | read-only BA | (pending) | ocg/muse-spark-1.2-contributor | muse | max | (pending) | PREPARING |

## Heartbeat / recovery history
(append per heartbeat)

## Test evidence
(append per gate)

## Final sprint gate result
(pending)

## 2026-08-21T05:02:00+07:00 / 2026-08-20T22:02:00Z — SESSION LINEAGE update
| Task | Session role | Session ID | Model | Provider | Reasoning | State |
|---|---|---|---|---|---|---|
| S07-T01 | writer | 20260821_011252_8f17a1 | ocg/muse-spark-1.2-contributor | muse | max | MANAGER_VERIFIED |
| S07-T02 | writer | (in-flight) | ocg/muse-spark-1.2-contributor | muse | max | RUNNING |
| S07-RO1 | read-only | 20260821_011356_2e4b34 | ocg/muse-spark-1.2-contributor | muse | max | SUBMITTED (snapshot; re-review needed) |
| S07-RO2 | read-only | 20260821_011356_f99a1a | ocg/muse-spark-1.2-contributor | muse | max | SUBMITTED (snapshot; re-review needed) |
| S11-T01-BA | read-only | 20260821_011356_05c03e | ocg/muse-spark-1.2-contributor | muse | max | SUBMITTED (SAFE_TO_PARALLELIZE) |
### Recovery history
- S07-T01: 502 → resumed same session 011252_8f17a1 (cli-syntax fix). head-test BLOCKED_SCOPE corrected within same session.
- S11-BA: 502 → resumed same session 011356_05c03e.

## 2026-08-21T05:50:00+07:00 / 2026-08-20T22:50:00Z — SESSION LINEAGE update
| Task | Session role | Session ID | Model | Provider | Reasoning | State |
|---|---|---|---|---|---|---|
| S07-T03 | writer | (in-flight) | ocg/muse-spark-1.2-contributor | muse | max | RUNNING |

## 2026-08-21T08:25:00+07:00 / 2026-08-21T01:25:00Z — S07 FINAL INTEGRATION GATE (manager, fresh) — PASS
- T01/T02/T03 all MANAGER_VERIFIED (each independently re-run by manager).
- Flaky isolated: combined post-fix 437 passed ×2 consecutive; 2-file 22 ×6; 21-file bundle.
- Gates: ruff 0, mypy 0 (94 files), alembic single head b2c3d4e5f6a7b, git diff --check 0,
  frontend typecheck/eslint/build 0, Playwright S07 desktop+390 (T02 14 + T03 8 passed),
  migration round-trip + foreign_key_check 0, protected hashes unchanged
  (channels.json dd7aae26…; motionforge.db 311296 B), MAIN a43b20da untouched, no listeners/process cleanup.
- Session lineage complete (see above). First-failure/rerun history: 502×3 (resumed), head-test BLOCKED_SCOPE
  (2 rounds, corrected in owning sessions), flaky partial_compat (isolated via fixture).
- STATUS → SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW

## 2026-08-22T06:52:00+07:00 / 2026-08-21T23:52:00Z — CORRECTION C3 VERIFIED (manager) — Codex CHANGES_REQUESTED resolved

- Scope: S07-T01 only; owner session 20260821_011252_8f17a1 resumed (model alpha @ custom/9Router 127.0.0.1:20128, reasoning max, fallback disabled); run 05:24–06:25+07, 253 messages, exit clean. No recovery needed.
- P1 closed: app/persistence/project_cast.py — broad `except Exception: current_gen = None` REMOVED (~L300); only RoleNotFoundError handled → fail-closed workspace_mismatch; every other authority exception propagates (5xx, no mapping, no revision bump, idempotency key not consumed). Evaluate runs BEFORE session.add/flush (L308 vs L499-500) so rejected requests are zero-mutation.
- P2 closed: tests/test_s07_cast_compatibility.py weak patterns (`"1" or "2"` L350/L357, conditional `if cur == "2":`/pass L376-384/L410-415) all removed; exact-generation assertions now deterministic.
- Regression evidence (output/s07-t01-c3/20260822_054741/): prefix_regression.log FAILED test_authority_error_fail_closed_no_2xx on pre-fix code; postfix_regression.log PASSED. New test asserts status >= 500, DB rows == [], idempotency key still free, retry with SAME key succeeds.
- Manager independent re-run (temp roots/basetemps s07c3mg_*, MOTIONFORGE_DATABASE_URL unset, -p no:cacheprovider):
  Gate A focused 6-file S07-T01: 64 passed (47.0s)
  Gate B full 9-file S07: 83 passed (63.2s) = Codex baseline 82 + 1 regression, none lost
  Gate C authority cluster (object_intelligence domain, A02 c2/c3/r1c1, structural-evidence ×3, object-extraction ×3): 321 passed (4m21s), no regression vs baseline
  Gate D: ruff app tests "All checks passed!"; mypy app "no issues in 96 source files"; git diff --check clean; alembic single head b2c3d4e5f6a7b; protected MAIN channels.json dd7aae26096902eff74986b36554957d87eb8e60c5e8ff8048064c31655eb555 + motionforge.db 311296 B unchanged; ports 8004/3013/3014 clean.
- Diff audit: only allowlist files changed by C3 worker (project_cast.py, cast_compatibility.py, project_cast_api.py; repository test file untouched this round). tests/test_s11_original_audio_acceptance.py changed in same window but is untracked S11-lane work by its own owner (0 mentions in C3 transcript) — noted as parallel-wave observation, not a C3 violation. Frontend/migrations/S08 production: untouched.
- STATUS → SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW (awaiting Codex final review; manager does not self-approve)

## 2026-08-22T19:12:00+07:00 / 2026-08-22T12:12:00Z — CORRECTION ROUND 2 (C4/C4b/C4c/C4d + C2/C2b) MANAGER FINAL VERIFICATION — Codex CHANGES_REQUESTED (3 finding) resolved

- Verdict đầu vào: Codex CHANGES_REQUESTED — P1 fallback vô hiệu (T02), P1 repin UI hỏng (T02), P2 acceptance bypass UI repin (T03).
- Session registry (resume đúng owner, không tạo session mới, route muse/ocg/muse-spark-1.2-contributor reasoning max fallback disabled giữ nguyên):
  - S07-T01: 20260821_011252_8f17a1 — không dispatch (không finding thuộc scope T01; project_cast.py sửa trong C4 là vị trí evidence đích danh của verdict, không đổi T01 persistence/migration semantics — verify mttime models.py 00:05 + migrations nguyên + alembic single head).
  - S07-T02: 20260821_044658_7fde0f — C4 (20m56s, P1×2) → C4b (19m31s, ruff I001 ×19) → C4c (3m49s, eslint any+unused) → C4d (3m57s, TS18047 ×2 do chính C4c gây ra, bắt được ở final gate tsc).
  - S07-T03: 20260821_051414_184fd2 — C2 (14m43s, P2 repin-via-UI; runtime BLOCKED_DEPENDENCY_T02 có evidence khi chạy trước fix) → C2b (6m11s, eslint any ×3). Re-run real vertical SAU khi T02 landed: PASSED.
- DAG: T02-C4 verification → T03-C2 real vertical re-run → final integration gate (đúng thứ tự bắt buộc; global gates qua mutex khi mọi writer dừng).
- Files changed theo owner:
  - T02: app/persistence/project_cast.py (fallback matrix deterministic: generation_mismatch/incomplete_pack(+missing_required_pose companion) → fallback_allowed=True + desc tiếng Việt; workspace_mismatch/source_overlay_refusal/object_kind_mismatch/unpublished_pack/missing_required_capability/stale_revision → fail-closed blocked=True; blocked = not compatible and not fallback_allowed); ProjectCastPicker.tsx (pinnedMappingId ← found.id L39, effectiveMappingId prop??pinned L60, PATCH CAS qua updateProjectCastMapping L112-118, POST chỉ khi chưa có mapping); e2e/s07-picker-compat.spec.ts; tests/test_s07_cast_compatibility.py (+test_21/22/fallback_unsupported exact-value); tests/test_s07_project_cast_picker_api.py (+fallback API tests).
  - T03: e2e/s07-t03-real-vertical.spec.ts (repin QUA picker UI L190-216: reload→expand role→picker→chọn version mới→submit-success→assert revision n+1 + pack_version_id mới; stale 409 zero-mutation giữ L220+; route.fulfill cho /api/v2/project-cast* = 0).
- Regression fail-before/pass-after: fail_before.log 3 failed (test_21, test_22, test_fallback_supported_via_api trên code cũ) → pass_after 6 passed.
- FINAL GATES (manager tự chạy trên code hiện tại sau C4d — KHÔNG tin report cũ; evidence output/s07-final/20260822_1900/):
  - Full nine-file S07 pytest: 91 passed (72.4s)
  - Focused T02 (compat+picker): 34 passed; focused T03 (reuse+isolation+acceptance): 19 passed
  - Regression cluster (channel×2, video_item, s08 taxonomy/evidence/security/root): 233 passed (131.2s)
  - Playwright s07t02 desktop+390: 26 passed (18.7s); s07t03 real-vertical desktop+390: 4 passed (14.4s) — submit-success + revision n→n+1 + pack mới QUA UI thật
  - ruff app tests: All checks passed!; mypy: Success 96 files; tsc --noEmit: exit 0 (SAU C4d); eslint .: 0 errors; next build: exit 0
  - Alembic single head b2c3d4e5f6a7b; migration round-trip upgrade→downgrade→upgrade MIGRT_EXIT=0; PRAGMA foreign_key_check = []
  - git diff --check sạch; HEAD a43b20da đầu=cuối; dirty 254 intentional bảo toàn
  - Protected: MAIN motionforge.db 311296 B unchanged; MOTIONFORGE_DATABASE_URL UNSET toàn bộ runs; temp root/basetemp riêng (fv_root, fv_fullnine_bt, fv_reg_bt, fv_mig)
  - netstat :8004/:3014/:3012 sau runs RỖNG — không orphan process/listener
- Blocker còn lại: không.
- STATUS → SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW (manager không self-approve; mời Codex re-review độc lập theo §10).

## 2026-08-22T21:10:00+07:00 / 2026-08-22T14:10:00Z — CORRECTION ROUND 3 (C5/C5b + T03 final re-run) MANAGER VERIFICATION — Codex CHANGES_REQUESTED P1 (fallback backend contract) resolved

- Finding P1 (Codex): `_check_compatibility_or_raise()` project_cast.py:388-412 reject mọi compatible==False kể cả fallback_allowed=true → UI "Ghim bất chấp khác biệt" bị backend conflict; e2e fallback mocked nên không phát hiện. Manager tái hiện trên code thật trước dispatch (đúng quy trình).
- Owner: S07-T02 session 20260821_044658_7fde0f — C5 (16m58s) → C5b (3m30s, TS18047/TS2339 ×3 do chính C5 để lại, bắt ở global tsc gate). Route muse/ocg/muse-spark-1.2-contributor reasoning max fallback disabled giữ nguyên.
- Thiết kế end-to-end được Codex cho phép: field `fallback_acknowledged` (default False) thêm vào ProjectCastCreateRequest L40 + ProjectCastUpdateRequest L54 (app/schemas/project_cast.py); repository `_check_compatibility_or_raise` nhận flag, chỉ return khi `fallback_allowed AND acknowledged` (L411-412), create call-site L529, repin call-site sau CAS revision check L636; routes truyền body.fallback_acknowledged (L75/L248); UI gửi flag khi compat.fallback_allowed (Picker L118/L127). Unsupported reasons VẪN fail-closed hoàn toàn. Không silent nearest-match, không fabricated compatibility.
- Regression API thật (TestClient, không mock): fallback-supported CREATE thành công + mapping đúng + reasons warning giữ nguyên; fallback-supported REPIN revision n→n+1 (thiếu acknowledged → reject); unsupported CREATE/REPIN reject zero-mutation (row count before==after); stale revision 409 zero-mutation; idempotency replay deterministic.
- Gates manager tự chạy sau C5b (output/s07-correction/20260822_2100/): full nine-file S07 **95 passed** (74.7s, +4 test mới so với 91); PW s07t02 **26 passed** ×2 viewport; ruff All checks passed!; mypy Success 96 files; tsc --noEmit exit 0; eslint 0 errors; build exit 0; git diff --check sạch (warning CRLF pre-existing); HEAD a43b20da unchanged; MAIN motionforge.db 311296 B unchanged; MOTIONFORGE_DATABASE_URL UNSET toàn bộ; ports 8004/3014/3012 rỗng sau runs.
- DAG bước 2: resume S07-T03 owner 20260821_051414_184fd2 (4m0s) re-run real vertical SAU C5: **4 passed** qua picker UI thật (output/s07-t03/20260822_140644/) — primary repin KHÔNG dùng direct PATCH; worker ghi nhận dependency trước đó BLOCKED_DEPENDENCY_T02 giờ xanh nhờ fallback_acknowledged end-to-end. T01 không dispatch (không finding thuộc scope).
- Blocker còn lại: không.
- STATUS → SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW (chờ Codex re-review lần nữa; manager không self-approve).
