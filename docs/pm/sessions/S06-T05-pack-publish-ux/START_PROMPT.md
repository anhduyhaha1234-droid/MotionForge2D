# Start Prompt — Task S06-T05: Pack Review & Publish UX

Continue from the approved S06-T04 UI in this worktree. Read SESSION_PROTOCOL,
the full S06-T05 TASK, S06-T04 PM_REVIEW/REPORT, and the approved R02 API
contract before editing. Inspect current git status/diff and preserve all
existing changes.

Implement only the validation-aware review/publish UX specified in TASK.md.
Use the exact approved publish endpoint and current version revision. Require
confirmation, handle 422 and 409 honestly, refetch after mutation, and keep
published versions visibly immutable. Do not add upload capability or change
backend contracts.

Stay within the TASK write scope. Use bounded commands. Do not commit, push,
deploy, delete/clean/reset, start S07, or touch user data. Run focused tests,
frontend checks, desktop/mobile QA, and a fresh 7/7 baseline. Update LOG/REPORT
and finish `SUBMITTED` without self-approval.
