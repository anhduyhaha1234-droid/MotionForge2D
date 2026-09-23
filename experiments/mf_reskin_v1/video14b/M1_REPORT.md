# M1_REPORT — MF-V1-VIDEO14B, wave B round M1 (closeout)

- Task ID: `MF-V1-VIDEO14B` — cùng task, cùng owner chain, **không tạo owner mới**.
- Model route: exact `ocg/deepseek-v4.1-flash`, provider `custom`, thinking ON, fallback OFF.
- **Round này KHÔNG có GPU**: không start engine, không nạp model, không submit. Clip đã tồn tại và đã được đo ở round M1 trước đó; round này chỉ commit + viết báo cáo + tạo review input + đo lại read-only (ffprobe/ffmpeg/sha256/pytest/ruff/git).
- Session: round M1 (GPU) chạy trong owner chain được Manager ghi ở ledger `actual_session = 20260923_174214_ce2c5d` (parent `20260923_165029_286f96`, chứng minh bằng `first-user-message == packet head`); **closeout này = `HERMES_SESSION_ID = 20260923_182342_5f2b84`** (đọc từ env của chính process). Bên trong lượt M1 worker không đọc được `state.db` nên **không tự khai** session id — dòng ledger của Manager là nguồn duy nhất cho mapping đó.
- Verdict: **`TASK_SUBMITTED`** cho phần việc của round closeout này. Không có `APPROVED` / `CLOSED` / `QUALITY_ACCEPTED` (xem §8).

---

## 0. KẾT QUẢ CƠ CHẾ (đầu báo cáo là cơ chế, không phải số test)

**Biến duy nhất của round M1:** `pose_end_percent` của node `672:587` (node `587` của subgraph
`"Motion Transfer (Wan Animate 2)"`, type `WanAnimate2ToVideo`, trong template official
`workflows/official/video_wan_animate2.json`):

| | pose_start_percent | pose_end_percent |
|---|---|---|
| baseline wave B đã nộp (`mf_animate2_book4s.waveB.api.json`) | 0 | **0** |
| **M1 đã nộp** (`mf_animate2_book4s.m1.api.json`) | 0 | **1** |
| template native (widget default đọc từ `/object_info` sống) | 0 | **1** |

**Cơ chế (đo được, không suy đoán).** Hai tham số này KHÔNG phải chỉ số frame: chúng là **cửa sổ
percent→sigma của nhánh pose conditioning**. Probe A2 (`VIDEO14B/raw/a2_motion_window.json`,
CPU-only, chạy trên **source runtime đã extract**, không engine, không mở weight) cho:

| case | pose window | số step denoise có pose | so với tổng |
|---|---|---|---|
| `submitted_0_0_structural_full_geometry` | `[0, 0]` | 1 | /6 |
| `native_0_1_structural_full_geometry` | `[0.0, 1.0]` | 6 | /6 |
| `submitted_0_0_payload_small_geometry` | `[0, 0]` | 1 | /6 |
| `native_0_1_payload_small_geometry` | `[0.0, 1.0]` | 6 | /6 |
| `submitted_0_0_structural_template_geometry_81` | `[0, 0]` | 1 | /6 |
| `window_0_0p7_structural` (kiểm tra biên) | `[0.0, 0.7]` | 5 | /6 |

Cơ học: với `[0,0]` cửa sổ co lại còn một điểm (`percent_to_sigma start = end = 1.0`, `cond_parts`
tách thành 2 phần và phần mang pose chỉ sống trong step 1); với `[0,1]` cửa sổ trùm toàn bộ
schedule (`start 1.0 → end 0.0`, `cond_parts` còn 1 phần) nên **cả 6/6 step mang pose**.
Probe A2 **đồng thuận độc lập** với probe của reviewer ở root khác
(`outputs/mf-technology-core-20260923/motion-window-probe.json`, sha `4df42e9d…`):
`pose_steps [1,1]` cho `[0,0]`, `[6,6]` cho `[0,1]`, `sigmas_equal: true`, `agrees: true`.

