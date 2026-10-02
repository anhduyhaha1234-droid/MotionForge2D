"""Shot-level reskin executor — the ONE door from FullApply chunks to the
pinned Comfy shot engine (MF-END-19.3).

This module is the shot-level executor the S10 worker calls for the
``comfy_shot_engine`` execution backend.  It is deliberately fail-closed and
side-effect bounded:

* the run's execution-backend manifest arrives already validated by the
  deterministic planner (``app.services.s10_chunk_plan``); this module refuses
  any backend other than ``comfy_shot_engine``;
* the model PROFILE must exist in the frozen registry
  (``app/media_workflows/model_profiles.json``) with an ``ELIGIBLE*`` status —
  an ineligible profile (e.g. the watermark-copy VACE challenger) refuses with
  a typed code BEFORE any GPU work;
* every input is pinned by sha256 under the managed root; the per-shot driving
  window is staged by this module (byte-copy for a full-span window so the
  source audio/timebase survive; frame-accurate re-encode otherwise);
* the graph is the profile's frozen graph file (file digest pinned); its own
  declared ``parameters`` pointers are the ONLY patches applied — a parameter
  that is not declared, or a required parameter without a value, refuses;
* the submission goes through the app's ONE Comfy door
  (``ComfyShotEngine``); the returned artifacts are re-hashed on disk, decoded
  and refused if they are the SOURCE bytes (the source is never returned as a
  successful output);
* the accepted (or rejected) execution record is written atomically under the
  managed root (``shot_render/<shot_id>/<chunk_id>.json``).

Server-input contract (driver side): the graph references its input files by
BASENAME; the staging copy of each declared input lives under
``media_engine/comfy_shot_engine/stage/inputs/<chunk_id>/``.  The operator of
the pinned Comfy instance materialises those staged files into the instance's
input directory before submit; the record lists every staged input with its
sha256 so the driver can prove the mirror byte-for-byte.  (The engine itself
never uploads inputs — the pinned mf-comfy adapter submits the graph as-is.)

No mock/fixture fallback exists anywhere in this module: any missing engine,
profile, input, artifact or capability is a typed refusal.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from enum import Enum
from pathlib import Path
from typing import Any

from app.persistence.artifacts import ManagedRoot, hash_file
from app.schemas.shot_reskin import (
    ArtifactRef,
    ContentHash,
    EngineAudioHandoff,
    EngineDecodedFacts,
    EngineInputBinding,
    EngineModelBinding,
    EngineOutputContract,
    EngineRequestIdentity,
    EngineResourceBudget,
    EngineSourceLock,
    EngineWorkflowPin,
    ReferenceItem,
    RoleCastBinding,
    SourceSpan,
    TimebaseFacts,
)

__all__ = [
    "DEFAULT_CAPABILITY",
    "ENGINE_FACTORY",
    "PROFILE_KIND",
    "PROFILES_RELPATH",
    "SHOT_RENDER_SCHEMA",
    "SHOT_RENDER_SUBDIR",
    "ShotRenderRefusalCode",
    "ShotRenderRefusal",
    "load_profile_registry",
    "select_profile",
    "profile_models",
    "prepare_graph",
    "run_shot_render",
    "s10_window_basename",
    "s10_unit_binding_digest",
    "s10_unit_control",
    "s10_unit_prompt_sha256",
    "s10_unit_time_map",
    "shot_render_record_rel_path",
]

SHOT_RENDER_SCHEMA = "mf.shot_render.execution_record/1"
SHOT_RENDER_SUBDIR = "shot_render"
#: Schema of the per-unit binding digest recorded beside every artifact.
UNIT_BINDING_SCHEMA = "mf.shot_render.unit_binding/1"

#: The frozen profile registry shipped with the app (MF-END-16).
PROFILES_RELPATH = "app/media_workflows/model_profiles.json"
#: The registry schema this executor understands.
PROFILES_SCHEMA = "mf.model_profiles.v1"
#: Only profiles declared for the shot-reskin video stage are selectable.
PROFILE_KIND = "shot_reskin_video"
#: Eligibility statuses usable for a render: ELIGIBLE / ELIGIBLE_PENDING_QUALITY_OWNER.
ALLOWED_ELIGIBILITY_PREFIX = "ELIGIBLE"
#: Default engine capability of the shot video render.
DEFAULT_CAPABILITY = "source_video_motion_transfer"

#: Graph parameters the executor REQUIRES a value for whenever the graph declares them.
REQUIRED_PARAMETERS = ("anchor", "source")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HEX64 = re.compile(r"[0-9a-f]{64}")
_SAFE = re.compile(r"[^0-9A-Za-z._-]")
_POINTER = re.compile(r"^(?:graph/)?([^/]+)/inputs/([^/]+)$")


class ShotRenderRefusalCode(str, Enum):
    """Typed refusals of the shot-level executor — one code per failure class."""

    SHOT_BACKEND_UNSUPPORTED = "shot_backend_unsupported"
    SHOT_MANIFEST_INVALID = "shot_manifest_invalid"
    SHOT_PROFILE_UNKNOWN = "shot_profile_unknown"
    SHOT_PROFILE_NOT_ELIGIBLE = "shot_profile_not_eligible"
    SHOT_PROFILE_KIND_UNSUPPORTED = "shot_profile_kind_unsupported"
    SHOT_GRAPH_MISSING = "shot_graph_missing"
    SHOT_GRAPH_PIN_MISMATCH = "shot_graph_pin_mismatch"
    SHOT_GRAPH_PARAMETER_MISSING = "shot_graph_parameter_missing"
    SHOT_GRAPH_POINTER_UNRESOLVED = "shot_graph_pointer_unresolved"
    SHOT_INPUT_INVALID = "shot_input_invalid"
    SHOT_INPUT_MISSING = "shot_input_missing"
    SHOT_INPUT_DIGEST_MISMATCH = "shot_input_digest_mismatch"
    SHOT_ANCHOR_GATE_REFUSED = "shot_anchor_gate_refused"
    SHOT_ANCHOR_BINDING_MISMATCH = "shot_anchor_binding_mismatch"
    SHOT_ANCHOR_POLICY_INVALID = "shot_anchor_policy_invalid"
    SHOT_ENGINE_REFUSED = "shot_engine_refused"
    SHOT_ENGINE_FAILED = "shot_engine_failed"
    SHOT_OUTPUT_MISSING = "shot_output_missing"
    SHOT_OUTPUT_HASH_MISMATCH = "shot_output_hash_mismatch"
    SHOT_OUTPUT_FRAME_MISMATCH = "shot_output_frame_mismatch"
    SHOT_OUTPUT_TIMEBASE_MISMATCH = "shot_output_timebase_mismatch"
    SHOT_SOURCE_RETURNED_AS_OUTPUT = "shot_source_returned_as_output"


class ShotRenderRefusal(Exception):  # noqa: N818 — mirrors the contract's refusal naming
    """Typed, fail-closed refusal of a shot render attempt."""

    def __init__(self, code: ShotRenderRefusalCode, detail: str, **context: Any) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail
        self.context = context

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "detail": self.detail, "context": dict(self.context)}


# ── profile registry (frozen MF-END-16 artifact) ─────────────────────────────


def load_profile_registry(path: str | Path | None = None) -> dict[str, Any]:
    """Load the frozen model-profile registry; malformed registry refuses."""
    target = Path(path) if path is not None else _REPO_ROOT / PROFILES_RELPATH
    if not target.is_file():
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_PROFILE_UNKNOWN,
            f"model profile registry {target} is missing",
        )
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_PROFILE_UNKNOWN,
            f"model profile registry {target} is unreadable: {type(exc).__name__}:{exc}",
        ) from exc
    if not isinstance(doc, dict) or doc.get("schema_version") != PROFILES_SCHEMA:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_PROFILE_UNKNOWN,
            f"model profile registry declares schema {doc.get('schema_version')!r}, "
            f"executor requires {PROFILES_SCHEMA!r}",
        )
    return doc


def select_profile(
    profile_id: str, registry: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Select ONE eligible profile entry — refuse unknown/ineligible profiles.

    The eligibility gate is the frozen registry's own status: only statuses
    starting with ``ELIGIBLE`` (``ELIGIBLE``, ``ELIGIBLE_PENDING_QUALITY_OWNER``)
    may render.  An ``INELIGIBLE`` profile (e.g. the watermark-copy VACE
    challenger) refuses with its recorded blockers BEFORE any engine work.
    """
    reg = dict(registry) if registry is not None else load_profile_registry()
    entries = reg.get("profiles")
    if not isinstance(entries, list):
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_PROFILE_UNKNOWN,
            "model profile registry carries no profiles list",
        )
    entry: dict[str, Any] | None = None
    for candidate in entries:
        if isinstance(candidate, dict) and str(candidate.get("id") or "") == profile_id:
            entry = candidate
            break
    if entry is None:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_PROFILE_UNKNOWN,
            f"profile {profile_id!r} is not registered in {PROFILES_RELPATH}",
            profile_id=profile_id,
        )
    if str(entry.get("kind") or "") != PROFILE_KIND:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_PROFILE_KIND_UNSUPPORTED,
            f"profile {profile_id!r} kind {entry.get('kind')!r} is not {PROFILE_KIND!r}",
            profile_id=profile_id,
        )
    eligibility = entry.get("eligibility")
    status = ""
    if isinstance(eligibility, dict):
        status = str(eligibility.get("status") or "")
    if not status.startswith(ALLOWED_ELIGIBILITY_PREFIX):
        blockers: list[Any] = []
        if isinstance(eligibility, dict):
            blockers = list(eligibility.get("blockers") or [])
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_PROFILE_NOT_ELIGIBLE,
            f"profile {profile_id!r} eligibility {status!r} is not eligible "
            f"(blockers: {blockers})",
            profile_id=profile_id,
            status=status,
            blockers=blockers,
        )
    return entry


