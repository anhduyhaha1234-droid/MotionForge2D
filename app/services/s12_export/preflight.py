"""Pure S12 export preflight evaluation (S12-T01).

No I/O, no DB, no render, no subprocess: the route assembles a
:class:`PreflightContext` from durable authorities (read-only consumes) and
this module returns the frozen verdict.  Every later S12 task reuses this
pure function for enqueue-time AND pre-publish re-checks.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from app.schemas.s12_export import (
    S12_EXPORT_CONTRACT_VERSION,
    AspectHandling,
    ExportPreflightRequest,
    ExportPreflightResponse,
    ExportProfile,
    ExportProfileId,
    PreflightCheck,
    PreflightReason,
    SourceKind,
)

__all__ = [
    "PREFLIGHT_PROFILES",
    "PROFILE_ENCODERS",
    "ESTIMATE_BPP",
    "EXPORT_GATE_SCHEMA",
    "GATE_REASON_NOT_RUN",
    "ExportGateConsumption",
    "PreflightContext",
    "evaluate_preflight",
    "classify_source_kind",
    "export_gate_consumption",
    "probe_encoder_support",
]

#: Master raster (WS-08 outcome).
MASTER_WIDTH = 3840
MASTER_HEIGHT = 2160

#: Conservative bytes-per-pixel estimate factor with basis string (T02 refines
#: with measured encoder data; this stays an estimate, never a fake number).
ESTIMATE_BPP = 0.5

#: Frozen profile table — ``supported`` is filled by T02 capability detection.
PREFLIGHT_PROFILES: dict[str, dict[str, object]] = {
    "master-4k-h264": {
        "width": 3840,
        "height": 2160,
        "codec": "h264",
        "upscale_method": None,
    },
    "master-4k-hevc": {
        "width": 3840,
        "height": 2160,
        "codec": "hevc",
        "upscale_method": None,
    },
    "preview-1080p-h264": {
        "width": 1920,
        "height": 1080,
        "codec": "h264",
        "upscale_method": None,
    },
}

#: Aspect tolerance: relative DAR drift above this fails closed (or letterbox).
ASPECT_EPSILON = 0.01

#: C02 — encoder required per frozen profile.  No heuristic guessing: each
#: profile names its ffmpeg encoder; support is PROBED (binary + encode
#: smoke), never a constant flag and never a silent fallback.
PROFILE_ENCODERS: dict[str, str] = {
    "master-4k-h264": "libx264",
    "master-4k-hevc": "libx265",
    "preview-1080p-h264": "libx264",
}

#: Probe TTL (seconds): positive results cache briefly; failures NEVER cache.
_PROBE_TTL_SEC = 300.0
_probe_cache: dict[str, tuple[float, str]] = {}


def _find_ffmpeg() -> str | None:
    try:
        from app.services.ffmpeg_utils import find_ffmpeg

        try:
            return find_ffmpeg()
        except Exception:
            return None
    except Exception:
        return None


def probe_encoder_support(profile_id: str) -> tuple[bool, str]:
    """C02 real capability probe for one frozen profile.

    Returns ``(supported, basis)``.  ``supported`` is True ONLY when the
    ffmpeg binary is located AND ``-encoders`` lists the profile's encoder
    AND a 1-frame CPU encode smoke test exits 0.  Any failure returns False
    with the concrete reason (binary missing / encoder absent / smoke rc).
    No constant flag, no silent fallback to another encoder.
    """
    spec = PREFLIGHT_PROFILES.get(str(profile_id))
    if spec is None:
        return False, f"unknown profile {profile_id!r}"
    encoder = str(PROFILE_ENCODERS.get(str(profile_id), ""))
    now = time.monotonic()
    cached = _probe_cache.get(str(profile_id))
    if cached is not None and (now - cached[0]) < _PROBE_TTL_SEC:
        return True, cached[1]
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg binary not found (capability unproven)"
    try:
        enc = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            timeout=30,
        )
    except Exception as exc:
        return False, f"ffmpeg -encoders probe failed: {exc}"
    if encoder.encode() not in (enc.stdout or b""):
        return False, f"encoder {encoder!r} absent from ffmpeg -encoders"
    import tempfile
    from pathlib import Path

    try:
        with tempfile.TemporaryDirectory(prefix="s12cap_") as tmp:
            out = str(Path(tmp) / "smoke.mp4")
            codec_flag = (
                "libx264" if encoder == "libx264" else encoder
            )
            smoke = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=64x64:d=1:r=5",
                    "-frames:v",
                    "1",
                    "-c:v",
                    codec_flag,
                    "-y",
                    out,
                ],
                capture_output=True,
                timeout=60,
            )
        if smoke.returncode != 0:
            tail = (smoke.stderr or b"")[-200:].decode("utf-8", "replace")
            return False, f"encoder {encoder!r} smoke failed rc={smoke.returncode}: {tail}"
    except Exception as exc:
        return False, f"encoder {encoder!r} smoke error: {exc}"
    basis = f"probed {encoder} via ffmpeg -encoders + 1-frame smoke (rc=0)"
    _probe_cache[str(profile_id)] = (now, basis)
    return True, basis


@dataclass(frozen=True)
class PreflightContext:
    """Durable facts the route resolved (read-only) before evaluation."""

    project_id: str
    video_item_id: str
    # Source media facts (VideoItem + Artifact row, read-only).
    source_found: bool = False
    source_ready: bool = False
    source_is_partial: bool = False
    source_width: int | None = None
    source_height: int | None = None
    source_frame_count: int | None = None
    # Provenance: actual render/source identity, not file size.
    source_native_4k: bool = False
    upscale_method: str | None = None
    # Full-apply checkpoint pin facts.
    checkpoint_found: bool = False
    checkpoint_hash_match: bool = False
    checkpoint_revision_match: bool = False
    checkpoint_cross_project: bool = False
    # Structural-lock pin facts.
    lock_found: bool = False
    lock_hash_match: bool = False
    lock_generation_match: bool = False
    # Readiness aggregate (Decision F consume, never recomputed here).
    readiness_status: str = "not_run"
    readiness_policy: str = ""
    readiness_policy_current: bool = False
    # Disk facts for the managed export root.
    disk_free_bytes: int | None = None
    # Profile support (T02 fills; unknown profile = unsupported fail-closed).
    profile_supported: bool = False
    profile_support_basis: str = ""
    extra_reasons: tuple[str, ...] = field(default_factory=tuple)


def classify_source_kind(ctx: PreflightContext) -> SourceKind:
    """Native vs upscale from PROVED provenance only (F-OBS-01 fix).

    ``source_native_4k`` may be set ONLY from a proved native-origin
    authority — dimensions alone NEVER imply native.  A 3840x2160 file of
    unproved origin is ``upscale_4k`` (already-upscaled-4K honesty), never
    ``native_4k``.
    """
    if (
        ctx.source_native_4k
            and ctx.source_width == MASTER_WIDTH
            and ctx.source_height == MASTER_HEIGHT
    ):
        return "native_4k"
    if ctx.source_width is not None and ctx.source_height is not None:
        return "upscale_4k"
    return "below_4k"


# ── MF-END-23 export gate consumption (MF-END-26) ───────────────────────────
#
# The S12 export preflight CONSUMES the additive ``mf-end-23/export-gate@1``
# report (``app/persistence/readiness.py``) — it never defines a second gate.
# The gate's OWN typed violation codes stay verbatim in the check detail; the
# check ``reason`` is mapped onto the CLOSED preflight vocabulary frozen in
# ``app/schemas/s12_export.py`` (later tasks must reuse those codes).
#
# Enforcement rule (single, uniform at every S12 leg): a gate verdict of
# ``blocked`` refuses the export.  A verdict of ``not_run`` means NO completed
# CURRENT full-scope QC run exists at all — that refusal is owned by the
# readiness authority (``S12_EXPORT_NOT_READY``), which every leg already
# consumes; the gate adds the output-bound band/binding/output-evidence
# enforcement on top of it.

#: The one export-gate schema this module consumes (identity pin, not a copy).
EXPORT_GATE_SCHEMA = "mf-end-23/export-gate@1"

#: Reason for a gate that ran but has no completed CURRENT full-scope run.
GATE_REASON_NOT_RUN = "S12_EXPORT_NOT_READY"

#: Gate violation code → CLOSED preflight reason code.  Anything unmapped
#: fails closed to ``S12_EXPORT_NOT_READY`` (never a silent pass).
_GATE_REASON_BY_CODE: dict[str, str] = {
    "EXPORT_BLOCKED_READINESS": "S12_EXPORT_NOT_READY",
    "EXPORT_BLOCKED_JOB_UNREADABLE": "S12_EXPORT_NOT_READY",
    "EXPORT_BLOCKED_BAND_MISMATCH": "S12_EXPORT_NOT_READY",
    "EXPORT_BLOCKED_DETECTOR_UNKNOWN": "S12_EXPORT_NOT_READY",
    "EXPORT_BLOCKED_DETECTOR_REVISION": "S12_EXPORT_NOT_READY",
    "EXPORT_BLOCKED_BINDING_MISSING": "S12_EXPORT_NOT_READY",
    "EXPORT_BLOCKED_BINDING_TAMPER": "S12_EXPORT_NOT_READY",
    "EXPORT_BLOCKED_STALE_SOURCE": "S12_EXPORT_SOURCE_STALE",
    "EXPORT_BLOCKED_STALE_RENDER": "S12_EXPORT_STALE_CHECKPOINT",
    "EXPORT_BLOCKED_STALE_CAST": "S12_EXPORT_STALE_CHECKPOINT",
    "EXPORT_BLOCKED_OUTPUT_EVIDENCE": "S12_EXPORT_NOT_READY",
}

#: Gate video statuses (from ``app/persistence/readiness.py``).
_GATE_STATUS_READY = "ready"
_GATE_STATUS_BLOCKED = "blocked"
_GATE_STATUS_NOT_RUN = "not_run"


@dataclass(frozen=True)
class ExportGateConsumption:
    """One video's export-gate verdict expressed in preflight vocabulary."""

    passed: bool
    reason: str
    detail: str
    schema: str = ""
    schema_ok: bool = False
    gate_status: str = ""
    video_status: str = ""
    codes: tuple[str, ...] = ()


