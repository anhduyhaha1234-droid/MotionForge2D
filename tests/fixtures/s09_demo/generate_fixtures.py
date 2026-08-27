"""Generate SYNTHETIC stable-frame demo-loop fixtures for S09-T03.

Four loops jointly cover the six TARGET_PROFILE §7 S09-T03 risk classes
(binary acceptance: "selected loops jointly cover hard cut, mouth/expression
swap, phone contact, whole-body rotation/bed contact, group occlusion and
semantic graphic replacement"):

    d1_cut_graphic     hard_cut + semantic_graphic_replacement
    d2_mouth_phone     mouth_expression_swap + phone_contact
    d3_rotation_bed    whole_body_rotation (body-to-bed contact)
    d4_group_occlusion group_occlusion + hard_cut

Every loop ships THREE things:
  - ``media/<loop_id>.mp4``   the SOURCE loop (bitexact H.264, deterministic
    on a fixed ffmpeg build) carrying the source identity: original-palette
    sprites, a source-only watermark overlay and the source sign card;
  - ``sprites/<loop_id>/*.png``  REPLACEMENT assets (recolored silhouettes,
    head variants, replacement graphic) — the reskin pack;
  - ``manifests/<loop_id>.json``  the machine-executable replacement program
    (cuts, swap plan, contact anchors, z-order, rotation keyframes, graphic
    windows, watermark clean-plate rect) consumed verbatim by the S09-T03
    demo-job renderer.

Determinism: pure functions of seed + fixed ffmpeg build; regenerating with
the same seed reproduces byte-identical media (the test suite proves this).

Usage:
    python tests/fixtures/s09_demo/generate_fixtures.py \
        [--out tests/fixtures/s09_demo] [--seed 20260823]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H, FPS = 640, 360, 30
FIXTURE_DIR = Path(__file__).resolve().parent
DEFAULT_SEED = 20260823

# ffmpeg bitexact encode settings (identical policy to s09_renderer fixtures:
# deterministic on a fixed ffmpeg build; global -bitexact strips version strs)
ENC = [
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "18",
    "-pix_fmt",
    "yuv420p",
    "-g",
    "30",
    "-keyint_min",
    "30",
    "-threads",
    "1",
    "-bitexact",
]

#: The six canonical S09-T03 risk classes (overlay §7 binary acceptance).
RISK_CLASSES = (
    "hard_cut",
    "mouth_expression_swap",
    "phone_contact",
    "whole_body_rotation",
    "group_occlusion",
    "semantic_graphic_replacement",
)


# ── ffmpeg helpers ───────────────────────────────────────────────────────────


def encode_mp4(frames_rgb: np.ndarray, out_path: Path) -> None:
    """Encode RGB frames to a bitexact H.264 MP4 via ffmpeg stdin pipe."""
    n, h, w, _ = frames_rgb.shape
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{w}x{h}",
        "-r",
        str(FPS),
        "-i",
        "-",
        *ENC,
        str(out_path),
    ]
    proc = subprocess.run(cmd, input=frames_rgb.tobytes(), check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"encode failed for {out_path}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── deterministic background plates ─────────────────────────────────────────


def gradient_plate(c0: tuple[int, int, int], c1: tuple[int, int, int]) -> np.ndarray:
    """Static two-color vertical gradient frame (RGB uint8)."""
    ramp = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    arr = np.zeros((H, W, 3), dtype=np.uint8)
    for c in range(3):
        arr[:, :, c] = (c0[c] + (c1[c] - c0[c]) * ramp).astype(np.uint8)
    return arr


def checker_frame(idx: int, seed: int, rng: random.Random | None = None) -> np.ndarray:
    """Moving test-pattern frame (deterministic function of the frame index)."""
    rng = rng or random.Random(seed * 100003 + idx)
    img = Image.fromarray(
        gradient_plate((24, 28, 46), (70, 84, 118)), "RGB"
    )
    d = ImageDraw.Draw(img)
    cell = 40
    for gy in range(0, H, cell):
        for gx in range(0, W, cell):
            if (gx // cell + gy // cell + idx) % 2 == 0:
                d.rectangle(
                    (gx, gy, gx + cell - 1, gy + cell - 1),
                    fill=(34 + (idx * 3) % 60, 52, 78),
                )
    d.ellipse(
        (80 + (idx * 5) % (W - 160), 60, 200 + (idx * 5) % (W - 160), 180),
        outline=(220, 226, 240),
        width=3,
    )
    _speckle_rgb(img, random.Random(seed + idx), 12)
    return np.asarray(img, dtype=np.uint8)


def _speckle_rgb(img: Image.Image, rng: random.Random, count: int) -> None:
    px = img.load()
    for _ in range(count):
        x, y = rng.randrange(img.size[0]), rng.randrange(img.size[1])
        r, g, b = px[x, y][:3]
        j = rng.randint(-8, 8)
        px[x, y] = (max(0, min(255, r + j)), max(0, min(255, g + j)), max(0, min(255, b + j)))


# ── sprite drawing (Pillow, seeded, flat-cutout style) ──────────────────────


def _outline(
    d: ImageDraw.ImageDraw,
    coords: list[tuple[float, float]],
    ink: tuple[int, int, int, int],
) -> None:
    d.line(coords + [coords[0]], fill=ink, width=4, joint="curve")


def draw_character(palette: dict[str, Any], seed: int, variant: str = "base") -> Image.Image:
    """Flat-cutout character, 160x260 canvas, thick outline, seeded speckle."""
    rng = random.Random(seed)
    img = Image.new("RGBA", (160, 260), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    body = palette["body"]
    ink = palette["ink"]
    d.rounded_rectangle((40, 90, 120, 230), radius=28, fill=body, outline=ink, width=4)
    d.ellipse((48, 14, 112, 92), fill=palette["skin"], outline=ink, width=4)
    d.ellipse((70, 44, 78, 54), fill=ink)
    d.ellipse((86, 44, 94, 54), fill=ink)
    if variant == "mouth_open":
        d.ellipse((72, 64, 88, 80), fill=palette["mouth"], outline=ink, width=3)
    else:
        d.line((72, 72, 88, 72), fill=ink, width=3)
    d.rounded_rectangle((18, 100, 44, 190), radius=12, fill=body, outline=ink, width=4)
    d.rounded_rectangle((116, 100, 142, 190), radius=12, fill=body, outline=ink, width=4)
    d.rounded_rectangle(
        (52, 224, 76, 258), radius=10, fill=palette["legs"], outline=ink, width=4
    )
    d.rounded_rectangle(
        (84, 224, 108, 258), radius=10, fill=palette["legs"], outline=ink, width=4
    )
    _speckle(img, rng, body, 36)
    return img


def draw_head_only(palette: dict[str, Any], seed: int, variant: str) -> Image.Image:
    """Head crop used as the pose_swap template pair (closed/open mouth)."""
    full = draw_character(palette, seed, variant=variant)
    return full.crop((44, 10, 116, 96))


def draw_phone(palette: dict[str, Any]) -> Image.Image:
    img = Image.new("RGBA", (56, 96), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (2, 2, 54, 94), radius=10, fill=palette["shell"], outline=palette["ink"], width=4
    )
    d.rectangle((10, 14, 46, 78), fill=palette["screen"])
    return img


def draw_pillar(palette: dict[str, Any]) -> Image.Image:
    """Full-height foreground occluder: hides a crossing character entirely."""
    img = Image.new("RGBA", (130, 360), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle(
        (10, 0, 120, 360), fill=palette["stone"], outline=palette["ink"], width=4
    )
    for y in range(30, 360, 60):
        d.line((16, y, 114, y), fill=palette["ink"], width=2)
    return img


def draw_card(palette: dict[str, Any], bars: tuple[int, int, int, int]) -> Image.Image:
    """Semantic graphic card with abstract text bars."""
    img = Image.new("RGBA", (180, 110), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (2, 2, 178, 108), radius=8, fill=palette["card"], outline=palette["ink"], width=4
    )
    y = 20
    for wdt in bars:
        d.rounded_rectangle((16, y, 16 + wdt, y + 10), radius=4, fill=palette["bars"])
        y += 20
    return img


def draw_bed(palette: dict[str, Any]) -> Image.Image:
    img = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (4, 30, 296, 96),
        radius=14,
        fill=palette["mattress"],
        outline=palette["ink"],
        width=4,
    )
    d.rounded_rectangle(
        (4, 8, 84, 60), radius=12, fill=palette["pillow"], outline=palette["ink"], width=4
    )
    return img


def draw_watermark(palette: dict[str, Any]) -> Image.Image:
    """Source-only overlay mark (bottom-right) — must be removed in output."""
    img = Image.new("RGBA", (90, 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 6, 34, 38), fill=palette["mark"])
    d.rounded_rectangle((40, 12, 88, 22), radius=4, fill=palette["mark"])
    d.rounded_rectangle((40, 26, 74, 34), radius=4, fill=palette["mark"])
    return img


def make_replacement(
    sprite: Image.Image, hue_shift: tuple[int, int, int], seed: int
) -> Image.Image:
    """Recolor + slightly grown silhouette replacement asset.

    Alpha grows 2px per side (MaxFilter) so a route clipping the replacement
    to the SOURCE silhouette measurably loses rim pixels.
    """
    arr = np.array(sprite, dtype=np.int16)
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3].copy()
    mask = alpha > 0
    for c in range(3):
        channel = rgb[:, :, c]
        channel[mask] = np.clip(channel[mask].astype(np.int16) + hue_shift[c], 0, 255)
    grown_alpha = sprite.split()[3].filter(ImageFilter.MaxFilter(5))
    channels = [Image.fromarray(rgb[:, :, c].astype(np.uint8)) for c in range(3)]
    out = Image.merge("RGBA", (*channels, grown_alpha))
    _speckle(out, random.Random(seed), (255, 255, 255), 20)
    return out


def _speckle(img: Image.Image, rng: random.Random, base: tuple[int, ...], count: int) -> None:
    px = img.load()
    w, h = img.size
    for _ in range(count):
        x, y = rng.randrange(w), rng.randrange(h)
        r, g, b, a = px[x, y]
        if a > 200:
            j = rng.randint(-14, 14)
            px[x, y] = (
                max(0, min(255, r + j)),
                max(0, min(255, g + j)),
                max(0, min(255, b + j)),
                255,
            )


def compose(
    bg: Image.Image, sprite: Image.Image, center: tuple[int, int], angle: float = 0.0
) -> Image.Image:
    """Alpha-composite sprite rotated by `angle` deg with center at `center`."""
    layer = sprite
    if angle % 360 != 0.0:
        layer = sprite.rotate(angle, resample=Image.BILINEAR, expand=True)
    lw, lh = layer.size
    px, py = int(center[0] - lw // 2), int(center[1] - lh // 2)
    out = bg.copy()
    out.alpha_composite(layer, (px, py))
    return out


# ── palettes ─────────────────────────────────────────────────────────────────

PAL_SRC_A = {
    "body": (66, 133, 244, 255),
    "skin": (255, 213, 170, 255),
    "legs": (52, 103, 194, 255),
    "mouth": (183, 58, 58, 255),
    "ink": (20, 24, 31, 255),
}
PAL_SRC_B = {
    "body": (214, 106, 58, 255),
    "skin": (255, 205, 160, 255),
    "legs": (168, 76, 40, 255),
    "mouth": (120, 40, 40, 255),
    "ink": (24, 20, 18, 255),
}
PAL_SRC_C = {
    "body": (86, 168, 96, 255),
    "skin": (250, 215, 180, 255),
    "legs": (56, 122, 66, 255),
    "mouth": (140, 52, 52, 255),
    "ink": (18, 26, 20, 255),
}
PHONE_PAL = {
    "shell": (32, 33, 36, 255),
    "screen": (138, 232, 164, 255),
    "ink": (12, 12, 12, 255),
}
PILLAR_PAL = {"stone": (150, 152, 160, 255), "ink": (28, 30, 36, 255)}
SIGN_PAL = {"card": (245, 240, 225, 255), "bars": (52, 78, 121, 255), "ink": (30, 30, 30, 255)}
BED_PAL = {
    "mattress": (222, 226, 235, 255),
    "pillow": (250, 250, 250, 255),
    "ink": (40, 44, 52, 255),
}
WM_PAL = {"mark": (128, 128, 128, 165)}
REPLACEMENT_SHIFT = (70, -35, 95)


# ── loop builders ────────────────────────────────────────────────────────────


def build_d1(out: Path, seed: int) -> tuple[dict[str, Any], dict[str, str]]:
    """Hard cut @45 + semantic sign-card replacement + source watermark."""
    n, cut = 90, 45
    grad = gradient_plate((32, 48, 74), (88, 120, 160))
    frames = [grad.copy() for _ in range(cut)] + [checker_frame(i, seed) for i in range(n - cut)]
    pil: list[Image.Image] = [Image.fromarray(f, "RGB").convert("RGBA") for f in frames]
    # source identity: hero holding the ORIGINAL sign (frames 0..44) + watermark in seg A
    src_card = draw_card(SIGN_PAL, (140, 120, 132, 90))
    for f in range(cut):
        pil[f] = compose(pil[f], draw_character(PAL_SRC_A, seed), (170, 210))
        pil[f] = compose(pil[f], src_card, (430, 110))
        pil[f].alpha_composite(draw_watermark(WM_PAL), (W - 100, H - 48))
    # seg B keeps a plain wall mount where the replacement card will go
    hashes: dict[str, str] = {}
    spr_dir = out / "sprites" / "d1_cut_graphic"
    spr_dir.mkdir(parents=True, exist_ok=True)
    rep_card = make_replacement(
        draw_card(SIGN_PAL, (150, 96, 138, 84)), REPLACEMENT_SHIFT, seed + 11
    )
    p_card_src = spr_dir / "sign_source.png"
    src_card.save(p_card_src)
    p_card_rep = spr_dir / "sign_replacement.png"
    rep_card.save(p_card_rep)
    hashes["sign_source"] = sha256_file(p_card_src)
    hashes["sign_replacement"] = sha256_file(p_card_rep)
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    path = media / "d1_cut_graphic.mp4"
    encode_mp4(np.stack([np.asarray(im.convert("RGB"), dtype=np.uint8) for im in pil]), path)
    manifest = {
        "loop_id": "d1_cut_graphic",
        "risk_classes": ["hard_cut", "semantic_graphic_replacement"],
        "resolution": {"width": W, "height": H},
        "fps": FPS,
        "frame_count": n,
        "time_base": "1/30",
        "start_time_ms": 0,
        "generation": {
            "tool": "PIL plates + ffmpeg libx264 bitexact",
            "seed": seed,
        },
        "cuts": [{"cut_frame": cut, "tolerance_frames": 1}],
        "segments": [
            {"shot_id": "shot_a", "start_frame": 0, "end_frame": cut - 1},
            {"shot_id": "shot_b", "start_frame": cut, "end_frame": n - 1},
        ],
        "replacement_program": [
            {
                "op": "graphic_replace",
                "replacement_png": "sprites/d1_cut_graphic/sign_replacement.png",
                # Stable machine binding (C4 §4.2): corrections target THIS
                # key, never an array position or filename.
                "layer_id": "d1_sign_graphic",
                "center_px": [430, 110],
                "start_frame": 50,
                "end_frame": n - 1,
            },
            {
                "op": "watermark_remove",
                "rect_px": [W - 104, H - 52, W - 6, H - 4],
                "sample_margin_px": 8,
                "start_frame": 0,
                "end_frame": cut - 1,
                "layer_id": "d1_watermark",
            },
        ],
        "annotations": {
            "watermark": {
                "kind": "source_only_overlay",
                "present_frames": [0, cut - 1],
                "rect_px": [W - 104, H - 52, W - 6, H - 4],
            },
            "graphic": {
                "kind": "semantic_graphic",
                "source_center_px": [430, 110],
                "required_content": "text_bars_story_equivalent",
            },
        },
    }
    hashes["media"] = sha256_file(path)
    return manifest, hashes


def build_d2(out: Path, seed: int) -> tuple[dict[str, Any], dict[str, str]]:
    """Mouth/expression swaps every 15 frames + phone-to-hand contact."""
    n, swap_every = 60, 15
    grad = gradient_plate((42, 63, 44), (135, 168, 111))
    head_closed = draw_head_only(PAL_SRC_A, seed, "base")
    head_open = draw_head_only(PAL_SRC_A, seed + 1, "mouth_open")
    rep_closed = make_replacement(head_closed, REPLACEMENT_SHIFT, seed + 2)
    rep_open = make_replacement(head_open, REPLACEMENT_SHIFT, seed + 3)
    phone = draw_phone(PHONE_PAL)
    torso = draw_character(PAL_SRC_A, seed).crop((0, 90, 160, 260))
    center = (320, 190)
    frames: list[np.ndarray] = []
    swap_plan: list[dict[str, Any]] = []
    for f in range(n):
        open_state = (f // swap_every) % 2 == 1
        if f > 0 and (f % swap_every) == 0:
            swap_plan.append(
                {
                    "swap_frame": f,
                    "from_state": "closed",
                    "to_state": "open" if open_state else "closed",
                }
            )
        base = Image.fromarray(grad, "RGB").convert("RGBA")
        base.alpha_composite(torso, (center[0] - 80, center[1] - 60))
        # phone enters the hand at frame 30 and stays (contact + z above torso)
        if f >= 30:
            base.alpha_composite(phone, (center[0] + 18, center[1] + 8))
        head = rep_open if open_state else rep_closed
        base = compose(base, head, (320, 96))
        frames.append(np.asarray(base.convert("RGB"), dtype=np.uint8))
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    path = media / "d2_mouth_phone.mp4"
    encode_mp4(np.stack(frames), path)
    spr_dir = out / "sprites" / "d2_mouth_phone"
    spr_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name, im in (
        ("head_closed_rep", rep_closed),
        ("head_open_rep", rep_open),
        ("phone_replacement", make_replacement(phone, (40, 60, -30), seed + 4)),
    ):
        p = spr_dir / f"{name}.png"
        im.save(p)
        hashes[name] = sha256_file(p)
    manifest = {
        "loop_id": "d2_mouth_phone",
        "risk_classes": ["mouth_expression_swap", "phone_contact"],
        "resolution": {"width": W, "height": H},
        "fps": FPS,
        "frame_count": n,
        "time_base": "1/30",
        "start_time_ms": 0,
        "generation": {"tool": "PIL plates + ffmpeg libx264 bitexact", "seed": seed},
        "cuts": [],
        "segments": [{"shot_id": "shot_a", "start_frame": 0, "end_frame": n - 1}],
        "replacement_program": [
            {
                "op": "pose_swap",
                "region_xywh_norm": [0.4375, 0.0833, 0.225, 0.2389],
                "templates": {
                    "closed": "sprites/d2_mouth_phone/head_closed_rep.png",
                    "open": "sprites/d2_mouth_phone/head_open_rep.png",
                },
                "swap_plan": swap_plan,
                "center_px": [320, 96],
                "initial_state": "closed",
                # Stable machine binding (C4 §4.2).
                "layer_id": "d2_mouth_head",
            },
            {
                "op": "graphic_replace",
                "replacement_png": "sprites/d2_mouth_phone/phone_replacement.png",
                "center_px": [338, 238],
                "start_frame": 30,
                "end_frame": n - 1,
                "layer_id": "d2_phone",
            },
        ],
        "annotations": {
            "phone_contact": {
                "hand_anchor_norm": [0.5312, 0.6528],
                "contact_start_frame": 30,
                "z_order": "phone_above_torso",
            }
        },
    }
    hashes["media"] = sha256_file(path)
    return manifest, hashes


def build_d3(out: Path, seed: int) -> tuple[dict[str, Any], dict[str, str]]:
    """Whole-body rotation 0->180 deg while translating onto the bed."""
    n = 72
    grad = gradient_plate((58, 46, 70), (128, 104, 148))
    bed = draw_bed(BED_PAL)
    hero = draw_character(PAL_SRC_A, seed)
    rep_hero = make_replacement(hero, REPLACEMENT_SHIFT, seed + 5)
    frames: list[np.ndarray] = []
    for f in range(n):
        t = f / (n - 1)
        angle = round(180.0 * t, 2)
        cx = round(140 + (330 - 140) * t)
        cy = round(150 + (250 - 150) * t)
        base = Image.fromarray(grad, "RGB").convert("RGBA")
        base.alpha_composite(bed, (300, 210))
        base = compose(base, rep_hero, (cx, cy), angle=angle)
        frames.append(np.asarray(base.convert("RGB"), dtype=np.uint8))
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    path = media / "d3_rotation_bed.mp4"
    encode_mp4(np.stack(frames), path)
    spr_dir = out / "sprites" / "d3_rotation_bed"
    spr_dir.mkdir(parents=True, exist_ok=True)
    p = spr_dir / "hero_replacement.png"
    rep_hero.save(p)
    hashes = {"hero_replacement": sha256_file(p)}
    manifest = {
        "loop_id": "d3_rotation_bed",
        "risk_classes": ["whole_body_rotation"],
        "resolution": {"width": W, "height": H},
        "fps": FPS,
        "frame_count": n,
        "time_base": "1/30",
        "start_time_ms": 0,
        "generation": {"tool": "PIL plates + ffmpeg libx264 bitexact", "seed": seed},
        "cuts": [],
        "segments": [{"shot_id": "shot_a", "start_frame": 0, "end_frame": n - 1}],
        "replacement_program": [
            {
                "op": "affine_keyframes",
                "replacement_png": "sprites/d3_rotation_bed/hero_replacement.png",
                # Stable machine binding (C4 §4.2).
                "layer_id": "d3_hero",
                "keyframes": [
                    {
                        "start_frame": 0,
                        "end_frame": n - 1,
                        "angle_start_deg": 0.0,
                        "angle_end_deg": 180.0,
                        "center_start_px": [140, 150],
                        "center_end_px": [330, 250],
                    }
                ],
            }
        ],
        "annotations": {
            "bed_contact": {
                "contact_anchor_norm": [0.5156, 0.6944],
                "contact_frame": n - 1,
                "z_order": "body_above_mattress",
            }
        },
    }
    hashes["media"] = sha256_file(path)
    return manifest, hashes


def build_d4(out: Path, seed: int) -> tuple[dict[str, Any], dict[str, str]]:
    """Group occlusion behind a pillar, hard cut to a 3-character group shot."""
    n, cut = 96, 48
    grad = gradient_plate((70, 62, 54), (150, 132, 108))
    pillar = draw_pillar(PILLAR_PAL)
    walker = draw_character(PAL_SRC_B, seed + 6)
    rep_walker = make_replacement(walker, (-60, 40, 70), seed + 7)
    palettes = (PAL_SRC_B, PAL_SRC_C, PAL_SRC_A)
    group = [draw_character(p, seed + 8 + i) for i, p in enumerate(palettes)]
    rep_group = [
        make_replacement(g, REPLACEMENT_SHIFT, seed + 20 + i) for i, g in enumerate(group)
    ]
    frames: list[np.ndarray] = []
    for f in range(n):
        if f < cut:
            # shot A: walker crosses LEFT->RIGHT BEHIND the pillar (z: pillar last)
            t = f / (cut - 1)
            cx = round(80 + 480 * t)
            base = Image.fromarray(grad, "RGB").convert("RGBA")
            base = compose(base, rep_walker, (cx, 200))
            base.alpha_composite(pillar, (270, 0))
        else:
            # shot B (after hard cut): three-character group, defined z order
            g = f - cut
            bob = (g % 30) // 15  # tiny held-pose alternation for liveliness
            base = Image.fromarray(grad, "RGB").convert("RGBA")
            xs = (140, 320, 500)
            for i, (spr, x) in enumerate(zip(rep_group, xs)):
                base = compose(base, spr, (x, 210 + bob * (4 - i)))
        frames.append(np.asarray(base.convert("RGB"), dtype=np.uint8))
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    path = media / "d4_group_occlusion.mp4"
    encode_mp4(np.stack(frames), path)
    spr_dir = out / "sprites" / "d4_group_occlusion"
    spr_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    sprites_to_save = [("walker_replacement", rep_walker)]
    sprites_to_save.extend(
        (f"group_{i}_replacement", im) for i, im in enumerate(rep_group)
    )
    for name, im in sprites_to_save:
        p = spr_dir / f"{name}.png"
        im.save(p)
        hashes[name] = sha256_file(p)
    manifest = {
        "loop_id": "d4_group_occlusion",
        "risk_classes": ["group_occlusion", "hard_cut"],
        "resolution": {"width": W, "height": H},
        "fps": FPS,
        "frame_count": n,
        "time_base": "1/30",
        "start_time_ms": 0,
        "generation": {"tool": "PIL plates + ffmpeg libx264 bitexact", "seed": seed},
        "cuts": [{"cut_frame": cut, "tolerance_frames": 1}],
        "segments": [
            {"shot_id": "cross_shot", "start_frame": 0, "end_frame": cut - 1},
            {"shot_id": "group_shot", "start_frame": cut, "end_frame": n - 1},
        ],
        "replacement_program": [
            {
                "op": "affine_keyframes",
                "replacement_png": "sprites/d4_group_occlusion/walker_replacement.png",
                # Stable machine binding (C4 §4.2).
                "layer_id": "d4_walker",
                "keyframes": [
                    {
                        "start_frame": 0,
                        "end_frame": cut - 1,
                        "angle_start_deg": 0.0,
                        "angle_end_deg": 0.0,
                        "center_start_px": [80, 200],
                        "center_end_px": [560, 200],
                    }
                ],
            },
            {
                "op": "group_place",
                "placements": [
                    {
                        "replacement_png": f"sprites/d4_group_occlusion/group_{i}_replacement.png",
                        "center_px": [x, 210 + ((g % 30) // 15) * (4 - i)],
                        # Stable machine binding (C4 §4.2): z-order
                        # corrections re-bind THIS key, never the index.
                        "layer_id": f"d4_group_{i}",
                        "z_order": i,
                        "start_frame": cut,
                        "end_frame": n - 1,
                    }
                    for i, x in enumerate((140, 320, 500))
                ],
            },
        ],
        "annotations": {
            "occlusion": {
                "occluder": "pillar",
                "occluder_rect_px": [270, 0, 400, 360],
                "hidden_window_frames": [24, 40],
                "z_order": "walker_behind_pillar",
            }
        },
    }
    hashes["media"] = sha256_file(path)
    return manifest, hashes


BUILDERS = {
    "d1_cut_graphic": build_d1,
    "d2_mouth_phone": build_d2,
    "d3_rotation_bed": build_d3,
    "d4_group_occlusion": build_d4,
}

REQUIRED_MANIFEST_KEYS = {
    "loop_id",
    "risk_classes",
    "resolution",
    "fps",
    "frame_count",
    "time_base",
    "start_time_ms",
    "generation",
    "cuts",
    "segments",
    "replacement_program",
}


def _collect_layer_ids(manifest: dict[str, Any]) -> list[str]:
    """Collect every stable ``layer_id`` binding stamped in a manifest.

    Mirrors the C4 §4.2 stable-binding surface: operation-level bindings
    first (program order), then placement-level bindings inside grouped
    operations (their own array order).  The loops index publishes these so
    consumers can address corrections by machine key without re-parsing
    every manifest.
    """
    ids: list[str] = []
    for entry in manifest.get("replacement_program", []):
        if not isinstance(entry, dict):
            continue
        lid = entry.get("layer_id")
        if isinstance(lid, str) and lid and lid not in ids:
            ids.append(lid)
        placements = entry.get("placements")
        if isinstance(placements, list):
            for placement in placements:
                if not isinstance(placement, dict):
                    continue
                plid = placement.get("layer_id")
                if isinstance(plid, str) and plid and plid not in ids:
                    ids.append(plid)
    return ids


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=FIXTURE_DIR)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args(argv)
    out = args.out.resolve()
    (out / "manifests").mkdir(parents=True, exist_ok=True)
    index: dict[str, Any] = {
        "schema_version": 1,
        "seed": args.seed,
        "risk_classes_canonical": list(RISK_CLASSES),
        "loops": [],
    }
    gen_src = Path(__file__).read_bytes()
    index["generator_sha256"] = hashlib.sha256(gen_src).hexdigest()
    covered: set[str] = set()
    for lid, builder in BUILDERS.items():
        print(f"[gen] {lid} ...", flush=True)
        manifest, hashes = builder(out, args.seed)
        missing = REQUIRED_MANIFEST_KEYS - set(manifest.keys())
        if missing:
            raise SystemExit(f"manifest {lid} missing keys: {sorted(missing)}")
        mpath = out / "manifests" / f"{lid}.json"
        mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        covered.update(manifest["risk_classes"])
        index["loops"].append(
            {
                "loop_id": lid,
                "risk_classes": manifest["risk_classes"],
                "manifest_path": f"manifests/{lid}.json",
                "media_path": f"media/{lid}.mp4",
                "manifest_sha256": sha256_file(mpath),
                "media_sha256": hashes["media"],
                "frame_count": manifest["frame_count"],
                "layer_ids": _collect_layer_ids(manifest),
            }
        )
        print(f"[gen] {lid} done  media_sha256={hashes['media'][:16]}...", flush=True)
    missing_classes = set(RISK_CLASSES) - covered
    if missing_classes:
        raise SystemExit(f"loops do not jointly cover risk classes: {sorted(missing_classes)}")
    ipath = out / "loops_index.json"
    ipath.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[gen] joint coverage OK ({len(covered)}/6 classes) -> {ipath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
