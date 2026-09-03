# S11-T06A1 REPORT — Deterministic media/QC seed infrastructure (W3)

Status: **TASK_SUBMITTED** (chờ Manager verify; KHÔNG tự ghi MANAGER_VERIFIED/APPROVED)
Branch/Worktree: `codex/s11/t06a1-0903w3` @ `C:\Users\Admin\MotionForge2D-worktrees\s11-t06a1-0903w3`
WAVE_BASE: `cd4f7925b9f924e19887ea3e7498c985fa28f454` | Commit: LOCAL, xem git log (không push)

## 1. Write-set (allowlist — 10 file mới, KHÔNG sửa file hiện hữu nào)

| File | Nội dung |
|---|---|
| `tests/s11_qc_media_builders.py` | 7 builder ffmpeg-lavfi deterministic (two_scene_source, multistream duration-variant 3s/4AAC, non-MP4 mkv, vp9, mpeg4, corrupt truncate, no_audio) + `probe`/`probe_facts` + `build_all_media` 1-lệnh + `load_manifest`/`iter_manifests`; MỖI builder assert-sau-khi-dựng bằng ffprobe thật (codec/duration/streams, fail-fast lane-B §3.4) |
| `tests/s11_qc_seed.py` | Seed QC items QUA `QCItemRepository` (Decision A — không HTTP POST): `seed_workspace_project_video` FK-chain upsert idempotent, `seed_qc_items_for_manifest` (seed_plan của manifest), `seed_all_reason_codes` (full 8 codes), evidence tối thiểu hợp lệ deterministic, `count_qc_items`/`list_qc_items` |
| `tests/test_s11_t06a1_fixture_harness.py` | Self-test 8 tests: manifest schema, dataset 1-lệnh vs manifest, determinism ×2, corrupt decode-reject, seed full codes, idempotent natural-key, seed per-manifest + negative empty, no-orphan ffmpeg; msvcrt lock machine-wide; cleanup best-effort |
| `tests/fixtures/s11_qc/media_manifests/*.json` (7) | Manifest v1 frozen: scenario → builder+params+relative_path + probe_expectations (format family, duration±tol 0.35, streams codec/count — KHÔNG hash cứng cross-machine) + seed_plan (negative scenarios: seed_plan rỗng — engine reject media at import, W7: no_audio → zero QCItem) |

KHÔNG đụng: `tests/fixtures/s11_golden/` (không tồn tại — cấm tuyệt đối), `thresholds.py` (không tồn tại), conftest.py (chỉ CONSUME fixture `_patch_project_root` — không sửa), `app/**`, `frontend/**`, MAIN, test S11-T01.

## 2. Đối chiếu Acceptance Criteria (binary — bằng chứng thật)

**AC1 — Một lệnh dựng toàn bộ dataset media vào temp dir, không network, không binary committed.**
ĐẠT. `build_all_media(dest)` = 7 file vào basetemp; harness `test_build_all_media_dataset_matches_manifests` build + re-probe từng file; toàn bộ nguồn = lavfi synthonics + encoder local (xffmpeg 8.1.2 gyan.dev). Không download, không file media trong git (git status chỉ 10 file mới, 0 binary).

**AC2 — grep allowlist diff: ZERO tham chiếu qc_thresholds.json/thresholds.py/expected-outcome/calibration.**
ĐẠT. `git diff cd4f7925... -- <allowlist> | grep -inE "qc_thresholds|thresholds\.py|expected[-_ ]outcome|calibration"` → rỗng, GREP_EXIT=1. (Lưu ý kiến trúc: test không chứa chuỗi cấm nên không có false-positive — grep chạy trên diff thật.)

**AC3 — Seed tạo QCItem MỌI reason_code qua REPOSITORY (không POST HTTP), evidence tối thiểu hợp lệ.**
ĐẠT. `seed_all_reason_codes` → 8/8 codes (trajectory_drift, cut_drift, contact_break, z_order, clipping, identity, flicker, audio_timecode), status=open, severity=warning, evidence `{schema_version:1, seed_source:"s11_qc_seed", manifest:{...}, media:{...}}` (non-empty, có schema_version). Chạy thật: `ev_seed_counts.py` (evidence/seed_counts.json) + harness test xác nhận. Đi qua `QCItemRepository.create` duy nhất — natural key 7 cột, ON CONFLICT DO NOTHING (C4-F1).

**AC4 — Self-test harness xanh độc lập; cleanup basetemp không mồ côi.**
ĐẠT. Harness 8/8 xanh ×3 (r1 10.69s, r2 10.71s, final 10.61s, EXIT 0 cả 3) với `-p no:cacheprovider`, `--basetemp` ngắn unique pid+seq, `env -u MOTIONFORGE_DATABASE_URL`, SQLite temp qua `_patch_project_root`. Cleanup: module temp dirs `rmtree(ignore_errors=True)` ở session teardown + pytest tự dọn basetemp; `test_no_orphan_ffmpeg_processes` assert 0 survivor sau build (ownership-scoped pid scan). Basetemp verified không mồ côi (basetemp nằm dưới %TEMP%, pytest xoá cuối session).

## 3. Isolation (lane-B §4 / RESOURCE_PLAN §3 — đủ C1/C2/C3)

