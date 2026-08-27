# S09-T05A — Targeted correction backend — REPORT

Worker session: 20260824_072626_645cde (provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled)
Worktree: `C:/Users/Admin/MotionForge2D-worktrees/s08-integration` @ `codex/s08-integration`, HEAD start `ee10e55a809c`
TASK.md: `docs/pm/sessions/S09-T05A-targeted-correction-backend/TASK.md`
LOG chi tiết: `docs/pm/sessions/S09-T05A-targeted-correction-backend/LOG.md`

## STATUS: TASK_SUBMITTED

---

## 1. Deliverables (write-set đúng allowlist)

| File | Loại | Nội dung |
|---|---|---|
| `app/persistence/models.py` | EDIT additive | class `S09Correction` + hằng `S09_CORRECTION_KINDS` / `S09_CORRECTION_STATUSES`; zero-removed verified vs HEAD copy (diff `<` = 0 dòng) |
| `migrations/versions/b3c4d5e6f7a9_s09_t05a_corrections.py` | NEW (188 dòng) | bảng `s09_correction`: FK workspace/project/video_item/segment, CHECK kind/status/key-length/revision>0, 2 partial-unique (natural_key, idempotency_key theo workspace), indexes video_status + segment |
| `app/services/s09_correction.py` | NEW (811 dòng) | `S09CorrectionRepository` (create/compute_impact/confirm CAS/cancel/get/list/counts), natural key `S09C:<kind>:<hash>` workspace-scoped, `_apply_mutation` per kind qua hạ tầng sẵn có, `applied_correction_counts` feed cho benchmark results |
| `app/schemas/s09_correction.py` | NEW (199 dòng) | typed payload RIÊNG từng kind (`Mask/ZOrder/Contact/MeshParts/RouteOverrideCorrectionRequest`, extra=forbid), `ConfirmCorrectionRequest`/`CancelCorrectionRequest` bắt buộc `workspace_id`+`revision ge=1`, response models |
| `app/api/routes/s09_correction.py` | NEW (230 dòng) | router `/api/v2/s09-corrections*`: POST submit idempotent, GET one/list, POST confirm/cancel CAS, GET counts — **KHÔNG wire vào `app/api/app.py`** (ngoài allowlist; chừa 1 dòng include cho Manager/Codex) |
| `tests/test_s09_t05_backend_domain.py` | NEW (783 dòng) | 18 tests repository trên sqlite alembic-upgraded thật |
| `tests/test_s09_t05_backend_migration.py` | NEW (379 dòng) | 8 tests schema/FK/CHECK/partial-unique/round-trip fail-closed |
| `tests/test_s09_t05_backend_api.py` | NEW (526 dòng) | 10 tests HTTP qua TestClient + FastAPI cô lập, dependency override `deps.get_db_session` |
| `docs/pm/sessions/S09-T05A-targeted-correction-backend/LOG.md` | NEW | timeline + root-cause từng fix |
| `output/s09/20260823_sprint_full/t05a/openapi_paths_before.txt` | baseline | 240 paths (+newline) chụp TRƯỚC khi sửa |

Không file nào ngoài allowlist bị tạo/sửa bởi task này. Dirty tree T00–T04 sẵn có (48→56 entries gồm cả file mới của T05A) không bị đụng tới.

## 2. Required-tests — binary ×2 PASS liên tiếp (adversarial, basetemp khác nhau)

```
env -u MOTIONFORGE_DATABASE_URL python -m pytest \
  tests/test_s09_t05_backend_domain.py \
  tests/test_s09_t05_backend_migration.py \
  tests/test_s09_t05_backend_api.py \
  -p no:cacheprovider -q --basetemp=$TMP/s09t05a-rNa
```

- Run r1a: **36 passed** (31.90s)
- Run r1b: **36 passed** (31.70s)
- Run r2a (sau vòng ruff --fix imports trong test files): **36 passed** (31.47s)
- Run r2b: **36 passed** (31.56s)

## 3. Bằng chứng acceptance (binary)

### CAS/idempotency zero-mutation CẢ HAI CHIỀU
- Stale confirm (`revision` cũ hơn DB) → `CorrectionConflictError` → HTTP 409; đếm trước/sau `occurrence_segment` KHÔNG đổi, row correction vẫn `pending` (domain + API test).
- Idempotency cùng key cùng payload → replay trả lại ĐÚNG row cũ (`replayed=True`), KHÔNG tạo row thứ hai; cùng key KHÁC payload → từ chối 409 (cả domain lẫn API).
- Cancel applied → 409; applied re-confirm → no-op trả lại trạng thái applied (không double-apply).

