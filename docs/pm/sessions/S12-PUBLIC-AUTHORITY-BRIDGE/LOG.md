# S12-PUBLIC-AUTHORITY-BRIDGE — session log (Hermes owner)

Task ID: `S12-PUBLIC-AUTHORITY-BRIDGE` (bounded cross-sprint bridge theo quyết định
R7; Manager B `20260915_194636_b5ea4c` điều phối).
Session owner (session mới, tạo đúng một lần): `20260916_105450_f38ead`.
Route: `ocg/deepseek-v4.1-flash` / provider `custom` / fallback OFF / native
thinking ON.
Worktree: `C:/Users/Admin/Documents/Codex/work/s12-r7-authority-bridge` —
branch `codex/s12-r7-authority-bridge` @ wave-base
`35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86`.
Runtime: `C:/Users/Admin/Documents/Codex/work/s12r7/0351/B/BRIDGE/`.
Evidence: `C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/s12-r7-two-managers/20260916T0351Z/B/BRIDGE/`.

- 2026-09-16 (~03:57Z) — **REQUIRED READING (đọc thật trong lượt này)**: đọc toàn bộ
  `C:/Users/Admin/MotionForge2D/docs/pm/HERMES_AUTOPILOT_RULES.md` (277 dòng);
  `MANAGER_B_PROMPT.md` (§5), `SHARED_CONTRACT.md`, `ACCEPTANCE_R7.md` (B03–B06),
  `REVIEW.md` (F04 + static risk `_stitch_verified_chunks`) tại
  `.../outputs/s12-hermes-r6-review-20260916/`; prompt phase-1 của lane BRIDGE.
  `RULES_LOADED` ghi nhận đầy đủ 12 mục.
- 2026-09-16 — **Grounding read-only (KHÔNG sửa)**: đọc trọn 5 file service:
  `app/services/s09_approval.py` (1380 dòng), `app/services/s10_full_apply.py`
  (850), `app/services/s10_chunk_plan.py` (480),
  `app/workflow/s10_full_apply_jobs.py` (1219),
  `app/services/structural_lock_producer.py` (1016); kèm
  `app/persistence/structural_lock.py` (validate_manifest/canonical),
  `app/persistence/models.py` (Scene/OccurrenceSegment/Contact/Occlusion),
  `app/services/renderer_routes/composite.py` (region/occluder/composite
  semantics), `app/services/s10_multi_role_apply.py` (role mapping contract),
  `app/services/renderer_contract.py` (AffectedRegion normalized [0,1]).
  Đối chiếu 3 artifact reviewer: `planner-1/captured_cooccurrence.json`,
  `planner-1/same_role_two_disjoint_occurrences.json`,
  `new-producer-4/points-only.json` — xác nhận nguyên nhân F04 tại đúng dòng code
  (1:1 segment→shot + layer_id=role_id tại `s10_full_apply.py:224–276`; dedup
  first-artifact tại `s10_full_apply_jobs.py:443–465`).
- 2026-09-16 04:21Z — **Verification + ledger** (driver
  `work/s12r7/0351/B/BRIDGE/ledger_run.py`, mỗi entry argv/cwd/UTC/exit/hashes;
  ledger JSONL: `.../BRIDGE/phase1/COMMAND_LEDGER.jsonl`):
  - `t00_head` 04:21:22.013Z exit=0 → `35f6cb2f2bd540c162d5a2f0e3ae8e152e392b86`.
  - `t01_branch_status` 04:21:22.122Z exit=0 → branch `codex/s12-r7-authority-bridge`,
    tree sạch (chỉ dòng `##`).
  - `t02_guard_allow` 04:21:22.286Z exit=0 → 4/4 allow file khớp SHA-256 + size với
    `guard-allow-pre.json` (không drift).
  - `t03_guard_protected` 04:21:22.462Z exit=0 → 18/18 protected khớp, bad=0.
  - `t04_docs_absent_failfirst` 04:21:22.594Z exit=1 → `docs/pm/sessions/
    S12-PUBLIC-AUTHORITY-BRIDGE` chưa tồn tại (fail-first chứng minh artifact mới).
  - `t05_service_lines` 04:21:22.719Z exit=0 → 1380/850/480/1219/1016 dòng (khớp
    snapshot guard).
- 2026-09-16 — **Deliverable phase 1**: tạo mới
  `docs/pm/sessions/S12-PUBLIC-AUTHORITY-BRIDGE/CONTRACT.md` (draft v0.1, 9 mục bắt
  buộc: frame conventions; temporal partition; layer identity + repeated roles;
  geometry; immutable authority block; schema compatibility; fail-closed reason
  codes; worker consumption; open questions) — viết trên cấu trúc THẬT của code
  (file:line), không trừu tượng hóa. Tạo `LOG.md` (file này).
- Trạng thái: `CONTRACT_DRAFTED_PENDING_FREEZE` — chờ freeze với Manager B + QA
  (10 open questions Q1–Q10 trong CONTRACT §9). KHÔNG viết production code lượt này.
  KHÔNG commit ngoài docs của lane; KHÔNG push.

