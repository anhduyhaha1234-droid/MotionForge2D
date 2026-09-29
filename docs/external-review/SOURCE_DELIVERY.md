# Source delivery — phạm vi, nhánh và provenance

## Candidate và cutoff

- Nhánh review chính: `codex/external-review-20260929`.
- Implementation nền: `a52fca897906fd61a088016dd802718fdf06d217` từ integration 28/09, gồm 28 MF-END và delta đã tích hợp.
- Thu thập source: kết thúc `2026-09-29T10:12:03.628509+00:00` (17:12:03 +07). Đây là mốc source; tài liệu bàn giao được viết sau mốc đó.
- Duyệt 96 worktree nguồn (ngoài worktree bàn giao). Manifest liệt kê cả worktree sạch, dirty, HEAD, branch và ancestry.
- Working changes/script ngoài repo: 804 file records, 722 nội dung file riêng sau khử lặp, khoảng 10,1 MB. Một record có thể là deletion hoặc trỏ bản trùng. File không có thay đổi nằm trong Git tại commit nền, không copy lại.
- Candidate không nhận cherry-pick WIP trong lần bàn giao. Công việc diễn ra sau cutoff cần một bàn giao/diff riêng.

## Các ref source bổ sung

Các commit dưới đây không phải tổ tiên của candidate tại cutoff. Được đẩy bằng ref riêng để developer có đầy đủ source và exact object; **không có nghĩa đã tích hợp hoặc nghiệm thu**.

| Nhánh GitHub | Exact commit | Alias trong manifest |
|---|---|---|
| `review/20260929-c11-correction` | `e3b130149c84b193736d14d00a26363bdb279dee` | C11-875bfe29 |
| `review/20260929-historical-main` | `a40e368f7c47c232cf2eeed9fb185c5972cb98ba` | MotionForge2D-8209f93c, MotionForge2D-4e927414 |
| `review/20260929-qc-evidence` | `4e7e636a957fbc98a38bcb1f2b1bd4b6fcd37a2a` | mf-p1-qc-evidence-1d601ef6 |
| `review/20260929-tool-contract` | `c19abb3fc242784c1035dd018400fa2268d259ec` | mf-tool-contract-54d8f5ed |
| `review/20260929-bench` | `87fe5e7343a3073d3f1d75bf18f23a024d8d2f02` | wt-bench-08f52f3f |
| `review/20260929-comfy-pin` | `70f718098f00f9dbdeb6cc9c5d7808b243eb0c57` | wt-comfy-5e7bf601 |
| `review/20260929-golden` | `bf3b28fe1e87c0a76c2acd093ac38f9d53cbd6ee` | wt-golden-83f246db |
| `review/20260929-video14b` | `cbd0216931362055e1227f6a09c332735ca2b24f` | wt-video14b-b6bc082b |
| `review/20260929-historical-s06` | `1a3e0fd86daeef278a70d50a576aa9f055b81956` | s06-t01-549eb82e |

`comfy-pin` đặc biệt quan trọng: builder đọc `experiments/mf_reskin_v1/comfy/mf_comfy` từ exact commit, không lấy byte ngẫu nhiên của working directory. `video14b`, `golden`, `bench` và `tool-contract` là source nghiên cứu/hợp đồng để đối chiếu đường proof với product. `historical-main`/`historical-s06` giữ công việc cũ chưa thuộc candidate; không dùng làm điểm chạy sản phẩm mới.

## Clone để review

```powershell
git clone --branch codex/external-review-20260929 https://github.com/anhduyhaha1234-droid/MotionForge2D.git
Set-Location MotionForge2D
git rev-parse HEAD
git show origin/review/20260929-c11-correction --stat
git diff a52fca897906fd61a088016dd802718fdf06d217 origin/review/20260929-c11-correction -- app/services/shot_reskin_plan.py tests/product_delivery/test_mf_end_11.py
```

Repository private: cần được chủ repo mời trước. Dùng full clone (không `--depth` hoặc `--single-branch`) để có các source pin và history assertions. Một file snapshot có thể so với `git show <base_commit>:<path>` theo manifest; không checkout hàng loạt các WIP lên candidate.

## Những gì không đưa vào gói source mới

Model weights, ComfyUI virtualenv/runtime của bên thứ ba, database và toàn bộ user project, video nguồn đầy đủ, credentials, cache, log hội thoại Hermes, raw request token logs và báo cáo test tự sinh bị loại khỏi snapshot mới. Danh sách đường dẫn bị loại trong manifest giúp reviewer thấy phạm vi, không chứa nội dung file đó.

Các fixture/media nhỏ đã tracked trong Git được giữ; bổ sung clip failed R5 12 giây và ảnh đối chiếu để giải thích chất lượng. Chúng không phải sản phẩm được duyệt. Không publish mirror mọi Git ref nội bộ; chỉ những branch source có tên rõ trong hồ sơ. Default branch và các branch đang làm không bị đổi.

## Quy trình và authority

Hợp đồng người dùng và hồ sơ hiện hành quyết định mục tiêu; code/hash/media quyết định kết luận. Hồ sơ `docs/pm/` và các phiên lịch sử là nguồn truy vết. Hermes worker báo cáo → Manager kiểm tra → Codex review độc lập → người dùng nghiệm thu chất lượng. `SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW` không đồng nghĩa `APPROVED` hay `CLOSED`.

Lần bàn giao này chỉ thêm docs/snapshot/evidence và công bố source, không chạy Hermes, không sửa thuật toán hoặc tự đóng S12/S13. Không cần đưa API key vào repo để reviewer đọc code. Bất kỳ script snapshot nào thao tác DB/process chỉ tái lập ở môi trường thử riêng.

## Kiểm tra lần bàn giao

- Đã hash file snapshot và media; kiểm tra manifest khớp nội dung.
- Đã quét pattern credential trên blob history reachable từ các commit công bố và file bàn giao mới; không phát hiện mẫu đã định nghĩa. Đây không phải chứng nhận không thể có secret ở mọi định dạng.
- Đã build `mf-comfy==0.1.0` từ exact pin, verify 11 file, wheel SHA-256 `c5bfa6f6d5a5152209e63f8a681b0f35bdceaae1fb21e0621b6ce95567c065ec`; không cài thêm vào runtime đang dùng.
- Không chạy lại full tests, GPU render hay clean-host install trong lần publish. Số test PASS lịch sử do Manager báo, không dùng thay nghiệm thu.

Receipt publish, remote SHA và kiểm tra fresh clone được lưu trong báo cáo giao nhận local và phản hồi người dùng. Manifest không tự nhúng hash của commit chứa chính nó.
