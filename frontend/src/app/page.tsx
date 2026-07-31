"use client";

import { useState } from "react";
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
  const screen = useProjectStore((s) => s.screen);
  const projectId = useProjectStore((s) => s.projectId);

  const { data: gpuInfo } = useQuery({
    queryKey: ["gpu-info"],
    queryFn: () => api.getGpuInfo(),
    staleTime: 60000,
  });

  const showFloatingStitchBtn = screen !== "start" && !!projectId;

  return (
    <>
      {/* Channel Dashboard Button + GPU Indicator */}
      <div className="fixed top-4 right-4 z-40 flex items-center gap-3">
        {gpuInfo && (
          <div className="flex items-center gap-1.5 text-xs">
            <span className={`w-2 h-2 rounded-full ${gpuInfo.has_nvenc ? 'bg-green-500' : 'bg-gray-500'}`} />
            <span className="text-gray-400">
              {gpuInfo.has_nvenc ? `GPU: ${gpuInfo.gpu_name}` : 'CPU Encode'}
            </span>
          </div>
        )}
        <button
          onClick={() => setShowDashboard(true)}
          className="px-3 py-1.5 text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-full"
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
        onResumeProject={(pid) => {
          const store = useProjectStore.getState();
          store.setProjectId(pid);
          api.getProject(pid).then((proj) => {
            store.setProject(proj);
            store.setScreen("selection");
          });
        }}
      />
    </>
  );
}
