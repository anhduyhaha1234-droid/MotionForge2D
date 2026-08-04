"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { FolderOpen, Home, Radio, Users } from "lucide-react";
import { api } from "@/lib/api";

const items = [
  { href: "/", label: "Trang chủ", icon: Home },
  { href: "/channels", label: "Kênh", icon: Radio },
  { href: "/projects", label: "Dự án", icon: FolderOpen },
  { href: "/characters", label: "Thư viện nhân vật", icon: Users },
];

export function AppNav() {
  const pathname = usePathname();
  const { data: gpu } = useQuery({ queryKey: ["gpu-info"], queryFn: () => api.getGpuInfo(), staleTime: 60_000 });

  return (
    <div className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-[var(--surface-800)] bg-[var(--surface-900)] md:flex">
      <div className="flex items-center gap-3 border-b border-[var(--surface-800)] px-4 py-4">
        <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-[var(--primary-500)] to-[var(--accent-500)] text-sm font-bold text-white shadow-glow">MF</div>
        <div className="min-w-0"><p className="font-display text-sm font-semibold">MotionForge 2D</p><p className="truncate text-xs text-[var(--text-muted)]">Reskin 2D & Xuất 4K</p></div>
      </div>
      <nav aria-label="Điều hướng chính" className="p-3">
        <ul className="space-y-1">
          {items.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
            return <li key={href}><Link href={href} aria-current={active ? "page" : undefined} className={`flex min-h-10 items-center gap-3 rounded-lg border-l-2 px-3 text-sm transition-colors ${active ? "border-[var(--primary-500)] bg-[color-mix(in_srgb,var(--primary-600)_15%,transparent)] text-[var(--primary-300)]" : "border-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-800)] hover:text-[var(--text-primary)]"}`}><Icon aria-hidden="true" size={18} />{label}</Link></li>;
          })}
        </ul>
      </nav>
      <div className="mt-auto space-y-3 border-t border-[var(--surface-800)] p-4">
        {gpu && <div className="flex items-center gap-2 rounded-lg bg-[var(--surface-850)] px-3 py-2 text-xs text-[var(--text-secondary)]"><span className={`size-2 rounded-full ${gpu.has_nvenc ? "bg-[var(--success)]" : "bg-[var(--text-muted)]"}`} /><span className="truncate">{gpu.has_nvenc ? `GPU: ${gpu.gpu_name}` : "CPU Mode"}</span></div>}
        <p className="text-xs text-[var(--text-muted)]">Phiên bản 0.1 · Local-first</p>
      </div>
    </div>
  );
}
