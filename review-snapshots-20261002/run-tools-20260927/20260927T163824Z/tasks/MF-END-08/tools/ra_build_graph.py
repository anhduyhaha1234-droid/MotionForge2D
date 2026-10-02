"""MF-END-08 — build `app/media_workflows/reference_asset_v1.json` (+ build record).

Derived from the OFFICIAL INSTALLED template
`comfyui_workflow_templates_json/templates/image_flux2_klein_image_edit_4b_distilled.json`
(the template's subgraph nodes are inlined to a flat API prompt), with:
  * declared canvas constants (official asks GetImageSize from the scaled input),
  * an IN-GRAPH alpha composite for RGBA references (EmptyImage neutral + InvertMask +
    ImageCompositeMasked) using the node-verified mask convention (`LoadImage` MASK = 1-alpha),
  * ResizeImageMaskNode 'scale longer dimension' for the reference (the accepted I1 handling).

Validator: imported from the delivered test module (single source of truth).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

EV = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/tasks/MF-END-08")
WT = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/MF-END-08")
TEST_PY = WT / "tests/product_delivery/test_mf_end_08.py"
OUT_JSON = WT / "app/media_workflows/reference_asset_v1.json"
OI = Path("C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/"
          "proof/evidence/P3_object_info_gpu.json")

SEED = 2026092801
REF_IMAGE = "ra_v1_ref_dan_choi.png"
REF_LONGER = 768
NEUTRAL_INT = 8421504
PREFIX = "mf_reference_asset_v1/dan_choi_back"

PROMPT = (
    "Reference image 1 is the character design: a flat doodle drawing in solid black ink on a "
    "plain light-grey background - a figure in a black baseball cap with its brim to the left, a "
    "black hoodie with a small STREET label on the chest, black trousers, black sneakers with "
    "laces and a tail that curls out behind, seated cross-legged, holding a phone in both hands "
    "and facing the viewer.\n"
    "Redraw this exact same character as a full-body view from BEHIND: the viewer now sees the "
    "character's back. The head shows only the back and the crown of the black cap - no eyes, no "
    "face, no mouth, no facial features at all - and the STREET label is not visible from this "
    "side because it is printed on the front of the chest. The black hoodie is seen from its back "
    "side with the hood lying flat, the tail curls out to the side of the body, and the phone "
    "stays in the character's hands as a small black shape beside the hip. Keep exactly the same "
    "drawing style as reference image 1: solid flat black fills, one thin clean black outline, no "
    "gradients, no shading, no texture, no extra colours - only black ink on the same plain grey "
    "background. Keep the same pose, proportions and presence: the character stays seated "
    "cross-legged in the centre of the frame at the same size, same head-to-body ratio, same "
    "sleeve, trouser and sneaker shapes. Do not show a face, do not turn the head towards the "
    "viewer, do not add colour, patterns, props, text, watermark or background objects, and do "
    "not change the clothes."
)


def load_validator():
    spec = importlib.util.spec_from_file_location("mf_end_08_test", TEST_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mf_end_08_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def build_graph() -> dict:
    return {
        # reference intake: LoadImage -> size -> neutral bg -> alpha composite (ONCE) -> resize
        "REF_LOAD": {"class_type": "LoadImage", "inputs": {"image": REF_IMAGE},
                     "_meta": {"title": "REF: identity reference (RGBA composited on neutral)"}},
        "REF_SIZE": {"class_type": "GetImageSize", "inputs": {"image": ["REF_LOAD", 0]},
                     "_meta": {"title": "REF: source size"}},
        "REF_BG": {"class_type": "EmptyImage",
                   "inputs": {"width": ["REF_SIZE", 0], "height": ["REF_SIZE", 1],
                              "batch_size": 1, "color": NEUTRAL_INT},
                   "_meta": {"title": "REF: declared neutral background 0x808080"}},
        "REF_INVERT": {"class_type": "InvertMask", "inputs": {"mask": ["REF_LOAD", 1]},
                       "_meta": {"title": "REF: LoadImage MASK is 1-alpha; invert to alpha"}},
        "REF_COMP": {"class_type": "ImageCompositeMasked",
                     "inputs": {"destination": ["REF_BG", 0], "source": ["REF_LOAD", 0],
                                "x": 0, "y": 0, "resize_source": False,
                                "mask": ["REF_INVERT", 0]},
                     "_meta": {"title": "REF: composite ONCE (graph-side alpha policy)"}},
        "REF_RESIZE": {"class_type": "ResizeImageMaskNode",
                       "inputs": {"input": ["REF_COMP", 0],
                                  "resize_type": "scale longer dimension",
                                  "resize_type.longer_size": REF_LONGER,
                                  "scale_method": "area"},
                       "_meta": {"title": "REF: aspect-preserving resize, no crop"}},
        "REF_LATENT": {"class_type": "VAEEncode",
                       "inputs": {"pixels": ["REF_RESIZE", 0], "vae": ["VAE", 0]},
                       "_meta": {"title": "REF: encode"}},
        # conditioning: positive prompt + zeroed negative, each carrying the reference latent
        "PROMPT": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["CLIP", 0]},
                   "_meta": {"title": "view/identity requirement (prompt)"}},
        "NEG_ZERO": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["PROMPT", 0]},
                     "_meta": {"title": "distilled template: zeroed negative"}},
        "POS_REF": {"class_type": "ReferenceLatent",
                    "inputs": {"conditioning": ["PROMPT", 0], "latent": ["REF_LATENT", 0]},
                    "_meta": {"title": "positive + reference latent"}},
        "NEG_REF": {"class_type": "ReferenceLatent",
                    "inputs": {"conditioning": ["NEG_ZERO", 0], "latent": ["REF_LATENT", 0]},
                    "_meta": {"title": "negative + reference latent"}},
        # model set (DISTILLED — base 4B files are not installed on the pinned runtime)
        "UNET": {"class_type": "UNETLoader",
                 "inputs": {"unet_name": "flux-2-klein-4b-fp8.safetensors",
                            "weight_dtype": "default"}, "_meta": {"title": "FLUX.2 klein 4B fp8"}},
        "CLIP": {"class_type": "CLIPLoader",
                 "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "flux2",
                            "device": "default"}, "_meta": {"title": "Qwen3-4B text encoder"}},
        "VAE": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"},
                "_meta": {"title": "FLUX.2 VAE"}},
        # sampling (distilled profile: 4 steps, cfg 1, euler, Flux2Scheduler)
        "LATENT": {"class_type": "EmptyFlux2LatentImage",
                   "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
                   "_meta": {"title": "canvas (declared, /16)"}},
        "SIGMAS": {"class_type": "Flux2Scheduler",
                   "inputs": {"steps": 4, "width": 1024, "height": 1024},
                   "_meta": {"title": "Flux2Scheduler (distilled 4 steps)"}},
        "SAMPLER": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"},
                    "_meta": {"title": "euler"}},
        "NOISE": {"class_type": "RandomNoise", "inputs": {"noise_seed": SEED},
                  "_meta": {"title": "declared seed"}},
        "GUIDER": {"class_type": "CFGGuider",
                   "inputs": {"cfg": 1, "model": ["UNET", 0], "positive": ["POS_REF", 0],
                              "negative": ["NEG_REF", 0]}, "_meta": {"title": "cfg 1 (distilled)"}},
        "SAMPLE": {"class_type": "SamplerCustomAdvanced",
                   "inputs": {"noise": ["NOISE", 0], "guider": ["GUIDER", 0],
                              "sampler": ["SAMPLER", 0], "sigmas": ["SIGMAS", 0],
                              "latent_image": ["LATENT", 0]}, "_meta": {"title": "sample"}},
        "DECODE": {"class_type": "VAEDecode", "inputs": {"samples": ["SAMPLE", 0], "vae": ["VAE", 0]},
                   "_meta": {"title": "decode"}},
        "SAVE": {"class_type": "SaveImage", "inputs": {"filename_prefix": PREFIX,
                                                       "images": ["DECODE", 0]},
                 "_meta": {"title": "save artwork (opaque RGB PNG)"}},
    }


def doc_payload(graph: dict, hashes: dict, staged: dict) -> dict:
    tmpl = {t["file"]: t for t in hashes["templates"]}
    dt = tmpl["image_flux2_klein_image_edit_4b_distilled.json"]
    bt = tmpl["image_flux2_klein_image_edit_4b_base.json"]
    params = [
        {"name": "ref_image", "pointer": "graph/REF_LOAD/inputs/image",
         "type": "string (file that must exist in the isolated server input dir)",
         "rule": "non-empty PNG filename resolved against the server input dir",
         "golden": REF_IMAGE,
         "description": "identity reference: the character artwork, RGBA composited ONCE on neutral"},
        {"name": "prompt", "pointer": "graph/PROMPT/inputs/text",
         "type": "string", "rule": "must state the target view AND the identity/style keepers",
         "golden": PROMPT, "description": "view/identity requirement text"},
        {"name": "seed", "pointer": "graph/NOISE/inputs/noise_seed", "type": "int",
         "rule": "0 <= seed < 2**63", "golden": SEED, "description": "declared sampling seed"},
        {"name": "canvas_width", "pointer": "graph/LATENT/inputs/width", "type": "int",
         "rule": "16..16384, divisible by 16 (EmptyFlux2LatentImage step)",
         "mirrors": ["graph/SIGMAS/inputs/width"], "golden": 1024,
         "description": "declared canvas width (NOT derived from the reference)"},
        {"name": "canvas_height", "pointer": "graph/LATENT/inputs/height", "type": "int",
         "rule": "16..16384, divisible by 16", "mirrors": ["graph/SIGMAS/inputs/height"],
         "golden": 1024, "description": "declared canvas height"},
        {"name": "ref_longer_side", "pointer": "graph/REF_RESIZE/inputs/resize_type.longer_size",
         "type": "int", "rule": "16..4096, python round() (half-to-even) as in the node",
         "golden": REF_LONGER, "description": "reference resize: longer side px, aspect preserved"},
        {"name": "neutral_rgb_int", "pointer": "graph/REF_BG/inputs/color", "type": "int",
         "rule": "0..0xFFFFFF as 0xRRGGBB", "golden": NEUTRAL_INT,
         "description": "declared neutral background for the alpha composite"},
        {"name": "steps", "pointer": "graph/SIGMAS/inputs/steps", "type": "int",
         "rule": "distilled profile: 4 (a base profile of 20 steps is NOT this graph)",
         "golden": 4, "description": "sampling steps"},
        {"name": "cfg", "pointer": "graph/GUIDER/inputs/cfg", "type": "number",
         "rule": "distilled profile: 1", "golden": 1, "description": "CFG scale"},
        {"name": "filename_prefix", "pointer": "graph/SAVE/inputs/filename_prefix", "type": "string",
         "rule": "run-scoped prefix; outputs land under <output>/<prefix>_00001_.png",
         "golden": PREFIX, "description": "output prefix"},
    ]
    return {
        "schema_version": "mf.reference_asset.graph.v1",
        "graph_id": "reference_asset_v1",
        "purpose": ("Create ONE character artwork view that is missing from the cast library, from "
                    "an existing authored reference of the SAME character, with the identity/style/"
                    "view requirement pinned by the prompt and the reference latent."),
        "derived_from": {
            "template_id": "image_flux2_klein_image_edit_4b_distilled",
            "template_package": dt["package"],
            "template_path": dt["path"],
            "template_sha256": dt["sha256"],
            "template_sha16": dt["sha256"][:16],
            "base_template_reference_only": {
                "template_id": "image_flux2_klein_image_edit_4b_base",
                "template_path": bt["path"], "template_sha256": bt["sha256"],
                "why_reference_only": ("the base 4B checkpoint and its VAE are NOT installed on the "
                                       "pinned runtime; the base profile (20 steps, cfg 5, "
                                       "full_encoder_small_decoder) is therefore not runnable here")},
            "conversion": ("official UI template -> flat API prompt: the two inline 'Image Edit "
                           "(Flux.2 Klein 4B Distilled)' subgraph instances and the 'Reference "
                           "Conditioning' sub-graph are inlined (their nodes are plain registered "
                           "nodes; no subgraph ids are sent to the API)"),
        },
        "distilled_vs_base": {
            "installed_variant": "distilled",
            "installed_artifacts": {
                "unet": "diffusion_models/flux-2-klein-4b-fp8.safetensors",
                "text_encoder": "text_encoders/qwen_3_4b.safetensors",
                "vae": "vae/flux2-vae.safetensors"},
            "base_artifacts_installed": False,
            "evidence": [
                "P0_MODEL_INVENTORY.json groups: diffusion_models has 4 files; no *base-4b* file",
                "official distilled template links flux-2-klein-4b-fp8.safetensors",
                "official base template links flux-2-klein-base-4b-fp8.safetensors + "
                "full_encoder_small_decoder.safetensors (absent)",
                "both official templates are hashed in the manifest (base kept as reference only)"],
            "profile_delta": {"steps": {"distilled": 4, "base": 20},
                              "cfg": {"distilled": 1, "base": 5},
                              "vae": {"distilled": "flux2-vae.safetensors",
                                      "base": "full_encoder_small_decoder.safetensors"}},
            "rule": ("a graph naming the base checkpoint, the base VAE, or the base 20-step/cfg-5 "
                     "profile is a DIFFERENT graph and must be refused (negative fixtures)"),
        },
        "parameters": params,
        "alpha_policy": {
            "neutral_rgb": [128, 128, 128],
            "emptyimage_color_int": NEUTRAL_INT,
            "composite_applied_in_graph": True,
            "composite_times": 1,
            "formula": "out = rgb*(alpha/255) + neutral*(1 - alpha/255)",
            "nodes": {"background": "REF_BG:EmptyImage", "invert": "REF_INVERT:InvertMask",
                      "composite": "REF_COMP:ImageCompositeMasked"},
            "mask_convention": ("measured in the pinned runtime: nodes.py LoadImage returns MASK = "
                                "1 - alpha; comfy_extras/nodes_mask.py ImageCompositeMasked weights "
                                "the SOURCE with `mask`; so the mask must be inverted first"),
            "why": ("raw RGB of an RGBA cutout is ~99% near-black (measured: dan_choi reference is "
                    "84.5% fully transparent); the accepted proof composites ONCE onto this neutral "
                    "grey before any resize - this graph enforces that recipe itself"),
            "output": {
                "channel_count": 3, "alpha_synthesized": False, "format": "PNG (opaque RGB)",
                "owner_of_background_removal": ("library ingest job (MF-END-03 upload / MF-END-09 "
                                                "asset job) - NOT this graph"),
                "reason": ("no segmentation/background-removal weights are provisioned on the "
                           "pinned runtime (P0: sam3/sam2/checkpoints groups missing); faking an "
                           "alpha channel from a colour key would silently punch holes in the "
                           "artwork, so the graph declares an opaque output instead")},
        },
        "dimensions_policy": {
            "canvas_wh": [1024, 1024],
            "canvas_source": "declared constants in the graph (parameters canvas_width/height)",
            "divisible_by": 16,
            "reference_resize": {"node": "REF_RESIZE:ResizeImageMaskNode",
                                 "resize_type": "scale longer dimension",
                                 "longer_size": REF_LONGER, "scale_method": "area",
                                 "node_formula": ("comfy_extras/nodes_post_processing.py "
                                                  "scale_longer_dimension - python round() "
                                                  "(half-to-even)"),
                                 "rounding_convention": "python round, identical to the node"},
            "crop_applied": False, "stretch_applied": False,
            "output_dims": "equal to canvas_wh (verified against the real run receipt)",
        },
        "graph": graph,
        "golden_request": {
            "character_id": "dan_choi",
            "missing_view": "back",
            "why_this_asset": ("the library's dan_choi_back.png is byte-identical to the other "
                               "five view files (single authored artwork, sha "
                               "271f1c5789ee8f...), so a back view does not exist; the accepted "
                               "proof also renders BOOK-P3 (seen from behind)"),
            "source_artwork_sha256": staged["source_artwork"]["sha256"],
            "staged_inputs": [{
                "role": "identity reference (image1)", "file": staged["staged_input"]["file"],
                "sha256": staged["staged_input"]["sha256"], "bytes": staged["staged_input"]["bytes"],
                "dims": staged["staged_input"]["dims"], "mode": "RGBA",
                "recipe": ("raw authored artwork staged as-is (byte copy); the GRAPH composites "
                           "its alpha ONCE on neutral 0x808080 before any resize"),
                "byte_identical_to_proof_reference": (
                    "this sha256 IS the accepted proof's BOOK-P2 cast reference artwork "
                    "(shot_reskin FROZEN_EXAMPLES _FROZEN_REF_SHA)"),
            }],
            "bindings": {p["name"]: {"pointer": p["pointer"], "value": p["golden"]} for p in params},
            "expected_output": {"dims": [1024, 1024], "channel_count": 3,
                                "note": "filled by the real run in the manifest golden_run block"},
        },
        "output_contract": {"node": "SAVE:SaveImage", "files": 1,
                            "dims": "canvas_wh", "alpha": "opaque RGB",
                            "naming": "<filename_prefix>_00001_.png under the run output dir"},
    }


def main() -> int:
    t = load_validator()
    hashes = json.loads((EV / "raw/model_and_node_hashes.json").read_text(encoding="utf-8"))
    staged = json.loads((EV / "raw/stage_input.json").read_text(encoding="utf-8"))
    graph = build_graph()
    doc = doc_payload(graph, hashes, staged)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    oi = json.loads(OI.read_text(encoding="utf-8"))
    rep = t.validate_graph(doc["graph"], oi, ("SAVE",))
    # Row 2: the LoadImage `image` enum of THIS dump predates the staging of our reference
    # (that dump was taken on the proof server's own input dir).  Extend ONLY that enum with the
    # staged name so the graph's own wiring is validated; the LIVE row is produced at run time
    # against the isolated server whose input dir really contains the staged file.
    import copy as _copy
    oi2 = _copy.deepcopy(oi)
    decl = oi2["LoadImage"]["input"]["required"]["image"][0]
    oi2["LoadImage"]["input"]["required"]["image"][0] = list(decl) + [REF_IMAGE]
    staged_rep = t.validate_graph(doc["graph"], oi2, ("SAVE",))
    rec = {"artifact": "build_record.json", "graph_file": str(OUT_JSON).replace("\\", "/"),
           "graph_file_sha256": hashlib.sha256(OUT_JSON.read_bytes()).hexdigest(),
           "graph_object_sha256": hashlib.sha256(json.dumps(
               doc["graph"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
           ).encode("utf-8")).hexdigest(),
           "object_info": str(OI).replace("\\", "/"),
           "validation": rep,
           "validation_raw_live_enum_rows": [e for e in rep["errors"] if "LoadImage" in e],
           "validation_enum_extended_with_staged_name": {
               "staged_name": REF_IMAGE, "errors": staged_rep["errors"],
               "warnings": staged_rep["warnings"], "enum_checked": staged_rep["enum_checked"],
               "inputs_checked": staged_rep["inputs_checked"], "nodes": staged_rep["nodes"],
               "unreachable": staged_rep["unreachable"]},
           "node_count": len(doc["graph"])}
    (EV / "raw/build_record.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                                              encoding="utf-8")
    print(json.dumps(rec, indent=1, ensure_ascii=False))
    hard = [e for e in rep["errors"] if "LoadImage" not in e]
    return 0 if not hard and not staged_rep["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
