"use client";

/**
 * S11-T05B — Project readiness panel (T05A aggregate, GET-only).
 *
 * Reflects the REAL /api/v2/projects/{id}/readiness payload for all three
 * fail-closed states:
 *   - ready   : "Không còn blocker nào." + evidence pass (số lượt kiểm tra
 *               QC đã chạy — completed current runs from videos[]);
 *   - blocked : header + blocker count + full WS-07 blocker list;
 *   - not_run : honest "Chưa chạy kiểm tra" (amber/zinc — NEVER green) with
 *               per-video check-state detail.
 *
 * Decision G: there is NO accepted-exception button and NO manual
 * "đánh dấu đã sửa" control anywhere — blockers clear ONLY through the
 * backend WS-07 auto-recheck; the panel exposes nothing but read + refresh
 * (a long running recheck shows "Đang xử lý lại…" as a status strip and
 * NEVER blocks navigation).
 */

import { useCallback, useEffect, useState } from "react";
import { AlertOctagon, AlertTriangle, CheckCircle2, Hourglass, Loader2, RefreshCw } from "lucide-react";
import {
  api,
  type ReadinessResponseData,
  type ReadinessStatus,
  type ReadinessVideoData,
} from "@/lib/api";
import { ReadinessBlockerList } from "./ReadinessBlockerList";

/** Aggregate status → Vietnamese label (stable UI copy). */
export const READINESS_STATUS_LABELS: Record<ReadinessStatus, string> = {
  ready: "Sẵn sàng",
  blocked: "Bị chặn",
  not_run: "Chưa chạy kiểm tra",
};

/** Per-video check-run state → Vietnamese label (honest, closed map). */
export const RUN_STATE_LABELS: Record<string, string> = {
  never_run: "Chưa chạy kiểm tra",
  queued: "Đang chờ kiểm tra",
  running: "Đang xử lý lại…",
  failed: "Kiểm tra thất bại",
  stale: "Đã cũ — cần chạy lại",
  completed: "Đã chạy kiểm tra",
};

export function runStateLabel(runState: string): string {
  return RUN_STATE_LABELS[runState] ?? runState.replace(/_/g, " ");
}

type PanelPhase = "loading" | "error" | "ready";

interface PanelState {
  phase: PanelPhase;
  error: string | null;
  data: ReadinessResponseData | null;
}

function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

