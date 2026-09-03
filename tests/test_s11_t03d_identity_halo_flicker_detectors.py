"""S11-T03D — identity_drift + edge_halo + temporal_flicker detector tests (W6).

C4-F5 binary 5 tests + flip + threshold-derivation-from-T06A2:

1. metadata stays pinned but pixels/visual identity drift crosses the
   boundary -> identity_drift QCItem (blocker/warning per policy);
2. metadata/cast-instance flip even with near-identical pixels -> blocker
   item (fail-closed identity flip, does NOT replace the visual metric);
3. stable pixels + stable metadata -> zero items;
4. re-running the same evidence -> byte-identical result + idempotent
   repository create (same natural key, single row);
5. no reason code is ever UNKNOWN or deferred — every detector returns a
   bound reason code and a stable THRESHOLD_* code.

Cộng (binding block):
- role/instance changing abruptly between adjacent frames vs the cast-pin
  authority (ProjectCastMapping pin + evaluate_compatibility) -> blocker ngay;
- edge_halo: halo around the rendered mask edge vs expected -> warning/blocker
  per the frozen T03A policy;
- temporal_flicker: per-frame metric noise inside a window -> warning/blocker
  per policy;
- thresholds are read from the frozen policy whose boundaries are the T06A2
  calibration raw values (provenance asserted directly against the fixture);
- evidence records artifact hashes, frame/window, mask/crop revision, feature
  revision and measured distance; schema_version=1; content-derived.

Isolation: per-test temp SQLite under the short pytest basetemp; run with
``-p no:cacheprovider`` and MOTIONFORGE_DATABASE_URL stripped.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest  # noqa: F401  # pytest fixtures are auto-discovered in this module
from sqlalchemy.orm import Session

from app.persistence import create_engine_for_path
from app.persistence.models import (
    CORE_POSE_SLOTS,
    Artifact,
    Base,
    Character,
    CharacterAsset,
    CharacterPackVersion,
    ObjectRole,
    ProjectCastMapping,
)
from app.persistence.project_cast import evaluate_compatibility
from app.persistence.qc_items import (
    QCItemRecord,
    QCItemRepository,
    canonical_evidence_json,
)
from app.services.qc_checks import (
    CODE_THRESHOLD_BLOCKER,
    CODE_THRESHOLD_INVALID,
    CODE_THRESHOLD_PASS,
    CODE_THRESHOLD_WARNING,
    classify,
    get_threshold,
    load_policy,
    registry,
)
from app.services.qc_checks.edge_halo import (
    detect as detect_halo,
    REASON_CODE as HALO_CODE,
)
from app.services.qc_checks.identity_drift import (
    detect as detect_identity,
    REASON_CODE as IDENTITY_CODE,
)
from app.services.qc_checks.temporal_flicker import (
    detect as detect_flicker,
    REASON_CODE as FLICKER_CODE,
)

WS = "ws-t03d"
P1 = "p-t03d"
V1 = "v-t03d"
GW = 8  # grayscale crop geometry (8x8)
GH = 8

_THRESHOLD_CODES = {
    CODE_THRESHOLD_PASS,
    CODE_THRESHOLD_WARNING,
    CODE_THRESHOLD_BLOCKER,
    CODE_THRESHOLD_INVALID,
}


# ── DB seeding (repository.create + evaluate_compatibility need FK chains) ──

def _seed_base(engine: Any) -> None:
    """Seed workspace/project/video_item the repository requires."""
    with engine.begin() as conn:
        conn.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO workspace(id,name) VALUES (:w,:w)"
            ),
            {"w": WS},
        )
        conn.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO project(id,workspace_id,name,description,status) "
                "VALUES (:p,:w,'ProjT03D','','active')"
            ),
            {"p": P1, "w": WS},
        )
        conn.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO video_item(id,project_id,title,position,status) "
                "VALUES (:v,:p,'VidT03D',0,'imported')"
            ),
            {"v": V1, "p": P1},
        )


def _fresh_engine(tmp_path: Path) -> Any:
    engine = create_engine_for_path(tmp_path / "t03d.db")
    Base.metadata.create_all(engine)
    _seed_base(engine)
    return engine


# ── identity fixtures ───────────────────────────────────────────────────────

def _crop(base: float = 100.0) -> dict[str, Any]:
    """8x8 flat grayscale crop; content-derived sha256 from the pixels."""
    pixels = [[int(base)] * GW for _ in range(GH)]
    raw = json.dumps(pixels, separators=(",", ":")).encode("utf-8")
    return {
        "width": GW,
        "height": GH,
        "pixels": pixels,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _sha256_of_pixels(pixels: list[list[int]]) -> str:
    raw = json.dumps(pixels, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _identity_args(*, delta: float, meta_deltas: list[bool], **over: Any) -> dict[str, Any]:
    """Identity detector args: pinned reference + N frames.

    ``meta_deltas[i]`` marks frame i as carrying flipped metadata.
    """
    ref = _crop(100.0)
    frames: list[dict[str, Any]] = []
    for i, flipped in enumerate(meta_deltas):
        pixels = [[int(100.0 + delta)] * GW for _ in range(GH)]
        frames.append(
            {
                "frame_index": i,
                "artifact_id": f"art-id-{i}",
                "sha256": _sha256_of_pixels(pixels),
                "crop": {
                    "width": GW,
                    "height": GH,
                    "pixels": pixels,
                },
                "metadata": {
                    "role_id": "role-flip" if flipped else "role-pinned",
                    "instance_id": "inst-pinned",
                    "cast_pin_ref": "cast-pin-1",
                },
            }
        )
    args: dict[str, Any] = {
        "workspace_id": WS,
        "project_id": P1,
        "video_item_id": V1,
        "layer_ref_type": "video_item",
        "layer_ref_id": V1,
        "checkpoint_ref": "ckpt-t03d-1",
        "segment_row_id": None,
        "segment_logical_id": None,
        "pinned_reference": {
            "artifact_id": "art-ref",
            "sha256": ref["sha256"],
            "crop_revision": "1.0.0",
            "crop": {"width": GW, "height": GH, "pixels": ref["pixels"]},
        },
        "cast_pin": {
            "object_role_id": "role-pinned",
            "character_id": "char-1",
            "pack_version_id": "pack-1",
            "revision": 1,
            "expected_metadata": {
                "role_id": "role-pinned",
                "instance_id": "inst-pinned",
                "cast_pin_ref": "cast-pin-1",
            },
            "compatible": True,
            "compatibility_reasons": [],
        },
        "frames": frames,
    }
    args.update(over)
    return args


# ── halo fixtures ───────────────────────────────────────────────────────────

def _disc_mask(grid: int, inner_r: float, halo_r: float) -> list[list[int]]:
    """Discrete binary mask sampling the EXACT T06A2 geometry (half-open
    ring): a pixel is inside when its continuous distance d satisfies
    ``d < inner_r + halo_r``; the halo ring between expected (``d < inner_r``)
    and rendered (``d < inner_r + halo_r``) is therefore
    ``inner_r <= d < inner_r + halo_r`` — byte-identical to the calibration
    fixture's ring sampling, so measured widths equal the raw values."""
    center = grid / 2.0
    mask: list[list[int]] = []
    for y in range(grid):
        row: list[int] = []
        for x in range(grid):
            d = math.sqrt((x - center) ** 2 + (y - center) ** 2)
            row.append(1 if d < inner_r + halo_r else 0)
        mask.append(row)
    return mask


