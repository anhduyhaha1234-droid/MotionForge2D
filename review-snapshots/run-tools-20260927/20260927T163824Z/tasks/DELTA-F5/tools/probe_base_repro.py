"""DELTA-F5 repro probe (run on the BASE tree): stitch the REAL run inputs.

Proves the pre-fix assembly rule reproduces the R3 publication byte-for-byte
(sha 6de96ac7...) at 640x368 and that the QC geometry comparison refuses it.

  cd <base tree> && python.exe <this file>
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

BASE_TREE = Path(r"C:/Users/Admin/AppData/Local/Temp/deltaf5_base")
sys.path.insert(0, str(BASE_TREE))

from app.services.renderer_routes.composite import (  # noqa: E402
    canonical_frame_sha256,
    decode_rgb_frames,
)
from app.workflow import s10_full_apply_jobs as jobs  # noqa: E402

R3 = Path(
    "C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/"
    "tasks/MF-DEMO-E2E-R3"
)
RUN_ID = "a94d76d9-8156-4ed2-a717-dd5fb2d733ad"
OUT = Path("C:/Users/Admin/AppData/Local/Temp/deltaf5_repro")


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    managed = OUT / "managed"
    managed.mkdir(parents=True)
    src_rel = "src/source_12s.mp4"
    src_path = managed / src_rel
    src_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(R3 / "raw/source_12s.mp4", src_path)
    src_sha = sha_file(src_path)
    print("SOURCE sha:", src_sha, "size:", src_path.stat().st_size)

    server = R3 / "raw/renders/server_output/s10_full_apply" / RUN_ID
    specs = [
        ("sc-f67c96", 0, 119, "sc-f67c96_00001_.mp4"),
        ("sc-7154cb", 120, 239, "sc-7154cb_00001_.mp4"),
        ("sc-d7b9f0", 240, 359, "sc-d7b9f0_00001_.mp4"),
    ]
    con = sqlite3.connect(str(OUT / "repro.db"))
    con.execute(
        "CREATE TABLE artifact(id TEXT PRIMARY KEY, workspace_id TEXT, kind TEXT,"
        " relative_path TEXT, state TEXT, sha256 TEXT, size_bytes INTEGER, revision INTEGER)"
    )
    chunks = []
    for shot, start, end, name in specs:
        rel = f"chunks/{shot}.mp4"
        target = managed / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(server / name, target)
        sha = sha_file(target)
        print(f"CHUNK {shot} sha: {sha} size: {target.stat().st_size}")
        con.execute(
            "INSERT INTO artifact VALUES (?,?,?,?,?,?,?,?)",
            (f"art-{shot}", "default", "video", rel, "ready", sha, target.stat().st_size, 1),
        )
        frames = decode_rgb_frames(target)
        jobs._write_evidence_sidecar(
            managed,
            Path(rel),
            {
                "decoded_sha256": canonical_frame_sha256(frames),
                "decoded_frame_count": len(frames),
                "fps_num": 30,
                "fps_den": 1,
                "layer_id": "",
                "shot_id": shot,
                "route": "shot_group",
                "effective_adapter": "comfy_shot_engine",
            },
        )
        chunks.append(
            {
                "chunk_id": f"ck_{shot}",
                "shot_id": shot,
                "core_start_frame": start,
                "core_end_frame": end,
                "verified": True,
                "artifact_id": f"art-{shot}",
                "content_hash": "a" * 64,
            }
        )
    con.commit()
    con.close()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    sf = sessionmaker(bind=create_engine(f"sqlite+pysqlite:///{OUT / 'repro.db'}"))
    rel, sha, size, meta = jobs._stitch_shot_chunks(
        managed_root=managed,
        run_id=RUN_ID,
        chunks=chunks,
        session_factory=sf,
        ws="default",
        fps_num=30,
        fps_den=1,
        authority={"probe": True},
        manifest={
            "source_media_rel": src_rel,
            "source_media_sha256": src_sha,
            "source_media_size_bytes": src_path.stat().st_size,
        },
        frame_count=360,
    )
    frames = decode_rgb_frames(managed / rel)
    print("PUBLICATION sha:", sha, "size:", size, "frames:", len(frames), "shape:", frames[0].shape)
    print("R3 published sha:  6de96ac723db87195f23f88397f5450dedaa52ef7aee4a53bd8817be013961f4")
    print("SHA MATCH:", sha == "6de96ac723db87195f23f88397f5450dedaa52ef7aee4a53bd8817be013961f4")
    src_frames = decode_rgb_frames(src_path)
    print("source shape:", src_frames[0].shape)
    from app.services.qc_evidence import measure as qc_measure

    try:
        print("QC measure:", qc_measure.changed_centroid_x(src_frames[0], frames[0]))
    except Exception as exc:
        print("QC measure REFUSED:", getattr(exc, "code", None), "|", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
