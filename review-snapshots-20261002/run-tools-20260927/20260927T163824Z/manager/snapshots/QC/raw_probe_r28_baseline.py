"""R28 baseline probe (v2): reproduce the two false-pass defects by MEASUREMENT.

XC-01 variant B (the one QC-R27-01 names as the false pass): a full-canvas
checker support + a clipped render -> the composer finds a rendered-side mask
by OVERLAP, attaches the authority metadata, and the frozen detector STILL
returns items == [] -> a cut object read as zero risk.

XC-02: support pixels are DISCARDED (hollow support still measures).
"""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "product_p1" / "qc_evidence"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import conftest as _conftest  # noqa: E402
from app.services.qc_checks import silhouette_clipping  # noqa: E402
from app.services.qc_evidence import compose_visual_band  # noqa: E402
from app.services.qc_evidence import observe as obs  # noqa: E402

from app.persistence import create_engine_for_path, create_session_factory  # noqa: E402

CANVAS_W, CANVAS_H = _conftest.CANVAS_W, _conftest.CANVAS_H
BOTTOM_B = (_conftest.MASK_B_RECT[0], _conftest.MASK_B_RECT[1],
            _conftest.MASK_B_RECT[2], CANVAS_H)
OUT: dict = {}


def _clip(path, layers) -> bytes:
    """Lossless FFV1 clip with the given composited (rect, frames, level) layers."""
    import cv2

    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"FFV1"),
        float(_conftest.FPS_NUM), (CANVAS_W, CANVAS_H),
    )
    assert writer.isOpened(), "FFV1 writer unavailable"
    for index in range(_conftest.TOTAL_FRAMES):
        frame = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)
        for rect, frames, level in layers:
            if index in frames:
                x0, y0, x1, y1 = rect
                frame[y0:y1, x0:x1] = int(level)
        writer.write(frame)
    writer.release()
    data = path.read_bytes()
    assert data, "clip came back empty"
    return data


def _rewrite_render(factory, managed, ids, layers) -> str:
    import hashlib

    from app.persistence.models import Artifact

    with factory() as session:
        art = session.get(Artifact, ids.render_artifact_id)
        target = Path(managed) / str(art.relative_path)
        data = _clip(target, layers)
        art.sha256 = hashlib.sha256(data).hexdigest()
        art.size_bytes = len(data)
        session.commit()
    return art.sha256


def _rewrite_mask(factory, managed, ids, artifact_id, png_bytes) -> str:
    """Replace ONE published mask's bytes in place (same artifact row)."""
    import hashlib

    from app.persistence.models import Artifact

    with factory() as session:
        art = session.get(Artifact, artifact_id)
        target = Path(managed) / str(art.relative_path)
        target.write_bytes(png_bytes)
        art.sha256 = hashlib.sha256(png_bytes).hexdigest()
        art.size_bytes = len(png_bytes)
        session.commit()
    return art.sha256


def _pnb(rect=None, fill=None) -> bytes:
    array = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    if fill is not None:
        array[:, :] = fill
    if rect is not None:
        x0, y0, x1, y1 = rect
        array[y0:y1, x0:x1] = 255
    buf = io.BytesIO()
    Image.fromarray(array, mode="L").save(buf, format="PNG")
    return buf.getvalue()


def _world(prefix):
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    managed = tmp / "managed"
    managed.mkdir(parents=True, exist_ok=True)
    db = tmp / "p1qc.sqlite"
    from alembic import command

    command.upgrade(_conftest._alembic_config(db), "head")
    factory = create_session_factory(create_engine_for_path(db))
    return factory, managed, _conftest.seed_qc_evidence(factory, managed)


def _compose(factory, managed, ids):
    with factory() as session:
        return compose_visual_band(
            session, managed_root=managed, workspace_id=ids.workspace_id,
            project_id=ids.project_id, video_item_id=ids.video_item_id,
        )


