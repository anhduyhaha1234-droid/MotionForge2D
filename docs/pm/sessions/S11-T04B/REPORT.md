# S11-T04B — Worker REPORT (W10)

## 1. Task identity

| Field | Value |
|---|---|
| Task ID | S11-T04B (serial sau W9 · T04A, depends T04A + T03G MANAGER_VERIFIED) |
| Wave | W10 |
| Worktree | `C:\Users\Admin\MotionForge2D-worktrees\s11-t04b-0903w10` |
| Branch | `codex/s11/t04b-0903w10` (local; không push/merge/rebase/reset/clean/stash/force) |
| WAVE_BASE | `b9176544d3a6af5566c61fe67a5d545b407d404b` (porcelain 0 tại start) |
| Model | `custom` / `ocg/deepseek-v4-flash`, reasoning max, fallback off |
| Status | TASK_SUBMITTED |

## 2. Verdict per acceptance criterion (ALL GREEN — 4/4)

**AC1 — Rerun scope V1 CHỈ cho issue neo occurrence/segment/StructuralLock/renderer route (Decision E); attempt ngoài phạm vi bị CHẶN với explain-action.**
- `classify_rerun_scope(item)` pure binary: 4 anchor in-scope (`object`+occurrence evidence,
  `segment`, `render`+lock_manifest_id, `route`+renderer_route ∈ RENDERER_ROUTES) —
  `test_v1_scope_accepts_only_the_four_anchors`.
- 7 trường hợp ngoài phạm vi (frame/audio/scene/video_item/render không lock/route ngoài contract/
  kind unknown) → `in_scope=False` + `explain_code` + `explain_reason` tiếng Việt (Decision E) —
  `test_v1_scope_rejects_out_of_scope_with_explain_action`.
- Chain entry points raise `QcRerunOutOfScopeError(code, reason)` TRƯỚC mọi pipeline call —
  `test_out_of_scope_chain_refuses_with_explain_action` (real session, real repository path).

**AC2 — Không có nút/code "rerun tất cả"; whole-project rerun KHÔNG tồn tại.**
- Bridge: 0 route decorators; 0 symbol `rerun_all|whole_project|rerun_project|RERUN_ALL|recompute_all`
  (source grep trong `test_no_whole_project_rerun_anywhere` + evidence/static_gates.txt).
- qc_items router: 0 mutation decorator (GET-only bảo toàn — Decision A).
- Corrections router: đúng 2 `@router.post ... recompute/retry` (2 path variants của route
  successor FROZEN S08-T05) — không retry generic mới; OpenAPI chứa path này
  (`test_retry_uses_existing_recompute_retry_route`).

**AC3 — Chuỗi preview → confirm → RECOMPUTE_OBJECTS trong một transaction; item chuyển recheck rồi auto-resolve bởi orchestrator sau publish OK.**
- `bridge.run_correction_chain` = compute_impact (ZERO-writes) → create(pending) → confirm(CAS
  applied) — MỘT transaction, caller commit 1 lần; recompute_job_id do CHÍNH pipeline tạo.
- Preview qua REAL HTTP `POST /corrections/preview` → 200 + 0 correction row + role/occurrence
  revision không đổi (`test_preview_zero_writes_revision_roles_unchanged`).
- Confirm xong → REAL worker (`svc.worker.run_once`) complete RECOMPUTE_OBJECTS; GET thật
  `/corrections/{id}` báo recompute completed/progress 100 (`test_bridge_chain_confirm_recompute_and_item_recheck`).
- Sau publish OK: `mark_item_recheck` (open→acknowledged qua T02B repo) + recheck trigger qua
  `submit_run_qc_checks` (T03G submit authority — job hàng thật) + REAL orchestrator
  `run_full_check_set` auto-resolve khi fresh run không còn báo window
  (`test_item_marked_recheck_then_orchestrator_auto_resolves`: phase 1 blocker → acknowledged,
  phase 2 NO_AUDIO_PRESENT → resolved_after_recheck=1, item `resolved` với fresh evidence).
- Retry terminal recompute qua EXISTING `POST /corrections/{id}/recompute/retry` → successor job
  ≠ predecessor, predecessor immutable, exactly 1 successor, worker hoàn thành
  (`test_retry_uses_existing_recompute_retry_route`).
- ROLE_CHANGED stale-guard: evidence `role_revision`/`occurrence_revision` so với row hiện tại →
  `QcCorrectionBridgeError(code=ROLE_CHANGED)` trước pipeline; confirm-time conflict pipeline được
  translate cùng code; HTTP layer giữ nguyên CAS semantics 409 (stale correction revision)
  (`test_role_changed_guard_blocks_before_pipeline`, `test_role_changed_at_confirm_time_maps_pipeline_conflict`).
- Replay: chain lần 2 sau correction bị guard chặn (evidence stale by design), chỉ đúng 1 correction
  row tồn tại (`test_chain_replay_never_duplicates_and_is_guarded_after_correction`).