def export_gate_consumption(record: Any, video_item_id: str) -> ExportGateConsumption:
    """Consume an ``mf-end-23/export-gate@1`` record for ONE video.

    Pure and read-only: the gate is resolved elsewhere (server-owned) and the
    record is only INTERPRETED here.  Fail-closed cases (unknown schema,
    missing video row, unreadable record) all refuse with a typed reason;
    the gate's own codes are preserved verbatim inside ``detail``.
    """
    if record is None:
        return ExportGateConsumption(
            passed=False,
            reason=GATE_REASON_NOT_RUN,
            detail="export gate record unavailable (fail closed)",
        )
    schema = str(getattr(record, "schema", "") or "")
    gate_status = str(getattr(record, "status", "") or "")
    videos = list(getattr(record, "videos", None) or [])
    video = next(
        (
            v
            for v in videos
            if str(getattr(v, "video_item_id", "") or "") == str(video_item_id)
        ),
        None,
    )
    schema_ok = schema == EXPORT_GATE_SCHEMA
    if video is None:
        return ExportGateConsumption(
            passed=False,
            reason=GATE_REASON_NOT_RUN,
            detail=(
                f"video {video_item_id!r} is absent from the export gate report "
                f"(schema={schema!r}, status={gate_status!r}) — fail closed"
            ),
            schema=schema,
            schema_ok=schema_ok,
            gate_status=gate_status,
        )
    violations = list(getattr(video, "violations", None) or [])
    codes = tuple(str(getattr(b, "code", "") or "") for b in violations)
    video_status = str(getattr(video, "status", "") or "")
    if not schema_ok:
        return ExportGateConsumption(
            passed=False,
            reason=GATE_REASON_NOT_RUN,
            detail=(
                f"export gate schema {schema!r} != {EXPORT_GATE_SCHEMA!r} — "
                "unknown contract, fail closed"
            ),
            schema=schema,
            schema_ok=False,
            gate_status=gate_status,
            video_status=video_status,
            codes=codes,
        )
    if video_status == _GATE_STATUS_READY and not codes:
        return ExportGateConsumption(
            passed=True,
            reason="S12_EXPORT_OK",
            detail=(
                f"export gate ready ({EXPORT_GATE_SCHEMA}; "
                f"binding={getattr(video, 'binding_state', '')!r}, "
                f"output={getattr(video, 'output_state', '')!r})"
            ),
            schema=schema,
            schema_ok=True,
            gate_status=gate_status,
            video_status=video_status,
        )
    if video_status == _GATE_STATUS_NOT_RUN:
        return ExportGateConsumption(
            passed=False,
            reason=GATE_REASON_NOT_RUN,
            detail=(
                "export gate not_run: no completed CURRENT full-scope QC run "
                f"({getattr(video, 'check_state_detail', '')}) — the readiness "
                "authority carries this refusal"
            ),
            schema=schema,
            schema_ok=True,
            gate_status=gate_status,
            video_status=video_status,
            codes=codes,
        )
    # blocked (or any inconsistent ready-with-violations row): refuse.
    reason = _GATE_REASON_BY_CODE.get(codes[0] if codes else "", GATE_REASON_NOT_RUN)
    first_detail = ""
    if violations:
        first_detail = str(getattr(violations[0], "detail", "") or "")
    detail = (
        f"export gate blocked ({EXPORT_GATE_SCHEMA}; status={video_status!r}; "
        f"codes={list(codes)}; first={first_detail})"
    )
    return ExportGateConsumption(
        passed=False,
        reason=reason,
        detail=detail,
        schema=schema,
        schema_ok=True,
        gate_status=gate_status,
        video_status=video_status,
        codes=codes,
    )


