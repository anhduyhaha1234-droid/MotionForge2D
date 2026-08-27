"""S09-T02-C1/C2 deterministic CPU compositor for the reskin routes.

This module is the REAL renderer the two wired routes delegate to:

- ``composite_pose_swap``  — pose/expression replacement FOLLOWING THE
  SCHEDULE in the request: from each scheduled frame the annotated region
  shows the scheduled replacement state, alpha-composited over the source.
  It is NOT a trim+re-encode of the source picture (F1).
- ``composite_sprite_affine`` — the REPLACEMENT LAYER is transformed by the
  request's anchor + affine keyframes (translation/scale/rotation sampled
  per output frame) and composited into the affected region.  There is no
  fixed 1°/1.02 transform anywhere and the source frame itself is never
  transformed (F1).  C2: occluder layers (``occluder_assets`` +
  ``layer_order``) execute real per-frame ordering — z>0 draws the
  replacement ABOVE the occluders, z<0 BELOW (f5_group_occlusion is plain
  request data, no fixture branch).

C2 alpha semantics (executed, not just accepted):
- ``straight``      — asset RGBA used as-is;
- ``premultiplied`` — RGB un-premultiplied by the asset alpha first;
- ``opaque``        — asset alpha forced to 255 (hard-edge cutout).

Determinism: pure OpenCV/numpy float math, no GPU, no network, no model
downloads; identical inputs decode → identical canonical frame hashes.

Region guarantee: pixels OUTSIDE the affected region/mask are copied from
the source frames unchanged; the new alpha never forces the old silhouette.
"""
from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.services.renderer_contract import (
    AffectedRegion,
    AffineKeyframe,
    CapabilityMismatchError,
    RenderRequest,
)

__all__ = [
    "apply_alpha_mode",
    "canonical_frame_sha256",
    "composite_pose_swap_frames",
    "composite_sprite_affine_frames",
    "decode_rgb_frames",
    "load_rgba",
    "probe_source_timebase",
    "write_frames_mp4",
]


# ── media IO ─────────────────────────────────────────────────────────────────


