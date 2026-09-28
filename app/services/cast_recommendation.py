"""MF-END-06 — library cast-set recommendation ("đề xuất bộ từ kho với lý do").

Read-only service: proposes REAL library packs (published
``CharacterPackVersion`` rows) for the roles of one target video, with
deterministic compatibility reasons, missing views, a bounded advisory call,
and the series-pin priority of MF-END-05.  It NEVER mutates anything: no
mapping, no pin, no artifact, no character, no snapshot, no job
(``mutations == 0`` on the result).

Pipeline (the packet's micro-jobs):

1. ``MF-END-06.1`` deterministic hard filter.  A pack becomes a candidate
   only when it is published, complete on its contract branch — legacy
   ``CORE_POSE_SLOTS`` demand or the frozen reference requirement manifest,
   the SAME authorities the pin path uses (``_reference_branch_missing_keys``,
   ``parse_reference_manifest``) — and kind-compatible with the role
   (``project_cast._kind_compatible``, imported, single source).  View
   coverage and style are deterministic METADATA of a candidate
   (``missing_views`` / ``style_match``): a pack one view short is still
   reported (with the missing views) because the documented remedy is
   generating exactly those views, not hiding the pack.
2. ``MF-END-06.2`` metadata-first ranking (series pin first, then view
   coverage, then style, then newer pack version).  The pinned advisory route
   is called ONLY when a role has no series pin and its top metadata rank is
   shared by ≥2 candidates, and the advisory may choose only WITHIN that tie
   set — it can never add, remove, or re-order outside the deterministic
   filter, and a choice outside the tie set is recorded and IGNORED.
3. ``MF-END-06.3`` the result carries only REAL ids resolved from rows
   (pack versions, characters, snapshot) plus reasons and missing views;
   hard-filtered packs are listed separately with their real ids so the
   refusal is auditable.
4. ``MF-END-06.4`` a series snapshot entry matched by ``role_key`` has
   ABSOLUTE priority (source ``series_snapshot``, rank 0, selected, advisory
   not called); if the advisory route is unavailable the deterministic
   selection stays fully usable (manual choice) and the error text is
   surfaced verbatim on the result.

Advisory payload discipline: text metadata + at most ``MAX_SOURCE_FRAMES``
caller-provided IMAGE artifacts + one artwork per tied candidate (each byte
cap enforced; digests verified against the artifact row).  A video artifact
is a typed refusal and the built payload is audited (``video_parts == 0``) —
the whole video is never sent to any LLM.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.persistence.artifacts import ManagedPathError, ManagedRoot, hash_file
from app.persistence.models import (
    CORE_POSE_SLOTS,
    PACK_CONTRACT_VERSION_REFERENCE,
    SOURCE_OVERLAY_KIND,
    Artifact,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    ObjectRole,
    Project,
    VideoItem,
)
from app.persistence.project_cast import (
    SeriesCastRepository,
    SeriesCastSnapshotRecord,
    _kind_compatible,
    _reference_branch_missing_keys,
)
from app.schemas.cast_recommendation import (
    GENERATION_PLAN_NOTE_FULL,
    GENERATION_PLAN_NOTE_MISSING,
    GENERATION_PLAN_NOTE_NONE,
    GENERATION_PLAN_NOTE_STALE_PIN,
    AdvisoryNoteData,
    AdvisoryReportData,
    AdvisoryRoutePinData,
    CandidateReasonData,
    CastCandidateData,
    CastRecommendationRequest,
    CastRecommendationResult,
    CastRoleRequirement,
    FilteredPackData,
    GenerationPlanData,
    RoleAdvisoryData,
    RoleRecommendationData,
    SeriesContextData,
    SeriesPinData,
    SourceFrameInput,
)
from app.workflow.character_validator import (
    PackContractBranch,
    parse_reference_manifest,
)

__all__ = [
    "ADVISORY_ROUTE_PIN",
    "ADVISORY_SYSTEM_PROMPT",
    "ESTIMATED_COST_UNITS_PER_VIEW",
    "GENERATION_COST_UNIT",
    "MAX_ADVISORY_CANDIDATES",
    "MAX_ADVISORY_IMAGES_PER_CANDIDATE",
    "MAX_ADVISORY_IMAGE_BYTES",
    "MAX_ADVISORY_PAYLOAD_BYTES",
    "AdvisoryClient",
    "AdvisoryRoutePin",
    "AdvisoryUnavailableError",
    "CastRecommendationError",
    "CastRecommendationInputError",
    "CastRecommendationNotFoundError",
    "PinnedRouteAdvisoryClient",
    "derive_role_requirements",
    "recommend_cast",
]

#: Maximum tied candidates included in one advisory call.
MAX_ADVISORY_CANDIDATES = 4

#: Artwork images per candidate in one advisory call (a front view).
MAX_ADVISORY_IMAGES_PER_CANDIDATE = 1

#: Hard byte ceiling for one advisory image (frame or candidate artwork).
MAX_ADVISORY_IMAGE_BYTES = 1_000_000

#: Hard byte ceiling for the whole advisory payload (after base64/JSON).
MAX_ADVISORY_PAYLOAD_BYTES = 10_000_000

#: Planning-only cost unit for the generation plan (1 = one missing view's
#: asset).  This is a labour COUNT, explicitly NOT a time/currency estimate;
#: real costs come from the MF-END-08 graph measurements.
ESTIMATED_COST_UNITS_PER_VIEW = 1
GENERATION_COST_UNIT = "asset"

#: Note recorded when the advisory route is unusable — the deterministic
#: result stays valid and the user chooses manually (MF-END-06.4).
_MANUAL_CHOICE_DETAIL = (
    "advisory route unavailable; choose manually from the listed candidates"
)

#: System prompt for the pinned advisory route.  It restates the contract the
#: service enforces on the response: choose within the candidates or say none.
ADVISORY_SYSTEM_PROMPT = (
    "You are MotionForge's cast-advisory judge. You receive a role requirement "
    "and a deterministic candidate list that has ALREADY passed the "
    "authoritative compatibility filter. Reply with one JSON object only: "
    '{"choice": "<pack_version_id from the candidates>", "reasons": ["..."]}. '
    "You may ONLY choose one of the listed candidate pack_version_id values, or "
    'use {"choice": null}. Never invent ids, never add candidates, never ask '
    "for the video — you only ever receive bounded still images and metadata."
)


# ── errors ────────────────────────────────────────────────────────────────────


class CastRecommendationError(Exception):
    """Base error for the cast recommendation service."""


class CastRecommendationNotFoundError(CastRecommendationError):
    """Target video/role not found in this workspace (no cross-workspace leak)."""


class CastRecommendationInputError(CastRecommendationError, ValueError):
    """The request cannot be served as written (422-class)."""


class AdvisoryUnavailableError(CastRecommendationError):
    """The pinned advisory route could not be used (result stays usable)."""


# ── pinned advisory route ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class AdvisoryRoutePin:
    """The ONE pinned advisory route.  Data, not a runtime decision.

    ``fallback_allowed=False`` is enforced by construction: the default client
    performs exactly one request to this exact model; on any failure it raises
    :class:`AdvisoryUnavailableError` instead of switching models.
    """

    provider: str
    base_url: str
    api_mode: str
    model: str
    fallback_allowed: bool
    timeout_seconds: float


#: Mirrors the delivery's pinned route (EXECUTION_CONTRACT §6): custom provider,
#: local OpenAI-compatible endpoint, chat_completions, fallback OFF.
ADVISORY_ROUTE_PIN = AdvisoryRoutePin(
    provider="custom",
    base_url="http://127.0.0.1:20128/v1",
    api_mode="chat_completions",
    model="ocg/deepseek-v4.1-flash",
    fallback_allowed=False,
    timeout_seconds=30.0,
)


class AdvisoryClient(Protocol):
    """Transport seam for the advisory route (injected in CI)."""

    def complete(
        self, pin: AdvisoryRoutePin, messages: list[dict], *, timeout_seconds: float
    ) -> object:
        """Return the parsed advisory answer, or raise.

        Returning a ``dict`` is the happy path; any exception becomes
        ``AdvisoryUnavailableError`` semantics at the call site.
        """
        ...  # pragma: no cover - protocol


def _extract_json_object(text: str) -> dict:
    """Extract the first..last ``{...}`` JSON object from *text*."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise AdvisoryUnavailableError("advisory response contained no JSON object")
    try:
        payload = json.loads(text[start : end + 1])
    except ValueError as exc:
        raise AdvisoryUnavailableError(
            f"advisory response was not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise AdvisoryUnavailableError("advisory response JSON was not an object")
    return payload


class PinnedRouteAdvisoryClient:
    """Default client: ONE POST to the pinned route, no model fallback.

    Uses the stdlib (no extra dependency) with proxies disabled — the pin is a
    loopback endpoint.  Any transport/HTTP/shape failure raises
    :class:`AdvisoryUnavailableError` with the concrete cause; the caller
    surfaces it and keeps the deterministic result usable.
    """

    def complete(
        self, pin: AdvisoryRoutePin, messages: list[dict], *, timeout_seconds: float
    ) -> object:
        url = pin.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(
            {"model": pin.model, "messages": messages, "temperature": 0},
            ensure_ascii=True,
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise AdvisoryUnavailableError(
                f"advisory route {pin.model!r} returned HTTP {exc.code}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - transport failures are unavailable
            raise AdvisoryUnavailableError(
                f"advisory route {pin.model!r} unreachable: {type(exc).__name__}: {exc}"
            ) from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise AdvisoryUnavailableError(
                f"advisory route {pin.model!r} returned non-JSON: {exc}"
            ) from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AdvisoryUnavailableError(
                "advisory response did not match the chat_completions shape"
            ) from exc
        if not isinstance(content, str):
            raise AdvisoryUnavailableError("advisory response content was not text")
        return _extract_json_object(content)


# ── internals ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _AdvisoryImage:
    label: str
    data_url: str


@dataclass(frozen=True)
class _Candidate:
    """One eligible candidate (real rows only)."""

    pack: CharacterPackVersion
    character: Character
    source: str  # "series_snapshot" | "library"
    snapshot_id: str | None
    snapshot_index: int | None
    live_ok: bool | None
    live_problems: tuple[str, ...]
    style_version: str | None
    style_match: bool | None
    available_views: tuple[str, ...]
    missing_views: tuple[str, ...]
    reasons: tuple[tuple[str, str], ...]
    rank: int = 0


def _reason(code: str, detail: str) -> tuple[str, str]:
    return (code, detail)


def _view_of_slot(pose_slot: str) -> str:
    """View name of a pose slot / reference key (``<view>@<role>``)."""
    return pose_slot.split("@", 1)[0]


def _sort_key(candidate: _Candidate) -> tuple[int, int, int, int]:
    """Deterministic metadata rank key (MF-END-06.2).

    Order: series pin first (absolute), then view coverage, then style
    knowledge, then newer pack version.  Equal keys are a REAL tie — only such
    a tie permits an advisory call, so the advisory can never overrule a
    deterministic preference.
    """
    source_rank = 0 if candidate.source == "series_snapshot" else 1
    coverage_rank = 0 if not candidate.missing_views else 1
    if candidate.style_match is True:
        style_rank = 0
    elif candidate.style_match is None:
        style_rank = 1
    else:
        style_rank = 2
    return (source_rank, coverage_rank, style_rank, -candidate.pack.version)


def _assign_ranks(candidates: list[_Candidate]) -> list[_Candidate]:
    """Rank candidates deterministically; equal metadata keys share a rank."""
    ordered = sorted(candidates, key=lambda item: (_sort_key(item), item.pack.id))
    ranked: list[_Candidate] = []
    previous_key: tuple[int, int, int, int] | None = None
    previous_rank = 0
    for index, candidate in enumerate(ordered):
        key = _sort_key(candidate)
        rank = index if key != previous_key else previous_rank
        ranked.append(
            _Candidate(
                pack=candidate.pack,
                character=candidate.character,
                source=candidate.source,
                snapshot_id=candidate.snapshot_id,
                snapshot_index=candidate.snapshot_index,
                live_ok=candidate.live_ok,
                live_problems=candidate.live_problems,
                style_version=candidate.style_version,
                style_match=candidate.style_match,
                available_views=candidate.available_views,
                missing_views=candidate.missing_views,
                reasons=candidate.reasons,
                rank=rank,
            )
        )
        previous_key = key
        previous_rank = rank
    return ranked


# ── requirement derivation / validation ───────────────────────────────────────


def derive_role_requirements(
    session: Session, workspace_id: str, video_item_id: str
) -> list[CastRoleRequirement]:
    """Server-side authority for a video's cast requirements.

    One requirement per confirmed ``ObjectRole`` of the video (name → role_key,
    kind → kind, real role id attached).  ``source_overlay`` is backend-owned
    removal-only and is never a cast requirement (it is skipped, not invented).
    ``required_views`` stays empty on purpose: the plan says views are created
    when a shot needs them, so no default six-pose demand is reintroduced here.
    """
    rows = session.scalars(
        select(ObjectRole)
        .where(
            ObjectRole.workspace_id == workspace_id,
            ObjectRole.video_item_id == video_item_id,
            ObjectRole.status == "confirmed",
        )
        .order_by(ObjectRole.name, ObjectRole.id)
    ).all()
    requirements: list[CastRoleRequirement] = []
    for row in rows:
        if row.kind == SOURCE_OVERLAY_KIND:
            continue
        requirements.append(
            CastRoleRequirement(
                role_key=row.name,
                kind=row.kind,
                object_role_id=row.id,
            )
        )
    return requirements


def _validate_explicit_requirements(
    session: Session,
    workspace_id: str,
    video_item_id: str,
    requirements: list[CastRoleRequirement],
) -> None:
    for requirement in requirements:
        if requirement.object_role_id is None:
            continue
        role = session.get(ObjectRole, requirement.object_role_id)
        if (
            role is None
            or role.workspace_id != workspace_id
            or role.video_item_id != video_item_id
        ):
            raise CastRecommendationNotFoundError(
                f"role {requirement.role_key!r}: object role "
                f"{requirement.object_role_id!r} does not belong to this video "
                "in this workspace"
            )
        if role.kind != requirement.kind:
            raise CastRecommendationInputError(
                f"role {requirement.role_key!r}: declared kind "
                f"{requirement.kind!r} does not match the live object role kind "
                f"{role.kind!r}"
            )


# ── advisory payload construction ─────────────────────────────────────────────


def _resolve_source_frames(
    session: Session,
    workspace_id: str,
    frames: list[SourceFrameInput],
    managed_root: Path | None,
) -> tuple[list[_AdvisoryImage], list[tuple[str, str]]]:
    """Resolve caller-provided advisory frames — IMAGES only, never a video."""
    if not frames:
        return [], []
    if managed_root is None:
        raise CastRecommendationInputError(
            "managed_root is required to resolve source frame artifacts"
        )
    root = ManagedRoot(managed_root)
    images: list[_AdvisoryImage] = []
    notes: list[tuple[str, str]] = []
    for index, frame in enumerate(frames):
        artifact = session.get(Artifact, frame.artifact_id)
        if artifact is None or artifact.workspace_id != workspace_id:
            raise CastRecommendationNotFoundError(
                f"source frame {index}: artifact {frame.artifact_id!r} not found "
                "in this workspace"
            )
        mime = (artifact.mime_type or "").lower()
        if artifact.kind == "video" or mime.startswith("video/"):
            raise CastRecommendationInputError(
                f"source frame {index}: artifact {frame.artifact_id!r} is a "
                "VIDEO — a whole video is never sent to the advisory route"
            )
        if artifact.kind != "image":
            raise CastRecommendationInputError(
                f"source frame {index}: artifact {frame.artifact_id!r} is not an "
                "image artifact"
            )
        if artifact.state != "ready":
            raise CastRecommendationInputError(
                f"source frame {index}: artifact {frame.artifact_id!r} is not "
                f"ready (state {artifact.state!r})"
            )
        label = frame.label or f"frame-{index}"
        image, note = _load_artifact_image(
            root, artifact, label=label, role="source frame"
        )
        if note is not None:
            notes.append(note)
        elif image is not None:
            images.append(image)
    return images, notes


def _load_artifact_image(
    root: ManagedRoot,
    artifact: Artifact,
    *,
    label: str,
    role: str,
) -> tuple[_AdvisoryImage | None, tuple[str, str] | None]:
    """Load + verify one image artifact as a data URL (or a skip note)."""
    try:
        path = root.resolve(artifact.relative_path)
    except ManagedPathError as exc:
        return None, _reason(
            "image_path_refused", f"{role} {label}: managed path refused: {exc}"
        )
    if not path.is_file():
        return None, _reason(
            "image_file_missing", f"{role} {label}: managed file is missing"
        )
    size = path.stat().st_size
    if size > MAX_ADVISORY_IMAGE_BYTES:
        return None, _reason(
            "image_too_large",
            f"{role} {label}: {size} bytes exceeds the "
            f"{MAX_ADVISORY_IMAGE_BYTES}-byte advisory image cap",
        )
    data = path.read_bytes()
    if artifact.sha256 and hash_file(path).lower() != artifact.sha256.lower():
        return None, _reason(
            "image_digest_mismatch",
            f"{role} {label}: bytes do not match the artifact sha256 — not sent",
        )
    mime = (artifact.mime_type or "image/png").lower()
    encoded = base64.b64encode(data).decode("ascii")
    return _AdvisoryImage(label=label, data_url=f"data:{mime};base64,{encoded}"), None


def _front_artwork_artifact(candidate: _Candidate) -> Artifact | None:
    """The candidate's front-view artwork artifact (deterministic pick)."""
    assets = sorted(candidate.pack.assets, key=lambda asset: asset.pose_slot)
    front = [asset for asset in assets if _view_of_slot(asset.pose_slot) == "front"]
    chosen = (front or assets)[: MAX_ADVISORY_IMAGES_PER_CANDIDATE]
    if not chosen:
        return None
    artifact = chosen[0].artifact
    if artifact is None or artifact.workspace_id != candidate.pack.workspace_id:
        return None
    return artifact


def _build_advisory_payload(
    scope: dict,
    candidate_images: list[_AdvisoryImage],
    frame_images: list[_AdvisoryImage],
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Assemble the chat_completions messages + size notes.

    The payload is re-bounded twice: whole-payload byte cap first drops the
    candidate artwork, then all images.  At no point can a video enter the
    payload (frames were validated as images and artwork comes from image
    artifacts only).
    """
    notes: list[tuple[str, str]] = []

    def _assemble(items: list[_AdvisoryImage]) -> tuple[list[dict], int]:
        parts: list[dict] = [
            {
                "type": "text",
                "text": json.dumps(scope, sort_keys=True, ensure_ascii=True),
            }
        ]
        for image in items:
            parts.append(
                {"type": "image_url", "image_url": {"url": image.data_url}}
            )
        messages = [
            {"role": "system", "content": ADVISORY_SYSTEM_PROMPT},
            {"role": "user", "content": parts},
        ]
        return messages, len(json.dumps(messages, ensure_ascii=True).encode("utf-8"))

    messages, total = _assemble(candidate_images + frame_images)
    if total > MAX_ADVISORY_PAYLOAD_BYTES and candidate_images:
        notes.append(
            _reason(
                "candidate_images_dropped_for_size",
                f"payload {total} bytes exceeded the cap; candidate artwork dropped",
            )
        )
        messages, total = _assemble(frame_images)
    if total > MAX_ADVISORY_PAYLOAD_BYTES and frame_images:
        notes.append(
            _reason(
                "advisory_images_dropped_for_size",
                f"payload {total} bytes exceeded the cap; all images dropped",
            )
        )
        messages, total = _assemble([])
    if total > MAX_ADVISORY_PAYLOAD_BYTES:  # pragma: no cover - defensive
        raise AdvisoryUnavailableError(
            "advisory metadata alone exceeds the payload cap"
        )
    return messages, notes


def _advisory_scope(
    requirement: CastRoleRequirement, tie_set: list[_Candidate]
) -> dict:
    return {
        "type": "cast_recommendation_advisory",
        "role_key": requirement.role_key,
        "kind": requirement.kind,
        "required_views": list(requirement.required_views),
        "style_version": requirement.style_version,
        "video_payload_attached": False,
        "candidates": [
            {
                "pack_version_id": candidate.pack.id,
                "character_id": candidate.character.id,
                "character_name": candidate.character.name,
                "character_code": candidate.character.code,
                "character_type": candidate.character.character_type,
                "available_views": list(candidate.available_views),
                "missing_views": list(candidate.missing_views),
                "source": candidate.source,
            }
            for candidate in tie_set[:MAX_ADVISORY_CANDIDATES]
        ],
        "instruction": (
            "Choose exactly one candidate pack_version_id (or null) and answer "
            'as {"choice": ..., "reasons": [...]}'
        ),
    }


def _run_advisory_for_role(
    *,
    pin: AdvisoryRoutePin,
    requirement: CastRoleRequirement,
    tie_set: list[_Candidate],
    frames: list[_AdvisoryImage],
    managed_root: Path | None,
    client: AdvisoryClient | None,
) -> tuple[RoleAdvisoryData, str | None]:
    """One advisory round-trip for one role; advisory can never override."""
    notes: list[tuple[str, str]] = []
    candidate_images: list[_AdvisoryImage] = []
    if managed_root is not None:
        for candidate in tie_set[:MAX_ADVISORY_CANDIDATES]:
            artifact = _front_artwork_artifact(candidate)
            if artifact is None:
                notes.append(
                    _reason(
                        "candidate_artwork_missing",
                        f"candidate {candidate.pack.id!r} has no attached artwork "
                        "artifact; sent as metadata only",
                    )
                )
                continue
            image, note = _load_artifact_image(
                ManagedRoot(managed_root),
                artifact,
                label=f"{candidate.pack.id}:front",
                role="candidate artwork",
            )
            if note is not None:
                notes.append(note)
            elif image is not None:
                candidate_images.append(image)
    else:
        notes.append(
            _reason(
                "managed_root_missing",
                "no managed root supplied; advisory call carries metadata only",
            )
        )
    scope = _advisory_scope(requirement, tie_set)
    try:
        messages, size_notes = _build_advisory_payload(
            scope, candidate_images, frames
        )
    except AdvisoryUnavailableError as exc:
        return (
            RoleAdvisoryData(
                status="unavailable",
                requested=True,
                calls=0,
                error=str(exc),
                notes=[AdvisoryNoteData(code=code, detail=detail) for code, detail in notes],
            ),
            None,
        )
    notes.extend(size_notes)
    resolved_client = client if client is not None else PinnedRouteAdvisoryClient()
    try:
        payload = resolved_client.complete(
            pin, messages, timeout_seconds=pin.timeout_seconds
        )
    except AdvisoryUnavailableError as exc:
        notes.append(
            _reason("manual_choice_available", _MANUAL_CHOICE_DETAIL)
        )
        return (
            RoleAdvisoryData(
                status="unavailable",
                requested=True,
                calls=1,
                error=str(exc),
                notes=[AdvisoryNoteData(code=code, detail=detail) for code, detail in notes],
            ),
            None,
        )
    except Exception as exc:  # noqa: BLE001 - any transport failure is "unavailable"
        notes.append(
            _reason("manual_choice_available", _MANUAL_CHOICE_DETAIL)
        )
        return (
            RoleAdvisoryData(
                status="unavailable",
                requested=True,
                calls=1,
                error=f"{type(exc).__name__}: {exc}",
                notes=[AdvisoryNoteData(code=code, detail=detail) for code, detail in notes],
            ),
            None,
        )
    permitted = {candidate.pack.id for candidate in tie_set}
    choice: str | None = None
    applied: str | None = None
    if not isinstance(payload, dict):
        notes.append(
            _reason(
                "advisory_response_invalid",
                "response was not a JSON object; deterministic selection kept",
            )
        )
    else:
        raw_choice = payload.get("choice")
        if raw_choice is None:
            notes.append(
                _reason(
                    "advisory_choice_none",
                    "advisory answered null; deterministic selection kept",
                )
            )
        elif not isinstance(raw_choice, str):
            notes.append(
                _reason(
                    "advisory_response_invalid",
                    "choice was not a string; deterministic selection kept",
                )
            )
        elif raw_choice not in permitted:
            notes.append(
                _reason(
                    "advisory_choice_outside_permitted_set",
                    f"choice {raw_choice!r} is not in the permitted tie set; "
                    "IGNORED (the deterministic filter is not overridable)",
                )
            )
        else:
            choice = raw_choice
            applied = raw_choice
        raw_reasons = payload.get("reasons")
        if isinstance(raw_reasons, list):
            for item in raw_reasons:
                if isinstance(item, str) and item.strip():
                    notes.append(_reason("advisory_reason", item.strip()))
    return (
        RoleAdvisoryData(
            status="ok",
            requested=True,
            calls=1,
            choice_pack_version_id=choice,
            choice_applied=applied is not None,
            error=None,
            notes=[AdvisoryNoteData(code=code, detail=detail) for code, detail in notes],
        ),
        applied,
    )


# ── candidate construction ────────────────────────────────────────────────────


def _library_pack_rows(session: Session, workspace_id: str) -> list[CharacterPackVersion]:
    """The pool the packet names: PUBLISHED packs of this workspace."""
    return list(
        session.scalars(
            select(CharacterPackVersion)
            .options(
                joinedload(CharacterPackVersion.assets).joinedload(
                    CharacterAsset.artifact
                ),
                joinedload(CharacterPackVersion.character),
            )
            .where(
                CharacterPackVersion.workspace_id == workspace_id,
                CharacterPackVersion.status == "published",
            )
            .order_by(CharacterPackVersion.id)
        )
        .unique()
        .all()
    )


def _evaluate_library_pack(
    pack: CharacterPackVersion,
    character: Character,
    requirement: CastRoleRequirement,
) -> tuple[list[tuple[str, str]], tuple[str, ...]]:
    """Deterministic hard filter for one pack against one requirement.

    Returns ``(reasons, available_views)``; an empty reason list means the pack
    is an eligible candidate.  Completeness reuses the SAME frozen authorities
    as the pin path (``_reference_branch_missing_keys`` for the reference
    branch, ``CORE_POSE_SLOTS`` for legacy).
    """
    reasons: list[tuple[str, str]] = []
    if pack.status != "published":
        reasons.append(
            _reason("unpublished_pack", f"pack status {pack.status!r} is not published")
        )
    if character.status == "archived" or character.archived_at is not None:
        reasons.append(
            _reason("archived_character", "character is archived")
        )
    if not _kind_compatible(requirement.kind, character.character_type):
        reasons.append(
            _reason(
                "object_kind_mismatch",
                f"role kind {requirement.kind!r} is not compatible with character "
                f"type {character.character_type!r}",
            )
        )
    declared_capabilities: tuple[str, ...] = ()
    if pack.pack_contract_version == PACK_CONTRACT_VERSION_REFERENCE:
        manifest = parse_reference_manifest(
            PackContractBranch(
                pack_contract_version=pack.pack_contract_version,
                requirement_manifest_json=pack.requirement_manifest_json,
                requirement_manifest_sha256=pack.requirement_manifest_sha256,
            )
        )
        missing_keys = _reference_branch_missing_keys(pack)
        if missing_keys == ["<invalid reference manifest>"]:
            reasons.append(
                _reason(
                    "incomplete_pack",
                    "reference manifest failed integrity: "
                    + "; ".join(manifest.errors),
                )
            )
        elif missing_keys:
            reasons.append(
                _reason(
                    "incomplete_pack",
                    "missing required reference keys: " + ", ".join(missing_keys),
                )
            )
        declared_capabilities = tuple(manifest.capabilities)
    else:
        present = {asset.pose_slot for asset in pack.assets}
        missing_slots = [slot for slot in CORE_POSE_SLOTS if slot not in present]
        if missing_slots:
            detail = "missing required pose slots: " + ", ".join(missing_slots)
            reasons.append(_reason("incomplete_pack", detail))
            reasons.append(_reason("missing_required_pose", detail))
    missing_capabilities = [
        capability
        for capability in requirement.required_capabilities
        if capability not in declared_capabilities
    ]
    if missing_capabilities:
        reasons.append(
            _reason(
                "missing_required_capability",
                "pack does not declare: " + ", ".join(missing_capabilities),
            )
        )
    views: set[str] = set()
    if pack.pack_contract_version == PACK_CONTRACT_VERSION_REFERENCE:
        views = {_view_of_slot(asset.pose_slot) for asset in pack.assets}
    else:
        views = {asset.pose_slot for asset in pack.assets}
    return reasons, tuple(sorted(views))


def _series_entry_candidate(
    session: Session,
    workspace_id: str,
    requirement: CastRoleRequirement,
    snapshot: SeriesCastSnapshotRecord,
) -> tuple[_Candidate | None, SeriesPinData | None]:
    """Build the series-pin candidate for *requirement* (absolute priority)."""
    entry = next(
        (item for item in snapshot.entries if item.role_key == requirement.role_key),
        None,
    )
    if entry is None:
        return None, None
    repository = SeriesCastRepository(session)
    live_ok = True
    problems: list[str] = []
    try:
        repository._assert_frozen_entry_live(workspace_id, entry)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001 - every staleness class is surfaced
        live_ok = False
        problems.append(f"{type(exc).__name__}: {exc}")
    character = session.get(Character, entry.character_id)
    if character is None:  # pragma: no cover - FK guarantees the row
        raise CastRecommendationError(
            f"series pin entry {entry.role_key!r} references a missing character"
        )
    pack = session.get(CharacterPackVersion, entry.pack_version_id)
    if pack is None:  # pragma: no cover - live check already classified this
        raise CastRecommendationError(
            f"series pin entry {entry.role_key!r} references a missing pack version"
        )
    available = tuple(sorted({_view_of_slot(ref.pose_slot) for ref in entry.references}))
    missing = tuple(
        view for view in requirement.required_views if view not in available
    )
    style_match: bool | None = None
    if requirement.style_version is not None:
        style_match = entry.style_version == requirement.style_version
    reasons: list[tuple[str, str]] = [
        _reason(
            "series_pin",
            f"series snapshot {entry.role_key!r} entry (snapshot index "
            f"{snapshot.snapshot_index}); absolute priority",
        )
    ]
    if not missing and requirement.required_views:
        reasons.append(
            _reason("covers_required_views", "frozen references cover every required view")
        )
    elif missing:
        reasons.append(
            _reason("missing_required_views", "missing: " + ", ".join(missing))
        )
    if requirement.style_version is not None:
        reasons.append(
            _reason(
                "style_match" if style_match else "style_mismatch",
                f"series style {entry.style_version!r} vs required "
                f"{requirement.style_version!r}",
            )
        )
    if not live_ok:
        reasons.append(
            _reason(
                "series_pin_stale",
                "frozen entry no longer matches the live library: "
                + "; ".join(problems),
            )
        )
    return (
        _Candidate(
            pack=pack,
            character=character,
            source="series_snapshot",
            snapshot_id=snapshot.id,
            snapshot_index=snapshot.snapshot_index,
            live_ok=live_ok,
            live_problems=tuple(problems),
            style_version=entry.style_version,
            style_match=style_match,
            available_views=available,
            missing_views=missing,
            reasons=tuple(reasons),
        ),
        SeriesPinData(
            snapshot_id=snapshot.id,
            snapshot_index=snapshot.snapshot_index,
            entries_sha256=snapshot.entries_sha256,
            live_ok=live_ok,
            problems=list(problems),
        ),
    )


def _library_candidate(
    pack: CharacterPackVersion,
    character: Character,
    requirement: CastRoleRequirement,
    available_views: tuple[str, ...],
) -> _Candidate:
    missing = tuple(
        view for view in requirement.required_views if view not in available_views
    )
    style_match: bool | None = None
    reasons: list[tuple[str, str]] = [
        _reason(
            "published_complete_kind_compatible",
            "published, complete on its contract branch, kind-compatible",
        )
    ]
    if requirement.required_views:
        if missing:
            reasons.append(
                _reason("missing_required_views", "missing: " + ", ".join(missing))
            )
        else:
            reasons.append(
                _reason("covers_required_views", "all required views available")
            )
    if requirement.style_version is not None:
        reasons.append(
            _reason(
                "style_unverified",
                "library packs carry no style version; style is only pinned "
                "through a series snapshot",
            )
        )
    if requirement.required_capabilities:
        reasons.append(
            _reason(
                "required_capabilities_declared",
                "declares: " + ", ".join(requirement.required_capabilities),
            )
        )
    return _Candidate(
        pack=pack,
        character=character,
        source="library",
        snapshot_id=None,
        snapshot_index=None,
        live_ok=None,
        live_problems=(),
        style_version=None,
        style_match=style_match,
        available_views=available_views,
        missing_views=missing,
        reasons=tuple(reasons),
    )


# ── serialization ─────────────────────────────────────────────────────────────


def _candidate_data(candidate: _Candidate) -> CastCandidateData:
    return CastCandidateData(
        pack_version_id=candidate.pack.id,
        pack_version=candidate.pack.version,
        character_id=candidate.character.id,
        character_name=candidate.character.name,
        character_code=candidate.character.code,
        character_type=candidate.character.character_type,
        pack_contract_version=candidate.pack.pack_contract_version,
        source=candidate.source,  # type: ignore[arg-type]
        snapshot_id=candidate.snapshot_id,
        snapshot_index=candidate.snapshot_index,
        live_ok=candidate.live_ok,
        live_problems=list(candidate.live_problems),
        rank=candidate.rank,
        available_views=list(candidate.available_views),
        missing_views=list(candidate.missing_views),
        covers_required_views=not candidate.missing_views,
        missing_capabilities=[],
        style_version=candidate.style_version,
        style_match=candidate.style_match,
        reasons=[
            CandidateReasonData(code=code, detail=detail)
            for code, detail in candidate.reasons
        ],
    )


def _generation_plan(
    selected: _Candidate | None, series_pin_stale: bool
) -> GenerationPlanData:
    if selected is None:
        return GenerationPlanData(
            required=False,
            views=[],
            estimated_cost_units=0,
            unit=GENERATION_COST_UNIT,
            note=GENERATION_PLAN_NOTE_NONE,
        )
    if series_pin_stale:
        return GenerationPlanData(
            required=False,
            views=[],
            estimated_cost_units=0,
            unit=GENERATION_COST_UNIT,
            note=GENERATION_PLAN_NOTE_STALE_PIN,
        )
    missing = list(selected.missing_views)
    if not missing:
        return GenerationPlanData(
            required=False,
            views=[],
            estimated_cost_units=0,
            unit=GENERATION_COST_UNIT,
            note=GENERATION_PLAN_NOTE_FULL,
        )
    return GenerationPlanData(
        required=True,
        views=missing,
        estimated_cost_units=len(missing) * ESTIMATED_COST_UNITS_PER_VIEW,
        unit=GENERATION_COST_UNIT,
        note=GENERATION_PLAN_NOTE_MISSING,
    )


# ── entrypoint ────────────────────────────────────────────────────────────────


def recommend_cast(
    session: Session,
    workspace_id: str,
    request: CastRecommendationRequest,
    *,
    advisory_client: AdvisoryClient | None = None,
    managed_root: Path | None = None,
) -> CastRecommendationResult:
    """Read-only cast-set recommendation (see module docstring).

    Never writes: no mapping, no pin, no artifact, no character, no snapshot,
    no job.  ``mutations == 0`` is part of the contract and is asserted.
    """
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise CastRecommendationInputError("workspace_id must not be empty")
    video = session.get(VideoItem, request.video_item_id)
    if video is None:
        raise CastRecommendationNotFoundError(
            f"video item {request.video_item_id!r} not found"
        )
    project = session.get(Project, video.project_id)
    if project is None or project.workspace_id != workspace_id:
        raise CastRecommendationNotFoundError(
            f"video item {request.video_item_id!r} not found in this workspace"
        )

    if request.requirements is None:
        requirements = derive_role_requirements(session, workspace_id, video.id)
    else:
        requirements = list(request.requirements)
        _validate_explicit_requirements(session, workspace_id, video.id, requirements)

    frames, global_notes = _resolve_source_frames(
        session, workspace_id, list(request.source_frames), managed_root
    )

    series_repository = SeriesCastRepository(session)
    snapshot = series_repository.latest_snapshot(workspace_id, project.id)
    series_context: SeriesContextData | None = None
    if snapshot is not None:
        series_context = SeriesContextData(
            snapshot_id=snapshot.id,
            snapshot_index=snapshot.snapshot_index,
            entries_sha256=snapshot.entries_sha256,
            role_keys=sorted(entry.role_key for entry in snapshot.entries),
        )

    library_rows = _library_pack_rows(session, workspace_id)
    advisory_requested = request.advisory == "auto"
    total_calls = 0
    advisory_failures: list[str] = []
    role_results: list[RoleRecommendationData] = []

    for requirement in requirements:
        candidates: list[_Candidate] = []
        filtered: list[FilteredPackData] = []
        for pack in library_rows:
            character = pack.character
            if character is None or character.workspace_id != workspace_id:
                continue
            reasons, available_views = _evaluate_library_pack(
                pack, character, requirement
            )
            if reasons:
                filtered.append(
                    FilteredPackData(
                        pack_version_id=pack.id,
                        character_id=character.id,
                        character_name=character.name,
                        reasons=[
                            CandidateReasonData(code=code, detail=detail)
                            for code, detail in reasons
                        ],
                    )
                )
                continue
            candidates.append(
                _library_candidate(pack, character, requirement, available_views)
            )

        series_candidate: _Candidate | None = None
        series_pin_data: SeriesPinData | None = None
        if snapshot is not None:
            series_candidate, series_pin_data = _series_entry_candidate(
                session, workspace_id, requirement, snapshot
            )
            if series_candidate is not None:
                # The frozen pack must appear exactly once: as the series pin.
                candidates = [
                    candidate
                    for candidate in candidates
                    if candidate.pack.id != series_candidate.pack.id
                ]
                filtered = [
                    entry
                    for entry in filtered
                    if entry.pack_version_id != series_candidate.pack.id
                ]
                candidates.append(series_candidate)

        ranked = _assign_ranks(candidates)
        top_ties = [candidate for candidate in ranked if candidate.rank == 0]
        advisory_data: RoleAdvisoryData
        advisory_choice: str | None = None
        if not advisory_requested:
            advisory_data = RoleAdvisoryData(
                status="not_requested", requested=False, calls=0
            )
        elif series_candidate is not None:
            advisory_data = RoleAdvisoryData(
                status="not_needed",
                requested=True,
                calls=0,
                notes=[
                    AdvisoryNoteData(
                        code="series_pin_decides",
                        detail="series pin has absolute priority; no advisory call",
                    )
                ],
            )
        elif len(ranked) >= 2 and len(top_ties) >= 2:
            advisory_data, advisory_choice = _run_advisory_for_role(
                pin=ADVISORY_ROUTE_PIN,
                requirement=requirement,
                tie_set=top_ties,
                frames=frames,
                managed_root=managed_root,
                client=advisory_client,
            )
        else:
            advisory_data = RoleAdvisoryData(
                status="not_needed",
                requested=True,
                calls=0,
                notes=[
                    AdvisoryNoteData(
                        code="deterministic_top_unique",
                        detail=(
                            "metadata ranking has a unique top candidate; no "
                            "advisory call"
                        ),
                    )
                ],
            )
        total_calls += advisory_data.calls
        if advisory_data.status == "unavailable" and advisory_data.error:
            advisory_failures.append(advisory_data.error)

        selected: _Candidate | None = None
        selection_mode: str
        if series_candidate is not None:
            selected = series_candidate
            selection_mode = "series_pin"
        elif advisory_choice is not None:
            selected = next(
                candidate for candidate in ranked if candidate.pack.id == advisory_choice
            )
            selection_mode = "advisory"
        elif ranked:
            selected = ranked[0]
            selection_mode = "metadata"
        else:
            selection_mode = "none"

        series_pin_stale = (
            series_candidate is not None and not series_candidate.live_ok
        )
        role_results.append(
            RoleRecommendationData(
                role_key=requirement.role_key,
                object_role_id=requirement.object_role_id,
                kind=requirement.kind,
                required_views=list(requirement.required_views),
                required_capabilities=list(requirement.required_capabilities),
                style_version=requirement.style_version,
                series_pin=series_pin_data,
                candidates=[_candidate_data(candidate) for candidate in ranked],
                filtered=filtered,
                selected_pack_version_id=(
                    selected.pack.id if selected is not None else None
                ),
                selected_character_id=(
                    selected.character.id if selected is not None else None
                ),
                selection_mode=selection_mode,  # type: ignore[arg-type]
                missing_views=list(selected.missing_views) if selected else [],
                generation=_generation_plan(
                    selected, series_pin_stale=bool(series_pin_stale)
                ),
                advisory=advisory_data,
            )
        )

    if not advisory_requested:
        overall_status = "not_requested"
    elif total_calls == 0:
        overall_status = "not_needed"
    elif advisory_failures:
        overall_status = "unavailable"
    else:
        overall_status = "ok"
    advisory_report = AdvisoryReportData(
        status=overall_status,  # type: ignore[arg-type]
        route=AdvisoryRoutePinData(
            provider=ADVISORY_ROUTE_PIN.provider,
            base_url=ADVISORY_ROUTE_PIN.base_url,
            api_mode=ADVISORY_ROUTE_PIN.api_mode,
            model=ADVISORY_ROUTE_PIN.model,
            fallback_allowed=ADVISORY_ROUTE_PIN.fallback_allowed,
            timeout_seconds=ADVISORY_ROUTE_PIN.timeout_seconds,
        ),
        calls=total_calls,
        error=advisory_failures[0] if advisory_failures else None,
        notes=[
            AdvisoryNoteData(code=code, detail=detail) for code, detail in global_notes
        ],
    )
    return CastRecommendationResult(
        workspace_id=workspace_id,
        project_id=project.id,
        video_item_id=video.id,
        series=series_context,
        roles=role_results,
        advisory=advisory_report,
        read_only=True,
        mutations=0,
        manual_choice_available=any(role.candidates for role in role_results),
    )
