"use client";

/**
 * S11-T04D — Review Queue page (project-scoped, real backend).
 *
 * /projects/[id]/review renders the lane-C queue from the REAL
 * /api/v2/projects/{id}/qc-items surface: default filter severity=blocker
 * (blockers first), warnings behind a collapsible count, and the item
 * detail with the T04A navigation payload (deep link = gallery at the
 * failing frame/role — never the full timeline, G13) plus the two-phase
 * correction flow (T04B preview → confirm).
 *
 * Data rules inherited from the backend contract:
 *   - queue/list/item/navigation are GET-only reads (Decision A)
 *   - corrections go through the S08-T05 preview/create/confirm routes only
 *   - the auto-resolve lifecycle stays server-owned — the UI only reflects
 *     status; a running recompute (RecomputeStateData) never blocks
 *     navigation.
 */

import { Suspense, use, useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import {
  api,
  type ObjectCorrection,
  type QcItemData,
  type QcNavigationData,
} from "@/lib/api";
import { ReviewCorrectionPanel } from "@/components/review/ReviewCorrectionPanel";
import { ReadinessPanel } from "@/components/readiness/ReadinessPanel";
import { ReviewItemDetail, type CorrectionProgressInfo } from "@/components/review/ReviewItemDetail";
import { ReviewQueueList } from "@/components/review/ReviewQueueList";

const TERMINAL_RECOMPUTE = new Set(["completed", "failed", "cancelled"]);

export default function ReviewPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<div className="min-h-full p-6" aria-busy="true" />}>
      <ReviewRoute params={params} />
    </Suspense>
  );
}

function progressOf(correction: ObjectCorrection): CorrectionProgressInfo {
  const recompute = correction.recompute;
  return {
    status: recompute?.status ?? correction.status,
    progress: recompute?.progress ?? null,
    error: recompute?.error ?? null,
  };
}

