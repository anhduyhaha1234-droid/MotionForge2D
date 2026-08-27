# MotionForge2D — Codex PM Session Handoff

Đọc file này đầu tiên khi tiếp quản bằng một Codex chat/session mới. Đây là
checklist phục hồi ngữ cảnh; TASK hiện hành, filesystem và process thực tế vẫn
là nguồn sự thật. Không dựa riêng vào lịch sử chat hoặc lời tóm tắt của Hermes.

Trước file này, bắt buộc đọc toàn bộ
`C:\Users\Admin\MotionForge2D\docs\pm\HERMES_AUTOPILOT_RULES.md`. Rules là
canonical cho orchestration; file handoff này chỉ giữ trạng thái điều hành và
không được dùng để ghi đè rules.

### Live update — 2026-08-27 21:40 +07 (Codex S09-C7-R2 final review)

- `S09-C7-R2 = CODEX_APPROVED / CLOSED`; toàn Sprint `S09 = CODEX_APPROVED /
  CLOSED`. Không còn P0/P1.
- Codex độc lập xác nhận build validator 7/7 trên BUILD_ID
  `dm7D7QTAc52eVVVHqU09Y`, 185 file/hash, manifest SHA `c606d99b...`; J1-v4
  direct 13/13; exact T06 backend 43/43; TSC, scoped ESLint và diff-check xanh.
- Direct SQLite trên cả hai R2 DB chứng minh đúng một renderer attempt, chỉ d4
  regenerated và d1-d3 exact reuse. Codex còn chạy một Chromium acceptance mới
  trên explicit fresh temp roots: 1 passed (41.4s), owned restart
  `28784 -> 18924`, checkpoint read sau restart, all owned processes exited và
  ports 3115/8201/8212 released; unrelated 3014/8099 preserved.
- Ba P2 không chặn được carry forward: `REPORT-C7.md` chưa append R2, per-run
  `env.json` chưa ghi BUILD_ID/manifest SHA, parser chưa reject positional
  garbage. Không mở C8 chỉ để sửa documentation/harness polish.
- Review:
  `docs/pm/reviews/S09_C7_R2_FINAL_PM_REVIEW_2026-08-27.md`.
- S10 Full Apply là production lane kế tiếp và đã được Codex chia thành tám
  owner packets. Prompt:
  `docs/pm/prompts/S10_FULL_APPLY_MANAGER_2026-08-27.md`.
- S11-T02..T06 vẫn blocked trên E06 cho tới S10 exit; production S13 vẫn không
  mở song song vì overlap `models.py`, migrations, `app/api/app.py` và
  integration state với S10.

### Live update — 2026-08-27 (Codex S09-C7-R1 independent review)

- `S09-C7-R1 = CHANGES_REQUESTED`; corrected terminal is
  `S09-C7-R2 = BLOCKED_WITH_FINDINGS / PENDING_CODEX_REVIEW`. This remains
  inside C7, not C8. S09 is not APPROVED/CLOSED; S10, production S11 and
  production S13 remain blocked.
- Product evidence is now materially green: both Chromium runs passed with
  real owned restart; direct DB probes show one attempt rendering d4 only and
  exact reuse of d1-d3; build chunks currently match 182/182; fixture is 21/21;
  independent J1 is 13/13, T06 backend 43/43, TSC and ESLint pass.
- P1 product/config blocker: R1 changed shared `frontend/next.config.ts` outside
  its write set and made test port 8201 the no-env application fallback. Normal
  product authorities still use 8888. Restore env-driven rewrite with 8888
  fallback; C7 build continues to inject 8201 explicitly.
- P1 harness blocker: `run-c7.js` still reuses a build when BUILD_ID alone
  matches and still hard-codes/deletes only run1/run2 roots. This contradicts
  the terminal claim and prevents safe fresh-root independent reproduction.
- P2: direct current `git diff --check` finds an extra blank EOF in the S09
  registry despite the report's exit-0 claim.
- Review: `docs/pm/reviews/S09_C7_R1_PM_REVIEW_2026-08-27.md`.
- Only authorized next packet:
  `docs/pm/prompts/S09_C7_R2_FINAL_CONFIG_BUILD_INTEGRITY_MANAGER_2026-08-27.md`.
  Resume Manager `20260827_020702_b17b35` and exact T06B owner
  `20260824_131423_423e42`, model `meta`, reasoning max. No backend/product-flow
  rewrite and no other sprint production.

