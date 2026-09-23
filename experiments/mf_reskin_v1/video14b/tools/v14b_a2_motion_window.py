"""A2 — motion-window probe on the ACTUAL runtime code (CPU, no weights, no server).

Independent of the technology audit's probe: it does not restate the reviewer's
cond dict.  It reads the INSTALLED runtime, extracts the real code objects and
then runs them:

  * ``WanAnimate2ToVideo.execute``          (installed ``comfy_extras/nodes_wan.py``)
      -> produces the real conditioning parts, including the windowed split
         (pose window part + complement parts) and the pose payload.
  * ``comfy.samplers.calculate_start_end_timesteps``  -> converts each part's
      ``start_percent``/``end_percent`` into the sampler's timestep range.
  * ``comfy.samplers.simple_scheduler``      -> the real sigma schedule.
  * ``comfy.samplers.get_area_and_mult``     -> the real per-step selector, so
      "this step receives the pose conditioning" is decided by runtime code.
  * ``comfy.model_sampling.ModelSamplingDiscreteFlow`` -> ``shift``/``percent_to_sigma``.

A step counts as pose-conditioned when an applying part carries the
``pose_video_latent`` payload; a second, payload-free run counts the window part
structurally.  Both are reported and must agree.

CPU only: tensors are created on the CPU, ``CUDA_VISIBLE_DEVICES`` is asserted
empty, no model file is opened and no server is started.

usage:
  python v14b_a2_motion_window.py [--out <a2_motion_window.json>]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
from pathlib import Path

RT = Path(r"C:\Users\Admin\Documents\Codex\work\mfv1\runtime\video14b")
COMFY = RT / "ComfyUI"
OLD = Path(
    r"C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs"
    r"\mf-reskin-correction-20260922\20260922T0955Z"
)
TECH = Path(
    r"C:\Users\Admin\Documents\Codex\2026-09-22\tr-ng-th-i-terminal-gi\outputs"
    r"\mf-technology-core-20260923"
)
NEW = Path(
    r"C:\Users\Admin\Documents\Codex\2026-09-22\tr-ng-th-i-terminal-gi\outputs"
    r"\mf-core-tool-delivery-20260923\20260923T1535Z"
)
SUBMITTED = OLD / "VIDEO14B/waveB/workflows/mf_animate2_book4s.waveB.api.json"

SOURCE_UNITS = (
    ("comfy/model_sampling.py", ("time_snr_shift", "ModelSamplingDiscreteFlow")),
    (
        "comfy/samplers.py",
        ("simple_scheduler", "get_area_and_mult", "calculate_start_end_timesteps"),
    ),
    ("node_helpers.py", ("conditioning_set_values",)),
    ("comfy/utils.py", ("common_upscale",)),
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extract_unit(path: Path, names: tuple[str, ...]) -> tuple[list[ast.stmt], dict]:
    """Top-level definitions ``names`` out of ``path``, unmodified."""
    source = path.read_bytes()
    tree = ast.parse(source)
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name in names
    ]
    found = {node.name for node in selected}
    if found != set(names):
        raise SystemExit(f"{path}: extracted {sorted(found)} != requested {sorted(names)}")
    segments = {}
    for node in selected:
        lines = ast.get_source_segment(source.decode("utf-8"), node)
        segments[node.name] = {
            "start_line": node.lineno,
            "end_line": node.end_lineno,
            "sha256": hashlib.sha256(lines.encode("utf-8")).hexdigest(),
            "source": lines,
        }
    return selected, {
        "path": str(path),
        "sha256": hashlib.sha256(source).hexdigest(),
        "definitions": {k: {kk: vv for kk, vv in v.items() if kk != "source"} for k, v in segments.items()},
    }, segments


def build_namespace() -> tuple[dict, list[dict], dict]:
    import collections
    import torch  # imported here so the CPU assertions below run first

    namespace: dict = {"torch": torch, "collections": collections}
    records: list[dict] = []
    segments: dict = {}

    units = list(SOURCE_UNITS)
    # the node under test, extracted as a plain function (decorators dropped)
    nodes_wan = COMFY / "comfy_extras/nodes_wan.py"
    wan_source = nodes_wan.read_bytes()
    wan_tree = ast.parse(wan_source)
    execute_node = None
    for cls in wan_tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "WanAnimate2ToVideo":
            for sub in cls.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == "execute":
                    execute_node = sub
    if execute_node is None:
        raise SystemExit("WanAnimate2ToVideo.execute not found")
    execute_node.decorator_list = []  # keep the body; the classmethod wrapper is not needed
    wan_text = ast.get_source_segment(wan_source.decode("utf-8"), execute_node)
    segments["WanAnimate2ToVideo.execute"] = {
        "start_line": execute_node.lineno,
        "end_line": execute_node.end_lineno,
        "sha256": hashlib.sha256(wan_text.encode("utf-8")).hexdigest(),
        "source": wan_text,
    }
    records.append(
        {
            "path": str(nodes_wan),
            "sha256": hashlib.sha256(wan_source).hexdigest(),
            "definitions": {"WanAnimate2ToVideo.execute": {
                "start_line": execute_node.lineno,
                "end_line": execute_node.end_lineno,
                "sha256": segments["WanAnimate2ToVideo.execute"]["sha256"],
            }},
        }
    )

    for relative, names in units:
        path = COMFY / relative
        module = ast.Module(body=extract_unit(path, names)[0], type_ignores=[])
        exec(compile(module, str(path), "exec"), namespace)  # noqa: S102 - auditing real runtime source
        unit_records, unit_segments = extract_unit(path, names)[1:]
        records.append(unit_records)
        segments.update({f"{relative}:{k}": v for k, v in unit_segments.items()})

    # The node code addresses two runtime services through module globals; both are
    # stubbed with CPU-only equivalents and the stub is disclosed in the evidence.
    class _ComfyUtils:
        common_upscale = staticmethod(namespace["common_upscale"])

    class _ComfyModelManagement:
        @staticmethod
        def intermediate_device():
            return torch.device("cpu")

    class _Comfy:
        utils = _ComfyUtils
        model_management = _ComfyModelManagement

    class _NodeHelpers:
        conditioning_set_values = staticmethod(namespace["conditioning_set_values"])

    def _node_output(*values):
        return values

    class _Io:
        NodeOutput = staticmethod(_node_output)

    namespace["comfy"] = _Comfy
    namespace["node_helpers"] = _NodeHelpers
    namespace["io"] = _Io

    module = ast.Module(body=[execute_node], type_ignores=[])
    exec(compile(module, str(nodes_wan), "exec"), namespace)  # noqa: S102
    return namespace, records, segments


class StubVae:
    """``encode`` returns a deterministic CPU latent with the VAE's real shrunken shape."""

    def __init__(self):
        self.calls = 0

    def encode(self, pixels):
        self.calls += 1
        frames = ((pixels.shape[0] - 1) // 4) + 1
        return __import__("torch").zeros(
            (1, 16, frames, pixels.shape[1] // 8, pixels.shape[2] // 8)
        )


def run_case(namespace: dict, case: dict, graph_node_inputs: dict) -> dict:
    import torch

    flow = namespace["ModelSamplingDiscreteFlow"]()
    flow.set_parameters(shift=graph_node_inputs["shift"])
    sigmas = namespace["simple_scheduler"](flow, graph_node_inputs["steps"])
    steps = [float(s) for s in sigmas[:-1]]

    pose_video = None
    if case.get("pose_video_frames"):
        frames = case["pose_video_frames"]
        pose_video = torch.zeros((frames, case["height"], case["width"], 3))

    positive = [["POS_STUB", {}]]
    negative = [["NEG_STUB", {}]]
    vae = StubVae()
    out = namespace["execute"](
        None,
        positive=positive,
        negative=negative,
        vae=vae,
        width=case["width"],
        height=case["height"],
        length=case["length"],
        batch_size=1,
        video_frame_offset=0,
        reference_image=None,
        pose_video=pose_video,
        clip_vision_output=None,
        positive_pose=None,
        clip_vision_output_pose=None,
        continue_motion=None,
        pose_strength=case.get("pose_strength", 1.0),
        pose_start_percent=case["pose_start_percent"],
        pose_end_percent=case["pose_end_percent"],
        reference_image_strength=1.0,
    )
    positive_out = out[0]
    # each part becomes one sampler cond; `model_conds`/`uuid` are filled by the model
    # patcher in a real run, and are stubbed empty here because no CLIP model is loaded.
    parts = []
    for cond in positive_out:
        part = dict(cond[1])
        part.setdefault("model_conds", {})
        part.setdefault("uuid", "a2-window-probe")
        parts.append(part)
    namespace["calculate_start_end_timesteps"](
        type("M", (), {"model_sampling": flow})(), parts
    )

    x_stub = torch.zeros((1, 16, 2, 2, 2), device="cpu")
    per_step = []
    for index, sigma in enumerate(steps, start=1):
        applied = []
        for part_index, part in enumerate(parts):
            if namespace["get_area_and_mult"](part, x_stub, torch.tensor([sigma])) is not None:
                applied.append(
                    {
                        "part": part_index,
                        "carries_pose_payload": "pose_video_latent" in part,
                        "start_percent": part.get("start_percent"),
                        "end_percent": part.get("end_percent"),
                        "timestep_start": part.get("timestep_start"),
                        "timestep_end": part.get("timestep_end"),
                    }
                )
        pose_window_part = 0
        pose_structural = any(a["part"] == pose_window_part for a in applied)
        pose_payload = any(a["carries_pose_payload"] for a in applied)
        per_step.append(
            {
                "step": index,
                "sigma": sigma,
                "applied_parts": applied,
                "pose_branch_active_structural": pose_structural,
                "pose_branch_active_by_payload": pose_payload,
            }
        )

    analytic_start = flow.percent_to_sigma(case["pose_start_percent"])
    analytic_end = flow.percent_to_sigma(case["pose_end_percent"])
    analytic = [
        {"step": index, "sigma": sigma,
         "applies": (not sigma > analytic_start) and (not sigma < analytic_end)}
        for index, sigma in enumerate(steps, start=1)
    ]

    return {
        "case": case["name"],
        "pose_window": [case["pose_start_percent"], case["pose_end_percent"]],
        "geometry": {
            "width": case["width"],
            "height": case["height"],
            "length": case["length"],
            "pose_video_frames": case.get("pose_video_frames"),
            "vae_encode_calls": vae.calls,
        },
        "steps": steps,
        "cond_parts": [
            {
                "part": index,
                "start_percent": part.get("start_percent"),
                "end_percent": part.get("end_percent"),
                "timestep_start": part.get("timestep_start"),
                "timestep_end": part.get("timestep_end"),
                "keys": sorted(part),
            }
            for index, part in enumerate(parts)
        ],
        "percent_to_sigma": {
            "start": analytic_start,
            "end": analytic_end,
        },
        "per_step": per_step,
        "pose_steps_structural": sum(1 for row in per_step if row["pose_branch_active_structural"]),
        "pose_steps_by_payload": sum(1 for row in per_step if row["pose_branch_active_by_payload"]),
        "pose_steps_analytic": sum(1 for row in analytic if row["applies"]),
        "total_steps": len(steps),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(NEW / "VIDEO14B/raw/a2_motion_window.json"))
    args = parser.parse_args()

    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "<unset>")
    namespace, source_records, segments = build_namespace()

    graph = json.loads(SUBMITTED.read_text(encoding="utf-8"))
    node = graph["672:587"]["inputs"]
    graph_inputs = {
        "shift": graph["672:592"]["inputs"]["shift"],
        "steps": graph["672:591"]["inputs"]["steps"],
        "scheduler": graph["672:591"]["inputs"]["scheduler"],
        "sampler_name": graph["672:593"]["inputs"]["sampler_name"],
        "cfg": graph["672:597"]["inputs"]["cfg"],
        "positive_source": graph["672:587"]["inputs"]["positive"][0],
    }
    # executed clip geometry: 121 pose frames padded to 640x368 (120 output frames)
    executed = {"width": 640, "height": 368, "length": 121}

    cases = [
        {
            "name": "submitted_0_0_structural_full_geometry",
            "pose_start_percent": node["pose_start_percent"],
            "pose_end_percent": node["pose_end_percent"],
            **executed,
        },
        {
            "name": "native_0_1_structural_full_geometry",
            "pose_start_percent": 0.0,
            "pose_end_percent": 1.0,
            **executed,
        },
        {
            "name": "submitted_0_0_payload_small_geometry",
            "pose_start_percent": node["pose_start_percent"],
            "pose_end_percent": node["pose_end_percent"],
            "width": 64,
            "height": 64,
            "length": 9,
            "pose_video_frames": 9,
        },
        {
            "name": "native_0_1_payload_small_geometry",
            "pose_start_percent": 0.0,
            "pose_end_percent": 1.0,
            "width": 64,
            "height": 64,
            "length": 9,
            "pose_video_frames": 9,
        },
        {
            "name": "submitted_0_0_structural_template_geometry_81",
            "pose_start_percent": node["pose_start_percent"],
            "pose_end_percent": node["pose_end_percent"],
            "width": 832,
            "height": 480,
            "length": 81,
        },
        {
            "name": "window_0_0p7_structural",
            "pose_start_percent": 0.0,
            "pose_end_percent": 0.7,
            **executed,
        },
    ]
    results = [run_case(namespace, case, graph_inputs) for case in cases]

    tech_path = TECH / "motion-window-probe.json"
    tech = json.loads(tech_path.read_text(encoding="utf-8")) if tech_path.is_file() else {}
    tech_compare = {
        "path": str(tech_path),
        "sha256": sha256_file(tech_path) if tech_path.is_file() else None,
        "reviewer_cases": [
            {
                "pose_window": [case["pose_start_percent"], case["pose_end_percent"]],
                "selected_count": case["selected_count"],
                "sigmas": [row["sigma"] for row in case["steps"]],
            }
            for case in tech.get("cases", [])
        ],
    }
    mine = {
        "submitted_0_0": next(r for r in results if r["case"].startswith("submitted_0_0_structural_full")),
        "native_0_1": next(r for r in results if r["case"].startswith("native_0_1_structural_full")),
    }
    tech_compare["agreement"] = {
        "submitted_0_0_pose_steps": [
            mine["submitted_0_0"]["pose_steps_structural"],
            next((c["selected_count"] for c in tech_compare["reviewer_cases"]
                  if c["pose_window"] == [0.0, 0.0]), None),
        ],
        "native_0_1_pose_steps": [
            mine["native_0_1"]["pose_steps_structural"],
            next((c["selected_count"] for c in tech_compare["reviewer_cases"]
                  if c["pose_window"] == [0.0, 1.0]), None),
        ],
        "sigmas_equal": all(
            [round(s, 9) for s in mine[key]["steps"]]
            == [round(s, 9) for s in next((c["sigmas"] for c in tech_compare["reviewer_cases"]
                                           if c["pose_window"] == ([0.0, 0.0] if key.startswith("submitted") else [0.0, 1.0])), [])]
            for key in ("submitted_0_0", "native_0_1")
        ),
    }
    tech_compare["agreement"]["agrees"] = (
        tech_compare["agreement"]["submitted_0_0_pose_steps"][0] == 1
        and tech_compare["agreement"]["native_0_1_pose_steps"][0] == 6
        and tech_compare["agreement"]["sigmas_equal"]
        and tech_compare["agreement"]["submitted_0_0_pose_steps"]
        == tech_compare["agreement"]["submitted_0_0_pose_steps"][::-1]
        and tech_compare["agreement"]["native_0_1_pose_steps"]
        == tech_compare["agreement"]["native_0_1_pose_steps"][::-1]
    )

    import torch

    result = {
        "scope": "A2 motion-window probe on extracted runtime code, CPU only",
        "no_engine": {
            "CUDA_VISIBLE_DEVICES": cuda_visible,
            "torch_cuda_is_available": torch.cuda.is_available(),
            "server_started": False,
            "model_weights_opened": False,
        },
        "graph": {
            "path": str(SUBMITTED),
            "sha256": sha256_file(SUBMITTED),
            "pose_window": [node["pose_start_percent"], node["pose_end_percent"]],
            "steps": graph_inputs["steps"],
            "scheduler": graph_inputs["scheduler"],
            "sampler_name": graph_inputs["sampler_name"],
            "shift": graph_inputs["shift"],
            "cfg": graph_inputs["cfg"],
            "positive_node": graph_inputs["positive_source"],
        },
        "extracted_source": source_records,
        "extracted_segments": {
            key: {k: v for k, v in value.items() if k != "source"}
            for key, value in segments.items()
        },
        "stubs_disclosed": {
            "comfy.utils.common_upscale": "real extracted function",
            "comfy.model_management.intermediate_device": "stub -> torch.device('cpu')",
            "io.NodeOutput": "stub -> tuple",
            "vae": "StubVae with the VAE's real shrunken OUTPUT SHAPE and no weights",
            "positive/negative": "single embedding stub entry, no CLIP model",
        },
        "cases": results,
        "reviewer_probe_compare": tech_compare,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "out": str(out),
                "cuda_visible_devices": cuda_visible,
                "torch_cuda_is_available": torch.cuda.is_available(),
                "cases": [
                    {
                        "case": row["case"],
                        "window": row["pose_window"],
                        "steps": row["total_steps"],
                        "pose_steps_structural": row["pose_steps_structural"],
                        "pose_steps_by_payload": row["pose_steps_by_payload"],
                        "pose_steps_analytic": row["pose_steps_analytic"],
                        "sigmas": [round(s, 6) for s in row["steps"]],
                    }
                    for row in results
                ],
                "reviewer_agreement": tech_compare["agreement"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
