# MotionForge 2D - Epic, Sprint and Task Roadmap

**Planning model:** outcome-based, dependency-gated  
**Execution rule:** one Task ID = one Hermes chat/session  
**Estimate unit:** session-sized, not calendar commitment

**Approved target overlay:** [Source-Locked 2D Target Profile](TARGET_PROFILE_2D_SOURCE_LOCKED.md)

Future S05-S12 acceptance contracts must apply this overlay before a task packet
is issued.

## Release map

| Release | Epics | Exit outcome |
|---|---|---|
| R0 Trusted Foundation | E00-E01 | Safe tests, durable domain and jobs |
| R1 Production Shell Alpha | E02-E03 | Manage channels/projects/videos and import/analyze |
| R2 Character & Reskin Alpha | E04-E06 | Reusable characters, object mapping, demo/apply |
| R3 Review & 4K Beta | E07-E08 | Actionable QC, original audio and validated 4K |
| R4 Character Generator | E09 | Guided six-pose 2D pack generation |

Sprint numbers express dependency order. They do not promise fixed duration. A sprint closes only when its exit gate is approved.

---

## EPIC E00 - Baseline and Change Safety

**Outcome:** repository has trustworthy gates and tests cannot mutate user production data.  
**Master Plan:** WS-01, G1.

### Sprint S00 - Isolate and record the baseline

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S00-T01 | Tests use isolated channel/preset storage and never write root `channels.json` | None | APPROVED |
| S00-T02 | Reproducible baseline script/report for Python, typecheck, lint and build | S00-T01 | APPROVED |
| S00-T03 | Declare/configure runtime dependencies and FFmpeg discovery without machine-specific fallback | S00-T02 | APPROVED |
| S00-T04A1 | Resolve Python mypy baseline outside monolithic projects route | S00-T03 | APPROVED |
| S00-T04A2 | Resolve Python mypy baseline in projects route | S00-T04A1 | APPROVED |
| S00-T04B | Resolve frontend ESLint baseline without behavior changes | S00-T04A2 | APPROVED |

**Sprint exit:** clean checkout can install/run gates; tests leave production-root data unchanged; remaining warnings are explicitly baselined.

**Sprint status:** APPROVED — exit verified by quality-baseline run `20260803-144737` (7/7 gates PASS).

---

## EPIC E01 - Durable Domain, Persistence and Jobs

**Outcome:** one backend authority persists business state and long jobs survive restart.  
**Master Plan:** WS-00, WS-01, G1.

### Sprint S01 - Persistence foundation

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S01-T01 | Define approved SQLAlchemy domain contracts and migration policy | S00 exit | APPROVED |
| S01-T02 | Bootstrap SQLite engine/session and schema-version migrations | S01-T01 | APPROVED |
| S01-T03 | Implement managed artifact paths, atomic writes and safe Trash contract | S01-T02 | APPROVED |
| S01-T04 | Build read-only legacy JSON inventory/import preview | S01-T02 | APPROVED |
| S01-T05 | Implement transactional legacy import with backup and migration tests | S01-T03,S01-T04 | APPROVED |

**Sprint status:** APPROVED — exit verified by quality-baseline run `20260803-184034` (7/7 gates PASS).

### Sprint S02 - Durable processing

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S02-T01 | Define Job, JobStep, Artifact and error/retry state machine | S01 exit | APPROVED |
| S02-T02 | Persist job lifecycle and idempotency keys | S02-T01 | APPROVED |
| S02-T03 | Worker executes/retries/cancels jobs outside HTTP request | S02-T02 | APPROVED |
| S02-T04 | Restart reconciliation resumes or safely fails interrupted jobs | S02-T03 | APPROVED |
| S02-T05 | Job API and backend integration tests cover recovery contract | S02-T04 | APPROVED |

**Sprint status:** APPROVED — exit verified by quality-baseline run `20260804-000921` (7/7 gates PASS).

