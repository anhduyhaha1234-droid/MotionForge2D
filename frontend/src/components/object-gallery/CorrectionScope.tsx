"use client";

/**
 * S08-T05 impacted-scope report + recompute tracking UI.
 *
 * `CorrectionScope` renders the pre-confirmation scope report (the exact
 * affected sets the backend computed — shown INSIDE the confirmation dialog,
 * BEFORE the mutation is confirmed).  `RecomputeStrip` renders the durable
 * RECOMPUTE_OBJECTS job progress and the HONEST terminal outcome (success /
 * failure with retry / cancel) — the mutation itself is already applied and
 * never undone; only the derived state recompute is retryable.
 */

import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Sparkles } from "lucide-react";
import type { CorrectionImpactData, RecomputeState } from "@/lib/api";

export const RECOMPUTE_STATUS_LABELS: Record<string, string> = {
  pending: "Đang chờ",
  queued: "Đang chờ",
  running: "Đang tính lại",
  cancelling: "Đang hủy",
  cancelled: "Đã hủy",
  completed: "Hoàn tất",
  failed: "Thất bại",
};

export function CorrectionScope({
  impact,
  loading,
  error,
  roleNames,
}: {
  impact: CorrectionImpactData | null;
  loading: boolean;
  error: string | null;
  roleNames: Map<string, string>;
}) {
  if (loading) {
    return (
      <p
        className="flex items-center gap-2 text-xs text-[var(--text-muted)]"
        data-testid="correction-scope-loading"
        aria-busy="true"
      >
        <Loader2 aria-hidden="true" size={13} className="animate-spin" />
        Đang tính phạm vi ảnh hưởng từ máy chủ…
      </p>
    );
  }
  if (error) {
    return (
      <p className="text-xs text-[var(--danger)]" role="alert">
        Không tính được phạm vi ảnh hưởng: {error}
      </p>
    );
  }
  if (!impact) return null;
  const nameOf = (id: string) => roleNames.get(id) ?? id.slice(0, 8);
  return (
    <div
      className="space-y-2 rounded-lg border border-[var(--surface-700)] bg-black/20 p-3"
      data-testid="correction-scope"
    >
      <p className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-secondary)]">
        <Sparkles aria-hidden="true" size={13} className="text-[var(--accent-300)]" />
        Phạm vi ảnh hưởng (tính toán lại có chọn lọc)
      </p>
      <ul className="space-y-1 text-xs text-[var(--text-secondary)]">
        <li data-testid={`scope-${impact.correction_type}-role-count`}>
          Vai trò bị ảnh hưởng ({impact.affected_role_ids.length}):{" "}
          <strong className="text-[var(--text-primary)]">
            {impact.affected_role_ids.map(nameOf).join(", ") || "—"}
          </strong>
        </li>
        <li data-testid={`scope-${impact.correction_type}-occurrence-count`}>
          Bằng chứng sẽ được chuyển/chỉnh: {impact.affected_occurrence_ids.length}
        </li>
        <li data-testid={`scope-${impact.correction_type}-suggestion-count`}>
          Gợi ý gộp đang chờ sẽ bị thay thế: {impact.invalidated_suggestion_ids.length}
        </li>
        <li data-testid={`scope-${impact.correction_type}-artifact-count`}>
          Ảnh mẫu/mặt nạ cần tạo lại: {impact.artifact_role_ids.length} vai trò
        </li>
      </ul>
      <p className="text-[11px] leading-snug text-[var(--text-muted)]">
        Mọi dữ liệu ngoài phạm vi trên giữ nguyên từng byte/hash. Trạng thái cũ được lưu lại
        để truy vết — không bao giờ bị xóa.
      </p>
      {!impact.recompute_needed ? (
        <p
          data-testid={`recompute-not-needed-${impact.correction_type}`}
          className="flex items-center gap-1 text-[11px] text-[var(--success)]"
        >
          <CheckCircle2 aria-hidden="true" size={12} />
          Không cần công việc tính toán lại nền — chỉnh sửa áp dụng ngay.
        </p>
      ) : (
        <p className="text-[11px] text-[var(--text-muted)]">
          Sau khi xác nhận, hệ thống chạy một công việc nền để tạo lại đúng phần dẫn xuất bị
          ảnh hưởng (gợi ý gộp + ảnh mẫu/mặt nạ).
        </p>
      )}
    </div>
  );
}

export function RecomputeStrip({
  correctionId,
  recompute,
  onRetry,
  busy,
}: {
  correctionId: string;
  recompute: RecomputeState | null;
  onRetry: () => void;
  busy: boolean;
}) {
  if (!recompute || !recompute.recompute_needed) return null;
  const status = recompute.status ?? "pending";
  const active = ["pending", "queued", "running", "cancelling"].includes(status);
  const progress = Math.max(0, Math.min(100, Math.round(recompute.progress ?? 0)));
  return (
    <section
      aria-label="Tính toán lại sau chỉnh sửa"
      data-testid="recompute-strip"
      data-state={status}
      className="rounded-xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-4"
      role="status"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="inline-flex items-center gap-2 font-display text-sm font-semibold text-[var(--text-primary)]">
          <Sparkles aria-hidden="true" size={16} className="text-[var(--accent-300)]" />
          Tính toán lại sau chỉnh sửa
          <span className="rounded-full bg-[var(--surface-800)] px-2 py-0.5 text-[11px] font-medium text-[var(--accent-300)]">
            {RECOMPUTE_STATUS_LABELS[status] ?? status}
          </span>
        </h2>
        {recompute.job_id && (
          <p className="font-mono text-[10px] text-[var(--text-faint)]">
            {recompute.job_id.slice(0, 8)} · chỉnh sửa {correctionId.slice(0, 8)}
          </p>
        )}
      </div>
      {active && (
        <div className="mt-3">
          <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--surface-800)]">
            <div
              className="h-full rounded-full bg-[var(--accent-400)] transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            {progress}% · đang tạo lại gợi ý/ảnh mẫu cho đúng các vai trò bị ảnh hưởng
          </p>
        </div>
      )}
      {status === "completed" && (
        <p className="mt-2 flex items-center gap-1.5 text-[11px] text-[var(--success)]">
          <CheckCircle2 aria-hidden="true" size={13} />
          Đã tạo lại đúng phần dẫn xuất của các vai trò bị ảnh hưởng; dữ liệu khác giữ nguyên.
        </p>
      )}
      {status === "failed" && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p className="flex items-start gap-1.5 text-xs text-[var(--danger)]" role="alert">
            <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
            <span>
              Không thể tính toán lại: {recompute.error ?? "lỗi không xác định"}. Chỉnh sửa
              của bạn ĐÃ được áp dụng — chỉ phần dẫn xuất (gợi ý/ảnh mẫu) còn thiếu.
            </span>
          </p>
          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              onClick={onRetry}
              disabled={busy}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--surface-800)] px-3 text-xs font-semibold text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-700)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw aria-hidden="true" size={13} />
              {busy ? "Đang thử lại…" : "Thử lại tính toán"}
            </button>
            <p className="text-[11px] text-[var(--text-muted)]">
              Tạo công việc kế nhiệm (không làm lại chỉnh sửa, không tạo bản sao).
            </p>
          </div>
        </div>
      )}
      {status === "cancelled" && (
        <p className="mt-2 text-[11px] text-[var(--text-muted)]">
          Công việc tính toán lại đã bị hủy — chỉnh sửa vẫn được giữ; bạn có thể thử lại bất
          cứ lúc nào.
        </p>
      )}
    </section>
  );
}