### Live update — 2026-08-27 (Codex S09-C7 independent review)

- `S09-C7 = CHANGES_REQUESTED`; corrected terminal is
  `S09-C7-R1 = BLOCKED_WITH_FINDINGS / PENDING_CODEX_REVIEW`. This is a bounded
  continuation inside C7, not C8. S09 is not APPROVED/CLOSED; S10, production
  S11 and production S13 remain blocked.
- Retained green: owned initial/replacement backend lifecycle is now real;
  Run1/Run2 lifecycle and product evidence are coherent; independent J1-v4 is
  13/13, T06 backend is 43/43, TSC and scoped ESLint pass. Independent failure
  cleanup also released exact PIDs and ports 3115/8201/8212.
- P1 blocker: current `.next` was rebuilt at 18:59 after the passing C7 runs,
  contains `http://localhost:8888` in 26 files and contains zero required 8201
  URL. `run-c7.js` trusts only BUILD_ID existence, so Codex's fresh Chromium
  run reached the wrong backend and failed at `(không có project)`.
- P1 launcher gap: active C4/C6 fixture fallback remains, and Next/Playwright
  still run through `npx` plus `shell:true`; REPORT-C7 does not reconcile those
  facts or the post-run build.
- Review: `docs/pm/reviews/S09_C7_PM_REVIEW_2026-08-27.md`.
- Only authorized next packet:
  `docs/pm/prompts/S09_C7_R1_REPRODUCIBLE_BUILD_CONTINUATION_MANAGER_2026-08-27.md`.
  Resume Manager `20260827_020702_b17b35` and exact T06B owner
  `20260824_131423_423e42`, model `meta`, reasoning max. No backend/product
  rewrite and no other sprint production.

### Live update — 2026-08-27 (Codex S09-C6 independent review)

- `S09-C6 = CHANGES_REQUESTED`; corrected terminal is
  `BLOCKED_WITH_FINDINGS / PENDING_CODEX_REVIEW`. S09 is not APPROVED/CLOSED;
  S10, production S11 and production S13 remain blocked.
- Retained green under Codex rerun: J1-v4 direct 13/13 with 12 LF + composite
  CRLF guard; coherent frozen-evidence test PASS; T06 backend 43/43; TSC and
  scoped ESLint PASS; Run1/Run2 use distinct runtime roots and DBs.
- P0 acceptance blocker: the spec calls `stopLaunched(primaryLaunched)` while
  `primaryLaunched` is still null. The original backend belongs to external
  `run-prod.js`; the attempted replacement may collide with port 8201 while the
  health probe still reaches the original process. The claimed checkpoint
  restart is therefore not proven.
- P1: runner cleanup can resolve without process exit, manual taskkill appears
  in the worker report, Next uses an unowned shell wrapper, and global setup /
  config retain C4 runtime/seeder fallbacks.
- Review: `docs/pm/reviews/S09_C6_PM_REVIEW_2026-08-27.md`.
- Only authorized next packet:
  `docs/pm/prompts/S09_C7_OWNED_RESTART_CORRECTION_MANAGER_2026-08-27.md`.
  Resume only T06B owner `20260824_131423_423e42` with exact model `meta`,
  reasoning max. No backend/product rewrite and no other sprint production.

### Live update — 2026-08-27 (Codex S09-C5 independent review)

- `S09-C5 = CHANGES_REQUESTED`; corrected terminal là
  `BLOCKED_WITH_FINDINGS / PENDING_CODEX_REVIEW`. S09 chưa APPROVED/CLOSED; S10,
  production S11 và production S13 vẫn blocked.
- Backend correction is materially green under independent rerun: T03 40/40,
  T04 24/24 including >=260-char path, T06 backend 43/43, Ruff/mypy/TSC/scoped
  ESLint pass.
- P1 blockers: J1-v4 direct bytes are 6/13 because seven files reverted to
  CRLF and no `.gitattributes` protects the manifest; Chromium restart kills an
  unverified listener on 8201 and leaks the replacement handle; Run1/Run2 reuse
  one hard-coded runtime/DB/output and Run2 lacks complete raw evidence.
- P2: “different verified evidence” flips only a declared SHA and accepts any
  404/409/422; J3 evidence directory omits several claimed logs.
