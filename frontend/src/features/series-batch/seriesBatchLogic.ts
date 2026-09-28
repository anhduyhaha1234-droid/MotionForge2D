/**
 * MF-END-27 — nhãn tiếng Việt + suy luận hiển thị cho batch series (thuần hàm).
 *
 * Không gọi mạng, không đọc DOM: chỉ dịch trạng thái durable của batch thành
 * chuỗi hiển thị, để panel và test cùng dùng một nguồn.
 */

import type { BatchVideoState, SeriesBatchView } from "./seriesBatchApi";

export const VIDEO_STATE_VI: Record<BatchVideoState, string> = {
  pending: "Chờ xếp hàng",
  deferred_lease: "Chờ lượt (video trước đang chạy)",
  running: "Đang chạy",
  completed: "Hoàn tất",
  failed: "Lỗi",
  cancelled: "Đã huỷ",
};

export const BATCH_STATE_VI: Record<string, string> = {
  queued: "Đã xếp hàng",
  running: "Đang chạy",
  completed: "Hoàn tất",
  partial_failure: "Có video lỗi — video khác vẫn giữ nguyên",
};

export function videoStateLabel(state: string | null | undefined): string {
  if (!state) return "Chưa có trạng thái";
  return VIDEO_STATE_VI[state as BatchVideoState] ?? state;
}

export function batchStateLabel(state: string | null | undefined): string {
  if (!state) return "Chưa có trạng thái";
  return BATCH_STATE_VI[state] ?? state;
}

export function isTerminalVideoState(state: string | null | undefined): boolean {
  return state === "completed" || state === "failed" || state === "cancelled";
}

/**
 * Đo lường chỉ hiển thị số khi THẬT SỰ đo — nếu chưa đo phải hiện nguyên văn
 * "unmeasured" (U26: không hứa 30 phút từ một mẫu dễ).
 */
export function metricsText(metrics: Record<string, unknown> | null | undefined): string {
  if (!metrics) return "unmeasured";
  if (metrics.measured !== true) return "unmeasured";
  const throughput = metrics.throughput_accepted_per_second;
  const ram = metrics.peak_ram_mb;
  const forecast = metrics.forecast_30min;
  return `throughput ${String(throughput)} · RAM ${String(ram)} MB · dự báo 30 phút ${String(forecast)}`;
}

export function outputText(
  output: { path: string; size_bytes: number; sha256: string | null } | null | undefined,
): string {
  if (!output) return "chưa có file xuất";
  const short = output.sha256 ? output.sha256.slice(0, 12) : "chưa băm";
  return `${output.path} · ${output.size_bytes} byte · sha ${short}`;
}

export function errorText(error: Record<string, unknown> | null | undefined): string | null {
  if (!error) return null;
  const code = typeof error.code === "string" ? error.code : "series_batch_error";
  const detail = typeof error.detail === "string" ? error.detail : JSON.stringify(error);
  return `${code}: ${detail}`;
}

export function leaseText(view: SeriesBatchView | null | undefined): string {
  if (!view) return "chưa có batch";
  const lease = view.lease;
  return `tối đa ${lease.max_heavy_in_flight} job nặng cùng lúc · đang chạy ${lease.active_heavy}`;
}

/** Video kế tiếp sẽ được mở khi lượt nặng trống (dùng cho nút "Mở video kế tiếp"). */
export function nextVideoId(view: SeriesBatchView | null | undefined): string | null {
  if (!view) return null;
  const next = view.videos.find(
    (row) => row.state === "deferred_lease" || row.state === "pending",
  );
  return next ? next.video_item_id : null;
}

export function canAdvance(view: SeriesBatchView | null | undefined): boolean {
  if (!view) return false;
  if (!view.lease.serialized) return false;
  return nextVideoId(view) !== null;
}
