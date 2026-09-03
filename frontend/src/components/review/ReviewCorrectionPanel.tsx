"use client";

/**
 * S11-T04D — Two-phase correction dialog for one QC item.
 *
 * Phase 1 (preview): the ImpactData scope report from the REAL
 * POST /corrections/preview is shown BEFORE the confirm button is ever
 * actionable — nothing is mutated without the user seeing the exact
 * affected sets.
 * Phase 2 (confirm): create (pending) → confirm (CAS) through the public
 * S08-T05 route pair; the applied correction + recompute outcome is
 * reported back so the queue row can render the non-blocking progress.
 *
 * Accessibility follows the ConfirmDialog pattern (S08-T04): role=dialog +
 * aria-modal + labelled title, focus moves IN on open, Tab is trapped,
 * Escape closes, and focus RESTORES to the trigger on close.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  Sparkles,
  X,
} from "lucide-react";
import {
  api,
  ApiError,
  type CorrectionImpactData,
  type CorrectionRequestPayload,
  type ObjectCorrection,
  type QcItemData,
} from "@/lib/api";
import { qcReasonLabel } from "./ReviewQueueList";
import { SeverityBadge } from "./ReviewQueueStates";

export interface ReviewCorrectionPanelProps {
  open: boolean;
  item: QcItemData;
  onClose: () => void;
  /** The applied correction (for the parent's non-blocking progress map). */
  onApplied: (correction: ObjectCorrection) => void;
}

type Phase =
  | "previewing"
  | "preview-error"
  | "ready"
  | "confirming"
  | "applied"
  | "applied-error";

function errorText(err: unknown): string {
  if (err instanceof ApiError) return `${err.status}: ${err.detailText()}`;
  return err instanceof Error ? err.message : "Lỗi kết nối máy chủ.";
}

