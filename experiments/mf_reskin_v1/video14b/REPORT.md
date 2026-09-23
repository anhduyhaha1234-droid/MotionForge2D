# REPORT — MF-V1-VIDEO14B (task report trong write-set của worker, root `NEW/`)

File này là **báo cáo của task trong evidence root hiện hành** (`NEW/VIDEO14B/**`), viết ở round
closeout M1. Các báo cáo wave B gốc nằm ở root **read-only** của lượt trước
(`…/mf-reskin-correction-20260922/20260922T0955Z/VIDEO14B/{REPORT.md,WAVE_B_REPORT.md,WAVE_B_RUN_PLAN.md}`)
và **đã không bị sửa** (kiểm bằng sha256: `REPORT.md f5777b9b…`, `WAVE_B_RUN_PLAN.md fb7aa9b3…`,
đo trước và sau round này — xem §4).

- Task: `MF-V1-VIDEO14B` — BOOK 4 s. Model route: exact `ocg/deepseek-v4.1-flash` / `custom`, thinking ON,
  fallback OFF. 12 s / 28 s / 4K / UI / production integration vẫn **đóng**.
- Owner chain: wave B → round M1 (GPU) → round M1 closeout (CPU-only). Không tạo owner mới.

---

## 1. Round đã chạy

| round | nội dung | engine/GPU | kết quả |
|---|---|---|---|
| wave B (b2/b3/b4) | dựng + chạy + export clip BOOK 4 s, sửa test drift, commit `658e540` | có | `TASK_SUBMITTED` |
| **M1** | **single-variable: `pose_end_percent 0 → 1` tại node `672:587`**, 1 submit, 1 prompt | có (1 job) | `RUNNING` (thiếu report/commit/review input) |
| **M1 closeout** | viết `M1_REPORT.md`, hoàn tất `raw/`, xoá file rác, commit local, tạo bộ review input cho người, cập nhật tài liệu | **KHÔNG** | `TASK_SUBMITTED` |

## 2. Export contract của clip M1 (số phải khớp khi review)

| field | giá trị |
|---|---|
| clip | `NEW/VIDEO14B/waveB_m1/clip/final_book4s_m1_decoded119_640x360.mp4` |
| sha256 / bytes | `5c2175ae73056ea6552b7b50432f618f7255a09f7cf9e5c695a870fe22286a6d` / 1,071,337 |
| video | h264 640×360, 120 frame, `time_base 1/15360`, `r_frame_rate 30/1` |
| container / audio | duration 4.001995 s; aac LC 44,100 Hz 2 ch, `nb_frames 216` |
| frame selection | decoded 121 → chọn index 0…119, **bỏ index 120**; `crop=640:360:0:4` pure translation |
| audio | 4 s đầu **bit-exact** với film window `[55.000, 59.000)`: PCM sha `2387eded…`, 176,400 mẫu/kênh |
| graph đã nộp | `workflows/run/mf_animate2_book4s.m1.api.json` — canonical `97045d0f…`, raw file `ff134923…` (17,935 B) |
| graph baseline | `mf_animate2_book4s.waveB.api.json` — raw file `7ea87b66…` (17,933 B) |
| khác biệt | **đúng 1 field**: `672:587.inputs.pose_end_percent 0 → 1` |
| số đo round M1 | cold load 25.82 s; stage 15,878 MB / 1,059 patches; pass1 6/6 = 1:11 @ 11.86 s/it; pass2 6/6 = 0:33 @ 5.52 s/it; server 162.14 s; client wall 164.673 s; peak VRAM 11,622 MiB; peak RAM 50,109 MiB |

Chi tiết + bằng chứng cơ chế: `waveB_m1/M1_REPORT.md`.

## 3. Review input đã giao cho người

`NEW/VIDEO14B/waveB_m1/review/` — **36 file, 0 file 0 byte**, tổng 5,076,187 B:

- `contact_sheet_candidate_01…06_f000-119.png` — **đủ 120 frame**, 20 frame/tấm
- `contact_sheet_side_by_side_01…06_f000-119.png` + `side_by_side_source_candidate_120f.mp4` (source | candidate, frame-locked)
- `grip_f068…f080_2xzoom.png`, `grip_f119_2xzoom.png`, `grip_strip_f068_f080_2xzoom.png`, `grip_strip_f119_2xzoom.png`
- `review_1x_120f.mp4`, `review_0.5x_120f.mp4`
- `source_window_120f.mp4` + `source_conditioning_padded_121f_640x368.mp4` (so like-for-like)
- record: `m1_review_bundle_record.json`, `review_bundle_manifest.json`, `review_bundle_dimensions_m1.json`

Sinh bằng `tools/m1_review_bundle.py` (delegate render cho `waveB_review_bundle.py` đã verify) +
`tools/m1_review_dimensions.py`; mọi file assert `exists && size > 0`.

## 4. Việc còn mở

1. **F08**: chất lượng hình **chưa ai xem** — `NOT_VISUALLY_APPROVED` / semantic `NOT_REVIEWED` / **0** `QUALITY_ACCEPTED`.
   Cần người/Codex có vision mở bộ review ở §3.
2. `accepted_seconds = 0` ⇒ cost per accepted second **chưa xác định**.
3. Provenance của baseline `0/0` (vì sao bản nộp wave B lệch native) — **chưa** điều tra, không kết luận.
4. Nhãn `file_sha256` trong `waveB_m1/raw/m1_build_graph.json` (raw vs LF-normalised) — đã ghi note, file cũ giữ nguyên.
5. Path clip: packet ghi `NEW/NEW/…`, thực tế `NEW/VIDEO14B/waveB_m1/clip/…` (một `NEW`). Bytes **không** bị move.
6. A1/A2/A3 evidence nằm ở root của Manager (`VIDEO14B/raw/a1,a2,a3`); script đã landed trong worktree ở round này.

## 5. Git (điền sau khi commit, cùng lượt)

- Branch `codex/mf-reskin-v1-video14b`; parent **bắt buộc** `658e540017f4890e81ec9aab4b625764f80aca51` — kiểm nguyên vẹn.
- Commit scoped (allowlist `experiments/mf_reskin_v1/video14b/**`, **không** `git add -A`), **không** push.
- Commit 1 (code, round này) = `cf5e7a83e727b0fd42c483fdb226849f42ded477`, parent
  `658e540017f4890e81ec9aab4b625764f80aca51` (**nguyên vẹn**), 11 file / +3,943 dòng, toàn bộ trong
  `experiments/mf_reskin_v1/video14b/**`, 0 file ngoài allowlist.
- Commit 2 (tài liệu) = commit chứa file này + bản copy `M1_REPORT.md` trong repo; hash đo bằng
  `git rev-parse HEAD` ngay sau khi commit và báo trong reply của worker (không hứa trước).
- Sau commit: `git status --porcelain` rỗng, `git branch -r --contains HEAD` rỗng (**không** push).
- `git commit` in `fatal: bad object refs/codex/turn-diffs/…` + `error: failed to perform geometric repack`:
  broken ref **có sẵn**, thuộc git maintenance; commit vẫn landed (đã xác nhận bằng `rev-parse`).
- Kiểm tra "không đụng root read-only": sha256 của `…/mf-reskin-correction-20260922/…/VIDEO14B/REPORT.md`
  và `WAVE_B_RUN_PLAN.md` đo trước round (`f5777b9b…`, `fb7aa9b3…`) và đo lại sau round — phải y hệt.
