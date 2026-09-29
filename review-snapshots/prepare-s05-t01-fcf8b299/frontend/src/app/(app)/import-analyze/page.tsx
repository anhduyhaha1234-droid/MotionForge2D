"use client";

/**
 * Import/Analyze screen — S05-T05.
 *
 * Hosts the ImportAnalyzePanel. Creates (or re-opens) the legacy project
 * the approved ingest route runs against, then delegates to the panel for
 * upload → durable job submit → real progress → cancel/retry/resume.
 * All job state comes from the backend state machine; no mock progress.
 */

import { Suspense, useCallback, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { ImportAnalyzePanel } from "@/components/ImportAnalyzePanel";

/**
 * Next.js static prerender requires useSearchParams to be wrapped in a
 * Suspense boundary (missing-suspense-with-csr-bailout). The page content
 * is fully client-rendered inside <Suspense>.
 */
export default function ImportAnalyzePage() {
  return (
    <Suspense fallback={<div className="min-h-full p-4 sm:p-6" aria-busy="true" />}>
      <ImportAnalyzeRoute />
    </Suspense>
  );
}

function ImportAnalyzeRoute() {
  const searchParams = useSearchParams();
  const router = useRouter();
  // Lazy init from ?project= — no effect needed (avoids setState-in-effect).
  const [projectId, setProjectId] = useState<string | null>(() => searchParams.get("project"));
  const [projectName, setProjectName] = useState("Dự án phân tích");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = useCallback(async () => {
    setCreating(true);
    setError(null);
    try {
      const res = await api.createProject(projectName.trim() || "Dự án phân tích");
      const pid = res.project_id;
      setProjectId(pid);
      router.replace(`/import-analyze?project=${encodeURIComponent(pid)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tạo dự án.");
      setCreating(false);
    }
  }, [projectName, router]);

  return (
    <div className="min-h-full p-4 sm:p-6">
      {!projectId ? (
        <div className="mx-auto w-full max-w-3xl space-y-6">
          <div className="space-y-2">
            <h1 className="font-display text-2xl font-semibold text-[var(--text-primary)]">
              Nhập &amp; Phân tích video
            </h1>
            <p className="text-sm text-[var(--text-muted)]">
              Tạo dự án mới để bắt đầu: đặt tên, chọn video MP4, hệ thống sẽ kiểm tra
              định dạng, phát hiện phân cảnh và chuẩn bị proxy.
            </p>
          </div>

          <section
            aria-label="Tạo dự án phân tích"
            className="space-y-4 rounded-2xl border border-[var(--surface-800)] bg-[var(--surface-900)] p-6 shadow-panel"
          >
            <div className="space-y-2">
              <label
                htmlFor="import-project-name"
                className="block text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]"
              >
                Tên dự án
              </label>
              <input
                id="import-project-name"
                type="text"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                disabled={creating}
                placeholder="VD: Dự án tập 1 — kênh Hài 2D"
                className="w-full rounded-lg border border-[var(--surface-700)] bg-[var(--surface-950)] px-4 py-2.5 text-sm text-[var(--text-primary)] placeholder-[var(--text-faint)] focus:border-[var(--primary-500)] focus:outline-none disabled:opacity-50"
              />
            </div>

            <div className="flex flex-col items-start gap-2">
              <button
                type="button"
                onClick={() => void handleCreate()}
                disabled={creating}
                className="rounded-lg bg-[var(--primary-600)] px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[var(--primary-700)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creating ? "Đang tạo dự án..." : "Tạo dự án và tiếp tục"}
              </button>
              <p className="text-[11px] text-[var(--text-muted)]">
                Tạo dự án mới chứa video nguồn, sau đó chuyển sang bước chọn tệp và phân tích.
              </p>
            </div>

            {error && (
              <p role="alert" className="text-xs text-[var(--danger)]">
                Không thể tạo dự án: {error}
              </p>
            )}
          </section>
        </div>
      ) : (
        <ImportAnalyzePanel projectId={projectId} />
      )}
    </div>
  );
}
