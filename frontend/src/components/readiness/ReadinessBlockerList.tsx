"use client";

/**
 * S11-T05B — Readiness blocker list (WS-07 full detail rows).
 *
 * Purely presentational over the REAL T05A payload: every row renders
 * icon + code + structured location + reason_vi + action_vi.  When the
 * navigation action is `navigate` with a structured frame anchor the row
 * carries the same G13 deep link the T04D review detail uses (gallery at
 * the failing frame/role); an `explain` action renders code + reason with
 * NO dead link (Decision E).
 *
 * There is deliberately NO dismiss/accept/manual "đánh dấu đã sửa" control
 * anywhere: blockers clear ONLY through the backend WS-07 auto-recheck
 * (Decision G — zero accepted-exception controls).
 */

import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import type { ReadinessBlockerData } from "@/lib/api";
import { qcReasonLabel } from "@/components/review/ReviewQueueList";

/** Structured location → honest Vietnamese one-liner (never invented). */
export function formatBlockerLocation(blocker: ReadinessBlockerData): string {
  const loc = blocker.location;
  const parts: string[] = [];
  if (loc.scene_id !== null && loc.scene_id !== undefined) parts.push(`Cảnh ${loc.scene_id}`);
  if (loc.frame_index !== null && loc.frame_index !== undefined) parts.push(`Khung ${loc.frame_index}`);
  if (loc.timecode_ms !== null && loc.timecode_ms !== undefined) {
    parts.push(`${(loc.timecode_ms / 1000).toFixed(1)} giây`);
  }
  if (loc.object_role_id) parts.push(`Vai trò ${loc.object_role_id.slice(0, 8)}`);
  if (loc.segment_row_id) parts.push(`Phân đoạn ${loc.segment_row_id.slice(0, 8)}`);
  if (loc.segment_logical_id) parts.push(`Phân đoạn ${loc.segment_logical_id.slice(0, 8)}`);
  return parts.length > 0 ? parts.join(" · ") : "Vị trí: —";
}

export interface ReadinessBlockerListProps {
  projectId: string;
  blockers: ReadinessBlockerData[];
}

export function ReadinessBlockerList({ projectId, blockers }: ReadinessBlockerListProps) {
  if (blockers.length === 0) return null;

  return (
    <ul data-testid="readiness-blockers" className="space-y-2">
      {blockers.map((blocker) => {
        const href =
          blocker.action.kind === "navigate" &&
          blocker.location.frame_index !== null &&
          blocker.location.frame_index !== undefined
            ? `/object-gallery?project=${encodeURIComponent(projectId)}&video=${encodeURIComponent(blocker.video_item_id)}&frame=${blocker.location.frame_index}${
                blocker.location.object_role_id
                  ? `&role=${encodeURIComponent(blocker.location.object_role_id)}`
                  : ""
              }`
            : null;
        return (
          <li
            key={blocker.qc_item_id}
            data-testid={`blocker-row-${blocker.qc_item_id}`}
            data-code={blocker.code}
            className="rounded-lg border border-red-500/20 bg-red-500/5 p-3 sm:p-4"
          >
            <div className="flex items-start gap-2.5">
              <span className="mt-0.5 flex min-h-7 shrink-0 items-center gap-1.5 rounded-full border border-red-500/30 bg-red-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-red-300">
                <AlertTriangle aria-hidden="true" size={13} />
                Chặn
              </span>
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="text-sm font-semibold text-zinc-100">
                    {qcReasonLabel(blocker.code)}
                  </span>
                  <span className="font-mono text-[11px] text-zinc-400">{blocker.code}</span>
                </div>
                <p data-testid={`blocker-location-${blocker.qc_item_id}`} className="text-[11px] text-gray-400">
                  Vị trí: {formatBlockerLocation(blocker)}
                </p>
                <p className="text-xs leading-relaxed text-zinc-300">{blocker.reason_vi}</p>
                <div className="flex flex-col items-start gap-1 pt-1">
                  {href ? (
                    <>
                      <p className="text-xs text-zinc-300">{blocker.action_vi}</p>
                      <Link
                        href={href}
                        data-testid={`blocker-action-${blocker.qc_item_id}`}
                        className="inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium text-indigo-300 transition hover:bg-zinc-800"
                      >
                        Mở vị trí lỗi →
                      </Link>
                      <p className="text-[11px] text-gray-400">
                        Mở vị trí lỗi ở thư viện đối tượng — không đánh dấu gì cả.
                      </p>
                    </>
                  ) : (
                    <p
                      data-testid={`blocker-explain-${blocker.qc_item_id}`}
                      className="text-[11px] text-gray-400"
                    >
                      {blocker.action_vi}
                      {blocker.action.code ? (
                        <span className="font-mono text-zinc-500"> ({blocker.action.code})</span>
                      ) : null}
                    </p>
                  )}
                </div>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}