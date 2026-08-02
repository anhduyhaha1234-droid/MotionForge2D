"use client";

/**
 * ScreenD — Replacement & Composite Preview
 *
 * 3-column layout:
 * Left:   objects & library (cards + upload + frame slider)
 * Center: Konva composite canvas
 * Right:  4 transform sliders + apply-all action + scene/dubbing panels
 */

import { useCallback, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useProjectStore } from "@/stores/project";
import { CompositeCanvas } from "@/components/CompositeCanvas";
import { SceneSelector } from "./SceneSelector";
import { ScenePreview } from "./ScenePreview";
import { DubbingPanel } from "./DubbingPanel";

/* ── Preview mode labels (Vietnamese) ──────────────────────────────────── */

const PREVIEW_MODES = [
  { value: "original" as const, label: "Ảnh gốc" },
  { value: "mask" as const, label: "Mask" },
  { value: "result" as const, label: "Kết quả" },
  { value: "comparison" as const, label: "So sánh" },
];

/* ── Slider helper ─────────────────────────────────────────────────────── */

function Slider({
  label,
  caption,
  value,
  min,
  max,
  step,
  unit,
  onChange,
}: {
  label: string;
  caption?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <label className="text-xs text-gray-300">{label}</label>
        <span className="text-xs text-gray-500 font-mono">
          {unit === "°"
            ? `${value}${unit}`
            : unit === "x"
              ? `${value.toFixed(2)}${unit}`
              : unit === "%"
                ? `${Math.round(value * 100)}${unit}`
                : value.toFixed(2)}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
      {caption && <p className="text-[10px] text-gray-600 -mt-1">{caption}</p>}
    </div>
  );
}

/* ── Main Component ────────────────────────────────────────────────────── */

