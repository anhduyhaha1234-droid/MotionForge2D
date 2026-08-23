# MotionForge 2D - Epic, Sprint and Task Roadmap

**Planning model:** outcome-based, dependency-gated  
**Execution rule:** one Task ID = one Hermes chat/session  
**Estimate unit:** session-sized, not calendar commitment

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

**Sprint status:** APPROVED — Codex PM review; UI quality-baseline `20260804-144203` (7/7 PASS).

**Epic exit:** Scenario H passes; a user never needs filesystem navigation to find the next Video Item.

---

## EPIC E03 - Import and Analyze

**Outcome:** an imported Video Item becomes a resumable, timebase-safe analyzed artifact.  
**Master Plan:** WS-03, G2.

### Sprint S05 - Import/analyze vertical slice

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S05-T01 | Video preflight/probe contract and actionable incompatibility errors | E02 | APPROVED |
| S05-T02 | Managed import copies/registers source safely with checksum | S05-T01 | APPROVED |
| S05-T03 | Canonical timebase and proxy artifact generation | S05-T02 | APPROVED |
| S05-T04 | Scene detection job uses stable Scene IDs and removes deprecated frame access | S05-T03 | APPROVED |
| S05-T05 | Import/Analyze UI shows estimate, progress, cancel, retry and resume | S05-T04 | APPROVED |
| S05-T06 | Golden import/analyze integration and restart-recovery evidence | S05-T05 | APPROVED |

**Epic exit:** one Video Item imports, analyzes and resumes from the new Project Shell with stable scene/time contracts.

**Sprint status:** APPROVED — final correction S05-C04 closed by Codex PM
review; independent 41/41 targeted tests and fresh quality baseline
`20260805-214242` (7/7 PASS).

---

## EPIC E04 - Character Library and Cast Mapping

**Outcome:** reusable, validated and version-pinned characters work across projects/channels.  
**Master Plan:** WS-05A, G2.5.

### Sprint S06 - Character Library

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S06-T01 | Character, Pack Version, Asset and pose-slot domain/API | E01 | APPROVED |
| S06-T02 | Import existing preset assets into draft packs without mutating originals | S06-T01 | APPROVED |
| S06-T03 | Six required poses, transparency/resolution and completeness validation | S06-T02 | APPROVED |
| S06-T04 | Character Library browse/search/filter/detail UI | S06-T03,S04-T01 | APPROVED |
| S06-T05 | Pack review, publish and immutable version UX | S06-T04 | APPROVED |

**Sprint status:** APPROVED — S06-T01..T04 approved per sprint; S06-T05 correction approved by Codex PM review 2026-08-05T09:28:00+07:00 (quality baseline `20260805-091121` 7/7 PASS). Sprint S06 complete at the product gate; integrated into the S08-P00 base (2026-08-05).

### Sprint S07 - Project cast reuse

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S07-T01 | Project Cast Mapping domain/API pins Object Role to Pack Version | S06 exit,E05 contract | PLANNED |
| S07-T02 | In-context library picker and compatibility warnings | S07-T01 | PLANNED |
| S07-T03 | Cross-project reuse and version-isolation integration tests | S07-T02 | PLANNED |

**Epic exit:** Scenario I passes; later library edits cannot silently alter prior project mappings.

---

## EPIC E05 - Object Intelligence

**Outcome:** users select video-global Object Roles rather than repeating work scene by scene.  
**Master Plan:** WS-04, G3.