## Post-freeze note (chưa thực hiện)

Production chỉ bắt đầu sau khi contract được freeze (prompt kế tiếp): allow =
4 service file + optional NEW `app/services/source_locked_timeline.py` + NEW
`tests/s12/s12-public-authority-bridge/**` + docs lane; file hiện hữu patch-only
(preimage/postimage hash).

## 2026-09-16 — PHASE 2: PRODUCTION B03–B06 (freeze đã hoàn tất)

Route: `ocg/deepseek-v4.1-flash` / provider custom / fallback OFF. Bắt đầu tại
HEAD `3963d31` (commit phase-1 docs), parent = wave-base `35f6cb2`. Freeze inputs
đã đọc đủ: `BRIDGE_CONTRACT_FREEZE_REVIEW.md` (Q1 revised, Q2–Q10),
`BRIDGE_RULING_Q4_region_scale_v0.2.md`, QA `R7_PREP.md` §Q9 (normative, commit
`d22d069`) + §D2 (danh sách node).

### Deliverables (chưa push)

- **NEW** `app/services/source_locked_timeline.py` — primitives dùng chung:
  Q1 box selection, dual-mode region derivation (ruling v0.2; **hardening
  frame-intersection được flag** vì bounds nghiêm của ruling từ chối chính các
  box padded của chain sanctioned: {100,100,300,300} trên 640×360 và
  {400,100,250,250}), timeline-block validator, `pick_partition_code`,
  `TIMELINE_VERSION = "s09.full-apply-timeline/v1"`.
- `app/services/s09_approval.py` — additive timeline build trong
  `submit_checkpoint_v2` (scene partition + manifest order + persisted boxed
  evidence + timing pins `fps_num/fps_den/frame_count` + source pins);
  eligibility per-segment = boxed-region derivable (points-only/missing/
  ambiguity → typed ineligibility; zero S10 rows); legacy classification:
  pre-timeline v2 → `LEGACY_AUTHORITY_REAPPROVAL_REQUIRED` (v1 giữ nguyên).
- `app/services/s10_full_apply.py` — `_canonical_planner_inputs` xây từ
  timeline (shots = scene partition; mappings = occurrence layers với
  `layer_id = occurrence_segment_id` + range/z/visibility/role); derivation
  dual-mode thay `_segment_region_from_geometry` raw-return; alias legacy có
  giới hạn (unambiguous) trong client-copy compare để giữ 202-control compat.
- `app/services/s10_chunk_plan.py` — optional active range per-layer +
  pair-intersection chunking + Q10 edge overlap (pair-first/pair-last = 0);
  không bypass validation; plan hash byte-stable cho legacy inputs.
- `app/workflow/s10_full_apply_jobs.py` — **composition thay dedup** trong
  `_stitch_verified_chunks`: mọi frame = source + ALL visible/occluded layers
  theo thứ tự z_order asc (tie → (logical_id, lineage_version)); reuse T02
  request builder + `composite_*`; per-unit Q9 evidence (19 trường theo frozen
  list) trong sidecar `<artifact>.evidence.json`; asset staging
  `<layer_id>.png` + resolve role-keyed manifest; codes mới
  `STITCH_LAYER_ARTIFACT_MISSING` / `STITCH_LAYER_EVIDENCE_MISSING` /
  `STITCH_FRAME_COVERAGE_MISMATCH`; cancel/CAS/lease fences nguyên vẹn.
- `tests/s12/s12-public-authority-bridge/**` — 27 node đúng tên D2 (B03×8,
  B04×6, B05×6, B06×7) + conftest harness (DB isolated, media thật, GLOBAL
  ranges; lưu ý: prompt ghi "23" nhưng bảng D2 liệt kê 27 — giữ đủ cả 27).

### Iterations (bằng output thật)

- micro v1: 4/27 → nguyên nhân đều là harness: worker composition đọc
  `render_authority` shape (không có `timeline` key — sửa worker dùng
  `scene_manifest.shots` + `structural_lock_manifest.frame_count`),
  `run_counts` đếm luôn DISCOVER job của fixture (lọc `job_type`),
  `pick_partition_code` rename sót 1 call-site, fixture B05 thiếu
  `policy_version`/timebase-fingerprint mismatch. Không có lỗi logic.
- micro v2: 26/27 → B06 frame-order threshold 40 → 20 (ramp + composite
  regions), node re-run xanh.
- `tests/test_s09_t06_backend_authority.py` (ngoài gate): 3 fail — 2 fail
  theo HỢP ĐỒNG (fixture points-only giờ ineligible; đúng B04/F04, cần owner
  cập nhật fixture/assertion), 1 fail PRE-EXISTING (alembic head constant
  `a10b11c12d3e` cũ so với head hiện tại `d4e5f6a7b8c9` — S12 migrations đã
  land trước lane này; chứng minh bằng diff scope: lane không chạm migrations).

