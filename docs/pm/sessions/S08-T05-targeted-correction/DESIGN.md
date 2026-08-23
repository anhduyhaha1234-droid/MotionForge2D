# S08-T05 — Dependency & Invalidation Graph (defined BEFORE implementation)

This document defines the explicit dependency/invalidation graph that the
S08-T05 correction workflow implements.  It was written before any
implementation code and is normative for the service, repository, job handler
and tests: every correction kind below must invalidate EXACTLY the derived
state named here, supersede/archive the affected state, recompute ONLY the
affected dependencies, and leave every unaffected row/file byte/hash
identical.

## 1. Domain nodes

| Node | Entity | Mutable? |
|---|---|---|
| R | `ObjectRole` (status suggested/confirmed/superseded) | CAS (`revision`) |
| O | `ObjectOccurrence` (bbox/time/confidence/reasons; `role_id` FK) | CAS (`revision`) |
| S | `ObjectGroupingSuggestion` (pending/dismissed/applied/superseded) | CAS (`revision`), natural-key detach |
| A | candidate artifacts of a `DISCOVER_OBJECTS` run (thumbnail/mask PNG rows + result manifest under `artifacts/<ws>/image/<job_id>/`), owner `video_item` | NOT updated by corrections (immutable historical rows) |
| Op | `RoleOperation` audit rows (T03 merge/split/confirm) | append-only |
| C | `ObjectCorrection` (the durable archive of one correction) | CAS (`revision`) |
| J' | `RECOMPUTE_OBJECTS` durable Job (the successor/recompute work) | durable job contract (immutable terminal; successor retry) |

## 2. Dependency edges (dependency → dependent)

1. `O → R` via `O.role_id`.  Moving an occurrence changes the dependent
   role's evidence set (and therefore its derived state).
2. `R → S` via `S.role_ids_json`.  A suggestion's confidence/reasons derive
   from the role's name/kind and the occurrences' geometry (footprint).
3. `O.geometry (bbox/time) → A` — candidate thumbnail/mask bytes derive
   deterministically from the occurrence bbox (`_crop_thumbnail` /
   `_mask_png`), so a geometry edit makes the role's derived artifacts stale.
4. `R.name/kind → S.reasons` — the grouping algorithm's same-name and
   cross-name rules are name-driven.

## 3. Invalidation rules per correction kind

`AR(K)` = affected role ids, `AO(K)` = affected occurrence ids.
`affected(S) = {S | S.role_ids ∩ AR(K) ≠ ∅}` (pending only; dismissed rows
are reviewer decisions and are never re-opened).

| Kind | Mutation at confirm (one txn) | Superseded / archived | Recomputed (J') |
|---|---|---|---|
| `reassign` — move O from role A to role B | atomic `UPDATE object_occurrence SET role_id=B, revision+1 WHERE id+workspace+role_id=A+revision` (collision on B's natural key `(role,scene,frame)` fails closed); bump `R_A.revision` and `R_B.revision` (CAS tokens for concurrent corrections); O content (bbox/time/confidence/reasons) untouched; old mapping archived in `C.result_json` | `affected(S)` → status `superseded`, `natural_key=NULL` | pairs containing A or B regenerated IF any S was invalidated; derived artifacts of A and B regenerated IF the role has `source_job_id` (a DISCOVER candidate) |
| `candidate_edit` (role: name/kind/description) | `R` fields via CAS, `revision+1` | `affected(S)` → superseded | pairs containing R IF S invalidated; artifacts NOT recomputed (no geometry change) |
| `candidate_edit` (occurrence: bbox/confidence) | `O` fields via CAS, `revision+1` | `affected(S)` → superseded | pairs containing the role IF S invalidated; role artifacts regenerated (geometry changed) |
| `merge` (sources → target) | T03 `apply_merge` (sources superseded with `supersedes_role_id`, occurrences re-pointed content-identical, T03 audit row) | `affected(S)` → superseded (T03 already supersedes referencing pending rows; the correction supersedes the remainder) | pairs containing the target IF S invalidated; target artifacts regenerated (occurrence set grew) |
| `split` (target → new role) | T03 `apply_split` (new suggested role, exact transferred occurrences moved back content-identical, original stays superseded, T03 audit row) | `affected(S)` → superseded | pairs containing target/new role IF S invalidated; artifacts of target + new role regenerated |

## 4. Preservation invariant (tested byte/hash-identical)

- Unaffected rows: same `revision`, same `status`, same content — proven by
  full-row snapshot comparison before/after.
- Unaffected files: same SHA-256 and size — proven by per-file hashing of the
  DISCOVER artifacts directory.
- Old affected state: superseded/archived, NEVER deleted — roles become
  `superseded` (T03 lineage), suggestions become `superseded`, the old
  occurrence mapping lives in `C.result_json`, and old artifact rows/files
  stay as immutable historical evidence of the original run.

## 5. Recompute-needed decision (durable work ONLY where needed)

J' is created at confirm iff:

```
recompute_needed = (invalidated_suggestions non-empty)
                   OR (any affected role has source_job_id NOT NULL)
```

Otherwise the correction completes synchronously (no job row).  The
recompute manifest carries the affected role ids resolved AT CONFIRM time
(split's new role id is only known then).

## 6. Durable job contracts for J' = RECOMPUTE_OBJECTS

- Idempotency key: `RECOMPUTE_OBJECTS:correction:<correction_id>` — exactly
  one recompute job per correction; confirm replay never creates a second.
- Retry: terminal failed/cancelled J' retries via
  `JobRepository.create_successor` (contract §6.4); `GET /corrections/{id}`
  follows the successor chain for the honest terminal outcome.
- Cancel: public JobService cancel (durable); cancel during running drains
  with ZERO new rows/files; staging drained.
- Restart: per-phase checkpoints (input fingerprint → recompute → staged →
  published); resume re-verifies the input fingerprint (role ids + occurrence
  geometry hash); publication replay is row-additive with job-scoped
  deterministic artifact ids (no duplicate rows/files).
- Concurrency: correction confirm uses an atomic CAS predicate
  (`pending → applied`, exactly one winner); the correction create uses a
  content-derived natural key with a partial unique index backstop.
- Orphan cleanup: every managed file under the job's final path must equal an
  artifact row (no-orphan gate); own + predecessor `*.staging` partials are
  garbage-collected on re-run (T02 precedent).

## 7. API surface (`/api/v2/object-intelligence/corrections`)

- `POST /preview` — impact report WITHOUT any durable write (the UI's
  pre-confirmation scope display).
- `POST /` — create the durable pending correction (impact computed +
  archived); natural-key replay returns the same row (200).
- `POST /{id}/confirm` — CAS apply: mutation + supersession + J' creation in
  ONE transaction; replay returns the recorded result (200).
- `GET /{id}`, `GET /` — read-only status (correction status + recompute job
  chain state + impact + result).  Zero durable mutations.
- `POST /{id}/cancel` — pending → cancelled (CAS); applied → durable cancel
  of the recompute job (honest terminal outcome; mutation is never undone).
- `POST /{id}/recompute/retry` — successor job for a failed/cancelled
  recompute (contract §6.4); idempotent.
