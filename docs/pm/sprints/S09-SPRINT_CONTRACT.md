# S09 SPRINT CONTRACT — Demo-first Reskin (pin → math → demo loops → compare UI → correction → approval)

- Author: HERMES MANAGER (chat 2026-08-22, model alpha @ custom 9Router)
- Authority: docs/pm/HERMES_AUTOPILOT_RULES.md (canonical, đã đọc toàn bộ 178 dòng) + prompt mở S09 của user + planning package output/s09-p00-readiness/20260822_052954_cf4196/ (9 file, normative)
- Unlock verdict: Codex Reviewer/PM xác nhận **S08 APPROVED** (reviews/S08_SPRINT_PM_REVIEW_2026-08-19.md) và **S07 CODEX APPROVED** sau independent review (full 95 passed; fallback/picker regression 38 passed; PW T02 26 passed; T03 real vertical 4 passed; không còn P0/P1/P2; conditions/follow-up chặn S09: **NONE**) → E04+E05 đóng → S09 mở chính thức
- Worktree: C:\Users\Admin\MotionForge2D-worktrees\s08-integration — branch codex/s08-integration — baseline HEAD **a43b20da742996bafcb2f9d1ac57b10d3f1a5204** — dirty 255 entries (intentional, bảo toàn)
- MAIN protected: C:\Users\Admin\MotionForge2D (never modify)
- Ngày tạo: 2026-08-22T22:46+07

## §1. Sprint outcome

Người dùng: (1) pin ReskinConfig vào Project Cast/PackVersion bất biến; (2) transform/compositing math deterministic; (3) render 3–5 demo loops đại diện THẬT; (4) so original/result/split/wipe/blink; (5) correction regenerate đúng loop bị ảnh hưởng; (6) "Phê duyệt Demo" tường minh tạo immutable ApplyCheckpoint cho S10. KHÔNG full-video apply.

## §2. Dependency DAG (SERIAL bắt buộc — audit PARALLEL_WAVES.md: 0 cặp disjoint)

```
S09-T01 → S09-T02 → S09-T03 → S09-T04 → S09-T05 → S09-T06 → final integration gate → SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW → STOP
```

Tối đa 1 production writer active. RO1 (domain/persistence/math-parity reviewer) chạy song song read-only khi có code để review; RO2 (UI/e2e reviewer) song song từ T04. Global gate qua mutex chỉ khi writer dừng.

## §3. Migration decision — FROZEN (phương án A)

S09-T01 là SOLE migration owner của toàn sprint. MỘT migration additive duy nhất, down_revision=b2c3d4e5f6a7b (Alembic head thực tế tại preflight), gồm bảng `reskin_config` VÀ `apply_checkpoint` (schema-only đầy đủ cho T06). T06 KHÔNG tạo migration thứ hai, KHÔNG sửa models.py — nếu schema checkpoint chưa đủ khi T06 bắt đầu: route correction về session S09-T01.

## §4. Task map (chi tiết normative: TASK_MAP.md 12 mục/task; gates: ACCEPTANCE_GATES.md G1–G10 + GF1–GF4)

