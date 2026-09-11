# S12-LC3-VAL R3 design note and finite anti-omission matrix

Transport evidence only; this note is not an approval or closure decision.

## Design note

The prior R2 child-kill check opened the isolated SQLite database, read the run
and job identifiers, and slept until the parent terminated it. It never invoked
the real export handler, `ExportRunner`, render boundary, or publication path.
Consequently it could prove process termination and retained identifiers only;
it could not prove publication receipt/sidecar behavior, a real render-to-
publication interruption, recovery of the same run/job, or convergence of the
durable rows. R3 therefore requires the child to execute the production handler
and publisher against the isolated fixture, with a barrier immediately before
the actual publication primitive, then verifies a fresh-process recovery.

## Finite anti-omission matrix

Each row must be exercised by an owned test or explicitly recorded as blocked by
an external owner. A green row requires exact identity, bytes, hashes, mtimes,
and durable row assertions; a fail-closed row requires no public mutation.

| Row | Boundary and controls | Required assertion |
|---|---|---|
| S01 | No receipt after final/sidecar; missing, malformed, mismatched, foreign, and pre-receipt recovery variants | Rebuild/adopt only from current owner, current fence, matching candidate and fresh validation; otherwise preserve or refuse with no unchecked mutation |
| S02 | Private candidate versus public final inode, commit fault before/after final/sidecar/receipt, open candidate handle, fresh recovery | Candidate and final are not aliases; completed winner is immutable; recovery is identity/content validated and retained chunks/rows are unchanged |
| S04 | Short, deep, spaces, Unicode, and overlong companion-path variants | Valid Windows names pass; invalid path is typed and rejected before public mutation |
| S05 | Actual owned worker/handler child executes render and publisher; barrier at publication; kill; fresh process uses same DB/run/job | Child is not a read/sleep surrogate; fresh process converges the same run/job, preserves chunks and winner, and leaves no owned children |
| R2 carry-forward | Live A/B fence handoff; stale ORM/expiry/reclaim; foreign/tampered/ambiguous/read-error; audio/deadline/cancel/provenance; bounded decoder/reap/resource controls | Existing controls remain green with exact fence, content, cleanup, and bounded-resource evidence; no 30-minute capacity claim |

The finite gate order is: S01/S02/S04/S05 counterexamples first, identical
assertions after repair, full matrix, focused allowed modules, compile/lint/
diff checks, then the guarded owner exit. Process joins are bounded; every
child is waited/reaped, and only owned runtime children may be cleaned.
