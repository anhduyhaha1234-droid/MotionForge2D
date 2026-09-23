# MF-TOOL-CONTRACT — REPORT

**Task ID:** MF-TOOL-CONTRACT · **Wave:** A (CPU) · **Status:** `TASK_SUBMITTED`
**Owner session:** `20260923_154033_6c0c8f` · **Model:** `ocg/deepseek-v4.1-flash` / `custom`, thinking ON, fallback OFF
**Tree:** `C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-tool-contract`
**Branch:** `codex/mf-tool-20260923-mf-tool-contract` · **base:** `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`
**Review target:** `C-CONTRACT` (Codex). This worker does **not** approve or close it.

---

## 1. Deliverables

| Artifact | Path | Bytes |
|---|---|---|
| Media-engine schema contract (pure) | `app/schemas/media_engine.py` | 45,136 |
| Contract tests | `tests/technology/test_media_engine_contract.py` | 39,670 |
| Engine contract document | `docs/technology/mf_engine_v1/MEDIA_ENGINE_CONTRACT.md` | 17,153 |
| Earlier-sprint delta | `docs/technology/mf_engine_v1/EARLIER_SPRINT_DELTA.md` | 12,258 |
| Pack capability contract | `docs/technology/mf_engine_v1/PACK_CAPABILITY_CONTRACT.md` | 8,886 |
| S13 P00 delta matrix | `docs/technology/mf_engine_v1/S13_P00_DELTA_MATRIX.md` | 13,419 |
| S13 P01 task contracts | `docs/technology/mf_engine_v1/S13_P01_TASK_CONTRACTS.md` | 10,036 |
| Session log | `docs/pm/sessions/MF-TOOL-CONTRACT/LOG.md` | this session |

Exact byte sizes and SHA-256 of every deliverable are in
`NEW/CONTRACT/raw/guard_after.json` (`deliverable_hashes`).

## 2. The four frozen capability facts, with refusal proofs

`MediaCapability` = `image_edit_multi_reference`, `source_video_motion_transfer`,
`video_edit_controlled`, `text_to_video` — exactly four, no aliases.
`SOURCE_LOCKED_CAPABILITIES` = the two clip-locked routes.

| Required refusal | Mechanism | Proof |
|---|---|---|
| **Capability fallback refused** | `FORBIDDEN_DEGRADATION_TARGETS` + `CapabilitySet.assert_can_serve` | `test_source_locked_route_refuses_t2v_i2v_substitution` (4 parametrised cases), `test_operator_approval_cannot_bless_a_t2v_degradation` — refused **even with** `operator_approved_substitution=True`. Mutation control **N1**: guard removed → 7 tests fail |
| **Client-supplied path/graph refused** | `MediaEngineRequest._refuse_client_supplied_inputs`, `ReferenceArtifact._check` | `test_request_refuses_a_client_supplied_path` (`client_artifact_path_refused`), `test_request_refuses_a_client_supplied_graph` (`client_graph_refused`), plus absolute/`..`/drive-qualified store paths. Control **N2**: guard removed → 2 tests fail |
| **Unresolved replay does not duplicate the POST** | `resolve_replay` (only `re_attach`/`refuse` exist) + `ReplayDecision.issues_post` constant `False`, enforced | 5-case table test (`ambiguous`, identity mismatch, acked→re-attach, un-acked, foreign owner) asserting `issues_post is False` on every branch. Control **N3**: guard removed + a `issues_post=True` injected → 2 tests fail |
| **Reference change invalidates** | `invalidate_for_reference_change` → `InvalidationReport` | Only entries using the changed role invalidate; others are listed unaffected; a change to an unused role invalidates nothing. Control **N4**: guard removed → 1 test fails |

Negative controls: `NEW/CONTRACT/raw/negative_controls.json` — `verdict:
NEGATIVE_CONTROLS_PASS`, `baseline_all_green: true`, all four `DETECTED`,
`restored_byte_identical: true` (schema `sha256 55a423df9bb00cb7561d3fc69196de481ab01fd198ae2364989774bc17d47cbc`
before == after).

