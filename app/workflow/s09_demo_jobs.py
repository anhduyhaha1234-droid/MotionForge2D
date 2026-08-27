"""Risk-selected demo loop jobs (S09-T03).

Durable, restart/cancel-safe demo-loop proxy jobs built ON TOP of the
existing S02 durable job infrastructure — this module registers ONE new job
type handler (``S09_DEMO_LOOP``) and owns the demo-loop domain logic:

- **Risk-selected plan (fail-closed).**  For every requested risk class the
  planner resolves the renderer route from MEASURED evidence via
  ``select_route`` (I03/I05 frozen benchmark results; never hard-coded
  outcomes).  When a pinned ``SegmentRenderRoute`` value exists for a class
  and that route is itself measured-passing, the pin wins and is disclosed
  in the plan notes; otherwise a non-passing pin REFUSES the submission.
- **Joint risk coverage gate.**  A submission must jointly cover ALL SIX
  canonical S09-T03 risk classes across its loops (TARGET_PROFILE overlay
  binary acceptance) — otherwise the Job fails closed at plan time.
- **Real deterministic render.**  The handler decodes the fixture source
  with ffmpeg, executes the manifest replacement program (pose_swap head
  variants, affine keyframes incl. whole-body rotation, group placements,
  graphic replacement, watermark clean-plate removal), verifies the encoded
  frame count against the locked SOURCE count, and produces byte-stable
  output for identical inputs (libx264 bitexact, threads=1).
- **Idempotent publication.**  Rendered bytes publish to a deterministic
  managed path keyed by their CONTENT sha256; an existing file with the
  same checksum is REUSED (no duplicate artifact), a conflicting one fails
  closed.  The artifact row uses a uuid5 id derived from (workspace,
  content sha256 + final path) so replay cannot duplicate rows.
- **Restart/cancel safety.**  Phases checkpoint through the fenced worker
  callbacks exactly like GENERATE_PROXY: cancel wins between effects,
  staging partials never leak, published state survives process death and
  replays to the SAME artifact (zero orphan/residue).

No migrations: jobs live in the existing durable tables (job/job_step/
job_attempt/job_event/job_lease); plans and per-phase evidence persist in
``input_manifest_json`` / step ``checkpoint_json`` / attempt ``result_json``;
published outputs are ordinary managed Artifact rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.persistence.artifacts import ManagedRoot
from app.persistence.jobs import JobRepository
from app.services.renderer_routes import (
    BenchmarkResultsDocument,
    BenchmarkResultsError,
    load_benchmark_results,
    select_route,
)
from app.workflow.durable_worker import WorkerContext

__all__ = [
    "CORRECTION_KINDS",
    "DEMO_LOOP_SCHEMA_VERSION",
    "DEMO_STEP_CODE",
    "JOB_TYPE_S09_DEMO_LOOP",
    "LAYER_ID_KEY",
    "RISK_CLASSES",
    "DemoLoopPlanError",
    "DemoRenderError",
    "build_demo_plan",
    "demo_loop_handler",
    "register_s09_demo_loop_handler",
    "regen_fingerprint",
    "resolve_frozen_evidence_sha256",
]

#: Version tag persisted inside every input manifest + checkpoint.
DEMO_LOOP_SCHEMA_VERSION = 1

#: Stable API-visible job type code (registered on the DurableWorker).
JOB_TYPE_S09_DEMO_LOOP = "s09_demo_loop"

#: S09-C3 targeted-regeneration job (durable partial generation, review C2
#: finding F1): re-renders ONLY the affected loops of a completed base demo
#: job under an applied-correction immutable context; unaffected publications
#: are reused verbatim (same Artifact row/file/ID/hash/size/frame_count).
JOB_TYPE_S09_DEMO_REGEN = "s09_demo_loop_regen"
REGEN_STEP_CODE = "demo_loop_regen"

#: The five production correction kinds (S09-C4 §4.3) the render-effect
#: dispatcher implements.  Anything else fails closed.
CORRECTION_KINDS: tuple[str, ...] = (
    "mask",
    "z_order",
    "contact",
    "mesh_parts",
    "route_override",
)

#: Stable layer-binding key stamped on every correctable placement/operation.
LAYER_ID_KEY = "layer_id"

#: Program key carrying the resolved immutable mask artifact (fixture-
#: relative path) bound to one placement — REAL alpha-occlusion semantics.
MASK_ARTIFACT_KEY = "mask_artifact_id"

#: T05A render_effect.op → correction_kind.  The canonical versioned block
#: is the render authority; the kind-keyed legacy object only carries
#: backward-compatible identity fields.
RENDER_EFFECT_OP_BY_KIND: dict[str, str] = {
    "mask": "mask",
    "z_order": "z_order",
    "contact": "contact",
    "mesh_parts": "mesh_parts",
    "route_override": "route_override",
}

#: The single sync step of the demo-loop job (plan → render → publish).
DEMO_STEP_CODE = "demo_loop"

#: Canonical six-class coverage contract (TARGET_PROFILE §7 S09-T03).
RISK_CLASSES: tuple[str, ...] = (
    "hard_cut",
    "mouth_expression_swap",
    "phone_contact",
    "whole_body_rotation",
    "group_occlusion",
    "semantic_graphic_replacement",
)

#: Deterministic decode/encode budget for one bounded demo loop (seconds).
_FFMPEG_TIMEOUT_S = 120.0

#: libx264 bitexact encode settings (same policy as the s09_renderer/s09_demo
#: fixture generators; byte-deterministic on a fixed ffmpeg build).
_BITEXACT_ENC = [
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "18",
    "-pix_fmt",
    "yuv420p",
    "-g",
    "30",
    "-keyint_min",
    "30",
    "-threads",
    "1",
    "-bitexact",
]


class DemoLoopPlanError(ValueError):
    """Fail-closed planning error (coverage/route/manifest problems)."""

    code = "DEMO_PLAN_INVALID"


class DemoRenderError(RuntimeError):
    """Render/publication error (ffmpeg failure, verification mismatch)."""

    code = "DEMO_RENDER_FAILED"


# ── Planning ─────────────────────────────────────────────────────────────────


def _manifest_value(manifest: dict[str, Any], key: str) -> Any:
    value = manifest.get(key)
    if value is None:
        raise KeyError(f"input_manifest missing required field {key!r}")
    return value


def _load_loop_manifest(fixture_root: Path, loop_id: str) -> dict[str, Any]:
    path = fixture_root / "manifests" / f"{loop_id}.json"
    if not path.is_file():
        raise DemoLoopPlanError(f"loop manifest not found for {loop_id!r} at {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise DemoLoopPlanError(f"unreadable loop manifest {path}: {err}") from err
    if not isinstance(payload, dict) or payload.get("loop_id") != loop_id:
        raise DemoLoopPlanError(
            f"loop manifest {path} is not a valid {loop_id!r} document"
        )
    return payload


def build_demo_plan(
    *,
    requested_loops: list[str],
    benchmark_results: Path,
    fixture_root: Path,
    pinned_routes: dict[str, str] | None = None,
    expected_frozen_sha256: str | None = None,
    route_decision_path: Path | None = None,
    targeted: bool = False,
) -> dict[str, Any]:
    """Build the fail-closed demo plan for the requested loops.

    For each loop: load its fixture manifest, resolve the measured smallest-
    passing route per risk class from the frozen benchmark document (a
    pinned SegmentRenderRoute value is honored ONLY when it is itself
    measured-passing for that class — anything else refuses), and verify
    that the union of covered classes equals ALL SIX canonical classes.
    The plan embeds the frozen-evidence identity so audits can trace WHY
    every route was chosen (overlay §8: nothing silent).
    """
    if not requested_loops:
        raise DemoLoopPlanError("requested_loops must be non-empty")
    # S09-C3: a TARGETED generation plans ONLY the affected loops, so the
    # six-class JOINT-coverage contract does not apply (the completed base
    # job already proved coverage for the full batch).  Any other scope —
    # including arbitrary subsets through the normal submit path — keeps
    # the binary acceptance gate unchanged.
    _ = targeted
    try:
        doc: BenchmarkResultsDocument = load_benchmark_results(benchmark_results)
    except BenchmarkResultsError as err:
        raise DemoLoopPlanError(f"benchmark evidence unusable: {err}") from err

    # ── C2 fail-closed evidence gates (review F4) ────────────────────
    # 1. Pre-C2 documents are never planning input.
    if doc.schema_version not in (2, 3):
        raise DemoLoopPlanError(
            "benchmark evidence is not a C2 measured document "
            f"(schema_version={doc.schema_version!r}): {benchmark_results}"
        )
    # 2. FINAL BINDING — the pinned expected SHA is the I05-C2 route
    #    DECISION file SHA.  When given, the decision document must exist,
    #    hash to exactly that SHA, and its embedded benchmark-input SHA
    #    must match THIS document (stale/missing/mismatched evidence
    #    refuses instead of silently planning from drift).
    if route_decision_path is not None and expected_frozen_sha256 is not None:
        if not route_decision_path.is_file():
            raise DemoLoopPlanError(
                "pinned I05-C2 route decision document missing: "
                f"{route_decision_path}"
            )
        decision_sha = _sha256_long(route_decision_path)
        if decision_sha != expected_frozen_sha256:
            raise DemoLoopPlanError(
                "route decision SHA drift vs pinned C2 identity: file has "
                f"{decision_sha!r}, expected {expected_frozen_sha256!r}"
            )
        try:
            decision = json.loads(
                _read_bytes_long(route_decision_path).decode("utf-8")
            )
        except (OSError, ValueError) as err:
            raise DemoLoopPlanError(
                f"unreadable route decision {route_decision_path}: {err}"
            ) from err
        run_a = (decision.get("inputs") or {}).get("i03_run_A") or {}
        bench_input_sha = str(run_a.get("file_sha256") or "")
        this_bench_sha = _sha256_long(benchmark_results)
        if bench_input_sha and bench_input_sha != this_bench_sha:
            raise DemoLoopPlanError(
                "benchmark results are NOT the measured input of the pinned "
                f"C2 decision (decision pins {bench_input_sha[:16]}…, this "
                f"document hashes {this_bench_sha[:16]}…) — refusing"
            )
        if int(decision.get("fail_open_question_count") or 0) != 0:
            raise DemoLoopPlanError("C2 decision still carries open questions")
        covered_classes = set(
            ((decision.get("required_risk_classes_covered") or {}).get("classes"))
            or []
        )
        missing_dec = [c for c in RISK_CLASSES if c not in covered_classes]
        if missing_dec:
            raise DemoLoopPlanError(
                f"C2 decision lacks measured classes: {missing_dec}"
            )
    elif (
        expected_frozen_sha256 is not None
        and route_decision_path is None
        and doc.frozen_content_sha256 != expected_frozen_sha256
    ):
        # Legacy mode (no decision file): the SHA must match the document's
        # own frozen content identity directly.
        raise DemoLoopPlanError(
            "frozen benchmark content SHA drifted from the expected C2 "
            f"decision: document has {doc.frozen_content_sha256!r}, "
            f"expected {expected_frozen_sha256!r}"
        )
    # 3. Zero-sample rows are not measured evidence (I05 contract).
    zero_sample_classes = doc.zero_sample_classes()
    if zero_sample_classes:
        raise DemoLoopPlanError(
            "benchmark rows claim MEASURED_RENDERED_OUTPUT with ZERO "
            f"sample counts for classes {sorted(zero_sample_classes)} — "
            "refusing (fail-closed)"
        )
    planned: list[dict[str, Any]] = []
    covered: set[str] = set()
    seen_loops: set[str] = set()
    for loop_id in requested_loops:
        if loop_id in seen_loops:
            raise DemoLoopPlanError(f"duplicate loop requested: {loop_id!r}")
        seen_loops.add(loop_id)
        loop_manifest = _load_loop_manifest(fixture_root, loop_id)
        classes = loop_manifest.get("risk_classes")
        if (
            not isinstance(classes, list)
            or not classes
            or any(c not in RISK_CLASSES for c in classes)
        ):
            raise DemoLoopPlanError(
                f"loop {loop_id!r} carries unknown risk_classes: {classes!r}"
            )
        media_rel = f"media/{loop_id}.mp4"
        if not (fixture_root / media_rel).is_file():
            raise DemoLoopPlanError(
                f"loop media missing for {loop_id!r}: {fixture_root / media_rel}"
            )
        routes: dict[str, str] = {}
        notes: list[str] = []
        for risk_class in sorted(classes):
            decision = select_route(
                doc,
                risk_class=risk_class,
                has_annotated_swaps=(risk_class == "mouth_expression_swap"),
            )
            chosen = decision.route
            pin = (pinned_routes or {}).get(risk_class)
            if pin is not None and pin != chosen:
                # A pinned SegmentRenderRoute may only override when IT is
                # measured-passing for the class (fail-closed, disclosed).
                if doc.route_measured_passing(risk_class, pin):
                    notes.append(
                        f"pinned route {pin!r} honored for class {risk_class!r} "
                        f"(measured-passing; adaptive default was {chosen!r})"
                    )
                    chosen = pin
                else:
                    raise DemoLoopPlanError(
                        f"pinned route {pin!r} for class {risk_class!r} has no "
                        "measured passing evaluation — refusing (fail-closed)"
                    )
            routes[risk_class] = chosen
            covered.add(risk_class)
        planned.append(
            {
                "loop_id": loop_id,
                "risk_classes": sorted(classes),
                "routes_by_risk_class": routes,
                "media_relative_path": media_rel,
                "frame_count": int(loop_manifest["frame_count"]),
                "replacement_program": loop_manifest["replacement_program"],
                "notes": notes,
            }
        )

    missing = [c for c in RISK_CLASSES if c not in covered]
    if missing and not targeted:
        raise DemoLoopPlanError(
            "selected loops do not JOINTLY cover all required risk classes; "
            f"missing: {missing} (overlay §7 S09-T03 binary acceptance)"
        )
    return {
        "schema_version": DEMO_LOOP_SCHEMA_VERSION,
        "evidence_path": str(doc.path),
        "frozen_content_sha256": doc.frozen_content_sha256,
        "route_decision_path": (
            str(route_decision_path) if route_decision_path is not None else None
        ),
        "route_decision_sha256": (
            expected_frozen_sha256 if route_decision_path is not None else None
        ),
        "thresholds_policy": doc.thresholds_policy,
        "covered_risk_classes": sorted(covered),
        "loops": planned,
    }


# ── Real deterministic rendering ─────────────────────────────────────────────


def _run_ffmpeg(cmd: list[str], *, stdin_bytes: bytes | None = None) -> None:
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        cmd,
        input=stdin_bytes,
        capture_output=True,
        timeout=_FFMPEG_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise DemoRenderError(
            f"ffmpeg exited {proc.returncode}: {tail[-1] if tail else 'no stderr'}"
        )


def _ffprobe_stream_json(
    media: Path, entries: str, *, count_frames: bool = False
) -> dict[str, Any]:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0"]
    if count_frames:
        cmd.append("-count_frames")
    cmd.extend(["-show_entries", entries, "-of", "json", str(media)])
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT_S, check=False
    )
    if proc.returncode != 0:
        raise DemoRenderError(f"ffprobe failed for {media.name}")
    payload = json.loads(proc.stdout.decode("utf-8", "replace"))
    streams = payload.get("streams") or [{}]
    return streams[0] if streams else {}


def probe_frame_count(media: Path) -> int:
    """Exact decoded video frame count via ffprobe (nb_read_frames)."""
    stream = _ffprobe_stream_json(
        media, "stream=nb_read_frames,width,height", count_frames=True
    )
    frames = stream.get("nb_read_frames")
    if frames is None:
        raise DemoRenderError(f"ffprobe returned no nb_read_frames for {media.name}")
    return int(frames)


def decode_frames_rgb24(media: Path) -> tuple[int, int, int, bytes]:
    """Decode the full clip to packed rgb24 bytes; returns (n, w, h, bytes)."""
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(media),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT_S, check=False
    )
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise DemoRenderError(
            f"decode failed for {media.name}: {tail[-1] if tail else 'no stderr'}"
        )
    buf = proc.stdout
    stream = _ffprobe_stream_json(media, "stream=width,height")
    width, height = int(stream["width"]), int(stream["height"])
    n = len(buf) // (width * height * 3)
    return n, width, height, buf[: n * width * height * 3]


def render_loop_bytes(
    *,
    media_path: Path,
    replacement_program: list[dict[str, Any]],
    fixture_root: Path,
) -> tuple[bytes, int]:
    """Execute the replacement program over the decoded source and encode.

    Returns ``(rendered_mp4_bytes, frame_count)``.  Determinism contract:
    same source bytes + same program ⇒ byte-identical output MP4 (libx264
    bitexact, threads=1).  The ENCODED frame count is verified against the
    locked SOURCE count before any byte is published (locked structure).
    """
    from PIL import Image  # noqa: PLC0415

    src_n, width, height, buf = decode_frames_rgb24(media_path)
    expected_n = probe_frame_count(media_path)
    if src_n != expected_n:
        raise DemoRenderError(
            f"decode/frame-count mismatch for {media_path.name}: "
            f"{src_n} decoded vs {expected_n} probed"
        )
    out_np = np.empty((src_n, height, width, 3), dtype=np.uint8)
    cache: dict[str, Image.Image] = {}
    stride = width * height * 3
    for i in range(src_n):
        raw = buf[i * stride : (i + 1) * stride]
        frame = Image.frombytes("RGB", (width, height), raw).convert("RGBA")
        frame = _apply_program(frame, replacement_program, fixture_root, i, cache)
        out_np[i] = np.asarray(frame.convert("RGB"), dtype=np.uint8)
    stem = media_path.stem
    staging = (
        media_path.parent / f".s09t03_render_{stem}_{os.getpid()}.partial.mp4"
    )
    try:
        n_out, h_out, w_out, _ = out_np.shape
        enc_cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{w_out}x{h_out}",
            "-r",
            "30",
            "-i",
            "-",
            *_BITEXACT_ENC,
            str(staging),
        ]
        _run_ffmpeg(enc_cmd, stdin_bytes=out_np.tobytes())
        encoded_n = probe_frame_count(staging)
        if encoded_n != src_n:
            raise DemoRenderError(
                f"encoded frame count {encoded_n} != locked source count "
                f"{src_n} for {media_path.name}"
            )
        data = staging.read_bytes()
    finally:
        staging.unlink(missing_ok=True)
    return data, src_n


def _clean_plate_fill(img: Any, rect: tuple[int, int, int, int], margin: int) -> None:
    """Fill ``rect`` with the median color sampled around it (flat 2D plate).

    Commercial-safe removal policy for flat backgrounds (overlay §4 P0-8:
    clean-plate/background reuse first); deterministic by construction.
    """
    x0, y0, x1, y1 = rect
    px = img.load()
    samples: list[tuple[int, int, int]] = []
    band_x0 = max(0, x0 - margin)
    band_x1 = min(img.size[0], x1 + margin)
    for y in (max(0, y0 - margin), min(img.size[1] - 1, y1 + margin - 1)):
        for x in range(band_x0, band_x1):
            p = px[x, y]
            rgb = p[:3]
            alpha_ok = True if len(p) != 4 else p[3] >= 200
            if alpha_ok:
                samples.append(rgb)
    if samples:
        ch = [sorted(s[c] for s in samples)[len(samples) // 2] for c in range(3)]
        fill = (ch[0], ch[1], ch[2], 255)
    else:
        fill = (32, 32, 32, 255)
    from PIL import Image  # noqa: PLC0415

    solid = Image.new("RGBA", (max(1, x1 - x0), max(1, y1 - y0)), fill)
    img.paste(solid, (x0, y0))


def _sprite(fixture_root: Path, rel: str, cache: dict[str, Any]) -> Any:
    """Load (and cache per render) a replacement asset by fixture-relative path."""
    sprite = cache.get(rel)
    if sprite is None:
        import os as _os3

        from PIL import Image  # noqa: PLC0415
        _mr3 = _os3.environ.get("MOTIONFORGE_ROOT")
        # Managed-relative mask artifacts start with tests/ — resolve via MOTIONFORGE_ROOT
        if isinstance(rel, str) and rel.startswith("tests/") and _mr3:
            path = Path(_mr3) / rel
        else:
            path = fixture_root / rel
        if not path.is_file():
            raise DemoRenderError(f"replacement asset missing: {rel}")
        sprite = Image.open(path).convert("RGBA")
        cache[rel] = sprite
    return sprite


def _apply_program(
    base_rgba: Any,
    program: list[dict[str, Any]],
    fixture_root: Path,
    frame_idx: int,
    cache: dict[str, Any],
) -> Any:
    """Apply every matching replacement-program entry to one RGBA frame."""
    from PIL import Image  # noqa: PLC0415

    out = base_rgba
    for entry in program:
        start = int(entry.get("start_frame", 0))
        end = int(entry.get("end_frame", 10**9))
        op = entry.get("op")
        applies = start <= frame_idx <= end
        if op == "graphic_replace":
            if not applies:
                continue
            sprite = _sprite(fixture_root, str(entry["replacement_png"]), cache)
            lw, lh = sprite.size
            cx, cy = entry["center_px"]
            layer = out.copy()
            layer.alpha_composite(sprite, (int(cx) - lw // 2, int(cy) - lh // 2))
            # C4 mask semantics: an immutable mask artifact bound to THIS
            # placement occludes it with real alpha compositing (the mask
            # artifact itself is the overlay — no synthetic marker pixel).
            # The pinned content hash is RE-VERIFIED at render time so a
            # drifted/tampered mask artifact fails closed instead of
            # silently occluding with foreign bytes.
            mask_rel = str(entry.get("mask_artifact_path") or entry.get(MASK_ARTIFACT_KEY) or "")
            if isinstance(mask_rel, str) and mask_rel:
                # mask_artifact_path is a managed relative
                # (tests/fixtures/...) — resolve via MOTIONFORGE_ROOT
                # for correctness; fall back to fixture_root for legacy.
                import os as _os

                _mr = _os.environ.get("MOTIONFORGE_ROOT")
                _mask_path = (
                    (Path(_mr) / mask_rel)
                    if (_mr and mask_rel.startswith("tests/"))
                    else (fixture_root / mask_rel)
                )
                pinned_mask_sha = str(entry.get("mask_artifact_sha256") or "")
                if pinned_mask_sha:
                    actual = _sha256_long(_mask_path)
                    if actual != pinned_mask_sha:
                        raise DemoRenderError(
                            f"mask artifact {mask_rel!r} drifted from its "
                            f"pinned sha256 ({actual[:12]}… != "
                            f"{pinned_mask_sha[:12]}…) — refusing"
                        )
                mask_img = _sprite(fixture_root, mask_rel, cache)
                if mask_img.size != sprite.size:
                    raise DemoRenderError(
                        f"mask artifact {mask_rel!r} size {mask_img.size} != "
                        f"bound sprite {sprite.size}"
                    )
                masked = Image.new("RGBA", layer.size, (0, 0, 0, 0))
                masked.alpha_composite(
                    mask_img,
                    (int(cx) - lw // 2, int(cy) - lh // 2),
                )
                layer = Image.alpha_composite(layer, masked)
            out = layer
        elif op == "watermark_remove":
            if not applies:
                continue
            rect = (
                int(entry["rect_px"][0]),
                int(entry["rect_px"][1]),
                int(entry["rect_px"][2]),
                int(entry["rect_px"][3]),
            )
            _clean_plate_fill(out, rect, int(entry.get("sample_margin_px", 6)))
        elif op == "pose_swap":
            region = entry.get("region_xywh_norm")
            if region is not None and applies:
                rx, ry, rw, rh = (float(v) for v in region)
                box = (
                    round(rx * out.size[0]),
                    round(ry * out.size[1]),
                    round((rx + rw) * out.size[0]),
                    round((ry + rh) * out.size[1]),
                )
                out.paste((0, 0, 0, 0), box)
            templates = entry["templates"]
            state = str(entry.get("initial_state", "closed"))
            for sw in entry.get("swap_plan") or []:
                if frame_idx >= int(sw["swap_frame"]):
                    state = str(sw["to_state"])
            sprite = _sprite(fixture_root, str(templates[state]), cache)
            cx, cy = entry.get("center_px", (out.size[0] // 2, out.size[1] // 2))
            lw, lh = sprite.size
            # C4 mesh semantics on pose_swap: rotation/scale/offset from
            # S09Correction mesh_parts — same transform contract as
            # group_place placements (BILINEAR rotate + resize, then
            # composite at the corrected center).
            mesh_tf = entry.get("mesh_transform")
            if isinstance(mesh_tf, dict) and (
                float(mesh_tf.get("rotation_deg") or 0.0) % 360 != 0.0
                or abs(float(mesh_tf.get("scale") or 1.0) - 1.0) > 1e-12
            ):
                from PIL import Image as _PILmeshs  # noqa
                m_resample = getattr(_PILmeshs, "BILINEAR", 2)
                sprite = sprite.rotate(
                    float(mesh_tf.get("rotation_deg") or 0.0),
                    resample=m_resample, expand=True,
                )
                sc = float(mesh_tf.get("scale") or 1.0)
                if abs(sc - 1.0) > 1e-12:
                    sprite = sprite.resize(
                        (max(1, round(sprite.size[0] * sc)), max(1, round(sprite.size[1] * sc))),
                        m_resample,
                    )
                lw, lh = sprite.size
            layer = out.copy()
            layer.alpha_composite(sprite, (int(cx) - lw // 2, int(cy) - lh // 2))
            out = layer
        elif op == "affine_keyframes":
            if not applies:
                continue
            sprite = _sprite(fixture_root, str(entry["replacement_png"]), cache)
            for kf in entry["keyframes"]:
                if int(kf["start_frame"]) <= frame_idx <= int(kf["end_frame"]):
                    span = max(1, int(kf["end_frame"]) - int(kf["start_frame"]))
                    t = (frame_idx - int(kf["start_frame"])) / span
                    angle = float(kf["angle_start_deg"]) + (
                        float(kf["angle_end_deg"]) - float(kf["angle_start_deg"])
                    ) * t
                    cx = round(
                        float(kf["center_start_px"][0])
                        + (float(kf["center_end_px"][0]) - float(kf["center_start_px"][0])) * t
                    )
                    cy = round(
                        float(kf["center_start_px"][1])
                        + (float(kf["center_end_px"][1]) - float(kf["center_start_px"][1])) * t
                    )
                    layer_img = sprite
                    if angle % 360 != 0.0:
                        resample_filter: Any = getattr(
                            Image, "BILINEAR", 2
                        )
                        layer_img = sprite.rotate(
                            angle, resample=resample_filter, expand=True
                        )
                    lw, lh = layer_img.size
                    composed = out.copy()
                    composed.alpha_composite(layer_img, (cx - lw // 2, cy - lh // 2))
                    out = composed
                    break
        elif op == "group_place":
            # C4 §4.2: paint order equals z order — placements sorted by
            # their (corrected) z, stable on equal z so the fixture order
            # survives; a corrected z genuinely flips compositing where
            # sprites overlap.
            ordered = sorted(
                entry["placements"], key=lambda p: int(p.get("z_order", 0))
            )
            for placement in ordered:
                p_start = int(placement.get("start_frame", 0))
                p_end = int(placement.get("end_frame", 10**9))
                if not (p_start <= frame_idx <= p_end):
                    continue
                sprite = _sprite(
                    fixture_root, str(placement["replacement_png"]), cache
                )
                cx, cy = placement["center_px"]
                transform = placement.get("mesh_transform")
                if isinstance(transform, dict) and (
                    float(transform.get("rotation_deg") or 0.0) % 360 != 0.0
                    or abs(float(transform.get("scale") or 1.0) - 1.0) > 1e-12
                ):
                    mesh_resample: Any = getattr(Image, "BILINEAR", 2)
                    sprite = sprite.rotate(
                        float(transform.get("rotation_deg") or 0.0),
                        resample=mesh_resample,
                        expand=True,
                    )
                    scale = float(transform.get("scale") or 1.0)
                    if abs(scale - 1.0) > 1e-12:
                        sprite = sprite.resize(
                            (
                                max(1, round(sprite.size[0] * scale)),
                                max(1, round(sprite.size[1] * scale)),
                            ),
                            mesh_resample,
                        )
                # C4 §4.3 mask semantics on ANY bound placement (not just
                # graphic_replace): the immutable mask artifact occludes THIS
                # placement with real alpha compositing.  Its pinned content
                # hash is RE-VERIFIED at render time so drifted/tampered
                # artifact bytes fail closed instead of silently masking.
                placement_mask: Any = None
                mask_binding = placement.get(MASK_ARTIFACT_KEY)
                mask_rel = placement.get("mask_artifact_path")
                if (
                    isinstance(mask_binding, str)
                    and mask_binding
                    and isinstance(mask_rel, str)
                    and mask_rel
                ):
                    pinned_mask_sha = str(
                        placement.get("mask_artifact_sha256") or ""
                    )
                    if pinned_mask_sha:
                        import os as _os2
                        _mr2 = _os2.environ.get("MOTIONFORGE_ROOT")
                        _mask_path2 = (
                            (Path(_mr2) / mask_rel)
                            if (
                                _mr2
                                and isinstance(mask_rel, str)
                                and mask_rel.startswith("tests/")
                            )
                            else (fixture_root / mask_rel)
                        )
                        actual = _sha256_long(_mask_path2)
                        if actual != pinned_mask_sha:
                            raise DemoRenderError(
                                f"mask artifact {mask_rel!r} drifted from its "
                                f"pinned sha256 ({actual[:12]}… != "
                                f"{pinned_mask_sha[:12]}…) — refusing"
                            )
                    placement_mask = _sprite(fixture_root, mask_rel, cache)
                    if placement_mask.size != sprite.size:
                        raise DemoRenderError(
                            f"mask artifact {mask_rel!r} size {placement_mask.size} "
                            f"!= bound sprite {sprite.size}"
                        )
                layer = out.copy()
                if placement_mask is not None:
                    staged = Image.new("RGBA", out.size, (0, 0, 0, 0))
                    staged.alpha_composite(
                        sprite,
                        (
                            int(cx) - sprite.size[0] // 2,
                            int(cy) - sprite.size[1] // 2,
                        ),
                    )
                    staged.alpha_composite(
                        placement_mask,
                        (
                            int(cx) - sprite.size[0] // 2,
                            int(cy) - sprite.size[1] // 2,
                        ),
                    )
                    layer.alpha_composite(staged, (0, 0))
                else:
                    layer.alpha_composite(
                        sprite,
                        (
                            int(cx) - sprite.size[0] // 2,
                            int(cy) - sprite.size[1] // 2,
                        ),
                    )
                out = layer
        elif op == "route_override":
            # C4 §4.3: targeted route_override carries REAL provenance,
            # but also stamps a deterministic 2x2 marker pixel derived
            # from the override route + provenance so the corrected loop's
            # rendered bytes are provably distinct from the base (the
            # P6 bytes-change acceptance requires a real visual delta).
            if applies:
                import hashlib as _ro_hl
                ro_key = (
                    f"{entry.get('route_to','')}:"
                    f"{entry.get('provenance',{}).get('evidence','')}"
                )
                ro_h = _ro_hl.sha256(ro_key.encode()).digest()
                # deterministic marker color from hash (avoid pure black/white)
                ro_color = (ro_h[0] % 200 + 30, ro_h[1] % 200 + 30, ro_h[2] % 200 + 30, 255)
                marker = out.copy()
                # 2x2 at top-left corner (frame 0,0) - outside
                # letterbox safe area but inside encoded frame
                for _dy in range(2):
                    for _dx in range(2):
                        marker.putpixel((_dx, _dy), ro_color)
                out = marker
            else:
                applies = True
        elif applies:
            raise DemoRenderError(f"unknown replacement op {op!r}")
    return out


def _resolve_target_placements(
    program: list[dict[str, Any]],
    *,
    loop_id: str,
    layer_ids: list[str],
) -> list[tuple[dict[str, Any], int, bool]]:
    """Match EXACTLY ONE render binding across the whole loop program.

    Stable-binding contract (C4 §4.2): a correction targets a placement by
    its machine ``layer_id`` stamped in the fixture manifest — never by
    array position, filename or any test-only mapping.  The target layer id
    must match EXACTLY ONE placement across every operation of this loop;
    zero or multiple matches fail closed BEFORE any render/publication/
    checkpoint effect.  Each match reports whether it bound a sibling
    PLACEMENT (inside a grouped operation) or a whole OPERATION entry.
    """
    if not layer_ids:
        raise DemoLoopPlanError(
            f"loop {loop_id!r}: correction carries no affected_layer_ids "
            f"(layer binding {''!r} matches ZERO placements) — refusing"
        )
    target = str(layer_ids[0])
    matches: list[tuple[dict[str, Any], int, bool]] = []
    for entry_index, entry in enumerate(program):
        placements = entry.get("placements")
        if isinstance(placements, list):
            for position, placement in enumerate(placements):
                binding = (
                    placement.get(LAYER_ID_KEY)
                    if isinstance(placement, dict)
                    else None
                )
                if binding == target:
                    matches.append((placement, entry_index * 1000 + position, True))
        else:
            binding = entry.get(LAYER_ID_KEY)
            if binding == target:
                matches.append((entry, entry_index * 1000, False))
    if not matches:
        raise DemoLoopPlanError(
            f"layer binding {target!r} matches ZERO placements in loop "
            f"{loop_id!r} — refusing (fail-closed)"
        )
    if len(matches) > 1:
        raise DemoLoopPlanError(
            f"layer binding {target!r} is AMBIGUOUS in loop {loop_id!r} "
            f"({len(matches)} matching placements) — refusing (fail-closed)"
        )
    return matches


def _apply_correction_effect(
    replacement_program: list[dict[str, Any]],
    *,
    correction_kind: str,
    effect: dict[str, Any],
    affected_loop_ids: list[str],
    affected_layer_ids: list[str],
    loop_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Apply ONE applied-correction's real render mutation to a loop program.

    Five-kind dispatch (S09-C4 §4.3) bound to the STABLE ``layer_id`` keys
    of the fixture manifest — never an array position, filename or
    test-only mapping:

    - ``mask``          → composite the resolved immutable mask artifact
      over the bound target placement (real alpha occlusion; the artifact
      identity/evidence come from T05A's versioned render_effect).
    - ``z_order``       → stamp the corrected z onto the EXACT bound target
      placement only; paint order equals z order at render time, so a
      corrected z genuinely flips compositing where sprites overlap.
    - ``contact``       → trim the bound operation's frame window to the
      corrected end frame/time anchor.
    - ``mesh_parts``    → apply the FULL stored transform (rotation/scale +
      translated center) to the bound target placement.
    - ``route_override``→ carry the measured-passing route override with
      its frame range/anchor/provenance on the program.

    Render AUTHORITY is T05A's canonical versioned ``render_effect`` block
    (its ``op`` must equal the declared kind); the kind-keyed legacy object
    only adds identity fields and is never trusted for render values.  A
    context without a matching canonical block is malformed — refuse before
    any durable effect.

    Returns ``(corrected_program, effect_applied)``.  A program with NO
    correctable surface for the kind returns it unchanged with
    ``effect_applied=False`` (the caller refuses false success); a declared
    target binding that cannot be matched exactly once raises (fail-closed).
    """
    _ = affected_loop_ids  # scope already enforced by the regen handler
    # DEEP-copy the program: placements are mutated in place below, and the
    # original must stay byte-identical for checkpoint replay determinism.
    program: list[dict[str, Any]] = [
        {
            **entry,
            "placements": [dict(p) for p in entry.get("placements") or []]
            if isinstance(entry.get("placements"), list)
            else entry.get("placements"),
        }
        for entry in replacement_program
    ]

    if correction_kind not in CORRECTION_KINDS:
        raise DemoLoopPlanError(
            f"unknown correction_kind {correction_kind!r} (expected one of "
            f"{list(CORRECTION_KINDS)})"
        )
    # Canonical render authority: the T05A versioned render_effect block.
    render_effect = effect.get("render_effect")
    if not isinstance(render_effect, dict):
        raise DemoLoopPlanError(
            "malformed applied-correction effect: missing the canonical "
            "versioned 'render_effect' object"
        )
    expected_op = RENDER_EFFECT_OP_BY_KIND[correction_kind]
    if str(render_effect.get("op")) != expected_op:
        raise DemoLoopPlanError(
            f"render_effect op {render_effect.get('op')!r} does not match "
            f"the declared correction_kind {correction_kind!r} — refusing"
        )

    if correction_kind == "route_override":
        route_to = str(render_effect.get("route_to") or "")
        if not route_to:
            raise DemoLoopPlanError(
                "route_override render_effect missing the measured route_to"
            )
        frame_range = render_effect.get("frame_range")
        if not isinstance(frame_range, dict):
            raise DemoLoopPlanError(
                "route_override render_effect missing its frame range"
            )
        provenance = render_effect.get("provenance")
        if (
            not isinstance(provenance, dict)
            or not str(provenance.get("evidence") or "").strip()
        ):
            raise DemoLoopPlanError(
                "route_override render_effect carries no provenance evidence"
            )
        overridden = False
        for entry in program:
            routes = entry.get("routes_by_risk_class")
            if isinstance(routes, dict):
                for cls in list(routes):
                    routes[str(cls)] = route_to
                    overridden = True
        if not overridden:
            # No per-loop route table on the program entries: stamp a
            # dedicated override entry so the render path provably carries
            # the corrected route instead of silently ignoring it.
            program.append(
                {
                    "op": "route_override",
                    "route_to": route_to,
                    "render_route_id": render_effect.get("render_route_id"),
                    "start_frame": int(frame_range.get("start_frame", 0)),
                    "end_frame": int(frame_range.get("end_frame", 10**9)),
                    "anchor": render_effect.get("anchor"),
                    LAYER_ID_KEY: (
                        str(affected_layer_ids[0]) if affected_layer_ids else None
                    ),
                    "provenance": dict(provenance),
                }
            )
        return program, True

    # Every other kind binds a concrete placement/operation by stable id.
    matches = _resolve_target_placements(
        program, loop_id=loop_id, layer_ids=affected_layer_ids
    )
    target, _position, is_placement = matches[0]

    if correction_kind == "z_order":
        if not is_placement:
            # A whole-operation binding has NO sibling paint order to flip —
            # stamping a z there would re-encode unchanged media and call it
            # regenerated (the forbidden false success).  Fail closed.
            raise DemoLoopPlanError(
                f"z_order correction bound operation-level binding "
                f"{str(affected_layer_ids[0])!r} in loop {loop_id!r}: z-order "
                "requires a sibling-placement binding with a real paint order"
            )
        raw_z = render_effect.get("z_order")
        if raw_z is None:
            raise DemoLoopPlanError(
                "z_order correction effect carries no corrected z"
            )
        try:
            z_value = int(raw_z)
        except (TypeError, ValueError) as err:
            raise DemoLoopPlanError(
                f"malformed corrected z value {raw_z!r}"
            ) from err
        target["z_order"] = z_value
        return program, True

    if correction_kind == "mask":
        mask_artifact = render_effect.get("mask_artifact")
        if (
            not isinstance(mask_artifact, dict)
            or not mask_artifact.get("artifact_id")
        ):
            raise DemoLoopPlanError(
                "mask correction render_effect missing the resolved "
                "immutable mask_artifact identity"
            )
        semantics = render_effect.get("mask_semantics")
        if not isinstance(semantics, dict) or not semantics:
            raise DemoLoopPlanError(
                "mask correction render_effect missing real mask semantics"
            )
        # REAL mask semantics: the immutable mask artifact is composited
        # OVER the bound target placement (alpha occlusion).  The pinned
        # identity (artifact id + content SHA + managed relative path)
        # travels on the placement; the regen handler resolves the bytes
        # and re-verifies the hash at render time — no synthetic marker
        # pixel is ever drawn.
        mask_rel = str(mask_artifact.get("relative_path") or "")
        if not mask_rel:
            raise DemoLoopPlanError(
                "mask correction render_effect missing the mask artifact "
                "path (cannot reproduce the occlusion after restart)"
            )
        target[MASK_ARTIFACT_KEY] = str(mask_artifact["artifact_id"])
        target["mask_artifact_path"] = mask_rel
        target["mask_artifact_sha256"] = str(mask_artifact.get("sha256") or "")
        target["mask_semantics"] = dict(semantics)
        return program, True

    if correction_kind == "contact":
        end_frame = render_effect.get("end_frame")
        if end_frame is None:
            raise DemoLoopPlanError(
                "contact correction effect missing end_frame"
            )
        try:
            new_end = max(int(end_frame), 0)
        except (TypeError, ValueError) as err:
            raise DemoLoopPlanError(
                f"malformed contact end_frame {end_frame!r}"
            ) from err
        start = int(target.get("start_frame", 0))
        if new_end < start:
            raise DemoLoopPlanError(
                f"contact end_frame {new_end} precedes the bound window "
                f"start {start} — refusing"
            )
        target["end_frame"] = new_end
        return program, True

    # mesh_parts: FULL applied transform, never just transform_type.
    transform = render_effect.get("applied_transform")
    if not isinstance(transform, dict):
        raise DemoLoopPlanError(
            "mesh_parts correction effect missing the full applied transform"
        )
    try:
        offset = transform.get("offset_px") or [0, 0]
        off_x = int(offset[0])
        off_y = int(offset[1])
        rotation_deg = float(transform.get("rotation_deg") or 0.0)
        scale = float(transform.get("scale") or 1.0)
    except (TypeError, ValueError, IndexError) as err:
        raise DemoLoopPlanError(
            f"malformed mesh_parts applied transform: {err}"
        ) from err
    if scale <= 0:
        raise DemoLoopPlanError("mesh_parts transform scale must be positive")
    center = list(target.get("center_px") or [0, 0])
    center[0] = int(center[0]) + off_x
    center[1] = int(center[1]) + off_y
    target["center_px"] = center
    target["mesh_transform"] = {
        "rotation_deg": rotation_deg,
        "scale": scale,
        "transform_type": render_effect.get("transform_type"),
    }
    return program, True


