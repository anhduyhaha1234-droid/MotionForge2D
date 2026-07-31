"use client";

/**
 * CompositeCanvas — Konva-based composite preview
 *
 * Renders: original frame → mask overlay → replacement image → bbox → centroid → anchor
 * All transforms use source video coordinates; Konva scales to viewport.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import Konva from "konva";
import { createViewportTransform } from "@/lib/coordinates";
import type { FrameMotion, ReplacementConfig, ClipMode } from "@/lib/api";

/* ── Types ─────────────────────────────────────────────────────────────── */

interface CompositeCanvasProps {
  frameUrl: string | null;
  maskUrl: string | null;
  replacementUrl: string | null;
  sequenceFrameUrl: string | null;
  frameMotion: FrameMotion | null;
  replacement: ReplacementConfig;
  videoWidth: number;
  videoHeight: number;
  previewMode: "original" | "mask" | "result" | "comparison";
}

interface TransformResult {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
  opacity: number;
}

/* ── Transform math ────────────────────────────────────────────────────── */

function computeReplacementTransform(
  motion: FrameMotion,
  rep: ReplacementConfig,
  assetNaturalW: number,
  assetNaturalH: number,
  frameW: number,
  frameH: number,
): TransformResult {
  // 1. Tracked centroid
  const cx = motion.centroid_x;
  const cy = motion.centroid_y;

  // 2. Bbox scaled by tracked scale
  const bboxW = motion.bbox.width * motion.scale_x;
  const bboxH = motion.bbox.height * motion.scale_y;

  // 3. Target size based on fit_mode
  let targetW: number;
  let targetH: number;
  if (rep.fit_mode === "contain") {
    const ratio = Math.min(bboxW / assetNaturalW, bboxH / assetNaturalH);
    targetW = assetNaturalW * ratio;
    targetH = assetNaturalH * ratio;
  } else if (rep.fit_mode === "cover") {
    const ratio = Math.max(bboxW / assetNaturalW, bboxH / assetNaturalH);
    targetW = assetNaturalW * ratio;
    targetH = assetNaturalH * ratio;
  } else {
    // stretch
    targetW = bboxW;
    targetH = bboxH;
  }

  // 4. Apply scale multiplier
  const finalW = targetW * rep.scale;
  const finalH = targetH * rep.scale;

  // 5. Anchor pixel offset
  const anchorPxX = finalW * rep.anchor.x;
  const anchorPxY = finalH * rep.anchor.y;

  // 6. Position
  const posX = cx - anchorPxX + rep.offset.x * frameW;
  const posY = cy - anchorPxY + rep.offset.y * frameH;

  // 7. Rotation
  const totalRotation = motion.rotation_deg + rep.rotation_offset_deg;

  return {
    x: posX,
    y: posY,
    width: finalW,
    height: finalH,
    rotation: totalRotation,
    opacity: rep.opacity,
  };
}

/* ── Clip helper ───────────────────────────────────────────────────────── */

function clipOpFor(mode: ClipMode): string {
  switch (mode) {
    case "asset_alpha":
      return "source-over";
    case "original_mask":
      return "destination-in";
    case "intersection":
      return "source-in";
  }
}

/* ── Component ─────────────────────────────────────────────────────────── */

