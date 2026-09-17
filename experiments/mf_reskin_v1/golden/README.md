# MF-V1-GOLDEN — golden fixture + gate/reference material (in-repo)

Task: **MF-V1-GOLDEN** (MF-RESKIN-V1 wave 1) · branch `codex/mf-reskin-v1-golden`
Base SHA: `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`
Worker session: `20260917_184835_1e70db` (continuation 02 / round 3 — cutout-crop fix)

This directory is this task's **only** in-repo write set
(`experiments/mf_reskin_v1/golden/**`). It holds the frozen benchmark fixture and
the gate/reference material a candidate must be judged against. Full evidence
(ledger raw output, tool sources, every hash) lives in the task evidence root:

```
C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\mf-reskin-v1\20260917T110554Z\GOLDEN
```

## Read this first

| File | What it is |
|---|---|
| `GOLDEN_FIXTURE.json` | the frozen fixture (source lock, window set, annotations, role inventory, style contract, gaps, assertions, freeze) |
| `KEYFRAME_SPEC.md` | keyframe-artwork spec **plus the exact unmet dependency** for producing artwork (G-A8 outcome b) |
| `REPORT.md` | what was run, real numbers, failures and open gaps |
| `MATRIX.md` | finite matrix: every row tied to an exact command and artifact |
| `NEXT_REVIEW_PACKET.md` | verdict + open gaps for the Manager |
| `HASH_TABLE` | in `…\GOLDEN\HASH_TABLE.json` / `.md` — SHA-256 + size for every input and output |
| `references/references_<TAG>.json` | per-window aligned keyframe list + per-role reference cutouts with provenance (incl. the mask index used and the crop window applied) |
| `annotations/annotation_<TAG>.json` | per-anchor masks, legend, contacts, exceptions (frozen) |
| `annotations/relations_<TAG>.json` | measured role relations / nesting (mask_count ≠ role_count) |
| `keyframes/<TAG>/` | 56 aligned source keyframes, decoded by frame number from the locked film (byte-identical across rounds 1–3) |
| `roles/<TAG>/` | 88 RGBA role reference cutouts, cropped to each mask's **tight bounding box** (round 3) |
| `ledger/commands.jsonl` | command ledger: argv, cwd, start/end, exit code, duration, raw output path |
| `guards/` | byte-safe write-set guard baseline + verify + classification records |
| `cutout_bounds_audit.json` | measured audit of the delivered role cutouts (crop vs mask tight bbox, element-wise alpha, index provenance) |
| `image_engine_probe.json` | measured proof that no image/generative engine is callable from this task's runtime |

## Freeze

`freeze_hash_sha256` = `2c558ce19e0a9d915d860dc07843bd1412ac4a7801284cca5293ea21cbfba684`
(canonical JSON: `sort_keys=True, separators=(',',':'), ensure_ascii=False`, with
the `freeze` key removed). The fixture was frozen **before** any candidate render.
Nothing in a candidate may redefine the fixture's expected values. Re-derived from
the file in round 3 and byte-identical: fixture file sha
`7e1627e4c8c2421e77758b48f0c003c23d0b8b2f50fc73bc2118bc6b06cd0dab`,
`KEYFRAME_SPEC.md` sha `4ed5b7bfec887c121b7a361c0d819302b8f991cd12efd4627ce483beafc940f4`,
protected annotation tree (126 files) aggregate
`fdd4345f6d62660ae18e1c774d5e6caaa983898c0c1bda5c2137c4f93852844b`.

## Reference geometry — read `crop_bbox_xywh`, not `bbox_xywh`

Each entry in `references_<TAG>.json` → `role_references[]` carries:

* `crop_basis: "mask_tight_bbox"`, `crop_bbox_xywh` / `crop_origin_xy` /
  `crop_size_wh` — the window the delivered PNG was actually taken from;
* `bbox_xywh` = `annotation_declared_bbox_xywh` — the annotation's own value,
  recorded verbatim, **not** the crop window;
* `mask_index` plus `role_index_candidates` / `role_index_candidate_areas_px` /
  `role_index_ambiguous_at_anchor` — which mask index the cutout came from, and
  whether that `role_id` is split across masks at that anchor;
* `provenance.source_film_sha256` and `derived_from_mask_artifact`.

The annotation's declared bbox is measurably wrong and is **frozen**: 9,058 of
2,089,631 mask pixels (0.433474 %) fall outside it, 6 of 88 declared bboxes
overshoot an axis, 82 of 88 are 1 px short on both. The delivered cutouts no longer
inherit that defect — round 3 measured **88/88 `EXACT`, 0 mask px outside the
applied crop** — but anything reconstructing reference geometry must use
`crop_bbox_xywh`.

## Status of this directory

- Golden/tracking inputs: **complete** (source lock, window set, annotations,
  aligned keyframes, per-role references, style contract, freeze) and re-asserted
  byte-identical in round 3.
- Reference cutouts: **tight-bbox correct** (`88/88 EXACT`, `0` mask px outside the
  crop), with the mask index recorded per reference (88/88) and the 10/88
  role-split ambiguity still reported.
- New-identity reskin artwork: **NOT produced** — recorded as an exact unmet
  dependency in `KEYFRAME_SPEC.md` (no callable image/generative engine in this
  task's runtime). A palette-only/histogram-only artifact is not offered as a reskin.
- Carried truthful negatives (unchanged): hands not separately resolvable at
  640×360; structural-only role labels (no vision route); between-anchor frames not
  interpolated; occlusion class `PARTIAL — NOT_DEMONSTRATED`; z-order `unresolved`;
  `mask_count != role_count`; the annotation's declared-bbox defect above.