export function ReviewCorrectionPanel({
  open,
  item,
  onClose,
  onApplied,
}: ReviewCorrectionPanelProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const lastFocusedRef = useRef<HTMLElement | null>(null);
  const [phase, setPhase] = useState<Phase>("previewing");
  const [impact, setImpact] = useState<CorrectionImpactData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [correction, setCorrection] = useState<ObjectCorrection | null>(null);
  const requestRef = useRef<CorrectionRequestPayload | null>(null);

  const preview = useCallback(async () => {
    setPhase("previewing");
    setImpact(null);
    setError(null);
    setCorrection(null);
    try {
      // Live role detail only for the generation anchor (T04B bridge mirror).
      const evidence = item.evidence ?? {};
      const roleId = typeof evidence.object_role_id === "string" ? evidence.object_role_id : null;
      let role: { source_generation: string } | null = null;
      if (roleId) {
        try {
          role = await api.getObjectRole(roleId);
        } catch {
          role = null; // preview still runs with generation fallback "1"
        }
      }
      const request = api.buildQcCorrectionRequest(item, role);
      if (!request) {
        setError(
          "Issue không có anchor occurrence có cấu trúc — ngoài phạm vi rerun V1, không tạo correction.",
        );
        setPhase("preview-error");
        return;
      }
      requestRef.current = request;
      const report = await api.previewCorrection(request);
      setImpact(report);
      setPhase("ready");
    } catch (err) {
      setError(errorText(err));
      setPhase("preview-error");
    }
  }, [item]);

  useEffect(() => {
    if (!open) return;
    lastFocusedRef.current = document.activeElement as HTMLElement | null;
    const node = dialogRef.current;
    node?.focus();
    // Preview starts in a microtask — no synchronous setState in the effect.
    queueMicrotask(() => {
      void preview();
    });

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !node) return;
      const focusables = Array.from(
        node.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("disabled"));
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      lastFocusedRef.current?.focus?.();
    };
  }, [open, preview, onClose]);

  if (!open) return null;

  const busy = phase === "previewing" || phase === "confirming";
  const confirmDisabled = busy || phase !== "ready";

  const runConfirm = async () => {
    const request = requestRef.current;
    if (!request || !impact) return;
    setPhase("confirming");
    setError(null);
    try {
      const created = await api.createCorrection(request);
      const applied = await api.confirmCorrection(
        created.correction.id,
        created.correction.revision,
      );
      setCorrection(applied);
      setPhase("applied");
      onApplied(applied);
    } catch (err) {
      setError(errorText(err));
      setPhase("applied-error");
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="presentation"
    >
      <div
        ref={dialogRef}
        data-testid="correction-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="correction-dialog-title"
        tabIndex={-1}
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-zinc-800 bg-zinc-950 p-5 shadow-panel outline-none"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2
              id="correction-dialog-title"
              className="font-display text-base font-semibold text-zinc-100"
            >
              Tạo correction cho issue này
            </h2>
            <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-gray-400">
              <SeverityBadge severity={item.severity} testid="correction-severity" />
              {qcReasonLabel(item.reason_code)}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="Đóng hộp thoại"
            className="flex min-h-10 min-w-10 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-50"
          >
            <X aria-hidden="true" size={16} />
          </button>
        </div>

        <div className="mt-3 space-y-3">
          {phase === "previewing" && (
            <p
              role="status"
              className="flex items-center gap-2 text-sm text-gray-400"
              aria-busy="true"
            >
              <Loader2 aria-hidden="true" size={14} className="animate-spin" />
              Đang tính phạm vi ảnh hưởng từ máy chủ…
            </p>
          )}

          {(phase === "preview-error" || phase === "applied-error") && (
            <div
              data-testid="correction-error"
              role="alert"
              className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300"
            >
              {error}
            </div>
          )}

          {impact && (
            <div
              data-testid="correction-scope"
              className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-900/60 p-3"
            >
              <p className="flex items-center gap-1.5 text-xs font-semibold text-zinc-200">
                <Sparkles aria-hidden="true" size={13} className="text-indigo-300" />
                Phạm vi ảnh hưởng (tính toán lại có chọn lọc)
              </p>
              <ul className="space-y-1 text-xs text-zinc-300">
                <li data-testid="scope-role-count">
                  Vai trò bị ảnh hưởng ({impact.affected_role_ids.length}):{" "}
                  <span className="font-mono text-zinc-100">
                    {impact.affected_role_ids.join(", ") || "—"}
                  </span>
                </li>
                <li>Bằng chứng sẽ được chuyển/chỉnh: {impact.affected_occurrence_ids.length}</li>
                <li>Gợi ý gộp đang chờ sẽ bị thay thế: {impact.invalidated_suggestion_ids.length}</li>
                <li>Ảnh mẫu/mặt nạ cần tạo lại: {impact.artifact_role_ids.length} vai trò</li>
              </ul>
              {impact.recompute_needed ? (
                <p className="text-[11px] leading-snug text-gray-400">
                  Sau khi xác nhận, hệ thống chạy một công việc nền để tạo lại đúng phần dẫn
                  xuất bị ảnh hưởng — tiến độ hiển thị ở hàng đợi, không khóa điều hướng.
                </p>
              ) : (
                <p className="text-[11px] text-emerald-300">
                  <CheckCircle2 aria-hidden="true" size={12} className="mr-1 inline" />
                  Không cần công việc tính toán lại nền — chỉnh sửa áp dụng ngay.
                </p>
              )}
            </div>
          )}

          {phase === "applied" && correction && (
            <div
              data-testid="correction-applied"
              className="flex items-start gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-300"
            >
              <CheckCircle2 aria-hidden="true" size={16} className="mt-0.5 shrink-0" />
              <div>
                <p className="font-semibold">Correction đã được áp dụng.</p>
                <p className="mt-0.5 text-[11px] text-gray-400">
                  Mã correction: <span className="font-mono">{correction.id.slice(0, 8)}</span>
                  {correction.recompute?.job_id
                    ? ` · công việc nền: ${correction.recompute.job_id.slice(0, 8)}`
                    : ""}
                </p>
                <p className="mt-0.5 text-[11px] text-gray-400">
                  Theo dõi tiến độ tại hàng đợi — điều hướng không bị khóa.
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          {phase !== "applied" ? (
            <>
              <div className="flex flex-col items-start gap-1">
                <button
                  type="button"
                  data-testid="correction-cancel"
                  onClick={onClose}
                  disabled={busy}
                  className="min-h-10 rounded-lg border border-zinc-700 bg-zinc-900 px-4 text-sm font-medium text-zinc-300 transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Hủy
                </button>
                <p className="text-[11px] text-gray-400">Đóng hộp thoại, không thay đổi gì.</p>
              </div>
              <div className="flex flex-col items-start gap-1">
                <button
                  type="button"
                  data-testid="correction-confirm"
                  onClick={() => void runConfirm()}
                  disabled={confirmDisabled}
                  className="min-h-10 rounded-lg bg-indigo-600 px-4 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {phase === "confirming" ? "Đang áp dụng…" : "Xác nhận correction"}
                </button>
                <p className="text-[11px] text-gray-400">
                  Áp dụng chỉnh sửa có chọn lọc đúng phạm vi bên trên.
                </p>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                data-testid="correction-close"
                onClick={onClose}
                className="min-h-10 rounded-lg border border-zinc-700 bg-zinc-900 px-4 text-sm font-medium text-zinc-300 transition hover:bg-zinc-800"
              >
                Đóng
              </button>
              <p className="text-[11px] text-gray-400">Đóng và xem tiến độ tại hàng đợi.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}