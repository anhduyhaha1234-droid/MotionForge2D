# S10-T02 — Multi-role independent apply

Outcome: 1-4 role mappings render independently while preserving contact, visibility and z-order graph edges.

Depends on: T01C.

Binary acceptance:
- group fixture represents at least two characters, prop/contact anchor and foreground occluder without flattening;
- every role uses its own pinned mapping/pack/route and attempt evidence;
- one role failure/correction never silently mutates another role's artifacts or route;
- exact contact and z-order edges survive chunk overlap/stitch boundaries; zero unexplained visibility event;
- scheduling order does not change canonical output identity.

Allowed write: app/services/s10_multi_role_apply.py, bounded edits in s10_full_apply.py/s10_full_apply_jobs.py, tests/test_s10_multi_role_apply.py, docs/pm/sessions/S10-T02-multi-role/**, output/s10/t02/**.
Forbidden: migration/model, frontend, S11/S13, renderer J1 files, data/**.

Validation: pytest tests/test_s10_multi_role_apply.py -v -p no:cacheprovider --basetemp=$(mktemp -d) PASS x2; Ruff scoped (E501 P2 documented); mypy Success on s10_multi_role_apply.py; git diff --check 0.
