"""Pilot-preview scene contract package (R2, source-locked).

New in DV3-R2-T01. This package owns the per-frame scene annotation for the
bounded V3 pilot window (source frames 450..569 of the 30 s clip) and the
fail-closed compatibility gate that must run BEFORE any heavy render work.

It never touches existing modules: it only reads immutable pins (source
video, V3 asset, SAM2 checkpoint) by hash, never by copying strings.
"""

from __future__ import annotations

from app.services.pilot_preview.scene_contract import (
    ANCHOR_SPACES,
    ASSET_NEGATIVE_SHA256,
    COMPAT_REQUIREMENTS,
    COORDINATE_SPACES,
    EVENT_LEDGER,
    LOCAL_TO_SOURCE,
    NEGATIVE_KNOWN_FAILURES,
    ROLE_IDS,
    SAM2_PINNED_SHA256,
    SCENE_CONTRACT_VERSION,
    SOURCE_PINNED_SHA256,
    SOURCE_WINDOW,
    SceneContractError,
    anchor_fullframe_to_bbox_local,
    anchor_fullframe_to_normalized,
    build_scene_contract,
    check_pack_compatibility,
    local_to_source,
    scene_contract_hash,
    source_to_local,
    validate_scene_contract,
)

__all__ = [
    "ANCHOR_SPACES",
    "ASSET_NEGATIVE_SHA256",
    "COMPAT_REQUIREMENTS",
    "COORDINATE_SPACES",
    "EVENT_LEDGER",
    "LOCAL_TO_SOURCE",
    "NEGATIVE_KNOWN_FAILURES",
    "ROLE_IDS",
    "SAM2_PINNED_SHA256",
    "SCENE_CONTRACT_VERSION",
    "SOURCE_PINNED_SHA256",
    "SOURCE_WINDOW",
    "SceneContractError",
    "anchor_fullframe_to_bbox_local",
    "anchor_fullframe_to_normalized",
    "build_scene_contract",
    "check_pack_compatibility",
    "local_to_source",
    "scene_contract_hash",
    "source_to_local",
    "validate_scene_contract",
]