- Review: `docs/pm/reviews/S09_C5_PM_REVIEW_2026-08-27.md`.
- Only authorized next packet:
  `docs/pm/prompts/S09_C6_EXIT_HARDENING_MANAGER_2026-08-27.md`. C6 runs one new
  EOL-guard task plus exact T03/T06B corrections; no other sprint opens.

### Live update — 2026-08-27 (Codex S09-C4 independent review)

- `S09-C4 = CHANGES_REQUESTED`; corrected terminal là
  `BLOCKED_WITH_FINDINGS / PENDING_CODEX_REVIEW`. S09 chưa APPROVED/CLOSED; S10,
  production S11 và production S13 vẫn blocked.
- Retained green: J1-v4 SHA `ae92247b...` re-hash 13/13, T06 backend 43 passed,
  frontend TSC và scoped ESLint pass.
- Independent blockers: T04 long-path run `22 passed, 1 failed`; zero-mutation
  collision test permits committed junk lineage; frozen identity includes
  filesystem path; Chromium production E2E is not reproducible from normal
  Windows Node/PowerShell launcher; Ruff has six errors and mypy one error.
- Manager evidence/state was not reconciled and old task-owned QA processes
  remained. Manager/worker scope boundaries must be restored.
- Review: `docs/pm/reviews/S09_C4_PM_REVIEW_2026-08-27.md`.
- Only authorized next packet:
  `docs/pm/prompts/S09_C5_FINAL_CORRECTION_MANAGER_2026-08-27.md` revision C5-R2;
  resume exact T03/T04/T06B owners in one disjoint PREP wave with Hermes
  model/combo `meta`, reasoning max, then enforce full quiescence and serialized
  integration/correction/production gates. No other sprint production work is
  opened.

### Live update — 2026-08-26 09:51 +07 (Codex S09-C3 independent review)

- `S09-C3 = CHANGES_REQUESTED`; corrected terminal là
  `BLOCKED_WITH_FINDINGS / PENDING_CODEX_REVIEW`. Không APPROVED/CLOSED/push;
  S10, production S11 và production S13 vẫn blocked.
- C3 giữ được các cải thiện thật: J1-v4 manifest SHA `ae92247b...` re-hash 13/13
  zero drift; I03 run-A `12de1345...`, run-B `dab37e41...`, I05 decision
  `d289929d...`; long-path/content/freeze chain hiện không phải blocker.
- Independent focused T03/T04/T05A-C3 suite `51 passed`; Ruff reviewed
  write-set, frontend TSC, Alembic one head `b3c4d5e6f7a9` và diff-check xanh.
- P0 runtime repro từ chính production QA DB: regeneration job
  `d2bad83e-9a89-4387-ad51-97ad7436dcba` requested/affected cả d1-d4 và ghi
  `regenerated=true` cho cả bốn; render_ms d1=764, d2=375, d3=687, d4=625.
  Artifact d1-d3 giống base chỉ vì byte-identical rerender, không phải reuse.
- Root causes: `CorrectionPanel` trả toàn bộ completed loops; T06B chỉ so
  artifact identity. T03 z-order luôn sửa `placements[0]`, bỏ qua affected layer;
  four non-z kinds không có real effect dispatcher; fingerprint thiếu frozen
  evidence SHA; worker workspace guard self-compares và không có tác dụng.
- Review record:
  `docs/pm/reviews/S09_C3_PM_REVIEW_2026-08-26.md`.
- Next authorized packet:
  `docs/pm/prompts/S09_C4_CORRECTION_MANAGER_2026-08-26.md`. Resume exact
  T05A/T03/T04/T05B/T06B owners theo Wave A; không rerun I03/I05 nếu J1-v4
  không drift. Không mở sprint khác.

### Live update — 2026-08-25 22:46 +07 (Codex S09-C2 independent review)

- `S09-C2 = CHANGES_REQUESTED`; corrected terminal là
  `BLOCKED_WITH_FINDINGS / PENDING_CODEX_REVIEW`. Không APPROVED/CLOSED/push;
  S10, production S11 và production S13 chưa được mở.
- P0 product gap: production correction confirm không tạo durable targeted
  regeneration. C2 E2E cố ý làm route pin fail rồi replay job cũ và assert mọi
  loop, kể cả affected loop, không đổi; đó là zero regeneration, trái binary
  acceptance “affected generation mới / unaffected exact reuse”.
- P0 evidence gap: Manager pin J1-v3 `b8928aec...` sau drift nhưng I03/I05 và
  production downstream vẫn pin v2 `aa405015...`; harness còn một freeze
  authority riêng chỉ ba file/token C1.
