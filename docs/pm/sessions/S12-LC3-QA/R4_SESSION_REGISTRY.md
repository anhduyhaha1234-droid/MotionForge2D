# S12 LC3-R4 QA session registry

This registry is an evidence record for the existing owner/session. It does
not dispatch, replace, or approve any task.

| Task | Role / exact owner-session | Worktree / branch | R4 state | Write-set / dependency |
|---|---|---|---|---|
| S12-LC3-VAL | Wegener / `01a089a3-2ca7-7642-8c16-e2904d9f7afa` | `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-val` / `codex/s12-lc3-luna-val` | F02/F03 owner; R4 terminal state not independently asserted by QA | VAL publication files/tests; QA waits for terminal candidate |
| S12-LC3-RETRY | Implement S12 retry lineage / `01a08e92-7385-7a21-beb7-67dc770ce118` | `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-retry` / `codex/s12-lc3-luna-retry` | F01/F04 owner; R4 terminal state not independently asserted by QA | RETRY persistence/workflow/tests; QA does not touch |
| S12-LC3-QA | Goodall / `01a08991-c909-7d03-86ed-ac236d50c87b` | `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-qa` / `codex/s12-lc3-luna-qa` | ACTIVE R4 evidence lane; QA HEAD `ac49c9d4e40e6c3d3a5b3cad49f67d6f12a80cdd` | `docs/pm/sessions/S12-LC3-QA/**`, `tests/s12/s12-lc3-qa-r4/**`, lane evidence |
| S12-LC3-INT | Pascal / `01a0898b-823a-7053-a1de-27d6fc24fce3` | `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-integration` / `codex/s12-lc3-luna-integration` | Candidate baseline `17b33f53b27da58e3330dd4a8270706ac853d37a`; transport only | Waits for terminal owner commits; no QA write |
| S12-LC3-UI | Noether / `01a089a3-2d09-7851-9a4d-25fa6c8c9262` | `C:\Users\Admin\MotionForge2D-worktrees\s12-lc3-luna-ui` / `codex/s12-lc3-luna-ui` | STANDBY; no bounded UI defect in QA lane | Zero write |
| S12-LOCK-PRODUCER-01 | No activated owner/session | Proposed only | `PROPOSED_ONLY / BLOCKED_DEPENDENCY` | B01 producer not activated in R4 |

Reported RETRY logs may contain manager ID
`01a08982-4ec8-7271-afa2-98efc200875c`; the actual RETRY child above remains
the only RETRY owner to resume. QA did not create a worker, send an owner
message, or change global model configuration.

Model route for this lane: `gpt-5.6-luna`, reasoning `high`, fallback `OFF`.
No context-health evidence authorizes owner transfer. No concurrent QA writer
or QA-owned runtime remains after the recorded commands.
