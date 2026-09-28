"use client";

/**
 * MF-END-24 — ShotList.
 *
 * One row per SHOT: real frame range, backend state, attempt, verified flag,
 * the publication/artifact refs that already exist (view refs) and a scoped
 * retry control.  The retry button only issues ONE intent per click (the
 * caller's latch dedupes) and is disabled while the run is still running.
 */

import type { ShotOutputRef, ShotSummary } from "./shotReviewLogic";

const HELPER = "text-[11px] leading-snug text-gray-400";

export interface ShotListProps {
  shots: ShotSummary[];
  outputRefs: Record<string, ShotOutputRef[]>;
  canRetryShot: boolean;
  busyShotId?: string | null;
  onRetryShot: (shotId: string) => void;
  onSelectShot?: (shotId: string) => void;
  activeShotId?: string | null;
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

function stateBadge(state: string): string {
  switch (state) {
    case "completed":
      return "bg-emerald-900/60 text-emerald-200";
    case "running":
      return "bg-indigo-900/60 text-indigo-200";
    case "failed":
      return "bg-red-900/60 text-red-200";
    case "skipped":
      return "bg-gray-700 text-gray-300";
    default:
      return "bg-gray-800 text-gray-300";
  }
}

export function ShotList({
  shots,
  outputRefs,
  canRetryShot,
  busyShotId,
  onRetryShot,
  onSelectShot,
  activeShotId,
}: ShotListProps) {
  if (shots.length === 0) {
    return (
      <section className="rounded border border-gray-700 bg-gray-900/40 p-4" data-testid="shot-review-shots-empty">
        <h3 className="text-sm font-semibold text-gray-100">Danh sách shot</h3>
        <p className="mt-1 text-xs text-gray-400">
          Run chưa có chunk/shot nào — dữ liệu sẽ hiện khi backend tạo kế hoạch chunk cho run.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded border border-gray-700 bg-gray-900/40 p-4" data-testid="shot-review-shots">
      <div>
        <h3 className="text-sm font-semibold text-gray-100">Danh sách shot &amp; tiến độ</h3>
        <p className={HELPER}>
          Mỗi dòng là một shot thật của run; số liệu lấy từ chunk state của backend, không đếm giả.
        </p>
      </div>
      <ul className="mt-3 space-y-2">
        {shots.map((shot) => {
          const refs = outputRefs[shot.shot_id] ?? [];
          return (
            <li
              key={shot.shot_id}
              className={`rounded bg-gray-800 px-3 py-2 ${activeShotId === shot.shot_id ? "ring-1 ring-indigo-400" : ""}`}
              data-testid={`shot-review-shot-${shot.shot_id}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2 text-xs text-gray-200">
                  <button
                    type="button"
                    onClick={() => onSelectShot?.(shot.shot_id)}
                    className="font-mono text-gray-100 underline-offset-2 hover:underline"
                    data-testid={`shot-review-shot-select-${shot.shot_id}`}
                  >
                    {shot.shot_id}
                  </button>
                  <span className={`rounded px-1.5 py-0.5 text-[11px] ${stateBadge(shot.state)}`}>{stateLabel(shot.state)}</span>
                  <span>
                    frames <span className="font-mono">{shot.start_frame}–{shot.end_frame}</span>
                  </span>
                  <span>
                    {shot.completed}/{shot.chunk_count} chunk
                  </span>
                  <span>lần thử {shot.attempt}</span>
                  {shot.verified && <span className="text-emerald-300">đã xác minh</span>}
                </div>
                <div className="flex flex-col items-start gap-1">
                  <button
                    type="button"
                    onClick={() => onRetryShot(shot.shot_id)}
                    disabled={!canRetryShot || busyShotId === shot.shot_id}
                    className="rounded bg-gray-700 px-2 py-1 text-[11px] text-gray-100 hover:bg-gray-600 disabled:cursor-not-allowed disabled:text-gray-500"
                    data-testid={`shot-review-retry-shot-${shot.shot_id}`}
                  >
                    {busyShotId === shot.shot_id ? "Đang gửi…" : "Thử lại shot này"}
                  </button>
                  <p className={HELPER}>
                    Chỉ chạy lại shot này; các shot đạt giữ nguyên output/hash.
                  </p>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-gray-400">
                {shot.progress_pct !== null && (
                  <span data-testid={`shot-review-shot-progress-${shot.shot_id}`}>tiến độ {shot.progress_pct}%</span>
                )}
                {refs.length > 0 ? (
                  refs.map((ref) => (
                    <span key={ref.publication_id} className="rounded bg-gray-900 px-2 py-0.5 font-mono">
                      {ref.artifact_id.slice(0, 12)}… · {ref.content_hash.slice(0, 10)}… · {ref.frame_count} frames
                    </span>
                  ))
                ) : (
                  <span className="text-amber-300">chưa có output đã publish cho shot này</span>
                )}
                {shot.role_ids.length > 0 && <span>role: {shot.role_ids.join(", ")}</span>}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