**Epic exit:** migration fixtures pass; jobs and artifacts reconcile after forced close; no durable truth relies only on RAM/frontend storage.

---

## EPIC E02 - Production Management and Product Shell

**Outcome:** users manage source/production channels, multi-video projects and resumable work.  
**Master Plan:** WS-00, WS-02, G2.

### Sprint S03 - Production management API

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S03-T01 | Channel CRUD with source/production role and validation | E01 | APPROVED |
| S03-T02 | Project CRUD with source and production channel relationships | S03-T01 | APPROVED |
| S03-T03 | Video Item lifecycle, ordering and per-video status | S03-T02 | APPROVED |
| S03-T04 | Project summary/read-model API for dashboard | S03-T03 | APPROVED |

**Sprint status:** APPROVED — exit verified by quality-baseline run `20260804-110540` (7/7 gates PASS).

### Sprint S04 - New UI shell

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S04-T01 | Establish UI tokens, layout primitives and Vietnamese product navigation | S03-T04 | APPROVED |
| S04-T02 | Home dashboard lists projects, next actions and active jobs | S04-T01 | APPROVED |
| S04-T03 | Channel management UX with empty/loading/error states | S04-T02 | APPROVED |
| S04-T04 | Project Detail manages Video Items, channels and outputs | S04-T02,S03-T04 | APPROVED |
| S04-T05 | Guided Project Shell persists step readiness and resume location | S04-T04 | APPROVED |

**Sprint status:** APPROVED — UI correction and visual QA verified by quality-baseline run `20260804-144203` (7/7 gates PASS).

**Epic exit:** Scenario H passes; a user never needs filesystem navigation to find the next Video Item.

---

## EPIC E03 - Import and Analyze

**Outcome:** an imported Video Item becomes a resumable, timebase-safe analyzed artifact.  
**Master Plan:** WS-03, G2.

### Sprint S05 - Import/analyze vertical slice

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S05-T01 | Video preflight/probe contract and actionable incompatibility errors | E02 | PLANNED |
| S05-T02 | Managed import copies/registers source safely with checksum | S05-T01 | PLANNED |
| S05-T03 | Canonical timebase/proxy plus StructuralLockManifest with exact frame and audio-stream facts | S05-T02 | PLANNED |
| S05-T04 | Stable shot IDs, scored cut candidates, camera/background classes and risk-frame manifest | S05-T03 | PLANNED |
| S05-T05 | Import/Analyze UI shows estimate, progress, cancel, retry and resume | S05-T04 | PLANNED |
| S05-T06 | Golden import/analyze integration includes the verified 2D reference fixture manifest and restart-recovery evidence | S05-T05 | PLANNED |

**Epic exit:** one Video Item imports, analyzes and resumes from the new Project Shell with stable scene/time contracts.

---

## EPIC E04 - Character Library and Cast Mapping

**Outcome:** reusable, validated and version-pinned characters work across projects/channels.  
**Master Plan:** WS-05A, G2.5.

### Sprint S06 - Character Library

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S06-T01 | Character, Pack Version, Asset and pose-slot domain/API | E01 | APPROVED |
| S06-T02 | Import existing preset assets into draft packs without mutating originals | S06-T01 | APPROVED |
| S06-T03 | Six required poses plus view/pose/anchor capability, transparency/resolution and completeness validation | S06-T02 | APPROVED |
| S06-T04 | Character Library browse/search/filter/detail UI | S06-T03,S04-T01 | APPROVED |
| S06-T05 | Pack review, publish and immutable version UX | S06-T04 | APPROVED |

**Sprint status:** APPROVED — product gate completed; S06-T05 baseline `20260805-091121` passed 7/7.

### Sprint S07 - Project cast reuse

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S07-T01 | Project Cast Mapping pins role type, Pack Version and CompatibilityPolicy version | S06 exit,E05 contract | APPROVED |
| S07-T02 | In-context picker shows per-occurrence compatibility evidence and fail-closed blockers | S07-T01 | APPROVED |
| S07-T03 | Cross-project reuse and version-isolation integration tests | S07-T02 | APPROVED |