export function ScreenD() {
  const {
    projectId,
    project,
    activeObject,
    setActiveObject,
    currentFrame,
    setCurrentFrame,
    replacement,
    setReplacement,
    resetReplacement,
    previewMode,
    setPreviewMode,
    frameMotion,
    setFrameMotion,
    setScreen,
  } = useProjectStore();

  const queryClient = useQueryClient();
  const activeSceneId = useProjectStore((s) => s.activeSceneId);

  /* ── Auto-select first object ───────────────────────────────────────── */

  useEffect(() => {
    if (!activeObject && project?.objects?.length) {
      setActiveObject(project.objects[0]);
    }
  }, [activeObject, project, setActiveObject]);

  const approveSceneMut = useMutation({
    mutationFn: () => {
      if (!projectId || activeSceneId === null) return Promise.resolve({ ok: false });
      return api.updateSceneStatus(projectId, activeSceneId, "approved");
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scenes", projectId] });
    },
  });

  const objectId = activeObject?.object_id;
  const meta = project?.video_metadata;
  const videoWidth = meta?.width ?? 1920;
  const videoHeight = meta?.height ?? 1080;
  const totalFrames = meta?.total_frames ?? 1;

  const sceneCount =
    project?.scene_details?.length ?? project?.scenes?.length ?? 0;

  /* ── Frame motion data ──────────────────────────────────────────────── */

  // Derive frame motion from activeObject when frame changes
  useEffect(() => {
    if (!activeObject?.motion?.frames) {
      setFrameMotion(null);
      return;
    }
    const frames = activeObject.motion.frames;
    const fm = frames.find((f) => f.frame_index === currentFrame) ?? null;
    setFrameMotion(fm);
  }, [activeObject, currentFrame, setFrameMotion]);

  /* ── Frame URL ──────────────────────────────────────────────────────── */

  const frameUrl = projectId ? api.getFrameUrl(projectId, currentFrame) : null;

  /* ── Mask URL ───────────────────────────────────────────────────────── */

  const maskUrl =
    projectId && objectId
      ? api.getMaskImageUrl(projectId, objectId, currentFrame)
      : null;

  /* ── Replacement image URL ──────────────────────────────────────────── */

  const replacementUrl =
    projectId && objectId && replacement.asset_path
      ? `http://localhost:8000${replacement.asset_path}`
      : null;

  /* ── Upload mutation ────────────────────────────────────────────────── */

  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      if (!projectId || !objectId) throw new Error("No project/object");
      const result = await api.uploadReplacement(projectId, objectId, file);
      setReplacement({ mode: "static_asset", asset_path: result.asset_path });
      return result;
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadMut.mutate(file);
  };

  /* ── Settings mutation ──────────────────────────────────────────────── */

  const settingsMut = useMutation({
    mutationFn: async () => {
      if (!projectId || !objectId) throw new Error("No project/object");
      return api.updateReplacementSettings(projectId, objectId, {
        mode: replacement.mode,
        asset_path: replacement.asset_path,
        anchor: replacement.anchor,
        offset: replacement.offset,
        scale: replacement.scale,
        rotation_offset_deg: replacement.rotation_offset_deg,
        opacity: replacement.opacity,
        fit_mode: replacement.fit_mode,
        clip_mode: replacement.clip_mode,
        frameSequenceDir: replacement.frameSequenceDir,
        frameSequenceFps: replacement.frameSequenceFps,
      });
    },
  });

  /* ── Sequence frame URL ──────────────────────────────────────────────── */

  const sequenceFrameUrl =
    projectId && objectId && replacement.mode === "frame_sequence"
      ? api.getSequenceFrameUrl(projectId, objectId, currentFrame)
      : null;

  /* ── Frame slider helper ────────────────────────────────────────────── */

  const handleFrameChange = useCallback(
    (val: number) => {
      setCurrentFrame(val);
    },
    [setCurrentFrame],
  );

  /* ── Render ─────────────────────────────────────────────────────────── */

  return (
    <div className="flex flex-col h-screen">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800">
        <h2 className="text-sm font-medium">Thay thế vật thể</h2>
        <div className="flex items-center gap-3">
          {/* Preview mode selector */}
          <div className="flex gap-1">
            {PREVIEW_MODES.map((pm) => (
              <button
                key={pm.value}
                onClick={() => setPreviewMode(pm.value)}
                className={`px-2 py-1 text-xs rounded ${
                  previewMode === pm.value
                    ? "bg-blue-600 text-white"
                    : "bg-gray-800 text-gray-300 hover:bg-gray-700"
                }`}
              >
                {pm.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => setScreen("review")}
            className="text-xs text-gray-400 hover:text-gray-200"
          >
            ← Quay lại kết quả
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* ── Left column: Objects & Library ─────────────────────────────── */}
        <div className="w-64 bg-gray-900 border-r border-gray-800 p-4 space-y-4 overflow-y-auto flex-shrink-0">
          <h3 className="text-xs text-gray-500 uppercase mb-2">
            🎭 Nhân vật đã tách
          </h3>
          <div className="space-y-2">
            {project?.objects?.map((obj) => (
              <button
                key={obj.object_id}
                onClick={() => setActiveObject(obj)}
                className={`w-full text-left p-2 rounded-lg border transition-colors ${
                  activeObject?.object_id === obj.object_id
                    ? "bg-purple-900/40 border-purple-500/50"
                    : "bg-gray-800/80 border-gray-700 hover:bg-gray-700/80"
                }`}
              >
                <div className="flex items-center gap-2">
                  <div className="w-10 h-10 bg-gray-900 rounded overflow-hidden flex-shrink-0">
                    {projectId && (
                      <img
                        src={api.getReplacementImageUrl(projectId, obj.object_id)}
                        alt={obj.name}
                        className="w-full h-full object-contain"
                        onError={(e) => {
                          // Fallback to generic thumbnail
                          const el = e.target as HTMLImageElement;
                          el.src = `http://localhost:8000/api/projects/${projectId}/objects/${obj.object_id}/thumbnail`;
                          el.onerror = null;
                        }}
                      />
                    )}
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-gray-200 truncate">
                      {obj.name}
                    </p>
                    <p className="text-[10px] text-gray-500">
                      Scene {obj.scene_id}
                    </p>
                  </div>
                </div>
              </button>
            ))}
            {!project?.objects?.length && (
              <p className="text-xs text-gray-600">
                Chưa có nhân vật nào. Vào Màn B để tách nhân vật.
              </p>
            )}
          </div>

          <div className="border-t border-gray-700 pt-3 space-y-2">
            <label className="block w-full py-2 text-center text-xs bg-blue-600 hover:bg-blue-500 rounded cursor-pointer">
              📁 Tải Ảnh Nhân Vật Mới (PNG)
              <input
                type="file"
                accept=".png,image/png"
                onChange={handleFileChange}
                className="hidden"
              />
            </label>
            {uploadMut.isPending && (
              <p className="text-xs text-yellow-400 text-center">
                Đang tải lên...
              </p>
            )}
            <button
              onClick={() =>
                alert(
                  "Thư viện nhân vật mẫu đang được phát triển — hãy tải PNG của bạn lên nhé!",
                )
              }
              className="w-full py-2 text-xs bg-gray-700 hover:bg-gray-600 rounded"
            >
              🎭 Thư Viện Nhân Vật Mẫu
            </button>
          </div>

          {/* Frame slider */}
          <div>
            <h3 className="text-xs text-gray-500 uppercase mb-2">
              Frame ({currentFrame}/{totalFrames - 1})
            </h3>
            <input
              type="range"
              min={0}
              max={totalFrames - 1}
              value={currentFrame}
              onChange={(e) => handleFrameChange(Number(e.target.value))}
              className="w-full"
              data-testid="frame-slider"
            />
            <div className="flex justify-between text-xs text-gray-500">
              <span>0</span>
              <span>{totalFrames - 1}</span>
            </div>
          </div>
        </div>

        {/* ── Center: Konva canvas ───────────────────────────────────────── */}
        <div className="flex-1 flex items-center justify-center bg-gray-950 min-w-0">
          <CompositeCanvas
            frameUrl={frameUrl}
            maskUrl={maskUrl}
            replacementUrl={replacementUrl}
            sequenceFrameUrl={sequenceFrameUrl}
            frameMotion={frameMotion}
            replacement={replacement}
            videoWidth={videoWidth}
            videoHeight={videoHeight}
            previewMode={previewMode}
          />
        </div>

        {/* ── Right column: Transform controls ───────────────────────────── */}
        <div className="w-72 bg-gray-900 border-l border-gray-800 p-4 space-y-4 overflow-y-auto flex-shrink-0">
          <h3 className="text-xs text-gray-500 uppercase">
            Điều chỉnh nhân vật
          </h3>

          {/* Scale */}
          <Slider
            label="🔍 Kích thước"
            caption="Phóng to / Thu nhỏ nhân vật mới"
            value={replacement.scale}
            min={0.1}
            max={3}
            step={0.05}
            unit="x"
            onChange={(v) => setReplacement({ scale: v })}
          />

          {/* Rotation */}
          <Slider
            label="🔄 Góc xoay"
            caption="Xoay nhân vật mới theo góc tùy chỉnh"
            value={replacement.rotation_offset_deg}
            min={-180}
            max={180}
            step={1}
            unit="°"
            onChange={(v) => setReplacement({ rotation_offset_deg: v })}
          />

          {/* Offset X */}
          <Slider
            label="↔️ Vị trí Ngang"
            caption="Dịch chuyển nhân vật sang trái / phải"
            value={replacement.offset.x}
            min={-0.5}
            max={0.5}
            step={0.01}
            onChange={(v) =>
              setReplacement({ offset: { ...replacement.offset, x: v } })
            }
          />

          {/* Offset Y */}
          <Slider
            label="↕️ Vị trí Dọc"
            caption="Dịch chuyển nhân vật lên / xuống"
            value={replacement.offset.y}
            min={-0.5}
            max={0.5}
            step={0.01}
            onChange={(v) =>
              setReplacement({ offset: { ...replacement.offset, y: v } })
            }
          />

          {/* 🚀 Apply to all scenes — save settings then auto-match */}
          <button
            onClick={async () => {
              if (!projectId || !objectId) return;
              try {
                await settingsMut.mutateAsync();
                const result = await api.autoMatchCharacter(
                  projectId,
                  objectId,
                );
                alert(`Đã áp dụng nhân vật mới cho ${result.count} cảnh!`);
              } catch (err) {
                alert(`Lỗi: ${(err as Error).message}`);
              }
            }}
            disabled={settingsMut.isPending}
            className="w-full py-3 text-sm bg-purple-600 hover:bg-purple-500 text-white font-bold rounded-xl shadow-lg shadow-purple-900/40 transition-all disabled:bg-gray-700 disabled:text-gray-400"
            data-testid="apply-all-scenes"
          >
            🚀 Áp Dụng Nhân Vật Mới Cho Tất Cả {sceneCount} Cảnh
          </button>

          {/* Actions */}
          <div className="space-y-1 pt-2 border-t border-gray-800">
            <button
              onClick={() => settingsMut.mutate()}
              disabled={settingsMut.isPending}
              className="w-full py-2 text-sm bg-green-700 hover:bg-green-600 disabled:bg-gray-800 rounded"
              data-testid="apply-settings"
            >
              {settingsMut.isPending ? "Đang lưu..." : "Áp dụng"}
            </button>
            <p className="text-[11px] text-gray-400 mt-1">
              Lưu ảnh thay thế + vị trí nhân vật hiện tại.
            </p>
            <button
              onClick={() => resetReplacement()}
              className="w-full py-2 text-sm bg-gray-800 hover:bg-gray-700 rounded"
            >
              Đặt lại
            </button>
            <p className="text-[11px] text-gray-400 mt-1">
              Xóa ảnh thay thế, quay về ảnh nhân vật gốc.
            </p>
            <button
              onClick={() => setScreen("render")}
              className="w-full py-2 text-sm bg-blue-700 hover:bg-blue-600 rounded"
              data-testid="next-render"
            >
              Tiếp: Render →
            </button>
            <p className="text-[11px] text-gray-400 mt-1">
              Chuyển sang bước render & ghép video hoàn chỉnh.
            </p>
          </div>

          {/* Scene selector & preview */}
          <div className="border-t border-gray-700 pt-3 space-y-3">
            <SceneSelector />
            <ScenePreview />
            <button
              onClick={() => approveSceneMut.mutate()}
              disabled={activeSceneId === null || approveSceneMut.isPending}
              className="w-full py-2 bg-green-600 hover:bg-green-500
                disabled:bg-gray-700 disabled:text-gray-500
                rounded font-medium text-sm transition-colors"
            >
              ✅ Duyệt phân cảnh này
            </button>
          </div>

          {/* Dubbing Section */}
          <details className="border-t border-gray-700 pt-3">
            <summary className="text-sm font-medium text-gray-300 cursor-pointer">
              🎙️ Lồng tiếng / Dubbing
            </summary>
            <div className="mt-2">
              <DubbingPanel />
            </div>
          </details>
        </div>
      </div>
    </div>
  );
}
