"use client";

/**
 * Role SUMMARY card for the paginated gallery list (S08-T04-C1, finding E #7).
 *
 * Renders ONLY the summary fields (name/kind/status/counts/current media
 * thumbnail) — the heavy occurrence detail rows are fetched lazily on
 * expand (useRoleDetail -> RoleCard). NEVER eager-renders occurrence-heavy
 * roles in one request; the roles list is paginated (limit/offset).
 */

import { AlertTriangle, CheckCircle2, ChevronDown, Layers, Trash2 } from "lucide-react";
import type { ObjectRole, ObjectRoleKind } from "@/lib/api";
import { roleMediaContentUrl } from "@/lib/api";
import {
  formatConfidence,
  isLowConfidence,
  isRemovalOnlyKind,
  kindLabel,
  shortId,
  summarizeConfidence,
} from "./galleryUtils";

export const ROLE_STATUS_LABELS: Record<string, string> = {
  suggested: "Đề xuất",
  confirmed: "Đã xác nhận",
  superseded: "Đã thay thế",
};

export interface RoleSummaryCardProps {
  role: ObjectRole;
  reviewThreshold: number | null;
  /** Backend-owned removal-only kinds (S08-A01). */
  removalOnlyKinds: ReadonlySet<ObjectRoleKind>;
  expanded: boolean;
  onExpand: (role: ObjectRole) => void;
}

export function RoleSummaryCard({ role, reviewThreshold, removalOnlyKinds, expanded, onExpand }: RoleSummaryCardProps) {
  const summary = summarizeConfidence(role.occurrences);
  const low = reviewThreshold !== null && isLowConfidence(summary.min, reviewThreshold);
  const superseded = role.status === "superseded";
  const sceneCount = new Set(role.occurrences.map((o) => o.scene_id)).size;
  const thumbnail = role.media.find((m) => m.purpose === "thumbnail") ?? role.media[0];
  const removalOnly = isRemovalOnlyKind(role.kind, removalOnlyKinds);
  // Node summary media preview is the REAL bytes via the contained endpoint.

  return (
    <article
      aria-label={`Vai trò ${role.name}`}
      className={`overflow-hidden rounded-xl border bg-[var(--surface-900)] ${
        expanded ? "border-[var(--primary-500)]" : "border-[var(--surface-800)]"
      }`}
    >
      <button
        type="button"
        onClick={() => onExpand(role)}
        aria-expanded={expanded}
        aria-label={`Xem chi tiết vai trò ${role.name}`}
        className="flex w-full items-center gap-3 p-3 text-left transition-colors hover:bg-[var(--surface-850)]"
      >
        {thumbnail ? (
          <span className="h-14 w-14 shrink-0 overflow-hidden rounded-md border border-[var(--surface-700)] bg-black/30">
            {/* Real byte preview (contained endpoint) — decoded dimensions
                asserted in E2E (naturalWidth/naturalHeight). */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={roleMediaContentUrl(thumbnail)}
              alt={`Ảnh mẫu của ${role.name}`}
              loading="lazy"
              className="h-full w-full object-contain"
            />
          </span>
        ) : (
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-md border border-[var(--surface-700)] bg-black/20 text-[10px] text-[var(--text-faint)]">
            {superseded ? "—" : "no media"}
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="truncate font-display text-sm font-semibold text-[var(--text-primary)]">
              {role.name}
            </span>
            <span className="rounded-full bg-[var(--surface-800)] px-1.5 py-0.5 text-[10px] text-[var(--text-muted)]">
              {kindLabel(role.kind)}
            </span>
            {removalOnly && (
              <span
                data-testid="removal-only-badge"
                className="inline-flex items-center gap-0.5 rounded-full bg-[var(--danger)]/15 px-1.5 py-0.5 text-[10px] font-semibold text-[var(--danger)]"
              >
                <Trash2 aria-hidden="true" size={10} />
                Chỉ loại bỏ (lớp nguồn)
              </span>
            )}
            {role.status === "confirmed" ? (
              <span className="inline-flex items-center gap-0.5 rounded-full bg-[var(--success-strong)]/20 px-1.5 py-0.5 text-[10px] font-medium text-[var(--success)]">
                <CheckCircle2 aria-hidden="true" size={11} />
                {ROLE_STATUS_LABELS.confirmed}
              </span>
            ) : superseded ? (
              <span className="rounded-full bg-[var(--surface-800)] px-1.5 py-0.5 text-[10px] text-[var(--text-faint)]">
                {ROLE_STATUS_LABELS.superseded}
              </span>
            ) : (
              <span className="rounded-full bg-[var(--surface-800)] px-1.5 py-0.5 text-[10px] text-[var(--accent-300)]">
                {ROLE_STATUS_LABELS.suggested}
              </span>
            )}
            {low && !superseded && (
              <span className="inline-flex items-center gap-0.5 rounded-full bg-[var(--warning)]/15 px-1.5 py-0.5 text-[10px] font-medium text-[var(--warning)]">
                <AlertTriangle aria-hidden="true" size={11} />
                Độ tin cậy thấp
              </span>
            )}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
            <span className="inline-flex items-center gap-1">
              <Layers aria-hidden="true" size={11} />
              {role.occurrences.length} khung · {sceneCount} cảnh
            </span>
            <span>tin cậy {formatConfidence(summary.average)}</span>
            <span className="font-mono text-[10px] text-[var(--text-faint)]">
              rev {role.revision} · {shortId(role.id)}
            </span>
          </span>
        </span>
        <ChevronDown
          aria-hidden="true"
          size={16}
          className={`shrink-0 text-[var(--text-muted)] transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </button>
    </article>
  );
}
