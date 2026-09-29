"""MF-END-09 — bounded preimage patch applier (byte-exact, CRLF-preserving).

Each patch: read bytes -> assert exactly ONE preimage match -> replace ->
write bytes.  Prints before/after bytes + sha256 per file so the guard can
verify the intended delta (never a silent adjacent-line loss).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-09")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


PATCHES: list[tuple[str, str, str]] = [
    (
        "app/workflow/job_handlers.py",
        """from app.persistence.artifacts import ManagedRoot, hash_file
from app.workflow.durable_worker import OUTPUT_PURPOSES, WorkerContext

__all__ = [
    "JOB_TYPE_INGEST",
    "JOB_TYPE_PROPAGATE",
    "JOB_TYPE_PREVIEW",
    "JOB_TYPE_RENDER",
    "declared_outputs_for",
    "register_api_handlers",
]
""",
        """from app.persistence.artifacts import ManagedRoot, hash_file
from app.workflow.durable_worker import OUTPUT_PURPOSES, WorkerContext
from app.workflow.reference_asset_jobs import (
    JOB_TYPE_REFERENCE_ASSET,
    register_reference_asset_handler,
)

__all__ = [
    "JOB_TYPE_INGEST",
    "JOB_TYPE_PROPAGATE",
    "JOB_TYPE_PREVIEW",
    "JOB_TYPE_REFERENCE_ASSET",
    "JOB_TYPE_RENDER",
    "declared_outputs_for",
    "register_api_handlers",
]
""",
    ),
    (
        "app/workflow/job_handlers.py",
        """    worker.register_handler(
        JOB_TYPE_RENDER,
        _render_handler_entry,
        declared_outputs=declared_outputs_for(JOB_TYPE_RENDER, {}),
    )
""",
        """    worker.register_handler(
        JOB_TYPE_RENDER,
        _render_handler_entry,
        declared_outputs=declared_outputs_for(JOB_TYPE_RENDER, {}),
    )
    # MF-END-09: the reference-asset generation job (own declared-output
    # validator inside the module; no static declared-output paths).
    register_reference_asset_handler(worker)
""",
    ),
    (
        "app/api/routes/durable_characters.py",
        "from app.api.deps import SessionDep, get_config, get_managed_root\n",
        "from app.api.deps import SessionDep, get_config, get_job_service, get_managed_root\n",
    ),
    (
        "app/api/routes/durable_characters.py",
        """    ReferenceArtworkData,
    SetDefaultVersionRequest,
    asset_content_url,
)
""",
        """    ReferenceArtworkData,
    ReferenceAssetJobData,
    ReferenceAssetJobRequest,
    ReferenceAssetJobRetryRequest,
    ReferenceAssetJobSubmitData,
    SetDefaultVersionRequest,
    asset_content_url,
)
""",
    ),
    (
        "app/api/routes/durable_characters.py",
        "from app.workflow import character_reference_ingest\n",
        "from app.workflow import character_reference_ingest, reference_asset_jobs\n",
    ),
    (
        "app/api/routes/durable_characters.py",
        "    return ReferenceArtworkData.from_result(result)\n",
        """    return ReferenceArtworkData.from_result(result)


# ── Reference-asset generation jobs (MF-END-09) ──────────────────────────────

#: Typed refusal code -> HTTP status (fail closed; unlisted codes are 422).
_REFERENCE_ASSET_REFUSAL_STATUS: dict[str, int] = {
    "mf_end09_version_not_found": 404,
    "mf_end09_version_not_draft": 409,
    "mf_end09_target_key_present": 409,
    "mf_end09_source_hash_mismatch": 409,
    "mf_end09_job_not_found": 404,
    "mf_end09_job_not_retryable": 409,
    "mf_end09_idempotency_conflict": 409,
    "mf_end09_graph_pin_mismatch": 500,
    "mf_end09_receipt_incomplete": 500,
}


def _reference_asset_refusal(err: reference_asset_jobs.ReferenceAssetJobError) -> HTTPException:
    status = _REFERENCE_ASSET_REFUSAL_STATUS.get(err.code.value, 422)
    return HTTPException(status, detail=err.as_dict())


