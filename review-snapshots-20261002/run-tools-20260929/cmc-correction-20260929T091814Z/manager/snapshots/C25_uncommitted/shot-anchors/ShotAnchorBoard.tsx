"use client";

/**
 * MF-END-25 (C25) — ShotAnchorBoard: the missing "build anchors" step of the
 * product journey (G2).
 *
 * Mounted on the project page with the project/video identity the user is
 * looking at.  Everything on this board is a REAL backend read/write:
 *   - configs:  GET   /api/v2/reskin-configs?project_id=…   (project-scoped)
 *   - shots:    GET   /api/v2/structural-evidence/segments?video_item_id=…
 *   - anchors:  GET   /api/v2/reskin-configs/{id}/renderer-route-evidence
 *   - save:     PATCH /api/v2/reskin-configs/{id}  (CAS revision, 409 = zero mutation)
 *   - frame:    GET   /api/projects/{id}/frames/{index}   (real source frame)
 *
 * Project-context invariant: a config row whose `project_id` differs from the
 * board's project is refused (typed) — anchors of two projects are never
 * mixed.  Nothing is seeded or defaulted: an absent anchor stays absent and
 * the gate says which shots are still missing.
 *
 * Dark theme: every button carries short Vietnamese helper text DIRECTLY
 * BELOW it (text-gray-400, ≥11px).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Crosshair, RefreshCw, Save } from "lucide-react";
import { ApiError } from "@/lib/api";
import {
  anchorCoverage,
  anchorGateMessage,
  anchorOverlayStyle,
  buildAnchorEdit,
  buildShotAnchors,
  classifyAnchorError,
  parseAnchor,
  projectScopeMatches,
  sourceFrameUrl,
  type AnchorPoint,
  type ShotAnchor,
} from "./shotAnchorsLogic";
import {
  getConfigAnchorEvidence,
  listProjectReskinConfigs,
  listVideoSegments,
  updateConfigAnchor,
  type ShotAnchorConfig,
  type ShotSegment,
} from "./shotAnchorsApi";

const HELPER = "text-[11px] leading-snug text-gray-400";

export interface ShotAnchorBoardProps {
  projectId: string;
  /** Video item of the analyzed source; null → honest empty state. */
  videoItemId: string | null;
  /** Scene id used by the real frame route (default 0). */
  sceneId?: number;
  onCoverageChange?: (ready: boolean, message: string) => void;
}

interface BoardState {
  phase: "loading" | "error" | "ready";
  error: string | null;
  configs: ShotAnchorConfig[];
  segments: ShotSegment[];
  anchorsByConfig: Record<string, ShotAnchor[]>;
  invalidTotal: number;
  scopeOk: boolean;
}

const EMPTY: BoardState = {
  phase: "loading",
  error: null,
  configs: [],
  segments: [],
  anchorsByConfig: {},
  invalidTotal: 0,
  scopeOk: true,
};