- Independent full 23-file S09 suite trên isolated worktree basetemp:
  `1 failed, 362 passed`. Failure thật là T04 content GET trả 404 trên absolute
  MP4 path dài 272 ký tự dù file đã publish; writer long-path safe nhưng reader/
  FileResponse chưa safe.
- Benchmark `decoded_output_hash` là raw frame concat, không phải canonical
  frame-count+shape+bytes hash. UI cũng không gửi `affected_loop_ids` và
  ApprovalPanel không match route-override evidence.
- Static gates vẫn tốt: Ruff, mypy 125 files, Alembic one head, TSC, scoped
  ESLint, production build và materialized OpenAPI no-duplicate đều pass.
- Review record:
  `docs/pm/reviews/S09_C2_PM_REVIEW_2026-08-25.md`.
- Next authorized packet:
  `docs/pm/prompts/S09_C3_CORRECTION_MANAGER_2026-08-25.md`. C3 resume exact
  T05A/T03/T04/T05B/I03 owners theo Wave A, unified J1-v4, I05 decision rồi
  T06B production E2E. Không tự mở sprint khác.

### Live update — 2026-08-25 09:50 +07 (Codex S09-C1 re-review)

- `S09-C1 = CHANGES_REQUESTED`; corrected terminal tại review boundary là
  `BLOCKED_WITH_FINDINGS / PENDING_CODEX_REVIEW`. Không APPROVED/CLOSED/push;
  S10 và production S11 vẫn blocked, production S13 chưa được mở bởi lane này.
- Independent current gate trên toàn bộ 22 `tests/test_s09*.py`:
  `8 failed, 318 passed`. Bốn lỗi do J1 frozen SHA drift
  (`46c6a4...` expected, `62c7d7...` actual); bốn lỗi T03/T04 do durable publish
  chạm Windows path length 260 và job fail tại `.mp4.upload`.
- C1 decision v2 chỉ có 4/12 route-fixture rows measured; hard-cut và
  group-occlusion không có route measured. C1 prompt bắt buộc trường hợp này
  phải BLOCKED, không cho Manager ghi TASK_MANAGER_VERIFIED.
- Benchmark hiện gọi thẳng compositor/private helper thay vì production
  `RendererRouter`/adapter; frontend/T03/T04 vẫn dùng artifact v1 `t00-i05`.
  Renderer còn fixed 30fps, request-ID identity control và pre-encode output
  hash; production E2E thiếu proof only-affected-loop regenerate.
- Review record:
  `docs/pm/reviews/S09_C1_PM_REVIEW_2026-08-25.md`.
- Next authorized packet:
  `docs/pm/prompts/S09_C2_CORRECTION_MANAGER_2026-08-25.md`. Wave A resume năm
  exact owners T02/I03/T03/T04/T06B song song; J1 immutable renderer manifest;
  I03 actual-router measurement; I05 decision; rồi downstream/E2E join và stop
  for Codex review. Không tự mở sprint khác.

### Live update — 2026-08-24 21:18 +07 (Codex S09 full-sprint review)

- `S09 = CHANGES_REQUESTED`; S09 is not approved/closed and S10/S11 production
  remains blocked.
- P0 core finding: T02 `pose_swap` only re-encodes the source and
  `sprite_affine` transforms the whole source frame with fixed constants; the
  benchmark scores source fixtures rather than renderer outputs. F5 group
  occlusion uses an empty probe universe yet is reported PASS, and reference
  `VERIFIED` means SHA/ffprobe only.
- Independent default-Windows S09 suite: `247 passed, 1 failed`; the T02
  additive gate depends on ambient subprocess encoding and mutable Git HEAD.
- Deferred post-core findings: production OpenAPI has no T05/T06 paths, T06A
  submit does not commit, correction schema accepts invalid route/anchor/frame
  payloads, and T01 route evidence mixes NULL-manifest rows into a pinned view.
- Review record:
  `docs/pm/reviews/S09_FULL_SPRINT_PM_REVIEW_2026-08-24.md`.
