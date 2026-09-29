"""Durable shot-anchor job — resolve → gate → run → manifest → video gate (MF-END-15).

This module owns the *anchor job*: the durable, replayable unit of work that
turns one shot's resolved cast/product inputs into the TARGET full-scene anchor
(the G2 gate of the delivery plan) and records a manifest that binds, in one
place, the three artifact domains the product cares about:

* **source** — the locked source artifact digest + span;
* **cast** — every role's character / immutable pack version / reference
  artifact digests, resolved from the PUBLISHED pack authority;
* **anchor** — the engine-produced image artifact, its digest and the engine
  receipt (``prompt_id``, server-side wall time, VRAM peak, graph sha).

Micro-jobs implemented here:

* ``MF-END-15.1`` — :func:`resolve_anchor_references` resolves exact published
  pack/view artifacts and REFUSES source-mask-as-artwork by kind AND by image
  mode; unpublished drafts, digest mismatches and unresolvable views are typed
  refusals (codes ``anchor_reference_*``).
* ``MF-END-15.2`` — :func:`run_anchor_attempt` + :func:`shot_anchor_handler`
  run the pinned anchor graph through the app's ONE Comfy engine door
  (``app.adapters.media_engine.comfy.ComfyShotEngine``) and save the anchor
  artifact + manifest through :class:`ManagedRoot` atomic managed writes; the
  worker's fail-closed output validator is :func:`anchor_output_validator`.
  A rejected run writes a ``verdict: rejected`` manifest with the reasons
  (durable failure evidence) and raises a typed refusal.
* ``MF-END-15.3`` — :func:`shot_anchor_handler` calls the input-readiness gate
  (``app.services.shot_input_readiness``) BEFORE any engine work and fails
  closed; warnings can never turn a blocked gate into a run.
* ``MF-END-15.4`` — :func:`require_accepted_anchor` is the gate every video
  submit must pass: missing / rejected / STALE (input identity digest changed
  because an asset or input was replaced) / artifact-missing anchors are
  refused with a typed code, so a wrong anchor can never start video work.

Retry law: the job identity is DERIVED (``anchor_input_identity_digest``) —
same inputs ⇒ same idempotency key ⇒ :func:`submit_shot_anchor_job` converges
on the existing Job (active) or reuses the completed one; a retry NEVER
multiplies jobs.  A changed input ⇒ a new digest ⇒ exactly that one shot's
anchor is re-run and the old manifest reads STALE for every consumer.

No GPU work happens in this module: the engine's HTTP transport is the process
boundary and tests drive a scripted engine/record at exactly that boundary.
The module never invents artifact digests: every sha it records is re-hashed
from bytes on disk before it is written into a manifest.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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
    ShotPlan,
    ShotReskinRefusal,
    SourceSpan,
    TimebaseFacts,
    payload_sha256,
)
from app.services.shot_input_readiness import (
    ReferenceResolution,
    evaluate_shot_input_readiness,
    require_ready,
)

__all__ = [
    "ANCHOR_MANIFEST_SCHEMA",
    "ANCHOR_MANIFEST_SUBDIR",
    "DEFAULT_ANCHOR_CAPABILITY",
    "DEFAULT_ANCHOR_OUTPUT_NODE",
    "ENGINE_FACTORY",
    "JOB_TYPE_SHOT_ANCHOR_RUN",
    "AnchorReferenceEntry",
    "ShotAnchorRefusal",
    "ShotAnchorRefusalCode",
    "anchor_gate",
    "anchor_input_identity",
    "anchor_input_identity_digest",
    "anchor_manifest_rel_path",
    "anchor_output_validator",
    "register_shot_anchor_handler",
    "require_accepted_anchor",
    "resolve_anchor_references",
    "run_anchor_attempt",
    "shot_anchor_handler",
    "submit_shot_anchor_job",
]

#: Stable durable job type for one shot's anchor attempt.
JOB_TYPE_SHOT_ANCHOR_RUN = "shot_anchor_run"
#: Schema of the request the job manifest carries (``input_manifest["anchor_request"]``).
ANCHOR_JOB_SCHEMA = "mf.shot_anchor.job_request/1"
#: Schema of the durable anchor manifest written through the managed root.
ANCHOR_MANIFEST_SCHEMA = "mf.shot_anchor.job_manifest/1"
#: Managed-root subdirectory every anchor manifest/artifact of a shot lives under.
ANCHOR_MANIFEST_SUBDIR = "anchor"
#: The capability the anchor graph is executed under (the image edit stage).
DEFAULT_ANCHOR_CAPABILITY = "image_edit_multi_reference"
#: The graph's declared terminal SaveImage node id.
DEFAULT_ANCHOR_OUTPUT_NODE = "SAVE"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE = re.compile(r"[^0-9A-Za-z._-]")


class ShotAnchorRefusalCode(str, Enum):
    """Typed anchor-job refusals — one code per condition, never a generic error."""

    ANCHOR_INPUT_INVALID = "anchor_input_invalid"
    ANCHOR_REFERENCE_UNRESOLVED = "anchor_reference_unresolved"
    ANCHOR_REFERENCE_MASK_AS_ARTWORK = "anchor_reference_mask_as_artwork"
    ANCHOR_REFERENCE_NOT_PUBLISHED = "anchor_reference_not_published"
    ANCHOR_REFERENCE_HASH_MISMATCH = "anchor_reference_hash_mismatch"
    ANCHOR_CAST_REFERENCE_REQUIRED = "anchor_cast_reference_required"
    ANCHOR_READINESS_BLOCKED = "anchor_readiness_blocked"
    ANCHOR_ENGINE_REFUSED = "anchor_engine_refused"
    ANCHOR_ENGINE_FAILED = "anchor_engine_failed"
    ANCHOR_ARTIFACT_MISSING = "anchor_artifact_missing"
    ANCHOR_ARTIFACT_HASH_MISMATCH = "anchor_artifact_hash_mismatch"
    ANCHOR_MANIFEST_MISSING = "anchor_manifest_missing"
    ANCHOR_NOT_ACCEPTED = "anchor_not_accepted"
    ANCHOR_STALE_INPUT = "anchor_stale_input"
    ANCHOR_JOB_ACTIVE = "anchor_job_active"
    ANCHOR_REFERENCE_VIEW_DUPLICATED = "anchor_reference_view_duplicated"
    ANCHOR_REFERENCE_PLACEHOLDER = "anchor_reference_placeholder"
    ANCHOR_DECISION_STALE = "anchor_decision_stale"
    ANCHOR_DECISION_INVALID = "anchor_decision_invalid"


class ShotAnchorRefusal(Exception):  # noqa: N818 — mirrors the contract's refusal naming
    """Typed refusal raised by every anchor-job boundary."""

    def __init__(self, code: ShotAnchorRefusalCode, detail: str, **context: Any) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.context = context

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "detail": self.detail, "context": self.context}


@dataclass(frozen=True)
class AnchorReferenceEntry:
    """One resolved (or proposed) published reference for a role.

    ``kind`` / ``mode`` are what the resolver found when it looked at the
    artifact itself: ``kind="mask"`` or a single-channel ``mode`` means the
    artifact is a mask and can NEVER be a character design.
    """

    role: str
    view: str | None
    artifact_id: str
    sha256: str | None
    published: bool
    key: str = ""
    kind: str = "artwork"
    mode: str | None = None
    character_id: str = ""
    pack_version_id: str = ""
    store_relative_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "view": self.view,
            "key": self.key,
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "published": self.published,
            "kind": self.kind,
            "mode": self.mode,
        }


def _safe_component(value: str) -> str:
    return _SAFE.sub("_", value or "") or "unknown"


def anchor_manifest_rel_path(shot_id: str) -> str:
    """Managed-root-relative path of one shot's anchor manifest."""
    return f"{ANCHOR_MANIFEST_SUBDIR}/{_safe_component(shot_id)}/shot_anchor_manifest.json"


