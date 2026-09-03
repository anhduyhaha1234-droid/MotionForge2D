"""Deterministic fixture generator — must be idempotent and produce LF-only JSON.

S10-T04C-C3 (C4A): fixture bundle now carries REAL canonical media:
  - media/source.mp4        real decodable deterministic source video (100 frames)
  - media/assets/*.png      real replacement asset sprites per layer
These bytes are staged into the isolated runtime by the seeder post-seed
(product-handler path) — no stage_c4.py, no input_manifest_json patching.
"""
from __future__ import annotations
import hashlib
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 64, 64
SEED = 20260827
MEDIA_W, MEDIA_H = 160, 120
MEDIA_FRAMES = 100
MEDIA_FPS = 30.0
FIXTURE_DIR = Path(__file__).resolve().parent


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def make_sprite(color: tuple[int, int, int], label: str, seed: int) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, W - 4, H - 4), radius=8, fill=color + (255,), outline=(20, 20, 20, 255), width=2)
    for _ in range(12):
        x, y = rng.randrange(W), rng.randrange(H)
        d.point((x, y), fill=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255), 180))
    return img


def make_asset(color: tuple[int, int, int], label: str, seed: int) -> Image.Image:
    """Replacement layer asset — distinct deterministic RGBA sprite per layer."""
    rng = random.Random(seed)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6, 6, W - 6, H - 6), radius=10, fill=color + (255,), outline=(10, 10, 10, 255), width=2)
    for _ in range(16):
        x, y = rng.randrange(W), rng.randrange(H)
        d.point((x, y), fill=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255), 200))
    return img


def make_source_mp4(out: Path) -> None:
    """Real decodable deterministic source video (same bytes every generation)."""
    import numpy as np
    import cv2

    out.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    w = cv2.VideoWriter(str(out), fourcc, MEDIA_FPS, (MEDIA_W, MEDIA_H))
    for i in range(MEDIA_FRAMES):
        f = np.zeros((MEDIA_H, MEDIA_W, 3), dtype=np.uint8)
        f[:, :, 0] = int(30 + i * 2) % 255
        f[:, :, 1] = 80
        f[:, :, 2] = 20
        w.write(f)
    w.release()


def main() -> None:
    out = FIXTURE_DIR
    sprites_dir = out / "sprites"
    media_dir = out / "media"
    assets_dir = media_dir / "assets"
    sprites_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    sprites = {
        "bg.png": make_sprite((66, 133, 244), "bg", SEED + 1),
        "fg_table.png": make_sprite((150, 152, 160), "fg", SEED + 2),
        "phone.png": make_sprite((32, 33, 36), "phone", SEED + 3),
    }
    file_entries = []
    for name, img in sprites.items():
        p = sprites_dir / name
        img.save(p)
        file_entries.append({"path": f"sprites/{name}", "size": p.stat().st_size, "sha256": sha256_file(p)})
    # The post-seed helper is part of the canonical bundle (verifyFixtureBundle
    # fails on unlisted files, so it MUST be listed here).
    for helper in ("post_seed_real_authority.py",):
        hp = out / helper
        if hp.is_file():
            file_entries.append({"path": helper, "size": hp.stat().st_size, "sha256": sha256_file(hp)})

    # Real canonical media: deterministic source mp4 + per-layer replacement assets
    source_rel = "media/source.mp4"
    make_source_mp4(out / source_rel)
    file_entries.append({"path": source_rel, "size": (out / source_rel).stat().st_size, "sha256": sha256_file(out / source_rel)})

    layer_assets = {
        "layer_bg": make_asset((66, 133, 244), "bg_asset", SEED + 10),
        "layer_fg": make_asset((150, 152, 160), "fg_asset", SEED + 11),
        "layer_phone": make_asset((32, 33, 36), "phone_asset", SEED + 12),
    }
    media_assets: dict[str, str] = {}
    for lid, img in layer_assets.items():
        rel = f"media/assets/{lid}.png"
        p = out / rel
        img.save(p)
        media_assets[lid] = rel
        file_entries.append({"path": rel, "size": p.stat().st_size, "sha256": sha256_file(p)})

    manifest = {
        "seed": SEED,
        "description": "S10 Full Apply deterministic compact multi-shot fixture — REAL canonical media (source.mp4 + per-layer assets), no user/reference media",
        "frame_count": MEDIA_FRAMES,
        "fps_num": 30,
        "fps_den": 1,
        "timebase": "1/30",
        "timebase_fingerprint": hashlib.sha256(b"1/30-30fps").hexdigest()[:16],
        "media": {
            "source": source_rel,
            "width": MEDIA_W,
            "height": MEDIA_H,
            "frame_count": MEDIA_FRAMES,
            "fps": MEDIA_FPS,
            "assets": media_assets,
        },
        "shots": [
            {"shot_id": "shot_a", "start_frame": 0, "end_frame": 49, "risk": "hard_cut", "cut_frame": 50, "contact": False, "z_order": [{"front": "layer_fg", "behind": "layer_bg"}]},
            {"shot_id": "shot_b", "start_frame": 50, "end_frame": 99, "risk": "group_occlusion", "contact": True, "contact_anchor": {"x": 0.42, "y": 0.55, "layer": "layer_phone", "target": "layer_fg"}, "z_order": [{"front": "layer_fg", "behind": "layer_bg"}, {"front": "layer_fg", "behind": "layer_phone"}]},
        ],
        "layers": [
            {"layer_id": "layer_bg", "route": "sprite_affine", "kind": "background", "z": 0},
            {"layer_id": "layer_fg", "route": "pose_swap", "kind": "foreground_occluder", "z": 20, "is_foreground_occluder": True},
            {"layer_id": "layer_phone", "route": "sprite_affine", "kind": "prop", "z": 12, "contact_anchor": {"x": 0.42, "y": 0.55}},
        ],
        "contact_edges": [
            {"edge_id": "contact_phone_hand", "source_layer": "layer_phone", "target_layer": "layer_fg", "contact_kind": "hand_phone", "start_frame": 50, "end_frame": 99, "anchor": {"x": 0.42, "y": 0.55}}
        ],
        "z_order_edges": [
            {"edge_id": "z_fg_over_bg", "front_layer": "layer_fg", "behind_layer": "layer_bg", "start_frame": 0, "end_frame": 99},
            {"edge_id": "z_fg_over_phone", "front_layer": "layer_fg", "behind_layer": "layer_phone", "start_frame": 50, "end_frame": 99}
        ],
        "trajectory": {
            "source_width": 640,
            "source_height": 360,
            "diagonal": 732.0,
            "notes": "synthetic — trajectory median 0.2% diagonal, P95 0.6%"
        },
        "files": sorted(file_entries, key=lambda x: x["path"]),
    }

    manifest_path = out / "manifest.json"
    raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    manifest_path.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    (out / "manifest.sha256").write_bytes(f"{sha}  manifest.json\n".encode("utf-8"))
    print(f"fixture manifest {sha[:12]} with {len(file_entries)} files, shots={len(manifest['shots'])}, layers={len(manifest['layers'])}, media={source_rel}")


if __name__ == "__main__":
    main()