## 3. Gate results (measured this session)

```
python -m pytest tests/technology/test_media_engine_contract.py -q
  → 62 passed, 62 collected in 1.73s
ruff check --select F app/schemas/media_engine.py tests/technology/test_media_engine_contract.py
  → All checks passed!
```

Raw output: `NEW/CONTRACT/raw/contract_tests.txt`.

## 4. Defects found and repaired (this is the substance of the run)

The previous run had written the schema module and died before executing any of it. Running
it found real bugs:

1. **`cache_identity_for` raised on every call.** It built the digest payload with key `pts`
   while `CacheIdentity` requires `pts_start_ticks`/`pts_end_ticks` and forbids extras — the
   core cache-identity path never worked. Fixed with a single-source payload
   (`IDENTITY_COMPONENT_FIELDS` + `_identity_payload`) shared by construction and the
   object's own check, so payload and fields cannot drift.
2. **`GpuLeaseGrant.is_expired` was a hardcoded `False`** — fake logic. Replaced with a real
   deterministic `expired_at(now_utc)` over a validated `YYYY-MM-DDTHH:MM:SSZ` string.
3. **`ManagedArtifact` refused `publishable=False`**, making the flag a constant and
   forbidding legitimate intermediates (masks/graphs). Now: an intermediate marked
   publishable is refused (`artifact_not_managed`), and a new `assert_publishable_set`
   publication gate refuses an empty publish set and any widening of the server-owned
   `SERVER_PUBLISHABLE_TYPES` — `OutputContract` enforces the same narrowing rule.

Two test-side bugs were also fixed (a registry fixture reusing the wrong capability; a
lease-expiry assertion aimed at a model with no such field).

## 5. Scope compliance

Additions only: `app/schemas/media_engine.py`, `tests/technology/`,
`docs/technology/mf_engine_v1/`, `docs/pm/sessions/MF-TOOL-CONTRACT/`.
**No tracked file modified, no forbidden path touched, no push, no history rewrite** —
established mechanically in `NEW/CONTRACT/raw/guard_after.json` (`no_tracked_file_modified`,
`all_additions_inside_allowlist`, `no_forbidden_path_touched`, `not_pushed`,
`base_is_ancestor`). Explicitly untouched: `app/api/app.py`, `app/config.py`,
`app/persistence/models.py`, `app/persistence/jobs.py`, every migration, every
UI/frontend file, `app/services/renderer_router.py`, `app/services/renderer_routes/**`,
`app/services/s10_*.py`, `app/services/s12_export/**`.

## 6. Disclosed discrepancy in the resume packet

The resume packet stated the previous run "wrote nothing" and the worktree was "pristine
(`porcelain=0`)". Measured at recon: `git status --porcelain` → `?? app/schemas/media_engine.py`,
a 42,003-byte artifact with mtime `16:32:08` (tree checked out `15:37:07`), whose docstring
names this task. The `NEW/CONTRACT/` = 0-files half was correct; the worktree half was not.
Action taken: verified the artifact (compile, lint, content, cross-repo claim check), kept
what was correct, repaired what was broken (see §4) — rather than discarding 42 KB of
on-spec work or trusting it unverified.

## 7. Limitations of this submission

- **Zero QUALITY_ACCEPTED / no visual verdict.** No vision was used; nothing here is a
  quality claim about generated media.
- **The full repository suite was not run** — outside this task's gate and unrelated to a
  pure, additive module whose own test proves it imports nothing from `app`.
- **Everything here is PROPOSAL.** The contract, the pack-capability proposal, the delta
  matrix and the P01 contracts carry no production authority until Codex reviews
  `C-CONTRACT`.
- `ResourceBudget.resource_class` is validated as a non-empty string, not against E01's
  `RESOURCE_CLASSES` — raised as open question §10.1 in `MEDIA_ENGINE_CONTRACT.md`.
