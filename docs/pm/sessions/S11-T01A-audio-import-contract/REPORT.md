# S11-T01A — REPORT

**Task:** S11-T01A — Audio Import Policy and Contract
**Owning session:** 20260821_160614_6958a5 (alpha @ custom, Hermes CLI)
**Worktree:** C:\Users\Admin\MotionForge2D-worktrees\s08-integration — branch codex/s08-integration @ a43b20d
**Status:** **SUBMITTED** — chờ Manager verify / Codex review. KHÔNG tự ghi APPROVED.
**Date:** 2026-08-21 (+07)

---

## 1. Deliverables (đúng Exclusive write ownership)

| File | Loại | Nội dung |
|---|---|---|
| `app/services/video_import.py` | MODIFIED (scope: non-AAC acceptance/warning) | `probe_source` không còn raise `UNSUPPORTED_AUDIO_CODEC`; non-AAC first audio → warning entry với severity=warning, location, reason, VN action, details {audio_codec, audio_stream_index, channels, sample_rate}. Container/video-codec/HDR/metadata gates giữ nguyên fail-closed. |
| `tests/test_video_import.py` | MODIFIED (scope: S11 non-AAC regressions) | Bỏ đúng 1 parametrize case MP3-reject khỏi `test_unsupported_media_fails_closed` + import tương ứng. Không test nào khác bị sửa. |
| `tests/test_s11_original_audio_contract.py` | NEW | 10 required tests binary của TASK.md (test_required_1..10; test 3 parametrize libmp3lame+ac3 → 11 items). |
| `docs/architecture/ORIGINAL_AUDIO_REMUX_CONTRACT.md` | NEW | Contract remux cho T01B đọc: canonical first-audio selection, accept matrix, stream-copy/transcode policy, scope boundaries. |
| `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` | APPEND-ONLY | §9-R Resolution R-B5 appended ở EOF. §1–§10 nguyên vẹn 100% (không dòng cũ nào sửa/xóa). |
| `output/s11-t01a/run-20260821T1812/pytest-required-tests.log` | Evidence | Full verbose log của final run 40 passed. |

## 2. Policy triển khai

- First audio stream = canonical (ffprobe streams order); multi-stream không merge.
- AAC first audio: accepted, zero audio warning.
- Non-AAC first audio (MP3/AC-3/…): **accepted WITH explicit warning** `UNSUPPORTED_AUDIO_CODEC` — không reject chỉ vì audio codec. T01B ATTACH_ORIGINAL_AUDIO chịu transcode AAC.
- No-audio: accepted với `NO_AUDIO_STREAM` warning (explicit no-audio metadata, không fabricated audio).
- Video codec/container/HDR policy KHÔNG nới: `UNSUPPORTED_CODEC`, `UNSUPPORTED_CONTAINER`, `HDR_UNSUPPORTED`, `INVALID_VIDEO_METADATA` vẫn fail-closed.
- Import không transcode/không mutate source bytes (artifact byte-identical source — verified bằng sha256 trong test_required_10).

## 3. Required tests (binary) — mapping & kết quả

| # | Required test | Test function | Kết quả |
|---|---|---|---|
| 1 | AAC remains accepted | `test_required_1_aac_first_audio_remains_accepted` | PASSED |
| 2 | No-audio remains accepted | `test_required_2_no_audio_remains_accepted_with_warning` | PASSED |
| 3 | Non-AAC first audio → accepted w/ explicit warning | `test_required_3_non_aac_first_audio_accepted_with_explicit_warning[libmp3lame]` + `[ac3]` | PASSED ×2 |
| 4 | Unsupported video codec vẫn reject | `test_required_4_unsupported_video_codec_still_rejected` | PASSED |
| 5 | Unsupported container vẫn reject | `test_required_5_unsupported_container_still_rejected` | PASSED |
| 6 | HDR/10-bit policy unchanged | `test_required_6_hdr_10bit_policy_unchanged` | PASSED |
| 7 | First audio stream remains canonical | `test_required_7_first_audio_stream_remains_canonical` | PASSED |
| 8 | Multi-stream input không merge | `test_required_8_multi_stream_input_not_merged` | PASSED |
| 9 | Probe/checkpoint retains codec/index/channels/sample rate | `test_required_9_checkpoint_retains_audio_metadata` | PASSED |
| 10 | Import không transcode/không mutate source bytes | `test_required_10_import_does_not_transcode_or_mutate_source` | PASSED |