def anchor_artifact_rel_path(shot_id: str, filename: str = "anchor.png") -> str:
    """Managed-root-relative path of the published anchor copy of one shot."""
    return f"{ANCHOR_MANIFEST_SUBDIR}/{_safe_component(shot_id)}/{_safe_component(filename)}"


# ── 15.1: exact published pack/view resolution (mask-as-artwork refused) ──────


def resolve_anchor_references(
    entries: Sequence[AnchorReferenceEntry | Mapping[str, Any]],
    *,
    expected_sha256: Mapping[str, str] | None = None,
) -> tuple[AnchorReferenceEntry, ...]:
    """Validate the request's published reference set, fail closed.

    ``expected_sha256`` optionally maps ``"<role>@<key-or-view>"`` (or a bare
    key) to the digest the caller's plan declared; a resolution whose digest
    differs is refused (``anchor_reference_hash_mismatch``).
    """
    resolved: list[AnchorReferenceEntry] = []
    for raw in entries:
        entry = raw if isinstance(raw, AnchorReferenceEntry) else AnchorReferenceEntry(**dict(raw))
        if not entry.role.strip():
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED,
                "a reference entry carries no role",
                entry=entry.to_dict(),
            )
        if not entry.artifact_id.strip():
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED,
                f"role {entry.role!r} carries a reference with no artifact id",
                entry=entry.to_dict(),
            )
        if resolution_is_mask(entry):
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_REFERENCE_MASK_AS_ARTWORK,
                f"role {entry.role!r} reference {entry.artifact_id!r} is a MASK "
                f"(kind={entry.kind!r}, mode={entry.mode!r}); a mask is never a character "
                "design — refusing source-mask-as-artwork",
                role=entry.role,
                artifact_id=entry.artifact_id,
            )
        if not entry.published:
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_REFERENCE_NOT_PUBLISHED,
                f"role {entry.role!r} reference {entry.artifact_id!r} is not published; "
                "only published pack artifacts may carry reference pixels into the engine",
                role=entry.role,
                artifact_id=entry.artifact_id,
            )
        if not entry.sha256 or not _HEX64.match(entry.sha256):
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED,
                f"role {entry.role!r} reference {entry.artifact_id!r} carries no full-file "
                f"sha256 (got {entry.sha256!r})",
                role=entry.role,
                artifact_id=entry.artifact_id,
            )
        declared = None
        if expected_sha256:
            keys = (
                f"{entry.role}@{entry.key}",
                f"{entry.role}@{entry.view}",
                f"{entry.view}@{entry.role}",
                entry.key,
                entry.artifact_id,
            )
            for key in keys:
                if key and key in expected_sha256:
                    declared = expected_sha256[key]
                    break
        if declared is not None and declared != entry.sha256:
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_REFERENCE_HASH_MISMATCH,
                f"role {entry.role!r} reference {entry.artifact_id!r} resolved to "
                f"{entry.sha256[:16]}… but the plan declares {declared[:16]}…",
                role=entry.role,
                artifact_id=entry.artifact_id,
            )
        resolved.append(entry)
    return tuple(resolved)


def resolution_is_mask(entry: AnchorReferenceEntry) -> bool:
    """Kind/mode test shared with the readiness service."""
    from app.services.shot_input_readiness import is_mask_like_mode  # noqa: PLC0415

    return entry.kind == "mask" or is_mask_like_mode(entry.mode)


def _resolver_for(
    resolved: Sequence[AnchorReferenceEntry],
) -> Callable[[str, str | None], ReferenceResolution | None]:
    """Project the resolved entries onto the readiness gate's resolver signature."""

    def resolve(role: str, view: str | None) -> ReferenceResolution | None:
        for entry in resolved:
            if entry.role != role:
                continue
            if view is not None and entry.view != view:
                continue
            return ReferenceResolution(
                artifact_id=entry.artifact_id,
                sha256=entry.sha256,
                published=entry.published,
                kind=entry.kind,
                mode=entry.mode,
                store_relative_path=entry.store_relative_path,
            )
        return None

    return resolve


# ── request identity (the retry/invalidations law) ───────────────────────────


