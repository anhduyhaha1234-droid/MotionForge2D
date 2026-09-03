# S11-T04A — Worker REPORT (W9)

## 1. Task identity

| Field | Value |
|---|---|
| Task ID | S11-T04A |
| Wave | W9 (song song T06B — write-set RIÊNG, không đụng) |
| Worktree | `C:\Users\Admin\MotionForge2D-worktrees\s11-t04a-0903w9` |
| Branch | `codex/s11/t04a-0903w9` (local; không push/merge/rebase/reset/clean/stash/force) |
| WAVE_BASE | `b2501598078c702d875f57ac0a17a78e3e40237b` (porcelain 0 tại start) |
| Model | `custom` / `ocg/deepseek-v4-flash`, reasoning max, fallback off |
| Status | TASK_SUBMITTED |

## 2. Verdict per acceptance criterion (ALL GREEN — 4/4)

**AC1 — Với MỖI layer_ref_type có thật trong fixtures: GET navigation trả target URL/endpoint tồn tại (test assert endpoint EXISTS bằng cách gọi thật trên temp DB/app).**
- 8 kinds seeded (7 canonical + video_item): `frame, object, audio, scene, segment, render, route, video_item`.
- Resolver test: mỗi kind → `action.kind="navigate"` + `endpoint` khớp template ĐÃ ĐĂNG KÝ trong OpenAPI thật (`app.openapi()` → 272 paths; 9 template target đều present, log xem phân tích trong LOG).
- API test: `GET /api/v2/qc-navigation/{item_id}` → 200; sau đó GỌI THẬT target trên temp app qua TestClient: status ∈ (200,400,404) + content-type JSON — endpoint dispatch thật, không phải plain-text 404 của path chưa đăng ký. Per-kind target:
  - `frame` → `/api/projects/{project_id}/frames/{frame_index}` (serve_frame frames.py) + `?scene_id=`
  - `object` → `/api/projects/{project_id}/objects/{object_id}/gallery` (gallery route projects.py); fallback `roles/{role_id}/occurrences` khi chỉ có object_role_id
  - `audio` → `/api/jobs/{job_id}` (job info — REVIEW_QUEUE_CONTRACT §2 audio, ATTACH_ORIGINAL_AUDIO context)
  - `scene` → `/api/projects/{project_id}/scenes/{scene_id}/objects` (segments/scenes endpoint; fallback `/scenes` list)
  - `segment` → `/api/v2/structural-evidence/segments/current/{segment_id}` (structural-evidence read authority)
  - `render` → `/api/projects/{project_id}` (project page)
  - `route` → structural-evidence segment endpoint + `renderer_route` meta qua structural_lock contract `RENDERER_ROUTES`
  - `video_item` → `/api/projects/{project_id}` (video-level issue — project page family)

**AC2 — Issue ngoài phạm vi rerun V1: vẫn có navigation + `action.kind=explain` với lý do — không đích chết, không crash.**
- `test_explain_action_when_anchor_missing[5 cases]` + `test_api_explain_action_when_role_frame_missing`: 200, `action.kind="explain"`, `target=None` (no dead link), `code` + `reason` (tiếng Việt):
  - `missing_frame_anchor`, `missing_object_anchor`, `missing_job_id`, `missing_segment_id`, `renderer_route_outside_contract`.
- Canonical location VẪN có mặt trong response explain case (AC3 không vi phạm).

**AC3 — Canonical location bắt buộc trong response; thiếu → 500 fail-closed stable error (không tự đoán).**
- `canonical_location` present trong MỌI response (test assert 4 fields `scene_id/frame_index/timecode_ms/object_role_id` + segment ids); nguồn CHỈ structured: evidence keys typed + QCItem fields — `test_canonical_location_never_parsed_from_free_text` (text "frame 42 scene 0 role-9" → all None), `test_canonical_location_typed_fail_closed` (str/float → None, không coerce).
- Unknown kind (`mystery_kind`) → `NavigationResolutionError(code="unknown_kind")` → HTTP 500 stable envelope `{"detail": {"code": "unknown_kind", "message": ...}}` — test API assert không có target nào bị đoán (`test_api_unknown_kind_fail_closed_500`).
- Missing item → 404; foreign workspace → 404 (fail-closed ownership, zero leak).

**AC4 — Router mới CHỈ GET (Decision A); app.py +1 dòng.**
- Source grep: `@router.get` = 2 (cùng route 2 path variants), mutation decorators = 0.
- `app.py`: đúng 1 `include_router(qc_navigation.router)`; diff additive +2 dòng (import + include); baseline hash cccb80cd… → c2f00c51… sau patch.
- OpenAPI: `/api/v2/qc-navigation/{item_id}` methods == {get} (test).

## 3. Điểm thiết kế (khớp trace/contract)

- Mapping 1-1 theo REVIEW_QUEUE_CONTRACT §2 — target CHỈ từ endpoint đã đăng ký thật (không phát minh URL).
- Renderer route: import-only `RENDERER_ROUTES` từ models (structural_lock contract); `renderer_route` chỉ được mang khi value trong enum; ngoài contract → explain fail-closed (DEPENDENCY_MATRIX mục 4 consume vế MISSING — navigation giờ đọc được route từ contract).
- KHÔNG suy diễn từ text tự do (MASTER_PLAN §10); sai kiểu → treated-as-absent, không coerce.
- 500 fail-closed thay vì tự đoán khi kind ngoài canonical set (kể cả `video_item` vẫn có mapping rõ ràng).

## 4. Evidence (raw, docs/pm/sessions/S11-T04A/evidence/)

| File | Nội dung |
|---|---|
| `baseline.txt` | porcelain head/branch/app.py hash lúc start |
| `full_verbose.txt` | 37 passed verbose — per-kind endpoint-exists + explain + canonical asserts |
| `regression_t02b.txt` | 40 passed (T02B readonly + repository lifecycle — app.py patch không phá surface) |
| `static_gates.txt` | ruff --select F 6 files; py_compile 4 prod; GET-only grep; include count 1; alembic head |

## 5. Isolation flags

- `--basetemp=C:/Users/Admin/AppData/Local/Temp/s11t04a_*` (short unique), `-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`.
- `env -u MOTIONFORGE_DATABASE_URL`; mỗi test SQLite tạm riêng (alembic upgrade head qua `_patch_project_root`); không đụng canonical tree.

## 6. Verdict

ALL GREEN — TASK_SUBMITTED. Commit local duy nhất trên `codex/s11/t04a-0903w9` (SHA ghi trong LOG + session registry manager nhé).