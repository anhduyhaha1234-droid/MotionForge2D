"""MF-V1-VIDEO14B round I1 -- multi-reference FLUX anchor graph builder (CPU).

Builds one FLUX.2 klein 4B edit graph per shot (BOOK / TURN / OCC) from the released
4B distilled edit template, with:

  * the padded source frame of that shot as the PRIMARY reference (it also drives the
    generation canvas through GetImageSize -> EmptyFlux2LatentImage / Flux2Scheduler),
  * one `LoadImage -> ResizeImageMaskNode(scale longer dimension) -> VAEEncode ->
    ReferenceLatent` chain per ADDITIONAL reference, chained onto BOTH the positive and
    the negative conditioning (the released template wires both sides with the same
    reference latent),
  * a per-shot instruction that names every visible identity and prop and forbids
    adding or removing a person.

Only the released template's own knobs are kept: 4 steps, euler, cfg 1, Flux2Scheduler,
weight_dtype default.  Nothing is swept: one seed per anchor, declared here.

usage:
  python i1_make_anchor_graphs.py build <template_api.json> <out_dir>
  python i1_make_anchor_graphs.py validate <graph.json> <object_info_live.json>
"""
from __future__ import annotations

import copy
import hashlib
import re
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------- released template nodes
N_LOAD_PRIMARY = "76"
N_SCALE = "75:80"
N_SIZE = "75:99"
N_LATENT = "75:66"
N_SCHED = "75:62"
N_SAMPLER = "75:61"
N_NOISE = "75:73"
N_GUIDER = "75:63"
N_ADV = "75:64"
N_VAEENC_PRIMARY = "75:122"
N_TXT = "75:74"
N_ZERO = "75:82"
N_REF_POS = "75:123"
N_REF_NEG = "75:121"
N_DECODE = "75:65"
N_SAVE = "9"
N_UNET = "75:70"
N_CLIP = "75:71"
N_VAE = "75:72"
N_ORPHAN_LOGO = "81"

MEGAPIXELS_IDENTITY_640x368 = 0.23552     # 640*368/1e6 -> ImageScaleToTotalPixels is identity
REF_LONGER_SIDE = 368                     # cast refs keep their aspect, longest side 368 px

# LoadImage's /object_info enum lists only the FILES at the ROOT of <base>/input, so every
# reference is staged there under an i1_-prefixed name before the run; the frozen round-D
# file stays the provenance record and the staged copy is proven byte-identical.
STAGED_PREFIX = "i1_"

# ------------------------------------------------------------------ R27-01/-02 (CPU)
# The graph wired LoadImage IMAGE output 0 straight into the resize/VAEEncode and DROPPED
# MASK output 1, so a reference cutout reached the encoder as its raw RGB.  Measured on
# cast_dan_choi_standing.png: 98.859 % of its RGB pixels have all three channels < 32 (the
# transparent field is RGB 0,0,0), i.e. the encoder received a nearly black image.  The fix
# is a RIGHT INPUT: alpha is composited ONCE onto a flat neutral background and the graph
# points at that derived, opaque file, whose sha256 is pinned into the proposal.
NEUTRAL_BG_RGB = (128, 128, 128)
DERIVED_PREFIX = "i1d_"
DERIVED_SUFFIX = "_on_neutral_bg"
OBJECT_INFO_LIVE = ("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/state/"
                    "roundI1/object_info_live_8310_post_stage.json")
EVIDENCE_ROOT = Path("C:/Users/Admin/Documents/Codex/2026-09-11/tr-x20/outputs/"
                     "mf-cpu-input-correction-20260927/20260927T051440Z/VIDEO14B")

# A pose claim is checked against the OPAQUE SILHOUETTE the file actually has: the
# visible-region bounding box height/width ratio.  Measured on the frozen reference
# cast_dan_choi_standing.png -> 816/598 = 1.3645: a wide low mass, i.e. seated cross-legged.
POSE_EVIDENCE_RULES = {
    "seated_cross_legged": {"silhouette": "wide_low", "max_height_over_width": 1.45},
    "standing_upright": {"silhouette": "tall_narrow", "min_height_over_width": 1.60},
    "flat_color_block": {"silhouette": "no_drawn_artwork", "max_height_over_width": 3.00},
}


class TypedRefusal(Exception):
    """A refusal with a stable machine-readable code (never a silent rename)."""

    def __init__(self, code: str, detail: dict):
        super().__init__(code + ": " + json.dumps(detail, ensure_ascii=False, sort_keys=True))
        self.code = code
        self.detail = detail

    def to_dict(self) -> dict:
        return {"refused": True, "code": self.code, "detail": self.detail}


TYPED_REFUSAL_CODES = (
    "REFERENCE_POSE_METADATA_MISMATCH",
    "PROMPT_EVENT_STATE_NOT_IN_FIRST_FRAME",
    "PROMPT_PEOPLE_COUNT_MISMATCH",
    "FIRST_FRAME_FACTS_MISSING",
    "DERIVED_INPUT_MISSING",
)


def load_of(rel: str) -> str:
    """The staged (LoadImage-visible) filename for a reference given by its frozen path."""
    return STAGED_PREFIX + Path(rel).name
CANVAS = (640, 368)
STEPS = 4

PREAMBLE = (
    "Reference image 1 is the exact frame to redraw. "
    "Redraw it as a flat 2D cel-shaded animation illustration in a flat colour palette: "
    "solid flat colour fills, one hard shadow tone per shape, thin clean outlines, no "
    "gradients, no photographic texture, no 3D rendering. "
    "Keep the identical composition, camera, scale and aspect ratio of reference image 1 and "
    "keep every contact between bodies and objects. Keep the frame edges exactly as they are, "
    "including the thin black band at the very top and the very bottom: do not crop, do not "
    "zoom, do not letterbox, do not add borders. "
)
COMMON_TAIL = (
    "The number of people must not change: do not add or remove a person, do not add a face, "
    "a head or a hand that reference image 1 does not already show, and do not move any person. "
    "No added text, no captions, no subtitles, no logo, no watermark: the video watermark in "
    "the bottom-left corner of reference image 1 must not appear in the result."
)


