# MF-TOOL-CONTRACT — session LOG

**Task:** MF-TOOL-CONTRACT (media-engine contract + C-CONTRACT domain/task deltas)
**Owner session:** `20260923_154033_6c0c8f` (resumed after an upstream 502 transport failure)
**Tree:** `C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-tool-contract`
**Branch:** `codex/mf-tool-20260923-mf-tool-contract` · **base** `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`
**Model:** `ocg/deepseek-v4.1-flash` (provider `custom`), thinking ON, fallback OFF
**Wave:** A (CPU) — no GPU, no DB, no network.

| # | Event | Evidence |
|---|---|---|
| 1 | Recon: tree exists, HEAD `2594de0`, branch correct, base is ancestor. **Manager footprint report contradicted by measurement** — `git status --porcelain` returned 1 entry, not 0. | `?? app/schemas/media_engine.py` |
| 2 | Identified the untracked file as a real prior-run artifact, not a stray: 1,152 lines / 42,003 B, mtime `16:32:08`, tree checked out `15:37:07`, docstring names this task and `docs/technology/mf_engine_v1/MEDIA_ENGINE_CONTRACT.md`. | `stat`, `head -40` |
| 3 | Verified rather than trusted it: `py_compile` OK, `ruff --select F` clean, tail intact (last function closes properly). Kept it. | compile + ruff |
| 4 | Verified every claim it makes about the repo: `app/services/renderer_contract.py` (36,104 B), `app/persistence/jobs.py` (68,253 B), `docs/architecture/DURABLE_JOB_CONTRACT.md` (49,383 B), `app/persistence/models.py::RENDERER_ROUTES` (5 routes) all exist. | existence + grep |
| 5 | Repaired two defects found by reading: (a) `GpuLeaseGrant.is_expired` returned a hardcoded `False` → replaced with a real deterministic `expired_at(now_utc)`; (b) `ManagedArtifact` refused `publishable=False`, making the flag a constant and forbidding legitimate intermediates → now only an intermediate marked publishable is refused, and `ARTIFACT_NOT_MANAGED` does real work in the new `assert_publishable_set` publication gate. | diffs + live probe |
| 6 | Wrote `tests/technology/test_media_engine_contract.py` (62 tests). **First run: 19 failed** — the failures exposed a genuine, fatal defect in the module: `cache_identity_for` passed key `pts` while `CacheIdentity` requires `pts_start_ticks`/`pts_end_ticks` and forbids extras, so the core cache-identity function raised `ValidationError` on **every** request and had never once executed. | 19 failed → tracebacks |
| 7 | Fixed it with a single-source digest payload (`IDENTITY_COMPONENT_FIELDS` + `_identity_payload`), so the hashed payload and the validated fields cannot drift. Also fixed 2 test-side bugs (wrong capability in a registry fixture; a lease-expiry assertion on a model with no such field). | 62 passed |
| 8 | Built a mutation harness (`NEW/CONTRACT/raw/negative_control_harness.py`): removes each guard in turn and requires the guard's own test to FAIL. First run FAILED for a harness bug (wrong repo root, then a mis-indented anchor) — read the real output, fixed, re-ran. | `raw/negative_controls.json` |
| 9 | Negative controls: `NEGATIVE_CONTROLS_PASS` — baseline green, all four guards DETECTED (N1 7 failed, N2 2, N3 2, N4 1), module restored **byte-identical** (`sha256 55a423df…` before == after). | `raw/negative_controls.json` |
| 10 | Grounded the four documents in real repo facts instead of prose: `CORE_POSE_SLOTS` (`models.py:170`), the completeness gate (`characters.py:569/746`), `CompatibilityReason` (`schemas/project_cast.py`), the ROADMAP S13 rows (`ROADMAP.md:264-277`), and the S13-P00 readiness synthesis (22 active sub-task IDs, waves W1–W11). | cited file:line |
| 11 | Wrote the five documents: `MEDIA_ENGINE_CONTRACT.md`, `EARLIER_SPRINT_DELTA.md`, `PACK_CAPABILITY_CONTRACT.md`, `S13_P00_DELTA_MATRIX.md`, `S13_P01_TASK_CONTRACTS.md`. | sizes in REPORT.md |
| 12 | Final gate: 62 passed, 62 collected, `ruff --select F` clean; guard accepted only-allowlisted additions. | `raw/contract_tests.txt`, `raw/guard_after.json` |

## Discrepancies and incidents (disclosed, not hidden)

- **Manager footprint report vs measurement.** The resume packet stated "you wrote nothing"
  and "worktree pristine (`porcelain=0`)". Measured: `porcelain=1` and a 42,003-byte
  `app/schemas/media_engine.py` written at `16:32:08` during the previous run. I did **not**
  discard it and did **not** trust it either — it was verified (compile, lint, content,
  cross-checked against the repo), then two defects were repaired. The Manager's
  `NEW/CONTRACT/` = 0-files measurement was correct; the worktree claim was not.
- **The unverified half of the prior run was the schema's own execution.** The module had
  never been run before this session. Six of its 1,152 lines were wrong in a way that broke
  the whole cache-identity path. This is why "wrote the file" is not evidence.
- **No push, no history rewrite, no forbidden path touched** — proven mechanically by
  `raw/guard_after.json`, not asserted.
- **Full repository suite not run** (outside this task's gate and unrelated to an additive,
  pure module): the gate is the contract suite plus `ruff --select F`, both green. The module
  imports nothing from `app`, enforced by its own test.