export function CompositeCanvas({
  frameUrl,
  maskUrl,
  replacementUrl,
  sequenceFrameUrl,
  frameMotion,
  replacement,
  videoWidth,
  videoHeight,
  previewMode,
}: CompositeCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<Konva.Stage | null>(null);
  const layerRef = useRef<Konva.Layer | null>(null);

  const [frameImg, setFrameImg] = useState<HTMLImageElement | null>(null);
  const [maskImg, setMaskImg] = useState<HTMLImageElement | null>(null);
  const [repImg, setRepImg] = useState<HTMLImageElement | null>(null);
  const [sequenceFrameImg, setSequenceFrameImg] = useState<HTMLImageElement | null>(null);

  /* ── Load images ─────────────────────────────────────────────────────── */

  useEffect(() => {
    if (!frameUrl) {
      setFrameImg(null);
      return;
    }
    const img = new window.Image();
    img.crossOrigin = "anonymous";
    img.onload = () => setFrameImg(img);
    img.onerror = () => setFrameImg(null);
    img.src = frameUrl;
  }, [frameUrl]);

  useEffect(() => {
    if (!maskUrl) {
      setMaskImg(null);
      return;
    }
    const img = new window.Image();
    img.crossOrigin = "anonymous";
    img.onload = () => setMaskImg(img);
    img.onerror = () => setMaskImg(null);
    img.src = maskUrl;
  }, [maskUrl]);

  useEffect(() => {
    if (!replacementUrl) {
      setRepImg(null);
      return;
    }
    const img = new window.Image();
    img.crossOrigin = "anonymous";
    img.onload = () => setRepImg(img);
    img.onerror = () => setRepImg(null);
    img.src = replacementUrl;
  }, [replacementUrl]);

  useEffect(() => {
    if (!sequenceFrameUrl) {
      setSequenceFrameImg(null);
      return;
    }
    const img = new window.Image();
    img.crossOrigin = "anonymous";
    img.onload = () => setSequenceFrameImg(img);
    img.onerror = () => setSequenceFrameImg(null);
    img.src = sequenceFrameUrl;
  }, [sequenceFrameUrl]);

  /* ── Stage setup & resize ────────────────────────────────────────────── */

  const getContainerSize = useCallback(() => {
    const el = containerRef.current;
    if (!el) return { w: 640, h: 480 };
    const rect = el.getBoundingClientRect();
    return { w: Math.floor(rect.width), h: Math.floor(rect.height) };
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const { w, h } = getContainerSize();
    const stage = new Konva.Stage({ container: el, width: w, height: h });
    const layer = new Konva.Layer();
    stage.add(layer);
    stageRef.current = stage;
    layerRef.current = layer;

    const ro = new ResizeObserver(() => {
      const { w: nw, h: nh } = getContainerSize();
      stage.width(nw);
      stage.height(nh);
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      stage.destroy();
      stageRef.current = null;
      layerRef.current = null;
    };
  }, [getContainerSize]);

  /* ── Render scene ────────────────────────────────────────────────────── */

  useEffect(() => {
    const layer = layerRef.current;
    const stage = stageRef.current;
    if (!layer || !stage) return;

    layer.destroyChildren();

    const stageW = stage.width();
    const stageH = stage.height();
    const vt = createViewportTransform(videoWidth, videoHeight, stageW, stageH);
    const dw = videoWidth * vt.scale;
    const dh = videoHeight * vt.scale;
    const ox = vt.offsetX;
    const oy = vt.offsetY;

    // Choose active replacement image based on mode
    const activeRepImg = replacement.mode === "frame_sequence" ? sequenceFrameImg : repImg;

    // Checkerboard background
    const bgGroup = new Konva.Group({ x: ox, y: oy, width: dw, height: dh });
    const CHECK = 12;
    const cols = Math.ceil(dw / CHECK);
    const rows = Math.ceil(dh / CHECK);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        bgGroup.add(
          new Konva.Rect({
            x: c * CHECK,
            y: r * CHECK,
            width: CHECK,
            height: CHECK,
            fill: (r + c) % 2 === 0 ? "#1a1a2e" : "#16162a",
          }),
        );
      }
    }
    layer.add(bgGroup);

    // Helper: draw frame image scaled to viewport
    const drawFrame = () => {
      if (!frameImg) return;
      const konvaImg = new Konva.Image({
        x: ox,
        y: oy,
        image: frameImg,
        width: dw,
        height: dh,
      });
      layer.add(konvaImg);
    };

    if (previewMode === "original") {
      drawFrame();
      layer.batchDraw();
      return;
    }

    if (previewMode === "mask") {
      drawFrame();
      if (maskImg) {
        const m = new Konva.Image({
          x: ox,
          y: oy,
          image: maskImg,
          width: dw,
          height: dh,
          opacity: 0.5,
          // green tint via globalCompositeOperation workaround:
          // Konva doesn't support composite ops directly, so use opacity
        });
        layer.add(m);
      }
      layer.batchDraw();
      return;
    }

    // "result" or "comparison" — draw composite
    const drawComposite = (offsetX: number) => {
      // Background frame
      if (frameImg) {
        layer.add(
          new Konva.Image({
            x: offsetX + ox,
            y: oy,
            image: frameImg,
            width: dw,
            height: dh,
          }),
        );
      }

      // Mask overlay (semi-transparent green)
      if (maskImg) {
        // We'll tint green by drawing a green rect then the mask on top
        // Actually, just show the mask at low opacity
        layer.add(
          new Konva.Image({
            x: offsetX + ox,
            y: oy,
            image: maskImg,
            width: dw,
            height: dh,
            opacity: 0.35,
          }),
        );
      }

      // Replacement image with transform
      if (activeRepImg && frameMotion) {
        const tf = computeReplacementTransform(
          frameMotion,
          replacement,
          activeRepImg.naturalWidth,
          activeRepImg.naturalHeight,
          videoWidth,
          videoHeight,
        );

        // Scale from source coords to viewport coords
        const scaledX = tf.x * vt.scale + offsetX + ox;
        const scaledY = tf.y * vt.scale + oy;
        const scaledW = tf.width * vt.scale;
        const scaledH = tf.height * vt.scale;

        // Center of the replacement for rotation
        const centerX = scaledX + scaledW / 2;
        const centerY = scaledY + scaledH / 2;

        const repNode = new Konva.Image({
          x: scaledX,
          y: scaledY,
          width: scaledW,
          height: scaledH,
          image: activeRepImg,
          opacity: tf.opacity,
          rotation: tf.rotation,
          offsetX: scaledW / 2,
          offsetY: scaledH / 2,
          // Position at center, then offset by half-size to rotate around center
          // Actually: Konva rotation is around (x, y) by default, or (x+offsetX, y+offsetY)
          // We want to rotate around center of the image
          // So set x,y to center, and offsetX/offsetY to half-width/height
        });
        // Fix: position at center
        repNode.x(centerX);
        repNode.y(centerY);
        layer.add(repNode);

        // Bounding box rectangle
        const bbox = frameMotion.bbox;
        const bx = bbox.x * vt.scale + offsetX + ox;
        const by = bbox.y * vt.scale + oy;
        const bw = bbox.width * vt.scale;
        const bh = bbox.height * vt.scale;
        layer.add(
          new Konva.Rect({
            x: bx,
            y: by,
            width: bw,
            height: bh,
            stroke: "#3b82f6",
            strokeWidth: 1.5,
            dash: [5, 3],
            listening: false,
          }),
        );

        // Centroid dot
        const cDotX = frameMotion.centroid_x * vt.scale + offsetX + ox;
        const cDotY = frameMotion.centroid_y * vt.scale + oy;
        layer.add(
          new Konva.Circle({
            x: cDotX,
            y: cDotY,
            radius: 4,
            fill: "#22c55e",
            stroke: "#fff",
            strokeWidth: 1,
          }),
        );

        // Anchor point marker
        const anchorAbsX =
          (frameMotion.centroid_x - tf.width * replacement.anchor.x +
            replacement.offset.x * videoWidth) *
            vt.scale +
          offsetX +
          ox +
          (tf.width * replacement.anchor.x * vt.scale);
        const anchorAbsY =
          (frameMotion.centroid_y - tf.height * replacement.anchor.y +
            replacement.offset.y * videoHeight) *
            vt.scale +
          oy +
          (tf.height * replacement.anchor.y * vt.scale);
        // The anchor point is at the centroid in source coords
        // Actually, the anchor point on the asset that aligns with centroid:
        const anchorOnScreenX = frameMotion.centroid_x * vt.scale + offsetX + ox;
        const anchorOnScreenY = frameMotion.centroid_y * vt.scale + oy;
        layer.add(
          new Konva.Star({
            x: anchorOnScreenX,
            y: anchorOnScreenY,
            numPoints: 4,
            innerRadius: 3,
            outerRadius: 7,
            fill: "#f59e0b",
            stroke: "#fff",
            strokeWidth: 0.5,
          }),
        );

        // Replacement outline (dashed green rect showing placement area)
        layer.add(
          new Konva.Rect({
            x: centerX,
            y: centerY,
            width: scaledW,
            height: scaledH,
            offsetX: scaledW / 2,
            offsetY: scaledH / 2,
            stroke: "#22c55e",
            strokeWidth: 1,
            dash: [3, 3],
            rotation: tf.rotation,
            listening: false,
          }),
        );
      }
    };

    if (previewMode === "comparison") {
      // Side-by-side: left = original, right = result
      const halfW = stageW / 2;
      // Draw original on left half
      if (frameImg) {
        layer.add(
          new Konva.Image({
            x: ox,
            y: oy,
            image: frameImg,
            width: halfW - ox,
            height: dh,
            crop: { x: 0, y: 0, width: videoWidth / 2, height: videoHeight },
          }),
        );
      }
      // Divider line
      layer.add(
        new Konva.Line({
          points: [halfW, oy, halfW, oy + dh],
          stroke: "#555",
          strokeWidth: 1,
          dash: [4, 4],
        }),
      );
      // Draw composite on right half
      drawComposite(halfW);

      // Label
      layer.add(
        new Konva.Text({
          x: 8,
          y: 8,
          text: "Ảnh gốc",
          fontSize: 12,
          fill: "#aaa",
          fontFamily: "sans-serif",
        }),
      );
      layer.add(
        new Konva.Text({
          x: halfW + 8,
          y: 8,
          text: "Kết quả",
          fontSize: 12,
          fill: "#aaa",
          fontFamily: "sans-serif",
        }),
      );
    } else {
      // "result"
      drawComposite(0);
    }

    layer.batchDraw();
  }, [
    frameImg,
    maskImg,
    repImg,
    sequenceFrameImg,
    frameMotion,
    replacement,
    videoWidth,
    videoHeight,
    previewMode,
  ]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full bg-gray-950"
      data-testid="composite-canvas"
    />
  );
}
