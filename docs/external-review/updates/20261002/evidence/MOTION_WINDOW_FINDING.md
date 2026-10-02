# Motion conditioning window: independent static audit

Date: 2026-10-01. Read-only source/graph/template inspection and one pure JSON comparison. No model loading, GPU inference, Comfy server launch, runtime/template edit, or production change. This file is the only write by this reviewer in this audit.

## Finding and precise consequence

**P1 configuration defect: the pinned `wan_shot_v1` API graph sets the driving-video conditioning window to `pose_start_percent=0`, `pose_end_percent=0`.** This is incompatible with treating it as a baseline that applies driving conditioning throughout sampling.

It is **not accurate to say the video driving branch is necessarily disabled on every step**. The current runtime includes schedule boundaries. For the graph's simple six-step / LCM schedule, the zero-width pose condition can still be active at the first sigma=1 evaluation. Its no-pose complement is active there too; later sigma<1 evaluations exclude the pose condition. This is sharply restricted driving conditioning, not a full-window motion-transfer proof.

This establishes a concrete graph issue. It does not establish that every historical demo used this graph, that this issue caused every visual failure, or that end=1 will meet the user's quality goal.

## Exact evidence chain

1. Canonical graph: `C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION/app/media_workflows/wan_shot_v1.json`.
   - Lines 1146–1206: node `672:587`, class `WanAnimate2ToVideo`.
   - Lines 1165–1168: strength 1, start 0, **end 0**, reference strength 1.
   - Lines 1185–1187: driving input is wired through `P3B_PAD`.
   - Lines 1257–1288: `BasicScheduler` simple, six steps, denoise 1; `ModelSamplingSD3` shift 5; sampler LCM.
   - Wrapper SHA-256 from the root's verified snapshot: `c08c64df713b65bb6a244ba13c75dcb5941638cfe6d1ead25d6fca4bbbae630e`.

2. Runtime node: `C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/ComfyUI/comfy_extras/nodes_wan.py`.
   - Lines 1278–1280 and 1295: runtime defaults are strength 1, start 0, **end 1**. The tooltip says the pose branch is skipped outside its window.
   - Lines 1296–1297 reject start greater than end, but permit equality.
   - Lines 1341–1348 encode the actual driving frames into `pose_video_latent`; encoding alone does not prove that denoising will use them at every step.
   - Lines 1361–1371 create a pose condition restricted to `[start,end]` and complementary conditions without pose values. With start=end=0 the two ranges are `[0,0]` with pose and `[0,1]` without pose.
   - Lines 1372–1374 attach pose values directly when the window is the full 0..1 range.
   - SHA-256: `39ff111cc45c8d2a75cab1aa3b97ad9bf9037868178af2468bc52b34dbd0d96d`.

3. Sampler range conversion and boundary handling:
   - `C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/ComfyUI/comfy/samplers.py:859` (`calculate_start_end_timesteps`), specifically lines 871–881, converts percentages to sigma thresholds.
   - `C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/ComfyUI/comfy/model_sampling.py:331`–336 maps Flow percent 0 to sigma 1 and percent 1 to sigma 0.
   - `C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/ComfyUI/comfy_extras/nodes_model_advanced.py:132`–148 shows `ModelSamplingSD3` using `ModelSamplingDiscreteFlow`.
   - `samplers.py:38`–45 skips only when sigma is greater than start or smaller than end. Equality remains eligible. Thus the pose range `[1,1]` survives only at sigma 1.
   - `samplers.py:645`–652 (`simple_scheduler`) begins from the largest sampled sigma. The Flow schedule construction at `model_sampling.py:308`–312 includes timestep 1, so its first sigma is 1.
   - `C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/ComfyUI/comfy/k_diffusion/sampling.py:1097`–1098 shows LCM evaluating the model at each `sigmas[i]`.
   - `samplers.py:341`–354 accumulates every active condition and divides by accumulated weights. At the shared first-step boundary, normal equal-strength/no-area conditions blend pose and no-pose predictions. This is not equivalent to full pose strength on that step.
   - `samplers.py` SHA-256: `2850b400e0c07ddb73429f35e5da3de01952e7ee58f4c050124ea948cbda53ae`.

