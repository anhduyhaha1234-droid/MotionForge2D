"""C27 stage-1 worker subprocess (owned, killable).

Runs a REAL chunk-render stage for ONE normal export job: claims the run,
renders every planned chunk (committing completed+verified rows), writes a
READY flag, then parks until the parent KILLS this exact pid.  The parent
then continues the SAME job in a fresh process (same DB, same worker
identity) and must REUSE the verified chunks without re-render.

Usage: python c27_stage1.py <db> <payload.json> <ready-flag>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PROJ))

DB = sys.argv[1]
PAYLOAD_F = sys.argv[2]
FLAG = sys.argv[3]


def main() -> None:
    payload = json.loads(Path(PAYLOAD_F).read_text(encoding="utf-8"))
    from app.persistence import create_engine_for_path, create_session_factory
    from app.persistence.s12_export import S12ExportRepository
    from app.services.s12_export.runner import ExportRunner, RunnerConfig

    factory = create_session_factory(create_engine_for_path(DB))
    with factory() as session:
        repo = S12ExportRepository(session)
        lease = repo.claim_run(payload["run_id"], payload["worker_id"])
        session.commit()
        cfg = RunnerConfig(
            run_id=payload["run_id"],
            workspace_id=payload["workspace_id"],
            worker_id=payload["worker_id"],
            fence_token=lease.fence_token,
            source_path=payload["source_path"],
            fps=float(payload["fps"]),
            chunk_dir=payload["chunk_dir"],
            scratch_dir=payload["scratch_dir"],
            output_path=payload["output_path"],
            audio_source=payload.get("audio_source"),
            max_frames_per_chunk=int(payload.get("max_frames_per_chunk", 120)),
            overlap_frames=int(payload.get("overlap_frames", 4)),
        )
        runner = ExportRunner(repo, cfg)
        specs = runner.ensure_plan()
        runner.render_pending(specs)  # committed+verified chunk rows + files
        session.commit()
    Path(FLAG).write_text("READY", encoding="ascii")
    # Park: parent kills this exact owned pid (never self-exits).
    try:
        time.sleep(600)
    except KeyboardInterrupt:  # pragma: no cover
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()