def anchor_input_identity(request: Mapping[str, Any]) -> dict[str, Any]:
    """The canonical input identity of one anchor run (what a retry must equal)."""
    cast = []
    for entry in request.get("cast_entries") or []:
        item = dict(entry)
        cast.append({
            "role": item.get("role"),
            "character_id": item.get("character_id"),
            "pack_version_id": item.get("pack_version_id"),
            "key": item.get("key"),
            "view": item.get("view"),
            "artifact_id": item.get("artifact_id"),
            "sha256": item.get("sha256"),
        })
    cast.sort(key=lambda c: (str(c["role"]), str(c["key"]), str(c["artifact_id"])))
    staged = request.get("staged_inputs") or {}
    staged_norm = {
        str(name): {"sha256": str((spec or {}).get("sha256") or "")}
        for name, spec in sorted(staged.items())
    }
    graph = request.get("graph") or {}
    source = request.get("source") or {}
    span = source.get("span") or {}
    return {
        "project_id": request.get("project_id"),
        "video_id": request.get("video_id"),
        "unit_id": request.get("unit_id"),
        "shot_id": request.get("shot_id"),
        "source_sha256": source.get("sha256"),
        "source_span": [span.get("start_frame"), span.get("end_frame_exclusive")],
        "graph_sha256": graph.get("sha256"),
        "graph_workflow_id": graph.get("workflow_id"),
        "seed": request.get("seed"),
        "cast": cast,
        "staged_inputs": staged_norm,
    }


def anchor_input_identity_digest(identity: Mapping[str, Any]) -> str:
    """Canonical digest of the input identity — the idempotency/staleness key."""
    return payload_sha256(dict(identity))


# ── binding composition ───────────────────────────────────────────────────────


def _view_or_none(value: Any) -> Any:
    if value in (None, "", "none"):
        return None
    allowed = ("front", "side", "back", "close_up", "three_quarter", "other")
    return value if value in allowed else "other"


def build_anchor_binding(
    request: Mapping[str, Any],
    resolved: Sequence[AnchorReferenceEntry],
    *,
    attempt_id: str,
) -> EngineInputBinding:
    """Compose the frozen engine input binding for one anchor attempt."""
    source = request["source"]
    span = source["span"]
    timebase = source["timebase"]
    graph = request["graph"]
    output = request.get("output_contract") or {}
    budget = request.get("budget") or {}
    capability = str(request.get("capability") or DEFAULT_ANCHOR_CAPABILITY)

    per_role: dict[str, list[AnchorReferenceEntry]] = {}
    for entry in resolved:
        per_role.setdefault(entry.role, []).append(entry)

    cast = tuple(
        RoleCastBinding(
            role=role,
            character_id=entries[0].character_id or role,
            pack_version_id=entries[0].pack_version_id or "unversioned",
            references=tuple(
                ReferenceItem(
                    key=entry.key or entry.view or entry.artifact_id,
                    artifact=ArtifactRef(
                        artifact_id=entry.artifact_id,
                        kind="image",
                        sha256=str(entry.sha256),
                        store_relative_path=entry.store_relative_path
                        or f"inputs/{_safe_component(entry.artifact_id)}.png",
                    ),
                    view=_view_or_none(entry.view),
                )
                for entry in entries
            ),
        )
        for role, entries in sorted(per_role.items())
    )

    model = graph["model"]
    try:
        return EngineInputBinding(
            capability=capability,
            identity=EngineRequestIdentity(
                workspace_id=str(request.get("workspace_id") or "default"),
                project_id=str(request["project_id"]),
                series_id=request.get("series_id"),
                video_id=str(request["video_id"]),
                stage="shot_anchor",
                attempt_id=attempt_id,
                job_id=request.get("job_id"),
            ),
            source=EngineSourceLock(
                source_artifact_id=str(source["artifact_id"]),
                source_sha256=str(source["sha256"]),
                span=SourceSpan(
                    start_frame=int(span["start_frame"]),
                    end_frame_exclusive=int(span["end_frame_exclusive"]),
                ),
                timebase=TimebaseFacts(**timebase),
                decoded_frame_count=timebase.get("decoded_frame_count"),
            ),
            cast=cast,
            anchor=None,
            source_window=ArtifactRef(
                artifact_id=str(source["artifact_id"]),
                kind="video",
                sha256=str(source["sha256"]),
                store_relative_path=str(source.get("store_relative_path") or "inputs/source.mp4"),
                size_bytes=source.get("size_bytes"),
            ),
            graph=EngineWorkflowPin(
                workflow_id=str(graph["workflow_id"]),
                workflow_version=str(graph.get("workflow_version") or "v1"),
                workflow_hash=str(graph["sha256"]),
                model=EngineModelBinding(
                    model_id=str(model["model_id"]),
                    revision=model.get("revision"),
                    file=ContentHash(scope="full_file", value=str(model["file_sha256"])),
                    precision=str(model.get("precision") or "fp8"),
                    size_bytes=int(model.get("size_bytes") or 0),
                ),
                nodes=(),
                config_hash=str(graph.get("config_hash") or graph["sha256"]),
                seed=int(request.get("seed") or 0),
            ),
            auxiliary_models=(),
            output_contract=EngineOutputContract(
                width=int(output.get("width") or 640),
                height=int(output.get("height") or 368),
                fps_num=int(output.get("fps_num") or 1),
                fps_den=int(output.get("fps_den") or 1),
                frame_count=int(output.get("frame_count") or 1),
                container=str(output.get("container") or "png"),
                video_codec=str(output.get("video_codec") or "png"),
                audio=EngineAudioHandoff(mode="silent"),
                stream_timebase_num=None,
                stream_timebase_den=None,
            ),
            budget=EngineResourceBudget(
                resource_class=str(budget.get("resource_class") or "gpu_12gb"),
                max_wall_seconds=float(budget.get("max_wall_seconds") or 900.0),
                max_vram_bytes=int(budget.get("max_vram_bytes") or 0),
                max_output_bytes=int(budget.get("max_output_bytes") or 536870912),
            ),
        )
    except ShotReskinRefusal as exc:
        code = getattr(exc, "code", None)
        code_value = code.value if hasattr(code, "value") else str(code)
        if code_value == "cast_reference_required":
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_CAST_REFERENCE_REQUIRED,
                f"the request's cast cannot carry capability {capability!r}: {exc}",
                refusal_code=code_value,
            ) from exc
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_INPUT_INVALID,
            f"the request cannot be composed into an engine binding: {exc}",
            refusal_code=code_value,
        ) from exc


# ── 15.2: the durable run (managed writes only) ───────────────────────────────


def _engine_factory(**kwargs: Any) -> Any:
    """Default engine factory — the app's ONE Comfy door, constructed lazily."""
    from app.adapters.media_engine.comfy import ComfyShotEngine  # noqa: PLC0415

    return ComfyShotEngine(**kwargs)


#: Injection point: tests/drivers may replace this to supply an isolated transport.
ENGINE_FACTORY: Callable[..., Any] = _engine_factory