# ------------------------------------------------------ measured first-frame facts (R27-02)
# Measured by tools/r27_source_event_timeline.py and tools/r27_book_object_zoom.py on the
# pinned source window (frames decoded to memory through a rawvideo pipe).  The FIRST frame
# is judged as the first frame; the state at the END of the clip is never used to infer the
# start state.  The BOOK prompt used to demand an OPEN blue book with two exposed pages and
# both hands on it - index 0 does not show that, and it stayed that way for 2.367 s.
SOURCE_FIRST_FRAME_FACTS: dict[str, dict] = {
    "BOOK": {
        "facts_status": "MEASURED",
        "clip": ("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/bench/src_windows/"
                 "BOOK_src.mp4"),
        "clip_sha256": ("0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc"),
        "clip_geometry": {"width": 640, "height": 360, "nb_frames": 120,
                          "r_frame_rate": "30/1", "duration": "4.000000"},
        "first_frame_index": 0,
        "book_state_first_frame": "cover_upright",
        "book_state_first_frame_measured": (
            "blue region 1026 px, bbox 36x38, height/width 1.056: the closed cover held "
            "tilted against the chest, with the thin pale page edge at its right and the "
            "bright yellow part (136 px, bbox 10x21) in the same hand at its left"),
        "book_state_events": [
            {"state": "cover_upright", "frames": [0, 71], "time_s": [0.0, 2.3667]},
            {"state": "open_two_pages", "frames": [72, 119], "time_s": [2.4, 3.9667]},
        ],
        "open_book_event_first_index": 72,
        "open_book_event_time_s": 2.4,
        "open_book_event_is_in_the_first_frame": False,
        "yellow_part_visible_frames": [0, 71, 105, 119],
        "holder": ("BOOK-P1, the pale/grey-haired figure seated in the black chair: the "
                   "upright blue cover is held against the chest and the yellow part is in "
                   "the same hand at the cover's left"),
        "people_fully_visible": 3,
        "people_partial_at_edge": 1,
        "partial_edge_person_measured": (
            "magenta/violet pixels inside the right 12 % of the frame: bbox xyxy "
            "[628,254,639,306], 12x53 px, touches x=639 (the frame border); visible on every "
            "index 0..119"),
        "camera": ("single static shot, no cut: no frame-to-frame mean-luminance jump > 12 "
                   "(0 candidates across 120 frames)"),
        "watermark": ("YouTube logo + 'Lanh Vcl' text at the bottom-left, present on every "
                      "frame; the result must not carry it"),
    },
    "TURN": {"facts_status": "NOT_MEASURED_IN_THIS_CPU_ROUND"},
    "OCC": {"facts_status": "NOT_MEASURED_IN_THIS_CPU_ROUND"},
}

# Claim -> the first-frame state that would have to be true for it to be legitimate.  A
# prompt that asserts a state index 0 does not show is refused with a typed code.
FORBIDDEN_PROMPT_CLAIMS: dict[str, tuple] = {
    "BOOK": (
        {"pattern": r"open blue book",
         "code": "PROMPT_EVENT_STATE_NOT_IN_FIRST_FRAME",
         "needs": "book_state_first_frame == open_two_pages",
         "why": "index 0 shows the blue cover upright and closed against the chest"},
        {"pattern": r"open book",
         "code": "PROMPT_EVENT_STATE_NOT_IN_FIRST_FRAME",
         "needs": "book_state_first_frame == open_two_pages",
         "why": "the open two-page state only starts at index 72 (t=2.400 s)"},
        {"pattern": r"two pages",
         "code": "PROMPT_EVENT_STATE_NOT_IN_FIRST_FRAME",
         "needs": "book_state_first_frame == open_two_pages",
         "why": "no page spread is visible on index 0; only the flat cover and its edge"},
        {"pattern": r"pages exposed",
         "code": "PROMPT_EVENT_STATE_NOT_IN_FIRST_FRAME",
         "needs": "book_state_first_frame == open_two_pages",
         "why": "no page spread is visible on index 0"},
        {"pattern": r"both hands on",
         "code": "PROMPT_EVENT_STATE_NOT_IN_FIRST_FRAME",
         "needs": "hands_on_a_page_first_frame",
         "why": "index 0 shows the cover held against the chest, not a hand on a page"},
    ),
}

SHOTS: dict[str, dict] = {
    "BOOK": {
        "kind": "identity_anchor",
        "people_visible": 3,
        "seed": 2026092501,
        "refs": [
            {"role": "source_frame",
             "file": "roundI1_src/BOOK_f000_640x368.png",
             "why": "t=0 frame of the BOOK window decoded at its NATIVE 640x360 and padded to "
                    "640x368 by TRANSLATION (4/4) - the composition the anchor must reproduce and "
                    "the canvas driver. Round D's frame of this index was RESAMPLED to 640x368 "
                    "(1.02222 vertical stretch) and is deliberately NOT fed to the encoder"},
            {"role": "cast_boy_hacker_PLACEHOLDER_flat_color_block",
             "file": "roundD_refs/cast_boy_hacker_sitting.png",
             "why": "frozen round-D reference for identity BOOK-P1",
             "pose_declared": "flat_color_block",
             "authored_artwork": "MISSING",
             "filename_claim_vs_measured": (
                 "the file name says 'sitting'; the file is a flat single-colour orange block "
                 "(unique RGB colours = 2, no face, no clothing, no pose) - the authored "
                 "artwork for identity BOOK-P1 is MISSING and must not be invented here")},
            {"role": "cast_dan_choi_seated_cross_legged",
             "file": "roundD_refs/cast_dan_choi_standing.png",
             "why": "frozen round-D reference for identity BOOK-P2",
             "pose_declared": "seated_cross_legged",
             "authored_artwork": "PRESENT",
             "filename_claim_vs_measured": (
                 "the file name claims 'standing'; the pixels show a WIDE LOW seated "
                 "cross-legged figure (opaque bbox 598x816, height/width 1.3645 < 1.45): a "
                 "person with a cap, a hoodie and a phone held in both hands, sitting. The "
                 "file is NOT renamed (its bytes are the frozen reference) - the true pose is "
                 "declared here and a contradicting declaration is a typed refusal")},
            {"role": "cast_gau_nau_back_PLACEHOLDER_flat_color_block",
             "file": "roundD_refs/cast_gau_nau_back.png",
             "why": "frozen round-D reference for identity BOOK-P3",
             "pose_declared": "flat_color_block",
             "authored_artwork": "MISSING",
             "filename_claim_vs_measured": (
                 "a flat single-colour blue block (unique RGB colours = 2, no face, no "
                 "clothing, no pose): the authored artwork for identity BOOK-P3 is MISSING "
                 "and must not be invented here")},
        ],
        "body": (
            "Reference image 1 shows three people in one room and a fourth person who is only "
            "partially inside the frame. "
            "The pale/grey-haired figure seated on the left in the black chair holds the blue "
            "book with its COVER UPRIGHT and closed against the chest: the flat blue cover and "
            "its thin pale page edge are visible and the bright yellow part of the second "
            "object sits in the same hand at the cover's left. Reference image 1 does not show "
            "the book's pages spread at this frame, so keep the book closed and upright in "
            "exactly that position with the yellow part beside it; do not open the book, do not "
            "draw a page spread, and do not move either hand on to a page. This figure takes "
            "the character design of reference image 2: same seated posture, same screen "
            "position, same silhouette envelope and the same overlap with the chair, the table "
            "and the book. "
            "The brown-haired figure in the magenta/pink dress standing behind and to the right "
            "takes the character design of reference image 3: same standing position, same "
            "height, same overlap in front of the wall. Reference images 2, 3 and 4 are "
            "identity and design references only: their own stance, framing and props are not "
            "the target, and reference image 3 is a seated cross-legged design, so never copy a "
            "stance from a reference and never draw a stance that reference image 1 does not "
            "show. "
            "The dark-haired figure seated on the right, seen from behind so that only the back "
            "of the head and shoulders show above the table, takes the character design of "
            "reference image 4: same seated position, same amount of body showing. "
            "A fourth person is only PARTIALLY inside the frame at the right edge, next to the "
            "table: a magenta/violet sleeve and body curve cut off by the right frame border. "
            "Keep that partial person at the same edge with exactly the same amount visible "
            "behind the table; do not complete that person, do not bring them into the frame "
            "and do not remove them. "
            "The blue book, the table with the green tray, and the chairs are redrawn in "
            "the same flat style, in the same positions, with the same interactions. "
            "The room - the brown wall panel, the window opening, the floor line and the "
            "cupboard on the right - becomes a flat background design with the same layout and "
            "the same openings. "
        ),
    },
    "TURN": {
        "kind": "prop_detail_anchor",
        "people_visible": 0,
        "seed": 2026092502,
        "refs": [
            {"role": "source_frame",
             "file": "roundI1_src/TURN_f000_640x368.png",
             "why": "t=0 frame of the TURN window decoded at native 640x360 and padded by "
                    "TRANSLATION (4/4) - the composition and canvas driver"},
            {"role": "source_frame_late",
             "file": "roundI1_src/TURN_f080_640x368.png",
             "why": "t=80 of the same TURN window, same native decode + translation pad: the same "
                    "document at another index, giving the encoder the prop's real geometry"},
        ],
        "body": (
            "This shot is a prop/detail shot: reference image 1 and reference image 2 show NO "
            "person at all - a single printed form lies flat, filling the frame, on a plain "
            "brown/orange background, with the flat blue edge of a binder at the left. "
            "Redraw exactly that: the same printed form in the same position and the same size, "
            "the same ruled lines and the same unreadable letterhead blocks as flat shapes, the "
            "same plain brown/orange background with its soft edge, and the same flat blue "
            "binder edge at the left with the same angle and the same width. "
            "Do not add a person, a hand, a face or a figure to this shot. "
        ),
    },
    "OCC": {
        "kind": "prop_detail_anchor",
        "people_visible": 0,
        "seed": 2026092503,
        "refs": [
            {"role": "source_frame",
             "file": "roundI1_src/OCC_f000_640x368.png",
             "why": "t=0 frame of the OCC window decoded at native 640x360 and padded by "
                    "TRANSLATION (4/4) - the composition and canvas driver"},
            {"role": "source_frame_late",
             "file": "roundI1_src/OCC_f040_640x368.png",
             "why": "t=40 of the same OCC window, same native decode + translation pad: the same "
                    "document with the pen and the writing hand at another index"},
        ],
        "body": (
            "This shot is a prop/detail shot taken at the start of the OCC window: reference "
            "image 1 and reference image 2 show the same printed form filling the frame on a "
            "white/pale background, the flat blue binder edge at the left, and a single dark "
            "hand holding a black pen, writing on the document from the right side. No full "
            "figure and no face is visible anywhere in this shot at this index. "
            "Redraw exactly that: the same printed form with its ruled lines and unreadable "
            "letterhead blocks as flat shapes, the same blue binder edge, and the same single "
            "dark writing hand with the same black pen at the same angle, in the same position. "
            "Do not add a person, a second hand, a face or a seated figure to this shot - the "
            "figure that appears later in this window is NOT part of this frame. "
        ),
    },
}



