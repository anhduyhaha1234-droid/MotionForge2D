"""S11-T03F full per-video orchestrator (W7).

OWNER: S11-T03F (this file is the single owner write of the whole block).
Consumes read-only: T03A registry/runner/thresholds, T03B/C/D/E detector
modules (imported through the registry — never modified) and the T02B
QCItemRepository lifecycle API (the ONLY persistence/transition path).

One command on ONE video_item:

``run_full_check_set`` runs the FULL registered check-set (the binding 10:
8 visual/timecode reasons + ``audio_missing`` + ``av_sync_drift``) in
registry registration order, each detector through the T03A common bounded
runner (child-process, deadline + capture cap + cancel), then:

- persists exactly the QCItem candidates each detector reported, through
  ``QCItemRepository.create`` (natural-key idempotent — re-runs reuse rows,
  zero duplicates);
- upstream of persistence, normalizes the two detector output families:
  candidate-style outputs (``qc_items`` / ``items`` keys, or a raw list)
  are whitelist-filtered to the repository ``create`` parameter set and
  persisted directly; measurement-style outputs (``measurements``) are
  persisted through the detector's own ``create_qc_items`` (the detector-
  owned creation path — the orchestrator never re-implements creation);
- runs the RECHECK pass: a pre-existing ``open``/``acknowledged`` item
  whose detector ran successfully auto-resolves (``recheck_resolved``)
  ONLY when the fresh run positively reports the issue gone — positive
  pass coverage for measurement-style detectors, complete-set absence for
  candidate-style detectors — and NEVER when the run output is invalid
  (fail-closed: invalid/hash-mismatch outputs resolve nothing).  An
  ``acknowledged`` item whose issue is still detected returns to ``open``
  via ``recheck_failed``.  Every terminal transition carries FRESH recheck
  evidence built from the run (C2-F2: there is no other code path — the
  test suite scans app/ for terminal-status writers and callers, zero
  exceptions outside this module and the lifecycle owner);
- applies the stale-reopen wiring (GAP-8, service layer shared with T04B):
  ``reopen_stale_evidence`` reopens an acknowledged item to ``open`` with a
  stale flag when superseding evidence arrives (``superseded_by_id``,
  manifest lifecycle, cast revision).  Terminal items are refused — the
  repository's stable transition error propagates, no reversal;
- returns a MEASURED summary: ``created`` / ``reused`` (row-level, natural
  key vs pre-run snapshot), ``resolved_after_recheck``,
  ``not_applicable`` (detectors whose run output is ``not_applicable`` —
  e.g. NO_AUDIO_PRESENT), ``errors`` and per-detector counts — every count
  computed at runtime, never hard-coded.

Bounding: the WHOLE run shares ONE absolute deadline and ONE cancel event;
a detector consumes only the remaining budget (never a fresh fixed window)
and cancellation/deadline stops further scheduling (checks_skipped).  On a
mid-run cancel/deadline the run completes honestly: completed detectors'
results are persisted, the summary records the failure codes, and the
caller may commit (default) or roll back the partial run.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy.orm import Session

from app.persistence.qc_items import (
    QCItemInvalidTransitionError,
    QCItemRecord,
    QCItemRepository,
)
from app.services.qc_checks.registry import get_detector, registry
from app.services.qc_checks.runner import (
    QC_RUNNER_CANCELLED,
    QC_RUNNER_DEADLINE_EXCEEDED,
    QC_RUNNER_INVALID_ARGS,
    QcRunnerError,
    run_detector,
)

#: Stable orchestrator-level error codes.
QC_ORCHESTRATOR_MISSING_ARGS = "QC_ORCHESTRATOR_MISSING_ARGS"
QC_ORCHESTRATOR_PERSIST_ERROR = "QC_ORCHESTRATOR_PERSIST_ERROR"
#: MF-END-22 / P1-03b: a detector that ran but never reached a measurement.
QC_ORCHESTRATOR_INDETERMINATE = "QC_ORCHESTRATOR_INDETERMINATE"

#: Whitelist of ``QCItemRepository.create`` parameters.  Detector
#: candidate payloads may carry extra keys (``status``, ``metric``, ...)
#: that are NOT repository parameters — the orchestrator filters, it never
#: guesses which fields a detector forgot.
_CREATE_PARAMS = frozenset(
    {
        "workspace_id",
        "project_id",
        "video_item_id",
        "layer_ref_type",
        "layer_ref_id",
        "reason_code",
        "evidence_window_key",
        "evidence",
        "severity",
        "category",
        "detector",
        "detector_revision",
        "confidence",
        "confidence_source",
        "checkpoint_ref",
        "segment_row_id",
        "segment_logical_id",
    }
)

#: Run outputs carrying a top-level status may only drive recheck
#: resolution when the fresh result is VALID.  ``invalid`` (e.g. identity
#: hash mismatch -> empty items) must never resolve anything.
_RESOLVE_OK_STATUSES = frozenset({"pass", "warning", "blocker", "not_applicable"})
_INVALID_STATUS = "invalid"

#: MF-END-22 / P1-03b: statuses that mean the detector did NOT reach a
#: measurement.  They are counted as ``indeterminate`` and they falsify
#: zero-item completion — a non-measurement is never a "0 items found" pass
#: (the R4/R5 identity_drift record: ``invalid`` / ``THRESHOLD_INVALID`` with
#: a measured distance of 109.05 and 0 items).
_INDETERMINATE_STATUSES = frozenset({"invalid", "unknown"})

#: Recheck evidence provenance.
_RECHECK_SOURCE = "s11-qc-orchestrator"


@dataclass(frozen=True)
class OrchestratorSummary:
    """Measured result of one full-set orchestrator command.

    Every count is computed at runtime from the actual run (rows created
    vs the pre-run natural-key snapshot, transitions performed, detector
    outputs) — nothing is hard-coded or estimated.
    """

    workspace_id: str
    project_id: str
    video_item_id: str
    run_id: str
    checks_requested: int
    checks_run: int
    checks_skipped: int
    created: int
    reused: int
    resolved_after_recheck: int
    reopened_stale: int
    not_applicable: int
    errors: int
    cancelled: bool
    deadline_exceeded: bool
    run_sec: float
    per_detector: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    indeterminate: int = 0
    indeterminate_detectors: tuple[str, ...] = ()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _run_fingerprint(
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    ordered: list[str],
    detector_args: Mapping[str, Mapping[str, Any]],
) -> str:
    """Deterministic run identity: identical requests -> identical run_id
    (reports/rechecks idempotent, no timestamps/randomness)."""
    payload = {
        "orchestrator": "s11-qc-orchestrator",
        "workspace_id": workspace_id,
        "project_id": project_id,
        "video_item_id": video_item_id,
        "detectors": ordered,
        "detector_args": {name: dict(detector_args.get(name, {})) for name in ordered},
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _natural_key(obj: Any) -> tuple[Any, ...]:
    """Natural-key tuple from a QCItemRecord OR a candidate dict."""
    # Explicit callable annotation: assigning the overloaded ``dict.get`` to
    # a variable would otherwise leak the overloaded type into the lambda
    # branch (mypy assignment error) — both branches satisfy (str) -> Any.
    get: Callable[[str], Any]
    if isinstance(obj, dict):
        get = obj.get
    else:
        get = lambda k: getattr(obj, k)  # noqa: E731
    return (
        get("workspace_id"),
        get("project_id"),
        get("video_item_id"),
        get("layer_ref_type"),
        get("layer_ref_id"),
        get("reason_code"),
        get("evidence_window_key"),
    )


def _module_for(name: str) -> Any:
    spec = get_detector(name)
    module_name, _, _qualname = spec.entry_point.partition(":")
    return importlib.import_module(module_name)


def _output_status(output: Any) -> str | None:
    if not isinstance(output, dict):
        return None
    status = output.get("status")
    if status is not None:
        return str(status)
    measurements = output.get("measurements")
    if isinstance(measurements, list) and measurements:
        severities = {m.get("severity") for m in measurements if m.get("severity")}
        if "blocker" in severities:
            return "blocker"
        if "warning" in severities:
            return "warning"
        return "pass"
    applicability = output.get("applicability")
    if applicability is not None:
        return str(applicability)
    return None


def _output_applicability(output: Any) -> str | None:
    if isinstance(output, dict):
        applicability = output.get("applicability")
        return str(applicability) if applicability is not None else None
    return None


def _output_revision(output: Any) -> str | None:
    if isinstance(output, dict):
        revision = output.get("detector_revision")
        return str(revision) if revision is not None else None
    return None


def _output_invalid(output: Any) -> bool:
    return isinstance(output, dict) and output.get("status") == _INVALID_STATUS


def _candidates_from_output(output: Any) -> list[dict[str, Any]] | None:
    """Extract the QCItem candidate list a detector run reported.

    Returns ``None`` for measurement-style outputs (persistence happens
    through the detector's own ``create_qc_items`` — the ONLY creation
    path that family exposes).
    """
    if isinstance(output, list):
        return [item for item in output if isinstance(item, dict)]
    if not isinstance(output, dict):
        return []
    for key in ("qc_items", "items"):
        value = output.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if "measurements" in output:
        return None
    return []


def _candidate_issue_keys(
    candidates: list[dict[str, Any]] | None,
) -> set[tuple[Any, ...]]:
    return {_natural_key(c) for c in candidates or []}


def _measurement_coverage_pass_keys(
    output: Any, args: Mapping[str, Any]
) -> set[tuple[Any, ...]]:
    """Positive pass coverage: measurement windows the fresh run examined
    and classified as pass (severity None) — the only basis on which a
    measurement-style item may auto-resolve (fail-closed on unexamined
    windows)."""
    keys: set[tuple[Any, ...]] = set()
    measurements = output.get("measurements") if isinstance(output, dict) else None
    if not isinstance(measurements, list):
        return keys
    layer_ref_type = str(args.get("layer_ref_type") or "video_item")
    layer_ref_id = str(args.get("layer_ref_id") or args.get("video_item_id") or "")
    for m in measurements:
        if m.get("severity") is not None:
            continue
        keys.add(
            (
                str(args.get("workspace_id") or ""),
                str(args.get("project_id") or ""),
                str(args.get("video_item_id") or ""),
                layer_ref_type,
                layer_ref_id,
                str(m.get("reason_code") or ""),
                str(m.get("evidence_window_key") or ""),
            )
        )
    return keys


def _recheck_evidence(
    kind: str,
    item: QCItemRecord,
    output: Any,
    run_id: str,
) -> dict[str, Any]:
    """FRESH recheck evidence for one lifecycle transition (C2-F2: every
    terminal transition must carry evidence — this builder is the only
    evidence source the orchestrator uses)."""
    applicability = _output_applicability(output)
    if kind == "failed":
        result = "still_detected"
    elif applicability == "not_applicable":
        result = "not_applicable"
    else:
        result = "pass"
    return {
        "schema_version": 1,
        "recheck": kind,
        "recheck_source": _RECHECK_SOURCE,
        "detector": item.detector,
        "detector_revision": _output_revision(output) or item.detector_revision,
        "reason_code": item.reason_code,
        "evidence_window_key": item.evidence_window_key,
        "run_id": run_id,
        "recheck_result": result,
        "supersedes_item_id": item.id,
    }


def _persist_output(
    session: Session,
    repo: QCItemRepository,
    *,
    detector: str,
    args: Mapping[str, Any],
    output: Any,
) -> list[QCItemRecord]:
    """Persist one detector's fresh output through the repository.

    Candidate-style: whitelist-filtered ``create`` per candidate.  Identity
    is injected from the run scope when a candidate family omits it (T03C
    candidates carry no workspace/project/video ids — the orchestrator's
    per-video scoping is authoritative).

    Measurement-style: the detector's own ``create_qc_items`` (the ONLY
    creation path that family exposes; never re-implemented here).
    """
    candidates = _candidates_from_output(output)
    records: list[QCItemRecord] = []
    if candidates is None:
        create_fn = getattr(_module_for(detector), "create_qc_items", None)
        if create_fn is None:
            raise TypeError(
                f"detector {detector!r} emitted a measurement-style output but "
                "has no create_qc_items entry point"
            )
        return list(
            create_fn(
                session,
                dict(args),
                checkpoint_ref=args.get("checkpoint_ref"),
            )
        )
    identity = {
        "workspace_id": str(args.get("workspace_id") or ""),
        "project_id": str(args.get("project_id") or ""),
        "video_item_id": str(args.get("video_item_id") or ""),
        "layer_ref_type": str(args.get("layer_ref_type") or "video_item"),
        "layer_ref_id": str(args.get("layer_ref_id") or args.get("video_item_id") or ""),
    }
    for candidate in candidates:
        params = {
            k: candidate[k]
            for k in _CREATE_PARAMS
            if k in candidate
        }
        for k in ("workspace_id", "project_id", "video_item_id", "layer_ref_id"):
            if k not in params:
                params[k] = identity[k]
        if "layer_ref_type" not in params:
            params["layer_ref_type"] = identity["layer_ref_type"]
        records.append(repo.create(**params))
    return records


def _apply_recheck(
    session: Session,
    repo: QCItemRepository,
    *,
    detector: str,
    args: Mapping[str, Any],
    output: Any,
    run_records: list[QCItemRecord],
    candidates: list[QCItemRecord],
    workspace_id: str,
    run_id: str,
) -> int:
    """Recheck pass for ONE detector against its pre-existing open/
    acknowledged items.  Returns the number of items auto-resolved.

    Resolution is ONLY allowed when the fresh run is valid and positively
    reports the item's window issue gone:
    - candidate-style: the item's natural key is absent from the fresh
      complete-set issue report;
    - measurement-style: the item's window was re-examined and classified
      pass (severity None).
    A still-detected acknowledged item returns to ``open`` via
    ``recheck_failed`` (fresh evidence).  Everything else stays untouched.
    """
    if _output_invalid(output):
        return 0  # fail-closed: invalid output resolves nothing
    issue_keys = _candidate_issue_keys_cache(run_records)
    measurement_style = isinstance(output, dict) and isinstance(
        output.get("measurements"), list
    )
    coverage_pass = (
        _measurement_coverage_pass_keys(output, args) if measurement_style else set()
    )

    resolved = 0
    for item in candidates:
        if item.detector != detector:
            continue
        key = _natural_key(item)
        if key in issue_keys:
            if item.status == "acknowledged":
                repo.recheck_failed(
                    item.id,
                    workspace_id,
                    evidence=_recheck_evidence("failed", item, output, run_id),
                )
            continue  # still open (or reopened open) — not resolved
        if measurement_style:
            if key not in coverage_pass:
                continue  # window not positively re-examined — fail-closed
        repo.recheck_resolved(
            item.id,
            workspace_id,
            evidence=_recheck_evidence("resolved", item, output, run_id),
        )
        resolved += 1
    return resolved


def _candidate_issue_keys_cache(
    run_records: list[QCItemRecord],
) -> set[tuple[Any, ...]]:
    return {_natural_key(r) for r in run_records}


def _entry(
    detector: str,
    *,
    ran: bool = False,
    skipped: bool = False,
    status: str | None = None,
    applicability: str | None = None,
    items_found: int = 0,
    error_code: str | None = None,
    error: str | None = None,
    run_sec: float = 0.0,
) -> dict[str, Any]:
    return {
        "detector": detector,
        "ran": ran,
        "skipped": skipped,
        "status": status,
        "applicability": applicability,
        "items_found": items_found,
        "created": 0,
        "reused": 0,
        "resolved_after_recheck": 0,
        "error_code": error_code,
        "error": error,
        "run_sec": run_sec,
    }


def reopen_stale_evidence(
    repo: QCItemRepository,
    item: QCItemRecord,
    *,
    workspace_id: str,
    superseded_by_id: str,
    supersession_reason: str,
    manifest_revision: str | None = None,
    cast_revision: str | None = None,
) -> QCItemRecord:
    """GAP-8 stale-reopen hook (service layer — shared with T04B).

    When superseding evidence arrives (``superseded_by_id`` referencing a
    manifest/cast lifecycle change), an ACKNOWLEDGED item reopens to
    ``open`` with the stale flag recorded in its fresh recheck evidence.
    An already-open item is a no-op (nothing to transition).  Terminal
    items (resolved/dismissed) are REFUSED with the repository's stable
    transition error — terminal states are terminal (T02B), a stale signal
    can never reverse them.
    """
    if item.status == "acknowledged":
        evidence = {
            "schema_version": 1,
            "recheck": "stale_superseded",
            "recheck_source": _RECHECK_SOURCE,
            "stale": True,
            "superseded_by_id": superseded_by_id,
            "supersession_reason": supersession_reason,
            "manifest_revision": manifest_revision,
            "cast_revision": cast_revision,
            "supersedes_item_id": item.id,
        }
        return repo.recheck_failed(item.id, workspace_id, evidence=evidence)
    if item.status == "open":
        return item
    raise QCItemInvalidTransitionError(
        f"QCItem {item.id!r} is terminally in status {item.status!r} and "
        "cannot be reopened by a stale supersession"
    )


def run_full_check_set(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    detector_args: Mapping[str, Mapping[str, Any]],
    detectors: Sequence[str] | None = None,
    deadline_sec: float,
    capture_cap_bytes: int,
    cancel_event: threading.Event | None = None,
    commit: bool = True,
    lifecycle_signal: Mapping[str, Any] | None = None,
) -> OrchestratorSummary:
    """Run the FULL registered check-set on ONE video_item in ONE command.

    Accepts a band of the registered set via ``detectors`` (default: every
    registered detector, in registration order).  Bounds (``deadline_sec``
    for the WHOLE run, ``capture_cap_bytes``, ``cancel_event``) apply to
    every detector AND to the scheduling between them.  Commits once at the
    end unless ``commit=False`` (the caller then owns commit/rollback,
    repository contract).  ``lifecycle_signal`` wires the GAP-8 stale
    reopen for an acknowledged item named by ``superseded_by_id``.

    Fail-closed: unknown requested detectors and non-positive bounds raise
    ``QcRunnerError`` (stable codes) BEFORE any spawn or write; a
    registered detector without args is recorded as
    ``QC_ORCHESTRATOR_MISSING_ARGS`` and never runs silently; a cancelled/
    deadline-exhausted run stops scheduling (skipped) and reports the
    partial result honestly.
    """
    if not all(
        isinstance(v, str) and v
        for v in (workspace_id, project_id, video_item_id)
    ):
        raise QcRunnerError(
            QC_RUNNER_INVALID_ARGS,
            "workspace_id/project_id/video_item_id must be non-empty strings",
        )
    if deadline_sec <= 0 or capture_cap_bytes <= 0:
        raise QcRunnerError(
            QC_RUNNER_INVALID_ARGS,
            "deadline_sec and capture_cap_bytes must be positive",
        )

    registered = registry.names()
    registered_set = set(registered)
    requested = list(detectors) if detectors is not None else registered
    unknown = [name for name in requested if name not in registered_set]
    if unknown:
        raise QcRunnerError(
            QC_ORCHESTRATOR_MISSING_ARGS,
            f"unregistered detectors requested: {sorted(unknown)}",
        )
    # canonical order: registry registration order, restricted to the request
    ordered = [name for name in registered if name in set(requested)]

    run_id = _run_fingerprint(
        workspace_id, project_id, video_item_id, ordered, detector_args
    )
    started = time.monotonic()
    deadline_abs = started + deadline_sec
    repo = QCItemRepository(session)

    pre_existing, _total = repo.list(
        workspace_id, video_item_id=video_item_id, limit=1_000_000
    )
    pre_keys = {_natural_key(r) for r in pre_existing}
    recheck_candidates = [
        r for r in pre_existing if r.status in ("open", "acknowledged")
    ]

    per_detector: dict[str, dict[str, Any]] = {}
    run_records: dict[str, list[QCItemRecord]] = {}
    checks_run = 0
    checks_skipped = 0
    resolved_total = 0
    not_applicable_total = 0
    errors_total = 0
    indeterminate_total = 0
    indeterminate_detectors: list[str] = []
    cancelled = False
    deadline_exceeded = False

    for name in ordered:
        entry = _entry(name)
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            entry.update(
                skipped=True,
                error_code=QC_RUNNER_CANCELLED,
                error="run cancelled before detector scheduling",
            )
            checks_skipped += 1
            per_detector[name] = entry
            continue
        remaining = deadline_abs - time.monotonic()
        if remaining <= 0:
            deadline_exceeded = True
            entry.update(
                skipped=True,
                error_code=QC_RUNNER_DEADLINE_EXCEEDED,
                error="overall run deadline exhausted before detector scheduling",
            )
            checks_skipped += 1
            per_detector[name] = entry
            continue

        args_raw = detector_args.get(name)
        if args_raw is None:
            errors_total += 1
            entry.update(
                error_code=QC_ORCHESTRATOR_MISSING_ARGS,
                error=f"no args supplied for registered detector {name!r}",
            )
            per_detector[name] = entry
            continue
        identity = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "video_item_id": video_item_id,
            "layer_ref_type": "video_item",
            "layer_ref_id": video_item_id,
        }
        args = json.loads(
            _canonical_json({**identity, **dict(args_raw)})
        )

        det_started = time.monotonic()
        try:
            run = run_detector(
                name,
                args=args,
                deadline_sec=remaining,
                capture_cap_bytes=capture_cap_bytes,
                cancel_event=cancel_event,
            )
        except QcRunnerError as exc:
            errors_total += 1
            if exc.code == QC_RUNNER_CANCELLED:
                cancelled = True
            if exc.code == QC_RUNNER_DEADLINE_EXCEEDED:
                deadline_exceeded = True
            entry.update(
                error_code=exc.code,
                error=exc.message,
                run_sec=time.monotonic() - det_started,
            )
            per_detector[name] = entry
            continue
        except Exception as exc:  # registry/unexpected — fail-closed per detector
            errors_total += 1
            entry.update(
                error_code=getattr(exc, "code", type(exc).__name__),
                error=str(exc),
                run_sec=time.monotonic() - det_started,
            )
            per_detector[name] = entry
            continue

        output = run.output
        entry.update(
            ran=True,
            status=_output_status(output),
            applicability=_output_applicability(output),
            items_found=len(
                _candidates_from_output(output)
                or _measurement_issue_count(output)
                or []
            ),
            run_sec=run.run_sec,
        )
        if _output_applicability(output) == "not_applicable":
            not_applicable_total += 1
        if str(_output_status(output) or "") in _INDETERMINATE_STATUSES:
            # MF-END-22 / P1-03b: the detector ran but never reached a
            # measurement (e.g. identity_drift invalid/THRESHOLD_INVALID with
            # a measured distance and 0 items).  Recorded per detector AND
            # aggregated, so the completion block can falsify zero-item
            # evidence instead of reporting a clean "0 issues" run.
            indeterminate_total += 1
            indeterminate_detectors.append(name)
            entry.update(
                indeterminate=True,
                indeterminate_code=str(
                    (output or {}).get("code")
                    if isinstance(output, dict)
                    else ""
                )
                or QC_ORCHESTRATOR_INDETERMINATE,
            )
        checks_run += 1

        try:
            with session.begin_nested():
                records = _persist_output(
                    session, repo, detector=name, args=args, output=output
                )
        except Exception as exc:
            errors_total += 1
            entry.update(
                error_code=QC_ORCHESTRATOR_PERSIST_ERROR,
                error=f"{type(exc).__name__}: {exc}",
            )
            per_detector[name] = entry
            continue
        run_records[name] = records
        entry["items_found"] = max(
            entry["items_found"],
            len(_candidate_issue_keys_cache(records)),
        )

        resolved_for_detector = _apply_recheck(
            session,
            repo,
            detector=name,
            args=args,
            output=output,
            run_records=records,
            candidates=recheck_candidates,
            workspace_id=workspace_id,
            run_id=run_id,
        )
        if resolved_for_detector:
            entry["resolved_after_recheck"] = resolved_for_detector
            resolved_total += resolved_for_detector
        per_detector[name] = entry

    # ── measured row-level accounting (final session state vs pre-run) ────
    created_total = 0
    reused_total = 0
    for name, records in run_records.items():
        new_rows = [
            r for r in records if _natural_key(r) not in pre_keys
        ]
        reused_rows = [
            r for r in records if _natural_key(r) in pre_keys
        ]
        per_detector[name]["created"] = len(new_rows)
        per_detector[name]["reused"] = len(reused_rows)
        created_total += len(new_rows)
        reused_total += len(reused_rows)

    # ── GAP-8 stale reopen wiring (service hook shared with T04B) ──────────
    reopened_stale_total = 0
    if lifecycle_signal:
        superseded_by_id = lifecycle_signal.get("superseded_by_id")
        if superseded_by_id:
            current, _total2 = repo.list(
                workspace_id, video_item_id=video_item_id, limit=1_000_000
            )
            for item in current:
                if item.status != "acknowledged":
                    continue
                if item.id != superseded_by_id:
                    continue
                reopen_stale_evidence(
                    repo,
                    item,
                    workspace_id=workspace_id,
                    superseded_by_id=str(superseded_by_id),
                    supersession_reason=str(
                        lifecycle_signal.get("supersession_reason")
                        or "manifest lifecycle superseded"
                    ),
                    manifest_revision=lifecycle_signal.get("manifest_revision"),
                    cast_revision=lifecycle_signal.get("cast_revision"),
                )
                reopened_stale_total += 1

    if commit:
        session.commit()

    return OrchestratorSummary(
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        run_id=run_id,
        checks_requested=len(ordered),
        checks_run=checks_run,
        checks_skipped=checks_skipped,
        created=created_total,
        reused=reused_total,
        resolved_after_recheck=resolved_total,
        reopened_stale=reopened_stale_total,
        not_applicable=not_applicable_total,
        errors=errors_total,
        cancelled=cancelled,
        deadline_exceeded=deadline_exceeded,
        run_sec=time.monotonic() - started,
        per_detector=per_detector,
        indeterminate=indeterminate_total,
        indeterminate_detectors=tuple(indeterminate_detectors),
    )


def _measurement_issue_count(output: Any) -> list[Any] | None:
    """Issue count for measurement-style outputs (severity-bearing
    measurements) — used only for the summary's ``items_found``."""
    measurements = output.get("measurements") if isinstance(output, dict) else None
    if not isinstance(measurements, list):
        return None
    return [m for m in measurements if m.get("severity") is not None]