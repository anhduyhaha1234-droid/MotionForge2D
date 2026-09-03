"""HTTP surface for S10 FullApply durable orchestration (S10-T01C).

Additive, project-scoped, idempotent:

  POST   /api/v2/projects/{project_id}/full-apply          submit (202 Accepted, worker outside request)
  GET    /api/v2/full-apply/{run_id}                        status + chunks/publications
  POST   /api/v2/full-apply/{run_id}/cancel                 cancel (exact owned process semantics)
  POST   /api/v2/full-apply/{run_id}/retry                  retry creates new attempt lineage
  POST   /api/v2/full-apply/{run_id}/resume                 resume from durable checkpoint

Every handler is workspace-scoped (query workspace_id, default workspace)
and project-scoped where applicable.  Same approved tuple dedupes; changed
checkpoint/plan/revision produces a distinct lineage (natural_key).
Artifacts publish via managed atomic storage + content sha256.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

from app.api.deps import SessionDep, get_job_service
from app.persistence import DEFAULT_WORKSPACE_ID
from app.persistence.s10_full_apply import (
    S10ApplyCheckpointStaleError,
    S10ApplyConflictError,
    S10ApplyNotFoundError,
    S10ApplyOwnershipError,
    S10ApplyParamsError,
)
from app.services.s10_full_apply import FullApplyService, FullApplyServiceError


# -- C6: persisted render authority resolution (never synthetic media) ---------
# The server resolves the ORIGINAL managed source artifact and the EXACT
# replacement pack/version/asset identities from persisted approved rows
# (video_item.source_artifact_id, apply_checkpoint.pack_version_ids_json ->
# character_pack_version -> character_asset.artifact_id) and pins artifact ids /
# relative paths / SHA / size / timebase BEFORE job creation.  Missing, tampered,
# cross-workspace or cross-project authority fails closed BEFORE enqueue — the
# production path NEVER creates media to make a request pass.


def _win_long_path(path: Path | str) -> str:
    """Windows extended-length path (>=260) — mirrors s09_demo_jobs helper."""
    raw = str(path)
    if os.name == "nt" and len(raw) > 259 and not raw.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(raw)
    return raw


def _validate_managed_artifact(
    session: Session,
    *,
    artifact_id: str,
    workspace_id: str,
    managed_root: Path | None,
) -> dict[str, Any]:
    """Validate a persisted Artifact row + backing file; fail closed on tamper."""
    from app.persistence.artifacts import hash_file as _hash_file
    from app.persistence.models import Artifact as _Artifact

    art = session.get(_Artifact, artifact_id)
    if art is None:
        raise FullApplyServiceError(f"persisted artifact {artifact_id!r} not found (missing authority)")
    if str(art.workspace_id) != workspace_id:
        raise FullApplyServiceError(
            f"artifact {artifact_id!r} workspace {art.workspace_id!r} != {workspace_id!r} (cross-workspace authority)"
        )
    if str(art.state) != "ready":
        raise FullApplyServiceError(f"artifact {artifact_id!r} state {art.state!r} not ready (authority not published)")
    rel = str(art.relative_path or "")
    sha = str(art.sha256 or "")
    size = int(art.size_bytes) if art.size_bytes is not None else 0
    if not rel or len(sha) != 64 or size <= 0:
        raise FullApplyServiceError(f"artifact {artifact_id!r} incomplete pin (rel/sha256/size_bytes) (missing authority)")
    if managed_root is not None:
        abs_p = managed_root / rel
        if not abs_p.is_file():
            raise FullApplyServiceError(f"artifact {artifact_id!r} backing file missing: {rel}")
        actual = _hash_file(Path(_win_long_path(abs_p)))
        if actual != sha.lower():
            raise FullApplyServiceError(f"artifact {artifact_id!r} sha mismatch: expected {sha} got {actual} (tampered authority)")
        if abs_p.stat().st_size != size:
            raise FullApplyServiceError(f"artifact {artifact_id!r} size mismatch: expected {size} got {abs_p.stat().st_size} (tampered authority)")
    return {"artifact_id": artifact_id, "rel": rel, "sha256": sha, "size_bytes": size}


def _resolve_canonical_render_pins(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    apply_checkpoint_id: str,
    authority: dict[str, Any],
    managed_root: Path | None,
) -> dict[str, Any]:
    """Resolve + validate source and replacement asset pins from the v2 authority.

    C8: EVERY pin (source artifact, per-role pack asset, timebase) comes from
    the frozen ``full_apply_authority`` block — frozen ids/hashes/sizes only,
    never a client mapping and never a scan/guess.  Missing/tampered/
    cross-workspace/cross-project pins fail closed BEFORE enqueue.
    """
    from app.persistence.models import ApplyCheckpoint as _ApplyCheckpoint

    # 1) Source managed artifact — frozen in v2 authority source block.
    source = authority.get("source")
    if not isinstance(source, dict) or not source.get("source_artifact_id"):
        raise FullApplyServiceError("v2 authority has no frozen source artifact (missing authority)")
    src = _validate_managed_artifact(
        session,
        artifact_id=str(source["source_artifact_id"]),
        workspace_id=workspace_id,
        managed_root=managed_root,
    )

    # 2) Per-role replacement assets — frozen in v2 role_mappings.pack_assets.
    role_mappings = authority.get("role_mappings") or []
    if not role_mappings:
        raise FullApplyServiceError("v2 authority has no role mappings (missing replacement asset authority)")
    assets: dict[str, dict[str, Any]] = {}
    for rm in role_mappings:
        if not isinstance(rm, dict):
            raise FullApplyServiceError("v2 authority role mapping must be a dict (tampered)")
        role_id = rm.get("object_role_id")
        if not isinstance(role_id, str) or not role_id:
            raise FullApplyServiceError("v2 authority role mapping missing object_role_id (tampered)")
        pack_assets = rm.get("pack_assets") or []
        if not isinstance(pack_assets, list) or not pack_assets:
            raise FullApplyServiceError(f"v2 authority role {role_id!r} has no frozen pack assets (missing authority)")
        chosen = pack_assets[0]
        if not isinstance(chosen, dict) or not chosen.get("artifact_id"):
            raise FullApplyServiceError(f"v2 authority role {role_id!r} pack asset missing artifact_id (tampered)")
        assets[role_id] = _validate_managed_artifact(
            session,
            artifact_id=str(chosen["artifact_id"]),
            workspace_id=workspace_id,
            managed_root=managed_root,
        )

    # 3) Timebase fingerprint — frozen on the persisted checkpoint row.
    ckpt = session.get(_ApplyCheckpoint, apply_checkpoint_id)
    if ckpt is None or str(ckpt.workspace_id) != workspace_id or str(ckpt.project_id) != project_id:
        raise FullApplyServiceError(
            f"apply_checkpoint {apply_checkpoint_id!r} not found in workspace/project (missing authority)"
        )
    tbf = str(getattr(ckpt, "timebase_fingerprint", "") or "")
    if not tbf:
        raise FullApplyServiceError("checkpoint timebase_fingerprint missing (incomplete authority)")
    return {
        "source_media_artifact_id": src["artifact_id"],
        "source_media_rel": src["rel"],
        "source_media_sha256": src["sha256"],
        "source_media_size_bytes": src["size_bytes"],
        "replacement_assets": assets,
        "timebase_fingerprint": tbf,
    }




router = APIRouter(prefix="/api/v2", tags=["s10-full-apply"])


def _compensate_run_pending_to_failed(session: Any, run_id: str, workspace_id: str) -> None:
    """S10-C10 F1: CAS-compensate an orphan ``pending`` run after enqueue failure.

    A post-commit ``create_job`` failure leaves the run committed but with ZERO
    durable job — a ``pending`` orphan that no worker will ever claim.  The
    CAS (``WHERE status='pending'``) only flips a run that is still the orphan
    we created; any concurrent terminal transition is respected.  ``failed`` is
    a coherent non-claimable state (retry route accepts failed/cancelled).
    Raises on failure — never swallowed (fail-closed, mirrors _compensate_resume).
    """
    from sqlalchemy import text as _sa_text  # noqa: PLC0415

    session.execute(
        _sa_text(
            "UPDATE s10_full_apply_run SET status='failed', updated_at=CURRENT_TIMESTAMP "
            "WHERE id=:rid AND workspace_id=:ws AND status='pending'"
        ),
        {"rid": run_id, "ws": workspace_id},
    )
    session.commit()


def _s10_find_durable_job(job_service: Any, run_id: str) -> dict[str, Any] | None:
    """S10-C10 F1: return the durable job summary for ``s10_full_apply_job:{run_id}``.

    Used by replay submits to PROVE an exact durable job exists before the
    route may answer ``reused=true`` (a 200 with zero durable job is a false
    success — F1b in the C6C review).  Read-only; returns None when absent.
    C6D F2: the returned summary carries the FULL immutable identity (job_type,
    workspace, owner, idempotency key, parsed manifest) so the caller can
    canonical-compare it before any replay success, not merely test None-ness.
    """
    from sqlalchemy import select as _sel  # noqa: PLC0415

    from app.persistence.jobs import parse_json as _parse  # noqa: PLC0415
    from app.persistence.models import Job as _Job  # noqa: PLC0415

    factory = getattr(job_service, "session_factory", None)
    if factory is None:
        return None
    try:
        with factory() as jsess:
            job = jsess.scalar(_sel(_Job).where(_Job.idempotency_key == f"s10_full_apply_job:{run_id}"))
            if job is None:
                return None
            parsed = _parse(job.input_manifest_json, {}) if isinstance(job.input_manifest_json, str) else {}
            return {
                "id": str(job.id),
                "job_type": str(job.job_type or ""),
                "state": str(job.state),
                "workspace_id": str(job.workspace_id or ""),
                "owner_type": str(job.owner_type or ""),
                "owner_id": str(job.owner_id or ""),
                "idempotency_key": str(job.idempotency_key or ""),
                "input_generation": str(job.input_generation or ""),
                "manifest": parsed,
            }
    except Exception:
        # Read-only existence probe: a transient lookup error must not be
        # reported as "job exists" — treat as missing so the caller repairs
        # or fails closed instead of answering a false reused=true.
        return None


def _s10_resolve_job_identity(
    job_service: Any,
    rec: Any,
    *,
    workspace_id: str,
    project_id: str,
) -> dict[str, Any]:
    """C6H R1 (UNION_IDENTITY_RESOLVER_GAP fix): TYPED UNION durable-job identity
    resolver for a replay whose exact canonical-key lookup returned nothing
    (``_existing_job is None``).

    Candidate discovery is the UNION of INDEPENDENT durable identity signals —
    each signal is evaluated on its own and the results are merged (never
    collapsed onto a single field, and never trusting the request body):

      1. canonical idempotency key      ``s10_full_apply_job:{run_id}``
      2. deterministic input generation ``_s10_job_generation(run_id)``
      3. stored manifest run identity   ``input_manifest_json`` parsed with
         run_id + project_id + plan_id all matching the replayed run
      4. expected workspace / job_type / owner identity — the classification
         anchor that decides whether a sole claimant is the FULL canonical
         identity or carries one or more wrong canonical fields.

    The scan is deliberately NOT filtered by canonical prefix, job_type or
    key NOT NULL, so a row whose key, generation AND job_type are all tampered
    is still discovered through its immutable stored manifest — otherwise the
    tamper would manufacture a false ``true-zero`` and a second canonical job
    (Codex C6H repro: jobs 1 -> 2 with 200 reused=true).

    Returns a typed verdict whose ``cls`` is exactly one of:

      * ``true-zero``              — NO row claims the run under ANY signal.
                                     The ONLY class allowed to repair.
      * ``exact-valid-one``        — exactly ONE claimant carrying the FULL
                                     canonical identity.  Defensive (the
                                     key-only lookup should have found it);
                                     NEVER repair.
      * ``wrong-one``              — exactly ONE claimant with 1+ canonical
                                     field wrong (key/generation/workspace/
                                     job_type/owner/manifest identity).
      * ``ambiguous-multiple``     — TWO+ rows claim the run through ANY
                                     combination of signals.
      * ``read/parse/query-error`` — the scan raised, or a potential
                                     claimant's stored manifest is
                                     unparseable.  Identity is NOT safely
                                     determinable: fail closed and NEVER
                                     treat the error as a missing job.

    The caller MUST block repair for every class except ``true-zero``; a
    ``wrong-one`` / ``ambiguous-multiple`` / ``exact-valid-one`` /
    ``read/parse/query-error`` verdict can never silently produce a second
    canonical job or a false ``reused=true``.

    Read-only.  ``rows`` carries the full claimant summaries (id, job_type,
    workspace, owner, state, key, generation) for diagnostics; ``reason``
    carries the error text for ``read/parse/query-error``.
    """
    import json as _json  # noqa: PLC0415

    from sqlalchemy import or_ as _or  # noqa: PLC0415
    from sqlalchemy import select as _sel  # noqa: PLC0415

    from app.persistence.models import Job as _Job  # noqa: PLC0415
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY as _JOB_TYPE  # noqa: PLC0415

    factory = getattr(job_service, "session_factory", None)
    if factory is None:
        return {
            "cls": "read/parse/query-error",
            "rows": [],
            "reason": "job_service has no session_factory",
        }
    run_id = str(rec.id)
    canonical_key = f"s10_full_apply_job:{run_id}"
    # C6H R3 (FORMAT_INDEPENDENT_MANIFEST_IDENTITY): the stored-manifest
    # prefilter is ONE containment of the EXACT target run_id literal.  LIKE
    # wildcards (%, _, \) in the run_id are escaped and ESCAPE '\\' is set so
    # the containment stays literal; the pattern never enumerates JSON
    # whitespace variants, so compact/spaced/tab/newline formatting can never
    # erase durable run identity.
    run_id_literal = (
        run_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    try:
        expected_gen = _s10_job_generation(run_id)
    except Exception as err:  # noqa: BLE001 — identity helper error must fail closed
        return {"cls": "read/parse/query-error", "rows": [], "reason": f"{type(err).__name__}: {err}"}

    try:
        with factory() as jsess:
            rows = jsess.scalars(
                _sel(_Job).where(
                    _or(
                        _Job.idempotency_key == canonical_key,
                        _Job.input_generation == expected_gen,
                        # Stored-manifest prefilter: text CONTAINING the EXACT
                        # target run_id literal — representation-independent of
                        # JSON whitespace/pretty-print.  Exact run/project/plan
                        # identity is still validated on the parsed JSON below;
                        # unrelated malformed manifests without the target run
                        # must never become candidates.
                        _Job.input_manifest_json.like(f"%{run_id_literal}%", escape="\\"),
                    )
                )
            ).all()
    except Exception as err:  # noqa: BLE001 — read error must fail closed
        return {"cls": "read/parse/query-error", "rows": [], "reason": f"{type(err).__name__}: {err}"}

    def _summary(row: Any) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "job_type": str(row.job_type or ""),
            "state": str(row.state),
            "workspace_id": str(row.workspace_id or ""),
            "owner_type": str(row.owner_type or ""),
            "owner_id": str(row.owner_id or ""),
            "idempotency_key": str(row.idempotency_key or ""),
            "input_generation": str(row.input_generation or ""),
        }

    expected_plan_id = str(getattr(rec, "plan_id", "") or "")

    claims: list[Any] = []
    manifest_parse_errors: list[str] = []
    for row in rows:
        sig_key = str(row.idempotency_key or "") == canonical_key
        sig_gen = row.input_generation is not None and str(row.input_generation) == expected_gen
        sig_manifest = False
        manifest_raw = row.input_manifest_json
        if isinstance(manifest_raw, str):
            try:
                parsed_manifest = _json.loads(manifest_raw)
            except Exception as err:  # noqa: BLE001 — unparseable manifest = broken identity
                parsed_manifest = None
                manifest_parse_errors.append(f"job {row.id}: {type(err).__name__}: {err}")
            if isinstance(parsed_manifest, dict):
                sig_manifest = (
                    str(parsed_manifest.get("run_id") or "") == run_id
                    and str(parsed_manifest.get("project_id") or "") == str(project_id)
                    and str(parsed_manifest.get("plan_id") or "") == expected_plan_id
                )
        if sig_key or sig_gen or sig_manifest:
            claims.append(row)

    # A potential claimant whose stored manifest cannot be parsed makes the
    # identity NOT safely determinable — fail closed; the caller must never
    # turn this into a repairable missing-job path.
    if manifest_parse_errors:
        return {
            "cls": "read/parse/query-error",
            "rows": [_summary(r) for r in rows],
            "reason": f"stored manifest unparseable for {', '.join(manifest_parse_errors)}",
        }

    if len(claims) == 0:
        return {"cls": "true-zero", "rows": [], "reason": None}

    if len(claims) == 1:
        row = claims[0]
        # C6H R2 F2 (PER_ROW_SIGNAL): recompute the manifest signal FROM THIS
        # ROW — never reuse the loop-leftover ``sig_manifest`` variable, which
        # may belong to the last scanned row instead of the claimant being
        # classified.  Parse errors already failed closed above, so this
        # recompute is exact for the claimant's own stored manifest.
        row_sig_manifest = False
        row_manifest_raw = row.input_manifest_json
        if isinstance(row_manifest_raw, str):
            try:
                row_manifest = _json.loads(row_manifest_raw)
            except Exception:  # noqa: BLE001 — unreachable after parse-error gate
                row_manifest = None
            if isinstance(row_manifest, dict):
                row_sig_manifest = (
                    str(row_manifest.get("run_id") or "") == run_id
                    and str(row_manifest.get("project_id") or "") == str(project_id)
                    and str(row_manifest.get("plan_id") or "") == expected_plan_id
                )
        canonical_complete = (
            str(row.idempotency_key or "") == canonical_key
            and row.input_generation is not None
            and str(row.input_generation) == expected_gen
            and str(row.workspace_id or "") == str(workspace_id)
            and str(row.job_type or "") == _JOB_TYPE
            and str(row.owner_type or "") == "project"
            and str(row.owner_id or "") == str(project_id)
            and row_sig_manifest
        )
        if canonical_complete:
            return {"cls": "exact-valid-one", "rows": [_summary(row)], "reason": None}
        return {"cls": "wrong-one", "rows": [_summary(row)], "reason": None}

    return {"cls": "ambiguous-multiple", "rows": [_summary(r) for r in claims], "reason": None}


def _s10_repair_missing_submit_job(
    job_service: Any,
    *,
    rec: Any,
    workspace_id: str,
    project_id: str,
    manifest: dict[str, Any],
) -> str:
    """S10-C10 F1: atomically repair the exact durable job for a replayed run.

    A historical replayed run can lack its durable job (crashed/orphaned
    enqueue).  The repair creates the job under the SAME deterministic
    idempotency key ``s10_full_apply_job:{run_id}`` — never a duplicate — with
    the immutable manifest identity re-derived from the persisted run row and
    (when available) the re-resolved canonical authority pins.  The manifest
    is built/validated by the caller (C6D F1/F2) so the run transition and this
    enqueue are one coherent, compensated sequence.  Raises on failure; caller
    surfaces an HTTP error (fail-closed, no false 200).
    """
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY  # noqa: PLC0415

    job_service.create_job(
        JOB_TYPE_S10_FULL_APPLY,
        manifest,
        workspace_id=workspace_id,
        owner_type="project",
        owner_id=project_id,
        idempotency_key=f"s10_full_apply_job:{rec.id}",
        # C6E F1: deterministic non-NULL generation derived from the run — the
        # unique index must treat concurrent same-identity repairs as a
        # collision (SQLite sees NULL generations as distinct and lets both
        # through, which is the C6D duplicate-job hole).
        input_generation=_s10_job_generation(str(rec.id)),
    )
    return f"s10_full_apply_job:{rec.id}"


# ── S10-T01C-C12/C6E: complete immutable job identity + lifecycle truth ──────
#
# Lifecycle matrix (run status x durable job state) that a replay-related
# handler may return 200/202/reused=true for.  Anything outside the matrix —
# and especially a TERMINAL run paired with an ACTIVE job — FAILS CLOSED
# (409/422) with zero mutation and never answers ``reused=true``.
#
#  run status        | durable job state               | verdict
#  ------------------|---------------------------------|--------------------------------
#  pending/running/  | queued/running                  | ACTIVE legitimate       -> reuse
#  verifying         |                                 |
#  failed            | queued/running                  | REPAIR heal (exact case)-> reuse, caller reopens run to pending
#  failed/completed/ | completed/failed/cancelled/     | TERMINAL legitimate     -> reuse
#  cancelled         | fenced                          |
#  cancelled         | cancelling                      | teardown legitimate     -> reuse
#  ANY terminal run  | queued/running/pending          | TERMINAL/ACTIVE CONTRADICTION -> FAIL CLOSED (409)
#   (completed/      |                                 |
#    cancelled)      |                                 |
#
# ``failed + queued/running`` is the ONLY active-job case that is healed, and
# only after full immutable identity validation — never a bare swallowed reuse.

#: Run statuses that mean the lineage still has active work.
_S10_ACTIVE_RUN_STATES = frozenset({"pending", "running", "verifying"})
#: Terminal (non-active-claimable) run statuses.
_S10_TERMINAL_RUN_STATES = frozenset({"failed", "completed", "cancelled"})
#: Durable job states that represent claimable / in-flight active work.
_S10_ACTIVE_JOB_STATES = frozenset({"queued", "running", "pending"})
#: Durable job states that represent a settled / terminal result.
_S10_TERMINAL_JOB_STATES = frozenset({"completed", "failed", "cancelled", "fenced"})
#: Durable job state that means the job is being torn down (run must be terminal).
_S10_TEARDOWN_JOB_STATES = frozenset({"cancelling"})


def _s10_job_generation(run_id: str) -> str:
    """Deterministic, non-NULL ``input_generation`` derived server-side from the run.

    The durable unique index ``uq_job_idempotency_key`` is on
    ``(workspace_id, idempotency_key, input_generation)`` with a partial
    predicate of ``state NOT IN ('failed','cancelled')``.  SQLite treats NULL
    generations as DISTINCT in a unique index, which is exactly why the C6D
    read-then-create race escaped the backstop (both S10 calls left the
    generation NULL and both INSERTs succeeded).  Every S10 job-creation path
    (submit, repair/replay, retry, resume) that may race on the same job
    identity derives the SAME deterministic non-NULL generation from the run
    id so the backstop actually fires and the loser converges on the winner.
    """
    raw = f"s10:{run_id}"
    if len(raw) <= 64:
        return raw
    import hashlib as _hl  # noqa: PLC0415

    return _hl.sha256(raw.encode()).hexdigest()


def _canonical_manifest_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    """C6E F3: the COMPLETE immutable canonical identity of a job manifest.

    Unlike the C6D whitelist, this is the FULL key set — including the
    server-injected framework defaults ``schema_version`` / ``managed_root`` /
    ``project_root`` and every render-authority pin.  Comparing two of these
    with ``!=`` is order-insensitive and nested-deep, and any missing, extra
    or mutated field makes the canonical dicts differ, so the caller fails
    closed.  A non-dict manifest returns a sentinel that never equals a real
    identity (malformed input is rejected).
    """
    if not isinstance(manifest, dict):
        return {"__invalid_manifest__": True}
    # A shallow copy + ``!=`` gives exactly the required semantics: full key
    # set equality (order-insensitive at every nesting level) and deep value
    # equality.  No key is excluded, so an immutable-field mutation, an added
    # key or a removed key all fail the compare.
    return dict(manifest)


def _build_submit_manifest(
    rec: Any,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    apply_checkpoint_id: str,
    plan: dict[str, Any],
    authority_pins: dict[str, Any],
    job_service: Any,
) -> dict[str, Any]:
    """C6D F1/F2 + C6E F3: the single canonical submit/repair job manifest.

    Reflects EXACTLY what the ``if created:`` branch enqueues (server-derived
    render authority + frozen authority pins + the framework defaults that
    ``JobService.create_job`` durably injects: ``schema_version``,
    ``managed_root``, ``project_root``), so a replay can re-derive the
    expected manifest and compare it against the stored durable job with the
    COMPLETE immutable identity (no whitelist cutoff — a changed
    ``project_root`` or ``schema_version`` now fails closed).
    """
    from app.workflow.job_service import _project_root  # noqa: PLC0415

    managed_root = str(job_service.managed_root) if hasattr(job_service, "managed_root") else ""
    manifest: dict[str, Any] = {
        "run_id": rec.id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "video_item_id": video_item_id,
        "apply_checkpoint_id": apply_checkpoint_id,
        "plan_id": rec.plan_id,
        "plan_hash": rec.plan_hash,
        "managed_root": managed_root,
        "render_authority": plan["render_authority"],
        # C6E F3: mirror the server defaults JobService.create_job injects so
        # the re-derived expected manifest has the SAME full key set as the
        # stored durable manifest (strict comparison, no allow/ignore list).
        "schema_version": 1,
        "project_root": str(_project_root()),
    }
    manifest.update(authority_pins)
    return manifest


#: The full valid status set of ``s10_full_apply_run.status`` — the CAS helper
#: only ever binds values from this whitelist (never string-interpolates).
_S10_VALID_RUN_STATUSES = frozenset({"failed", "pending", "running", "verifying", "completed", "cancelled"})


def _s10_cas_run_status(
    session: Session,
    run_id: str,
    workspace_id: str,
    *,
    from_statuses: tuple[str, ...],
    to_status: str,
) -> bool:
    """C6F: compare-and-swap a run row's status, returning True iff WE won.

    The ``UPDATE`` is gated on ``status IN :from_statuses`` so it is a true CAS:
    under SQLite's single-writer serialisation, exactly ONE of two mutually
    exclusive claims on the same run row wins (replay-repair ``failed ->
    pending`` vs Retry-claim ``failed/cancelled -> cancelled``).  ``rowcount == 1``
    means this caller claimed the row and may proceed to create a job/successor;
    ``rowcount == 0`` means an opponent already transitioned it — the caller MUST
    fail closed (409) with ZERO new job/successor.  Only whitelisted statuses are
    ever bound as parameters.
    """
    from sqlalchemy import text as _sa_text  # noqa: PLC0415

    if not set(from_statuses) <= _S10_VALID_RUN_STATUSES or to_status not in _S10_VALID_RUN_STATUSES:
        raise ValueError(f"invalid run-status CAS: from={from_statuses!r} to={to_status!r}")
    placeholders = ", ".join(f":s{i}" for i in range(len(from_statuses)))
    params: dict[str, object] = {f"s{i}": st for i, st in enumerate(from_statuses)}
    params.update({"rid": run_id, "ws": workspace_id, "to": to_status})
    result = session.execute(
        _sa_text(
            "UPDATE s10_full_apply_run SET status=:to, updated_at=CURRENT_TIMESTAMP "
            f"WHERE id=:rid AND workspace_id=:ws AND status IN ({placeholders})"
        ),
        params,
    )
    session.commit()
    # A Core DML UPDATE returns a ``CursorResult`` with a real ``rowcount``; the
    # Session.execute stub types it as ``Result`` (no rowcount), so narrow it.
    from sqlalchemy.engine import CursorResult  # noqa: PLC0415

    rowcount: int = result.rowcount if isinstance(result, CursorResult) else 0
    return rowcount == 1


def _s10_retry_claim_predecessor(session: Session, run_id: str, workspace_id: str) -> bool:
    """C6G F2/G2-R1: CAS-claim an ACTIVE-retryable predecessor BEFORE a Retry.

    Only a REAL transition ``failed -> cancelled`` (the S10 convention for
    "superseded — no longer the canonical attempt") is ownership.  This is
    mutually exclusive with the replay-repair CAS (``failed -> pending``) on the
    same row, so a truly simultaneous Replay(R1) || Retry(R1) on a FAILED
    predecessor can never yield TWO active canonical work items: the loser sees
    ``rowcount == 0`` and must fail closed (409) BEFORE creating any successor
    run or job.

    CRITICAL (G2-R1): a ``cancelled -> cancelled`` transition is a SAME-STATE
    NO-OP, NOT ownership.  The row is ALREADY cancelled; flipping it to
    ``cancelled`` changes nothing yet the old code reported ``rowcount == 1`` so
    two callers both "won" (the exclusive-claim defect).  This helper now returns
    True ONLY when the CAS actually transitioned a row it still owned — a
    FATAL no-op on an already-cancelled predecessor returns False.  For a TRUE
    exclusive-claim on a cancelled predecessor, ownership is decided by the
    ATOMIC unique-successor insertion (caller-side, via the unique
    ``uq_s10_run_natural`` backstop on ``s10_retry:{run_id}:{attempt}``), not by
    a same-state no-op — see ``retry_full_apply``.
    """
    return _s10_cas_run_status(
        session,
        run_id,
        workspace_id,
        from_statuses=("failed",),
        to_status="cancelled",
    )


def _restore_run_to_pending(session: Session, run_id: str, workspace_id: str) -> bool:
    """C6D F1: CAS-reopen a compensated ``failed`` run to ``pending``.

    Only ``failed`` (the compensation state after an enqueue failure) is
    reopened; an already-active run (pending/running/verifying) is left alone,
    and a terminal completed/cancelled state is never regressed.  The guard
    ``WHERE status='failed'`` makes the transition a compare-and-swap so a
    concurrent repair/retry cannot double-reopen.

    Returns True when this caller won the reopen (``failed -> pending``); False
    when the row was already claimed — either a concurrent identical repair/
    replay reopened it, or a Retry superseded it to ``cancelled``.  The caller
    must then converge (concurrent identical replay) or fail closed (superseded).
    """
    return _s10_cas_run_status(
        session,
        run_id,
        workspace_id,
        from_statuses=("failed",),
        to_status="pending",
    )


def _s10_predecessor_has_active_job(job_service: Any, run_id: str) -> bool:
    """C6D F1: True when the durable job for ``run_id`` is ACTIVE claimable work.

    Only ``queued``/``running`` block a retry — a ``cancelling`` job is being
    torn down (its run is terminal cancelled), so retrying that lineage is
    legitimate.  This is the single-canonical-work barrier: a lineage holding a
    genuinely claimable/running job must not spawn a competing successor.
    """
    job = _s10_find_durable_job(job_service, str(run_id))
    return job is not None and str(job.get("state") or "") in ("queued", "running")


def _s10_lineage_has_newer_active_attempt(session: Session, rec: Any, workspace_id: str) -> bool:
    """C6E F1: True when the SAME lineage already holds a NEWER active attempt
    (attempt > ``rec.attempt``, run status ``pending/running/verifying``).

    Detects BOTH lineage notions:
    * content-lineage — a run with the SAME ``natural_key`` as ``rec`` and a
      higher attempt;
    * retry-lineage — a run whose ``natural_key`` is ``s10_retry:<rec.id>:<n>``,
      i.e. a Retry successor OF ``rec`` itself (the retry supersedes the failed
      predecessor; ``rec`` is no longer the canonical attempt).

    A replay-repair must NEVER reactivate ``rec`` when this returns True:
    restoring the older run to ``pending`` on top of a newer active attempt
    would create a SECOND active canonical work item on the lineage.  When
    True the caller must fail closed instead of repairing.
    """
    from sqlalchemy import select as _sel  # noqa: PLC0415

    from app.persistence.models import S10FullApplyRun as _Run  # noqa: PLC0415

    rec_id = str(getattr(rec, "id", "") or "")
    natural_key = str(getattr(rec, "natural_key", "") or "")
    rec_attempt = int(getattr(rec, "attempt", 0) or 0)
    active = ("pending", "running", "verifying")
    # (a) content-lineage: same natural_key, higher attempt, active.
    if natural_key:
        newer = session.scalar(
            _sel(_Run.id)
            .where(
                _Run.workspace_id == workspace_id,
                _Run.natural_key == natural_key,
                _Run.attempt > rec_attempt,
                _Run.status.in_(active),
            )
            .limit(1)
        )
        if newer is not None:
            return True
    # (b) retry-lineage: a Retry successor OF rec — RetryService writes
    # ``s10_retry:<predecessor_run_id>:<attempt>`` as its natural_key, so the
    # run id of the failed predecessor is embedded in the successor's key.
    if rec_id:
        descendant = session.scalar(
            _sel(_Run.id)
            .where(
                _Run.workspace_id == workspace_id,
                _Run.natural_key.like(f"s10_retry:{rec_id}:%"),
                _Run.status.in_(active),
            )
            .limit(1)
        )
        if descendant is not None:
            return True
    return False


def _validate_replay_durable_job(
    stored: dict[str, Any],
    *,
    expected_manifest: dict[str, Any],
    rec: Any,
    project_id: str,
    workspace_id: str,
) -> None:
    """C6D F2 + C6E F2/F3: complete immutable identity + lifecycle validation.

    Fail closed (409/422) on: wrong job_type, wrong idempotency key, wrong
    workspace / cross-project owner, wrong deterministic generation, a
    missing/malformed/tampered manifest, a manifest whose COMPLETE canonical
    identity does not exactly match the re-derived expected manifest (full key
    set + nested values — no whitelist cutoff), or a run-status/job-state pair
    outside the lifecycle matrix — notably a TERMINAL run paired with an
    ACTIVE job (``cancelled+queued``, ``completed+running``, ...), which must
    never answer ``reused=true``.  Never trusts the client body; never answers
    reused=true on mismatch.
    """
    from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY  # noqa: PLC0415

    job_type = str(stored.get("job_type") or "")
    if job_type != JOB_TYPE_S10_FULL_APPLY:
        raise S10ApplyConflictError(
            f"durable job for run {rec.id!r} has wrong job_type {job_type!r} (expected {JOB_TYPE_S10_FULL_APPLY!r})"
        )
    if str(stored.get("idempotency_key") or "") != f"s10_full_apply_job:{rec.id}":
        raise S10ApplyConflictError(f"durable job idempotency key does not match run identity {rec.id!r}")
    if str(stored.get("workspace_id") or "") != workspace_id:
        raise S10ApplyConflictError("durable job bound to a different workspace")
    if str(stored.get("owner_type") or "") != "project" or str(stored.get("owner_id") or "") != project_id:
        raise S10ApplyConflictError(
            f"durable job cross-owner: owner {stored.get('owner_type')!r}/{stored.get('owner_id')!r} "
            f"!= project {project_id!r}"
        )
    # C6E F1: the deterministic generation is part of the immutable job
    # identity — a job on the run key carrying a different (or NULL) generation
    # is not the same canonical work item and must fail closed.
    expected_gen = _s10_job_generation(str(rec.id))
    if str(stored.get("input_generation") or "") != expected_gen:
        raise S10ApplyConflictError(
            f"durable job input_generation {stored.get('input_generation')!r} "
            f"!= deterministic generation {expected_gen!r} for run {rec.id!r}"
        )
    stored_manifest = stored.get("manifest")
    if not isinstance(stored_manifest, dict):
        raise FullApplyServiceError("durable job input_manifest_json unparseable/missing (tampered)")
    expected_ident = _canonical_manifest_identity(expected_manifest)
    stored_ident = _canonical_manifest_identity(stored_manifest)
    if stored_ident != expected_ident:
        raise FullApplyServiceError(
            "durable job immutable manifest identity mismatch vs re-derived canonical manifest "
            "(tampered/missing/extra immutable field)"
        )
    # C6E F2: lifecycle matrix — the run-status/job-state pair must be one the
    # replay logic is allowed to answer reused=true for.
    _validate_replay_lifecycle(rec, stored)


def _validate_replay_lifecycle(rec: Any, stored: dict[str, Any]) -> None:
    """C6E F2: enforce the explicit run-status x job-state lifecycle matrix.

    Allowed pairs (any other combination FAILS CLOSED with zero mutation, never
    ``reused=true``):

    * ACTIVE legitimate   — run ``pending/running/verifying`` + job ``queued/running``
    * REPAIR heal         — run ``failed`` + job ``queued/running`` (only the exact
      repair case; the caller reopens the run to ``pending`` AFTER identity validation)
    * TERMINAL legitimate — run ``failed/completed/cancelled`` + job ``completed/failed/cancelled/fenced``
    * TEARDOWN legitimate — run ``cancelled`` + job ``cancelling``

    Notably ``cancelled + queued`` and ``completed + running`` (a terminal run
    carrying an ACTIVE durable job) are terminal/active contradictions and are
    rejected, so a replay can never surface a false ``reused=true`` on a
    corrupted or half-cancelled lineage.
    """
    run_status = str(getattr(rec, "status", "") or "")
    job_state = str(stored.get("state") or "")

    if run_status in _S10_ACTIVE_RUN_STATES and job_state in _S10_ACTIVE_JOB_STATES:
        return  # active legitimate
    if run_status == "failed" and job_state in _S10_ACTIVE_JOB_STATES:
        return  # repair heal (exact case) — caller reopens the run
    if run_status in _S10_TERMINAL_RUN_STATES and job_state in _S10_TERMINAL_JOB_STATES:
        return  # terminal legitimate
    if run_status == "cancelled" and job_state in _S10_TEARDOWN_JOB_STATES:
        return  # teardown legitimate
    raise S10ApplyConflictError(
        f"lifecycle contradiction for run {rec.id!r}: run status {run_status!r} "
        f"with durable job state {job_state!r} is not an allowed pair "
        f"(terminal run + active job is rejected; fail closed, no mutation)"
    )


def _s10_ensure_run_coherent(session: Session, rec: Any, job_state: str, workspace_id: str) -> None:
    """C6D F1: heal a run whose durable job is active so the pair is coherent.

    A ``failed`` run with a queued/running/cancelling job is the exact F1
    incoherence; CAS-reopen it to ``pending`` and refresh ``rec`` so the caller
    reads the truthful active state (the identity was already validated).  A
    terminal completed/cancelled run is never regressed — an active durable job
    paired with a terminal run is a genuine corruption and is surfaced by the
    identity/lifecycle caller, not silently overwritten here.
    """
    run_status = str(getattr(rec, "status", "") or "")
    if job_state in ("queued", "running") and run_status == "failed":
        _restore_run_to_pending(session, str(rec.id), workspace_id)

WORKSPACE_ID = DEFAULT_WORKSPACE_ID


# ── Schemas ───────────────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubmitFullApplyRequest(_Strict):
    video_item_id: str = Field(min_length=1)
    apply_checkpoint_id: str = Field(min_length=1)
    expected_checkpoint_hash: str = Field(min_length=64, max_length=64)
    expected_checkpoint_revision: int = Field(ge=1)
    # Legacy authority fields — OPTIONAL for compatibility only.  When present
    # the server canonical-compares every field against the frozen v2
    # authority; mismatch fails closed BEFORE any run/job/publication.  The
    # server NEVER prefers or merges client authority.
    approved_checkpoint: dict[str, Any] | None = None
    structural_lock_manifest: dict[str, Any] | None = None
    scene_manifest: dict[str, Any] | list[dict[str, Any]] | None = None
    mapping: dict[str, Any] | list[dict[str, Any]] | None = None
    compatibility_policy: dict[str, Any] | None = None
    chunk_config: dict[str, Any] | None = None
    chunk_frames: int | None = Field(default=None, ge=1)
    overlap_frames: int | None = Field(default=None, ge=0)
    fps_num: int | None = Field(default=None, ge=1)
    fps_den: int | None = Field(default=None, ge=1)
    idempotency_key: str | None = Field(default=None, max_length=255)
    natural_key: str | None = Field(default=None, max_length=255)


class SubmitFullApplyResponse(BaseModel):
    run_id: str
    workspace_id: str
    project_id: str
    status: str
    created: bool
    plan_id: str
    plan_hash: str
    frame_count: int
    reused: bool = False


class FullApplyStatusResponse(BaseModel):
    run_id: str
    workspace_id: str
    project_id: str
    video_item_id: str
    apply_checkpoint_id: str
    apply_checkpoint_hash: str
    apply_checkpoint_revision: int
    plan_id: str
    plan_hash: str
    status: str
    frame_count: int
    attempt: int
    natural_key: str | None
    idempotency_key: str | None
    chunks: list[dict[str, Any]]
    publications: list[dict[str, Any]]
    checkpoint: dict[str, Any] | None = None


# ── Helpers ───────────────────────────────────────────────────────────────


def _service(session: Session) -> FullApplyService:
    return FullApplyService(session)


def _err_status(err: Exception) -> int:
    if isinstance(err, S10ApplyNotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(err, (S10ApplyConflictError, S10ApplyOwnershipError)):
        return status.HTTP_409_CONFLICT
    if isinstance(err, (S10ApplyParamsError, S10ApplyCheckpointStaleError, FullApplyServiceError)):
        return status.HTTP_422_UNPROCESSABLE_ENTITY
    return status.HTTP_500_INTERNAL_SERVER_ERROR


# ── Routes ────────────────────────────────────────────────────────────────


@router.post("/projects/{project_id}/full-apply", status_code=status.HTTP_202_ACCEPTED)
def submit_full_apply(
    project_id: str,
    body: SubmitFullApplyRequest,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
) -> Any:
    svc = _service(session)
    try:
        rec, created, plan = svc.submit(
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=body.video_item_id,
            apply_checkpoint_id=body.apply_checkpoint_id,
            expected_checkpoint_hash=body.expected_checkpoint_hash,
            expected_checkpoint_revision=body.expected_checkpoint_revision,
            approved_checkpoint=dict(body.approved_checkpoint) if body.approved_checkpoint is not None else None,
            structural_lock_manifest=dict(body.structural_lock_manifest) if body.structural_lock_manifest is not None else None,
            scene_manifest=body.scene_manifest,
            mapping=body.mapping,
            compatibility_policy=dict(body.compatibility_policy) if body.compatibility_policy is not None else None,
            chunk_config=dict(body.chunk_config) if body.chunk_config is not None else None,
            chunk_frames=body.chunk_frames,
            overlap_frames=body.overlap_frames,
            fps_num=body.fps_num,
            fps_den=body.fps_den,
            idempotency_key=body.idempotency_key,
            natural_key=body.natural_key,
        )
    except (S10ApplyNotFoundError, S10ApplyConflictError, S10ApplyOwnershipError, S10ApplyParamsError, S10ApplyCheckpointStaleError, FullApplyServiceError) as err:
        session.rollback()
        raise HTTPException(status_code=_err_status(err), detail=str(err)) from err
    except Exception:
        session.rollback()
        raise
    if created:
        # C8: resolve + validate the canonical render pins (source artifact +
        # per-role replacement assets) EXCLUSIVELY from the frozen v2
        # authority BEFORE commit / enqueue.  The server pins the ORIGINAL
        # managed source artifact and exact replacement pack/version/asset
        # identities from the v2 authority block (frozen ids/hashes/sizes) —
        # never a client mapping.  Missing, tampered, cross-workspace or
        # cross-project authority raises here — the run row is rolled back (no
        # orphan run) and the job is NEVER created, so no render can start.
        job_service = get_job_service()
        _mr_submit = job_service.managed_root if hasattr(job_service, "managed_root") else None
        try:
            from app.services.s09_approval import S09ApprovalRepository as _S09Repo

            _authority = _S09Repo(session).full_apply_authority(
                body.apply_checkpoint_id, workspace_id
            )
            _authority_pins = _resolve_canonical_render_pins(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=body.video_item_id,
                apply_checkpoint_id=body.apply_checkpoint_id,
                authority=_authority,
                managed_root=Path(_mr_submit) if _mr_submit else None,
            )
        except FullApplyServiceError as err:
            session.rollback()
            raise HTTPException(status_code=_err_status(err), detail=str(err)) from err
        # render_authority is the CANONICAL SERVER authority produced by the
        # service from the frozen v2 checkpoint — NOT a client body echo.  The
        # worker re-derives the authority fingerprint from the persisted v2
        # row and verifies plan/authority pins before any render.
        # C6D: single canonical manifest builder (server-derived render
        # authority + frozen authority pins) — identical shape to the manifest
        # a replay re-derives for validation, so identity compares are sound.
        manifest: dict[str, Any] = _build_submit_manifest(
            rec,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=body.video_item_id,
            apply_checkpoint_id=body.apply_checkpoint_id,
            plan=plan,
            authority_pins=_authority_pins,
            job_service=job_service,
        )
        # Commit only on creation; replays rollback (existing row already committed)
        # CORRECTION 2 P0: commit run BEFORE opening a second SQLite writer
        # connection for create_job — avoids whole-DB busy lock ("database is
        # locked" 5s timeout) that the inner broad except would swallow.
        # Pattern mirrors retry_full_apply (commit-then-enqueue in separate tx),
        # immediately after register_attach_original_audio_handler precedent.
        try:
            session.commit()
        except Exception as err:
            session.rollback()
            raise HTTPException(status_code=500, detail=f"full-apply commit failed: {err}") from err
        # Enqueue durable worker job outside request — thin durable row
        # The worker executes chunks and checkpoints asynchronously.
        # Now in a separate transaction/connection (commit released the lock).
        try:
            from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY  # noqa: PLC0415  # isort: skip
            from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

            # Use a deterministic idempotency for the job so a replay submit
            # does not enqueue a duplicate worker job when the run was deduped.
            job_key = f"s10_full_apply_job:{rec.id}"
            try:
                job_service.create_job(
                    JOB_TYPE_S10_FULL_APPLY,
                    manifest,
                    workspace_id=workspace_id,
                    owner_type="project",
                    owner_id=project_id,
                    idempotency_key=job_key,
                    # C6E F1: deterministic non-NULL generation derived from the
                    # run so the unique backstop serializes a concurrent
                    # identical submit/replay for the SAME job identity.
                    input_generation=_s10_job_generation(str(rec.id)),
                )
            except (S10ApplyConflictError, IntegrityError) as dup_err:
                # Job idempotency — duplicate idempotency_key for the same run
                # is the ONLY swallowable case (replay submit). Log, do not hide.
                import logging  # noqa: PLC0415

                logging.getLogger(__name__).warning(
                    "s10_full_apply job deduped for run %s: %s", rec.id, dup_err
                )
            except Exception as err:
                # S10-C10 F1: non-idempotent enqueue failure after the run was
                # already committed would strand a ``pending`` orphan with ZERO
                # durable job — compensate the run to a coherent non-claimable
                # ``failed`` state BEFORE surfacing the failure (fail-closed,
                # never swallowed; compensation failure propagates as-is).
                try:
                    _compensate_run_pending_to_failed(session, str(rec.id), workspace_id)
                except Exception as comp_err:
                    raise HTTPException(
                        status_code=500,
                        detail=f"full-apply enqueue failed: {err}; compensation failed: {comp_err}",
                    ) from comp_err
                raise
        except HTTPException:
            raise
        except Exception as err:
            # Preserve committed run; surface enqueue failure distinctly so
            # monitor/checkpoint never silently stalls on swallowed busy error.
            raise HTTPException(status_code=500, detail=f"full-apply enqueue failed: {err}") from err
    else:
        session.rollback()
        # S10-C10 F1 req 2 + C6D F1/F2: a replay dedupe may NEVER answer
        # 200 reused=true while the exact durable job is missing (historical
        # orphan), and must NEVER reuse a tampered / cross-owner / wrong-type /
        # wrong-manifest durable job.  Re-resolve the canonical authority +
        # pins server-side, then either (a) repair the exact job AND restore the
        # run to a coherent ACTIVE state (never run=failed + job=queued), or
        # (b) canonical-compare the stored durable job's immutable identity
        # before any success — never trusting the client body.
        _js = get_job_service()
        _existing_job = _s10_find_durable_job(_js, str(rec.id))
        try:
            from app.services.s09_approval import S09ApprovalRepository as _S09Repo

            _mr = _js.managed_root if hasattr(_js, "managed_root") else None
            _authority = _S09Repo(session).full_apply_authority(
                rec.apply_checkpoint_id, workspace_id
            )
            _pins = _resolve_canonical_render_pins(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=body.video_item_id,
                apply_checkpoint_id=rec.apply_checkpoint_id,
                authority=_authority,
                managed_root=Path(_mr) if _mr else None,
            )
        except FullApplyServiceError as err:
            raise HTTPException(status_code=_err_status(err), detail=str(err)) from err
        _expected_manifest = _build_submit_manifest(
            rec,
            workspace_id=workspace_id,
            project_id=project_id,
            video_item_id=body.video_item_id,
            apply_checkpoint_id=rec.apply_checkpoint_id,
            plan=plan,
            authority_pins=_pins,
            job_service=_js,
        )
        if _existing_job is None:
            # C6G F1/G1: a durable row that CLAIMS the run identity (same
            # deterministic input_generation) but carries a NON-CANONICAL key is
            # INVISIBLE to the key-only lookup above, so a naive "true orphan"
            # repair would create a SECOND canonical job and answer a false
            # reused=true.  The typed resolver classifies the candidates; ONLY
            # ``zero-candidates`` (a genuine orphan) is allowed to repair.  Any
            # wrong-key claimant — a single one (wrong-1) or two+ ambiguous ones
            # (multiple-ambiguous), the exact-1 defensive guard, or a read/parse
            # error (query-error) — FAILS CLOSED (409) with ZERO mutation; never
            # a len==1/None-for-ambiguity shortcut, never a prefix-only filter.
            _identity = _s10_resolve_job_identity(
                _js,
                rec,
                workspace_id=workspace_id,
                project_id=project_id,
            )
            if _identity["cls"] != "true-zero":
                session.rollback()
                if _identity["cls"] == "read/parse/query-error":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"run {rec.id!r} durable-job identity lookup FAILED "
                            f"({_identity.get('reason')}); replay rejected (fail-closed, no repair)"
                        ),
                    )
                _claimant_keys = [r["idempotency_key"] for r in _identity["rows"]]
                _class_msg = {
                    "wrong-one": "a wrong-identity claimant",
                    "ambiguous-multiple": "multiple ambiguous claimants across identity signals",
                    "exact-valid-one": "a row already carrying the exact canonical identity",
                }.get(_identity["cls"], "an unexpected claimant class")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"run {rec.id!r} has a durable job bound to its identity via "
                        f"{_class_msg} (keys={_claimant_keys!r}); replay rejected "
                        "(no repair over a same-identity claimant)"
                    ),
                )
            # F1 repair: restore the run to a coherent ACTIVE state and create
            # the exact durable job in one compensated sequence.  The run is
            # reopened BEFORE enqueue so we never transiently expose
            # run=failed + job=queued; if enqueue fails we re-compensate the
            # run to failed (coherent non-claimable, no false success).
            from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

            from app.persistence.jobs import IdempotencyKeyInUse as _IdemInUse  # noqa: PLC0415

            # C6E F1 point 4 (replay-vs-retry): a replay-repair must NEVER
            # reactivate a run that a concurrent Retry already superseded with a
            # NEWER active attempt.  Reopening this older run to ``pending`` on
            # top of a newer active attempt would leave TWO active canonical work
            # items on the lineage.  Fail closed (409) with zero mutation.
            if _s10_lineage_has_newer_active_attempt(session, rec, workspace_id):
                session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"run {rec.id!r} was superseded by a newer active retry attempt; "
                        "replay-repair rejected (no second active canonical work on lineage)"
                    ),
                )
            reopened = _restore_run_to_pending(session, str(rec.id), workspace_id)
            if not reopened:
                # C6F: the replay-repair CAS lost.  Two possibilities:
                #   * a concurrent Retry superseded this run to ``cancelled`` —
                #     we must NOT heal a superseded run (that would create a
                #     second active canonical work item); fail closed (409).
                #   * a concurrent identical replay already reopened it to
                #     ``pending`` — converge via the idempotency backstop below.
                if rec_status(session, str(rec.id), workspace_id) == "cancelled":
                    session.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"run {rec.id!r} was superseded by a concurrent retry; "
                            "replay-repair rejected (no second active canonical work on lineage)"
                        ),
                    )
            try:
                _s10_repair_missing_submit_job(
                    _js,
                    rec=rec,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    manifest=_expected_manifest,
                )
            except (_IdemInUse, IntegrityError):
                # C6E F1: a concurrent identical replay already created the job.
                # This is a STABLE idempotency-domain collision (the unique
                # backstop fired) — NOT a generic enqueue failure.  Re-read the
                # winner, validate it in FULL, and converge on the truthful
                # reused result.  We must NEVER compensate the SHARED winning
                # run to failed (the winner is a legitimate active job; the
                # loser converges on it) — only a genuine enqueue failure
                # compensates.  Zero duplicate work, zero false mutation.
                _existing_job = _s10_find_durable_job(_js, str(rec.id))
                if _existing_job is None:
                    raise
                try:
                    _validate_replay_durable_job(
                        _existing_job,
                        expected_manifest=_expected_manifest,
                        rec=rec,
                        project_id=project_id,
                        workspace_id=workspace_id,
                    )
                except (S10ApplyConflictError, FullApplyServiceError) as err:
                    session.rollback()
                    raise HTTPException(status_code=_err_status(err), detail=str(err)) from err
                # The winner's run is a valid active job — ensure the SHARED run
                # is coherent (never left failed + active job).
                _s10_ensure_run_coherent(session, rec, str(_existing_job["state"]), workspace_id)
            except (S10ApplyConflictError, FullApplyServiceError) as err:
                # Genuine enqueue failure after reopening — compensate back to
                # failed so the final state is a coherent non-claimable run,
                # never a pending orphan with zero job.  (A STABLE idempotency
                # collision is handled above and never reaches here.)
                try:
                    _compensate_run_pending_to_failed(session, str(rec.id), workspace_id)
                except Exception as comp_err:
                    raise HTTPException(
                        status_code=_err_status(err),
                        detail=f"{err}; run compensation failed: {comp_err}",
                    ) from comp_err
                raise HTTPException(status_code=_err_status(err), detail=str(err)) from err
            except Exception as err:
                try:
                    _compensate_run_pending_to_failed(session, str(rec.id), workspace_id)
                except Exception as comp_err:
                    raise HTTPException(
                        status_code=500,
                        detail=f"full-apply job repair failed: {err}; compensation failed: {comp_err}",
                    ) from comp_err
                raise HTTPException(status_code=500, detail=f"full-apply job repair failed: {err}") from err
        else:
            # F2: immutable identity + lifecycle validation BEFORE any success.
            try:
                _validate_replay_durable_job(
                    _existing_job,
                    expected_manifest=_expected_manifest,
                    rec=rec,
                    project_id=project_id,
                    workspace_id=workspace_id,
                )
                # F1 defensive: heal an incoherent run (failed + active job) so
                # the truthful pair is active — never failed+queued.
                _s10_ensure_run_coherent(session, rec, str(_existing_job["state"]), workspace_id)
            except (S10ApplyConflictError, FullApplyServiceError) as err:
                session.rollback()
                raise HTTPException(status_code=_err_status(err), detail=str(err)) from err
        # Re-read the run as a fresh S10RunRecord so the response reflects the
        # COHERENT current DB state (the dataclass returned by svc.submit is a
        # snapshot; after a repair the run is restored to pending, so it must be
        # re-read to never report run=failed + job=queued).
        rec = svc.get_run(str(rec.id), workspace_id)

    payload = SubmitFullApplyResponse(
        run_id=rec.id,
        workspace_id=rec.workspace_id,
        project_id=rec.project_id,
        status=rec.status,
        created=created,
        plan_id=rec.plan_id,
        plan_hash=rec.plan_hash,
        frame_count=rec.frame_count,
        reused=not created,
    ).model_dump(mode="json")
    # 202 on creation (worker outside request), 200 on replay dedupe
    return JSONResponse(content=payload, status_code=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK)


@router.get("/full-apply/{run_id}")
def get_full_apply_status(
    run_id: str,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    svc = _service(session)
    try:
        rec = svc.get_run(run_id, workspace_id)
    except S10ApplyNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    if project_id is not None and rec.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"FullApplyRun {run_id!r} not found in project")
    chunks = svc.list_chunks(workspace_id, run_id)
    pubs = svc.list_publications(workspace_id, run_id)
    # Fetch worker checkpoint if a durable job exists for this run
    checkpoint: dict[str, Any] | None = None
    try:
        js = get_job_service()
        factory = js.session_factory
        if factory is not None:
            from app.persistence.jobs import JobRepository  # noqa: PLC0415

            with factory() as jsess:
                repo = JobRepository(jsess)
                # Find job by idempotency key s10_full_apply_job:{run_id}
                from sqlalchemy import select as _select  # noqa: PLC0415

                from app.persistence.models import Job as _Job  # noqa: PLC0415

                job = jsess.scalar(_select(_Job).where(_Job.idempotency_key == f"s10_full_apply_job:{run_id}"))
                if job is not None:
                    steps = repo.list_steps(job.id)
                    if steps:
                        raw = getattr(steps[0], "checkpoint_json", None) or getattr(steps[0], "checkpoint", None)
                        if isinstance(raw, str):
                            try:
                                import json as _jl  # noqa: PLC0415  # local, not top-level

                                checkpoint = _jl.loads(raw)
                            except Exception:
                                checkpoint = {"raw": raw}
                        elif isinstance(raw, dict):
                            checkpoint = raw
    except Exception:
        pass
    return FullApplyStatusResponse(
        run_id=rec.id,
        workspace_id=rec.workspace_id,
        project_id=rec.project_id,
        video_item_id=rec.video_item_id,
        apply_checkpoint_id=rec.apply_checkpoint_id,
        apply_checkpoint_hash=rec.apply_checkpoint_hash,
        apply_checkpoint_revision=rec.apply_checkpoint_revision,
        plan_id=rec.plan_id,
        plan_hash=rec.plan_hash,
        status=rec.status,
        frame_count=rec.frame_count,
        attempt=rec.attempt,
        natural_key=rec.natural_key,
        idempotency_key=rec.idempotency_key,
        chunks=[dict(c.__dict__) for c in chunks],
        publications=[dict(p.__dict__) for p in pubs],
        checkpoint=checkpoint,
    ).model_dump(mode="json")


@router.post("/full-apply/{run_id}/cancel")
def cancel_full_apply(
    run_id: str,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Cancel a run AND its owned durable job as ONE atomic transition.

    S10-C6A F1: the previous implementation applied the run cancel in this
    request session, then opened a second read session and a third writer to
    cancel the durable job BEFORE committing the run — a deterministic
    rollback-journal deadlock (``database is locked``) whose ``except: pass``
    then faked ``cancelled: true`` while the job kept running.

    Now the durable job cancellation (``queued|running -> cancelling``) is
    applied on THIS SAME session/transaction via ``JobService.cancel_run_atomic``
    before the run writer runs; one commit publishes both, any failure rolls
    both back and surfaces the HTTP error — false success is impossible.
    """
    js = get_job_service()
    svc = _service(session)
    applied: list[Any] = []
    try:
        # Same-session atomic lifecycle: job cancellation signal FIRST (no
        # commit), then the validated run transition, ONE commit by the route.
        result = js.cancel_run_atomic(
            session,
            run_writer=lambda: applied.append(
                svc.cancel_run(run_id, workspace_id, project_id=project_id)
            ),
            job_key=f"s10_full_apply_job:{run_id}",
        )
    except S10ApplyNotFoundError as err:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(err)) from err
    except (S10ApplyParamsError, S10ApplyConflictError, S10ApplyOwnershipError, FullApplyServiceError) as err:
        session.rollback()
        raise HTTPException(status_code=_err_status(err), detail=str(err)) from err
    except Exception as err:
        # Lock/transition failures are NEVER swallowed (S10-C6A req 2): the
        # whole transaction rolls back and the failure is surfaced.
        session.rollback()
        raise HTTPException(status_code=500, detail=f"cancel failed: {err}") from err
    try:
        session.commit()
    except Exception as err:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"cancel commit failed: {err}") from err
    # No publication should be completed after cancel — verified by workflow tests
    rec = applied[0] if applied else None
    return {
        "run_id": run_id,
        "status": rec_status(session, run_id, workspace_id) or (rec.status if rec else None),
        "cancelled": bool(rec is not None and rec.status == "cancelled"),
        "job_state": result.get("job_state"),
    }


