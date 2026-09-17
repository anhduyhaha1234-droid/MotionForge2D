"""Unit tests for mf_comfy.reskin — the mf_keyframe_reskin_v1 core.

These are contract tests, not engine proof: they pin the graph-shape rules, the
deterministic seed policy, the cutout recipe and the measurement functions. The
engine proof for this workflow is the real run on 127.0.0.1:8199 recorded in
`EV/runs/reskin_batch.json` plus the 56 artwork frames it produced.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from mf_comfy import reskin

TEMPLATE = Path(__file__).resolve().parent.parent / "workflows" / "mf_keyframe_reskin_v1.json"


def base_params(**over):
    p = reskin.build_params("BOOK", 1650, "mf_init_BOOK_f1650.png", "POS", "NEG", 0.6,
                            "mf_reskin_v1/BOOK_reskin_f1650")
    p.update(over)
    return p


# ---------------------------------------------------------------- template
def test_template_loads_and_resolves():
    t = reskin.load_template(TEMPLATE)
    g = reskin.resolve_graph(t, base_params())
    assert len(g) == 10
    classes = [n["class_type"] for n in g.values()]
    assert classes.count("LoadImage") == 1
    assert classes.count("KSampler") == 1
    assert "EmptyLatentImage" not in classes
    assert g["2"]["inputs"]["image"] == "mf_init_BOOK_f1650.png"
    assert g["7"]["inputs"]["denoise"] == 0.6
    assert g["7"]["inputs"]["seed"] == reskin.deterministic_seed("BOOK", 1650)
    assert g["10"]["inputs"]["filename_prefix"] == "mf_reskin_v1/BOOK_reskin_f1650"
    assert json.dumps(g)  # serialisable


def test_template_placeholders_are_all_parameterised():
    t = reskin.load_template(TEMPLATE)
    reskin.resolve_graph(t, base_params())  # would raise KeyError on an unbound placeholder


def test_no_double_underscore_placeholder_survives_resolution():
    t = reskin.load_template(TEMPLATE)
    g = reskin.resolve_graph(t, base_params())
    blob = json.dumps(g)
    assert "__init_image__" not in blob and "__seed__" not in blob


def test_resolution_is_1024x576_in_and_640x360_out():
    g = reskin.resolve_graph(reskin.load_template(TEMPLATE), base_params())
    assert (g["3"]["inputs"]["width"], g["3"]["inputs"]["height"]) == tuple(reskin.INIT_SIZE)
    assert (g["9"]["inputs"]["width"], g["9"]["inputs"]["height"]) == (640, 360)
    assert reskin.INIT_SIZE[0] / reskin.INIT_SIZE[1] == pytest.approx(16 / 9)


# ---------------------------------------------------------------- guards
@pytest.mark.parametrize("denoise", [0.0, 1.0, 1.5, -0.2])
def test_denoise_must_be_strictly_inside_0_1(denoise):
    with pytest.raises(ValueError, match="denoise"):
        reskin.resolve_graph(reskin.load_template(TEMPLATE), base_params(denoise=denoise))


def test_text_to_image_graph_is_refused():
    t = reskin.load_template(TEMPLATE)
    t["6"] = {"class_type": "EmptyLatentImage",
              "inputs": {"width": 64, "height": 64, "batch_size": 1}}
    with pytest.raises(ValueError, match="EmptyLatentImage|VAE-encode"):
        reskin.resolve_graph(t, base_params())


def test_graph_without_loadimage_is_refused():
    t = reskin.load_template(TEMPLATE)
    del t["2"]
    t["3"]["inputs"]["image"] = ["1", 0]
    with pytest.raises(ValueError, match="LoadImage"):
        reskin.resolve_graph(t, base_params())


def test_loadimage_must_name_the_staged_keyframe():
    t = reskin.load_template(TEMPLATE)
    t["2"]["inputs"]["image"] = "something_else.png"
    with pytest.raises(ValueError, match="staged frozen keyframe"):
        reskin.resolve_graph(t, base_params())


# ---------------------------------------------------------------- shape hash
def test_shape_hash_is_stable_across_per_anchor_values():
    t = reskin.load_template(TEMPLATE)
    a = reskin.graph_shape_hash(reskin.resolve_graph(t, base_params()))
    b = reskin.graph_shape_hash(reskin.resolve_graph(
        t, reskin.build_params("WALK_7927", 7927, "other.png", "DIFFERENT PROMPT", "NEG2",
                               0.6, "another/prefix")))
    assert a == b


def test_shape_hash_tracks_denoise():
    t = reskin.load_template(TEMPLATE)
    a = reskin.graph_shape_hash(reskin.resolve_graph(t, base_params(denoise=0.6)))
    b = reskin.graph_shape_hash(reskin.resolve_graph(t, base_params(denoise=0.52)))
    assert a != b


def test_shape_hash_tracks_resolution():
    t = reskin.load_template(TEMPLATE)
    t2 = copy.deepcopy(t)
    t2["3"]["inputs"]["width"] = 1280
    t2["3"]["inputs"]["height"] = 720
    assert (reskin.graph_shape_hash(reskin.resolve_graph(t, base_params()))
            != reskin.graph_shape_hash(reskin.resolve_graph(t2, base_params())))


# ---------------------------------------------------------------- seeds
def test_seed_is_deterministic_and_per_anchor():
    assert reskin.deterministic_seed("BOOK", 1650) == reskin.deterministic_seed("BOOK", 1650)
    assert reskin.deterministic_seed("BOOK", 1650) != reskin.deterministic_seed("BOOK", 1665)
    assert reskin.deterministic_seed("BOOK", 1650) != reskin.deterministic_seed("WALK_7927", 1650)


def test_seed_fits_31_bits():
    for tag in ("BOOK", "CUT_660", "WALK_7927", "HOLDOUT_16231"):
        for fid in (660, 1650, 7927, 16231):
            assert 0 <= reskin.deterministic_seed(tag, fid) < 2 ** 31


# ---------------------------------------------------------------- cutout recipe
def test_role_cutout_is_rgba_cropped_to_the_bbox():
    frame = np.zeros((40, 60, 3), np.uint8)
    idx = np.zeros((40, 60), np.uint8)
    idx[10:20, 5:25] = 3
    cut = reskin.role_cutout(frame, idx, 3, [0, 0, 60, 40])
    assert cut.shape == (40, 60, 4)
    assert cut.dtype == np.uint8
    assert set(np.unique(cut[:, :, 3]).tolist()) == {0, 255}
    # an exact-bbox crop of the same mask is fully opaque
    tight = reskin.role_cutout(frame, idx, 3, [5, 10, 20, 10])
    assert tight.shape == (10, 20, 4)
    assert set(np.unique(tight[:, :, 3]).tolist()) == {255}


def test_role_cutout_alpha_is_binary_and_zero_outside_the_role():
    frame = np.full((30, 30, 3), 200, np.uint8)
    idx = np.zeros((30, 30), np.uint8)
    idx[0:5, 0:5] = 1
    idx[10:30, 10:30] = 2
    cut = reskin.role_cutout(frame, idx, 1, [0, 0, 30, 30])
    assert cut.shape == (30, 30, 4)
    assert np.count_nonzero(cut[:, :, 3]) == 25


# ---------------------------------------------------------------- agreement
def test_iou_extremes():
    a = np.zeros((10, 10), np.uint8)
    a[0:5] = 255
    b = a.copy()
    assert reskin.iou(a, b) == pytest.approx(1.0)
    c = a.copy()
    c[5:10] = 255
    c[0:5] = 0
    assert reskin.iou(a, c) == pytest.approx(0.0)
    assert reskin.iou(np.zeros((4, 4), np.uint8), np.zeros((4, 4), np.uint8)) == pytest.approx(1.0)


def test_pearson_identical_and_independent():
    a = np.zeros((20, 20), np.uint8)
    a[5:10, 5:10] = 255
    assert reskin.pearson(a, a) == pytest.approx(1.0)
    b = np.zeros((20, 20), np.uint8)
    b[15:19, 15:19] = 255
    assert reskin.pearson(a, b) < 0.5


def test_bbox_and_centroid():
    m = np.zeros((50, 80), np.uint8)
    m[10:20, 30:50] = 255
    assert reskin.bbox_of(m) == (30, 10, 20, 10)
    cx, cy = reskin.centroid_of(m)
    assert (cx, cy) == pytest.approx((39.5, 14.5))
    assert reskin.bbox_of(np.zeros((5, 5), np.uint8)) == (0, 0, 0, 0)


def test_envelope_iou_ignores_translation_but_not_shape():
    m = np.zeros((100, 100), np.uint8)
    m[20:60, 20:60] = 255
    other = np.zeros((100, 100), np.uint8)
    other[45:85, 45:85] = 255          # same size, moved
    assert reskin.envelope_iou(m, other) > 0.95
    thin = np.zeros((100, 100), np.uint8)
    thin[20:60, 20:30] = 255           # different shape
    assert reskin.envelope_iou(m, thin) < 0.6


# ---------------------------------------------------------------- foreground
def test_foreground_mask_on_a_uniform_frame_is_empty():
    flat = np.full((180, 320, 3), 77, np.uint8)
    assert np.count_nonzero(reskin.foreground_mask(flat)) == 0


def test_foreground_mask_recovers_a_synthetic_subject():
    img = np.full((360, 640, 3), 210, np.uint8)
    img[120:240, 200:440] = (40, 60, 90)
    fg = reskin.foreground_mask(img)
    truth = np.zeros((360, 640), np.uint8)
    truth[120:240, 200:440] = 255
    assert reskin.iou(fg, truth) > 0.85


def test_foreground_mask_is_identical_for_identical_input():
    img = np.full((360, 640, 3), 30, np.uint8)
    img[100:200, 100:300] = 200
    assert np.array_equal(reskin.foreground_mask(img), reskin.foreground_mask(img.copy()))


# ---------------------------------------------------------------- contacts
def test_contact_band_lies_on_the_shared_boundary():
    idx = np.zeros((40, 40), np.uint8)
    idx[:, :20] = 1
    idx[:, 20:] = 2
    band = reskin.contact_band(idx, 1, 2, radius=2)
    assert band.shape == (40, 40)
    assert np.count_nonzero(band) > 0
    ys, xs = np.nonzero(band)
    assert xs.min() >= 18 and xs.max() <= 22


def test_contact_band_is_empty_for_masks_that_do_not_touch():
    idx = np.zeros((40, 40), np.uint8)
    idx[:, :5] = 1
    idx[:, 30:] = 2
    assert np.count_nonzero(reskin.contact_band(idx, 1, 2, radius=2)) == 0


def test_coverage_extremes():
    band = np.zeros((20, 20), np.uint8)
    band[5:10, 5:10] = 1
    full = np.full((20, 20), 255, np.uint8)
    empty = np.zeros((20, 20), np.uint8)
    t, c, r = reskin.coverage(band, full)
    assert (t, c) == (25, 25) and r == pytest.approx(1.0)
    assert reskin.coverage(band, empty)[2] == pytest.approx(0.0)


# ---------------------------------------------------------------- appearance
def test_appearance_is_zero_for_an_identical_image():
    rng = np.random.default_rng(7)
    img = rng.integers(0, 255, (120, 200, 3), dtype=np.uint8)
    s = reskin.appearance_stats(img, img.copy())
    assert s["hist_l1"] == pytest.approx(0.0)
    assert s["texture_entropy_delta"] == pytest.approx(0.0)
    assert s["flat_fraction_delta"] == pytest.approx(0.0)
    assert s["unique_colour_ratio"] == pytest.approx(1.0)


def test_appearance_separates_texture_change_from_palette_change():
    flat = np.full((200, 320, 3), 128, np.uint8)
    flat[50:150, 80:240] = 90
    textured = flat.copy()
    rng = np.random.default_rng(11)
    noise = rng.integers(-30, 30, (200, 320, 3), dtype=np.int16)
    textured = np.clip(textured.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    s = reskin.appearance_stats(flat, textured)
    assert s["texture_entropy_delta"] > 2.0
    assert s["flat_fraction_delta"] > 0.10


def test_flat_fraction_of_a_flat_source_is_high():
    flat = np.full((200, 320, 3), 200, np.uint8)
    assert reskin.flat_fraction(flat) > 0.95


# ---------------------------------------------------------------- misc
def test_summarise_ignores_nan_and_none():
    s = reskin.summarise([1.0, None, float("nan"), 3.0])
    assert s["n"] == 2 and s["median"] == pytest.approx(2.0)
    assert reskin.summarise([])["n"] == 0


def test_content_contrast_is_positive_for_a_subject_region():
    img = np.full((200, 320, 3), 128, np.uint8)
    img[50:150, 80:240] = 90
    rng = np.random.default_rng(3)
    img[50:150, 80:240] = np.clip(
        img[50:150, 80:240].astype(np.int16)
        + rng.integers(-40, 40, (100, 160, 3), dtype=np.int16), 0, 255).astype(np.uint8)
    subj = np.zeros((200, 320), np.uint8)
    subj[50:150, 80:240] = 255
    assert reskin.content_contrast(img, subj) > 1.0


def test_hash_helpers_are_stable(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"mf-reskin")
    assert reskin.sha256_file(p) == reskin.sha256_file(p)
    assert len(reskin.sha256_file(p)) == 64


# ------------------------------------------------- continuation-03: fix 1
def _synthetic_frame() -> np.ndarray:
    img = np.full((360, 640, 3), 128, np.uint8)
    img[40:100, 60:140] = 30
    img[200:230, 300:350] = 240
    img[90:160, 480:520] = 70
    return img


def test_degenerate_detects_a_black_transition_frame():
    black = np.zeros((360, 640, 3), np.uint8)
    d = reskin.frame_degeneracy(black)
    assert d["degenerate"] is True
    assert d["exclusion_code"] == reskin.DEGENERATE_SOURCE_CODE == "degenerate_source_frame"
    assert d["per_channel_std_max"] == 0.0
    assert d["unique_colours"] == 1
    assert "zero_variance_every_channel" in d["reasons"]
    assert "iou(empty, empty) is 1.0" in d["consequence"]


def test_degenerate_detects_a_uniform_non_black_frame_too():
    flat = np.full((180, 320, 3), 77, np.uint8)
    d = reskin.frame_degeneracy(flat)
    assert d["degenerate"] is True
    assert "single_colour_frame" in d["reasons"]


def test_degenerate_does_not_fire_on_a_real_frame():
    d = reskin.frame_degeneracy(_synthetic_frame())
    assert d["degenerate"] is False
    assert d["exclusion_code"] is None
    assert d["per_channel_std_max"] > 0.0
    assert d["unique_colours"] > 1


def test_degenerate_anchor_is_excluded_not_counted_as_perfect_geometry():
    """The trap this fix closes: an empty subject scores IoU 1.0 by definition."""
    black = np.zeros((360, 640, 3), np.uint8)
    assert reskin.foreground_mask(black).max() == 0
    # ... which is why the naive metric would call it perfect:
    assert reskin.iou(np.zeros((8, 8), np.uint8), np.zeros((8, 8), np.uint8)) == pytest.approx(1.0)
    assert reskin.bbox_of(np.zeros((8, 8), np.uint8)) == (0, 0, 0, 0)
    # ... and why the anchor is excluded instead:
    elig = reskin.anchor_eligibility(black)
    assert elig["eligible_for_gates"] is False
    assert elig["exclusion_code"] == "degenerate_source_frame"
    assert reskin.anchor_eligibility(_synthetic_frame())["eligible_for_gates"] is True


# ------------------------------------------------- continuation-03: fix 2
def _legend_and_kinds():
    legend = [{"index": 1, "role_id": "role_1"}, {"index": 2, "role_id": "role_2"},
              {"index": 3, "role_id": "role_3"}, {"index": 9, "role_id": "role_9"}]
    kinds = {"role_1": "background", "role_2": "character", "role_3": "unclassified"}
    return legend, kinds  # role_9 is absent from the kinds table on purpose


def test_frozen_subject_union_drops_only_background():
    legend, kinds = _legend_and_kinds()
    idx = np.zeros((20, 30), np.uint8)
    idx[0:10, :] = 1        # background -> excluded
    idx[10:14, :] = 2       # character -> included
    idx[14:17, :] = 3       # unclassified -> included
    idx[17:20, :] = 9       # not in kinds -> included (matches the nonbg convention)
    union = reskin.frozen_subject_union(idx, legend, kinds)
    assert np.count_nonzero(union) == 300          # the 10 non-background rows of 30 px
    assert np.all(union[0:10, :] == 0)
    assert np.all(union[10:20, :] == 255)


def test_frozen_subject_union_is_derivation_free_and_idempotent():
    legend, kinds = _legend_and_kinds()
    rng = np.random.default_rng(5)
    idx = rng.integers(0, 10, (40, 40), dtype=np.uint8)
    a = reskin.frozen_subject_union(idx, legend, kinds)
    b = reskin.frozen_subject_union(idx.copy(), legend, kinds)
    assert np.array_equal(a, b)


def test_frozen_subject_metrics_are_exact_for_identical_frames():
    img = _synthetic_frame()
    legend, kinds = _legend_and_kinds()
    idx = np.zeros((360, 640), np.uint8)
    idx[0:100, :] = 1
    idx[100:260, :] = 2
    m = reskin.geometry_metrics_frozen_subject(img, img.copy(),
                                               reskin.frozen_subject_union(idx, legend, kinds))
    assert m["subject_derivation"] == "none (frozen fixture bytes)"
    assert m["edge_iou_in_frozen_subject"] == pytest.approx(1.0)
    assert m["edge_density_ratio"] == pytest.approx(1.0)
    assert m["content_contrast_ratio"] == pytest.approx(1.0)
    assert m["layout_shift_px"] == pytest.approx(0.0)
    assert m["layout_shift_pct_diag"] == pytest.approx(0.0)


def test_frozen_subject_metrics_detect_a_real_layout_shift():
    img = _synthetic_frame()
    moved = np.roll(img, 10, axis=1)          # the whole pattern translated 10 px in x
    legend, kinds = _legend_and_kinds()
    idx = np.zeros((360, 640), np.uint8)
    idx[0:100, :] = 1
    idx[100:260, :] = 2
    subj = reskin.frozen_subject_union(idx, legend, kinds)
    m = reskin.geometry_metrics_frozen_subject(img, moved, subj)
    assert 8.0 <= m["layout_shift_px"] <= 12.0
    assert m["layout_shift_pct_diag"] > 1.0
    assert m["edge_iou_in_frozen_subject"] < 0.9   # the derivation-free row notices


def test_derived_foreground_family_is_labelled_with_its_bias():
    img = _synthetic_frame()
    legend, kinds = _legend_and_kinds()
    idx = np.zeros((360, 640), np.uint8)
    idx[0:100, :] = 1
    idx[100:260, :] = 2
    subj = reskin.frozen_subject_union(idx, legend, kinds)
    d = reskin.geometry_metrics_derived_foreground(img, img.copy(), subj)
    assert "0.559" in d["bias"] and "NOT the primary gate" in d["bias"]
    for k in ("fg_iou", "envelope_iou", "bbox_area_ratio", "centroid_shift_pct_diag",
              "fg_vs_frozen_subject_iou_source", "fg_vs_frozen_subject_iou_reskin",
              "envelope_vs_frozen_subject_source", "envelope_vs_frozen_subject_reskin"):
        assert k in d


def test_lut_test_says_a_palette_change_could_be_a_colour_remap():
    img = _synthetic_frame()
    lut = (np.clip((np.arange(256) / 255.0) ** 0.7 * 255.0, 0, 255)).astype(np.uint8)
    recoloured = lut[img]
    r = reskin.palette_lut_residual(img, recoloured)
    s = reskin.structure_after_lut(img, recoloured)
    assert r["within_16_fraction"] > 0.9, r
    assert r["residual"] < 0.05, r
    assert s["edge_iou_lut_vs_render"] > 0.9, s
    assert s["highpass_corr_lut_vs_render"] > 0.9, s


def test_lut_test_says_a_content_change_cannot_be_a_colour_remap():
    flat = np.full((200, 320, 3), 200, np.uint8)
    flat[50:150, 80:240] = 120
    rng = np.random.default_rng(13)
    textured = np.clip(flat.astype(np.int16)
                       + rng.integers(-60, 60, flat.shape, dtype=np.int16),
                       0, 255).astype(np.uint8)
    r = reskin.palette_lut_residual(flat, textured)
    s = reskin.structure_after_lut(flat, textured)
    assert r["residual"] > 0.05, r                     # the change is NOT invertible as colour
    assert s["edge_iou_lut_vs_render"] < 0.5, s        # LUT(source) does not carry this structure
    assert s["edge_iou_lut_vs_render"] < s["edge_iou_lut_vs_src"]