**Sprint status:** APPROVED — independent Codex re-review 2026-08-22; no blocking follow-up for S09.

**Epic exit:** Scenario I passes; later library edits cannot silently alter prior project mappings.

---

## EPIC E05 - Object Intelligence

**Outcome:** users select video-global Object Roles rather than repeating work scene by scene.  
**Master Plan:** WS-04, G3.

### Sprint S08 - Object discovery and curation

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S08-T01 | Occurrence/Role and scene-graph schema covers character, prop, background, foreground, graphic and source-only overlay | E03 | APPROVED |
| S08-T02 | Candidate extraction stores prompts/masks, representative thumbnails, camera-relative motion and risk evidence | S08-T01 | APPROVED |
| S08-T03 | Cross-scene grouping combines visual identity with motion/interaction evidence and merge/split/confirm API | S08-T02 | APPROVED |
| S08-T04 | Object Gallery selection and confidence UX | S08-T03 | APPROVED |
| S08-T05 | Object correction actions rerun only affected dependencies | S08-T04 | APPROVED |
| S08-T06 | Golden role/group/contact/occlusion dataset and calibrated metrics report | S08-T05 | APPROVED |

**Sprint status:** APPROVED — original foundation review in `reviews/S08_SPRINT_PM_REVIEW_2026-08-19.md`; required Source-Locked taxonomy/structural-evidence bridges are the dependency baseline used by approved S07 and the S09 realignment below.

**Epic exit:** Scenarios A-B pass through object selection with actionable low-confidence handling.

---

## EPIC E06 - Reskin Demo and Apply

**Outcome:** users prove the look on representative loops before committing full-video compute.  
**Master Plan:** WS-05, G3-G4.

### Sprint S09 - Demo-first reskin

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S09-T00 | Benchmark SceneGraph/MotionContract/RendererRouter on verified risk loops and license-gate every adapter | S05 exit,E05 contract | APPROVED — J1-v4 direct 13/13, measured 6/6 risk classes retained |
| S09-T01 | Reskin Mapping pins compatibility evidence, pose/contact anchors and renderer route per segment | E04,E05,S09-T00 | APPROVED |
| S09-T02 | Implement tested pose-swap/affine route behind adaptive renderer contract; escalate by measured residual | S09-T01 | APPROVED |
| S09-T03 | Select 3-5 risk-covering demo loops and create proxy jobs | S09-T02 | APPROVED |
| S09-T04 | Demo comparison UI: original/result/split/wipe/blink | S09-T03 | APPROVED |
| S09-T05 | Demo corrections for masks, z-order, contacts, mesh/parts and route override regenerate only affected loop | S09-T04 | APPROVED |
| S09-T06 | Explicit approval pins structural/compatibility/renderer contracts in immutable apply checkpoint | S09-T05 | APPROVED — C7-R2 build/config/owned-restart acceptance independently verified |

**Execution update (2026-08-23):** Codex independently approved the S09-T00 readiness package and verified the old T01 foundation with 48/48 focused tests. A dedicated Manager prompt may now run the full S09 implementation slice: implement/benchmark T00 first, resume the exact old T01 owner, then T02..T06 in dependency order, and stop once at `SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW`. Do not silently downgrade to legacy transform-only parity.

**Codex review update (2026-08-24 21:18 +07):** full S09 is
`CHANGES_REQUESTED`. The current T02 adapters do not perform replacement-layer
reskinning and the v1 harness does not score renderer output. User đã chọn ưu
tiên tốc độ thay vì tiết kiệm quota: chạy full correction prompt
`prompts/S09_C1_FAST_TRACK_MANAGER_2026-08-24.md` với Wave A tối đa 5 worker có
write-set tách biệt, renderer/API join gates, rồi stop for Codex review. T03/T04
disk state được giữ lại nhưng chưa approved; S10 và S11 production vẫn blocked.