def _halo_args(*, halo_r: float, grid: int = 200, inner_r: float = 40.0) -> dict[str, Any]:
    expected_px = _disc_mask(grid, inner_r, 0.0)
    rendered_px = _disc_mask(grid, inner_r, halo_r)
    return {
        "workspace_id": WS,
        "project_id": P1,
        "video_item_id": V1,
        "layer_ref_type": "video_item",
        "layer_ref_id": V1,
        "checkpoint_ref": "ckpt-t03d-halo",
        "frame_index": 10,
        "mask_revision": "2.1.0",
        "inner_radius_px": inner_r,
        "rendered": {
            "artifact_id": "art-rendered-halo",
            "sha256": _sha256_of_pixels(rendered_px),
            "mask": {"width": grid, "height": grid, "pixels": rendered_px},
        },
        "expected": {
            "artifact_id": "art-expected-mask",
            "sha256": _sha256_of_pixels(expected_px),
            "mask": {"width": grid, "height": grid, "pixels": expected_px},
        },
    }


# ── flicker fixtures ────────────────────────────────────────────────────────

def _flicker_args(*, amp: float, frames: int = 128, seed: int = 11008) -> dict[str, Any]:
    phase = float(seed % 8)
    t = [float(i) for i in range(frames)]
    luminance = [100.0 + amp * math.sin(2.0 * math.pi * (ti + phase) / 16.0) for ti in t]
    return {
        "workspace_id": WS,
        "project_id": P1,
        "video_item_id": V1,
        "layer_ref_type": "video_item",
        "layer_ref_id": V1,
        "checkpoint_ref": "ckpt-t03d-flicker",
        "window": {"start_frame": 0, "end_frame": frames - 1},
        "luminance": luminance,
    }


