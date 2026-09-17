# KEYFRAME_SPEC.md — MF-V1-GOLDEN keyframe artwork specification

Status: **SPEC + UNMET DEPENDENCY (G-A8 outcome b)**
Produced by: MF-V1-GOLDEN worker, round 2 (session `20260917_180945_1e9357`)
Fixture this spec belongs to: `GOLDEN_FIXTURE.json`, freeze hash
`2c558ce19e0a9d915d860dc07843bd1412ac4a7801284cca5293ea21cbfba684`
(hash scope: canonical JSON, `sort_keys=True, separators=(',',':')`,
`ensure_ascii=False`, with the `freeze` key removed).

This file is the `keyframes.spec_artifact` referenced by the frozen fixture. It
defines exactly what aligned keyframe artwork must be for this wave, what inputs
already exist, and the **exact unmet dependency** that prevents producing it in
this task's runtime. No artwork is claimed here. No palette-only or
histogram-only artifact is offered as a reskin.

---

## 1. What artwork would have to be

For every window in the frozen fixture (7 windows, 4.0 s each, 120 frames each,
anchor cadence 15 frames, 8 anchors per window) the reskin deliverable must be:

| Item | Exact requirement |
|---|---|
| Source frame set | the exact source frames at the 8 declared anchors, decoded by frame number from the locked reference film (already produced: 56 aligned keyframes) |
| Artwork frame set | a new-identity render of each anchor frame: 640x360, RGB, one file per anchor, named `<TAG>_reskin_f<frame_id>.png` |
| Per-role artwork cutouts | for every role in the window's role list, an RGBA cutout of the *artwork* frame masked by that role's mask index, named `<role_id>_f<frame_id>.png`, so a checker can diff role-by-role against the source reference cutouts |
| Provenance | tool name + version, weights file name + SHA-256, prompt/seed/params, source film SHA-256, and the SHA-256 of every input keyframe/reference used |
| Freeze discipline | artwork is a *candidate*; it may never redefine the fixture. Tolerances below are calibrated on the source and are already frozen |

### 1.1 Windows, anchors and role-reference counts (inputs that exist today)

| Window | Tag | Film frames | Anchors | Holdout | Classes | Roles / role references |
|---|---|---|---|---|---|---|
| W01_BOOK | BOOK | 1650–1769 | 1650,1665,1680,1695,1710,1725,1740,1755 | no | prop_interaction, contact, hold | 8 |
| W02_CUT | CUT_660 | 660–779 | 660,675,690,705,720,735,750,765 | no | hard_cut | 20 |
| W03_WALK | WALK_7927 | 7927–8046 | 7927,7942,7957,7972,7987,8002,8017,8032 | no | walking | 5 |
| W04_TURN | TURN_795 | 795–914 | 795,810,825,840,855,870,885,900 | no | turn_or_shape_change | 6 |
| W05_CAMERA | CAM_4212 | 4212–4331 | 4212,4227,4242,4257,4272,4287,4302,4317 | no | camera_motion | 25 |
| W06_OVERLAP | OCC_14768 | 14768–14887 | 14768,14783,14798,14813,14828,14843,14858,14873 | no | overlap_or_occlusion | 11 |
| W07_HOLDOUT | HOLDOUT_16231 | 16231–16350 | 16231,16246,16261,16276,16291,16306,16321,16336 | **yes** | unlabelled_holdout | 13 |

Total: 56 aligned keyframes, 88 role reference cutouts, all produced in round 2
with per-artifact provenance (`references_<tag>.json`, `references_index.json`).
Timeline: `t = frame_id / 30` exactly, `pts = frame_id * 512` exactly
(timebase 1/15360), locked reference film SHA-256
`5A175454C2C2965BAC5013A53926E210A9F70A185D802D0F2E0083A6FB399FA2`.

### 1.2 Constraints the artwork must satisfy (from `style_contract`)