**Codex C1 re-review update (2026-08-25 09:50 +07):** S09 remains
`CHANGES_REQUESTED`. Current all-S09 gate is `8 failed, 318 passed`; C1 has only
4/12 measured route-fixture rows, J1 SHA drifted after its handshake, benchmark
bypasses production router/adapters, T03 durable publish fails at Windows path
length 260, and production E2E omits only-affected-loop proof. Authorized next
packet is `prompts/S09_C2_CORRECTION_MANAGER_2026-08-25.md`: five disjoint owner
lanes in Wave A, immutable full renderer freeze manifest, actual-router I03
measurement, I05 measured decision, then downstream/E2E join. S10/S11 production
remain blocked until Codex independently approves S09-C2.

**Codex C2 independent review update (2026-08-25 22:46 +07):** S09 remains
`CHANGES_REQUESTED`. C2 materially fixed the renderer and reached 6/6 measured
classes, but it did not implement correction-bound regeneration: its final E2E
fails an unmeasured route pin, reuses the old job and asserts every artifact is
unchanged. J1-v3 was pinned after loader drift while I03/I05/downstream remained
on v2, and the harness uses a second three-file freeze authority plus a
noncanonical raw-concat decoded hash. Independent current gate is
`1 failed, 362 passed`; T04 cannot serve a published artifact at a 272-character
Windows path. Authorized next packet is
`prompts/S09_C3_CORRECTION_MANAGER_2026-08-25.md`, which resumes exact owners for
durable affected-only generation, UI scope/evidence, unified J1-v4, rerun
I03/I05 and production E2E. S10, production S11 and production S13 remain
blocked until Codex approves S09-C3.

**Codex C3 independent review update (2026-08-26 09:51 +07):** S09 remains
`CHANGES_REQUESTED`. C3 materially fixed unified freeze/canonical hash,
long-path serving and durable regeneration plumbing; Codex re-hashed J1-v4
13/13 clean and independently got 51/51 focused backend tests, Ruff, TSC and
Alembic one head. However the production QA DB disproves affected-only
acceptance: the formal job requested and rendered all four loops
(`regenerated=true` for d1-d4; d1/d2/d3 merely produced byte-identical files).
The UI returns all `completedLoops`, z-order always edits `placements[0]`, four
other correction kinds have no real render-effect dispatcher, the fingerprint
omits frozen-evidence SHA and T06B never asserts per-loop regenerated state.
Review: `reviews/S09_C3_PM_REVIEW_2026-08-26.md`. Authorized packet:
`prompts/S09_C4_CORRECTION_MANAGER_2026-08-26.md`, resuming the exact
T05A/T03/T04/T05B/T06B owners. S10, production S11 and production S13 remain
blocked until Codex independently approves S09-C4.

**Codex C5 independent review update (2026-08-27):** S09 remains
`CHANGES_REQUESTED`, but the product backend is now materially green: Codex
independently obtained T03 40/40, T04 24/24 with a real >=260-character path,
T06 backend 43/43, plus Ruff/mypy/TSC/scoped ESLint passes. Exit is blocked by
acceptance integrity: J1-v4 direct hash is only 6/13 after CRLF recurrence;
Chromium restart force-kills an unverified port owner and leaks its replacement;
the two runs reuse one hard-coded runtime/DB/output and Run2 lacks complete raw
evidence. Review: `reviews/S09_C5_PM_REVIEW_2026-08-27.md`. Authorized bounded
packet: `prompts/S09_C6_EXIT_HARDENING_MANAGER_2026-08-27.md`; one new
EOL-guard task plus exact T03/T06B owner corrections. No S10/S11/S13 production
work opens before Codex approves C6.