def rec_status(session: Session, run_id: str, workspace_id: str) -> str | None:
    """Re-read the live run status after the atomic cancel commit."""
    from sqlalchemy import select as _select  # noqa: PLC0415

    from app.persistence.models import S10FullApplyRun as _Run  # noqa: PLC0415

    return session.scalar(
        _select(_Run.status).where(_Run.id == run_id, _Run.workspace_id == workspace_id)
    )


def _s10_retry_successor_exists(session: Session, run_id: str, workspace_id: str) -> bool:
    """C6F F2: True when this predecessor lineage ALREADY has a Retry successor.

    A Retry successor is a run whose ``natural_key`` is ``s10_retry:{run_id}:<n>``
    (written by ``FullApplyService.retry_run``).  A repeat Retry on the same
    cancelled/failed predecessor — or a concurrent Retry that lost the unique
    ``natural_key`` backstop — must fail closed (409) instead of creating a
    duplicate successor or surfacing an IntegrityError (the F2-R1 500 defect).
    This is the deterministic pre-check; the unique index remains the backstop
    for a true race where both threads pass this check.
    """
    from sqlalchemy import select as _sel  # noqa: PLC0415

    from app.persistence.models import S10FullApplyRun as _Run  # noqa: PLC0415

    successor = session.scalar(
        _sel(_Run.id)
        .where(
            _Run.workspace_id == workspace_id,
            _Run.natural_key.like(f"s10_retry:{run_id}:%"),
        )
        .limit(1)
    )
    return successor is not None