### Restart/cancel safe
- Sau confirm/cancel, đóng session rồi mở session factory MỚI đọc lại: trạng thái terminal giữ nguyên; cancel khi đã applied bị từ chối. Trạng thái nằm trong sqlite thật, không phải in-memory.

### Unaffected hash byte-identical
- Correction trên segment A: segment B (không liên quan) giữ nguyên toàn bộ cột byte-for-byte (so dict trước/sau sau expire); lineage của A đi qua supersede (logical_id giữ nguyên, version tăng) nên consumer khác của logical_id cũ không thấy thay đổi ngoài phiên bản mới.

### Provenance persist (route_override KHÔNG mutate row cũ)
- Seed route row "pose_swap" (model decision) → submit route_override → confirm: `segment_render_route` có 2 dòng, dòng đầu byte-identical với snapshot trước confirm; dòng MỚI mang `provenance_json` đủ `route_from/route_to/evidence` + `confidence_source='user'`. Incomplete provenance → fail-closed TRƯỚC khi ghi.

### Counts flow vào benchmark results
- `applied_correction_counts(workspace_id, video_item_id)` chỉ đếm status=`applied`, group theo kind; API GET `/api/v2/videos/{id}/s09-correction-counts` trả `{total, by_kind}` khớp từng bước (0 pending → 1 sau confirm). Hàm này là feed cho `correction_counts` trong benchmark results document (field sẵn có ở metrics schema I03, writer `scripts/s09_renderer_benchmark.py:780`).

## 4. Quyết định migration (tiêu chí TASK.md)

- TẠO ĐÚNG MỘT bảng mới `s09_correction` — lý do thật: 5 loại correction S09 cần durable audit row thống nhất (pending → applied/cancelled) với CAS revision + idempotency workspace-scoped + impact/result JSON. `object_correction` hiện hữu KHÔNG tái sử dụng được vì CHECK khóa cứng 4 loại S08 (`reassign|candidate_edit|merge|split`) — sửa constraint = phi-cộng-thêm, vi phạm additive-only.
- Mutation thật KHÔNG nằm trong bảng mới mà đi hạ tầng sẵn có: mask/z_order → supersede lineage `OccurrenceSegment`; contact → CAS `SceneGraphContact`; mesh_parts → CAS `SegmentMotion`; route_override → INSERT row `SegmentRenderRoute` MỚI kèm provenance.
- `b3c4d5e6f7a9` nối live head `d8e9f0a1b2c3` (discovered runtime bằng ScriptDirectory, không hard-code vào gate). Single head verify runtime.

## 5. Gates

| Gate | Kết quả |
|---|---|
| Single alembic head | `['b3c4d5e6f7a9']` — OK (runtime ScriptDirectory) |
| Round-trip upgrade→downgrade→upgrade | OK — downgrade REFUSE fail-closed khi còn dữ liệu (zero mutation lúc refuse), purge → drop đúng bảng → re-upgrade schema identical |
| Downgrade fail-closed | RuntimeError "refusing to downgrade" — OK |
| PRAGMA integrity_check / foreign_key_check | `ok` / 0 violations — OK |
| ORM parity vs migrated DB | nullability từng cột khớp — OK |
| models.py zero-removed | diff vs HEAD copy = 0 dòng bị xóa — OK |
| OpenAPI removed=0 | before 241 = after 241, REMOVED 0; correction paths expose qua router probe 6 operations (chưa wire vào app chính — xem §6) — OK |
| ruff | All checks passed! (app T05A + 3 test files) |
| mypy | Success: no issues found in 3 source files (service+schemas+routes) |
| git diff --check | EXIT=0 |
| MOTIONFORGE_DATABASE_URL | UNSET mọi lần chạy (verify shell) |

## 6. Ghi chú cho Manager/Codex (quyết định còn mở)

1. **Wiring router**: `app/api/app.py` ngoài allowlist ⇒ router chưa include vào app chính. Một dòng `app.include_router(s09_correction_router)` (prefix `/api/v2`) là đủ để 6 operations vào OpenAPI production. Baseline OpenAPI removed=0 vẫn giữ nguyên sau wiring vì chỉ ADD.
2. **Fix code đáng chú ý**: payload `RouteOverrideCorrectionRequest` ban đầu lặp `project_id/video_item_id` trong envelope — đã bỏ và handler inject giá trị ENVELOPE (đã qua `_assert_ownership`) vào request_dict trước apply, loại bỏ khả năng route row trỏ về project chưa kiểm ownership.
3. **Replay HTTP convention**: submit replay trả 200 (không 201) theo house style `object_correction` + `s09_demo_loops`.
4. Không commit/push gì — để Manager review. Không secret/connection string nào xuất hiện trong repo/report.