**Kết luận cơ chế.** Baseline đã nộp đi chạy với cửa sổ pose **lệch template native** (0/0 ⇒ 1/6 step);
M1 chạy **đúng cửa sổ của template native** (0/1 ⇒ 6/6 step). Đó là **toàn bộ** điều round này chứng minh
được. Baseline có bị sửa có chủ đích hay không là câu hỏi provenance **không** được round này trả lời.

**Tính đơn biến — đo lại độc lập trong round closeout này** (walk đệ quy baseline đã nộp vs graph M1):

```
nodes baseline=64 m1=64
structural_diff_count=1
  DIFF 672:587.inputs.pose_end_percent: 0 -> 1
```

Preflight của round M1: `PREFLIGHT_OK`, **7/7** check true (live `/object_info` khớp pin `d9e8e25a…`,
0 class thiếu, 5/5 model pin khớp, reference sha `1311699b…` khớp, pose window **LÀ** native, baseline
**KHÔNG** là native) — `raw/m1_preflight.json`.

---

## 1. Số đo của round M1 (nguồn: log server + record của adapter; không suy diễn)

| đại lượng | giá trị | nguồn |
|---|---|---|
| prompt id (duy nhất) | `adb0fd50-0676-4c95-9a87-19de9c6055c4` | `raw/m1_history.json` |
| `submit_calls` | **1** (không retry, không sweep seed, không cấu hình thứ hai) | `raw/run_m1/run_record.json` |
| cold load / model init | **25.82 s** (pass đầu, `Model Initializing → complete`) | `raw/server_log_excerpt_m1.log` |
| model stage | **15,878 MB staged / 1,059 patches / 202 weights 2,008 KB** (×2 trong log, mỗi pass một lần) | idem |
| sampler pass 1 | **6/6 = 1:11 @ 11.86 s/it** | idem |
| sampler pass 2 | **6/6 = 0:33 @ 5.52 s/it** | idem |
| server "Prompt executed" | **162.14 s** (Δ history `execution_start 1790161104812 → success 1790161266951` = **162.139 s**) | idem + `raw/m1_history.json` |
| client | wait **163.734 s**, total **164.656 s**, **wall 164.673 s** | `raw/run_m1/run_record.json` timing |
| peak VRAM | **11,622 MiB** (min 1,670; **81 sample**) | `raw/m1_resource_samples.json` |
| peak RAM | **50,109 / 65,325 MiB** | idem |
| engine epoch | `instance_id 7b4b7a8f2c6743ec806e31cfaa363d8b`, pid **36720**, port **8310**, ComfyUI **0.37.0** / commit `73c9bad4`, host `DESKTOP-B5TR9HD` | `raw/m1_preflight.json` |
| decode+export (CPU) | rc 0, **8/8** check true, encode loss `mae_max 0.0`, crop pure-translation true | `raw/export_m1/f06_export_record.json` |
| cost per **accepted** second | **KHÔNG XÁC ĐỊNH** (`generated 4.000000 s` / `accepted 0 s`) | — |

---

## 2. Câu hỏi "hai sampling pass" — trả lời bằng số đo, không phải lời khai

Manager từng hỏi vì sao một prompt lại có **2 pass**. Đo lại **cả hai** log server trong round này:

| log | `got prompt` | `Prompt executed` | dòng `Model WAN_Animate2 prepared … 15878MB` | thanh tiến trình 6 step |
|---|---|---|---|---|
| `logs/server_gpu_waveB.log` (wave B, 4 prompt) | 4 | **4** | **4** | 2 prompt × 2 pass |
| `logs/server_gpu_waveB_m1.log` (M1, 1 prompt) | 1 | **1** | **2** | 1 prompt × 2 pass |

Đọc thẳng log wave B theo từng prompt (line 87/107/148 = `got prompt`): **2 prompt Animate-2** có stage
line và 2 pass 6-step (`9.09 s/it` và `3.78 s/it`), còn **2 prompt 4-step** (anchor/reference) không
có stage line nào. Nghĩa là: tỉ lệ "4 prompt ↔ 4 stage line" mà owner báo trước đó là **đúng số nhưng
đúng do trùng hợp 2×2**, không phải vì mỗi prompt chỉ có 1 pass. Cấu trúc thật — và đây mới là điều
cần chốt — là:

