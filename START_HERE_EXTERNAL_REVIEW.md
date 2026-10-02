# MotionForge2D — Hồ sơ bàn giao review kỹ thuật

**Cập nhật: 02/10/2026 · Nhánh đầy đủ mới: `review/20261002-full-code` · NOT_APPROVED / NOT_CLOSED · QUALITY_ACCEPTED = 0.**

Đọc [bản cập nhật hiện hành 02/10](docs/external-review/updates/20261002/README.md) trước. Code tích hợp ở root vẫn là candidate `a52fca897906fd61a088016dd802718fdf06d217`; thay đổi chưa commit đã được chụp lại từ100 worktree, gồm C19/C25/M1-01 và tài liệu quản lý mới. `review-snapshots-20261002/` là WIP để review, không được nhập hàng loạt vào app. Graph WAN sửa motion window được cung cấp riêng trong bản cập nhật; chưa chạy inference hoặc merge vào production.

Phần dưới ghi nhận bàn giao29/09 để truy nguồn. Số liệu cutoff, ưu tiên triển khai và visibility repo ở tài liệu cũ không được coi là trạng thái mới nhất; update02/10 ghi đè các điểm đó.

MotionForge2D là công cụ chạy local để chuyển diện mạo video có sẵn sang bộ nhân vật, đồ vật và bối cảnh mới. Người dùng chọn nhân vật từ kho riêng, dùng nhất quán xuyên suốt một series, đồng thời giữ hành động, tương tác, camera, nhịp cắt, timeline và âm thanh nguồn. ComfyUI điều phối xử lý từng scene/unit; model video là thành phần của pipeline.

Code đã có nền tảng ứng dụng, persistence/jobs, thư viện nhân vật, Comfy adapter, render, QC và export. Đã có render GPU thực. **Chưa có demo đầu cuối được nghiệm thu:** nội dung render sai hành động/chủ thể; một số component chưa nối vào hành trình app; export mới nhất còn lỗi validation audio.

## Đọc theo thứ tự

1. [Hồ sơ BA: mục tiêu, yêu cầu, kiến trúc, trạng thái và nghiệm thu](docs/external-review/PROJECT_BRIEF_VI.md).
2. [Danh sách vấn đề và hướng review theo nguyên nhân](docs/external-review/KNOWN_ISSUES.md).
3. [Hướng dẫn tiếp quản môi trường và các giới hạn cài đặt](docs/external-review/DEVELOPER_ONBOARDING.md).
4. [Bản đồ nhánh, code đang sửa dở và cách đối chiếu](docs/external-review/SOURCE_DELIVERY.md).
5. [Bằng chứng chất lượng và trạng thái các lần chạy](docs/external-review/evidence/README.md).

## Bản nào là code hiện tại?

| Lớp | Vị trí | Ý nghĩa |
|---|---|---|
| Candidate tích hợp | `app/`, `frontend/`, `tests/`, `scripts/`, `migrations/`, `packaging/` trên nhánh này | Giữ nguyên implementation từ `a52fca897906fd61a088016dd802718fdf06d217`; commit bàn giao thêm tài liệu và snapshot |
| Sửa C11 vừa hoàn tất | `review/20260929-c11-correction` | Commit `e3b130149c84b193736d14d00a26363bdb279dee`, chưa tích hợp hoặc được Codex chấp thuận |
| Dependency Comfy đã pin | `review/20260929-comfy-pin` | Exact commit cần cho `scripts/build_mf_comfy_dependency.py` |
| Nghiên cứu và nhánh lịch sử | Các ref `review/20260929-*` trong SOURCE_DELIVERY | Source bổ sung có provenance; không tự động coi là production |
| Thay đổi chưa commit và script chạy demo | `review-snapshots/` | Bản sao để đọc/diff, **không nằm trên import path của app và không phải bản đã merge** |

Phạm vi snapshot kết thúc **17:12:03 +07 ngày 29/09/2026**. Writer khác có thể tiếp tục sau mốc này; đây là bản bàn giao cố định, không phải đồng bộ trực tiếp. Manifest ghi hash từng file, commit nền và phần loại trừ. Mô hình AI, database người dùng, video nguồn đầy đủ, môi trường ảo và thông tin đăng nhập không được đóng gói.

## Mục tiêu của dev review

Xác nhận khoảng cách giữa yêu cầu sản phẩm và code; tái lập blocker; đề xuất sửa nhỏ theo luồng đầu cuối. Ưu tiên một video đúng qua app từ import đến export/reopen, rồi mới mở rộng batch và packaging. Test xanh hoặc số sprint đã submit không thay cho video đạt yêu cầu.

Tài liệu này là lối vào hiện hành cho lần bàn giao. README gốc và hồ sơ sprint cũ vẫn được giữ để truy nguồn; các tuyên bố PASS trong chúng cần đối chiếu với snapshot và bằng chứng mới hơn. Hồ sơ này không cấp quyền waive gate hoặc tự đóng sprint.
