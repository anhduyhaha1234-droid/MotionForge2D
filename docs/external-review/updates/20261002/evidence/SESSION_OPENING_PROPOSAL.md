# Session Opening Proposal — WAN-PROTOTYPE-01

Authority: user 01/10/2026 yêu cầu video mẫu trước tool, WAN qua ComfyUI, Hermes tự vision review/correct tối đa10 sản phẩm rồi Codex review một lần. Canonical rules §0.2 đã cập nhật. Người dùng tự giao prompt; Codex chưa dispatch.

| Mục | Quyết định |
|---|---|
| Task/microstep | Existing MF-DEMO-E2E-R5 / WAN-PROTOTYPE-01, một outcome media |
| Manager | `20260930_235002_3ac7f9`; nếu user giao Manager mới thì nhận takeover rõ và kiểm không có controller khác |
| Worker | Resume exact `20260929_041810_bc7c61`; không tạo owner trùng |
| Route | custom `cmc/deepseek/deepseek-v4.1-flash`, chat_completions, fallback OFF; vision tool actual phải probe/ghi provider riêng |
| Baseline | INTEGRATION clean a52fca897906fd61a088016dd802718fdf06d217, branch codex/mf-end-integration-0928; read-only |
| Write-set | RUN mới dưới mf-delivery-runs/20261001; Manager RUN/manager; Worker RUN/tasks/MF-DEMO-E2E-R5/WAN-PROTOTYPE-01; run-local graph/harness/media/cache/ASR env |
| Protected | MAIN, INTEGRATION, M1 dirty4files, C19/C25, old evidence, global runtime/models/config; không production/test/DB mutation |
| Wave | WIP1/GPU1, không parallel implementation hoặc integration |
| Dependencies | Source/model/runtime có thật; public UI/library/API không còn là prerequisite cho prototype theo chỉ thị mới |
| Limits | ≤10 candidate versions (partial/fail tính); ≤40 video submissions (≤4units/candidate); ≤20 image submissions; ≤40 vision requests; worker300/Manager60 observed attempts;6h shared deadline; initial+≤3 continuations |
| Early stop | All mandatory criteria PASS, no UNKNOWN, full MP4; SELF_REVIEW_PASS_PENDING_CODEX |
| Recovery | Chỉ theo context-health evidence và zero concurrent writer; không transfer vì history dài đơn thuần |
| Deferred | M1/UI corrections, full app integration, batch/S12/S13; giữ NOT_APPROVED/NOT_CLOSED |
| Review | Hermes tự kiểm media trong task; Codex độc lập một lần sau submission; QUALITY_ACCEPTED=0 trước verdict |
| Dispatch state | AUTHORIZED_FOR_USER_HANDOFF; chỉ Manager được user giao prompt thực hiện. Codex không tự launch/message |

Raw read-only preflight và query được lưu trong PROTOTYPE_PREFLIGHT.json / prototype_preflight_readonly.py. Saved DB labels không chứng minh live route/activity; Manager phải kiểm actual. Prompt đầy đủ: NEXT_HERMES_DEMO_PROMPT.md.

Reuse update: đọc REUSE_EXECUTION_MATRIX.md và MOTION_WINDOW_FINDING.md. WAN baseline cho prototype là copy `reuse_bundle/wan_shot_v1.motion_enabled.api.json`, sửa pose_end_percent0→1.0 từ graph/P6 cũ. Installed UI template cũng cần sửa link trên bản sao nếu dùng để export; không coi widget default là effective input. Rebind source/cast/prompt từng shot. Chưa render; timing/VRAM full-pose phải đo lại.
