"use client";

import { useState } from "react";
import { useProjectStore } from "@/stores/project";
import { ScreenA } from "@/components/ScreenA";
import { ScreenB } from "@/components/ScreenB";
import { ScreenC } from "@/components/ScreenC";
import { ScreenD } from "@/components/ScreenD";
import { ScreenE } from "@/components/ScreenE";
import { AssemblyModal } from "@/components/AssemblyModal";

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
  const screen = useProjectStore((s) => s.screen);
  const projectId = useProjectStore((s) => s.projectId);

  const showFloatingStitchBtn = screen !== "start" && !!projectId;

  return (
    <>
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
    </>
  );
}
