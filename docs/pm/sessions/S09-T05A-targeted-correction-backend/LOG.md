# S09-T05A — Targeted correction backend — LOG

Worker session: 20260824_072626_645cde (provider custom @ 9Router http://127.0.0.1:20128/v1, model alpha, reasoning max, fallback disabled)
Worktree: C:/Users/Admin/MotionForge2D-worktrees/s08-integration @ codex/s08-integration
HEAD at start: ee10e55a809c84d5cb5d4a3046a1ee78828528d0

## Bước 0

- RULES_LOADED: đọc TOÀN BỘ C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md (180 dòng) trong lượt làm việc hiện tại.
- Worktree guard PASS: cwd đúng worktree, branch codex/s08-integration; MAIN READ-ONLY.
- MOTIONFORGE_DATABASE_URL UNSET (verify bằng shell thật).
- Dirty tree 48 entries là trạng thái tích hợp sẵn của T00–T04 — không đụng.

## Preflight baseline (chụp TRƯỚC khi sửa code)

- OpenAPI paths baseline = 241 (output/s09/20260823_sprint_full/t05a/openapi_paths_before.txt, 240 dòng + newline cuối).
- app/persistence/models.py sha256 đầu 4b1bcc9defee8761 (đã khớp nội dung với git HEAD ee10e55 modulo CRLF — diff --strip-trailing-cr rỗng ⇒ zero-removed proof có thể so trực tiếp vs HEAD).
- Alembic live head discover (làm lại runtime trong test): kỳ vọng d8e9f0a1b2c3.

## Quyết định thiết kế (theo tiêu chí TASK.md)

1. Migration: TẠO ĐÚNG MỘT bảng mới `s09_correction` + migration mới `b3c4d5e6f7a9` (down_revision = live head d8e9f0a1b2c3, discovered runtime chứ không hard-code vào test gate). Lý do THẬT SỰ cần bảng mới: 5 loại correction S09 cần một durable audit row thống nhất (pending → applied/cancelled) với CAS revision + workspace-scoped idempotency + impact/result JSON; `object_correction` hiện hữu bị CHECK khóa cứng 4 loại S08 (`reassign|candidate_edit|merge|split`) và CHECK khóa status — không thể tái sử dụng nếu không sửa constraint phi-cộng thêm (vi phạm "additive only" trên models.py hiện trạng). Các MUTATION thật KHÔNG nằm trong bảng mới mà đi qua hạ tầng sẵn có:
   - masks / z-order → supersede lineage `OccurrenceSegment` (app.persistence.structural_evidence.supersede_segment) — history giữ nguyên qua logical_id/lineage_version.
   - contacts → CAS update `SceneGraphContact` (structural_evidence.update_contact).
   - mesh/parts → CAS update `SegmentMotion` (structural_evidence.update_motion).
   - route override → INSERT row `SegmentRenderRoute` MỚI mang provenance {route_from, route_to, reason, evidence} — KHÔNG mutate row cũ (history theo natural key).
2. API: một endpoint typed payload `/api/v2/s09-corrections` (POST submit typed union, POST /{id}/confirm CAS, GET /{id}, POST /{id}/cancel) — mỗi loại là một payload type riêng trong cùng router.
3. Regeneration scope: chỉ affected loop/layer/segment — test byte-identical unaffected hashes (render_loop_bytes deterministic của T03 dùng làm bytewise oracle cho affected loop; unaffected segments/rows phải giữ nguyên hash trước/sau confirm).
4. Correction counts flow vào benchmark results schema: provider đọc corrections applied từ DB và ghi `correction_counts` vào results document schema_version=1 (field đã tồn tại trong metrics schema của harness I03) qua hàm `correction_counts_for_video` + writer `apply_correction_counts_to_results`.
5. app/api/app.py KHÔNG thuộc allowlist ⇒ router KHÔNG wire vào app chính trong task này (tránh vi phạm write-set); test gắn router lên FastAPI app cô lập. Ghi rõ trong REPORT để Manager/Codex quyết định wiring.

## Write allowlist (NGHIÊM)

- app/persistence/models.py (ADDITIVE ONLY — append class + __all__ entries)
- migrations/versions/b3c4d5e6f7a9_s09_t05a_corrections.py (MỘT file mới)
- NEW app/services/s09_correction.py
- NEW app/api/routes/s09_correction.py
- NEW app/schemas/s09_correction.py
- tests/test_s09_t05_backend_domain.py + tests/test_s09_t05_backend_migration.py + tests/test_s09_t05_backend_api.py
- output/s09/20260823_sprint_full/t05a/**
- docs/pm/sessions/S09-T05A-targeted-correction-backend/{LOG.md,REPORT.md}

## Timeline

- Bước 0 + preflight + explore repo (models/structural_lock/structural_evidence/object_correction/s09_demo_jobs/benchmark harness/migration T00 khuôn) — DONE.
- Baseline openapi 241 paths + models.py sha chụp TRƯỚC khi sửa — DONE.
- models.py: additive `S09Correction` + `S09_CORRECTION_KINDS`/`S09_CORRECTION_STATUSES` — DONE (zero-removed verify vs HEAD copy, diff `<` = 0 dòng).
- Migration b3c4d5e6f7a9 (revises d8e9f0a1b2c3): single-head verify bằng ScriptDirectory runtime; upgrade thật trên sqlite probe; FK/CHECK/partial-unique enforce — DONE.
- Service app/services/s09_correction.py (811 dòng): repository + natural key `S09C:<kind>:<hash>` + CAS house style (instance attributes + flush, KHÔNG UPDATE..RETURNING) + `_apply_mutation` per kind + `applied_correction_counts` feed — DONE (ruff + mypy sạch).
- Schemas app/schemas/s09_correction.py: typed payload riêng từng kind, extra=forbid fail-closed; Confirm/Cancel bắt buộc workspace_id + revision ge=1 — DONE.
- Routes app/api/routes/s09_correction.py (230 dòng): POST submit idempotent (201 mới / 200 replay theo convention object_correction+s09_demo_loops), GET one/list, POST confirm/cancel CAS, GET counts — DONE. KHÔNG wire vào app/api/app.py (ngoài allowlist) — 6 operations expose qua router-level OpenAPI probe.
- Tests 3 file (domain 783 / migration 379 / api 526 dòng):
  - RESUME fix #1 `test_submit_and_replay_mask`: root cause = test kỳ vọng replay 201 trong khi handler trả 200 replay theo house convention → sửa TEST assertion sang 200 (handler đúng).
  - RESUME fix #2 `test_route_override_typed_flow`: root cause THẬT = payload schema RouteOverrideCorrectionRequest lặp project_id/video_item_id trong khi envelope đã có → lỗ hổng: route row có thể trỏ về project khác chưa qua ownership assert. Fix CODE: bỏ 2 field khỏi payload schema, handler inject giá trị ENVELOPE vào request_dict trước khi apply ⇒ ownership luôn được assert trên chính ids dùng ghi row.
  - RESUME fix #3 `test_openapi_additive_removed_zero`: assertion flawed đếm path-level trùng giữa POST submit và GET list cùng `/s09-corrections` → thay bằng uniqueness theo cặp (logical-path, method), expected set đủ 6 operations.
  - Domain suite 18/18: CAS zero-mutation cả hai chiều (stale confirm/cancel từ chối, không đổi segment/contact/motion count), idempotency same-key-same-payload replay vs different-payload refuse, restart-safe (mở lại session mới đọc đúng trạng thái applied/cancelled terminal), unaffected-segment hash byte-identical sau mutation, route_override append history không mutate row cũ + provenance persist đủ route_from/route_to/evidence, counts chỉ đếm applied.
  - Migration suite 8/8: single head b3c4d5e6f7a9 (down_revision d8e9f0a1b2c3), column contract + CHECK/UNIQUE names, ORM parity nullability, FK enforce (project sai bị từ chối), CHECK refuse kind/status/revision<=0/key quá dài, partial-unique workspace-scoped natural_key + idempotency_key (khác workspace được phép trùng key), round-trip upgrade→seed 2 rows thật→downgrade REFUSE fail-closed không mutate gì→purge→downgrade drop đúng bảng→re-upgrade schema giống hệt, integrity_check ok + foreign_key_check rỗng xuyên suốt.
  - API suite 10/10: typed union submit từng kind, replay 200/replayed=true, same-key-different-payload 409, unknown field 422 fail-closed tại boundary, stale revision confirm 409 ZERO durable change rồi revision đúng thành công, re-confirm applied no-op, cancel pending→cancelled, cancel applied 409, cross-workspace GET 404, counts chỉ applied, router OpenAPI uniqueness theo (path, method).
- FULL 3 suites ×2 PASS liên tiếp (adversarial, basetemp khác nhau): s09t05a-r1a/r1b = 36 passed ×2; sau vòng ruff --fix imports chạy lại r2a/r2b = 36 passed ×2. MOTIONFORGE_DATABASE_URL UNSET mọi lần (-p no:cacheprovider).
- Gates cuối: single head OK; models.py zero-removed OK (diff vs HEAD copy = 0 dòng xóa); OpenAPI removed=0 (baseline 241 = after 241); correction paths chưa nằm trong app chính vì router không wire (đúng allowlist — chừa 1 dòng include cho Manager/Codex); integrity_check=ok + FK check=0 + version b3c4d5e6f7a9; ruff All checks passed (app T05A + tests); mypy Success (service+schemas+routes); git diff --check EXIT=0.
- Self-audit write-set: chỉ các file trong allowlist bị tạo/sửa bởi T05A (git status xác nhận: 4 file ?? mới + docs session dir; models.py là M duy nhất do task này trong nhóm app/, còn lại M là dirty tree T00–T04 sẵn có). — DONE

## S09-T05A-C1 — correction validation trước mutation (2026-08-24, resume owner)

- RULES_LOADED lần 2 (đọc lại toàn bộ 180 dòng rules trong lượt hiện tại) + đọc TOÀN BỘ review `docs/pm/reviews/S09_FULL_SPRINT_PM_REVIEW_2026-08-24.md` (F5 P1) + prompt `docs/pm/prompts/S09_C1_FAST_TRACK_MANAGER_2026-08-24.md` mục 7.
- Preflight C1: worktree s08-integration @ codex/s08-integration, HEAD ee10e55a809c (không đổi), MOTIONFORGE_DATABASE_URL UNSET, dirty tree tích hợp không đụng.
- Root cause F5 xác minh bằng probe thật TRƯỚC khi sửa:
  1. `RendererRoute = Literal["direct_composite","keyed_pipeline"]` stale placeholder — không thuộc frozen policy.
  2. route_from/route_to là str tự do; anchors float không bounded; frames không kiểm order; evidence chỉ min_length=1 chưa normalized; NaN/Inf đi qua được.
  3. Route-literal check chỉ chạy lúc CONFIRM (_apply_route_override) ⇒ submit archive được pending row rác rồi mới refuse — đúng kịch bản "invalid blocker" của F5. Probe Pydantic cũ chấp nhận thật: bogus_from/bogus_to/9.0/-2.0/20..1/evidence rỗng (bằng chứng trong LOG pha explore).
- SỬA app/schemas/s09_correction.py: RendererRoute Literal = {pose_swap, sprite_affine, mesh_warp, part_rig, controlled_redraw} + import-time assertion khớp RENDERER_ROUTES (drift ⇒ crash lúc import, không bao giờ fail-open); anchors ge=0 le=1 allow_inf_nan=False; start_frame/end_frame ge=0 + model_validator start<=end; provenance.evidence và override_reason strip + non-empty; provenance.route_from/to phải KHỚP payload; _ID_PATTERN chặn path escape (/, \, .., control chars) trên mọi field id-shape; deep NaN/Inf refusal cho segmentation/provenance/transform; extra=forbid giữ nguyên.
- SỬA app/services/s09_correction.py: `_validated_request` giờ chạy ĐẦY ĐỦ closed-domain check CHO MỌI kind (helper mới `_validate_route_override_request` + `_reject_path_escape_ids` mirror chính xác Pydantic boundary) — chạy TRƯỚC compute_impact LẪN create_correction ⇒ invalid request không bao giờ tạo pending row hay side effect; override_reason/provenance.evidence được normalize in-place vào request_json archive; `_apply_route_override` đổi lấy project_id/video_item_id từ ARCHIVED ROW (đã ownership-asserted ở submit) thay vì request dict — payload không thể trỏ route row về project khác; confirm_correction truyền row.project_id/video_item_id xuống; SegmentNotFoundError import + map 409.
- SỬA app/api/routes/s09_correction.py: import SegmentNotFoundError; gộp Contact/Motion/SegmentNotFound thành `_MISSING_OBJECT_ERRORS` → 409 (ghost segment trước đây rơi vào 500).
- Tests: viết mới tests/test_s09_t05_backend_c1_validation.py (39 tests): contract enum frozen; 19 param Pydantic adversarial (bogus/stale routes, anchors 9/-2/NaN/Inf, frames đảo, evidence rỗng/thiếu/mismatch, path escape segment+manifest, negative frame, unknown field, reason rỗng, confidence>1); normalization valid request; mask deep NaN; 6 param repository-level zero-side-effect (row count + render_route count KHÔNG đổi sau reject); valid submit→confirm→1 render route row mới + idempotent replay same-row; 9 param HTTP adversarial (8×422 + ghost_segment 409) đều zero side effect + valid HTTP deterministic/replay/same-key-diff-payload 409. Viết lại test domain `test_route_override_incomplete_provenance_fails_closed`: hành vi MỚI reject tại submit với zero row (test cũ mã hóa đúng hành vi lỗi F5 nên phải đổi).
- Kết quả focused ×2 PASS liên tiếp (4 suites: c1 39 + domain 18 + migration 8 + api 10): f1a=75 passed (46.99s), f1b=75 passed (46.75s); basetemp %TEMP%/s09t05ac1-f1a|f1b; env -u MOTIONFORGE_DATABASE_URL; -p no:cacheprovider.
- Gates C1: ruff All checks passed trên toàn bộ write-set T05A-C1 (7 file; 1 lỗi I001 duy nhất nằm ở sprite_affine_adapter.py thuộc T02-C1 owner khác — KHÔNG đụng theo write-set); mypy Success 3 source files; git diff --check EXIT=0; không đụng models/migrations/app.py/data/**/MAIN.

## S09-T05A-C3 — immutable applied-regeneration context (2026-08-25, resume owner)

- Đọc TOÀN BỘ `docs/pm/reviews/S09_C2_PM_REVIEW_2026-08-25.md` (F1 P0 + F5 P1) và `docs/pm/prompts/S09_C3_CORRECTION_MANAGER_2026-08-25.md` §3.2 + acceptance S09-T05A-C3 (:167-183).
- Preflight: HEAD ee10e55a809c không đổi; MOTIONFORGE_DATABASE_URL UNSET; dirty tree tích hợp không đụng.
- IMPLEMENT `app/services/s09_correction.py` — method public MỚI thuần đọc `S09CorrectionRepository.applied_regeneration_context(workspace_id, correction_id, *, expected_applied_revision=None) -> dict`:
  - Trả context canonical: correction_id/workspace/project/video, correction_kind, applied_revision (= row.revision sau apply), natural_key, occurrence_segment_id, 4 danh sách affected IDs (sorted+dedup: loop/layer/segment/contact/motion), effect = mutation result canonical nguyên vẹn.
  - `context_sha256` = sha256(canonical-json(context TRỪ chính field sha)); payload chỉ chứa post-apply stable facts (KHÔNG timestamp); applied row bất biến (confirm-replay no-op, cancel bị chặn) ⇒ SHA deterministic qua fresh session/restart.
  - REFUSE fail-closed zero mutation: non-applied pending/cancelled → CorrectionConflictError; expected_applied_revision lệch → CorrectionConflictError (CAS-style stale guard cho T04 verify trước submit job); natural_key thiếu / applied_at thiếu / affected loops rỗng / result malformed-rỗng → CorrectionValidationError; id lạ/cross-workspace → CorrectionNotFoundError. Hash non-serializable → CorrectionValidationError.
- Routes/schemas KHÔNG đụng: contract §3.2 là service-level cho T04 load trực tiếp; không cần surface HTTP additive — giữ behavior confirm hiện tại nguyên vẹn.
- TESTS `tests/test_s09_t05_backend_c3_context.py` (11 tests): shape + recompute SHA độc lập bằng hashlib trong test; deterministic 3 fresh sessions cùng SHA/payload byte-identical; refuse pending/cancelled/empty-loops/malformed-result đều assert durable snapshot (s09_correction/artifact/job/occurrence_segment/apply_checkpoint) bất biến; stale expected revision refuse + exact revision accept; unknown id + cross-workspace 404-style NotFound; replay confirm changed=False giữ revision + SHA ổn định qua cancel-attempt; 3 kind happy-path (mask/z_order/route_override với retarget lineage successor sau supersede + fresh CAS revision) context hợp lệ, effect non-empty, SHA unique giữa các kind.
- Fix vòng 1: request z_order thiếu field `z_order` (required list) → thêm `"z_order": 42`; vòng 2: mask supersede làm predecessor terminal → retarget request về successor (`superseded_by_id`) + luôn gửi revision hiện hành.
- KẾT QUẢ focused ×2 PASS liên tiếp (5 suites T05: c1 39 + c3 11 + domain 18 + migration 8 + api 11): f1a=87 passed (70.11s), f1b=87 passed (70.19s); basetemp %TEMP%/s09t05ac3-f1a|f1b; env -u MOTIONFORGE_DATABASE_URL; -p no:cacheprovider.
- Gates C3: ruff All checks passed (8 file write-set); mypy Success 1 source file; git diff --check EXIT=0 (chỉ CRLF warning sẵn có của dirty tree); write-set chỉ app/services/s09_correction.py + tests/test_s09_t05_backend_c3_context.py; KHÔNG đụng s09_demo_jobs.py, s09_demo_compare.*, renderer files, frontend, models, migrations.



## S09-T05A-C4 — canonical render context cho cả 5 kinds (2026-08-26, resume owner 20260824_072626_645cde)

- RULES_LOADED lần 3: đọc TOÀN BỘ rules (180 dòng) + review C3 `docs/pm/reviews/S09_C3_PM_REVIEW_2026-08-26.md` + contract C4 `C:/Users/Admin/MotionForge2D/docs/pm/prompts/S09_C4_CORRECTION_MANAGER_2026-08-26.md` §4.1–§4.6 + acceptance T05A-C4. Preflight: HEAD ee10e55a809c không đổi; MOTIONFORGE_DATABASE_URL UNSET; re-hash J1-v4 manifest SHA ae92247b8bfd7bf2a43dcfcd83f71ac91603c86fa9f59b9c34d4c254df18d0d5 + 13/13 file ZERO drift (verify lại lần 2 sau mọi thay đổi — vẫn NONE).
- Trạng thái resume: service đã mang khối render_effect C4 (WIP của chính session này trước khi đứt) nhưng còn 3 lỗi thật phát hiện bằng đọc code + test:
  1. **SHA-drift bug (F3/immutability)**: `_context_layer_binding` re-derive từ LIVE rows MỖI lần gọi context ⇒ một correction supersede cùng lineage SAU đó làm payload context cũ đổi → SHA drift → vi phạm điều khoản 4 (replay same SHA). Không test nào chốt kịch bản stacking.
  2. **Guard sai thứ tự**: `_context_layer_binding` chạy trong applied_regeneration_context (read-path) chứ KHÔNG chốt tại confirm-time; impact thiếu stable layer ids chỉ bị refuse khi ĐỌC, không phải trước mutation.
  3. **mypy attr-defined**: `Artifact.byte_size` không tồn tại trên model (thật ra là `size_bytes`) ⇒ getattr luôn None — evidence byte_size chết.
- FIX app/services/s09_correction.py (additive, KHÔNG đổi mutation logic hiện có):
  - confirm_correction giờ resolve stable layer ids từ archived impact (`_impact_layer_ids` mới — authority là impact_json đã compute_impact lúc submit, không nhận request field) và prove live binding tồn tại TRƯỚC `_apply_mutation` (pure read, zero write khi raise), sau mutation freeze POST-APPLY binding snapshot vào `result["applied_layer_bindings"]` rồi mới archive result.
  - applied_regeneration_context đọc `applied_layer_bindings` từ result đã lưu (ưu tiên), fallback re-derive cho legacy row ⇒ context + SHA byte-stable qua restart VÀ qua supersede chồng.
  - `_context_layer_binding` docstring cập nhật đúng semantic mới (derive once, frozen at confirm).
  - mask render_effect: `byte_size` lấy đúng cột `size_bytes`; mypy sạch.
- TESTS tests/test_s09_t05_backend_c4_render_effect.py: thêm 3 test (tổng 7):
  - `test_zorder_and_mask_and_route_contexts_carry_canonical_effects`: per-kind completeness z_order (target_layer_id=logical_id ổn định, target_segment_id ∈ bound_segment_ids, applied_layer_bindings ≡ layer_bindings), mask (artifact store evidence: id/sha256-64/path/kind/byte-size cột thật + semantics version s09-mask-semantics-v1 + confidence_source manual + retarget successor đúng lineage), route_override (target segment CHÍNH XÁC phone, route_from/to, frame_range {20,90}, anchor {0.25,0.75}, provenance.evidence, render_route_id khớp history row).
  - `test_context_sha_immutable_when_lineage_superseded_later`: REGRESSION của bug 1 — apply z_order #1 → supersede cùng logical_id lần 2 → context #1 byte-identical + same SHA; context #2 khác SHA, cùng affected_layer_ids ổn định; replay cả hai fresh session ×2 identical.
  - `test_confirm_refuses_impact_without_stable_layer_ids_zero_mutation`: impact legacy chỉ có label ("Phone") → confirm raise CorrectionValidationError TRƯỚC mọi durable write (snapshot occurrence_segment/s09_correction/artifact/job/segment_motion/scene_graph_contact/apply_checkpoint bất biến).
- KẾT QUẢ focused gate ×2 PASS liên tiếp (5 suites T05: c3 12 + c4 7 + domain 18 + migration 8 + api 11 = 56):
  - f2a = 56 passed (52.98s), basetemp C:/Users/Admin/AppData/Local/Temp/s09t05ac4-f2a
  - f2b = 56 passed (52.86s), basetemp ...s09t05ac4-f2b
  - lệnh: `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t05_backend_c3_context.py tests/test_s09_t05_backend_c4_render_effect.py tests/test_s09_t05_backend_domain.py tests/test_s09_t05_backend_migration.py tests/test_s09_t05_backend_api.py -p no:cacheprovider -q --basetemp=<mỗi run một basetemp>`
  - (f1a/f1b trước fix mypy cũng 56+56; fix size_bytes chỉ đổi giá trị byte_size nên rerun f2 xác nhận.)
- Gates C4: ruff All checks passed (8 file write-set); mypy Success app/services/s09_correction.py; git diff --check EXIT=0 (chỉ CRLF warning sẵn có dirty tree); freeze J1-v4 re-hash ×3 NONE drift; I03/I05 SHAs không đụng (không rerun benchmark).
- Write-set attribution: chỉ app/services/s09_correction.py + tests/test_s09_t05_backend_c4_render_effect.py được sửa hôm nay (mtime 13:xx); routes/schemas KHÔNG đụng (additive result key đi qua `dict[str, Any]` sẵn có); KHÔNG đụng s09_demo_jobs.py, s09_demo_compare.*, renderer files, frontend, models, migrations, MAIN, 13-file freeze set.

## Verification re-run (fresh evidence, cùng phiên C4)

- v1: `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t05_backend_c3_context.py tests/test_s09_t05_backend_c4_render_effect.py tests/test_s09_t05_backend_domain.py tests/test_s09_t05_backend_migration.py tests/test_s09_t05_backend_api.py -p no:cacheprovider -q --basetemp=%TEMP%/s09t05ac4-v1` → **56 passed** (53.01s)
- v2: same command, basetemp `%TEMP%/s09t05ac4-v2` → **56 passed** (52.84s)
- ruff (service + c4 test file): All checks passed
- mypy app/services/s09_correction.py: Success
- Freeze J1-v4 re-hash: manifest ae92247b… OK, 13/13 ZERO drift; git diff --check EXIT=0

Không có code thay đổi sau các run này. STATUS giữ nguyên: TASK_MANAGER_VERIFIED / PENDING_CODEX_REVIEW.

## Verification re-run #2 (fresh evidence turn, cùng phiên C4)

- Precondition: mtime 2 file changed (service 13:41:47, c4-test 13:34:42) — KHÔNG có edit nào sau lần xanh trước.
- v3: `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_s09_t05_backend_c3_context.py tests/test_s09_t05_backend_c4_render_effect.py tests/test_s09_t05_backend_domain.py tests/test_s09_t05_backend_migration.py tests/test_s09_t05_backend_api.py -p no:cacheprovider -q --basetemp=%TEMP%/s09t05ac4-v3` → **56 passed** (52.50s)
- v4: same command, basetemp `%TEMP%/s09t05ac4-v4` → **56 passed** (52.79s)

Gate ×2 fresh PASS. Không code đổi sau các run. STATUS giữ nguyên: TASK_MANAGER_VERIFIED / PENDING_CODEX_REVIEW.
