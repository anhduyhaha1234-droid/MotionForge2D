# REPORT — MF-V1-GOLDEN (continuation 02 / round 3 — cutout-crop fix)

Task ID: **MF-V1-GOLDEN** · Branch `codex/mf-reskin-v1-golden` · Base SHA
`2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64` (re-asserted, unchanged)
Worker session: `20260917_184835_1e70db` (the continuation-02 packet's own pin;
the round-1/round-2 documents under this same Task ID record
`20260917_180945_1e9357` — both are quoted verbatim rather than reconciled)
Model route: exact `ocg/deepseek-v4.1-flash`, thinking ON, effort N/A, fallback OFF
Round-3 window (local +07): 2026-09-17 19:31 → 19:5x (single bounded correction)

## 0. Verdict in one line

**TASK_SUBMITTED** — the one authorised correction (your decision #2) is done:
role reference cutouts are now cropped from the **mask's tight bounding box**, the
audit reads **88/88 `EXACT` with 0 of 2,089,631 mask pixels outside the crop**, the
round-2 declared-bbox defect is **still measured and reported unchanged**
(9,058 px = 0.433474 %), the fixture / keyframes / freeze are **re-asserted
byte-identical**, the guard is re-run and classified, the docs and manifests are
refreshed to the corrected values, and the work is in a **local commit** on
`codex/mf-reskin-v1-golden`. **Nothing was pushed.** No engine→artwork, no vision
work, no PROPAGATE/BENCH, no fixture/tolerance change.

## 1. What actually ran this round (real numbers)

| Step | Command (exact, via `tools/run_log.py`) | Result | Exit |
|---|---|---|---|
| pre-image freeze (1st) | `python tools/round3_preimage.py` | patched-tool preimages + 7 frozen artifacts | 0 |
| pre-image freeze (2nd) | `python tools/round3_preimage.py` | same two preimages plus protected/regenerated tree aggregates | 0 |
| round-2 byte archive | `python tools/round3_preserve.py` | **9** files copied, all `byte_identical: true` | 0 |
| bounded patch | `python tools/round3_patch.py` | `measure_cutout_bounds.py` patched (`applied_now`); `make_references.py` re-measured | 0 |
| references (the fix) | `python tools/make_references.py` | 7 windows → **56 keyframes (skipped, already present)** + **88 role cutouts regenerated** + 7 manifests + index | 0 |
| audit | `python tools/measure_cutout_bounds.py` | 88 roles: **88 `EXACT`**, mask px outside crop **0 / 2,089,631 = 0.0 %** | 0 |
| independent check | `python tools/verify_round3.py` | **14/14 checks true**, `failures []` | 0 |

Two commands **failed first** and are kept in the ledger as raw evidence (they are
part of this round's record, not hidden):

* row 96 `classify_guard_result_precommit_r3` → exit 1: the first version of the
  round-3 classifier demanded a HEAD advance, which a pre-commit state cannot have,
  so it returned `DRIFT`. It was corrected to be stage-aware
  (`--stage precommit|postcommit`) and re-run (row 97, exit 0). Both raw outputs are
  kept; the failed one is **not** deleted.
* row 102 `publish_ev_r3` → exit 1 `PermissionError`: `publish_evidence.py` listed
  `ledger/raw/` flatly, and this round put the preimage snapshots in a
  **subdirectory** there, so the tool tried to `sha256` a directory. Fixed by a
  bounded patch (see §2.3) and re-run as row 105 (exit 0).

`round3_preimage.py` ran twice. The **first** invocation (19:32:41) recorded a
7-entry frozen list that included `references_index.json` and
`cutout_bounds_audit.json`; those two are rebuilt by design in this round, so the
**second, authoritative** invocation (19:34:12) moved them to the
`regenerated_artifacts_pre` group and added the protected/regenerated tree
aggregates. Both raw outputs are kept
(`ledger/raw/20260917T123241_round3_preimage.txt`,
`ledger/raw/20260917T123412_round3_preimage.txt`) and the **two runs agree
byte-for-byte on both patched-tool preimages** (`016f7acd…`, `665cdb34…`). Only the
second run's `ledger/round3_preimage.json` is used as authority below.

## 2. The correction itself — bounded patches, with preimage

Three tool files moved: two carry the correction itself, the third is a measured
necessity (§2.3). All are **untracked runtime tools**, so Git cannot restore
them; each was snapshotted byte-for-byte before any write
(`ledger/raw/round3_preimage/`) and the snapshot hash was verified equal to the
source hash (`snapshot_is_byte_identical: true`). No file was rewritten whole:
`whole_file_rewrite: false` for all three, and every replacement asserts the old
block occurs exactly once. Record: `ledger/round3_tool_patch.json`.

| Tool | sha256 before → after | bytes | lines | diff |
|---|---|---|---|---|
| `make_references.py` | `016f7acd4f17916970a971b5856c5b3760d20ce58d805f159cd9b98616f60580` → `9588e8d9ae749894aeeb4760c0a471c044f26d6fc27e7bd1a25e009a28a67124` | 6,829 → 9,977 | 181 → 232 | +54 / −3 |
| `measure_cutout_bounds.py` | `665cdb34f35969a4d39203b88d686306e5aba40db2cd3049972f2f25847c0b42` → `4c7a694379f91badf04069c275e67e047840387b0985af9993de6eb3c93bd1d7` | 7,853 → 12,329 | 189 → 258 | +100 / −31 |
| `publish_evidence.py` (see §2.3) | `5399a175ea30d585c370c6c5ba519104800ba62c7bfe3567fc6ce48bc4af834d` → `c5e904e980b73280b13b05d756c9d3f58b930bd9db123c611e0104ae43bc56ab` | 15,797 → 16,189 | 321 → 328 | +8 / −1 |

### 2.1 `make_references.py` — crop from the mask's tight bbox

The crop window is now computed from the mask itself:

```
ys, xs = np.where(m)
tx, ty = int(xs.min()), int(ys.min())
tw, th = int(xs.max() - tx + 1), int(ys.max() - ty + 1)
cut = rgba[ty:ty + th, tx:tx + tw]
```

An empty mask now aborts (`refusing to write an empty cutout`) instead of writing a
degenerate PNG. The annotation's declared bbox is **kept verbatim** as `bbox_xywh`
and aliased as `annotation_declared_bbox_xywh`; the applied window is recorded
separately as `crop_basis: "mask_tight_bbox"`, `crop_bbox_xywh`, `crop_origin_xy`,
`crop_size_wh`. Nothing is silently redefined and no annotation byte changed.

Per reference the manifest now also records **which mask index was used**, which
closes the round-2 gap where that was only inferable from the audit:
`mask_index`, `role_index_candidates` (every index carrying that `role_id` at the
anchor), `role_index_candidate_areas_px` and `role_index_ambiguous_at_anchor`, plus
a `field_notes` map describing each field.

### 2.2 `measure_cutout_bounds.py` — measure the crop that was applied

The primary metric is now the crop window the cutout was **actually** taken from,
instead of the annotation's declared bbox. **The check was not relaxed** — it was
made stronger, and the old number is still produced:

* the crop window is taken from the **delivered PNG's own dimensions**, not from a
  JSON field the same tool wrote;
* the mask's tight bbox is **recomputed independently** from
  `maskindex_f<frame>.png`;
* the alpha channel is now compared to the mask **element-wise**
  (`(alpha == expected).all()`), not merely by non-zero pixel count;
* `mask_px_outside_declared_crop` keeps the exact round-2 metric, and
  `mask_px_outside_crop` is the new one — both are in `totals`, so the two rounds
  can be compared line by line.

Field names were disambiguated rather than reused: the round-2 field
`mask_px_outside_crop` (which meant *declared-bbox*) is now
`mask_px_outside_declared_crop`, and `mask_px_outside_crop` means the crop that was
applied. The round-2 audit bytes are preserved unchanged at
`probe/round2/cutout_bounds_audit.json`
(`5744ea2d8a2572087d3774cce4dbed45bf540353635f9ad7cba8b100b6c5462a`).

### 2.3 `publish_evidence.py` — a measured necessity, not scope creep

`publish --target ev` died with `PermissionError: [Errno 13]` on
`ledger\raw\round3_preimage` (ledger row 102, exit 1, raw traceback kept): the tool
lists `ledger/raw/` flatly for publication, and this round stored its preimage
snapshots as a **subdirectory** there. The bounded patch skips entries that are not files, so
the EV publish completes (row 105, exit 0, 356 files, 0 problems). Nothing about the
publication semantics changed — the same files are copied and hash-verified — and no
snapshot was moved to dodge the bug. `ledger/round3_preimage.json` had recorded this
tool under `unpatched_tool_hashes`; that record is superseded here explicitly, and
the preimage snapshot was taken byte-identical before the patch
(`5399a175ea30d585c370c6c5ba519104800ba62c7bfe3567fc6ce48bc4af834d`).



## 3. New measured numbers (both metrics, same run)

| Metric | Round 2 | Round 3 |
|---|---|---|
| Verdict histogram | 88 `CLIPPED` | **88 `EXACT`** (0 `CLIPPED`, 0 `OVERSIZED`, 0 `ANOMALY`) |
| Mask px outside the crop that was applied | 9,058 / 2,089,631 | **0 / 2,089,631 = 0.0 %** |
| Mask px outside the **declared annotation bbox** | 9,058 = 0.433474 % | **9,058 = 0.433474 % (unchanged — still measured)** |
| Worst single cutout | 990 px, `CAM_4212 role_25 f4317` | same role, now `declared [0,0,639,359]` vs `tight [0,0,640,360]` → delivered **640×360, 211,809 px, 0 outside** |
| Alpha integrity | 88/88 count-true | **88/88 element-wise true** (`alpha_elementwise_equals_mask`) |
| Role→mask-index ambiguity | 10/88, index only inferable | **10/88 still recorded**, and the manifest now states the index |
| References recording `mask_index` | 0/88 | **88/88** |
| Manifest index == max-area inference | n/a | **88/88** |

Geometry of the defect, measured: **82 of 88** roles had a declared bbox exactly
**1 px short on both axes**; the other **6** had a declared bbox that *overshot* one
axis by 2–180 px while still clipping the other — i.e. the old crop was
simultaneously clipped and padded. All 88 lost at least 4 px (lowest
`CUT_660 role_3 f660`: `[0,0,97,66]` vs tight `[0,0,98,67]`).

The 10 ambiguous roles (recorded, not hidden) — every one of them resolves to the
same index by both the manifest and the max-area rule:

```
CAM_4212 role_2  f4242  idx 2 candidates [1,2]     CAM_4212 role_15 f4272 idx 6 candidates [2,6]
CAM_4212 role_5  f4287  idx 7 candidates [3,7]     CAM_4212 role_16 f4272 idx 8 candidates [3,8]
CAM_4212 role_7  f4242  idx 8 candidates [7,8]     CAM_4212 role_17 f4302 idx 6 candidates [4,6]
CUT_660  role_19 f750   idx 9 candidates [8,9]     OCC_14768 role_7  f14873 idx 2 candidates [1,2]
OCC_14768 role_8 f14873 idx 4 candidates [3,4]     OCC_14768 role_10 f14873 idx 8 candidates [6,7,8]
```

**Second and independent derivation** (`tools/verify_round3.py`, a different code
path that does not import the audit tool): for each of the 88 delivered PNGs it
re-reads the mask index image, recomputes the tight bbox with `np.where`, and
requires `alpha.shape == (th, tw)` **and** element-wise equality with the mask.
Result: `roles_checked 88`, `roles_exact 88`, `mask_px_all_roles 2,089,631`,
`mask_px_outside_crop 0`. Two independent implementations agree.

## 4. Frozen bytes re-asserted byte-identical

`tools/verify_round3.py` → `verdict ALL_FROZEN_BYTES_IDENTICAL_AND_CUTOUTS_EXACT`,
`failures []`, 14/14 checks true (`ledger/round3_after.json`).

| Artifact | sha256 (pre == post) |
|---|---|
| `GOLDEN_FIXTURE.json` | `7e1627e4c8c2421e77758b48f0c003c23d0b8b2f50fc73bc2118bc6b06cd0dab` (matches the Manager's recomputation) |
| fixture freeze hash (canonical JSON minus `freeze`, re-derived from the file) | `2c558ce19e0a9d915d860dc07843bd1412ac4a7801284cca5293ea21cbfba684` |
| `KEYFRAME_SPEC.md` | `4ed5b7bfec887c121b7a361c0d819302b8f991cd12efd4627ce483beafc940f4` |
| `SOURCE_PROBE.json` | `d9d3053323dd4dbc15fe9dd9b94d5f83b58f5fa9ba3b64c865156d085470420b` |
| `image_engine_probe.json` | `6dc834143fc3322ed94f6754c97853e2e87515ba9f4f7ef259b4174cd18e5b62` |
| `vision_route_probe.json` | `82cdbca8515f7ee32bc5c9dbd59d4f9a086c0361931480ec25d5033f8f48604f` |
| protected annotation tree (7 annotations + 7 relations + 56 keyframes + 56 mask-index PNGs = **126 files**) | aggregate `fdd4345f6d62660ae18e1c774d5e6caaa983898c0c1bda5c2137c4f93852844b` (**pre == post**) |

Regenerated **by design** this round, 95 files, all 95 rewritten
(`regenerated_changed 95`): `roles/<TAG>/*.png` (88) + `references_<TAG>.json` (7),
now 1,907,367 B of role cutouts in total. `probe/references_index.json` was
rewritten but is **byte-identical** to its round-2 image
(`a20a370545dc3d0be24d18aa670ee627d5b1df4e4aa6ef5cc4094b5abcb7b727`) because it
records only counts and paths. `probe/cutout_bounds_audit.json`:
75,273 → 119,946 B, 2,671 → 3,990 lines,
`62cd9320426ed6ddb21bbd7cce4bd8ff399038f12d6c2c57fdacabdf3c9980fe`.

## 5. Round-2 bytes preserved, not destroyed

Before the first overwrite, 9 round-2 files were copied to side paths inside the
same allowlist root and hash-verified equal (`ledger/round3_preserve.json`):
`ledger/round2/guard_baseline.json`, `ledger/round2/guard_verify.json`,
`probe/guard_final_classification.round2.json`,
`probe/round2/cutout_bounds_audit.json`, `probe/round2/references_index.json` and
`report/round2/{REPORT,MATRIX,NEXT_REVIEW_PACKET,README}.md`. Round-2 bytes are also
in git history (`674fc0c`, `86e794c`, `278bacf`, `ee7aab4`) — none of it rewritten.

## 6. Gaps I am not hiding (carried from round 2, plus what this round found)

1. **The annotation's declared bbox is still wrong.** It is frozen, and this round
   did not touch it: **9,058 of 2,089,631 mask pixels (0.433474 %)** still fall
   outside it, 6 of 88 declared bboxes overshoot an axis, and 82 are 1 px short on
   both. The cutouts no longer inherit that defect, but **any downstream consumer
   must read `crop_bbox_xywh` / `crop_basis`, never `bbox_xywh`, to reconstruct the
   reference geometry** — `bbox_xywh` is documented in `field_notes` as the
   annotation's own value.
2. **10 of 88 role references come from an anchor where one `role_id` is carried by
   more than one mask index** (role split across masks). The ambiguity is real and
   still recorded; `make_references.py` keeps the largest-area index, the manifest
   now states it, and the audit independently agrees on all 88. It remains the
   mechanism behind `mask_count != role_count`.
3. Carried unchanged: hands not separately resolvable at 640×360 · structural-only
   labels (no vision route: `[image omitted: model has no vision support]`) ·
   between-anchor frames not annotated (cadence 15 only) · occlusion
   `PARTIAL — NOT_DEMONSTRATED`, z-order `unresolved` · `mask_count != role_count` ·
   route-A background holes not silently backgrounded · `camera_motion` rests on
   318/39,634 frames (0.80 %) · provisional REF-R02/R05 land on static holds ·
   exact-repeat/hold divergence vs the locked profile kept as measured.
4. Measurement note, reported not hidden: the continuation-02 packet quotes
   `COPY_MANIFEST.json 160,899 B`; the measured EV copy at this round's preflight is
   **167,197 B** and the in-repo copy **87,064 B** (the EV manifest grows as it
   records superseded hashes). Both are recorded in `HASH_TABLE.json` this round.
5. **A third tool had to be patched for a measured reason** (§2.3): the new preimage
   snapshot subdirectory under `ledger/raw/` broke `publish_evidence.py`'s flat
   listing and the first EV publish crashed. The failed command, its traceback and
   the patch record are all kept. This is disclosed as a scope addition beyond
   `make_references.py`, with its before/after bytes in the ledger.
6. **The round-3 guard classifier itself was wrong on its first run** (§1): it
   demanded a HEAD advance in a pre-commit state. The failed run is kept; the
   corrected, stage-aware version is the one whose verdict is published.

## 7. Write set, guard and scope

Write set used: this task's runtime root
`C:\Users\Admin\Documents\Codex\work\mfv1\runtime\golden\**`, the in-repo allowlist
`experiments/mf_reskin_v1/golden/**`, and the evidence root
`…\outputs\mf-reskin-v1\20260917T110554Z\GOLDEN\**`. Guard: the pre-write baseline
(`ledger/guard_baseline.json`, HEAD `ee7aab4`, porcelain **0**, 2,017 tracked files,
runtime 370 / EV 338 / in-repo 180 files) was **not** re-taken; `write_set_guard.py
verify` was run after the work and the result classified by an additive round-3
classifier (`tools/classify_guard_result_r3.py`) — the round-2
`write_set_guard.py` and its round-2 classifier were **not** modified.

**Not done this round:** no engine→artwork (that is MF-V1-COMFY's step against
`KEYFRAME_SPEC.md`), no viewport/vision work, no PROPAGATE/BENCH, no wave, no new
window, no fixture or tolerance change, no write under `runtime\comfy`, no sibling
worktree, no MAIN, no `app/`, `frontend/`, `migrations/`, `docs/`. No push, no
merge, no `reset/clean/stash/restore`. `APPROVED`/`CLOSED` are not mine to write.

## 8. Terminal state

`TASK_SUBMITTED` — one bounded correction delivered: **88/88 `EXACT`, 0 mask px
outside the applied crop**, freeze re-asserted byte-identical, guard classified,
local commit on `codex/mf-reskin-v1-golden` only.
