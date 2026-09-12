# S12-LC3-R5 VAL F02 exact-owner evidence

Route: `gpt-5.6-luna`, high, fallback OFF. Owner/session remains
`01a089a3-2ca7-7642-8c16-e2904d9f7afa`. Worktree
`C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val`, branch
`codex/s12-lc3-luna-val`, start HEAD
`e9a1686df7c740934c6fa8e12e23e1597f04856f`.

Fresh before-red command/output is captured at
`C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r5-owner-submission\20260912T164057Z\VAL\F02-recovery\F02-unowned-pair-before-red.md`.
The fresh corrected micro and finite results are at
`C:\Users\Admin\Documents\Codex\2026-09-11\tr-x20\outputs\s12-r5-owner-submission\20260912T164057Z\VAL\F02-finite\results.md`.

Before-red was `1 passed, 1 failed, 4 warnings`, exit `1`: the positive actual
publisher interruption/recovery passed, while the synthetic unowned same-byte
pair was incorrectly accepted (`DID NOT RAISE PublicationError`). Corrected
micro was `2 passed, 4 warnings`, exit `0`, pytest `6.25s`. The positive
asserted durable attempt intent, final creation, absence of sidecar/receipt at
the interruption point, second-process recovery, completed run, final
SHA-256 `ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7`,
and distinct candidate/final inode. The negative verified unchanged running
DB status, final and sidecar bytes/inodes, and absent intent/receipt.

The complete allowed VAL/T03C-publication/T04A-source-lock finite gate passed
`84 passed, 76 warnings`, exit `0` in two runs. The timestamped repeat was
`77.51s` in pytest / `78.726475s` measured process wall. Compileall, Ruff F/I,
and diff-check exited `0`; exact UTC envelopes are in the external lane
evidence. Production changed only
`app/services/s12_export/publication.py`; tests changed only
`tests/s12/s12-lc3-val/test_r3_publication_boundaries.py`. Existing R3/R4
immutable publication probes remain in the passing finite set.

The frozen manager before-red file was not modified. Migrations, models, and
the T03A migration test were not edited. `work/` was not cleaned, staged, or
written; preservation is checked against the manager manifest by the final
post-write-set guard at `evidence/20260913T-post-guard-r5-f02.json` reports
`VERIFIED`, `103` entries, `0` failures; all `58` manager-manifest `work/`
entries are unchanged. The retry-lineage migration remains absent; models
and the T03A migration test retain their manager-baseline hashes. This is a
local VAL transport checkpoint only, not an integration, approval, or closure
claim.