def xc01_variant_b() -> dict:
    """Full-canvas checker support + clipped render: overlap lookup grants authority."""
    factory, managed, ids = _world("p1qc-xc01b-")
    # Segment B's PUBLISHED MASK becomes a full-canvas checker.
    checker = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    ys, xs = np.indices((CANVAS_H, CANVAS_W))
    checker[((ys // 4) + (xs // 4)) % 2 == 1] = 255
    buf = io.BytesIO()
    Image.fromarray(checker, mode="L").save(buf, format="PNG")
    _rewrite_mask(factory, managed, ids, ids.mask_b, buf.getvalue())
    # The render paints segment B clipped at the bottom frame side.
    _rewrite_render(factory, managed, ids, (
        (_conftest.DELTA_RECT, range(0, 10), 8),
        (BOTTOM_B, range(10, _conftest.TOTAL_FRAMES), 8),
        (_conftest.MASK_C_RECT, range(10, _conftest.TOTAL_FRAMES), 8),
    ))
    try:
        composed = _compose(factory, managed, ids)
    except Exception as exc:  # noqa: BLE001
        return {"outcome": "TYPED_REFUSAL", "type": type(exc).__name__,
                "code": getattr(exc, "code", None), "message": str(exc)[:400]}
    args = composed["silhouette_clipping"]
    rows = {row["id"]: row for row in args["segments"]}
    if ids.segment_b not in rows:
        return {"outcome": "segment_b_absent", "segment_ids": sorted(rows)}
    row = rows[ids.segment_b]
    auth = row["clipping_authority"]
    items = silhouette_clipping.detect_silhouette_clipping(copy.deepcopy(args))
    return {
        "outcome": "COMPOSED",
        "measured_bbox": row["bbox"],
        "expected_bbox": row["expected_bbox"],
        "verdict": auth["verdict"],
        "newly_introduced_truncation": auth["newly_introduced_truncation"],
        "detector_clearance": auth["detector_clearance"],
        "rendered_role_extent_bbox": auth["rendered_role_extent_bbox"],
        "measure_authority": auth["measure_authority"],
        "band_flagged": args["clipping_authority"]["newly_introduced_truncation"],
        "detector_items_count": len(items),
        "FALSE_PASS_empty_success": len(items) == 0,
    }


def xc02_support_discarded() -> dict:
    hollow = np.zeros((CANVAS_H, CANVAS_W), dtype=bool)
    hollow[160:200, 300:340] = True
    hollow[172:188, 312:328] = False
    support = hollow.astype(np.uint8) * 255
    full = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    full[160:200, 300:340] = 8
    interior = np.zeros((CANVAS_H, CANVAS_W), dtype=np.uint8)
    interior[172:188, 312:328] = 8
    m_full = obs.supported_object_bbox(full, support=support, region=(300, 160, 340, 200))
    m_int = obs.supported_object_bbox(interior, support=support, region=(300, 160, 340, 200))
    return {
        "full_rect_paint_bbox": [int(v) for v in m_full] if m_full else None,
        "interior_only_paint_bbox": [int(v) for v in m_int] if m_int else None,
        "interior_object_still_attributed": m_int is not None,
        "support_pixels_intersected": False,
    }


def xc01_uniform_support() -> dict:
    """A UNIFORM (all-white) support is accepted as the role's geometry."""
    factory, managed, ids = _world("p1qc-xc01u-")
    _rewrite_mask(factory, managed, ids, ids.mask_b, _pnb(fill=255))
    _rewrite_render(factory, managed, ids, (
        (_conftest.DELTA_RECT, range(0, 10), 8),
        (BOTTOM_B, range(10, _conftest.TOTAL_FRAMES), 8),
        (_conftest.MASK_C_RECT, range(10, _conftest.TOTAL_FRAMES), 8),
    ))
    try:
        composed = _compose(factory, managed, ids)
    except Exception as exc:  # noqa: BLE001
        return {"outcome": "TYPED_REFUSAL", "code": getattr(exc, "code", None),
                "message": str(exc)[:300]}
    rows = {row["id"]: row for row in composed["silhouette_clipping"]["segments"]}
    if ids.segment_b not in rows:
        return {"outcome": "segment_b_absent"}
    row = rows[ids.segment_b]
    return {
        "outcome": "COMPOSED",
        "expected_bbox": row["expected_bbox"],
        "measured_bbox": row["bbox"],
        "verdict": row["clipping_authority"]["verdict"],
    }


def main() -> int:
    OUT["XC01_variantB_overlap_authority"] = xc01_variant_b()
    OUT["XC01_uniform_support"] = xc01_uniform_support()
    OUT["XC02_support_discarded"] = xc02_support_discarded()
    b = OUT["XC01_variantB_overlap_authority"]
    OUT["bottom_line"] = {
        "XC01_empty_success_reproduced": bool(b.get("FALSE_PASS_empty_success")),
        "XC02_support_discarded_reproduced": OUT["XC02_support_discarded"][
            "interior_object_still_attributed"],
    }
    print(json.dumps(OUT, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
