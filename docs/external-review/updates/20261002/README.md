# MotionForge2D — cập nhật source bàn giao 02/10/2026

**Nhánh GitHub:** `review/20261002-full-code`. Đây là bản code và hồ sơ để developer review, không phải release đã nghiệm thu. `SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW — NOT_APPROVED / NOT_CLOSED`, `QUALITY_ACCEPTED=0`.

## Đọc đúng bản code

| Phần | Vị trí | Trạng thái |
|---|---|---|
| Backend/frontend tích hợp | `app/`, `frontend/`, `tests/`, `migrations/`, `scripts/` ở root | Candidate `a52fca897906fd61a088016dd802718fdf06d217`, implementation không đổi trong lần publish này |
| Source còn sửa dở | `review-snapshots-20261002/` + [manifest](CODE_SNAPSHOT_MANIFEST.json) | Chụp mới903 file records,821 nội dung riêng,11.85MB; không tự merge vào candidate |
| Các commit chưa thuộc candidate | Các nhánh `review/20261002-source-<sha12>` trong manifest | Có đầy đủ Git objects để diff; gồm C11/C15/C22 và nhánh research/lịch sử |
| Workflow WAN đã sửa cấu hình | [motion_enabled API graph](reuse_bundle/wan_shot_v1.motion_enabled.api.json) | Copy thí nghiệm, sửa đúng một giá trị end0→1; cần bind media từng shot; chưa inference |
| Rules/handoff/roadmap hiện hành | [current-pm-20261002](current-pm-20261002/) | Bản cập nhật cuối02/10 từ MAIN; ưu tiên chứng minh video mẫu trước tích hợp tool |

Capture source kết thúc **2026-10-02T02:56:02.380416Z** (09:56:02 +07),100 worktree. [Manifest](CODE_SNAPSHOT_MANIFEST.json) ghi commit nền, path, hash, rename/deletion, phân loại WIP và phần loại trừ. [Artifact index](ARTIFACT_INDEX.json) ghi hash của các báo cáo/workflow bổ sung. Đây là snapshot tại thời điểm, không phải đồng bộ liên tục. Snapshot29/09 giữ nguyên để đối chiếu.

## Mục tiêu sản phẩm không đổi

Video nguồn → phân cảnh/đoạn chuyển động → bộ nhân vật/props/style riêng dùng nhất quán cả series → ComfyUI tạo ảnh cảnh thay thế → WAN sinh từng đoạn theo driving nguồn → kiểm chất lượng → ghép timeline/tiếng gốc → xuất và mở lại. Giữ sát hành động, tương tác, camera và nhịp cắt; thay toàn bộ diện mạo thuộc scope. Sau video mẫu đạt mới đưa workflow đã chứng minh về tool/batch/S12/S13.

Hướng triển khai mới tách theo cảnh; cảnh dài được chia tiếp theo giới hạn runtime, giữ mối nối và context. Giữ người đang tương tác cùng đoạn. Tái sử dụng đoạn đạt và chỉ chạy lại đoạn lỗi cùng các đoạn phụ thuộc continuation. Không sinh mỗi frame độc lập hoặc đổi cast mỗi shot. Tối đa10 phiên bản mẫu có log, dừng sớm khi đạt, Codex review cuối. [Prompt hiện hành02/10](prompt-20261002/NEXT_HERMES_DEMO_PROMPT.md) và [Session Opening Proposal](prompt-20261002/SESSION_OPENING_PROPOSAL.md) thay packet01/10 cho cùng prototype; được tối đa8chunk/candidate trong trần40video submissions toàn lượt, không reset counters/deadline nếu đãdispatch. [Additional artifact index](ADDITIONAL_ARTIFACT_INDEX.json) ghi hashes và mốc chụp bổ sung sau cutoff code. Chưa dispatch/chạy video mới trong lần bàn giao này.

## Phát hiện mới cần reviewer chú ý

