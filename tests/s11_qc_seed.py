"""S11-T06A1 QC seed infrastructure — repository-fixture seeding (Decision A).

Owned module (W3 write-set).  Seeds QCItems EXCLUSIVELY through the
``QCItemRepository`` (``app.persistence.qc_items``, T02B — import only,
never modified) — there is NO HTTP POST anywhere; tests and later task
suites (T06B golden manifests, T06C acceptance, T05 readiness) seed rows
with this module, exactly what Decision A froze for the whole sprint.

Determinism + idempotency:

- the 7-column natural key
  (workspace_id, project_id, video_item_id, layer_ref_type, layer_ref_id,
  reason_code, evidence_window_key) is derived FULLY from deterministic
  inputs (manifest scenario + reason code), so re-seeding the same fixture
  reuses the same rows (repository atomic ``ON CONFLICT DO NOTHING``,
  C4-F1) — zero duplicates, zero silent overwrite, first evidence kept;
- evidence payloads are minimal-valid and deterministic (schema_version +
  seed_source + manifest media reference) — they carry NO expected
  outcomes and NO measured values (those belong to T06A2/T06B);
- ``seed_workspace_project_video`` (raw SQL upsert) provides the FK chain
  the repository requires (workspace → project → video_item, all RESTRICT).

Seed plans come from the committed media manifests
(``tests/fixtures/s11_qc/media_manifests/*.json``): positive scenarios
seed their listed reason codes; negative scenarios (unsupported container
/ codec, corrupt, no-audio) carry an EMPTY plan — the engine rejects that
media at import, so zero QCItems are seedable against it (production plan
W7: no_audio_source → zero QCItem created).  ``seed_all_reason_codes``
covers the FULL closed set of reason codes on a healthy video_item — the
acceptance-criterion-3 path for T06B/T06C.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.persistence.models import (
    QC_ITEM_SEVERITIES,
    QC_REASON_CODES,
    QCItem,
)
from app.persistence.qc_items import QCItemRecord, QCItemRepository

from s11_qc_media_builders import load_manifest

__all__ = [
    "SEED_DETECTOR",
    "SEED_DETECTOR_REVISION",
    "count_qc_items",
    "list_qc_items",
    "make_evidence",
    "seed_all_reason_codes",
    "seed_qc_items_for_manifest",
    "seed_workspace_project_video",
]

#: Stable detector identity for every seeded item — the seed source, not a
#: real detector (detector/revision/checkpoint_ref lengths are CHECK-bound).
SEED_DETECTOR = "s11-seed-media"
SEED_DETECTOR_REVISION = "1.0.0"

#: Default healthy scenario for the full reason-code sweep.
DEFAULT_SCENARIO = "two_scene_source"

#: Deterministic confidence of a seeded record (derived, not measured).
SEED_CONFIDENCE = 0.9


def seed_workspace_project_video(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
) -> None:
    """Idempotent FK-chain seeding the repository requires (workspace →
    project → video_item, all RESTRICT FKs).  Re-running on the same DB is
    a no-op (``ON CONFLICT DO NOTHING`` per row)."""
    session.execute(
        text(
            "INSERT INTO workspace(id, name) VALUES (:id, :id) "
            "ON CONFLICT(id) DO NOTHING"
        ),
        {"id": workspace_id},
    )
    session.execute(
        text(
            "INSERT INTO project(id, workspace_id, name, description, status) "
            "VALUES (:p, :w, :p, '', 'active') "
            "ON CONFLICT(id) DO NOTHING"
        ),
        {"p": project_id, "w": workspace_id},
    )
    session.execute(
        text(
            "INSERT INTO video_item(id, project_id, title, position, status) "
            "VALUES (:v, :p, :v, 0, 'imported') "
            "ON CONFLICT(id) DO NOTHING"
        ),
        {"v": video_item_id, "p": project_id},
    )


def make_evidence(
    *,
    scenario: str,
    builder: str,
    relative_path: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Minimal-valid deterministic evidence for a seeded QCItem.

    Carries only provenance of the seed/media manifest — NEVER expected
    outcomes or measured values (owner boundaries: T06A2 / T06B).
    """
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "seed_source": "s11_qc_seed",
        "manifest": {
            "scenario": scenario,
            "manifest_version": 1,
        },
        "media": {
            "builder": builder,
            "relative_path": relative_path,
        },
    }
    if extra:
        evidence.update(extra)
    return evidence