# ── helpers ─────────────────────────────────────────────────────────────────

def _persist_items(
    session: Session, repo: QCItemRepository, items: list[dict[str, Any]]
) -> list[QCItemRecord]:
    records = [repo.create(**item) for item in items]
    session.flush()  # repository never commits on its own — caller commits
    return records


def test_identity_drift_metadata_stable_pixels_cross_boundary_blocker(tmp_path: Path) -> None:
    """C4-F5 (1): metadata pinned, visual identity distance at/over the
    calibrated blocker boundary -> item."""
    engine = _fresh_engine(tmp_path)
    args = _identity_args(delta=8.0, meta_deltas=[False, False])
    result = detect_identity(args)

    assert result["reason_code"] == IDENTITY_CODE
    assert result["code"] == CODE_THRESHOLD_BLOCKER
    assert result["identity_flip"]["flipped"] is False

    visual_items = [i for i in result["items"] if "identity_flip" not in i["evidence"]]
    assert len(visual_items) == 1
    item = visual_items[0]
    assert item["reason_code"] == IDENTITY_CODE
    assert item["category"] == IDENTITY_CODE
    assert item["severity"] == "blocker"
    assert item["confidence_source"] == "detector"
    ev = item["evidence"]
    assert ev["schema_version"] == 1
    assert ev["pinned_reference"]["artifact_id"] == "art-ref"
    assert ev["frames"] == [
        {"frame_index": 0, "artifact_id": "art-id-0", "sha256": args["frames"][0]["sha256"]},
        {"frame_index": 1, "artifact_id": "art-id-1", "sha256": args["frames"][1]["sha256"]},
    ]
    assert ev["feature_revision"] == "1.0.0"
    assert ev["measured"]["measured_distance"] == 8.0
    assert ev["metric"]["value"] == 8.0
    assert ev["metric"]["policy"]["policy_id"] == load_policy()["policy_id"]

    # beyond the calibrated envelope (max = level-4 raw) the policy fail-closes:
    # THRESHOLD_INVALID with zero items — never an invented measurement
    beyond = detect_identity(_identity_args(delta=10.0, meta_deltas=[False, False]))
    assert beyond["code"] == CODE_THRESHOLD_INVALID
    assert beyond["items"] == []

    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _persist_items(session, repo, result["items"])[0]
        assert record.reason_code == IDENTITY_CODE
        assert record.category == IDENTITY_CODE
        assert record.severity == "blocker"
        assert record.status == "open"
        assert record.evidence == ev
        session.commit()


def test_identity_drift_warning_band_and_pass_band(tmp_path: Path) -> None:
    """Warning band -> warning item; inside bounds -> zero item."""
    _ = tmp_path
    warn = detect_identity(_identity_args(delta=3.0, meta_deltas=[False, False]))
    assert warn["code"] == CODE_THRESHOLD_WARNING
    warn_items = [i for i in warn["items"] if "identity_flip" not in i["evidence"]]
    assert len(warn_items) == 1
    assert warn_items[0]["severity"] == "warning"

    ok = detect_identity(_identity_args(delta=1.0, meta_deltas=[False, False]))
    assert ok["code"] == CODE_THRESHOLD_PASS
    assert ok["items"] == []


def test_identity_flip_metadata_change_near_identical_pixels_blocker(tmp_path: Path) -> None:
    """C4-F5 (2): cast-instance flip with near-identical pixels -> blocker item
    (fail-closed flip; visual metric still measured, not replaced)."""
    engine = _fresh_engine(tmp_path)
    args = _identity_args(delta=0.5, meta_deltas=[False, True])
    result = detect_identity(args)

    # visual is still measured: sub-warning band (near-identical pixels)
    assert result["measured_distance"] < 2.0
    assert result["code"] == CODE_THRESHOLD_BLOCKER  # flip dominates
    assert result["identity_flip"]["flipped"] is True

    flip_items = [i for i in result["items"] if i["evidence"].get("identity_flip", {}).get("flipped")]
    assert len(flip_items) == 1
    flip = flip_items[0]
    assert flip["reason_code"] == IDENTITY_CODE
    assert flip["severity"] == "blocker"
    assert flip["evidence"]["identity_flip"]["flip_kind"] == "adjacent_metadata_change"
    # visual metric NOT replaced: it is still present in the same evidence
    assert flip["evidence"]["measured"]["measured_distance"] < 2.0

    with Session(engine) as session:
        repo = QCItemRepository(session)
        record = _persist_items(session, repo, flip_items)[0]
        assert record.severity == "blocker"
        session.commit()