def _write_manifest(root: ManagedRoot, shot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    rel = anchor_manifest_rel_path(shot_id)
    root.atomic_write_bytes(rel, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))
    target = root.resolve(rel)
    return {"relative_path": rel, "sha256": hash_file(target), "size_bytes": target.stat().st_size}


def _rejected_payload(
    *,
    request: Mapping[str, Any],
    identity: Mapping[str, Any],
    digest: str,
    reasons: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": ANCHOR_MANIFEST_SCHEMA,
        "job_id": request.get("job_id"),
        "attempt": request.get("attempt"),
        "workspace_id": request.get("workspace_id"),
        "project_id": request.get("project_id"),
        "video_id": request.get("video_id"),
        "unit_id": request.get("unit_id"),
        "shot_id": request.get("shot_id"),
        "verdict": "rejected",
        "reasons": [dict(reason) for reason in reasons],
        "input_identity": dict(identity),
        "input_identity_digest": digest,
        "source": dict(request.get("source") or {}),
        "cast": [dict(entry) for entry in request.get("cast_entries") or []],
        "graph": {
            "workflow_id": (request.get("graph") or {}).get("workflow_id"),
            "workflow_sha256": (request.get("graph") or {}).get("sha256"),
            "seed": request.get("seed"),
        },
        "anchor": None,
        "receipt": None,
        "generated_at_unix": time.time(),
    }


def run_anchor_attempt(
    *,
    managed_root: str | Path,
    request: Mapping[str, Any],
    engine: Any,
) -> dict[str, Any]:
    """Run one anchor attempt end to end against ``engine``; fail closed.

    Returns the accepted manifest record.  On any rejection a durable
    ``verdict: rejected`` manifest is written first (so consumers see WHY the
    shot is blocked) and a typed :class:`ShotAnchorRefusal` is raised.
    """
    root = ManagedRoot(managed_root)
    for key in ("project_id", "video_id", "shot_id", "source", "graph", "cast_entries"):
        if key not in request:
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_INPUT_INVALID,
                f"anchor request is missing required field {key!r}",
            )
    shot_id = str(request["shot_id"])
    identity = anchor_input_identity(request)
    digest = anchor_input_identity_digest(identity)
    attempt_id = str(request.get("attempt_id") or f"anchor-{digest[:12]}")

    resolved = resolve_anchor_references(
        list(request["cast_entries"]),
        expected_sha256=request.get("expected_reference_sha256") or None,
    )

    # 15.3 — the input gate runs BEFORE any engine work; blocked is terminal.
    plan = ShotPlan.model_validate(request["plan"])
    report = evaluate_shot_input_readiness(
        plan,
        required_views=request.get("required_views") or None,
        resolve_reference=_resolver_for(resolved),
    )
    try:
        require_ready(report)
    except Exception as exc:  # noqa: BLE001 - converted to the anchor's typed refusal
        reasons = [
            {
                "code": "readiness_blocked",
                "row": row,
                "detail": report.get("rows", {}).get(row, {}).get("detail"),
            }
            for row in report.get("blocking_rows") or []
        ]
        _write_manifest(
            root,
            shot_id,
            _rejected_payload(request=request, identity=identity, digest=digest, reasons=reasons),
        )
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_READINESS_BLOCKED,
            f"input readiness blocked the anchor run: {exc}",
            blocking_rows=list(report.get("blocking_rows") or []),
        ) from exc

    staged_problems: list[dict[str, Any]] = []
    for name, spec in (request.get("staged_inputs") or {}).items():
        rel = str((spec or {}).get("relative_path") or "")
        want = str((spec or {}).get("sha256") or "")
        try:
            target = root.resolve(rel)
        except Exception:  # noqa: BLE001 - containment refusal is a missing input
            staged_problems.append({"name": name, "problem": "path escapes the managed root"})
            continue
        if not target.is_file():
            staged_problems.append({"name": name, "problem": f"missing at {rel!r}"})
        elif not _HEX64.match(want) or hash_file(target) != want:
            staged_problems.append({"name": name, "problem": "digest mismatch"})
    if staged_problems:
        _write_manifest(
            root,
            shot_id,
            _rejected_payload(
                request=request, identity=identity, digest=digest,
                reasons=[{"code": "staged_input_invalid", **problem} for problem in
                         staged_problems],
            ),
        )
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_INPUT_INVALID,
            f"staged anchor inputs are not on disk with their declared digests: "
            f"{staged_problems}",
            problems=staged_problems,
        )

    graph_spec = request["graph"]
    graph_root = Path(str(graph_spec.get("source_root") or Path(__file__).resolve().parents[2]))
    graph_file = graph_root / str(graph_spec["file"])
    if not graph_file.is_file() or hash_file(graph_file) != str(graph_spec["sha256"]):
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_INPUT_INVALID,
            f"anchor graph {graph_file} is missing or its digest does not match "
            f"{graph_spec.get('sha256')}",
        )
    graph_obj = json.loads(graph_file.read_text(encoding="utf-8"))
    if isinstance(graph_obj, dict) and isinstance(graph_obj.get("graph"), dict):
        graph_obj = graph_obj["graph"]

    binding = build_anchor_binding(request, resolved, attempt_id=attempt_id)
    terminal = {
        str(request.get("output_node") or DEFAULT_ANCHOR_OUTPUT_NODE): {
            "kind": "image",
            "media_type": "image",
        }
    }
    try:
        record = engine.run_shot(
            binding,
            graph=graph_obj,
            terminal_outputs=terminal,
            shot_id=shot_id,
            decoded_facts=EngineDecodedFacts(
                decoded_frames=1, first_pts_ticks=0, timebase="1/1", mapping=None
            ),
        )
    except ShotAnchorRefusal:
        raise
    except Exception as exc:  # noqa: BLE001 - engine boundary refusal, typed below
        code = getattr(exc, "code", None)
        code_value = code.value if hasattr(code, "value") else str(code)
        reason = {"code": "engine_refused", "engine_code": code_value, "detail": str(exc)}
        _write_manifest(
            root, shot_id,
            _rejected_payload(request=request, identity=identity, digest=digest,
                              reasons=[reason]),
        )
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_ENGINE_REFUSED,
            f"the engine refused the anchor attempt: {exc}",
            engine_code=code_value,
        ) from exc

    if getattr(record, "outcome", None) != "completed" or getattr(record, "output", None) is None:
        error = getattr(record, "error", None)
        reason = {
            "code": "engine_failed",
            "engine_code": getattr(error, "code", None),
            "detail": getattr(error, "message", None) or "engine returned a non-terminal outcome",
        }
        _write_manifest(
            root, shot_id,
            _rejected_payload(request=request, identity=identity, digest=digest,
                              reasons=[reason]),
        )
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_ENGINE_FAILED,
            f"the anchor attempt did not complete: {reason['detail']}",
            engine_code=reason["engine_code"],
        )

    artifacts = list(record.output.artifacts)
    if not artifacts:
        _write_manifest(
            root, shot_id,
            _rejected_payload(request=request, identity=identity, digest=digest,
                              reasons=[{"code": "engine_failed", "detail": "no artifact"}]),
        )
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_ENGINE_FAILED,
            "the completed record carries no artifact",
        )
    produced = artifacts[0]
    produced_path = root.resolve(produced.store_relative_path)
    if not produced_path.is_file():
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_ARTIFACT_MISSING,
            f"engine artifact {produced.store_relative_path!r} is not on disk under the "
            "managed root",
        )
    produced_bytes = produced_path.read_bytes()
    produced_sha = hash_file(produced_path)
    if produced_sha != produced.sha256:
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_ARTIFACT_HASH_MISMATCH,
            f"engine artifact digest {produced_sha[:16]}… != the record's "
            f"{produced.sha256[:16]}…",
        )

    anchor_rel = str(request.get("anchor_rel_path")
                     or anchor_artifact_rel_path(shot_id))
    root.atomic_write_bytes(anchor_rel, produced_bytes, expected_sha256=produced_sha)
    anchor_target = root.resolve(anchor_rel)
    anchor_sha = hash_file(anchor_target)

    receipt = {
        "prompt_id": record.output.prompt_id,
        "graph_sha256_server": record.output.graph_sha256_server,
        "server_side_wall_s": record.output.server_side_wall_s,
        "vram_peak_mib": record.output.vram_peak_mib,
        "owner_session": record.output.owner_session,
    }
    manifest = {
        "schema_version": ANCHOR_MANIFEST_SCHEMA,
        "job_id": request.get("job_id"),
        "attempt": request.get("attempt"),
        "attempt_id": attempt_id,
        "workspace_id": request.get("workspace_id"),
        "project_id": request.get("project_id"),
        "series_id": request.get("series_id"),
        "video_id": request.get("video_id"),
        "unit_id": request.get("unit_id"),
        "shot_id": shot_id,
        "verdict": "accepted",
        "reasons": [],
        "input_identity": identity,
        "input_identity_digest": digest,
        "source": dict(request.get("source") or {}),
        "cast": [entry.to_dict() for entry in resolved],
        "graph": {
            "workflow_id": graph_spec.get("workflow_id"),
            "workflow_sha256": graph_spec.get("sha256"),
            "seed": request.get("seed"),
        },
        "anchor": {
            "artifact_id": f"artifact.shot_anchor.{_safe_component(shot_id)}",
            "store_relative_path": anchor_rel,
            "sha256": anchor_sha,
            "size_bytes": anchor_target.stat().st_size,
            "engine_store_relative_path": produced.store_relative_path,
            "engine_artifact_sha256": produced_sha,
        },
        "receipt": receipt,
        "readiness": {
            "schema_version": report.get("schema_version"),
            "verdict": report.get("verdict"),
            "report_sha256": report.get("report_sha256"),
            "rows": {
                row: (report.get("rows", {}).get(row) or {}).get("status")
                for row in report.get("row_order") or []
            },
        },
        "generated_at_unix": time.time(),
    }
    written = _write_manifest(root, shot_id, manifest)
    return {
        "verdict": "accepted",
        "shot_id": shot_id,
        "input_identity_digest": digest,
        "prompt_id": record.output.prompt_id,
        "anchor_manifest": written,
        "anchor": manifest["anchor"],
        "readiness": manifest["readiness"],
    }


