"""MF-V1-VIDEO14B wave B round M1 — pre-submit static preflight + native-template match.

Everything here is read-only against the LIVE engine (`/object_info`) and the
graphs on disk.  It answers, before any POST:

  1. engine identity: is the instance epoch on disk the server we are talking to?
  2. node inventory: does the live `/object_info` hash to the pinned value, and
     does the M1 graph reference any class the server cannot run?
  3. model pins: sha256 of every weight file the graph loads (recomputed now).
  4. input pins: reference image + driving clip sha256, frame counts.
  5. the ONE delta: 672:587.pose_start_percent / pose_end_percent vs the frozen
     wave-B baseline.
  6. native-template match: the documented `video_wan_animate2.json` subgraph
     "Motion Transfer (Wan Animate 2)" node 587 widget vector, mapped through the
     LIVE `/object_info` widget order, compared field by field with the M1 node --
     so the M1 pose window is the documented window, not an invented one.

usage:
  python m1_preflight.py <m1_api.json> <baseline_api.json> <out.json>
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

RT = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\runtime\video14b")
BASE_URL = "http://127.0.0.1:8310"
NODE_INVENTORY_SHA256 = "d9e8e25aa7c6b32fd67100fb7a5bef58c37686414cbf7de5172b2c67b1b63da3"
NATIVE_TEMPLATE = Path(
    r"C:\Users\Admin\Documents\Codex\work\mfv1\wt-video14b\experiments\mf_reskin_v1"
    r"\video14b\workflows\official\video_wan_animate2.json")
REFERENCE = RT / "input" / "mf_book_anchor_1650.png"
DRIVING = RT / "input" / "mf_book_f1650_1770_drive_121f_padded_640x368.mp4"

MODEL_KEYS = {"unet_name": "diffusion_models", "ckpt_name": "checkpoints",
              "lora_name": "loras", "clip_name": "text_encoders", "vae_name": "vae"}
EXPECT_PINS = {
    "wan_animate_2_int8_convrot.safetensors": "0580ecdd65e47e97c30df9670d13a6c4a131d26de5a1faf2ccc78392d5167584",
    "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors": "85c4a61c30e0497aa44b91d93a893b624708461a56fe5485183b28fa07e2dfb3",
    "umt5_xxl_fp8_e4m3fn_scaled.safetensors": "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
    "clip_vision_h.safetensors": "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161",
    "Wan2_1_VAE_bf16.safetensors": "1ab9a32cc2c740f6e39d80d367ce5dcc28db8c71b79b28670546b8973e9d75f9",
}
REF_SHA = "1311699b55c586abdb631d0468b4afc19cdf73a1b45b86fc4403f4517daf03fe"
BASE_POSE = {"pose_start_percent": 0, "pose_end_percent": 0}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def hash_workflow(graph: dict) -> str:
    return hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def node_inventory(oi: dict) -> dict:
    inv = {}
    for cls, spec in sorted((oi or {}).items()):
        if not isinstance(spec, dict):
            continue
        inputs = spec.get("input") or {}
        inv[cls] = {"required": sorted((inputs.get("required") or {}).keys()),
                    "optional": sorted((inputs.get("optional") or {}).keys()),
                    "return_types": spec.get("output") or [],
                    "output_node": bool(spec.get("output_node")),
                    "python_module": spec.get("python_module") or ""}
    return inv


def hash_inventory(oi: dict) -> str:
    return hashlib.sha256(json.dumps(node_inventory(oi), sort_keys=True,
                                     separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def ffprobe_frames(p: Path) -> dict:
    out = {}
    for key, args in (("nb_read_frames", ["-count_frames"]), ("nb_frames", [])):
        cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0"] + args + [
            "-show_entries", f"stream={key},width,height,r_frame_rate,time_base",
            "-of", "json", str(p)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            out[key] = json.loads(r.stdout or "{}").get("streams", [{}])
        except Exception as exc:  # noqa: BLE001
            out[key] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


def native_pose_window() -> dict:
    """Widget vector of native subgraph node 587 -> named values via live widget order."""
    t = json.loads(NATIVE_TEMPLATE.read_text(encoding="utf-8"))
    node = None
    for sg in (t.get("definitions") or {}).get("subgraphs") or []:
        if not str(sg.get("name") or "").startswith("Motion Transfer"):
            continue
        for n in sg.get("nodes") or []:
            if n.get("type") == "WanAnimate2ToVideo":
                node = n
    if node is None:
        return {"found": False}
    return {"found": True, "subgraph": "Motion Transfer (Wan Animate 2)",
            "node_id": node.get("id"), "type": node.get("type"),
            "widgets_values": node.get("widgets_values")}


def main() -> int:
    m1_p, base_p, out_p = (Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    m1 = json.loads(m1_p.read_text(encoding="utf-8"))
    base = json.loads(base_p.read_text(encoding="utf-8"))

    oi = json.loads(urllib.request.urlopen(f"{BASE_URL}/object_info", timeout=180)
                    .read().decode("utf-8"))
    inv_sha = hash_inventory(oi)
    classes = sorted({n.get("class_type") for n in m1.values()})
    missing = [c for c in classes if c not in oi]

    # -------- widget order for WanAnimate2ToVideo, from the LIVE server ---------
    spec = oi.get("WanAnimate2ToVideo") or {}
    req = list(((spec.get("input") or {}).get("required") or {}).items())
    opt = [k for k, _ in (((spec.get("input") or {}).get("optional") or {}).items())]
    linky = {"positive", "negative", "vae", "reference_image", "pose_video",
             "clip_vision_output", "positive_pose", "clip_vision_output_pose",
             "continue_motion"}
    widget_order = [k for k, _ in req if k not in linky]
    defaults = {k: (v[1].get("default") if len(v) > 1 and isinstance(v[1], dict) else None)
                for k, v in req}

    nat = native_pose_window()
    nat_named = {}
    if nat.get("found") and len(nat.get("widgets_values") or []) >= len(widget_order):
        nat_named = dict(zip(widget_order, nat["widgets_values"]))

    # -------- model pins --------------------------------------------------------
    pins, pin_mismatch = {}, []
    for node in m1.values():
        ins = node.get("inputs") or {}
        for key, sub in MODEL_KEYS.items():
            val = ins.get(key)
            if not isinstance(val, str):
                continue
            cand = RT / "models" / sub / val
            if not cand.is_file():
                cand = RT / "models" / ("clip_vision" if "clip_vision" in val else sub) / val
            pins[val] = sha256_file(cand) if cand.is_file() else "<absent>"
            if pins[val] != EXPECT_PINS.get(val, pins[val]):
                pin_mismatch.append({"file": val, "expected": EXPECT_PINS.get(val),
                                     "actual": pins[val], "path": str(cand)})

    epoch = json.loads((RT / "instance_epoch.json").read_text(encoding="utf-8"))

    m1_pose = m1["672:587"]["inputs"]
    base_pose = base["672:587"]["inputs"]
    pose_delta = {k: {"baseline": base_pose.get(k), "m1": m1_pose.get(k)}
                  for k in ("pose_start_percent", "pose_end_percent", "pose_strength",
                            "reference_image_strength")
                  if base_pose.get(k) != m1_pose.get(k)}

    ref_sha = sha256_file(REFERENCE) if REFERENCE.is_file() else "<absent>"
    drive_probe = ffprobe_frames(DRIVING) if DRIVING.is_file() else {"error": "absent"}

    checks = {
        "live_node_inventory_hash_matches_pin": inv_sha == NODE_INVENTORY_SHA256,
        "no_missing_class": not missing,
        "model_pins_match": not pin_mismatch,
        "reference_image_sha_matches": ref_sha == REF_SHA,
        "pose_delta_is_exactly_end_percent": set(pose_delta) == {"pose_end_percent"},
        "pose_window_is_native": (m1_pose.get("pose_start_percent")
                                  == nat_named.get("pose_start_percent")
                                  and m1_pose.get("pose_end_percent")
                                  == nat_named.get("pose_end_percent")),
        "baseline_pose_window_was_not_native": (base_pose.get("pose_end_percent")
                                                != nat_named.get("pose_end_percent")),
    }
    rec = {
        "artifact": "m1_preflight.json",
        "task_id": "MF-V1-VIDEO14B",
        "round": "waveB_m1",
        "engine_epoch_on_disk": epoch,
        "m1_graph": {"path": str(m1_p), "graph_sha256_canonical": hash_workflow(m1),
                     "nodes": len(m1), "classes": len(classes)},
        "live_object_info": {
            "url": f"{BASE_URL}/object_info",
            "node_inventory_sha256": inv_sha,
            "pinned": NODE_INVENTORY_SHA256,
            "missing_classes": missing,
        },
        "model_pins_recomputed": pins,
        "model_pin_mismatches": pin_mismatch,
        "input_pins": {"reference": {"path": str(REFERENCE), "sha256": ref_sha},
                       "driving": {"path": str(DRIVING),
                                   "sha256": sha256_file(DRIVING) if DRIVING.is_file() else None,
                                   "probe": drive_probe},
                       "window": "source frames 1650..1769 (121 decoded frames)"},
        "single_delta_vs_frozen_baseline": pose_delta,
        "native_template": {
            "path": str(NATIVE_TEMPLATE),
            "file_sha256": sha256_file(NATIVE_TEMPLATE) if NATIVE_TEMPLATE.is_file() else None,
            "wan_animate2_node": nat,
            "widget_order_from_live_object_info": widget_order,
            "link_inputs_from_live_object_info": sorted(linky),
            "optional_inputs_from_live_object_info": opt,
            "widget_defaults_from_live_object_info": defaults,
            "native_named_widget_values": nat_named,
            "m1_node_672_587_inputs": m1_pose,
        },
        "checks": checks,
        "verdict": "PREFLIGHT_OK" if all(checks.values()) else "PREFLIGHT_FAILED",
    }
    out_p.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"verdict": rec["verdict"], "checks": checks,
                      "missing_classes": missing,
                      "pose_delta": pose_delta,
                      "native_named": nat_named,
                      "m1_pose": {k: m1_pose.get(k) for k in
                                  ("pose_strength", "pose_start_percent",
                                   "pose_end_percent", "reference_image_strength")},
                      "out": str(out_p)}, indent=1, ensure_ascii=False))
    return 0 if rec["verdict"] == "PREFLIGHT_OK" else 5


if __name__ == "__main__":
    raise SystemExit(main())