def test_identity_stable_pixels_metadata_no_item(tmp_path: Path) -> None:
    """C4-F5 (3): stable pixels + stable metadata -> zero items."""
    engine = _fresh_engine(tmp_path)
    result = detect_identity(_identity_args(delta=0.0, meta_deltas=[False, False]))
    assert result["code"] == CODE_THRESHOLD_PASS
    assert result["items"] == []
    with Session(engine) as session:
        repo = QCItemRepository(session)
        _, total = repo.list(WS, video_item_id=V1)
        assert total == 0


def test_rerun_same_evidence_byte_identical_idempotent(tmp_path: Path) -> None:
    """C4-F5 (4): re-run same evidence -> byte-identical result JSON and
    repository create idempotent (one row, same natural key)."""
    engine = _fresh_engine(tmp_path)
    args = _identity_args(delta=8.0, meta_deltas=[False, False])
    r1 = detect_identity(args)
    r2 = detect_identity(args)
    assert json.dumps(r1, sort_keys=True, separators=(",", ":")) == json.dumps(
        r2, sort_keys=True, separators=(",", ":")
    )
    item = r1["items"][0]
    with Session(engine) as session:
        repo = QCItemRepository(session)
        rec1 = _persist_items(session, repo, [item])[0]
        rec2 = repo.create(**item)  # same natural key -> reuse
        assert rec2.id == rec1.id
        assert rec2.evidence == rec1.evidence
        assert canonical_evidence_json(rec1.evidence) == canonical_evidence_json(item["evidence"])
        _, total = repo.list(WS, video_item_id=V1)
        assert total == 1
        session.commit()


def test_no_unknown_or_deferred_reason_code_any_detector(tmp_path: Path) -> None:
    """C4-F5 (5): every detector returns a bound reason code + a stable
    THRESHOLD_* code; no UNKNOWN / deferred anywhere; all three registered."""
    _ = tmp_path
    detectors = {
        IDENTITY_CODE: detect_identity(_identity_args(delta=10.0, meta_deltas=[False, False])),
        HALO_CODE: detect_halo(_halo_args(halo_r=8.0)),
        FLICKER_CODE: detect_flicker(_flicker_args(amp=0.1)),
    }
    for label, result in detectors.items():
        assert result["reason_code"] in {IDENTITY_CODE, HALO_CODE, FLICKER_CODE}
        assert result["code"] in _THRESHOLD_CODES, label
        blob = json.dumps(result, sort_keys=True)
        assert "UNKNOWN" not in blob and "deferred" not in blob, label
        for item in result["items"]:
            assert item["reason_code"] == label
            assert item["category"] == label
            assert item["severity"] in {"blocker", "warning"}
            assert item["evidence"]["schema_version"] == 1
    names = set(registry.names())
    assert {IDENTITY_CODE, HALO_CODE, FLICKER_CODE} <= names