# ── the durable handler + the worker's fail-closed validator ──────────────────


def shot_anchor_handler(ctx: Any) -> dict[str, Any]:
    """Durable worker handler for ``JOB_TYPE_SHOT_ANCHOR_RUN``."""
    manifest = ctx.input_manifest
    request = manifest.get("anchor_request")
    if not isinstance(request, dict):
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_INPUT_INVALID,
            "job input_manifest carries no 'anchor_request' object",
        )
    request = dict(request)
    request.setdefault("workspace_id", manifest.get("workspace_id"))
    request["job_id"] = request.get("job_id") or ctx.job_id
    request["attempt"] = ctx.attempt
    request["attempt_id"] = request.get("attempt_id") or _safe_component(
        f"{ctx.job_id}:{ctx.attempt}"
    )
    engine_cfg = dict(request.get("engine") or {})
    factory_kwargs: dict[str, Any] = {
        "managed_root": str(Path(str(manifest.get("managed_root") or ctx.staging_dir()))),
        "base_url": str(engine_cfg.get("base_url") or "http://127.0.0.1:8188"),
    }
    if engine_cfg.get("stage_timeout_s") is not None:
        factory_kwargs["stage_timeout_s"] = float(engine_cfg["stage_timeout_s"])
    if engine_cfg.get("poll_s") is not None:
        factory_kwargs["poll_s"] = float(engine_cfg["poll_s"])
    ctx.progress(5, "resolving published pack/view artifacts")
    engine = ENGINE_FACTORY(**factory_kwargs)
    try:
        result = run_anchor_attempt(
            managed_root=factory_kwargs["managed_root"], request=request, engine=engine
        )
    finally:
        close = getattr(engine, "close", None)
        if callable(close):
            with contextlib.suppress(Exception):  # close is best-effort
                close()
    ctx.progress(100, "anchor accepted and manifest published")
    return result


