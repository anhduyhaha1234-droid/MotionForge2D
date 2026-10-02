# S05-C04 Hermes start prompt

Work only in `C:\Users\Admin\MotionForge2D-worktrees\prepare-s05-t01`.

Read `docs/pm/sessions/S05-C04-production-job-service-wiring/TASK.md` completely,
then follow it exactly. This is a bounded correction of the confirmed default
production JobService wiring defect. Preserve every pre-existing dirty change.
Do not touch MAIN, real data, old QA artifacts, other task packets, roadmap, or
frontend. Do not commit, push, merge, switch branches, stash, reset, clean,
restore, delete, or perform destructive cleanup.

Implement the smallest public/explicit lifecycle binding that makes the real
`app.main:app` default path work. Add the pristine isolated production-wiring
integration test required by the packet. Record the pre-write guard and every
verification in this packet's LOG/REPORT. Stop at `SUBMITTED`; Codex alone will
review and approve.
