"use client";

/**
 * MF-END-24 — ApplyShotReview (integration into the Apply flow).
 *
 * Mounts the shared ShotReviewPanel for the CURRENT Full Apply run so the
 * apply page gains: per-shot progress, before/after sync, QC markers and a
 * scoped retry — all reading the same run the progress card already shows.
 */

import { ShotReviewPanel } from "@/features/shot-review/ShotReviewPanel";
import type { ApplyStatus } from "./useApplyStatus";

export interface ApplyShotReviewProps {
  data: ApplyStatus;
}

export function ApplyShotReview({ data }: ApplyShotReviewProps) {
  return (
    <div className="mt-4" data-testid="apply-shot-review">
      <ShotReviewPanel
        runId={data.run_id}
        projectId={data.project_id}
        videoItemId={data.video_item_id}
      />
    </div>
  );
}
