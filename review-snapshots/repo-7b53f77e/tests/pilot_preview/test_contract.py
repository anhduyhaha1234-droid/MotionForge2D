from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.pilot_preview import (
    PilotPreviewAnchorKeyframe,
    PilotPreviewMaskCorrection,
    PilotPreviewOccluder,
    PilotPreviewSubmitRequest,
)


def _payload() -> dict[str, object]:
    return {
        "project_id": "legacy-demo",
        "start_frame": 450,
        "end_frame": 570,
        "source_prompt": "replace the seated source character",
        "asset_sha256": "e07e2a3a76ea3d7d3144ae43f89ebbcc225a37cf91aa6ab159961f6d7349dc47",
        "mask_correction": {
            "bbox_xywh_norm": (0.32, 0.26, 0.16, 0.60),
            "source_frame": 450,
        },
        "anchor_keyframes": [
            {"frame": 450, "anchor_xy_norm": (0.40, 0.55)},
            {"frame": 569, "anchor_xy_norm": (0.40, 0.55)},
        ],
        "occluder": {"region_xywh_norm": (0.76, 0.34, 0.20, 0.66)},
    }


def test_pilot_contract_accepts_bounded_single_shot() -> None:
    request = PilotPreviewSubmitRequest.model_validate(_payload())
    assert request.end_frame - request.start_frame == 120
    assert request.occluder.z == -1


@pytest.mark.parametrize(
    "field,value",
    [
        ("asset_sha256", "not-a-hash"),
        ("start_frame", -1),
        ("end_frame", 0),
    ],
)
def test_pilot_contract_rejects_invalid_input(field: str, value: object) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        PilotPreviewSubmitRequest.model_validate(payload)


def test_pilot_contract_rejects_out_of_bounds_annotations() -> None:
    with pytest.raises(ValidationError):
        PilotPreviewMaskCorrection(bbox_xywh_norm=(0.9, 0.2, 0.2, 0.2), source_frame=450)
    with pytest.raises(ValidationError):
        PilotPreviewAnchorKeyframe(frame=450, anchor_xy_norm=(1.2, 0.5))
    with pytest.raises(ValidationError):
        PilotPreviewOccluder(region_xywh_norm=(0.7, 0.3, 0.4, 0.4))


def test_pilot_contract_forbids_unknown_fields() -> None:
    payload = _payload()
    payload["full_apply"] = True
    with pytest.raises(ValidationError):
        PilotPreviewSubmitRequest.model_validate(payload)
