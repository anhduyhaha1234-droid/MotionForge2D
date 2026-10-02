"""MF-END-14 — build the delivered graph document `app/media_workflows/shot_anchor_v1.json`.

NEW file in the allowlist -> whole-file generation (no preimage exists yet).
The frozen prompt text is EXTRACTED from the accepted proof's API graph
(`proof/graphs/anchor_book.p2.api.json`, node 75:74) and its sha256 is asserted at build
time, so no byte is transcribed by hand.

Writes:  <WT>/app/media_workflows/shot_anchor_v1.json   (deliverable)
         <EV>/raw/build_record.json                     (evidence)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-14")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-14")
PROOF = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof")
OUT = WT / "app/media_workflows/shot_anchor_v1.json"

PROOF_GRAPH = PROOF / "graphs/anchor_book.p2.api.json"
PROOF_GRAPH_SHA = "853cafb4f88fa8a284d6de085910a573640e0e76e58a52e3d75a90ed6c2d46cb"

TEMPLATE_PATH = ("C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/venv/Lib/"
                 "site-packages/comfyui_workflow_templates_json/templates/"
                 "image_flux2_klein_image_edit_4b_distilled.json")
TEMPLATE_SHA = "e0388a8870495802314d58fa61616ddcdb7064dac5f85a8787c9e08180b8a560"

# staged input names (files that must exist in the isolated server input dir)
KEYFRAME_FILE = "sa_v1_keyframe_book_f000.png"
REF_FILES = {"ROLE-BOOK-P1": "sa_v1_ref_p1_boy_hacker.png",
             "ROLE-BOOK-P2": "sa_v1_ref_p2_dan_choi.png",
             "ROLE-BOOK-P3": "sa_v1_ref_p3_gau_nau_back.png"}
SAVE_PREFIX = "mf_shot_anchor_v1/book_f000"
CANVAS = (640, 368)
REF_LONGER = 368
NEUTRAL_RGB = (128, 128, 128)
NEUTRAL_INT = 8421504
SEED = 2026092501
STEPS = 4
CFG = 1.0
SAMPLER_NAME = "euler"

FACTS_DIGEST = "b286377c2ba583dffe19b43dd0fac0530eb8a3b77af4d06aac876c645234191b"
TRACK_DIGEST = "47e327e94d8c3d53d77ac6e5794d1da3c52f6ae35f790a6d4f5d8eacb235492d"
SOURCE_SHA = "0a7ed862b799838a13eea9e2202b0962b41d383c3ca35f06ce8d1fc00cbe4acc"
KEYFRAME_SHA = "3f0d090a9c022fe136542c9f017b1f7cde40b1f79e80b92541846ed0e0a9c8c0"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def N(class_type: str, inputs: dict, title: str) -> dict:
    return {"class_type": class_type, "inputs": inputs, "_meta": {"title": title}}


def intake(prefix: str, load_node: str, file_key: str) -> dict:
    """One image intake: LoadImage -> declared-neutral composite ONCE (mask inverted) -> [resize]."""
    return {
        f"{prefix}_LOAD": N("LoadImage", {"image": file_key},
                            f"{prefix}: staged input (opaque RGB or RGBA; composite below is "
                            "the declared identity for opaque inputs)"),
        f"{prefix}_SIZE": N("GetImageSize", {"image": [load_node, 0]}, f"{prefix}: source size"),
        f"{prefix}_BG": N("EmptyImage", {"width": [f"{prefix}_SIZE", 0],
                                         "height": [f"{prefix}_SIZE", 1],
                                         "batch_size": 1, "color": NEUTRAL_INT},
                          f"{prefix}: declared neutral background 0x808080"),
        f"{prefix}_INV": N("InvertMask", {"mask": [load_node, 1]},
                           f"{prefix}: LoadImage MASK is 1-alpha; invert to alpha"),
        f"{prefix}_COMP": N("ImageCompositeMasked",
                            {"destination": [f"{prefix}_BG", 0], "source": [load_node, 0],
                             "x": 0, "y": 0, "resize_source": False,
                             "mask": [f"{prefix}_INV", 0]},
                            f"{prefix}: composite ONCE (graph-side alpha policy)"),
    }


def main() -> int:
    assert sha256_file(PROOF_GRAPH) == PROOF_GRAPH_SHA, "proof graph hash drift"
    proof = json.loads(PROOF_GRAPH.read_text(encoding="utf-8"))
    prompt = proof["75:74"]["inputs"]["text"]
    assert isinstance(prompt, str) and len(prompt) > 3000, "prompt extraction failed"
    prompt_sha = sha256_bytes(prompt.encode("utf-8"))
    # sanity: the accepted prompt is for exactly this ref order (refs 2,3,4)
    for needle in ("reference image 2", "reference image 3", "reference image 4",
                   "PARTIALLY inside the frame", "keep the book closed"):
        assert needle in prompt, f"prompt lost the accepted binding: {needle!r}"

    g: dict = {}
    g.update(intake("KEY", "KEY_LOAD", KEYFRAME_FILE))
    for i, role in enumerate(("ROLE-BOOK-P1", "ROLE-BOOK-P2", "ROLE-BOOK-P3"), start=1):
        g.update(intake(f"R{i}", f"R{i}_LOAD", REF_FILES[role]))
    # the keyframe latent feeds the conditioning chain first (reference image 1)
    g["KEY_ENC"] = N("VAEEncode", {"pixels": ["KEY_COMP", 0], "vae": ["VAE", 0]},
                     "reference image 1: keyframe latent (edit base / composition)")
    for i in (1, 2, 3):
        g[f"R{i}_RES"] = N("ResizeImageMaskNode",
                           {"input": [f"R{i}_COMP", 0], "resize_type": "scale longer dimension",
                            "resize_type.longer_size": REF_LONGER, "scale_method": "area"},
                           f"reference image {i + 1}: aspect-preserving resize, no crop")
        g[f"R{i}_ENC"] = N("VAEEncode", {"pixels": [f"R{i}_RES", 0], "vae": ["VAE", 0]},
                           f"reference image {i + 1}: latent for the conditioning chain")

    g["PROMPT"] = N("CLIPTextEncode", {"text": prompt, "clip": ["CLIP", 0]},
                    "frozen shot-anchor prompt (role map + holder + partial policy, verbatim)")
    g["NEG_ZERO"] = N("ConditioningZeroOut", {"conditioning": ["PROMPT", 0]},
                      "distilled template: zeroed negative")
    g["KPOS"] = N("ReferenceLatent", {"conditioning": ["PROMPT", 0], "latent": ["KEY_ENC", 0]},
                  "positive + reference image 1 (keyframe)")
    g["KNEG"] = N("ReferenceLatent", {"conditioning": ["NEG_ZERO", 0], "latent": ["KEY_ENC", 0]},
                  "negative + reference image 1 (keyframe)")
    prev_pos, prev_neg = "KPOS", "KNEG"
    for i in (1, 2, 3):
        g[f"R{i}_POS"] = N("ReferenceLatent",
                           {"conditioning": [prev_pos, 0], "latent": [f"R{i}_ENC", 0]},
                           f"positive + reference image {i + 1} (cast conditioning, chained)")
        g[f"R{i}_NEG"] = N("ReferenceLatent",
                           {"conditioning": [prev_neg, 0], "latent": [f"R{i}_ENC", 0]},
                           f"negative + reference image {i + 1} (cast conditioning, chained)")
        prev_pos, prev_neg = f"R{i}_POS", f"R{i}_NEG"

    g["UNET"] = N("UNETLoader", {"unet_name": "flux-2-klein-4b-fp8.safetensors",
                                 "weight_dtype": "default"}, "FLUX.2 klein 4B fp8 (distilled)")
    g["CLIP"] = N("CLIPLoader", {"clip_name": "qwen_3_4b.safetensors", "type": "flux2",
                                 "device": "default"}, "Qwen3-4B text encoder")
    g["VAE"] = N("VAELoader", {"vae_name": "flux2-vae.safetensors"}, "FLUX.2 VAE")
    g["LATENT"] = N("EmptyFlux2LatentImage", {"width": CANVAS[0], "height": CANVAS[1],
                                              "batch_size": 1},
                    "canvas = source composition geometry (declared constants, /16)")
    g["SIGMAS"] = N("Flux2Scheduler", {"steps": STEPS, "width": CANVAS[0], "height": CANVAS[1]},
                    "Flux2Scheduler (distilled 4 steps)")
    g["SAMPLER"] = N("KSamplerSelect", {"sampler_name": SAMPLER_NAME}, SAMPLER_NAME)
    g["NOISE"] = N("RandomNoise", {"noise_seed": SEED},
                   "declared seed (same as the accepted P2 BOOK anchor, for comparability)")
    g["GUIDER"] = N("CFGGuider", {"cfg": CFG, "model": ["UNET", 0],
                                  "positive": [prev_pos, 0], "negative": [prev_neg, 0]},
                    "cfg 1 (distilled)")
    g["SAMPLE"] = N("SamplerCustomAdvanced", {"noise": ["NOISE", 0], "guider": ["GUIDER", 0],
                                              "sampler": ["SAMPLER", 0], "sigmas": ["SIGMAS", 0],
                                              "latent_image": ["LATENT", 0]}, "sample")
    g["DECODE"] = N("VAEDecode", {"samples": ["SAMPLE", 0], "vae": ["VAE", 0]}, "decode")
    g["SAVE"] = N("SaveImage", {"filename_prefix": SAVE_PREFIX, "images": ["DECODE", 0]},
                  "save target full-scene anchor (opaque RGB PNG)")

    doc = {
        "schema_version": "mf.shot_anchor.graph.v1",
        "graph_id": "shot_anchor_v1",
        "purpose": ("Build the TARGET full-scene anchor of a shot, headless: the measured source "
                    "keyframe is redrawn in the cast's flat style with every role (incl. the "
                    "partial person at the frame edge) addressed, while the holder, the book state, "
                    "the camera and the layout of the source composition are kept. No video."),
        "derived_from": {
            "template_id": "image_flux2_klein_image_edit_4b_distilled",
            "template_path": TEMPLATE_PATH,
            "template_sha256": TEMPLATE_SHA,
            "template_sha256_16": TEMPLATE_SHA[:16],
            "accepted_predecessor_graph": {
                "file": "proof/graphs/anchor_book.p2.api.json",
                "sha256": PROOF_GRAPH_SHA,
                "why": ("the accepted P2 BOOK anchor run; this in-tree graph is its formalization: "
                        "declared canvas, per-image alpha composite, the same 4 inputs, the same "
                        "seed, the same frozen prompt (text sha frozen below)"),
            },
            "in_tree_precedent": {
                "graph": "app/media_workflows/reference_asset_v1.json",
                "why": "same formalization pattern (parameters/alpha/dimensions policies + validator)",
            },
            "multi_reference_support": {
                "node_source": "comfy_extras/nodes_edit_model.py: ReferenceLatent",
                "node_doc": ("\"If the model supports it you can chain multiple to set multiple "
                             "reference images.\""),
                "model_source": ("comfy/model_base.py Flux.extra_conds -> ref_latents CONDList over "
                                 "ALL reference_latents (not only the last); Flux2 inherits"),
                "measured": ("the accepted predecessor graph chained 3 extra references on both "
                             "positive and negative conditioning; extra anchors are CONDITIONING "
                             "ONLY (they never drive canvas/size or the edit base)"),
            },
        },
        "source_facts": {
            "artifact_schema": "mf.source_interaction_facts.v1",
            "artifact_digest": FACTS_DIGEST,
            "track_artifact_digest": TRACK_DIGEST,
            "track_engine": "sam2.1",
            "producer": "MF-END-13 app/services/source_interaction_facts.py (sealed artifact, "
                        "production=true)",
            "window_id": "BOOK",
            "source_sha256": SOURCE_SHA,
            "keyframe": {
                "frame": 0,
                "file": KEYFRAME_FILE,
                "sha256": KEYFRAME_SHA,
                "dims": list(CANVAS),
                "recipe": ("native 640x360 decoded at t=0 + translation pad 4/4 (measured, "
                           "P1_UNIT_MANIFESTS BOOK-UNIT-001 'source_frame'); the graph never "
                           "resamples or crops the frame"),
            },
            "camera": {
                "classification": "static",
                "cut_frames": [],
                "content_events": [72, 95],
                "border_drift_px_per_frame_median": 0.000468,
                "policy": ("no new camera is inferred: the canvas IS the source composition "
                           "geometry and the graph exposes NO camera/zoom/crop/pan parameter"),
            },
            "holder": {
                "subject_role_id": "ROLE-BOOK-P1",
                "object_role_id": "PROP-BOOK",
                "contact_intervals": 7,
                "first_interval": [2, 17],
                "last_interval": [106, 120],
                "all_kind": "grasp",
            },
            "occlusion": {
                "occluder_role_id": "PROP-BOOK",
                "occludee_role_id": "ROLE-BOOK-P1",
                "order": "in_front_of",
                "span": [0, 120],
                "mean_containment": 0.969667,
            },
            "change_frames": [1, 2, 17, 43, 46, 47, 72, 95, 105, 106],
            "book_state_at_keyframe": ("closed, cover upright against the chest; the book's first "
                                       "state change in the source is open_two_pages @72, outside "
                                       "frame 0"),
        },
        "role_map": {
            "note": ("each visible person and the prop, with the measured source evidence and the "
                     "target disposition; the frozen prompt binds the same mapping (reference "
                     "images 2/3/4) and the partial-person keep policy"),
            "roles": [
                {"role_id": "ROLE-BOOK-P1", "instance_id": "trk:ROLE-BOOK-P1", "kind": "person",
                 "source_evidence": {"tracker": "sam2.1", "track_digest": TRACK_DIGEST,
                                     "bbox_frame0_xywh": [223, 100, 72, 196], "span": [0, 120],
                                     "visibility": "visible"},
                 "target_ref": {"file": REF_FILES["ROLE-BOOK-P1"],
                                "sha256": "a2ad4db98ac733c969260d052f35e737c37eef664b1b36d5a6fd9a7254006821",
                                "kind": "cast_placeholder_flat_color_block",
                                "appearance_claim": False},
                 "disposition": ("redraw with the reference-2 design at the same seated position, "
                                 "same silhouette envelope; keeps holding the closed book "
                                 "(holder fact)")},
                {"role_id": "ROLE-BOOK-P2", "instance_id": None, "kind": "person",
                 "source_evidence": {"unit_manifest": "BOOK-UNIT-001",
                                     "element": "cast_dan_choi_seated_cross_legged",
                                     "authored_artwork_sha256":
                                         "271f1c5789ee8fb9022ab402d834c8f2d4e862f972a105060e457b68b0282496",
                                     "staged_on_neutral_sha256":
                                         "2ffc245346340b4cc95ffa4c5ac9f3ad3e4485927a655e6a47ab960e5c848969"},
                 "target_ref": {"file": REF_FILES["ROLE-BOOK-P2"],
                                "sha256": "2ffc245346340b4cc95ffa4c5ac9f3ad3e4485927a655e6a47ab960e5c848969",
                                "kind": "authored_artwork_on_neutral", "appearance_claim": True},
                 "disposition": ("redraw with the reference-3 design at the same standing position "
                                 "behind-right; never copy the reference's own stance")},
                {"role_id": "ROLE-BOOK-P3", "instance_id": None, "kind": "person",
                 "source_evidence": {"unit_manifest": "BOOK-UNIT-001",
                                     "element": "cast_gau_nau_back_PLACEHOLDER_flat_color_block",
                                     "staged_on_neutral_sha256":
                                         "49e99094d802495dd92e1dbab87125806efcb077f0be37125738b7218a63096f"},
                 "target_ref": {"file": REF_FILES["ROLE-BOOK-P3"],
                                "sha256": "49e99094d802495dd92e1dbab87125806efcb077f0be37125738b7218a63096f",
                                "kind": "cast_placeholder_flat_color_block",
                                "appearance_claim": False},
                 "disposition": ("redraw with the reference-4 design at the same position, seen "
                                 "from behind, same amount of body showing")},
                {"role_id": "ROLE-BOOK-P4-EDGE", "instance_id": "trk:ROLE-BOOK-P4-EDGE",
                 "kind": "partial_person_at_frame_edge",
                 "source_evidence": {"tracker": "sam2.1", "track_digest": TRACK_DIGEST,
                                     "bbox_frame0_xywh": [597, 98, 43, 194], "border_touch": True,
                                     "span": [0, 120]},
                 "target_ref": None,
                 "disposition": ("KEEP PARTIAL: stays at the same edge with exactly the same "
                                 "amount visible; not completed, not brought into frame, not "
                                 "removed (frozen prompt states this binding)")},
                {"role_id": "PROP-BOOK", "instance_id": "trk:PROP-BOOK", "kind": "prop",
                 "source_evidence": {"tracker": "sam2.1", "track_digest": TRACK_DIGEST,
                                     "bbox_frame0_xywh": [248, 161, 50, 71], "span": [0, 120]},
                 "target_ref": None,
                 "disposition": ("redrawn in the same flat style, same position, closed upright "
                                 "with the yellow part beside it; no page spread at frame 0")},
            ],
        },
        "parameters": [
            {"name": "keyframe", "pointer": "graph/KEY_LOAD/inputs/image", "type": "string",
             "rule": ("file in the isolated server input dir; MUST be the frozen keyframe "
                      f"(sha256 {KEYFRAME_SHA[:16]}...), dims == canvas"),
             "golden": KEYFRAME_FILE},
            {"name": "ref_p1", "pointer": "graph/R1_LOAD/inputs/image", "type": "string",
             "rule": "cast reference for ROLE-BOOK-P1 (reference image 2 in the prompt)",
             "golden": REF_FILES["ROLE-BOOK-P1"]},
            {"name": "ref_p2", "pointer": "graph/R2_LOAD/inputs/image", "type": "string",
             "rule": "cast reference for ROLE-BOOK-P2 (reference image 3 in the prompt)",
             "golden": REF_FILES["ROLE-BOOK-P2"]},
            {"name": "ref_p3", "pointer": "graph/R3_LOAD/inputs/image", "type": "string",
             "rule": "cast reference for ROLE-BOOK-P3 (reference image 4 in the prompt)",
             "golden": REF_FILES["ROLE-BOOK-P3"]},
            {"name": "prompt", "pointer": "graph/PROMPT/inputs/text", "type": "string",
             "rule": "frozen shot-anchor prompt (verbatim from the accepted P2 BOOK anchor graph)",
             "golden": None, "golden_sha256": prompt_sha},
            {"name": "seed", "pointer": "graph/NOISE/inputs/noise_seed", "type": "int",
             "rule": "0 <= seed < 2**63", "golden": SEED},
            {"name": "canvas_width", "pointer": "graph/LATENT/inputs/width", "type": "int",
             "rule": "16..16384, divisible by 16; must equal the staged keyframe width",
             "mirrors": ["graph/SIGMAS/inputs/width"], "golden": CANVAS[0]},
            {"name": "canvas_height", "pointer": "graph/LATENT/inputs/height", "type": "int",
             "rule": "16..16384, divisible by 16; must equal the staged keyframe height",
             "mirrors": ["graph/SIGMAS/inputs/height"], "golden": CANVAS[1]},
            {"name": "ref_longer_side",
             "pointer": "graph/R1_RES/inputs/resize_type.longer_size", "type": "int",
             "rule": "16..4096, python round() (half-to-even) as in the node",
             "mirrors": ["graph/R2_RES/inputs/resize_type.longer_size",
                         "graph/R3_RES/inputs/resize_type.longer_size"],
             "golden": REF_LONGER},
            {"name": "neutral_rgb_int", "pointer": "graph/KEY_BG/inputs/color", "type": "int",
             "rule": "0..0xFFFFFF as 0xRRGGBB",
             "mirrors": ["graph/R1_BG/inputs/color", "graph/R2_BG/inputs/color",
                         "graph/R3_BG/inputs/color"],
             "golden": NEUTRAL_INT},
            {"name": "steps", "pointer": "graph/SIGMAS/inputs/steps", "type": "int",
             "rule": "distilled profile: 4 (a base profile of 20 steps is NOT this graph)",
             "golden": STEPS},
            {"name": "cfg", "pointer": "graph/GUIDER/inputs/cfg", "type": "number",
             "rule": "distilled profile: 1", "golden": CFG},
            {"name": "sampler", "pointer": "graph/SAMPLER/inputs/sampler_name", "type": "string",
             "rule": "enum: measured registered samplers", "golden": SAMPLER_NAME},
            {"name": "filename_prefix", "pointer": "graph/SAVE/inputs/filename_prefix",
             "type": "string",
             "rule": "run-scoped prefix; outputs land under <output>/<prefix>_00001_.png",
             "golden": SAVE_PREFIX},
        ],
        "alpha_policy": {
            "neutral_rgb": list(NEUTRAL_RGB),
            "emptyimage_color_int": NEUTRAL_INT,
            "composite_applied_in_graph": True,
            "composite_times_per_image": 1,
            "images_covered": ["KEY_LOAD", "R1_LOAD", "R2_LOAD", "R3_LOAD"],
            "formula": "out = rgb*(alpha/255) + neutral*(1 - alpha/255)",
            "nodes": {"background": "<P>_BG:EmptyImage", "invert": "<P>_INV:InvertMask",
                      "composite": "<P>_COMP:ImageCompositeMasked"},
            "mask_convention": ("measured in the pinned runtime: nodes.py LoadImage returns "
                                "MASK = 1 - alpha; comfy_extras/nodes_mask.py "
                                "ImageCompositeMasked weights the SOURCE with `mask`; so the mask "
                                "must be inverted first"),
            "why": ("all delivered inputs are opaque RGB (measured: composite is the identity "
                    "path); an RGBA input (e.g. the raw authored artwork) is still composited "
                    "correctly exactly once instead of being silently blackened by VAEEncode"),
            "output": {"channel_count": 3, "alpha_synthesized": False,
                       "format": "PNG (opaque RGB)",
                       "owner_of_background_removal": ("library ingest job - NOT this graph; no "
                                                       "segmentation weights are claimed here")},
        },
        "dimensions_policy": {
            "canvas_wh": list(CANVAS),
            "canvas_source": ("declared constants in the graph (parameters canvas_width/height); "
                              "canvas == source keyframe composition geometry (640x360 native + "
                              "4/4 translation pad, measured)"),
            "divisible_by": 16,
            "reference_resize": {"node": "<P>_RES:ResizeImageMaskNode",
                                 "resize_type": "scale longer dimension",
                                 "longer_size": REF_LONGER, "scale_method": "area",
                                 "node_formula": ("comfy_extras/nodes_post_processing.py "
                                                  "scale_longer_dimension - python round() "
                                                  "(half-to-even)")},
            "crop_applied": False,
            "stretch_applied": False,
            "layout_pin": ("the delivered anchor keeps the source layout: same aspect, same frame "
                           "edges, no crop/zoom/letterbox; the graph exposes no geometry "
                           "parameter other than the declared canvas/ref-resize constants"),
            "output_dims": "equal to canvas_wh (verified against the real run receipt)",
        },
        "graph": g,
        "tensor_preview": {
            "job": ("CPU-only prefix job of the same isolated server; its graph has NO model node, "
                    "so it is not a GPU job and runs before the golden GPU job (one job at a time)"),
            "renders": [
                {"node": "KEY_COMP", "reason": "composited keyframe (identity path, opaque in)"},
                {"node": "R1_COMP", "reason": "composited cast ref 1"},
                {"node": "R1_RES", "reason": "resized cast ref 1"},
                {"node": "R2_COMP", "reason": "composited cast ref 2"},
                {"node": "R2_RES", "reason": "resized cast ref 2"},
                {"node": "R3_COMP", "reason": "composited cast ref 3"},
                {"node": "R3_RES", "reason": "resized cast ref 3"},
            ],
            "pixel_comparison": ("each rendered preview's display pixels must equal the OFFLINE "
                                 "float32 node path (torch.nn.functional.interpolate mode='area') "
                                 "byte-for-byte: sha256 equality in raw/run_record.json"),
            "overlay": {
                "artifact": "previews/sa_v1_overlay_*.png",
                "recipe": ("role/prop/contact overlay drawn from the SEALED MF-END-12 masks "
                           "(raw/mask_*.png) and the SEALED MF-END-13 facts on both the source "
                           "keyframe and the produced anchor, for review BEFORE video"),
                "never_an_input": "the overlay is derived evidence; it is not part of the graph",
            },
        },
        "golden_request": {
            "shot": "BOOK", "window_id": "BOOK", "keyframe_frame": 0,
            "why_this_keyframe": ("frame 0 of the measured BOOK window; camera static, book "
                                  "closed; the accepted P2 anchor gates measured this composition"),
            "seed_rationale": ("the same seed as the accepted P2 BOOK anchor run, so the delivered "
                               "graph is directly comparable with the accepted anchor"),
            "source_facts_digest": FACTS_DIGEST,
            "staged_inputs": [
                {"role": "reference image 1 (edit base / canvas driver)", "file": KEYFRAME_FILE,
                 "sha256": KEYFRAME_SHA, "bytes": 115799, "dims": list(CANVAS), "mode": "RGB",
                 "source": "proof/inputs/i1_BOOK_f000_640x368.png"},
                {"role": "reference image 2 (ROLE-BOOK-P1 design)", "file": REF_FILES["ROLE-BOOK-P1"],
                 "sha256": "a2ad4db98ac733c969260d052f35e737c37eef664b1b36d5a6fd9a7254006821",
                 "bytes": 3586, "dims": [768, 512], "mode": "RGB",
                 "source": "proof/inputs/i1d_cast_boy_hacker_sitting_on_neutral_bg.png",
                 "appearance_claim": False},
                {"role": "reference image 3 (ROLE-BOOK-P2 design)", "file": REF_FILES["ROLE-BOOK-P2"],
                 "sha256": "2ffc245346340b4cc95ffa4c5ac9f3ad3e4485927a655e6a47ab960e5c848969",
                 "bytes": 156508, "dims": [1024, 1024], "mode": "RGB",
                 "source": "proof/inputs/i1d_cast_dan_choi_standing_on_neutral_bg.png"},
                {"role": "reference image 4 (ROLE-BOOK-P3 design)", "file": REF_FILES["ROLE-BOOK-P3"],
                 "sha256": "49e99094d802495dd92e1dbab87125806efcb077f0be37125738b7218a63096f",
                 "bytes": 3195, "dims": [640, 640], "mode": "RGB",
                 "source": "proof/inputs/i1d_cast_gau_nau_back_on_neutral_bg.png",
                 "appearance_claim": False},
            ],
            "prompt_sha256": prompt_sha,
            "prompt_len": len(prompt),
            "bindings": {
                "keyframe": {"pointer": "graph/KEY_LOAD/inputs/image", "value": KEYFRAME_FILE},
                "ref_p1": {"pointer": "graph/R1_LOAD/inputs/image",
                           "value": REF_FILES["ROLE-BOOK-P1"]},
                "ref_p2": {"pointer": "graph/R2_LOAD/inputs/image",
                           "value": REF_FILES["ROLE-BOOK-P2"]},
                "ref_p3": {"pointer": "graph/R3_LOAD/inputs/image",
                           "value": REF_FILES["ROLE-BOOK-P3"]},
                "seed": {"pointer": "graph/NOISE/inputs/noise_seed", "value": SEED},
                "canvas_width": {"pointer": "graph/LATENT/inputs/width", "value": CANVAS[0]},
                "canvas_height": {"pointer": "graph/LATENT/inputs/height", "value": CANVAS[1]},
                "ref_longer_side": {"pointer": "graph/R1_RES/inputs/resize_type.longer_size",
                                    "value": REF_LONGER},
                "neutral_rgb_int": {"pointer": "graph/KEY_BG/inputs/color", "value": NEUTRAL_INT},
                "steps": {"pointer": "graph/SIGMAS/inputs/steps", "value": STEPS},
                "cfg": {"pointer": "graph/GUIDER/inputs/cfg", "value": CFG},
                "filename_prefix": {"pointer": "graph/SAVE/inputs/filename_prefix",
                                    "value": SAVE_PREFIX},
            },
        },
        "output_contract": {
            "node": "SAVE:SaveImage", "files": 1, "dims": "canvas_wh", "alpha": "opaque RGB",
            "naming": "<filename_prefix>_00001_.png under the run output dir",
            "note": ("the anchor is a still image; video rendering is a different task "
                     "(Wan profile), not this graph"),
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    OUT.write_text(text, encoding="utf-8")
    canonical = json.dumps(doc["graph"], sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    rec = {
        "artifact": "build_record.json",
        "graph_file": str(OUT).replace("\\", "/"),
        "graph_file_sha256": sha256_file(OUT),
        "graph_object_sha256": sha256_bytes(canonical),
        "prompt_sha256": prompt_sha, "prompt_len": len(prompt),
        "prompt_source": str(PROOF_GRAPH).replace("\\", "/"),
        "nodes": len(g), "save_nodes": [k for k, v in g.items() if v["class_type"] == "SaveImage"],
        "classes": sorted({v["class_type"] for v in g.values()}),
        "bytes": len(text.encode("utf-8")),
    }
    (EV / "raw").mkdir(parents=True, exist_ok=True)
    (EV / "raw/build_record.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                              encoding="utf-8")
    print(json.dumps(rec, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
