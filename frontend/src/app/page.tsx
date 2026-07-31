"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useProjectStore } from "@/stores/project";
import { ScreenA } from "@/components/ScreenA";
import { ScreenB } from "@/components/ScreenB";
import { ScreenC } from "@/components/ScreenC";
import { ScreenD } from "@/components/ScreenD";
import { ScreenE } from "@/components/ScreenE";
import { AssemblyModal } from "@/components/AssemblyModal";
import { ChannelDashboard } from "@/components/ChannelDashboard";
import { api } from "@/lib/api";
import { useProjectRehydration, saveSession, clearSession } from "@/hooks/useProjectRehydration";

function ScreenRouter() {
  const screen = useProjectStore((s) => s.screen);

  switch (screen) {
    case "start":
      return <ScreenA />;
    case "selection":
      return <ScreenB />;
    case "review":
      return <ScreenC />;
    case "replacement":
      return <ScreenD />;
    case "render":
      return <ScreenE />;
    default:
      return <ScreenA />;
  }
}

export default function Home() {
  const [showAssembly, setShowAssembly] = useState(false);
  const [showDashboard, setShowDashboard] = useState(false);
  const { isRehydrating } = useProjectRehydration();

  const screen = useProjectStore((s) => s.screen);
  const projectId = useProjectStore((s) => s.projectId);
  const activeSceneId = useProjectStore((s) => s.activeSceneId);
  const setProject = useProjectStore((s) => s.setProject);
  const setScenes = useProjectStore((s) => s.setScenes);
  const resetAll = useProjectStore((s) => s.resetAll);

  // Auto-restore project state on F5 browser refresh
  useEffect(() => {
    async function restoreProjectState() {
      if (!projectId) return;

      try {
        const projData = await api.getProject(projectId);
        setProject(projData);

        const sceneDetails = await api.getSceneDetails(projectId);
        setScenes(sceneDetails);
      } catch (err) {
        console.warn("Failed to auto-restore project:", err);
        resetAll();
      }
    }

    restoreProjectState();
  }, [projectId, setProject, setScenes, resetAll]);

  // Save session whenever projectId/screen/activeSceneId changes
  useEffect(() => {
    if (projectId) {
      saveSession({
        projectId,
        screen,
        activeSceneId: activeSceneId ?? null,
      });
    } else {
      clearSession();
    }
  }, [projectId, screen, activeSceneId]);

  const { data: gpuInfo } = useQuery({
    queryKey: ["gpu-info"],
    queryFn: () => api.getGpuInfo(),
    staleTime: 60000,
  });

  const showFloatingStitchBtn = screen !== "start" && !!projectId;

  if (isRehydrating) {
    return (
      <div className="min-h-screen bg-[#0b0f19] flex items-center justify-center">
        <div className="text-gray-400 text-sm animate-pulse">
          Đang khôi phục phiên làm việc...
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Channel Dashboard Button + GPU Indicator + New Project Button */}
      <div className="fixed top-4 right-4 z-40 flex items-center gap-3">
        {gpuInfo && (
          <div className="flex items-center gap-1.5 text-xs bg-slate-900/80 backdrop-blur-md px-3 py-1.5 rounded-full border border-slate-800">
            <span className={`w-2 h-2 rounded-full ${gpuInfo.has_nvenc ? 'bg-emerald-400' : 'bg-slate-400'}`} />
            <span className="text-slate-300 font-medium">
              {gpuInfo.has_nvenc ? `⚡ GPU: ${gpuInfo.gpu_name}` : '💻 CPU Mode'}
            </span>
          </div>
        )}

        {projectId && (
          <button
            onClick={() => resetAll()}
            className="px-3 py-1.5 text-xs bg-purple-950/60 hover:bg-purple-900 border border-purple-800/40 text-purple-200 rounded-full font-medium transition-all"
          >
            ✨ Tạo Dự Án Mới
          </button>
        )}

        <button
          onClick={() => setShowDashboard(true)}
          className="px-4 py-1.5 text-xs bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-200 rounded-full font-semibold transition-all shadow-lg"
        >
          📁 Quản Lý Kênh & Dự Án
        </button>
      </div>

      <ScreenRouter />

      {showFloatingStitchBtn && (
        <button
          onClick={() => setShowAssembly(true)}
          title="Bấm để xem danh sách cảnh đã duyệt và tiến hành ghép video thành phẩm"
          className="fixed bottom-6 right-6 px-5 py-3 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-bold rounded-full text-xs shadow-2xl shadow-purple-600/40 transition-all z-40 border border-purple-400/30 flex items-center gap-2"
        >
          🎬 Ghép Video Hoàn Chỉnh
        </button>
      )}

      <AssemblyModal
        isOpen={showAssembly}
        onClose={() => setShowAssembly(false)}
      />

      <ChannelDashboard
        isOpen={showDashboard}
        onClose={() => setShowDashboard(false)}
        onResumeProject={async (pid) => {
          const store = useProjectStore.getState();
          store.setProjectId(pid);
          try {
            const proj = await api.getProject(pid);
            store.setProject(proj);
            const scenes = await api.getSceneDetails(pid);
            store.setScenes(scenes);
            store.setScreen("selection");
          } catch (e) {
            console.error(e);
          }
        }}
      />
    </>
  );
}
