# Session Protocol

## 1. Context firewall

Mỗi `TASK.md` phải khai báo bốn vùng:

- `Required reading`: bắt buộc đọc đầy đủ.
- `Optional evidence`: chỉ đọc khi gặp câu hỏi cụ thể được nêu trong task.
- `Allowed write scope`: file/thư mục được phép sửa.
- `Forbidden scope`: không được sửa hoặc mở rộng.

Hermes không được tự duyệt toàn repo để tìm việc cần “cleanup”. Lệnh tìm kiếm có thể chạy trong repo khi cần định vị dependency trực tiếp, nhưng không tạo quyền sửa ngoài allowlist.

## 2. Một task phải đủ nhỏ

Task hợp lệ phải:

- tạo một outcome review được;
- có một owner/session;
- có acceptance criteria nhị phân;
- có test/evidence cụ thể;
- hoàn thành hợp lý trong một session;
- không phụ thuộc vào quyết định sản phẩm chưa được duyệt.

Nếu task vừa đổi schema, xây nhiều API, làm toàn bộ UI và migration phức tạp thì phải tách.

## 3. Quy tắc trước khi code

Hermes phải:

1. Đọc đúng required reading.
2. Kiểm tra `git status` và không ghi đè thay đổi có sẵn.
3. Ghi baseline commands/results vào `LOG.md`.
4. Tóm tắt plan ngắn trong chat.
5. Dừng và báo `BLOCKED` nếu requirement mâu thuẫn, migration có nguy cơ mất dữ liệu hoặc cần mở rộng write scope.

## 4. Quy tắc trong khi code

- Không sửa PRD, MP, roadmap hoặc task contract.
- Không đổi public contract ngoài phần task cho phép.
- Không xóa dữ liệu người dùng.
- Không “tiện thể” sửa lỗi lint/refactor ngoài scope.
- Mọi schema change phải có migration và backward/upgrade test.
- Business state bền vững không được chỉ nằm trong RAM, Zustand hoặc localStorage.
- Long-running operation không chạy đồng bộ trong request/UI.
- Frontend phải tuân thủ `frontend/AGENTS.md` và đọc tài liệu Next.js local liên quan trước khi code.
- Không che test fail bằng skip, ignore hoặc nới assertion nếu task không cho phép.

## 5. Deliverables bắt buộc

Trước khi submit, Hermes phải:

- chạy validation ghi trong task;
- chạy targeted tests cho thay đổi;
- cập nhật `REPORT.md` theo template;
- append các hành động/kết quả quan trọng vào `LOG.md`;
- ghi rõ test nào không chạy và lý do;
- liệt kê file thay đổi;
- để trạng thái `SUBMITTED`, không tự nhận `APPROVED`.

## 6. PM review

PM kiểm tra theo thứ tự:

1. Scope compliance.
2. Acceptance criteria.
3. Architecture/domain compatibility.
4. Data safety/migration.
5. Tests và evidence.
6. UX states nếu có UI.
7. Regression risk.

Nếu chưa đạt, PM không sửa lẫn vào task hiện tại. PM ghi `CHANGES_REQUESTED` với danh sách hữu hạn; Hermes tiếp tục đúng session hoặc PM tạo repair task riêng.

## 7. Session handoff

Task kế tiếp chỉ được dùng các output đã được PM approve. Dependency chưa approve được coi là chưa tồn tại. Mỗi `TASK.md` mới phải trỏ chính xác đến report/contract được phép kế thừa.