def anchor_output_validator(ctx: Any, result: dict[str, Any], staging_dir: Path) -> dict[str, Any]:
    """Fail-closed completion gate: the accepted manifest must exist with its digest."""
    spec = result.get("anchor_manifest")
    if not isinstance(spec, dict) or not spec.get("relative_path"):
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_MANIFEST_MISSING,
            "handler result carries no anchor manifest reference",
        )
    root = ManagedRoot(Path(str(ctx.input_manifest["managed_root"])))
    target = root.resolve(str(spec["relative_path"]))
    if not target.is_file():
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_MANIFEST_MISSING,
            f"anchor manifest is missing at {spec['relative_path']!r}",
        )
    sha = hash_file(target)
    size = target.stat().st_size
    if spec.get("sha256") and sha != spec["sha256"]:
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_ARTIFACT_HASH_MISMATCH,
            f"anchor manifest digest {sha[:16]}… != the recorded {str(spec['sha256'])[:16]}…",
        )
    if spec.get("size_bytes") is not None and size != int(spec["size_bytes"]):
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_ARTIFACT_HASH_MISMATCH,
            "anchor manifest size does not match the recorded size",
        )
    return {
        "anchor_manifest": {"relative_path": str(spec["relative_path"]), "sha256": sha,
                            "size_bytes": size},
        "verdict": result.get("verdict"),
        "input_identity_digest": result.get("input_identity_digest"),
    }


def register_shot_anchor_handler(worker: Any) -> None:
    """Register the anchor handler (with its fail-closed validator) on a worker."""
    worker.register_handler(
        JOB_TYPE_SHOT_ANCHOR_RUN,
        shot_anchor_handler,
        output_validator=anchor_output_validator,
    )


# ── idempotent submit (retry never multiplies jobs) ──────────────────────────


def submit_shot_anchor_job(
    job_service: Any,
    *,
    request: Mapping[str, Any],
    workspace_id: str | None = None,
    generation: int | None = None,
) -> Any:
    """Submit (or converge on) the ONE durable anchor job for this input identity.

    The idempotency key is derived from :func:`anchor_input_identity_digest`, so
    re-submitting identical inputs while the job is active converges on the
    existing Job (``IdempotencyKeyInUse.job_id``) and a completed job is reused
    by the repository — a retry never inserts a second row.
    """
    from app.persistence.jobs import IdempotencyKeyInUse  # noqa: PLC0415

    identity = anchor_input_identity(request)
    digest = anchor_input_identity_digest(identity)
    shot_id = str(request["shot_id"])
    project_id = str(request["project_id"])
    #: A RETRY keeps the same input identity (so a completed run is never
    #: duplicated) and only bumps the generation, which is what makes exactly
    #: ONE successor job for the SAME inputs.
    suffix = f":g{int(generation)}" if generation else ""
    key = f"shot-anchor:{project_id}:{shot_id}:{digest}{suffix}"
    manifest = {
        "anchor_request": dict(request),
        "project_id": project_id,
        "video_id": str(request["video_id"]),
        "shot_id": shot_id,
        "unit_id": str(request.get("unit_id") or ""),
        "input_identity_digest": digest,
    }
    try:
        return job_service.create_job(
            JOB_TYPE_SHOT_ANCHOR_RUN,
            manifest,
            workspace_id=workspace_id or str(request.get("workspace_id") or "default"),
            owner_type="project",
            owner_id=str(request.get("owner_id") or project_id),
            idempotency_key=key,
            input_generation=digest,
        )
    except IdempotencyKeyInUse as exc:
        existing_id = getattr(exc, "job_id", None)
        if existing_id:
            existing = job_service.get_job(str(existing_id))
            if existing is not None:
                return existing
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_INPUT_INVALID,
            f"an anchor job for this input identity already exists but could not be "
            f"resolved: {exc}",
        ) from exc


# ── 15.4: the video-submit gate (rejected/stale anchor blocks video) ─────────


def anchor_gate(
    *,
    managed_root: str | Path,
    shot_id: str,
    expected_identity_digest: str | None = None,
) -> dict[str, Any]:
    """Read one shot's anchor manifest; refuse unless an ACCEPTED anchor stands.

    Codes: ``anchor_manifest_missing`` (no anchor was ever produced),
    ``anchor_not_accepted`` (the run was rejected — reasons included),
    ``anchor_stale_input`` (an asset/input changed since the anchor was
    produced, so the anchor is invalid for the CURRENT input identity),
    ``anchor_artifact_missing`` (the anchor bytes are gone or were replaced).
    """
    root = ManagedRoot(managed_root)
    rel = anchor_manifest_rel_path(shot_id)
    target = root.resolve(rel)
    if not target.is_file():
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_MANIFEST_MISSING,
            f"shot {shot_id!r} has no anchor manifest at {rel!r}: video work cannot start",
            shot_id=shot_id,
        )
    doc = json.loads(target.read_text(encoding="utf-8"))
    if doc.get("schema_version") != ANCHOR_MANIFEST_SCHEMA:
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_MANIFEST_MISSING,
            f"shot {shot_id!r} anchor manifest schema {doc.get('schema_version')!r} is not "
            f"{ANCHOR_MANIFEST_SCHEMA!r}",
            shot_id=shot_id,
        )
    if doc.get("verdict") != "accepted":
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_NOT_ACCEPTED,
            f"shot {shot_id!r} anchor was REJECTED: "
            f"{[reason.get('code') for reason in doc.get('reasons') or []]}",
            shot_id=shot_id,
            reasons=list(doc.get("reasons") or []),
        )
    if expected_identity_digest is not None and (
        doc.get("input_identity_digest") != expected_identity_digest
    ):
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_STALE_INPUT,
            f"shot {shot_id!r} anchor is STALE: its input identity digest "
            f"{str(doc.get('input_identity_digest'))[:16]}… != the current "
            f"{expected_identity_digest[:16]}… (an asset/input changed — re-run the anchor "
            "before video)",
            shot_id=shot_id,
        )
    manifest_sha = hash_file(target)
    decision = read_anchor_decision(root, shot_id)
    if decision is not None:
        if decision.get("manifest_sha256") != manifest_sha:
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_DECISION_STALE,
                f"shot {shot_id!r} carries a review decision bound to manifest "
                f"{str(decision.get('manifest_sha256'))[:16]}… but the current anchor manifest "
                f"is {manifest_sha[:16]}… — the decision does not cover this anchor",
                shot_id=shot_id,
            )
        if decision.get("decision") == "rejected":
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_NOT_ACCEPTED,
                f"shot {shot_id!r} anchor was REJECTED by the reviewer: "
                f"{decision.get('reason')!r}; video work stays blocked until a new anchor is "
                "produced and accepted",
                shot_id=shot_id,
                decision=dict(decision),
            )
    anchor = doc.get("anchor") or {}
    anchor_rel = str(anchor.get("store_relative_path") or "")
    artifact = root.resolve(anchor_rel)
    if not anchor_rel or not artifact.is_file() or hash_file(artifact) != anchor.get("sha256"):
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_ARTIFACT_MISSING,
            f"shot {shot_id!r} anchor artifact {anchor_rel!r} is missing or its bytes do "
            "not match the manifest digest",
            shot_id=shot_id,
        )
    return {
        "shot_id": shot_id,
        "manifest_relative_path": rel,
        "manifest_sha256": hash_file(target),
        "input_identity_digest": doc.get("input_identity_digest"),
        "anchor": dict(anchor),
        "receipt": dict(doc.get("receipt") or {}),
        "verdict": "accepted",
    }