**Codex C6 independent review update (2026-08-27):** S09 remains
`CHANGES_REQUESTED`, although the remaining scope is now only T06B acceptance
lifecycle. Codex directly confirmed J1-v4 13/13, coherent-evidence proof PASS,
T06 backend 43/43, TSC and scoped ESLint; Run1/Run2 also have distinct roots and
DBs. The blocker is a false restart: `primaryLaunched` is null when Phase G calls
`stopLaunched`, while the original backend was launched by an external runner;
the replacement can collide with the old listener and readiness still succeeds
against the old process. Cleanup is not fail-closed and active C4 fallbacks
remain. Review: `reviews/S09_C6_PM_REVIEW_2026-08-27.md`. Authorized bounded
packet: `prompts/S09_C7_OWNED_RESTART_CORRECTION_MANAGER_2026-08-27.md`; resume
only T06B owner `20260824_131423_423e42`. S10 and other production lanes remain
blocked until Codex approves C7.

**Codex C7 independent review update (2026-08-27):** C7 materially closes the
C6 process-lifecycle defect: exact initial/replacement listener ownership,
ordered stop/relaunch, durable checkpoint read and fail-closed cleanup are real;
J1-v4 13/13, T06 backend 43/43, TSC and scoped ESLint remain green. S09 still
cannot close because the current post-run `.next` bakes API port 8888 while the
launcher trusts BUILD_ID existence; Codex's fresh isolated Chromium run failed
before the product flow at `(không có project)`. The launcher also retains
C4/C6 fixture fallbacks and `npx`/`shell:true`. Review:
`reviews/S09_C7_PM_REVIEW_2026-08-27.md`. Authorized same-round continuation:
`prompts/S09_C7_R1_REPRODUCIBLE_BUILD_CONTINUATION_MANAGER_2026-08-27.md`;
resume only the exact T06B owner. No C8 and no other production lane.

**Codex C7-R1 independent review update (2026-08-27):** the two R1 Chromium
runs, lifecycle and direct DB truth are green: one completed render attempt for
d4 only, exact reuse of d1-d3, checkpoint survives exact owned restart. Current
build hashes match 182/182; fixture 21/21; J1 13/13, T06 backend 43/43, TSC and
ESLint pass. S09 still cannot close because R1 changed the normal frontend proxy
fallback from 8888 to test port 8201 outside its write set, while the launcher
still reuses `.next` on BUILD_ID alone and cannot accept safe explicit fresh
roots. Review: `reviews/S09_C7_R1_PM_REVIEW_2026-08-27.md`. Authorized narrow
same-C7 continuation:
`prompts/S09_C7_R2_FINAL_CONFIG_BUILD_INTEGRITY_MANAGER_2026-08-27.md`. Resume
only the exact T06B owner; no backend/product-flow rewrite and no other lane.

**Codex C7-R2 final review update (2026-08-27 21:40 +07):** R2 restored the
normal 8888 frontend fallback, replaced BUILD_ID-only reuse with a seven-check
content/input/build validator and accepted arbitrary safe fresh runtime/output
roots. Codex independently passed J1 13/13, T06 backend 43/43, TSC/ESLint,
direct DB affected-only probes and a third fresh Chromium run with exact owned
restart and cleanup. `S09 = CODEX_APPROVED / CLOSED`. Review:
`reviews/S09_C7_R2_FINAL_PM_REVIEW_2026-08-27.md`. Three documentation/parser
P2 items are carried forward without opening C8.

### Sprint S10 - Full apply

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S10-T01 | Shot/layer chunked full-video reskin job with overlap, deterministic checkpoint and resume | S09 exit | READY — authorized full-sprint packet 2026-08-27 |
| S10-T02 | Multi-role mappings process independently while preserving contact/z-order edges | S10-T01 | INTRA_SPRINT_BLOCKED_ON_T01_MANAGER_GATE |
| S10-T03 | Partial recompute preserves approved/unaffected segments | S10-T02 | INTRA_SPRINT_BLOCKED_ON_T02_MANAGER_GATE |
| S10-T04 | End-to-end Demo→Apply restart plus frame/cut/trajectory/contact regression evidence | S10-T03 | INTRA_SPRINT_BLOCKED_ON_T03_MANAGER_GATE |

