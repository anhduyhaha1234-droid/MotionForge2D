"use client";

/**
 * MF-END-24 — DemoShotReview (integration into the demo compare flow).
 *
 * The demo surface gains the before/after SYNC viewer for a published loop:
 * the source fixture and the rendered result are kept frame-locked over the
 * real time map, with play + frame-step controls.  URLs are the backend's
 * own (source-content route + published content_url); nothing is invented.
 * QC markers stay on the project review surface (ApplyShotReview) because
 * qc-items are project-scoped — this card links there instead of faking rows.
 */

import { BeforeAfterSync } from "@/features/shot-review/BeforeAfterSync";

const HELPER = "text-[11px] leading-snug text-gray-400";

export interface DemoShotReviewProps {
  loopId: string;
  originalUrl: string;
  resultUrl: string;
  fpsNum?: number | null;
  fpsDen?: number | null;
  frameCount?: number;
}

export function DemoShotReview({
  loopId,
  originalUrl,
  resultUrl,
  fpsNum = null,
  fpsDen = null,
  frameCount = 0,
}: DemoShotReviewProps) {
  return (
    <div className="mt-3" data-testid={`demo-shot-review-${loopId}`}>
      <BeforeAfterSync
        beforeUrl={originalUrl}
        afterUrl={resultUrl}
        fpsNum={fpsNum}
        fpsDen={fpsDen}
        frameCount={frameCount}
        label={`Xem lại shot demo — loop ${loopId}`}
      />
      <p className={`mt-1 ${HELPER}`}>
        QC marker theo frame/role nằm ở mục “Xem lại shot” của luồng Apply (QC item gắn theo project), không hiển thị trùng ở đây.
      </p>
    </div>
  );
}
