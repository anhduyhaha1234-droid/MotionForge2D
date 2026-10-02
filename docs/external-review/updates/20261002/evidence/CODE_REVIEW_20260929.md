# MotionForge — independent code and goal review, 2026-09-29

**Verdict: CHANGES_REQUESTED / NOT_APPROVED / NOT_CLOSED. QUALITY_ACCEPTED=0.**
The project has working components and real GPU output, but a completed, source-faithful app demo is still unproven. Local correction commits are not integrated into the canonical candidate.

## Review boundary and source identity

Read-only code/report review plus small isolated CPU probes; no production edits, Hermes messages, GPU runs, live database mutations, broad tests or push. Canonical rules were read in full this turn. Skills applied after installation: `api-contract-checker`, `evidence-gap-review`, `acceptance-criteria-writer`; their actual `SKILL.md` files were read.

| Tree | Observed HEAD | Status |
|---|---|---|
| `C:/Users/Admin/Documents/Codex/work/mf-delivery-20260927/INTEGRATION` | `a52fca897906fd61a088016dd802718fdf06d217` | Clean canonical candidate; unchanged since morning |
| `C:/Users/Admin/Documents/Codex/work/mf-delivery-20260929/C11` | `e3b130149c84b193736d14d00a26363bdb279dee` | Clean local source-map correction; not integrated |
| `.../C15` | `cf82d30f543afd33c4fc2c00e86414e84a3daa40` | Clean local anchor API correction; not integrated |
| `.../C22` | `2a2b57763c1114aeb273c024eb3f2f1e128d9d5a` | Clean local QC correction; not integrated |
| `.../C19` | `a52fca897906fd61a088016dd802718fdf06d217` | Three modified source files; unfinished implementation |
| `.../C25` | `a52fca897906fd61a088016dd802718fdf06d217` | Three modified frontend files plus untracked shot-anchors feature; unfinished implementation |

Manager `SESSION_REGISTRY.md` and `MATRIX.md` still describe earlier 16:35/17:10 state. Those snapshots cannot override later commits, receipts or reports. Do not dispatch a duplicate owner from their stale NOT_DISPATCHED labels.

## Goal checklist

The goal remains: import source MP4; choose reusable cast/immutable PackVersion for a whole series; decompose into source-aligned units; generate and review target-scene anchors; execute suitable ComfyUI graphs; preserve action, interaction, occlusion, camera, cuts and audio; review/retry the affected shots; export/reopen real MP4; scale to multiple videos; deliver a clean-machine package.

| Goal item | State supported by evidence | Remaining proof / difficulty | Existing owner |
|---|---|---|---|
| Durable import/analyze | Implemented API and UI exist | Latest demo still seeds DB; browser-to-durable chain not demonstrated | MF-END-25 + demo |
| Reusable library / series cast pin | Persistence and interfaces exist | Real target artwork is not proven end-to-end; latest source crops still duplicate one image over six slots | Demo; library owner only on reproducible defect |
| Exact units/time map | Existing detector correctly finds 121/241/343; C11 adds source-map/verification/audio helpers | C11 new functions have no external production callers found; fixed map must be consumed by app generation, not only verified in tests | MF-END-11 + MF-END-19 |
| Scene-image anchor generation/review | Durable anchor job exists; C15 adds seven HTTP paths | Public success contract breaks on `video_id`; missing review decision still opens gate | MF-END-15 |
| Per-unit Comfy graph/prompt/anchor/control | Real app GPU rendering and stitching already work | C19 is unfinished; media remains wrong BOOK/TURN/OCC; same-prompt failure not yet replaced by validated bindings | MF-END-19; conditional MF-END-16; demo |
| Output observations | MF-END-21 producer exists; D0 invokes it on real output pixels | Canonical `app/` search finds definitions only, no automatic publication caller | MF-END-21 |
| Comparative QC | C22 now calls comparison band and blocks unknown/invalid | Measured hard failures are not enforced; missing both evidence sides is exempted | MF-END-22 |
| End-user browser journey | Existing pages and project context work is present | C25 WIP confuses scene-image anchor with placement coordinates; browser E2E missing | MF-END-25 |
| Export/audio/reopen | D0 progressed through actual export submit and three chunks; source audio attached | Export validation refuses 1 ms audio phase mismatch; no completed published master | S12 validation owner via MF-END-26/F7 ownership reconciliation; demo |
| Two-video batch | Export scheduler exists | Render is absent; `SeriesBatchPanel` has no mount caller; requires one accepted video first | MF-END-27 |
| S12 package | Staged package/dev-host checks exist | Clean Windows/human acceptance not run; inventory must be refreshed once after final integration | MF-END-28 |

