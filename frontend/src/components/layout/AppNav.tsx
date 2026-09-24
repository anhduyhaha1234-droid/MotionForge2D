"use client";

import { Suspense } from "react";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Boxes, Clapperboard, FolderOpen, Home, Play, Radio, Sparkles, UploadCloud, Users } from "lucide-react";
import { api } from "@/lib/api";

const items = [
  { href: "/", label: "Trang chủ", icon: Home },
  { href: "/import-analyze", label: "Nhập & Phân tích", icon: UploadCloud },
  { href: "/channels", label: "Kênh", icon: Radio },
  { href: "/projects", label: "Dự án", icon: FolderOpen },
  { href: "/object-gallery", label: "Thư viện đối tượng", icon: Boxes },
  { href: "/characters", label: "Thư viện nhân vật", icon: Users },
  { href: "/demo-compare", label: "So sánh demo", icon: Sparkles },
  { href: "/apply", label: "Áp dụng (Full Apply)", icon: Play },
  { href: "/export", label: "Xuất 4K", icon: Clapperboard },
];

/**
 * Next.js App Router prerenders every static route under (app)/, and AppShell
 * renders AppNav from the SHARED layout. A bare useSearchParams() call here
 * therefore aborts the prerender of the FIRST route with
 *   useSearchParams() should be wrapped in a suspense boundary at page "/apply"
 * (missing-suspense-with-csr-bailout), so the production build emits no app
 * at all. Fix shape: the hook is isolated in <AppNavWithQueryParams/> and
 * wrapped in a Suspense boundary whose fallback is the SAME sidebar markup
 * with no deep-link params - which is exactly the correct prerendered shell,
 * because a static prerender has no query string. usePathname()/useQuery()
 * are prerender-safe and keep their server-rendered output.
 */
export function AppNav() {
  return (
    <Suspense fallback={<AppNavSidebar projectId={null} videoItemId={null} />}>
      <AppNavWithQueryParams />
    </Suspense>
  );
}

function AppNavWithQueryParams() {
  const params = useSearchParams();
  return <AppNavSidebar projectId={params.get("project")} videoItemId={params.get("video")} />;
}

function AppNavSidebar({ projectId, videoItemId }: { projectId: string | null; videoItemId: string | null }) {
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
            const targetHref = href === "/export" && projectId && videoItemId
              ? `/export?project=${encodeURIComponent(projectId)}&video=${encodeURIComponent(videoItemId)}`
              : href;
            const active = href === "/" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
            return <li key={href}><Link href={targetHref} aria-current={active ? "page" : undefined} className={`flex min-h-10 items-center gap-3 rounded-lg border-l-2 px-3 text-sm transition-colors ${active ? "border-[var(--primary-500)] bg-[color-mix(in_srgb,var(--primary-600)_15%,transparent)] text-[var(--primary-300)]" : "border-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-800)] hover:text-[var(--text-primary)]"}`}><Icon aria-hidden="true" size={18} />{label}</Link></li>;
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
