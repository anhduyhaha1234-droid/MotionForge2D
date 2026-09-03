"use client";

/**
 * S11-T04D — Review Queue shared UI states + severity taxonomy.
 *
 * Every async region of the review page renders one of these honest states:
 * loading (role="status"), empty (role="status"), error (role="alert" +
 * retry) and the refresher (last-updated status + refresh action).  The
 * severity presentation is ALWAYS icon + text (never color-only) — G3 in
 * the a11y gate list.
 */

import { AlertTriangle, AlertCircle, Info, Loader2, RefreshCw } from "lucide-react";

export type QcSeverity = "blocker" | "warning" | "info";

/** Vietnam verbatim copy convention (preflightErrors): stable UI labels. */
export const SEVERITY_META: Record<
  QcSeverity,
  { label: string; icon: typeof AlertTriangle }
> = {
  blocker: { label: "Chặn", icon: AlertTriangle },
  warning: { label: "Cảnh báo", icon: AlertCircle },
  info: { label: "Thông tin", icon: Info },
};

export function severityLabel(severity: string): string {
  return (SEVERITY_META[severity as QcSeverity] ?? SEVERITY_META.warning).label;
}

export function severityIcon(severity: string) {
  return (SEVERITY_META[severity as QcSeverity] ?? SEVERITY_META.warning).icon;
}

/** Row/detail severity badge — icon + text, data-severity for tests. */
export function SeverityBadge({
  severity,
  testid = "severity-badge",
}: {
  severity: string;
  testid?: string;
}) {
  const tone =
    severity === "blocker"
      ? "border-red-500/30 bg-red-500/10 text-red-300"
      : severity === "warning"
        ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
        : "border-zinc-600 bg-zinc-800 text-zinc-300";
  return (
    <span
      data-testid={testid}
      data-severity={severity}
      className={`inline-flex min-h-7 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${tone}`}
    >
      {severity === "blocker" ? (
        <AlertTriangle aria-hidden="true" size={13} />
      ) : severity === "warning" ? (
        <AlertCircle aria-hidden="true" size={13} />
      ) : (
        <Info aria-hidden="true" size={13} />
      )}
      {severityLabel(severity)}
    </span>
  );
}

/** Loading skeleton — role="status" so AT users hear the fetch started. */
export function QueueLoading() {
  return (
    <div
      data-testid="queue-loading"
      role="status"
      aria-busy="true"
      aria-label="Đang tải hàng đợi QC từ máy chủ"
      className="space-y-2 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4"
    >
      <div className="h-5 w-40 animate-pulse rounded bg-zinc-800" />
      <div className="h-14 animate-pulse rounded-lg bg-zinc-900" />
      <div className="h-14 animate-pulse rounded-lg bg-zinc-900" />
      <p className="text-[11px] text-gray-400">
        Đang tải danh sách issue từ máy chủ — dữ liệu thật, không có mẫu.
      </p>
    </div>
  );
}

/** Empty queue — role="status" (informative, not an error). */
export function QueueEmpty({ projectId }: { projectId: string }) {
  return (
    <div
      data-testid="queue-empty"
      role="status"
      className="rounded-xl border border-dashed border-zinc-800 p-8 text-center"
    >
      <p className="text-sm text-zinc-300">Không có issue nào cần xem lại trong dự án này.</p>
      <p className="mt-1 text-[11px] text-gray-400">
        Hàng đợi QC của dự án <span className="font-mono">{projectId.slice(0, 8)}</span> đang
        trống — mọi kiểm tra gần nhất đều sạch.
      </p>
    </div>
  );
}

/** Error + retry — role="alert" (the retry is a real refetch). */
export function QueueError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      data-testid="queue-error"
      role="alert"
      className="rounded-xl border border-red-500/30 bg-zinc-900/60 p-6 text-center space-y-3"
    >
      <p className="text-sm text-red-300">Không thể tải hàng đợi QC: {message}</p>
      <div className="flex flex-col items-center gap-1">
        <button
          type="button"
          data-testid="queue-retry"
          onClick={onRetry}
          className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-zinc-800 px-4 py-2 text-sm text-zinc-200 transition hover:bg-zinc-700"
        >
          <RefreshCw aria-hidden="true" size={15} />
          Thử lại
        </button>
        <p className="text-[11px] text-gray-400">Tải lại danh sách issue từ máy chủ.</p>
      </div>
    </div>
  );
}

/** Refresher — last-updated status + reload action. */
export function Refresher({
  lastUpdated,
  onRefresh,
  busy,
}: {
  lastUpdated: string | null;
  onRefresh: () => void;
  busy: boolean;
}) {
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid="refresh-button"
          onClick={onRefresh}
          disabled={busy}
          className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-zinc-200 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? (
            <Loader2 aria-hidden="true" size={14} className="animate-spin" />
          ) : (
            <RefreshCw aria-hidden="true" size={14} />
          )}
          Làm mới
        </button>
        <span
          data-testid="refresher-status"
          role="status"
          className="text-[11px] text-gray-400"
        >
          Cập nhật: {lastUpdated ?? "—"}
        </span>
      </div>
      <p className="text-[11px] text-gray-400">
        Tải lại hàng đợi từ máy chủ sau khi chạy lại kiểm tra.
      </p>
    </div>
  );
}