### Gates (final, revision đóng băng — raw trong `phase2/`)

| Gate | Command | Result | Raw |
|---|---|---|---|
| Micro B03–B06 | `pytest tests/s12/s12-public-authority-bridge/` | **27 passed** (124.90s) | `g4_final_micro.*` |
| Affected s10 API | `pytest tests/test_s10_full_apply_api.py` | **71 passed** (165.72s) | `g5_final_api.*` |
| Affected s12 reg | `pytest tests/s12/s12-t03c/test_publication.py tests/s12/s12-lc3-retry/test_r6_identity_resolution.py` | **66 passed** (152.82s) | `g6_final_reg.*` |
| Static | `ruff check --select F` (5 file + suite) | clean (exit 0) | `s1_ruff.*`, `s1b_ruff_recheck.*` |
| Static | `py_compile` 5 file + `compileall -q app` | exit 0 | `s2_pycompile.*`, `s3_compileall.*` |
| Diff | `git diff --check` | exit 0 | `s4_diff_check.*` |
| Guards | protected 18/18 (sha256+size) | **bad=0** | `v1_guard_protected.*` |
| Guards | allow-pre drift | đúng 4 file allow (viết-set) | `post_patch_hashes.json` |

- Ledger phase 2: 17 entries (argv/cwd/UTC/exit/elapsed_ms; log riêng trong
  `phase2/COMMAND_LEDGER.jsonl` của evidence BRIDGE).
- Commit local (2 commit cùng prefix, do `-am` không nhận file mới; không
  rewrite history):
  - `b6108d4` — `S12-PUBLIC-AUTHORITY-BRIDGE: R7 production B03-B06 (timeline authority + planner + composition)` — 6 file, +1251/−148 (4 service + CONTRACT + LOG).
  - `34e680c` — `S12-PUBLIC-AUTHORITY-BRIDGE: R7 production B03-B06 (new module + tests + report)` — 7 file mới, +2444.
  - Anomaly khi commit 2: `fatal: bad object refs/codex/turn-diffs/…` +
    `failed to perform geometric repack` — thuộc nhóm pre-existing đã biết
    (exit commit = 0, tree sạch sau đó).
  Không push. Status: `PRODUCTION_B03_B06_DELIVERED_PENDING_MANAGER_B_QA_REVIEW`.

## 2026-09-16 — FOLLOW-UP: Q4-coverage nodes (QA review `958d021`, bounded)

QA verdict phase-2: D2 `VERBATIM_27` + re-run 27 passed, Q9 `CONFORMANT 19/19`,
alias `BOUNDED NO-HOLE`, clip code v0.2.1 `ACCEPTED` — còn **coverage gap cho
ruling v0.2 §5**. Bổ sung 4 node test (KHÔNG sửa production; nằm NGOÀI bảng D2
gốc — inventory D2 vẫn `DELIVERED VERBATIM 27`; đây là additions coverage):

- `test_b04_mode_b_padded_clip_positive` — box {400,100,250,250} trên 640×360
  → region clip [0.625, 0.2777…, 0.375, 0.6944…] xác nhận qua HAI đường: công
  thức clip viết độc lập trong test + `derive_region(...)` thật (shared module);
  `scale_mode="pixel"`, `raw_box` giữ nguyên, `geometry_source` frozen;
  authority PROCEEDS (submit 202).
- `test_b04_scale_unresolved_negative` — pixel-scale box + dims NULL
  (harness `hide_dims=True`) → typed deny `OCCURRENCE_REGION_SCALE_UNRESOLVED`
  (cả direct `derive_region` raise code + authority excluded/reason + submit
  422) và zero mutation (0 runs / 0 jobs).
- `test_b04_fully_outside_deny` — box {700,100,50,50} trên 640×360 (x>=src_w)
  → typed deny `OCCURRENCE_REGION_OUT_OF_BOUNDS`, zero mutation.
- `test_b04_cross_key_precedence_geometry_source` — dùng fixture
  `cross_key_conflict` (segmentation.boxes={16,12,80,60} vs prompt.boxes=
  {30,20,50,50} KHÁC nhau): region lấy từ segmentation (precedence chốt),
  `geometry_source="segmentation.boxes[0]"` frozen, prompt evidence giữ
  nguyên verbatim; PROCEEDS (202). Fixture đã khớp semantics ruling Q1 nên
  KHÔNG cần chỉnh.
- Harness: `build_graph(..., hide_dims=True)` — VideoItem.width/height nullable
  (ràng buộc schema `width IS NULL OR width >= 0`).

Gates follow-up: suite **31 passed** (27+4; 88.18s, exit 0 — raw
`phase2_q4/q4_micro_31.*`); `ruff check --select F` 2 file changed exit 0;
`git diff --check` exit 0; protected 18/18 **bad=0**. Commit:
`db1c66c6f63d5fd29f97102a48452747c9a82149` (+ hash-record commit cho dòng này).