**Execution authority (2026-08-27):** Codex packet
`prompts/S10_FULL_APPLY_MANAGER_2026-08-27.md` freezes eight owner sessions and
the exact internal DAG. Only T01A/T01B may write in parallel; shared
workflow/API/schema integration is serialized. Hermes must stop once at
`SPRINT_SUBMITTED / PENDING_CODEX_REVIEW`.

**Epic exit:** Scenarios A-E pass; no full apply begins without explicit Demo approval.

---

## EPIC E07 - Review and Original Audio

**Outcome:** users review only actionable problems while source audio remains synchronized.  
**Master Plan:** WS-06, WS-07, G4.

### Sprint S11 - QC and original audio

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S11-T01 | Original audio remux/codec fallback consumes S05 stream facts and preserves source synchronization | E03 | APPROVED — Codex direct review 2026-08-23, 64/64 suite |
| S11-T02 | QCItem domain normalizes visual/audio/timecode issues | E06,S11-T01 | BLOCKED_DEPENDENCY |
| S11-T03 | Structural drift, contact, z-order, clipping, identity/flicker and A/V checks create QC items | S11-T02 | BLOCKED_DEPENDENCY |
| S11-T04 | Review Queue navigates issue, correction and affected rerun | S11-T03 | BLOCKED_DEPENDENCY |
| S11-T05 | Readiness gate blocks only unresolved blockers | S11-T04 | BLOCKED_DEPENDENCY |
| S11-T06 | Original-audio and targeted-review acceptance suite | S11-T05 | BLOCKED_DEPENDENCY |

**Current gate (2026-08-27 21:40 +07):** S11-T01 is APPROVED. S11-P02 rev-C5 is `CHANGES_REQUESTED`; correction C6 must resume synthesis owner `20260823_145947_057312`. S09 is now approved, but T02..T06 remain blocked on E06/S10 Full Apply exit and P02 approval. Readiness correction may run docs-only in a separate lane; production S11 must not overlap S10.

**Epic exit:** unchanged source voice/BGM/SFX play in sync; Scenario D works without reviewing the full timeline.

---

## EPIC E08 - Validated 4K Delivery and Packaging

**Outcome:** approved projects render, resume and validate a clearly labeled 4K master.  
**Master Plan:** WS-08, WS-09, G5.

### Sprint S12 - 4K beta candidate

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S12-T01 | Export preflight distinguishes native 4K from upscale | E07 | PLANNED |
| S12-T02 | GPU/CPU render profiles and capability detection | S12-T01 | PLANNED |
| S12-T03 | Chunked render, stitch and restart-safe checkpoint | S12-T02 | PLANNED |
| S12-T04 | Output validation covers StructuralLockManifest, resolution, frames/timebase, streams and partial files | S12-T03 | PLANNED |
| S12-T05 | Export UI shows estimate/progress/retry/result and evidence | S12-T04 | PLANNED |
| S12-T06 | Clean-machine packaging and supported hardware matrix | S12-T05 | PLANNED |

**Epic exit:** Scenarios F-G pass and a `.partial` artifact is never shown as completed output.

---

## EPIC E09 - Guided 2D Character Generator

**Outcome:** one simple 2D reference becomes a human-reviewed six-pose library pack without training.  
**Master Plan:** WS-05B, G4.5.

### Sprint S13 - Generator alpha

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S13-P00 | Readiness package: dependency proof, domain/provider/validation contracts, write-set matrix and task packets | E04 | APPROVED — Codex C6 re-review 2026-08-23; binding 22-task planning baseline |
| S13-T01 | Character Profile and stable reference-code prompt contract | E04,S13-P00 | READY_BY_DEPENDENCY / NOT_DISPATCH_AUTHORIZED — S09 closed, but serialize shared schema/API paths behind active-authorized S10 |
| S13-T02 | ComfyUI/provider adapter with capability and failure contracts | S13-T01 | PLANNED |
| S13-T03 | Pose-conditioned six-panel generation job | S13-T02,E01 | PLANNED |
| S13-T04 | Identity/style/pose validation and panel status | S13-T03 | PLANNED |
| S13-T05 | Guided upload→profile→generate→review UI | S13-T04 | PLANNED |
| S13-T06 | Regenerate one panel and preserve approved panels | S13-T05 | PLANNED |
| S13-T07 | Publish complete approved output as immutable Pack Version | S13-T06 | PLANNED |
| S13-T08 | Scenario J quality/performance benchmark report | S13-T07 | PLANNED |