## 4. Evidence (lệnh thật + output thật)

### 4.1 Worktree guard (trước mọi write)
```
$ pwd
/c/Users/Admin/MotionForge2D-worktrees/s08-integration
$ git rev-parse --show-toplevel
C:/Users/Admin/MotionForge2D-worktrees/s08-integration
$ echo "MOTIONFORGE_DATABASE_URL=[${MOTIONFORGE_DATABASE_URL:-UNSET}]"
MOTIONFORGE_DATABASE_URL=[UNSET]
```

### 4.2 Baseline TRƯỚC thay đổi (chứng minh check có thật)
```
$ python -m pytest tests/test_video_import.py -q -p no:cacheprovider \
    --basetemp="C:/Users/Admin/AppData/Local/Temp/s11t01a-baseline"
30 passed, 54 warnings in 24.77s
```
Baseline sha256 khớp LOG entry Manager 16:05+07:
video_import.py=e3723fd2…, test_video_import.py=a8b2d5bd…, VIDEO_PREFLIGHT_CONTRACT.md=db27fbbe…

### 4.3 Sau thay đổi — required tests + S05 regression
```
$ python -m pytest tests/test_video_import.py tests/test_s11_original_audio_contract.py \
    -v -p no:cacheprovider --basetemp="C:/Users/Admin/AppData/Local/Temp/s11t01a-final"
...
tests/test_s11_original_audio_contract.py::test_required_10_import_does_not_transcode_or_mutate_source PASSED [100%]
====================== 40 passed, 74 warnings in 32.28s =======================
```
Full log: `output/s11-t01a/run-20260821T1812/pytest-required-tests.log`
(29 S05 tests + 11 S11 tests = 40; case MP3-reject cũ đã chuyển thành accept-with-warning theo policy mới.)

### 4.4 Full suite regression check
```
$ python -m pytest tests/ -q -p no:cacheprovider \
    --basetemp="C:/Users/Admin/AppData/Local/Temp/s11t01a-suite3" \
    --ignore=tests/test_integration.py
15 failed, 1431 passed, 19 skipped, 2276 warnings in 1033.47s (0:17:13)
```
15 failures TOÀN BỘ pre-existing, thuộc S07 project_cast domain + 1 durable-persistence table assertion — không liên quan audio import:
- `ProjectCastConflictError: compatibility blocked: incomplete_pack,missing_required_pose` (app/persistence/project_cast.py:358)
- `AssertionError: unexpected tables: ['project_cast_mapping']` (tests/test_durable_job_persistence.py:411)
- grep `video_import|probe_source|submit_import` trong 3 file test fail = **0 matches**.
Tail output lưu tại `output/s11-t01a/full-suite-tail.txt`. (`tests/test_integration.py` bỏ theo quy ước SAM2 segfault.)

## 5. Post-change hashes (sha256)