def _require_reference_asset_job(job_id: str):
    info = get_job_service().get_job(job_id)
    if info is None or str(info.job_type or "") != reference_asset_jobs.JOB_TYPE_REFERENCE_ASSET:
        raise HTTPException(404, detail={"code": "mf_end09_job_not_found", "job_id": job_id})
    return info


@router.post("/versions/{version_id:uuid}/reference-asset-jobs", status_code=202)
@router.post("/versions/{version_id:uuid}/reference-asset-jobs/", status_code=202)
def submit_reference_asset_job(
    version_id: uuid.UUID,
    body: ReferenceAssetJobRequest,
    session: SessionDep,
    workspace_id: str = WORKSPACE_ID,
) -> ReferenceAssetJobSubmitData:
    \"\"\"Register ONE durable reference-asset generation intent (async).

    The request only validates the live draft pack and inserts the Job row:
    no engine work and no library write happens inside this request.  The
    worker drives graph G1 and the managed ingest; poll the job status for
    progress, the generated asset (draft only) and the cache key.
    \"\"\"
    repo = CharacterRepository(session, storage_root=get_managed_root())
    try:
        version = repo.get_pack_version(str(version_id), workspace_id)
    except PackVersionNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    try:
        result = reference_asset_jobs.submit_reference_asset_job(
            job_service=get_job_service(),
            workspace_id=workspace_id,
            character_id=str(version.character_id),
            version_id=str(version_id),
            reference_key=body.reference_key,
            view_prompt=body.view_prompt,
            source_reference_key=body.source_reference_key,
            style_version=body.style_version,
            seed=body.seed,
            idempotency_key=body.idempotency_key,
            input_generation=body.input_generation,
        )
    except reference_asset_jobs.ReferenceAssetJobError as err:
        raise _reference_asset_refusal(err) from err
    return ReferenceAssetJobSubmitData(
        job=ReferenceAssetJobData.from_info(result.job),
        content_key=result.content_key,
        reference_key=result.reference_key,
        view=result.view,
        role=result.role,
        duplicate=result.duplicate,
    )


@router.get("/reference-asset-jobs/{job_id}")
@router.get("/reference-asset-jobs/{job_id}/")
def get_reference_asset_job(job_id: str) -> ReferenceAssetJobData:
    \"\"\"Durable status of one reference-asset job (reference jobs only).\"\"\"
    return ReferenceAssetJobData.from_info(_require_reference_asset_job(job_id))


@router.post("/reference-asset-jobs/{job_id}/cancel")
@router.post("/reference-asset-jobs/{job_id}/cancel/")
def cancel_reference_asset_job(job_id: str) -> dict[str, object]:
    \"\"\"Durably request cancellation; the attempt identity is preserved.\"\"\"
    _require_reference_asset_job(job_id)
    job_svc = get_job_service()
    if not job_svc.cancel_job(job_id):
        info = job_svc.get_job(job_id)
        raise HTTPException(400, f"Cannot cancel job in state: {info.state.value}")
    return {"status": "cancel_requested", "job_id": job_id}


@router.post("/reference-asset-jobs/{job_id}/retry", status_code=202)
@router.post("/reference-asset-jobs/{job_id}/retry/", status_code=202)
def retry_reference_asset_job(
    job_id: str,
    body: ReferenceAssetJobRetryRequest,
) -> ReferenceAssetJobSubmitData:
    \"\"\"Retry a TERMINAL reference-asset job as a new input generation.

    The content key (identity/view/style/graph) is unchanged, so a terminal
    receipt is replayed with zero engine submits instead of generating again.
    \"\"\"
    _require_reference_asset_job(job_id)
    try:
        result = reference_asset_jobs.resubmit_reference_asset_job(
            job_service=get_job_service(),
            job_id=job_id,
            input_generation=body.input_generation,
        )
    except reference_asset_jobs.ReferenceAssetJobError as err:
        raise _reference_asset_refusal(err) from err
    return ReferenceAssetJobSubmitData(
        job=ReferenceAssetJobData.from_info(result.job),
        content_key=result.content_key,
        reference_key=result.reference_key,
        view=result.view,
        role=result.role,
        duplicate=result.duplicate,
    )