- C1 basetemp ngắn: `C:/Users/Admin/AppData/Local/Temp/s11t06a1-w3-r1-<pid>-1` dạng `s11t06a1-w3-<tag>-<pid>-<n>` (không chain MAX_PATH).
- C2 lock nested: `%TEMP%/s11-t06a1-suite.lock` msvcrt `LK_NBLCK` retry 0.25s (pattern T01D C2) — autouse session fixture.
- C3 env strip + temp DB: mọi lệnh pytest `env -u MOTIONFORGE_DATABASE_URL`; seed tests dùng fixture `_patch_project_root` (alembic upgrade head vào `test_root/data/test.db`, managed root `test_root/artifacts`); evidence script dùng Base.metadata.create_all trên DB riêng `%TEMP%/.../seed_evidence.db`. Zero chạm `data/motionforge.db`.
- Process hygiene: subprocess list-args, timeout ≤120s, assert rc==0; no orphan ffmpeg (test 8).

## 4. Determinism ×2 (bằng chứng)

- Harness `test_determinism_two_runs_identical_probe_facts`: build toàn dataset 2 lần (run1/run2), `probe_facts` BẰNG NHAU từng scenario (kể cả corrupt: `probe_ok=False, size_bytes=13219` + error đã scrub deterministic); 6/7 file **byte-identical** giữa 2 run.
- Ngoại lệ duy nhất có chủ đích: `unsupported_non_mp4` (.mkv) — Matroska muxer inject SegmentUID RANDOM mỗi lần mux (kiểm tra `-h muxer=matroska`: không có option tắt) → byte-identity bất khả thi về kiến trúc; determinism contract cho scenario này = probe facts + size (đều bằng). Đã note rõ trong code + báo cáo — không giấu.
- Không assert hash cứng cross-machine (lane-B §1.1).

## 5. Trạng thái snapshot (thời điểm submit)

- `git status --porcelain`: 0 file modified; 10 file untracked → đã add allowlist + docs/S11-T06A1.
- HEAD trước commit: `cd4f7925...` (WAVE_BASE) — chưa push/rebase/merge.
- Evidence files: `docs/pm/sessions/S11-T06A1/evidence/{probe_facts.json, seed_counts.json, run1.txt, run2.txt}`.

## 6. Ghi chú ownership (cho Manager/Codex review)

- T06B consume: manifests (builder theo TÊN + params — không inline trùng media params), `build_all_media`, `probe_facts`, seed plan; golden manifest T06B sẽ gắn expectation riêng (ngoài phạm vi T06A1).
- T06A2 calibration: KHÔNG nằm trong T06A1 — zero tham chiếu (AC2). T03A thresholds: zero tham chiếu.
- `app/persistence/qc_items.py`: CHỈ import (bất biến — T02B ownership).
- W3 là serial wave: 1 worker duy nhất, session mới, không resume task khác.
---

## 7. CORRECTION C1 — Finding P1 (contract violation) — RESOLVED

**Finding:** media manifests dùng reason-code KHÔNG tồn tại trong enum binding mới
(T02A-C1: 10 codes = 8 overlay + 2 audio) → seed fail DB CHECK tại gate cumulative
(28 fail; 2/2 harness test seed fail).

**Root cause:** manifest seed_plan freeze từ trước T02A-C1; harness/seed không hardcode
nên KHÔNG phải nguồn lỗi (scan xác nhận zero token cũ trong seed + builders + harness).

**Fix (hữu hạn, 2 file):**
| Manifest | Trước (cũ) | Sau (binding 10 codes) |
|---|---|---|
| `two_scene_source.json` | trajectory_drift, cut_drift, identity, flicker | trajectory_drift, cut_drift, identity_drift, temporal_flicker |
| `multistream_duration_variant.json` | audio_timecode, cut_drift, clipping | audio_missing, av_sync_drift, cut_drift (2 audio riêng Decision D + cut_drift) |

Giữ nguyên semantics fixture: two_scene = 4 overlay trên 2-cảnh; multistream 5-stream audio = 2 audio codes + cut_drift. Negative scenarios (unsupported/corrupt/no_audio) giữ seed_plan rỗng.

**Verify (thật, sau sửa):**
- grep zero token cũ trong manifests + seed + builders + harness → RESCAN_EXIT=1 ✓
- Harness: 8 passed in 10.77s, EXIT 0 (fresh basetemp `s11t06a1-c1-463-1`, `-p no:cacheprovider`, `env -u MOTIONFORGE_DATABASE_URL`) ✓
- Seed AC3: 10/10 reason codes (8 overlay + audio_missing + av_sync_drift) qua `QCItemRepository`; reseed idempotent (count 10→10, ids identical) — evidence/seed_counts.json cập nhật ✓
- Determinism ×2 + ffprobe asserts: giữ nguyên (test determinism vẫn xanh) ✓
- ruff `--select F` All checks passed; py_compile OK; JSON 7/7 valid ✓

**Diff scope vs WAVE_BASE `746b129a…`:** CHỈ 2 manifest + `docs/pm/sessions/S11-T06A1/**` (LOG/REPORT append + evidence/seed_counts.json). KHÔNG push/merge/rebase/reset/clean/stash.

Status: **TASK_SUBMITTED (correction)** — terminal `CORRECTION_C1_SUBMITTED`.