- Next prompt is the user-authorized fast-track full correction:
  `docs/pm/prompts/S09_C1_FAST_TRACK_MANAGER_2026-08-24.md`. Prompt tuần tự
  `S09_CORE_C1_CORRECTION_MANAGER_2026-08-24.md` đã superseded theo quyết định
  ưu tiên tốc độ của user. Fast-track chạy tối đa 5 owner có write-set tách biệt,
  dùng renderer-contract và production-API join gates. Wave A resume exact
  owners T02, I03, T01, T05A và T06A; Wave B chạy I05 và production-stack T06B,
  rồi stop for Codex re-review. Không mở S10/S11/S13.

### Live update — 2026-08-24 00:20 +07 (Codex S11-P02 rev-C5 re-review)

- `S11-P02 rev-C5 = CHANGES_REQUESTED`; exact synthesis owner phải resume:
  `20260823_145947_057312`, route custom/alpha/max/no-fallback.
- C5 đã sửa đúng bốn wave/Task references và thêm lane-proposal authority
  fence, nhưng active T03D acceptance vẫn đếm 8 overlay reason codes qua
  T03E audio/timecode. Binding partition phải là T03B=2 + T03C=3 + T03D=3;
  T03E là hai check riêng.
- Metadata hiện hành còn stale/sai ngày và C5 chưa tách explicit worker
  write-set khỏi Manager coordination append. Review record:
  `docs/pm/reviews/S11_P02_PM_REVIEW_2026-08-23.md`.
- Next prompt:
  `docs/pm/prompts/S11_P02_C6_CORRECTION_2026-08-24.md`. Đây là docs-only
  correction; `S11-T02..T06 = BLOCKED_DEPENDENCY_ON_E06/S09`, không production
  dispatch.

### Live update — 2026-08-23 23:20 +07 (Codex re-review of actual C6)

- `S13-P00 = CODEX_APPROVED`: C6 changed exactly the three authorized files;
  23/26 baseline files remained byte-identical, the stale C4 label is gone,
  the report ends `TASK_SUBMITTED`, and all 22 task/write-set/acceptance/DAG
  contracts remain intact. Review record:
  `docs/pm/reviews/S13_P00_PM_REVIEW_2026-08-23.md`.
- Approval is for the P00 planning baseline only. `PRODUCTION_S13 = NOT_OPENED /
  BLOCKED_RESOURCE_ON_S09_ACTIVE_INTEGRATION_LANE`.
- At 23:20 +07, integration HEAD was
  `ee10e55a809c84d5cb5d4a3046a1ee78828528d0`; S09 I02/I03 artifacts had recent
  writes through 23:18 and the worktree carried active S09 renderer/harness
  changes. Future S09 tasks overlap S13 on `models.py`, migrations and
  `app/api/app.py`. The `prepare-s13-t01` worktree remains stale at
  `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`.
- Next prompt is wait/preflight-only:
  `docs/pm/prompts/S13_POST_P00_STABLE_LANE_WAIT_MANAGER_2026-08-23.md`. It may
  not dispatch a worker. Codex must issue a later full-sprint prompt after S09
  writers exit and a current stable lane is verified.

### Live update — 2026-08-23 22:25 +07 (Codex re-review of actual C5)

- Actual integration HEAD is `ee10e55a809c84d5cb5d4a3046a1ee78828528d0` on
  `codex/s08-integration`; dirty source paths are attributed to S09/S11.
- S13-P00 C5 was independently checked: 22 task IDs/rows/nodes, lane hashes
  unchanged, and no P0/P1 structural finding remains.
- One P2 metadata finding remains: synthesis `READINESS_REPORT.md` still labels
  the current package `C4 revision`. Resume the exact synthesis owner
  `20260823_033031_3a5082` with the C6 metadata-only prompt; do not rerun lanes.
- Terminal state remains `S13-P00 = TASK_MANAGER_VERIFIED -> PENDING_CODEX_REVIEW`;
  `PRODUCTION_S13 = NOT_OPENED`; no S13 production dispatch.
- Next prompt: `docs/pm/prompts/S13_P00_C6_METADATA_CORRECTION_2026-08-23.md`.

## Trạng thái điều hành hiện hành — 2026-08-23 12:05 +07

### Live update — 2026-08-23 12:05 +07 (Codex direct review)

- Baseline tích hợp vẫn là `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`,
  branch `codex/s08-integration`, HEAD
  `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`; dirty count quan sát là 266.
  Manager phải khám phá lại, không pin snapshot này thành sự thật vĩnh viễn.
