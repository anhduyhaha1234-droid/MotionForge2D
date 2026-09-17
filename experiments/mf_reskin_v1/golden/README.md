# MF-V1-GOLDEN — golden fixture + gate/reference material (in-repo)

Task: **MF-V1-GOLDEN** (MF-RESKIN-V1 wave 1) · branch `codex/mf-reskin-v1-golden`
Base SHA: `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`
Worker session: `20260917_180945_1e9357` (this round is a continuation of that session)

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
| `references/references_<TAG>.json` | per-window aligned keyframe list + per-role reference cutouts with provenance |
| `annotations/annotation_<TAG>.json` | per-anchor masks, legend, contacts, exceptions (frozen) |
| `annotations/relations_<TAG>.json` | measured role relations / nesting (mask_count ≠ role_count) |
| `keyframes/<TAG>/` | 56 aligned source keyframes, decoded by frame number from the locked film |
| `roles/<TAG>/` | 88 RGBA role reference cutouts (one per role in each window's role list) |
| `ledger/commands.jsonl` | command ledger: argv, cwd, start/end, exit code, duration, raw output path |
| `guards/` | byte-safe write-set guard baseline + verify records |
| `cutout_bounds_audit.json` | measured audit of the delivered role cutouts (crop vs mask tight bbox, alpha integrity) |
| `image_engine_probe.json` | measured proof that no image/generative engine is callable from this task's runtime |

## Freeze

`freeze_hash_sha256` = `2c558ce19e0a9d915d860dc07843bd1412ac4a7801284cca5293ea21cbfba684`
(canonical JSON: `sort_keys=True, separators=(',',':'), ensure_ascii=False`, with
the `freeze` key removed). The fixture was frozen **before** any candidate render.
Nothing in a candidate may redefine the fixture's expected values.

## Status of this directory

- Golden/tracking inputs: **complete** (source lock, window set, annotations,
  aligned keyframes, per-role references, style contract, freeze).
- New-identity reskin artwork: **NOT produced** — recorded as an exact unmet
  dependency in `KEYFRAME_SPEC.md` (no callable image/generative engine in this
  task's runtime). A palette-only/histogram-only artifact is not offered as a reskin.
- Carried truthful negatives (unchanged from round 1): hands not separately
  resolvable at 640x360; structural-only role labels (no vision route);
  between-anchor frames not interpolated; occlusion class
  `PARTIAL — NOT_DEMONSTRATED`; z-order `unresolved`; `mask_count != role_count`;
  delivered role cutouts are cropped by the annotation's declared bbox
  (0.433% of mask pixels fall outside that crop — measured in
  `cutout_bounds_audit.json`).
