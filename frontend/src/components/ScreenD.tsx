"use client";

/**
 * ScreenD — Replacement & Composite Preview
 *
 * Left panel:   object thumbnail + replacement upload
 * Center:       Konva composite canvas
 * Right panel:  transform controls + preview mode selector
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type ClipMode, type FrameMotion } from "@/lib/api";
import { useProjectStore } from "@/stores/project";
import { CompositeCanvas } from "@/components/CompositeCanvas";

/* ── Preview mode labels (Vietnamese) ──────────────────────────────────── */

const PREVIEW_MODES = [
  { value: "original" as const, label: "Ảnh gốc" },
  { value: "mask" as const, label: "Mask" },
  { value: "result" as const, label: "Kết quả" },
  { value: "comparison" as const, label: "So sánh" },
];

const FIT_MODES = [
  { value: "contain" as const, label: "Contain" },
  { value: "cover" as const, label: "Cover" },
  { value: "stretch" as const, label: "Stretch" },
];

const CLIP_MODES: { value: ClipMode; label: string; desc: string }[] = [
  { value: "asset_alpha", label: "Alpha asset", desc: "Dùng alpha của PNG thay thế" },
  { value: "original_mask", label: "Mask gốc", desc: "Cắt theo mask object gốc" },
  { value: "intersection", label: "Giao", desc: "Giao của alpha + mask gốc" },
];

/* ── Slider helper ─────────────────────────────────────────────────────── */

function Slider({
  label,
  value,
  min,
  max,
  step,
  unit,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label className="text-xs text-gray-400">{label}</label>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
      <span className="text-xs text-gray-500">
        {unit === "°" ? `${value}${unit}` : unit === "x" ? `${value.toFixed(2)}${unit}` : unit === "%" ? `${Math.round(value * 100)}${unit}` : value.toFixed(2)}
      </span>
    </div>
  );
}

/* ── Main Component ────────────────────────────────────────────────────── */

