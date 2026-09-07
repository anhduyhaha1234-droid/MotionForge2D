"use client";

/**
 * S12-T05 — /export route (Export UI).
 *
 * Vietnamese Export flow: preflight → submit → poll status →
 * cancel/retry → result/evidence. All business state refetched from the
 * S12 API; localStorage + URL keep only run/project/video pointers so a
 * refresh or restart resumes from durable truth.
 *
 * Dark theme: every button has VN helper text directly below
 * (text-gray-400, 11px+). Responsive: flex-wrap, no overflow at 390px.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ExportPanel } from "@/components/export/ExportPanel";

const STORAGE_RUN_ID = "s12:export:lastRunId";
const STORAGE_PROJECT_ID = "s12:export:lastProjectId";
const STORAGE_VIDEO_ID = "s12:export:lastVideoItemId";

function readStorage(): { runId: string | null; projectId: string | null; videoItemId: string | null } {
  if (typeof window === "undefined") return { runId: null, projectId: null, videoItemId: null };
  try {
    return {
      runId: localStorage.getItem(STORAGE_RUN_ID),
      projectId: localStorage.getItem(STORAGE_PROJECT_ID),
      videoItemId: localStorage.getItem(STORAGE_VIDEO_ID),
    };
  } catch {
    return { runId: null, projectId: null, videoItemId: null };
  }
}

function writeStorage(runId: string | null, projectId: string | null, videoItemId: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (runId) localStorage.setItem(STORAGE_RUN_ID, runId);
    else localStorage.removeItem(STORAGE_RUN_ID);
    if (projectId) localStorage.setItem(STORAGE_PROJECT_ID, projectId);
    else localStorage.removeItem(STORAGE_PROJECT_ID);
    if (videoItemId) localStorage.setItem(STORAGE_VIDEO_ID, videoItemId);
    else localStorage.removeItem(STORAGE_VIDEO_ID);
  } catch {
    // ignore
  }
}

export default function ExportPage() {
  return (
    <Suspense fallback={<div className="min-h-full p-4 sm:p-6" aria-busy="true" />}>
      <ExportRoute />
    </Suspense>
  );
}

function ExportRoute() {
  const params = useSearchParams();
  const [stored] = useState<{ runId: string | null; projectId: string | null; videoItemId: string | null }>(() => readStorage());

  const projectId = params.get("project") ?? stored.projectId ?? "";
  const videoItemId = params.get("video") ?? stored.videoItemId ?? "";
  const workspaceId = params.get("workspace") ?? "default";
  const initialRunId = params.get("run") ?? stored.runId;

  useEffect(() => {
    writeStorage(initialRunId, projectId || null, videoItemId || null);
  }, [initialRunId, projectId, videoItemId]);

  if (!projectId || !videoItemId) {
    return (
      <div className="min-h-full p-4 sm:p-6">
        <h1 data-testid="export-title" className="text-base font-semibold text-gray-100">Export video</h1>
        <p data-testid="export-empty" className="mt-2 text-xs leading-snug text-gray-400">
          Chưa chọn project/video. Mở trang Export từ project (kèm ?project=&amp;video=) hoặc chọn project rồi quay lại.
        </p>
      </div>
    );
  }

  return (
    <div className="min-h-full p-4 sm:p-6">
      <h1 data-testid="export-title" className="sr-only">Export video</h1>
      <ExportPanel projectId={projectId} videoItemId={videoItemId} workspaceId={workspaceId} initialRunId={initialRunId} />
    </div>
  );
}