- **S11-T01 APPROVED** sau Codex đọc trực tiếp engine/handler/tests và chạy lại
  full five-file suite: `64 passed` trong 240.58s, basetemp ngoài protected MAIN,
  `MOTIONFORGE_DATABASE_URL` unset. T01B/T01C/T01D không cần correction thêm.
  S11-T02..T06 vẫn `BLOCKED_DEPENDENCY` vì cần E06/S09 exit; chỉ readiness
  docs-only được phép chạy song song trước gate đó.
- **S09-T00 readiness package APPROVED làm input triển khai.** Codex cũng đọc
  trực tiếp sản phẩm T01 contract cũ và chạy lại 48/48 test. Giữ sản phẩm cũ
  làm nền, nhưng S09-T01 chưa hoàn tất contract Source-Locked hiện hành và phải
  resume đúng session `20260822_232748_b4b2ad` sau T00 implementation. Một
  Manager S09 mới được cấp quyền chạy trọn sprint T00 implementation → T06,
  theo task map/write-set trong prompt Codex 2026-08-23, rồi dừng một lần ở
  sprint gate.
- **S13-P00 CHANGES_REQUESTED**: synthesis dùng sai migration path
  `alembic/versions/**`, task packets quá lớn cho một session, còn đề xuất
  production `qa_stub.py`, và chưa khóa rõ isolated-test DB/network authority.
  Chỉ resume synthesis owner `20260823_033031_3a5082`; không rerun A/B/C và
  chưa mở production S13-T01..T08 cho tới Codex re-review correction.
- Các prompt manager chuẩn hiện hành được lưu dưới `docs/pm/prompts/` với ngày
  2026-08-23. Chỉ prompt đích danh được phép ghi đè trạng thái stale bên dưới;
  rules canonical vẫn là `HERMES_AUTOPILOT_RULES.md`.

### Live update — 2026-08-23 00:01 +07

- S09-T01 theo contract cũ đã thực sự chạy từ 23:27, process owner hiện ghi
  `proc_f24cb4aef494`; `output/s09/s09-t01/dispatch.log` còn tăng lúc 23:59.
  Worker đang ở pha phân tích/thiết kế và tại snapshot chưa thấy S09 production
  file mới. Phải gửi scope correction vào đúng Manager S09 hiện tại để yêu cầu
  worker dừng an toàn, giữ nguyên owner lineage và chuyển T01 về
  `BLOCKED_DEPENDENCY` trước khi chạy S09-T00.
- S11 correction round R6 đang chạy song song đúng owner: T01B session
  `20260821_160614_40b90e` xử lý F1+F3 và T01C session
  `20260821_214021_cbc36d` xử lý F2; T01D chờ Wave 2 cho F4. Không tạo session
  S11 thay thế và không gửi task mới vào các owner này.
- S13-P00 chưa chạy. Có thể mở Manager riêng sau khi S09-T01 cũ đã dừng an
  toàn. Manager mới phải audit tài nguyên và tăng số audit worker disjoint theo
  slot thực tế; không làm nghẽn heartbeat/liveness của S11/S09.

- Workspace tích hợp: `C:\Users\Admin\MotionForge2D-worktrees\s08-integration`,
  branch `codex/s08-integration`, HEAD quan sát gần nhất
  `a43b20da742996bafcb2f9d1ac57b10d3f1a5204`. Mọi Manager vẫn phải preflight
  lại HEAD/dirty tree/process thay vì coi snapshot này là khóa cố định.
- S07 Project Cast Reuse: **APPROVED** sau Codex review độc lập; focused/full,
  Playwright và vertical reuse gates đã xanh, không còn finding chặn S09.
- S08 Object Intelligence cùng bridge Source-Locked đã qua gate mở S07/S09.
  Review nền được lưu tại `docs/pm/reviews/S08_SPRINT_PM_REVIEW_2026-08-19.md`.
- S11-T01: **CHANGES_REQUESTED**. Correction phải resume đúng owner sessions
  T01B `20260821_160614_40b90e`, T01C `20260821_214021_cbc36d`, T01D
  `20260822_003041_b18319`; S11-T02..T06 vẫn `BLOCKED_DEPENDENCY` trên E06 và
  T01 Codex approval.
- S09: contract worktree tạo lúc 22:46 +07 đang lệch roadmap MAIN vì bỏ qua
  `S09-T00` và adaptive renderer/source-lock overlay. Tại snapshot 23:26 +07
  chưa thấy S09 output hay production file mới, registry còn ghi session T01
  “đang tạo”. Không cho T01 code tiếp theo contract cũ; phải realign và chạy
  S09-T00 trước, sau đó dừng ở Codex gate trước khi chốt T01..T06.
