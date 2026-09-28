"use client";

/**
 * S10-T04B — ApplyProgress
 *
 * Renders backend-truth progress: chunk histogram, current chunk pointer,
 * derived progress percent, attempt + frame_count.  No synthetic 100%.
 * Dark theme. Every button carries VN helper text below.
 */

import type { ApplyStatus } from "./useApplyStatus";
import { ApplyShotReview } from "./ApplyShotReview";

const HELPER = "text-[11px] leading-snug text-gray-400";

interface ApplyProgressProps {
  data: ApplyStatus | null;
  progress: number | null;
  currentChunk: ApplyStatus["chunks"][number] | null;
  isPolling: boolean;
  onRefresh?: () => void;
}

function stateColor(state: string): string {
  switch (state) {
    case "completed":
      return "bg-emerald-500";
    case "running":
      return "bg-indigo-500 animate-pulse";
    case "failed":
      return "bg-red-500";
    case "skipped":
      return "bg-gray-500";
    default:
      return "bg-gray-700";
  }
}

function stateLabel(state: string): string {
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

export function ApplyProgress({ data, progress, currentChunk, isPolling, onRefresh }: ApplyProgressProps) {
  if (!data) {
    return (
      <div className="rounded border border-gray-700 bg-gray-900/40 p-4" data-testid="apply-progress-empty">
        <p className="text-sm text-gray-400">Chưa có tiến trình Apply nào — hãy bắt đầu một lần Apply mới.</p>
        <p className={HELPER}>Tiến trình sẽ hiển thị khi backend trả về dữ liệu cho run_id hiện tại.</p>
      </div>
    );
  }

  return (
    <section className="rounded border border-gray-700 bg-gray-900/40 p-4" data-testid="apply-progress" aria-label="Tiến trình Full Apply">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-100">Tiến trình Full Apply</h3>
          <p className={HELPER}>Số liệu lấy trực tiếp từ backend — không tính giả.</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-300" data-testid="apply-status">
            Trạng thái: <span className="font-medium">{data.status}</span>
          </span>
          <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-300" data-testid="apply-attempt">
            Lần thử: {data.attempt}
          </span>
          {onRefresh && (
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={onRefresh}
                className="rounded bg-gray-800 px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700"
                data-testid="apply-refresh"
              >
                Làm mới
              </button>
              <p className={HELPER}>Tải lại trạng thái mới nhất từ backend.</p>
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">
            Tiến độ: <span className="font-medium text-gray-200" data-testid="apply-progress-pct">{progress ?? 0}%</span>
            {isPolling && <span className="ml-2 text-[11px] text-indigo-400">đang cập nhật…</span>}
          </span>
          <span className="text-xs text-gray-400" data-testid="apply-frame-count">
            {data.frame_count} frames · {data.chunks.length} chunks
          </span>
        </div>
        <div
          className="h-2 w-full overflow-hidden rounded bg-gray-800"
          role="progressbar"
          aria-valuenow={progress ?? 0}
          aria-valuemin={0}
          aria-valuemax={100}
          data-testid="apply-progress-bar"
        >
          <div className="h-full bg-indigo-600 transition-all" style={{ width: `${progress ?? 0}%` }} />
        </div>
      </div>

      {currentChunk && (
        <div className="mt-3 rounded bg-gray-800 px-3 py-2" data-testid="apply-current-chunk">
          <p className="text-xs text-gray-300">
            Chunk hiện tại: <span className="font-mono">{currentChunk.shot_id}</span> · frames {currentChunk.core_start_frame}–{currentChunk.core_end_frame} ·{" "}
            <span className="rounded bg-gray-700 px-1.5 py-0.5 text-[11px]">{stateLabel(currentChunk.state)}</span>
            {currentChunk.layer_id && <span className="ml-1 font-mono text-[11px]">layer {currentChunk.layer_id}</span>}
          </p>
          <p className={HELPER}>Chunk đang xử lý hoặc tiếp theo sẽ chạy — cập nhật từ backend mỗi {isPolling ? "1.5 giây" : "khi làm mới"}.</p>
        </div>
      )}

      <div className="mt-3" data-testid="apply-chunks">
        <p className="text-xs font-medium text-gray-300">Chi tiết chunk (theo backend)</p>
        <p className={HELPER}>Màu xanh = hoàn tất, tím = đang chạy, xám = chờ, đỏ = thất bại.</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {data.chunks.map((c) => (
            <span
              key={c.id}
              className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] text-white ${stateColor(c.state)}`}
              title={`${c.shot_id} ${c.core_start_frame}-${c.core_end_frame} — ${c.state}`}
              data-testid={`apply-chunk-${c.chunk_index}`}
            >
              <span className="font-mono">
                {c.shot_id}:{c.chunk_index}
              </span>
              <span>{stateLabel(c.state)}</span>
            </span>
          ))}
        </div>
      </div>

      <p className={`mt-3 ${HELPER}`} data-testid="apply-plan-hash">
        Plan: <span className="font-mono">{data.plan_hash.slice(0, 12)}…</span> · plan_id {data.plan_id.slice(0, 8)}…
      </p>

      <ApplyShotReview data={data} />
    </section>
  );
}
