"""MF-END-07 bounded patch: byte-exact preimage edits to the two existing files.

Reads each file as bytes, asserts the LF-normalised preimage occurs EXACTLY
once, applies the edit, writes back with the file's original CRLF convention
and verifies the postimage (sha256/size/line-count deltas recorded).
Never used for whole-file regeneration: every edit is anchored on a unique
preimage; the append blocks only ADD bytes (shrink guard).

Usage:  python mf_end_07_patch.py [--check]
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-07")
EV = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-END-07"
)

SCHEMAS = ROOT / "app/schemas/project_cast.py"
ROUTES = ROOT / "app/api/routes/project_cast.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def logical_lines(data: bytes) -> int:
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


# ── schemas block ─────────────────────────────────────────────────────────────

SCHEMAS_IMPORT_OLD = """from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):"""

SCHEMAS_IMPORT_NEW = """from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.cast_recommendation import REQUIRED_VIEW_VOCABULARY
from app.schemas.shot_reskin import ENGINE_CAPABILITY_PINS


class _StrictModel(BaseModel):"""

SCHEMAS_APPEND = """


# ── MF-END-07: recommendation / confirm (U03/U04/U13 API boundary) ──────────
#
# The suggestion route surfaces MF-END-06's READ-ONLY service verbatim; the
# confirm route accepts the user's choice TOGETHER with the trace of the
# recommendation it came from, so a pin is only ever mutated while the live
# server state still supports that trace (a stale basis is a typed refusal).

#: The selection modes a recommendation can report (echoed by the confirm).
CAST_CONFIRM_SELECTION_MODES = ("series_pin", "advisory", "metadata", "manual")


