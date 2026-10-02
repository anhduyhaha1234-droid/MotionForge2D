# S06-R01 - Review and integrate character domain foundation

**Status:** READY
**Source commit:** `62b2bcd` from `codex/s06-t01`
**Base:** current `master` at `a43b20d`

## Objective

Independently review and safely port only the S06-T01 durable character-library foundation onto the current base. Do not inherit Antigravity approval claims.

## Required work

1. Inspect source commit `62b2bcd` and its parent context before applying it.
2. Apply with `git cherry-pick --no-commit 62b2bcd`; resolve against current persistence/API architecture.
3. Remove unrelated legacy-import fixtures and unrelated test changes unless directly required and justified.
4. Audit migration lineage, downgrade safety, workspace isolation, revision/CAS behavior, archive semantics, route ordering and DTO boundaries.
5. Add or repair focused tests for the character domain.
6. Run focused tests, migration upgrade/downgrade checks, Ruff, MyPy and the fresh full 7/7 baseline.

## Allowed write scope

- `.gitignore`
- `app/api/app.py`, `app/api/deps.py`, `app/api/routes/durable_characters.py`
- `app/persistence/characters.py`, `app/persistence/models.py`
- `app/schemas/characters.py`
- character migration file(s)
- character-domain focused tests and directly required persistence bootstrap tests
- this session `LOG.md` and `REPORT.md`

## Forbidden scope

- frontend, channels.json, data, roadmap and other session packets
- legacy importer fixtures unless a demonstrated character-domain requirement exists
- commits, pushes, approval or starting dependent S06 tasks

Finish with REPORT `SUBMITTED` and exit for Codex review.
