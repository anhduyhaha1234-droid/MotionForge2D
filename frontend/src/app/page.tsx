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

  return (
    <>
      <ScreenRouter />
      <button
        onClick={() => setShowAssembly(true)}
        className="fixed bottom-4 right-4 px-4 py-2 bg-purple-600
          hover:bg-purple-500 rounded-full font-medium text-sm
          shadow-lg transition-colors z-40"
      >
        🎬 Ghép video
      </button>
      <AssemblyModal isOpen={showAssembly} onClose={() => setShowAssembly(false)} />
    </>
  );
}
