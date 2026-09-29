# MotionForge pilot-preview-v1

`MF-DEMO-V3-01` is a bounded, preview-only product path for one real source
shot. It is not the six-pose demo, S10 Full Apply, approval, QC, or S12.

## Contract

- `POST /api/v2/pilot-preview/context` resolves a legacy project id or a
  durable project UUID and returns the server-owned source identity, probe
  metadata, chain state, and the legacy-to-durable id bridge. Optional
  `pack_id` and `clean_plate_id` select server-owned versioned inputs and
  return independent compatibility verdicts.
- The source must have been imported and analyzed through the existing public
  `POST /api/projects/{legacy_project_id}/video` then
  `POST /api/projects/{legacy_project_id}/analyze` chain. Pilot submission is
  rejected until that durable chain is completed.
- `POST /api/v2/pilot-preview/jobs` creates the immutable `pilot_preview_v1`
  Job manifest. The HTTP request performs no render work.
- The durable worker resolves the versioned closed/open RGBA state files,
  consumes an approved source-bound full-frame clean plate for the actual
  edit pixels (source reuse/Telea is diagnostic-only), applies the SAM2 +
  source-observed reconstruction and protected masks,
  builds pose/book/layer schedule before pixel composition, composites each
  state using its measured asset-local anchors, restores foreground layers,
  remuxes source audio, and validates both MP4s before publication.
- The demo render is fixed to `[450,570)` (120 frames, 4 seconds at 30fps),
  640x360, H264/yuv420p, with original audio when present.
- The worker publishes only the bounded preview artifacts under its managed
  root, namespaced by the full canonical input identity:
  `pilot-preview/jobs/{input_identity_sha256}/before.mp4`,
  `pilot-preview/jobs/{input_identity_sha256}/after.mp4`, and
  `pilot-preview/jobs/{input_identity_sha256}/evidence.json`.

## Honesty gates

The pinned V3 RGBA asset SHA-256 is retained as an intentional incompatible
negative sample. A compatible render requires a server-resolved pack whose
manifest, state-file hashes, genuine alpha, camera view, poses, and anchors
all pass, plus an approved clean plate bound to the exact source SHA, window,
camera view, canvas, image hash, and reviewer approval. A missing or changed
input fails closed. Completion requires decodable media,
the expected frame count and dimensions, and audio presence in both outputs
when the source carries audio. No completion state is emitted for a staged,
missing, or hash-mismatched output.

The UI distinguishes render-completed, automated-QC-passed,
needs-visual-review, and not-approved. This contract does not assert
approval. Review remains an explicit next step.
