from __future__ import annotations

from pathlib import Path

import numpy as np

from app.workflow.pilot_preview_jobs import (
    _clean_source_frames,
    _replacement_fit_scale,
)


class _Context:
    def is_cancelled(self) -> bool:
        return False

    def progress(self, _value: float, _message: str) -> None:
        return None


def test_c13_tight_removal_uses_propagated_mask_inside_prompt_envelope() -> None:
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    propagated = np.zeros((360, 640), dtype=np.uint8)
    propagated[130:180, 215:240] = 255
    propagated[100:120, 190:205] = 255
    cleaned, first_mask, metrics = _clean_source_frames(
        [frame], (0.32, 0.26, 0.16, 0.60), [propagated], _Context()
    )
    assert cleaned[0].shape == frame.shape
    assert int(first_mask[100:120, 190:205].sum()) == 0
    assert int((first_mask > 0).sum()) == 50 * 25
    assert metrics[0]["mask_role"] == "tight_target_removal"


def test_c13_asset_alpha_bbox_fit_preserves_aspect_ratio() -> None:
    asset = Path(
        r"C:\Users\Admin\Documents\Codex\2026-09-05\files-pasted-by-the-user-codex\work\mf-demo-v3-20260907\runtime\assets\v3-seated-rgba.png"
    )
    scale, bbox = _replacement_fit_scale(asset, (0.32, 0.26, 0.16, 0.60), 640, 360)
    assert bbox == (454, 41, 346, 1135)
    assert scale == min(102 / 346, 216 / 1135)
