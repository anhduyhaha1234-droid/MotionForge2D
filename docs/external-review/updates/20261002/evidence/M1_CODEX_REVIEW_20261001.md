# Codex independent review — MotionForge M1-01 — 2026-10-01

**Verdict: CHANGES_REQUESTED. M1-01 chưa được duyệt; M1, S12 và S13 chưa đóng. QUALITY_ACCEPTED=0.**

Hermes có tiến bộ thực: tạo identity nhân vật và phiên bản nháp qua UI/API thật, đọc lại sau reload. Nhưng lượt này **không tích hợp thêm công nghệ tạo ảnh/video, không tạo video demo mới**, và candidate chưa commit/transport vào INTEGRATION. Không thể gọi đây là sản phẩm hoàn chỉnh.

Phạm vi này do prompt Codex trước đó chỉ giao M1-01. Việc chưa chạy GPU/demo đúng phạm vi được cấp; không quy lỗi cho Hermes vì chưa thực hiện một task bị khóa. Điểm cần bác bỏ là các kết luận AC đã PASS và budget đã được kiểm soát.

## 1. Candidate và bằng chứng độc lập

- Submission: `C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z/manager/NEXT_CODEX_REVIEW.md`.
- Candidate: `C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01`, branch `codex/mf-end-10-m1-01-0930`, HEAD `a52fca897906fd61a088016dd802718fdf06d217`; 4 file implementation/test chưa commit.
- Manager `20260930_235002_3ac7f9`; implementation owner MF-END-10 `20260928_181955_a6d89a`.
- INTEGRATION vẫn clean tại cùng HEAD. Bốn SHA nguồn khớp submission và bản sao chạy review. `.last-run.json` có normalized blob bằng HEAD; không phải nội dung sản phẩm thay đổi.
- Đã xác minh **154/154 entries** trong evidence manifest khớp bytes/hash. Manifest nguyên vẹn không có nghĩa các kết luận trong tài liệu đúng.
- Chạy lại nguyên spec Hermes trên frontend snapshot và **SQLite mới**: **4 passed, 13.2s**. Sau đó chạy probe độc lập với API thật và chặn phản hồi sau server commit: tái hiện được bốn defect bên dưới.
- QA riêng `C:/Users/Admin/AppData/Local/Temp/mfm1-codex-review-20261001`, UI3071/API8071. Chỉ dừng PID do review tạo, đối chiếu executable/create-time; không sửa code/test gốc, user DB, Hermes, Comfy hay model.
- Retained Python22-pass và webpack build là kết quả Manager, chưa được Codex tái chạy lượt này. `npm run build` mặc định vẫn có failure do node_modules junction; webpack là phương pháp thay thế được công bố, không phải bằng chứng default build đã PASS.

Raw: [packet/hash verification](./PACKET_VERIFICATION.json), [E2E rerun](./runtime/submitted-spec-rerun.log), [independent probe](./runtime/adversarial.cjs), [actual probe results](./adversarial/result.json), [usage audit](./usage/USAGE_AUDIT.md).

## 2. Findings bắt buộc sửa

### F01 — P1 — Retry tạo draft trùng khi chưa biết kết quả lần trước

Source: `C:/Users/Admin/Documents/Codex/work/mf-delivery-20260930/M1-01/frontend/src/features/reference-library/CreateCharacterDialog.tsx:414` (handler guard:176).

UI chỉ disable khi busy; khi trạng thái `uncertain`, nút tạo gốc vẫn enabled. Probe thực hiện POST thật → server trả201/tạo v1 → abort response về browser → bấm nút gốc trước GET. Kết quả **2 POST, 0 GET trước retry, 2 draft tồn tại**. Điều này vi phạm AC2 và có thể tạo nhầm dữ liệu rồi chạy việc tiếp theo trên sai version.

Expected: cả handler lẫn UI chặn mutation khi uncertain/reconcile đang chờ hoặc thất bại. Chỉ cho retry khi đã đọc thành công và có kết luận không tồn tại kết quả cần nhận lại; không blind retry. Test phải mô phỏng **server commit rồi mất response**, đếm request và toàn bộ versions; đếm response bằng0 không chứng minh không có request.

### F02 — P2 — Tìm thấy draft đã tạo nhưng không nhận lại để hoàn tất

Source: `.../CreateCharacterDialog.tsx:196` và `:464`; parent `.../frontend/src/app/(app)/characters/page.tsx:590`.

