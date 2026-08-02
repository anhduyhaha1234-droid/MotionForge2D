"""Character preset library manager — multi-pose template characters.

Provides three built-in character sets (Boy Cool, Thỏ Cute, Gấu Nâu), each
with 4 poses (sitting, standing, walking, talking) as PNG assets, plus
AI auto-pose matching logic that selects the best pose from the aspect
ratio of the original character's bounding box:

- width > height * 1.1  → sitting (lying/wide pose)
- height > width * 1.3  → standing / walking (tall pose)
- otherwise             → talking (balanced pose)
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

# Built-in character sets: name → {pose: filename}
BUILTIN_CHARACTERS: dict[str, dict[str, str]] = {
    "boy_cool": {
        "label": "Bộ Boy Cool",
        "poses": {
            "sitting": "boy_cool_sitting.png",
            "standing": "boy_cool_standing.png",
            "walking": "boy_cool_walking.png",
            "talking": "boy_cool_talking.png",
        },
    },
    "tho_cute": {
        "label": "Bộ Thỏ Cute",
        "poses": {
            "sitting": "tho_cute_sitting.png",
            "standing": "tho_cute_standing.png",
            "walking": "tho_cute_walking.png",
            "talking": "tho_cute_talking.png",
        },
    },
    "gau_nau": {
        "label": "Bộ Gấu Nâu",
        "poses": {
            "sitting": "gau_nau_sitting.png",
            "standing": "gau_nau_standing.png",
            "walking": "gau_nau_walking.png",
            "talking": "gau_nau_talking.png",
        },
    },
}

POSE_LABELS: dict[str, str] = {
    "sitting": "🪑 Ngồi",
    "standing": "🧍 Đứng",
    "walking": "🚶 Đi bộ",
    "talking": "💬 Nói chuyện",
}


def _draw_character(canvas: np.ndarray, color: tuple[int, int, int], pose: str) -> None:
    """Draw a simple character silhouette on a transparent canvas."""
    h, w = canvas.shape[:2]
    cx = w // 2
    body_bottom = int(h * 0.82)

    # Head (circle)
    head_r = int(h * 0.16)
    head_cy = int(h * 0.16)
    cv2.circle(canvas, (cx, head_cy), head_r, color, -1)

    if pose == "sitting":
        # Torso leaning back, legs forward (wide aspect)
        cv2.ellipse(
            canvas, (cx, int(h * 0.45)),
            (int(w * 0.28), int(h * 0.18)), 0, 0, 360, color, -1,
        )
        # Thighs forward
        cv2.rectangle(
            canvas, (cx - int(w * 0.22), int(h * 0.52)),
            (cx - int(w * 0.02), int(h * 0.62)), color, -1,
        )
        cv2.rectangle(
            canvas, (cx + int(w * 0.02), int(h * 0.52)),
            (cx + int(w * 0.22), int(h * 0.62)), color, -1,
        )
        # Shins down
        cv2.rectangle(
            canvas, (cx - int(w * 0.2), int(h * 0.62)),
            (cx - int(w * 0.12), int(h * 0.78)), color, -1,
        )
        cv2.rectangle(
            canvas, (cx + int(w * 0.12), int(h * 0.62)),
            (cx + int(w * 0.2), int(h * 0.78)), color, -1,
        )
    elif pose == "standing":
        # Tall upright body
        cv2.rectangle(
            canvas, (cx - int(w * 0.14), int(h * 0.28)),
            (cx + int(w * 0.14), body_bottom), color, -1,
        )
        # Arms
        cv2.rectangle(
            canvas, (cx - int(w * 0.2), int(h * 0.30)),
            (cx - int(w * 0.14), int(h * 0.55)), color, -1,
        )
        cv2.rectangle(
            canvas, (cx + int(w * 0.14), int(h * 0.30)),
            (cx + int(w * 0.2), int(h * 0.55)), color, -1,
        )
        # Legs
        cv2.rectangle(
            canvas, (cx - int(w * 0.13), body_bottom - int(h * 0.2)),
            (cx - int(w * 0.03), body_bottom), color, -1,
        )
        cv2.rectangle(
            canvas, (cx + int(w * 0.03), body_bottom - int(h * 0.2)),
            (cx + int(w * 0.13), body_bottom), color, -1,
        )
    elif pose == "walking":
        # Slightly tilted body + legs apart
        cv2.rectangle(
            canvas, (cx - int(w * 0.13), int(h * 0.28)),
            (cx + int(w * 0.13), body_bottom - int(h * 0.05)), color, -1,
        )
        cv2.rectangle(
            canvas, (cx - int(w * 0.2), int(h * 0.30)),
            (cx - int(w * 0.13), int(h * 0.55)), color, -1,
        )
        cv2.rectangle(
            canvas, (cx + int(w * 0.13), int(h * 0.30)),
            (cx + int(w * 0.2), int(h * 0.55)), color, -1,
        )
        # Stride legs
        cv2.rectangle(
            canvas, (cx - int(w * 0.16), body_bottom - int(h * 0.2)),
            (cx - int(w * 0.02), body_bottom), color, -1,
        )
        cv2.rectangle(
            canvas, (cx + int(w * 0.05), body_bottom - int(h * 0.2)),
            (cx + int(w * 0.18), body_bottom), color, -1,
        )
    else:  # talking
        # Body + open mouth indication (small circle below head)
        cv2.rectangle(
            canvas, (cx - int(w * 0.14), int(h * 0.28)),
            (cx + int(w * 0.14), body_bottom), color, -1,
        )
        cv2.rectangle(
            canvas, (cx - int(w * 0.2), int(h * 0.30)),
            (cx - int(w * 0.14), int(h * 0.55)), color, -1,
        )
        cv2.rectangle(
            canvas, (cx + int(w * 0.14), int(h * 0.30)),
            (cx + int(w * 0.2), int(h * 0.55)), color, -1,
        )
        cv2.rectangle(
            canvas, (cx - int(w * 0.13), body_bottom - int(h * 0.2)),
            (cx + int(w * 0.13), body_bottom), color, -1,
        )
        # Mouth bubble
        cv2.circle(
            canvas, (cx + int(w * 0.24), int(h * 0.12)),
            int(h * 0.05), color, -1,
        )


class CharacterPresetManager:
    """Manage built-in character preset assets (multi-pose PNGs)."""

    def __init__(self, assets_root: Path) -> None:
        self.assets_root = Path(assets_root)

    # ── Asset generation / bootstrap ──────────────────────────────────────

    def ensure_assets(self) -> None:
        """Generate all preset PNGs if they do not exist yet."""
        for key, spec in BUILTIN_CHARACTERS.items():
            for pose, filename in spec["poses"].items():
                target = self.assets_root / filename
                if target.is_file():
                    continue
                self._generate_asset(filename, pose, key)

    def _generate_asset(self, filename: str, pose: str, set_key: str) -> None:
        """Generate a transparent PNG for a pose with a set-specific color."""
        palette: dict[str, tuple[int, int, int]] = {
            "boy_cool": (70, 130, 220),      # cool blue
            "tho_cute": (250, 180, 210),     # pink
            "gau_nau": (150, 110, 80),       # brown
        }
        color = palette.get(set_key, (200, 200, 200))

        # Sitting/talking → wide canvas; standing/walking → tall canvas
        if pose in ("standing", "walking"):
            w, h = 512, 768
        elif pose == "sitting":
            w, h = 768, 512
        else:
            w, h = 640, 640

        canvas = np.zeros((h, w, 4), dtype=np.uint8)
        body = np.zeros((h, w, 3), dtype=np.uint8)
        _draw_character(body, color, pose)
        canvas[:, :, :3] = body
        canvas[:, :, 3] = np.where(np.any(body > 0, axis=2), 255, 0).astype(np.uint8)

        self.assets_root.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(self.assets_root / filename), canvas)

    # ── Listing ───────────────────────────────────────────────────────────

    def list_characters(self) -> list[dict]:
        """Return all built-in character sets with their poses."""
        self.ensure_assets()
        result = []
        for key, spec in BUILTIN_CHARACTERS.items():
            poses = []
            for pose, filename in spec["poses"].items():
                poses.append(
                    {
                        "pose": pose,
                        "label": POSE_LABELS.get(pose, pose),
                        "filename": filename,
                        "url": f"/api/presets/characters/{key}/{pose}/image",
                    }
                )
            result.append(
                {
                    "id": key,
                    "label": spec["label"],
                    "poses": poses,
                }
            )
        return result

    def asset_path(self, set_key: str, pose: str) -> Path | None:
        """Return the absolute path of a preset asset, or None."""
        spec = BUILTIN_CHARACTERS.get(set_key)
        if spec is None:
            return None
        filename = spec["poses"].get(pose)
        if filename is None:
            return None
        self.ensure_assets()
        p = self.assets_root / filename
        return p if p.is_file() else None

    # ── AI auto-pose matching ─────────────────────────────────────────────

    @staticmethod
    def auto_pose_for_bbox(width: float, height: float) -> str:
        """Pick a pose based on the original character bbox aspect ratio.

        - width  > height * 1.1  → sitting (lying/wide)
        - height > width * 1.3   → standing (tall)
        - otherwise              → talking (balanced)
        """
        if width <= 0 or height <= 0:
            return "talking"
        if width > height * 1.1:
            return "sitting"
        if height > width * 1.3:
            return "standing"
        return "talking"


def get_preset_manager() -> CharacterPresetManager:
    """Get the singleton preset manager rooted at the project data dir."""
    from app.api import deps

    root = Path(deps._config.project_root)
    return CharacterPresetManager(root / "presets" / "characters")