May change: character identity, face, hair, clothing, materials, palette,
background design, prop design.
Must NOT change: scale; layout / framing; silhouette envelope; grip / touch
contact geometry; shot order and cut frames; frame count, timing and original
audio; z-order and visibility intervals.

Hard: no renderer may redefine what "correct" means; a palette-only or
histogram-only change is not a reskin; source watermark/logo pixels are
source-only and must not be reproduced.

The interaction group `G_BOOK_MAN_HANDS` (man + two hands + book, window
W01_BOOK) is one constrained group: these members may not be generated or
transformed independently while the book is held/open.

### 1.3 How a produced artwork set would be checked (checker contract, not a tolerance widening)

1. Existence and count: 7 windows x 8 anchors = 56 artwork frames; per-role
   cutouts equal to the frozen per-window role counts (88).
2. Provenance completeness: every artwork file resolves to a tool + version +
   weights SHA + params + input SHAs.
3. Identity change present: artwork differs from source inside the role masks
   (not a palette-only/histogram-only transform of the source).
4. Geometry preserved: silhouette envelope and contact geometry measured against
   the frozen source reference cutouts, using tolerances calibrated on the source
   in this task and frozen in the fixture — never adjusted after a candidate fails.
5. Frame count / timing / audio untouched: 120 frames per window, 30 fps,
   original audio retained.

---

## 2. Exact unmet dependency

**Required dependency:** an image-editing / generative engine that is actually
callable from this task's runtime and whose weights and parameters can be hashed
into provenance.

**Status: NOT AVAILABLE to this task.** Measured in this round, from this
runtime, on 2026-09-17 (all commands recorded in `ledger/commands.jsonl`):

| Check | Exact command shape | Measured result |
|---|---|---|
| HTTP image engine listening (ComfyUI default port) | `curl -m 3 http://127.0.0.1:8188/system_stats` | connection failed, HTTP code `000` |
| Second local port probed | `curl -m 3 http://127.0.0.1:8201/system_stats` | `000` |
| Third local port probed | `curl -m 3 http://127.0.0.1:7860/system_stats` | `000` |
| Diffusion weights in this task's runtime | `find <runtime>/golden -name '*.safetensors' -o -name '*.ckpt'` | `0` files |
| Diffusion library in this interpreter | `python -c "import diffusers"` | ModuleNotFoundError |
| Transformers in this interpreter | `python -c "import transformers"` | ModuleNotFoundError |
| Torch present (needed by an engine) | `python -c "import torch"` | OK, `2.11.0+cu128` |
| PIL present | `python -c "import PIL"` | OK, `12.2.0` |
| Vision model on this task's model route | image probe on the `ocg/deepseek-v4.1-flash` route | image omitted, no vision support (re-confirmed by the Manager) |

**Boundary that makes this an unmet dependency rather than a workaround:** a
sibling task (MF-V1-COMFY) has brought up its own ComfyUI runtime under
`…\mfv1\runtime\comfy` with its own model store. It exists — observed read-only
this round: `runtime\comfy\models\checkpoints\Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors`,
7,105,348,188 bytes. It is **not this task's**: this task wrote nothing into it,
depends on nothing in it, and did not mutate its model store. The Manager's
round-2 packet explicitly forbids coupling the two tasks and routes
engine→artwork as a separate authorised step. So the exact missing piece is an
authorised, callable image engine plus hashed weights — not a missing idea.

**What is delivered instead (and is complete):** all golden/tracking inputs —
source fingerprint, window set with exact frame IDs + PTS, annotations,
alignment references, per-role references for all 88 roles, style contract and
the freeze hash.

**What the Manager must authorise to close G-A8 as (a):** an artwork step that
runs the authorised engine, records engine+weights SHA-256 and params, writes
`<TAG>_reskin_f<frame_id>.png` plus per-role cutouts for the 56 anchors into the
`GOLDEN`/wave output allowlist, and re-states this spec's checker contract in the
producing task's report. The fixture stays frozen and unchanged by that step.