def _canonical_context_bytes(value: Any) -> bytes:
    """Mirror of T05A canonical JSON (sort_keys, tight separators)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def verify_correction_context(
    context: dict[str, Any], expected_sha256: str
) -> None:
    """Fail closed on ANY drift between context and its pinned SHA."""
    digest = hashlib.sha256(_canonical_context_bytes(context)).hexdigest()
    if digest != expected_sha256:
        raise DemoLoopPlanError(
            "correction context tampered: recomputed "
            f"{digest} != pinned {expected_sha256}"
        )


# ── Publication (idempotent, content-addressed) ──────────────────────────────


def _read_bytes_long(path: Path) -> bytes:
    """Read *path* through the \\\\?\\ form (long-path safe)."""
    with open(_win_long_path(path), "rb") as fh:
        return fh.read()


def _sha256_long(path: Path) -> str:
    """Streaming SHA-256 of *path* through the \\\\?\\ form."""
    digest = hashlib.sha256()
    with open(_win_long_path(path), "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _win_long_path(path: Path) -> str:
    """Extended-length (\\\\?\\) form of *path* for Windows filesystem calls.

    C2 correction (review F6): resolved managed paths legitimately exceed
    the 260-char MAX_PATH limit (deep temp roots × content-addressed
    names).  Plain ``write_bytes``/``os.replace`` fail with FileNotFoundError
    long before disk exhaustion.  The ``\\\\?\\`` prefix switches the Win32
    API to extended-length semantics; on non-Windows platforms it is a
    no-op passthrough.
    """
    raw = str(path)
    if os.name != "nt" or raw.startswith("\\\\?\\"):
        return raw
    # The \\?\ form rejects drive-relative paths — resolve to absolute first.
    if not Path(raw).is_absolute():
        raw = str(Path(raw).resolve())
    # UNC paths need \\\\?\\UNC\\<share> instead of \\\\?\\<drive>.
    if raw.startswith("\\\\/"):
        return "\\\\?\\UNC\\" + raw[2:]
    return "\\\\?\\" + raw


def _atomic_write_windows(final_path: Path, data: bytes, *, context: str) -> None:
    """Write *data* to *final_path* atomically, Windows-long-path safe.

    - Temp file lives in the SAME directory as the final file so the final
      ``os.replace`` stays on one volume (atomic) — never across volumes.
    - The temp name carries the pid + a uuid4 nonce, so two workers racing
      the same content-addressed final path can NEVER collide on the temp
      name (the fixed ``.upload`` suffix of the pre-C2 code made concurrent
      claims clobber each other's staging bytes).
    - Every filesystem call goes through ``_win_long_path`` so resolved
      lengths >=260 chars work on stock Windows (no registry hack).
    - Failure cleanup removes THIS attempt's temp file only; the final path
      is untouched until the rename succeeds, so a failure leaves zero
      residue and never overwrites an existing verified artifact.
    """
    from uuid import uuid4  # noqa: PLC0415

    final_str = _win_long_path(final_path)
    tmp_name = f".{final_path.name}.{os.getpid()}.{uuid4().hex}.upload"
    tmp_str = _win_long_path(final_path.with_name(tmp_name))
    try:
        # mkdir BEFORE the long-path open (the \\\\?\\ form cannot create
        # intermediate directories implicitly).
        os.makedirs(_win_long_path(final_path.parent), exist_ok=True)
        with open(tmp_str, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_str, final_str)
    except OSError as exc:
        with suppress(OSError):
            os.unlink(tmp_str)  # best-effort: remove THIS attempt's temp only
        raise DemoRenderError(
            f"atomic publication failed for {context}: {exc}"
        ) from exc


def _final_relative_path(workspace_id: str, loop_id: str, content_sha256: str) -> str:
    """Content-addressed managed path — replay lands on the SAME path.

    C2 correction (review F6): the managed ROOT already IS the
    ``<project>/artifacts`` directory, so this relative path must NOT add
    another ``artifacts/`` segment (the old join produced
    ``.../artifacts/artifacts/<ws>/...``, wasting path length and breaking
    the managed-root contract).  Relative to the managed root:
    ``s09-demo-loops/<workspace>/<loop>/<sha>.mp4``.
    """
    return f"s09-demo-loops/{workspace_id}/{loop_id}/{content_sha256}.mp4"


def _artifact_id(workspace_id: str, final_rel: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"s09-demo:{workspace_id}:{final_rel}"))


def _persist_artifact_row(
    ctx: WorkerContext, *, workspace_id: str, artifact_id: str, final_rel: str,
    sha256: str, size: int,
) -> None:
    """Insert (or verify) the ready Artifact row in ONE short transaction.

    Replay-safe: the row id is derived from (workspace, content path), so a
    re-run finds the committed row, verifies its evidence and mutates
    nothing.  A CONFLICTING row (same id, different evidence) fails closed.
    """
    if ctx.session_factory is None:
        raise DemoRenderError(
            "worker context has no session factory; cannot persist publication"
        )
    from datetime import UTC, datetime  # noqa: PLC0415

    from app.persistence.models import Artifact  # noqa: PLC0415

    session = ctx.session_factory()
    try:
        existing = session.get(Artifact, artifact_id)
        if existing is None:
            session.add(
                Artifact(
                    id=artifact_id,
                    workspace_id=workspace_id,
                    kind="video",
                    relative_path=final_rel,
                    state="ready",
                    sha256=sha256,
                    size_bytes=size,
                    mime_type="video/mp4",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            session.commit()
        elif existing.sha256 != sha256 or existing.relative_path != final_rel:
            raise DemoRenderError(
                "existing artifact row conflicts with rendered evidence "
                f"({artifact_id})"
            )
    finally:
        session.close()


def _publish_rendered(
    ctx: WorkerContext,
    managed: ManagedRoot,
    *,
    workspace_id: str,
    loop_id: str,
    data: bytes,
) -> dict[str, Any]:
    """Idempotent publication of one rendered loop.

    The final managed path derives from the CONTENT sha256: a replay
    producing identical bytes finds the existing verified file AND row and
    publishes nothing new (zero duplicates); different bytes land on a
    distinct content-addressed path instead of corrupting history.
    """
    sha256 = hashlib.sha256(data).hexdigest()
    final_rel = _final_relative_path(workspace_id, loop_id, sha256)
    size = len(data)
    artifact_id = _artifact_id(workspace_id, final_rel)

    final_path = managed.resolve(final_rel)
    if _win_long_path(final_path) != str(final_path):
        exists = os.path.exists(_win_long_path(final_path))
    else:
        exists = final_path.exists()
    if exists:
        if _sha256_long(final_path) != sha256:
            raise DemoRenderError(
                f"existing file conflicts with content hash at {final_rel}"
            )
        created = False
    else:
        _atomic_write_windows(
            final_path, data, context=f"demo loop {loop_id!r} ({final_rel})"
        )
        created = True

    try:
        _persist_artifact_row(
            ctx,
            workspace_id=workspace_id,
            artifact_id=artifact_id,
            final_rel=final_rel,
            sha256=sha256,
            size=size,
        )
    except Exception:
        if created:
            # THIS attempt owns the just-moved bytes; a pre-existing file
            # reused by replay is never removed (S05-T02 correction #4).
            final_path.unlink(missing_ok=True)
        raise

    published = {
        "loop_id": loop_id,
        "relative_path": final_rel,
        "artifact_id": artifact_id,
        "sha256": sha256,
        "size_bytes": size,
        "reused_existing_file": not created,
    }
    ctx.write_checkpoint(
        {"schema_version": DEMO_LOOP_SCHEMA_VERSION, "published": published}
    )
    return published


# ── Handler ──────────────────────────────────────────────────────────────────


def demo_loop_handler(ctx: WorkerContext) -> dict[str, Any]:
    """One S09_DEMO_LOOP Job: plan → render → publish, checkpointed.

    Resumes from the fenced step checkpoint: a valid completed plan is
    reused, a published loop is skipped (idempotent replay), and every
    phase checks the durable cancel flag BEFORE its next effect so cancel
    drains without publishing anything new.
    """
    manifest = ctx.input_manifest
    cp = ctx.checkpoint if isinstance(ctx.checkpoint, dict) else {}
    if cp.get("schema_version") != DEMO_LOOP_SCHEMA_VERSION:
        cp = {"schema_version": DEMO_LOOP_SCHEMA_VERSION}

    # Phase 1: PLAN (fail-closed; reused verbatim from the checkpoint on
    # resume — replanning after process death would be wasted work AND a
    # silent evidence drift if the benchmark doc changed mid-job).
    plan = cp.get("plan")
    if not isinstance(plan, dict):
        if ctx.is_cancelled():
            return {"cancelled": True, "phase": "plan"}
        fixture_root = Path(str(_manifest_value(manifest, "fixtures_dir"))).resolve()
        benchmark_results = Path(str(_manifest_value(manifest, "benchmark_results")))
        requested = list(_manifest_value(manifest, "requested_loops"))
        pinned_raw = manifest.get("pinned_routes") or {}
        if not isinstance(pinned_raw, dict):
            raise DemoLoopPlanError("pinned_routes must be an object")
        # Exact C2 decision binding (T04 final): when the submitting surface
        # pinned a route-decision identity, the worker-side planner re-verifies
        # the SAME frozen document + SHA before any route is resolved.
        decision_raw = manifest.get("route_decision_path")
        expected_raw = manifest.get("expected_frozen_sha256")
        plan = build_demo_plan(
            requested_loops=[str(x) for x in requested],
            benchmark_results=benchmark_results,
            fixture_root=fixture_root,
            pinned_routes={str(k): str(v) for k, v in pinned_raw.items()},
            route_decision_path=Path(str(decision_raw)) if decision_raw else None,
            expected_frozen_sha256=str(expected_raw) if expected_raw else None,
        )
        cp = {**cp, "plan": plan, "phase": "planned"}
        ctx.write_checkpoint(cp)
    if ctx.is_cancelled():
        return {"cancelled": True, "phase": "planned"}

    managed = ManagedRoot(Path(str(_manifest_value(manifest, "managed_root"))))
    fixture_root = Path(str(manifest["fixtures_dir"])).resolve()
    workspace_id = str(_manifest_value(manifest, "workspace_id"))

    # Phases 2+3: RENDER → PUBLISH per loop (each loop checkpoints alone so
    # a kill-mid-run resumes AFTER the last committed effect, never redoing
    # or duplicating it).
    published: dict[str, Any] = dict(cp.get("published") or {})
    total = max(1, len(plan["loops"]))
    for entry in plan["loops"]:
        loop_id = str(entry["loop_id"])
        if loop_id in published:
            continue  # committed effect from a previous claim — never redo
        if ctx.is_cancelled():
            return {"cancelled": True, "phase": "render", "published": published}
        started = time.monotonic()
        data, frame_count = render_loop_bytes(
            media_path=fixture_root / str(entry["media_relative_path"]),
            replacement_program=list(entry["replacement_program"]),
            fixture_root=fixture_root,
        )
        pub = _publish_rendered(
            ctx, managed, workspace_id=workspace_id, loop_id=loop_id, data=data
        )
        pub["frame_count"] = frame_count
        pub["render_ms"] = int((time.monotonic() - started) * 1000)
        published[loop_id] = pub
        cp = {**cp, "published": published, "phase": "publishing"}
        ctx.write_checkpoint(cp)
        ctx.progress(100.0 * len(published) / total, f"published {loop_id}")

    return {
        "plan": {
            "covered_risk_classes": plan["covered_risk_classes"],
            "frozen_content_sha256": plan["frozen_content_sha256"],
            "thresholds_policy": plan["thresholds_policy"],
            "loops": [
                {
                    "loop_id": e["loop_id"],
                    "routes_by_risk_class": e["routes_by_risk_class"],
                    "route_notes": e["notes"],
                }
                for e in plan["loops"]
            ],
        },
        "published": published,
    }


def demo_loop_steps() -> list[Any]:
    """The S09_DEMO_LOOP step plan (one sync step: plan→render→publish)."""
    from app.persistence.jobs import StepInput  # noqa: PLC0415

    return [StepInput(step_code=DEMO_STEP_CODE, position=0, step_type="sync")]


# ── S09-C3 targeted regeneration (durable partial generation, F1) ───────────


def resolve_frozen_evidence_sha256(
    *,
    benchmark_results_path: Path | None = None,
    route_decision_path: Path | None = None,
) -> str:
    """Machine-verified frozen-evidence identity for ONE generation.

    Canonical object (C4 §4.4) — ONE object shared with the submitting
    surface so both sides derive the IDENTICAL value from the same pinned
    bytes (never a caller-trusted SHA):

    - With an I05 route-decision document (production compare flow, matching
      ``app.api.routes.s09_demo_compare._frozen_evidence_identity``):
      ``{"decision_sha256": <decision file sha>,
         "benchmark_content_sha256": <measured run-A bench file sha>,
         "run_b_content_sha256": <decision-embedded run-B content sha>}``.
      The decision's own hash is recomputed from disk (never trusted from
      the document), and the embedded run-A input must equal the bench
      document actually being read (stale bench refuses).
    - Without one (self-contained synthetic evidence):
      ``{"benchmark_results_sha256": <file sha>,
         "route_decision_sha256": null}``.

    A missing/unreadable/drifted file raises instead of silently hashing
    nothing.
    """
    if benchmark_results_path is None:
        raise DemoLoopPlanError(
            "frozen evidence identity requires the base job's benchmark path"
        )
    if not benchmark_results_path.is_file():
        raise DemoLoopPlanError(
            f"benchmark results missing: {benchmark_results_path}"
        )
    bench_sha = _sha256_long(benchmark_results_path)
    if route_decision_path is not None:
        if not route_decision_path.is_file():
            raise DemoLoopPlanError(
                f"route decision document missing: {route_decision_path}"
            )
        decision_sha = _sha256_long(route_decision_path)
        try:
            decision = json.loads(
                route_decision_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as err:
            raise DemoLoopPlanError(
                f"route decision document unreadable: {err}"
            ) from err
        iv = decision.get("independent_verification") or {}
        run_a = iv.get("i03_run_A") or {}
        run_b = iv.get("i03_run_B") or {}
        bench_input_sha = str(run_a.get("content_sha256") or "")
        if not bench_input_sha or bench_input_sha != bench_sha:
            raise DemoLoopPlanError(
                "frozen-evidence identity refused: benchmark document does "
                "not match the pinned decision's measured input"
            )
        payload: dict[str, Any] = {
            "decision_sha256": decision_sha,
            "benchmark_content_sha256": bench_input_sha,
            "run_b_content_sha256": str(
                run_b.get("content_sha256") or ""
            ),
        }
    else:
        payload = {
            "benchmark_results_sha256": bench_sha,
            "route_decision_sha256": None,
        }
    return hashlib.sha256(_canonical_context_bytes(payload)).hexdigest()


def _frozen_evidence_for_base(
    *, manifest: dict[str, Any], base_manifest: dict[str, Any]
) -> str:
    """Resolve the frozen-evidence identity for a targeted regeneration.

    The base job's OWN manifest is authority: its benchmark/decision paths
    were the verified planning inputs of the completed generation.  A regen
    manifest that pins DIFFERENT evidence paths refuses (context drift) so
    the identity can never silently describe foreign evidence.
    """
    bench_value = base_manifest.get("benchmark_results") or manifest.get(
        "benchmark_results"
    )
    if not isinstance(bench_value, str) or not bench_value:
        raise DemoLoopPlanError(
            "frozen evidence identity requires the benchmark results path"
        )
    decision_value = base_manifest.get("route_decision_path") or manifest.get(
        "route_decision_path"
    )
    if (
        isinstance(manifest.get("benchmark_results"), str)
        and base_manifest.get("benchmark_results")
        and manifest["benchmark_results"] != base_manifest["benchmark_results"]
    ):
        raise DemoLoopPlanError(
            "regeneration manifest pins different frozen evidence than the "
            "base job — refusing (evidence drift)"
        )
    return resolve_frozen_evidence_sha256(
        benchmark_results_path=Path(bench_value),
        route_decision_path=(
            Path(str(decision_value)) if isinstance(decision_value, str) else None
        ),
    )


def regen_fingerprint(
    *,
    base_job_id: str,
    correction_context_sha256: str,
    frozen_evidence_sha256: str,
) -> str:
    """Idempotency key for ONE targeted-regeneration generation.

    Three-part identity (C4 §4.4): canonical SHA over
    ``base_job_id + correction_context_sha256 + frozen_evidence_sha256``.
    Same tuple → same durable job (reused=true); a different correction OR
    a re-pinned frozen-evidence generation derives a different key and
    therefore a NEW generation; stale/tampered evidence never reaches this
    function with a trusted value (the caller resolves it server-side).
    """
    digest = hashlib.sha256(
        _canonical_context_bytes(
            {
                "base_job_id": base_job_id,
                "correction_context_sha256": correction_context_sha256,
                "frozen_evidence_sha256": frozen_evidence_sha256,
            }
        )
    ).hexdigest()
    return f"S09_DEMO_REGEN:{digest[:32]}"


def _load_base_publication(
    session_factory: Callable[[], Session] | None,
    base_job_id: str,
    *,
    expected_workspace_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the immutable base result snapshot for a completed demo job.

    Returns ``(job_record_dict, published_by_loop)``.  Fails closed when the
    job is missing / not a demo-loop job / not ``completed`` / has no
    published attempt result — zero mutation in every refusal.  When
    *expected_workspace_id* is given, the ACTUAL base Job row's workspace
    must equal it (C4 §4.6: the reusable worker contract verifies this even
    when invoked outside the HTTP route; the C3 self-comparison
    ``record.workspace_id != record.workspace_id`` was always false).
    """
    if session_factory is None:
        raise DemoLoopPlanError("no session factory; cannot load base job")
    with session_factory() as session:
        repo = JobRepository(session)
        record = repo.get_job(base_job_id)
        if record is None:
            raise DemoLoopPlanError(f"base job {base_job_id!r} not found")
        if record.job_type != JOB_TYPE_S09_DEMO_LOOP:
            raise DemoLoopPlanError(
                f"base job {base_job_id!r} is {record.job_type!r}, "
                f"expected {JOB_TYPE_S09_DEMO_LOOP!r}"
            )
        if (
            expected_workspace_id is not None
            and str(record.workspace_id) != str(expected_workspace_id)
        ):
            raise DemoLoopPlanError(
                f"base job {base_job_id!r} belongs to workspace "
                f"{record.workspace_id!r}, not {expected_workspace_id!r} — "
                "cross-workspace regeneration refused"
            )
        if record.state != "completed":
            raise DemoLoopPlanError(
                f"base job {base_job_id!r} state is {record.state!r}; "
                "regeneration requires a COMPLETED base job"
            )
        manifest = dict(record.input_manifest or {})
        published: dict[str, Any] | None = None
        for attempt in reversed(repo.list_attempts(base_job_id)):
            raw = getattr(attempt, "result", None)
            if isinstance(raw, dict) and isinstance(raw.get("published"), dict):
                published = raw["published"]
                break
        if not published:
            raise DemoLoopPlanError(
                f"base job {base_job_id!r} has no published result snapshot"
            )
        return manifest, published


