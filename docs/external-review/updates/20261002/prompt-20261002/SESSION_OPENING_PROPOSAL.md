# Session Opening Proposal — 02/10/2026 shotwise prototype revision

Authority: user yêu cầu prompt để tách video thành cảnh/đoạn, thay diện mạo rồi ghép lại; kế thừa demo-first WAN và tự vision/correct tối đa10 phiên bản. Prompt hiện hành: NEXT_HERMES_DEMO_PROMPT.md cùng thư mục. Trạng thái AUTHORIZED_FOR_USER_HANDOFF; người dùng giao Manager, Codex không launch/message Hermes.

| Mục | Quyết định |
|---|---|
| Task | MF-DEMO-E2E-R5 / WAN-PROTOTYPE-01, cùng task với packet01/10 |
| Manager | Resume20260930_235002_3ac7f9; Manager mới do user giao phải ghi takeover/zero controller trùng |
| Worker | Resume exact20260929_041810_bc7c61; không mở owner/task mới mỗi shot/chunk |
| Route | custom cmc/deepseek/deepseek-v4.1-flash; chat_completions; fallbackOFF; reasoning chỉ setting route thực hỗ trợ; vision tool/provider actual cần probe |
| Context health | Kiểm lặp/sai scope/truncation theo rules; history dài đơn thuần không phải lý do transfer. Nếu thật sự hỏng, zero concurrent writer và handoff tối thiểu theo rules |
| Baseline | INTEGRATION a52fca897906fd61a088016dd802718fdf06d217, codex/mf-end-integration-0928, clean tại kiểm02/10; read-only |
| Write-set | RUN/manager của Manager; RUN/tasks/MF-DEMO-E2E-R5/WAN-PROTOTYPE-01 của Worker. RUN mới mf-delivery-runs/20261002/<UTC>-wan-shotwise nếu chưa dispatch, hoặc tiếp tục RUN cũ đúng prototype |
| Protected | MAIN/INTEGRATION/C19/C25/M1, global runtime/models/config, DB thật, evidence cũ; không Git mutation/production/tests |
| Wave/DAG | WIP1/GPU1. Preflight→source/shot/cast→ảnh cảnh→WAN chunks theo continuation dependency→QC/assembly→Manager verify→Codex cuối |
| Microsteps | Các bước trong cùng task có gate kỹ thuật tự kiểm; không thêm gate Codex mỗi render, không mở UI task trong lúc chờ GPU |
| Chunk policy | Giữ source/cuts/timeline/cast; tối đa8render chunks/candidate cho source12s, plan được version giữa candidates. Context handles trim rõ, dependencies invalidate nếu output trước đổi |
| Budget | Cùng trần10candidate/40video submissions/20image/40vision/worker300/Manager60;6h từ dispatch đầu,initial+3continuations. Nếu packet cũ đã chạy, dùng remaining budget/deadline cũ |
| Early stop | Full MP4/audio, mọi mandatoryPASS khôngUNKNOWN→SELF_REVIEW_PASS_PENDING_CODEX; nếu hết trần/blocker nộp best/partial và evidence |
| Deferred | Tool integration/UI/S12/S13/batch; giữ QUALITY_ACCEPTED0 và NOT_APPROVED/NOT_CLOSED |

Source/model tồn tại đã được đọc tại PROTOTYPE_PREFLIGHT.json; saved metadata không chứng minh live route/process activity. Model-label cũ ocg không được dùng thay actual CMC routing. Motion-enabled API graph/provenance ở thư viện mf-rebuild-skills-20261001; chỉ sửa tĩnh end0→1 đã review, chưa chứng minh generation thành công.
