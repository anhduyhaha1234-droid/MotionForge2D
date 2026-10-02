# Quyết định: video mẫu WAN trước, tool vận hành sau

Ngày 01/10/2026. Đây là hướng triển khai và packet cho người dùng giao Hermes; Codex chưa chạy Hermes, ComfyUI hoặc inference mới. User đã xác nhận giữ sát động tác/camera/timeline và chỉ thay diện mạo, chỉ định WAN, yêu cầu mẫu thành công trước tích hợp tool, cho phép Hermes tự xem vision và sửa tối đa10 sản phẩm.

**Chọn hướng transcript hình ảnh có cấu trúc + ảnh cảnh đích mới + WAN nhận driving video nguồn qua ComfyUI.** Dựng lại toàn bộ diện mạo không đòi phải bỏ tín hiệu chuyển động nguồn. Thay đổi thực dụng nhất ở lượt này là tách kiểm chứng media khỏi UI/API đang lỗi, dùng graph sẵn có để ra video mẫu, rồi chỉ tích hợp workflow đã có bằng chứng.

**Cập nhật sau audit graph:** phát hiện pose window0→0 trong graph WAN/P6 và lỗi nối start sang end trong template UI installed. Đã chuẩn bị API copy sửa end→1, chưa inference. Đây là correction phải áp dụng trước C01; các số tốc độ/VRAM P6 cũ không đại diện full-pose. Chi tiết `MOTION_WINDOW_FINDING.md`, cách reuse `REUSE_EXECUTION_MATRIX.md`, graph và hashes trong `reuse_bundle/PROVENANCE.json`. Static fix đã được review độc lập; chất lượng sản phẩm vẫn chưa được nghiệm thu.

## So sánh đúng ba phương án

| Tiêu chí | MotionForge hiện có | Transcript chữ/ảnh → WAN sinh tự do | Phương án mẫu được chọn |
|---|---|---|---|
| Đầu vào | Có shot/cast schema, source spans, ảnh anchor, graph WAN; binding/integration còn lỗi | Câu chuyện, prompt, ảnh nhân vật/storyboard | Visual transcript + frame map + cast thật + ảnh cảnh đích + driving clip |
| Model tạo video | Đã có Wan-Animate-2 trong nhánh Comfy, cùng các renderer lịch sử | WAN T2V/I2V | WAN Animate 2 đã cài, qua ComfyUI |
| Pixel output | Graph WAN đã sinh clip mới; không chỉ thay layer cũ | Sinh mới | Sinh mới |
| Bám động tác/camera | Có cơ sở từ source conditioning nhưng kết quả chưa được nghiệm thu | Text/storyboard không giữ được toàn bộ quỹ đạo giữa keyframes; phải sinh lại/chọn nhiều hơn nếu yêu cầu sát nguồn | Có driving nguồn; vẫn phải đánh giá thực, không bảo đảm100% |
| Khởi tạo demo | Đang bị kéo theo library/API/QC/export/UI corrections | Dễ viết demo từ một prompt | Có thể chạy ngay với runtime/graph hiện có, không chờ app |
| Phân tích nguồn | Nhiều thành phần sẵn nhưng chưa nối đầy đủ | Nhẹ nếu chỉ giữ nội dung; mất dữ liệu chuyển động | Transcript semantic theo shot; chỉ thêm control graph thực dùng |
| Kho nhân vật | Có version/persistence, UI thiếu parts | Vẫn cần bộ nhân vật ổn định | Manifest cast thật trong RUN cho mẫu; đưa vào library sau |
| Retry | Chưa được khoanh nguyên nhân tốt, từng nhầm đầu vào các shot | Retry thường để sửa diễn biến/chuyển động thiếu control | Vision phân loại lỗi, sửa ảnh/binding/recipe liên quan, tái dùng unit không đổi |
| Chi phí vận hành | Chưa có giây video chất lượng được chấp nhận để tính throughput | Không có đo trên cùng tiêu chí; ít input chưa chắc ít retry | Có ledger10versions và đo thời gian/accepted second sau review |
| Phù hợp yêu cầu user đã xác nhận | Đúng định hướng, implementation chưa đủ | Không đủ nếu bỏ driving và vẫn đòi motion/camera/timing sát | Phù hợp nhất để kiểm chứng nhanh trong phạm vi hiện tại |