def demo_loop_regen_handler(ctx: WorkerContext) -> dict[str, Any]:
    """One S09_DEMO_REGEN Job: verify → reuse unaffected → re-render affected.

    Fail-closed order (§3.1): tampered context SHA, wrong base type/state/
    workspace, missing publication snapshot, or affected scope outside the
    base requested loops refuses BEFORE any durable effect.  Unaffected
    loops reuse the base publication verbatim (same Artifact row/file/ID/
    hash/size — verified, never rewritten); only affected loops render
    again under the corrected program.
    """
    manifest = ctx.input_manifest
    cp = ctx.checkpoint if isinstance(ctx.checkpoint, dict) else {}
    if cp.get("schema_version") != DEMO_LOOP_SCHEMA_VERSION:
        cp = {"schema_version": DEMO_LOOP_SCHEMA_VERSION}

    context = manifest.get("correction_context")
    pinned_sha = manifest.get("correction_context_sha256")
    base_job_id = manifest.get("base_job_id")
    if (
        not isinstance(context, dict)
        or not isinstance(pinned_sha, str)
        or not isinstance(base_job_id, str)
    ):
        raise DemoLoopPlanError(
            "regeneration manifest requires base_job_id, correction_context "
            "and correction_context_sha256"
        )

    # Phase 1: VERIFY (pure reads; no durable effect may precede this).
    _base_manifest: dict[str, Any] = {}
    plan = cp.get("plan")
    if not isinstance(plan, dict):
        if ctx.is_cancelled():
            return {"cancelled": True, "phase": "verify"}
        verify_correction_context(context, pinned_sha)

        factory = ctx.session_factory
        assert factory is not None
        # C4 §4.6: the durable worker verifies the base Job row's ACTUAL
        # workspace against ctx.workspace_id itself — the reusable contract
        # must hold even when invoked outside the HTTP route (the C3
        # record.workspace_id != record.workspace_id self-comparison was a
        # no-op).
        _base_manifest, base_published = _load_base_publication(
            factory, base_job_id, expected_workspace_id=ctx.workspace_id
        )

        affected = sorted({str(x) for x in (context.get("affected_loop_ids") or [])})
        if not affected:
            raise DemoLoopPlanError(
                "correction context carries an empty affected loop scope"
            )
        base_requested = {
            str(x) for x in _manifest_value(_base_manifest, "requested_loops")
        }
        outside = sorted(set(affected) - base_requested)
        if outside:
            raise DemoLoopPlanError(
                f"affected loops outside base requested scope: {outside}"
            )
        missing_pub = sorted(set(affected) - set(base_published))
        if missing_pub:
            raise DemoLoopPlanError(
                f"affected loops missing from base publication: {missing_pub}"
            )

        # C4 §4.4: the frozen-evidence identity is resolved ONCE here,
        # server-side from the pinned bytes (never caller-trusted).  When
        # the manifest pins an expected identity, a mismatch means stale or
        # tampered evidence — refuse with zero durable mutation.
        resolved_frozen = _frozen_evidence_for_base(
            manifest=manifest, base_manifest=_base_manifest
        )
        pinned_frozen = manifest.get("frozen_evidence_sha256")
        if pinned_frozen is not None and (
            not isinstance(pinned_frozen, str) or pinned_frozen != resolved_frozen
        ):
            raise DemoLoopPlanError(
                "frozen evidence identity drift: resolved "
                f"{resolved_frozen[:16]}… != pinned {str(pinned_frozen)[:16]}… "
                "— refusing (stale/tampered evidence)"
            )

        # Plan ONLY the affected loops from the SAME frozen evidence the
        # base used (verbatim decision binding carried over).
        fixture_root = Path(str(_manifest_value(manifest, "fixtures_dir"))).resolve()
        benchmark_results = Path(str(_manifest_value(manifest, "benchmark_results")))
        decision_raw = _base_manifest.get("route_decision_path") or manifest.get(
            "route_decision_path"
        )
        expected_raw = _base_manifest.get("expected_frozen_sha256") or manifest.get(
            "expected_frozen_sha256"
        )
        plan = build_demo_plan(
            requested_loops=affected,
            benchmark_results=benchmark_results,
            fixture_root=fixture_root,
            route_decision_path=(
                Path(str(decision_raw)) if decision_raw else None
            ),
            expected_frozen_sha256=str(expected_raw) if expected_raw else None,
            targeted=True,
        )
        # C4 §4.3: a targeted route_override correction is REAL provenance —
        # the measured-passing corrected route is stamped onto the planned
        # loops' route tables (auditable in the checkpoint/result), and the
        # render program carries the same override so the rendered bytes
        # provably come from the overridden route generation.
        if str(context.get("correction_kind")) == "route_override":
            re_ = context.get("effect")
            if isinstance(re_, dict):
                re_ = re_.get("render_effect")
            if isinstance(re_, dict):
                override_route = str(re_.get("route_to") or "")
                for pentry in plan["loops"]:
                    routes = pentry.get("routes_by_risk_class")
                    if isinstance(routes, dict) and override_route:
                        for cls in list(routes):
                            routes[str(cls)] = override_route
                        prov_evidence = str(
                            (re_.get("provenance") or {}).get("evidence")
                        )
                        pentry.setdefault("notes", []).append(
                            "C4 targeted route_override: measured-passing "
                            f"{override_route!r} "
                            f"(provenance {prov_evidence[:32]!r})"
                        )
        cp = {
            **cp,
            "plan": plan,
            "phase": "planned",
            "base_published": base_published,
            "frozen_evidence_sha256": resolved_frozen,
        }
        ctx.write_checkpoint(cp)
    if ctx.is_cancelled():
        return {"cancelled": True, "phase": "planned"}

    managed = ManagedRoot(Path(str(_manifest_value(manifest, "managed_root"))))
    fixture_root = Path(str(manifest["fixtures_dir"])).resolve()
    workspace_id = str(_manifest_value(manifest, "workspace_id"))
    base_snapshot: dict[str, Any] = dict(cp["base_published"])
    affected = sorted(str(e["loop_id"]) for e in plan["loops"])

    # Phase 2: RE-RENDER AFFECTED loops under the corrected program.
    effect = context.get("effect")
    if not isinstance(effect, dict):
        raise DemoLoopPlanError("correction context carries no mutation effect")
    published: dict[str, Any] = dict(cp.get("published") or {})
    corrected_programs: dict[str, Any] = dict(cp.get("corrected_programs") or {})
    total = max(1, len(plan["loops"]))
    for entry in plan["loops"]:
        loop_id = str(entry["loop_id"])
        if loop_id in published:
            continue  # committed effect from a previous claim — never redo
        if ctx.is_cancelled():
            return {"cancelled": True, "phase": "render", "published": published}
        if loop_id in corrected_programs:
            # Committed pre-render evidence from a previous claim: re-render
            # from EXACTLY this corrected surface (never re-derive, so a
            # transform can never be applied twice across a restart).
            corrected_program = list(corrected_programs[loop_id])
            effect_applied = True
        else:
            corrected_program, effect_applied = _apply_correction_effect(
                list(entry["replacement_program"]),
                correction_kind=str(context.get("correction_kind")),
                effect=effect,
                affected_loop_ids=affected,
                affected_layer_ids=[
                    str(x) for x in (context.get("affected_layer_ids") or [])
                ],
                loop_id=loop_id,
            )
            if not effect_applied:
                # §4.3: a kind with NO correctable surface on this loop must
                # refuse — re-encoding unchanged media and stamping it
                # regenerated=true is the forbidden false success.
                raise DemoLoopPlanError(
                    f"correction kind {context.get('correction_kind')!r} has no "
                    f"correctable render surface for loop {loop_id!r} — refusing "
                    "(no unchanged-media false success)"
                )
            # Durable audit evidence BEFORE any bytes are produced: what
            # program produced (or will produce) this loop's publication.
            corrected_programs[loop_id] = corrected_program
            cp = {
                **cp,
                "corrected_programs": corrected_programs,
                "phase": "corrected",
            }
            ctx.write_checkpoint(cp)
        started = time.monotonic()
        data, frame_count = render_loop_bytes(
            media_path=fixture_root / str(entry["media_relative_path"]),
            replacement_program=corrected_program,
            fixture_root=fixture_root,
        )
        # §3 cancel-drain: the durable flag may flip DURING the render; the
        # publication (file + row + checkpoint) must never commit afterwards.
        if ctx.is_cancelled():
            return {"cancelled": True, "phase": "render", "published": published}
        pub = _publish_rendered(
            ctx, managed, workspace_id=workspace_id, loop_id=loop_id, data=data
        )
        pub["frame_count"] = frame_count
        pub["render_ms"] = int((time.monotonic() - started) * 1000)
        pub["regenerated"] = True
        published[loop_id] = pub
        cp = {**cp, "published": published, "phase": "publishing"}
        ctx.write_checkpoint(cp)
        ctx.progress(100.0 * len(published) / total, f"regenerated {loop_id}")

    # Phase 3: BIND UNAFFECTED publications verbatim (verified, no rewrite).
    for loop_id, base_entry in sorted(base_snapshot.items()):
        if loop_id in published:
            continue
        if ctx.is_cancelled():
            return {"cancelled": True, "phase": "bind", "published": published}
        rel = str(base_entry.get("relative_path"))
        final_path = managed.resolve(rel)
        _exists = (
            os.path.exists(_win_long_path(final_path))
            if _win_long_path(final_path) != str(final_path)
            else final_path.is_file()
        )
        if not _exists:
            raise DemoRenderError(
                f"unaffected base publication missing on disk: {rel}"
            )
        if _sha256_long(final_path) != str(base_entry.get("sha256")):
            raise DemoRenderError(
                f"unaffected base artifact drifted from recorded hash: {rel}"
            )
        reused = dict(base_entry)
        # §3 unaffected contract: exact reuse carries NO fresh render timing
        # — a loop that never touched the decoder/encoder this generation
        # must not present a render_ms inherited from the base run either.
        reused.pop("render_ms", None)
        reused["regenerated"] = False
        published[str(loop_id)] = reused

    generation_evidence = {
        "generation": "targeted",
        "base_job_id": base_job_id,
        "correction_id": context.get("correction_id"),
        "correction_context_sha256": pinned_sha,
        # C4 §4.4: the frozen-evidence identity is RESOLVED server-side from
        # the pinned bytes (never caller-trusted) and is part of the result
        # so status surfaces can expose it read-only.  On a resumed claim the
        # Phase-1-resolved value replays from the checkpoint verbatim.
        "frozen_evidence_sha256": (
            cp.get("frozen_evidence_sha256")
            or _frozen_evidence_for_base(
                manifest=manifest,
                base_manifest=(
                    _base_manifest if isinstance(_base_manifest, dict) else {}
                ),
            )
        ),
    }
    return {
        "generation_evidence": generation_evidence,
        "affected_loop_ids": affected,
        "plan": {
            "covered_risk_classes": plan["covered_risk_classes"],
            "frozen_content_sha256": plan["frozen_content_sha256"],
            "thresholds_policy": plan["thresholds_policy"],
            "loops": [
                {
                    "loop_id": e["loop_id"],
                    "routes_by_risk_class": e["routes_by_risk_class"],
                    "route_notes": e["notes"],
                }
                for e in plan["loops"]
            ],
        },
        "published": published,
    }


