/**
 * Preflight/incompatibility error taxonomy for the Import/Analyze UI.
 *
 * Source of truth: `docs/architecture/VIDEO_PREFLIGHT_CONTRACT.md` §7
 * (12 stable codes + severity + Vietnamese suggested actions) extended by
 * the V1 PM decisions implemented in `app/services/video_import.py`
 * (INSUFFICIENT_DISK, HDR_UNSUPPORTED, INVALID_VIDEO_METADATA,
 * PATH_CONTAINMENT, VIDEO_ITEM_NOT_FOUND, PROJECT_NOT_FOUND,
 * OWNERSHIP_MISMATCH, PUBLICATION_FAILED, CANCELLED) and the S05-T04
 * scene-detection codes (`app/services/scene_detector.py`). The Vietnamese
 * action strings are copied VERBATIM from the backend
 * `VIETNAMESE_ACTIONS` dicts so UI and backend never disagree.
 *
 * The durable job API exposes `error` as the envelope MESSAGE string (the
 * code itself is not in the legacy JobInfo response), so the UI matches
 * stable code tokens inside the error string and falls back to the raw
 * backend message — never a bare "failed".
 */

export type PreflightSeverity = "blocker" | "warning" | "info";

export interface PreflightErrorInfo {
  code: string;
  severity: PreflightSeverity;
  action: string;
}

const ACTION_INPUT_MISSING =
  "Tệp nguồn không tồn tại hoặc đã bị di chuyển. Vui lòng chọn lại tệp video.";
const ACTION_INPUT_UNREADABLE =
  "Không thể đọc tệp nguồn (thiếu quyền hoặc tệp đang bị khóa). Kiểm tra quyền truy cập và thử lại.";
const ACTION_NO_VIDEO_STREAM =
  "Tệp không chứa luồng video. Tệp này có thể không phải video hợp lệ; hãy chọn tệp video khác.";
const ACTION_UNSUPPORTED_CONTAINER =
  "Định dạng container chưa được hỗ trợ. Chỉ hỗ trợ MP4; hãy chuyển đổi tệp sang MP4 (H.264/HEVC + AAC) rồi thử lại.";
const ACTION_UNSUPPORTED_CODEC =
  "Codec video chưa được hỗ trợ. Chỉ hỗ trợ H.264 (AVC) và HEVC (H.265); hãy chuyển đổi codec rồi thử lại.";
const ACTION_UNSUPPORTED_AUDIO_CODEC =
  "Codec âm thanh chưa được hỗ trợ (chỉ hỗ trợ AAC). Hãy chuyển đổi âm thanh sang AAC rồi thử lại.";
const ACTION_NO_AUDIO_STREAM =
  "Video không có âm thanh. Vẫn import được nhưng output sẽ không có audio (PRD §9 Step 4/FR-07).";
const ACTION_PROBE_TIMEOUT =
  "Quá thời gian phân tích. Hãy thử lại; nếu tệp quá lớn, hãy kiểm tra định dạng hoặc tốc độ ổ đĩa.";
const ACTION_PROBE_BINARY_NOT_FOUND =
  "Không tìm thấy ffprobe. Cài đặt FFmpeg (winget install Gyan.FFmpeg) hoặc đặt MOTIONFORGE_FFMPEG/MOTIONFORGE_FFPROBE rồi thử lại.";
const ACTION_PROBE_NONZERO_EXIT =
  "ffprobe không đọc được tệp. Tệp có thể bị hỏng hoặc không phải video hợp lệ; hãy kiểm tra lại tệp nguồn.";
const ACTION_PROBE_JSON_PARSE_ERROR =
  "Kết quả phân tích không hợp lệ. Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi hệ thống kèm tệp nguồn.";
const ACTION_CHECKSUM_MISMATCH =
  "Kiểm tra toàn vẹn tệp thất bại (checksum không khớp). Nguồn có thể bị thay đổi hoặc hỏng; hãy kiểm tra lại tệp nguồn trước khi import.";
const ACTION_INSUFFICIENT_DISK =
  "Không đủ dung lượng ổ đĩa cho tệp nguồn cộng với vùng dự phòng 1 GiB. Giải phóng dung lượng trên ổ lưu trữ rồi thử lại.";
const ACTION_HDR_UNSUPPORTED =
  "Đầu vào HDR/10-bit chưa được hỗ trợ ở phiên bản V1. Hãy chuyển đổi tệp sang SDR 8-bit trước khi import.";
const ACTION_INVALID_VIDEO_METADATA =
  "Thông số video không hợp lệ (cần thời lượng và kích thước dương). Hãy kiểm tra lại tệp nguồn.";
const ACTION_PATH_CONTAINMENT =
  "Đường dẫn tệp không hợp lệ hoặc cố thoát khỏi vùng lưu trữ được quản lý. Hãy kiểm tra lại tên tệp nguồn.";