Probe thứ hai: POST commit v1 rồi mất response; GET reconcile trả đúng một draft. UI chỉ liệt kê, gợi ý đóng hoặc tạo thêm, không nhận lại draft/gọi completion callback. Đóng xong: **success banner0, matching detail0, nhân vật mới chưa xuất hiện**, dù backend giữ đúng identity và v1.

Expected: dùng lại identity/draft đã tồn tại, cập nhật danh sách và chọn đúng ID; không thêm POST. Nếu nhiều kết quả không thể xác định, yêu cầu lựa chọn rõ ràng thay vì đoán.

### F03 — P2 — Banner in ID v2 nhưng detail chọn v1

Source: `.../frontend/src/app/(app)/characters/page.tsx:148`, `:596`, `:802`.

Callback giữ returned ID để in banner nhưng không truyền nó làm selection vào CharacterDetail. Detail dùng default/`versions[0]`. Probe F01 cho banner `version.id=534dc95f-2b96-46c7-b101-a042c3ad8630` (v2), trong khi **v1 aria-pressed=true, v2=false**. Đây là defect độc lập về selection, có thể xảy ra cả khi actor khác tạo draft trước UI.

Expected: selection dựa trên returned/reconciled version ID, với test nhiều phiên bản và assertion vào control/detail đang chọn thật. Test chỉ kiểm text ID không đủ.

### F04 — P2 — Keyboard focus thoát modal

Source: `.../CreateCharacterDialog.tsx:111`, `:218`; trigger return `.../characters/page.tsx:822`.

Từ input tên, Shift+Tab lần1 đến nút đóng; lần2 đến character card **phía sau modal**. Modal không giữ focus bên trong. Code cũng luôn trả focus về header CTA, kể cả khi mở bằng empty-state CTA (phần return-trigger này là code finding, chưa chạy probe riêng).

Expected: Tab/Shift+Tab nằm trong dialog; Escape/X/done trả focus đúng trigger. Giữ kiểm tra narrow390 và flow cũ.

### F05 — P1 — Không có hard request cap; báo cáo nguyên nhân dừng sai

Source: `C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260930/20260930T165243Z/manager/tools/dispatch_m1_01.py:10`, `:106`; `manager/NEXT_CODEX_REVIEW.md:110`, `:120`.

Dispatch chỉ có timeout7200s và max-turns160, đo requests sau khi chạy. Worker dừng vì output/tool arguments bị cắt, không phải budget-stop. Manager nói dưới20 nhưng exact-session log ghi **300+142=442 main loop/API counters**, thêm24 background counters. Giữ các loại counter tách nhau; không cộng thành một con số HTTP chính xác giả tạo.

Worker ghi nhận **114 calls có usage**, nhưng có thêm30 truncated/partial attempts bị Hermes bỏ qua trước bước accounting: **ít nhất144 attempts**, so với cap60. Ngân sách80 của cả task đã vượt; không tự reset bằng resume/run/session mới.

Expected: ghi sự thật và dùng enforcement trước request, tính cả retry/probe/auxiliary/resume. Không dùng max-turns hoặc tự đếm bằng lời thay request cap. Chưa có cơ chế đó thì chưa cấp chạy thêm bằng ngân sách cũ. Chi tiết, schema, log và runtime source trong [USAGE_AUDIT.md](./usage/USAGE_AUDIT.md).

### F06 — P2 — Acceptance/metadata/closure packet còn sai hoặc thiếu

- AC_MATRIX nói selected ID đúng và uncertain response được reconcile trước retry đều PASS; F01–F03 chứng minh kết luận đó không bao phủ hành vi thực.
- Pending test bấm lại sau201, chưa chứng minh đang pending không submit trùng. Fault injection abort trước commit, bỏ sót tình huống nguy hiểm hơn.
- Ba số byte trong bảng AC_MATRIX sai: page **37,380** (báo35,349); API **14,636** (báo15,029); dialog **22,218** (báo20,113). SHA vẫn khớp; backup manifest có số đúng. Đây là lỗi báo cáo, không có bằng chứng mất source.
- Worker chưa local commit, thiếu REPORT/AC_MATRIX/DIFF riêng; command ledger có5 row nhưng command rỗng. Manager có thể cung cấp evidence riêng và ghi rõ tác giả, không gán ngược thành evidence worker.
- Baseline spec4fail chỉ chứng minh thiếu CTA bị phát hiện; chưa chứng minh caller/selected-ID regression được bắt.