function apiBase(): string {
  return (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8888").replace(/\/+$/, "");
}

export function ShotAnchorBoard({
  projectId,
  videoItemId,
  sceneId = 0,
  onCoverageChange,
}: ShotAnchorBoardProps) {
  const [state, setState] = useState<BoardState>(EMPTY);
  const [savingConfig, setSavingConfig] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, AnchorPoint>>({});

  const load = useCallback(async () => {
    setState((prev) => ({ ...prev, phase: "loading", error: null }));
    if (!videoItemId) {
      setState({ ...EMPTY, phase: "ready", segments: [] });
      return;
    }
    try {
      const configsRes = await listProjectReskinConfigs(projectId);
      const configs = configsRes.configs;
      const scopeOk = configs.every((c) => projectScopeMatches(c.project_id, projectId));
      if (!scopeOk) {
        setState({ ...EMPTY, phase: "ready", scopeOk: false, configs: [] });
        return;
      }
      const [segmentsRes, ...evidence] = await Promise.all([
        listVideoSegments(videoItemId),
        ...configs.map((c) => getConfigAnchorEvidence(c.id).catch(() => [] as never[])),
      ]);
      const anchorsByConfig: Record<string, ShotAnchor[]> = {};
      let invalidTotal = 0;
      configs.forEach((cfg, index) => {
        const built = buildShotAnchors(evidence[index] ?? [], {
          projectId,
          rowsProjectId: cfg.project_id,
        });
        anchorsByConfig[cfg.id] = built.anchors;
        invalidTotal += built.invalid;
      });
      const segments = (segmentsRes.segments ?? []).filter(
        (s) => projectScopeMatches(s.project_id ?? null, projectId),
      );
      setState({
        phase: "ready",
        error: null,
        configs,
        segments,
        anchorsByConfig,
        invalidTotal,
        scopeOk: true,
      });
    } catch (err) {
      setState({
        ...EMPTY,
        phase: "error",
        error:
          err instanceof ApiError
            ? classifyAnchorError(err.status, err.detailText()).message
            : err instanceof Error
              ? err.message
              : "Không tải được dữ liệu anchor.",
      });
    }
  }, [projectId, videoItemId]);

  useEffect(() => {
    queueMicrotask(() => {
      void load();
    });
  }, [load]);

  const coverage = useMemo(() => {
    const all = Object.values(state.anchorsByConfig).flat();
    return anchorCoverage(all, state.segments, state.invalidTotal);
  }, [state.anchorsByConfig, state.segments, state.invalidTotal]);

  const gateMessage = useMemo(() => {
    if (state.configs.length === 0 && state.phase === "ready") {
      return state.segments.length === 0
        ? "Chưa có shot/segment nào cho video này (cần bước phân tích cảnh)."
        : "Chưa có cấu hình reskin cho vai nào — hãy ghim bộ nhân vật (cast) trước.";
    }
    return anchorGateMessage(coverage, state.scopeOk);
  }, [coverage, state.configs.length, state.phase, state.segments.length, state.scopeOk]);

  useEffect(() => {
    onCoverageChange?.(coverage.ready, gateMessage);
  }, [coverage.ready, gateMessage, onCoverageChange]);

  const draftFor = useCallback(
    (anchor: ShotAnchor): AnchorPoint => draft[anchor.segmentId] ?? anchor.anchor,
    [draft],
  );

  const save = useCallback(
    async (config: ShotAnchorConfig, anchor: ShotAnchor) => {
      const next = draft[anchor.segmentId] ?? anchor.anchor;
      const plan = buildAnchorEdit(config, projectId, config.project_id, next);
      if (!plan.ok || !plan.params || plan.revision === null) {
        setSaveNotice(null);
        setSaveError(
          plan.refusal === "anchor_out_of_range"
            ? "Anchor phải nằm trong [0,1] cho cả x và y."
            : plan.refusal === "project_scope_mismatch"
              ? "Cấu hình này thuộc dự án khác — không lưu để tránh trộn project."
              : "Anchor không hợp lệ — không gửi yêu cầu.",
        );
        return;
      }
      setSavingConfig(config.id);
      setSaveError(null);
      setSaveNotice(null);
      try {
        const updated = await updateConfigAnchor(config.id, {
          revision: plan.revision,
          params: plan.params,
        });
        setState((prev) => {
          const anchors = (prev.anchorsByConfig[config.id] ?? []).map((row) =>
            row.segmentId === anchor.segmentId
              ? { ...row, anchor: next, measured: true }
              : row,
          );
          return {
            ...prev,
            configs: prev.configs.map((c) =>
              c.id === updated.id ? { ...c, revision: updated.revision, params: updated.params } : c,
            ),
            anchorsByConfig: { ...prev.anchorsByConfig, [config.id]: anchors },
          };
        });
        setSaveNotice(
          `Đã lưu anchor cho shot #${anchor.startFrame}–${anchor.endFrame} (revision ${updated.revision}).`,
        );
      } catch (err) {
        const status = err instanceof ApiError ? err.status : null;
        const copy = classifyAnchorError(status, err instanceof ApiError ? err.detailText() : undefined);
        setSaveError(copy.message);
        if (copy.code === "conflict") void load();
      } finally {
        setSavingConfig(null);
      }
    },
    [draft, load, projectId],
  );

  const totalAnchors = Object.values(state.anchorsByConfig).flat().length;

  return (
    <section
      data-testid="shot-anchor-board"
      aria-label="Anchors theo shot (G2)"
      className="space-y-4 rounded-xl border border-zinc-800 bg-zinc-900/60 p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-zinc-100">
            <Crosshair aria-hidden="true" size={18} className="text-indigo-400" />
            Anchors theo shot (G2)
          </h2>
          <p className="text-xs text-zinc-400">
            Anchor là điểm neo chuẩn hoá [0,1] trên khung nguồn của từng shot, lấy từ máy chủ.
            Điểm neo và route hiển thị đúng dữ liệu đã lưu — không tự suy diễn.
          </p>
        </div>
        <span className="text-[11px] text-gray-400" data-testid="anchor-scope">
          Dự án: <span className="font-mono">{projectId}</span>
          {videoItemId ? (
            <>
              {" · video "}
              <span className="font-mono">{videoItemId.slice(0, 8)}</span>
            </>
          ) : null}
        </span>
      </div>

      {state.phase === "loading" && (
        <div className="space-y-2" aria-busy="true" data-testid="anchor-loading">
          <div className="h-24 animate-pulse rounded-lg bg-zinc-800" />
          <p className={HELPER}>Đang đọc cấu hình và anchor từ máy chủ…</p>
        </div>
      )}

      {state.phase === "error" && (
        <div role="alert" className="space-y-2" data-testid="anchor-error">
          <p className="flex items-center gap-2 text-sm text-red-300">
            <AlertTriangle aria-hidden="true" size={15} />
            {state.error}
          </p>
          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              onClick={() => void load()}
              className="inline-flex min-h-9 items-center gap-2 rounded bg-zinc-800 px-3 py-1.5 text-xs text-zinc-100 hover:bg-zinc-700"
              data-testid="anchor-retry"
            >
              <RefreshCw aria-hidden="true" size={13} />
              Thử lại
            </button>
            <p className={HELPER}>Tải lại cấu hình và anchor thật từ máy chủ.</p>
          </div>
        </div>
      )}

      {state.phase === "ready" && (
        <>
          <div
            className={`rounded-lg border p-3 ${
              coverage.ready
                ? "border-emerald-500/30 bg-emerald-500/5"
                : "border-amber-500/30 bg-amber-500/5"
            }`}
            data-testid="anchor-gate"
          >
            <p className="text-sm text-zinc-100">{gateMessage}</p>
            <p className={HELPER} data-testid="anchor-coverage">
              Shot cần anchor: {coverage.expected} · đã có: {coverage.measured} · thiếu:{" "}
              {coverage.missing} · không hợp lệ: {coverage.invalid} · tổng anchor đọc được:{" "}
              {totalAnchors}
            </p>
          </div>

          {state.configs.length === 0 ? (
            <p className="rounded-lg border border-dashed border-zinc-700 p-4 text-xs text-gray-400" data-testid="anchor-empty">
              {state.segments.length === 0
                ? "Chưa có shot/segment nào cho video này — chạy Nhập & Phân tích để phát hiện cảnh trước."
                : "Chưa có cấu hình reskin cho vai nào. Hãy ghim bộ nhân vật (bước Chọn đối tượng) rồi quay lại đây."}
            </p>
          ) : (
            <ul className="space-y-4" data-testid="anchor-rows">
              {state.configs.map((config) => {
                const rows = state.anchorsByConfig[config.id] ?? [];
                return (
                  <li
                    key={config.id}
                    data-testid={`anchor-config-${config.id}`}
                    className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-zinc-300">
                      <span className="font-mono">
                        vai {config.object_role_id.slice(0, 8)} · nhân vật{" "}
                        {config.character_id.slice(0, 8)}
                      </span>
                      <span className="text-gray-400">revision {config.revision}</span>
                    </div>
                    {rows.length === 0 ? (
                      <p className="text-[11px] text-amber-300" data-testid={`anchor-none-${config.id}`}>
                        Cấu hình này chưa có anchor nào được backend ghi cho shot nào.
                      </p>
                    ) : (
                      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                        {rows.map((anchor) => {
                          const point = draftFor(anchor);
                          const overlay = anchorOverlayStyle(point);
                          return (
                            <div
                              key={anchor.segmentId}
                              data-testid={`anchor-shot-${anchor.segmentId}`}
                              className="space-y-2 rounded-lg border border-zinc-800 p-3"
                            >
                              <div className="flex items-center justify-between gap-2 text-[11px] text-gray-400">
                                <span>
                                  shot {anchor.startFrame}–{anchor.endFrame} ({anchor.frameCount} frame)
                                </span>
                                <span>
                                  route {anchor.route || "—"} · tin cậy{" "}
                                  {anchor.confidence.toFixed(2)}
                                </span>
                              </div>
                              <div className="relative overflow-hidden rounded border border-zinc-800 bg-zinc-900">
                                {/* Real source frame served by the app (no local synthesis). */}
                                {/* eslint-disable-next-line @next/next/no-img-element */}
                                <img
                                  src={sourceFrameUrl(
                                    apiBase(),
                                    projectId,
                                    anchor.startFrame,
                                    sceneId,
                                  )}
                                  alt={`Khung nguồn shot ${anchor.startFrame}`}
                                  className="h-40 w-full object-contain"
                                  data-testid={`anchor-frame-${anchor.segmentId}`}
                                />
                                <span
                                  aria-hidden="true"
                                  data-testid={`anchor-overlay-${anchor.segmentId}`}
                                  className="absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-cyan-400 ring-2 ring-cyan-400/40"
                                  style={{ left: overlay.left, top: overlay.top }}
                                />
                              </div>
                              <div className="flex flex-wrap items-end gap-3">
                                <label className="flex flex-col gap-1 text-[11px] text-gray-400">
                                  anchor X (0–1)
                                  <input
                                    type="number"
                                    step="0.01"
                                    min={0}
                                    max={1}
                                    value={point.x}
                                    aria-label={`anchor X cho shot ${anchor.startFrame}`}
                                    onChange={(e) =>
                                      setDraft((prev) => ({
                                        ...prev,
                                        [anchor.segmentId]: {
                                          x: Number(e.target.value),
                                          y: point.y,
                                        },
                                      }))
                                    }
                                    className="min-h-8 w-24 rounded border border-zinc-700 bg-zinc-900 px-2 text-xs text-zinc-100"
                                  />
                                </label>
                                <label className="flex flex-col gap-1 text-[11px] text-gray-400">
                                  anchor Y (0–1)
                                  <input
                                    type="number"
                                    step="0.01"
                                    min={0}
                                    max={1}
                                    value={point.y}
                                    aria-label={`anchor Y cho shot ${anchor.startFrame}`}
                                    onChange={(e) =>
                                      setDraft((prev) => ({
                                        ...prev,
                                        [anchor.segmentId]: {
                                          x: point.x,
                                          y: Number(e.target.value),
                                        },
                                      }))
                                    }
                                    className="min-h-8 w-24 rounded border border-zinc-700 bg-zinc-900 px-2 text-xs text-zinc-100"
                                  />
                                </label>
                                <div className="flex flex-col items-start gap-1">
                                  <button
                                    type="button"
                                    disabled={savingConfig === config.id}
                                    onClick={() => void save(config, anchor)}
                                    className={`inline-flex min-h-9 items-center gap-2 rounded px-3 py-1.5 text-xs font-medium ${
                                      savingConfig === config.id
                                        ? "cursor-not-allowed bg-zinc-700 text-gray-400"
                                        : "bg-indigo-600 text-white hover:bg-indigo-500"
                                    }`}
                                    data-testid={`anchor-save-${anchor.segmentId}`}
                                  >
                                    <Save aria-hidden="true" size={13} />
                                    {savingConfig === config.id ? "Đang lưu…" : "Lưu anchor"}
                                  </button>
                                  <p className={HELPER}>
                                    Lưu điểm neo cho shot này (kiểm tra revision — xung đột trả 409,
                                    không ghi gì).
                                  </p>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {saveNotice && (
            <p role="status" className="text-xs text-emerald-300" data-testid="anchor-save-ok">
              {saveNotice}
            </p>
          )}
          {saveError && (
            <p role="alert" className="text-xs text-red-300" data-testid="anchor-save-error">
              {saveError}
            </p>
          )}

          <div className="flex flex-col items-start gap-1">
            <button
              type="button"
              onClick={() => void load()}
              className="inline-flex min-h-9 items-center gap-2 rounded border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-100 hover:bg-zinc-800"
              data-testid="anchor-refresh"
            >
              <RefreshCw aria-hidden="true" size={13} />
              Nạp lại anchor từ máy chủ
            </button>
            <p className={HELPER}>
              Đọc lại cấu hình, shot và anchor đã lưu — dùng sau khi đổi cast hoặc chạy lại route.
            </p>
          </div>
        </>
      )}
    </section>
  );
}