def test_adjacent_flip_vs_cast_pin_authority_blocker_immediate(tmp_path: Path) -> None:
    """Binding: role/instance flips abruptly between adjacent frames vs the
    ProjectCastMapping pin + evaluate_compatibility -> blocker ngay."""
    engine = _fresh_engine(tmp_path)
    with Session(engine) as session:
        session.add(Character(id="char-1", workspace_id=WS, name="Hero", code="hero",
                              character_type="character", symmetry="symmetric"))
        pack = CharacterPackVersion(id="pack-1", character_id="char-1",
                                    workspace_id=WS, version=1, status="published")
        session.add(pack)
        session.flush()
        for i, slot in enumerate(CORE_POSE_SLOTS):
            art = Artifact(id=f"art-pack-{i}", workspace_id=WS, kind="image",
                           relative_path=f"pack/{slot}.png", state="ready",
                           size_bytes=10, mime_type="image/png",
                           sha256=hashlib.sha256(slot.encode()).hexdigest())
            session.add(art)
            session.flush()
            session.add(CharacterAsset(pack_version_id=pack.id, workspace_id=WS,
                                       pose_slot=slot, artifact_id=art.id))
        session.add(ObjectRole(id="role-pinned", workspace_id=WS, project_id=P1,
                               video_item_id=V1, source_generation="1",
                               name="Hero role", kind="character"))
        session.add(ProjectCastMapping(id="map-1", workspace_id=WS, project_id=P1,
                                       object_role_id="role-pinned", character_id="char-1",
                                       pack_version_id="pack-1", revision=1))
        session.flush()
        result = evaluate_compatibility(
            session, WS, P1, "role-pinned", "char-1", "pack-1",
            expected_revision=1, mapping_id="map-1",
        )
        assert result.compatible is True
        pin_metadata = {
            "role_id": "role-pinned", "instance_id": "inst-pinned", "cast_pin_ref": "cast-pin-1",
        }
        session.commit()

    # frame 0 pinned; frame 1 role/instance flips abruptly (near-identical pixels)
    args = _identity_args(delta=0.0, meta_deltas=[False, False])
    args["frames"][1]["metadata"] = {
        "role_id": "role-OTHER", "instance_id": "inst-OTHER", "cast_pin_ref": "cast-pin-1",
    }
    args["cast_pin"] = {
        "object_role_id": "role-pinned",
        "character_id": "char-1",
        "pack_version_id": "pack-1",
        "revision": 1,
        "expected_metadata": pin_metadata,
        "compatible": result.compatible,
        "compatibility_reasons": list(result.reasons),
    }
    out = detect_identity(args)
    assert out["code"] == CODE_THRESHOLD_BLOCKER
    flip_items = [i for i in out["items"] if i["evidence"].get("identity_flip", {}).get("flipped")]
    assert len(flip_items) == 1
    ev = flip_items[0]["evidence"]
    assert ev["identity_flip"]["flip_kind"] == "adjacent_metadata_change"
    assert ev["identity_flip"]["observed"][1] == args["frames"][1]["metadata"]
    assert ev["identity_flip"]["expected"] == pin_metadata

    # cast authority incompatible (stale pin revision) -> fail-closed blocker
    args2 = _identity_args(delta=0.0, meta_deltas=[False, False])
    args2["cast_pin"]["compatible"] = False
    args2["cast_pin"]["compatibility_reasons"] = ["stale_revision"]
    out2 = detect_identity(args2)
    assert out2["code"] == CODE_THRESHOLD_BLOCKER
    flips2 = [i for i in out2["items"] if i["evidence"].get("identity_flip", {}).get("flipped")]
    assert len(flips2) == 1
    assert flips2[0]["evidence"]["identity_flip"]["flip_kind"] == "cast_authority_incompatible"

    # both persist through the repository with the binding reason code
    with Session(engine) as session:
        repo = QCItemRepository(session)
        records = _persist_items(session, repo, flip_items + flips2)
        assert all(r.reason_code == IDENTITY_CODE and r.severity == "blocker" for r in records)
        session.commit()


def test_edge_halo_pass_warning_blocker_per_policy(tmp_path: Path) -> None:
    """Binding: halo around the rendered mask edge vs expected mask ->
    warning/blocker strictly by the frozen policy boundaries."""
    engine = _fresh_engine(tmp_path)
    thr = get_threshold("edge_halo")

    pass_r = detect_halo(_halo_args(halo_r=1.0))
    assert pass_r["code"] == CODE_THRESHOLD_PASS
    assert pass_r["items"] == []

    warn_r = detect_halo(_halo_args(halo_r=2.0))
    assert warn_r["code"] == CODE_THRESHOLD_WARNING
    warn_items = [i for i in warn_r["items"]]
    assert len(warn_items) == 1
    assert warn_items[0]["severity"] == "warning"
    assert warn_items[0]["reason_code"] == HALO_CODE
    ev = warn_items[0]["evidence"]
    assert ev["frame_index"] == 10
    assert ev["mask_revision"] == "2.1.0"
    assert ev["feature_revision"] == "1.0.0"
    assert ev["rendered"]["artifact_id"] == "art-rendered-halo"
    assert ev["expected"]["artifact_id"] == "art-expected-mask"
    assert ev["measured"]["halo_width_px"] >= thr["warning_boundary"]
    assert ev["measured"]["halo_width_px"] < thr["blocker_boundary"]

    blk_r = detect_halo(_halo_args(halo_r=8.0))
    assert blk_r["code"] == CODE_THRESHOLD_BLOCKER
    blk_items = [i for i in blk_r["items"]]
    assert len(blk_items) == 1
    assert blk_items[0]["severity"] == "blocker"
    assert blk_items[0]["evidence"]["measured"]["halo_width_px"] >= thr["blocker_boundary"]

    with Session(engine) as session:
        repo = QCItemRepository(session)
        warn_rec = _persist_items(session, repo, warn_items)[0]
        blk_rec = _persist_items(session, repo, blk_items)[0]
        assert warn_rec.category == HALO_CODE and blk_rec.severity == "blocker"
        session.commit()


