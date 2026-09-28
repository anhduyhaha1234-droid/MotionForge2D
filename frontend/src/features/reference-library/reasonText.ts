/**
 * MF-END-10 — nhãn tiếng Việt cho lý do/cảnh báo của luồng chọn bộ + job asset.
 *
 * Mọi code do server trả về đều có nhãn VI; code chưa biết hiển thị nguyên văn
 * (không bao giờ bịa nghĩa). Không hiển thị chi tiết nội bộ của engine cho
 * người dùng — chỉ lý do hữu ích.
 */

export const CANDIDATE_REASON_VI: Record<string, string> = {
  series_pin: "Đang nằm trong bộ series đã chốt",
  series_entry: "Thuộc snapshot series đã chốt",
  series_pin_stale: "Bộ series đã chốt không còn khớp kho hiện tại",
  library_candidate: "Có trong kho đã xuất bản",
  published_complete_kind_compatible: "Đã xuất bản, đủ điều kiện và đúng loại đối tượng",
  required_capabilities_declared: "Có khai capability cần thiết",
  style_unverified: "Chưa xác minh được phong cách từ kho",
  metadata_rank: "Xếp hạng theo chất lượng metadata",
  covers_required_views: "Đủ mọi view bắt buộc",
  missing_required_views: "Thiếu một số view bắt buộc",
  missing_required_pose: "Thiếu tư thế bắt buộc",
  style_match: "Khớp phiên bản phong cách",
  style_mismatch: "Khác phiên bản phong cách",
  newest_pack: "Phiên bản pack mới nhất",
  more_views: "Nhiều view hơn",
  unpublished_pack: "Pack chưa xuất bản",
  archived_character: "Nhân vật đã lưu trữ",
  workspace_mismatch: "Khác workspace",
  source_overlay_refusal: "Role source_overlay không thể dùng làm cast",
  object_kind_mismatch: "Loại đối tượng không khớp",
  incomplete_pack: "Pack chưa hoàn chỉnh",
  generation_mismatch: "Thế hệ dữ liệu không khớp",
  missing_required_capability: "Thiếu capability bắt buộc",
  advisory_tie: "Nhiều lựa chọn ngang nhau — AI chọn thay",
  advisory_choice: "AI đề xuất (ưu tiên lý do ở trên)",
  advisory_choice_outside_permitted_set: "AI chọn ngoài tập hợp lệ — đã bỏ qua",
  advisory_unavailable: "Không gọi được AI — dùng xếp hạng theo metadata",
  manual_choice_available: "Có thể tự chọn thủ công từ danh sách",
};

export const FILTER_REASON_VI: Record<string, string> = {
  unpublished_pack: "Chưa xuất bản",
  archived_character: "Nhân vật đã lưu trữ",
  workspace_mismatch: "Khác workspace",
  source_overlay_refusal: "Role source_overlay không thể thay thế",
  object_kind_mismatch: "Loại đối tượng không khớp",
  incomplete_pack: "Thiếu tư thế bắt buộc",
  missing_required_pose: "Thiếu tư thế bắt buộc",
  missing_required_capability: "Thiếu capability bắt buộc",
  generation_mismatch: "Thế hệ dữ liệu không khớp",
};

export const SELECTION_MODE_VI: Record<string, string> = {
  series_pin: "Theo bộ series đã chốt",
  advisory: "AI đề xuất",
  metadata: "Xếp hạng theo metadata",
  none: "Chưa có lựa chọn",
  manual: "Tự chọn thủ công",
};

export const ADVISORY_STATUS_VI: Record<string, string> = {
  not_requested: "Không yêu cầu AI",
  not_needed: "Không cần AI (kết quả đã rõ)",
  ok: "AI đã phản hồi",
  unavailable: "AI không khả dụng",
};

export const JOB_STATE_VI: Record<string, string> = {
  queued: "Đang chờ máy chủ xử lý",
  running: "Đang tạo ảnh bằng engine",
  completed: "Hoàn tất",
  failed: "Thất bại",
  cancelled: "Đã hủy",
  superseded: "Đã thay thế bởi lần chạy mới",
};

export function reasonLabel(code: string): string {
  return CANDIDATE_REASON_VI[code] ?? code;
}

export function filteredReasonLabel(code: string): string {
  return FILTER_REASON_VI[code] ?? code;
}

export function selectionModeLabel(mode: string): string {
  return SELECTION_MODE_VI[mode] ?? mode;
}

export function advisoryStatusLabel(status: string): string {
  return ADVISORY_STATUS_VI[status] ?? status;
}

export function jobStateLabel(state: string): string {
  return JOB_STATE_VI[state] ?? state;
}

/** Job đã kết thúc (không còn poll). */
export function isTerminalJobState(state: string): boolean {
  return state === "completed" || state === "failed" || state === "cancelled";
}

/** Nhãn VI cho lỗi HTTP của route kho cast/asset (không lộ chi tiết engine). */
export function httpErrorText(status: number, detail: string): string {
  if (status === 404) return `Không tìm thấy dữ liệu (404). ${detail}`.trim();
  if (status === 409) return `Xung đột trạng thái (409) — dữ liệu đã thay đổi. ${detail}`.trim();
  if (status === 413) return `Ảnh quá lớn (413). ${detail}`.trim();
  if (status === 415) return `Ảnh không đọc được (415). ${detail}`.trim();
  if (status === 422) return `Dữ liệu chưa hợp lệ (422). ${detail}`.trim();
  return `Lỗi ${status}. ${detail}`.trim();
}
