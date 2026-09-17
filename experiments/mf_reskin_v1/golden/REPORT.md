# REPORT — MF-V1-GOLDEN (round 2, continuation of session `20260917_180945_1e9357`)

Task ID: **MF-V1-GOLDEN** · Branch `codex/mf-reskin-v1-golden` · Base SHA
`2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64` (re-asserted, unchanged)
Worker: Hermes worker session `20260917_180945_1e9357` (same owner as round 1)
Model route: exact `ocg/deepseek-v4.1-flash`, fallback OFF (unchanged)
Round-2 window (local +07): 2026-09-17 18:50 → 19:05

## 0. Verdict in one line

**TASK_SUBMITTED** — all five outstanding steps I.1–I.5 are done and landed;
G-A1..G-A7, G-A9..G-A12 are green; **G-A8 is satisfied as outcome (b)** (keyframe
spec + exact unmet dependency), because no image/generative engine is callable
from this task's runtime. Nothing was pushed, merged, or self-approved.

## 1. What actually ran this round (real numbers)

| Step | Command (exact, via `tools/run_log.py`) | Result | Duration |
|---|---|---|---|
| I.2 guard baseline | `python tools/write_set_guard.py baseline` | HEAD `2594de0`, porcelain `0` lines, tracked `1837`; runtime root `176` files, EV `0`, in-repo allowlist `0` | 0.410 s |
| I.1 references | `python tools/make_references.py` | 7 windows → **56 aligned keyframes**, **88 role reference cutouts**, 7 `references_<tag>.json` + `references_index.json`; exit 0 | 22.442 s |
| audit (new) | `python tools/measure_cutout_bounds.py` | 88 roles audited: **88 CLIPPED**, **10** role→mask-index ambiguous, mask px outside declared crop **9,058 / 2,089,631 = 0.433474 %**, alpha integrity **88/88 true** | 0.236 s |
| G-A8b evidence (new) | `python tools/probe_image_engine.py` | `any_engine_reachable = false`; ports 8188/8201/7860/8888/3000 → TCP refused; `diffusers`/`transformers` missing; diffusion weights in this runtime `0` | 22.179 s |
| I.3 evidence publish | `python tools/publish_evidence.py publish --target ev` | byte-verified copies into `…\GOLDEN` | see §4 |
| I.4 in-repo | `python tools/publish_evidence.py publish --target repo` | **175** files byte-verified into `experiments/mf_reskin_v1/golden/**` | 0.793 s |
| I.5 commit | `git commit` on `codex/mf-reskin-v1-golden` | commit **674fc0c** (parent `2594de0`), 176 files changed, 26,642 insertions, porcelain `0` after | — |
| I.2 guard verify | `python tools/write_set_guard.py verify` (pre-commit) | **VERIFIED**, `problems: []`, added `165`, modified `1`, removed `0` | 0.310 s |

The single `modified` file in the guard verify is `ledger/commands.jsonl` — the
command ledger itself, which every logged command appends to (inside the
allowlist). **Zero round-1 runtime bytes were modified** and zero files were
removed.

## 2. Manager round-1 verification — carried forward, not re-derived

The Manager independently recomputed and accepted: fixture SHA
`7e1627e4…cd0dab`; freeze hash `2c558ce1…fa684`; 7 windows / 28.0 s / 1 holdout /
≥1 primary; reference film A/B SHA == pin, identical, 39,634 decoded frames;
scene candidates 208 (>0.45) / 224 (>0.25); real SAM 2.1 inference
(hiera-large, cuda, 2.184 s, 8 masks, frame 1650); 7/7 windows annotated at
anchor cadence; demo→film offset `film = demo + 1200` (900 frames, MAE 0.1536 at
1200 vs 0.445 at ±1, 39.2 at 300). The frame-space resolution (film frames
1650–1769 = the "book scene", PROTOTYPE_A = diagnostic harness output, never
source truth) stays as accepted and **was not re-opened**.

## 3. New measured findings this round (kept visible, not softened)

1. **Delivered role cutouts are cropped by the annotation's declared bbox, and
   that bbox under-covers the mask.** `tools/measure_cutout_bounds.py`:
   88/88 cutouts verdict `CLIPPED`, **9,058 of 2,089,631 mask pixels (0.433474 %)**
   fall outside the crop; worst single case `CAM_4212 role_25 f4317`
   = 990 px of 211,809 (0.467 %); the declared bbox is usually the mask's tight
   bbox minus one pixel on an edge (e.g. `[0,0,173,288]` vs tight `[0,0,174,289]`).
   Alpha integrity holds exactly for all 88 (alpha pixel count == mask pixels
   inside the crop), so the cutouts are *correct but slightly clipped*.
   `tools/make_references.py` was **not** modified: round-1 bytes must stay
   byte-identical, so the geometry is reported as a measured defect instead of
   silently rewritten. Fixing it is a one-line change if the Manager authorises it.
2. **10 of 88 role references come from an anchor where one `role_id` is carried
   by more than one mask index** (role split across masks), e.g. `CAM_4212
   role_15 f4272` → indices `[2, 6]`. `make_references.py` keeps the largest-area
   entry; the audit reproduces that rule and records `candidate_indices`,
   per-index areas and `index_used_by_make_references_inferred` per role. This is
   the concrete mechanism behind the round-1 `mask_count != role_count` gap, and
   it means the reference manifest cannot be read as a unique mask-index
   provenance record — the audit supplies it.