class CastConfirmTrace(_StrictModel):
    \"\"\"The recommendation the user acted on (the client's echo of it).

    ``selected_pack_version_id`` is the pack the recommendation proposed and it
    must equal the confirmed ``pack_version_id``.  The optional view /
    capability / style fields are the recommendation basis for THIS role (the
    same vocabulary the suggestion request validates); feeding them back lets
    the confirm re-derive the identical candidate set and report actionable
    missing assets instead of guessing.  A ``series_pin`` trace must pin the
    frozen snapshot it came from (MF-END-05) so a stale basis is refused.
    \"\"\"

    role_key: str = Field(
        ..., min_length=1, max_length=64, pattern=SERIES_ROLE_KEY_PATTERN
    )
    selection_mode: Literal[\"series_pin\", \"advisory\", \"metadata\", \"manual\"]
    selected_pack_version_id: str = Field(..., min_length=1, max_length=36)
    required_views: list[str] = Field(
        default_factory=list, max_length=len(REQUIRED_VIEW_VOCABULARY)
    )
    required_capabilities: list[str] = Field(
        default_factory=list, max_length=len(ENGINE_CAPABILITY_PINS)
    )
    style_version: str | None = Field(None, min_length=1, max_length=64)
    series_snapshot_id: str | None = Field(None, min_length=1, max_length=36)
    series_snapshot_index: int | None = Field(None, ge=0)
    series_entries_sha256: str | None = Field(None, pattern=r\"^[0-9a-f]{64}$\")

    @field_validator(\"required_views\")
    @classmethod
    def _views_in_vocabulary(cls, values: list[str]) -> list[str]:
        unknown = [value for value in values if value not in REQUIRED_VIEW_VOCABULARY]
        if unknown:
            raise ValueError(
                \"required_views must come from the measured view vocabulary \"
                f\"{sorted(REQUIRED_VIEW_VOCABULARY)}; unknown: {unknown}\"
            )
        return _unique_nonempty(values, field=\"required_views\")

    @field_validator(\"required_capabilities\")
    @classmethod
    def _capabilities_in_pins(cls, values: list[str]) -> list[str]:
        unknown = [value for value in values if value not in ENGINE_CAPABILITY_PINS]
        if unknown:
            raise ValueError(
                \"required_capabilities must be pinned engine capabilities \"
                f\"{list(ENGINE_CAPABILITY_PINS)}; unknown: {unknown}\"
            )
        return _unique_nonempty(values, field=\"required_capabilities\")

    @model_validator(mode=\"after\")
    def _series_pin_trace_pins_its_snapshot(self) -> CastConfirmTrace:
        if self.selection_mode == \"series_pin\":
            missing = [
                name
                for name, value in (
                    (\"series_snapshot_id\", self.series_snapshot_id),
                    (\"series_snapshot_index\", self.series_snapshot_index),
                    (\"series_entries_sha256\", self.series_entries_sha256),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    \"a series_pin trace must pin the frozen snapshot it was \"
                    \"derived from; missing: \" + \", \".join(missing)
                )
        return self


class CastConfirmRequest(_StrictModel):
    \"\"\"Confirm ONE recommended cast choice against the live server state.

    ``idempotency_key`` is REQUIRED: an identical confirm always replays the
    same mapping and can never write twice.  ``expected_revision`` is the
    version guard for REPLACING an existing pin — a replacement without it is
    refused (422) and a stale token is refused (409).
    \"\"\"

    video_item_id: str = Field(..., min_length=1, max_length=36)
    object_role_id: str = Field(..., min_length=1, max_length=36)
    character_id: str = Field(..., min_length=1, max_length=36)
    pack_version_id: str = Field(..., min_length=1, max_length=36)
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    expected_revision: int | None = Field(None, ge=1)
    fallback_acknowledged: bool = False
    recommendation: CastConfirmTrace


class CastConfirmWarningData(BaseModel):
    \"\"\"One actionable warning about the confirmed choice (never a blocker).\"\"\"

    code: str
    detail: str
    action: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CastConfirmTraceData(BaseModel):
    \"\"\"What the server VERIFIED about the trace (provenance of this write).\"\"\"

    role_key: str
    selection_mode: str
    selected_pack_version_id: str
    verified_source: Literal[\"series_pin\", \"library_candidate\"]
    snapshot_id: str | None = None
    snapshot_index: int | None = None
    entries_sha256: str | None = None
    checked_against: Literal[\"live_recommendation\"] = \"live_recommendation\"

    model_config = ConfigDict(from_attributes=True)


class CastConfirmResponse(BaseModel):
    \"\"\"Result of confirming one recommended choice (write or replay).\"\"\"

    workspace_id: str
    project_id: str
    mapping: ProjectCastData
    trace: CastConfirmTraceData
    warnings: list[CastConfirmWarningData]
    missing_views: list[str]
    generation: GenerationPlanData
    created: bool
    replayed: bool
    mutations: int
    read_only: bool = False

    model_config = ConfigDict(from_attributes=True)
"""

# ── routes edits ──────────────────────────────────────────────────────────────

ROUTES_IMPORT_FASTAPI_OLD = (
    "from fastapi import APIRouter, HTTPException, Query, Response"
)
ROUTES_IMPORT_FASTAPI_NEW = (
    "from fastapi import APIRouter, Depends, HTTPException, Query, Response"
)

ROUTES_IMPORT_DEPS_OLD = "from app.api.deps import SessionDep"
ROUTES_IMPORT_DEPS_NEW = "from app.api.deps import SessionDep, get_managed_root"

ROUTES_IMPORT_MODELS_OLD = """from app.persistence.models import (
    Character,
    CharacterPackVersion,
)
"""
ROUTES_IMPORT_MODELS_NEW = """from app.persistence.models import (
    Character,
    CharacterPackVersion,
    ObjectRole,
    ProjectCastMapping,
)
"""

ROUTES_IMPORT_SCHEMAS_OLD = """from app.schemas.project_cast import (
    CompatibilityEvaluateRequest,
"""
ROUTES_IMPORT_SCHEMAS_NEW = """from app.schemas.cast_recommendation import (
    CastCandidateData,
    CastRecommendationRequest,
    CastRecommendationResult,
    CastRoleRequirement,
    RoleRecommendationData,
)
from app.schemas.project_cast import (
    CastConfirmRequest,
    CastConfirmResponse,
    CastConfirmTraceData,
    CastConfirmWarningData,
    CompatibilityEvaluateRequest,
"""
ROUTES_IMPORT_SERVICES_OLD = """    SeriesCastSnapshotListResponse,
)

router = APIRouter("""
ROUTES_IMPORT_SERVICES_NEW = """    SeriesCastSnapshotListResponse,
)
from app.services.cast_recommendation import (
    AdvisoryClient,
    CastRecommendationInputError,
    CastRecommendationNotFoundError,
    recommend_cast,
)

router = APIRouter("""

ROUTES_APPEND = '''

# ── MF-END-07: recommendation (read-only) + confirm (guarded mutation) ───────
#
# The suggestion route surfaces the MF-END-06 service verbatim: role
# requirements and the series pin are read from the SERVER (never supplied by
# the client), nothing is written and no job is enqueued.  The confirm route
# re-derives that recommendation from the live state and refuses (typed 409,
# zero mutation) whenever the user's trace no longer matches it — only then
# does it write through the EXISTING ProjectCastRepository authority.


def get_cast_advisory_client() -> AdvisoryClient | None:
    """Advisory client for the suggestion route: None = the pinned default.

    Exposed as a dependency so a test (or an embedding host) can override it
    and prove that no advisory call happens on paths that do not need one.
    """
    return None


CastAdvisoryDep = Annotated[AdvisoryClient | None, Depends(get_cast_advisory_client)]


@router.post("/recommendations", status_code=200)
@router.post("/recommendations/", status_code=200)
def recommend_cast_route(
    body: CastRecommendationRequest,
    session: SessionDep,
    advisory_client: CastAdvisoryDep,
) -> CastRecommendationResult:
    """Suggest a cast set for one video (READ-ONLY: never mutates a pin)."""
    try:
        return recommend_cast(
            session,
            WORKSPACE_ID,
            body,
            advisory_client=advisory_client,
            managed_root=get_managed_root(),
        )
    except CastRecommendationNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    except CastRecommendationInputError as err:
        raise HTTPException(422, str(err)) from err


def _match_trace_role(
    plan: CastRecommendationResult, body: CastConfirmRequest
) -> RoleRecommendationData:
    """Resolve the role the trace names — 409 when it is not this video's role."""
    trace = body.recommendation
    role = next((item for item in plan.roles if item.role_key == trace.role_key), None)
    if role is None:
        raise HTTPException(
            409,
            f"recommendation trace role_key {trace.role_key!r} is not one of this "
            "video's server-derived cast requirements",
        )
    if role.object_role_id != body.object_role_id:
        raise HTTPException(
            409,
            f"recommendation trace role_key {trace.role_key!r} maps to object role "
            f"{role.object_role_id!r}, not {body.object_role_id!r}",
        )
    return role


def _confirm_basis(
    session: Session, body: CastConfirmRequest
) -> tuple[CastRecommendationResult, RoleRecommendationData]:
    """Re-derive the LIVE recommendation basis for the trace being confirmed.

    The trace's view / capability / style claims are fed back as an explicit
    requirement (the kind always comes from the live role — a client never
    supplies it), so the confirm validates against the SAME deterministic
    filter the user was shown and can report the real missing assets for the
    chosen pack.
    """
    trace = body.recommendation
    requirements: list[CastRoleRequirement] | None = None
    if trace.required_views or trace.required_capabilities or trace.style_version:
        base_plan = recommend_cast(
            session,
            WORKSPACE_ID,
            CastRecommendationRequest(video_item_id=body.video_item_id, advisory="off"),
        )
        base_role = _match_trace_role(base_plan, body)
        requirements = [
            CastRoleRequirement(
                role_key=trace.role_key,
                kind=base_role.kind,
                object_role_id=body.object_role_id,
                required_views=list(trace.required_views),
                required_capabilities=list(trace.required_capabilities),
                style_version=trace.style_version,
            )
        ]
    plan = recommend_cast(
        session,
        WORKSPACE_ID,
        CastRecommendationRequest(
            video_item_id=body.video_item_id,
            requirements=requirements,
            advisory="off",
        ),
    )
    return plan, _match_trace_role(plan, body)


def _require_fresh_series_basis(
    body: CastConfirmRequest,
    role: RoleRecommendationData,
    candidate: CastCandidateData,
) -> None:
    """The trace's frozen snapshot must BE the live series pin (else 409)."""
    trace = body.recommendation
    pin = role.series_pin
    if (
        trace.selection_mode != "series_pin"
        or trace.series_snapshot_id != candidate.snapshot_id
        or trace.series_snapshot_index != candidate.snapshot_index
        or (pin is not None and trace.series_entries_sha256 != pin.entries_sha256)
    ):
        raise HTTPException(
            409,
            "stale recommendation basis: the live series pin for role "
            f"{trace.role_key!r} is snapshot {candidate.snapshot_id!r} "
            f"(index {candidate.snapshot_index}), not snapshot "
            f"{trace.series_snapshot_id!r} (index {trace.series_snapshot_index})",
        )


@router.post("/recommendations/confirm", status_code=201)
@router.post("/recommendations/confirm/", status_code=201)
def confirm_recommendation_route(
    body: CastConfirmRequest,
    session: SessionDep,
    response: Response,
) -> CastConfirmResponse:
    """Confirm ONE recommended choice — the only mutating path of this API.

    A mutation requires: the trace still matching the LIVE recommendation, the
    chosen pack being a live candidate, and (when an existing pin is replaced)
    an explicit matching ``expected_revision``.  Every refusal returns
    404/409/422 with ZERO mutation, and the write itself rides the existing
    cast repository — no new store, no new job type, no new table.
    """
    trace = body.recommendation
    role_row = session.get(ObjectRole, body.object_role_id)
    if (
        role_row is None
        or role_row.workspace_id != WORKSPACE_ID
        or role_row.video_item_id != body.video_item_id
    ):
        raise HTTPException(
            404,
            f"object role {body.object_role_id!r} does not belong to this video "
            "in this workspace",
        )
    plan, role = _confirm_basis(session, body)
    if trace.selected_pack_version_id != body.pack_version_id:
        raise HTTPException(
            409,
            "confirmed pack_version_id does not match the recommendation trace "
            f"proposal {trace.selected_pack_version_id!r}",
        )
    candidate = next(
        (item for item in role.candidates if item.pack_version_id == body.pack_version_id),
        None,
    )
    if candidate is None:
        excluded = next(
            (
                item
                for item in role.filtered
                if item.pack_version_id == body.pack_version_id
            ),
            None,
        )
        detail = (
            "; ".join(f"{reason.code}: {reason.detail}" for reason in excluded.reasons)
            if excluded is not None
            else "the pack is not among this role's live candidates"
        )
        raise HTTPException(
            409,
            f"pack {body.pack_version_id!r} is not a live candidate for role "
            f"{trace.role_key!r} ({detail})",
        )
    if candidate.character_id != body.character_id:
        raise HTTPException(
            409,
            "character_id does not match the recommended candidate's character "
            f"{candidate.character_id!r}",
        )
    if candidate.source == "series_snapshot":
        _require_fresh_series_basis(body, role, candidate)
    elif trace.selection_mode == "series_pin":
        raise HTTPException(
            409,
            "stale recommendation basis: the frozen series entry this trace was "
            "derived from is no longer the live series pin for this role",
        )
    if candidate.live_ok is False:
        raise HTTPException(
            409,
            "stale recommendation basis: the frozen series entry no longer matches "
            "the live library (" + "; ".join(candidate.live_problems) + ")",
        )
    repo = ProjectCastRepository(session)
    existing = session.scalar(
        select(ProjectCastMapping).where(
            ProjectCastMapping.workspace_id == WORKSPACE_ID,
            ProjectCastMapping.project_id == plan.project_id,
            ProjectCastMapping.object_role_id == body.object_role_id,
        )
    )
    created = False
    replayed = False
    try:
        if existing is not None and (
            existing.character_id == body.character_id
            and existing.pack_version_id == body.pack_version_id
        ):
            # Idempotent replay: this choice is already pinned — zero mutation.
            record = repo.get_mapping(str(existing.id), WORKSPACE_ID)
            replayed = True
        else:
            if existing is None:
                record, created = repo.create_mapping(
                    workspace_id=WORKSPACE_ID,
                    project_id=plan.project_id,
                    object_role_id=body.object_role_id,
                    character_id=body.character_id,
                    pack_version_id=body.pack_version_id,
                    idempotency_key=body.idempotency_key,
                    fallback_acknowledged=body.fallback_acknowledged,
                )
            else:
                if body.expected_revision is None:
                    raise HTTPException(
                        422,
                        "expected_revision is required to replace the existing pin "
                        f"of role {body.object_role_id!r}",
                    )
                record = repo.update_mapping(
                    str(existing.id),
                    WORKSPACE_ID,
                    expected_revision=body.expected_revision,
                    character_id=body.character_id,
                    pack_version_id=body.pack_version_id,
                    fallback_acknowledged=body.fallback_acknowledged,
                )
            session.commit()
    except HTTPException:
        session.rollback()
        raise
    except ProjectCastOwnershipError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ProjectCastConflictError as err:
        session.rollback()
        raise HTTPException(409, str(err)) from err
    except ProjectCastNotFoundError as err:
        session.rollback()
        raise HTTPException(404, str(err)) from err
    except ValueError as err:
        session.rollback()
        raise HTTPException(422, str(err)) from err
    except IntegrityError as err:
        session.rollback()
        raise HTTPException(409, "cast confirm conflict") from err
    if not created:
        response.status_code = 200
    warnings: list[CastConfirmWarningData] = []
    if candidate.missing_views:
        warnings.append(
            CastConfirmWarningData(
                code="missing_required_views",
                detail=(
                    "the chosen pack does not cover required views: "
                    + ", ".join(candidate.missing_views)
                ),
                action=(
                    "create the missing assets before rendering; the generation "
                    "plan below is the actionable list"
                ),
            )
        )
    if candidate.missing_capabilities:
        warnings.append(
            CastConfirmWarningData(
                code="missing_required_capabilities",
                detail=(
                    "the chosen pack does not declare: "
                    + ", ".join(candidate.missing_capabilities)
                ),
                action=(
                    "confirm a pack that declares the capability or extend this one"
                ),
            )
        )
    if role.generation.required:
        warnings.append(
            CastConfirmWarningData(
                code="generation_plan_required",
                detail=role.generation.note,
                action=(
                    "hand this plan to the generation flow (assets are created "
                    "only when missing)"
                ),
            )
        )
    return CastConfirmResponse(
        workspace_id=WORKSPACE_ID,
        project_id=plan.project_id,
        mapping=ProjectCastData.from_record(record),
        trace=CastConfirmTraceData(
            role_key=trace.role_key,
            selection_mode=trace.selection_mode,
            selected_pack_version_id=trace.selected_pack_version_id,
            verified_source=(
                "series_pin"
                if candidate.source == "series_snapshot"
                else "library_candidate"
            ),
            snapshot_id=candidate.snapshot_id,
            snapshot_index=candidate.snapshot_index,
            entries_sha256=(
                role.series_pin.entries_sha256 if role.series_pin is not None else None
            ),
        ),
        warnings=warnings,
        missing_views=list(candidate.missing_views),
        generation=role.generation,
        created=created,
        replayed=replayed,
        mutations=0 if replayed else 1,
        read_only=False,
    )
'''


def apply(path: Path, edits: list[tuple[str, str]], append: str | None) -> dict:
    before = path.read_bytes()
    text = before.decode("utf-8")
    lf = text.replace("\r\n", "\n")
    record = {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "sha256_before": hashlib.sha256(before).hexdigest(),
        "bytes_before": len(before),
        "lines_before": logical_lines(before),
        "edits": [],
    }
    for index, (old, new) in enumerate(edits, start=1):
        old_lf = old.replace("\r\n", "\n")
        new_lf = new.replace("\r\n", "\n")
        count = lf.count(old_lf)
        assert count == 1, f"{path.name} edit {index}: preimage count {count} != 1"
        lf = lf.replace(old_lf, new_lf, 1)
        record["edits"].append({"edit": index, "preimage_count": count})
    if append:
        assert append.endswith("\n"), "append block must end with a newline"
        tail = lf[-80:].replace("\n", "\\n")
        assert lf.endswith("\n"), f"{path.name}: file does not end with newline"
        lf = lf.rstrip("\n") + "\n\n\n" + append.lstrip("\n")
        record["append_tail_before"] = tail
    out = lf.replace("\n", "\r\n").encode("utf-8")
    assert len(out) > len(before), "destructive shrink detected"
    path.write_bytes(out)
    after = path.read_bytes()
    record.update(
        {
            "sha256_after": hashlib.sha256(after).hexdigest(),
            "bytes_after": len(after),
            "lines_after": logical_lines(after),
            "bytes_delta": len(after) - len(before),
            "lines_delta": logical_lines(after) - logical_lines(before),
            "crlf_after": after.count(b"\r\n") == after.count(b"\n"),
            "compiles": None,
        }
    )
    return record


def main() -> int:
    check = "--check" in sys.argv
    records = [
        apply(
            SCHEMAS,
            [(SCHEMAS_IMPORT_OLD, SCHEMAS_IMPORT_NEW)],
            SCHEMAS_APPEND,
        ),
        apply(
            ROUTES,
            [
                (ROUTES_IMPORT_FASTAPI_OLD, ROUTES_IMPORT_FASTAPI_NEW),
                (ROUTES_IMPORT_DEPS_OLD, ROUTES_IMPORT_DEPS_NEW),
                (ROUTES_IMPORT_MODELS_OLD, ROUTES_IMPORT_MODELS_NEW),
                (ROUTES_IMPORT_SCHEMAS_OLD, ROUTES_IMPORT_SCHEMAS_NEW),
                (ROUTES_IMPORT_SERVICES_OLD, ROUTES_IMPORT_SERVICES_NEW),
            ],
            ROUTES_APPEND,
        ),
    ]
    out = EV / "raw" / "patch_applied.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, indent=1), encoding="utf-8")
    print(json.dumps(records, indent=1))
    print("PATCH_OK" if not check else "CHECK_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
