"use client";

import type { S12ExportRunStatusPayload } from "@/lib/s12-export-api";

const HELPER = "text-[11px] leading-snug text-gray-400";

interface ExportProgressProps {
  runId: string;
  data: S12ExportRunStatusPayload | null;
  loading: boolean;
  error: string | null;
  actionBusy: "cancel" | "retry" | null;
  canCancel: boolean;
  canRetry: boolean;
  onCancel: () => void;
  onRetry: () => void;
}

function statusLabel(status: string): string {
  switch (status) {
    case "pending":
      return "Đang chờ";
    case "running":
      return "Đang chạy";
    case "verifying":
      return "Đang xác minh";
    case "completed":
      return "Hoàn tất";
    case "failed":
      return "Thất bại";
    case "cancelled":
      return "Đã hủy";
    default:
      return status;
  }
}

function statusClass(status: string): string {
  switch (status) {
    case "completed":
      return "bg-emerald-900/30 text-emerald-300";
    case "failed":
      return "bg-red-900/30 text-red-300";
    case "cancelled":
      return "bg-amber-900/30 text-amber-300";
    default:
      return "bg-indigo-900/30 text-indigo-300";
  }
}

function chunkStateLabel(state: string): string {
  switch (state) {
    case "completed":
      return "Hoàn tất";
    case "running":
      return "Đang chạy";
    case "failed":
      return "Thất bại";
    case "skipped":
      return "Bỏ qua";
    default:
      return "Chờ";
  }
}

function shortId(value: string | null): string {
  if (!value) return "—";
  return value.length > 18 ? `${value.slice(0, 18)}…` : value;
}