- Lane song song bổ sung được phép ngay: **S13-P00 readiness-only**, tối đa ba
  worker audit read-only song song rồi một worker synthesis; chỉ được ghi
  `output/s13-p00-readiness/<run-id>/**`. Không được viết production code,
  migration, test hay mở S13-T01 cho tới Codex review P00.
- Product backlog/target overlay chuẩn nằm ở MAIN `docs/pm/ROADMAP.md`. Bản
  roadmap cũ trong worktree không được dùng để hạ scope chuẩn.

## Vai trò cố định

- Codex là PM/reviewer: audit, quyết định gate và soạn prompt cho Hermes manager.
- Hermes Manager chỉ preflight, dispatch, monitor, review và report; Manager
  không tự sửa production code/test/migration/UI/config. Worker session riêng
  mới là implementation writer.
- Codex không tự chạy Hermes khi người dùng đã có Hermes quản lý; chỉ khởi chạy
  nếu người dùng cho phép rõ ràng.
- Hermes chỉ được kết thúc task ở `TASK_SUBMITTED`/`TASK_MANAGER_VERIFIED` và
  sprint ở `SPRINT_SUBMITTED / MANAGER_VERIFIED_PENDING_CODEX_REVIEW`. Chỉ
  Codex được ghi `APPROVED`.

## Khôi phục trạng thái trước mọi hành động

1. Đọc `docs/pm/SESSION_PROTOCOL.md`, `docs/pm/README.md`, roadmap, TASK/LOG/
   REPORT/PM_REVIEW của task liên quan và automation state.
2. Kiểm tra tất cả worktree, branch, `git status --short`, process Hermes/watcher,
   session ID và log đang tăng hay đã ổn định.
3. Nếu Hermes writer còn chạy: Codex hoàn toàn read-only; không sửa tài liệu,
   không chạy quality gate và không review giữa chừng.
4. Không tự suy ra “task mới nhất”; xác định Task ID, worktree và exact session
   từ filesystem/evidence.

## Task và Hermes session lifecycle

- Một Task ID = một session folder = một Hermes chat/session.
- Task ID mới phải dùng Hermes session mới.
- Cùng Task ID bị `CHANGES_REQUESTED` phải resume đúng stored session ID; không
  mở fresh session. S05-C04 từng vi phạm điều này ở R2/R3 — không lặp lại.
- Session đã APPROVED/CLOSED không được nhận Task ID mới.
- Không mở task kế tiếp cho đến khi task cũ: writer thoát, REPORT SUBMITTED,
  Codex review APPROVED và trạng thái CLOSED.
- Automation state có thể cũ do launcher thủ công; phải reconcile trước khi dùng.
  Không dùng “most recent session” ngầm định.

## Parallel work

- Chạy tối đa các task dependency-ready đã được Codex/BA cấp quyền và có
  exclusive write-set cùng runtime resources không giao nhau. Watcher/read-only
  reviewer không được tính là production writer.
- Mỗi Task ID vẫn có exact owner session riêng. Cùng worktree chỉ được chạy
  song song khi prompt chứng minh disjoint cả file/API/schema/migration/fixture,
  database/temp/output/port/cache; global gate phải qua mutex ở checkpoint ổn
  định. Nếu không chứng minh được thì serialize hoặc dùng worktree riêng.
- Không dùng parallel để né Codex sprint gate hoặc dependency chưa APPROVED.

## An toàn tuyệt đối

- Không commit/push/deploy/merge/reset/checkout/restore/clean/stash/delete nếu
  chưa có quyền rõ ràng.
- Bảo vệ `channels.json`, mọi `data/`, database, fixture, user data, backup,
  evidence cũ và dirty changes. Không overwrite QA run/screenshot cũ.
- Mọi test/runtime phải dùng root/database/evidence directory mới và cô lập.
- Không sửa PRD, Master Plan, roadmap hoặc task contract từ Hermes; PM sở hữu.
- Không skip/ignore/nới assertion để làm xanh gate.

## Cấu trúc prompt giao Hermes manager

Mỗi prompt phải nêu: Task ID + exact worktree + new/resume exact session; hard
worktree guard; required reading; outcome; findings/AC nhị phân; allowed write
scope; forbidden scope; protected-data baseline; validation tách riêng; evidence
cần append; stop conditions; và `SUBMITTED only`.