Kết luận “dễ hơn” ở đây là **dễ hoàn thành phép thử và tìm nguyên nhân hơn vì chưa phụ thuộc tool**, không phải đã chứng minh diffusion giữ đúng mọi cảnh. WAN vẫn được dùng. Không đổi sang VACE hoặc dịch vụ video khác trong packet.

Comfy/Wan-Animate-2 hướng dẫn nhận driving video trực tiếp, không cần mặc định pose/skeleton preprocessing. Đây là lý do có thể giảm chuỗi bước phân tích bắt buộc cho route hiện có. [Comfy chính thức](https://docs.comfy.org/tutorials/video/wan/wan-animate-2), [Wan upstream](https://github.com/Wan-Video/Wan-Animate-2).

## Transcript cần mang những gì

Speech transcript ghi lời nói; visual transcript ghi ai/vật gì xuất hiện, hành động, sự kiện/contact, trạng thái trước/sau, camera và khoảng frame. Whisper phục vụ lớp lời nói, không tự cho dữ liệu hình ảnh. [Whisper](https://github.com/openai/whisper).

JSON là kế hoạch và bằng chứng: source hash, shot spans/timebase, role IDs, target cast refs, keyframes và events. Dữ liệu vận động chi tiết vẫn do driving clip cung cấp. Không biến một câu “nhặt cuốn sách” thành giả định đã biết mọi chuyển động ngón tay.

Ảnh scene đích phải chứa đủ cast/props/background đúng bố cục, rồi đưa một ảnh đó vào node video hiện có. Node đang pin lấy `reference_image[:1]`; một batch nhiều ảnh không có nghĩa nhiều nhân vật được thay độc lập. Dùng FLUX.2 Klein graph hiện có cho ảnh cảnh là reuse, không thêm image engine mới. [Hướng dẫn Klein](https://docs.comfy.org/tutorials/flux/flux-2-klein).

## Vì sao thứ tự mới hợp lý

Các lỗi create/reconcile/version của M1 và public anchor/export là lỗi tool thật. Nhưng chúng không cần được sửa trước khi thử cùng graph ảnh/video trong môi trường riêng. User hiện cho phép tách hai quyết định:

1. **Công nghệ có tạo được video mẫu đúng ý không?** Chứng minh bằng source/transcript/cast/ảnh/WAN/output/QC thật.
2. **Tool có vận hành workflow đó được không?** Chỉ làm sau khi bước1 đạt; sửa các API/caller/queue/UI/export cần để chạy lại đúng recipe.

Vì thế không cần xóa code, đổi schema hoặc mở dự án Video DOM mới. Giữ kho/jobs/adapter/UI hữu ích để tái dùng sau. Media prototype có harness riêng được user cấp, nhưng không được biến thành service sản phẩm thứ hai hoặc giả app đã hoàn tất.

Rules §0.2 và current overlay handoff/roadmap đã được cập nhật, có backup trước patch. M1 và các corrections giữ nguyên bytes và trạng thái; thứ tự M1-first cũ không chặn prototype này. Không tuyên bố đã đóng sprint.

## Clip mẫu và giới hạn thử

Source12s cũ tại `C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260929/cmc-correction-20260929T091814Z/tasks/MF-DEMO-E2E-R5/raw/source_12s.mp4` có SHA `fc18e859599f8feeb730ee9018413ced4c183f90a15e20ccc162433c4666c8cc`. FFprobe đọc lại: video12,000s,360frames,30/1fps,640×360; audio48kHz stereo, duration12,001667s; container12,002667s. Chênh vài ms này là số đo container/stream, không tự kết luận audio sync đúng hoặc sai. `SOURCE_FFPROBE.json` lưu raw output.

- Một candidate là phiên bản của toàn clip nguồn, cùng cast/map/criteria; tối đa10slots tính cả partial/fail. Không gọi mỗi shot là một sản phẩm hoàn chỉnh.
- Mỗi candidate tối đa một WAN submission mới/unit, tối đa4units và40video submissions. Mỗi GPU retry tiêu slot tiếp theo; no seed sweep/best-of-N/batch ẩn. Tái dùng phần không đổi có hash.
- Tối đa20image submissions cho cast/anchors/corrections; tối đa40vision requests. Source/anchor cần được vision xem thật, không chấm bằng tên model.
- Thời hạn6giờ và operating budgets300worker/60Manager là **trần**, không phải ETA, không yêu cầu phải sử dụng hết. Không thể hứa số lần nào sẽ đạt trước khi chạy.
- Dừng ngay full candidate đủ tiêu chí, trạng thái SELF_REVIEW_PASS_PENDING_CODEX; hết trần thì nộp best-so-far và lỗi cụ thể. Không auto chuyển sang tool.

Mẫu12s tốt chưa chứng minh mọi loại nguồn, batch hoặc S12 clean-host. Review Codex sau lượt này quyết định khả năng dùng recipe và scope tích hợp tiếp theo.

## Vision giúp gì và giới hạn

User cho phép Hermes tự kiểm ảnh/clip, tìm sai role/action/contact/camera và chọn biện pháp sửa. Điều đó giảm thời gian chờ review thủ công giữa mỗi lần. Vision vẫn có thể bỏ sót lỗi, đặc biệt nếu chỉ xem keyframes. Phải ghi media thật đã xem, timestamp, confidence và UNKNOWN; bổ sung dense frames quanh sự kiện cùng kiểm frame/timebase/audio. Metadata hoặc lời tự đánh giá của worker không thay hình ảnh đầu vào.

Codex review độc lập cuối vẫn cần xem video/các thời điểm quan trọng. QUALITY_ACCEPTED giữ0 trước verdict; Hermes không tự gán approval của người dùng/Codex.

## Skills đã cập nhật và cách áp dụng

Đã cài13skills/155files mới từ CE, Planning with Files, ECC, wshobson và beltonk; giữ10Spec Kit cũ. 445file cũ không bị đổi. Superpowers bị admin disable nên không cài; BMAD/gstack chỉ lưu source vì còn runtime/setup; VoltAgent là role prompts, không phải SKILL.md. [Báo cáo cài đặt](SKILLS_INSTALL_REPORT.md) có trạng thái từng repo và hash.

Đã áp dụng nguyên tắc `search-first`: kiểm code, runtime và official graph trước tự viết; chọn reuse Animate2/Klein/FFmpeg và adapter mỏng. Áp dụng `cost-aware-llm-pipeline` ở ledger/cache/retry hữu hạn; không dùng giá/model routing ví dụ của skill thay route CMC user đã chọn, không bịa hard limiter. Những framework lập kế hoạch đầy đủ không phải prerequisite cho demo.

Hermes đọc skills qua đường dẫn local trong report khi được user giao prompt. Không cài vào `.hermes`, bật hooks hoặc chạy Hermes từ Codex. Skills mới có thể được Codex nhận diện từ lượt tiếp theo.

## Tài liệu giao thực hiện

- [Prompt đầy đủ](NEXT_HERMES_DEMO_PROMPT.md)
- [Session Opening Proposal](SESSION_OPENING_PROPOSAL.md)
- [Review kiến trúc độc lập](INDEPENDENT_ARCHITECTURE.md)
- [Review vòng thử nghiệm](DEMO_LOOP_REVIEW.md)

Trạng thái project: `SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW — NOT_APPROVED / NOT_CLOSED`, `QUALITY_ACCEPTED=0`. Không có video mới trong lượt soạn packet; video là đầu ra bắt buộc của lượt Hermes được user giao tiếp theo.
