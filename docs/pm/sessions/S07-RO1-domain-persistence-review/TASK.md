# S07-RO1 — Read-Only Review: Domain & Persistence

READ-ONLY. Do NOT modify production code, tests, migrations, or task scope. Only write findings to:
`output/s07-readonly-review/<run-id>/FINDINGS_RO1.md` (+ optional evidence dir).

## Model
- Provider muse, model ocg/muse-spark-1.2-contributor, reasoning max, fallback disabled. Mismatch → stop & report.

## Review focus (while S07-T01 writer runs — review the code as it lands + final state)
1. Schema/migration of `project_cast_mapping` (FK RESTRICT, workspace isolation, UNIQUE idempotency).
2. FK correctness + `PRAGMA foreign_key_check`.
3. Idempotency semantics (equivalent replay no dup; different payload stable conflict, zero mutation).
4. Revision/CAS (stale 409; concurrent one winner, loser rollback).
5. Immutable version pin (pins pack_version id; new publish does not mutate old mapping).
6. Cross-workspace enforcement (project/role/character/pack all in same workspace; no leak).
7. Transaction rollback on failure (atomic).
8. Deterministic serialization.

## Output contract
Findings with: priority (blocking/follow-up), file/function, reproduction, expected, actual, impact,
missing test, verdict.

## Review sources (read)
- docs/pm/sessions/S07-T01-project-cast-domain-api/TASK.md + START_PROMPT.md + code on disk
- S06 character library / pack version models+repo; S08 ObjectRole patterns
- docs/architecture/PERSISTENCE_DOMAIN_CONTRACT.md

## Constraints
- No writes outside output/s07-readonly-review/<run-id>/; no app/tests/migrations changes; no commit/push;
  no MAIN writes.
