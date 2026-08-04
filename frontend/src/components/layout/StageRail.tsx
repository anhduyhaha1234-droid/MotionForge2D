"use client";

import type { LucideIcon } from "lucide-react";
import { Check, CheckCircle2, Clapperboard, Layers, Play, Upload, Wand2 } from "lucide-react";

export interface Stage { key: string; label: string; icon: LucideIcon }
const defaultStages: Stage[] = [
  { key: "import", label: "Nhập video", icon: Upload }, { key: "objects", label: "Đối tượng", icon: Layers },
  { key: "demo", label: "Demo thay thế", icon: Wand2 }, { key: "apply", label: "Áp dụng", icon: Play },
  { key: "review", label: "Kiểm tra", icon: CheckCircle2 }, { key: "export", label: "Xuất 4K", icon: Clapperboard },
];

export function StageRail({ currentIndex = 0, stages = defaultStages, dense = false }: { currentIndex?: number; stages?: Stage[]; dense?: boolean }) {
  return <ol role="list" aria-label="Tiến trình sản xuất" className="flex min-h-14 items-center overflow-x-auto border-b border-[var(--surface-800)] bg-[var(--surface-850)] px-4 py-2">
    {stages.map(({ key, label, icon: Icon }, index) => { const done = index < currentIndex; const current = index === currentIndex; return <li key={key} aria-current={current ? "step" : undefined} className="flex min-w-0 flex-1 items-center last:flex-none">
      <div className={`flex min-h-11 shrink-0 items-center gap-2 rounded-full px-3 text-xs font-medium ${current ? "bg-[var(--primary-700)] text-white shadow-glow ring-1 ring-[var(--primary-300)]" : done ? "text-[var(--text-primary)]" : "text-[var(--text-faint)]"}`}>{done ? <Check size={17} className="text-[var(--primary-300)]" /> : <Icon size={17} />} {!dense && <span className="whitespace-nowrap">{label}</span>}</div>
      {index < stages.length - 1 && <span aria-hidden="true" className={`mx-2 h-px min-w-4 flex-1 ${done ? "bg-[var(--primary-500)]" : "bg-[var(--surface-700)]"}`} />}
    </li>; })}
  </ol>;
}