| Task | Outcome | Exclusive write allowlist (tóm tắt) | Depends | Session |
|---|---|---|---|---|
| S09-T01 Reskin Mapping Contract | ReskinConfig pin (project, object_role)→PackVersion + anchor/scale/fit/clip/offset/rotation/opacity contract, revision CAS, idempotency | models.py additive reskin_config+apply_checkpoint; migrations/versions/<1 new>; app/persistence/reskin_config.py NEW; app/schemas/reskin_config.py NEW; app/api/routes/reskin_config.py NEW; app/api/app.py additive include_router; frontend/src/features/reskin/index.ts NEW thin client; tests test_s09_reskin_config_domain/api/migration.py NEW; output/s09/s09-t01/** | E04+E05 APPROVED — READY | mới |
| S09-T02 Pure Reskin Math | numpy-only deterministic transform/compositing + parity ≤1e-6 vs legacy oracle (CompositeCanvas.tsx, coordinates.ts, compositing.py — read-only) | app/services/reskin_math.py NEW; tests/test_s09_reskin_math_unit.py + _parity.py NEW; tests/fixtures/s09_math_golden/** NEW; output/s09/s09-t02/** | T01 VERIFIED | mới |
| S09-T03 Demo Loop Jobs | 3–5 loop THẬT qua GENERATE_DEMO_LOOP durable jobs, canonical timebase, managed artifacts atomic publish | app/services/demo_loop.py NEW; app/persistence/demo_loop.py NEW (no table); app/schemas/demo_loop.py NEW; app/api/routes/demo_loop.py NEW; app/workflow/job_service.py additive handler; app/api/app.py additive router; tests/test_s09_demo_loop_job.py + _selection.py NEW; output/s09/s09-t03/** | T02 VERIFIED | mới |
| S09-T04 Demo Compare UI | original/result/split/wipe/blink, keyboard, scene/timecode, audio state, desktop+390px | frontend/src/features/reskin/DemoCompare.tsx NEW; useDemoLoop.ts NEW; frontend/src/app/(app)/projects/[id]/reskin/page.tsx NEW; frontend/src/lib/api.ts append-only; frontend/e2e/s09-demo-compare.spec.ts NEW; frontend/playwright.s09.config.ts NEW; output/s09/s09-t04/** | T03 VERIFIED | mới |
| S09-T05 Impact Corrections | chỉnh param → regenerate CHỈ loop affected; 4 loop khác byte-identical | CorrectionPanel.tsx NEW; DemoCompare.tsx append; page.tsx append; demo_loop service/routes/schemas append impact/regenerate; tests/test_s09_loop_recompute_impact.py + _job.py NEW; e2e s09-correction.spec.ts NEW; output/s09/s09-t05/** | T04 VERIFIED | mới |
| S09-T06 Approval Checkpoint | "Phê duyệt Demo" → immutable append-only ApplyCheckpoint freeze revision/pack IDs/loop hashes/timebase fingerprint | app/persistence/apply_checkpoint.py NEW; schemas NEW; routes NEW; app.py include_router additive; ApprovalDialog.tsx NEW; DemoCompare/page/api.ts append; tests test_s09_apply_checkpoint_domain/api/immutability.py NEW; e2e s09-approval.spec.ts NEW; output/s09/s09-t06/** | T05 VERIFIED | mới |

Forbidden chung: legacy CompositeCanvas/Screen*, compositing/render/video_proxy/object_correction (read-only), migrations cũ, S07/S08/S11 files, MAIN tree, data/ protected, commit/push/merge.

## §5. Model policy

Mọi worker/reviewer session MỚI: provider **custom**, base URL http://127.0.0.1:20128/v1, model **alpha**, reasoning max, fallback disabled. Route sai → BLOCKED_MODEL_ROUTE. Dispatch: `"C:\Users\Admin\AppData\Local\Programs\Python\Python311\Scripts\hermes.exe" chat --provider custom --model alpha -q "$(cat prompt.txt)" --yolo --pass-session-id` background, log ra output/s09/<task>/.

## §6. Session ownership & registry

Một Task ID = một owning session mới; correction/retry = resume ĐÚNG owning session (--resume <sid> --provider custom --model alpha); recovery session mới chỉ khi owner chết có bằng chứng. Registry: docs/pm/sessions/S09-SESSION_REGISTRY.md.

## §7. Liveness

Heartbeat ≥ mỗi 20 phút; audit ngay nếu 8 phút không progress/log; connection error → RUNNING_RETRY_WAIT, chờ đủ 5 phút, resume đúng session/model, lặp vô hạn tới khi chạy tiếp/user dừng/bằng chứng chết. Retry nội bộ "failed after 3 retries" không phải terminal.

## §8. Verification gates

Per-task: focused tests ×2 liên tiếp; ruff app/tests; mypy app; alembic single head; git diff --check; regressions S07/S08/durable; protected hashes; adversarial review; Manager rerun độc lập ≥1 test chính; evidence output/s09/<task>/. Frontend thêm: typecheck/eslint/build/PW desktop+390/helper-text checklist/regression S07 picker+import-analyze.
Final gate sau T06: toàn bộ test_s09_* ×2; S07 cast + S08 object-intelligence + durable regressions; restart drill giữa demo job; determinism ×3 hash identical; alembic downgrade/upgrade + PRAGMA foreign_key_check; OpenAPI additive; ruff/mypy/typecheck/eslint/build; combined PW S09 desktop+390; fresh baseline; MAIN hashes unchanged; no orphan process/listener; lineage đầy đủ.
Baseline attribution (không sửa, không weaken): tests/test_integration.py SAM2 segfault skip; test_no_worker_or_api_cutover_tables fail historical do project_cast_mapping — fail mới ngoài baseline phải báo Codex.

## §9. Frozen product decisions

1. Reuse evaluate_compatibility (project_cast) — không policy mới, không GPU. 2. Legacy = read-only oracle. 3. Loop = scene-bounded theo CanonicalTimebase. 4. Pre-confirmation impact read-only rồi job thật. 5. Checkpoint append-only, không PATCH/DELETE. 6. NO mock/stub/placeholder. 7. UI tiếng Việt dark-theme helper text dưới mọi nút text-gray-400 ≥11px.

## §10. Terminal

Task: TASK_SUBMITTED → TASK_MANAGER_VERIFIED. Sprint: SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW → dừng mọi lane, dọn process/port, bàn giao Codex, KHÔNG ghi APPROVED/CLOSED, KHÔNG mở S10.