def test_temporal_flicker_pass_warning_blocker_per_policy(tmp_path: Path) -> None:
    """Binding: per-frame luminance noise in a window -> warning/blocker by
    the frozen policy; measured value derives from the T06A2 formula."""
    engine = _fresh_engine(tmp_path)
    thr = get_threshold("temporal_flicker")

    pass_f = detect_flicker(_flicker_args(amp=0.05))
    assert pass_f["code"] == CODE_THRESHOLD_PASS
    assert pass_f["items"] == []

    warn_f = detect_flicker(_flicker_args(amp=0.1))
    assert warn_f["code"] == CODE_THRESHOLD_WARNING
    warn_items = [i for i in warn_f["items"]]
    assert len(warn_items) == 1
    assert warn_items[0]["severity"] == "warning"
    assert warn_items[0]["reason_code"] == FLICKER_CODE
    ev = warn_items[0]["evidence"]
    assert ev["window"] == {"start_frame": 0, "end_frame": 127}
    assert ev["frame_count"] == 128
    assert ev["feature_revision"] == "1.0.0"
    assert ev["measured"]["mean_interframe_luminance_delta"] >= thr["warning_boundary"]
    assert ev["measured"]["mean_interframe_luminance_delta"] < thr["blocker_boundary"]

    blk_f = detect_flicker(_flicker_args(amp=0.4))
    assert blk_f["code"] == CODE_THRESHOLD_BLOCKER
    blk_items = [i for i in blk_f["items"]]
    assert len(blk_items) == 1
    assert blk_items[0]["severity"] == "blocker"
    assert blk_items[0]["evidence"]["measured"]["mean_interframe_luminance_delta"] >= thr["blocker_boundary"]

    with Session(engine) as session:
        repo = QCItemRepository(session)
        warn_rec = _persist_items(session, repo, warn_items)[0]
        blk_rec = _persist_items(session, repo, blk_items)[0]
        assert warn_rec.category == FLICKER_CODE and blk_rec.severity == "blocker"
        session.commit()


def test_thresholds_derive_from_t06a2_calibration_raw_values() -> None:
    """AC3: identity/halo/flicker metric boundaries are the T06A2 calibration
    raw values (warning=level 2, blocker=level 4) — no invented numbers."""
    calib = (
        Path(__file__).resolve().parent
        / "fixtures" / "s11_qc" / "calibration" / "identity_halo_flicker.json"
    )
    doc = json.loads(calib.read_text(encoding="utf-8"))
    raw: dict[str, dict[int, float]] = {}
    for rec in doc["metrics"]:
        raw[rec["metric"]] = {
            lv["level"]: lv["raw_value"] for lv in rec["perturbation_levels"]
        }
    for metric in ("identity_drift", "edge_halo", "temporal_flicker"):
        entry = get_threshold(metric)
        assert entry["warning_boundary"] == raw[metric][2], metric
        assert entry["blocker_boundary"] == raw[metric][4], metric
        assert entry["kind"] == "increasing"
        assert entry["sanity_bounds"]["min"] == 0.0
        # classification honors the policy (read-only T03A) — not hard-coded
        mid_warn = (raw[metric][2] + raw[metric][3]) / 2.0
        status, code = classify(metric, mid_warn)
        assert status == "warning" and code == CODE_THRESHOLD_WARNING
        # exactly at the level-4 raw value -> blocker (values above the max
        # calibrated envelope would be THRESHOLD_INVALID by design)
        status, code = classify(metric, raw[metric][4])
        assert status == "blocker" and code == CODE_THRESHOLD_BLOCKER


def test_evidence_hash_mismatch_fail_closed_invalid(tmp_path: Path) -> None:
    """Evidence corruption (sha256 mismatch) is fail-closed: THRESHOLD_INVALID,
    zero items — never a fabricated measurement."""
    _ = tmp_path
    args = _identity_args(delta=10.0, meta_deltas=[False, False])
    args["frames"][1]["sha256"] = "deadbeef"  # tampered artifact hash
    result = detect_identity(args)
    assert result["code"] == CODE_THRESHOLD_INVALID
    assert result["items"] == []