export function ReadinessPanel({ projectId }: { projectId: string }) {
  const [state, setState] = useState<PanelState>({
    phase: "loading",
    error: null,
    data: null,
  });
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const load = useCallback(
    async (mode: "initial" | "refresh" = "initial") => {
      if (mode === "refresh") setRefreshing(true);
      else setState({ phase: "loading", error: null, data: null });
      try {
        const data = await api.getReadiness(projectId);
        setState({ phase: "ready", error: null, data });
        setLastUpdated(
          new Date().toLocaleTimeString("vi-VN", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }),
        );
      } catch (err) {
        setState({
          phase: "error",
          error: err instanceof Error ? err.message : "Lỗi kết nối máy chủ.",
          data: null,
        });
      } finally {
        setRefreshing(false);
      }
    },
    [projectId],
  );

  useEffect(() => {
    queueMicrotask(() => {
      void load("initial");
    });
  }, [load]);

  if (state.phase === "loading") {
    return (
      <section
        data-testid="readiness-panel"
        aria-label="Mức sẵn sàng kiểm tra chất lượng"
        className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 sm:p-5"
      >
        <div data-testid="readiness-loading" role="status" aria-busy="true" className="space-y-2">
          <div className="h-5 w-48 animate-pulse rounded bg-zinc-800" />
          <div className="h-14 animate-pulse rounded-lg bg-zinc-900" />
          <p className="text-[11px] text-gray-400">Đang tính toán mức sẵn sàng từ máy chủ…</p>
        </div>
      </section>
    );
  }

  if (state.phase === "error" || !state.data) {
    return (
      <section
        data-testid="readiness-panel"
        aria-label="Mức sẵn sàng kiểm tra chất lượng"
        className="rounded-xl border border-red-500/30 bg-zinc-900/60 p-4 sm:p-5"
      >
        <div data-testid="readiness-error" role="alert" className="space-y-3">
          <div className="flex items-center gap-2 text-sm text-red-300">
            <AlertOctagon aria-hidden="true" size={16} />
            <span className="font-medium">Chưa tính được readiness</span>
          </div>
          <p className="text-xs text-zinc-400 break-all">{state.error}</p>
          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              data-testid="readiness-retry"
              onClick={() => void load("initial")}
              className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-zinc-800 px-4 py-2 text-sm text-zinc-200 transition hover:bg-zinc-700"
            >
              <RefreshCw aria-hidden="true" size={15} />
              Thử lại
            </button>
            <p className="text-[11px] text-gray-400">Tính lại mức sẵn sàng từ máy chủ.</p>
          </div>
        </div>
      </section>
    );
  }

  const data = state.data;
  const longRunning = data.videos.some((v) => v.run_state === "running" || v.run_state === "queued");
  const completedRuns = data.videos.filter((v) => v.run_state === "completed").length;

  const statusTone =
    data.status === "ready"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
      : data.status === "blocked"
        ? "border-red-500/30 bg-red-500/10 text-red-300"
        : "border-amber-500/30 bg-amber-500/10 text-amber-300";

  const StatusIcon =
    data.status === "ready" ? CheckCircle2 : data.status === "blocked" ? AlertTriangle : Hourglass;

  return (
    <section
      data-testid="readiness-panel"
      data-status={data.status}
      aria-label="Mức sẵn sàng kiểm tra chất lượng"
      className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">
              Mức sẵn sàng
            </h3>
            <span
              data-testid="readiness-status"
              data-status={data.status}
              role="status"
              className={`inline-flex min-h-7 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${statusTone}`}
            >
              <StatusIcon aria-hidden="true" size={13} />
              {READINESS_STATUS_LABELS[data.status]}
            </span>
          </div>

          {data.status === "ready" && (
            <div data-testid="readiness-ready">
              <p className="text-sm text-zinc-100">Không còn blocker nào.</p>
              <p
                data-testid="readiness-ready-evidence"
                role="status"
                className="text-[11px] text-gray-400"
              >
                Tất cả {completedRuns}/{data.videos.length} video đã chạy kiểm tra QC · chính sách v
                {data.policy_version}
              </p>
            </div>
          )}

          {data.status === "blocked" && (
            <div>
              <p className="text-sm text-zinc-100">
                Dự án đang bị chặn bởi {data.blockers.length} blocker — chưa thể xác nhận sẵn sàng.
              </p>
              {data.warning_count > 0 && (
                <p className="text-[11px] text-gray-400">
                  Ngoài ra còn {data.warning_count} cảnh báo (không chặn tiến độ).
                </p>
              )}
            </div>
          )}

          {data.status === "not_run" && (
            <div data-testid="readiness-notrun">
              <p className="text-sm text-zinc-100">
                Chưa chạy kiểm tra — một số video chưa có lượt kiểm tra QC hoàn tất.
              </p>
              <p className="text-[11px] text-gray-400">
                Mức sẵn sàng chỉ được tính sau khi mọi video đã chạy kiểm tra xong.
              </p>
            </div>
          )}
        </div>

        <div className="flex flex-col items-start gap-1">
          <button
            type="button"
            data-testid="readiness-refresh"
            onClick={() => void load("refresh")}
            disabled={refreshing}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-200 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {refreshing ? (
              <Loader2 aria-hidden="true" size={14} className="animate-spin" />
            ) : (
              <RefreshCw aria-hidden="true" size={14} />
            )}
            Làm mới
          </button>
          <span data-testid="readiness-refresher-status" role="status" className="text-[11px] text-gray-400">
            Cập nhật: {lastUpdated ?? "—"}
          </span>
          <p className="text-[11px] text-gray-400">
            Tải lại trạng thái sau khi kiểm tra lại (recheck) chạy xong.
          </p>
        </div>
      </div>

      {longRunning && (
        <p
          data-testid="readiness-longjob"
          role="status"
          className="mt-3 flex items-center gap-1.5 rounded-lg border border-indigo-500/20 bg-indigo-500/10 px-3 py-2 text-[11px] text-indigo-300"
        >
          <Loader2 aria-hidden="true" size={13} className="animate-spin" />
          Đang xử lý lại… — kiểm tra đang chạy lại; mọi thao tác điều hướng vẫn bình thường.
        </p>
      )}

      {data.blockers.length > 0 && (
        <div className="mt-3">
          <ReadinessBlockerList projectId={projectId} blockers={data.blockers} />
        </div>
      )}

      {/* Per-video check-run evidence (honest, fail-closed detail). */}
      <div className="mt-3 flex flex-wrap gap-2" data-testid="readiness-videos">
        {data.videos.map((v: ReadinessVideoData) => (
          <span
            key={v.video_item_id}
            data-testid={`readiness-video-${v.video_item_id}`}
            data-run-state={v.run_state}
            title={v.check_state_detail}
            className="inline-flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-900 px-2.5 py-1 text-[11px] text-zinc-300"
          >
            <span className="font-mono">{shortId(v.video_item_id)}</span>
            <span aria-hidden="true">·</span>
            <span>{runStateLabel(v.run_state)}</span>
            {v.blockers > 0 && (
              <span className="rounded bg-red-500/10 px-1.5 text-red-300">{v.blockers} blocker</span>
            )}
          </span>
        ))}
      </div>

      <p className="mt-3 text-[11px] text-gray-400">
        Trạng thái chỉ thay đổi khi kiểm tra lại (recheck) xác nhận — không có nút đánh dấu thủ công.
      </p>
    </section>
  );
}