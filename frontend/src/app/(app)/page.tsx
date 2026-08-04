"use client";

import { LegacyWorkspace } from "@/components/LegacyWorkspace";
import { StageRail } from "@/components/layout/StageRail";
import { useProjectStore } from "@/stores/project";

const stageMap = { start: 0, selection: 1, replacement: 2, review: 4, render: 5 } as const;
export default function HomePage() {
  const projectId = useProjectStore((s) => s.projectId);
  const screen = useProjectStore((s) => s.screen);
  return <div className="flex min-h-full flex-col">{projectId && <StageRail currentIndex={stageMap[screen]} />}<LegacyWorkspace /></div>;
}