def _check(
    checks: list[PreflightCheck],
    reasons: list[PreflightReason],
    name: str,
    passed: bool,
    reason: PreflightReason,
    detail: str,
) -> None:
    checks.append(PreflightCheck(name=name, passed=passed, reason=reason, detail=detail))
    if not passed:
        reasons.append(reason)


def evaluate_preflight(
    request: ExportPreflightRequest,
    ctx: PreflightContext,
    *,
    aspect_handling: AspectHandling | None = None,
) -> ExportPreflightResponse:
    """Pure preflight verdict — performs zero render and zero I/O."""
    handling: AspectHandling = aspect_handling or request.aspect_handling
    profile_id: ExportProfileId = request.profile_id
    spec = PREFLIGHT_PROFILES.get(str(profile_id))

    checks: list[PreflightCheck] = []
    reasons: list[PreflightReason] = []

    if spec is None:
        _check(
            checks,
            reasons,
            "profile",
            False,
            "S12_EXPORT_UNSUPPORTED_PROFILE",
            f"unknown profile {profile_id!r}",
        )
        target_w, target_h, codec = MASTER_WIDTH, MASTER_HEIGHT, "h264"
    else:
        target_w = int(spec["width"])
        target_h = int(spec["height"])
        codec = str(spec["codec"])  # type: ignore[arg-type]
        _check(
            checks,
            reasons,
            "profile",
            ctx.profile_supported,
            "S12_EXPORT_UNSUPPORTED_PROFILE" if not ctx.profile_supported else "S12_EXPORT_OK",
            ctx.profile_support_basis or f"profile {profile_id!r} support unproven",
        )

    # ── source gates ────────────────────────────────────────────────
    _check(
        checks,
        reasons,
        "source",
        ctx.source_found,
        "S12_EXPORT_SOURCE_MISSING" if not ctx.source_found else "S12_EXPORT_OK",
        "source artifact row missing" if not ctx.source_found else "source artifact present",
    )
    if ctx.source_found:
        _check(
            checks,
            reasons,
            "source_state",
            ctx.source_ready and not ctx.source_is_partial,
            "S12_EXPORT_SOURCE_PARTIAL"
            if ctx.source_is_partial
            else "S12_EXPORT_SOURCE_NOT_READY",
            ".partial source must never export as final"
            if ctx.source_is_partial
            else ("source artifact not ready" if not ctx.source_ready else "source ready"),
        )

    # ── checkpoint pin gates ────────────────────────────────────────
    _check(
        checks,
        reasons,
        "checkpoint_cross_project",
        not ctx.checkpoint_cross_project,
        "S12_EXPORT_CROSS_PROJECT" if ctx.checkpoint_cross_project else "S12_EXPORT_OK",
        "checkpoint belongs to another project"
        if ctx.checkpoint_cross_project
        else "checkpoint project matches",
    )
    _check(
        checks,
        reasons,
        "checkpoint",
        ctx.checkpoint_found and ctx.checkpoint_hash_match and ctx.checkpoint_revision_match,
        "S12_EXPORT_STALE_CHECKPOINT",
        "frozen checkpoint pin matches"
        if (ctx.checkpoint_found and ctx.checkpoint_hash_match and ctx.checkpoint_revision_match)
        else "checkpoint missing or stale (hash/revision drift)",
    )

    # ── structural-lock pin gates ───────────────────────────────────
    _check(
        checks,
        reasons,
        "structural_lock",
        ctx.lock_found and ctx.lock_hash_match and ctx.lock_generation_match,
        "S12_EXPORT_LOCK_MISSING",
        "structural lock pin matches current generation"
        if (ctx.lock_found and ctx.lock_hash_match and ctx.lock_generation_match)
        else "structural lock missing or stale identity",
    )

    # ── readiness gate (consumed, never loosened here) ──────────────
    ready_ok = ctx.readiness_status == "ready" and ctx.readiness_policy_current
    _check(
        checks,
        reasons,
        "readiness",
        ready_ok,
        "S12_EXPORT_STALE_POLICY"
        if (ctx.readiness_status == "ready" and not ctx.readiness_policy_current)
        else "S12_EXPORT_NOT_READY",
        f"readiness={ctx.readiness_status} policy_current={ctx.readiness_policy_current}",
    )

    # ── native vs upscale (Scenario F honesty) ──────────────────────
    source_kind = classify_source_kind(ctx)

    # ── aspect gate (never silent stretch/crop) ─────────────────────
    aspect_ok = True
    aspect_detail = "aspect not measurable (missing dimensions)"
    if (
        ctx.source_width
        and ctx.source_height
        and ctx.source_width > 0
        and ctx.source_height > 0
    ):
        src_dar = ctx.source_width / ctx.source_height
        tgt_dar = target_w / target_h
        drift = abs(src_dar - tgt_dar) / max(tgt_dar, 1e-9)
        if drift <= ASPECT_EPSILON:
            aspect_detail = f"DAR match (drift {drift:.4f})"
        elif handling == "letterbox":
            aspect_detail = f"DAR drift {drift:.4f} preserved via letterbox"
        else:
            aspect_ok = False
            aspect_detail = f"DAR drift {drift:.4f} with handling={handling} fails closed"
    _check(
        checks,
        reasons,
        "aspect",
        aspect_ok,
        "S12_EXPORT_ASPECT_MISMATCH" if not aspect_ok else "S12_EXPORT_OK",
        aspect_detail,
    )

    # ── disk gate (estimate with basis, never a fake exact number) ──
    frames = ctx.source_frame_count or 0
    estimate: int | None = None
    basis = ""
    if frames > 0:
        estimate = int(target_w * target_h * frames * ESTIMATE_BPP)
        basis = (
            f"heuristic {target_w}x{target_h}x{frames}f"
            f"x{ESTIMATE_BPP}B/px (T02 refines with measured data)"
        )
        disk_ok = ctx.disk_free_bytes is not None and ctx.disk_free_bytes >= estimate
        _check(
            checks,
            reasons,
            "disk",
            disk_ok,
            "S12_EXPORT_DISK_INSUFFICIENT" if not disk_ok else "S12_EXPORT_OK",
            f"need ~{estimate}B, free {ctx.disk_free_bytes}B"
            if not disk_ok
            else f"~{estimate}B fits in {ctx.disk_free_bytes}B free",
        )
    else:
        _check(
            checks,
            reasons,
            "disk",
            False,
            "S12_EXPORT_DISK_INSUFFICIENT",
            "frame count unknown — cannot prove disk fits",
        )

    eligible = all(c.passed for c in checks)
    final_reasons: list[PreflightReason] = list(reasons)
    if eligible:
        final_reasons = ["S12_EXPORT_OK"]

    provenance = "proved-native" if source_kind == "native_4k" else "unproven"

    method = ctx.upscale_method
    if source_kind == "upscale_4k" and not method:
        method = "labeled-upscale-method-required-by-T02"
    profile = ExportProfile(
        profile_id=profile_id,
        width=target_w,
        height=target_h,
        codec=codec,  # type: ignore[arg-type]
        upscale_method=method if source_kind != "native_4k" else None,
        supported=ctx.profile_supported,
        support_basis=ctx.profile_support_basis or None,
    )
    return ExportPreflightResponse(
        contract_version=S12_EXPORT_CONTRACT_VERSION,
        project_id=ctx.project_id,
        video_item_id=ctx.video_item_id,
        profile=profile,
        source_kind=source_kind,
        source_provenance=provenance,
        source_width=ctx.source_width,
        source_height=ctx.source_height,
        eligible=eligible,
        reasons=final_reasons,
        checks=checks,
        estimate_bytes=estimate,
        estimate_basis=basis,
        readiness_status=ctx.readiness_status,
        readiness_policy=ctx.readiness_policy,
    )