### Sprint S08 - Object discovery and curation

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S08-T01 | ObjectOccurrence/ObjectRole schema with stable IDs and confidence | E03 | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW (C1+C2) |
| S08-T02 | Candidate extraction job stores representative thumbnails/masks | S08-T01 | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW (C1+C2) |
| S08-T03 | Cross-scene grouping suggestions with merge/split/confirm API | S08-T02 | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW (C1+C2) |
| S08-T04 | Object Gallery selection and confidence UX | S08-T03 | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW (C1+C2) |
| S08-T05 | Object correction actions rerun only affected dependencies | S08-T04 | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW (C1+C2) |
| S08-T06 | Golden grouping/correction dataset and metrics report | S08-T05 | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW (C1+C2: final golden vertical Run `20260818-s08t06-c2`, fresh 7/7 baseline Run `20260819-004409`) |
| S08-R01 | Runtime lifecycle safety (queued cancel, absolute root, QA fail-closed) | — | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW |
| S08-H01 | Frontend production authority (no fabricated fallback) | — | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW |
| S08-H02 | Local API origin/upload/media safety (C1 recovered: server-owned storage, real probe, atomicity, containment) | — | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW (C1 recovery 2026-08-19) |
| S08-H02-C2 | Preset path containment + bounded video_probe (C2: client preset name/path traversal + unbounded ffprobe stdout) | — | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW (2026-08-19, baseline Run `20260819-015528` 7/7 PASS) |
| S08-H02-C3 | Probe deadline + preset root containment + preset collision (C3: concurrent probe drain <1s deadline, preset root symlink/junction 422 anchored, collision 409 no-overwrite) | — | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW (2026-08-19, session `20260819_033728_0a3c30`, baseline Run `20260819-041116` 7/7 PASS) |
| S08-H02-C4 | Atomic preset + exact probe bounds (C4: O_EXCL atomic preset no race, binary byte-cap before decode, max(0,deadline-monotonic) waits, deterministic concurrency test) | — | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW (2026-08-19, session `20260819_105751_c6c6a1`, baseline Run `20260819-114525` 7/7 PASS) |
| S08-H02-C4-C5 | Atomic combined pipe cap + cleanup deadline budgets (C5: atomic _CaptureState accept/reject overshoot ≤1 chunk, shared remaining_budget(deadline), no fixed 5s windows, no child leak) | — | SUBMITTED → MANAGER_VERIFIED_PENDING_SPRINT_REVIEW (2026-08-19, resume same session `20260819_105751_c6c6a1`, baseline Run `20260819-133623` 7/7 PASS) |

**Sprint status (2026-08-19, after H02-C5 correction):** SPRINT_SUBMITTED — all correction rounds incl. H02-C4-C5 MANAGER_VERIFIED_PENDING_SPRINT_REVIEW; fresh 7/7 baseline Run `20260819-133623` PASS; golden metrics contract SHA `f008c027…`; all writers stopped; ports free; protected MAIN unchanged. Awaiting ONE Codex sprint-exit review — Hermes never writes APPROVED/CLOSED.

**Epic exit:** Scenarios A-B pass through object selection with actionable low-confidence handling.

---

## EPIC E06 - Reskin Demo and Apply

**Outcome:** users prove the look on representative loops before committing full-video compute.  
**Master Plan:** WS-05, G3-G4.

### Sprint S09 - Demo-first reskin

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S09-T01 | Reskin Mapping and pinned pose/anchor/scale contracts | E04,E05 | PLANNED |
| S09-T02 | Extract reusable transform/compositing math from legacy UI with tests | S09-T01 | PLANNED |
| S09-T03 | Select 3-5 representative demo loops and create proxy jobs | S09-T02 | PLANNED |
| S09-T04 | Demo comparison UI: original/result/split/wipe/blink | S09-T03 | PLANNED |
| S09-T05 | Demo correction controls regenerate only affected loop | S09-T04 | PLANNED |
| S09-T06 | Explicit approval creates immutable apply checkpoint | S09-T05 | PLANNED |

### Sprint S10 - Full apply

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S10-T01 | Chunked full-video reskin job with checkpoint/resume | S09 exit | PLANNED |
| S10-T02 | Multi-object mappings process independently in one batch | S10-T01 | PLANNED |
| S10-T03 | Partial recompute preserves approved/unaffected segments | S10-T02 | PLANNED |
| S10-T04 | End-to-end Demo→Apply restart and regression evidence | S10-T03 | PLANNED |

**Epic exit:** Scenarios A-E pass; no full apply begins without explicit Demo approval.

---

## EPIC E07 - Review and Original Audio

**Outcome:** users review only actionable problems while source audio remains synchronized.  
**Master Plan:** WS-06, WS-07, G4.

### Sprint S11 - QC and original audio