No percentage is assigned: component count, test count and elapsed sessions do not measure successful product output.

## New findings with exact anchors

### P1-C15-REQUEST — public submit cannot reach the successful job path

`C15/app/api/routes/shot_anchors.py:132` declares `video_item_id`; `:217` forwards `payload.model_dump()` without mapping it. `C15/app/workflow/shot_anchor_jobs.py:922` requires `request["video_id"]` (the engine also consumes this field at `:427`).

Independent probe executes the actual request builder with resolver/readiness preconditions stubbed ready, then the actual submit helper: `video_id_mapped=false`, `KeyError('video_id')`. The HTTP route only catches typed anchor refusals here, so the successful preflight branch is expected to produce HTTP 500 before creating a job. The claimed seven routes exist, but route existence is not successful execution.

**Bounded acceptance:** Given a real published pack and ready plan, POST must return the documented successful status, create exactly one job with the correct video identity, and complete through the existing durable worker. Repeat submit must match its documented idempotency response and preserve one job. Include a test through HTTP with actual isolated DB/library state, not only the existing 422 refusal case.

### P1-C15-DECISION — no explicit review decision still allows video

`C15/app/workflow/shot_anchor_jobs.py:1005` enforces reviewer rejection/staleness only inside `if decision is not None`. An automatically accepted manifest with valid artifact hash and **no decision file** passes `require_accepted_anchor`.

Independent isolated-file probe: `decision_exists=false`, `gate_without_human_decision="accepted"`. This is a gate contract result, not a claim that synthetic bytes are a real image/model output.

**Bounded acceptance:** For the required reviewed-anchor product route, no decision → review required/non-ready; reject → blocked; current manifest accepted explicitly → allowed; changed manifest/source/cast → stale/blocked until re-review. Run these through preview/accept/reject/video-gate HTTP and verify rendering does not start on blocked cases. Keep engine success and human acceptance as distinct states.

### P1-C22-HARD-FAIL — measured comparison defects are recorded but do not block readiness

`C22/app/services/qc_evidence/compose.py:3516` records hard failures and items; `:3578` computes `not_ready` only from indeterminacy/missing frame map/missing entries. A known `fail` status is not indeterminate. `C22/app/workflow/qc_checks_handler.py:729` counts issues only from the old orchestrator summary, and `:780` checks `_comparison_not_ready`, which does not inspect comparison hard failures. `C22/app/persistence/qc_check_runs.py:870` treats `not_ready=false` as successful comparison completion; `:962` then uses persisted blocker rows. The new band does not persist its comparison items into that blocker authority.

Independent probe calls the **real** temporal comparator with frozen output/moving source. It returns `fail`, `QC_COMPARISON_MOTION_STATIC`, one blocker. Passing its actual failure into the actual completion builder yields `zero_item_evidence=true`, `issues_found=0`, `comparison_completion_flag=true`, `non_ready=[]`. An unknown-control case correctly returns false, so C22's invalid/unknown improvement is real but incomplete.

**Bounded acceptance:** For each of five real comparators, inject one measured hard failure and demonstrate actual durable QC completion → readiness blocked → export refused; retain reason, role/frame and current output hash. Replaying must not duplicate issues; corrected output must re-measure and resolve the matching issue without waiving unrelated blockers. Include a valid-control case and unknown case. Test the composition/orchestrator/readiness seam, not only dictionaries.

### P1-C22-MISSING — missing required evidence is treated as inapplicable

`C22/app/services/qc_evidence/compose.py:3453`–`:3471` marks the band `not_applicable/not_ready=false` when both source facts and output observations are missing. The current reskin goal requires these producers. An absence of both does not establish that comparison is unnecessary. Probe of the resulting completion shape returns `zero_item_evidence=true`, `comparison_completion_flag=true`.

**Bounded acceptance:** For the current source-preserving Comfy reskin route, neither side / source-only / output-only / invalid frame map / stale artifact must all produce typed non-ready and refuse export. A legacy exception, if needed, must be keyed to an explicit supported capability/contract, never inferred from missing data. Publish observations automatically after successful render via the existing MF-END-21 producer; use source facts sealed into the matching run.

### P1-C25-CONTRACT-DRIFT — WIP UI implements placement coordinates, not scene-image anchors

`C25/frontend/src/features/shot-anchors/shotAnchorsLogic.ts:5` defines an anchor as normalized coordinates; `:23` contains only `x/y`; `:180` marks ready from coordinate coverage and `:190` tells the user they may render. `shotAnchorsApi.ts:117` reads renderer-route evidence, `:126` patches reskin params. No C15 image-anchor submit/preview/accept/reject call appears in this feature.