def _s10_inherit_job_manifest(job_service: Any, run_id: str) -> dict[str, Any]:
    """C4: copy immutable render authority + media pins from the predecessor job.

    Reads the durable job whose idempotency key is ``s10_full_apply_job:{run_id}``
    (server-side immutable record).  Returns only the authority/media keys so a
    retry/resume can render without the caller re-supplying inputs.  On any
    lookup error the missing keys stay missing — the worker fails closed instead
    of fabricating input.
    """
    from sqlalchemy import select as _select  # noqa: PLC0415

    from app.persistence.jobs import parse_json as _parse  # noqa: PLC0415
    from app.persistence.models import Job as _Job  # noqa: PLC0415

    out: dict[str, Any] = {}
    factory = getattr(job_service, "session_factory", None)
    if factory is None:
        return out
    try:
        with factory() as jsess:
            job = jsess.scalar(
                _select(_Job).where(_Job.idempotency_key == f"s10_full_apply_job:{run_id}")
            )
            if job is None:
                return out
            raw_manifest = getattr(job, "input_manifest_json", None)
            parsed = _parse(raw_manifest, {}) if isinstance(raw_manifest, str) else {}
            if not isinstance(parsed, dict):
                return out
            for key in (
                "render_authority",
                "source_media_artifact_id",
                "source_media_rel",
                "source_media_sha256",
                "source_media_size_bytes",
                "replacement_assets",
                "timebase_fingerprint",
            ):
                if key in parsed and parsed[key] not in (None, ""):
                    out[key] = parsed[key]
            return out
    except Exception:
        return out