def _precision_token(rel: str) -> str:
    name = Path(rel).name.lower()
    for token in ("int8", "fp8", "fp16", "bf16", "fp32"):
        if token in name:
            return token
    return "unspecified"


def profile_models(profile: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Profile ``models`` → (primary pin dict, auxiliary pin dicts).

    The primary pin is the profile's ``unet`` entry (the model the graph's
    sampler loads); every other declared model file rides as an auxiliary pin.
    """
    models = profile.get("models")
    if not isinstance(models, list) or not models:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_PROFILE_UNKNOWN,
            f"profile {profile.get('id')!r} declares no model pins",
        )
    primary: dict[str, Any] | None = None
    auxiliary: list[dict[str, Any]] = []
    for entry in models:
        if not isinstance(entry, dict):
            raise ShotRenderRefusal(
                ShotRenderRefusalCode.SHOT_PROFILE_UNKNOWN,
                "profile model entry is not an object",
            )
        rel = str(entry.get("rel") or "")
        sha = str(entry.get("sha256") or "")
        if not rel or not _HEX64.fullmatch(sha):
            raise ShotRenderRefusal(
                ShotRenderRefusalCode.SHOT_PROFILE_UNKNOWN,
                f"profile model entry {entry.get('role')!r} lacks rel/sha256 pins",
            )
        pin = {
            "model_id": Path(rel).stem,
            "revision": str(entry.get("revision") or "") or None,
            "file_sha256": sha,
            "precision": _precision_token(rel),
            "size_bytes": int(entry.get("bytes") or 0),
            "role": str(entry.get("role") or ""),
        }
        if pin["role"] == "unet" and primary is None:
            primary = pin
        else:
            auxiliary.append(pin)
    if primary is None:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_PROFILE_UNKNOWN,
            f"profile {profile.get('id')!r} declares no 'unet' primary model pin",
        )
    return primary, auxiliary


# ── graph preparation (declared pointers only) ───────────────────────────────


def _resolve_pointer(pointer: str) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for part in str(pointer or "").split("|"):
        part = part.strip()
        if not part:
            continue
        match = _POINTER.fullmatch(part)
        if match is None:
            raise ShotRenderRefusal(
                ShotRenderRefusalCode.SHOT_GRAPH_POINTER_UNRESOLVED,
                f"declared parameter pointer {part!r} does not resolve to "
                "<node>/inputs/<field>",
            )
        targets.append((match.group(1), match.group(2)))
    if not targets:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_GRAPH_POINTER_UNRESOLVED,
            f"declared parameter pointer {pointer!r} carries no resolvable target",
        )
    return targets


def prepare_graph(
    graph_obj: Mapping[str, Any],
    parameters: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Patch the frozen graph through ITS OWN declared parameter pointers.

    Returns ``(patched_graph, record)``.  A requested value for a parameter the
    graph does not declare refuses (``shot_graph_parameter_missing``); a
    declared required parameter without a value refuses
    (``shot_input_missing``); an unresolvable pointer or missing node/field
    refuses.  The patched object is a deep copy — the template is untouched.
    """
    declared: dict[str, dict[str, Any]] = {}
    raw_params = graph_obj.get("parameters")
    if isinstance(raw_params, list):
        for item in raw_params:
            if isinstance(item, dict) and item.get("name"):
                declared[str(item["name"])] = item
    if not declared:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_GRAPH_PARAMETER_MISSING,
            "the frozen graph declares no settable parameters",
        )
    for name in parameters:
        if name not in declared:
            raise ShotRenderRefusal(
                ShotRenderRefusalCode.SHOT_GRAPH_PARAMETER_MISSING,
                f"graph does not declare parameter {name!r} "
                f"(declared: {sorted(declared)})",
            )
    missing_required = [
        name for name in REQUIRED_PARAMETERS if name in declared and name not in parameters
    ]
    if missing_required:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_INPUT_MISSING,
            f"required graph parameter(s) {missing_required} carry no value",
        )

    graph = json.loads(json.dumps(dict(graph_obj["graph"])))
    patch_record: dict[str, Any] = {}
    pointers_record: dict[str, Any] = {}
    for name, value in parameters.items():
        entry = declared[name]
        ptype = str(entry.get("type") or "string")
        if ptype == "int" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ShotRenderRefusal(
                ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,
                f"parameter {name!r} is declared int; got {type(value).__name__}",
            )
        elif ptype == "string" and not isinstance(value, str):
            raise ShotRenderRefusal(
                ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,
                f"parameter {name!r} is declared string; got {type(value).__name__}",
            )
        targets = _resolve_pointer(str(entry.get("pointer") or ""))
        pointers_record[name] = [f"{node}/inputs/{field}" for node, field in targets]
        for node_id, field in targets:
            node = graph.get(node_id)
            if not isinstance(node, dict):
                raise ShotRenderRefusal(
                    ShotRenderRefusalCode.SHOT_GRAPH_POINTER_UNRESOLVED,
                    f"parameter {name!r} points at node {node_id!r} which the "
                    "frozen graph does not carry",
                )
            inputs = node.get("inputs")
            if not isinstance(inputs, dict) or field not in inputs:
                raise ShotRenderRefusal(
                    ShotRenderRefusalCode.SHOT_GRAPH_POINTER_UNRESOLVED,
                    f"parameter {name!r} points at {node_id!r}/inputs/{field!r} "
                    "which the frozen graph does not carry",
                )
            inputs[field] = value
            patch_record[f"{node_id}/inputs/{field}"] = value
    return graph, {"parameter_pointers": pointers_record, "patched": patch_record}