1. **WAN motion conditioning window sai:** node `672:587` trong `app/media_workflows/wan_shot_v1.json` đặt start0/end0. Runtime cho phép điều kiện pose ở biên đầu với schedule đã kiểm, thay vì suốt sampling. Template UI installed còn nối cùng start vào cả end. [Audit độc lập](evidence/MOTION_WINDOW_FINDING.md) đối chiếu cả graph P6/receipt; số135.21s và10763MiB cũ không phải phép đo full-window. [Bản sửa](reuse_bundle/wan_shot_v1.motion_enabled.api.json) đã qua static review; chất lượng/tốc độ/VRAM sau sửa chưa được đo.
2. **M1-01:** bốn file source đang sửa liên quan tạo nhân vật, API, dialog và e2e. [Review01/10](evidence/M1_CODEX_REVIEW_20261001.md), [correction matrix](evidence/M1_CORRECTION_MATRIX_20261001.md). Không dùng `frontend/test-results/.last-run.json` làm source hoặc bằng chứng sản phẩm.
3. **C19:** ba file WIP `s10_full_apply.py`, `s10_chunk_plan.py`, `shot_reskin_executor.py`; chưa tích hợp. Có thay đổi cấu trúc hàm đáng ngờ trong executor cần review trước khi chạy; lưu nguyên bytes để truy nguyên, không sửa hoặc tuyên bố đã pass ở lần publish này.
4. **C25:** bảy file source WIP, gồm import/analyze UI và shot-anchors. Tên component không chứng minh có generation: phần anchor hiện cần phân biệt tọa độ/bố cục với submit Comfy tạo ảnh thật. Server còn chạy trên checkout này cũng không chứng minh candidate root đã chạy end-to-end.
5. Các lỗi bindings/ảnh reference/prompt theo shot, audio/QC và trạng thái chưa nghiệm thu phải đọc cùng [code review29/09](evidence/CODE_REVIEW_20260929.md). Test count và integrity gates không thay video đúng yêu cầu.

## Backend ở đâu và chạy endpoint nào?

- Backend là **`app/`**, Python/FastAPI; entry `app/main.py` → `app/api/app.py`. Routes `app/api/routes/`, business logic `app/services/`, lưu trữ `app/persistence/`.
- `backend/` trong MAIN local chỉ là khung rỗng, không phải backend triển khai.
- Kiểm trên máy chủ ngày02/10: process uvicorn PID36088, cwd `C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C25`, cổng **8041**; `/health`, `/docs`, `/openapi.json` đều HTTP200. OpenAPI title MotionForge2D API,308 path keys (gồm alias). Chưa smoke-test tất cả endpoint.
- Ví dụ local: `http://127.0.0.1:8041/docs`; `/api/v2/projects`, `/api/v2/characters`, `/api/jobs/{job_id}`. Đây là server local tại thời điểm kiểm, không phải public deployment hoặc địa chỉ truy cập từ máy dev khác.
- Các file cũ MAIN có8002/8888 khác nhau. Khi dựng môi trường review phải chọn một cổng và nối frontend đúng API base; không dùng con số trong README cũ làm runtime proof.
- MAIN `C:/Users/Admin/MotionForge2D` đang mở trong VS Code là checkout lịch sử khác candidate tích hợp. Sửa MAIN không tự cập nhật server C25.

## Lấy toàn bộ source để review

```powershell
git clone --branch review/20261002-full-code https://github.com/anhduyhaha1234-droid/MotionForge2D.git
Set-Location MotionForge2D
git rev-parse HEAD
```

Không shallow/single-branch clone nếu cần exact dependency commits. Dùng base_commit và path trong manifest để diff WIP; các file chưa thay nằm ở Git commit nền, snapshot chỉ bổ sung bytes đã đổi. Không copy tất cả snapshot chồng lên root: nhiều nhánh thay cùng file theo các mục tiêu khác nhau và có verifier/negative-control.

GitHub metadata kiểm02/10 cho thấy repo **public**; lần publish này không đổi visibility, collaborators hay default branch `main`. Link bàn giao phải mở đúng nhánh `review/20261002-full-code`; `main` vẫn là lịch sử cũ. Chủ repo có thể mời collaborator qua Settings → Collaborators.

## Phạm vi công bố và xác minh

Source, migration, config mẫu, tests, script demo/điều phối và docs được chụp theo allowlist. Không đóng gói credentials, `.env`, database/user projects, checkpoint model nhiềuGB, virtualenv/node_modules/cache, raw hội thoại/request logs hoặc Windows backups. Các file lớn/ngoài source có lý do loại trừ trong manifest. Fixture/media đã tracked từ các commit trước vẫn giữ lịch sử.

Lần này chỉ tạo snapshot/docs và publish Git: không gọi model, không render GPU, không chạy lại full product tests, không merge WIP và không thay đổi index/bytes của các worktree nguồn. Kiểm hash snapshot/artifacts, kiểm staged bytes, quét pattern credential và blob lớn trước push; kiểm SHA remote sau push. Kết quả là bằng chứng bàn giao source, không phải bằng chứng các chức năng đã hoàn thiện.

Các docs29/09 vẫn hữu ích để hiểu BA/kiến trúc; bản cập nhật này ưu tiên cho trạng thái hiện tại, route local, motion finding, cast/demo-first và phạm vi source. Không coi skill đã cài trên máy chủ là dependency bắt buộc cho dev để đọc/chạy code.
