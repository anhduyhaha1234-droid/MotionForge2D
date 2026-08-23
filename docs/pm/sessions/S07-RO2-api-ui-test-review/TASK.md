# S07-RO2 — Read-Only Review: API, UI & Test Strength

READ-ONLY. Do NOT modify production code, tests, migrations, or task scope. Only write findings to:
`output/s07-readonly-review/<run-id>/FINDINGS_RO2.md` (+ optional evidence dir).

## Model
- Provider muse, model ocg/muse-spark-1.2-contributor, reasoning max, fallback disabled. Mismatch → stop & report.

## Review focus (T01 lands first; T02 UI/picker lands later — review each as it lands)
For T01 (API/schema):
1. Strict schemas (typed requestBody/response; unknown field 422; no wrong numeric/string/bool coercion).
2. OpenAPI typed (not generic) for project_cast endpoints.
3. API error mapping (404 no-existence-leak, 409 stale revision, 422 validation, conflict mapping).
4. No client-fabricated workspace authority; workspace always derived server-side.
5. Idempotency/conflict endpoints stable response contract.
For T02 (UI/picker — when it lands):
6. Compatibility warnings (object kind mismatch, missing pose/capability, incomplete pack, unpublished
   pack, generation mismatch, source_overlay refusal, workspace mismatch, stale revision).
7. No silent nearest-match; no fabricated compatibility; incompatible submit blocked.
8. Loading/empty/error/retry states; stale revision recovery UX; Vietnamese helper text (dark theme,
   text-gray-400 or brighter, 11px min).
9. Desktop + 390px layout; keyboard/focus basics.
Test strength:
10. Tests call production repo/API (no mock-away); assertions check exact IDs/revisions/rows;
    no raw-SQL bypass; no editing ORM objects to fake pass; scenario coverage (Scenario I).

## Output contract
Findings with: priority, file/function, reproduction, expected, actual, impact, missing test, verdict.

## Review sources (read)
- docs/pm/sessions/S07-T01... / S07-T02... packets + code on disk
- existing app/api/routes + schemas patterns; frontend conventions (features structure, dark theme helper text)

## Constraints
- No writes outside output/s07-readonly-review/<run-id>/; no app/tests/migrations/frontend changes;
  no commit/push; no MAIN writes.