def require_accepted_anchor(**kwargs: Any) -> dict[str, Any]:
    """The named gate every video submit calls (see :func:`anchor_gate`)."""
    return anchor_gate(**kwargs)


# ── C15: preview / accept / reject surface (bound to CURRENT hashes) ─────────

#: Schema of the durable review decision (accept/reject) of one shot's anchor.
ANCHOR_DECISION_SCHEMA = "mf.shot_anchor.decision/1"


def anchor_decision_rel_path(shot_id: str) -> str:
    """Managed-root-relative path of one shot's anchor review decision."""
    return f"{ANCHOR_MANIFEST_SUBDIR}/{_safe_component(shot_id)}/shot_anchor_decision.json"


def _as_managed_root(value: Any) -> ManagedRoot:
    """Accept either a managed root path or an already-built ``ManagedRoot``."""
    return value if isinstance(value, ManagedRoot) else ManagedRoot(value)


def read_anchor_decision(managed_root: str | Path, shot_id: str) -> dict[str, Any] | None:
    """Read the recorded review decision of one shot, or ``None`` when there is one."""
    root = _as_managed_root(managed_root)
    target = root.resolve(anchor_decision_rel_path(shot_id))
    if not target.is_file():
        return None
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def record_anchor_decision(
    managed_root: str | Path,
    shot_id: str,
    decision: str,
    *,
    expected_manifest_sha256: str | None = None,
    reason: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Record ``accepted`` / ``rejected`` for the anchor a caller just previewed.

    Fail-closed binding: the decision quotes the manifest hash it was taken
    against, so a stale quote refuses instead of approving a different anchor.
    A rejected RUN verdict can never be accepted by a decision, and a rejection
    must carry a reason (the reviewer's finding is evidence, not a flag).
    """
    if decision not in ("accepted", "rejected"):
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_DECISION_INVALID,
            f"decision must be 'accepted' or 'rejected'; got {decision!r}",
        )
    if decision == "rejected" and not (reason or "").strip():
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_DECISION_INVALID,
            "a rejection must carry a reason",
        )
    root = ManagedRoot(managed_root)
    manifest_target = root.resolve(anchor_manifest_rel_path(shot_id))
    if not manifest_target.is_file():
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_MANIFEST_MISSING,
            f"shot {shot_id!r} has no anchor manifest to decide on",
            shot_id=shot_id,
        )
    manifest_sha = hash_file(manifest_target)
    if not expected_manifest_sha256 or expected_manifest_sha256 != manifest_sha:
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_DECISION_STALE,
            f"the decision quotes manifest {str(expected_manifest_sha256)[:16]}… but the current "
            f"anchor manifest is {manifest_sha[:16]}…; preview again before deciding",
            shot_id=shot_id,
            current_manifest_sha256=manifest_sha,
        )
    doc = json.loads(manifest_target.read_text(encoding="utf-8"))
    if decision == "accepted" and doc.get("verdict") != "accepted":
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_NOT_ACCEPTED,
            f"shot {shot_id!r} anchor run verdict is {doc.get('verdict')!r}; a rejected run "
            "cannot be accepted by a decision",
            shot_id=shot_id,
            reasons=list(doc.get("reasons") or []),
        )
    decision_doc: dict[str, Any] = {
        "schema_version": ANCHOR_DECISION_SCHEMA,
        "shot_id": shot_id,
        "decision": decision,
        "reason": (reason or "").strip() or None,
        "note": note,
        "manifest_sha256": manifest_sha,
        "anchor_sha256": (doc.get("anchor") or {}).get("sha256"),
        "input_identity_digest": doc.get("input_identity_digest"),
        "decided_at_unix": time.time(),
    }
    rel = anchor_decision_rel_path(shot_id)
    root.atomic_write_bytes(
        rel, json.dumps(decision_doc, indent=2, sort_keys=True).encode("utf-8")
    )
    decision_doc["decision_path"] = rel
    decision_doc["decision_file_sha256"] = hash_file(root.resolve(rel))
    return decision_doc


def anchor_status(
    managed_root: str | Path,
    shot_id: str,
    *,
    expected_identity_digest: str | None = None,
) -> dict[str, Any]:
    """PREVIEW one shot's anchor: verdict, CURRENT hashes, staleness, decision.

    Read-only and non-raising for a missing anchor (the preview must be able to
    say "nothing yet"); ``video_allowed`` is computed from the SAME rules the
    gate enforces, so the preview cannot claim more than the gate will honour.
    """
    root = ManagedRoot(managed_root)
    rel = anchor_manifest_rel_path(shot_id)
    target = root.resolve(rel)
    body: dict[str, Any] = {
        "shot_id": shot_id,
        "manifest_path": rel,
        "manifest_present": target.is_file(),
        "expected_identity_digest": expected_identity_digest,
        "verdict": "missing",
        "stale": None,
        "video_allowed": False,
        "decision": read_anchor_decision(root, shot_id),
    }
    if not target.is_file():
        return body
    doc = json.loads(target.read_text(encoding="utf-8"))
    body["manifest_sha256"] = hash_file(target)
    body["verdict"] = doc.get("verdict")
    body["reasons"] = list(doc.get("reasons") or [])
    body["anchor"] = dict(doc.get("anchor") or {})
    body["receipt"] = dict(doc.get("receipt") or {})
    body["input_identity_digest"] = doc.get("input_identity_digest")
    body["readiness"] = dict(doc.get("readiness") or {})
    stale = (
        None if expected_identity_digest is None
        else doc.get("input_identity_digest") != expected_identity_digest
    )
    body["stale"] = stale
    anchor = body["anchor"]
    anchor_rel = str(anchor.get("store_relative_path") or "")
    intact = False
    if anchor_rel:
        anchor_file = root.resolve(anchor_rel)
        intact = bool(
            anchor_file.is_file() and hash_file(anchor_file) == anchor.get("sha256")
        )
    body["anchor_artifact_intact"] = intact
    decision = body["decision"]
    body["video_allowed"] = bool(
        doc.get("verdict") == "accepted"
        and intact
        and stale is not True
        and (decision or {}).get("decision") != "rejected"
    )
    return body


def plan_from_payload(payload: Mapping[str, Any]) -> ShotPlan:
    """Validate a shot-plan payload into the FROZEN ``ShotPlan`` contract."""
    try:
        return ShotPlan.model_validate(dict(payload))
    except Exception as exc:  # noqa: BLE001 — a malformed plan is a typed refusal
        raise ShotAnchorRefusal(
            ShotAnchorRefusalCode.ANCHOR_INPUT_INVALID,
            f"the shot plan is not a valid {ShotPlan.__name__}: {exc}",
        ) from exc


def reference_resolver(
    entries: Sequence[AnchorReferenceEntry],
) -> Callable[[str, str | None], Any]:
    """The readiness gate's resolver over already-resolved cast entries."""
    return _resolver_for(entries)


def resolve_published_cast_references(
    session: Any,
    *,
    workspace_id: str,
    requirements: Sequence[Mapping[str, Any]],
    managed_root: str | Path | None = None,
) -> tuple[AnchorReferenceEntry, ...]:
    """Resolve each role's references from the PUBLISHED cast authority.

    The client never names an artifact: every entry comes from the workspace's
    own ``CharacterRepository`` pack versions.  Refused, typed:

    * the pack version is missing/foreign or NOT ``published``
      (``anchor_reference_not_published``);
    * a required view has no asset on that pose slot, or its artifact is not
      ``ready`` / carries no full-file sha (``anchor_reference_unresolved``);
    * the artifact is a declared placeholder (``anchor_reference_placeholder``);
    * ONE artifact sha stands in for two poses of the same role
      (``anchor_reference_view_duplicated`` — "một ảnh cho nhiều pose").

    When ``managed_root`` is supplied the managed file is measured, so a
    single-channel (mask) image mode is caught by ``resolve_anchor_references``
    as source-mask-as-artwork.
    """
    from app.persistence.characters import CharacterRepository  # noqa: PLC0415
    from app.services.shot_input_readiness import probe_image_mode  # noqa: PLC0415
    repository = CharacterRepository(
        session, Path(str(managed_root)) if managed_root is not None else None
    )
    entries: list[AnchorReferenceEntry] = []
    for requirement in requirements:
        role = str(requirement.get("role") or "")
        character_id = str(requirement.get("character_id") or "")
        version_id = str(requirement.get("pack_version_id") or "")
        views = [str(view) for view in (requirement.get("views") or [])]
        placeholders = {
            str(item) for item in (requirement.get("placeholder_artifact_ids") or [])
        }
        if not role or not character_id or not version_id or not views:
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED,
                f"cast requirement {requirement!r} must carry role, character_id, "
                "pack_version_id and at least one view",
            )
        try:
            version = repository.get_pack_version_for_character(
                character_id, version_id, workspace_id
            )
        except Exception as exc:  # noqa: BLE001 — unknown/foreign version is a refusal
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED,
                f"role {role!r}: pack version {version_id!r} could not be read "
                f"({type(exc).__name__}: {exc})",
                role=role,
                character_id=character_id,
            ) from exc
        if version.status != "published":
            raise ShotAnchorRefusal(
                ShotAnchorRefusalCode.ANCHOR_REFERENCE_NOT_PUBLISHED,
                f"role {role!r}: pack version {version_id!r} is {version.status!r}; only a "
                "PUBLISHED pack may carry reference pixels into the engine",
                role=role,
                status=version.status,
            )
        by_slot = {asset.pose_slot: asset for asset in version.assets}
        seen: dict[str, str] = {}
        for view in views:
            asset = by_slot.get(view)
            if asset is None:
                raise ShotAnchorRefusal(
                    ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED,
                    f"role {role!r}: pack version {version_id!r} has no asset on pose slot "
                    f"{view!r} (available: {sorted(by_slot)})",
                    role=role,
                    view=view,
                )
            if asset.artifact_id in placeholders:
                raise ShotAnchorRefusal(
                    ShotAnchorRefusalCode.ANCHOR_REFERENCE_PLACEHOLDER,
                    f"role {role!r} view {view!r}: artifact {asset.artifact_id!r} is a declared "
                    "placeholder, not finished artwork",
                    role=role,
                    view=view,
                )
            if asset.artifact_state != "ready" or not asset.artifact_sha256:
                raise ShotAnchorRefusal(
                    ShotAnchorRefusalCode.ANCHOR_REFERENCE_UNRESOLVED,
                    f"role {role!r} view {view!r}: artifact {asset.artifact_id!r} is "
                    f"{asset.artifact_state!r} without a verified digest",
                    role=role,
                    view=view,
                )
            previous = seen.get(str(asset.artifact_sha256))
            if previous is not None and previous != view:
                raise ShotAnchorRefusal(
                    ShotAnchorRefusalCode.ANCHOR_REFERENCE_VIEW_DUPLICATED,
                    f"role {role!r}: views {previous!r} and {view!r} resolve to the SAME artifact "
                    f"sha {str(asset.artifact_sha256)[:16]}… — one image may not stand in for two "
                    "poses",
                    role=role,
                    views=[previous, view],
                )
            seen[str(asset.artifact_sha256)] = view
            store_rel = asset.artifact_relative_path
            mode = None
            if managed_root is not None and store_rel:
                try:
                    managed_file = ManagedRoot(managed_root).resolve(store_rel)
                    mode = probe_image_mode(managed_file) if managed_file.is_file() else None
                except Exception:  # noqa: BLE001 — an unreadable path is "no mode measured"
                    mode = None
            entries.append(
                AnchorReferenceEntry(
                    role=role,
                    view=view,
                    artifact_id=asset.artifact_id,
                    sha256=asset.artifact_sha256,
                    published=True,
                    key=f"{view}@{role}",
                    kind="artwork",
                    mode=mode,
                    character_id=character_id,
                    pack_version_id=version_id,
                    store_relative_path=store_rel,
                )
            )
    if not entries:
        return ()
    return resolve_anchor_references(entries)
