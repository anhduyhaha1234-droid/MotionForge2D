"""S10-T04B-C3 (C6B) — v1 disk-store mirror for the isolated runtime.

Product design (intentional dual-store):
  - POST /api/projects (v1) persists a ProjectData document to
    ``<MOTIONFORGE_ROOT>/projects/<project_id>/project.json`` through
    ``ProjectWorkflowService.create_project`` -> ``ProjectService.create``.
  - The legacy list page (GET /api/projects) reads ONLY that disk store;
    the durable v2 store (SQLite) is a separate authority.

The isolated E2E runtime historically seeded the durable SQLite store only,
so the v1 disk store started EMPTY and GET /api/projects returned [] — a
harness setup gap, not a product defect.  This mirror closes the gap the
same way POST /api/projects would: for every durable project seeded into
the isolated runtime it materialises the canonical v1 disk document with
the SAME identity (durable project id = directory name), so both stores
describe one project, each in its own store.  No response injection, no DB
patching of run/approval truth — pure setup parity.

Contract reproduced exactly (app/workflow/project_workflow.py:61-77 +
app/services/project_service.py:31-35 + app/schemas/__init__.py:926):
  - directory  <projects_root>/<durable_id>/   (uuid passes
    validate_path_identifier: ^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$)
  - document   ProjectData(name=<durable name>, source_video="")
  - timestamps created_at/updated_at = datetime.now(UTC).isoformat()
  - persisted  json.dump(model_dump(), indent=2, default=str)

Idempotent: an existing, loadable project.json is left untouched; a
corrupt existing file fails closed.  Prints MIRROR_V1_SEEDED on success.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path


def _resolve_worktree(cli: str | None) -> Path:
    wt = cli or os.environ.get("MOTIONFORGE_WORKTREE", "")
    if wt and Path(wt).is_dir():
        return Path(wt)
    return Path("C:/Users/Admin/MotionForge2D-worktrees/s08-integration")


def _resolve_run_root(cli: str | None) -> Path:
    rr = cli or os.environ.get("MOTIONFORGE_ROOT", "")
    if not rr or not Path(rr).is_dir():
        raise SystemExit(
            "mirror_v1_disk_projects: --runtime-root or MOTIONFORGE_ROOT required (fail-closed)"
        )
    return Path(rr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S10-C6B v1 disk-store mirror")
    parser.add_argument("--runtime-root", default=None)
    parser.add_argument("--worktree", default=None)
    args, _ = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    worktree = _resolve_worktree(args.worktree)
    run_root = _resolve_run_root(args.runtime_root)
    db_path = run_root / "data" / "motionforge.db"
    projects_root = run_root / "projects"

    if not db_path.is_file():
        raise SystemExit(
            f"mirror_v1_disk_projects: DB missing at {db_path} (run T04C setup first)"
        )

    from app.persistence import create_engine_for_path, create_session_factory
    from app.persistence.models import Project, Workspace
    from app.services.project_service import ProjectService

    WS = "default"

    engine = create_engine_for_path(db_path)
    factory = create_session_factory(engine)

    mirrored: list[str] = []
    skipped: list[str] = []

    with factory() as s:
        if s.get(Workspace, WS) is None:
            raise SystemExit("mirror_v1_disk_projects: workspace 'default' missing")
        rows = s.query(Project).filter_by(workspace_id=WS).all()
        # Read the durable identity inside the session, write the disk mirror
        # after it (no DB writes happen here — the session is read-only).
        identities = [(p.id, p.name) for p in rows]

    now = datetime.now(UTC).isoformat()
    for project_id, name in identities:
        proj_dir = projects_root / project_id
        doc_path = proj_dir / "project.json"
        if doc_path.exists():
            # Fail closed on a corrupt existing document — never mask setup rot.
            ProjectService(doc_path).load()
            skipped.append(project_id)
            continue
        # Exact product contract of POST /api/projects (v1) via
        # ProjectWorkflowService.create_project:
        svc = ProjectService(doc_path)
        svc.create(name=name, source_video="")
        svc.data.created_at = now
        svc.data.updated_at = now
        svc.save()
        # Round-trip validation through the same product service.
        reloaded = ProjectService(doc_path).load()
        if reloaded.name != name or not reloaded.version:
            raise SystemExit(
                f"mirror_v1_disk_projects: round-trip mismatch for {project_id}"
            )
        mirrored.append(project_id)

    engine.dispose()

    summary = {
        "projects_root": str(projects_root),
        "mirrored": mirrored,
        "skipped_existing": skipped,
        "count": len(mirrored) + len(skipped),
    }
    print(
        "MIRROR_V1_SEEDED "
        + json.dumps(summary, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
