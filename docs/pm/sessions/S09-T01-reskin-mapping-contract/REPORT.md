# REPORT — S09-T01 Source-Locked Reskin Mapping completion

- **Session**: S09-T01-reskin-mapping-contract — RESUME owner `20260822_232748_b4b2ad` (SL-2, 2026-08-24)
- **Worktree**: C:/Users/Admin/MotionForge2D-worktrees/s08-integration @ codex/s08-integration `ee10e55a809c`
- **RULES**: HERMES_AUTOPILOT_RULES.md đọc trọn (RULES_LOADED); overlay TARGET_PROFILE_2D_SOURCE_LOCKED.md đọc trọn; MOTIONFORGE_DATABASE_URL UNSET mọi lệnh; MAIN READ-ONLY.
- **STATUS: TASK_SUBMITTED** (không self-APPROVED)

## Outcome 1 — Durable pin, fail-closed (app/persistence/reskin_config.py)
`_resolve_lock_pin` + wiring vào create/update:
- Manifest phải tồn tại CÙNG workspace (cross-workspace → ownership refusal, zero mutation).
- Stored manifest_json re-validate qua authority `canonical_manifest_json`; corrupt → conflict refusal.
- Recomputed sha256 phải khớp `manifest_hash` (tamper → hash-mismatch refusal).
- MỌI segment route trong manifest phải thuộc enum authority `RENDERER_ROUTES` (5 giá trị) → route ngoài enum bị refuse.
- Manifest `voided` không pin được; `lock_policy_version` LUÔN derive từ manifest (client hint chỉ được phép khớp, không tự chế).
- Update CAS 3-trạng-thái: omitted = giữ pin; explicit id = re-pin full-validate; "" = unpin cả hai cột. Idempotent replay so sánh cả pin pair.

## Outcome 2 — Evidence per segment, không global score
- Repository `list_renderer_route_evidence`: trả về từng SegmentRenderRoute của manifest đang pin — occurrence_segment_id / route (enum exact) / anchor x,y ∈ [0,1] / frame range / confidence + source / reasons / provenance. Read-only.
- API `GET /api/v2/reskin-configs/{id}/renderer-route-evidence` (+ trailing-slash variant). Response DTO expose thêm `structural_lock_manifest_id`, `lock_policy_version`.
- **Bug thật đã sửa**: route truyền nhầm thứ tự (config_id ↔ workspace_id) gây 404 "default" — bắt được bởi test mới, đã fix + regression.

## Outcome 3 — Router registration
Router reskin-configs đã đăng ký sẵn từ foundation (được Codex duyệt giữ) — KHÔNG đụng app/api/app.py trong phiên này (additive-only nếu thiếu; thực tế không cần).

## Outcome 4 — Frontend additive (frontend/src/features/reskin/index.ts)
Mirror schema mới: 2 field pin trong ReskinConfigData/Create/Update + interface `RendererRouteEvidence` + `getRendererRouteEvidence()`. tsc --noEmit EXIT=0; eslint --max-warnings 0 EXIT=0.

## Outcome 5 — Tests (adversarial, zero mutation trên mọi refusal)
- NEW `tests/test_s09_reskin_source_locked_domain.py`: 9 test — pin derive policy; cross-workspace refuse; tampered-hash refuse zero-mutation; voided refuse; route-enum enforce; CAS repin/unpin/keep ×2 runs; evidence per-segment; unpinned→empty; idempotent replay pin-conflict.
- `tests/test_s09_reskin_config_api.py` +1: POST có pin → 201 derive policy; evidence endpoint per-segment; unknown id 404.
- `tests/test_s09_reskin_migration.py` repair theo head mới d8e9f0a1b2c3 + leg-wise downgrade semantics (pinned row chặn chân 1 atomic ở head; unpinned row đi chân 1, chân 2 refuse → đậu c9d0e1f2a3b4) + FK parity chuẩn hóa cho pin columns do native ALTER TABLE ADD COLUMN REFERENCES (reflection không báo ondelete inline; RESTRICT enforce thật ở engine level).

## Acceptance gate — bằng chứng chạy thật
| Gate | Kết quả |
|---|---|
| Focused SL domain ×2 | 9 passed / 9 passed |
| API reskin ×2 | 15 passed / 15 passed |
| Domain gốc ×2 | 26 passed / 26 passed |
| Migration ×2 | 9 passed / 9 passed |
| FULL S09 4 file ×2 (basetemp khác nhau) | **59 passed** (38.00s) / **59 passed** (37.46s) — sl-pytest-final-run1.log |
| Regression T00 (domain+migration) | 20 passed |
| Regression S07 nguyên file | 10 passed (live-head discovery, không deselect) |
| OpenAPI | 219 → 221 paths, removed=0, chỉ ADD evidence path ×2 — openapi-after-sl.json |
| ruff app+tests | All checks passed! |
| mypy app | Success: no issues in 110 source files |
| git diff --check | EXIT=0 |
| alembic heads | `d8e9f0a1b2c3 (head)` duy nhất — không tạo revision mới |
| Frontend | tsc EXIT=0, eslint EXIT=0 |

Mọi pytest chạy: `env -u MOTIONFORGE_DATABASE_URL -p no:cacheprovider --basetemp=%TEMP%/s09t01-*`.