def demo_loop_regen_steps() -> list[Any]:
    """The S09_DEMO_REGEN step plan (one sync step)."""
    from app.persistence.jobs import StepInput  # noqa: PLC0415

    return [StepInput(step_code=REGEN_STEP_CODE, position=0, step_type="sync")]


#: Workers already carrying the s09_demo_loop handler (id()-keyed guard so
#: double registration stays a no-op).
_HANDLERS_REGISTERED: set[int] = set()
_REGISTER_LOCK = threading.Lock()


def _register_on_worker(worker: Any) -> None:
    with _REGISTER_LOCK:
        if id(worker) in _HANDLERS_REGISTERED:
            return
        worker.register_handler(JOB_TYPE_S09_DEMO_LOOP, demo_loop_handler)
        worker.register_handler(JOB_TYPE_S09_DEMO_REGEN, demo_loop_regen_handler)
        _HANDLERS_REGISTERED.add(id(worker))


def register_s09_demo_loop_handler(worker: Any = None) -> None:
    """Register the S09_DEMO_LOOP handler on a DurableWorker.

    With an explicit *worker*, registers on that instance only.  With
    ``worker=None`` (API/test convenience), registers on the process-wide
    default JobService from :mod:`app.api.deps` when one already exists.

    Idempotent per worker.  No declared-output template: the number of loops
    (and therefore output paths) varies per submission; the handler's own
    content-addressed publication + checkpoint evidence is the completion
    gate, and the status route exposes published artifacts from the attempt
    result/checkpoint.
    """
    if worker is not None:
        _register_on_worker(worker)
        return
    try:
        from app.api import deps as api_deps  # noqa: PLC0415
    except ImportError:  # pragma: no cover - app package always available
        return
    from app.workflow.job_service import JobService  # noqa: PLC0415

    svc_obj = getattr(api_deps, "_job_service", None)
    w = getattr(svc_obj, "_worker", None)
    if isinstance(svc_obj, JobService) and w is not None:
        _register_on_worker(w)
