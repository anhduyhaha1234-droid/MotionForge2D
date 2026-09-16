# S12-PUBLIC-AUTHORITY-BRIDGE — R7 phase 2 (production B03–B06) report

- Session: `20260916_105450_f38ead` (owner duy nhất Task ID; route
  `ocg/deepseek-v4.1-flash` / provider custom / fallback OFF / native thinking).
- Worktree: `C:/Users/Admin/Documents/Codex/work/s12-r7-authority-bridge` —
  branch `codex/s12-r7-authority-bridge`; wave-base `35f6cb2…`; phase-1 docs
  commit `3963d31…`; phase-2 commits: `b6108d4` (4 service files + CONTRACT +
  LOG, +1251/−148) và `34e680c` (new module + tests + report, +2444); không
  rewrite history (`-am` không nhận file mới nên tách 2 commit cùng prefix).
- Status: `PRODUCTION_B03_B06_DELIVERED_PENDING_MANAGER_B_QA_REVIEW` (không push).

## Files changed (post-patch sha256/size/lines — `phase2/post_patch_hashes.json`)

| File | sha256 (12) | bytes | lines |
|---|---|---|---|
| `app/services/source_locked_timeline.py` (NEW) | `AA223514591B` | 16886 | 414 |
| `app/services/s09_approval.py` | `61916B717684` | 75104 | 1731 |
| `app/services/s10_full_apply.py` | `E1B512271AB8` | 45105 | 992 |
| `app/services/s10_chunk_plan.py` | `9E97D00BE88B` | 24447 | 526 |
| `app/workflow/s10_full_apply_jobs.py` | `544844696A09` | 74614 | 1652 |
| `tests/s12/s12-public-authority-bridge/conftest.py` | `253F7DF6AA55` | 23755 | 675 |
| `tests/s12/s12-public-authority-bridge/test_b03_partition_layers.py` | `0DCB08A7E96A` | 10551 | 286 |
| `tests/s12/s12-public-authority-bridge/test_b04_eligibility.py` | `340F143DE0B4` | 5875 | 160 |
| `tests/s12/s12-public-authority-bridge/test_b05_authority_freeze.py` | `32B61C305A20` | 17115 | 423 |
| `tests/s12/s12-public-authority-bridge/test_b06_composition.py` | `1541C13AD099` | 13788 | 383 |
| `docs/.../S12-PUBLIC-AUTHORITY-BRIDGE/CONTRACT.md` (v0.2) | `CD4CCC039B4E` | 35496 | 493 |
| `docs/.../S12-PUBLIC-AUTHORITY-BRIDGE/LOG.md` | (xem sau commit) | — | — |

Write-set proof: `guard-allow-pre.json` drift = EXACTLY the 4 allow service
files; `guard-protected-pre.json` → `entries=18 bad=0` (`v1_guard_protected.*`).

## Acceptance results (raw in `phase2/`)

| Row | Nodes | Result |
|---|---|---|
| B03 | 8 (`test_b03_*`) | green — partition/co-occurrence/repeated-role/background/1-frame/multiscene/no-Cartesian |
| B04 | 6 (`test_b04_*`) | green — points-only/missing/ambiguous/unsupported-route → typed ineligible + zero S10 rows; Mode A proceeds; no invented rectangle |
| B05 | 6 (`test_b05_*`) | green — timeline inside checkpoint hash; live mutations frozen; stale → reapproval; v1/v2-legacy bytes preserved; corrupted timeline fails closed with no live fallback |
| B06 | 7 (`test_b06_*`) | green — composition (both layers into final pixels), frozen Q9 evidence, no-dedup proof, occluded-layer overpaint documented, missing artifact/evidence fail-closed (live + e2e), 120-frame/rational-fps preserved, audio policy untouched |

Gate summary (final frozen revision):
- `g4_final_micro` → **27 passed** (124.90s)
- `g5_final_api` (`tests/test_s10_full_apply_api.py`) → **71 passed** (165.72s)
- `g6_final_reg` (`s12-t03c/test_publication.py` + `s12-lc3-retry/test_r6_identity_resolution.py`) → **66 passed** (152.82s)
- static: ruff `--select F` clean; `py_compile` + `compileall -q app` exit 0; `git diff --check` exit 0
- ledger: `phase2/COMMAND_LEDGER.jsonl` — 17 entries (argv/cwd/UTC/exit/elapsed_ms)

## D1 (B01 timing dependency)

Parse-and-validate path implemented exactly per ruling Q8: `time_base`
`"{fps_den}/{fps_num}"` split → exact ints > 0; `fps` cross-check via exact
double compare (`fps_num/fps_den`); unprovable → `TIMELINE_TIME_BASE_UNAVAILABLE`
(hard deny). B01's landed fix is enforcement-only and keeps the format
unchanged — the parse path remains valid; the dependent branch blocks only if a
future producer drops the parseable fields. No interface change was required on
my side.