**Execution update (2026-08-23 23:20 +07):** S13-P00 C6 is Codex
`APPROVED`; no P0/P1/P2 finding remains. Production S13 is still `NOT_OPENED`
because S09 I02/I03 is active in the shared integration worktree and later S09
write-sets overlap early S13 schema/migration/router paths. The existing
`prepare-s13-t01` worktree is behind the integration HEAD. The current Hermes
prompt is preflight/wait-only; a new Codex production prompt is required after
the integration lane is stable.

### S13 mandatory identity-quality requirements

These requirements are inherited by every S13 implementation task and may not be
weakened by a provider-specific shortcut:

- Separate immutable `Character Identity` from versioned pose-pack candidates and
  published `Pack Version`; projects pin the exact published version they use.
- Generate and review one slot at a time from the same reference hash, identity-profile
  hash, prompt-template version and reproducibility metadata. Only pose/camera variables
  may change between slots.
- Each slot follows `GENERATING -> REVIEW_REQUIRED | REJECTED | APPROVED -> SUPERSEDED`.
  Regenerating one slot preserves all other approved slots.
- Publish is fail-closed: all six required slots must pass hard integrity/topology checks
  and explicit human approval. Uncertain or near-threshold results are
  `REVIEW_REQUIRED`, never silent `PASS`.
- Validation covers real transparency, SHA-256/size/resolution, silhouette, palette,
  landmark/proportion, limb topology, line weight/style, clothing/accessories,
  cross-view identity, unwanted text/watermark/background and crop completeness.
- Every compositing-ready slot has a consistent canvas, scale, facing direction,
  ground/contact anchor and bounding box; no cropped limbs or unexplained position/scale
  jump is allowed across views.
- Review UI keeps the original reference visible and supports zoom plus
  overlay/blink/wipe comparison, validation reasons, candidate history and single-slot
  regeneration.
- Every candidate records reference/profile hashes, provider/model/adapter version,
  seed, final prompt, generation settings, template version and approval audit data.
- V1 is deliberately limited to simple flat-color 2D stick/doodle characters with clear
  outlines and standard two-arm/two-leg topology. Complex anime, photoreal, 3D,
  gradients and texture-heavy styles remain unsupported until benchmark evidence exists.
- S13-T08 must use a 20-40 character golden set with approved six-slot truth, controlled
  variations and negative identity-drift examples. The primary metric is false-accept
  rate, followed by review/regeneration rate, repeatability, latency and cost per pack.

**Epic exit:** generator failure cannot block manual library usage; only complete reviewed packs can be published.

---

## Task activation rules

- Chỉ một task ở trạng thái `IN_PROGRESS` trừ khi PM chủ động cho phép parallel work với write scopes không giao nhau.
- Task chỉ chuyển `PLANNED -> READY` khi mọi dependency đã `APPROVED` và PM đã tạo session packet.
- Sprint/epic exit là task review riêng nếu evidence phân tán; không tự suy ra từ việc các PR đã merge.
- Thứ tự E04 và E05 có thể overlap sau khi contract ObjectRole tối thiểu được approve; `S07-T01` vẫn chờ contract đó.
- E09 có thể chạy sau E04 nhưng mặc định đặt sau beta reskin để không làm trễ core value.
- Ngoại lệ đã cấp quyền 2026-08-22: `S13-P00` readiness-only được chạy song song với S09/S11 vì chỉ ghi output riêng. Không task production S13 nào được mở trước Codex review P00 và một prompt cấp quyền mới.
