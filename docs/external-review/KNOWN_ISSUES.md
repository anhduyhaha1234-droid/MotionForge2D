# Vấn đề đang mở — bản đồ review cho developer

Mốc candidate: `a52fca897906fd61a088016dd802718fdf06d217`. Phân biệt ba mức bằng chứng: **đã kiểm chứng độc lập**, **quan sát code**, **Manager báo cáo, cần tái lập**. Severity P1 dưới đây là blocker đối với demo đúng hợp đồng; không phải xếp hạng bảo mật.

## P1-01 · Graph và binding mỗi cảnh chưa giữ được nội dung nguồn

**Đã kiểm chứng độc lập:** R5 FullApply render thực 3 chunk nhưng publication trùng SHA-256 với R4. Cảnh TURN (giấy chứng nhận + zoom camera) thành người đọc sách; OCC (tay/bút ký giấy + cut) thành phụ nữ đọc sách; BOOK không thực hiện mở sách. Xem [bằng chứng](evidence/README.md).

**Nguyên nhân ở harness đã thấy:** `demo_run5.py` gán cùng prompt BOOK cho mọi shot, `require_accepted_anchor=False`, chia cố định 3 × 120 frame. Tìm file trong [manifest](CODE_SNAPSHOT_MANIFEST.json); bản sao script nằm trong `review-snapshots/run-tools-*`. Khả năng model chưa giữ đủ motion còn cần benchmark đúng control; không thể quy toàn bộ lỗi cho Wan khi binding đầu vào sai.

**Review/sửa ở:** [shot_reskin_executor](../../app/services/shot_reskin_executor.py), [FullApply](../../app/workflow/s10_full_apply_jobs.py), [backend manifest](../../app/schemas/s10_full_apply.py), adapter và graph manifests. Chứng minh unit → source facts → cast pins → anchor → prompt/control → output bằng hash/receipt. Giữ video lỗi làm negative control.

**Đóng khi:** BOOK mở sách đúng thời điểm; TURN giữ giấy và zoom; OCC giữ ký giấy và cut; toàn bộ cast/props/background được reskin đúng. Không được thay câu chuyện, bỏ chủ thể ở mép hình hoặc dùng ảnh đứng để né chuyển động.

## P1-02 · Evidence hình ảnh của demo chưa phải quan sát output thật

**Đã kiểm chứng từ code:** harness dựng mask hình chữ nhật trước render, dùng một ảnh cho sáu pose slots, có prop được seed như character. Những dữ liệu này kiểm plumbing được nhưng không xác nhận segmentation/identity/occlusion thật.

**Review/sửa ở:** [rendered_observations](../../app/services/rendered_observations.py), `app/services/qc_evidence/`, ingestion references và type binding. Mỗi observation cần lineage tới bytes của output đúng run/frame, detector/profile và source fact để đối chiếu.

**Đóng khi:** actual failed R5 bị phát hiện qua output observation; thiếu detector/measurement báo unknown hoặc error và chặn acceptance; không dùng placeholder để làm QC xanh.

## P1-03 · Comparators có code nhưng chưa đủ production wiring

**Quan sát code:** năm entry point `compare_contact_facts`, `compare_occlusion_facts`, `compare_motion_facts`, `compare_identity_facts`, `compare_static_and_flicker` mới có definition; review candidate chưa thấy caller trong production flow. `tests/product_delivery/test_mf_end_22.py` pass không chứng minh production đã gọi.

**Rủi ro cần tái lập:** probe identity có `invalid`, `THRESHOLD_INVALID`, measured distance 109.048669 nhưng `items=0`. Chưa được suy diễn thành đã chứng minh false-ready live. Báo cáo Manager 17:10 ghi hai QC jobs completed với zero qc_item và export vẫn failed: zero issues cũng không tự chứng minh video đúng.

**Review/sửa ở:** [orchestrator](../../app/services/qc_checks/orchestrator.py), [QC handler](../../app/workflow/qc_checks_handler.py), evidence compose/measure. Test negative phải qua production orchestration và readiness, không chỉ unit comparator.

**Đóng khi:** 5 loại so sánh chạy trên đúng output; invalid/unknown/error/thiếu phép đo đều non-ready; actual R5 sai nội dung bị chặn rõ nguyên nhân.

## P1-04 · Anchor và user journey chưa hoàn chỉnh qua public app

**Quan sát code:** upload/analyze công khai đã có trong [projects routes](../../app/api/routes/projects.py) và [ImportAnalyzePanel](../../frontend/src/components/ImportAnalyzePanel.tsx). Demo R5 lại seed trực tiếp DB. Không kết luận “chưa có import” rồi xây lại module trùng.

[shot_anchor_jobs](../../app/workflow/shot_anchor_jobs.py) có handler/submit nhưng chưa tìm được public API caller; UI build anchors còn thiếu. So sánh kết quả cần project context đúng. `require_accepted_anchor=False` không thể là đường nghiệm thu.

**Đóng khi:** browser thật thực hiện import → chọn cast → tạo/duyệt anchor → preview/apply → QC → retry shot lỗi → export/reopen, không SQL seed hoặc sửa DB thủ công. Reject/stale anchor phải chặn render.

## P1-05 · Time map nguồn và manifest lệch nhau