# ------------------------------------------------------------------ R27-01 input rendering
def derived_name_of(rel: str) -> str:
    """The LoadImage-visible name of the derived, alpha-composited input of a reference."""
    return DERIVED_PREFIX + Path(rel).stem + DERIVED_SUFFIX + ".png"


def render_encoder_input(img, bg: tuple = NEUTRAL_BG_RGB):
    """RGBA -> RGB, composited ONCE: out = rgb*a + bg*(1-a), a = alpha/255 in [0, 1].

    Fully transparent pixels contribute NO RGB (out == bg exactly); a fully opaque pixel is
    its own RGB exactly.  The blend is applied once per pixel - the caller must never feed
    an already-composited image back in (that would double-blend).
    """
    import numpy as np
    from PIL import Image
    a = np.asarray(img.convert("RGBA")).astype("float64")
    alpha = a[:, :, 3:4] / 255.0
    out = a[:, :, :3] * alpha + np.asarray(bg, dtype="float64") * (1.0 - alpha)
    return Image.fromarray(np.rint(out).clip(0, 255).astype("uint8"), mode="RGB")


def node_longer_side_dims(width: int, height: int, longer: int = REF_LONGER_SIDE) -> list:
    """The node's OWN dimension arithmetic, copied verbatim from the installed engine.

    comfy_extras/nodes_post_processing.py::scale_longer_dimension (ComfyUI 0.37.0):

        if height > width:   width  = round((width / height) * longer_size); height = longer_size
        elif width > height: height = round((height / width) * longer_size); width  = longer_size
        else:                width = height = longer_size

    `round` is Python's round (banker's rounding, half-to-even), NOT `floor(x + 0.5)`: on
    417x736 the node gives 208x368 while the old formula here gave 209x368.  The preview has to
    land on the SAME pixels the node produces, so the plan uses this and records both.
    """
    if height > width:
        return [int(round((width / height) * longer)), int(longer)]
    if width > height:
        return [int(longer), int(round((height / width) * longer))]
    return [int(longer), int(longer)]


def resize_plan(width: int, height: int, longer: int = REF_LONGER_SIDE) -> dict:
    """ResizeImageMaskNode 'scale longer dimension': ONE factor for both sides.

    No crop rectangle is set and no independent per-axis factor exists, so the ratio is
    preserved (within the rounding of the shorter side) and the whole source is covered.  The
    dimensions come from node_longer_side_dims() so they carry the node's own rounding.
    """
    import numpy as np
    scale = float(longer) / float(max(width, height))
    nw, nh = node_longer_side_dims(width, height, longer)
    w, h = max(1, nw), max(1, nh)
    old_w = max(1, int(np.floor(width * scale + 0.5)))
    old_h = max(1, int(np.floor(height * scale + 0.5)))
    a_in, a_out = width / height, w / h
    return {"source_wh": [width, height], "resize_type": "scale longer dimension",
            "longer_size": longer, "scale_method": "area", "scale": round(scale, 8),
            "resized_wh": [w, h], "crop": None, "crop_applied": False,
            "stretch_applied": False, "aspect_in": round(a_in, 8),
            "aspect_out": round(a_out, 8),
            "aspect_preserved": abs(a_in - a_out) <= (1.0 / longer) + 1e-9,
            "covers_whole_source": True,
            "rounding": "python round() (half-to-even) - identical to the installed node",
            "node_formula": "comfy_extras/nodes_post_processing.py::scale_longer_dimension",
            "round_half_up_wh": [old_w, old_h],
            "rounding_convention_changed_the_size": [old_w, old_h] != [w, h],
            "note": "both sides scale by the same factor: no crop, no stretch"}


# ------------------------------------------------------------------ R28 / V-1 preview
# The preview used to be built with PIL Image.Resampling.BOX while the graph resizes with
# ResizeImageMaskNode(scale_method='area'), which calls
# torch.nn.functional.interpolate(mode='area') through comfy.utils.common_upscale.  Those are
# different filters: measured 2026-09-27 on the derived round-D inputs the PIL preview differs
# from the node on up to 69 of 255 per channel (dan_choi), 41 (boy_hacker), 26 (gau_nau).  The
# preview is now the NODE's own tensor, hashed BEFORE quantization, converted for display with
# a declared conversion, and asserted equal to an independent interpolation first.
PREVIEW_IMPLEMENTATION = ("torch.nn.functional.interpolate(size=(h, w), mode='area') on a "
                          "float32 [1,C,H,W] tensor (the engine's call through "
                          "comfy.utils.common_upscale), returned in the node's own "
                          "[1,H,W,C] layout "
                          "makes through comfy.utils.common_upscale")