@router.post("/full-apply/{run_id}/retry")
def retry_full_apply(
    run_id: str,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    svc = _service(session)
    # C6D F1: a predecessor lineage that still holds an ACTIVE durable job must
    # not spawn a competing successor — fail closed with 409 (never a second
    # active canonical work item on the lineage).
    if _s10_predecessor_has_active_job(get_job_service(), str(run_id)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="predecessor run has an active full-apply job; retry would create competing work — reject",
        )
    # C6F F2-R1: a RETRY on this predecessor lineage ALREADY produced a successor
    # (a repeat Retry on the same cancelled/failed predecessor).  Deterministic
    # fail-closed 409 — never a second successor or a 500 from the unique
    # natural_key backstop.  (A true concurrent race is handled by the unique
    # index + the IntegrityError catch below.)
    if _s10_retry_successor_exists(session, str(run_id), workspace_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="predecessor run already has a retry successor; repeat retry rejected (no competing work)",
        )
    # C6F: CAS-claim a FAILED predecessor run row BEFORE creating any successor
    # run or job.  This is mutually exclusive with the replay-repair CAS
    # (failed -> pending) on the SAME row, so a truly simultaneous
    # Replay(R1) || Retry(R1) on a FAILED predecessor yields exactly ONE active
    # canonical work item: the loser sees rowcount==0 and fails closed (409) with
    # ZERO mutation (no successor run, no job).
    #
    # C6G G2-R1: this CAS is ONLY meaningful when we actually transition a row
    # (failed -> cancelled).  For an ALREADY-CANCELLED predecessor a cancelled ->
    # cancelled same-state flip is a NO-OP that must NOT be reported as ownership
    # (that was the exclusive-claim defect — two callers both "won").  So we CAS
    # only when the predecessor is genuinely failed; for a cancelled predecessor
    # ownership is decided by the ATOMIC unique-successor insertion inside
    # svc.retry_run (the uq_s10_run_natural backstop on s10_retry:{run}:{attempt})
    # — the loser hits IntegrityError and converges to a clean 409 below.
    if rec_status(session, str(run_id), workspace_id) == "failed":
        if not _s10_retry_claim_predecessor(session, str(run_id), workspace_id):
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="predecessor run was reactivated/superseded concurrently; retry rejected (no competing work)",
            )
    try:
        new_rec = svc.retry_run(run_id, workspace_id, project_id=project_id)
    except S10ApplyNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except (S10ApplyParamsError, S10ApplyConflictError, FullApplyServiceError) as err:
        session.rollback()
        raise HTTPException(status_code=_err_status(err), detail=str(err)) from err
    except IntegrityError as err:
        # C6F F2-R1/R2/R3: a concurrent Retry on the SAME predecessor already
        # created the `s10_retry:{run_id}:{attempt}` successor (the unique
        # natural_key backstop fired).  This is a STABLE idempotency-domain
        # collision, not an enqueue failure — the loser must fail closed (409)
        # truthfully, never surface a raw 500.  Zero mutation (rollback).
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="predecessor run was retried concurrently; retry rejected (no competing work)",
        ) from err
    # Commit the new attempt row BEFORE creating the durable job in a separate tx
    # so SQLite writer lock does not hit "database is locked" (one tx at a time).
    try:
        session.commit()
    except Exception as err:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"retry commit failed: {err}") from err
    # C6D F1 race guard: a concurrent replay may re-activate the predecessor
    # between our pre-check and the enqueue.  If so, compensate the fresh
    # successor attempt (fail-closed) and reject — never two active jobs.
    if _s10_predecessor_has_active_job(get_job_service(), str(run_id)):
        try:
            _compensate_run_pending_to_failed(session, str(new_rec.id), workspace_id)
        except Exception as comp_err:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"retry race: predecessor re-activated concurrently; successor compensation failed: {comp_err}",
            ) from comp_err
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="predecessor run re-activated concurrently; retry rejected (no competing work)",
        )
    try:
        js = get_job_service()
        from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY  # noqa: PLC0415

        manifest = {
            "run_id": new_rec.id,
            "workspace_id": workspace_id,
            "project_id": new_rec.project_id,
            "plan_id": new_rec.plan_id,
            "plan_hash": new_rec.plan_hash,
            "predecessor_run_id": run_id,
            "managed_root": str(js.managed_root) if hasattr(js, "managed_root") else "",
        }
        # C4: inherit the immutable render authority + media pins from the
        # predecessor job manifest (server-side record) so a retry can render
        # without caller re-supplying inputs.  Missing authority stays missing —
        # the worker fails closed instead of fabricating.
        inherited = _s10_inherit_job_manifest(js, run_id)
        manifest.update(inherited)
        # C6: revalidate the persisted authority for the retry lineage BEFORE
        # enqueue.  We NEVER scan/guess paths, copy arbitrary bytes, or
        # regenerate fixture media — the same immutable authority is resolved
        # again from the frozen v2 checkpoint and must pin identical
        # rel/sha/size.
        _mr_retry = js.managed_root if hasattr(js, "managed_root") else None
        _auth_retry = inherited.get("render_authority") if isinstance(inherited, dict) else None
        if isinstance(_auth_retry, dict) and _auth_retry.get("authority_fingerprint"):
            from app.services.s09_approval import S09ApprovalRepository as _S09Repo

            _v2_retry = _S09Repo(session).full_apply_authority(
                new_rec.apply_checkpoint_id, workspace_id
            )
            _retry_pins = _resolve_canonical_render_pins(
                session,
                workspace_id=workspace_id,
                project_id=new_rec.project_id,
                video_item_id=new_rec.video_item_id,
                apply_checkpoint_id=new_rec.apply_checkpoint_id,
                authority=_v2_retry,
                managed_root=Path(_mr_retry) if _mr_retry else None,
            )
            for _k in ("source_media_rel", "source_media_sha256", "source_media_size_bytes"):
                if manifest.get(_k) != _retry_pins.get(_k):
                    raise FullApplyServiceError(
                        f"retry authority revalidation mismatch on {_k}: manifest {manifest.get(_k)!r} vs persisted {_retry_pins.get(_k)!r} (tampered/missing authority)"
                    )
            if manifest.get("replacement_assets") != _retry_pins.get("replacement_assets"):
                raise FullApplyServiceError(
                    "retry replacement_assets revalidation mismatch vs persisted authority (tampered/missing authority)"
                )
            if manifest.get("timebase_fingerprint") != _retry_pins.get("timebase_fingerprint"):
                raise FullApplyServiceError("retry timebase_fingerprint revalidation mismatch (tampered/missing authority)")
        js.create_job(
            JOB_TYPE_S10_FULL_APPLY,
            manifest,
            workspace_id=workspace_id,
            owner_type="project",
            owner_id=new_rec.project_id,
            idempotency_key=f"s10_full_apply_job:{new_rec.id}",
            # C6E F1: deterministic non-NULL generation derived from the fresh
            # attempt run so the unique backstop serializes any concurrent
            # replay/retry on the same new attempt identity.
            input_generation=_s10_job_generation(str(new_rec.id)),
        )
    except FullApplyServiceError as err:
        # S10-C10 F1 req 3: any post-commit retry failure (authority
        # revalidation mismatch included) must compensate the successor
        # attempt to a durable coherent non-active state — a ``pending``
        # attempt-2 row with zero durable job is an orphan no worker claims.
        # Predecessor stays untouched (its row is terminal cancelled); zero
        # publication/checkpoint mutation.  Compensation failure is surfaced
        # inside the detail (fail-closed), never swallowed.
        try:
            _compensate_run_pending_to_failed(session, str(new_rec.id), workspace_id)
        except Exception as comp_err:
            raise HTTPException(
                status_code=_err_status(err),
                detail=f"{err}; attempt compensation failed: {comp_err}",
            ) from comp_err
        raise HTTPException(status_code=_err_status(err), detail=str(err)) from err
    except Exception as err:
        # S10-C10 F1 req 3: forced create_job failure after the attempt-2 row
        # committed — compensate pending→failed (coherent non-claimable) before
        # surfacing, so no pending successor orphan survives the 500.
        try:
            _compensate_run_pending_to_failed(session, str(new_rec.id), workspace_id)
        except Exception as comp_err:
            raise HTTPException(
                status_code=500,
                detail=f"retry enqueue failed: {err}; attempt compensation failed: {comp_err}",
            ) from comp_err
        raise HTTPException(status_code=500, detail=f"retry enqueue failed: {err}") from err
    return {"run_id": new_rec.id, "predecessor_run_id": run_id, "status": new_rec.status, "attempt": new_rec.attempt}


