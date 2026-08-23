"use client";

/**
 * Legacy step workspace (S08-H01 correction — finding F, item 4).
 *
 * `?project=<id>` hydration now VALIDATES the durable id against the real
 * backend BEFORE writing the Zustand store, and any failure renders an honest
 * error banner with working retry — the store/localStorage are never the sole
 * truth and an invalid id can never enter the workspace silently.  Sessions
 * saved to localStorage remain a convenience, but every load re-validates
 * identity through `GET /api/projects/{id}` + `GET /api/projects/{id}/scenes`.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useProjectStore } from "@/stores/project";
import { ScreenA } from "@/components/ScreenA";
import { ScreenB } from "@/components/ScreenB";
import { ScreenC } from "@/components/ScreenC";
import { ScreenD } from "@/components/ScreenD";
import { ScreenE } from "@/components/ScreenE";
import { AssemblyModal } from "@/components/AssemblyModal";
import { ChannelDashboard } from "@/components/ChannelDashboard";
import { NavigationHeader } from "@/components/NavigationHeader";
import { api, ApiError } from "@/lib/api";
import { useProjectRehydration, saveSession, clearSession } from "@/hooks/useProjectRehydration";

function ScreenRouter() {
  const screen = useProjectStore((s) => s.screen);
  switch (screen) { case "start": return <ScreenA />; case "selection": return <ScreenB />; case "review": return <ScreenC />; case "replacement": return <ScreenD />; case "render": return <ScreenE />; default: return <ScreenA />; }
}

/**
 * Validate identity from the backend and ONLY THEN commit it to the store.
 * Throws so the caller can render an honest error (never swallowed).
 */
async function resumeProject(pid: string): Promise<void> {
  const project = await api.getProject(pid); // 404/network → throws, store untouched
  const scenes = await api.getSceneDetails(pid);
  const store = useProjectStore.getState();
  store.setProjectId(pid);
  store.setProject(project);
  store.setScenes(scenes);
  store.setScreen("selection");
}

function hydrateErrorMessage(err: unknown, pid: string): string {
  if (err instanceof ApiError && err.status === 404) {
    return `Không tìm thấy dự án "${pid}" trên máy chủ (đã xóa hoặc sai mã).`;
  }
  if (err instanceof ApiError) {
    return `Lỗi ${err.status} khi đọc dự án "${pid}": ${err.detailText()}`;
  }
  return `Không thể kết nối máy chủ để mở dự án "${pid}". Hãy thử lại sau.`;
}

export function LegacyWorkspace() {
  const [showAssembly, setShowAssembly] = useState(false);
  const [showDashboard, setShowDashboard] = useState(false);
  const { isRehydrating } = useProjectRehydration();
  const screen = useProjectStore((s) => s.screen);
  const projectId = useProjectStore((s) => s.projectId);
  const activeSceneId = useProjectStore((s) => s.activeSceneId);
  const setProject = useProjectStore((s) => s.setProject);
  const setScenes = useProjectStore((s) => s.setScenes);
  const resetAll = useProjectStore((s) => s.resetAll);

  const [hydrateError, setHydrateError] = useState<string | null>(null);
  const [hydrateTarget, setHydrateTarget] = useState<string | null>(null);
  // Track the last ?project= we tried so "✨ Tạo Dự Án Mới" (resetAll →
  // projectId null) never silently re-resumes the same URL project.
  const handledUrlRef = useRef<string | null>(null);

  useEffect(() => {
    const requestedId = new URLSearchParams(window.location.search).get("project");
    if (!requestedId) return;
    if (handledUrlRef.current === requestedId) return;
    handledUrlRef.current = requestedId;
    setHydrateTarget(requestedId);
    setHydrateError(null);
    resumeProject(requestedId).catch((err: unknown) => {
      setHydrateError(hydrateErrorMessage(err, requestedId));
    });
  }, [projectId]);

  useEffect(() => {
    async function restoreProjectState() {
      if (!projectId) return;
      try {
        setProject(await api.getProject(projectId));
        setScenes(await api.getSceneDetails(projectId));
      } catch (error) {
        console.warn("Failed to auto-restore project:", error);
        resetAll();
      }
    }
    void restoreProjectState();
  }, [projectId, setProject, setScenes, resetAll]);

  useEffect(() => { if (projectId) saveSession({ projectId, screen, activeSceneId: activeSceneId ?? null }); else clearSession(); }, [projectId, screen, activeSceneId]);

  if (isRehydrating) return <div className="flex min-h-[60vh] items-center justify-center bg-[#0b0f19]"><div className="animate-pulse text-sm text-gray-400">Đang khôi phục phiên làm việc...</div></div>;

  return <>
    {/* Honest hydrate error — retry + escape hatch, never silent */}
    {hydrateError && (
      <div
        role="alert"
        className="mx-auto mt-4 w-[min(92vw,48rem)] rounded-xl border border-red-500/40 bg-red-950/40 p-4"
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-red-300">Không thể mở dự án từ địa chỉ</p>
            <p className="mt-1 break-all text-xs text-red-300/80">{hydrateError}</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => {
                if (hydrateTarget) {
                  setHydrateError(null);
                  resumeProject(hydrateTarget).catch((err: unknown) =>
                    setHydrateError(hydrateErrorMessage(err, hydrateTarget)),
                  );
                }
              }}
              className="inline-flex min-h-9 items-center rounded-lg bg-red-700 px-3 text-xs font-semibold text-white hover:bg-red-600"
            >
              🔄 Thử lại
            </button>
            <Link
              href="/projects"
              className="inline-flex min-h-9 items-center rounded-lg border border-gray-700 px-3 text-xs font-medium text-gray-300 hover:bg-gray-800"
            >
              📁 Danh sách dự án
            </Link>
          </div>
        </div>
      </div>
    )}

    <div className="fixed right-4 top-20 z-40 flex items-center gap-3">
      {projectId && <button onClick={resetAll} className="rounded-full border border-purple-800/40 bg-purple-950/60 px-3 py-1.5 text-xs font-medium text-purple-200 transition-all hover:bg-purple-900">✨ Tạo Dự Án Mới</button>}
      <button onClick={() => setShowDashboard(true)} className="rounded-full border border-slate-700 bg-slate-900 px-4 py-1.5 text-xs font-semibold text-slate-200 shadow-lg transition-all hover:bg-slate-800">📁 Quản Lý Kênh & Dự Án</button>
    </div>
    <NavigationHeader onOpenAssembly={() => setShowAssembly(true)} />
    <ScreenRouter />
    <AssemblyModal isOpen={showAssembly} onClose={() => setShowAssembly(false)} />
    <ChannelDashboard isOpen={showDashboard} onClose={() => setShowDashboard(false)} onResumeProject={(pid) => resumeProject(pid).catch((err: unknown) => { window.alert(`Không thể mở dự án: ${hydrateErrorMessage(err, pid)}`); })} />
  </>;
}
