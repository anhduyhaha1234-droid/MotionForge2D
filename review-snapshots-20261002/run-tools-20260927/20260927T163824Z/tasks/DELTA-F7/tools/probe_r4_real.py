"""DELTA-F7 live probe — the REAL MF-DEMO-E2E-R4 world.

Run with cwd = the DELTA-F7 worktree (imports ``app`` from there) or set
``F7_WORKTREE``.  Uses the ACTUAL R4 harvested runtime DB + ACTUAL R4
artifacts (source ``fc18e859…``, publication ``075133f3…``) in an isolated
managed root, and regenerates the (unharvested) attach output at its
recorded managed path with the REAL S11 remux engine.  Runs the REAL export
resolution (``resolve_export_audio_source``) over three states:

  1. attach row present   → mode ``original_audio_attach``, artifact
     ``02c9d19e…``, resolved sha == the R4 DB row sha;
  2. attach row removed   → mode ``source_artifact``, artifact
     ``art-src-2b5220``, resolved file == the R4 source;
  3. source detached too  → honest ``absent`` with the measured fallback
     attempts (nothing fabricated).

Measured values only; JSON to stdout.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from sqlalchemy import text

WT = Path(os.environ.get("F7_WORKTREE", ".")).resolve()
sys.path.insert(0, str(WT))

from app.persistence import create_engine_for_path, create_session_factory  # noqa: E402
from app.services import original_audio_remux as remux  # noqa: E402
from app.workflow import s12_export_jobs as jobs  # noqa: E402

R4 = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/"
    "20260927T163824Z/tasks/MF-DEMO-E2E-R4"
)
WS = "default"
VIDEO = "a19be9bb-7b11-47fe-8621-d26a99c7a697"
PUB_REL = "s10_full_apply/7333c9e8-f67e-493a-bbcb-fcb6c5507448/stitch_shot_chunks.mp4"
SRC_REL = f"s10_full_apply/_authority/{VIDEO}/source_12s.mp4"
ATTACH_REL = (
    "artifacts/default/audio/3a1dbde3-27df-4ce3-b2bd-61bfb0ce2101/"
    "attach/original_audio.mp4"
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="f7_r4_"))
    managed = work / "managed"
    (managed / PUB_REL).parent.mkdir(parents=True, exist_ok=True)
    (managed / SRC_REL).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(R4 / "raw/runtime_harvest" / PUB_REL, managed / PUB_REL)
    shutil.copyfile(R4 / "raw/runtime_harvest" / SRC_REL, managed / SRC_REL)
    attach_out = remux.remux_original_audio(
        managed / SRC_REL, (managed / ATTACH_REL).parent
    )
    assert attach_out.status == remux.STATUS_STREAM_COPY, attach_out.status
    regen_attach = Path(attach_out.output_path)
    assert regen_attach.name == "original_audio.mp4"

    db = work / "motionforge.db"
    shutil.copyfile(R4 / "raw/runtime_harvest/data/motionforge.db", db)
    factory = create_session_factory(create_engine_for_path(str(db)))

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    db_attach_sha, db_attach_size = con.execute(
        "SELECT sha256, size_bytes FROM artifact "
        "WHERE id='02c9d19e-1d51-5167-b3b0-e23c1a661bd5'"
    ).fetchone()
    db_src_sha = con.execute(
        "SELECT sha256 FROM artifact WHERE id='art-src-2b5220'"
    ).fetchone()[0]
    con.close()

    out: dict[str, object] = {
        "r4_root": str(R4),
        "managed_root": str(managed),
        "files": {
            "publication_sha": sha(managed / PUB_REL),
            "publication_a0": remux.probe_original_audio(managed / PUB_REL).present,
            "source_sha": sha(managed / SRC_REL),
            "source_ok": remux.probe_original_audio(managed / SRC_REL).present,
            "regen_attach_sha": sha(regen_attach),
            "db_attach_sha": db_attach_sha,
            "db_attach_size": db_attach_size,
            "regen_attach_size": regen_attach.stat().st_size,
            "attach_bytes_match_db": sha(regen_attach) == db_attach_sha,
            "source_sha_match_db": sha(managed / SRC_REL) == db_src_sha,
        },
    }

    def resolve() -> dict[str, object]:
        with factory() as session:
            value, provenance = jobs.resolve_export_audio_source(
                session,
                workspace_id=WS,
                video_item_id=VIDEO,
                source_path=str(managed / PUB_REL),
                managed_root=str(managed),
            )
        payload: dict[str, object] = {
            "audio_value": value,
            "mode": provenance.get("mode"),
            "artifact_id": provenance.get("artifact_id"),
            "sample_rate": provenance.get("sample_rate"),
            "channels": provenance.get("channels"),
            "fallbacks": provenance.get("fallbacks"),
        }
        if value is not None:
            payload["value_sha"] = sha(Path(value))
            payload["value_probe_present"] = remux.probe_original_audio(value).present
        return payload

    case1 = resolve()
    case1["resolved_is_attach"] = case1["audio_value"] == str(regen_attach)
    case1["resolved_sha_matches_db"] = case1.get("value_sha") == db_attach_sha
    out["case1_attach_present"] = case1

    with factory() as session:
        session.execute(
            text(
                "DELETE FROM artifact_owner WHERE owner_type='video_item' "
                "AND owner_id=:v AND purpose='original_audio'"
            ),
            {"v": VIDEO},
        )
        session.commit()
    case2 = resolve()
    case2["resolved_is_source"] = case2["audio_value"] == str(managed / SRC_REL)
    out["case2_attach_removed"] = case2

    with factory() as session:
        session.execute(
            text("UPDATE video_item SET source_artifact_id=NULL WHERE id=:v"),
            {"v": VIDEO},
        )
        session.commit()
    out["case3_source_detached"] = resolve()

    out["verdict"] = {
        "case1_original_audio_attach": bool(
            out["case1_attach_present"]["mode"] == "original_audio_attach"
            and out["case1_attach_present"]["resolved_is_attach"]
            and out["case1_attach_present"]["resolved_sha_matches_db"]
        ),
        "case2_source_artifact": bool(
            out["case2_attach_removed"]["mode"] == "source_artifact"
            and out["case2_attach_removed"]["resolved_is_source"]
        ),
        "case3_honest_absent": bool(
            out["case3_source_detached"]["audio_value"] is None
            and out["case3_source_detached"]["mode"] == "absent"
            and out["case3_source_detached"]["fallbacks"] == []
        ),
        "attach_bytes_are_the_r4_bytes": bool(
            out["files"]["attach_bytes_match_db"]
            and out["files"]["source_sha_match_db"]
        ),
    }
    out["PASS"] = all(out["verdict"].values())
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0 if out["PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
