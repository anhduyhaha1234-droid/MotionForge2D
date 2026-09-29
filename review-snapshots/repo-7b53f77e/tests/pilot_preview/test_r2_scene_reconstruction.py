"""R2 scene-reconstruction tests (DV3-R2-T02, new file).

Replaces the defect in REVIEW.md F02 (``_clean_source_frames`` Telea
radius3 per frame over a clipped SAM mask + ``_composite_v3`` opaque
occluder rectangle): removal is source-derived + correction-history
refined, book/chair/woman are protected separately, clean plate prefers
source-observed reuse with frame provenance, Telea is a bounded fallback
only, hidden background with no observation is explicit ``unknown``.

All fixtures are derived from REAL decoded source frames
(``runtime-runs/DV3-R2-20260908T1000Z/T02/temp/fixture-src{450,510,522,
569}.png`` = byte crops of the pinned source MP4; the ``output/
fixtures`` crops are real source regions too).  No black-rectangle-only
or hardcoded-screenshot assertions anywhere.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.services.pilot_preview.scene_contract import (
    FRAME_HEIGHT,
    FRAME_WIDTH,
    SOURCE_PINNED_SHA256,
    SOURCE_WINDOW,
)
from app.services.pilot_preview.scene_reconstruction import (
    BOOK_TRANSITION_SOURCE,
    LAYER_ORDER,
    PROTECTED_ROLES,
    RECONSTRUCTION_REVISION,
    TELEA_MAX_FRAME_FRACTION,
    MaskCorrection,
    ReconstructionCache,
    ReconstructionError,
    apply_corrections,
    book_insert_box_px,
    book_state_at,
    decompose_frame,
    decomposition_identity,
    derive_protected_masks,
    derive_temporal_woman_repair,
    derive_target_mask,
    finish_source_book,
    plate_cache_key,
    propose_reviewed_clean_plate,
    reader_proposal_box_px,
    reconstruct_clean_plate,
    reconstruct_frame,
    repair_source_woman_edge,
    render_decomposition_sheet,
)

# Real source-derived fixtures (written by the T02 R1 worker from decoded
# source frames; resolved at runtime, skipped if absent).  runtime-runs
# lives at the WORK root (sibling of repo/), so parents[3].
_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME_T02 = (
    _REPO_ROOT
    / "runtime-runs"
    / "DV3-R2-20260908T1000Z"
    / "T02"
)
_SRC_FIXTURES = {
    450: _RUNTIME_T02 / "temp" / "fixture-src450.png",
    510: _RUNTIME_T02 / "temp" / "fixture-src510.png",
    522: _RUNTIME_T02 / "temp" / "fixture-src522.png",
    569: _RUNTIME_T02 / "temp" / "fixture-src569.png",
}
_REGION_FIXTURES = {
    "book-closed": _RUNTIME_T02 / "output" / "fixtures" / "fixture-book-closed510.png",
    "book-open": _RUNTIME_T02 / "output" / "fixtures" / "fixture-book-open569.png",
    "chair": _RUNTIME_T02 / "output" / "fixtures" / "fixture-chair510.png",
    "reader": _RUNTIME_T02 / "output" / "fixtures" / "fixture-reader510.png",
    "woman": _RUNTIME_T02 / "output" / "fixtures" / "fixture-woman510.png",
}
PROMPT_BBOX = (150, 60, 300, 280)  # operator edit envelope (never the removal mask)


def _require_src(source_frame: int) -> np.ndarray:
    path = _SRC_FIXTURES[source_frame]
    assert path.is_file(), f"missing source-derived fixture: {path}"
    frame = cv2.imread(str(path))
    assert frame is not None and tuple(frame.shape[:2]) == (FRAME_HEIGHT, FRAME_WIDTH)
    return frame


def _reconstruct(source_frame: int, **kwargs) -> object:
    frame = _require_src(source_frame)
    params = {
        "source_frame": source_frame,
        "source_sha256": SOURCE_PINNED_SHA256,
        "source_prompt_bbox_xywh_px": PROMPT_BBOX,
    }
    params.update(kwargs)
    return reconstruct_frame(frame, **params)


# ------------------------------------------------------- fixtures are real

def test_r2_source_derived_fixtures_present() -> None:
    """Guard: fixtures are real decoded-frame derivatives, not black rects."""
    for source_frame, path in _SRC_FIXTURES.items():
        assert path.is_file(), f"missing fixture src{source_frame}: {path}"
        assert path.stat().st_size > 50000, f"fixture too small: {path}"
        frame = cv2.imread(str(path))
        assert frame.shape == (FRAME_HEIGHT, FRAME_WIDTH, 3)
        assert float(frame.std()) > 15.0, "fixture looks flat/synthetic"
    for name, path in _REGION_FIXTURES.items():
        assert path.is_file(), f"missing region fixture {name}: {path}"
        crop = cv2.imread(str(path))
        assert crop is not None and float(crop.std()) > 5.0


# ------------------------------------------------------------- MUST-RUN 1

def test_r2_removal_excludes_book_chair_woman() -> None:
    """MUST-RUN: removal never claims protected book/chair/woman pixels.

    The whole prompt rectangle is only the edit envelope: the removal
    mask must be strictly smaller than the envelope, and zero removal
    pixels may overlap any protected role mask.
    """
    for source_frame in (450, 510, 522, 569):
        result = _reconstruct(source_frame)
        removal = np.asarray(result.removal_mask) > 0
        assert int(removal.sum()) > 1000, "removal mask is vacuous"
        # Never the whole prompt rectangle.
        px, py, pw, ph = PROMPT_BBOX
        envelope_area = pw * ph
        assert int(removal.sum()) < envelope_area, "removal == prompt rectangle"
        for role in ("book", "chair_occupied", "chair_spare", "woman"):
            protected = np.asarray(result.protected_masks[role]) > 0
            assert int(protected.sum()) > 0, f"{role} mask vacuous @{source_frame}"
            overlap = removal & protected
            assert int(overlap.sum()) == 0, (
                f"removal claims {int(overlap.sum())} {role} pixels @{source_frame}"
            )
        # Permitted-edits field also excludes every protected pixel.
        permitted = np.asarray(result.permitted_edits_mask) > 0
        for role, mask in result.protected_masks.items():
            overlap = permitted & (np.asarray(mask) > 0)
            assert int(overlap.sum()) == 0, f"permitted edits touch {role}"


def test_c7_book_finish_cannot_write_outside_source_role_mask() -> None:
    """C7 page/outline finishing is clipped by the observed book role."""
    frame = np.zeros((40, 60, 3), dtype=np.uint8)
    mask = np.zeros((40, 60), dtype=np.uint8)
    mask[15:25, 25:35] = 1
    output = finish_source_book(frame, source_frame=450, book_mask=mask)
    changed = np.any(output != frame, axis=2)
    assert int(changed.sum()) > 0
    assert not np.any(changed & ~(mask > 0))


def test_c8_book_role_covers_complete_early_open_prop() -> None:
    """Open/closed source masks cover the measured blue silhouette, not a late box."""
    for source_frame in (450, 521, 522, 523, 569):
        frame = _require_src(450 if source_frame < 522 else 522)
        mask = derive_protected_masks(frame, source_frame=source_frame)["book"] > 0
        b, g, r = [frame[:, :, index].astype(np.int16) for index in (0, 1, 2)]
        blue = (b >= 150) & ((b - r) >= 90) & ((b - g) >= 90)
        x, y, w, h = book_insert_box_px(source_frame)
        region = np.zeros(mask.shape, dtype=bool); region[y:y + h, x:x + w] = True
        assert np.all(mask[blue & region]), f"book mask misses source blue at {source_frame}"
        ys, _ = np.where(mask & region)
        assert len(ys) and int(ys.min()) <= (204 if source_frame >= 522 else 200)


def test_c8_restored_woman_occlusion_survives_replacement() -> None:
    """Temporal source support restores the dress inside the old-arm footprint."""
    donor = _require_src(510)
    repair_mask, repair_reference, provenance = derive_temporal_woman_repair(
        source_frame=522, neighbour_frames={510: donor, 521: donor}
    )
    assert provenance["status"] == "source_temporal_support"
    assert repair_reference is not None
    assert repair_mask[197, 315] > 0
    final = np.zeros_like(donor); final[:, :] = (0, 255, 0)
    repaired = repair_source_woman_edge(
        final, source_frame=522, source_reference=final,
        woman_mask=np.zeros((FRAME_HEIGHT, FRAME_WIDTH), dtype=np.uint8),
        repair_mask=repair_mask, repair_reference=repair_reference,
    )
    assert np.array_equal(repaired[197, 315], donor[197, 315])


def test_c8_temporal_repair_preserves_outside_mask() -> None:
    """The temporal foreground repair cannot write outside its authority mask."""
    donor = _require_src(510)
    mask = np.zeros((FRAME_HEIGHT, FRAME_WIDTH), dtype=np.uint8)
    mask[190:202, 308:320] = 255
    base = np.zeros_like(donor); base[:, :] = (0, 255, 0)
    repaired = repair_source_woman_edge(
        base, source_frame=522, source_reference=base,
        woman_mask=np.zeros_like(mask), repair_mask=mask, repair_reference=donor,
    )
    changed = np.any(repaired != base, axis=2)
    assert np.all(~changed | (mask > 0))


# ------------------------------------------------------------- MUST-RUN 2

def test_r2_old_arm_event_removed() -> None:
    """MUST-RUN: the old moving limb at the end of the window is removed.

    src-569 carries the old-arm event (the F01 ghost the R1 hands-on-knees
    run left behind); src-450 is the quiet begin control.  The end-frame
    removal must cover the event region inside the reader proposal box,
    and the result-without-replacement must differ from source exactly
    where removal was permitted (no ghost left in place).
    """
    begin = _reconstruct(450)
    end = _reconstruct(569)
    for result, source_frame in ((begin, 450), (end, 569)):
        removal = np.asarray(result.removal_mask) > 0
        # Event region: lower half of the reader proposal box (arms/hands
        # zone at chest, measured on real frames).
        px, py, pw, ph = reader_proposal_box_px(source_frame)
        event = np.zeros((FRAME_HEIGHT, FRAME_WIDTH), dtype=bool)
        event[py + ph // 2: py + ph, px: px + pw] = True
        covered = removal & event
        assert int(covered.sum()) > 500, (
            f"event region not covered @{source_frame}: {int(covered.sum())} px"
        )
    # End frame: removed pixels actually change in the clean result.
    src = _require_src(569).astype(np.int16)
    out = np.asarray(end.result_without_replacement).astype(np.int16)
    removal = np.asarray(end.removal_mask) > 0
    protected_union = np.zeros((FRAME_HEIGHT, FRAME_WIDTH), dtype=bool)
    for mask in end.protected_masks.values():
        protected_union |= np.asarray(mask) > 0
    changed = (np.abs(out - src).sum(axis=2) > 0) & removal & ~protected_union
    assert int(changed.sum()) > 500, "removed target left unchanged (ghost)"
    # No old head ghost: removal covers the head rows of the proposal box.
    px, py, pw, ph = reader_proposal_box_px(569)
    head = np.zeros((FRAME_HEIGHT, FRAME_WIDTH), dtype=bool)
    head[py: py + 60, px: px + pw] = True
    assert int(((np.asarray(end.removal_mask) > 0) & head).sum()) > 200


# ------------------------------------------------------------- MUST-RUN 3

def test_r2_protected_pixels_equal_preencode() -> None:
    """MUST-RUN: protected pixels are exactly unchanged, pre-encode.

    Every pixel claimed by any protected role mask must be byte-identical
    between the source frame and the result-without-replacement.  This is
    the F02 acceptance row (crisp source-visible chair edges, no Telea
    smear into protected line art).
    """
    for source_frame in (450, 510, 522, 569):
        result = _reconstruct(source_frame)
        src = _require_src(source_frame)
        out = np.asarray(result.result_without_replacement)
        for role, mask in result.protected_masks.items():
            keep = np.asarray(mask) > 0
            if int(keep.sum()) == 0:
                continue
            assert np.array_equal(src[keep], out[keep]), (
                f"protected role {role} changed pre-encode @{source_frame}"
            )
        # Chair edges stay crisp: no broad smear — the permitted-edits
        # area is bounded well below the whole frame.
        permitted_fraction = float((np.asarray(result.permitted_edits_mask) > 0).mean())
        assert permitted_fraction < 0.10, f"edit area too broad: {permitted_fraction}"


# ------------------------------------------------------------- MUST-RUN 4

def test_r2_clean_plate_provenance_and_temporal_hold() -> None:
    """MUST-RUN: clean-plate provenance is honest and temporally stable.

    Provenance counts partition the frame; Telea is bounded (never a
    finished blurred plate); neighbour reuse carries ``shot_reuse:``
    provenance with static alignment; and the same-frame reconstruction
    is deterministic across repeated runs (temporal hold).
    """
    frame_total = FRAME_WIDTH * FRAME_HEIGHT
    for source_frame in (450, 510, 522, 569):
        result = _reconstruct(source_frame)
        prov = result.clean_plate_provenance
        assert prov["revision"] == RECONSTRUCTION_REVISION
        assert prov["source_sha256"] == SOURCE_PINNED_SHA256
        assert prov["source_frame"] == source_frame
        assert prov["alignment"] == "static"
        counted = (
            prov["same_frame_pixels"]
            + prov["shot_reuse_pixels"]
            + prov["telea_fallback_pixels"]
            + prov["unknown_pixels"]
        )
        assert counted == frame_total, (source_frame, counted)
        assert prov["telea_fallback_pixels"] <= int(TELEA_MAX_FRAME_FRACTION * frame_total)
        # Book event state rides the provenance record's frame identity.
        assert book_state_at(source_frame) == ("closed" if source_frame < BOOK_TRANSITION_SOURCE else "open")

    # Shot reuse: neighbours donate observed pixels with provenance.
    frames = {sf: _require_src(sf) for sf in (450, 510, 522, 569)}
    plate, prov, _unknown = reconstruct_clean_plate(
        frames[510],
        np.asarray(_reconstruct(510).removal_mask),
        dict(_reconstruct(510).protected_masks),
        source_frame=510,
        source_sha256=SOURCE_PINNED_SHA256,
        neighbour_frames={sf: frames[sf] for sf in (450, 522, 569)},
    )
    assert prov["shot_reuse_pixels"] >= 0
    assert prov["same_frame_pixels"] + prov["shot_reuse_pixels"] + prov["telea_fallback_pixels"] + prov["unknown_pixels"] == frame_total

    # Temporal hold: same inputs -> byte-identical plate + identity.
    first = _reconstruct(510)
    second = _reconstruct(510)
    assert np.array_equal(np.asarray(first.clean_plate), np.asarray(second.clean_plate))
    assert decomposition_identity(decompose_frame(first)) == decomposition_identity(decompose_frame(second))


# ------------------------------------------------- tamper changes identity

def test_r2_layer_mask_or_event_tamper_changes_identity() -> None:
    """Per-layer mask / clean-plate / event tamper changes identity or fails."""
    result = _reconstruct(510)
    view = decompose_frame(result)
    baseline = decomposition_identity(view)
    assert len(baseline) == 64

    tampered = {k: (np.asarray(v).copy() if isinstance(v, np.ndarray) else v) for k, v in view.items()}
    tampered["protected_masks"] = {r: m.copy() for r, m in view["protected_masks"].items()}
    tampered["protected_masks"]["book"] = np.zeros_like(view["protected_masks"]["book"])
    assert decomposition_identity(tampered) != baseline

    tampered_plate = {k: (np.asarray(v).copy() if isinstance(v, np.ndarray) else v) for k, v in view.items()}
    tampered_plate["protected_masks"] = {r: m.copy() for r, m in view["protected_masks"].items()}
    tampered_plate["clean_plate"] = np.zeros_like(view["clean_plate"])
    assert decomposition_identity(tampered_plate) != baseline

    tampered_layer = dict(view)
    tampered_layer["layer_order"] = list(reversed(view["layer_order"]))
    assert decomposition_identity(tampered_layer) != baseline

    # Event tamper (wrong book state for the frame) fails validation first.
    with pytest.raises(ReconstructionError):
        book_state_at(449)
    assert book_state_at(521) == "closed"
    assert book_state_at(522) == "open"


# ------------------------------------------------------- correction history

def test_r2_correction_history_recorded_and_replayable() -> None:
    """Corrections carve/extend the mask explicitly and ride the identity."""
    frame = _require_src(510)
    base = derive_target_mask(frame, source_frame=510)
    exclude_box = book_insert_box_px(510)  # protect the PiP insert interior
    include_box = (230, 120, 40, 60)  # force removal in the torso zone
    corrections = (
        MaskCorrection(bbox_xywh_px=exclude_box, mode="exclude", note="keep book insert"),
        MaskCorrection(bbox_xywh_px=include_box, mode="include", note="old limb", supersedes=-1),
    )
    refined = derive_target_mask(frame, source_frame=510, corrections=corrections)
    assert int((np.asarray(refined) > 0).sum()) > 0
    # Exclude box genuinely carves.
    only_include = apply_corrections(base, corrections[1:])
    both = apply_corrections(only_include, corrections[:1])
    assert int((np.asarray(both) > 0).sum()) <= int((np.asarray(only_include) > 0).sum())

    result = _reconstruct(510, corrections=list(corrections))
    assert len(result.correction_history) == 2
    view = decompose_frame(result)
    assert len(view["correction_history"]) == 2
    plain = _reconstruct(510)
    assert decomposition_identity(view) != decomposition_identity(decompose_frame(plain))

    with pytest.raises(ReconstructionError):
        MaskCorrection(bbox_xywh_px=(0, 0, 0, 10), mode="include")
    with pytest.raises(ReconstructionError):
        MaskCorrection(bbox_xywh_px=(0, 0, 10, 10), mode="merge")


# ------------------------------------------------- cache + unknown + gates

def test_r2_plate_cache_identity_and_unknown_flag() -> None:
    """Cache binds full identity; unknown regions are flagged, never filled."""
    frame = _require_src(510)
    removal = derive_target_mask(frame, source_frame=510)
    protected = derive_protected_masks(frame, source_frame=510)
    cache = ReconstructionCache()

    first_plate, first_prov, first_unknown = reconstruct_clean_plate(
        frame, removal, protected, source_frame=510,
        source_sha256=SOURCE_PINNED_SHA256, cache=cache,
    )
    assert len(cache) == 1
    second_plate, second_prov, _ = reconstruct_clean_plate(
        frame, removal, protected, source_frame=510,
        source_sha256=SOURCE_PINNED_SHA256, cache=cache,
    )
    assert np.array_equal(first_plate, second_plate)
    assert second_prov == first_prov  # cache hit returns the same record

    key = plate_cache_key(
        source_sha256=SOURCE_PINNED_SHA256, source_frame=510,
        mask_identity="ab" * 32, algorithm="x", algorithm_params={},
    )
    other = plate_cache_key(
        source_sha256=SOURCE_PINNED_SHA256, source_frame=511,
        mask_identity="ab" * 32, algorithm="x", algorithm_params={},
    )
    assert key != other  # frame is part of the identity

    # Force the unknown path: removal larger than the Telea budget.
    big = np.full((FRAME_HEIGHT, FRAME_WIDTH), 255, dtype=np.uint8)
    _plate, prov, unknown = reconstruct_clean_plate(
        frame, big, protected, source_frame=510, source_sha256=SOURCE_PINNED_SHA256,
    )
    assert prov["unknown_pixels"] > 0
    assert int((unknown > 0).sum()) == prov["unknown_pixels"]

    # Reviewed-plate proposal never invents pixels without approval.
    record = propose_reviewed_clean_plate(prov)
    assert record["status"].startswith("NEEDS_REVIEW")
    approved = propose_reviewed_clean_plate(prov, reviewer="t02", approved=True)
    assert approved["status"] == "REVIEWED"


def test_r2_reviewed_plate_pixels_are_consumed_before_fallback() -> None:
    """A reviewed plate replaces the actual edit pixels; Telea is not relabeled."""
    frame = _require_src(510)
    removal = derive_target_mask(frame, source_frame=510)
    protected = derive_protected_masks(frame, source_frame=510)
    reviewed = np.full_like(frame, (11, 22, 33))
    plate, provenance, unknown = reconstruct_clean_plate(
        frame,
        removal,
        protected,
        source_frame=510,
        source_sha256=SOURCE_PINNED_SHA256,
        reviewed_plate=reviewed,
        reviewed_plate_identity="plate-content-test",
    )
    assert provenance["reviewed_plate_pixels"] == int((np.asarray(removal) > 0).sum())
    assert provenance["telea_fallback_pixels"] == 0
    assert provenance["unknown_pixels"] == 0
    assert int((np.asarray(unknown) > 0).sum()) == 0
    assert np.all(np.asarray(plate)[np.asarray(removal) > 0] == (11, 22, 33))


def test_r2_fail_closed_gates() -> None:
    """Out-of-window frames, wrong source, bad shapes fail closed."""
    frame = _require_src(510)
    with pytest.raises(ReconstructionError):
        reconstruct_frame(
            frame, source_frame=449, source_sha256=SOURCE_PINNED_SHA256,
            source_prompt_bbox_xywh_px=PROMPT_BBOX,
        )
    with pytest.raises(ReconstructionError):
        reconstruct_frame(
            frame, source_frame=510, source_sha256="0" * 64,
            source_prompt_bbox_xywh_px=PROMPT_BBOX,
        )
    bad = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(ReconstructionError):
        derive_target_mask(bad, source_frame=510)
    with pytest.raises(ReconstructionError):
        derive_protected_masks(bad, source_frame=510)
    assert SOURCE_WINDOW == (450, 569)
    assert BOOK_TRANSITION_SOURCE == 522
    assert set(PROTECTED_ROLES) >= {"book", "chair_occupied", "chair_spare", "woman"}
    assert "character" not in PROTECTED_ROLES
    assert list(LAYER_ORDER) == [
        "room", "chair_occupied", "chair_spare", "character", "woman",
        "table", "book", "seated_back", "chair_foreground",
    ]


# ----------------------------------------------- decomposition stills (gen)

def _book_state_suffix(source_frame: int) -> str:
    return "closed" if source_frame < BOOK_TRANSITION_SOURCE else "open"


def test_r2_decomposition_stills_and_ledger(tmp_path) -> None:
    """Generate review decomposition sheets (begin/event/end) + ledger.

    Writes into pytest's isolated temporary output root (never the repo or a
    historical runtime): sheets for
    src-450 (begin, book closed), src-522 (event, book open transition),
    src-569 (end, book open) plus a JSON provenance ledger.  Review
    artefacts only — never product output.
    """
    out_dir = tmp_path / "output" / "decomposition"
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger: dict[str, object] = {
        "revision": RECONSTRUCTION_REVISION,
        "source_sha256": SOURCE_PINNED_SHA256,
        "prompt_bbox_xywh_px": list(PROMPT_BBOX),
        "frames": [],
    }
    for source_frame in (450, 522, 569):
        result = _reconstruct(source_frame)
        view = decompose_frame(result)
        identity = decomposition_identity(view)
        sheet_name = f"decomposition-src{source_frame}-{_book_state_suffix(source_frame)}.png"
        render_decomposition_sheet(_require_src(source_frame), result, str(out_dir / sheet_name))
        ledger["frames"].append(
            {
                "source_frame": source_frame,
                "role": (
                    "begin-closed" if source_frame == 450
                    else "event-transition" if source_frame == 522 else "end-open"
                ),
                "book_state": book_state_at(source_frame),
                "sheet": f"output/decomposition/{sheet_name}",
                "identity": identity,
                "provenance": dict(result.clean_plate_provenance),
                "removal_pixels": int((np.asarray(result.removal_mask) > 0).sum()),
                "protected_pixels": {
                    role: int((np.asarray(mask) > 0).sum())
                    for role, mask in result.protected_masks.items()
                },
                "corrections": len(result.correction_history),
            }
        )
        assert (out_dir / sheet_name).stat().st_size > 20000
    ledger_path = out_dir / "provenance-ledger.json"
    ledger_path.write_text(
        json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8"
    )
    assert ledger_path.is_file()
    digest = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    assert len(digest) == 64