> **mỗi prompt chạy subgraph Animate-2 đều sinh đúng 2 sampling pass (vòng lặp s1+s2 bình thường của
> template); M1 có 1 prompt nên có 2 pass, không thiếu và không thừa prompt nào.**

Bằng chứng khớp: `got prompt` = 1, `Prompt executed` = 1, **một** prompt id, **một**
`execution_success`, `submit_calls = 1`; ngoài 2 pass đó **không** có dòng stage hay `100%` nào khác.

---

## 3. Clip đã giao (đo lại trong round này bằng `ffprobe`/`sha256sum`, không copy số cũ)

| field | giá trị |
|---|---|
| path (thực tế trên đĩa) | `…/mf-core-tool-delivery-20260923/20260923T1535Z/NEW/VIDEO14B/waveB_m1/clip/final_book4s_m1_decoded119_640x360.mp4` |
| sha256 | **`5c2175ae73056ea6552b7b50432f618f7255a09f7cf9e5c695a870fe22286a6d`** |
| bytes | **1,071,337** |
| video | `h264`, **640×360**, `nb_frames 120` (presentation 0…119), `r_frame_rate 30/1`, `time_base 1/15360` |
| container | `duration 4.001995 s`, `size 1,071,337` |
| audio | `aac` LC, **44,100 Hz, 2 ch**, `nb_frames 216` |
| export contract | decoded 121 frame → chọn decoded index **0…119**, **bỏ index 120** (held pad); `select='between(n,0,119),setpts=N/30/TB,crop=640:360:0:4'`; identity pixel-map 0..119 true; crop là pure translation (121/121 frame, `max_abs_diff 0`, `mismatched_frames 0`) |
| audio window | 4 s đầu **bit-exact** với cửa sổ film `[55.000, 59.000)`: sha PCM `2387eded…`, **176,400 mẫu/kênh**, 0 mismatch; clip decoded **176,484 (+84)**; container Δ **+1.995 ms** |
| Δ còn lại của audio | hai đại lượng **khác nhau**, phải tách nhãn: container Δ 1.995 ms ≠ decoded Δ 84 mẫu = 1.904762 ms |

**Đo lại độc lập trong round closeout:** clip sha `5c2175ae…` ✓, bytes 1,071,337 ✓, 640×360 ✓,
120 frame ✓, tb 1/15360 ✓, container 4.001995 s ✓, aac 44100 2ch ✓; **phía clip** của audio: decode
4.000 s → 705,600 byte PCM = 176,400 mẫu/kênh, sha **`2387eded24366afefdcf16cea122f4cc85366d0be086652fea8ee4e041129292`** = khớp bản ghi.
(Phía film-window của claim bit-exact nằm ở `raw/audio_contract_m1.json`; Manager đã decode **cả hai** phía và
thu được đúng sha đó ở cả hai — round này tôi chỉ đo lại phía clip vì film là media của user.)

### 3.1 Sự thật về path: "nested NEW" — ghi rõ, KHÔNG di chuyển bytes

Packet mô tả clip nằm ở `NEW/NEW/VIDEO14B/waveB_m1/clip/…`. **Trên đĩa điều đó không tồn tại.**
Đo bằng `find` trên run root (`…/mf-core-tool-delivery-20260923/20260923T1535Z`): chỉ có **đúng một**
thư mục tên `NEW`, và cây bên trong nó là `NEW/VIDEO14B/waveB_m1/{clip,raw}`. Run root **cũng** có
`VIDEO14B/` ở mức 1 (chỉ chứa `fixtures/` + `raw/a1,a2,a3` của manager), nên nhìn từ run root thì có
hai chỗ mang tên `VIDEO14B`, còn `NEW/NEW/…` thì không có. Vị trí thật, chính xác:

```
…/20260923T1535Z/NEW/VIDEO14B/waveB_m1/clip/final_book4s_m1_decoded119_640x360.mp4
```

**Đã không sửa** bằng cách move bytes (bytes bị hash, move = phá tham chiếu). Toàn bộ record:
`raw/m1_clip_facts.json` (có cả hai cách viết path + ghi chú này).