| Task ID | Session outcome | Depends on | Status |
|---|---|---|---|
| S11-T01 | Original audio stream mapping/remux contract and codec fallback | E03 | PLANNED |
| S11-T02 | QCItem domain normalizes visual/audio/timecode issues | E06,S11-T01 | PLANNED |
| S11-T03 | Automated visual anomaly and A/V sync checks create QC items | S11-T02 | PLANNED |
| S11-T04 | Review Queue navigates issue, correction and affected rerun | S11-T03 | PLANNED |
| S11-T05 | Readiness gate blocks only unresolved blockers | S11-T04 | PLANNED |
| S11-T06 | Original-audio and targeted-review acceptance suite | S11-T05 | PLANNED |

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
| S12-T04 | Output validation covers resolution, duration, streams and partial files | S12-T03 | PLANNED |
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
| S13-T01 | Character Profile and stable reference-code prompt contract | E04 | PLANNED |
| S13-T02 | ComfyUI/provider adapter with capability and failure contracts | S13-T01 | PLANNED |
| S13-T03 | Pose-conditioned six-panel generation job | S13-T02,E01 | PLANNED |
| S13-T04 | Identity/style/pose validation and panel status | S13-T03 | PLANNED |
| S13-T05 | Guided upload→profile→generate→review UI | S13-T04 | PLANNED |
| S13-T06 | Regenerate one panel and preserve approved panels | S13-T05 | PLANNED |
| S13-T07 | Publish complete approved output as immutable Pack Version | S13-T06 | PLANNED |
| S13-T08 | Scenario J quality/performance benchmark report | S13-T07 | PLANNED |

**Epic exit:** generator failure cannot block manual library usage; only complete reviewed packs can be published.

---

## Task activation rules

- Chỉ một task ở trạng thái `IN_PROGRESS` trừ khi PM chủ động cho phép parallel work với write scopes không giao nhau.
- Task chỉ chuyển `PLANNED -> READY` khi mọi dependency đã `APPROVED` và PM đã tạo session packet.
- Sprint/epic exit là task review riêng nếu evidence phân tán; không tự suy ra từ việc các PR đã merge.
- Thứ tự E04 và E05 có thể overlap sau khi contract ObjectRole tối thiểu được approve; `S07-T01` vẫn chờ contract đó.
- E09 có thể chạy sau E04 nhưng mặc định đặt sau beta reskin để không làm trễ core value.

| S05-C01 | Approved-pipeline orchestration + successor retry (correction) | S05-T05 | SUBMITTED (Codex CHANGES_REQUESTED → S05-C02) |
| S05-C02 | Durable chain progression correction (read-only GET, orchestrator-owned chain, source-SHA identity) | S05-C01 | SUBMITTED (sprint-exit review pending; baseline 7/7 `20260805-163430`) |

_S05-C02 correction (2026-08-05, appended — do not rewrite history): chain
progression moved from the projects route into_
`app/workflow/analyze_orchestrator.py`_; GET /analyze strictly read-only;
chain identity bound to source SHA-256 + generation; evidence in_
`docs/pm/sessions/S05-C02-durable-chain-progression/REPORT.md`_.


S05-C03 correction (2026-08-05, appended — do not rewrite history): Codex
CHANGES_REQUESTED round 3 (S05-C02 review) — orchestrator start/stop wired
into the real FastAPI lifespan with a startup scan-and-resume (no
POST/GET/browser/manual advance); TRUE process-lifecycle test (restart
after import, restart after proxy, zero analyze API calls); source
replacement with a different SHA now performs an explicit VideoItem/version
supersession (old VideoItem archived, jobs/artifacts/scenes byte-identical
immutable, new VideoItem distinct identity + outputs, new chain COMPLETES,
chain state exposes only the current source); GET read-only + all C02
concurrency/retry guarantees preserved. Evidence:
`docs/pm/sessions/S05-C03-final-lifecycle-correction/REPORT.md`_. Status:
SUBMITTED (never APPROVED).

S05-C04 final correction (2026-08-05, appended — do not rewrite history):
production `JobService` wiring, authoritative lifecycle binding, atomic current-
step chain cancellation, isolated default-binding coverage and corrected
desktop/390px completion evidence. Codex decision: APPROVED and CLOSED. Evidence:
`docs/pm/sessions/S05-C04-production-job-service-wiring/PM_REVIEW.md`; fresh
quality baseline `20260805-214242` (7/7 PASS).