def _graph_object_sha256(graph_obj: Mapping[str, Any]) -> str:
    def _canonical_json(payload: Any) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


    def s10_unit_prompt_sha256(request: Mapping[str, Any]) -> str:
        """sha256 of the unit's frozen prompt text (the per-unit prompt binding)."""
        text = str((request.get("parameters") or {}).get("prompt") or "")
        if not text:
            raise ShotRenderRefusal(
                ShotRenderRefusalCode.SHOT_INPUT_MISSING,
                "the request carries no prompt text (per-unit prompt binding missing)",
            )
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


    def s10_window_basename(chunk_id: str, span_start: int, span_end_exclusive: int) -> str:
        """Deterministic staged driving-window filename of one chunk/span."""
        safe_chunk = _SAFE.sub("_", str(chunk_id)) or "chunk"
        return f"shotwin_{safe_chunk}_{int(span_start)}_{int(span_end_exclusive)}.mp4"


    def s10_unit_control(request: Mapping[str, Any]) -> dict[str, Any]:
        """The frozen CONTROL of one unit: graph + output node + seed + parameters."""
        backend = dict(request.get("backend") or {})
        graph = dict(request.get("graph") or {})
        params = dict(request.get("parameters") or {})
        return {
            "profile_id": str(backend.get("profile_id") or ""),
            "capability": str(backend.get("capability") or ""),
            "graph_file": str(graph.get("file") or backend.get("graph_file") or ""),
            "graph_file_sha256": str(graph.get("file_sha256") or backend.get("graph_sha256") or ""),
            "output_node": str(backend.get("output_node") or ""),
            "seed": int(backend["seed"]) if backend.get("seed") is not None else None,
            "parameters": {str(k): params[k] for k in sorted(params)},
        }


    def s10_unit_time_map(request: Mapping[str, Any]) -> dict[str, Any]:
        """The unit's TIME MAP: source span, fps, frame count and staged window."""
        source = dict(request.get("source") or {})
        span = dict(source.get("span") or {})
        fps = dict(source.get("fps") or {})
        out = dict(request.get("output_contract") or {})
        start = int(span.get("start_frame"))
        end = int(span.get("end_frame_exclusive"))
        return {
            "source_start_frame": start,
            "source_end_frame_exclusive": end,
            "fps_num": int(fps.get("num") or out.get("fps_num") or 30),
            "fps_den": int(fps.get("den") or out.get("fps_den") or 1),
            "frame_count": int(out.get("frame_count") or (end - start)),
            "window_basename": s10_window_basename(str(request.get("chunk_id") or ""), start, end),
            "width": int(out.get("width") or 0),
            "height": int(out.get("height") or 0),
        }


    def s10_unit_binding_digest(request: Mapping[str, Any]) -> str:
        """Digest of EVERY input a unit's render consumes, plus its unit identity.

        Callers and the engine path compute this over the SAME request dict, so a
        cached/chunk artifact may only be reused when this digest still matches the
        one recorded with the artifact: a changed prompt, anchor, cast, graph, seed,
        control, span or output shape forces a re-render.
        """
        source = dict(request.get("source") or {})
        anchor = dict(request.get("anchor") or {})
        cast = [
            {
                "role": str(entry.get("role") or ""),
                "character_id": str(entry.get("character_id") or ""),
                "pack_version_id": str(entry.get("pack_version_id") or ""),
                "references": sorted(
                    [
                        {"key": str(r.get("key") or ""), "sha256": str(r.get("sha256") or "")}
                        for r in (entry.get("references") or [])
                    ],
                    key=lambda r: (r["key"], r["sha256"]),
                ),
            }
            for entry in sorted(
                (request.get("cast") or []),
                key=lambda e: (str(e.get("role") or ""), str(e.get("pack_version_id") or "")),
            )
        ]
        staged = {
            str(k): {
                "relative_path": str((v or {}).get("relative_path") or ""),
                "sha256": str((v or {}).get("sha256") or ""),
            }
            for k, v in sorted((request.get("staged_inputs") or {}).items())
        }
        body = {
            "unit_id": str((request.get("unit_id") or "")),
            "shot_id": str(request.get("shot_id") or ""),
            "chunk_id": str(request.get("chunk_id") or ""),
            "prompt_sha256": s10_unit_prompt_sha256(request),
            "source": {
                "sha256": str(source.get("sha256") or ""),
                "relative_path": str(source.get("relative_path") or ""),
            },
            "time_map": s10_unit_time_map(request),
            "anchor": {
                "relative_path": str(anchor.get("relative_path") or ""),
                "sha256": str(anchor.get("sha256") or ""),
            },
            "staged": staged,
            "cast": cast,
            "control": s10_unit_control(request),
            "binding_schema": UNIT_BINDING_SCHEMA,
        }
        return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── staged inputs + window staging ───────────────────────────────────────────