---

## 7. S09-T05A-C1 — correction validation trước mutation (append-only, 2026-08-24)

Review finding: F5 (P1) — `S09_FULL_SPRINT_PM_REVIEW_2026-08-24.md`. Prompt gốc: `S09_C1_FAST_TRACK_MANAGER_2026-08-24.md` mục 7. Resume đúng owner session `20260824_072626_645cde`.

### Files changed (đúng write-set phase A)

| File | Thay đổi |
|---|---|
| `app/schemas/s09_correction.py` | REWRITE: xóa stale literal `direct_composite/keyed_pipeline`; `RendererRoute = Literal[pose_swap, sprite_affine, mesh_warp, part_rig, controlled_redraw]` + import-time assertion khớp `RENDERER_ROUTES`; anchors `[0,1]` + `allow_inf_nan=False`; frames `ge=0` + validator `start<=end`; evidence/reason strip+non-empty; provenance route fields phải khớp payload; `_ID_PATTERN` chặn path escape; deep NaN/Inf refusal |
| `app/services/s09_correction.py` | `_validated_request` enforce full closed-domain cho MỌI kind TRƯỚC compute_impact/archive (helpers `_validate_route_override_request`, `_reject_path_escape_ids`); normalize in-place vào request_json; `_apply_route_override` lấy project/video ids từ ARCHIVED ROW (không từ request); confirm truyền row ids xuống; SegmentNotFoundError → mapped |
| `app/api/routes/s09_correction.py` | `_MISSING_OBJECT_ERRORS` (Contact/Motion/SegmentNotFound) → HTTP 409 thay vì 500 rò rỉ; KHÔNG mount app |
| `tests/test_s09_t05_backend_c1_validation.py` | NEW 39 tests adversarial (chi tiết LOG.md) |
| `tests/test_s09_t05_backend_domain.py` | Viết lại 1 test mã hóa hành vi lỗi F5 → pin hành vi mới reject-at-submit zero-row |
| `output/s09/20260823_sprint_full/t05a-c1/` | Thư mục evidence phase A |