**Đã đo độc lập:** source_12s có cut ở frame 121/241/343, manifest lại chia 120/240 và thiếu cut nội bộ OCC. BOOK mở sách là event trong shot, không phải lý do tạo hard cut giả. Đủ 360 frame không chứng minh đúng từng frame.

**Code mới chưa tích hợp:** C11 `e3b130149c84b193736d14d00a26363bdb279dee` thêm 229 dòng vào shot_reskin_plan và 175 dòng tests; mục tiêu là source-authoritative map, verifier và audio timebase. Đã lưu ref riêng. Chưa review correctness hoặc chạy lại tests C11 trong lần bàn giao này.

**Review/sửa ở:** [shot_reskin_plan](../../app/services/shot_reskin_plan.py), [source_locked_timeline](../../app/services/source_locked_timeline.py), normalization/assembly và audio map.

**Đóng khi:** map đo từ source bytes; không mất/lặp frame ở cut; event/contact/occlusion dùng cùng timebase; audio trim/pad được khai báo và kiểm chứng riêng.

## P1-06 · S12 export đã tiến tới validation, vẫn chưa xuất thành công

**Snapshot độc lập buổi sáng:** R5 mới có render, chưa có S12 export run. **Delta Manager báo cáo 17:10:** ATTACH_ORIGINAL_AUDIO completed; export submit 202, run `7da2cb5f-2ea0-414a-a2db-8803ee8f0f59`, ba export chunk xong nhưng fail `PUBLICATIONERROR`, `export validation FAIL on ['av_policy']`, permanent/non-retryable. Xem [matrix có timestamp](evidence/MANAGER_MATRIX_1710.md). Đây là tiến bộ thực trong luồng theo báo cáo, chưa được tái lập độc lập ở lần bàn giao.

**Review/sửa ở:** [audio handler](../../app/workflow/original_audio_handler.py), [audio remux](../../app/services/original_audio_remux.py), [export handler](../../app/workflow/s12_export_jobs.py), `app/services/s12_export/validation.py` và `publication.py`. Phân biệt audio attach input, audio trong export chunk, audio publication và policy validator; đừng sửa threshold chỉ để pass. Kiểm provenance/timestamps trước khi tái dùng render cache.

**Đóng khi:** S12 run completed, final MP4 có audio nguồn, đúng codec/preset/frame/PTS/duration, ffmpeg decode rc=0, restart/reopen và phát được từ app. File publication hoặc tên `demo_final.mp4` không đủ chứng minh S12.

## P1-07 · Batch và package chưa đạt mục tiêu sử dụng

**Quan sát code/report:** [series_batch](../../app/services/series_batch.py) hiện phục vụ batch export; panel chưa mount, chưa chứng minh batch render. Package staged ngoài checkout trên dev host; clean Windows/human acceptance NOT_RUN.

**Đóng khi:** sau khi một video đạt, chạy ít nhất hai video cùng immutable cast qua render + export; restart/cancel/retry không duplicate hoặc lẫn artifact. Sau đó kiểm package ngoài checkout và máy Windows sạch theo release matrix S12 gốc.

## P2-08 · Onboarding phụ thuộc máy tác giả

Default source repo của builder `mf_comfy` và model root là đường dẫn máy tác giả. Pin source đã được đưa lên ref riêng; wheel build stdlib đã xác minh 11 file. Engine còn yêu cầu live boot epoch; chưa có launcher `serve_comfy` hoàn chỉnh trong code app/scripts. `scripts/setup.sh` cu124 lệch pyproject cu128; build-backend và dependency multipart cần kiểm clean install. Chi tiết và lệnh đề xuất ở [onboarding](DEVELOPER_ONBOARDING.md).

**Đóng khi:** developer mới clone, cài dependency đã pin, cấu hình models, khởi động engine với identity thật, chạy vertical slice theo tài liệu mà không mượn môi trường máy tác giả.

## P2-09 · Chi phí orchestration và độ tin cậy báo cáo

Audit 44 phiên ghi nhận Manager dùng 60.073.794 uncached input token, 62,28% tổng; 86 request cache <10% tiêu 53.395.387 uncached. Đây là token log, không phải hóa đơn. Retry tiếp sau quota và context dài làm mất hiệu quả. Matrix mới báo route CMC và ledger đã có; chưa có audit độc lập chứng minh tiết kiệm.

Đề nghị review control: task ngắn có owner rõ, checkpoint compact, local monitoring theo thay đổi, dừng retry khi hard quota, không fallback OCG. Việc code review của developer này không cần chạy Hermes hoặc cấp API key để đọc source.

## Thứ tự review có hiệu quả

1. Cố định môi trường và tái lập failed artifact để làm baseline.
2. Review C11/time map, per-unit binding, anchor và observations/QC trên một vài unit đại diện.
3. Nối user journey thực; xử lý audio/export validation bằng receipt + decoded media.
4. Nghiệm thu một video theo hợp đồng; sau đó mới batch và clean-host package.

Không cần viết lại toàn bộ dự án trước khi đối chiếu code đang có. Mỗi finding mới nên ghi: commit, đường gọi, expected/actual, phép tái lập, mức chắc chắn, tác động người dùng và điều kiện đóng.
