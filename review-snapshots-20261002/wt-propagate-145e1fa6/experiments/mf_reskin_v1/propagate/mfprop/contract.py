"""Frozen GOLDEN contract reader (read-only consumer; never modifies GOLDEN)."""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re

import numpy as np
from PIL import Image

from . import GOLDEN_ROOT, HEIGHT, WIDTH

FREEZE_HASH_EXPECTED = "2c558ce19e0a9d915d860dc07843bd1412ac4a7801284cca5293ea21cbfba684"
REF_FILM_SHA256 = "5A175454C2C2965BAC5013A53926E210A9F70A185D802D0F2E0083A6FB399FA2"
GROUP_WINDOW = "BOOK"


def _load(rel: str) -> dict:
    with open(os.path.join(GOLDEN_ROOT, rel), encoding="utf-8") as fh:
        return json.load(fh)


def film_path() -> str:
    cands = glob.glob(r"C:\Users\Admin\MotionForge2D\projects\2dc14177a212\*.mp4")
    if not cands:
        raise SystemExit("REFERENCE FILM NOT FOUND on the locked path")
    return cands[0]


def fixture() -> dict:
    return _load("GOLDEN_FIXTURE.json")


def freeze_check() -> dict:
    """Recompute the canonical freeze hash and compare with the frozen value."""
    fix = fixture()
    expected = fix["freeze"]["freeze_hash_sha256"]
    stripped = {k: v for k, v in fix.items() if k != "freeze"}
    canon = json.dumps(stripped, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    got = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    with open(os.path.join(GOLDEN_ROOT, "GOLDEN_FIXTURE.json"), "rb") as fh:
        raw_sha = hashlib.sha256(fh.read()).hexdigest()
    return {
        "expected": expected,
        "recomputed": got,
        "matches": got == expected,
        "matches_packet_constant": expected == FREEZE_HASH_EXPECTED,
        "fixture_bytes_sha256": raw_sha,
        "hash_scope": fix["freeze"]["hash_scope"],
    }


def tag_index() -> dict:
    """Map a frozen window's start_frame -> artifact tag.

    The fixture's window_id (`W05_CAMERA`) is NOT the artifact tag (`CAM_4212`), so
    the mapping is derived from the frozen annotations (start_frame of each
    annotation window) instead of being guessed from the window_id string.
    """
    index = _load("references_index.json")
    out = {}
    for tag in index:
        ann = annotation(tag)
        out[int(ann["window"]["start_frame"])] = tag
    return out


def windows() -> list[dict]:
    """Windows in source (frame-id) order, with exact frame/pts/timebook keeping."""
    ws = sorted(fixture()["windows"], key=lambda w: w["start_frame"])
    tags = tag_index()
    out = []
    for w in ws:
        anchors = list(w["anchors"])
        tag = tags.get(int(w["start_frame"]))
        if tag is None:
            raise KeyError(f"no artifact tag maps to window {w['window_id']} start {w['start_frame']}")
        out.append({
            "window_id": w["window_id"],
            "tag": tag,
            "classes": w["classes"],
            "holdout": bool(w["holdout"]),
            "start_frame": w["start_frame"],
            "end_frame_exclusive": w["end_frame_exclusive"],
            "start_pts": w["start_frame"] * 512,
            "end_pts_exclusive": w["end_frame_exclusive"] * 512,
            "frames": w["end_frame_exclusive"] - w["start_frame"],
            "duration_s": w["duration_s"],
            "anchors": anchors,
            "anchor_cadence": (anchors[1] - anchors[0]) if len(anchors) > 1 else None,
        })
    return out


def window(tag: str) -> dict:
    for w in windows():
        if w["tag"] == tag:
            return w
    raise KeyError(tag)


def annotation(tag: str) -> dict:
    return _load(os.path.join("annotations", f"annotation_{tag}.json"))


def relations(tag: str) -> dict:
    return _load(os.path.join("annotations", f"relations_{tag}.json"))


def references(tag: str) -> dict:
    return _load(os.path.join("references", f"references_{tag}.json"))


def role_ids(tag: str) -> list[str]:
    return [r["role_id"] for r in annotation(tag)["roles"]]


def role_kinds(tag: str) -> dict:
    return {r["role_id"]: r["kind_structural"] for r in annotation(tag)["roles"]}


def role_states(tag: str) -> dict:
    return {r["role_id"]: {s["frame_id"]: s["state"] for s in r["states"]}
            for r in annotation(tag)["roles"]}


def contacts(tag: str) -> list[tuple[str, str]]:
    return [(c["role_a"], c["role_b"]) for c in annotation(tag)["contacts"]]


def cuts_inside(tag: str) -> list[dict]:
    return list(annotation(tag)["cuts_inside_window"])


def occlusion_events(tag: str) -> list[dict]:
    return list(annotation(tag)["occlusion_events"])


def containment_depth(tag: str) -> dict:
    """Depth from the measured containment relations (nesting), not a guessed z-order."""
    rel = relations(tag)
    parent = {}
    for r in rel["relations"]:
        cr, cg = r.get("contained_role"), r.get("containing_role")
        if cr and cg and r.get("relation") == "smaller_role_lies_inside_larger_role_region":
            parent[cr] = cg
    depth = {}
    for role in role_ids(tag):
        d, cur, guard = 0, parent.get(role), 0
        while cur is not None and guard < 8:
            d += 1
            cur = parent.get(cur)
            guard += 1
        depth[role] = d
    return {"parent": parent, "depth": depth,
            "source": "relations.json measured containment (relational nesting only)"}


def interaction_group(tag: str = GROUP_WINDOW) -> dict:
    """Group members, read from the frozen fixture text (never redefined here).

    The fixture names the window by `window_id` (`W01_BOOK`) while artifacts use the
    tag (`BOOK`), so the lookup resolves the tag through the frozen window list
    instead of string-matching the two namespaces.
    """
    g = fixture()["interaction_group"]
    owner_window = None
    for w in fixture()["windows"]:
        if w["window_id"] == g["window"]:
            owner_window = w
            break
    if owner_window is None:
        return {}
    if tag_index().get(int(owner_window["start_frame"])) != tag:
        return {}
    members = re.findall(r"role_\d+", g["structure"])
    return {"id": g["id"], "window": g["window"], "members": sorted(set(members)),
            "constraint": g["constraint"], "separation_status": g["separation_status"],
            "structure": g["structure"]}


# ------------------------------------------------------------------ artifacts
def keyframe_png(tag: str, frame_id: int) -> str:
    return os.path.join(GOLDEN_ROOT, "keyframes", tag, f"keyframe_f{frame_id}.png")


def load_keyframe(tag: str, frame_id: int) -> np.ndarray:
    p = keyframe_png(tag, frame_id)
    if not os.path.exists(p):
        raise FileNotFoundError(p)
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.uint8)


