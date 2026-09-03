"use client";

/**
 * S11-T04D — Review Queue list (blocker-first, warnings collapsible).
 *
 * Purely presentational over the REAL backend payloads: the parent page
 * fetches severity=blocker (default filter) + severity=warning (collapsed
 * count), and hands the rows over.  Rows are real buttons (keyboard
 * complete), severity is icon+text (G3), every action carries Vietnamese
 * helper text under it, and a running correction's RecomputeStateData is
 * rendered as a NON-blocking progress strip on the row (role="status") —
 * the row click/navigation is never disabled by a background job.
 */

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import type { QcItemData } from "@/lib/api";
import {
  QueueEmpty,
  QueueError,
  QueueLoading,
  Refresher,
  SeverityBadge,
} from "./ReviewQueueStates";

/** Category → Vietnamese label (UI copy, stable like preflightErrors). */
export const QC_REASON_LABELS: Record<string, string> = {
  trajectory_drift: "Lệch quỹ đạo",
  cut_drift: "Lệch thời điểm cắt",
  contact_break: "Mất tiếp xúc",
  z_order_error: "Sai thứ tự lớp (z-order)",
  silhouette_clipping: "Silhouette bị cắt",
  identity_drift: "Nhận diện đối tượng lệch",
  edge_halo: "Viền sáng quanh đối tượng",
  temporal_flicker: "Nhấp nháy theo thời gian",
  audio_missing: "Thiếu âm thanh",
  av_sync_drift: "Âm thanh lệch hình",
};

export function qcReasonLabel(code: string): string {
  return QC_REASON_LABELS[code] ?? code.replace(/_/g, " ");
}

const STATUS_LABELS: Record<string, string> = {
  open: "Đang mở",
  acknowledged: "Đã ghi nhận",
  resolved: "Đã xử lý",
  dismissed: "Đã bỏ qua",
};

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export interface ReviewQueueListProps {
  projectId: string;
  /** severity=blocker rows (the default queue filter). */
  blockers: QcItemData[];
  /** severity=warning rows (hidden behind the collapsible count). */
  warnings: QcItemData[];
  selectedId: string | null;
  loading: boolean;
  error: string | null;
  lastUpdated: string | null;
  refreshing: boolean;
  /** itemId → live recompute outcome (RecomputeStateData) — never blocks nav. */
  progress: Record<string, { status: string; progress: number | null }>;
  onSelect: (itemId: string) => void;
  onRetry: () => void;
  onRefresh: () => void;
}

function Row({
  item,
  selected,
  progress,
  onSelect,
}: {
  item: QcItemData;
  selected: boolean;
  progress: ReviewQueueListProps["progress"][string] | undefined;
  onSelect: (itemId: string) => void;
}) {
  const active =
    progress && ["pending", "queued", "running", "cancelling"].includes(progress.status);
  return (
    <div className={`border-b border-zinc-800/80 last:border-b-0 ${selected ? "bg-indigo-500/10" : "hover:bg-zinc-900/60"}`}>
      <button
        type="button"
        data-testid={`qc-row-${item.id}`}
        data-severity={item.severity}
        aria-pressed={selected}
        onClick={() => onSelect(item.id)}
        className="flex min-h-12 w-full items-center gap-3 px-4 py-3 text-left"
      >
        <SeverityBadge severity={item.severity} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-zinc-100">
            {qcReasonLabel(item.reason_code)}
          </span>
          <span className="block truncate text-[11px] text-gray-400">
            {item.detector} · độ chắc {Math.round(item.confidence * 100)}% ·{" "}
            {statusLabel(item.status)}
          </span>
        </span>
        {active ? (
          <span
            data-testid={`row-progress-${item.id}`}
            role="status"
            className="flex shrink-0 items-center gap-1.5 text-[11px] text-indigo-300"
          >
            <Loader2 aria-hidden="true" size={13} className="animate-spin" />
            {Math.round((progress.progress ?? 0) * 100)}%
          </span>
        ) : (
          <ChevronRight aria-hidden="true" size={16} className="shrink-0 text-zinc-500" />
        )}
      </button>
      <p className="px-4 pb-2 -mt-1 text-[11px] text-gray-400" aria-hidden="true">
        Chọn để xem chi tiết + vị trí lỗi + correction.
      </p>
    </div>
  );
}

export function ReviewQueueList({
  projectId,
  blockers,
  warnings,
  selectedId,
  loading,
  error,
  lastUpdated,
  refreshing,
  progress,
  onSelect,
  onRetry,
  onRefresh,
}: ReviewQueueListProps) {
  const [warningsOpen, setWarningsOpen] = useState(false);
  const warningRows = useMemo(
    () => (warningsOpen ? warnings : []),
    [warningsOpen, warnings],
  );

  if (loading) return <QueueLoading />;
  if (error) return <QueueError message={error} onRetry={onRetry} />;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h2 className="text-lg font-semibold text-zinc-100">
            Hàng đợi QC ({blockers.length + warnings.length})
          </h2>
          <p className="text-[11px] text-gray-400">
            Issue chặn (blocker) hiện trước; cảnh báo được gộp lại.
          </p>
        </div>
        <Refresher lastUpdated={lastUpdated} onRefresh={onRefresh} busy={refreshing} />
      </div>

      <div data-testid="qc-queue" className="rounded-xl border border-zinc-800 bg-zinc-900/40">
        {blockers.length === 0 && warnings.length === 0 ? (
          <QueueEmpty projectId={projectId} />
        ) : (
          <>
            {blockers.map((item) => (
              <Row
                key={item.id}
                item={item}
                selected={selectedId === item.id}
                progress={progress[item.id]}
                onSelect={onSelect}
              />
            ))}

            {/* Warnings — collapsible count by default (non-blocking). */}
            <div className="border-t border-zinc-800/80">
              <button
                type="button"
                data-testid="warnings-toggle"
                aria-expanded={warningsOpen}
                onClick={() => setWarningsOpen((v) => !v)}
                className="flex min-h-10 w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-zinc-300 transition hover:bg-zinc-900/60"
              >
                {warningsOpen ? (
                  <ChevronDown aria-hidden="true" size={15} />
                ) : (
                  <ChevronRight aria-hidden="true" size={15} />
                )}
                {warningsOpen
                  ? `Ẩn cảnh báo (${warnings.length})`
                  : `Xem ${warnings.length} cảnh báo`}
              </button>
              <p className="px-4 pb-2 -mt-1 text-[11px] text-gray-400" aria-hidden="true">
                Cảnh báo không chặn — mở để xem danh sách.
              </p>
              {warningRows.map((item) => (
                <Row
                  key={item.id}
                  item={item}
                  selected={selectedId === item.id}
                  progress={progress[item.id]}
                  onSelect={onSelect}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}