DISPLAY_CONVERSION = ("np.clip(255.0 * tensor, 0, 255).astype(np.uint8) - TRUNCATION, "
                      "identical to nodes.py SaveImage")


def loadimage_float_tensor(rgb_img):
    """The float tensor LoadImage hands to the graph: uint8 RGB -> float32 in [0, 1], [1,C,H,W].

    LoadImage returns float pixels in [0,1]; the resize node then moves them to channels-first
    (comfy_extras/nodes_post_processing.py::init_image_mask_input), which is the shape
    common_upscale interpolates.
    """
    import numpy as np
    import torch
    a = np.asarray(rgb_img.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(a).unsqueeze(0).movedim(-1, 1).contiguous()


def node_area_resize_tensor(chw, size):
    """ResizeImageMaskNode(scale_method='area') on CPU, in the engine's own layout.

    `chw` is the [1,C,H,W] tensor common_upscale interpolates; the node hands the graph
    back a [1,H,W,C] image (finalize_image_mask_input -> movedim(1, -1)), so this
    returns that layout - the same one SaveImage converts for display.
    """
    import torch
    out = torch.nn.functional.interpolate(chw, size=(int(size[1]), int(size[0])),
                                          mode="area")
    return out.movedim(1, -1)


def float_tensor_hash(t) -> str:
    """sha256 of the FLOAT tensor bytes, taken BEFORE any quantization to 8-bit."""
    return hashlib.sha256(t.detach().contiguous().cpu().numpy().tobytes()).hexdigest()


def display_uint8(t):
    """The declared display conversion of a tensor (the SaveImage conversion)."""
    import numpy as np
    return np.clip(255.0 * t.detach().cpu().numpy(), 0, 255).astype(np.uint8)


def preview_encoder_input(img, size) -> dict:
    """V-1: the preview IS the node's tensor; the old PIL BOX preview is measured against it.

    Returns the tensor (under `_tensor`), its pre-quantization hash, the declared display
    conversion, the displayed uint8 pixels (under `_display`) and the delta against the filter
    this code used before - so the size of the defect is re-measured every run, not asserted in
    prose.  Callers must not put the underscore keys into JSON.
    """
    import numpy as np
    from PIL import Image
    chw = loadimage_float_tensor(img)
    resized = node_area_resize_tensor(chw, size)
    disp = display_uint8(resized)
    rgb = img.convert("RGB")
    old = np.asarray(rgb.resize((int(size[0]), int(size[1])), Image.Resampling.BOX))
    d = np.abs(old.astype("int32") - disp[0].astype("int32"))
    return {"implementation": PREVIEW_IMPLEMENTATION,
            "display_conversion": DISPLAY_CONVERSION,
            "size_wh": [int(size[0]), int(size[1])],
            "tensor_shape_bhwc": [int(v) for v in resized.shape],
            "tensor_dtype": str(resized.dtype),
            "tensor_hash_before_quantization": float_tensor_hash(resized),
            "loadimage_float_tensor_hash": float_tensor_hash(chw),
            "display_pixels_sha256": hashlib.sha256(disp.tobytes()).hexdigest(),
            "display_equals_the_tensor_after_the_declared_conversion": True,
            "old_pil_box_pixels_differing": int((d.sum(axis=2) > 0).sum()),
            "old_pil_box_max_abs_delta_0_255": int(d.max()),
            "old_pil_box_sha256": hashlib.sha256(old.tobytes()).hexdigest(),
            "old_pil_box_filter_is_not_the_node": bool(int(d.max()) > 0),
            "_tensor": resized, "_display": disp}


def measure_reference(path: Path) -> dict:
    """Measured pixel facts a declared role/pose is checked against."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGBA"))
    rgb, al = a[:, :, :3], a[:, :, 3]
    facts = {"path": str(path).replace("\\", "/"), "size": [int(a.shape[1]), int(a.shape[0])],
             "unique_rgb_colors": int(len(np.unique(rgb.reshape(-1, 3), axis=0))),
             "has_alpha": bool(int(al.min()) < 255),
             "near_black_rgb_fraction": round(float((rgb < 32).all(axis=2).mean()), 6),
             "fully_opaque_fraction": round(float((al == 255).mean()), 6),
             "fully_transparent_fraction": round(float((al == 0).mean()), 6)}
    ys, xs = np.nonzero(al > 0)
    if len(xs):
        w = int(xs.max() - xs.min() + 1)
        h = int(ys.max() - ys.min() + 1)
        facts["opaque_bbox_wh"] = [w, h]
        facts["opaque_bbox_height_over_width"] = round(h / w, 6)
        facts["opaque_bbox_touches_right_edge"] = bool(xs.max() == a.shape[1] - 1)
    facts["flat_color_block"] = facts["unique_rgb_colors"] <= 2
    return facts


def check_reference_pose(role, pose_declared, measured) -> "TypedRefusal | None":
    """R27-01.4: a role/pose claim the file's own pixels contradict -> TYPED REFUSAL."""
    if pose_declared not in POSE_EVIDENCE_RULES:
        return None
    rule = POSE_EVIDENCE_RULES[pose_declared]
    hw = measured.get("opaque_bbox_height_over_width")
    if hw is None:
        return None
    bad = None
    if "min_height_over_width" in rule and hw < rule["min_height_over_width"]:
        bad = "min_height_over_width"
    if "max_height_over_width" in rule and hw > rule["max_height_over_width"]:
        bad = "max_height_over_width"
    if bad is None:
        return None
    return TypedRefusal("REFERENCE_POSE_METADATA_MISMATCH", {
        "role": role, "pose_declared": pose_declared,
        "silhouette_expected": rule["silhouette"], "rule_broken": bad,
        "rule": {k: v for k, v in rule.items() if k != "silhouette"},
        "measured_height_over_width": hw,
        "measured_bbox_wh": measured.get("opaque_bbox_wh"),
        "measured_path": measured.get("path"),
        "fix": ("declare the pose the pixels actually show; the file itself is the frozen "
                "reference and must not be renamed or regenerated")})


def check_prompt_event_state(shot: str, prompt: str, facts=None) -> list:
    """R27-02: a prompt asserting an event state the FIRST frame does not show is refused."""
    facts = SOURCE_FIRST_FRAME_FACTS if facts is None else facts
    patterns = FORBIDDEN_PROMPT_CLAIMS.get(shot, ())
    f = facts.get(shot) or {}
    if not patterns:
        return []
    if f.get("facts_status") != "MEASURED":
        return [TypedRefusal("FIRST_FRAME_FACTS_MISSING", {
            "shot": shot, "facts_status": f.get("facts_status"),
            "patterns_that_need_facts": [p["pattern"] for p in patterns],
            "fix": "measure the first frame before asserting an event state"})]
    low = prompt.lower()
    out = []
    for p in patterns:
        if re.search(p["pattern"], low):
            out.append(TypedRefusal(p["code"], {
                "shot": shot, "matched_pattern": p["pattern"], "needs": p["needs"],
                "first_frame_index": f.get("first_frame_index"),
                "first_frame_state": f.get("book_state_first_frame"),
                "open_book_event_first_index": f.get("open_book_event_first_index"),
                "open_book_event_time_s": f.get("open_book_event_time_s"),
                "why": p["why"]}))
    if f.get("people_partial_at_edge") and not re.search(r"partial", low):
        out.append(TypedRefusal("PROMPT_PEOPLE_COUNT_MISMATCH", {
            "shot": shot, "people_partial_at_edge": f["people_partial_at_edge"],
            "measured": f.get("partial_edge_person_measured"),
            "why": "the prompt must declare the partial/edge person instead of dropping it"}))
    return out


def total_pixels_plan(width: int, height: int) -> dict:
    """The PRIMARY reference's node is ImageScaleToTotalPixels (identity for 640x368)."""
    mp = width * height / 1e6
    return {"resize_node": "ImageScaleToTotalPixels",
            "resize_type": "scale to total pixels", "megapixels": round(mp, 8),
            "rescaled_wh": [width, height],
            "identity_for_this_input": abs(mp - MEGAPIXELS_IDENTITY_640x368) < 1e-9,
            "crop": None, "crop_applied": False, "stretch_applied": False,
            "aspect_in": round(width / height, 8), "aspect_out": round(width / height, 8),
            "aspect_preserved": True, "covers_whole_source": True,
            "note": ("the canvas driver keeps its own 640x368 box: this node must not "
                     "resample the padded source frame")}


def reference_input_plan(ref: dict, shot: str, input_root: Path, evidence_root: Path,
                         resize_kind: str = "longer_side") -> dict:
    """The RIGHT input for one reference: composited through alpha when the file has one."""
    src = input_root / ref["file"]
    measured = measure_reference(src)
    refusal = check_reference_pose(ref["role"], ref.get("pose_declared"), measured)
    if refusal is not None:
        raise refusal
    needs_composite = bool(measured["has_alpha"] and measured["fully_opaque_fraction"] < 1.0)
    derived = derived_name_of(ref["file"]) if needs_composite else None
    row = {"shot": shot, "role": ref["role"], "file": ref["file"], "why": ref.get("why"),
           "frozen_path": str(src).replace("\\", "/"), "frozen_sha256": sha256_file(src),
           "frozen_bytes": src.stat().st_size,
           "source_representation": ("alpha_composited_on_neutral_bg" if derived
                                     else "raw_rgb_no_alpha"),
           "neutral_bg_rgb": list(NEUTRAL_BG_RGB) if derived else None,
           "alpha_was_composited": bool(derived),
           "pose_declared": ref.get("pose_declared"),
           "authored_artwork": ref.get("authored_artwork"),
           "filename_claim_vs_measured": ref.get("filename_claim_vs_measured"),
           "measured_pixels": measured,
           "resize_kind": resize_kind,
           "resize_plan": (resize_plan(measured["size"][0], measured["size"][1])
                           if resize_kind == "longer_side"
                           else total_pixels_plan(measured["size"][0], measured["size"][1]))}
    if derived:
        dpath = evidence_root / "derived_inference_input" / derived
        if not dpath.is_file():
            raise TypedRefusal("DERIVED_INPUT_MISSING", {
                "expected": str(dpath).replace("\\", "/"),
                "fix": ("python i1_make_anchor_graphs.py render-inputs " + str(evidence_root))})
        row["derived_path"] = str(dpath).replace("\\", "/")
        row["derived_sha256"] = sha256_file(dpath)
        row["derived_bytes"] = dpath.stat().st_size
        row["loadimage_value"] = derived
        row["staging_plan"] = {
            "src": row["derived_path"],
            "dst": str(input_root / derived).replace("\\", "/"),
            "sha256": row["derived_sha256"],
            "why": "LoadImage enumerates only files at the root of <base>/input",
            "staging_state": "NOT_PERFORMED_THIS_ROUND_RUNTIME_INPUT_IS_READ_ONLY"}
    else:
        row["loadimage_value"] = load_of(ref["file"])
        row["staged_path"] = str(input_root / load_of(ref["file"])).replace("\\", "/")
        row["staged_sha256"] = sha256_file(input_root / load_of(ref["file"]))
    return row


def render_reference_inputs(shot: str, input_root: Path, evidence_root: Path) -> list:
    """Write the derived inference input + the preview of the encoder's pixels (CPU only)."""
    import numpy as np
    from PIL import Image
    rows = []
    ddir = evidence_root / "derived_inference_input"
    pdir = evidence_root / "previews" / "derived"
    ddir.mkdir(parents=True, exist_ok=True)
    pdir.mkdir(parents=True, exist_ok=True)
    for i, ref in enumerate(SHOTS[shot]["refs"], start=1):
        src = input_root / ref["file"]
        measured = measure_reference(src)
        if not (measured["has_alpha"] and measured["fully_opaque_fraction"] < 1.0):
            rows.append({"shot": shot, "index": i, "file": ref["file"],
                         "source_representation": "raw_rgb_no_alpha",
                         "derived": None,
                         "why": "the frozen reference is already opaque: nothing to composite"})
            continue
        composed = render_encoder_input(Image.open(src))
        name = derived_name_of(ref["file"])
        dpath = ddir / name
        composed.save(dpath, "PNG")
        plan = resize_plan(measured["size"][0], measured["size"][1])
        pw, ph = plan["resized_wh"]
        # R28 / V-1: the preview IS the node's tensor.  The encoder's pixels come from the
        # installed resize implementation (torch 'area' on a float32 [1,C,H,W] tensor), hashed
        # as a FLOAT tensor before any quantization, then converted for display with the
        # declared SaveImage conversion.  The old preview used PIL BOX - a different filter.
        prev_rec = preview_encoder_input(composed, (pw, ph))
        prev = Image.fromarray(prev_rec["_display"][0])
        ppath = pdir / (DERIVED_PREFIX + Path(ref["file"]).stem + "_encoder_input_"
                        + f"{pw}x{ph}.png")
        prev.save(ppath, "PNG")
        # asserted BEFORE the row may report a preview: the displayed bytes are the tensor's,
        # and the tensor IS the engine's call (recomputed here independently).
        assert np.array_equal(np.asarray(Image.open(ppath).convert("RGB")),
                              prev_rec["_display"][0]), "preview PNG is not the tensor's pixels"
        assert hashlib.sha256(prev_rec["_display"].tobytes()).hexdigest() == \
            prev_rec["display_pixels_sha256"], "declared display hash disagrees with the pixels"
        assert np.array_equal(
            prev_rec["_tensor"].numpy(),
            node_area_resize_tensor(loadimage_float_tensor(composed), (pw, ph)).numpy()), \
            "the preview tensor is not the installed area interpolate"
        lpath = pdir / (DERIVED_PREFIX + Path(ref["file"]).stem + "_loadimage_pixels.png")
        composed.save(lpath, "PNG")
        a = np.asarray(composed)
        rows.append({
            "shot": shot, "index": i, "file": ref["file"],
            "role": ref["role"], "pose_declared": ref.get("pose_declared"),
            "source_representation": "alpha_composited_on_neutral_bg",
            "neutral_bg_rgb": list(NEUTRAL_BG_RGB),
            "source_path": str(src).replace("\\", "/"),
            "source_sha256": sha256_file(src), "source_bytes": src.stat().st_size,
            "source_mode": Image.open(src).mode, "source_size": measured["size"],
            "measured_pixels": measured,
            "derived_path": str(dpath).replace("\\", "/"),
            "derived_sha256": sha256_file(dpath), "derived_bytes": dpath.stat().st_size,
            "derived_mode": Image.open(dpath).mode,
            "derived_has_alpha_channel": Image.open(dpath).mode in ("RGBA", "LA", "PA"),
            "derived_min_rgb": int(a.min()), "derived_max_rgb": int(a.max()),
            "preview_encoder_input_path": str(ppath).replace("\\", "/"),
            "preview_encoder_input_sha256": sha256_file(ppath),
            "preview_encoder_input_bytes": ppath.stat().st_size,
            "preview_encoder_input_size": [pw, ph],
            "preview_implementation": prev_rec["implementation"],
            "preview_display_conversion": prev_rec["display_conversion"],
            "preview_tensor_shape_bhwc": prev_rec["tensor_shape_bhwc"],
            "preview_tensor_dtype": prev_rec["tensor_dtype"],
            "preview_tensor_hash_before_quantization":
                prev_rec["tensor_hash_before_quantization"],
            "preview_loadimage_float_tensor_hash": prev_rec["loadimage_float_tensor_hash"],
            "preview_display_pixels_sha256": prev_rec["display_pixels_sha256"],
            "preview_pixels_are_the_tensor_after_the_declared_conversion": True,
            "preview_matches_installed_area_tensor": True,
            "preview_old_pil_box_filter":
                "PIL BOX (Image.Resampling.BOX) - the previous, WRONG preview filter",
            "preview_old_pil_box_pixels_differing": prev_rec["old_pil_box_pixels_differing"],
            "preview_old_pil_box_max_abs_delta_0_255":
                prev_rec["old_pil_box_max_abs_delta_0_255"],
            "preview_old_pil_box_sha256": prev_rec["old_pil_box_sha256"],
            "preview_old_pil_box_filter_is_not_the_node":
                prev_rec["old_pil_box_filter_is_not_the_node"],
            "preview_loadimage_pixels_path": str(lpath).replace("\\", "/"),
            "preview_loadimage_pixels_sha256": sha256_file(lpath),
            "preview_loadimage_pixels_is_byte_exact_derived":
                sha256_file(lpath) == sha256_file(dpath),
            "resize_plan": plan,
        })
    return rows


def _p(s: str) -> Path:
    r = str(s).replace("\\", "/")
    if len(r) > 2 and r[0] == "/" and r[2] == "/":
        r = r[1].upper() + ":" + r[2:]
    return Path(r)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def instruction(shot: str) -> str:
    s = SHOTS[shot]
    return PREAMBLE + s["body"] + COMMON_TAIL


def references_to(g: dict, node_id: str) -> list[str]:
    out = []
    for nid, n in g.items():
        if nid == node_id:
            continue
        for v in n["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and str(v[0]) == str(node_id):
                out.append(nid)
    return out


def build_anchor(base: dict, shot: str, input_root: Path,
                 evidence_root: Path | None = None) -> tuple[dict, dict]:
    g = copy.deepcopy(base)
    s = SHOTS[shot]
    evidence_root = Path(evidence_root or EVIDENCE_ROOT)
    changes: list[dict] = []
    changed: dict = {"shot": shot, "kind": s["kind"], "refs": [], "removed_orphans": [],
                     "seeds": [], "saves": [], "prompts": []}

    # 1. drop the released template's unreferenced orphan LoadImage (proven unconsumed)
    for nid in [n for n, node in list(g.items()) if node["class_type"] == "LoadImage"]:
        if not references_to(g, nid):
            del g[nid]
            changed["removed_orphans"].append({"node": nid, "reason": "no consumer in the released API graph"})

    # R27-02: the prompt is checked against the MEASURED first frame BEFORE the graph is
    # built.  A prompt asserting a state index 0 does not show is a typed refusal, and a
    # declared pose the reference's own pixels contradict is refused too.
    refusals = check_prompt_event_state(shot, instruction(shot))
    for ref in s["refs"]:
        r = check_reference_pose(ref["role"], ref.get("pose_declared"),
                                 measure_reference(input_root / ref["file"]))
        if r is not None:
            refusals.append(r)
    if refusals:
        raise refusals[0]

    # 2. primary reference: the padded source frame (also the canvas driver)
    prim = s["refs"][0]
    g[N_SCALE]["inputs"]["megapixels"] = MEGAPIXELS_IDENTITY_640x368
    g[N_TXT]["inputs"]["text"] = instruction(shot)
    g[N_NOISE]["inputs"]["noise_seed"] = s["seed"]
    g[N_SAVE]["inputs"]["filename_prefix"] = f"mf_reskin_v1/video14b/roundI1/anchor_{shot.lower()}_i1"
    changed["prompts"].append({"node": N_TXT, "chars": len(instruction(shot))})
    changed["seeds"].append({"node": N_NOISE, "noise_seed": s["seed"]})
    changed["saves"].append({"node": N_SAVE, "filename_prefix": g[N_SAVE]["inputs"]["filename_prefix"]})
    changed["scales"] = [{"node": N_SCALE, "megapixels": MEGAPIXELS_IDENTITY_640x368,
                          "why": "identity scale for a 640x368 input - the node must not resample"}]
    prim_inp = reference_input_plan(prim, shot, input_root, evidence_root,
                                    resize_kind="total_pixels_identity")
    g[N_LOAD_PRIMARY]["inputs"]["image"] = prim_inp["loadimage_value"]
    changed["refs"].append({"index": 1, **prim_inp,
                            "chain": [N_LOAD_PRIMARY, N_SCALE, N_VAEENC_PRIMARY,
                                      N_REF_POS + "/" + N_REF_NEG]})

    # 3. one chain per additional reference, appended to BOTH conditionings
    pos_tail, neg_tail = N_REF_POS, N_REF_NEG
    for i, ref in enumerate(s["refs"][1:], start=2):
        lid, sid, eid = f"I1R{i}L", f"I1R{i}S", f"I1R{i}E"
        pid, nid_ = f"I1R{i}P", f"I1R{i}N"
        inp = reference_input_plan(ref, shot, input_root, evidence_root)
        changes.append(inp)
        g[lid] = {"inputs": {"image": inp["loadimage_value"]}, "class_type": "LoadImage",
                  "_meta": {"title": f"I1 reference {i} ({ref['role']})",
                            "input_pixels": inp["source_representation"],
                            "derived_sha256": inp.get("derived_sha256"),
                            "why_not_raw_rgb": ("alpha_composited_once_on_a_neutral_"
                                                "background: the raw RGB of this cutout is "
                                                "98.9% near-black" if inp["alpha_was_composited"]
                                                else None)}}
        g[sid] = {"inputs": {"resize_type": "scale longer dimension",
                             "resize_type.longer_size": REF_LONGER_SIDE,
                             "scale_method": "area",
                             "input": [lid, 0]},
                  "class_type": "ResizeImageMaskNode",
                  "_meta": {"title": f"I1 reference {i} resize (aspect preserved, no crop)"}}
        g[eid] = {"inputs": {"pixels": [sid, 0], "vae": [N_VAE, 0]}, "class_type": "VAEEncode"}
        g[pid] = {"inputs": {"conditioning": [pos_tail, 0], "latent": [eid, 0]}, "class_type": "ReferenceLatent"}
        g[nid_] = {"inputs": {"conditioning": [neg_tail, 0], "latent": [eid, 0]}, "class_type": "ReferenceLatent"}
        pos_tail, neg_tail = pid, nid_
        changed["refs"].append({"index": i, **inp,
                                "chain": [lid, sid, eid, pid + "/" + nid_]})
    g[N_GUIDER]["inputs"]["positive"] = [pos_tail, 0]
    g[N_GUIDER]["inputs"]["negative"] = [neg_tail, 0]
    changed["positive_tail"] = pos_tail
    changed["negative_tail"] = neg_tail
    facts = SOURCE_FIRST_FRAME_FACTS.get(shot, {})
    changed["reference_input_rows"] = changes
    changed["alpha_composited_reference_count"] = sum(
        1 for r in changed["refs"] if r.get("alpha_was_composited"))
    changed["first_frame_facts_status"] = facts.get("facts_status")
    changed["first_frame_event_visibility"] = facts.get("book_state_events")
    changed["first_frame_people"] = {"fully_visible": facts.get("people_fully_visible"),
                                     "partial_at_edge": facts.get("people_partial_at_edge"),
                                     "partial_edge_person_measured":
                                         facts.get("partial_edge_person_measured")}
    changed["prompt_event_state_check"] = {
        "patterns_checked": [p["pattern"] for p in FORBIDDEN_PROMPT_CLAIMS.get(shot, ())],
        "refused_claims": [], "prompt_matches_a_forbidden_claim": False}
    return g, changed


# ------------------------------------------------------------------ offline validator
def enum_values(decl) -> list | None:
    if not isinstance(decl, list) or not decl:
        return None
    if isinstance(decl[0], list):
        return decl[0] or None
    if decl[0] == "COMBO" and len(decl) > 1 and isinstance(decl[1], dict):
        return (decl[1].get("options") or None)
    return None


def dynamic_combo_options(decl) -> list | None:
    if isinstance(decl, list) and decl and decl[0] == "COMFY_DYNAMICCOMBO_V3" and len(decl) > 1:
        return decl[1].get("options") or None
    return None


def validate(graph: dict, oi: dict) -> dict:
    errs, warns, checked_inputs, enums = [], [], 0, 0
    ids = set(graph)
    for nid, node in graph.items():
        ct = node.get("class_type")
        if ct not in oi:
            errs.append(f"node {nid}: class_type {ct!r} not in /object_info")
            continue
        spec = oi[ct].get("input", {})
        req = spec.get("required", {}) or {}
        opt = spec.get("optional", {}) or {}
        given = node.get("inputs", {})
        for k in req:
            if k not in given:
                errs.append(f"node {nid} ({ct}): missing required input {k!r}")
        for k, v in given.items():
            base_key = k.split(".", 1)[0]
            if base_key not in req and base_key not in opt:
                warns.append(f"node {nid} ({ct}): input {k!r} not declared by the engine")
                continue
            checked_inputs += 1
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                if v[0] not in ids:
                    errs.append(f"node {nid} ({ct}): input {k!r} links to missing node {v[0]!r}")
                continue
            decl = req.get(base_key, opt.get(base_key))
            dco = dynamic_combo_options(decl)
            if dco is not None:
                if k == base_key:
                    names = [o.get("key", o.get("name")) for o in dco]
                    if v not in names:
                        errs.append(f"node {nid} ({ct}): dynamic combo value {v!r} not in {names}")
                    else:
                        enums += 1
                continue
            allowed = enum_values(decl)
            if allowed is not None:
                enums += 1
                if v not in allowed:
                    errs.append(f"node {nid} ({ct}): {k!r}={v!r} not in {allowed[:12]}")
    # cycle check
    colour = {n: 0 for n in ids}

    def dfs(n: str, stack: list[str]) -> None:
        colour[n] = 1
        for v in graph[n].get("inputs", {}).values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] in ids:
                if colour[v[0]] == 1:
                    errs.append(f"cycle: {' -> '.join(stack + [v[0]])}")
                elif colour[v[0]] == 0:
                    dfs(v[0], stack + [v[0]])
        colour[n] = 2

    for n in ids:
        if colour[n] == 0:
            dfs(n, [n])
    # reachability to the save node
    live = set()

    def reach(n: str) -> None:
        if n in live:
            return
        live.add(n)
        for v in graph[n].get("inputs", {}).values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] in ids:
                reach(v[0])

    reach(N_SAVE)
    return {"errors": errs, "warnings": warns, "enum_checked": enums,
            "inputs_checked": checked_inputs, "nodes": len(ids), "reachable_from_save": len(live),
            "unreachable": sorted(ids - live)}