## Write-set self-audit (allowlist TASK-SL)
Sửa: app/persistence/reskin_config.py · app/schemas/reskin_config.py · app/api/routes/reskin_config.py · frontend/src/features/reskin/index.ts · tests/test_s09_reskin_config_api.py · tests/test_s09_reskin_migration.py.
Tạo: tests/test_s09_reskin_source_locked_domain.py.
KHÔNG đụng: migrations/**, structural_lock.py, models.py (chỉ import), tests S07/T00 (read-only), MAIN. Git status phiên: 17 → 25 entries (delta = đúng các file allowlist + TASK-SL.md untracked). Không commit/push/stash/merge.

## Ghi chú minh bạch
- Foundation cũ giữ nguyên 100% (không revert): models/migration c9d0e1f2a3b4/routes/client/48 tests — chỉ mở rộng additive.
- Migration test repair là điều CHỈNH test theo contract mới (head dịch + leg-wise chain), không phải bypass: hành vi fail-closed vẫn được assert đầy đủ và có test mới riêng cho leg-wise.
- Không có secret nào xuất hiện trong artifact/evidence.

---

# ADDENDUM — S09-T01-C1 correction (2026-08-24): pinned route evidence isolation

- **Session**: RESUME owner `20260822_232748_b4b2ad` (C1) — review `S09_FULL_SPRINT_PM_REVIEW_2026-08-24.md` finding **F6 (P1)** + fast-track prompt §6.
- **STATUS: TASK_SUBMITTED** (không self-APPROVED)

## Root cause (F6 xác nhận)
`list_renderer_route_evidence` lọc theo `structural_lock_manifest_id == pin OR IS NULL` — nhánh OR NULL cho phép row legacy/unattributed của cùng video lọt vào pinned evidence. Test T01 cũ chỉ seed NULL-row nên leak được codify thành hành vi "đúng".

## Fix — strict isolation (app/persistence/reskin_config.py, duy nhất)
1. Bỏ hoàn toàn nhánh `OR IS NULL`: chỉ row có `structural_lock_manifest_id == pinned manifest.id` được trả.
2. Frozen-surface guard: thêm điều kiện `created_at(route) <= created_at(config)` (pin moment, bền vững qua reload vì là cột DB có sẵn — không cần migration). Row tạo sau pin bị loại kể cả khi đúng manifest.
3. `_as_comparable_dt` normalize naive↔aware trước so sánh (SQLite strip tzinfo vs ORM aware-UTC).
4. Projection thứ hai (`s09_demo_compare._route_evidence_from_manifest`) đi qua cùng repo method → tự hưởng isolation, không sửa file đó.

## Acceptance tests (tests/test_s09_reskin_source_locked_domain.py, +4)
| Case | Kết quả |
|---|---|
| Đúng manifest (ghi trước pin) → CÓ | ✅ test_f6_evidence_excludes_null_manifest_rows (kèm NULL-row bị loại) |
| NULL-manifest row → LOẠI | ✅ cùng test trên |
| Manifest khác (m2 cùng video) → LOẠI | ✅ test_f6_evidence_excludes_other_manifest_rows |
| Row tạo SAU pin → LOẠI | ✅ test_f6_evidence_excludes_rows_created_after_pin |
| Reload DB mới → cùng kết quả | ✅ test_f6_evidence_stable_across_fresh_db_reload |

Test cũ `test_renderer_route_evidence_per_segment` cập nhật: route row giờ PHẢI bind manifest id khi ghi (chính là contract F6).

## Gates
- Focused ×2 basetemp riêng: **13 passed / 13 passed** — output/s09/20260823_sprint_full/t01-c1/f6-focused-run{1,2}.log
- Regression ×2 (T01 domain 26 + SL domain 13 + API 15 + migration 9 + T04 demo-compare 9): **72 passed / 72 passed** — f6-regression-run1.log
- ruff write-set: All checks passed! · mypy reskin_config.py: Success · git diff --check EXIT=0
- Không đụng: models/migrations/API/frontend/MAIN/data/** (forbidden tôn trọng); alembic head b3c4d5e6f7a9 do worker khác quản lý.

## Findings ngoài write-set (attribution minh bạch — KHÔNG tự sửa)
1. **T02 evidence fixture đỏ đúng spec mới**: `test_route_evidence_api_read_model_matches_persisted_row` INSERT config với `created_at='2026-08-24T00:00:00'` hard-code nhưng route row dùng utc_now() thật → post-pin theo định nghĩa F6 → bị loại ĐÚNG. Owner T02 cần backdate route-row timestamp hoặc forward-date config trong fixture.
2. 3 test NVENC khác của T02 đỏ "output_media escapes workspace_root" — do validate_for_render mới trong renderer_contract.py (+306 dòng uncommitted của T02-C1). Thuộc T02 owner.
3. mypy app: `app/workflow/s09_demo_jobs.py:203 "object" not callable` — select_route lazy re-export qua PEP 562 __getattr__ khiến mypy suy `object`. File untracked thuộc worker khác; khuyến nghị eager import hoặc TYPE_CHECKING guard.

## Write-set audit (độc quyền §6)
Sửa: app/persistence/reskin_config.py · tests/test_s09_reskin_source_locked_domain.py.
Tạo: output/s09/20260823_sprint_full/t01-c1/** (focused/regression/ruff/mypy/diff-check logs).
Append-only: LOG.md, REPORT.md này. reskin_config.py sha256-prefix sau fix: `3a4eabbc16711e8e`.
Không commit/push/stash/merge; MAIN và data/** không đụng.
