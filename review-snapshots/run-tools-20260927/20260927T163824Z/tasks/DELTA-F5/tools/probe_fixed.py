"""DELTA-F5 probe (fixed code): stitch the REAL run inputs + QC geometry seam.

  python.exe C:/Users/Admin/AppData/Local/Temp/deltaf5_tools/probe_fixed.py
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F5")

import numpy as np  # noqa: E402

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
OUT = Path("C:/Users/Admin/AppData/Local/Temp/deltaf5_probe")


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
    chunk_specs = [
        ("sc-f67c96", 0, 119, "sc-f67c96_00001_.mp4"),
        ("sc-7154cb", 120, 239, "sc-7154cb_00001_.mp4"),
        ("sc-d7b9f0", 240, 359, "sc-d7b9f0_00001_.mp4"),
    ]
    db_path = OUT / "probe.db"
    con = sqlite3.connect(str(db_path))
    con.execute(
        "CREATE TABLE artifact(id TEXT PRIMARY KEY, workspace_id TEXT, kind TEXT,"
        " relative_path TEXT, state TEXT, sha256 TEXT, size_bytes INTEGER, revision INTEGER)"
    )
    chunks = []
    raw_chunks = {}
    for shot, start, end, name in chunk_specs:
        rel = f"chunks/{shot}.mp4"
        target = managed / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(server / name, target)
        sha = sha_file(target)
        print(f"CHUNK {shot} sha: {sha} size: {target.stat().st_size}")
        art_id = f"art-{shot}"
        con.execute(
            "INSERT INTO artifact VALUES (?,?,?,?,?,?,?,?)",
            (art_id, "default", "video", rel, "ready", sha, target.stat().st_size, 1),
        )
        frames = decode_rgb_frames(target)
        raw_chunks[shot] = frames
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
                "artifact_id": art_id,
                "content_hash": "a" * 64,
            }
        )
    con.commit()
    con.close()

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    session_factory = sessionmaker(bind=engine)

    declaration = jobs._publication_geometry_declaration(
        {"profile_id": "wan_animate2_int8_pad640x368_cacheoff"}
    )
    print("DECLARATION:", declaration)

    manifest = {
        "source_media_rel": src_rel,
        "source_media_sha256": src_sha,
        "source_media_size_bytes": src_path.stat().st_size,
    }
    rel, sha, size, meta = jobs._stitch_shot_chunks(
        managed_root=managed,
        run_id=RUN_ID,
        chunks=chunks,
        session_factory=session_factory,
        ws="default",
        fps_num=30,
        fps_den=1,
        authority={"probe": True},
        manifest=manifest,
        frame_count=360,
        pad=declaration,
    )
    out = managed / rel
    frames = decode_rgb_frames(out)
    print("PUBLICATION sha:", sha, "size:", size, "frames:", len(frames), "shape:", frames[0].shape)
    print("R3 base sha (must DIFFER now): 6de96ac723db87195f23f88397f5450dedaa52ef7aee4a53bd8817be013961f4")
    print("conform meta:", meta["conform"])
    print("publication_geometry:", meta["publication_geometry"])

    # the conform must be EXACTLY the declared center strip of the raw chunk frames
    strip = raw_chunks["sc-f67c96"][4:364]
    same = all(
        np.array_equal(frames[i], strip[i]) for i in range(0, 120, 17)
    )
    print("strip-equality sample (chunk0 [4:364] vs publication):", same)
    print("publication[0] vs chunk0[4]:", np.array_equal(frames[0], raw_chunks["sc-f67c96"][4]))
    print("publication[119] vs chunk0[363]:", np.array_equal(frames[119], raw_chunks["sc-f67c96"][363]))
    print("publication[120] vs chunk1[4]:", np.array_equal(frames[120], raw_chunks["sc-7154cb"][4]))
    print("publication[359] vs chunk2[363]:", np.array_equal(frames[359], raw_chunks["sc-d7b9f0"][363]))

    src_frames = decode_rgb_frames(src_path)
    print("source shape:", src_frames[0].shape, "count:", len(src_frames))

    from app.services.qc_evidence import measure as qc_measure

    try:
        value = qc_measure.changed_centroid_x(src_frames[0], frames[0])
        print("QC measure: OK, centroid:", value)
    except Exception as exc:
        print("QC measure REFUSED:", getattr(exc, "code", None), "|", exc)

    # negative control: a declaration that lies about the pad rows
    bad = {"pad": "centered (4+5 rows over 640x360)", "native_output_dims": [640, 368]}
    try:
        jobs._publication_conform(
            source_shape=(360, 640), render_shape=(368, 640), declaration=bad
        )
        print("NEGATIVE: NO REFUSAL (BAD)")
    except jobs.S10FullApplyJobError as exc:
        print("NEGATIVE refused:", str(exc)[:120])
    # negative control: no declaration at all
    try:
        jobs._publication_conform(
            source_shape=(360, 640), render_shape=(368, 640), declaration={}
        )
        print("NEGATIVE-MISSING: NO REFUSAL (BAD)")
    except jobs.S10FullApplyJobError as exc:
        print("NEGATIVE-MISSING refused:", str(exc)[:100])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