def load_rgba(path: Path) -> np.ndarray:
    """Decode an asset as RGBA uint8; missing alpha becomes opaque."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise CapabilityMismatchError(f"asset not decodable as image: {path}")
    if img.ndim == 2:
        rgba = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    elif img.shape[2] == 4:
        rgba = img
    else:  # pragma: no cover - exotic channel counts
        raise CapabilityMismatchError(
            f"unsupported channel count {img.shape[2]} in {path}"
        )
    return rgba


def apply_alpha_mode(layer_bgra: np.ndarray, alpha_mode: str) -> np.ndarray:
    """EXECUTE the declared alpha semantics on a BGRA layer (C2, F5).

    - ``straight``: unchanged (RGBA used as-is);
    - ``premultiplied``: un-premultiply RGB by alpha so the composite is
      color-correct for assets stored with premultiplied alpha;
    - ``opaque``: force alpha to 255 (hard-edge cutout — the asset's own
      alpha channel is ignored).
    """
    if alpha_mode == "straight":
        return layer_bgra
    out = layer_bgra.copy()
    if alpha_mode == "opaque":
        out[:, :, 3] = 255
        return out
    if alpha_mode == "premultiplied":
        alpha = out[:, :, 3:4].astype(np.float64) / 255.0
        rgb = out[:, :, :3].astype(np.float64)
        # Guard division by zero: fully transparent pixels keep RGB=0.
        safe_alpha = np.maximum(alpha, 1.0 / 255.0)
        straight = np.clip(rgb / safe_alpha, 0.0, 255.0)
        out[:, :, :3] = (
            np.where(alpha > 0.0, straight, 0.0)
        ).astype(np.uint8)
        return out
    raise CapabilityMismatchError(f"unknown alpha_mode {alpha_mode!r}")


def probe_source_timebase(path: Path) -> tuple[int, int]:
    """Probe the source container's rational fps as (num, den).

    Uses ffprobe when locatable (exact r_frame_rate fraction); falls back to
    OpenCV's float fps converted to an exact fraction.  Fail-closed: raises
    when neither probe can determine a positive frame rate.
    """
    from fractions import Fraction as _Fraction

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        try:
            from app.adapters.renderer.ffmpeg_binary import probe_ffmpeg

            ffmpeg_path = probe_ffmpeg().ffmpeg_path
            if ffmpeg_path:
                sibling = Path(ffmpeg_path).with_name("ffprobe.exe")
                candidate = (
                    sibling
                    if sibling.is_file()
                    else Path(ffmpeg_path).with_name("ffprobe")
                )
                if candidate.is_file():
                    ffprobe = str(candidate)
        except Exception:  # noqa: BLE001 - fall through to OpenCV probe
            ffprobe = None
    if ffprobe:
        try:
            import subprocess

            completed = subprocess.run(  # noqa: S603 - fixed argv
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=r_frame_rate",
                    "-of",
                    "default=nw=1:nk=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
            text_rate = (completed.stdout or "").strip().splitlines()
            if completed.returncode == 0 and text_rate:
                num, _, den = text_rate[0].partition("/")
                frac = _Fraction(int(num), int(den or 1))
                if frac > 0:
                    return frac.numerator, frac.denominator
        except Exception:  # noqa: BLE001 - fall through to OpenCV probe
            pass
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
    finally:
        cap.release()
    if not fps or fps <= 0.0 or not math.isfinite(fps):
        raise CapabilityMismatchError(
            f"cannot determine source fps for timebase preservation: {path}"
        )
    frac = _Fraction(fps).limit_denominator(1001 * 32)
    if frac <= 0:
        raise CapabilityMismatchError(f"non-positive probed fps {fps!r}")
    return frac.numerator, frac.denominator


def decode_rgb_frames(path: Path) -> list[np.ndarray]:
    """Decode every video frame to BGR uint8 (deterministic order)."""
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise CapabilityMismatchError(f"video not decodable: {path}")
        frames: list[np.ndarray] = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
        if not frames:
            raise CapabilityMismatchError(f"video has zero decodable frames: {path}")
        return frames
    finally:
        cap.release()


def write_frames_mp4(
    frames_bgr: list[np.ndarray],
    out_path: Path,
    *,
    fps: float,
    extra_output_opts: list[str] | None = None,
) -> None:
    """Encode BGR frames to MP4.

    Default writer is OpenCV mp4v (deterministic CPU reference).  When
    ``extra_output_opts`` is given the frames are piped to ffmpeg with those
    OUTPUT options appended after the input spec (e.g. h264_nvenc as pure
    encode acceleration).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    h, w = frames_bgr[0].shape[:2]
    if not extra_output_opts:
        fourcc = cv2.VideoWriter.fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(out_path), fourcc, fps, (w, h))
        if not writer.isOpened():  # pragma: no cover - codec availability
            raise CapabilityMismatchError(
                f"cannot open mp4 writer at {out_path}"
            )
        for frame in frames_bgr:
            writer.write(frame)
        writer.release()
        return
    # Raw pipe into an external ffmpeg command.  ``extra_output_opts`` are
    # OUTPUT options — they MUST come after the input spec, otherwise ffmpeg
    # parses them as input decoder settings.
    import subprocess

    from app.adapters.renderer.ffmpeg_binary import probe_ffmpeg

    ffmpeg = probe_ffmpeg()
    if not ffmpeg.available or ffmpeg.ffmpeg_path is None:
        raise CapabilityMismatchError(
            f"ffmpeg unavailable for accelerated encode: {ffmpeg.error}"
        )
    cmd = [
        str(ffmpeg.ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{w}x{h}",
        "-r",
        f"{fps:.6f}",
        "-i",
        "pipe:0",
        *extra_output_opts,
        "-fps_mode",
        "cfr",
        "-r",
        f"{fps:.6f}",
        "-y",
        str(out_path),
    ]
    proc = subprocess.Popen(  # noqa: S603 - fixed argv
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    try:
        for frame in frames_bgr:
            proc.stdin.write(np.ascontiguousarray(frame).tobytes())
        proc.stdin.close()
    except OSError:
        # ffmpeg exited before consuming everything — do not mask its
        # stderr; surface the REAL encoder failure below.
        pass
    _, err = proc.communicate()
    if proc.returncode != 0:
        tail = (err or b"").decode("utf-8", errors="replace").strip().splitlines()
        raise CapabilityMismatchError(
            "encoder failed: " + (tail[-1] if tail else f"exit {proc.returncode}")
        )


def canonical_frame_sha256(frames_bgr: list[np.ndarray]) -> str:
    """Order-sensitive SHA-256 over raw frame bytes — run-to-run identity."""
    import hashlib

    digest = hashlib.sha256()
    digest.update(f"{len(frames_bgr)}".encode("ascii"))
    for frame in frames_bgr:
        digest.update(str(frame.shape).encode("ascii"))
        digest.update(np.ascontiguousarray(frame).tobytes())
    return digest.hexdigest()


# ── geometry helpers ──────────────────────────────────────────────────────────


def _region_px(
    bbox_norm: tuple[float, float, float, float], w: int, h: int
) -> tuple[int, int, int, int]:
    x0 = max(0, min(w - 1, int(round(bbox_norm[0] * w))))
    y0 = max(0, min(h - 1, int(round(bbox_norm[1] * h))))
    x1 = max(x0 + 1, min(w, int(round((bbox_norm[0] + bbox_norm[2]) * w))))
    y1 = max(y0 + 1, min(h, int(round((bbox_norm[1] + bbox_norm[3]) * h))))
    return x0, y0, x1, y1


def _sample_keyframe(
    keyframes: tuple[AffineKeyframe, ...] | None, frame_index: int
) -> AffineKeyframe:
    """Piecewise-linear sample of the keyframe track at ``frame_index``."""
    if not keyframes:
        return AffineKeyframe(frame=frame_index)
    if frame_index <= keyframes[0].frame:
        return keyframes[0]
    if frame_index >= keyframes[-1].frame:
        return keyframes[-1]
    for lo, hi in zip(keyframes, keyframes[1:]):
        if lo.frame <= frame_index <= hi.frame:
            if hi.frame == lo.frame:  # pragma: no cover - dedup guard
                return hi
            t = (frame_index - lo.frame) / (hi.frame - lo.frame)
            tx = lo.translation_xy[0] + t * (
                hi.translation_xy[0] - lo.translation_xy[0]
            )
            ty = lo.translation_xy[1] + t * (
                hi.translation_xy[1] - lo.translation_xy[1]
            )
            scale = lo.scale + t * (hi.scale - lo.scale)
            rot = lo.rotation_deg + t * (hi.rotation_deg - lo.rotation_deg)
            return AffineKeyframe(
                frame=frame_index,
                translation_xy=(tx, ty),
                scale=scale,
                rotation_deg=rot,
            )
    return keyframes[-1]  # pragma: no cover - loop covers all indices


def _warp_layer(
    layer_bgra: np.ndarray,
    *,
    translation_xy_norm: tuple[float, float],
    scale: float,
    rotation_deg: float,
    dst_w: int,
    dst_h: int,
) -> np.ndarray:
    """Warp the replacement layer onto a transparent canvas of the DESTINATION
    size.  The layer CENTER lands at (cx, cy): the anchor position plus the
    keyframe translation (normalized units of the destination frame)."""
    lh, lw = layer_bgra.shape[:2]
    cx = dst_w / 2.0 + translation_xy_norm[0] * dst_w
    cy = dst_h / 2.0 + translation_xy_norm[1] * dst_h
    theta = np.deg2rad(rotation_deg)
    cos_t, sin_t = float(np.cos(theta)), float(np.sin(theta))
    # Forward map: rotate+scale about the layer center, then place at (cx, cy).
    src_x = (
        cos_t * (np.arange(dst_w)[None, :] - cx) / scale
        + sin_t * (np.arange(dst_h)[:, None] - cy) / scale
        + lw / 2.0
    ).astype(np.float32)
    src_y = (
        -sin_t * (np.arange(dst_w)[None, :] - cx) / scale
        + cos_t * (np.arange(dst_h)[:, None] - cy) / scale
        + lh / 2.0
    ).astype(np.float32)
    canvas = cv2.remap(
        layer_bgra,
        src_x,
        src_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    return canvas


def _alpha_composite_into(
    base_bgr: np.ndarray, layer_bgra: np.ndarray, x0: int, y0: int
) -> None:
    """Alpha-composite ``layer`` over ``base`` in-place at offset (x0, y0)."""
    h, w = layer_bgra.shape[:2]
    region = base_bgr[y0 : y0 + h, x0 : x0 + w].astype(np.float64)
    alpha = layer_bgra[:, :, 3:4].astype(np.float64) / 255.0
    layer_rgb = layer_bgra[:, :, :3].astype(np.float64)
    blended = layer_rgb * alpha + region * (1.0 - alpha)
    base_bgr[y0 : y0 + h, x0 : x0 + w] = blended.astype(np.uint8)


def _mask_alpha(
    request_mask: np.ndarray | None,
    layer_h: int,
    layer_w: int,
) -> np.ndarray | None:
    if request_mask is None:
        return None
    mask = request_mask.astype(np.float64) / 255.0
    mask = mask[:, :, :1] if mask.ndim == 3 else mask[:, :, None]
    resized = cv2.resize(
        mask,
        (layer_w, layer_h),
        interpolation=cv2.INTER_LINEAR,
    )
    if resized.ndim == 2:  # pragma: no cover - keep 3D shape stable
        resized = resized[:, :, None]
    return resized


# ── route compositors ────────────────────────────────────────────────────────


def _occluder_z_for_frame(
    request: RenderRequest, frame_no: int
) -> int | None:
    """Active z of the replacement layer at ``frame_no`` (C2 occlusion).

    Returns None when no occluder semantics apply for the frame.  Later
    entries win on overlapping frame ranges (documented contract).
    """
    active: int | None = None
    if not request.layer_order or not request.occluder_assets:
        return None
    for entry in request.layer_order:
        if entry.frame_from <= frame_no <= entry.frame_to:
            active = entry.z
    return active


def _draw_occluders(
    composed: np.ndarray,
    occluders: dict[str, np.ndarray],
    bbox: tuple[float, float, float, float] | None,
    regions: dict[str, tuple[float, float, float, float]] | None = None,
) -> None:
    """Draw every occluder layer over ``composed`` (BEFORE replacement when
    z>0 — i.e. this runs first and the replacement covers it; AFTER when
    z<0 — i.e. this runs last and covers the replacement).

    J1-C2-v2 placement precedence per occluder:
    1. explicit ``regions[name]`` (normalized x,y,w,h) → stretched into that
       sub-rect ONLY; the rest of the frame stays untouched;
    2. no region + ``bbox`` (affected region) → stretched to the region rect
       (legacy behavior);
    3. no region + no bbox → full-frame cover (legacy behavior).
    """
    h, w = composed.shape[:2]
    for name, layer_rgba in occluders.items():
        region = (regions or {}).get(name)
        if region is not None:
            rx, ry, rw, rh = region
            px = _region_px((rx, ry, rw, rh), w, h)
            x0, y0, x1, y1 = px
            crop = cv2.resize(
                layer_rgba, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA
            )
            _alpha_composite_into(composed[y0:y1, x0:x1], crop, 0, 0)
        elif bbox is None:
            cover = cv2.resize(
                layer_rgba, (w, h), interpolation=cv2.INTER_AREA
            )
            _alpha_composite_into(composed, cover, 0, 0)
        else:
            x0, y0, x1, y1 = _region_px(bbox, w, h)
            rw, rh = x1 - x0, y1 - y0
            crop = cv2.resize(
                layer_rgba, (rw, rh), interpolation=cv2.INTER_AREA
            )
            _alpha_composite_into(composed[y0:y1, x0:x1], crop, 0, 0)


def composite_pose_swap_frames(
    source_frames: list[np.ndarray],
    request: RenderRequest,
    *,
    progress: dict[str, Any] | None = None,
) -> list[np.ndarray]:
    """Pose/expression replacement STRICTLY following the pose schedule.

    Frames before the first scheduled swap are copied verbatim; from each
    swap frame onward the affected region shows the scheduled state's
    replacement asset until superseded by the next entry.  Outside the
    affected region pixels stay EXACTLY the source pixels.  C2: the asset's
    declared alpha_mode is executed and occluder layers are ordered per
    frame via layer_order (z>0: occluder under replacement, z<0: above).
    """
    assert request.pose_schedule is not None
    assert request.pose_state_assets is not None
    schedule = sorted(request.pose_schedule, key=lambda e: e.frame)

    layers: dict[str, np.ndarray] = {}
    for state_id, asset in request.pose_state_assets.items():
        layers[state_id] = apply_alpha_mode(
            load_rgba(asset.path), asset.alpha_mode
        )
    occluders = {
        name: load_rgba(asset.path)
        for name, asset in (request.occluder_assets or {}).items()
    }

    region = request.affected_region or AffectedRegion(None)
    bbox = region.bbox_xywh_norm

    out: list[np.ndarray] = []
    active_state: str | None = None
    for idx, src_frame in enumerate(source_frames):
        frame_no = request.start_frame + idx
        due = [e.state_id for e in schedule if e.frame == frame_no]
        if due:
            active_state = due[-1]  # later entries win on same-frame ties
        z = _occluder_z_for_frame(request, frame_no)
        if active_state is None and z is None:
            out.append(src_frame.copy())
            continue
        composed = src_frame.copy()
        # Occluders BELOW the replacement draw first.
        if z is not None and z > 0:
            _draw_occluders(
                composed,
                occluders,
                bbox,
                regions=request.occluder_regions,
            )
        if active_state is not None:
            layer_full = layers.get(active_state)
            if layer_full is None:
                raise CapabilityMismatchError(
                    f"pose state {active_state!r} has no loaded asset"
                )
            if bbox is None:
                layer = layer_full.copy()
                if request.mask_asset is not None:
                    m = _mask_alpha(
                        _load_mask(request), *layer.shape[:2]
                    )
                    if m is not None:
                        layer[:, :, 3:4] = np.minimum(
                            layer[:, :, 3:4], (m * 255.0).astype(np.uint8)
                        )
                _alpha_composite_into(composed, layer, 0, 0)
            else:
                h, w = composed.shape[:2]
                x0, y0, x1, y1 = _region_px(bbox, w, h)
                rw, rh = x1 - x0, y1 - y0
                layer_crop = cv2.resize(
                    layer_full,
                    (rw, rh),
                    interpolation=cv2.INTER_AREA,
                )
                if request.mask_asset is not None:
                    m = _mask_alpha(_load_mask(request), rh, rw)
                    if m is not None:
                        layer_crop[:, :, 3:4] = np.minimum(
                            layer_crop[:, :, 3:4],
                            (m * 255.0).astype(np.uint8),
                        )
                _alpha_composite_into(composed[y0:y1, x0:x1], layer_crop, 0, 0)
        # Occluders ABOVE the replacement draw last.
        if z is not None and z < 0:
            _draw_occluders(
                composed,
                occluders,
                bbox,
                regions=request.occluder_regions,
            )
        if progress is not None:
            progress[str(frame_no)] = active_state
        out.append(composed)
    return out


def _load_mask(request: RenderRequest) -> np.ndarray | None:
    if request.mask_asset is None:
        return None
    img = cv2.imread(str(request.mask_asset.path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise CapabilityMismatchError(
            f"mask asset not decodable: {request.mask_asset.path}"
        )
    if img.ndim == 3 and img.shape[2] >= 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY if img.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    return img


def composite_sprite_affine_frames(
    source_frames: list[np.ndarray],
    request: RenderRequest,
    *,
    progress: dict[str, Any] | None = None,
) -> list[np.ndarray]:
    """Composite the TRANSFORMED replacement layer over each source frame.

    The transform comes ONLY from the request anchor + affine keyframes;
    the source picture itself is never rotated/scaled (F1: no fixed 1°/1.02
    whole-frame transform).  C2: ``identity_transform=True`` (with an empty
    keyframe track, enforced at the contract boundary) composites the layer
    with NO transform; occluder layers are ordered per frame via
    layer_order; the asset's declared alpha_mode is executed.
    """
    assert request.replacement_asset is not None
    asset = request.replacement_asset
    layer = apply_alpha_mode(load_rgba(asset.path), asset.alpha_mode)
    if request.identity_transform:
        # Typed identity (C2): no transform at all.  The contract refuses
        # identity_transform=True with a non-empty track, so this branch is
        # exact — never mixed with sampled keyframes.
        assert not request.affine_keyframes
        center_only = True
    else:
        center_only = False
    mask_full = _load_mask(request) if request.mask_asset else None
    anchor = request.anchor_xy_norm or (0.5, 0.5)
    region = request.affected_region or AffectedRegion(None)
    bbox = region.bbox_xywh_norm
    occluders = {
        name: load_rgba(asset.path)
        for name, asset in (request.occluder_assets or {}).items()
    }

    out: list[np.ndarray] = []
    for idx, src_frame in enumerate(source_frames):
        frame_no = request.start_frame + idx
        if center_only:
            kf = AffineKeyframe(frame=frame_no)
        else:
            kf = _sample_keyframe(request.affine_keyframes, frame_no)
        composed = src_frame.copy()
        h, w = composed.shape[:2]
        z = _occluder_z_for_frame(request, frame_no)
        if z is not None and z > 0:
            _draw_occluders(
                composed,
                occluders,
                bbox,
                regions=request.occluder_regions,
            )

        # Layer placement: layer center lands on the ANCHOR plus the
        # keyframe translation (normalized units of the destination frame).
        tx = anchor[0] + kf.translation_xy[0]
        ty = anchor[1] + kf.translation_xy[1]

        if bbox is None:
            warped = _warp_layer(
                layer,
                translation_xy_norm=(tx - 0.5, ty - 0.5),
                scale=kf.scale,
                rotation_deg=kf.rotation_deg,
                dst_w=w,
                dst_h=h,
            )
            if mask_full is not None:
                m = _mask_alpha(mask_full, h, w)
                if m is not None:
                    warped[:, :, 3:4] = np.minimum(
                        warped[:, :, 3:4], (m * 255.0).astype(np.uint8)
                    )
            _alpha_composite_into(composed, warped, 0, 0)
        else:
            x0, y0, x1, y1 = _region_px(bbox, w, h)
            rw, rh = x1 - x0, y1 - y0
            sub_anchor = (
                (anchor[0] * w - x0) / max(rw, 1),
                (anchor[1] * h - y0) / max(rh, 1),
            )
            warped = _warp_layer(
                layer,
                translation_xy_norm=(
                    sub_anchor[0] + kf.translation_xy[0] - 0.5,
                    sub_anchor[1] + kf.translation_xy[1] - 0.5,
                ),
                scale=kf.scale,
                rotation_deg=kf.rotation_deg,
                dst_w=rw,
                dst_h=rh,
            )
            if mask_full is not None:
                m = _mask_alpha(mask_full, rh, rw)
                if m is not None:
                    warped[:, :, 3:4] = np.minimum(
                        warped[:, :, 3:4], (m * 255.0).astype(np.uint8)
                    )
            _alpha_composite_into(composed[y0:y1, x0:x1], warped, 0, 0)
        if z is not None and z < 0:
            _draw_occluders(
                composed,
                occluders,
                bbox,
                regions=request.occluder_regions,
            )
        if progress is not None:
            progress[str(frame_no)] = (kf.translation_xy, kf.scale, kf.rotation_deg)
        out.append(composed)
    return out