export function ExportProgress({
  runId,
  data,
  loading,
  error,
  actionBusy,
  canCancel,
  canRetry,
  onCancel,
  onRetry,
}: ExportProgressProps) {
  const totalChunks = data?.chunks.length ?? 0;
  const verifiedChunks = data?.chunks.filter((chunk) => chunk.verified === 1).length ?? 0;
  const progress = totalChunks > 0 ? Math.round((verifiedChunks / totalChunks) * 100) : 0;

  return (
    <section
      className="min-w-0 w-full rounded border border-gray-700 bg-gray-900/40 p-3 sm:p-4"
      data-testid="export-progress"
      aria-label="Tiến trình export"
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-gray-100">Tiến trình export</h2>
          <p className={HELPER}>
            Polling trạng thái backend mỗi 2 giây khi pending, running hoặc verifying; dừng khi run ở trạng thái cuối.
          </p>
        </div>
        <span className="max-w-full break-all rounded bg-gray-800 px-2 py-1 font-mono text-[11px] text-gray-300">
          run_id: {runId}
        </span>
      </div>

      {error && (
        <p className="mt-3 break-words rounded border border-red-800 bg-red-900/20 px-3 py-2 text-xs text-red-300" role="alert">
          {error}
        </p>
      )}

      {!data && loading && (
        <p className="mt-3 text-sm text-gray-300">Đang tải trạng thái export…</p>
      )}

      {data && (
        <>
          <div className="mt-3 flex min-w-0 flex-wrap items-center gap-2">
            <span className={`rounded px-2 py-1 text-xs font-medium ${statusClass(data.status)}`} data-testid="export-status">
              Trạng thái: {statusLabel(data.status)}
            </span>
            <span className="rounded bg-gray-800 px-2 py-1 text-xs text-gray-300">
              Job: {data.job_state ?? "—"}
            </span>
            {loading && <span className={HELPER}>đang cập nhật…</span>}
          </div>

          <div className="mt-4 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-400">
              <span>
                Tiến độ xác minh: <span className="font-medium text-gray-200">{progress}%</span>
              </span>
              <span>
                {verifiedChunks}/{totalChunks} chunks đã verified
              </span>
            </div>
            <div
              className="h-2 w-full overflow-hidden rounded bg-gray-800"
              role="progressbar"
              aria-label="Tiến độ chunk đã verified"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div className="h-full bg-indigo-600 transition-all" style={{ width: `${progress}%` }} />
            </div>
            <p className={HELPER}>Phần trăm chỉ tính chunk có verified = 1 từ backend; không suy diễn từ state hoặc output path.</p>
          </div>

          <div className="mt-4 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
            <p className="min-w-0 break-words rounded bg-gray-800 px-3 py-2 text-xs text-gray-300">
              Attempt: <span className="font-medium text-gray-100">{data.attempt}</span> · Revision: {data.revision}
            </p>
            <p className="min-w-0 break-all rounded bg-gray-800 px-3 py-2 text-xs text-gray-300">
              Job ID: <span className="font-mono text-gray-100">{data.job_id ?? "—"}</span>
            </p>
          </div>

          <div className="mt-4 flex min-w-0 flex-wrap gap-2">
            <div className="flex min-w-[9rem] max-w-full flex-col items-start gap-1">
              <button
                type="button"
                onClick={onCancel}
                disabled={!canCancel || actionBusy !== null}
                className={`min-h-9 rounded px-3 py-1.5 text-xs font-medium ${canCancel && actionBusy === null ? "bg-red-700 text-white hover:bg-red-600" : "cursor-not-allowed bg-gray-700 text-gray-400"}`}
                data-testid="export-cancel"
              >
                {actionBusy === "cancel" ? "Đang hủy…" : "Hủy export"}
              </button>
              <p className={HELPER}>
                {canCancel ? "Chỉ hủy run đang pending, running hoặc verifying." : "Chỉ có thể hủy khi run còn đang hoạt động."}
              </p>
            </div>
            <div className="flex min-w-[9rem] max-w-full flex-col items-start gap-1">
              <button
                type="button"
                onClick={onRetry}
                disabled={!canRetry || actionBusy !== null}
                className={`min-h-9 rounded px-3 py-1.5 text-xs font-medium ${canRetry && actionBusy === null ? "bg-indigo-600 text-white hover:bg-indigo-500" : "cursor-not-allowed bg-gray-700 text-gray-400"}`}
                data-testid="export-retry"
              >
                {actionBusy === "retry" ? "Đang retry…" : "Retry export"}
              </button>
              <p className={HELPER}>
                {canRetry ? "Chỉ retry run failed hoặc cancelled; backend sẽ trả về run_id mới." : "Chỉ retry sau khi run failed hoặc cancelled."}
              </p>
            </div>
          </div>

          <div className="mt-4 min-w-0">
            <p className="text-xs font-medium text-gray-300">Chunks từ backend</p>
            <div className="mt-2 min-w-0 overflow-hidden rounded border border-gray-800">
              <table className="w-full table-fixed text-left text-[11px] text-gray-300">
                <thead className="bg-gray-800 text-gray-400">
                  <tr>
                    <th className="w-[22%] px-2 py-1.5 font-medium">Chunk</th>
                    <th className="w-[30%] px-2 py-1.5 font-medium">State</th>
                    <th className="w-[24%] px-2 py-1.5 font-medium">Verified</th>
                    <th className="w-[24%] px-2 py-1.5 font-medium">Attempt</th>
                  </tr>
                </thead>
                <tbody>
                  {data.chunks.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="break-words px-2 py-2 text-gray-500">Backend chưa trả về chunk.</td>
                    </tr>
                  ) : (
                    data.chunks.map((chunk) => (
                      <tr key={`${chunk.chunk_index}-${chunk.attempt}`} className="border-t border-gray-800">
                        <td className="break-all px-2 py-1.5 font-mono">{chunk.chunk_index}</td>
                        <td className="break-words px-2 py-1.5">{chunkStateLabel(chunk.state)}</td>
                        <td className="break-words px-2 py-1.5">{chunk.verified === 1 ? "Có" : "Chưa"}</td>
                        <td className="break-words px-2 py-1.5">{chunk.attempt}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <p className={HELPER}>Bảng chỉ hiển thị record chunk và attempt do status API trả về.</p>
          </div>

          <dl className="mt-4 grid min-w-0 grid-cols-1 gap-2 text-[11px] text-gray-400 sm:grid-cols-2">
            <div className="min-w-0 rounded bg-gray-800 px-3 py-2">
              <dt>Plan</dt>
              <dd className="break-all font-mono text-gray-300">{shortId(data.plan_id)} · {shortId(data.plan_hash)}</dd>
            </div>
            <div className="min-w-0 rounded bg-gray-800 px-3 py-2">
              <dt>Project / video</dt>
              <dd className="break-all font-mono text-gray-300">{data.project_id} / {data.video_item_id}</dd>
            </div>
          </dl>
        </>
      )}
    </section>
  );
}