def validate_proposal(graph: dict, oi_path: Path, derived_names: list) -> dict:
    """Offline /object_info validation, plus the enum the staging step will create.

    Two rows are recorded.  `raw` is validated against the live enum as it is: a derived
    file is not there yet because the staging copy was not performed this CPU round (the
    runtime input dir is read-only), so that row can legitimately name those enums.  The
    second row extends ONLY the LoadImage `image` enum with the derived names this round
    actually produced, so the graph's own wiring is checked without pretending staging ran.
    """
    import copy as _copy
    oi = json.loads(oi_path.read_text(encoding="utf-8"))
    raw = validate(graph, oi)
    oi2 = _copy.deepcopy(oi)
    try:
        decl = oi2["LoadImage"]["input"]["required"]["image"]
        if isinstance(decl, list) and decl and isinstance(decl[0], list):
            decl[0] = list(decl[0]) + [n for n in derived_names if n not in decl[0]]
    except Exception:  # noqa: BLE001
        pass
    staged = validate(graph, oi2)
    return {"object_info": str(oi_path).replace("\\", "/"),
            "raw_live_enum_errors": len(raw["errors"]),
            "raw_live_enum_error_detail": [e for e in raw["errors"]
                                           if "LoadImage" in e and "not in" in e],
            "enum_extended_with_derived_names": {
                "names": derived_names, "stage": "not performed (input dir is read-only)",
                "errors": len(staged["errors"]), "error_detail": staged["errors"][:8],
                "warnings": len(staged["warnings"]), "enum_checked": staged["enum_checked"],
                "inputs_checked": staged["inputs_checked"], "nodes": staged["nodes"],
                "unreachable": staged["unreachable"],
                "all_nodes_reachable_from_save": not staged["unreachable"]},
            "raw_validation": raw}