def _create_via_repository(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    reason_code: str,
    evidence_window_key: str,
    evidence: Mapping[str, Any],
    severity: str,
    checkpoint_ref: str,
) -> QCItemRecord:
    """Single QCItem creation — the ONLY write path (repository, Decision
    A).  A duplicate natural key atomically reuses the existing row."""
    assert reason_code in QC_REASON_CODES, f"unknown reason_code {reason_code!r}"
    assert severity in QC_ITEM_SEVERITIES, f"unknown severity {severity!r}"
    return QCItemRepository(session).create(
        workspace_id=workspace_id,
        project_id=project_id,
        video_item_id=video_item_id,
        layer_ref_type="video_item",
        layer_ref_id=video_item_id,
        reason_code=reason_code,
        evidence_window_key=evidence_window_key,
        evidence=evidence,
        severity=severity,
        category=reason_code,  # 1:1 reason_code <-> category taxonomy
        detector=SEED_DETECTOR,
        detector_revision=SEED_DETECTOR_REVISION,
        confidence=SEED_CONFIDENCE,
        confidence_source="derived",
        checkpoint_ref=checkpoint_ref,
    )


def seed_qc_items_for_manifest(
    session: Session,
    manifest: dict[str, Any],
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
) -> list[QCItemRecord]:
    """Seed the manifest's deterministic plan: one QCItem per reason code
    in ``seed_plan`` (video-item layer).  Idempotent by natural key —
    re-seeding returns the SAME records (reused rows, first evidence kept).

    Negative scenarios carry an empty plan → no rows are created (engine
    rejects that media at import; zero QCItems seedable against it).
    """
    scenario = manifest["scenario"]
    plan = manifest["seed_plan"]
    severity = plan["severity"]
    media = manifest["media"]
    checkpoint_ref = f"s11-t06a1:{scenario}"
    records: list[QCItemRecord] = []
    for reason_code in plan["reason_codes"]:
        records.append(
            _create_via_repository(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=video_item_id,
                reason_code=reason_code,
                evidence_window_key=f"{scenario}:{reason_code}",
                evidence=make_evidence(
                    scenario=scenario,
                    builder=media["builder"],
                    relative_path=media["relative_path"],
                ),
                severity=severity,
                checkpoint_ref=checkpoint_ref,
            )
        )
    return records


def seed_all_reason_codes(
    session: Session,
    *,
    workspace_id: str,
    project_id: str,
    video_item_id: str,
    scenario: str = DEFAULT_SCENARIO,
) -> list[QCItemRecord]:
    """Seed ONE QCItem for EVERY closed reason code (the full
    ``QC_REASON_CODES`` set) against a healthy video_item — acceptance
    criterion 3's path.  The media reference is the default healthy
    scenario's manifest.  Idempotent by natural key."""
    manifest = load_manifest(scenario)
    media = manifest["media"]
    checkpoint_ref = f"s11-t06a1:{scenario}"
    records: list[QCItemRecord] = []
    for reason_code in QC_REASON_CODES:
        records.append(
            _create_via_repository(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                video_item_id=video_item_id,
                reason_code=reason_code,
                evidence_window_key=f"{scenario}:all:{reason_code}",
                evidence=make_evidence(
                    scenario=scenario,
                    builder=media["builder"],
                    relative_path=media["relative_path"],
                ),
                severity=manifest["seed_plan"]["severity"],
                checkpoint_ref=checkpoint_ref,
            )
        )
    return records


def count_qc_items(session: Session) -> int:
    """Total QCItem rows visible to this session (currently uncommitted
    writes included)."""
    return int(
        session.scalar(select(func.count()).select_from(QCItem)) or 0
    )


def list_qc_items(
    session: Session, workspace_id: str
) -> list[QCItemRecord]:
    """All QCItem records in one workspace (deterministic ordering,
    repository read surface — zero leakage across workspaces)."""
    records, _total = QCItemRepository(session).list(workspace_id=workspace_id)
    return records