""",
    ),
    (
        "app/schemas/characters.py",
        """class CharacterListResponse(BaseModel):
    workspace_id: str
    limit: int
    offset: int
    total: int
    characters: list[CharacterData]
""",
        """class CharacterListResponse(BaseModel):
    workspace_id: str
    limit: int
    offset: int
    total: int
    characters: list[CharacterData]


class ReferenceAssetJobRequest(BaseModel):
    \"\"\"Submit one reference-asset generation intent (MF-END-09).

    ``reference_key`` is the missing ``<view>@<role>`` the job must create;
    ``view_prompt`` must name that view (the graph prompt is validated, never
    invented).  ``source_reference_key`` defaults to the pack convention
    ``front@character`` when omitted.
    \"\"\"

    reference_key: str = Field(..., min_length=3, max_length=64)
    view_prompt: str = Field(..., min_length=20, max_length=2000)
    source_reference_key: str | None = Field(None, min_length=3, max_length=64)
    style_version: str | None = Field(None, max_length=64)
    seed: int | None = Field(None, ge=0, lt=2**63)
    idempotency_key: str | None = Field(None, min_length=8, max_length=120)
    input_generation: str | None = Field(None, min_length=1, max_length=120)


class ReferenceAssetJobRetryRequest(BaseModel):
    \"\"\"Retry a terminal reference-asset job (new input generation).\"\"\"

    input_generation: str | None = Field(None, min_length=1, max_length=120)


class ReferenceAssetJobSubmitData(BaseModel):
    \"\"\"Public result of an intent registration (no engine work yet).\"\"\"

    job: "ReferenceAssetJobData"
    content_key: str
    reference_key: str
    view: str
    role: str
    duplicate: bool = False


class ReferenceAssetJobData(BaseModel):
    \"\"\"Durable status of one reference-asset generation job.\"\"\"

    job_id: str
    state: str
    progress: float = 0.0
    message: str = ""
    job_type: str = ""
    content_key: str | None = None
    reference_key: str | None = None
    view: str | None = None
    role: str | None = None
    duplicate: bool = False

    @classmethod
    def from_info(
        cls,
        info: Any,
        *,
        content_key: str | None = None,
        reference_key: str | None = None,
        view: str | None = None,
        role: str | None = None,
        duplicate: bool = False,
    ) -> "ReferenceAssetJobData":
        state = getattr(info, "state", "")
        return cls(
            job_id=str(info.job_id),
            state=str(getattr(state, "value", state)),
            progress=float(getattr(info, "progress", 0.0) or 0.0),
            message=str(getattr(info, "message", "") or ""),
            job_type=str(getattr(info, "job_type", "") or ""),
            content_key=content_key,
            reference_key=reference_key,
            view=view,
            role=role,
            duplicate=duplicate,
        )
""",
    ),
]


def apply_all() -> int:
    ok = 0
    for rel, old_text, new_text in PATCHES:
        path = ROOT / rel
        data = path.read_bytes()
        newline = b"\r\n" if b"\r\n" in data else b"\n"
        old = old_text.replace("\n", newline.decode()).encode("utf-8")
        new = new_text.replace("\n", newline.decode()).encode("utf-8")
        count = data.count(old)
        if count != 1:
            print(f"REFUSED {rel}: preimage count={count} (expected 1)")
            return 1
        before_bytes, before_sha = len(data), sha(data)
        updated = data.replace(old, new)
        path.write_bytes(updated)
        print(
            f"PATCHED {rel}: {before_bytes}->{len(updated)} B  sha {before_sha[:12]}"
            f"->{sha(updated)[:12]}"
        )
        ok += 1
    print(f"APPLIED {ok}/{len(PATCHES)}")
    return 0


if __name__ == "__main__":
    sys.exit(apply_all())
