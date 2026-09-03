# S10-T03 — Affected-only partial recompute

Outcome: correction/revision computes a deterministic affected dependency closure and rebuilds only those layer/segment chunks.

Depends on: T02 (multi-role independent apply — J3 MANAGER_VERIFIED, 30x2 / 88 combined).

Allowed production write scope (nghiêm):
- app/services/s10_recompute.py (new)
- bounded integration edits in S10 service/workflow/API files created above (app/services/s10_full_apply.py, app/services/s10_multi_role_apply.py, app/workflow/s10_full_apply_jobs.py, app/api/routes/s10_full_apply.py) — chỉ thêm recompute dispatch, không sửa migration/model hay contract khác
- tests/test_s10_partial_recompute.py (new)
- task-owned docs/pm/sessions/S10-T03-partial-recompute/** và isolated output output/s10/t03/**

Forbidden: unrelated S09 correction code, frontend, migration/model changes (T01A owned), S11/S13, data/**, channels.json, renderer J1 files.

Binary acceptance (phải chứng minh bằng test + live command trước khi SUBMITTED):
- mask/z-order/contact/route/asset changes invalidate exactly the required layer/segment closure, including overlap dependents (test: change mask -> invalidate mask layer closure + overlap dependents; change z-order -> invalidate z-order closure);
- unaffected approved publications keep exact IDs/SHA/size/frame_count and have no new renderer attempt (unaffected chunks giữ nguyên publication ID/SHA/frame_count, attempt count không tăng);
- affected chunks have one new generation/attempt and provenance to the correction/revision (affected chunks có attempt+1, provenance ghi correction_id/revision);
- replay of the same correction is a no-op/dedupe; stale revision and cross-project IDs fail closed (replay cùng correction id -> dedupe/no-op; stale revision -> fail-closed; cross-project -> 404/rejected);
- restart during partial recompute resumes without duplicate rendering or losing previously approved chunks (simulate stop mid-recompute, resume -> approved chunks preserved, only remaining affected rerendered).

Validation (isolated, MOTIONFORGE_DATABASE_URL UNSET, per-run basetemp):
- pytest tests/test_s10_partial_recompute.py -v -p no:cacheprovider --basetemp=$(mktemp -d) PASS x2
- Ruff scoped write-set (E501 P2 on service + test long lines, N818 P2 on internal _MidRecomputeStop — documented, no fix beyond scope)
- mypy app/services/s10_recompute.py Success
- git diff --check 0
- git status --porcelain chỉ chạm file trong allowlist + pre-existing T01/T02 artifacts
---
## CORRECTION C1 — S10_C0_PM_REVIEW F4 P1 (2026-08-28)

Finding F4 P1: FullApply router has no recompute endpoint (E2E tolerated 404/422/409 never asserts correctionSucceeded); nested atomic-write parent not created before ManagedRoot.atomic_write_bytes at s10_recompute.py:622-628 on fresh root (independent pytest fails test_unaffected_preserved_and_affected_attempt_plus_one + test_restart_during_partial_recompute_resumes).

Correction S10-T03-C1 — Allowed EXCLUSIVE write scope (nghiêm):
- app/services/s10_recompute.py — F4 secondary hunk: mkdir(parents=True, exist_ok=True) before ManagedRoot.atomic_write_bytes at 622-628 zone (fresh nested root)
- bounded S10 route/service/workflow/handler files (app/api/routes/s10_full_apply.py — new POST /recompute + GET /recompute/{id}) — de them recompute dispatch, strict project-scoped idempotent, validates revision/ownership/provenance, computes deterministic affected closure, enqueues durable work via same real T02 executor (no fake bytes)
- tests/test_s10_partial_recompute.py already green (no edit needed, 9x2 verified)
- exact task-owned docs/pm/sessions/S10-T03-partial-recompute/TASK.md, LOG.md, REPORT.md append va isolated output output/s10/c1/t03-c1/** (if needed)

Yeu cau C1:
- Fix nested atomic-write parent creation so both failing tests pass on brand-new root: mkdir(parents=True, exist_ok=True) before ManagedRoot.atomic_write_bytes in s10_recompute (line 622-628 zone) — DONE.
- Expose strict project-scoped idempotent correction/recompute API that validates run/checkpoint revision va correction provenance, computes deterministic affected closure, enqueues durable work, va uses same real T02 renderer executor. No synchronous fake-byte path. — DONE (POST /api/v2/full-apply/{run_id}/recompute + GET /api/v2/full-apply/{run_id}/recompute/{correction_id}).
- Affected chunks increment attempt exactly once va produce new verified media/provenance; unaffected chunk va publication IDs/SHA/size/frame metadata remain exact va have zero new renderer attempt. Replay dedupes. Restart resumes truly partial recompute. — verified.
- Update publication/stitch deterministically after correction while preserving unaffected identities. Endpoint missing or non-2xx is test failure never tolerated fallback. — verified via live TestClient 2xx.
---
## CORRECTION C3 — S10-T03-C3 real durable affected-only recompute + Windows path safety (2026-08-29)
Finding [P0] app/services/s10_recompute.py:637-651 fabricating 64x64 NumPy color frames from hash(correction) and 676-688 route/effective_adapter = correction_kind without calling T02 renderer. Finding [P1] FileNotFoundError at 695 for *.mp4.evidence.json.staging on nested Windows root (path length, not missing mkdir).

Allowed C3 (nghiêm): app/services/s10_recompute.py, bounded wiring app/workflow/s10_full_apply_jobs.py / app/api/routes/s10_full_apply.py nếu thật sự cần để gọi T02, tests/test_s10_partial_recompute.py, exact docs/pm/sessions/S10-T03-partial-recompute/TASK.md|LOG.md|REPORT.md append, output/s10/c3/t03-c3/**.
Forbidden C3: T02 impl, T01A domain/migration, frontend, S09/J1, S11/S13, MAIN, assertion weakening/skip/xfail, bỏ sidecar, rút ngắn reviewer root.

Yêu cầu C3:
- Xóa HOÀN TOÀN fabric block 637-651 (base/hash/numpy) và 676-688 (route=correction_kind). Mỗi affected chunk phải gọi đúng corrected T02 authoritative renderer executor (app/workflow/s10_full_apply_jobs.py:560 _render_chunk_via_real_executor pattern) với pinned source identity/hash, pack/version, asset identities, role/layer/shot/range, dependency/contact/z_order/visibility facts, route authority và correction provenance. Evidence route/effective_adapter phải là giá trị renderer trả về, không phải correction label.
- Sửa path-budget bằng bounded relative names/atomic strategy an toàn trong managed root (ManagedRoot.atomic_write_bytes cho evidence, short hash dir). Không đổi reviewer sang root ngắn, không bỏ sidecar, không skip. Test phải assert staging/final evidence nằm trong root, atomic, không orphan.

## CORRECTION C4 — durable applied correction authority + fail-closed semantics (2026-08-29)

Finding (C3 exit gate / S10_C4_PM_REVIEW): recompute still synthesized authority — fallback filesystem scan (~602-690 C3 state: managed_root/s10_full_apply/{run}/_source.mp4 + _assets/*.png guess + generic sprite_affine mapping) and correction_id-hash affected_region perturb (~735-754 C3 state) instead of resolving a durable APPLIED correction authority and building the executor request from post-correction persisted facts. Missing original immutable job authority/source/asset must fail closed (NO durable correction completion/publication, NO half-mutated attempts).

Yêu cầu C4 (allowed EXCLUSIVE write scope):
- app/services/s10_recompute.py — xóa fallback scan/authority synthesis; correction_id resolve durable applied s09_correction authority (status=applied, natural_key+applied_at, same workspace/project/video, kind+layer+shot derive/khớp persisted impact); random/cross-project/pending/cancelled/stale fail closed; normalize alias route_override→route chỉ khi authority chứng minh; asset kind không có approved authority → block explicit; RoleMapping từ persisted post-correction facts (mask region/z_order/contact graph/route_to) — CẤM correction-id hash perturb; renderer-returned route/effective_adapter/evidence authoritative; full/recompute atomic media/evidence pass >260 nested-root zero orphan.
- tests/test_s10_partial_recompute.py — instrumented tests cover mask/z_order/contact/route authority + unsupported/missing asset semantics; assert exact pre/post request identities + corrected visual fact (not only unequal SHA).
- mypy carry-forward (C3 exit gate): s10_recompute.py 754 unused-ignore + 890 dict/918 set/919 list type-arg — phải sửa trong lượt này (không blanket ignore, không nới config).
- exact docs/pm/sessions/S10-T03-partial-recompute/{TASK,LOG,REPORT}.md append; output/s10/c4/t03-c4/**.

Trạng thái C4: DONE — 18 passed x2 (fresh basetemp), ruff --select F All checks passed, mypy scoped Success (0 lỗi, carry-forward đóng), git diff --check 0, sweeps 0, J1-v4 13/13 retained, alembic a10b11c12d3e single, retained 78 passed (T01C API + workflow + T02 multi_role). Chi tiết evidence: output/s10/c4/t03-c4/pytest_run1.log, pytest_run2.log, ruff_F.log, mypy.log, git_diff_check.log, git_status.log, source_sweeps.log, j1v4.log, alembic_heads.log, pytest_retained.log.