def _verify_staged_inputs(
    root: ManagedRoot, staged: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    verified: dict[str, dict[str, Any]] = {}
    for name, spec in (staged or {}).items():
        rel = str((spec or {}).get("relative_path") or "")
        want = str((spec or {}).get("sha256") or "")
        if not rel or not _HEX64.fullmatch(want):
            raise ShotRenderRefusal(
                ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,
                f"staged input {name!r} lacks a relative_path/sha256 pin",
            )
        try:
            target = root.resolve(rel)
        except Exception as exc:  # noqa: BLE001 — containment refusal is an invalid input
            raise ShotRenderRefusal(
                ShotRenderRefusalCode.SHOT_INPUT_INVALID,
                f"staged input {name!r} path {rel!r} escapes the managed root",
            ) from exc
        if not target.is_file():
            raise ShotRenderRefusal(
                ShotRenderRefusalCode.SHOT_INPUT_MISSING,
                f"staged input {name!r} is not on disk at {rel!r}",
            )
        actual = hash_file(target)
        if actual != want:
            raise ShotRenderRefusal(
                ShotRenderRefusalCode.SHOT_INPUT_DIGEST_MISMATCH,
                f"staged input {name!r} digest {actual[:16]}… != pinned {want[:16]}…",
                name=name,
            )
        verified[name] = {
            "relative_path": rel,
            "sha256": want,
            "size_bytes": target.stat().st_size,
            "basename": Path(rel).name,
        }
    return verified


def _stage_shot_source_window(
    root: ManagedRoot,
    *,
    chunk_id: str,
    source_abs: Path,
    span_start: int,
    span_end_exclusive: int,
    fps_num: int,
    fps_den: int,
) -> dict[str, Any]:
    """Stage the chunk's driving window under the engine stage inputs dir.

    A window covering the FULL decoded source is a byte copy (the source's
    audio/timebase survive verbatim); a sub-range window is a frame-accurate
    decode/re-encode of exactly ``[start, end)``.  The staged path is returned
    with its digest; the graph references it by basename.
    """
    from app.services.renderer_routes.composite import decode_rgb_frames, write_frames_mp4

    frames = decode_rgb_frames(source_abs)
    if not frames:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_INPUT_INVALID,
            f"source media {source_abs.name!r} decodes to zero frames",
        )
    if span_end_exclusive > len(frames) or span_start >= span_end_exclusive:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_INPUT_INVALID,
            f"window [{span_start},{span_end_exclusive}) exceeds the decoded source "
            f"({len(frames)} frames)",
        )
    safe_chunk = _SAFE.sub("_", chunk_id) or "chunk"
    basename = f"shotwin_{safe_chunk}_{span_start}_{span_end_exclusive}.mp4"
    rel = (
        Path("media_engine")
        / "comfy_shot_engine"
        / "stage"
        / "inputs"
        / safe_chunk
        / basename
    )
    staged_abs = root.resolve(rel)
    staged_abs.parent.mkdir(parents=True, exist_ok=True)
    full_span = span_start == 0 and span_end_exclusive == len(frames)
    if full_span:
        staged_abs.write_bytes(source_abs.read_bytes())
        mode = "byte_copy_full_span"
    else:
        fps = float(fps_num) / float(fps_den)
        write_frames_mp4(list(frames[span_start:span_end_exclusive]), staged_abs, fps=fps)
        mode = "frame_slice_reencode"
    if not staged_abs.is_file() or staged_abs.stat().st_size <= 0:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_INPUT_MISSING,
            f"staging the source window wrote no bytes at {rel.as_posix()}",
        )
    return {
        "basename": basename,
        "relative_path": rel.as_posix(),
        "sha256": hash_file(staged_abs),
        "size_bytes": staged_abs.stat().st_size,
        "mode": mode,
        "span": [span_start, span_end_exclusive],
    }


# ── binding composition ──────────────────────────────────────────────────────


def _artifact_ref_from(spec: Mapping[str, Any]) -> ArtifactRef:
    sha = str(spec.get("sha256") or "")
    if not _HEX64.fullmatch(sha):
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,
            f"cast reference for {spec.get('key')!r} lacks a sha256 pin",
        )
    return ArtifactRef(
        artifact_id=str(spec.get("artifact_id") or sha[:32]),
        kind=str(spec.get("kind") or "image"),  # type: ignore[arg-type]
        sha256=sha,
        store_relative_path=str(spec.get("store_relative_path") or f"inputs/{sha[:16]}.png"),
        size_bytes=spec.get("size_bytes"),
    )


