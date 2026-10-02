"""DELTA-F5 probe v3: deterministic re-encode proof + QC seam via the real decode path."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, r"C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/DELTA-F5")

import numpy as np  # noqa: E402

from app.services.qc_evidence import measure as qc_measure  # noqa: E402
from app.services.renderer_routes.composite import (  # noqa: E402
    decode_rgb_frames,
    write_frames_mp4,
)
from app.workflow import s10_full_apply_jobs as jobs  # noqa: E402

OUT = Path("C:/Users/Admin/AppData/Local/Temp/deltaf5_probe/managed")
RUN_ID = "a94d76d9-8156-4ed2-a717-dd5fb2d733ad"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite+pysqlite:///{OUT.parent / 'probe.db'}")
    session_factory = sessionmaker(bind=engine)

    chunk_specs = [("sc-f67c96", 0, 119), ("sc-7154cb", 120, 239), ("sc-d7b9f0", 240, 359)]
    chunks = []
    raw_chunks = {}
    strip_timeline = []
    for shot, start, end in chunk_specs:
        raw = decode_rgb_frames(OUT / f"chunks/{shot}.mp4")
        raw_chunks[shot] = raw
        strip_timeline.extend([frame[4:364] for frame in raw])
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
    src_path = OUT / "src/source_12s.mp4"
    manifest = {
        "source_media_rel": "src/source_12s.mp4",
        "source_media_sha256": sha_file(src_path),
        "source_media_size_bytes": src_path.stat().st_size,
    }
    rel, sha, size, meta = jobs._stitch_shot_chunks(
        managed_root=OUT,
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
    print("PUBLICATION sha:", sha, "shape:", decode_rgb_frames(OUT / rel)[0].shape)

    # deterministic re-encode of EXACTLY the declared center strips
    expect_path = OUT.parent / "expected_strip.mp4"
    write_frames_mp4(strip_timeline, expect_path, fps=30.0)
    expect_sha = sha_file(expect_path)
    print("STRIP re-encode sha:", expect_sha)
    print("STRIP == PUBLICATION:", expect_sha == sha)

    # QC seam through the REAL decode path used by the composer
    src_frames = decode_rgb_frames(src_path)
    ren_frames = decode_rgb_frames(OUT / rel)
    print("source shape:", src_frames[0].shape, "render shape:", ren_frames[0].shape)
    indices = [0, 10, 40, 80, 119]
    src_gray = qc_measure.decode_video_frames(src_path, indices, detector="trajectory_drift")
    ren_gray = qc_measure.decode_video_frames(OUT / rel, indices, detector="trajectory_drift")
    print("decoded indices:", sorted(src_gray), sorted(ren_gray))
    observed = []
    for idx in indices:
        value = qc_measure.changed_centroid_x(src_gray[idx], ren_gray[idx])
        observed.append(value)
    print("changed_centroid_x observed:", [None if v is None else round(v, 3) for v in observed])
    print("QC seam OK (no malformed):", all(v is not None for v in observed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