const ACTION_VIDEO_ITEM_NOT_FOUND =
  "Video Item không tồn tại hoặc đã bị lưu trữ. Hãy tạo lại Video Item rồi thử import.";
const ACTION_PROJECT_NOT_FOUND =
  "Project không tồn tại hoặc đã bị lưu trữ. Hãy kiểm tra Project và thử lại.";
const ACTION_OWNERSHIP_MISMATCH =
  "Video Item không thuộc Project/Workspace được khai báo. Hãy chọn đúng Project và Workspace chứa Video Item rồi thử lại.";
const ACTION_PUBLICATION_FAILED =
  "Không thể công bố artifact nguồn. Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi hệ thống kèm Job id.";
const ACTION_CANCELLED = "Import đã bị hủy theo yêu cầu.";
const ACTION_SCENE_DETECT_FAILED =
  "Không phát hiện được cảnh (ffmpeg thoát lỗi). Tệp proxy/nguồn có thể bị hỏng; hãy kiểm tra lại và thử lại.";
const ACTION_SCENE_DETECT_TIMEOUT =
  "Quá thời gian phát hiện cảnh. Hãy thử lại; nếu tệp quá lớn, hãy kiểm tra định dạng hoặc tốc độ ổ đĩa.";
const ACTION_SCENE_PROFILE_INVALID =
  "Profile phát hiện cảnh không hợp lệ (ngưỡng phải trong [0,1], độ dài tối thiểu ≥ 1, thời gian > 0). Hãy kiểm tra lại cấu hình.";
const ACTION_INPUT_CHANGED =
  "Đầu vào của Job đã thay đổi so với lần chạy trước (proxy/nguồn khác hoặc tệp bị thay thế). Hãy tạo lại Job với generation mới để phân tích lại.";
const ACTION_SCENE_EVIDENCE_CONFLICT =
  "Dữ liệu cảnh hiện có của Video Item không khớp với kết quả phát hiện (cảnh đã tồn tại từ nguồn khác). Job không ghi đè cảnh của nguồn khác; hãy kiểm tra dữ liệu cảnh hiện có trước khi phân tích lại.";
const ACTION_UNKNOWN_ANALYZE_STEP =
  "Bước ANALYZE_MEDIA không xác định. Hãy báo lỗi hệ thống kèm Job id.";
const ACTION_PROXY_ARTIFACT_NOT_FOUND =
  "Artifact proxy không tồn tại hoặc không thuộc Workspace này. Hãy tạo proxy (S05-T03) trước khi phát hiện cảnh.";
const ACTION_PROXY_NOT_READY =
  "Artifact proxy chưa sẵn sàng (không phải video ready hoặc thiếu checksum). Hãy đợi proxy hoàn tất rồi thử lại.";
const ACTION_PROXY_OWNER_MISMATCH =
  "Artifact proxy không được liên kết với Video Item này (thiếu liên kết purpose=proxy). Hãy tạo proxy cho đúng Video Item.";
const ACTION_GENERIC =
  "Hãy thử lại; nếu lỗi lặp lại, hãy báo lỗi hệ thống kèm Job id.";

