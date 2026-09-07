# S12-T01 REPORT — Export preflight + frozen contract

- Branch: `codex/s12/s12-t01-0907a`, base `1f5936d`.
- Contract: `s12-export-v1` (`app/schemas/s12_export.py`) — request/response
  strict, 14 reason codes closed, 3 profiles dims/codec frozen, native-vs-
  upscale provenance, validation/publication contracts cho T04A/T03C.
- Route: `POST /api/v2/projects/{project_id}/export/preflight`
  (`app/api/routes/s12_export_preflight.py`) — verdict-only, KHÔNG render
  trong request; consume readiness/S10 checkpoint/structural lock read-only.
- Service pure: `app/services/s12_export/preflight.py` — I/O-free, fail-closed.
- Contract doc: `docs/contracts/s12-export.md`.
- app.py: bounded patch +5 dòng (import + register router), hash
  `7334f81b…` (preimage `6523ac5`), 224 lines.
- Tests: `tests/s12/s12-t01/test_preflight_contract.py` — **15 passed**
  (4 pure + 1 OpenAPI + 9 HTTP + 1 no-render).
- Regression: S10 domain 15 passed, S11 readiness API 9 passed.
- Ruff `--select F`: clean.
- Upstream readiness/S10/lock: untouched (chỉ consume).
- Open item cho T02: `profile.supported=false` + basis
  "T02 capability detection pending" — T02 điền encoder-probe thật.

## Files changed (allowlist)

NEW: app/schemas/s12_export.py, app/services/s12_export/__init__.py,
app/services/s12_export/preflight.py, app/api/routes/s12_export_preflight.py,
docs/contracts/s12-export.md, docs/pm/sessions/S12-T01/{LOG.md,REPORT.md},
tests/s12/s12-t01/test_preflight_contract.py.
PATCH: app/api/app.py (+5).

## TASK_SUBMITTED (transport checkpoint, local branch — không phải APPROVED)
