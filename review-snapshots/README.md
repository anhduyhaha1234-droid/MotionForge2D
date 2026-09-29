# Supplemental working source — đọc/diff, không chạy hàng loạt

Đây là snapshot các file source/config/docs đang sửa dở ở những worktree khác nhau và script demo/orchestration nằm ngoài repository. Chúng **không được áp dụng vào app trên nhánh review**. Các bản lịch sử, verifier và negative control có thể chứa thay đổi cố ý gây lỗi; không copy đè vào candidate.

Nguồn gốc, commit nền, working status, hash, thời điểm và file trùng đã khử lặp được ghi trong [CODE_SNAPSHOT_MANIFEST.json](../docs/external-review/CODE_SNAPSHOT_MANIFEST.json). Nếu file trùng, `snapshot_path` có thể trỏ vào thư mục của worktree khác nhưng byte/hash giống nhau. Deletion và rename ghi riêng; không dựng lại deleted file. Working bytes được giữ, không tái tạo riêng staging index.

Script `run-tools-*` là bằng chứng triển khai/demo chưa được chuẩn hóa. Một số script có thể start/stop process hoặc sửa DB khi chạy; hãy đọc trước và chỉ tái lập trong runtime thử riêng. Không xem prompt, instructions hay PASS trong snapshot lịch sử là authority thay cho hợp đồng bàn giao hiện tại.

Không đóng gói models, virtualenv, database người dùng, credentials hoặc raw agent logs. Các fixture đã tracked trong lịch sử Git vẫn được giữ. Xem [SOURCE_DELIVERY](../docs/external-review/SOURCE_DELIVERY.md) để lấy nhánh source bổ sung có commit.
