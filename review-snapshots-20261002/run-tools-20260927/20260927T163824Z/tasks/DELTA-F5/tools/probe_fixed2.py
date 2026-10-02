"""DELTA-F5 probe v2: exact per-frame strip equality + QC seam on the real inputs."""

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
    managed = OUT / "managed"
    src_path = managed / "src/source_12s.mp4"
    server = R3 / "raw/renders/server_output/s10_full_apply" / RUN_ID
    db_path = OUT / "probe.db"

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    session_factory = sessionmaker(bind=engine)

    chunk_specs = [
        ("sc-f67c96", 0, 119),
        ("sc-7154cb", 120, 239),
        ("sc-d7b9f0", 240, 359),
    ]
    chunks = []
    raw_chunks = {}
    for shot, start, end in chunk_specs:
        rel = f"chunks/{shot}.mp4"
        raw_chunks[shot] = decode_rgb_frames(managed / rel)
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

    declaration = jobs._publication_geometry_declaration(
        {"profile_id": "wan_animate2_int8_pad640x368_cacheoff"}
    )
    manifest = {
        "source_media_rel": "src/source_12s.mp4",
        "source_media_sha256": sha_file(src_path),
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
    frames = decode_rgb_frames(managed / rel)
    print("PUBLICATION sha:", sha, "size:", size, "shape:", frames[0].shape, "frames:", len(frames))

    # exact per-frame strip equality: publication frame i == raw chunk frame i rows [4:364]
    exact = 0
    mismatched: list[int] = []
    for shot, start, end in chunk_specs:
        raw = raw_chunks[shot]
        for i in range(end - start + 1):
            expected = raw[i][4:364]
            if np.array_equal(frames[start + i], expected):
                exact += 1
            else:
                mismatched.append(start + i)
    print("exact strip frames:", exact, "/ 360; mismatched:", mismatched[:5])

    src_frames = decode_rgb_frames(src_path)
    print("source shape:", src_frames[0].shape, "count:", len(src_frames))

    from app.services.qc_evidence import measure as qc_measure
    from app.services.qc_evidence import observe as qc_observe

    for name, fn in (("changed_centroid_x", qc_measure.changed_centroid_x),):
        try:
            value = fn(src_frames[0], frames[0])
            print(f"QC {name}: OK ->", value)
        except Exception as exc:
            print(f"QC {name} REFUSED:", getattr(exc, "code", None), "|", exc)
    try:
        mask = qc_observe.changed_mask(
            src_frames[0].mean(axis=2), frames[0].mean(axis=2)
        )
        print("QC changed_mask: OK, changed px:", int(mask.sum()))
    except Exception as exc:
        print("QC changed_mask REFUSED:", getattr(exc, "code", None), "|", exc)

    bad = {"pad": "centered (4+5 rows over 640x360)", "native_output_dims": [640, 368]}
    try:
        jobs._publication_conform(source_shape=(360, 640), render_shape=(368, 640), declaration=bad)
        print("NEGATIVE: NO REFUSAL (BAD)")
    except jobs.S10FullApplyJobError as exc:
        print("NEGATIVE refused:", str(exc)[:140])
    try:
        jobs._publication_conform(source_shape=(360, 640), render_shape=(368, 640), declaration={})
        print("NEGATIVE-MISSING: NO REFUSAL (BAD)")
    except jobs.S10FullApplyJobError as exc:
        print("NEGATIVE-MISSING refused:", str(exc)[:110])
    # identity case: render already at source geometry, no declaration needed
    ident = jobs._publication_conform(
        source_shape=(360, 640), render_shape=(360, 640), declaration={}
    )
    print("IDENTITY conform:", ident)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