/** Stable code → severity + approved Vietnamese suggested action. */
export const PREFLIGHT_ERRORS: Readonly<Record<string, PreflightErrorInfo>> = {
  INPUT_MISSING: { code: "INPUT_MISSING", severity: "blocker", action: ACTION_INPUT_MISSING },
  INPUT_UNREADABLE: { code: "INPUT_UNREADABLE", severity: "blocker", action: ACTION_INPUT_UNREADABLE },
  NO_VIDEO_STREAM: { code: "NO_VIDEO_STREAM", severity: "blocker", action: ACTION_NO_VIDEO_STREAM },
  UNSUPPORTED_CONTAINER: { code: "UNSUPPORTED_CONTAINER", severity: "blocker", action: ACTION_UNSUPPORTED_CONTAINER },
  UNSUPPORTED_CODEC: { code: "UNSUPPORTED_CODEC", severity: "blocker", action: ACTION_UNSUPPORTED_CODEC },
  UNSUPPORTED_AUDIO_CODEC: { code: "UNSUPPORTED_AUDIO_CODEC", severity: "warning", action: ACTION_UNSUPPORTED_AUDIO_CODEC },
  NO_AUDIO_STREAM: { code: "NO_AUDIO_STREAM", severity: "warning", action: ACTION_NO_AUDIO_STREAM },
  PROBE_TIMEOUT: { code: "PROBE_TIMEOUT", severity: "blocker", action: ACTION_PROBE_TIMEOUT },
  PROBE_BINARY_NOT_FOUND: { code: "PROBE_BINARY_NOT_FOUND", severity: "blocker", action: ACTION_PROBE_BINARY_NOT_FOUND },
  PROBE_NONZERO_EXIT: { code: "PROBE_NONZERO_EXIT", severity: "blocker", action: ACTION_PROBE_NONZERO_EXIT },
  PROBE_JSON_PARSE_ERROR: { code: "PROBE_JSON_PARSE_ERROR", severity: "blocker", action: ACTION_PROBE_JSON_PARSE_ERROR },
  CHECKSUM_MISMATCH: { code: "CHECKSUM_MISMATCH", severity: "blocker", action: ACTION_CHECKSUM_MISMATCH },
  INSUFFICIENT_DISK: { code: "INSUFFICIENT_DISK", severity: "blocker", action: ACTION_INSUFFICIENT_DISK },
  HDR_UNSUPPORTED: { code: "HDR_UNSUPPORTED", severity: "blocker", action: ACTION_HDR_UNSUPPORTED },
  INVALID_VIDEO_METADATA: { code: "INVALID_VIDEO_METADATA", severity: "blocker", action: ACTION_INVALID_VIDEO_METADATA },
  PATH_CONTAINMENT: { code: "PATH_CONTAINMENT", severity: "blocker", action: ACTION_PATH_CONTAINMENT },
  VIDEO_ITEM_NOT_FOUND: { code: "VIDEO_ITEM_NOT_FOUND", severity: "blocker", action: ACTION_VIDEO_ITEM_NOT_FOUND },
  PROJECT_NOT_FOUND: { code: "PROJECT_NOT_FOUND", severity: "blocker", action: ACTION_PROJECT_NOT_FOUND },
  OWNERSHIP_MISMATCH: { code: "OWNERSHIP_MISMATCH", severity: "blocker", action: ACTION_OWNERSHIP_MISMATCH },
  PUBLICATION_FAILED: { code: "PUBLICATION_FAILED", severity: "blocker", action: ACTION_PUBLICATION_FAILED },
  CANCELLED: { code: "CANCELLED", severity: "info", action: ACTION_CANCELLED },
  SCENE_DETECT_FAILED: { code: "SCENE_DETECT_FAILED", severity: "blocker", action: ACTION_SCENE_DETECT_FAILED },
  SCENE_DETECT_TIMEOUT: { code: "SCENE_DETECT_TIMEOUT", severity: "blocker", action: ACTION_SCENE_DETECT_TIMEOUT },
  SCENE_PROFILE_INVALID: { code: "SCENE_PROFILE_INVALID", severity: "blocker", action: ACTION_SCENE_PROFILE_INVALID },
  INPUT_CHANGED: { code: "INPUT_CHANGED", severity: "blocker", action: ACTION_INPUT_CHANGED },
  SCENE_EVIDENCE_CONFLICT: { code: "SCENE_EVIDENCE_CONFLICT", severity: "blocker", action: ACTION_SCENE_EVIDENCE_CONFLICT },
  UNKNOWN_ANALYZE_STEP: { code: "UNKNOWN_ANALYZE_STEP", severity: "blocker", action: ACTION_UNKNOWN_ANALYZE_STEP },
  PROXY_ARTIFACT_NOT_FOUND: { code: "PROXY_ARTIFACT_NOT_FOUND", severity: "blocker", action: ACTION_PROXY_ARTIFACT_NOT_FOUND },
  PROXY_NOT_READY: { code: "PROXY_NOT_READY", severity: "blocker", action: ACTION_PROXY_NOT_READY },
  PROXY_OWNER_MISMATCH: { code: "PROXY_OWNER_MISMATCH", severity: "blocker", action: ACTION_PROXY_OWNER_MISMATCH },
};

/**
 * Match a backend error string against the approved stable-code taxonomy.
 *
 * The durable JobInfo `error` field carries the envelope message; the code
 * itself is not exposed by the legacy response. We therefore scan the
 * string for stable code tokens (e.g. "UNSUPPORTED_CODEC", "PROBE_TIMEOUT")
 * — these appear verbatim in S05 service messages and envelopes. When no
 * code token matches, the caller MUST still render the raw backend message
 * (never a bare "failed"); `matchPreflightError` returns `null` then.
 */
export function matchPreflightError(error: string | null | undefined): PreflightErrorInfo | null {
  if (!error) return null;
  for (const code of Object.keys(PREFLIGHT_ERRORS)) {
    // Token boundary: the code as a standalone uppercase token.
    const re = new RegExp(`\\b${code}\\b`);
    if (re.test(error)) return PREFLIGHT_ERRORS[code];
  }
  return null;
}

/** Generic recoverable-error guidance (contract-aligned fallback). */
export const GENERIC_ACTION: PreflightErrorInfo = {
  code: "UNKNOWN",
  severity: "blocker",
  action: ACTION_GENERIC,
};

/** Vietnamese label for a job state (UI_UX_DESIGN_STANDARD copy). */
export const JOB_STATE_LABEL: Record<string, string> = {
  pending: "Đang chờ",
  queued: "Đang xếp hàng",
  running: "Đang xử lý",
  cancelling: "Đang hủy",
  cancelled: "Đã hủy",
  completed: "Hoàn tất",
  failed: "Thất bại",
};