| File | Hash |
|---|---|
| app/services/video_import.py | 87b548e8bcf8f612f04918c1833b2519452858b755d72aad859edb43c455c94a (sau R5-P2; trước R5-P2/R2: 90c7d3f5…/ccb9e8e2…) |
| tests/test_video_import.py | 590ff88126deb562bd2bc10210a6ced47c3aa5b6b6940f4230d93370a9e5d4f1 |
| docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md | 32287504862af7a17f5113ccaa180c8cf5bad1850af081bdc63e223bcbcac024 |
| docs/architecture/ORIGINAL_AUDIO_REMUX_CONTRACT.md | 552f11ab10cf3c97ec20c57ad3f5c9817db2f55f03934fe095cb7a101ad1466f |
| tests/test_s11_original_audio_contract.py | 5b27eea74c9ceaf3808ee191cc0bdb9d9b0bbfba8a2606e99fa7801547513acc (sau R5-P2; trước R5-P2/correction #1: f48bda72…/7f133d36…) |

## 6. Compliance checklist

- [x] Hard worktree guard PASS trước mọi write (pwd + toplevel khớp).
- [x] MOTIONFORGE_DATABASE_URL UNSET toàn phiên; tests dùng temp DB (alembic upgrade per-test) + `--basetemp` Windows-native riêng + `-p no:cacheprovider`.
- [x] FFmpeg discovery chỉ qua app/services/ffmpeg_utils (find_ffprobe); fixtures qua `shutil.which("ffmpeg")`.
- [x] Chỉ ghi file trong Exclusive write ownership; không đụng original_audio_remux.py / job_service.py / models.py / migrations / API/frontend / file S07 / packet T01B-C-D.
- [x] Không git reset/clean/stash/restore/checkout-file/commit/push/merge; không sửa MAIN repo; không production DB/data/motionforge.db; không git global config.
- [x] Append-only B5 resolution — §1–§10 VIDEO_PREFLIGHT_CONTRACT.md nguyên vẹn.
- [x] TASK.md Owning session ID đã điền.
- [x] LOG.md có evidence lệnh + output thật từng bước.
- [x] Status = SUBMITTED, KHÔNG tự ghi APPROVED.

## 7. Ghi chú cho reviewer

1. `pcm_alaw` fixture: ffmpeg build hiện tại từ chối encode pcm_alaw vào MP4 (verify trực tiếp: "Nothing was written into output file"). Required test 3 dùng `libmp3lame` + `ac3` — cả hai đều là non-AAC thực và encode được; policy code path giống hệt cho mọi codec khác.
2. Warning `UNSUPPORTED_AUDIO_CODEC` giữ nguyên text VN action cũ (contract §7 demote severity blocker→warning nhưng không đổi action text).
3. File `tests/test_s11_original_audio_remux.py` trong tree là packet T01B (session song song) — không thuộc quyền ghi của task này, không đụng.

## 8. Corrections (post-submission, theo Manager verification)

### R1 — F401 unused import (2026-08-21T18:32+07)

- **Phát hiện của Manager:** `python -m ruff check` → `F401 'app.services.video_import.JOB_TYPE_ANALYZE_MEDIA imported but unused'` tại tests/test_s11_original_audio_contract.py:54.
- **Xác minh độc lập:** chạy lại ruff — lỗi tái hiện đúng 1 error. Test file KHÔNG assert `job_type` ở đâu (chức năng đó đã có trong test S05 `test_success_import_publishes_ready_source_artifact`) → chọn sửa hẹp phương án **bỏ import thừa**, không thêm assert mới.
- **Sửa:** xóa đúng 1 dòng import; không file nào khác bị đụng.
- **Verify (1) ruff:**
  ```
  $ env -u MOTIONFORGE_DATABASE_URL python -m ruff check app/services/video_import.py \
      tests/test_video_import.py tests/test_s11_original_audio_contract.py
  All checks passed!
  RUFF_EXIT=0
  ```
- **Verify (2) pytest:**
  ```
  $ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_video_import.py \
      tests/test_s11_original_audio_contract.py -q -p no:cacheprovider \
      --basetemp="C:/Users/Admin/AppData/Local/Temp/s11t01a-correction"
  40 passed, 74 warnings in 32.44s
  ```
  Log: `output/s11-t01a/run-20260821T1812/pytest-after-correction.log`
- **Hash sau correction:** test_s11_original_audio_contract.py = f48bda720ba5293c6f85c7b009d1ac4fec648aef9eb59018d14fdf473cdb106b

Status vẫn **SUBMITTED** — chờ Manager verify lại sau correction.

### R2 — mypy assignment type error (2026-08-21T19:10+07)

- **Phát hiện của Manager:** `python -m mypy app/services/video_import.py` → `video_import.py:576: error: Incompatible types in assignment (expression has type "None", variable has type "dict[str, object]") [assignment]`.
- **Xác minh độc lập:** chạy lại mypy — lỗi tái hiện đúng 1 error (MYPY_EXIT=1). Nguyên nhân: sau S11-T01A, lần gán đầu của `audio_payload` nằm trong nhánh `if audio is not None:` nên mypy suy luận kiểu `dict[str, object]`; nhánh `if audio is None: audio_payload = None` phía dưới gán None → conflict.
- **Sửa hẹp TẠI ĐÓ:** thêm đúng 1 dòng annotation tường minh trước nhánh if đầu:
  `audio_payload: dict[str, Any] | None = None`
  (đúng pattern gốc S05 đã từng dùng cho biến này; không refactor gì khác; chỉ đụng app/services/video_import.py).
- **Verify (1) mypy:**
  ```
  $ python -m mypy app/services/video_import.py
  Success: no issues found in 1 source file
  MYPY_EXIT=0
  ```
- **Verify (2) ruff:**
  ```
  $ env -u MOTIONFORGE_DATABASE_URL python -m ruff check app/services/video_import.py \
      tests/test_video_import.py tests/test_s11_original_audio_contract.py
  All checks passed!
  RUFF_EXIT=0
  ```
- **Verify (3) pytest:**
  ```
  $ env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_video_import.py \
      tests/test_s11_original_audio_contract.py -q -p no:cacheprovider \
      --basetemp="C:/Users/Admin/AppData/Local/Temp/s11t01a-corr2"
  40 passed, 74 warnings in 32.71s
  ```
  Log: `output/s11-t01a/run-20260821T1812/pytest-after-correction2.log`
- **Hash sau correction #2:** app/services/video_import.py = 90c7d3f57d9dcab9fea5c049727f2110c2e68bb43aef17266d369f25a5e2946d

Status vẫn **SUBMITTED** — chờ Manager verify lại sau correction #2.

### R5-P2 — warning/action text mâu thuẫn (Codex CHANGES_REQUESTED round 5, 2026-08-22T18:44+07)

- **Finding (Manager đã xác minh):** `video_import.py:516-528` chấp nhận non-AAC import-with-warning với reason đúng ('accepted with warning per ORIGINAL_AUDIO_REMUX_CONTRACT (S11 B5) — ATTACH_ORIGINAL_AUDIO will transcode to AAC'), NHƯNG `VIETNAMESE_ACTIONS[CODE_UNSUPPORTED_AUDIO_CODEC]` tại :199-201 vẫn là 'Codec âm thanh chưa được hỗ trợ (chỉ hỗ trợ AAC). Hãy chuyển đổi âm thanh sang AAC rồi thử lại.' — action bảo user convert-manual + retry trong khi policy là auto-accept + transcode-later → user hiểu sai policy.
- **Cause:** text action kế thừa từ V1 preflight (fail-closed era) không được cập nhật khi B5 demote blocker→warning.
- **Fix (chỉ text, zero policy/code-path change):**
  - `VIETNAMESE_ACTIONS[CODE_UNSUPPORTED_AUDIO_CODEC]` mới: *"Âm thanh không phải AAC nhưng vẫn được import kèm cảnh báo; khi chạy ATTACH_ORIGINAL_AUDIO hệ thống sẽ tự transcode sang AAC — bạn không cần chuyển đổi thủ công."*
  - Tighten `test_required_3`: assert reason chứa 'accepted with warning' + 'transcode to AAC'; assert action chứa 'vẫn được import' + 'transcode sang AAC' và KHÔNG chứa 'thử lại'.
  - `tests/test_video_import.py` KHÔNG sửa — grep xác nhận không test nào pin chuỗi cũ; scene_detector/video_proxy spread toàn dict nên text mới lan truyền tự động.
- **Gates (evidence output/s11-t01a/run-20260822T1848-r5p2/):**

| Gate | Lệnh | Output thật |
|---|---|---|
| a | `env -u MOTIONFORGE_DATABASE_URL python -m pytest tests/test_video_import.py -q -p no:cacheprovider --basetemp="C:/Users/Admin/AppData/Local/Temp/s11t01a-r5p2a"` | `29 passed, 52 warnings in 23.81s` |
| b | `… pytest tests/test_s11_original_audio_contract.py … --basetemp="C:/Users/Admin/AppData/Local/Temp/s11t01a-r5p2b"` | `11 passed, 22 warnings in 14.01s` |
| c | `… ruff check app/services/video_import.py tests/test_video_import.py tests/test_s11_original_audio_contract.py` | `All checks passed!` exit 0 |
| d | `python -m mypy app/services/video_import.py` | `Success: no issues found in 1 source file` exit 0 |
| e | `git diff --check` | exit 0 (clean) |

- **Hashes sau R5-P2:** video_import.py=87b548e8…, test_s11_original_audio_contract.py=5b27eea7…, test_video_import.py=590ff881… (không đổi — đúng vì không pin chuỗi).

Status: **TASK_SUBMITTED** — chờ Manager/Codex re-review. KHÔNG tự ghi APPROVED.
