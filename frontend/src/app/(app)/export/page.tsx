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

import { Suspense, useCallback, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ExportPanel } from "@/components/export/ExportPanel";

function scopedStorageKey(workspaceId: string, projectId: string, videoItemId: string): string {
  return `s12:export:${workspaceId}:${projectId}:${videoItemId}:run`;
}

function readStorage(workspaceId: string, projectId: string, videoItemId: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(scopedStorageKey(workspaceId, projectId, videoItemId));
  } catch {
    return null;
  }
}

function writeStorage(runId: string | null, workspaceId: string, projectId: string, videoItemId: string) {
  if (typeof window === "undefined") return;
  try {
    const key = scopedStorageKey(workspaceId, projectId, videoItemId);
    if (runId) localStorage.setItem(key, runId);
    else localStorage.removeItem(key);
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
  const router = useRouter();

  const projectId = params.get("project") ?? "";
  const videoItemId = params.get("video") ?? "";
  const workspaceId = params.get("workspace") ?? "default";
  const initialRunId = params.get("run") ?? (projectId && videoItemId ? readStorage(workspaceId, projectId, videoItemId) : null);
  const scopeKey = `${workspaceId}:${projectId}:${videoItemId}`;

  useEffect(() => {
    if (initialRunId && projectId && videoItemId) writeStorage(initialRunId, workspaceId, projectId, videoItemId);
  }, [initialRunId, workspaceId, projectId, videoItemId]);

  const updateRunPointer = useCallback((runId: string) => {
    writeStorage(runId, workspaceId, projectId, videoItemId);
    const next = new URLSearchParams(params.toString());
    next.set("project", projectId);
    next.set("video", videoItemId);
    next.set("workspace", workspaceId);
    next.set("run", runId);
    router.replace(`/export?${next.toString()}`, { scroll: false });
  }, [params, router, workspaceId, projectId, videoItemId]);

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
      <ExportPanel key={scopeKey} projectId={projectId} videoItemId={videoItemId} workspaceId={workspaceId} initialRunId={initialRunId} onRunPointerChange={updateRunPointer} />
    </div>
  );
}