The first-step conclusion assumes this inspected graph/current runtime path without an unrecorded scheduler or conditioning override. If execution starts below sigma 1, the zero-width pose condition would not run at all. No GPU trace was captured in this audit.

## Installed official-template provenance contains the same effective wiring problem

File: `C:/Users/Admin/Documents/Codex/work/mfv1/runtime/video14b/venv/Lib/site-packages/comfyui_workflow_templates_json/templates/video_wan_animate2.json`.

- SHA-256: `f9907c332e7b2c48e9378797f8952ed90391efd6924a4ff162208d369fb52563`.
- Node 587 local `widgets_values_named` at lines 3510–3513 records strength 1, start 0, **end 1**.
- However, the enclosing subgraph input named `pose_start_percent` at lines 1763–1769 fans out through **both links 1001 and 1002**.
- Links at lines 5665–5678 connect the same external origin slot 6 to node 587 slots 14 (`pose_start_percent`) and 15 (`pose_end_percent`).
- The top-level subgraph widget `pose_start_percent` is 0 at line 437. Its exposed named widgets do not independently provide an end value.

Therefore, the connected input topology drives both start and end from the same exposed zero, overriding the node's stored unconnected end default of 1. The template's displayed/local default must not be mistaken for its effective exported API input.

This is an audit of the installed package file and its copy in the reuse bundle. It is **not** a claim that the latest remote upstream template at every revision has this defect. Reuse remains appropriate after inspecting effective bindings. If an editable UI workflow is delivered, correct the run-local end link/exposure as well; re-exporting the unchanged installed UI template can reintroduce end=0. Do not edit the protected installed template.

## P6 timing provenance is specifically tied to the zero-window recipe

Graph: `C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof/graphs/animate2_book.p6nocache.api.json`.

- Lines 400–401 explicitly contain start 0 and end 0.
- Measured SHA-256: `4247f9e8b233da4b6213c3254b637abd4d2e6c17b307b32cddb9b7b17bbd4759`.
- This exactly matches `graph_sha256` in `C:/Users/Admin/Documents/Codex/work/mf-delivery-runs/20260927/20260927T163824Z/proof/evidence/P6_NOCACHE_RECEIPT.json`.
- Receipt identifies prompt `06302bb4-68d1-4a48-be56-59c14451e100`, server wall 135.21 seconds and peak VRAM 10,763 MiB. Its `quality_accepted` is false.

Those figures remain valid as historical observations of that recorded run. They are **not a measured forecast for end=1/full-window conditioning**. Full-window compute/VRAM and image quality must be measured afresh; the original recipe also had cached upstream nodes. Do not infer a proportional slowdown or a guaranteed improvement without a run. This audit did not compare all prior run graphs or independently verify every byte of the old runtime.

## Static review of root's corrected run-local API copy

Reviewed: `C:/Users/Admin/Documents/Codex/2026-09-22/tr-ng-th-i-terminal-gi/outputs/mf-rebuild-skills-20261001/reuse_bundle/wan_shot_v1.motion_enabled.api.json`.

- SHA-256: `7da45b824d0c0810a5ff318fcf713914fb211a6405985de9e22435a042e448c7`.
- Compared parsed JSON recursively to `wan_shot_v1.baseline.api.json`: both have 63 nodes; exactly one value differs.
- Difference: `/672:587/inputs/pose_end_percent`, 0 → 1.0.
- The hash and delta agree with `reuse_bundle/PROVENANCE.json` as read.

**Static fix PASS:** for the inspected node semantics this enables the full 0..1 driving-conditioning range. The API graph is already expanded, so the defective UI subgraph link does not override this explicit API input. Baseline strength remains 1 and batch size remains 1.

Per-shot source/anchor/prompt/path bindings still must be applied to a fresh copy; this is not a ready-made accepted video. Record resolved end=1 in every submitted prompt and the settings receipt. Preserve the original baseline and production files. Candidate generation, performance measurement and visual review remain within the authorized finite demo loop; no new model download or runtime update is required for this particular fix.