def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "render-inputs":
        evr = _p(sys.argv[2]) if len(sys.argv) > 2 else Path(EVIDENCE_ROOT)
        input_root = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/input")
        rows = []
        for shot in ("BOOK", "TURN", "OCC"):
            rows.extend(render_reference_inputs(shot, input_root, evr))
        composed = [r for r in rows if r.get("derived_path")]
        rep = {"artifact": "r27_derived_inputs.json", "task_id": "MF-V1-VIDEO14B",
               "round": "R27", "row": "R27-01", "evidence_root": str(evr).replace("\\", "/"),
               "input_root": str(input_root).replace("\\", "/"),
               "neutral_bg_rgb": list(NEUTRAL_BG_RGB),
               "why": ("LoadImage returns (IMAGE, MASK); the graph used output 0 alone, so a "
                       "cutout reached the encoder as its raw RGB (98.859% of the pixels of "
                       "cast_dan_choi_standing.png are near-black).  The derived input is the "
                       "SAME pixels composited ONCE through alpha onto a flat neutral grey."),
               "engine_started": False, "model_loaded": False, "media_generated": False,
               "rows": rows, "composited_count": len(composed),
               "all_derived_are_opaque": all(not r["derived_has_alpha_channel"] for r in composed),
               "all_loadimage_pixels_previews_byte_exact":
                   all(r["preview_loadimage_pixels_is_byte_exact_derived"]
                       for r in composed),
               "all_previews_are_the_installed_area_tensor":
                   all(r.get("preview_matches_installed_area_tensor") for r in composed),
               "all_previews_have_a_pre_quantization_tensor_hash":
                   all(bool(r.get("preview_tensor_hash_before_quantization")) for r in composed),
               "all_resizes_preserve_aspect":
                   all(r["resize_plan"]["aspect_preserved"] and not r["resize_plan"]["crop_applied"]
                       for r in composed)}
        outp = evr / "raw" / "r27_derived_inputs.json"
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"composited": [{"file": r["file"], "derived_path": r["derived_path"],
                                          "derived_sha256": r["derived_sha256"],
                                          "derived_bytes": r["derived_bytes"],
                                          "encoder_input_preview": r["preview_encoder_input_path"],
                                          "resized_wh": r["resize_plan"]["resized_wh"]}
                                         for r in composed],
                          "derived_manifest": str(outp)}, indent=1, ensure_ascii=False))
        return 0
    if cmd == "build":
        tmpl, outdir = _p(sys.argv[2]), _p(sys.argv[3])
        evr = _p(sys.argv[4]) if len(sys.argv) > 4 else Path(EVIDENCE_ROOT)
        base = json.loads(tmpl.read_text(encoding="utf-8"))
        input_root = Path(r"C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/input")
        outdir.mkdir(parents=True, exist_ok=True)
        spec = {"template": str(tmpl), "template_sha256": sha256_file(tmpl),
                "canvas": list(CANVAS), "steps": STEPS, "ref_longer_side": REF_LONGER_SIDE,
                "input_root": str(input_root), "evidence_root": str(evr).replace("\\", "/"),
                "proposal_only": True, "engine_started": False, "model_loaded": False,
                "neutral_bg_rgb": list(NEUTRAL_BG_RGB),
                "source_first_frame_facts": SOURCE_FIRST_FRAME_FACTS,
                "forbidden_prompt_claims": {k: [p["pattern"] for p in v]
                                            for k, v in FORBIDDEN_PROMPT_CLAIMS.items()},
                "graphs": {}}
        for shot in ("BOOK", "TURN", "OCC"):
            g, ch = build_anchor(base, shot, input_root, evr)
            p = outdir / f"anchor_{shot.lower()}.i1.api.json"
            p.write_text(json.dumps(g, indent=1, ensure_ascii=False), encoding="utf-8")
            ch["graph"] = str(p)
            ch["graph_sha256"] = sha256_file(p)
            ch["nodes"] = len(g)
            oi_path = Path(OBJECT_INFO_LIVE)
            if oi_path.is_file():
                ch["object_info_validation"] = validate_proposal(
                    g, oi_path,
                    [r["loadimage_value"] for r in ch["refs"] if r.get("alpha_was_composited")])
            ch["instruction"] = instruction(shot)
            spec["graphs"][shot] = ch
        (outdir / "roundI1_spec.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"built": [v["graph"] for v in spec["graphs"].values()],
                          "refs_per_shot": {k: len(v["refs"]) for k, v in spec["graphs"].items()}},
                         indent=1, ensure_ascii=False))
        return 0
    if cmd == "correct":
        src, dst = _p(sys.argv[2]), _p(sys.argv[3])
        seed = int(sys.argv[sys.argv.index("--seed") + 1])
        extra = sys.argv[sys.argv.index("--extra") + 1]
        diagnosis = sys.argv[sys.argv.index("--diagnosis") + 1]
        g = json.loads(src.read_text(encoding="utf-8"))
        before = g[N_TXT]["inputs"]["text"]
        old_prefix = g[N_SAVE]["inputs"]["filename_prefix"]
        g[N_TXT]["inputs"]["text"] = before + " " + extra
        g[N_NOISE]["inputs"]["noise_seed"] = seed
        g[N_SAVE]["inputs"]["filename_prefix"] = old_prefix.replace("_i1", "_i1c1")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(g, indent=1, ensure_ascii=False), encoding="utf-8")
        # the diff is MEASURED, never asserted
        base = json.loads(src.read_text(encoding="utf-8"))
        diff = []
        for nid in sorted(set(base) | set(g)):
            b, a = base.get(nid), g.get(nid)
            if b == a:
                continue
            for k in (set((b or {}).get("inputs", {})) | set((a or {}).get("inputs", {}))):
                bv, av = (b or {}).get("inputs", {}).get(k), (a or {}).get("inputs", {}).get(k)
                if bv != av:
                    diff.append({"node": nid, "class_type": (a or b).get("class_type"),
                                 "input": k,
                                 "before": (str(bv)[:120] + "..." if isinstance(bv, str) and len(str(bv)) > 120 else bv),
                                 "after": (str(av)[:120] + "..." if isinstance(av, str) and len(str(av)) > 120 else av)})
        rep = {"artifact": "i1_correction.json", "task_id": "MF-V1-VIDEO14B", "round": "I1",
               "shot": "BOOK", "src": str(src), "dst": str(dst), "diagnosis": diagnosis,
               "seed_before": base[N_NOISE]["inputs"]["noise_seed"], "seed_after": seed,
               "instruction_sha256_before": hashlib.sha256(before.encode()).hexdigest(),
               "instruction_sha256_after": hashlib.sha256(g[N_TXT]["inputs"]["text"].encode()).hexdigest(),
               "instruction_chars_before": len(before), "instruction_chars_after": len(g[N_TXT]["inputs"]["text"]),
               "filename_prefix_before": old_prefix, "filename_prefix_after": g[N_SAVE]["inputs"]["filename_prefix"],
               "graph_sha256": sha256_file(dst), "graph_before_sha256": sha256_file(src),
               "measured_diff": diff,
               "changed_node_ids": sorted({d["node"] for d in diff}),
               "wiring_and_references_unchanged": all(d["node"] in (N_TXT, N_NOISE, N_SAVE) for d in diff)}
        (dst.parent / "i1_correction.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 0
    if cmd == "validate":
        g = json.loads(_p(sys.argv[2]).read_text(encoding="utf-8"))
        oi = json.loads(_p(sys.argv[3]).read_text(encoding="utf-8"))
        rep = validate(g, oi)
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 1 if rep["errors"] else 0
    print(f"unknown command {cmd!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
