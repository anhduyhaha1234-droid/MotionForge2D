# MATRIX — CMC correction 29/09 (12 hàng, trạng thái thật)

Run root: `C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z`
Cập nhật: 2026-09-29 17:10 +07. Mọi số liệu dưới đây là **đo thật** trong lượt này; ô nào chưa đo ghi `NOT_RUN`/`PENDING`, **không** suy diễn.

| # | Hạng mục | Owner | Actual (đo được) | Expected | Production call path | Test / artifact | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | CMC route, no fallback, usage/context controls | MANAGER `20260929_161633_4008ff` | `provider=custom`, `model=cmc/deepseek/deepseek-v4.1-flash` thật trong receipt log; `hermes fallback list` = No fallback providers; ledger v2 khớp 120/120 row cmc | exact model, fallback OFF, ledger có thật | `custom → http://127.0.0.1:20128/v1`, chat_completions | `manager/PREFLIGHT.md` §6, `ledgers/usage-ledger.v2.jsonl` (120 row cmc, 0 missing / 0 extra) | **PASS** |
| 2 | Source time map / cuts / events, không mất-lặp frame, audio map | MF-END-11 `20260928_121441_bdf0d8` (C11) | PENDING — worker đang chạy, đã patch `shot_reskin_plan.py` +229 dòng, `test_mf_end_11.py` +175 dòng (porcelain 2) | cut 121/241/343 + OCC 102 trong 1 time map có thẩm quyền; audio trim/pad riêng | `app/services/{shot_reskin_plan,scene_detection,source_locked_timeline}.py` | `tasks/MF-END-11/` (TARGET, FINDINGS, raw/, guard before/after) | **PENDING** |
| 3 | Artwork thật, cast/series pins, không fake poses | MF-DEMO-E2E-R5 `20260929_041810_bc7c61` (D0) | PENDING — D0 harvest + journey đang chạy | reference từ library/public ingest, pin cast, không 1 ảnh cho 6 pose | `app/api/routes/projects.py` upload/analyze + ImportAnalyzePanel | `tasks/MF-DEMO-E2E-R5/` | **PENDING** |
| 4 | Anchor đủ người/props/cảnh, đúng contact/camera; reject chặn video | MF-END-15 `20260928_153337_741b7e` | `NOT_RUN` — chưa dispatch (hết slot wave 0). Đã xác nhận: `app/api/routes/shot_anchors.py` **KHÔNG tồn tại**; `shot_anchor_jobs.py` có `submit_shot_anchor_job` nhưng **0 public caller** | anchor dùng được qua public API, reject/stale chặn video | `app/workflow/shot_anchor_jobs.py`, `app/services/shot_input_readiness.py` | worktree `C15` đã dựng sẵn @ `a52fca8` | **NOT_RUN** |
| 5 | BOOK mở sách; TURN giấy zoom; OCC ký giấy/cut; không đổi chủ thể/style | MF-DEMO-E2E-R5 (D0) | **Bằng chứng thật đã có**: R5 publication 640×360 video-only sha `075133f3…` **trùng tuyệt đối R4**; Codex đã xem frame: BOOK sách khép tới frame 90/119; TURN giấy→ông tóc bạc đọc sách; OCC tay/bút→phụ nữ đọc sách, mất cut 102 | giữ động tác + đổi toàn bộ appearance, đủ người | demo owner dùng đường app | `REVIEW/compare_{book,turn,occ}.jpg`, `RAW/.../R5_RENDER_ONLY_NOT_ACCEPTED.mp4` | **FAIL (chưa sửa)** |
| 6 | Per-unit bindings qua public app, hashes khớp | MF-END-19 `20260928_160603_9d1521` | `NOT_RUN` — cần proven unit bindings (blocked bởi #5) | đúng prompt/anchor/control/time map mỗi unit, cache đủ hash | `app/services/s10_full_apply*` | chưa dựng worktree | **NOT_RUN** |
| 7 | Observations từ output bytes, comparators được gọi | MF-END-22 `20260928_181430_0350c2` | `NOT_RUN` — chưa dispatch. Đã xác nhận trước dispatch: 5 comparator **chỉ có definition, 0 caller**; `app/services/qc_evidence/{compose,measure}.py` + `app/workflow/qc_checks_handler.py` có drift so với task HEAD cũ | 5 comparator chạy thật trên output bytes của đúng run | `app/services/qc_checks/orchestrator.py`, `app/workflow/qc_checks_handler.py` | worktree `C22` đã dựng sẵn @ `a52fca8` | **NOT_RUN** |
| 8 | Invalid/unknown/error non-ready; actual bad R5 bị chặn | MF-END-22 (C22) | **Một phần đo được ngay**: QC run R5 hiện có `RUN_QC_CHECKS completed ×2` trong DB, nhưng `qc_item` **0 row**; export vẫn **FAILED** (409 typed) | invalid/unknown ⇒ non-ready, không zero-issue pass | `app/workflow/qc_checks_handler.py:765,911` | DB `Temp/mfr5/data/motionforge.db` (read-only) | **PENDING (D0+C22)** |
| 9 | Browser journey từ import, không SQL/manual; context đúng | MF-END-25 `20260928_203715_8f1486` | `NOT_RUN` — cần API/engine contracts | import→cast→anchor→preview/apply→QC→retry→export/reopen | `frontend/src/components/ImportAnalyzePanel.tsx` | — | **NOT_RUN** |
| 10 | S12 export thật có audio gốc, codec preset, frame/PTS/duration, decode 0, restart/reopen | MF-DEMO-E2E-R5 (D0) | **Đo thật, đây là tiến bộ lớn nhất của lượt**: export submit **202** (run `7da2cb5f-2ea0-414a-a2db-8803ee8f0f59`, job `1e7c146f`), 3 chunk export render xong (`chunk_0000..0002.mp4` + .sha256), rồi **FAILED** ở bước validation: `PUBLICATIONERROR` — `export validation FAIL on ['av_policy']`, `class=permanent`, `retryable=false`. ATTACH_ORIGINAL_AUDIO **completed** (job `d33a1085`, 202→completed). `s12_export_run` **1 row** (trước lượt này: 0) | export completed + aac + 640×360×360f + decode rc0 | `app/services/s12_export/{validation,publication}.py` | `tasks/MF-DEMO-E2E-R5/raw/export_receipt.json`, DB `s12_export_run`, `artifacts/s12-exports/**/chunks/` | **FAIL (audio policy) — advance thật** |
| 11 | Hai video cùng cast qua batch render+export; restart/cache/cancel | MF-END-27 `20260928_210647_069401` | `NOT_RUN` — **chỉ mở sau khi có một video đạt** | 2 MP4 thật cùng PackVersion, không duplicate | `app/services/series_batch.py` | — | **NOT_RUN (blocked by #5/#10)** |
| 12 | Package ngoài checkout + original S12 release matrix | MF-END-28 `20260928_214702_f7c6aa` | `NOT_RUN` — cần frozen journey | staged outside checkout launch/render/export/reopen | `packaging/demo/**`, `scripts/mf_delivery_launcher.ps1` | — | **NOT_RUN** |

## Diễn giải

- **PASS**: 1 hàng ổn định (route/usage/context) — cần chốt lại ở cuối bằng ledger khớp.
- **FAIL có bằng chứng**: 2 hàng (#5 visual, #10 export audio policy). #10 là **tiến bộ thật**: trước lượt này `s12_export_run` = 0, giờ có 1 run thật đi qua submit→chunk→validation; nó chặn ở `av_policy` chứ không im lặng thành công.
- **PENDING (đang chạy)**: #2 (C11), #3 (D0).
- **NOT_RUN**: #4, #6, #7, #8, #9, #11, #12 — chờ dependency hoặc hết slot; **không đánh dấu SKIP**.
- Cap 3 stream (tính cả Manager): wave 0 = Manager + D0 (GPU) + C11 (CPU). C22 vào ngay khi một slot rảnh.

## Việc Manager chưa làm được / Disclosure

- Chưa có **browser thật** nào chạy journey → hàng #9 chỉ có code inspection, **không** gọi là đã chứng minh.
- **Vision chưa verified** trên route CMC: D0 phải tự ghi `UNREVIEWED` nếu không xem được ảnh; Manager cũng không tự tuyên bố đã xem frame.
- `888 tests` / `884 pass` **không** được dùng làm acceptance sản phẩm.
- Clean-host Windows NOT_RUN → **không** đóng S12.
- Không có cột nào ở đây được phép dùng để waive hàng còn mở.