Expected: sửa matrix theo proof, dùng metadata sinh từ bytes, command log có command/exit/duration thật; local commit chỉ đúng bốn file sau correction đã pass. Không merge/transport trước Codex.

## 3. Công nghệ và sản phẩm hiện có

| Hạng mục | Trạng thái sau lượt này |
|---|---|
| UI kho trống → character → draft → reload | Happy path đã chạy thật, còn lỗi recovery/selection/accessibility |
| Kho nhân vật hoàn chỉnh, ảnh reference, published pack, series pin | Chưa được chứng minh qua toàn flow; draft mới vẫn thiếu6 ảnh legacy |
| AI coding route | Worker có usage trên `cmc/deepseek/deepseek-v4.1-flash`; có2 approval route calls ghi riêng. Đổi coding route không đồng nghĩa đổi video model |
| ComfyUI / Wan-Animate-2 | Đã có ở baseline trước; lượt này không đổi graph/model/adapter, không chạyGPU |
| MoCha / WanVideoWrapper / SCAIL-2 | Nằm trong kế hoạch reuse có điều kiện; **không có integration/proof mới trong submission** |
| SAM2 | Có adapter từ trước; lượt này chưa chứng minh mask/tracking được graph thực tiêu thụ |
| Video demo mới | **0 file video** trong run; report cũng ghi GPU/video/QC/export NOT_RUN |
| Video cũ | Review trước ghi render thật nhưng sai BOOK/TURN/OCC và export/audio gate còn vấn đề. Không xem/chấm lại file cũ trong lượt này; không đổi chất lượng thành PASS |
| Bản app tích hợp | INTEGRATION chưa nhận candidate; HEAD vẫn a52fca8 |
| S12/S13 / project goal | NOT_APPROVED / NOT_CLOSED; chưa có master đầu-cuối được nghiệm thu |

Nhận xét ảnh UI đã xem: form và trạng thái thành công rõ hơn, nhưng thẻ nhân vật còn là placeholder, sáu ảnh trống, publish bị chặn đúng. Banner đang dùng ID kỹ thuật để làm evidence; ảnh giao diện này không phải demo hình ảnh/video đạt goal.

## 4. Usage có thể kết luận

Worker phần có accounting: uncached input **655,810**, cache read **34,386,688**, inclusive prompt **35,042,498**, output **70,739**. Đây chưa gồm token của30 attempts thiếu accounting. Không gọi35triệu là toàn bộ uncached; cũng không quy đổi tiền khi chưa có billing.

Manager token total và exact HTTP total **unavailable**. DB ghi0 dù có log/messages thực là thiếu telemetry, không phải dùng0. Mức tiêu hao quá lớn so với một bước UI; không có cơ sở nói cơ chế tiết kiệm token đã cải thiện.

## 5. Hướng đi sau verdict

Giữ nguyên goal và roadmap đã chốt. Không nghiên cứu/cài model hàng loạt để né bốn lỗi UI. Chốt F01–F04 bằng cùng owner, cùng write-set, một matrix hữu hạn; đồng thời sửa F05/F06 trong evidence/dispatch control. Một correction được đề xuất, không vòng tự lặp. Cần ngân sách bổ sung do user cấp và cap thực trước khi chạy tiếp.

M1-02 manifest API → M1-03 ảnh/publish → M1-04 series pin vẫn chờ Codex đóng M1-01. Sau M1, ảnh cảnh Comfy đã duyệt và một unit video khó phải được chứng minh trước khi chạy hàng loạt; native graph trước, upstream alternatives chỉ khi có failure cụ thể, theo reuse matrix hiện hành. Không cấp mở những task này trong review.

Đã lưu [Session Opening Proposal](./SESSION_OPENING_PROPOSAL.md), [finite correction matrix](./CORRECTION_MATRIX.md), [complete next prompt](./NEXT_HERMES_MANAGER_PROMPT.md). Đây là đề xuất để **người dùng tự giao**; Codex không launch/resume/message Hermes hay tiếp tục theo dõi sau review.

Submission envelope giữ: `SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW — NOT_APPROVED / NOT_CLOSED`. Codex verdict gắn thêm: `CHANGES_REQUESTED / BLOCKED_BUDGET`; `QUALITY_ACCEPTED=0`. Không biến submission thành approved.
