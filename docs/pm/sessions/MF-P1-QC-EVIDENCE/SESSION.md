# MF-P1-QC-EVIDENCE — session record

**Task:** MF-P1-QC-EVIDENCE (Wave A, CPU-only)
**Owner session:** `20260923_154031_f6a46e` (resumed; the first run died on a
transient upstream `502 fetch connect timeout` after having written code but
before any verification — see "Resume contradiction" below)
**Model:** `ocg/deepseek-v4.1-flash`, provider `custom`, thinking ON, fallback OFF
**Tree:** `C:/Users/Admin/Documents/Codex/work/mf-tool-20260923/mf-p1-qc-evidence`
**Branch:** `codex/mf-tool-20260923-mf-p1-qc-evidence`
**Baseline:** `2594de06cd5b2355e7e874ae4d6deb8a7b5b1b64`

---

## 1. Resume contradiction (measured, not assumed)

The resume packet stated the worktree was pristine (`porcelain=0`) and that the
previous run "wrote nothing". Measured at recon:

```
$ git status --porcelain
 M app/workflow/qc_checks_handler.py
?? app/services/qc_evidence/
?? tests/product_p1/
PORCELAIN_COUNT=3
```

So the evidence-root half of the claim was true (`NEW/P1QC/` did not exist) but
the worktree half was false. Per the "a resume claim is hearsay" rule, the
half-written work was neither trusted nor discarded: it was compiled, linted and
**executed**. The first real execution gave:

```
16 failed, 9 passed, 4 errors in 35.79s
```

The writing run had produced ~3,560 lines of unexecuted code and died mid-way
(the last file mtime was 17:49, one minute after `sources.py`). The code was
sound in design but carried three real defects that only execution exposes —
all three are fixed and covered by the tests now (see §3).

## 2. What was frozen first

`app/services/qc_evidence/contract.py` holds the detector → required input →
producer → persistence → provenance-proof → derivation → refusal table for all
ten FULL-band detectors, with `table_digest()` as the machine-checkable freeze.
It was frozen before the implementation, and `test_contract.py` pins the digest,
so drift in any producer/persistence/provenance/derivation/refusal fails the
suite rather than silently redefining what "evidence" means.

## 3. Real defects fixed in this session (each one execution-proven)

1. **`sources.read_artifact` inverted a containment guard.**
   `is_within(path, root)` was called as `is_within(managed_root, absolute)`,
   i.e. "is the root inside the file?" — always `False`, so *every* artifact read
   refused with `QC_EVIDENCE_MISSING` and 16 tests failed for the wrong reason.
2. **The handler resolved the managed root from a module that does not export it.**
   `app/workflow/qc_checks_handler._evidence_managed_root()` did
   `from app.workflow.job_service import get_job_service` inside a bare
   `try/except Exception` fallback. That symbol lives in `app.api.deps`, so the
   import always raised, the fallback silently won, and the evidence reader
   verified bytes against the *default* artifacts root instead of the root the
   application actually writes. On the public path this surfaced as
   `422 QC_EVIDENCE_MISSING: artifact … file is absent under the managed root`
   for evidence that was present. Now resolved through the app's own public
   accessor `app.api.deps.get_managed_root()`.
3. **A non-published render candidate was silently skipped.**
   `rendered_result_artifacts` filtered `Artifact.state == 'ready'`, so a newer
   render artifact in `staging` was skipped in favour of an older ready one —
   green-by-fallback. The state filter is gone: the byte reader now raises
   `QC_EVIDENCE_STALE` for a candidate that is not published, which is the
   honest answer and is what
   `test_stale_render_artifact_refuses_the_render_backed_detectors` asserts.
4. **The `edge_halo` window could not contain the ring it measures.** The window
   was a centre-crop *inside* the expected-mask bbox, but the halo ring lies
   *outside* that bbox by definition, so the measured ring was always empty
   (`halo_width_px = 0.0`). The window is now the expected ∪ rendered bbox
   expanded by a disclosed margin, bounded to a disclosed limit.
5. **`edge_halo` could compare two different objects.** Any other mask artifact
   was an acceptable "rendered side", so segment B's mask could stand in as the
   rendered side of segment A's edge. A candidate must now bound the *same
   region* (overlapping measured bbox); a byte-identical candidate is still
   refused as a self-comparison.
6. **A missing structural fact reported a dependency instead of a gap.**
   `_trajectory_drift` asked for a render route before it asked for the video's
   segments, so a video with no visual evidence at all refused with
   `QC_EVIDENCE_DEPENDENCY` (a producer that was never asked to run) instead of
   `QC_EVIDENCE_MISSING` (nothing was ever published). Order corrected.

Test-side corrections (all in the task's own new test tree): FK-ordered deletes
(`occurrence_segment` is `ON DELETE RESTRICT` from six tables), the real
`QCItem.evidence_json` column name, and a fixture render layer at gray level 8
(a saturated 255 delta is correct behaviour but lands outside the `identity_drift`
metric's sanity bound, so it can never exercise the positive path).

## 4. Deliberate fixture disclosure

The fixture writes the media/mask **bytes** itself through the real
`ManagedRoot` contract and seeds the upstream domain rows through the real
repositories, because driving the whole S08→S10 chain needs a GPU renderer this
wave does not have. Every byte is real, every `sha256` is the real digest of the
bytes on disk, and **no QC row is ever seeded** — every QC item asserted in the
suite is produced by the real detector reading those persisted facts through the
public submit → worker → persistence chain.

The `full-apply publication` precedence rule stays **NOT_REVIEWED** for that
reason; the fixture exercises the published-render-artifact rule and the source
fallback rule instead, and the source-fallback case is additionally proven to be
*refused* (never measured) by the self-comparison guard.

## 5. Terminal state

`TASK_SUBMITTED`. No threshold, registry, readiness or migration was touched.
The commit is local to this tree and not pushed.