def _compensate_resume(session: Any, run_id: str, workspace_id: str, pre_status: str | None) -> None:
    """S10-C6A F3: revert the committed run-side resume after enqueue failure.

    Only ``failed -> pending`` actually mutates the run during resume; the
    compensation CAS-reverts that reopen so the caller never observes a
    "resumed" run with no durable successor behind it.  Any other pre-state
    was never mutated — no-op.  Raises on failure, never swallowed.
    """
    if pre_status != "failed":
        return
    from sqlalchemy import text as _sa_text  # noqa: PLC0415

    session.execute(
        _sa_text(
            "UPDATE s10_full_apply_run SET status='failed', updated_at=CURRENT_TIMESTAMP "
            "WHERE id=:rid AND workspace_id=:ws AND status='pending'"
        ),
        {"rid": run_id, "ws": workspace_id},
    )
    session.commit()


@router.post("/full-apply/{run_id}/resume")
def resume_full_apply(
    run_id: str,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    svc = _service(session)
    pre_status: str | None = None
    try:
        pre_status = str(svc.get_run(run_id, workspace_id).status or "")
        rec = svc.resume_run(run_id, workspace_id, project_id=project_id)
    except S10ApplyNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except (S10ApplyParamsError, FullApplyServiceError) as err:
        # C9: taxonomy-consistent mapping (module-wide _err_status) instead of
        # the previous hardcoded 409 — state-invalid resume requests (e.g.
        # "cannot resume a cancelled run; use retry") are S10ApplyParamsError
        # → 422, matching the sibling retry route and the submit route.
        session.rollback()
        raise HTTPException(status_code=_err_status(err), detail=str(err)) from err
    try:
        # S10-C6A F3: commit the request transaction (run reopened) BEFORE the
        # job-session opens its own SQLite writer — one writer at a time, no
        # whole-DB busy lock (mirrors retry commit-first ordering).
        session.commit()
    except Exception as err:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"resume commit failed: {err}") from err
    try:
        # Re-enqueue or re-activate the durable job so a fresh worker resumes
        js = get_job_service()
        from sqlalchemy import select as _select  # noqa: PLC0415

        from app.persistence.models import Job as _Job  # noqa: PLC0415
        from app.workflow.s10_full_apply_jobs import JOB_TYPE_S10_FULL_APPLY  # noqa: PLC0415

        factory = js.session_factory
        if factory is not None:
            with factory() as jsess:
                from app.persistence.jobs import JobRepository  # noqa: PLC0415

                repo = JobRepository(jsess)
                existing = jsess.scalar(_select(_Job).where(_Job.idempotency_key == f"s10_full_apply_job:{run_id}"))
                if existing is None:
                    manifest = {
                        "run_id": rec.id,
                        "workspace_id": workspace_id,
                        "project_id": rec.project_id,
                        "plan_id": rec.plan_id,
                        "plan_hash": rec.plan_hash,
                        "managed_root": str(js.managed_root) if hasattr(js, "managed_root") else "",
                    }
                    # C4: inherit immutable authority/media from any prior job for
                    # this run; missing authority fails closed inside the worker.
                    inherited = _s10_inherit_job_manifest(js, run_id)
                    manifest.update(inherited)
                    # C6: revalidate the persisted authority before enqueue —
                    # resume reuses the exact immutable lineage after revalidation,
                    # never scanning/guessing paths or regenerating media.
                    _mr_resume = js.managed_root if hasattr(js, "managed_root") else None
                    _auth_resume = inherited.get("render_authority") if isinstance(inherited, dict) else None
                    if isinstance(_auth_resume, dict) and _auth_resume.get("authority_fingerprint"):
                        from app.services.s09_approval import S09ApprovalRepository as _S09Repo

                        _v2_resume = _S09Repo(session).full_apply_authority(
                            rec.apply_checkpoint_id, workspace_id
                        )
                        _resume_pins = _resolve_canonical_render_pins(
                            session,
                            workspace_id=workspace_id,
                            project_id=rec.project_id,
                            video_item_id=rec.video_item_id,
                            apply_checkpoint_id=rec.apply_checkpoint_id,
                            authority=_v2_resume,
                            managed_root=Path(_mr_resume) if _mr_resume else None,
                        )
                        for _k in ("source_media_rel", "source_media_sha256", "source_media_size_bytes"):
                            if manifest.get(_k) != _resume_pins.get(_k):
                                raise FullApplyServiceError(
                                    f"resume authority revalidation mismatch on {_k} (tampered/missing authority)"
                                )
                        if manifest.get("replacement_assets") != _resume_pins.get("replacement_assets"):
                            raise FullApplyServiceError(
                                "resume replacement_assets revalidation mismatch vs persisted authority (tampered/missing authority)"
                            )
                        if manifest.get("timebase_fingerprint") != _resume_pins.get("timebase_fingerprint"):
                            raise FullApplyServiceError(
                                "resume timebase_fingerprint revalidation mismatch (tampered/missing authority)"
                            )
                    js.create_job(
                        JOB_TYPE_S10_FULL_APPLY,
                        manifest,
                        workspace_id=workspace_id,
                        owner_type="project",
                        owner_id=rec.project_id,
                        idempotency_key=f"s10_full_apply_job:{run_id}",
                        # C6E F1: deterministic non-NULL generation derived from
                        # the resumed run so the unique backstop serializes any
                        # concurrent resume/replay on the same job identity.
                        input_generation=_s10_job_generation(str(run_id)),
                    )
                else:
                    # If the job is terminal (completed/failed/cancelled), create a successor
                    # so the worker actually resumes.  Otherwise the existing queued/running
                    # job will be picked up by the poll loop.
                    if existing.state in ("completed", "failed", "cancelled"):
                        from app.persistence.jobs import parse_json as _parse  # noqa: PLC0415

                        raw_manifest = getattr(existing, "input_manifest_json", None)
                        parsed = _parse(raw_manifest, {}) if isinstance(raw_manifest, str) else {}
                        if not isinstance(parsed, dict):
                            parsed = {}
                        # S10-C6A F3: create-successor failure is NEVER swallowed —
                        # it surfaces as 500 and the committed run-side resume is
                        # compensated back to ``failed`` (no phantom ``resumed``).
                        repo.create_successor(
                            predecessor_job_id=existing.id,
                            input_manifest=dict(parsed) if parsed else {"run_id": run_id, "workspace_id": workspace_id},
                            idempotency_key=f"s10_full_apply_job:{run_id}:resume:{rec.attempt}",
                        )
                        jsess.commit()
    except FullApplyServiceError as err:
        session.rollback()
        _compensate_resume(session, rec.id, workspace_id, pre_status)
        raise HTTPException(status_code=_err_status(err), detail=str(err)) from err
    except Exception as err:
        # F3: no swallowed enqueue failure — compensate the committed reopen
        # so state stays coherent, then surface 500 (never resumed:true).
        try:
            session.rollback()
        except Exception:
            pass
        _compensate_resume(session, rec.id, workspace_id, pre_status)
        raise HTTPException(status_code=500, detail=f"resume commit/enqueue failed: {err}") from err
    return {"run_id": rec.id, "status": rec.status, "resumed": True}


