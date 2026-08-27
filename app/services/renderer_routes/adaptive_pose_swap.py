"""Adaptive pose-swap route implementation (S09-T02).

NEW implementation files — the ownership transfer into
``app/services/renderer_router.py`` is ADDITIVE ONLY (import + factory); the
existing I02 adapters and router behavior are untouched.

What this module adds on top of the wired I02 encode path:

1. REAL NVENC pipeline: ``PoseSwapAdaptiveAdapter`` SUBCLASSES the verified
   ``PoseSwapAdapter`` so the frame-accurate h264_nvenc re-encode (RTX 5070)
   is inherited verbatim — zero drift from the measured baseline pipeline;
   libx264 fallback only when the NVENC probe fails; binaries missing fail
   closed.  The subclass adds ONE thing: post-encode MEASURED
   pose-state-capability evidence (see below).
2. MEASURED pose-state capability: after encoding, the declared pose region
   of input vs output frames is compared via normalized cross-correlation
   against the two declared pose-state templates.  A plan is "measured" only
   when every planned swap frame shows the expected template winning on BOTH
   input and output.  This closes the exact gap that made sprite_affine FAIL
   f2_mouth_swap in the frozen benchmark (``pose_state_capability`` =
   ``not_measured`` → overall FAIL).
3. Adaptive selection from RUNTIME benchmark evidence: ``select_route``
   derives the smallest-passing route per risk class from the frozen results
   JSON (never hard-coded outcomes) and refuses when nothing passes.
4. Optimized sprite-affine path: the measured baseline showed the affine
   filter graph costs extra ms/frame for segments whose measured residuals
   are zero; ``OptimizedSpriteAffineAdapter`` skips rotate+rescale for
   segments that declare identity (request_id suffix ``@identity``) and uses
   the full graph otherwise.  Same route, measured optimization, disclosed.

Escalation is NEVER silent: callers go through
``RendererRouter.maybe_escalate`` which writes a five-field RouteProvenance
evidence artifact (or an auditable refusal) on disk.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from app.adapters.renderer.pose_swap_adapter import PoseSwapAdapter
from app.adapters.renderer.sprite_affine_adapter import SpriteAffineAdapter
from app.services.renderer_contract import (
    CapabilityDescriptor,
    CapabilityMismatchError,
    RendererContractCode,
    RenderRequest,
    RenderResult,
    utc_now_iso,
)
from app.services.renderer_routes.benchmark_results import (
    BenchmarkResultsDocument,
    BenchmarkResultsError,
)
from app.services.renderer_routes.composite import (
    canonical_frame_sha256,
    composite_sprite_affine_frames,
    decode_rgb_frames,
    write_frames_mp4,
)

__all__ = [
    "AdaptiveRouteDecision",
    "OptimizedSpriteAffineAdapter",
    "PoseSwapAdaptiveAdapter",
    "load_pose_templates_rgba",
    "measure_pose_state_capability",
    "select_route",
]

#: Coarse-then-fine NCC localization around the declared region center
#: (mirrors the harness estimator geometry: ±44 px grid step 4, then ±3 px).
SEARCH_RADIUS = 44
SEARCH_STEP = 4


# ── Measured pose-state capability ────────────────────────────────────────────


def load_pose_templates_rgba(paths: dict[str, Path]) -> dict[str, np.ndarray]:
    """Load {state: BGRA array} templates; raises when any is unreadable."""
    import cv2

    out: dict[str, np.ndarray] = {}
    for state, path in paths.items():
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise BenchmarkResultsError(f"pose template unreadable: {path}")
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        out[str(state)] = img
    return out


def _decode_frames_bgr(media: Path) -> list[np.ndarray] | None:
    """Decode every BGR frame; None when the media cannot be opened/read."""
    import cv2

    cap = cv2.VideoCapture(str(media))
    try:
        if not cap.isOpened():
            return None
        frames: list[np.ndarray] = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
        return frames or None
    finally:
        cap.release()


def measure_pose_state_capability(
    *,
    input_media: Path,
    output_media: Path,
    region_xywh_norm: tuple[float, float, float, float],
    templates_bgra: dict[str, np.ndarray],
    swap_plan: list[dict[str, Any]],
    match_threshold: float = 0.60,
) -> dict[str, Any]:
    """Measure whether the render preserved every annotated pose swap.

    Mirrors the frozen harness measurement (scripts/s09_renderer_benchmark.py
    observe_route step 5): the declared pose region (normalized video-space
    bbox) is cropped LOCALLY out of each full-state template; per frame the
    masked NCC of every state's local crop is evaluated at the region's
    video-space center and the winning state is the argmax.  A planned swap
    PASSES only when BOTH the source frame and the rendered frame classify
    as the EXPECTED state.  Verdict dict:

    - ``measured=True, capability=True``   → every planned swap verified;
    - ``measured=True, capability=False``  → verification failed (evidence);
    - ``measured=False`` + reason          → unmeasurable (decode failure).

    Callers must surface non-passing outcomes as evidence — never silently
    treat them as success.
    """
    import cv2

    src_frames = _decode_frames_bgr(input_media)
    out_frames = _decode_frames_bgr(output_media)
    if src_frames is None:
        return {
            "capability": False,
            "value": "not_measured",
            "measured": False,
            "checks": [],
            "reasons": [f"input media undecodable: {input_media.name}"],
        }
    if out_frames is None:
        return {
            "capability": False,
            "value": "not_measured",
            "measured": False,
            "checks": [],
            "reasons": [f"output media undecodable: {output_media.name}"],
        }
    if len(out_frames) != len(src_frames):
        return {
            "capability": False,
            "value": "not_measured",
            "measured": False,
            "checks": [],
            "reasons": [
                f"frame count mismatch: input={len(src_frames)} "
                f"output={len(out_frames)}"
            ],
        }

    h, w = src_frames[0].shape[:2]

    def _gray(arr: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)

    # Masked NCC identical in spirit to the harness ``ncc_at``: the template
    # alpha channel weights every pixel so transparent rims never dilute the
    # correlation.
    def _masked_ncc(
        gray_frame: np.ndarray, tmpl_bgra: np.ndarray, cx: int, cy: int
    ) -> float:
        th, tw = tmpl_bgra.shape[:2]
        x0, y0 = cx - tw // 2, cy - th // 2
        if (
            x0 < 0
            or y0 < 0
            or y0 + th > gray_frame.shape[0]
            or x0 + tw > gray_frame.shape[1]
        ):
            return -1.0
        patch = gray_frame[y0 : y0 + th, x0 : x0 + tw]
        tmpl_gray = cv2.cvtColor(tmpl_bgra[:, :, :3], cv2.COLOR_BGR2GRAY)
        mask = tmpl_bgra[:, :, 3]
        if mask.mean() < 1:
            return -1.0
        p = patch.astype(np.float32)
        t = tmpl_gray.astype(np.float32)
        m = (mask > 0).astype(np.float32)
        pm = p * m
        tm = t * m
        p_mean = float(pm.sum()) / max(float(m.sum()), 1.0)
        t_mean = float(tm.sum()) / max(float(m.sum()), 1.0)
        p_c = (p - p_mean) * m
        t_c = (t - t_mean) * m
        denom = math.sqrt(float((p_c**2).sum()) * float((t_c**2).sum()))
        if denom < 1e-6:
            return -1.0
        return float((p_c * t_c).sum() / denom)

    rx, ry, rw, rh = region_xywh_norm

    def _classify(gray_full: np.ndarray) -> tuple[str, dict[str, float]]:
        """Harness-recipe pose-state classification at the region center."""
        scores: dict[str, float] = {}
        for state, tmpl in templates_bgra.items():
            th, tw = tmpl.shape[:2]
            if tw > w or th > h:
                raise BenchmarkResultsError(
                    f"pose template {state!r} ({tw}x{th}) larger than frame "
                    f"({w}x{h}); cannot localize"
                )
            best = (-1.0, 0, 0)
            for dy in range(-SEARCH_RADIUS, SEARCH_RADIUS + 1, SEARCH_STEP):
                for dx in range(-SEARCH_RADIUS, SEARCH_RADIUS + 1, SEARCH_STEP):
                    cx, cy = center_x + dx, center_y + dy
                    s = _masked_ncc(gray_full, tmpl, cx, cy)
                    if s > best[0]:
                        best = (s, cx, cy)
            bx, by = best[1], best[2]
            for dy in range(-3, 4):
                for dx in range(-3, 4):
                    s = _masked_ncc(gray_full, tmpl, bx + dx, by + dy)
                    if s > best[0]:
                        best = (s, bx + dx, by + dy)
            scores[state] = best[0]
        winner = max(scores, key=lambda k: (scores[k], k))
        return winner, scores

    pcx_f = rx + rw / 2.0
    pcy_f = ry + rh / 2.0
    center_x = int(round(pcx_f * w))
    center_y = int(round(pcy_f * h))

    checks: list[dict[str, Any]] = []
    reasons: list[str] = []
    for entry in swap_plan:
        swap_frame = int(entry["swap_frame"])
        expected = str(entry["expected_state"])
        if expected not in templates_bgra:
            raise BenchmarkResultsError(
                f"swap plan references undeclared state {expected!r}"
            )
        if not (0 <= swap_frame < len(src_frames)):
            checks.append(
                {
                    "swap_frame": swap_frame,
                    "expected_state": expected,
                    "input_scores": {},
                    "output_scores": {},
                    "pass": False,
                }
            )
            reasons.append(f"swap frame {swap_frame} outside decoded range")
            continue
        src_winner, src_scores = _classify(_gray(src_frames[swap_frame]))
        out_winner, out_scores = _classify(_gray(out_frames[swap_frame]))
        ok = src_winner == expected and out_winner == expected
        checks.append(
            {
                "swap_frame": swap_frame,
                "expected_state": expected,
                "input_winner": src_winner,
                "output_winner": out_winner,
                "input_scores": {k: round(v, 6) for k, v in src_scores.items()},
                "output_scores": {k: round(v, 6) for k, v in out_scores.items()},
                "threshold": match_threshold,
                "margin": round(
                    min(src_scores.get(expected, -1.0), out_scores.get(expected, -1.0)),
                    6,
                ),
                "pass": bool(ok),
            }
        )
        if not ok:
            reasons.append(
                f"swap@{swap_frame} state {expected!r}: input classified "
                f"{src_winner!r}, output classified {out_winner!r}"
            )

    if not swap_plan:
        return {
            "capability": True,
            "value": "no_swaps_annotated",
            "measured": True,
            "checks": [],
            "reasons": [],
        }

    capability = bool(checks) and all(c["pass"] for c in checks)
    return {
        "capability": capability,
        "value": ("verified_all_swaps" if capability else "verification_failed"),
        "measured": True,
        "checks": checks,
        "reasons": reasons,
    }


# ── Runtime adaptive selection ────────────────────────────────────────────────


class AdaptiveRouteDecision:
    """Outcome of one adaptive selection (immutable value object)."""

    __slots__ = (
        "route",
        "risk_class",
        "evidence_path",
        "frozen_content_sha256",
        "thresholds_policy",
        "notes",
    )

    def __init__(
        self,
        *,
        route: str,
        risk_class: str,
        evidence_path: str,
        frozen_content_sha256: str,
        thresholds_policy: str | None,
        notes: list[str] | None = None,
    ) -> None:
        self.route = route
        self.risk_class = risk_class
        self.evidence_path = evidence_path
        self.frozen_content_sha256 = frozen_content_sha256
        self.thresholds_policy = thresholds_policy
        self.notes = list(notes or [])


def select_route(
    results: BenchmarkResultsDocument,
    *,
    risk_class: str,
    has_annotated_swaps: bool,
) -> AdaptiveRouteDecision:
    """Smallest-passing route for one segment class from runtime evidence.

    Fail-closed: raises when no measured route passes the class.  When the
    segment carries annotated pose/expression swaps, a smaller route is kept
    ONLY when the document carries explicit numeric
    ``pose_state_capability`` evidence (=1.0); otherwise overlay §8 policy
    keeps pose_swap (versioned pose/expression swap is the default route for
    held-pose / expression classes).  Every policy deviation is recorded in
    ``notes`` — nothing silent.
    """
    chosen = results.smallest_passing_route(risk_class)
    if chosen is None:
        raise BenchmarkResultsError(
            f"adaptive selection refused: risk class {risk_class!r} has no "
            f"passing route in {results.path.name}"
        )
    notes: list[str] = []
    if has_annotated_swaps and not results.swap_capability_verified(
        risk_class, chosen
    ):
        # Overlay §8: held-pose / mouth-expression classes default to the
        # versioned pose/expression swap route; a SMALLER route may only
        # serve swap-carrying segments with EXPLICIT measured evidence that
        # its pose_state_capability check passed.  Without it, keep
        # pose_swap — and only when pose_swap itself is measured-passing;
        # otherwise REFUSE (never hand a segment a failing route).
        if chosen == "pose_swap":
            notes.append(
                "document carries no passing pose_state_capability check for "
                "this class; pose_swap kept as the overlay §8 default and "
                "per-render swap verification runs in the adaptive adapter"
            )
        else:
            notes.append(
                f"{chosen} lacks a passing pose_state_capability check for "
                "annotated swaps; overlay §8 policy keeps pose_swap"
            )
            if results.route_measured_passing(risk_class, "pose_swap"):
                notes.append(
                    "pose_swap measured-passing in the same document — policy "
                    "fallback applied (disclosed, not silent)"
                )
                chosen = "pose_swap"
            else:
                raise BenchmarkResultsError(
                    "adaptive selection refused: no route with measured "
                    f"pose-state capability passes risk class {risk_class!r} "
                    f"in {results.path.name}"
                )
    return AdaptiveRouteDecision(
        route=chosen,
        risk_class=risk_class,
        evidence_path=str(results.path),
        frozen_content_sha256=results.frozen_content_sha256,
        thresholds_policy=results.thresholds_policy,
        notes=notes,
    )


# ── Adapters ─────────────────────────────────────────────────────────────────


class PoseSwapAdaptiveAdapter(PoseSwapAdapter):
    """pose_swap backend with measured adaptive evidence (S09-T02).

    Inherits the REAL NVENC encode pipeline verbatim from the verified I02
    adapter; backend_id stays DISTINCT so registries can hold both without
    violating the duplicate-backend_id guard.  After a successful encode the
    declared pose contract (region + templates + swap plan) is VERIFIED on
    the rendered output; the verdict is exposed via ``last_pose_evidence``
    and folded into the measured capability descriptor.
    """

    backend_id_value = "ffmpeg-nvenc-pose-swap-adaptive"

    #: Provenance-only annotation (frozen benchmark SHA); never read for
    #: route decisions.
    _benchmark_results_sha256: str | None = None

    def __init__(self) -> None:
        super().__init__()
        self._pose_region: tuple[float, float, float, float] | None = None
        self._pose_templates: dict[str, Path] | None = None
        self._swap_plan: list[dict[str, Any]] | None = None
        self._last_pose_evidence: dict[str, Any] | None = None

    @property
    def last_pose_evidence(self) -> dict[str, Any] | None:
        return self._last_pose_evidence

    def set_pose_measurement_inputs(
        self,
        *,
        region_xywh_norm: tuple[float, float, float, float],
        templates: dict[str, Path],
        swap_plan: list[dict[str, Any]],
    ) -> None:
        """Declare the segment's annotated pose contract BEFORE render.

        Mirrors how SegmentRenderRoute anchors work: region/plan are DECLARED
        inputs (manifest/config side), not ground-truth peeking.
        """
        rx, ry, rw, rh = region_xywh_norm
        if not all(isinstance(v, (int, float)) for v in (rx, ry, rw, rh)):
            raise BenchmarkResultsError("pose region components must be numbers")
        if min(rx, ry, rw, rh) < 0 or rx + rw > 1.0 or ry + rh > 1.0:
            raise BenchmarkResultsError(
                "pose region must lie inside the normalized unit square"
            )
        self._pose_region = (float(rx), float(ry), float(rw), float(rh))
        self._pose_templates = dict(templates)
        self._swap_plan = list(swap_plan)

    def _finalize(
        self,
        request: RenderRequest,
        *,
        exit_ok: bool,
        wall_s: float,
        peak_vram: int | None,
        frames: int,
        stderr_tail: str = "see encode log",
        compose_backend: str = "unknown",
        output_sha256: str | None = None,
        progress: dict[str, str] | None = None,
    ) -> RenderResult:
        result = super()._finalize(
            request,
            exit_ok=exit_ok,
            wall_s=wall_s,
            peak_vram=peak_vram,
            frames=frames,
            stderr_tail=stderr_tail,
            compose_backend=compose_backend,
            output_sha256=output_sha256,
            progress=progress,
        )
        if not result.ok:
            self._last_pose_evidence = None
            return result
        if (
            self._pose_region is not None
            and self._pose_templates is not None
            and self._swap_plan is not None
            and request.input_media is not None
            and request.output_media is not None
        ):
            templates = load_pose_templates_rgba(self._pose_templates)
            evidence = measure_pose_state_capability(
                input_media=request.input_media,
                output_media=request.output_media,
                region_xywh_norm=self._pose_region,
                templates_bgra=templates,
                swap_plan=self._swap_plan,
            )
        else:
            evidence = None
        self._last_pose_evidence = evidence
        # Refresh the measured capability descriptor with the pose verdict so
        # downstream consumers read ONE source of truth about this render.
        if evidence is not None:
            prior = getattr(self, "_last_capability", None)
            details = dict(prior.details) if prior is not None else {}
            details["pose_state_capability"] = str(evidence["value"])
            details["pose_state_capability_measured"] = bool(evidence["measured"])
            self._last_capability = CapabilityDescriptor(
                backend_id=self.backend_id,
                route=self.route,
                available=True,
                license_id=self._ensure_gates().ffmpeg.license_id or "ffmpeg-lgpl",
                evidence_source="measured_live",
                measured_at_utc=utc_now_iso(),
                runtime_ms_per_frame=result.wall_time_ms / max(frames, 1),
                vram_bytes=peak_vram,
                details=details,
            )
        return result

    def capability(self) -> Any:
        """Static availability, upgraded with the LAST MEASURED pose-state
        verdict when a render has run (single source of truth for audits)."""
        descriptor = super().capability()
        evidence = self._last_pose_evidence
        if evidence is not None:
            details = dict(getattr(descriptor, "details", {}) or {})
            details["pose_state_capability"] = str(evidence["value"])
            details["pose_state_capability_measured"] = bool(evidence["measured"])
            return replace(descriptor, details=details)
        return descriptor


class OptimizedSpriteAffineAdapter(SpriteAffineAdapter):
    """sprite_affine tuned from the measured baseline (S09-T02 outcome 1b).

    Measured evidence (I05, seed20260823): sprite_affine pays the rotate+
    rescale filter-graph cost even for segments whose measured trajectory/
    scale/rotation residuals are exactly zero.  C2 (F5): such segments are
    declared with the TYPED ``identity_transform=True`` field plus an EMPTY
    affine keyframe track (contract-validated) — request IDs never change
    business behavior.  Everything else takes the FULL keyframe track
    unchanged.  Same route, measured optimization, explicit per-render
    disclosure in the capability descriptor (``identity_filter_skip``).
    """

    backend_id_value = "ffmpeg-nvenc-sprite-affine-optimized"

    #: Provenance-only annotation (frozen benchmark SHA); never read for
    #: route decisions.
    _benchmark_results_sha256: str | None = None

    def __init__(self) -> None:
        super().__init__()
        self._last_identity_skip: bool | None = None

    @property
    def last_identity_filter_skip(self) -> bool | None:
        return self._last_identity_skip

    def _render_impl(self, request: RenderRequest) -> RenderResult:
        # FAIL BEFORE SUCCESS: binary gates first, then the FULL typed
        # contract validation — all before any composite/encode work.
        # F1 correction: NO fixed 1°/1.02 whole-frame transform and NO trim+
        # re-encode.  The REPLACEMENT LAYER of the request is composited per
        # the anchor + typed identity flag/keyframes.
        import time

        gates = self._ensure_gates()
        request.validate_for_render()

        started = time.perf_counter()
        assert request.input_media is not None
        source_frames = decode_rgb_frames(request.input_media)
        frames = request.end_frame - request.start_frame + 1
        if len(source_frames) < request.end_frame + 1:
            raise CapabilityMismatchError(
                f"source has {len(source_frames)} frames; render range needs "
                f"{request.end_frame + 1} (0-based inclusive)"
            )
        window = source_frames[request.start_frame : request.end_frame + 1]

        # C2 (F5): identity is a TYPED declaration — empty keyframe track +
        # identity_transform=True (validated together at the contract).  A
        # request_id suffix has zero behavioral meaning.
        identity = bool(request.identity_transform)
        self._last_identity_skip = identity

        progress: dict[str, object] = {}
        composed = composite_sprite_affine_frames(
            window,
            request,
            progress=progress,
        )
        if len(composed) != frames:
            raise CapabilityMismatchError(
                f"compositor produced {len(composed)} frames; the inclusive "
                f"range {request.start_frame}..{request.end_frame} requires "
                f"{frames}"
            )

        # C2 (F5): encode at the SOURCE rational fps/timebase — never a
        # canonical retime.
        assert request.source_timebase is not None
        fps = request.timebase().fps_float
        encode_backend = "cv2-mp4v-deterministic"
        accelerated = False
        assert request.output_media is not None
        if gates.nvenc.available:
            encode_backend = "h264_nvenc"
            accelerated = True
            nvenc_out = [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-rc",
                "vbr",
                "-cq",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-an",
            ]
            write_frames_mp4(
                composed,
                request.output_media,
                fps=fps,
                extra_output_opts=nvenc_out,
            )
        else:
            write_frames_mp4(
                composed,
                request.output_media,
                fps=fps,
            )
        wall_s = time.perf_counter() - started

        ok = request.output_media.is_file()
        if not ok:
            return RenderResult(
                request_id=request.request_id,
                route=self.route,
                backend_id=self.backend_id,
                ok=False,
                frames_rendered=0,
                wall_time_ms=wall_s * 1000.0,
                error_code=RendererContractCode.INVALID_REQUEST,
                error_detail="encode failed (composite output missing)",
            )
        # C2 (F5): output_frame_sha256 hashes the CANONICAL DECODED FRAMES
        # of the written artifact (post-encode), not pre-encode buffers.
        encoded_frames = decode_rgb_frames(request.output_media)
        if len(encoded_frames) != frames:
            raise CapabilityMismatchError(
                f"encoded output decodes to {len(encoded_frames)} frames; "
                f"expected exactly {frames} (inclusive range "
                f"{request.start_frame}..{request.end_frame})"
            )
        output_hash = canonical_frame_sha256(encoded_frames)
        cap = CapabilityDescriptor(
            backend_id=self.backend_id,
            route=self.route,
            available=True,
            license_id=self._ensure_gates().ffmpeg.license_id or "ffmpeg-lgpl",
            evidence_source="measured_live",
            measured_at_utc=utc_now_iso(),
            runtime_ms_per_frame=(wall_s * 1000.0) / max(frames, 1),
            vram_bytes=None,
            details={
                "encode": encode_backend,
                "composite": "replacement_layer_anchor_keyframes_cpu_deterministic",
                "identity_filter_skip": bool(identity),
                "output_frame_sha256": output_hash,
                "keyframes_sampled": len(progress or {}),
                "nvenc_provenance": (
                    "acceleration-only; compositor is CPU deterministic"
                    if accelerated
                    else "cpu_reference"
                ),
            },
        )
        self._last_capability = cap
        self._last_output_sha256 = output_hash
        return RenderResult(
            request_id=request.request_id,
            route=self.route,
            backend_id=self.backend_id,
            ok=True,
            frames_rendered=frames,
            wall_time_ms=wall_s * 1000.0,
            output_media=request.output_media,
        )