**AC4 — Stale-reopen 3 anchor (segment supersede / manifest lifecycle / cast revision); ReskinConfig KHÔNG là anchor (phủ định lane-A).**
- Anchor 1 `segment_superseded`: REAL `supersede_segment` (workflow A manual) → superseded_by_id →
  check stale tại recheck-run → `reopen_if_stale` qua GAP-8 hook `reopen_stale_evidence` (T03F
  shared) → item `open` + evidence `stale=True, recheck=stale_superseded, superseded_by_id`
  (`test_segment_supersede_anchor_reopens_with_stale_flag`); lineage bump alone cũng stale
  (`test_segment_lineage_bump_alone_flags_stale`).
- Anchor 2 `manifest_lifecycle`: active→superseded (v1 archived trước v2 — đúng thứ tự create_manifest)
  và draft→voided đều stale; reopen mang `manifest_revision` vào evidence
  (`test_manifest_lifecycle_anchor_reopens`, `test_voided_manifest_is_also_stale`).
- Anchor 3 `cast_revision`: REAL repin `ProjectCastRepository.update_mapping` (CAS, revision 1→2)
  → evidence `cast_revision=1` stale → reopen mang `cast_revision="2"`
  (`test_cast_revision_anchor_reopens`); mapping không đổi → không stale
  (`test_cast_revision_untouched_means_not_stale`).
- Phủ định lane-A: REAL `ReskinConfigRepository.update_config` bump revision 1→2 → check VẪN
  `stale=False` + source-grep bridge không chứa `reskin_config|ReskinConfig(` —
  (`test_reskin_config_revision_change_is_never_an_anchor`, `test_bridge_source_never_references_reskin`).
- Terminal items (resolved) + stale signal → `QCItemInvalidTransitionError` fail-closed qua hook
  (`test_terminal_item_is_refused_by_stale_reopen`).

## 3. Thiết kế (khớp trace/contract)

- **Bridge = SOLE OWNER mapping** (app/services/qc_correction_bridge.py): scope V1 (Decision E),
  request mapping (candidate_edit target=occurrence với occurrence CAS thật từ ORM tại call-time,
  generation từ role, idempotency_key `qc-item:{id}`), chain 1-tx, ROLE_CHANGED guard, recheck
  trigger (T03G), stale-check 3 anchors + GAP-8 reopen (T03F hook) — KHÔNG route mới, KHÔNG sửa
  pipeline/lifecycle.
- Pipeline consume đúng hàm route gọi (`compute_impact`/`create_correction`/`confirm_correction`);
  HTTP surface test qua TestClient thật (preview/confirm/retry/OpenAPI).
- Stale-check fail-closed: anchor row MISSING (`SegmentNotFoundError`/`StructuralLockNotFoundError`)
  → STALE (anchor đã biến mất); payload corrupt → propagate (không silently-fresh).
- "Recompute only affected layers/segments" (overlay §S11 L363): manifest.affected_role_ids ==
  [role A]; role C artifacts (row id + sha256 + managed bytes) byte-identical sau rerun; published
  rows của recompute job không thuộc role unaffected
  (`test_unaffected_artifacts_byte_identical_after_rerun`).
- ReskinConfig không cột-revision làm anchor: dù model THỰC TẾ có revision CAS
  (`ck_reskin_config_revision_positive` models.py L2231 — plan ghi "không có cột" là không chính xác),
  bridge không bao giờ đọc nó; phủ định bind trên hành vi (bump revision → không stale) + source
  grep.

## 4. Evidence (raw, docs/pm/sessions/S11-T04B/evidence/)

| File | Nội dung |
|---|---|
| `baseline.txt` | porcelain 0 + HEAD/WAVE_BASE + branch + RED gate (bridge absent tại base) |
| `full_verbose.txt` | 21 passed verbose — 12 rerun + 9 stale, per-test |
| `runs_summary.txt` | run1 (8 pass/13 fail — chẩn đoán+fix, xem LOG), run r5 (21 passed 23.35s), run r6 (21 passed 23.04s) |
| `regression.txt` | 52 passed — T02B lifecycle + T03G API + S08 correction API (consume surfaces) |
| `static_gates.txt` | ruff --select F clean; py_compile OK; alembic head f9a0b1c2d3e4; status allowlist-only; 0 route/rerun-all/reskin refs; retry posts=2 |

Isolation mọi run: basetemp ngắn unique `%TEMP%/s11t04b_*`, `-p no:cacheprovider`,
`MOTIONFORGE_DATABASE_URL` unset, temp SQLite Alembic-head qua conftest client fixture + real
JobService worker.

## 5. Ngoài scope (báo cáo cho manager — KHÔNG tự sửa)

1. **Route confirm không bắt `OccurrenceConflictError`** (chỉ `OccurrenceNotFoundError`) → stale
   occurrence anchor qua HTTP confirm = 500; stale CORRECTION revision = 409 (đúng S08-T05).
   Pre-existing; ngoài allowlist T04B; bridge giữ guard ROLE_CHANGED service-layer như băng dính.
2. **Plan nói "ReskinConfig không có cột revision"** — thực tế models.py L2231 có
   `ck_reskin_config_revision_positive`. Không ảnh hưởng binding: bridge không dùng ReskinConfig
   làm anchor (AC4 phủ định xanh cả hành vi lẫn source).

## 6. Commit local

- SHA: `7629ab24b00ecbd82f753df5d467ecb609825072`
- Parent: b9176544d3a6af5566c61fe67a5d545b407d404b (WAVE_BASE canonical)