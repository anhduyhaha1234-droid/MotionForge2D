"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, RefreshCw, Users } from "lucide-react";
import { api } from "@/lib/api";

export default function CharactersPage() {
  const query = useQuery({ queryKey: ["character-presets"], queryFn: () => api.listCharacterPresets() });
  return <div className="p-6 lg:p-8"><div className="mb-6"><h2 className="font-display text-2xl font-semibold">Thư viện nhân vật</h2><p className="mt-1 text-sm text-[var(--text-muted)]">Duyệt bộ nhân vật và các tư thế có sẵn từ thư viện sản xuất.</p></div>
    {query.isLoading && <div className="space-y-6">{[1,2].map((n) => <div key={n} className="h-64 animate-pulse rounded-xl bg-[var(--surface-850)]" />)}</div>}
    {query.isError && <div className="rounded-xl border border-[var(--danger)] bg-[var(--surface-900)] p-6 text-center"><AlertCircle className="mx-auto text-[var(--danger)]" /><p className="mt-3 text-[var(--text-secondary)]">Không thể tải thư viện nhân vật.</p><button onClick={() => query.refetch()} className="mx-auto mt-4 flex min-h-10 items-center gap-2 rounded-lg bg-[var(--surface-800)] px-4 text-sm"><RefreshCw size={16} />Thử lại</button></div>}
    {query.data?.characters.length === 0 && <div className="rounded-xl border border-dashed border-[var(--surface-700)] bg-[var(--surface-900)] p-10 text-center"><Users className="mx-auto text-[var(--primary-300)]" /><h3 className="mt-4 font-display text-lg font-semibold">Chưa có nhân vật mẫu</h3><p className="mt-2 text-sm text-[var(--text-muted)]">Thư viện hiện chưa có bộ nhân vật được tạo.</p></div>}
    <div className="space-y-6">{query.data?.characters.map((character) => <section key={character.id} className="rounded-xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-5"><div className="mb-4"><h3 className="font-display text-lg font-semibold">{character.label}</h3><p className="mt-1 font-mono text-xs text-[var(--text-muted)]">{character.id}</p></div><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">{character.poses.map((pose) => <article key={pose.pose} className="rounded-lg border border-[var(--surface-700)] bg-[var(--surface-850)] p-3"><div className="aspect-square overflow-hidden rounded-lg border border-[var(--surface-700)] bg-black/40"><img src={pose.url || api.getCharacterPresetImageUrl(character.id, pose.pose)} alt={pose.label} className="h-full w-full object-contain" /></div><h4 className="mt-3 text-sm font-semibold text-[var(--text-primary)]">{pose.label}</h4><p className="mt-1 truncate font-mono text-xs text-[var(--text-muted)]">{pose.filename}</p></article>)}</div></section>)}</div>
  </div>;
}