function ReviewRoute({ params }: { params: Promise<{ id: string }> }) {
  const resolved = use(params);
  const projectId = resolved.id;
  const router = useRouter();
  const searchParams = useSearchParams();

  const [blockers, setBlockers] = useState<QcItemData[]>([]);
  const [warnings, setWarnings] = useState<QcItemData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [item, setItem] = useState<QcItemData | null>(null);
  const [navigation, setNavigation] = useState<QcNavigationData | null>(null);
  const [navLoading, setNavLoading] = useState(false);
  const [navError, setNavError] = useState<string | null>(null);
  const [correctionOpen, setCorrectionOpen] = useState(false);
  const [corrections, setCorrections] = useState<Record<string, ObjectCorrection>>({});
  const [projectName, setProjectName] = useState<string | null>(null);

  const initialSelectDone = useRef(false);
  const pollTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  const loadQueue = useCallback(
    async (mode: "initial" | "refresh" = "initial") => {
      if (mode === "refresh") setRefreshing(true);
      else setLoading(true);
      setError(null);
      try {
        const [blockerRes, warningRes] = await Promise.all([
          api.listQcItems(projectId, { severity: "blocker", limit: 200 }),
          api.listQcItems(projectId, { severity: "warning", limit: 200 }),
        ]);
        setBlockers(blockerRes.items);
        setWarnings(warningRes.items);
        setLastUpdated(
          new Date().toLocaleTimeString("vi-VN", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          }),
        );
        // Project identity (real backend, non-fatal if it races).
        try {
          const durable = await api.getDurableProject(projectId);
          setProjectName(durable.name);
        } catch {
          setProjectName((prev) => prev ?? null);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Lỗi kết nối máy chủ.");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [projectId],
  );

  const selectItem = useCallback(
    async (itemId: string) => {
      setSelectedId(itemId);
      setItem(null);
      setNavigation(null);
      setNavError(null);
      setNavLoading(true);
      router.replace(`/projects/${encodeURIComponent(projectId)}/review?item=${encodeURIComponent(itemId)}`);
      try {
        const [itemData, nav] = await Promise.all([
          api.getQcItem(itemId),
          api.getQcNavigation(itemId),
        ]);
        setItem(itemData);
        setNavigation(nav);
      } catch (err) {
        setNavError(err instanceof Error ? err.message : "Lỗi kết nối máy chủ.");
      } finally {
        setNavLoading(false);
      }
    },
    [projectId, router],
  );

  const backToList = useCallback(() => {
    setSelectedId(null);
    setItem(null);
    setNavigation(null);
    setCorrectionOpen(false);
    router.replace(`/projects/${encodeURIComponent(projectId)}/review`);
  }, [projectId, router]);

  // Initial load + the ?item= deep link (once).  setState moves into a
  // microtask so no synchronous state write happens inside the effect body.
  useEffect(() => {
    queueMicrotask(() => {
      void loadQueue("initial");
    });
  }, [loadQueue]);

  useEffect(() => {
    if (loading || initialSelectDone.current) return;
    initialSelectDone.current = true;
    const itemId = searchParams.get("item");
    if (itemId) {
      queueMicrotask(() => {
        void selectItem(itemId);
      });
    }
  }, [loading, searchParams, selectItem]);

  useEffect(() => {
    const timers = pollTimers.current;
    return () => {
      for (const t of Object.values(timers)) clearInterval(t);
    };
  }, []);

  // Non-blocking poll: when a correction enters a running recompute, poll
  // GET /corrections/{id} and update the progress map; stop on terminal.
  const startPolling = useCallback((itemId: string, correctionId: string) => {
    if (pollTimers.current[itemId]) return;
    pollTimers.current[itemId] = setInterval(async () => {
      try {
        const latest = await api.getCorrection(correctionId);
        setCorrections((prev) => ({ ...prev, [itemId]: latest }));
        const status = latest.recompute?.status;
        if (status && TERMINAL_RECOMPUTE.has(status)) {
          clearInterval(pollTimers.current[itemId]);
          delete pollTimers.current[itemId];
        }
      } catch {
        // transient read failure — keep polling, never block the UI
      }
    }, 2500);
  }, []);

  // The applied handler receives the correction but we need the SELECTED
  // item id to key the queue row — wire it here (closure over selectedId).
  const handleAppliedForKeyed = useCallback(
    (applied: ObjectCorrection) => {
      const key = selectedId ?? applied.video_item_id;
      setCorrections((prev) => ({ ...prev, [key]: applied }));
      if (applied.recompute?.job_id) {
        startPolling(key, applied.id);
      }
    },
    [selectedId, startPolling],
  );

  const progressMap: Record<string, CorrectionProgressInfo> = {};
  for (const [key, corr] of Object.entries(corrections)) {
    progressMap[key] = progressOf(corr);
  }

  // Stable identities — the correction panel's open-effect keys on
  // onClose/onApplied; an inline arrow would re-run preview on every parent
  // re-render (polling/applied) and lose the two-phase state.
  const closeCorrection = useCallback(() => setCorrectionOpen(false), []);
  const applyCorrection = useCallback(
    (applied: ObjectCorrection) => handleAppliedForKeyed(applied),
    [handleAppliedForKeyed],
  );

  const canCorrect =
    item !== null &&
    typeof item.evidence?.object_role_id === "string" &&
    typeof item.evidence?.occurrence_id === "string";

  return (
    <div className="min-h-full bg-zinc-950 p-4 sm:p-6 text-zinc-100 max-w-6xl mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800 pb-4">
        <div className="flex items-center gap-2 text-sm text-zinc-400 min-w-0">
          <Link href={`/projects/${encodeURIComponent(projectId)}`} className="hover:text-zinc-200 transition">
            &larr; {selectedId ? "Về dự án" : "Tất cả dự án"}
          </Link>
          <span aria-hidden="true">/</span>
          <span className="text-zinc-200 font-medium truncate">Hàng đợi QC</span>
        </div>
        <p className="text-[11px] text-gray-400">
          Dữ liệu thật từ máy chủ (QC items GET-only) — blocker luôn hiện trước.
        </p>
      </div>

      <div className="mt-4 space-y-4">
        <ReviewQueueList
          projectId={projectId}
          blockers={blockers}
          warnings={warnings}
          selectedId={selectedId}
          loading={loading}
          error={error}
          lastUpdated={lastUpdated}
          refreshing={refreshing}
          progress={progressMap}
          onSelect={(id) => void selectItem(id)}
          onRetry={() => void loadQueue("initial")}
          onRefresh={() => void loadQueue("refresh")}
        />

        {selectedId && item && (
          <>
            <ReviewItemDetail
              projectId={projectId}
              projectName={projectName ?? "dự án"}
              item={item}
              navigation={navigation}
              navLoading={navLoading}
              navError={navError}
              correction={progressMap[selectedId] ?? null}
              canCorrect={canCorrect}
              onOpenCorrection={() => setCorrectionOpen(true)}
              onRetryNav={() => {
                if (selectedId) void selectItem(selectedId);
              }}
              onBack={backToList}
            />
            {correctionOpen && (
              <ReviewCorrectionPanel
                open={correctionOpen}
                item={item}
                onClose={closeCorrection}
                onApplied={applyCorrection}
              />
            )}
          </>
        )}
      </div>

      {/* S11-T05B additive: readiness block (T05A payload, GET-only). */}
      <ReadinessPanel projectId={projectId} />

      <p className="mt-6 flex items-center gap-1.5 text-[11px] text-gray-400">
        <ArrowLeft aria-hidden="true" size={12} className="hidden" />
        Issue được tự động đánh dấu sau khi kiểm tra lại xác nhận đã hết — màn hình này chỉ
        phản ánh trạng thái máy chủ.
      </p>
    </div>
  );
}