# ── S10-T04A — Structural comparison gate (bounded, additive) ─────────────────


class StructuralCompareRequest(_Strict):
    """Client intent hint — server ignores all pass/fail measurements.

    Only run scoping is authoritative from the client; every metric is
    derived server-side from persisted publication + source lock + evidence.
    The body is accepted as an empty hint so existing UI callers survive,
    but no field inside it can influence the pass/fail decision.
    """
    # Back-compat: accept any extra keys silently (they are ignored).
    model_config = ConfigDict(extra="allow")


@router.post("/full-apply/{run_id}/structural-compare", tags=["s10-full-apply"])
def structural_compare_gate(
    run_id: str,
    body: StructuralCompareRequest,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Server-derived machine gate — clients cannot supply pass evidence.

    Loads the pinned StructuralLockManifest/checkpoint, completed publication,
    decoded rendered media and stored per-role evidence; computes every metric
    on the server and records content hashes. Crafted good metrics cannot
    convert a blocked run to REVIEW_REQUIRED.
    """
    # verify run exists / ownership
    svc = _service(session)
    try:
        rec = svc.get_run(run_id, workspace_id)
    except S10ApplyNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    if project_id is not None and rec.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"FullApplyRun {run_id!r} not found in project")

    from sqlalchemy import text as _sa_text  # noqa: PLC0415

    from app.persistence.models import ApplyCheckpoint as _ApplyCheckpoint  # noqa: PLC0415
    from app.services.s10_structural_compare import (  # noqa: PLC0415
        S10StructuralCompareService,
        ServerDerivedCompareInput,
        S10StructuralEvidenceError,
        build_server_derived_result,
        expected_publication_lineage_hash,
        hash_canonical,
    )

    # ── 1) Load checkpoint + pinned source lock ─────────────────────
    ckpt = session.get(_ApplyCheckpoint, rec.apply_checkpoint_id)
    if ckpt is None or str(ckpt.workspace_id) != workspace_id:
        raise HTTPException(status_code=422, detail="checkpoint not found for run (missing authority)")
    # ckpt pins structural_lock_manifest_id + lock_policy_version when S10 was enqueued
    slm_id = getattr(ckpt, "structural_lock_manifest_id", None)
    ckpt_policy = getattr(ckpt, "lock_policy_version", None)
    if not slm_id:
        # No pinned source lock -> cannot prove structural validity
        gate = S10StructuralCompareService(expected_policy_version=ckpt_policy)
        # Force BLOCKED via missing source manifest (fail-closed)
        r = gate.compare(
            source_manifest=None,
            rendered_manifest=None,
            metrics=None,
            annotations=None,
            policy_version=None,
            expected_policy_version=ckpt_policy,
        )
        # Override reason to be explicit about missing source lock
        payload = r.to_dict()
        payload["run_id"] = rec.id
        payload["workspace_id"] = rec.workspace_id
        payload["server_derived"] = True
        # Ensure BLOCKED even if default path accidentally passes
        if payload.get("status") == "REVIEW_REQUIRED":
            payload["status"] = "BLOCKED"
            payload["passed"] = False
            payload["failures"] = [
                {
                    "code": "SOURCE_LOCK_MISSING",
                    "reason": "checkpoint has no pinned StructuralLockManifest [role=unknown layer=unknown segment=unknown route=unknown]",
                    "role": "unknown",
                    "layer": "unknown",
                    "segment": "unknown",
                    "route": "unknown",
                    "metric": "source_manifest",
                    "value": None,
                    "threshold": None,
                }
            ]
        return payload

    from app.persistence.models import StructuralLockManifest as _SLM  # noqa: PLC0415

    slm = session.get(_SLM, str(slm_id))
    if slm is None or str(slm.workspace_id) != workspace_id:
        raise HTTPException(status_code=422, detail="pinned StructuralLockManifest not found (missing authority)")

    # Re-validate manifest_json is canonical; tampered row -> BLOCKED
    try:

        from app.persistence.structural_lock import (  # noqa: PLC0415
            canonical_manifest_json,
            parse_manifest,
        )

        manifest_dict = parse_manifest(str(slm.manifest_json))
        canonical = canonical_manifest_json(manifest_dict)
        # Integrity: stored hash must match computed
        import hashlib as _hl  # noqa: PLC0415

        computed_hash = _hl.sha256(canonical.encode()).hexdigest()
        if computed_hash != str(slm.manifest_hash):
            raise S10StructuralEvidenceError("source manifest hash mismatch (tampered)")
        source_manifest_hash = computed_hash
    except S10StructuralEvidenceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        # Use 422 for evidence corruption, not 500
        raise HTTPException(status_code=422, detail=f"source manifest invalid: {e}") from e

    expected_policy = str(slm.policy_version)

    # C4: fail-closed BLOCKED payload builder for the structural-compare gate.
    # Blocked branches never fabricate a rendered manifest or metrics — the
    # verdict is a single explicit failure, not a compare with invented truth.
    def _blocked(code: str, reason: str, metric: str = "", value: Any = None) -> dict[str, Any]:
        return {
            "status": "BLOCKED",
            "passed": False,
            "failures": [
                {
                    "code": code,
                    "reason": f"{reason} [role=unknown layer=unknown segment=unknown route=unknown]",
                    "role": "unknown",
                    "layer": "unknown",
                    "segment": "unknown",
                    "route": "unknown",
                    "metric": metric,
                    "value": value,
                    "threshold": None,
                }
            ],
            "checks": {},
            "policy_version": expected_policy,
            "expected_policy_version": expected_policy,
            "run_id": rec.id,
            "workspace_id": rec.workspace_id,
            "server_derived": True,
            "source_manifest_hash": source_manifest_hash,
        }

    # Stale policy: checkpoint policy must match manifest policy
    if ckpt_policy and str(ckpt_policy) != expected_policy:
        return _blocked(
            "POLICY_VERSION_MISMATCH",
            f"policy_version mismatch: checkpoint pins {str(ckpt_policy)!r} but pinned source manifest expects {expected_policy!r}",
            metric="policy_version",
            value={"checkpoint": str(ckpt_policy), "expected": expected_policy},
        )

    # ── 2) Load completed publication + rendered artifact ────────────
    pubs = svc.list_publications(workspace_id, run_id)
    completed = [p for p in pubs if p.state == "completed"]
    if not completed:
        return _blocked(
            "PUBLICATION_MISSING",
            "no completed publication for run — output not yet verified",
            metric="publication",
        )

    # Use the latest completed publication (there is exactly one on success)
    pub = sorted(completed, key=lambda p: p.created_at, reverse=True)[0]
    # Derive rendered evidence server-side — do NOT trust body metrics
    from pathlib import Path as _Path  # noqa: PLC0415

    from app.api.deps import get_managed_root as _get_managed_root  # noqa: PLC0415
    from app.persistence.artifacts import hash_file as _hash_file  # noqa: PLC0415
    from app.persistence.models import Artifact as _Artifact  # noqa: PLC0415

    art = session.get(_Artifact, pub.artifact_id)
    if art is None or str(art.workspace_id) != workspace_id:
        raise HTTPException(status_code=422, detail="publication artifact not found (missing evidence)")
    if art.sha256 is None or art.size_bytes is None or int(art.size_bytes) <= 0:
        raise HTTPException(status_code=422, detail="publication artifact has null SHA/size (unverified)")
    if ".partial" in str(art.relative_path):
        raise HTTPException(status_code=422, detail="publication artifact is .partial (unverified)")
    try:
        managed_root = _get_managed_root()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"managed root unavailable: {e}") from e
    # Windows extended-length path: the producer writes every media/evidence
    # file through `_lp` (\\?\ prefix) so deep managed roots survive
    # MAX_PATH; the gate MUST read through the same form or
    # is_file()/_hash_file()/stat()/decode fail with RENDERED_FILE_MISSING
    # on >260-char artifact paths (binary rule 4/6 unreachable).  The
    # fail-closed branches below (missing/tamper/size) are unchanged.
    abs_path = _Path(_win_long_path(_Path(managed_root) / str(art.relative_path)))
    if not abs_path.is_file():
        # Missing file = BLOCKED, not 404 — evidence is authority, not client path
        return _blocked(
            "RENDERED_FILE_MISSING",
            f"rendered file missing at {art.relative_path!r}",
            metric="rendered_file",
            value=str(art.relative_path),
        )

    # Verify file SHA/size match stored artifact row — tamper => BLOCKED
    try:
        file_sha = _hash_file(abs_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"rendered file hash failed: {e}") from e
    if file_sha != str(art.sha256):
        return _blocked(
            "RENDERED_TAMPERED",
            f"rendered file SHA mismatch: stored {art.sha256!r} vs file {file_sha!r}",
            metric="rendered_sha256",
            value={"stored": str(art.sha256), "file": file_sha},
        )
    if int(abs_path.stat().st_size) != int(art.size_bytes):
        return _blocked(
            "RENDERED_SIZE_MISMATCH",
            f"rendered file size mismatch: stored {art.size_bytes} vs file {abs_path.stat().st_size}",
            metric="rendered_size_bytes",
            value={"stored": int(art.size_bytes), "file": int(abs_path.stat().st_size)},
        )
    # Publication content_hash must satisfy the producer LINEAGE contract —
    # FullApply: sha256("pub:{run_id}:{artifact_sha}"), partial-recompute:
    # sha256("pub-recompute:{run_id}:{correction_id}:{artifact_sha}") resolved
    # from natural_key provenance.  content_hash is a lineage key, NOT a raw
    # file digest (the artifact's own sha256/size are verified against the
    # managed file above via RENDERED_TAMPERED / RENDERED_SIZE_MISMATCH).
    # A publication row whose content_hash does not bind to its artifact
    # (raw-sha synthetic, tampered, or foreign provenance) is BLOCKED.
    expected_pub_hash = expected_publication_lineage_hash(
        str(rec.id), str(art.sha256), getattr(pub, "natural_key", None)
    )
    if expected_pub_hash is None or str(pub.content_hash) != expected_pub_hash:
        return _blocked(
            "PUBLICATION_CONTENT_HASH_MISMATCH",
            f"publication content_hash does not satisfy lineage contract: pub {str(pub.content_hash)!r} vs artifact {str(art.sha256)!r} expected {expected_pub_hash!r}",
            metric="publication_content_hash",
            value={
                "publication": str(pub.content_hash),
                "artifact": str(art.sha256),
                "expected_lineage": expected_pub_hash,
                "natural_key": getattr(pub, "natural_key", None),
            },
        )

    # Try to decode rendered media — undecodable => BLOCKED
    try:
        from app.services.renderer_routes.composite import (  # noqa: PLC0415
            decode_rgb_frames,
            probe_source_timebase,
        )

        decoded = decode_rgb_frames(abs_path)
        decoded_count = len(decoded)
        if decoded_count == 0:
            raise ValueError("decoded zero frames")
        # Rendered timebase: measured from the decoded publication container,
        # NEVER mirrored from the source manifest.
        rendered_fps_num, rendered_fps_den = probe_source_timebase(abs_path)
        # Frame diagonal for %-of-diagonal metrics from the decoded frame.
        _fh, _fw = decoded[0].shape[:2]
        diagonal_px = math.hypot(int(_fw), int(_fh))
    except Exception as e:
        return _blocked(
            "RENDERED_UNDECODABLE",
            f"rendered media undecodable or unmeasurable: {e}",
            metric="decoded_frames",
            value=str(e),
        )

    # ── 3) Measured structural gate (C4) ───────────────────────────
    # Every metric is measured server-side from the pinned source manifest
    # (source authority) and the decoded publication + persisted output
    # evidence (rendered authority).  No fixed arrays, no rendered->source
    # mirroring, no chunk/hash "measured" placeholder, no missing-evidence
    # 0/False default-pass.  Missing authority -> BLOCKED (fail-closed).
    # Source frame/timebase/shot/cut truth: ONLY from the pinned manifest.
    source_frame_count = manifest_dict.get("frame_count")
    if not isinstance(source_frame_count, int):
        source_frame_count = None  # -> FRAME_COUNT_MISSING BLOCKED
    # Source timebase is read by the compare from the pinned manifest
    # (timebase.fps -> fps_num/fps_den); missing manifest timebase results in
    # TIMEBASE_MISSING BLOCKED.  Rendered timebase is measured separately
    # from the decoded publication container (never mirrored from source).
    source_shot_order = manifest_dict.get("shot_order")
    if not isinstance(source_shot_order, list) or not source_shot_order:
        # No shot_order in manifest -> BLOCKED (cannot verify shot truth)
        return _blocked(
            "SHOT_ORDER_MISSING",
            "source shot_order missing from pinned manifest",
            metric="shot_order",
        )
    source_shot_order = [str(x) for x in source_shot_order]
    # Source cuts: explicit cut_frames when present, else interior segment
    # start_frame boundaries (>0) from the pinned manifest.  NEVER mirrored
    # from rendered chunk boundaries.
    source_cut_frames: list[int] | None = None
    manifest_cuts = manifest_dict.get("cut_frames")
    if isinstance(manifest_cuts, list) and manifest_cuts:
        source_cut_frames = [int(x) for x in manifest_cuts]
    else:
        _manifest_segs = manifest_dict.get("segments")
        if isinstance(_manifest_segs, list) and _manifest_segs:
            _seg_starts = sorted(
                {int(s.get("start_frame", 0)) for s in _manifest_segs if isinstance(s, dict) and int(s.get("start_frame", 0)) > 0}
            )
            if _seg_starts:
                source_cut_frames = _seg_starts
        # No source authority -> source_cut_frames stays None -> BLOCKED
    # Rendered shot/cut truth: ONLY from chunk cores, never synthesized.
    chunks = svc.list_chunks(workspace_id, run_id)
    if not chunks:
        return _blocked(
            "EVIDENCE_MISSING",
            "no chunk evidence for run — cannot verify structure",
            metric="chunks",
            value=0,
        )
    by_shot: dict[str, dict[str, int]] = {}
    for c in chunks:
        sid = str(c.shot_id)
        prev = by_shot.get(sid)
        if prev is None:
            by_shot[sid] = {"start": int(c.core_start_frame), "end": int(c.core_end_frame)}
        else:
            prev["start"] = min(prev["start"], int(c.core_start_frame))
            prev["end"] = max(prev["end"], int(c.core_end_frame))
    ordered_shots = sorted(by_shot.items(), key=lambda kv: kv[1]["start"])
    rendered_shot_order = [sid for sid, _ in ordered_shots]
    rendered_cut_frames: list[int] = []
    for idx in range(1, len(ordered_shots)):
        rendered_cut_frames.append(int(ordered_shots[idx][1]["start"]))
    # Evidence hashes for audit trail (hashes are recorded alongside
    # measurements, never substituted for them).
    from app.services.s10_structural_compare import (  # noqa: PLC0415
        MEASUREMENT_METHOD,
        MEASUREMENT_VERSION,
        S10StructuralEvidenceError,
        expected_segment_for_frame,
        measure_contact_error_pct,
        measure_rotation_error_deg,
        measure_scale_error_pct,
        measure_trajectory_error_pct,
        transform_parse,
    )

    evidence_hashes: dict[str, str] = {}
    try:
        route_rows = session.execute(
            _sa_text("SELECT id, route, occurrence_segment_id, anchor_x, anchor_y FROM segment_render_route WHERE workspace_id=:ws AND video_item_id=:vid"),
            {"ws": workspace_id, "vid": rec.video_item_id},
        ).mappings().all()
        evidence_hashes["routes"] = hash_canonical([dict(r) for r in route_rows])
    except Exception:
        evidence_hashes["routes"] = hash_canonical([])
    try:
        contact_rows = session.execute(
            _sa_text("SELECT id, contact_kind, source_segment_id, target_segment_id, start_frame FROM scene_graph_contact WHERE workspace_id=:ws AND video_item_id=:vid ORDER BY start_frame, id"),
            {"ws": workspace_id, "vid": rec.video_item_id},
        ).mappings().all()
        evidence_hashes["contacts"] = hash_canonical([dict(r) for r in contact_rows])
    except Exception:
        evidence_hashes["contacts"] = hash_canonical([])
    try:
        occ_rows = session.execute(
            _sa_text("SELECT id, occluder_segment_id, occludee_segment_id FROM scene_graph_occlusion WHERE workspace_id=:ws AND video_item_id=:vid"),
            {"ws": workspace_id, "vid": rec.video_item_id},
        ).mappings().all()
        evidence_hashes["occlusions"] = hash_canonical([dict(r) for r in occ_rows])
    except Exception:
        evidence_hashes["occlusions"] = hash_canonical([])
    try:
        seg_rows = session.execute(
            _sa_text("SELECT id, z_order, visibility, mask_artifact_id, source_generation, start_frame FROM occurrence_segment WHERE workspace_id=:ws AND video_item_id=:vid ORDER BY start_frame, id"),
            {"ws": workspace_id, "vid": rec.video_item_id},
        ).mappings().all()
        evidence_hashes["segments"] = hash_canonical([dict(r) for r in seg_rows])
    except Exception:
        seg_rows = []
        evidence_hashes["segments"] = hash_canonical([])
    try:
        mot_rows = session.execute(
            _sa_text("SELECT sm.id, sm.occurrence_segment_id, sm.transform_type, sm.start_frame, sm.transform_json FROM segment_motion sm JOIN occurrence_segment os ON os.id = sm.occurrence_segment_id WHERE sm.workspace_id=:ws AND os.video_item_id=:vid ORDER BY sm.start_frame, sm.id"),
            {"ws": workspace_id, "vid": rec.video_item_id},
        ).mappings().all()
        evidence_hashes["motion"] = hash_canonical([dict(r) for r in mot_rows])
    except Exception:
        mot_rows = []
        evidence_hashes["motion"] = hash_canonical([])

    # ── rendered motion authority: persisted segment_motion.transform_json ──
    # Trajectory/scale/rotation are MEASURED from the persisted transform
    # parameters vs the pinned-manifest expected per segment.  No motion rows
    # => unsupported => None => BLOCKED (never a fixed low-error pass).
    rendered_frame_count = decoded_count
    _manifest_segs = manifest_dict.get("segments") if isinstance(manifest_dict.get("segments"), list) else []
    evidence_hashes["measurement_diagonal_px"] = hash_canonical(round(diagonal_px, 4))
    trajectory_errors: list[float] | None = None
    scale_errors_m: list[float] | None = None
    rotation_errors_m: list[float] | None = None
    if mot_rows:
        trajectory_errors = []
        scale_errors_m = []
        rotation_errors_m = []
        try:
            for _mr in mot_rows:
                _tr = transform_parse(str(_mr["transform_json"]))
                _seg_exp = expected_segment_for_frame(_manifest_segs, int(_mr["start_frame"]))
                trajectory_errors.append(measure_trajectory_error_pct(_tr, _seg_exp, diagonal_px))
                scale_errors_m.append(measure_scale_error_pct(_tr, _seg_exp, diagonal_px))
                rotation_errors_m.append(measure_rotation_error_deg(_tr, _seg_exp))
            evidence_hashes["measurement_source"] = hash_canonical("segment_motion.transform_json")
        except S10StructuralEvidenceError as _me:
            # Unsupported measurement (malformed/zero-expectation) -> BLOCKED
            trajectory_errors = None
            scale_errors_m = None
            rotation_errors_m = None
            evidence_hashes["measurement_unsupported"] = hash_canonical(str(_me))
            evidence_hashes["measurement_source"] = hash_canonical("unsupported-motion-measurement")
    else:
        evidence_hashes["measurement_source"] = hash_canonical("missing-segment_motion-rows")
    # ── rendered contact authority: persisted scene_graph_contact rows ──
    # Contact error = |dist(applied anchors) - dist(expected anchors)| / D.
    contact_errors_m: list[float] | None = None
    if contact_rows and mot_rows:
        _mot_by_seg: dict[str, tuple[int, dict[str, Any]]] = {}
        for _mr in mot_rows:
            _sid = str(_mr["occurrence_segment_id"])
            if _sid not in _mot_by_seg:
                _mot_by_seg[_sid] = (int(_mr["start_frame"]), transform_parse(str(_mr["transform_json"])))
        contact_errors_m = []
        try:
            for _cr in contact_rows:
                _sf_t, _ts = _mot_by_seg.get(str(_cr["source_segment_id"]), (None, None))
                _tf_t, _tt = _mot_by_seg.get(str(_cr["target_segment_id"]), (None, None))
                if _ts is None or _tt is None:
                    raise S10StructuralEvidenceError(
                        "contact endpoint segment missing motion evidence (unsupported contact measurement)"
                    )
                _seg_s = expected_segment_for_frame(_manifest_segs, _sf_t or 0)
                _seg_t = expected_segment_for_frame(_manifest_segs, _tf_t or 0)
                contact_errors_m.append(measure_contact_error_pct(_ts, _tt, _seg_s, _seg_t, diagonal_px))
            evidence_hashes["measurement_contact_source"] = hash_canonical("scene_graph_contact+motion")
        except S10StructuralEvidenceError as _ce:
            contact_errors_m = None
            evidence_hashes["measurement_unsupported"] = hash_canonical(str(_ce))
            evidence_hashes["measurement_contact_source"] = hash_canonical("unsupported-contact-measurement")
    elif not contact_rows:
        evidence_hashes["measurement_contact_source"] = hash_canonical("missing-scene_graph_contact-rows")
    # ── z-order / visibility / clipping: persisted segment + occlusion ──
    # No segment rows => every value None => BLOCKED (missing authority).
    if seg_rows:
        _z_orders = [int(r["z_order"]) for r in seg_rows]
        z_order_inversions: int | None = sum(
            1 for i in range(1, len(_z_orders)) if _z_orders[i] < _z_orders[i - 1]
        )
        _occluded_ids = {str(r["occludee_segment_id"]) for r in occ_rows}
        visibility_events: int | None = sum(
            1 for r in seg_rows if str(r["visibility"]) != "visible" and str(r["id"]) not in _occluded_ids
        )
        # Clipping via silhouette reuse: a rendered (non-source-generation)
        # segment whose mask artifact equals the pinned source generation's
        # silhouette artifact = the renderer reused the source silhouette
        # instead of producing a replacement.  Missing silhouette authority
        # (no source-generation segment masks) or missing rendered mask
        # authority (any segment without mask_artifact_id) => None => BLOCKED.
        _src_gen = str(getattr(slm, "source_generation", "") or "")
        _src_sil_ids = {
            str(r["mask_artifact_id"]) for r in seg_rows if str(r["source_generation"]) == _src_gen and r["mask_artifact_id"]
        }
        if not _src_sil_ids or any(r["mask_artifact_id"] is None for r in seg_rows):
            clipping: bool | None = None
        else:
            clipping = any(
                str(r["mask_artifact_id"]) in _src_sil_ids and str(r["source_generation"]) != _src_gen for r in seg_rows
            )
    else:
        z_order_inversions = None
        visibility_events = None
        clipping = None
    if not source_shot_order or source_cut_frames is None or not seg_rows:
        annotations = None
    else:
        annotations = {
            "shot_order": list(source_shot_order),
            "cut_frames": list(source_cut_frames),
            "z_order": [{"z_order": v} for v in _z_orders],
            "visibility": [
                {"visibility": str(r["visibility"]), "mask_artifact_id": str(r["mask_artifact_id"])} for r in seg_rows
            ],
        }

    inp = ServerDerivedCompareInput(
        source_manifest=manifest_dict,
        source_manifest_hash=source_manifest_hash,
        policy_version=expected_policy,
        rendered_frame_count=rendered_frame_count,
        rendered_fps_num=rendered_fps_num,
        rendered_fps_den=rendered_fps_den,
        rendered_shot_order=rendered_shot_order,
        rendered_cut_frames=rendered_cut_frames,
        trajectory_errors=trajectory_errors,
        scale_errors=scale_errors_m,
        rotation_errors=rotation_errors_m,
        contact_errors=contact_errors_m,
        z_order_inversions=z_order_inversions,
        visibility_events=visibility_events,
        clipping_via_silhouette_reuse=clipping,
        annotations=annotations,
        rendered_sha256=file_sha,
        rendered_size_bytes=int(art.size_bytes),
        decoded_frame_count=decoded_count,
        publication_id=pub.id,
        publication_content_hash=pub.content_hash,
        evidence_hashes=evidence_hashes,
        measurement_method=MEASUREMENT_METHOD,
        measurement_version=MEASUREMENT_VERSION,
    )
    derived = build_server_derived_result(
        inp,
        expected_policy_version=expected_policy,
        context={"role": "server", "layer": "server", "segment": "server", "route": "server"},
    )
    payload = derived.to_dict()
    payload["run_id"] = rec.id
    payload["workspace_id"] = rec.workspace_id
    payload["server_derived"] = True
    return payload


# ── S10-T03 — Partial recompute (F4) ────────────────────────────────────────────


class RecomputeRequest(_Strict):
    correction_id: str = Field(min_length=1, max_length=255)
    correction_kind: str = Field(min_length=1)
    target_layer_ids: list[str] = Field(min_length=1)
    target_shot_ids: list[str] | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    provenance_extra: dict[str, Any] | None = None


class RecomputeResponse(BaseModel):
    correction_id: str
    correction_kind: str
    run_id: str
    workspace_id: str
    project_id: str
    affected_chunk_ids: list[str]
    result_hash: str
    created: bool
    reused: bool
    revision_before: int | None = None
    revision_after: int | None = None
    provenance: dict[str, Any] | None = None


@router.post("/full-apply/{run_id}/recompute", tags=["s10-full-apply"])
def recompute_full_apply(
    run_id: str,
    body: RecomputeRequest,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Project-scoped idempotent recompute: validates ownership/revision, computes
    affected closure, bumps affected attempts exactly once, and enqueues durable
    execution of affected chunks via the same real T02 executor (no fake bytes).
    """
    from app.services.s10_recompute import (
        S10RecomputeConflictError,
        S10RecomputeNotFoundError,
        S10RecomputeOwnershipError,
        S10RecomputeParamsError,
        S10RecomputeService,
        S10RecomputeStaleError,
    )

    eff_project = project_id
    if eff_project is None:
        try:
            from sqlalchemy import text as _t

            row = session.execute(_t("SELECT project_id FROM s10_full_apply_run WHERE id=:rid AND workspace_id=:ws"), {"rid": run_id, "ws": workspace_id}).mappings().first()
            if row is not None:
                eff_project = str(row["project_id"])
            else:
                raise S10RecomputeNotFoundError(f"FullApplyRun {run_id!r} not found")
        except Exception as exc:
            if isinstance(exc, S10RecomputeNotFoundError):
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise HTTPException(status_code=404, detail=f"FullApplyRun {run_id!r} not found") from exc

    try:
        svc = S10RecomputeService(session)
        rec, created = svc.apply_correction(
            workspace_id=workspace_id,
            project_id=str(eff_project),
            run_id=run_id,
            correction_id=str(body.correction_id),
            correction_kind=str(body.correction_kind),
            target_layer_ids=list(body.target_layer_ids),
            target_shot_ids=list(body.target_shot_ids) if body.target_shot_ids is not None else None,
            expected_revision=body.expected_revision,
            provenance_extra=dict(body.provenance_extra) if body.provenance_extra else None,
        )
    except S10RecomputeNotFoundError as err:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(err)) from err
    except S10RecomputeOwnershipError as err:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(err)) from err
    except S10RecomputeStaleError as err:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(err)) from err
    except S10RecomputeConflictError as err:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(err)) from err
    except S10RecomputeParamsError as err:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(err)) from err
    except Exception as err:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(err)) from err

    try:
        session.commit()
    except Exception as err:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"recompute commit failed: {err}") from err

    _recompute_managed_root = None
    try:
        from app.api import deps as _deps_r4

        try:
            _recompute_managed_root = _deps_r4.get_managed_root()
        except Exception:
            _recompute_managed_root = None
        if _recompute_managed_root is not None:
            _fac_r4 = None
            try:
                _fac_r4 = _deps_r4.get_job_service().session_factory
            except Exception:
                _fac_r4 = None
            if _fac_r4 is None:
                try:
                    from app.lifecycle import default_database_path as _ddp_r4
                    from app.persistence import create_engine_for_path as _cef_r4
                    from app.persistence import create_session_factory as _csf_r4

                    _engine_r4 = _cef_r4(_ddp_r4())
                    _fac_r4 = _csf_r4(_engine_r4)
                except Exception:
                    _fac_r4 = None
            if _fac_r4 is not None:
                with _fac_r4() as _s_r4:
                    from app.services.s10_recompute import S10RecomputeService as _S_r4

                    _svc_r4 = _S_r4(_s_r4)
                    _svc_r4.execute_partial(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        correction_id=str(body.correction_id),
                        managed_root=_recompute_managed_root,
                    )
                    _s_r4.commit()
            else:
                raise RuntimeError("no isolated session factory for recompute")
    except Exception as _recompute_execute_err:
        _recompute_error = __import__("traceback").format_exc()
        try:
            from pathlib import Path as _P_re_r4

            _log_r4 = _P_re_r4(_recompute_managed_root) / "_recompute_execute_error.log" if _recompute_managed_root is not None else _P_re_r4("C:/tmp/_recompute_error.log")
            _log_r4.parent.mkdir(parents=True, exist_ok=True)
            _log_r4.write_text(_recompute_error, encoding="utf-8")
        except Exception:
            pass
        pass

    return RecomputeResponse(
        correction_id=str(rec["correction_id"]),
        correction_kind=str(rec["correction_kind"]),
        run_id=str(rec["run_id"]),
        workspace_id=str(rec["workspace_id"]),
        project_id=str(rec["project_id"]),
        affected_chunk_ids=list(rec["affected_chunk_ids"]),
        result_hash=str(rec["result_hash"]),
        created=bool(rec.get("created", created)),
        reused=bool(rec.get("reused", not created)),
        revision_before=rec.get("revision_before"),
        revision_after=rec.get("revision_after"),
        provenance=rec.get("provenance"),
    ).model_dump(mode="json")


