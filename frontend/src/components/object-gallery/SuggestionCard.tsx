"use client";

/**
 * Grouping suggestion card (S08-T04).
 *
 * A T03 suggestion is REVIEWABLE evidence: it always starts `pending`,
 * carries real confidence/reasons/provenance and is NEVER auto-confirmed.
 * The card shows the pair of roles, the confidence bar (low-confidence
 * suggestions flagged), the reasons with Vietnamese labels, and two
 * explicit actions — merge (opens the merge dialog) or dismiss (explicit
 * rejection with its own confirmation).
 */

import { AlertTriangle, GitMerge, Sparkles, XCircle } from "lucide-react";
import type { GroupingSuggestion, ObjectRole } from "@/lib/api";
import {
  ConfidenceBar,
  formatConfidence,
  reasonLabel,
  shortId,
} from "./galleryUtils";

export interface SuggestionCardProps {
  suggestion: GroupingSuggestion;
  /** The two candidate roles of this suggestion (stable role ids). */
  roles: ObjectRole[];
  /** Backend grouping-policy review threshold (nullable until policy loads). */
  reviewThreshold: number | null;
  /** Backend policy calibration version shown as provenance. */
  calibrationVersion: string;
  onMerge: (suggestion: GroupingSuggestion) => void;
  onDismiss: (suggestion: GroupingSuggestion) => void;
  busy?: boolean;
}

export function SuggestionCard({
  suggestion,
  roles,
  reviewThreshold,
  calibrationVersion,
  onMerge,
  onDismiss,
  busy,
}: SuggestionCardProps) {
  const low = reviewThreshold !== null && suggestion.confidence < reviewThreshold;
  const roleById = new Map(roles.map((r) => [r.id, r]));
  const pair = suggestion.role_ids.map((id) => roleById.get(id)?.name ?? shortId(id));

  return (
    <article
      aria-label={`Gợi ý gộp ${pair.join(" và ")}`}
      className={`rounded-xl border bg-[var(--surface-900)] p-4 ${
        low ? "border-[var(--warning)]/40" : "border-[var(--surface-800)]"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--surface-800)] px-2.5 py-1 text-xs font-medium text-[var(--accent-300)]">
            <Sparkles aria-hidden="true" size={12} />
            Gợi ý gộp
          </span>
          {low && (
            <span className="inline-flex items-center gap-1 rounded-full bg-[var(--warning)]/15 px-2.5 py-1 text-xs font-medium text-[var(--warning)]">
              <AlertTriangle aria-hidden="true" size={12} />
              Độ tin cậy thấp — không tự động xác nhận
            </span>
          )}
        </div>
        <p className="font-mono text-[10px] text-[var(--text-faint)]">
          {suggestion.algorithm} v{suggestion.algorithm_version} · hiệu chuẩn{" "}
          {calibrationVersion} · {shortId(suggestion.id)}
        </p>
      </div>

      <p className="mt-2 text-sm text-[var(--text-primary)]">
        <strong>{pair[0] ?? "?"}</strong>
        <span className="mx-1.5 text-[var(--text-muted)]">+</span>
        <strong>{pair[1] ?? "?"}</strong>
        <span className="ml-2 text-[11px] text-[var(--text-muted)]">
          (cùng một đối tượng qua các cảnh?)
        </span>
      </p>

      <div className="mt-2">
        <div className="mb-1 flex items-center justify-between text-[11px] text-[var(--text-muted)]">
          <span>Độ tin cậy gợi ý</span>
          <span>{formatConfidence(suggestion.confidence)}</span>
        </div>
        <ConfidenceBar value={suggestion.confidence} threshold={reviewThreshold} />
      </div>

      {suggestion.reasons.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {suggestion.reasons.map((reason) => (
            <li key={reason} className="text-xs text-[var(--text-secondary)]">
              {reasonLabel(reason)}
              <span className="ml-1 font-mono text-[10px] text-[var(--text-faint)]">({reason})</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap items-start gap-x-4 gap-y-3 border-t border-[var(--surface-800)] pt-3">
        <div className="flex flex-col items-start gap-1">
          <button
            type="button"
            onClick={() => onMerge(suggestion)}
            disabled={busy}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--primary-600)] px-3 text-xs font-semibold text-white transition-colors hover:bg-[var(--primary-700)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <GitMerge aria-hidden="true" size={14} />
            Gộp hai vai trò
          </button>
          <p className="text-[11px] leading-snug text-[var(--text-muted)]">
            Mở hộp thoại xác nhận — bạn chọn vai trò đích trước khi gộp.
          </p>
        </div>
        <div className="flex flex-col items-start gap-1">
          <button
            type="button"
            onClick={() => onDismiss(suggestion)}
            disabled={busy}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[var(--surface-800)] px-3 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-700)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <XCircle aria-hidden="true" size={14} />
            Từ chối gợi ý
          </button>
          <p className="text-[11px] leading-snug text-[var(--text-muted)]">
            Giữ các vai trò riêng biệt; gợi ý chuyển thành đã từ chối.
          </p>
        </div>
      </div>
    </article>
  );
}