def _build_binding(
    *,
    request: Mapping[str, Any],
    capability: str,
    attempt_id: str,
    primary: Mapping[str, Any],
    auxiliary: list[dict[str, Any]],
    graph_sha256: str,
    seed: int,
    fps_num: int,
    fps_den: int,
    anchor_ref: ArtifactRef,
) -> EngineInputBinding:
    source = dict(request["source"])
    span_raw = dict(source.get("span") or {})
    cast_raw = list(request.get("cast") or [])
    if not cast_raw:
        raise ShotRenderRefusal(
            ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,
            "cast is empty — the shot has no role binding",
        )
    cast: list[RoleCastBinding] = []
    for role_entry in cast_raw:
        refs_raw = list((role_entry or {}).get("references") or [])
        refs = tuple(
            ReferenceItem(key=str(r.get("key") or r.get("sha256") or "ref"),
                          artifact=_artifact_ref_from(r))
            for r in refs_raw
        )
        cast.append(
            RoleCastBinding(
                role=str(role_entry.get("role") or ""),
                character_id=str(role_entry.get("character_id") or role_entry.get("role") or ""),
                pack_version_id=str(role_entry.get("pack_version_id") or "unversioned"),
                references=refs,
                style_version=role_entry.get("style_version"),
            )
        )
    output_raw = dict(request.get("output_contract") or {})
    budget_raw = dict(request.get("budget") or {})
    timebase = TimebaseFacts(
        fps_num=fps_num,
        fps_den=fps_den,
        pts_start_ticks=int(span_raw.get("pts_start_ticks") or 0),
        pts_end_ticks=int(
            span_raw.get("pts_end_ticks")
            if span_raw.get("pts_end_ticks") is not None
            else max(int(output_raw.get("frame_count") or 1) - 1, 0)
        ),
        decoded_frame_count=int(output_raw.get("frame_count") or 0) or None,
    )
    source_window_sha = str(source.get("sha256") or "")
    return EngineInputBinding(
        capability=capability,
        identity=EngineRequestIdentity(
            workspace_id=str(request.get("workspace_id") or "default"),
            project_id=str(request["project_id"]),
            series_id=request.get("series_id"),
            video_id=str(request.get("video_id")),
            stage="shot_render",
            attempt_id=attempt_id,
            job_id=request.get("job_id"),
        ),
        source=EngineSourceLock(
            source_artifact_id=str(source.get("artifact_id") or source_window_sha[:32]),
            source_sha256=source_window_sha,
            span=SourceSpan(
                start_frame=int(span_raw.get("start_frame")),
                end_frame_exclusive=int(span_raw.get("end_frame_exclusive")),
            ),
            timebase=timebase,
            decoded_frame_count=timebase.decoded_frame_count,
        ),
        cast=tuple(cast),
        anchor=anchor_ref,
        source_window=ArtifactRef(
            artifact_id=str(source.get("artifact_id") or source_window_sha[:32]),
            kind="video",
            sha256=source_window_sha,
            store_relative_path=str(source.get("store_relative_path") or "inputs/source.mp4"),
            size_bytes=source.get("size_bytes"),
        ),
        graph=EngineWorkflowPin(
            workflow_id=str(request.get("workflow_id") or "shot_reskin_video"),
            workflow_version=str(request.get("workflow_version") or "v1"),
            workflow_hash=graph_sha256,
            model=EngineModelBinding(
                model_id=str(primary["model_id"]),
                revision=primary.get("revision"),
                file=ContentHash(scope="full_file", value=str(primary["file_sha256"])),
                precision=str(primary["precision"]),
                size_bytes=int(primary.get("size_bytes") or 0),
            ),
            nodes=(),
            config_hash=str(request.get("config_hash") or graph_sha256),
            seed=int(seed),
        ),
        auxiliary_models=tuple(
            EngineModelBinding(
                model_id=str(aux["model_id"]),
                revision=aux.get("revision"),
                file=ContentHash(scope="full_file", value=str(aux["file_sha256"])),
                precision=str(aux["precision"]),
                size_bytes=int(aux.get("size_bytes") or 0),
            )
            for aux in auxiliary
        ),
        output_contract=EngineOutputContract(
            width=int(output_raw.get("width") or 640),
            height=int(output_raw.get("height") or 368),
            fps_num=int(output_raw.get("fps_num") or fps_num),
            fps_den=int(output_raw.get("fps_den") or fps_den),
            frame_count=int(output_raw.get("frame_count") or 1),
            container=str(output_raw.get("container") or "mp4"),
            video_codec=str(output_raw.get("video_codec") or "h264"),
            audio=EngineAudioHandoff(
                mode=str((output_raw.get("audio") or {}).get("mode") or "source_remux"),
                source_artifact_id=str(
                    (output_raw.get("audio") or {}).get("source_artifact_id")
                    or source.get("artifact_id")
                    or source_window_sha[:32]
                ),
            ),
            stream_timebase_num=None,
            stream_timebase_den=None,
        ),
        budget=EngineResourceBudget(
            resource_class=str(budget_raw.get("resource_class") or "gpu_12gb"),
            max_wall_seconds=float(budget_raw.get("max_wall_seconds") or 900.0),
            max_vram_bytes=int(budget_raw.get("max_vram_bytes") or 0),
            max_output_bytes=int(budget_raw.get("max_output_bytes") or 536870912),
        ),
    )


# ── the engine door ──────────────────────────────────────────────────────────


def _engine_factory(**kwargs: Any) -> Any:
    """Default engine factory — the app's ONE Comfy door, constructed lazily."""
    from app.adapters.media_engine.comfy import ComfyShotEngine  # noqa: PLC0415

    return ComfyShotEngine(**kwargs)


#: Injection point: tests/drivers may replace this to supply an isolated transport.
ENGINE_FACTORY: Callable[..., Any] = _engine_factory


def shot_render_record_rel_path(shot_id: str, chunk_id: str) -> str:
    safe_shot = _SAFE.sub("_", str(shot_id)) or "shot"
    safe_chunk = _SAFE.sub("_", str(chunk_id)) or "chunk"
    return f"{SHOT_RENDER_SUBDIR}/{safe_shot}/{safe_chunk}.json"