@router.get("/full-apply/{run_id}/recompute/{correction_id}", tags=["s10-full-apply"])
def get_recompute_status(
    run_id: str,
    correction_id: str,
    session: SessionDep,
    workspace_id: str = Query(default=WORKSPACE_ID, min_length=1),
    project_id: str | None = Query(default=None),
) -> dict[str, Any]:
    from sqlalchemy import text as _t

    from app.services.s10_recompute import S10RecomputeNotFoundError, S10RecomputeService

    svc = S10RecomputeService(session)
    try:
        rec = svc.get_record(workspace_id, str(correction_id))
    except S10RecomputeNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    if str(rec["run_id"]) != run_id:
        raise HTTPException(status_code=404, detail="correction run_id mismatch")
    if project_id is not None and str(rec["project_id"]) != project_id:
        raise HTTPException(status_code=404, detail="correction not in project")
    cp = session.execute(_t("SELECT next_index, executed_json, completed FROM s10_recompute_checkpoint WHERE correction_id=:cid AND workspace_id=:ws"), {"cid": str(correction_id), "ws": workspace_id}).mappings().first()
    checkpoint = None
    if cp is not None:
        try:
            import json as _j

            executed = _j.loads(str(cp["executed_json"]))
        except Exception:
            executed = []
        checkpoint = {"next_index": int(cp["next_index"]), "executed": executed, "completed": bool(cp["completed"])}
    out = dict(rec)
    out["checkpoint"] = checkpoint
    return out