Nếu là correction, prompt phải giữ nguyên lịch sử LOG/REPORT, append correction
round, sửa toàn bộ finding hữu hạn và resume exact session. Nếu phát sinh nhu
cầu ngoài scope, Hermes dừng `BLOCKED` để PM quyết định.

## Review gate của Codex

Chỉ review sau khi writer thoát và tree ổn định. Thứ tự: scope → acceptance →
architecture/domain → data/migration → tests/evidence → UX → regression.
Đọc code/diff trực tiếp; không tin riêng REPORT. Chạy lại gate độc lập theo rủi
ro, kiểm tra protected hash, new run ID, screenshot và isolation. Ghi PM_REVIEW
với decision, timestamp, reviewed tree, session ID và Quality Run ID.

Script `.ps1`/`.sh` không phải module Python nên không chạy trực tiếp bằng
pytest. Kiểm tra phù hợp là PowerShell Parser, `bash -n`, functional smoke và
regression Python liên quan.

## Chế độ thực thi sprint do người dùng yêu cầu

- Codex chuẩn bị/duyệt sprint contract, dependency graph, task packets, worktree
  và protected-data baseline trước khi giao việc.
- Một Hermes manager điều phối TOÀN BỘ sprint. Mỗi Task ID con vẫn phải dùng một
  Hermes coding session riêng; manager không biến cả sprint thành một session
  writer duy nhất và không tái sử dụng session đã đóng cho Task ID khác.
- Manager được tự review từng task sau khi writer thoát: audit diff/scope, chạy
  targeted + regression gates, yêu cầu correction bằng cách resume đúng session
  của Task ID đó, rồi mới mở dependency kế tiếp.
- Việc manager tự review chỉ là internal gate, không phải Codex `APPROVED`.
  Trong lúc sprint chạy, task hoàn tất giữ trạng thái
  `MANAGER_VERIFIED_PENDING_SPRINT_REVIEW`/`SUBMITTED`; Hermes không ghi PM
  approval.
- Manager chạy đến hết sprint, tạo sprint-exit report, fresh 7/7 baseline,
  integration/Playwright/visual evidence theo scope, protected-data comparison
  và danh sách mọi correction/session ID. Sau đó dừng toàn bộ writer ở
  `SUBMITTED` và gọi người dùng/Codex review MỘT LẦN ở sprint exit.
- Codex không theo dõi/poll khi sprint đang chạy. Chỉ review khi người dùng báo
  Hermes đã xong; Codex có thể APPROVED toàn sprint hoặc trả một correction
  packet hữu hạn cho manager xử lý trong cùng sprint.
- Parallel trong sprint chỉ dành cho task độc lập: dependency đã mở, worktree +
  session + write scope riêng, không chia sẻ mutable QA/database/output. Manager
  phải serialize mọi integration hoặc scope giao nhau.
- Không bắt đầu sprint mới trước khi sprint hiện tại được Codex APPROVED/CLOSED.

## Snapshot lịch sử 2026-08-05 — đã bị trạng thái 2026-08-22 ở trên thay thế

- S05-C04 và Sprint S05: APPROVED/CLOSED.
- Reviewed Hermes submission: `20260805_210521_ead0fd`.
- Fresh quality baseline: `20260805-214242`, 7/7 PASS.
- Codex independent targeted suite: 41/41 PASS.
- Protected MAIN `channels.json` SHA-256:
  `DD7AAE26096902EFF74986B36554957D87EB8E60C5E8FF8048064C31655EB555`.
- S06-T01..T04 đã APPROVED. S06-T05 packet đã tồn tại với trạng thái
  APPROVED trong worktree `s06-t01-review`; baseline `20260805-091121` 7/7
  PASS, focused Playwright 8/8. Sprint S06 hoàn tất về product gate. MAIN và
  một số packet/worktree còn snapshot cũ/bản sao incident; phải reconcile bằng
  thao tác không phá hủy trước integration, nhưng không chạy lại S06-T05.
- Các sprint đã hoàn tất về product gate: S00, S01, S02, S03, S04, S05, S06.
- Sprint sản phẩm tiếp theo theo dependency core là S08. S07 vẫn chờ E05/
  ObjectRole contract từ S08; không chạy S07 trước contract này.

Trạng thái trên chỉ là snapshot. Session mới luôn phải kiểm tra lại filesystem
và process trước khi tiếp tục.