def _write_record(
    root: ManagedRoot, shot_id: str, chunk_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    rel = shot_render_record_rel_path(shot_id, chunk_id)
    root.atomic_write_bytes(rel, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))
    target = root.resolve(rel)
    return {"relative_path": rel, "sha256": hash_file(target), "size_bytes": target.stat().st_size}


def _rejected_payload(
    *,
    request: Mapping[str, Any],
    reasons: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SHOT_RENDER_SCHEMA,
        "verdict": "rejected",
        "shot_id": request.get("shot_id"),
        "chunk_id": request.get("chunk_id"),
        "attempt_id": request.get("attempt_id"),
        "workspace_id": request.get("workspace_id"),
        "project_id": request.get("project_id"),
        "video_id": request.get("video_id"),
        "backend": dict(request.get("backend") or {}),
        "reasons": reasons,
        "receipt": None,
        "generated_at_unix": time.time(),
    }


def run_shot_render(
    *,
    managed_root: str | Path,
    request: Mapping[str, Any],
    engine: Any | None = None,
) -> dict[str, Any]:
    """Run ONE shot chunk through the pinned engine; fail closed end to end.

    Returns the accepted execution record (also written durably under the
    managed root).  On any refusal the durable ``verdict: rejected`` record is
    written first (so consumers see WHY the chunk is blocked) and a typed
    :class:`ShotRenderRefusal` is raised.  ``engine`` may be injected; the
    default is the real ``ComfyShotEngine``.
    """
    root = ManagedRoot(managed_root)
    shot_id = str(request.get("shot_id") or "")
    chunk_id = str(request.get("chunk_id") or "")

    def _refuse(
        code: ShotRenderRefusalCode, detail: str, **context: Any
    ) -> ShotRenderRefusal:
        refusal = ShotRenderRefusal(code, detail, **context)
        if shot_id and chunk_id:
            with contextlib.suppress(Exception):
                # Recording must never mask the refusal itself.
                _write_record(
                    root,
                    shot_id,
                    chunk_id,
                    _rejected_payload(request=request, reasons=[refusal.as_dict()]),
                )
        return refusal

    for key in ("project_id", "video_id"):
        if not request.get(key):
            raise _refuse(
                ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,
                f"shot render request is missing required field {key!r}",
            )
    if not shot_id or not chunk_id:
        raise _refuse(
            ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,
            "shot render request is missing shot_id/chunk_id",
        )
    backend = dict(request.get("backend") or {})
    if str(backend.get("backend") or "") != "comfy_shot_engine":
        raise _refuse(
            ShotRenderRefusalCode.SHOT_BACKEND_UNSUPPORTED,
            f"shot render executor only drives 'comfy_shot_engine'; got "
            f"{backend.get('backend')!r} (the legacy per-layer routes keep their "
            "own executor)",
        )

    # 1. profile: registered + eligible + the right kind, BEFORE any GPU work.
    profile = select_profile(str(backend.get("profile_id") or ""))
    primary, auxiliary = profile_models(profile)
    capability = str(backend.get("capability") or DEFAULT_CAPABILITY)

    # 2. graph file: pinned bytes, loaded through its declared parameters.
    graph_spec = dict(request.get("graph") or {})
    graph_rel = str(graph_spec.get("file") or profile.get("graph_file") or "")
    graph_root = Path(str(graph_spec.get("source_root") or _REPO_ROOT))
    graph_path = Path(graph_rel)
    if not graph_path.is_absolute():
        graph_path = graph_root / graph_path
    if not graph_path.is_file():
        raise _refuse(
            ShotRenderRefusalCode.SHOT_GRAPH_MISSING,
            f"frozen graph {graph_path} is missing",
        )
    graph_file_sha = hash_file(graph_path)
    pinned_graph_sha = str(graph_spec.get("file_sha256") or backend.get("graph_sha256") or "")
    if not _HEX64.fullmatch(pinned_graph_sha):
        raise _refuse(
            ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,
            "the frozen graph digest pin is missing (fail closed)",
        )
    if graph_file_sha != pinned_graph_sha:
        raise _refuse(
            ShotRenderRefusalCode.SHOT_GRAPH_PIN_MISMATCH,
            f"graph file digest {graph_file_sha[:16]}… != pinned {pinned_graph_sha[:16]}…",
        )
    graph_doc = json.loads(graph_path.read_text(encoding="utf-8"))
    if not isinstance(graph_doc, dict) or not isinstance(graph_doc.get("graph"), dict):
        raise _refuse(
            ShotRenderRefusalCode.SHOT_GRAPH_MISSING,
            f"frozen graph {graph_path} does not carry a graph object",
        )
    template_object_sha = _graph_object_sha256(graph_doc["graph"])

    # 3. staged inputs (anchors etc.) verified by digest under the managed root.
    staged = _verify_staged_inputs(root, dict(request.get("staged_inputs") or {}))

    # 4. the per-shot driving window is staged HERE (byte copy or frame slice).
    source_spec = dict(request.get("source") or {})
    span_raw = dict(source_spec.get("span") or {})
    if not source_spec.get("relative_path"):
        raise _refuse(
            ShotRenderRefusalCode.SHOT_INPUT_MISSING,
            "source window spec carries no relative_path pin",
        )
    source_abs = root.resolve(str(source_spec["relative_path"]))
    if not source_abs.is_file():
        raise _refuse(
            ShotRenderRefusalCode.SHOT_INPUT_MISSING,
            f"source media is not on disk at {source_spec['relative_path']!r}",
        )
    fps_raw = dict(source_spec.get("fps") or {})
    fps_num = int(fps_raw.get("num") or 30)
    fps_den = int(fps_raw.get("den") or 1)
    window = _stage_shot_source_window(
        root,
        chunk_id=chunk_id,
        source_abs=source_abs,
        span_start=int(span_raw.get("start_frame")),
        span_end_exclusive=int(span_raw.get("end_frame_exclusive")),
        fps_num=fps_num,
        fps_den=fps_den,
    )

    # 5. the shot's START ANCHOR is mandatory (the G2 gate): the frame is
    #    digest-pinned under the managed root.  When the frozen manifest
    #    declares it, the MF-END-15 accepted-anchor gate must ALSO stand.
    anchor_entry = dict(request.get("anchor") or {})
    anchor_gate_info: dict[str, Any] | None = None
    if bool(backend.get("require_accepted_anchor")):
        from app.workflow.shot_anchor_jobs import (  # noqa: PLC0415
            ShotAnchorRefusal,
            require_accepted_anchor,
        )

        try:
            anchor_gate_info = require_accepted_anchor(
                managed_root=managed_root,
                shot_id=shot_id,
                expected_identity_digest=request.get("anchor_identity_digest") or None,
            )
        except ShotAnchorRefusal as exc:
            raise _refuse(
                ShotRenderRefusalCode.SHOT_ANCHOR_GATE_REFUSED,
                f"the accepted-anchor gate blocked the video render: {exc}",
                anchor_code=str(getattr(exc, "code", "")),
            ) from exc
        gate_anchor = dict(anchor_gate_info.get("anchor") or {})
        anchor_entry = {
            "relative_path": gate_anchor.get("store_relative_path"),
            "sha256": gate_anchor.get("sha256"),
        }
    anchor_rel = str(anchor_entry.get("relative_path") or "")
    anchor_sha = str(anchor_entry.get("sha256") or "")
    anchor_abs = None
    with contextlib.suppress(Exception):
        anchor_abs = root.resolve(anchor_rel) if anchor_rel else None
    if (
        anchor_abs is None
        or not anchor_abs.is_file()
        or not _HEX64.fullmatch(anchor_sha)
        or hash_file(anchor_abs) != anchor_sha
    ):
        raise _refuse(
            ShotRenderRefusalCode.SHOT_INPUT_MISSING,
            f"shot anchor input {anchor_rel!r} is missing or its digest does not "
            f"match the pin {str(anchor_sha)[:16]}… (a start anchor is mandatory)",
        )
    anchor_ref = ArtifactRef(
        artifact_id=str(anchor_entry.get("artifact_id") or anchor_sha[:32]),
        kind="image",
        sha256=anchor_sha,
        store_relative_path=anchor_rel,
        size_bytes=anchor_abs.stat().st_size,
    )
    if anchor_gate_info is None:
        anchor_gate_info = {
            "verdict": "input_pinned_only",
            "anchor": {
                "store_relative_path": anchor_rel,
                "sha256": anchor_sha,
            },
        }

    # 6. patch the graph by its declared pointers; the values this executor OWNS
    #    (source window + anchor basename) are set from the staged bytes.
    parameters = dict(request.get("parameters") or {})
    parameters["source"] = window["basename"]
    if anchor_entry:
        parameters["anchor"] = Path(str(anchor_entry["relative_path"])).name
    patched_graph, patch_record = prepare_graph(graph_doc, parameters)
    submitted_sha = _graph_object_sha256(patched_graph)

    seed = int(backend.get("seed") if backend.get("seed") is not None else 0)
    output_spec = dict(request.get("output_contract") or {})
    frame_count = int(output_spec.get("frame_count") or 0)
    if frame_count < 1:
        raise _refuse(
            ShotRenderRefusalCode.SHOT_MANIFEST_INVALID,
            "output_contract.frame_count must be >= 1",
        )

    binding = _build_binding(
        request=request,
        capability=capability,
        attempt_id=str(request.get("attempt_id") or f"shot-{chunk_id}"),
        primary=primary,
        auxiliary=auxiliary,
        graph_sha256=submitted_sha,
        seed=seed,
        fps_num=fps_num,
        fps_den=fps_den,
        anchor_ref=anchor_ref,
    )

    output_node = str(backend.get("output_node") or "246")
    terminal = {output_node: {"kind": "video", "media_type": "video"}}

    owns_engine = engine is None
    engine_obj = engine
    if engine_obj is None:
        try:
            engine_obj = ENGINE_FACTORY(
                managed_root=str(managed_root),
                base_url=str(backend.get("engine_base_url") or "http://127.0.0.1:8188"),
            )
        except Exception as exc:  # noqa: BLE001 — the door itself refused to open
            raise _refuse(
                ShotRenderRefusalCode.SHOT_ENGINE_REFUSED,
                f"the Comfy shot engine is not available: {type(exc).__name__}:{exc}",
            ) from exc
    try:
        try:
            record = engine_obj.run_shot(
                binding,
                graph=patched_graph,
                terminal_outputs=terminal,
                shot_id=shot_id,
                decoded_facts=EngineDecodedFacts(
                    decoded_frames=frame_count,
                    first_pts_ticks=0,
                    timebase=f"{fps_num}/{fps_den}",
                    mapping=None,
                ),
            )
        except ShotRenderRefusal:
            raise
        except Exception as exc:  # noqa: BLE001 — engine boundary refusal
            code_value = getattr(exc, "code", None)
            code_value = code_value.value if hasattr(code_value, "value") else str(code_value)
            raise _refuse(
                ShotRenderRefusalCode.SHOT_ENGINE_REFUSED,
                f"the engine refused the shot attempt: {exc}",
                engine_code=code_value,
            ) from exc
    finally:
        if owns_engine and engine_obj is not None:
            with contextlib.suppress(Exception):
                engine_obj.close()

    if getattr(record, "outcome", None) != "completed" or getattr(record, "output", None) is None:
        error = getattr(record, "error", None)
        raise _refuse(
            ShotRenderRefusalCode.SHOT_ENGINE_FAILED,
            f"the shot attempt did not complete: "
            f"{getattr(error, 'message', None) or 'non-terminal outcome'}",
            engine_code=getattr(error, "code", None),
        )

    # 7. artifact harvest: the MAIN clip of the declared terminal node, re-hashed
    #    on disk, decoded and proven NOT to be the source bytes.
    engine_output = record.output
    artifacts = list(engine_output.artifacts)
    candidates = [a for a in artifacts if str(getattr(a, "kind", "")) == "video"]
    mains = [a for a in candidates if "_00001_" in Path(a.store_relative_path).name]
    main = mains[0] if len(mains) == 1 else (candidates[0] if len(candidates) == 1 else None)
    if main is None:
        raise _refuse(
            ShotRenderRefusalCode.SHOT_OUTPUT_MISSING,
            f"the completed record carries no unambiguous main video artifact "
            f"(videos: {[a.store_relative_path for a in candidates]})",
        )
    produced_path = root.resolve(main.store_relative_path)
    if not produced_path.is_file():
        raise _refuse(
            ShotRenderRefusalCode.SHOT_OUTPUT_MISSING,
            f"engine artifact {main.store_relative_path!r} is not on disk under the "
            "managed root",
        )
    produced_sha = hash_file(produced_path)
    if produced_sha != main.sha256:
        raise _refuse(
            ShotRenderRefusalCode.SHOT_OUTPUT_HASH_MISMATCH,
            f"engine artifact digest {produced_sha[:16]}… != the record's "
            f"{str(main.sha256)[:16]}…",
        )
    source_sha = str(source_spec.get("sha256") or "")
    if source_sha and produced_sha == source_sha:
        raise _refuse(
            ShotRenderRefusalCode.SHOT_SOURCE_RETURNED_AS_OUTPUT,
            "the produced artifact is byte-identical to the source window — the "
            "source is never returned as a successful render",
        )
    from app.services.renderer_routes.composite import (  # noqa: PLC0415
        canonical_frame_sha256,
        decode_rgb_frames,
        probe_source_timebase,
    )

    decoded = decode_rgb_frames(produced_path)
    if len(decoded) != frame_count:
        raise _refuse(
            ShotRenderRefusalCode.SHOT_OUTPUT_FRAME_MISMATCH,
            f"produced video decodes to {len(decoded)} frames; contract says {frame_count}",
        )
    probed = probe_source_timebase(produced_path)
    expected_tb = (
        int(output_spec.get("fps_num") or fps_num),
        int(output_spec.get("fps_den") or fps_den),
    )
    if tuple(probed) != expected_tb:
        raise _refuse(
            ShotRenderRefusalCode.SHOT_OUTPUT_TIMEBASE_MISMATCH,
            f"produced video timebase {probed} != contract "
            f"{(output_spec.get('fps_num') or fps_num, output_spec.get('fps_den') or fps_den)}",
        )
    decoded_sha = canonical_frame_sha256(decoded)

    receipt = {
        "prompt_id": str(engine_output.prompt_id),
        "graph_sha256_server": str(engine_output.graph_sha256_server),
        "server_side_wall_s": float(engine_output.server_side_wall_s),
        "vram_peak_mib": int(engine_output.vram_peak_mib),
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "kind": a.kind,
                "media_type": a.media_type,
                "sha256": a.sha256,
                "store_relative_path": a.store_relative_path,
                "size_bytes": a.size_bytes,
                "server_output_type": a.server_output_type,
            }
            for a in artifacts
        ],
    }
    payload = {
        "schema_version": SHOT_RENDER_SCHEMA,
        "verdict": "accepted",
        "shot_id": shot_id,
        "chunk_id": chunk_id,
        "attempt_id": str(request.get("attempt_id") or ""),
        "workspace_id": request.get("workspace_id"),
        "project_id": request.get("project_id"),
        "video_id": request.get("video_id"),
        "backend": backend,
        "capability": capability,
        "profile_id": str(profile.get("id")),
        "graph": {
            "file": graph_rel,
            "file_sha256": graph_file_sha,
            "object_sha256_template": template_object_sha,
            "object_sha256_submitted": submitted_sha,
            "parameter_pointers": patch_record["parameter_pointers"],
            "patched": patch_record["patched"],
        },
        "inputs": {
            "source": {
                "relative_path": str(source_spec.get("relative_path")),
                "sha256": source_sha,
                "span": [
                    int(span_raw.get("start_frame")),
                    int(span_raw.get("end_frame_exclusive")),
                ],
            },
            "window": window,
            "staged": staged,
            "anchor": anchor_gate_info,
            "cast": [
                {
                    "role": str(c.get("role") or ""),
                    "pack_version_id": str(c.get("pack_version_id") or ""),
                    "references": [
                        {"key": str(r.get("key") or ""), "sha256": str(r.get("sha256") or "")}
                        for r in (c.get("references") or [])
                    ],
                }
                for c in request.get("cast") or []
            ],
        },
        "receipt": receipt,
        "output": {
            "store_relative_path": str(main.store_relative_path),
            "filename": Path(main.store_relative_path).name,
            "sha256": produced_sha,
            "size_bytes": produced_path.stat().st_size,
            "decoded_frame_count": len(decoded),
            "decoded_sha256": decoded_sha,
            "fps_num": int(output_spec.get("fps_num") or fps_num),
            "fps_den": int(output_spec.get("fps_den") or fps_den),
            "is_source_copy": False,
        },
        "server_input_contract": {
            "note": (
                "the pinned Comfy instance's input directory must mirror the "
                "staged window file (byte-identical) before submit; see "
                "inputs.window.relative_path + inputs.staged"
            ),
            "required_server_inputs": {
                window["basename"]: window["sha256"],
                **{
                    entry["basename"]: entry["sha256"]
                    for entry in ([staged["anchor"]] if "anchor" in staged else [])
                },
            },
        },
        "generated_at_unix": time.time(),
    }
    record_meta = _write_record(root, shot_id, chunk_id, payload)
    return {
        "verdict": "accepted",
        "shot_id": shot_id,
        "chunk_id": chunk_id,
        "record": record_meta,
        "output_relative_path": str(main.store_relative_path),
        "output_sha256": produced_sha,
        "output_size_bytes": produced_path.stat().st_size,
        "decoded_frame_count": len(decoded),
        "decoded_sha256": decoded_sha,
        "fps_num": int(output_spec.get("fps_num") or fps_num),
        "fps_den": int(output_spec.get("fps_den") or fps_den),
        "prompt_id": str(engine_output.prompt_id),
        "server_side_wall_s": float(engine_output.server_side_wall_s),
        "vram_peak_mib": int(engine_output.vram_peak_mib),
        "graph_object_sha256_submitted": submitted_sha,
        "patched": patch_record["patched"],
        "window": window,
    }