## Flags for Manager B / QA (explicit, not silent)

1. **Q4 amendment hardening**: ruling v0.2's Mode-B containment bounds
   (`x+w ≤ src_w`, `y+h ≤ src_h`) reject the SANCTIONED chain's own padded boxes
   ({100,100,300,300} and {400,100,250,250} on 640×360). Delivered: Mode B
   = box intersects frame + normalized region clipped to the physical frame;
   fully-outside → `OCCURRENCE_REGION_OUT_OF_BOUNDS`; dims unavailable →
   `OCCURRENCE_REGION_SCALE_UNRESOLVED`. (CONTRACT amendment v0.2 documents it.)
2. **D2 count**: the D2 table lists 27 node names (8+6+6+7); the dispatch
   prompt's "23" summary is an arithmetic miscount. All 27 delivered verbatim.
3. **Legacy client-copy alias**: the pre-bridge client-copy control test
   (`test_client_legacy_authority_tamper_fails_closed_zero_run_job`, 202-control)
   echoes segment-as-shot / role-as-layer ids. The compare keeps a bounded
   UNAMBIGUOUS alias (occurrence→scene for old shot ids; role→occurrence only
   when the role owns exactly one occurrence; ambiguous → fail closed). Plan
   remains purely canonical; every value mismatch still 422.
4. **`test_s09_t06_backend_authority.py`** (outside gate): 3 failures —
   (a) two are contract-mandated (`seg["eligibility"]["executable"] is True` /
   `reasons == []` for a POINTS-ONLY fixture; the frozen B04/F04 semantics make
   it ineligible with a typed reason — the owner of that fixture must update the
   assertion or add boxed geometry);
   (b) one is PRE-EXISTING: the test pins the old alembic head
   `a10b11c12d3e` vs current `d4e5f6a7b8c9` (S12 migrations landed before this
   lane; proven: this lane touched no migrations/models — `git diff --name-only`
   vs wave-base shows only the 6 write-set paths).
5. **Worker composition input**: the job manifest's `render_authority` carries
   `scene_manifest.shots` + `structural_lock_manifest.frame_count` + canonical
   mapping (incl. per-occurrence range/z/visibility) — composition consumes
   exactly these; it does not need (and does not re-read) the full timeline
   block or live Scene rows.
6. **Q9 row granularity**: rows are per active (shot ∩ occurrence ∩ chunk run)
   unit (a pair spanning multiple chunks has one row per run — the only coherent
   reading of the frozen artifact_sha256-per-range field). 19 fields delivered
   covering the entire frozen list; crop hashes = sha256 of concatenated
   deterministic PNG (RGB8) bytes across sampled frames.

## Anomalies / deviations

- micro v1→v3 iterations documented in LOG (all harness-side).
- `git diff --check` note: CONTRACT.md LF→CRLF warning (repo convention),
  pre-existing class, exit 0.
- No data-model/migration/API/producer/publication-producer files touched.

## Q4-coverage additions beyond D2 (follow-up, QA review `958d021`)

QA accepted the v0.2.1 clip code but flagged a COVERAGE GAP for ruling v0.2 §5.
Added 4 test nodes (production untouched; they are ADDITIONS — the D2 inventory
already stands DELIVERED VERBATIM at 27):

| New node | Covers |
|---|---|
| `test_b04_mode_b_padded_clip_positive` | padded pixel box {400,100,250,250}/640×360 → clip region `[0.625, 0.2777…, 0.375, 0.6944…]` asserted via independent formula AND real `derive_region`; authority PROCEEDS (202) |
| `test_b04_scale_unresolved_negative` | pixel-scale box + dims NULL (`hide_dims`) → `OCCURRENCE_REGION_SCALE_UNRESOLVED`, zero mutation (0 runs/0 jobs) |
| `test_b04_fully_outside_deny` | box {700,100,50,50}/640×360 (x≥src_w) → `OCCURRENCE_REGION_OUT_OF_BOUNDS`, zero mutation |
| `test_b04_cross_key_precedence_geometry_source` | `cross_key_conflict` fixture: differing segmentation vs prompt boxes → segmentation wins, `geometry_source="segmentation.boxes[0]"` frozen, prompt evidence preserved, PROCEEDS (202) |

Suite after additions: **31 passed** (27+4; 88.18s, exit 0; raw
`phase2_q4/q4_micro_31.*`). ruff `--select F` + `git diff --check` exit 0;
protected 18/18 bad=0.

## Next

Manager B + QA review of this packet (artifacts in
`outputs/s12-r7-two-managers/20260916T0351Z/B/BRIDGE/phase2/`); no push; no
APPROVED/CLOSED emitted by the owner.