This is a WIP divergence, **not a submitted final feature verdict**. Placement controls can be useful but do not fulfil the requested Comfy-generated full-scene image, cast/contact/camera preview, explicit review decision and stale invalidation.

**Bounded acceptance:** After the corrected C15 contract is frozen, the UI calls its actual submit/status/preview/accept/reject/retry surface, shows the generated scene image beside its source with roles/cast/version, and uses server readiness. No client-side coordinate coverage may claim the required scene-image gate passed. Capture a browser journey from import through at least one accepted anchor without SQL/CLI seeding. Keep any placement editor visibly separate from scene-image acceptance.

## Evidence and test limitations

- `code_seam_probes.py`, `C15_SEAM_PROBE.json`, `C22_SEAM_PROBE.json`; parent reruns `C15_SEAM_PROBE_RERUN.json`, `C22_SEAM_PROBE_RERUN.json` confirm the same outputs.
- Fresh isolated focused tests: C15 `43 passed` in 11.24 s; C22 correction `10 passed` in 2.19 s, `PYTHONDONTWRITEBYTECODE=1`, pytest cache disabled, independent audit basetemps. Source trees remained unchanged by these checks.
- C22 test `tests/product_delivery/test_mf_end_22_correction.py:143` is named “band runs the five comparators,” but its final assertions at `:178`–`:179` only check callability/count; it installs spies without executing the band or asserting the call list. Its green result is not production-call proof.
- Probes use synthetic contract inputs and limited precondition stubs; they prove failure of those source functions, not a new real-media DB/browser run. Full endpoint success and durable readiness/export regression tests remain necessary.
- C19 current WIP at `shot_reskin_executor.py:394` nests helper definitions and leaves `canonical` undefined at `:507`; Manager's C19-R2 packet already identifies 13 failed/19 passed. Do not integrate or judge this active unfinished tree as a finished delivery.
- D0's new export report is useful progress: real submit/chunks and source audio exist; validation fails. Its measured 48-sample/1 ms lag with aligned correlation 0.9981 suggests an audio timestamp alignment issue. Do not relax quality thresholds; retain bad-content and excessive-offset negatives when fixing.
- D0 raw pixel-difference peaks at 163/176/331 are not automatically additional scene cuts; compare source semantics and the scene detector's explicit cut contract. C11 confirms 121/241/343 on the actual source.

## Next bounded owner actions (proposal only)

1. Resume **MF-END-15 `20260928_153337_741b7e`** for request identity and explicit decision gate. Exclusive API/anchor-job/test paths already owned by C15. Complete HTTP success and rejection matrix before C25 integrates.
2. Resume **MF-END-22 `20260928_181430_0350c2`** for hard-failure propagation, mandatory evidence applicability and real seam tests. Existing QC files/tests only; no threshold relaxation. This can run independently of C15 in isolated resources.
3. Resume **MF-END-19 `20260928_160603_9d1521`** for guarded WIP repair, then source-map/per-unit graph/prompt/anchor/cast/control/cache bindings. Avoid enforcing prompt uniqueness as a proxy for semantic correctness: distinct units can legitimately share prompt text; differing bindings and source facts must be authoritative. Prove BOOK/TURN/OCC actual inputs.
4. Resume **MF-END-25 `20260928_203715_8f1486`** after corrected C15 contract is pinned. Correct terminology and actual API binding before further UI expansion. Real browser proof uses isolated backend/DB.
5. Conditional **MF-END-21 `20260928_172924_b16d5f`** publishes observations on the real completion path; coordinate exclusive write paths with C19/C22 before dispatch. Conditional export validator correction needs exact ownership reconciliation (MF-END-26/F7/S12 owner), not a new arbitrary writer.
6. Exact **demo owner `20260929_041810_bc7c61`** consumes frozen integrated corrections and proves one app video first. Reuse unchanged render bytes only for downstream audio/QC tests when identity matches. New generation is needed for the wrong visual units after proven inputs are wired.
7. **MF-END-27 `20260928_210647_069401`** batch render+export waits for one accepted video. **MF-END-28 `20260928_214702_f7c6aa`** clean-host/release proof waits for frozen journey; inventory refresh occurs once after integration.

All are existing-owner corrections, not new parallel owners. Manager coordinates; implementation remains with workers; Codex independently reviews final artifacts. Latest requested route remains `cmc/deepseek/deepseek-v4.1-flash`, fallback off, subject to actual route/context preflight. This document itself grants no dispatch authority.
