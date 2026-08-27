"""Generate SYNTHETIC golden fixtures for S09-T00-I03 (deterministic).

Six fixtures map 1:1 to the six S09-T03 risk classes (TARGET_PROFILE §7):

    f1_hard_cut              REF-R01 hard cuts + semantic transition
    f2_mouth_swap            REF-R02 mouth/expression pose swaps
    f3_phone_contact         REF-R03 phone/hand/face contact + prop z-order
    f4_body_rotation         REF-R04 whole-body rotation + bed contact
    f5_group_occlusion       REF-R05 group movement/occlusion
    f6_graphic_replacement   semantic graphic replacement + source-only overlay

Pipeline per fixture:
    1. background frames come from ffmpeg lavfi sources (gradients /
       smptebars / testsrc2 / color) piped as rawvideo;
    2. sprites are drawn with Pillow using a seeded RNG (flat cutout style,
       thick outlines) -- fully deterministic;
    3. per-frame composition uses analytic ground truth (integer placements,
       explicit per-frame trajectory tables stored in the manifest);
    4. encoding is libx264 yuv420p with bitexact flags and -threads 1 so two
       generations produce byte-identical MP4s on the same ffmpeg build.

Ground truth is SYNTHETIC metadata defined here at generation time -- it is
NOT derived from any user media.

Usage:
    python tests/fixtures/s09_renderer/generate_fixtures.py \
        [--out tests/fixtures/s09_renderer] [--seed 20260823]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H, FPS = 640, 360, 30
FIXTURE_DIR = Path(__file__).resolve().parent
DEFAULT_SEED = 20260823

# ffmpeg bitexact encode settings (deterministic on a fixed ffmpeg build)
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
    # global bitexact flag: strips encoder/muxer version strings so two runs
    # of this generator produce byte-identical MP4s on a fixed ffmpeg build
    # (ffmpeg 8 rejects per-stream '-movflags +bitexact' syntax)
    "-bitexact",
]


# ── ffmpeg helpers ────────────────────────────────────────────────────────────


def read_lavfi(spec: str, frames: int) -> np.ndarray:
    """Read `frames` RGB frames from an ffmpeg lavfi source."""
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        spec,
        "-frames:v",
        str(frames),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"lavfi source failed: {spec}\n{proc.stderr.decode()}")
    expected = frames * H * W * 3
    buf = proc.stdout
    if len(buf) < expected:
        raise RuntimeError(f"lavfi source {spec!r} produced {len(buf)} bytes, need {expected}")
    arr = np.frombuffer(buf[:expected], dtype=np.uint8).reshape(frames, H, W, 3)
    return arr.copy()


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


# ── sprite drawing (Pillow, seeded, flat cutout style) ───────────────────────


def _outline(draw: ImageDraw.ImageDraw, coords: list[tuple[float, float]], ink: str) -> None:
    draw.line(coords + [coords[0]], fill=ink, width=4, joint="curve")


def draw_character(palette: dict[str, str], seed: int, variant: str = "base") -> Image.Image:
    """Flat-cutout character, 160x260 canvas, thick outline, seeded speckle."""
    rng = random.Random(seed)
    img = Image.new("RGBA", (160, 260), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    body = palette["body"]
    ink = palette["ink"]
    # torso
    d.rounded_rectangle((40, 90, 120, 230), radius=28, fill=body, outline=ink, width=4)
    # head
    d.ellipse((48, 14, 112, 92), fill=palette["skin"], outline=ink, width=4)
    # eyes
    d.ellipse((70, 44, 78, 54), fill=ink)
    d.ellipse((86, 44, 94, 54), fill=ink)
    # mouth variants
    if variant == "mouth_open":
        d.ellipse((72, 64, 88, 80), fill=palette["mouth"], outline=ink, width=3)
    else:
        d.line((72, 72, 88, 72), fill=ink, width=3)
    # arms
    d.rounded_rectangle((18, 100, 44, 190), radius=12, fill=body, outline=ink, width=4)
    d.rounded_rectangle((116, 100, 142, 190), radius=12, fill=body, outline=ink, width=4)
    # legs
    d.rounded_rectangle((52, 224, 76, 258), radius=10, fill=palette["legs"], outline=ink, width=4)
    d.rounded_rectangle((84, 224, 108, 258), radius=10, fill=palette["legs"], outline=ink, width=4)
    _speckle(img, rng, body, 40)
    return img


def draw_phone(palette: dict[str, str]) -> Image.Image:
    img = Image.new("RGBA", (56, 96), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (2, 2, 54, 94), radius=10, fill=palette["shell"], outline=palette["ink"], width=4
    )
    d.rectangle((10, 14, 46, 78), fill=palette["screen"])
    return img


def draw_pillar(palette: dict[str, str]) -> Image.Image:
    """Full-height foreground occluder: hides a crossing character entirely.

    J1-C2-v2 geometry: char_a's rep sprite is 164 wide and its walk crosses
    x 222..522 during the hidden window [28,45]; a 130px pillar can never
    fully cover that (the old window only passed because the legacy
    compositor stretched the occluder full-frame).  The pillar is now 310px
    wide with an opaque core x 4..306 (abs 221..523 when centered at 372),
    so the hide window is geometrically true under per-region placement.
    """
    img = Image.new("RGBA", (310, 360), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((4, 0, 306, 360), fill=palette["stone"], outline=palette["ink"], width=4)
    for y in range(30, 360, 60):
        d.line((16, y, 294, y), fill=palette["ink"], width=2)
    return img


def draw_sign(palette: dict[str, str]) -> Image.Image:
    """Semantic graphic: card with abstract text bars (story-equivalent)."""
    img = Image.new("RGBA", (180, 110), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (2, 2, 178, 108), radius=8, fill=palette["card"], outline=palette["ink"], width=4
    )
    y = 20
    for wdt in (140, 120, 132, 90):
        d.rounded_rectangle((16, y, 16 + wdt, y + 10), radius=4, fill=palette["bars"])
        y += 20
    return img


def draw_bed(palette: dict[str, str]) -> Image.Image:
    img = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (4, 30, 296, 96), radius=14, fill=palette["mattress"], outline=palette["ink"], width=4
    )
    d.rounded_rectangle(
        (4, 8, 84, 60), radius=12, fill=palette["pillow"], outline=palette["ink"], width=4
    )
    return img


def draw_watermark(palette: dict[str, str]) -> Image.Image:
    """Source-only overlay: channel mark bottom-right, must be removed."""
    img = Image.new("RGBA", (90, 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 6, 34, 38), fill=palette["mark"])
    d.rounded_rectangle((40, 12, 88, 22), radius=4, fill=palette["mark"])
    d.rounded_rectangle((40, 26, 74, 34), radius=4, fill=palette["mark"])
    return img


def make_replacement(
    sprite: Image.Image, hue_shift: tuple[int, int, int], seed: int
) -> Image.Image:
    """Recolor + slightly larger silhouette replacement asset (pose_swap route).

    The alpha grows by 2px on every side (MaxFilter) so a route that clips the
    replacement to the SOURCE silhouette measurably loses rim pixels, while a
    correct route keeps them.
    """
    arr = np.array(sprite, dtype=np.int16)
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3].copy()
    mask = alpha > 0
    for c in range(3):
        channel = rgb[:, :, c]
        channel[mask] = np.clip(channel[mask].astype(np.int16) + hue_shift[c], 0, 255)
    grown_alpha = sprite.split()[3].filter(ImageFilter.MaxFilter(5))
    out = Image.merge(
        "RGBA", (*[Image.fromarray(rgb[:, :, c].astype(np.uint8)) for c in range(3)], grown_alpha)
    )
    rng = random.Random(seed)
    _speckle(out, rng, (255, 255, 255), 24)
    return out


def _speckle(img: Image.Image, rng: random.Random, base: tuple[int, ...], count: int) -> None:
    """Deterministic texture speckle inside opaque areas."""
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


PALETTE_A = {
    "body": (66, 133, 244, 255),
    "skin": (255, 213, 170, 255),
    "legs": (52, 103, 194, 255),
    "mouth": (183, 58, 58, 255),
    "ink": (20, 24, 31, 255),
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


# ── composition helpers ──────────────────────────────────────────────────────


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


def lin(
    start: tuple[int, int], end: tuple[int, int], frames: list[int], f0: int, f1: int
) -> dict[int, tuple[int, int]]:
    """Linear interpolation table over inclusive frame range [f0, f1]."""
    span = max(1, f1 - f0)
    return {
        f: (
            round(start[0] + (end[0] - start[0]) * (f - f0) / span),
            round(start[1] + (end[1] - start[1]) * (f - f0) / span),
        )
        for f in frames
        if f0 <= f <= f1
    }


def const(pos: tuple[int, int], frames: list[int]) -> dict[int, tuple[int, int]]:
    return {f: pos for f in frames}


def emit_source_plate(out: Path, fid: str, frames_rgb: np.ndarray) -> dict[str, Any]:
    """Encode the replacement-free SOURCE plate consumed by the v2 renderer.

    The plate is the renderer's input scene (background + non-replaced
    elements), encoded with the same bitexact settings as the fixture media so
    hashes stay stable across regenerations. The v2 benchmark measures the
    renderer's OUTPUT against ground truth; this plate is what the renderer
    actually receives as source input (F2 remediation).
    """
    pdir = out / "render_plates" / fid
    pdir.mkdir(parents=True, exist_ok=True)
    ppath = pdir / "source_plate.mp4"
    encode_mp4(frames_rgb, ppath)
    return {
        "path": f"render_plates/{fid}/source_plate.mp4",
        "sha256": sha256_file(ppath),
        "frame_count": int(frames_rgb.shape[0]),
    }


def static_plate_frames(bg_frame: np.ndarray, n: int) -> np.ndarray:
    """Repeat a static background frame n times for plate encoding."""
    return np.repeat(bg_frame[0:1], n, axis=0)


# ── fixture builders ─────────────────────────────────────────────────────────


def build_f1(out: Path, seed: int) -> tuple[dict[str, Any], dict[str, str]]:
    """Hard cut + a typed replacement that must survive the cut.

    Segment A (0..44): static gradient with a static sign graphic; segment B
    (45..89): moving testsrc2 with the SAME sign at its second position. The
    sign is the typed ``prop_trajectory`` replacement the renderer composites;
    the hard cut at 45 is preserved by the plate itself so the route must keep
    cut semantics while placing both sign instances.
    """
    n, cut = 90, 45
    # gradients has seed=-1 (random) by default -> pin it for determinism
    spec_a = f"gradients=size={W}x{H}:rate={FPS}:speed=0:c0=0x20304a:c1=0x5878a0:seed={seed}"
    seg_a = read_lavfi(spec_a, cut)
    seg_b = read_lavfi(f"testsrc2=size={W}x{H}:rate={FPS}", n - cut)
    frames = np.concatenate([seg_a, seg_b], axis=0)
    sign = draw_sign(SIGN_PAL)
    rep_sign = make_replacement(sign, REPLACEMENT_SHIFT, seed + 30)
    all_f = list(range(n))
    sign_pos: dict[int, tuple[int, int]] = {}
    sign_pos.update(const((140, 90), [f for f in all_f if f < cut]))
    sign_pos.update(const((480, 250), [f for f in all_f if f >= cut]))
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    path = media / "f1_hard_cut.mp4"
    encode_mp4(frames, path)
    spr_dir = out / "sprites" / "f1_hard_cut"
    spr_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name, im in (("sign_src", sign), ("sign_rep", rep_sign)):
        p = spr_dir / f"{name}.png"
        im.save(p)
        hashes[name] = sha256_file(p)
    manifest = {
        "fixture_id": "f1_hard_cut",
        "risk_class": "hard_cut",
        "t03_loop": "REF-R01",
        "resolution": {"width": W, "height": H},
        "fps": FPS,
        "frame_count": n,
        "time_base": "1/30",
        "start_time_ms": 0,
        "generation": {
            "tool": "ffmpeg lavfi (gradients speed=0, testsrc2) + libx264 bitexact",
            "sources": [spec_a, f"testsrc2=size={W}x{H}:rate={FPS}"],
            "seed": seed,
        },
        "cuts": [{"cut_frame": cut, "tolerance_frames": 1}],
        "segments": [
            {"shot_id": "shot_a", "start_frame": 0, "end_frame": cut - 1},
            {"shot_id": "shot_b", "start_frame": cut, "end_frame": n - 1},
        ],
        # v2 render contract: renderer receives source_plate.mp4 + this
        # replacement spec and must produce rendered_output.mp4.  C2-PREP:
        # f1 carries a TYPED replacement (sign graphic) whose position jumps
        # at the cut -- the route must place both instances while the plate
        # preserves the hard-cut segment structure.
        "render_contract": {
            "source_plate": emit_source_plate(out, "f1_hard_cut", frames),
            "replacements": [
                {
                    "layer_id": "sign",
                    "kind": "prop_trajectory",
                    "assets_by_state": {
                        "default": {
                            "file": "sprites/f1_hard_cut/sign_rep.png",
                            "sha256": hashes["sign_rep"],
                        }
                    },
                    "positions_by_frame": {
                        str(k): list(v) for k, v in sign_pos.items()
                    },
                }
            ],
            "note": (
                "cut/segmentation fixture: the typed sign replacement must "
                "land on both sides of the cut; cut semantics live in the "
                "plate itself"
            ),
        },
        "metrics_applicable": ["cut_error_frames", "timebase_error_frames", "frame_error"],
    }
    hashes["media"] = sha256_file(path)
    return manifest, hashes


def build_f2(out: Path, seed: int) -> tuple[dict[str, Any], dict[str, str]]:
    """Mouth/expression pose swaps every 15 frames over a static gradient."""
    n = 60
    spec = f"gradients=size={W}x{H}:rate={FPS}:speed=0:c0=0x2a3f2c:c1=0x87a86f:seed={seed + 1}"
    bg_frames = read_lavfi(spec, 1)
    head_closed = draw_character(PALETTE_A, seed, variant="closed").crop((30, 0, 130, 100))
    head_open = draw_character(PALETTE_A, seed + 1, variant="mouth_open").crop((30, 0, 130, 100))
    rep_closed = make_replacement(head_closed, REPLACEMENT_SHIFT, seed + 2)
    rep_open = make_replacement(head_open, REPLACEMENT_SHIFT, seed + 3)
    center = (320, 150)
    frames: list[np.ndarray] = []
    swap_plan: list[dict[str, Any]] = []
    for f in range(n):
        open_state = (f // 15) % 2 == 1
        if f > 0 and (f % 15) == 0:
            swap_plan.append(
                {
                    "swap_frame": f,
                    "from_state": "closed",
                    "to_state": "open" if open_state else "closed",
                }
            )
        base = Image.fromarray(bg_frames[0]).convert("RGBA")
        # torso stays; head swaps between closed/open variants (pose_swap)
        torso = draw_character(PALETTE_A, seed, variant="closed").crop((0, 90, 160, 260))
        base.alpha_composite(torso, (center[0] - 80, center[1] - 60))
        head = rep_open if open_state else rep_closed
        base = compose(base, head, (center[0], center[1] - 50))
        frames.append(np.asarray(base.convert("RGB"), dtype=np.uint8))
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    path = media / "f2_mouth_swap.mp4"
    encode_mp4(np.stack(frames), path)
    spr_dir = out / "sprites" / "f2_mouth_swap"
    spr_dir.mkdir(parents=True, exist_ok=True)
    heads = {}
    for name, im in (("head_closed_src", head_closed), ("head_open_src", head_open)):
        p = spr_dir / f"{name}.png"
        im.save(p)
        heads[name] = sha256_file(p)
    for name, im in (("head_closed_rep", rep_closed), ("head_open_rep", rep_open)):
        p = spr_dir / f"{name}.png"
        im.save(p)
        heads[name] = sha256_file(p)
    # v2 source plate: background + torso WITHOUT the swappable head
    plate = emit_source_plate(out, "f2_mouth_swap", static_plate_frames(bg_frames, n))
    manifest = {
        "fixture_id": "f2_mouth_swap",
        "risk_class": "mouth_expression_swap",
        "t03_loop": "REF-R02",
        "resolution": {"width": W, "height": H},
        "fps": FPS,
        "frame_count": n,
        "time_base": "1/30",
        "start_time_ms": 0,
        "generation": {
            "tool": "ffmpeg lavfi (gradients speed=0) + Pillow sprites + libx264 bitexact",
            "sources": [spec],
            "seed": seed,
        },
        "layers": [
            {
                "layer_id": "torso",
                "role": "character",
                "z": 0,
                "color_hint_rgb": list(PALETTE_A["body"][:3]),
            },
            {
                "layer_id": "head",
                "role": "character_pose_state",
                "z": 1,
                "states": ["closed", "open"],
            },
        ],
        "swaps": [
            {"swap_frame": 15, "expected_state": "open"},
            {"swap_frame": 30, "expected_state": "closed"},
            {"swap_frame": 45, "expected_state": "open"},
        ],
        "pose_region_bbox_xywh_norm": [
            0.484375,
            0.311111,
            0.03125,
            0.055556,
        ],
        "pose_layer": {
            "layer_id": "head",
            "center_xy": [center[0], center[1] - 50],
            "sprite_size_wh": [head_closed.width, head_closed.height],
            "templates": {"open": "head_open_rep", "closed": "head_closed_rep"},
        },
        "render_contract": {
            "source_plate": plate,
            "replacements": [
                {
                    "layer_id": "head",
                    "kind": "pose_state_sequence",
                    "assets_by_state": {
                        "closed": {
                            "file": "sprites/f2_mouth_swap/head_closed_rep.png",
                            "sha256": heads["head_closed_rep"],
                        },
                        "open": {
                            "file": "sprites/f2_mouth_swap/head_open_rep.png",
                            "sha256": heads["head_open_rep"],
                        },
                    },
                    "state_schedule": [
                        {"from_frame": 0, "to_frame": 14, "state": "closed"},
                        {"from_frame": 15, "to_frame": 29, "state": "open"},
                        {"from_frame": 30, "to_frame": 44, "state": "closed"},
                        {"from_frame": 45, "to_frame": 59, "state": "open"},
                    ],
                    "placement_center_xy": [center[0], center[1] - 50],
                }
            ],
        },
        "sprites": heads,
        "metrics_applicable": [
            "swap_error_frames",
            "timebase_error_frames",
            "frame_error",
            "trajectory_median_pct",
            "trajectory_p95_pct",
        ],
    }
    return manifest, {"media": sha256_file(path)}


def build_f3(out: Path, seed: int) -> tuple[dict[str, Any], dict[str, str]]:
    """Phone travels chest->ear (linear), holds, returns; contact anchors GT."""
    n = 90
    spec = f"gradients=size={W}x{H}:rate={FPS}:speed=0:c0=0x402a3f:c1=0xa07898:seed={seed + 2}"
    bg_frames = read_lavfi(spec, 1)
    char = draw_character(PALETTE_A, seed)
    rep_char = make_replacement(char, REPLACEMENT_SHIFT, seed + 1)
    phone = draw_phone(PHONE_PAL)
    all_f = list(range(n))
    char_pos = const((280, 200), all_f)
    # phone: chest (330,210) -> ear (300,120) frames 10..40, hold 40..75, back 75..89
    phone_traj: dict[int, tuple[int, int]] = {}
    phone_traj.update(lin((330, 210), (300, 120), all_f, 10, 40))
    phone_traj.update(const((300, 120), [f for f in all_f if 41 <= f <= 75]))
    phone_traj.update(lin((300, 120), (330, 210), all_f, 75, 89))
    phone_traj = {f: phone_traj.get(f, (330, 210)) for f in all_f}
    frames: list[np.ndarray] = []
    for f in all_f:
        base = Image.fromarray(bg_frames[0]).convert("RGBA")
        base = compose(base, rep_char, char_pos[f])
        base = compose(base, phone, phone_traj[f])
        frames.append(np.asarray(base.convert("RGB"), dtype=np.uint8))
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    path = media / "f3_phone_contact.mp4"
    encode_mp4(np.stack(frames), path)
    spr_dir = out / "sprites" / "f3_phone_contact"
    spr_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name, im in (("char_src", char), ("char_rep", rep_char), ("phone", phone)):
        p = spr_dir / f"{name}.png"
        im.save(p)
        hashes[name] = sha256_file(p)
    diag = math.hypot(W, H)
    contact_active = list(range(41, 76))
    manifest = {
        "fixture_id": "f3_phone_contact",
        "risk_class": "phone_contact",
        "t03_loop": "REF-R03",
        "resolution": {"width": W, "height": H},
        "fps": FPS,
        "frame_count": n,
        "time_base": "1/30",
        "start_time_ms": 0,
        "generation": {
            "tool": (
                "ffmpeg lavfi (gradients speed=0, seed-pinned) + Pillow sprites + libx264 bitexact"
            ),
            "sources": [spec],
            "seed": seed,
        },
        "layers": [
            {"layer_id": "character", "role": "character", "z": 0, "color_hint_rgb": None},
            {"layer_id": "phone", "role": "prop", "z": 1},
        ],
        "trajectories": [
            {
                "layer_id": "phone",
                "positions_by_frame": {str(k): list(v) for k, v in phone_traj.items()},
            },
            {
                "layer_id": "character",
                "positions_by_frame": {str(k): list(v) for k, v in char_pos.items()},
            },
        ],
        "contacts": [
            {
                "name": "phone_to_ear_hold",
                "layer_id": "phone",
                "active_frames": contact_active,
                "anchor_xy_norm": [round(300 / W, 6), round(120 / H, 6)],
                "expected_error_pct_of_diagonal_max": round(6.0 / diag * 100, 6),
            }
        ],
        "render_contract": {
            "source_plate": emit_source_plate(
                out, "f3_phone_contact", static_plate_frames(bg_frames, n)
            ),
            # plate = background ONLY; the renderer composites BOTH the
            # character (static trajectory) and the phone replacement
            "plate_layers": [
                {
                    "layer_id": "character",
                    "file": "sprites/f3_phone_contact/char_rep.png",
                    "sha256": hashes["char_rep"],
                    "positions_by_frame": {str(k): list(v) for k, v in char_pos.items()},
                }
            ],
            "replacements": [
                {
                    "layer_id": "phone",
                    "kind": "prop_trajectory",
                    "assets_by_state": {
                        "default": {
                            "file": "sprites/f3_phone_contact/phone.png",
                            "sha256": hashes["phone"],
                        }
                    },
                    "positions_by_frame": {str(k): list(v) for k, v in phone_traj.items()},
                }
            ],
        },
        "sprites": hashes,
        "metrics_applicable": [
            "trajectory_median_pct",
            "trajectory_p95_pct",
            "contact_p95_pct",
            "scale_p95_pct",
            "rotation_p95_deg",
            "unexplained_visibility_events",
            "frame_error",
            "timebase_error_frames",
        ],
    }
    return manifest, {"media": sha256_file(path)}


def build_f4(out: Path, seed: int) -> tuple[dict[str, Any], dict[str, str]]:
    """Whole-body rotation 0->90deg + scale ramp 1.00->1.12, then hold on bed."""
    n = 90
    spec = f"gradients=size={W}x{H}:rate={FPS}:speed=0:c0=0x33313f:c1=0x9aa0b4:seed={seed + 3}"
    bg_frames = read_lavfi(spec, 1)
    char = draw_character(PALETTE_A, seed + 7)
    rep_char = make_replacement(char, REPLACEMENT_SHIFT, seed + 8)
    bed = draw_bed(BED_PAL)
    all_f = list(range(n))
    frames: list[np.ndarray] = []
    gt_rot: dict[int, float] = {}
    gt_scale: dict[int, float] = {}
    for f in all_f:
        base = Image.fromarray(bg_frames[0]).convert("RGBA")
        base = compose(base, bed, (430, 260))
        if f <= 60:
            ang = 90.0 * f / 60.0
            sc = 1.0 + 0.12 * f / 60.0
        else:
            ang, sc = 90.0, 1.12
        gt_rot[f] = ang
        gt_scale[f] = sc
        spr = rep_char.resize(
            (max(1, round(rep_char.width * sc)), max(1, round(rep_char.height * sc)))
        )
        base = compose(base, spr, (220, 190), angle=ang)
        frames.append(np.asarray(base.convert("RGB"), dtype=np.uint8))
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    path = media / "f4_body_rotation.mp4"
    encode_mp4(np.stack(frames), path)
    spr_dir = out / "sprites" / "f4_body_rotation"
    spr_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name, im in (("char_src", char), ("char_rep", rep_char), ("bed", bed)):
        p = spr_dir / f"{name}.png"
        im.save(p)
        hashes[name] = sha256_file(p)
    manifest = {
        "fixture_id": "f4_body_rotation",
        "risk_class": "whole_body_rotation",
        "t03_loop": "REF-R04",
        "resolution": {"width": W, "height": H},
        "fps": FPS,
        "frame_count": n,
        "time_base": "1/30",
        "start_time_ms": 0,
        "generation": {
            "tool": "ffmpeg lavfi (gradients speed=0) + Pillow sprites + libx264 bitexact",
            "sources": [spec],
            "seed": seed,
        },
        "layers": [
            {"layer_id": "bed", "role": "prop", "z": 0},
            {"layer_id": "body", "role": "character", "z": 1},
        ],
        "motion": {
            "layer_id": "body",
            "pivot_xy": [220, 190],
            "rotation_deg_by_frame": {str(k): v for k, v in gt_rot.items()},
            "scale_by_frame": {str(k): v for k, v in gt_scale.items()},
            # declared segment-entry transform (route input contract, same as
            # SegmentRenderRoute anchors): motion starts from identity
            "start_rotation_deg": 0.0,
            "start_scale": 1.0,
            "source_basis_scale": 1.0,
            "max_scale": 1.12,
        },
        "contacts": [
            {
                "name": "body_rest_center_final",
                "layer_id": "body",
                "active_frames": [85, 86, 87, 88, 89],
                "anchor_xy_norm": [round(220 / W, 6), round(190 / H, 6)],
                "expected_error_pct_of_diagonal_max": round(6.0 / math.hypot(W, H) * 100, 6),
            }
        ],
        "clipping_probe": {
            "purpose": (
                "asset-level audit: would a route that reuses the SOURCE "
                "silhouette lose replacement content at max declared scale? "
                "Detector ships in the harness and is unit-validated; it "
                "fails only routes declared to perform silhouette reuse."
            ),
            "min_clipped_pixels_for_fail": 25,
            "applies_to_routes": [],
        },
        "render_contract": {
            "source_plate": emit_source_plate(
                out, "f4_body_rotation", static_plate_frames(bg_frames, n)
            ),
            # plate = background + bed; the renderer composites the rotating
            # body replacement from the motion contract below
            "plate_layers": [
                {
                    "layer_id": "bed",
                    "file": "sprites/f4_body_rotation/bed.png",
                    "sha256": hashes["bed"],
                    "center_xy": [430, 260],
                }
            ],
            "replacements": [
                {
                    "layer_id": "body",
                    "kind": "affine_keyframes",
                    "assets_by_state": {
                        "default": {
                            "file": "sprites/f4_body_rotation/char_rep.png",
                            "sha256": hashes["char_rep"],
                        }
                    },
                    "placement_center_xy": [220, 190],
                    "rotation_deg_by_frame": {str(k): v for k, v in gt_rot.items()},
                    "scale_by_frame": {str(k): v for k, v in gt_scale.items()},
                    "start_rotation_deg": 0.0,
                    "start_scale": 1.0,
                }
            ],
        },
        "sprites": hashes,
        "metrics_applicable": [
            "rotation_p95_deg",
            "scale_p95_pct",
            "trajectory_median_pct",
            "trajectory_p95_pct",
            "contact_p95_pct",
            "clipping_from_source_silhouette",
            "frame_error",
            "timebase_error_frames",
        ],
    }
    return manifest, {"media": sha256_file(path)}


def emit_f5_plate(out: Path, seed: int) -> dict[str, Any]:
    """Build + encode the f5 source plate: background + pillar + charB.

    charA is the replacement layer the renderer must composite BEHIND the
    pillar (z_order), so it is deliberately absent from the plate.
    """
    n = 120
    bg_frames = read_lavfi(f"smptebars=size={W}x{H}:rate={FPS}", 1)
    pal_b = dict(PALETTE_A)
    pal_b["body"] = (214, 93, 46, 255)
    pal_b["legs"] = (170, 70, 30, 255)
    char_b = draw_character(pal_b, seed + 12)
    rep_b = make_replacement(char_b, (40, -60, 70), seed + 14)
    pillar = draw_pillar(PILLAR_PAL)
    frames: list[np.ndarray] = []
    for _ in range(n):
        base = Image.fromarray(bg_frames[0]).convert("RGBA")
        base = compose(base, pillar, (372, 180))
        base = compose(base, rep_b, (100, 205))
        frames.append(np.asarray(base.convert("RGB"), dtype=np.uint8))
    return emit_source_plate(out, "f5_group_occlusion", np.stack(frames))


def build_f5(out: Path, seed: int) -> tuple[dict[str, Any], dict[str, str]]:
    """Group occlusion: charA crosses BEHIND a foreground pillar (exact hidden
    window), charB stands in front; exercises z-order + visibility metrics."""
    n = 120
    bg_frames = read_lavfi(f"smptebars=size={W}x{H}:rate={FPS}", 1)
    char_a = draw_character(PALETTE_A, seed + 11)
    pal_b = dict(PALETTE_A)
    pal_b["body"] = (214, 93, 46, 255)
    pal_b["legs"] = (170, 70, 30, 255)
    char_b = draw_character(pal_b, seed + 12)
    rep_a = make_replacement(char_a, (-60, 40, -20), seed + 13)
    rep_b = make_replacement(char_b, (40, -60, 70), seed + 14)
    pillar = draw_pillar(PILLAR_PAL)
    all_f = list(range(n))
    # charA walks 80->560 over frames 0..79 (8 px/frame), then holds.
    # rep sprite 164x264 -> half-width 82; pillar core abs x in [215, 525];
    # fully hidden iff center ax in [297, 443]  ->  frames [28, 45].
    a_traj: dict[int, tuple[int, int]] = {}
    a_traj.update(lin((80, 200), (560, 200), all_f, 0, 79))
    a_traj.update(const((560, 200), [f for f in all_f if f >= 80]))
    # charB stands LEFT of the pillar (span [18,182]) so the pillar rect
    # [221,523] never covers it: with the v2 sandwich order the occluder
    # draws above ALL plate content inside the window, so any overlap would
    # wrongly hide char_b.  char_b must stay visible per its GT intervals.
    b_traj = const((100, 205), all_f)
    hide_lo, hide_hi = 28, 45
    overlap_lo, overlap_hi = 24, 49
    frames: list[np.ndarray] = []
    for f in all_f:
        base = Image.fromarray(bg_frames[0]).convert("RGBA")
        ax, ay = a_traj[f]
        if not (hide_lo <= f <= hide_hi):
            base = compose(base, rep_a, (ax, ay))
        base = compose(base, pillar, (372, 180))
        base = compose(base, rep_b, b_traj[f])
        frames.append(np.asarray(base.convert("RGB"), dtype=np.uint8))
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    path = media / "f5_group_occlusion.mp4"
    encode_mp4(np.stack(frames), path)
    spr_dir = out / "sprites" / "f5_group_occlusion"
    spr_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name, im in (
        ("char_a_src", char_a),
        ("char_b_src", char_b),
        ("char_a_rep", rep_a),
        ("char_b_rep", rep_b),
        ("pillar", pillar),
    ):
        p = spr_dir / f"{name}.png"
        im.save(p)
        hashes[name] = sha256_file(p)
    manifest = {
        "fixture_id": "f5_group_occlusion",
        "risk_class": "group_occlusion",
        "t03_loop": "REF-R05",
        "resolution": {"width": W, "height": H},
        "fps": FPS,
        "frame_count": n,
        "time_base": "1/30",
        "start_time_ms": 0,
        "generation": {
            "tool": "ffmpeg lavfi (smptebars) + Pillow sprites + libx264 bitexact",
            "sources": [f"smptebars=size={W}x{H}:rate={FPS}"],
            "seed": seed,
        },
        "layers": [
            {"layer_id": "char_a", "role": "character", "z": 0},
            {"layer_id": "pillar", "role": "foreground_occluder", "z": 1},
            {"layer_id": "char_b", "role": "character", "z": 2},
        ],
        # v2 REQUIRED coverage: every layer below must have measured samples
        # for its applicable metrics -- an empty/unmapped template is
        # UNKNOWN/FAIL, never an implicit pass (F2 remediation)
        "required_layers": ["char_a", "char_b", "pillar"],
        "trajectories": [
            {
                "layer_id": "char_a",
                "positions_by_frame": {str(k): list(v) for k, v in a_traj.items()},
            },
            {
                "layer_id": "char_b",
                "positions_by_frame": {str(k): list(v) for k, v in b_traj.items()},
            },
        ],
        "visibility": [
            {"layer_id": "char_a", "intervals": [[0, hide_lo - 1], [hide_hi + 1, n - 1]]},
            {"layer_id": "pillar", "intervals": [[0, n - 1]]},
            {"layer_id": "char_b", "intervals": [[0, n - 1]]},
        ],
        "z_order": [
            {
                "above": "pillar",
                "below": "char_a",
                "frames": [overlap_lo, overlap_hi],
                "ambiguous_frames": [
                    f for f in range(overlap_lo, overlap_hi + 1) if not (hide_lo <= f <= hide_hi)
                ],
            },
            {"above": "char_b", "below": "pillar", "frames": [0, n - 1]},
        ],
        "render_contract": {
            # plate = background + charB (charA is the replacement; the pillar
            # travels with the request as a typed OCCLUDER so the renderer
            # must honor the per-frame z-order below -- C2-PREP)
            "source_plate_source_frames": emit_f5_plate(out, seed),
            "replacements": [
                {
                    "layer_id": "char_a",
                    "kind": "prop_trajectory",
                    "assets_by_state": {
                        "default": {
                            "file": "sprites/f5_group_occlusion/char_a_rep.png",
                            "sha256": hashes["char_a_rep"],
                        }
                    },
                    "positions_by_frame": {str(k): list(v) for k, v in a_traj.items()},
                    "z": 0,
                }
            ],
            # C2-PREP (F1): typed occluders + EXPECTED per-frame layer order.
            # The renderer receives the pillar as an occluder asset and the
            # z directive ``replacement BELOW pillar`` exactly over the
            # hidden window 28..45; outside that window no layer_order entry
            # is active, so the pillar drawn by the request only appears in
            # that window (the plate itself never carries the pillar -- the
            # GT media does, matching the original scene).
            "occluders": [
                {
                    "layer_id": "pillar",
                    "file": "sprites/f5_group_occlusion/pillar.png",
                    "sha256": hashes["pillar"],
                    "kind": "sprite",
                }
            ],
            # J1-C2-v2 per-region occluder placement: pillar sprite is
            # 310x360 centered at (372,180) -> opaque core abs x 221..523,
            # full height (normalized 0.3390625, 0.0, 0.484375, 1.0).
            # Without a region the legacy compositor stretches the occluder
            # over the WHOLE frame, which would also cover char_b inside
            # the hidden window.
            "occluder_regions": {
                "pillar": [217 / W, 0.0, 310 / W, 1.0]
            },
            "expected_layer_order": [
                {
                    "frame_from": hide_lo,
                    "frame_to": hide_hi,
                    "below": "char_a",
                    "above": "pillar",
                    "note": (
                        "char_a replacement must render BEHIND the pillar "
                        "occluder inside the hidden window"
                    ),
                }
            ],
        },
        "sprites": hashes,
        "metrics_applicable": [
            "z_order_inversions",
            "unexplained_visibility_events",
            "trajectory_median_pct",
            "trajectory_p95_pct",
            "frame_error",
            "timebase_error_frames",
        ],
    }
    return manifest, {"media": sha256_file(path)}


def build_f6(out: Path, seed: int) -> tuple[dict[str, Any], dict[str, str]]:
    """Semantic graphic sign + source-only watermark over a room-ish gradient."""
    n = 60
    spec = f"gradients=size={W}x{H}:rate={FPS}:speed=0:c0=0x6b5a3f:c1=0xcbb894:seed={seed + 5}"
    bg_frames = read_lavfi(spec, 1)
    sign = draw_sign(SIGN_PAL)
    rep_sign = make_replacement(sign, (90, -70, 30), seed + 21)
    wm = draw_watermark(WM_PAL)
    all_f = list(range(n))
    sign_pos = const((200, 120), all_f)
    frames: list[np.ndarray] = []
    for f in all_f:
        base = Image.fromarray(bg_frames[0]).convert("RGBA")
        base = compose(base, rep_sign, sign_pos[f])
        # Source-only watermark intentionally NOT composited: a correct render
        # removes it. The harness actively probes its absence per frame and a
        # unit test injects it to prove the leak detector fires.
        frames.append(np.asarray(base.convert("RGB"), dtype=np.uint8))
    media = out / "media"
    media.mkdir(parents=True, exist_ok=True)
    path = media / "f6_graphic_replacement.mp4"
    encode_mp4(np.stack(frames), path)
    spr_dir = out / "sprites" / "f6_graphic_replacement"
    spr_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name, im in (("sign_src", sign), ("sign_rep", rep_sign), ("watermark", wm)):
        p = spr_dir / f"{name}.png"
        im.save(p)
        hashes[name] = sha256_file(p)
    manifest = {
        "fixture_id": "f6_graphic_replacement",
        "risk_class": "semantic_graphic_replacement",
        "t03_loop": "REF-R01",
        "resolution": {"width": W, "height": H},
        "fps": FPS,
        "frame_count": n,
        "time_base": "1/30",
        "start_time_ms": 0,
        "generation": {
            "tool": "ffmpeg lavfi (gradients speed=0) + Pillow sprites + libx264 bitexact",
            "sources": [spec],
            "seed": seed,
        },
        "layers": [
            {"layer_id": "sign", "role": "semantic_graphic", "z": 0},
            {"layer_id": "watermark", "role": "source_only_overlay", "z": 9},
        ],
        "graphics": [
            {
                "layer_id": "sign",
                "bbox_xywh_norm": [
                    round(110 / W, 6),
                    round(65 / H, 6),
                    round(180 / W, 6),
                    round(110 / H, 6),
                ],
            },
            {
                "layer_id": "watermark",
                "source_only": True,
                "must_be_absent": True,
                "bbox_xywh_norm": [
                    round(536 / W, 6),
                    round(306 / H, 6),
                    round(90 / W, 6),
                    round(40 / H, 6),
                ],
            },
        ],
        "trajectories": [
            {
                "layer_id": "sign",
                "positions_by_frame": {str(k): list(v) for k, v in sign_pos.items()},
            }
        ],
        "render_contract": {
            # plate = background only; renderer composites the sign
            # replacement. The source-only watermark must NOT appear in any
            # rendered output (must_be_absent).
            "source_plate": emit_source_plate(
                out, "f6_graphic_replacement", static_plate_frames(bg_frames, n)
            ),
            "replacements": [
                {
                    "layer_id": "sign",
                    "kind": "prop_trajectory",
                    "assets_by_state": {
                        "default": {
                            "file": "sprites/f6_graphic_replacement/sign_rep.png",
                            "sha256": hashes["sign_rep"],
                        }
                    },
                    "positions_by_frame": {str(k): list(v) for k, v in sign_pos.items()},
                }
            ],
        },
        "sprites": hashes,
        "metrics_applicable": [
            "graphic_present_frames_ratio",
            "watermark_leak_events",
            "trajectory_median_pct",
            "trajectory_p95_pct",
            "frame_error",
            "timebase_error_frames",
        ],
    }
    return manifest, {"media": sha256_file(path)}


BUILDERS = {
    "f1_hard_cut": build_f1,
    "f2_mouth_swap": build_f2,
    "f3_phone_contact": build_f3,
    "f4_body_rotation": build_f4,
    "f5_group_occlusion": build_f5,
    "f6_graphic_replacement": build_f6,
}

REQUIRED_MANIFEST_KEYS = {
    "fixture_id",
    "risk_class",
    "t03_loop",
    "resolution",
    "fps",
    "frame_count",
    "time_base",
    "start_time_ms",
    "generation",
    "metrics_applicable",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=FIXTURE_DIR)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args(argv)
    out = args.out.resolve()
    (out / "manifests").mkdir(parents=True, exist_ok=True)
    # frozen thresholds travel WITH the fixture set so a harness pointed at
    # this directory freezes against the exact same bytes
    thr_src = Path(__file__).resolve().parent / "thresholds.json"
    shutil.copyfile(thr_src, out / "thresholds.json")
    index: dict[str, Any] = {"schema_version": 1, "seed": args.seed, "fixtures": []}
    gen_src = Path(__file__).read_bytes()
    index["generator_sha256"] = hashlib.sha256(gen_src).hexdigest()
    for fid, builder in BUILDERS.items():
        print(f"[gen] {fid} ...", flush=True)
        manifest, hashes = builder(out, args.seed)
        missing = REQUIRED_MANIFEST_KEYS - set(manifest.keys())
        if missing:
            raise SystemExit(f"manifest {fid} missing keys: {sorted(missing)}")
        mpath = out / "manifests" / f"{fid}.json"
        mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        index["fixtures"].append(
            {
                "fixture_id": fid,
                "risk_class": manifest["risk_class"],
                "manifest_path": str(mpath.relative_to(out)).replace("\\", "/"),
                "media_path": f"media/{fid}.mp4",
                "manifest_sha256": sha256_file(mpath),
                "media_sha256": hashes["media"],
                "frame_count": manifest["frame_count"],
            }
        )
        print(f"[gen] {fid} done  media_sha256={hashes['media'][:16]}...", flush=True)
    ipath = out / "fixtures_index.json"
    ipath.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[gen] index -> {ipath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