---

## 4. Digest & canonicalisation — vì sao `97045d0f…` không tái lập được bằng JSON thường

Manager báo: canonical digest `97045d0f…` **không** tái lập từ "plain sorted-key JSON" (ra `d33bb57b…`).
**Cả hai số đều thật và đã được tái lập trong round này; chúng là hash của hai byte-string khác nhau.**
Canonicalisation thật của adapter:

* hàm: `mf_comfy.pinning.hash_workflow(graph)` = `sha256(canonical_json(graph).encode("utf-8"))`
* `mf_comfy.pinning.canonical_json(obj)` = `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
  (file read-only: `…/work/mfv1/wt-comfy/experiments/mf_reskin_v1/comfy/mf_comfy/pinning.py`)
* hash trên **object đã parse**, không phải text file; **không loại trừ field nào**, không thêm gì
* **khác biệt duy nhất** so với "plain sorted-key JSON": **`ensure_ascii=False`**. Mặc định của Python là
  `True`, tức escape mọi ký tự non-ASCII thành `\uXXXX`. Graph này có **133 ký tự non-ASCII** (negative
  prompt tiếng Trung: `色调艳丽，过曝，静态，…`), nên bản dump mặc định dài hơn và hash khác.

| đại lượng | giá trị (đo trong round này) |
|---|---|
| M1 graph — **raw file bytes** | `ff134923db899b3a9b84baf05fa2c51c8caeb6420075b1765af979400dc7c02f` (17,935 B, 1,114 CRLF) |
| M1 graph — LF-normalised | `1bb1d26cdb2cac0f503a6e4f444722700f7456f0a05c97886baed4e99c0d6537` (16,821 B) |
| M1 graph — **canonical, `ensure_ascii=False`** (= `workflow_sha256` của adapter) | **`97045d0f5adfb961ae907e3628a2a0a5974c12c15ac7705721eb593358ebb796`** |
| M1 graph — canonical với mặc định `ensure_ascii=True` | `d33bb57bdf7e7febfc2ad55f85f5725e2fff50e00efab04e67ce538bfbf88fd6` |
| baseline wave B — raw file bytes | `7ea87b66569cc629b02bc27f2e7db0d6d03a4700403bf317076f3ab5f8f4c6f8` (17,933 B) |
| baseline wave B — canonical | `f246221af10a27072481e6985c3683cf257269318e807c16e692261245cf3e5e` |

Tái lập (1 dòng):

```
python -c "import hashlib,json;g=json.load(open(r'…/workflows/run/mf_animate2_book4s.m1.api.json',encoding='utf-8'));print(hashlib.sha256(json.dumps(g,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest())"
```

**Hai bẫy nhãn phải nói rõ (đã sửa trong record, không sửa file cũ):**

1. `raw/m1_build_graph.json` ghi `m1.file_sha256 = 1bb1d26c…`, `bytes = 16821` — nhưng file trên đĩa là
   **17,935 B / `ff134923…`**. Cả hai đúng: field đó giữ digest **LF-normalised** (và byte count sau LF),
   còn `baseline.file_sha256` trong **cùng file** lại giữ digest **raw**. Một tên key, hai đại lượng khác
   nhau ở hai entry → dùng tên key đó để so sánh xuyên entry là **sai**.
2. `graph_sha256` / `workflow_sha256` trong run record = canonical digest ở bảng trên, **không** phải hash file.

---

## 5. Shutdown của engine (đã chứng minh ở round M1, giữ nguyên record)

`SHUTDOWN_PROVEN` 14/14 check true: chain dừng leaf→root `[36720] → [34152]`, `taskkill /PID <p> /F`
(**không** `/T`), mỗi pid khớp command line `serve_video14b.py`; trước dừng engine pids `[34152, 36720]`,
sau dừng `[]`; VRAM `3,704 → 1,525 MiB`; listeners 4 port dự phòng = `[]`; collateral được khai
nguyên văn (`[31896]`, một poll helper tự thoát). Bằng chứng: `raw/shutdown.json`,
`raw/shutdown/` (netstat, pid set trước/sau, VRAM, `SHUTDOWN.md`), `raw/state_*_shutdown.json`.
**Không dùng** `connect_ex 10035` làm bằng chứng (đó là `WSAEWOULDBLOCK` của non-blocking socket);
probe lại blocking cho **10061 (WSAECONNREFUSED)** cho 8310/8210/8199/8301/8302.

---

## 6. Test & lint tại HEAD (chạy lại trong round này)

```
python -m pytest experiments/mf_reskin_v1/video14b/tests -q   →  36 passed, 1 skipped in 3.13s   (rc 0)
ruff check --select F experiments/mf_reskin_v1/video14b/tools tests →  All checks passed!        (rc 0)
```

Khớp đúng con số Manager đo lại (36 passed / 1 skipped). Không có GPU, không engine trong cả hai lệnh.

---

## 7. Review input cho người (round này tạo) — đường duy nhất để F08 nhích

Không có vision trên route này, nên round tự nó **không** được phán chất lượng. Round này chỉ tạo thứ
để **người/Codex** xem, tại `NEW/VIDEO14B/waveB_m1/review/` (**36 file, 0 file 0 byte**):

| nhóm | file | bytes |
|---|---|---|
| contact sheet candidate, 20 frame/tấm (**6 tấm = đủ 120 frame**) | `contact_sheet_candidate_01…06_f000-119.png` | 119,345 – 163,488 |
| contact sheet side-by-side (source \| candidate) | `contact_sheet_side_by_side_01…06_f000-119.png` | 202,006 – 246,695 |
| side-by-side video (frame-locked cùng index) | `side_by_side_source_candidate_120f.mp4` | 218,869 |
| clip bản 1x / 0.5x | `review_1x_120f.mp4` / `review_0.5x_120f.mp4` | 1,071,337 / 40,123 |
| grip 2× cho **f68–f80** và **f119** | `grip_f068…f080_2xzoom.png`, `grip_f119_2xzoom.png` | 61,444 – 68,943 |
| strip 2× | `grip_strip_f068_f080_2xzoom.png` (307,268), `grip_strip_f119_2xzoom.png` (68,943) | |
| **source window clip copy** (compare like-for-like) | `source_window_120f.mp4` (63,301) | |
| source conditioning input đúng như run đã ăn | `source_conditioning_padded_121f_640x368.mp4` (216,572) | |
| record | `m1_review_bundle_record.json` (12,279), `review_bundle_manifest.json` (37,835), `review_bundle_dimensions_m1.json` (5,476) | |

Bảo vệ artifact: mỗi file được assert **tồn tại** và **`size > 0`** (một `select` không khớp frame nào
vẫn exit 0 và **không** ghi file — bị coi là FAIL, không phải thành công); thêm kiểm tra **cấu trúc**
(PNG IHDR / ffprobe): `review_bundle_dimensions_m1.json` → 35/35 non-zero, 0 file 0 byte,
0 ảnh degenerate (`0×0`/None), tổng 5,070,711 B (trước khi thêm chính file dimension record).
Tool (đã commit cùng round): `tools/m1_review_bundle.py` (render + copy + assert + record),
`tools/m1_review_dimensions.py` (đo cỡ/khung, ghi rõ `STRUCTURAL_ONLY__NOT_A_VISUAL_VERDICT`).

**Tuyên bố bắt buộc:** trong round M1 **và** trong round closeout này, **không một frame nào của clip
được mở/ xem/ kiểm tra bằng mắt** (không có tool vision trên route này và worker cố ý không tự mô tả
hình). In plain English: **no frame of the clip was visually inspected — not in the M1 round, not in
this closeout round**; the route has no vision tool and the worker deliberately does not describe the
picture. There is therefore no visual statement about the book, the hands, the background or identity.

Vì vậy: reference giữ **`NOT_VISUALLY_APPROVED`**, các row semantic (character/hands/book/
background/identity/blur-flicker) giữ **`NOT_REVIEWED`**, **0** `QUALITY_ACCEPTED`.
Round này **không** nói clip "đã sửa", "tốt hơn" hay "chấp nhận được" ở bất kỳ dòng nào — chỉ cơ chế + số.

---

## 8. Git

- Branch: `codex/mf-reskin-v1-video14b`. Parent bắt buộc `658e540017f4890e81ec9aab4b625764f80aca51` **nguyên vẹn**.
- Round này commit **local, scoped** (allowlist `experiments/mf_reskin_v1/video14b/**`, **không** `git add -A`),
  và **không push**.
- **Commit 1 (code, round này)** = `cf5e7a83e727b0fd42c483fdb226849f42ded477`, parent
  `658e540017f4890e81ec9aab4b625764f80aca51` (**nguyên vẹn**). 11 file, **+3,943 dòng**, tất cả
  trong `experiments/mf_reskin_v1/video14b/**` (0 file ngoài allowlist):

```
 tests/test_video14b_cpu_probes.py     |  278 ++++
 tools/m1_build_graph.py               |  211 ++++
 tools/m1_preflight.py                 |  232 ++++
 tools/m1_review_bundle.py             |  130 +++
 tools/m1_review_dimensions.py         |   76 ++
 tools/m1_shutdown_proof.py            |  155 +++
 tools/m1_state_capture.py             |  146 +++
 tools/v14b_a1_native_diff.py          |  427 ++++++++
 tools/v14b_a2_motion_window.py        |  495 +++++++++
 tools/v14b_a3_identity_trace.py       |  679 ++++++++++++
 workflows/run/mf_animate2_book4s.m1.api.json | 1114 ++++++++++++++++++++
 11 files changed, 3943 insertions(+)
```

- **Commit tài liệu (cùng lượt)**: file này + bản copy trong repo. Chain đo được: `HEAD^` = code commit
  `cf5e7a8…`, `HEAD^^` = `658e540…` (parent bắt buộc, **nguyên vẹn**). Hash HEAD cuối cùng của round
  được ghi bằng **số đo** trong `NEW/VIDEO14B/CLOSEOUT_STATE.json` → `git.head` (file này regenerate sau
  commit cuối) và trong reply của worker — không hứa trước, không tự bịa.
- `git status --porcelain` sau commit 1 = **rỗng**; `git branch -r --contains HEAD` = **rỗng** (không push).
- Sự cố đã khai: `git commit` in ra `fatal: bad object refs/codex/turn-diffs/…` +
  `error: failed to perform geometric repack` — đây là git maintenance (`gc --auto`) gặp broken ref
  **có sẵn từ trước**, không phải lỗi commit; commit vẫn landed và `rev-parse` xác nhận cả hai hash.

---

## 9. Còn mở (residual gaps) — lý do round này chỉ được `TASK_SUBMITTED`

| # | gap | trạng thái | cần gì để đóng |
|---|---|---|---|
| 1 | **F08 — phán chất lượng hình** (sách có mở, tay chỉ đúng?) | **NOT_REVIEWED / NOT_VISUALLY_APPROVED** | người hoặc Codex **có vision** mở `review/` (contact sheet 120 frame + side-by-side + grip f68–f80/f119). Worker **không được phép** kết luận. |
| 2 | `accepted_seconds = 0` | chưa xác định cost/accepted-second | một vòng review chấp nhận chất lượng; hiện chỉ có số học thuần 164.673/4.000 |
| 3 | provenance của baseline 0/0 | **không** kết luận | cần điều tra riêng vì sao bản nộp wave B lệch native; round M1 chỉ chứng minh nó lệch |
| 4 | nhãn `file_sha256` trong `raw/m1_build_graph.json` (raw vs LF) | đã ghi rõ trong `raw/m1_digest_canonicalisation.md`; **file cũ giữ nguyên** (không sửa record đã nộp) | reviewer đọc note khi so hash |
| 5 | path "nested NEW" | đã ghi rõ + **không** move bytes | reviewer dùng path thật ở §3.1 |
| 6 | A1/A2/A3 evidence ở root cũ | script đã landed vào worktree (commit cùng round); file evidence nằm ở `VIDEO14B/raw/a1,a2,a3` của Manager root, worker **không** ghi vào đó | nếu cần bản trong write-set thì copy ở round sau |