def mask_png(tag: str, frame_id: int) -> str:
    return os.path.join(GOLDEN_ROOT, "masks", tag, f"maskindex_f{frame_id}.png")


def load_index_mask(tag: str, frame_id: int) -> np.ndarray:
    """Indexed mask: pixel value = mask index (matches mask_index_legend['index'])."""
    p = mask_png(tag, frame_id)
    if not os.path.exists(p):
        return np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    m = np.asarray(Image.open(p))
    if m.ndim == 3:
        m = m[..., 0]
    if m.dtype != np.uint8:
        mm = m.astype(np.int64)
        if mm.max() > 255:
            mm = np.clip(mm, 0, 255)
        m = mm.astype(np.uint8)
    return m


def legend(tag: str, frame_id: int) -> dict:
    """index -> role_id for one anchor frame."""
    ann = annotation(tag)
    for a in ann["anchors"]:
        if a["frame_id"] == frame_id:
            return {int(e["index"]): e["role_id"] for e in a["mask_index_legend"]}
    return {}


def anchor_mask_bundle(tag: str) -> dict:
    """{frame_id: {'index_map': uint8 HxW, 'role_of_index': {i: role_id}}} for all anchors."""
    out = {}
    for fid in window(tag)["anchors"]:
        out[fid] = {"index_map": load_index_mask(tag, fid), "role_of_index": legend(tag, fid)}
    return out


def holdout_guard(tag: str) -> dict:
    """W07_HOLDOUT may never be tuned. Recorded per invocation with the enforced rule."""
    w = window(tag)
    return {
        "tag": tag,
        "is_holdout": w["holdout"],
        "tuning_parameters_read_from_holdout": False,
        "enforced_by": "single frozen parameter set (mfprop.params.PARAMS) shared by all windows; "
                       "holdout metrics are computed once and never fed back into any parameter",
    }
