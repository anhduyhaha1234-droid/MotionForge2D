# Hermes MAX Autopilot Rules

**Owner:** Hermes skill `motionforge-autopilot`
**Human review policy:** autonomous task/phase execution; one independent Codex
audit after Hermes reports final SUCCESS or a requested phase boundary.
**Pinned coding model:** `ocg/qwen3.7-max` (Hermes MAX); no medium/free fallback.

## Phase plan

| Phase | Scope | Parallel policy |
|---|---|---|
| A | Close S03; S04 UI shell | S04 preflight may overlap S03 correction; writes wait for S03 approval |
| B | S05 Import/Analyze; S06 Character Library | S06 isolated worktree may overlap S05 |
| C | S07 Cast, S08 Objects, S09 Demo, S10 Apply | Only dependency-safe worktrees |
| D | S11 QC/audio, S12 export, S13 generator | S13 may overlap after E04; integration waits for dependencies |
| FINAL | Integrated acceptance, demo, packaging/readiness | Single clean integration branch |

## Mandatory gates

Every task requires focused tests, combined regressions, lint/typecheck,
diff-check, protected-data hash, adversarial self-review, and a fresh 7/7
quality baseline before commit/advance. Phase exit repeats integration evidence.

## Stop policy

Hermes keeps working through ordinary failures. It stops only at `SUCCESS` or a
specific `BLOCKED` condition that cannot be resolved without user authority,
hardware/service availability, or a product decision. No push/deploy/external
mutation is authorized.

## Skill learning policy

Autopilot may create or install supporting Hermes skills. External skills must
be inspected and audited first; local skills are preferred for verified
MotionForge2D workflows. Every addition is logged in `AUTOPILOT_SKILLS.md` with
source, purpose, trust decision, and validation. Skills never expand authority
to push, deploy, spend, message, access unrelated data, or bypass quality gates.
