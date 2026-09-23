# WAVE_B_RUN_PLAN — MF-V1-VIDEO14B (bản của write-set hiện hành, cập nhật ở round M1 closeout)

Kế hoạch wave B gốc ở root read-only của lượt trước
(`…/mf-reskin-correction-20260922/20260922T0955Z/VIDEO14B/WAVE_B_RUN_PLAN.md`, sha `fb7aa9b3…`)
**không bị sửa**. File này là bản trong write-set hiện hành (`NEW/VIDEO14B/**`) và ghi lại **trạng thái
thực thi** của wave B + round M1 tính đến round closeout này.

---

## 0. Luật bất biến (giữ nguyên, không nới)

1. Một heavy GPU job tại một thời điểm; gate `gpu_stage.lock` + `InstanceLease` là cơ chế thực thi.
2. Một model một lúc.
3. Không tự viết pose extractor / rig / renderer — chỉ model có sẵn + preprocessor official.
4. Không đổi cấu hình giữa đường; cấm hand-mixed set (LoRA/step không có trong template official).
5. `allowed_types` chỉ **thu hẹp** (`("output",)`); `RunSpec.terminal_outputs` phải khai báo.
6. **Không có `QUALITY_ACCEPTED`** khi không có vision xem.
7. Không `git add -A`, không push/merge; commit local chỉ trong `experiments/mf_reskin_v1/video14b/**`.

## 1. Trình tự đã thực thi

| bước | kế hoạch | trạng thái thực tế |
|---|---|---|
| B1 | re-check **live** `/object_info` trước mọi submit | **XONG** — pin `d9e8e25a…` khớp, 0 class thiếu (wave B và M1 đều kiểm) |
| B2 | anchor/reference pick + presubmit gate | **XONG** (wave B, raw ở root lượt trước) |
| B3 | render BOOK 4 s + export contract F06 | **XONG** — clip wave B `55daef67…` (b1-b4); commit `658e540` |
| B-review | bộ review input cho người (contact sheet, side-by-side, grip 2×) | **XONG** (wave B) |
| **M1** | **single-variable motion diagnosis: `pose_end_percent 0 → 1`**, 1 prompt, 1 submit, không sweep | **XONG (GPU)** — clip M1 `5c2175ae…`; mechanism xem `waveB_m1/M1_REPORT.md` §0 |
| **M1 closeout** | closeout CPU-only: report + `raw/` + xoá rác + commit local + bộ review input M1 + tài liệu | **XONG (round này)** |
| tiếp theo | F08 = review bằng mắt (người/Codex có vision) | **MỞ** — worker không được tự kết luận |

## 2. Ngân sách GPU đã dùng (để không chạy lại trùng)

| round | submit | prompt id | thời gian server | ghi chú |
|---|---|---|---|---|
| wave B (b2/b3) | 4 prompt (2 Animate-2 + 2 prompt 4-step anchor/reference) | raw ở root lượt trước | 150.04 s + 135.09 s (2 prompt Animate-2) | clip wave B `55daef67…` |
| **M1** | **1** | `adb0fd50-0676-4c95-9a87-19de9c6055c4` | **162.14 s** | clip M1 `5c2175ae…`; engine epoch `7b4b7a8f…`, pid 36720, port 8310, ComfyUI 0.37.0 |

Round M1 closeout: **0 submit, 0 engine start, 0 model load** (CPU-only: ffprobe/ffmpeg/sha256/pytest/ruff/git).

## 3. Open items chuyển cho người

1. **F08**: xem bộ review `waveB_m1/review/` (36 file) — quyết định chất lượng do người/Codex.
2. `cost per accepted second`: chưa xác định (`accepted_seconds = 0`).
3. Provenance baseline `0/0` — chưa điều tra.
4. Nếu Manager muốn evidence A1/A2/A3 nằm trong write-set của worker: copy ở round sau (hiện ở root của Manager).