KHÔNG đụng: models.py, migrations/**, app/api/app.py, data/**, MAIN, file owner khác.

### Acceptance — binary

- **Bogus routes / stale literals** (`bogus_from`, `bogus_to`, `direct_composite`, `keyed_pipeline`, `teleport`): REJECT ở cả Pydantic lẫn repository — probe thật trước/sau sửa lưu LOG.md.
- **Anchors** 9.0 / -2.0 / NaN / Inf: REJECT (`less than or equal to 1` / `greater than or equal to 0` / `finite number`).
- **Reversed frames** 20..1: REJECT (`start_frame (20) must be <= end_frame (1)`); negative frame REJECT.
- **Empty/whitespace evidence**: REJECT; missing evidence key REJECT; provenance route mismatch REJECT.
- **Path escape** `../../etc/passwd`, `..\x`: REJECT bởi `_ID_PATTERN` (Pydantic + service mirror).
- **Unknown field/value**: extra=forbid 422.
- **DB row count & artifacts KHÔNG đổi khi reject**: 6 param repository-level + 9 param HTTP-level đều assert `s09_correction` count và `segment_render_route` count bất biến sau reject (kể cả ghost segment 409).
- **Valid request vẫn deterministic/idempotent**: replay same-row (`created=True` → `created=False`, cùng id), same-key-different-payload 409, confirm tạo đúng 1 render-route row mới.

### Focused tests ×2 PASS liên tiếp

```
env -u MOTIONFORGE_DATABASE_URL python -m pytest \
  tests/test_s09_t05_backend_c1_validation.py \
  tests/test_s09_t05_backend_domain.py \
  tests/test_s09_t05_backend_migration.py \
  tests/test_s09_t05_backend_api.py \
  -p no:cacheprovider -q --basetemp=$TEMP/s09t05ac1-f1a   → 75 passed (46.99s)
  ... --basetemp=$TEMP/s09t05ac1-f1b                      → 75 passed (46.75s)
```

### Gates C1

- ruff: `All checks passed!` trên 7 file write-set T05A-C1 (1 finding I001 duy nhất nằm ở `sprite_affine_adapter.py` — T02-C1 owner khác, ngoài write-set, không đụng).
- mypy: `Success: no issues found in 3 source files`.
- git diff --check: EXIT=0. models/migrations không đổi ⇒ single head b3c4d5e6f7a9 giữ nguyên.
- J2 note: router vẫn CHƯA mount vào app chính — chờ T56-INTEGRATION theo đúng phân vai.

---

## 8. S09-T05A-C3 — immutable applied-regeneration context (append-only, 2026-08-25)

Review nguồn: `S09_C2_PM_REVIEW_2026-08-25.md` F1 (P0) + F5; prompt `S09_C3_CORRECTION_MANAGER_2026-08-25.md` §3.2 (:80-101) + acceptance S09-T05A-C3 (:167-183). Resume đúng owner session `20260824_072626_645cde`.

### Files changed (đúng write-set)

| File | Thay đổi |
|---|---|
| `app/services/s09_correction.py` | ADD method public thuần đọc `applied_regeneration_context(...)` — KHÔNG sửa mutation logic hiện có |
| `tests/test_s09_t05_backend_c3_context.py` | NEW 11 tests |

Routes + schemas: KHÔNG đụng (contract là service-level cho T04 load trực tiếp; không cần HTTP surface additive). KHÔNG đụng s09_demo_jobs.py, s09_demo_compare.*, renderer, frontend, models, migrations.

### Contract trả về

```python
ctx = repo.applied_regeneration_context(
    workspace_id, correction_id,
    expected_applied_revision=None,   # optional CAS stale-guard cho T04
)
# ctx keys: correction_id, workspace_id, project_id, video_item_id,
#   correction_kind, applied_revision, natural_key, occurrence_segment_id,
#   affected_occurrence_segment_ids / affected_contact_ids /
#   affected_motion_ids / affected_loop_ids / affected_layer_ids
#   (mỗi list sorted+dedup), effect (= canonical mutation result),
#   context_sha256 = sha256(canonical_json(ctx trừ field context_sha256))
```

Deterministic: payload chỉ chứa post-apply stable facts (không timestamp); row applied bất biến (confirm-replay no-op changed=False; cancel bị refuse) ⇒ cùng correction → same SHA qua fresh session/restart.

### Refusals — fail closed, zero mutation

| Case | Exception |
|---|---|
| pending / cancelled | `CorrectionConflictError` |
| `expected_applied_revision` lệch revision hiện hành | `CorrectionConflictError` |
| affected_loop_ids rỗng sau apply | `CorrectionValidationError` |
| natural_key / applied_at thiếu | `CorrectionValidationError` |
| result malformed / rỗng (kể cả legacy row bị corrupt) | `CorrectionValidationError` |
| id không tồn tại / cross-workspace | `CorrectionNotFoundError` |

Tests refuse đều assert durable snapshot (s09_correction/artifact/job/occurrence_segment/apply_checkpoint) bất biến trước/sau.

### Focused tests ×2 PASS liên tiếp (5 suites T05: c1 39 + c3 11 + domain 18 + migration 8 + api 11)

```
env -u MOTIONFORGE_DATABASE_URL python -m pytest \
  tests/test_s09_t05_backend_c1_validation.py \
  tests/test_s09_t05_backend_c3_context.py \
  tests/test_s09_t05_backend_domain.py \
  tests/test_s09_t05_backend_migration.py \
  tests/test_s09_t05_backend_api.py \
  -p no:cacheprovider -q --basetemp=$TEMP/s09t05ac3-f1a → 87 passed (70.11s)
  ... --basetemp=$TEMP/s09t05ac3-f1b                    → 87 passed (70.19s)
```

Regression: toàn bộ five kinds/CAS/idempotency giữ nguyên xanh (87 gồm 76 test pre-existing C1/T05A).

### Gates C3

- ruff: All checks passed (8 file write-set).
- mypy: Success — no issues in app/services/s09_correction.py.
- git diff --check EXIT=0 (chỉ CRLF warnings sẵn có của dirty tree tích hợp).
- Ghi chú cho T04-C3: endpoint regenerate load context QUA service này; dùng `expected_applied_revision` để CAS-guard trước khi submit job; caller KHÔNG được tự truyền/tamper affected scope — mọi scope lấy từ context.

STATUS: TASK_SUBMITTED



---

# S09-T05A-C4 — canonical render context cho cả 5 kinds (2026-08-26, resume owner)

Phạm vi: đóng phần T05A của F3 (C3 review) theo contract C4 §4.2/§4.3/§4.5 — applied regeneration context chứa đủ canonical post-apply values để T03 tái tạo effect sau restart với identical SHA.

## STATUS: TASK_MANAGER_VERIFIED

(Worker-owned verification packet cho Manager gate; Codex review độc lập là approval gate duy nhất.)

## 1. Files changed (đúng exclusive write-set)

| File | Thay đổi |
|---|---|
| `app/services/s09_correction.py` | confirm-time freeze `applied_layer_bindings` vào result; `_impact_layer_ids()` fail-closed; read-path ưu tiên snapshot đã lưu (legacy fallback re-derive); mask evidence `byte_size` đọc đúng cột `Artifact.size_bytes` (mypy fix) |
| `tests/test_s09_t05_backend_c4_render_effect.py` | 4 → 7 tests: +per-kind completeness z_order/mask/route_override, +SHA-immutable-under-lineage-stacking regression, +confirm refuse impact không stable ids zero-mutation |

Không file nào khác trong write-set bị đụng hôm nay (`git status` attribution: routes/schemas mtime cũ; s09_demo_jobs/s09_demo_compare/renderer/frontend/fixtures/freeze set nguyên vẹn).

## 2. Contract mapping §4.1–§4.5

- **§4.2 stable layer IDs**: `affected_layer_ids` = lineage `logical_id` từ structural evidence; binding fail-closed khi thiếu; display label chỉ nằm ở `affected_layer_labels`.
- **§4.3 per-kind canonical render effect** (mọi kind đều có khối `render_effect` version-pinned `s09-correction-render-effect-v1`):
  - mask → artifact store evidence thật (artifact_id/sha256/relative_path/kind/byte_size) + mask_semantics (segmentation/source_generation/confidence_source/reasons);
  - z_order → exact corrected z trên target placement (target_layer_id + target_segment_id thuộc live binding);
  - contact → exact start/end frame + ms + kind BẮT vào cả hai endpoint segment bindings;
  - mesh_parts → FULL applied transform (từng tham số) + frame range;
  - route_override → target segment chính xác + measured-passing route_to + frame_range/anchor/provenance/render_route_id.
- **§4 replay/immutability**: binding snapshot frozen tại confirm (post-apply), mọi lần đọc sau lấy từ archived result => SHA byte-stable qua fresh session VÀ qua supersede chồng cùng lineage (test regression riêng).
- **Fail-closed zero mutation**: pending/cancelled/stale revision/empty loops/no stable layer ids (cả ở confirm lẫn read)/malformed result/unknown+cross-workspace id — tất cả raise trước durable write, có test đếm snapshot 7 bảng.

## 3. Required-tests ×2 PASS liên tiếp

```
env -u MOTIONFORGE_DATABASE_URL python -m pytest \
  tests/test_s09_t05_backend_c3_context.py tests/test_s09_t05_backend_c4_render_effect.py \
  tests/test_s09_t05_backend_domain.py tests/test_s09_t05_backend_migration.py \
  tests/test_s09_t05_backend_api.py -p no:cacheprovider -q --basetemp=<fresh mỗi run>
```

- f2a: **56 passed** (52.98s) — basetemp `%TEMP%/s09t05ac4-f2a`
- f2b: **56 passed** (52.86s) — basetemp `%TEMP%/s09t05ac4-f2b`
- (Trước fix mypy size_bytes: f1a/f1b cũng 56+56.)

Regression: toàn bộ five kinds/CAS/idempotency/provenance/count pre-existing giữ nguyên xanh.

## 4. Static gates & freeze

- ruff: All checks passed — 8 file write-set.
- mypy: Success — app/services/s09_correction.py (fix attr-defined `byte_size`→`size_bytes`).
- git diff --check: EXIT=0 (chỉ CRLF warning sẵn có của dirty tree tích hợp).
- Freeze J1-v4: manifest SHA `ae92247b8bfd7bf2…` re-hash ×3 (preflight/giữa/sau cùng) — 13/13 ZERO drift. I03 run-A/run-B + I05 decision SHAs không đụng, không rerun benchmark.
- MOTIONFORGE_DATABASE_URL UNSET toàn phiên; basetemp ngoài protected MAIN; không migration/schema mới (không cần — additive JSON field trong result_json hiện có).

## 5. Blockers / rủi ro / handoff

- Không blocker. Không mở subworker. Không commit/push/reset/stash.
- Ghi chú cho T03-C4 (owner 20260824_031524_a6bb2a): consume `applied_regeneration_context` — dispatch theo `effect.render_effect.op`, bind target qua `layer_bindings[logical_id].bound_segment_ids` (đã post-apply, restart-stable); KHÔNG suy luận target từ placements[0]/label; refuse khi zero/>1 match.
- Ghi chú cho T04-C4: fingerprint dùng `context_sha256` từ context này + frozen evidence identity (phần T04); `expected_applied_revision` để CAS-guard trước submit job.

STATUS: TASK_MANAGER_VERIFIED / PENDING_CODEX_REVIEW