export function ScreenD() {
  const {
    projectId,
    project,
    activeObject,
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

  const objectId = activeObject?.object_id;
  const meta = project?.video_metadata;
  const videoWidth = meta?.width ?? 1920;
  const videoHeight = meta?.height ?? 1080;
  const totalFrames = meta?.total_frames ?? 1;

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
      });
    },
  });

  /* ── Frame slider helper ────────────────────────────────────────────── */

  // Find the nearest tracked frame when user scrubs
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
        {/* ── Left panel ─────────────────────────────────────────────────── */}
        <div className="w-64 bg-gray-900 border-r border-gray-800 p-4 space-y-4 overflow-y-auto">
          {/* Object thumbnail */}
          <div>
            <h3 className="text-xs text-gray-500 uppercase mb-2">
              Object gốc
            </h3>
            <div className="aspect-square bg-gray-800 rounded flex items-center justify-center overflow-hidden">
              {projectId && objectId ? (
                <img
                  src={api.getReplacementImageUrl(projectId, objectId)}
                  alt="Object thumbnail"
                  className="w-full h-full object-contain"
                  onError={(e) => {
                    // Fallback to generic thumbnail
                    const el = e.target as HTMLImageElement;
                    el.src = `http://localhost:8000/api/projects/${projectId}/objects/${objectId}/thumbnail`;
                    el.onerror = null;
                  }}
                />
              ) : (
                <span className="text-gray-600 text-xs">Chưa có object</span>
              )}
            </div>
          </div>

          {/* Replacement upload */}
          <div>
            <h3 className="text-xs text-gray-500 uppercase mb-2">
              Ảnh thay thế
            </h3>
            <input
              type="file"
              accept=".png,image/png"
              onChange={handleFileChange}
              data-testid="replacement-upload"
              className="w-full text-xs text-gray-400 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:bg-blue-600 file:text-white file:text-xs"
            />
            {uploadMut.isPending && (
              <p className="text-xs text-yellow-400 mt-1">Đang tải lên...</p>
            )}
            {replacementUrl && (
              <div className="mt-2 aspect-square bg-gray-800 rounded overflow-hidden relative">
                <div
                  className="absolute inset-0"
                  style={{
                    backgroundImage:
                      "linear-gradient(45deg, #333 25%, transparent 25%), linear-gradient(-45deg, #333 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #333 75%), linear-gradient(-45deg, transparent 75%, #333 75%)",
                    backgroundSize: "12px 12px",
                    backgroundPosition: "0 0, 0 6px, 6px -6px, -6px 0px",
                  }}
                />
                <img
                  src={replacementUrl}
                  alt="Ảnh thay thế"
                  className="relative w-full h-full object-contain"
                  data-testid="replacement-preview"
                />
              </div>
            )}
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

          {/* Motion data info */}
          {frameMotion && (
            <div className="text-xs space-y-1">
              <h3 className="text-gray-500 uppercase">Motion data</h3>
              <div className="flex justify-between">
                <span className="text-gray-400">Centroid:</span>
                <span>
                  ({Math.round(frameMotion.centroid_x)},{" "}
                  {Math.round(frameMotion.centroid_y)})
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">BBox:</span>
                <span>
                  {Math.round(frameMotion.bbox.width)}×
                  {Math.round(frameMotion.bbox.height)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Rotation:</span>
                <span>{frameMotion.rotation_deg.toFixed(1)}°</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Confidence:</span>
                <span
                  className={
                    frameMotion.confidence >= 0.8
                      ? "text-green-400"
                      : frameMotion.confidence >= 0.5
                        ? "text-yellow-400"
                        : "text-red-400"
                  }
                >
                  {(frameMotion.confidence * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          )}
        </div>

        {/* ── Center: Konva canvas ───────────────────────────────────────── */}
        <div className="flex-1 flex items-center justify-center bg-gray-950 min-w-0">
          <CompositeCanvas
            frameUrl={frameUrl}
            maskUrl={maskUrl}
            replacementUrl={replacementUrl}
            frameMotion={frameMotion}
            replacement={replacement}
            videoWidth={videoWidth}
            videoHeight={videoHeight}
            previewMode={previewMode}
          />
        </div>

        {/* ── Right panel: Transform controls ────────────────────────────── */}
        <div className="w-72 bg-gray-900 border-l border-gray-800 p-4 space-y-4 overflow-y-auto">
          <h3 className="text-xs text-gray-500 uppercase">Transform</h3>

          {/* Anchor */}
          <Slider
            label="Anchor X"
            value={replacement.anchor.x}
            min={0}
            max={1}
            step={0.01}
            onChange={(v) =>
              setReplacement({ anchor: { ...replacement.anchor, x: v } })
            }
          />
          <Slider
            label="Anchor Y"
            value={replacement.anchor.y}
            min={0}
            max={1}
            step={0.01}
            onChange={(v) =>
              setReplacement({ anchor: { ...replacement.anchor, y: v } })
            }
          />

          {/* Offset */}
          <Slider
            label="Offset X"
            value={replacement.offset.x}
            min={-0.5}
            max={0.5}
            step={0.01}
            onChange={(v) =>
              setReplacement({ offset: { ...replacement.offset, x: v } })
            }
          />
          <Slider
            label="Offset Y"
            value={replacement.offset.y}
            min={-0.5}
            max={0.5}
            step={0.01}
            onChange={(v) =>
              setReplacement({ offset: { ...replacement.offset, y: v } })
            }
          />

          {/* Scale */}
          <Slider
            label="Tỷ lệ"
            value={replacement.scale}
            min={0.1}
            max={3}
            step={0.05}
            unit="x"
            onChange={(v) => setReplacement({ scale: v })}
          />

          {/* Rotation */}
          <Slider
            label="Xoay bổ sung"
            value={replacement.rotation_offset_deg}
            min={-180}
            max={180}
            step={1}
            unit="°"
            onChange={(v) => setReplacement({ rotation_offset_deg: v })}
          />

          {/* Opacity */}
          <Slider
            label="Độ mờ"
            value={replacement.opacity}
            min={0}
            max={1}
            step={0.01}
            unit="%"
            onChange={(v) => setReplacement({ opacity: v })}
          />

          {/* Fit mode */}
          <div>
            <label className="text-xs text-gray-400">Chế độ fit</label>
            <div className="grid grid-cols-3 gap-1 mt-1">
              {FIT_MODES.map((fm) => (
                <button
                  key={fm.value}
                  onClick={() => setReplacement({ fit_mode: fm.value })}
                  className={`px-2 py-1 text-xs rounded ${
                    replacement.fit_mode === fm.value
                      ? "bg-blue-600 text-white"
                      : "bg-gray-800 text-gray-300 hover:bg-gray-700"
                  }`}
                >
                  {fm.label}
                </button>
              ))}
            </div>
          </div>

          {/* Clip mode */}
          <div>
            <label className="text-xs text-gray-400">Chế độ clip</label>
            <div className="space-y-1 mt-1">
              {CLIP_MODES.map((cm) => (
                <button
                  key={cm.value}
                  onClick={() =>
                    setReplacement({ clip_mode: cm.value })
                  }
                  className={`w-full px-2 py-1.5 text-xs rounded text-left ${
                    replacement.clip_mode === cm.value
                      ? "bg-blue-600 text-white"
                      : "bg-gray-800 text-gray-300 hover:bg-gray-700"
                  }`}
                  title={cm.desc}
                >
                  {cm.label}
                  <span className="block text-[10px] opacity-70">
                    {cm.desc}
                  </span>
                </button>
              ))}
            </div>
          </div>

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
            <button
              onClick={() => resetReplacement()}
              className="w-full py-2 text-sm bg-gray-800 hover:bg-gray-700 rounded"
            >
              Đặt lại
            </button>
            <button
              onClick={() => setScreen("render")}
              className="w-full py-2 text-sm bg-blue-700 hover:bg-blue-600 rounded"
              data-testid="next-render"
            >
              Tiếp: Render →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