3. **Freeze hash is over a canonical form, not over the file bytes.**
   `freeze.hash_of_fixture_bytes_sha256` is `null` in the frozen fixture. The
   real fixture file hash is
   `7e1627e4c8c2421e77758b48f0c003c23d0b8b2f50fc73bc2118bc6b06cd0dab` (matches
   the Manager's round-1 recomputation `7e1627e4…cd0dab`) — recorded here so both
   numbers are unambiguous.
4. **Guard semantics caveat (round-1 tool, unchanged):** the guard's
   `forbidden_touched` map reports `alembic.ini: true` and `pyproject.toml: true`
   because those files *exist* in the worktree (the check is
   `exists and not isdir`), not because they were touched. The enforced
   protections that actually hold are: `git diff --stat` unchanged,
   `tracked files newly modified: []`, `removed_count 0`, and every changed path
   inside the allowlist — all satisfied.
5. **Incidental, outside my scope:** `git commit` on this worktree reported
   `fatal: bad object refs/codex/turn-diffs/captures/1787896071503/…/base` and
   `error: failed to perform geometric repack` from an automatic maintenance
   task. The commit itself succeeded (`674fc0c`, porcelain `0`). I did not touch
   or repair that ref — it belongs to another tool's capture store.
6. **Vision route re-probed this round and still has no vision support:** the
   image probe on the active route returned the marker
   `[image omitted: model has no vision support]` (verbatim response in
   `probe/vision_route_probe.json`). All role labels therefore remain structural
   or cross-referenced from project records.

## 4. Deliverables landed

**In-repo write set** (commit `674fc0c`): `experiments/mf_reskin_v1/golden/**`
= `GOLDEN_FIXTURE.json`, `SOURCE_PROBE.json`, `KEYFRAME_SPEC.md`, `README.md`,
`references/` (8 JSON), `annotations/` (14 JSON), `keyframes/<TAG>/` (56 PNG),
`roles/<TAG>/` (88 PNG), `ledger/commands.jsonl`, `guards/` (baseline + verify),
`cutout_bounds_audit.json`, `image_engine_probe.json`, `COPY_MANIFEST.json`.

**Evidence root** `…\mf-reskin-v1\20260917T110554Z\GOLDEN\`: the above plus
`REPORT.md`, `MATRIX.md`, `NEXT_REVIEW_PACKET.md`, `HASH_TABLE.json`,
`HASH_TABLE.md`, `SOURCE_PROBE.json`, `probe/` companions, `source_probe/` raw
container probes, `masks/<TAG>/` (56 SAM2 mask-index images), `sam2/`, `sheets/`,
`tools/` (12 tool sources used), `ledger/commands.jsonl` + `ledger/raw/` (all raw
command output) + `ledger/guard_baseline.json` + `ledger/guard_verify.json`.
Every published file was copied byte-for-byte and verified by SHA-256 equality;
`COPY_MANIFEST.json` records the verification per file.

## 5. G-A8 — stated explicitly

**Outcome (b): keyframe spec + exact unmet dependency.**
`KEYFRAME_SPEC.md` defines the required artwork set (56 artwork frames +
per-role artwork cutouts + provenance requirements + the frozen checker
contract) and names the exact missing piece: a callable image-editing/generative
engine with hashable weights and parameters. Measured, in this runtime:
no loopback engine accepts a connection (5 ports), no diffusion library in this
interpreter, no diffusion weights on disk in this runtime, no vision route that
accepts an image. The sibling MF-V1-COMFY runtime exists (read-only observation:
`…\runtime\comfy\models\checkpoints\Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors`,
7,105,348,188 bytes) but is explicitly not mine — nothing was written to it,
nothing was read from it beyond a directory listing, and this task does not
depend on it. **No artwork was fabricated, and no palette-only/histogram-only
artifact is presented as a reskin.**

## 6. Gaps carried forward (unchanged, truthful negatives)

- hands not separately resolvable as two distinct roles at 640×360
- structural-only role labels (no vision route available)
- between-anchor frames not annotated/interpolated (anchor cadence 15 only)
- occlusion class `PARTIAL — NOT_DEMONSTRATED`; z-order `unresolved`
- `mask_count != role_count` (now with a measured mechanism, §3.2)
- flat background regions uncovered by route A; route B colour regions are
  lower-confidence and are not silently treated as background
- `camera_motion` rests on a small number of windows (318 / 39,634 frames =
  0.80 % show >1 px global shift)
- provisional REF-R02/R05 windows land on static holds and were not used
- exact-repeat/hold divergence vs locked profile (3224 / 8.135 % and 59 vs
  2675 / 6.75 % and 57) kept as measured, not reconciled
- **new:** role cutout crop clipping (§3.1) and per-anchor role→index ambiguity
  (§3.2)

## 7. What I did NOT do

No push. No merge. No `reset/clean/stash/restore/checkout`. No write into
`runtime\comfy\**`, no sibling worktree, no MAIN, no `app/`, `frontend/`,
`migrations/`, `docs/`. No round-1 output byte deleted or modified. No
PROPAGATE/BENCH work. No self-approval. `APPROVED`/`CLOSED` are not mine to write.

## 8. Terminal state

`TASK_SUBMITTED` — handed back to the Manager for verification, then Codex
review. Round-2 artifacts: commit `674fc0c` (artifacts) plus the immediately
following commit on the same branch (this documentation + SHA record).
